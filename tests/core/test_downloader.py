import pathlib
import pytest
from csvmusic.core import downloader
import unicodedata


def test_youtube_client_fallbacks_use_current_client_names():
	assert downloader.YOUTUBE_CLIENTS[0] == "web_embedded"
	assert downloader.YOUTUBE_CLIENTS[1] is None
	assert "tv_embedded" not in downloader.YOUTUBE_CLIENTS
	assert "webremix" not in downloader.YOUTUBE_CLIENTS
	assert downloader._extractor_args(None) == []


def test_mp3_source_format_falls_back_to_combined_stream():
	assert downloader.MP3_SOURCE_FORMAT == "bestaudio/best"


def test_auth_required_errors_do_not_retry_without_cookies():
	assert not downloader._should_retry_without_cookies(
		"ERROR: Sign in to confirm your age",
		"",
	)
	assert not downloader._should_retry_without_cookies(
		"ERROR: login_required: age-restricted video",
		"",
	)
	assert not downloader._should_retry_without_cookies(
		"ERROR: Precondition check failed",
		"",
	)


def test_cookie_backed_age_failure_mentions_cookies_were_used():
	detail = downloader._summarize_tool_output(
		"ERROR: Sign in to confirm your age",
		"",
		using_cookies=True,
	)

	assert "Cookies were used" in detail
	assert "Sign into YouTube with Firefox cookies" not in detail


def test_public_extraction_errors_can_still_retry_without_cookies():
	assert downloader._should_retry_without_cookies(
		"ERROR: signature solving failed",
		"",
	)


def test_js_runtime_failure_mentions_deno_or_node():
	detail = downloader._summarize_tool_output(
		"WARNING: No supported JavaScript runtime could be found",
		"",
	)

	assert "Deno 2.3+" in detail
	assert "Node 22+" in detail


def test_error_summary_prefers_error_over_trailing_progress():
	detail = downloader._summarize_tool_output(
		"ERROR: [youtube] challenge solving failed\n[youtube] Downloading android vr player API JSON",
		"[youtube] Sleeping 1.25 seconds",
	)

	assert "challenge solving failed" in detail
	assert "Sleeping" not in detail


def test_large_batch_warning_requires_explicit_risk_acknowledgement():
	profile = downloader.youtube_batch_mitigation(300, using_cookies=False)
	message = downloader.youtube_risk_acknowledgement(profile)

	assert profile.active is True
	assert "repeated YouTube API, search, and media requests" in message
	assert "temporarily block requests" in message
	assert "randomized delays" in message


def test_small_batch_does_not_require_risk_acknowledgement():
	profile = downloader.youtube_batch_mitigation(20, using_cookies=False)

	assert downloader.youtube_risk_acknowledgement(profile) is None


def test_list_downloads_matches_decomposed_accents(tmp_path):
	base = downloader.sanitize_name("Björk - Jóga")
	decomposed = unicodedata.normalize("NFD", base)
	path = tmp_path / f"{decomposed}.webm"
	path.write_text("audio")

	assert downloader._list_downloads(tmp_path, base) == [path]


def test_cleanup_outputs_removes_decomposed_accents(tmp_path):
	base = downloader.sanitize_name("Mötley Crüe - Über")
	decomposed = unicodedata.normalize("NFD", base)
	path = tmp_path / f"{decomposed}.tmp.webm"
	path.write_text("audio")

	downloader._cleanup_outputs(tmp_path, base)

	assert not path.exists()


def test_sanitize_name_shortens_long_windows_filenames_deterministically():
	first = downloader.sanitize_name("Orchestra - " + "A" * 300)
	second = downloader.sanitize_name("Orchestra - " + "B" * 300)

	assert len(first) == downloader._MAX_SAFE_NAME_LENGTH
	assert len(second) == downloader._MAX_SAFE_NAME_LENGTH
	assert first != second
	assert first == downloader.sanitize_name("Orchestra - " + "A" * 300)


def test_tag_file_writes_mp3_track_and_disc_numbers(monkeypatch, tmp_path):
	tags = {}

	class FakeEasyID3(dict):
		def save(self, *_args, **_kwargs):
			pass

	class FakeID3:
		def __init__(self, _path):
			pass

	def fake_easy_id3(_path=None):
		return tags_object

	tags_object = FakeEasyID3()
	monkeypatch.setattr(downloader, "EasyID3", fake_easy_id3)
	monkeypatch.setattr(downloader, "ID3", FakeID3)

	downloader.tag_file(
		tmp_path / "track.mp3",
		{"title": "Song", "artists": "Artist", "album": "Album", "track_no": 7, "disc_no": 2},
		None,
	)

	assert tags_object["tracknumber"] == "7"
	assert tags_object["discnumber"] == "2"


def test_tag_file_writes_m4a_track_and_disc_numbers(monkeypatch, tmp_path):
	class FakeMP4(dict):
		def save(self):
			pass

	tags = FakeMP4()
	monkeypatch.setattr(downloader, "MP4", lambda _path: tags)

	downloader.tag_file(
		tmp_path / "track.m4a",
		{"title": "Song", "artists": "Artist", "album": "Album", "track_no": 7, "disc_no": 2},
		None,
	)

	assert tags["trkn"] == [(7, 0)]
	assert tags["disk"] == [(2, 0)]


def test_tag_file_writes_opus_metadata(monkeypatch, tmp_path):
	class FakeOpus(dict):
		def save(self):
			pass

	tags = FakeOpus()
	monkeypatch.setattr(downloader, "OggOpus", lambda _path: tags)

	downloader.tag_file(
		tmp_path / "track.opus",
		{"title": "Song", "artists": "Artist", "album": "Album", "year": 2026, "track_no": 7, "disc_no": 2},
		None,
	)

	assert tags["title"] == ["Song"]
	assert tags["artist"] == ["Artist"]
	assert tags["date"] == ["2026"]
	assert tags["tracknumber"] == ["7"]
	assert tags["discnumber"] == ["2"]


def test_write_m3u_defaults_to_audio_folder(tmp_path):
	track = {"title": "Song", "artists": "Artist", "album": "Album", "duration_ms": 1000}
	path = downloader.write_m3u(tmp_path, "Mix", [track], "mp3")

	assert path == tmp_path / "Mix" / "Mix.m3u8"
	assert path.read_text(encoding="utf-8").splitlines()[-1] == "Artist - Song.mp3"


def test_write_m3u_uses_relative_media_paths_from_custom_folder(tmp_path):
	track = {"title": "Song", "artists": "Artist", "album": "Album", "duration_ms": 1000}
	playlist_dir = tmp_path / "Playlists"
	path = downloader.write_m3u(tmp_path / "Music", "Mix", [track], "mp3", playlist_output_dir=playlist_dir)

	assert path == playlist_dir / "Mix.m3u8"
	assert path.read_text(encoding="utf-8").splitlines()[-1] == "../Music/Mix/Artist - Song.mp3"


@pytest.mark.parametrize("download", [downloader.download_mp3, downloader.download_m4a, downloader.download_opus])
def test_bot_check_in_raw_stderr_is_detected_and_stops_attempts(monkeypatch, tmp_path, download):
	calls = []
	def fail(args):
		calls.append(args)
		return 1, "", "ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies"
	monkeypatch.setattr(downloader, "_run_ytdlp_module", fail)
	monkeypatch.setattr(downloader, "ytdlp_js_runtime_args", lambda _bin: [])
	with pytest.raises(downloader.YouTubeRiskError) as error:
		download("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP)
	assert error.value.reason == "YouTube asked for bot verification"
	assert len(calls) == 1


def test_rate_limit_on_first_attempt_is_not_masked_by_later_errors(monkeypatch, tmp_path):
	answers = iter([
		(1, "", "ERROR: Unable to download webpage: HTTP Error 429: Too Many Requests"),
	] + [(1, "", "ERROR: Video unavailable")] * 30)
	monkeypatch.setattr(downloader, "_run_ytdlp_module", lambda _args: next(answers))
	monkeypatch.setattr(downloader, "ytdlp_js_runtime_args", lambda _bin: [])
	with pytest.raises(downloader.YouTubeRiskError) as error:
		downloader.download_m4a("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP)
	assert error.value.reason == "YouTube returned HTTP 429"


def test_plain_failures_keep_details_from_every_attempt(monkeypatch, tmp_path):
	answers = iter([(1, "", "ERROR: first problem")] + [(1, "", "ERROR: last problem")] * 30)
	monkeypatch.setattr(downloader, "_run_ytdlp_module", lambda _args: next(answers))
	monkeypatch.setattr(downloader, "ytdlp_js_runtime_args", lambda _bin: [])
	with pytest.raises(downloader.DownloadError) as error:
		downloader.download_opus("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP)
	assert not isinstance(error.value, downloader.YouTubeRiskError)
	assert "first problem" in str(error.value)
	assert "last problem" in str(error.value)


@pytest.mark.parametrize("count", [500, 1124, 5000])
def test_huge_batch_starts_paced_without_false_throttling_warning(count):
	profile = downloader.youtube_batch_mitigation(count, using_cookies=False)

	assert profile.label != downloader.YOUTUBE_MITIGATION_AGGRESSIVE.label
	assert profile.active is True
	assert "throttling" not in (profile.warning or "").lower()
	assert "started throttling" not in (downloader.youtube_risk_acknowledgement(profile) or "").lower()


def _fake_tools(monkeypatch, *, ext="webm", payload=b"new audio", codec="aac"):
	"""Simulate yt-dlp (writes the -o target) and ffmpeg (copies input to output)."""
	import shutil
	import subprocess
	calls = {"ytdlp": [], "ffmpeg": []}

	def fake_ytdlp(args):
		calls["ytdlp"].append(args)
		target = args[args.index("-o") + 1].replace("%(ext)s", ext)
		pathlib.Path(target).write_bytes(payload)
		return 0, "", ""

	def fake_capture(cmd, **_kwargs):
		calls["ffmpeg"].append(cmd)
		source = cmd[cmd.index("-i") + 1] if "-i" in cmd else None
		if source and cmd[-1] == source:
			# ffmpeg -i <arquivo> sem saída: só descreve as faixas.
			return subprocess.CompletedProcess(cmd, 1, "", f"Stream #0:0: Audio: {codec}, 48000 Hz, stereo")
		if source and not cmd[-1].startswith("-"):
			shutil.copyfile(source, cmd[-1])
		return subprocess.CompletedProcess(cmd, 0, "", "")

	monkeypatch.setattr(downloader, "_run_ytdlp_module", fake_ytdlp)
	monkeypatch.setattr(downloader, "_run_capture", fake_capture)
	monkeypatch.setattr(downloader, "ytdlp_js_runtime_args", lambda _bin: [])
	monkeypatch.setattr(downloader, "store_source", lambda _path: None)
	return calls


@pytest.mark.parametrize("download, fmt", [
	(downloader.download_m4a, "m4a"),
	(downloader.download_mp3, "mp3"),
	(downloader.download_opus, "opus"),
])
def test_switching_format_keeps_other_files_of_the_same_song(monkeypatch, tmp_path, download, fmt):
	_fake_tools(monkeypatch)
	others = {}
	for ext in ("mp3", "m4a", "opus", "lrc", "webm"):
		if ext == fmt:
			continue
		path = tmp_path / f"Artist - Song.{ext}"
		path.write_bytes(f"old {ext}".encode())
		others[path] = path.read_bytes()

	result = download("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP, ffmpeg_bin="ffmpeg")

	assert result == tmp_path / f"Artist - Song.{fmt}"
	assert result.read_bytes() == b"new audio"
	for path, content in others.items():
		assert path.read_bytes() == content
	assert not (tmp_path / downloader.STAGING_DIR_NAME).exists()


def test_redownload_keeps_replaced_file_in_trash(monkeypatch, tmp_path):
	_fake_tools(monkeypatch)
	current = tmp_path / "Artist - Song.mp3"
	current.write_bytes(b"old audio")

	downloader.download_mp3("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP, ffmpeg_bin="ffmpeg")

	assert current.read_bytes() == b"new audio"
	kept = list((tmp_path / downloader.TRASH_DIR_NAME).iterdir())
	assert len(kept) == 1 and kept[0].suffix == ".mp3"
	assert kept[0].read_bytes() == b"old audio"


def test_failed_download_leaves_no_partial_files(monkeypatch, tmp_path):
	_fake_tools(monkeypatch)

	def fail(args):
		target = args[args.index("-o") + 1].replace("%(ext)s", "webm")
		pathlib.Path(target + ".part").write_bytes(b"half")
		return 1, "", "ERROR: Video unavailable"

	monkeypatch.setattr(downloader, "_run_ytdlp_module", fail)
	existing = tmp_path / "Artist - Song.m4a"
	existing.write_bytes(b"old audio")

	with pytest.raises(downloader.DownloadError):
		downloader.download_m4a("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP, ffmpeg_bin="ffmpeg")

	assert existing.read_bytes() == b"old audio"
	assert sorted(p.name for p in tmp_path.iterdir()) == ["Artist - Song.m4a"]


@pytest.mark.parametrize("download, fmt", [
	(downloader.download_m4a, "m4a"),
	(downloader.download_mp3, "mp3"),
	(downloader.download_opus, "opus"),
])
def test_file_is_finished_before_it_reaches_the_playlist_folder(monkeypatch, tmp_path, download, fmt):
	_fake_tools(monkeypatch)
	final = tmp_path / f"Artist - Song.{fmt}"
	seen = []

	def before_install(staged):
		seen.append((staged, final.exists()))

	result = download("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP, ffmpeg_bin="ffmpeg", before_install=before_install)

	assert result == final and final.read_bytes() == b"new audio"
	assert len(seen) == 1
	staged, final_existed = seen[0]
	assert staged.parent.name == downloader.STAGING_DIR_NAME
	assert staged.suffix == f".{fmt}"
	assert final_existed is False


def test_failed_finishing_step_never_leaves_a_file_in_the_playlist_folder(monkeypatch, tmp_path):
	_fake_tools(monkeypatch)
	previous = tmp_path / "Artist - Song.m4a"
	previous.write_bytes(b"old audio")

	def broken_tags(_staged):
		raise RuntimeError("tagging crashed")

	with pytest.raises(RuntimeError, match="tagging crashed"):
		downloader.download_m4a("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP, ffmpeg_bin="ffmpeg", before_install=broken_tags)

	assert previous.read_bytes() == b"old audio"
	assert sorted(p.name for p in tmp_path.iterdir()) == ["Artist - Song.m4a"]


@pytest.mark.parametrize("codec, expect_copy", [("opus", False), ("vorbis", False), ("aac", True)])
def test_m4a_only_copies_streams_apple_devices_can_play(monkeypatch, tmp_path, codec, expect_copy):
	calls = _fake_tools(monkeypatch, codec=codec)

	result = downloader.download_m4a("video", tmp_path, "Artist - Song", yt_dlp_bin=downloader.INTERNAL_YTDLP, ffmpeg_bin="ffmpeg")

	assert result == tmp_path / "Artist - Song.m4a"
	writes = [cmd for cmd in calls["ffmpeg"] if cmd[-1].endswith(".normalized.m4a")]
	assert len(writes) == 1
	encoder = writes[0][writes[0].index("-c:a") + 1]
	assert encoder == ("copy" if expect_copy else "aac")
