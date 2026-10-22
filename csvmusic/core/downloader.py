# tabs only
import os, pathlib, subprocess, requests, io, contextlib, json, base64, hashlib, shutil, threading, time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, List
import re, unicodedata
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.flac import Picture
from csvmusic.core.paths import ffmpeg_path, ytdlp_path, INTERNAL_YTDLP
from csvmusic.core.log import log
from csvmusic.core.js_runtime import ytdlp_js_runtime_args
from csvmusic.core.subprocess_env import subprocess_kwargs
from csvmusic.core.source_quality import capture_source, store_source

YTM_URL = "https://music.youtube.com/watch?v={vid}"
YT_URL = "https://www.youtube.com/watch?v={vid}"
YOUTUBE_CLIENTS: list[str | None] = ["web_embedded", None, "ios", "tv", "android_vr"]
MP3_SOURCE_FORMAT = "bestaudio/best"
_YOUTUBE_RISK_PATTERNS: tuple[tuple[str, str], ...] = (
	("http error 429", "YouTube returned HTTP 429"),
	("too many requests", "YouTube is rate limiting requests"),
	("sign in to confirm you're not a bot", "YouTube asked for bot verification"),
	("sign in to confirm you’re not a bot", "YouTube asked for bot verification"),
	("confirm you’re not a bot", "YouTube asked for bot verification"),
	("confirm you're not a bot", "YouTube asked for bot verification"),
	# The summary this app writes itself, so a stored error is still recognized later.
	("youtube asked for bot verification", "YouTube asked for bot verification"),
	("this content isn't available, try again later", "YouTube temporarily blocked the session"),
	("unable to download video data: http error 403", "YouTube rejected the download request"),
)
_YOUTUBE_LARGE_BATCH_THRESHOLD = 250

class DownloadError(Exception): pass


class AgeRestrictedError(DownloadError):
	"""The selected video needs an eligible authenticated YouTube session."""


class DownloadCancelled(DownloadError):
	"""The user pressed Stop; the running yt-dlp/ffmpeg was ended."""


class YouTubeRiskError(DownloadError):
	"""YouTube signalled rate limiting or bot verification; other clients and candidates will fail too."""

	def __init__(self, message: str, reason: str):
		super().__init__(message)
		self.reason = reason


def is_age_restriction_error(message: str) -> bool:
	text = message.lower()
	return any(marker in text for marker in (
		"sign in to confirm your age", "this video may be inappropriate for some users",
		"age-restricted", "age restricted", "age_restricted", "confirm your age",
	))


def age_restriction_message(*, using_cookies: bool) -> str:
	if using_cookies:
		return (
			"Age-restricted video. Cookies were used, but YouTube still rejected this result. "
			"Open Settings > YouTube Account, reconnect or refresh your cookies, and test the connection. "
			"Check that this account can play the video on YouTube, then retry or choose another result."
		)
	return (
		"Age-restricted video. Enable cookies in Settings > YouTube Account. "
		"Sign in, enable 'Use this YouTube session for downloads', press Save, then retry. "
		"Cookies can allow access when your account is eligible to watch the video on YouTube."
	)


@dataclass(frozen=True)
class YouTubeMitigationProfile:
	label: str
	track_sleep_s: float = 0.0
	request_sleep_s: float = 0.0
	sleep_interval_s: float = 0.0
	max_sleep_interval_s: float = 0.0
	limit_rate: str | None = None
	warning: str | None = None
	reason: str | None = None

	@property
	def active(self) -> bool:
		return any((
			self.track_sleep_s > 0,
			self.request_sleep_s > 0,
			self.sleep_interval_s > 0,
			self.max_sleep_interval_s > 0,
			bool(self.limit_rate),
		))


YOUTUBE_MITIGATION_NONE = YouTubeMitigationProfile(label="normal")
YOUTUBE_MITIGATION_LARGE_BATCH = YouTubeMitigationProfile(
	label="large-batch",
	track_sleep_s=5.0,
	request_sleep_s=0.75,
	sleep_interval_s=5.0,
	max_sleep_interval_s=10.0,
	limit_rate="1.5M",
	warning="Large YouTube batch detected. Downloads will be paced with randomized waits to reduce rate-limit risk.",
	reason="large playlist size",
)
YOUTUBE_MITIGATION_AGGRESSIVE = YouTubeMitigationProfile(
	label="aggressive",
	track_sleep_s=6.0,
	request_sleep_s=1.25,
	sleep_interval_s=8.0,
	max_sleep_interval_s=15.0,
	limit_rate="900K",
	warning="YouTube started throttling or blocking requests. Applying slower download pacing automatically.",
	reason="YouTube rate-limit response",
)

_TARGET_LOUDNESS_I = -16.0
_TARGET_TRUE_PEAK_DB = -2.5
_MAX_SAFE_NAME_LENGTH = 140

def _run(cmd: list[str]) -> int:
	proc = _run_capture(cmd)
	if proc.returncode != 0:
		err = (proc.stderr or "").strip()
		out = (proc.stdout or "").strip()
		log(f"yt-dlp command failed rc={proc.returncode} cmd={' '.join(cmd)} stderr={err[:500]} stdout={out[:200]}")
	return proc.returncode

# Uma música de 10 min a 900 KB/s leva ~1 min; 10 min de silêncio é travamento.
YTDLP_TIMEOUT_S = 600.0
FFMPEG_TIMEOUT_S = 600.0
_POLL_S = 0.25
_cancel_state = threading.local()


@contextlib.contextmanager
def cancellation_scope(event: threading.Event):
	"""Let ``event.set()`` (from any thread) end the yt-dlp/ffmpeg running in this thread."""
	previous = getattr(_cancel_state, "event", None)
	_cancel_state.event = event
	try:
		yield event
	finally:
		_cancel_state.event = previous


def _cancel_requested() -> bool:
	event = getattr(_cancel_state, "event", None)
	return bool(event is not None and event.is_set())


def _raise_if_cancelled() -> None:
	if _cancel_requested():
		raise DownloadCancelled("Stopped by user.")


def _run_capture(cmd: list[str], *, timeout: float = FFMPEG_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
	"""Run a tool, killing it on Stop or after ``timeout`` seconds."""
	_raise_if_cancelled()
	proc = subprocess.Popen(
		cmd,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
		encoding="utf-8",
		errors="replace",
		**subprocess_kwargs()
	)
	deadline = time.monotonic() + timeout
	while True:
		try:
			stdout, stderr = proc.communicate(timeout=_POLL_S)
			return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
		except subprocess.TimeoutExpired:
			cancelled = _cancel_requested()
			if not cancelled and time.monotonic() < deadline:
				continue
			proc.kill()
			proc.communicate()
			name = pathlib.Path(str(cmd[0])).name if cmd else "tool"
			if cancelled:
				log(f"{name} killed: stopped by user")
				raise DownloadCancelled("Stopped by user.")
			log(f"{name} killed after {timeout:g}s timeout")
			raise DownloadError(f"{name} did not finish within {timeout:g} seconds")


class _InProcessAbort(BaseException):
	"""Raised inside the in-process yt-dlp to stop it (BaseException so yt-dlp does not swallow it)."""


class _AbortableBuffer(io.StringIO):
	"""Output buffer that ends the in-process yt-dlp on Stop or timeout at its next write."""

	def __init__(self, deadline: float):
		super().__init__()
		self.deadline = deadline

	def write(self, text: str) -> int:
		if _cancel_requested():
			raise _InProcessAbort("cancelled")
		if time.monotonic() > self.deadline:
			raise _InProcessAbort("timeout")
		return super().write(text)


@contextlib.contextmanager
def _abort_hooks_installed(deadline: float):
	"""Give every YoutubeDL that yt-dlp's main() builds in this thread hooks that check Stop and the time limit.

	`--print` makes yt-dlp quiet (no progress lines), so the output buffer alone is not written during a
	download. The progress hook runs on each received block and the postprocessor hook at each step.
	"""
	import yt_dlp

	original = yt_dlp.YoutubeDL
	owner = threading.get_ident()

	def check(_status: dict) -> None:
		if threading.get_ident() != owner:
			return
		if _cancel_requested():
			raise _InProcessAbort("cancelled")
		if time.monotonic() > deadline:
			raise _InProcessAbort("timeout")

	class _AbortableYoutubeDL(original):  # type: ignore[misc, valid-type]
		def __init__(self, *args, **kwargs):
			super().__init__(*args, **kwargs)
			self.add_progress_hook(check)
			self.add_postprocessor_hook(check)

	yt_dlp.YoutubeDL = _AbortableYoutubeDL
	try:
		yield
	finally:
		yt_dlp.YoutubeDL = original


def _run_ytdlp_module(args: list[str]) -> tuple[int, str, str]:
	# Rodando no mesmo processo não dá para matar o yt-dlp; ele para no próximo
	# bloco recebido (gancho de progresso) ou na próxima linha que escrever.
	deadline = time.monotonic() + YTDLP_TIMEOUT_S
	stdout_buf = _AbortableBuffer(deadline)
	stderr_buf = _AbortableBuffer(deadline)
	try:
		from yt_dlp import main as yt_dlp_main
	except Exception as exc:
		return 1, "", f"failed to import yt_dlp module: {exc}"
	try:
		with _abort_hooks_installed(deadline), contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
			try:
				rc = yt_dlp_main(args)
			except SystemExit as exc:
				code = exc.code
				if isinstance(code, int):
					rc = code
				elif code is None:
					rc = 0
				else:
					rc = 1
			except Exception as exc:
				return 1, stdout_buf.getvalue(), f"{stderr_buf.getvalue()}\n{exc}".strip()
	except _InProcessAbort as abort:
		if str(abort) == "cancelled":
			raise DownloadCancelled("Stopped by user.") from None
		raise DownloadError(f"yt-dlp did not finish within {YTDLP_TIMEOUT_S:g} seconds") from None
	return int(rc or 0), stdout_buf.getvalue(), stderr_buf.getvalue()

def _summarize_tool_output(stderr: str, stdout: str, *, using_cookies: bool = False) -> str:
	def _clean_lines(text: str) -> list[str]:
		lines: list[str] = []
		for raw in text.splitlines():
			line = raw.strip()
			if not line:
				continue
			if line.startswith("[download]") or line.startswith("\r[download]"):
				continue
			lines.append(line)
		return lines
	lines = _clean_lines(stderr) + _clean_lines(stdout)
	if not lines:
		return "no diagnostic output"
	full_text = " | ".join(lines)
	lower_full = full_text.lower()
	if is_age_restriction_error(full_text):
		return age_restriction_message(using_cookies=using_cookies)
	if "sign in to confirm you're not a bot" in lower_full or "sign in to confirm you’re not a bot" in lower_full:
		if using_cookies:
			return "YouTube asked for bot verification even with cookies enabled. Re-test cookies, wait and retry, or choose another result."
		return "YouTube asked for bot verification. Try Firefox cookies or wait and retry."
	if "no supported javascript runtime could be found" in lower_full:
		return "yt-dlp could not solve the YouTube player challenge. Install Deno 2.3+ or Node 22+, then update yt-dlp with the default extras."
	if "requested format is not available" in lower_full:
		return "Requested audio format is not available for this result."
	error_lines = [line for line in lines if line.lower().startswith("error:") or " error:" in line.lower()]
	warning_lines = [line for line in lines if line.lower().startswith("warning:") or " warning:" in line.lower()]
	interesting = (error_lines[-2:] or warning_lines[-2:] or lines[-3:])
	msg = " | ".join(interesting)
	msg = re.sub(r"\s+", " ", msg).strip()
	return msg[:280]


def youtube_batch_mitigation(track_count: int, *, using_cookies: bool) -> YouTubeMitigationProfile:
	"""Initial pacing chosen from the batch size only.

	The size never selects the aggressive profile: that one is reserved for a
	real rate-limit signal, so it can still escalate and its "throttling"
	warning is never shown before YouTube actually throttled anything.
	"""
	if track_count >= _YOUTUBE_LARGE_BATCH_THRESHOLD:
		return YOUTUBE_MITIGATION_LARGE_BATCH
	return YOUTUBE_MITIGATION_NONE


def youtube_risk_acknowledgement(profile: YouTubeMitigationProfile) -> str | None:
	"""Build the shared user acknowledgement shown by every download interface."""
	if not profile.warning:
		return None
	message = profile.warning
	if profile.reason:
		message += f"\n\nReason: {profile.reason.capitalize()}."
	message += (
		"\n\nDownloading this batch requires repeated YouTube API, search, and media requests. "
		"YouTube may rate-limit the connection, require bot verification, temporarily block requests, "
		"or restrict the account/IP being used. CSVMusic cannot guarantee that throttling will prevent a block."
		"\n\nAutomatic randomized delays and reduced request/download rates will be enabled. "
		"Large playlists can take a long time and should not be restarted repeatedly."
		"\n\nDo you understand these risks and want to continue?"
	)
	return message


def detect_youtube_risk(detail: str) -> str | None:
	text = (detail or "").lower()
	for pattern, reason in _YOUTUBE_RISK_PATTERNS:
		if pattern in text:
			return reason
	return None


def build_ytdlp_mitigation_args(profile: YouTubeMitigationProfile | None) -> list[str]:
	if not profile or not profile.active:
		return []
	args: list[str] = []
	if profile.request_sleep_s > 0:
		args += ["--sleep-requests", f"{profile.request_sleep_s:g}"]
	if profile.sleep_interval_s > 0:
		args += ["--sleep-interval", f"{profile.sleep_interval_s:g}"]
	if profile.max_sleep_interval_s > 0:
		args += ["--max-sleep-interval", f"{profile.max_sleep_interval_s:g}"]
	if profile.limit_rate:
		args += ["--limit-rate", profile.limit_rate]
	return args

def _strip_cookie_args(cmd: list[str]) -> list[str]:
	new: list[str] = []
	skip_next = False
	for i, tok in enumerate(cmd):
		if skip_next:
			skip_next = False
			continue
		if tok == "--cookies":
			skip_next = True
			continue
		if tok.startswith("--cookies="):
			continue
		if tok == "--cookies-from-browser":
			skip_next = True
			continue
		if tok.startswith("--cookies-from-browser="):
			continue
		new.append(tok)
	return new

def _should_retry_without_cookies(stderr: str, stdout: str) -> bool:
	text = f"{stderr or ''}\n{stdout or ''}".lower()
	if (
		"sign in to confirm" in text
		or "login required" in text
		or "login_required" in text
		or "precondition check failed" in text
	):
		return False
	return any(phrase in text for phrase in (
		"requested format is not available",
		"only images are available for download",
		"signature solving failed",
		"n challenge solving failed",
		"nsig extraction failed",
		"unable to extract initial player response",
		"unable to download api page",
		"video unavailable",
		"this content isn't available",
		"this video is unavailable",
	))

def _cmd_uses_cookies(cmd: list[str]) -> bool:
	return any(
		tok in ("--cookies", "--cookies-from-browser")
		or tok.startswith("--cookies=")
		or tok.startswith("--cookies-from-browser=")
		for tok in cmd
	)

def _run_ytdlp(cmd: list[str]) -> int:
	return _run_ytdlp_detail(cmd)[0]


def _run_ytdlp_detail(cmd: list[str]) -> tuple[int, str]:
	_raise_if_cancelled()
	capture_source("")
	cmd = cmd[:1] + ["--no-simulate", "--print", "after_move:%(.{id,format_id,acodec,vcodec,abr,tbr})j"] + cmd[1:]
	# Never silently discard an explicitly selected authenticated session.
	if cmd and cmd[0] == INTERNAL_YTDLP:
		rc, stdout, stderr = _run_ytdlp_module(cmd[1:])
	else:
		proc = _run_capture(cmd, timeout=YTDLP_TIMEOUT_S)
		rc, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
	if rc == 0:
		capture_source(stdout)
		return 0, ""
	detail = _summarize_tool_output(stderr, stdout, using_cookies=_cmd_uses_cookies(cmd))
	log(f"yt-dlp failed rc={rc}: {detail}")
	if is_age_restriction_error(detail):
		# Preserve the actionable error instead of masking it with later client,
		# format, or search failures (or downloading a different video).
		raise AgeRestrictedError(detail)
	# A detecção roda na saída crua: o resumo reescreve o aviso de robô e
	# nenhum padrão casaria depois disso.
	risk = detect_youtube_risk(f"{stderr}\n{stdout}")
	if risk:
		raise YouTubeRiskError(f"{risk}: {detail}", risk)
	return rc, detail


def _join_attempt_details(details: list[str]) -> str:
	unique: list[str] = []
	for detail in details:
		if detail and detail not in unique:
			unique.append(detail)
	if not unique:
		return "no yt-dlp attempts recorded"
	return " || ".join(unique[-3:])


def _run_ytdlp_attempts(attempts: list[tuple[list[str], str]], *, label: str, video_id: str) -> None:
	"""Run yt-dlp attempts in order until one succeeds.

	Only the chosen video is ever downloaded. There is no ``ytsearch1:``
	fallback: it fetched the first YouTube hit for the file name without any
	check. When a video fails, the pipeline tries the next scored candidate.

	Age restriction and YouTube risk signals stop the sequence at once: trying
	the remaining clients would only send more requests to a session that is
	already being blocked. Every failure detail is kept for the final error.
	"""
	details: list[str] = []
	for cmd, description in attempts:
		try:
			rc, detail = _run_ytdlp_detail(cmd)
		except (AgeRestrictedError, YouTubeRiskError, DownloadCancelled):
			raise
		except DownloadError as exc:
			# Timeout of one attempt: the next client may still work.
			rc, detail = 1, str(exc)
		if rc == 0:
			log(f"{label}: {description} succeeded video_id={video_id}")
			return
		details.append(detail)
		log(f"{label}: {description} failed video_id={video_id}")
	log(f"{label}: all yt-dlp attempts failed video_id={video_id}")
	raise DownloadError(f"yt-dlp failed for {label.removeprefix('download_')}: {_join_attempt_details(details)}")


def _youtube_clients(cookie_args: list[str]) -> list[str | None]:
	# Let yt-dlp choose cookie-compatible clients and Premium formats.
	return [None] if _cmd_uses_cookies(cookie_args) else YOUTUBE_CLIENTS

_FILENAME_CHAR_MAP = str.maketrans({
	"\\": "＼",
	"/": "／",
	":": "：",
	"*": "＊",
	"?": "？",
	'"': "＂",
	"<": "＜",
	">": "＞",
	"|": "｜",
})

def sanitize_name(name: str) -> str:
	text = unicodedata.normalize("NFC", name or "").translate(_FILENAME_CHAR_MAP)
	text = re.sub(r"[\x00-\x1f]+", "", text)
	text = re.sub(r"\s+", " ", text).strip()
	text = text.rstrip(". ")
	text = text or "_"
	if len(text) <= _MAX_SAFE_NAME_LENGTH:
		return text
	digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
	prefix_length = _MAX_SAFE_NAME_LENGTH - len(digest) - 1
	return f"{text[:prefix_length].rstrip()}-{digest}"

def _safe(name: str) -> str:
	# Backward-compatible helper kept for internal use
	return sanitize_name(name)

def _filename_starts_with_base(filename: str, base: str) -> bool:
	for form in ("NFC", "NFD", "NFKC", "NFKD"):
		name_norm = unicodedata.normalize(form, filename)
		base_norm = unicodedata.normalize(form, base)
		if name_norm.startswith(base_norm + "."):
			return True
	return False

def _list_downloads(dir: pathlib.Path, base: str) -> list[pathlib.Path]:
	# Find files that start with our sanitized base, allowing Unicode normalization differences.
	return sorted(
		[p for p in dir.iterdir() if p.is_file() and _filename_starts_with_base(p.name, base)],
		key=lambda x: x.stat().st_mtime, reverse=True
	)

# Tudo o que o yt-dlp e o ffmpeg escrevem fica nesta pasta até o arquivo final
# estar pronto. A limpeza só mexe aqui dentro: um "Artista - Música.mp3" antigo
# ou um ".lrc" do usuário na pasta da playlist nunca é apagado ao trocar de formato.
STAGING_DIR_NAME = ".csvmusic-partial"
# Arquivo que vai ser substituído por um download novo vem para cá antes; o
# usuário esvazia quando quiser.
TRASH_DIR_NAME = ".csvmusic-lixeira"


def _staging_dir(dst_dir: pathlib.Path) -> pathlib.Path:
	staging = dst_dir / STAGING_DIR_NAME
	staging.mkdir(parents=True, exist_ok=True)
	return staging


def _cleanup_outputs(dir: pathlib.Path, base: str) -> None:
	"""Remove leftovers for ``base`` inside a staging folder (never a user folder)."""
	if not dir.is_dir():
		return
	for p in _list_downloads(dir, base):
		try:
			p.unlink()
		except Exception:
			pass


def _finish_staging(staging: pathlib.Path, base: str) -> None:
	_cleanup_outputs(staging, base)
	try:
		staging.rmdir()
	except OSError:
		pass


def keep_previous_copy(path: pathlib.Path) -> pathlib.Path | None:
	"""Keep the file about to be replaced in the internal trash folder.

	A hard link keeps the old copy without doubling disk use on the same
	volume; a plain copy is the fallback.
	"""
	if not path.is_file():
		return None
	trash = path.parent / TRASH_DIR_NAME
	trash.mkdir(parents=True, exist_ok=True)
	stamp = time.strftime("%Y%m%d-%H%M%S")
	target = trash / f"{path.stem}.{stamp}{path.suffix}"
	counter = 2
	while target.exists():
		target = trash / f"{path.stem}.{stamp}-{counter}{path.suffix}"
		counter += 1
	try:
		os.link(path, target)
	except OSError:
		shutil.copy2(path, target)
	log(f"previous file kept in trash: '{path.name}' -> '{target}'")
	return target


BeforeInstall = Callable[[pathlib.Path], None]


def _install_output(staged: pathlib.Path, final: pathlib.Path, before_install: BeforeInstall | None = None) -> pathlib.Path:
	"""Finish the staged file (tags, checks) and only then move it into place.

	``os.replace`` is atomic on the same volume: the playlist folder never holds
	a half-written or untagged file, so "already downloaded" stays trustworthy.
	If ``before_install`` raises, the staged file is discarded and any previous
	file stays untouched.
	"""
	if before_install is not None:
		before_install(staged)
	if final.exists():
		keep_previous_copy(final)
	os.replace(staged, final)
	return final


def _replace_file(src: pathlib.Path, dst: pathlib.Path) -> None:
	if dst.exists():
		try:
			dst.unlink()
		except Exception:
			pass
	src.replace(dst)


def _audio_processing_enabled(audio_processing: Dict | None) -> bool:
	if not audio_processing:
		return False
	return (
		bool(audio_processing.get("normalize"))
		or int(audio_processing.get("bass_gain", 0) or 0) != 0
		or int(audio_processing.get("treble_gain", 0) or 0) != 0
		or int(audio_processing.get("volume_gain", 0) or 0) != 0
	)


def _tone_filter_chain(audio_processing: Dict | None) -> list[str]:
	filters: list[str] = []
	bass_gain = int(audio_processing.get("bass_gain", 0) or 0) if audio_processing else 0
	treble_gain = int(audio_processing.get("treble_gain", 0) or 0) if audio_processing else 0
	if bass_gain:
		filters.append(f"bass=g={bass_gain}:f=110:w=0.6")
	if treble_gain:
		filters.append(f"treble=g={treble_gain}:f=6000:w=0.6")
	return filters


def _extract_loudnorm_json(stderr: str) -> Dict | None:
	matches = re.findall(r"\{\s*\"input_i\".*?\}", stderr or "", flags=re.S)
	if not matches:
		return None
	try:
		return json.loads(matches[-1])
	except Exception:
		return None


def _measure_static_normalize_gain(src: pathlib.Path, ffmpeg_bin: str, audio_processing: Dict | None) -> float:
	pre_filters = _tone_filter_chain(audio_processing)
	filter_parts = list(pre_filters)
	filter_parts.append(f"loudnorm=I={_TARGET_LOUDNESS_I}:TP={_TARGET_TRUE_PEAK_DB}:LRA=11:print_format=json")
	proc = _run_capture([
		ffmpeg_bin, "-hide_banner", "-i", str(src), "-vn", "-sn",
		"-af", ",".join(filter_parts),
		"-f", "null", "-"
	])
	stats = _extract_loudnorm_json((proc.stderr or "") + "\n" + (proc.stdout or ""))
	if not stats:
		return 0.0
	try:
		input_i = float(stats.get("input_i"))
		input_tp = float(stats.get("input_tp"))
	except Exception:
		return 0.0
	target_i = _TARGET_LOUDNESS_I
	target_tp = _TARGET_TRUE_PEAK_DB
	gain = target_i - input_i
	peak_limited_gain = target_tp - input_tp
	return min(gain, peak_limited_gain)


def _audio_filter_chain(audio_processing: Dict | None, src: pathlib.Path | None = None, ffmpeg_bin: str | None = None) -> str | None:
	if not _audio_processing_enabled(audio_processing):
		return None
	filters = _tone_filter_chain(audio_processing)
	total_gain = float(int(audio_processing.get("volume_gain", 0) or 0)) if audio_processing else 0.0
	if audio_processing and audio_processing.get("normalize") and src and ffmpeg_bin:
		total_gain += _measure_static_normalize_gain(src, ffmpeg_bin, audio_processing)
	if abs(total_gain) > 0.01:
		filters.append(f"volume={total_gain:.2f}dB")
	limit_linear = 10 ** (_TARGET_TRUE_PEAK_DB / 20.0)
	filters.append(f"alimiter=limit={limit_linear:.3f}:attack=5:release=50:level=disabled:latency=1")
	return ",".join(filters) if filters else None


def _append_audio_filter(args: list[str], audio_processing: Dict | None, src: pathlib.Path | None = None, ffmpeg_bin: str | None = None) -> None:
	filter_chain = _audio_filter_chain(audio_processing, src=src, ffmpeg_bin=ffmpeg_bin)
	if filter_chain:
		args += ["-af", filter_chain]


# Codecs que o app Música, o iPhone e o iPod tocam dentro de um .m4a.
_M4A_COPY_CODECS = {"aac", "alac"}


def _probe_audio_codec(src: pathlib.Path, ffmpeg_bin: str) -> str | None:
	"""Read the first audio codec name from ``ffmpeg -i`` (no ffprobe needed)."""
	proc = _run_capture([ffmpeg_bin, "-hide_banner", "-i", str(src)])
	match = re.search(r"Audio:\s*([A-Za-z0-9_]+)", f"{proc.stderr or ''}\n{proc.stdout or ''}")
	return match.group(1).lower() if match else None


def _normalize_to_m4a(src: pathlib.Path, dst: pathlib.Path, ffmpeg_bin: str, video_id: str, audio_processing: Dict | None = None) -> pathlib.Path:
	tmp_dst = dst.with_name(dst.stem + ".normalized.m4a")
	if tmp_dst.exists():
		try:
			tmp_dst.unlink()
		except Exception:
			pass

	codec = None if _audio_processing_enabled(audio_processing) else _probe_audio_codec(src, ffmpeg_bin)
	if codec is not None and codec not in _M4A_COPY_CODECS:
		# Opus (ou Vorbis) copiado para dentro do .m4a não toca em Apple nem iPod.
		log(f"download_m4a: source codec {codec} is not AAC, re-encoding video_id={video_id}")
	if codec in _M4A_COPY_CODECS:
		proc = _run_capture([ffmpeg_bin, "-y", "-i", str(src), "-vn", "-sn", "-c:a", "copy", str(tmp_dst)])
		rc = proc.returncode
		if rc == 0 and tmp_dst.exists():
			if src != dst:
				try: src.unlink()
				except Exception: pass
			_replace_file(tmp_dst, dst)
			return dst

	args = [ffmpeg_bin, "-y", "-i", str(src), "-vn", "-sn"]
	_append_audio_filter(args, audio_processing, src=src, ffmpeg_bin=ffmpeg_bin)
	args += ["-c:a", "aac", "-b:a", "192k", str(tmp_dst)]
	proc = _run_capture(args)
	rc = proc.returncode
	detail = _summarize_tool_output(proc.stderr or "", proc.stdout or "")
	if rc == 0 and tmp_dst.exists():
		if src != dst:
			try: src.unlink()
			except Exception: pass
		_replace_file(tmp_dst, dst)
		return dst

	try:
		if tmp_dst.exists():
			tmp_dst.unlink()
	except Exception:
		pass
	log(f"download_m4a: ffmpeg normalization failed video_id={video_id} src='{src.name}' dst='{dst.name}' rc={rc}")
	raise DownloadError(f"failed to produce .m4a: {detail}")

def yt_thumbnail_bytes(video_id: str) -> Optional[bytes]:
	# Best-effort cover from YouTube thumbnails
	for quality in ("maxresdefault","sddefault","hqdefault","mqdefault","default"):
		url = f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"
		try:
			r = requests.get(url, timeout=12)
			if r.status_code == 200 and r.content and len(r.content) > 1024:
				return _square_cover_art_bytes(r.content) or r.content
		except Exception:
			pass
	return None

def cover_art_url_bytes(url: str | None) -> Optional[bytes]:
	"""Fetch and normalize trusted HTTP(S) artwork, with a conservative size cap."""
	if not url or not str(url).lower().startswith(("https://", "http://")):
		return None
	from csvmusic.core.artwork import artwork_download_urls
	for candidate in artwork_download_urls(str(url)):
		cover = _fetch_cover_art_url_bytes(candidate)
		if cover:
			return cover
	return None


def _fetch_cover_art_url_bytes(url: str) -> Optional[bytes]:
	try:
		r = requests.get(str(url), timeout=12, stream=True)
		if r.status_code != 200 or not str(r.headers.get("content-type") or "").lower().startswith("image/"):
			return None
		content = r.raw.read(10 * 1024 * 1024 + 1)
		if not content or len(content) > 10 * 1024 * 1024:
			return None
		return _square_cover_art_bytes(content) or content
	except Exception:
		return None

def _square_cover_art_bytes(cover_bytes: bytes, *, size: int = 600) -> Optional[bytes]:
	"""
	Normalize embedded artwork to a square JPEG without stretching.
	Some older players assume cover art is square and distort non-square images.
	The image is center-cropped instead of padded so players do not show borders.
	"""
	if not cover_bytes:
		return None
	try:
		from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
		from PySide6.QtGui import QImage
		src = QImage()
		if src.loadFromData(cover_bytes):
			cropped = src.convertToFormat(QImage.Format_RGB32)
			cropped = cropped.scaled(
				size,
				size,
				Qt.KeepAspectRatioByExpanding,
				Qt.SmoothTransformation
			)
			x = max(0, (cropped.width() - size) // 2)
			y = max(0, (cropped.height() - size) // 2)
			cropped = cropped.copy(x, y, size, size)
			out = QByteArray()
			buf = QBuffer(out)
			buf.open(QIODevice.WriteOnly)
			if cropped.save(buf, "JPEG"):
				data = bytes(out)
				if len(data) > 1024:
					return data
	except Exception as exc:
		log(f"cover art Qt square normalization skipped: {exc}")
	try:
		ffmpeg_bin = ffmpeg_path()
		proc = subprocess.run(
			[
				ffmpeg_bin,
				"-hide_banner",
				"-loglevel", "error",
				"-f", "image2pipe",
				"-i", "pipe:0",
				"-vf", f"scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size}",
				"-frames:v", "1",
				"-f", "image2pipe",
				"-vcodec", "mjpeg",
				"pipe:1",
			],
			input=cover_bytes,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			**subprocess_kwargs()
		)
		if proc.returncode == 0 and proc.stdout and len(proc.stdout) > 1024:
			return proc.stdout
	except Exception as exc:
		log(f"cover art square normalization skipped: {exc}")
	return None

def tag_file(path: pathlib.Path, meta: Dict, cover_bytes: Optional[bytes], *, cover_size: int = 600) -> None:
	if cover_bytes and cover_size > 0:
		cover_bytes = _square_cover_art_bytes(cover_bytes, size=cover_size) or cover_bytes
	elif cover_size <= 0:
		cover_bytes = None
	if path.suffix.lower() == ".mp3":
		# ID3 (MP3)
		try:
			_ = EasyID3(path)
		except Exception:
			EasyID3.register_text_key("date", "TDRC")
			audio = EasyID3(); audio.save(path)
		audio = EasyID3(path)
		audio["title"] = meta.get("title","")
		audio["artist"] = meta.get("artists","")
		audio["album"] = meta.get("album","")
		if meta.get("year"): audio["date"] = str(meta["year"])
		if meta.get("track_no"): audio["tracknumber"] = str(meta["track_no"])
		if meta.get("disc_no"): audio["discnumber"] = str(meta["disc_no"])
		audio.save()
		id3 = ID3(path)
		if cover_bytes:
			id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_bytes))
			id3.save(v2_version=3)
	elif path.suffix.lower() in (".opus", ".ogg"):
		opus = OggOpus(path)
		opus["title"] = [meta.get("title", "")]
		opus["artist"] = [meta.get("artists", "")]
		opus["album"] = [meta.get("album", "")]
		if meta.get("year"): opus["date"] = [str(meta["year"])]
		if meta.get("track_no"): opus["tracknumber"] = [str(meta["track_no"])]
		if meta.get("disc_no"): opus["discnumber"] = [str(meta["disc_no"])]
		if cover_bytes:
			picture = Picture()
			picture.type = 3
			picture.mime = "image/jpeg"
			picture.desc = "Cover"
			picture.data = cover_bytes
			opus["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
		opus.save()
	else:
		# MP4/M4A
		mp4 = MP4(path)
		mp4["\xa9nam"] = meta.get("title","")
		mp4["\xa9ART"] = [meta.get("artists","")]
		mp4["\xa9alb"] = [meta.get("album","")]
		if meta.get("year"): mp4["\xa9day"] = [str(meta["year"])]
		if meta.get("track_no"): mp4["trkn"] = [(int(meta["track_no"]), 0)]
		if meta.get("disc_no"): mp4["disk"] = [(int(meta["disc_no"]), 0)]
		if cover_bytes:
			mp4["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
		mp4.save()


def _extractor_args(client: str | None) -> list[str]:
	if client is None:
		return []
	return ["--extractor-args", f"youtube:player_client={client}"]


_COMMON_YTDLP_ARGS = [
	"--no-playlist",
	"--force-overwrites",
	"--retries", "5",
	"--fragment-retries", "5",
	"--socket-timeout", "30",
]


def download_m4a(video_id: str, dst_dir: pathlib.Path, base_name: str, *, yt_dlp_bin: str | None = None, ffmpeg_bin: str | None = None, extra_yt_dlp_args: List[str] | None = None, audio_processing: Dict | None = None, before_install: BeforeInstall | None = None) -> pathlib.Path:
	"""
	YT Music only. Save using a sanitized stem so our search matches what yt-dlp writes.
	- If output is already .m4a → done.
	- Else try remux to .m4a (stream copy).
	- Else transcode to AAC .m4a.
	Everything is written in the staging folder first; only the finished file
	reaches ``dst_dir``.
	"""
	dst_dir.mkdir(parents=True, exist_ok=True)
	safe_base = _safe(base_name)
	staging = _staging_dir(dst_dir)
	# Force yt-dlp to use our sanitized basename
	out_tpl = str(staging / (safe_base + ".%(ext)s"))
	_cleanup_outputs(staging, safe_base)
	try:
		# Resolve yt-dlp automatically if not provided
		yt_bin = yt_dlp_bin or ytdlp_path()
		cookies_args: list[str] = list(extra_yt_dlp_args or [])
		js_runtime_args = ytdlp_js_runtime_args(yt_bin)
		primary_base = [yt_bin, "-f", "ba[ext=m4a]/bestaudio[ext=m4a]/bestaudio"] + _COMMON_YTDLP_ARGS
		fallback_base = [yt_bin, "-f", "bestaudio", "--no-continue"] + _COMMON_YTDLP_ARGS
		attempts: list[tuple[list[str], str]] = []
		for base_url in (YTM_URL.format(vid=video_id), YT_URL.format(vid=video_id)):
			for client in _youtube_clients(cookies_args):
				extractor_args = _extractor_args(client)
				attempts.append((primary_base + extractor_args + js_runtime_args + cookies_args + ["-o", out_tpl, base_url], f"primary client={client} url={base_url}"))
				attempts.append((fallback_base + extractor_args + js_runtime_args + cookies_args + ["-o", out_tpl, base_url], f"fallback client={client} url={base_url}"))
		_run_ytdlp_attempts(attempts, label="download_m4a", video_id=video_id)

		# What got written?
		cands = _list_downloads(staging, safe_base)
		if not cands:
			raise DownloadError("downloaded file not found")
		src = cands[0]
		staged = staging / (safe_base + ".m4a")
		ffmpeg_bin = ffmpeg_bin or ffmpeg_path()
		staged = _normalize_to_m4a(src, staged, ffmpeg_bin, video_id, audio_processing)
		store_source(staged)
		return _install_output(staged, dst_dir / (safe_base + ".m4a"), before_install)
	finally:
		_finish_staging(staging, safe_base)

def download_opus(video_id: str, dst_dir: pathlib.Path, base_name: str, *, yt_dlp_bin: str | None = None, ffmpeg_bin: str | None = None, extra_yt_dlp_args: List[str] | None = None, before_install: BeforeInstall | None = None) -> pathlib.Path:
	"""Download native Opus audio and remux it into an Ogg Opus container without re-encoding."""
	dst_dir.mkdir(parents=True, exist_ok=True)
	safe_base = _safe(base_name)
	staging = _staging_dir(dst_dir)
	out_tpl = str(staging / (safe_base + ".%(ext)s"))
	_cleanup_outputs(staging, safe_base)
	try:
		yt_bin = yt_dlp_bin or ytdlp_path()
		cookies_args = list(extra_yt_dlp_args or [])
		js_runtime_args = ytdlp_js_runtime_args(yt_bin)
		cmd_base = [yt_bin, "-f", "ba[acodec^=opus]"] + _COMMON_YTDLP_ARGS
		attempts: list[tuple[list[str], str]] = []
		for base_url in (YTM_URL.format(vid=video_id), YT_URL.format(vid=video_id)):
			for client in _youtube_clients(cookies_args):
				attempts.append((cmd_base + _extractor_args(client) + js_runtime_args + cookies_args + ["-o", out_tpl, base_url], f"client={client} url={base_url}"))
		_run_ytdlp_attempts(attempts, label="download_opus", video_id=video_id)
		candidates = _list_downloads(staging, safe_base)
		if not candidates:
			raise DownloadError("downloaded Opus file not found")
		src = candidates[0]
		staged = staging / f"{safe_base}.opus"
		if src != staged:
			ffmpeg_bin = ffmpeg_bin or ffmpeg_path()
			proc = _run_capture([ffmpeg_bin, "-y", "-i", str(src), "-map", "0:a:0", "-c:a", "copy", str(staged)])
			detail = _summarize_tool_output(proc.stderr or "", proc.stdout or "")
			if proc.returncode != 0 or not staged.exists():
				raise DownloadError(f"ffmpeg Opus remux failed: {detail}")
		store_source(staged)
		return _install_output(staged, dst_dir / f"{safe_base}.opus", before_install)
	finally:
		_finish_staging(staging, safe_base)

def download_mp3(video_id: str, dst_dir: pathlib.Path, base_name: str, cbr_320: bool = False, *, yt_dlp_bin: str | None = None, ffmpeg_bin: str | None = None, extra_yt_dlp_args: List[str] | None = None, audio_processing: Dict | None = None, mp3_quality: int = 0, cbr_bitrate_kbps: int | None = None, before_install: BeforeInstall | None = None) -> pathlib.Path:
	dst_dir.mkdir(parents=True, exist_ok=True)
	safe_base = _safe(base_name)
	staging = _staging_dir(dst_dir)
	tmp = staging / (safe_base + ".tmp")
	_cleanup_outputs(staging, safe_base)
	try:
		yt_bin = yt_dlp_bin or ytdlp_path()
		cookies_args: list[str] = list(extra_yt_dlp_args or [])
		js_runtime_args = ytdlp_js_runtime_args(yt_bin)
		cmd_base = [yt_bin, "-f", MP3_SOURCE_FORMAT] + _COMMON_YTDLP_ARGS
		attempts: list[tuple[list[str], str]] = []
		for base_url in (YTM_URL.format(vid=video_id), YT_URL.format(vid=video_id)):
			for client in _youtube_clients(cookies_args):
				attempts.append((cmd_base + _extractor_args(client) + js_runtime_args + cookies_args + ["-o", str(tmp), base_url], f"client={client} url={base_url}"))
		_run_ytdlp_attempts(attempts, label="download_mp3", video_id=video_id)

		# yt-dlp may append extension to .tmp; find it
		src = None
		if tmp.exists():
			src = tmp
		else:
			cands = _list_downloads(staging, safe_base + ".tmp")
			if cands: src = cands[0]
		if not src:
			raise DownloadError("temp file not found")

		staged = staging / (safe_base + ".mp3")
		ffmpeg_bin = ffmpeg_bin or ffmpeg_path()
		args = [ffmpeg_bin, "-y", "-i", str(src)]
		_append_audio_filter(args, audio_processing, src=src, ffmpeg_bin=ffmpeg_bin)
		mp3_quality = max(0, min(10, int(mp3_quality)))
		if cbr_bitrate_kbps is not None:
			args += ["-codec:a","libmp3lame","-b:a", f"{max(96, int(cbr_bitrate_kbps))}k"]
		elif cbr_320:
			args += ["-codec:a","libmp3lame","-b:a","320k"]
		else:
			args += ["-codec:a","libmp3lame","-q:a", str(mp3_quality)]
		args += [str(staged)]
		proc = _run_capture(args)
		rc = proc.returncode
		detail = _summarize_tool_output(proc.stderr or "", proc.stdout or "")
		if rc != 0 or not staged.exists():
			log(f"download_mp3: ffmpeg transcode failed video_id={video_id} dst='{staged.name}' rc={rc}")
			raise DownloadError(f"ffmpeg mp3 transcode failed: {detail}")
		store_source(staged)
		return _install_output(staged, dst_dir / (safe_base + ".mp3"), before_install)
	finally:
		_finish_staging(staging, safe_base)

# --- Conferência da duração depois de baixar (doc 13 §4.4) -------------------

# Até aqui a diferença é normal (arredondamento, silêncio no começo/fim).
DURATION_VERIFIED_MAX_S = 3.0
# Acima disto é outra versão ou um download cortado: rejeita.
DURATION_REJECT_OVER_S = 10.0
# Fontes que podem trazer outra versão da música; não servem para rejeitar.
_UNTRUSTED_DURATION_SOURCES = {"deezer", "itunes", "musicbrainz", "youtube"}


class DurationMismatchError(DownloadError):
	"""The downloaded file is much longer or shorter than the song asked for."""


@dataclass(frozen=True)
class DurationCheck:
	expected_s: float
	actual_s: float

	@property
	def diff_s(self) -> float:
		return self.actual_s - self.expected_s

	@property
	def verified(self) -> bool:
		return abs(self.diff_s) <= DURATION_VERIFIED_MAX_S

	@property
	def needs_review(self) -> bool:
		return not self.verified


def trusted_expected_duration(track: Dict) -> tuple[float, float] | None:
	"""Expected length in seconds and its precision, when the source is trustworthy."""
	try:
		duration_ms = float(track.get("duration_ms") or 0)
	except (TypeError, ValueError):
		return None
	if duration_ms <= 0:
		return None
	source = str(track.get("duration_source") or "").strip().lower()
	if source in _UNTRUSTED_DURATION_SOURCES:
		return None
	try:
		precision = max(0.0, float(track.get("duration_precision_s") or 0))
	except (TypeError, ValueError):
		precision = 0.0
	return duration_ms / 1000.0, precision


def measure_audio_duration_s(path: pathlib.Path) -> float | None:
	"""Real length of an audio file, read by mutagen (no decoding)."""
	try:
		import mutagen
		audio = mutagen.File(str(path))
	except Exception as exc:
		log(f"duration check: could not read '{path.name}': {exc}")
		return None
	length = getattr(getattr(audio, "info", None), "length", None)
	try:
		length = float(length)
	except (TypeError, ValueError):
		return None
	return length if length > 0 else None


def _format_seconds(seconds: float) -> str:
	total = int(round(abs(seconds)))
	return f"{total // 60}:{total % 60:02d}"


def check_downloaded_duration(path: pathlib.Path, track: Dict, *, reject: bool = True) -> DurationCheck | None:
	"""Compare the file length with the trusted length of the requested song.

	Returns ``None`` when there is no trusted length to compare with. With
	``reject``, a difference above ``DURATION_REJECT_OVER_S`` (or an unreadable
	file) raises ``DurationMismatchError`` so the next candidate can be tried.
	"""
	expected = trusted_expected_duration(track)
	if expected is None:
		return None
	expected_s, precision = expected
	actual_s = measure_audio_duration_s(path)
	if actual_s is None:
		if reject:
			raise DurationMismatchError(f"could not read the length of the downloaded file (expected {_format_seconds(expected_s)})")
		return None
	check = DurationCheck(expected_s, actual_s)
	if reject and abs(check.diff_s) > DURATION_REJECT_OVER_S + precision:
		sign = "+" if check.diff_s > 0 else "-"
		raise DurationMismatchError(
			f"wrong length: file {_format_seconds(actual_s)}, expected {_format_seconds(expected_s)} ({sign}{abs(check.diff_s):.0f} s)"
		)
	return check


def write_m3u(out_dir: pathlib.Path, playlist_name: str, tracks_done: List[Dict], ext: str, *, suffix: str = ".m3u8", encoding: str = "utf-8", playlist_output_dir: pathlib.Path | None = None) -> pathlib.Path:
	media_dir = out_dir / _safe(playlist_name)
	media_dir.mkdir(parents=True, exist_ok=True)
	playlist_dir = pathlib.Path(playlist_output_dir) if playlist_output_dir else media_dir
	playlist_dir.mkdir(parents=True, exist_ok=True)
	fp = playlist_dir / f"{_safe(playlist_name)}{suffix}"
	with fp.open("w", encoding=encoding, errors="ignore") as f:
		f.write("#EXTM3U\n")
		f.write(f"#EXTPLAYLIST:{playlist_name}\n")
		for t in tracks_done:
			title = t["title"]; artists = t["artists"]; album = t["album"]
			base = f"{artists} - {title}"
			if t.get("filename_prefix_number"):
				width = max(2, int(t.get("filename_prefix_width") or 2))
				base = f"{int(t['filename_prefix_number']):0{width}d}- {base}"
			media_path = media_dir / f"{_safe(base)}.{ext}"
			stored = str(t.get("downloaded_path") or "").strip()
			if stored and not media_path.exists() and pathlib.Path(stored).is_file():
				# The song's file kept an older name (position changed, no prefix): list the real file.
				media_path = pathlib.Path(stored)
			try:
				rel = pathlib.Path(os.path.relpath(media_path.resolve(), playlist_dir.resolve()))
			except ValueError:
				# Windows cannot make a relative path across different drives.
				rel = media_path.resolve()
			dur = int(round((t.get("duration_ms") or 0)/1000))
			f.write(f"#EXTINF:{dur},{artists} - {title}\n")
			if t.get("isrc"): f.write(f"#EXTISRC:{t['isrc']}\n")
			f.write(f"#EXTALBUM:{album}\n")
			f.write(str(rel.as_posix()) + "\n")
	return fp
