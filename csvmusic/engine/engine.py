# tabs only
"""Motor do CSVMusic: biblioteca em memória, análises, downloads, conta, aparelhos.

Roda na thread principal do Qt e não cria widget nenhum. O que precisa de uma
janela nativa (seletor de pasta, login do Google, leitor do Spotify) pede ao
`host` (ver `csvmusic/web/native.py`); nos testes o host é falso.

Cada mudança vira um evento (`add_listener`), que o servidor repassa para a
página por Server-Sent Events (docs/fork/14-interface-web.md §5).
"""
from __future__ import annotations

import base64
import collections
import datetime
import hashlib
import pathlib
import random
import re
import tempfile
import threading
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer

from csvmusic.core.downloader import sanitize_name, tag_file, write_m3u, youtube_batch_mitigation, youtube_risk_acknowledgement
from csvmusic.core.library import (
	FAILURE_AGE_RESTRICTED, add_playlist_urls, age_restricted_targets, apply_library_download_result,
	backup_library_file, clear_playlist_access_error, describe_skip, edit_library_track, enabled_tracks,
	export_csv, find_library_track, import_csv_playlist, library_track_path, load_library, m3u_ready_tracks, playlist_probes,
	mark_playlist_access_error, merge_playlist_scan, new_library, playlist_by_id, rename_library_playlist,
	save_library, write_library_m3us,
)
from csvmusic.core.log import log
from csvmusic.core.settings import flush_settings, load_settings, save_settings, settings_path
from csvmusic.core.track_output import SUPPORTED_FORMATS, expected_track_path, library_format
from csvmusic.core.youtube_url import YouTubeVideoUrlError, parse_youtube_video_id
from csvmusic.engine import texts, views
from csvmusic.engine.trash import TrashError, empty_internal_trash, internal_trash_stats, move_to_system_trash
from csvmusic.engine.workers import (
	DevicePlaylistReadWorker, DeviceSyncWorker, DirectLibraryScanWorker, audio_processing_settings,
	audio_processing_signature, legacy_options, pending_download_tracks,
)
from csvmusic.version import APP_VERSION

# Gravação agrupada do library.json durante um download (sempre grava no fim do lote e ao fechar).
LIBRARY_SAVE_DELAY_MS = 3000
# Durante um lote, o M3U da playlist é reescrito a cada tantas músicas baixadas.
M3U_WRITE_EVERY_TRACKS = 10
# No máximo 4 eventos `job` por segundo.
JOB_EVENT_INTERVAL_S = 0.25
SESSION_LOG_LIMIT = 5000
DEFAULT_WEB_PORT = 8765
EQ_BANDS = ("volume", "bass", "treble")
LEGACY_MP3_MODES = ("vbr", "cbr_192", "cbr_256", "cbr_320")
THEMES = ("system", "light", "dark")

_BOOL_SETTINGS = {
	"legacy_ipod_mode": False, "embed_art": True, "force_download_mode": False, "prefix_track_numbers": False,
	"write_m3u8": True, "write_m3u_plain": False, "use_cookies": False, "eq_enabled": False, "eq_normalize": False,
	"device_sync_auto_eject": False,
}
_PATH_SETTINGS = ("m3u_output_dir", "yt_dlp_path", "ffmpeg_path", "cookies_file")


class EngineError(Exception):
	"""Pedido recusado; `message` vai para a tela (português) e `status` vira o código HTTP."""

	def __init__(self, status: int, message: str, **extra: Any):
		super().__init__(message)
		self.status = status
		self.message = message
		self.extra = extra


class NullHost:
	"""Host sem janelas: usado nos testes e quando o app roda sem tela."""

	def choose_folder(self, purpose: str, start: str = "") -> str | None:
		return None

	def choose_file(self, purpose: str) -> str | None:
		return None

	def save_file(self, purpose: str, suggested: str = "") -> str | None:
		return None

	def youtube_sign_in(self, method: str) -> str | None:
		return None

	def create_spotify_reader(self):
		return None

	def show_spotify_reader(self, reader) -> None:
		pass

	def hide_spotify_reader(self, reader) -> None:
		pass

	def open_path(self, path: str) -> bool:
		return False

	def reveal_path(self, path: str) -> bool:
		return False


def _now_local() -> datetime.datetime:
	return datetime.datetime.now().astimezone()


def _key_of(playlist: dict) -> str:
	return views.playlist_key(playlist)


class Engine(QObject):
	def __init__(self, *, host=None, library_path: str | pathlib.Path | None = None, parent: QObject | None = None):
		super().__init__(parent)
		self.host = host or NullHost()
		self._listeners: list[Callable[[str, dict], None]] = []
		# Fábricas trocáveis nos testes (nenhum teste acessa a rede).
		from csvmusic.ui.workers import PipelineWorker, SingleDownloadWorker, YouTubeSessionTestWorker
		self.pipeline_worker_factory = PipelineWorker
		self.single_worker_factory = SingleDownloadWorker
		self.session_worker_factory = YouTubeSessionTestWorker
		self.direct_scan_worker_factory = DirectLibraryScanWorker
		self.device_sync_worker_factory = DeviceSyncWorker
		self.trash_mover = move_to_system_trash
		self.mp3_check: Callable[[], bool] = self._ffmpeg_supports_mp3
		# Biblioteca.
		self.library_path = pathlib.Path(library_path) if library_path else settings_path().parent / "library.json"
		self.library_load_error: str | None = None
		self.library = self._load_or_create()
		self.library_dirty = False
		self._save_timer = QTimer(self)
		self._save_timer.setSingleShot(True)
		self._save_timer.setInterval(LIBRARY_SAVE_DELAY_MS)
		self._save_timer.timeout.connect(self.flush_library)
		self._paths_cache: dict[str, list[pathlib.Path | None]] = {}
		self.runtime_states: dict[tuple[str, int], str] = {}
		# Análise.
		self.scan_queue: list[dict] = []
		self.scan_results: list[dict] = []
		self.scan_cancelled = False
		self.scan_current: dict | None = None
		self.scan_progress: tuple[int, int | None] = (0, None)
		self.scraper = None
		self.direct_worker = None
		self._scan_running = False
		self._scan_timer: QTimer | None = None
		# Download.
		self.download_worker = None
		self.single_worker = None
		self.download_targets: dict[int, tuple[str, int]] = {}
		self.download_playlist_ids: list[str] = []
		self.download_total = 0
		self.download_processed = 0
		self.download_started_at = 0.0
		self.download_stopping = False
		self.download_current: dict | None = None
		self.download_m3u_tracks: list[dict] = []
		self.download_m3u_pending: set[str] = set()
		self.download_m3u_count = 0
		self.age_restricted_pending: set[tuple[str, int]] = set()
		# Conta do YouTube.
		self.session_worker = None
		self._session_purpose = ""
		self.account_checked_at: str | None = None
		self.account_ok: bool | None = None
		# Aparelhos.
		self._devices: dict[str, Any] = {}
		self._device_lock = threading.Lock()
		self.device_worker = None
		self.device_busy = False
		# Registro da sessão.
		self._log_entries: collections.deque = collections.deque(maxlen=SESSION_LOG_LIMIT)
		self._log_seq = 0
		self._log_lock = threading.Lock()
		# Eventos `job`, no máximo 4 por segundo.
		self._job_last_emit = 0.0
		self._job_timer = QTimer(self)
		self._job_timer.setSingleShot(True)
		self._job_timer.timeout.connect(lambda: self.emit_job(force=True))
		self._video_info_cache: dict[str, dict] = {}

	# --- eventos ---------------------------------------------------------------------

	def add_listener(self, listener: Callable[[str, dict], None]) -> None:
		self._listeners.append(listener)

	def remove_listener(self, listener: Callable[[str, dict], None]) -> None:
		if listener in self._listeners:
			self._listeners.remove(listener)

	def emit(self, kind: str, data: dict) -> None:
		for listener in list(self._listeners):
			try:
				listener(kind, data)
			except Exception as exc:
				log(f"engine event listener failed kind={kind} error={exc}")

	def emit_job(self, *, force: bool = False) -> None:
		now = time.monotonic()
		if not force and now - self._job_last_emit < JOB_EVENT_INTERVAL_S:
			if not self._job_timer.isActive():
				self._job_timer.start(int(JOB_EVENT_INTERVAL_S * 1000))
			return
		self._job_timer.stop()
		self._job_last_emit = now
		self.emit("job", self.job())

	def emit_playlist(self, playlist_id: str) -> None:
		summary = self.playlist_summary(playlist_id)
		if summary:
			self.emit("playlist", summary)

	def emit_track(self, playlist_id: str, index: int) -> None:
		playlist = playlist_by_id(self.library, playlist_id)
		if playlist is None or not (0 <= index < len(playlist.get("tracks", []))):
			return
		self.emit("track", {"playlist_id": _key_of(playlist), "track": self._track_view(playlist, index)})

	def warn(self, message: str) -> None:
		self.emit("warning", {"message": message})

	# --- registro da sessão ----------------------------------------------------------

	def session_log(self, level: str, message: str) -> None:
		clean = " ".join(str(message or "").split())
		if not clean:
			return
		with self._log_lock:
			self._log_seq += 1
			entry = {"seq": self._log_seq, "ts": _now_local().isoformat(timespec="seconds"), "level": level, "message": clean}
			self._log_entries.append(entry)
		self.emit("log", entry)

	def log_entries(self, since: int = 0) -> dict:
		with self._log_lock:
			entries = [entry for entry in self._log_entries if entry["seq"] > since]
			return {"entries": entries, "last_seq": self._log_seq}

	# --- biblioteca ----------------------------------------------------------------------

	def _load_or_create(self) -> dict:
		self.library_load_error = None
		if self.library_path.exists():
			try:
				return load_library(self.library_path)
			except Exception as exc:
				log(f"library load failed path={self.library_path} error={exc}")
				# Nunca gravar uma biblioteca vazia por cima de um arquivo que não deu para ler.
				backup_note = ""
				try:
					backup = backup_library_file(self.library_path)
					backup_note = f" Uma cópia foi guardada em {backup}."
					log(f"library unreadable file copied backup={backup}")
				except OSError as backup_exc:
					log(f"library unreadable file backup failed error={backup_exc}")
				self.library_load_error = (
					f"Não deu para abrir a biblioteca ({self.library_path}); o arquivo ficou como estava.{backup_note} "
					"O app abriu vazio e não grava nada até o arquivo voltar a ser lido."
				)
		return new_library()

	def mark_dirty(self) -> None:
		"""Agenda uma gravação agrupada; o tempo não reinicia, então um lote longo grava a cada poucos segundos."""
		self.library_dirty = True
		if not self._save_timer.isActive():
			self._save_timer.start()

	def flush_library(self) -> None:
		if self.library_dirty:
			self.save()

	def save(self) -> None:
		self._save_timer.stop()
		self.library_dirty = False
		if self.library_load_error:
			log(f"library save blocked: the file could not be read path={self.library_path}")
			return
		save_library(self.library_path, self.library)
		log(f"library saved path={self.library_path} playlists={len(self.library.get('playlists', []))}")

	def output_dir(self) -> str:
		return str(self.library.get("output_dir") or "").strip()

	def fmt(self) -> str:
		return library_format(self.library)

	def invalidate_paths(self, playlist_id: str | None = None) -> None:
		if playlist_id is None:
			self._paths_cache.clear()
		else:
			self._paths_cache.pop(playlist_id, None)

	def _paths(self, playlist: dict) -> list[pathlib.Path | None]:
		key = _key_of(playlist)
		cached = self._paths_cache.get(key)
		tracks = playlist.get("tracks", [])
		if cached is not None and len(cached) == len(tracks):
			return cached
		listing: dict = {}
		output, fmt = self.output_dir(), self.fmt()
		probes = playlist_probes(playlist)
		paths = [views.resolve_track_path(playlist, track, output, fmt, listing, probes) for track in tracks]
		self._paths_cache[key] = paths
		return paths

	def _refresh_track_path(self, playlist: dict, index: int) -> None:
		paths = self._paths(playlist)
		if 0 <= index < len(paths):
			paths[index] = views.resolve_track_path(playlist, playlist["tracks"][index], self.output_dir(), self.fmt())

	def _counts(self, playlist: dict) -> dict:
		counts = views.empty_counts()
		for track, path in zip(playlist.get("tracks", []), self._paths(playlist)):
			views.add_to_counts(counts, track, path is not None)
		return counts

	def _playlist(self, playlist_id: str) -> dict:
		playlist = playlist_by_id(self.library, playlist_id)
		if playlist is None:
			raise EngineError(404, "Esta playlist não está na biblioteca.")
		return playlist

	def _track(self, playlist: dict, index: int) -> dict:
		tracks = playlist.get("tracks", [])
		if not (0 <= index < len(tracks)):
			raise EngineError(404, "Esta música não está mais na playlist.")
		return tracks[index]

	def _track_view(self, playlist: dict, index: int) -> dict:
		paths = self._paths(playlist)
		return views.track_view(
			playlist, index, playlist["tracks"][index], paths[index] if index < len(paths) else None,
			self.runtime_states.get((_key_of(playlist), index)),
		)

	def playlist_summary(self, playlist_id: str) -> dict | None:
		playlist = playlist_by_id(self.library, playlist_id)
		if playlist is None:
			return None
		return views.playlist_view(playlist, self._counts(playlist), self.output_dir())

	def busy(self) -> bool:
		return self.downloads_running() or self.scan_running()

	def state(self) -> dict:
		if not self.busy():
			# Fora de uma tarefa, confere de novo os arquivos (o usuário pode ter mexido na pasta).
			self.invalidate_paths()
		cfg = load_settings()
		return {
			"version": APP_VERSION,
			"library": {
				"path": str(self.library_path), "output_dir": self.output_dir(), "format": self.fmt(),
				"load_error": self.library_load_error,
			},
			"playlists": [views.playlist_view(playlist, self._counts(playlist), self.output_dir()) for playlist in self.library.get("playlists", [])],
			"job": self.job(),
			"account": self.account(cfg),
			"first_run": not bool(cfg.get("hide_startup_disclaimer", False)),
		}

	def tracks(self, playlist_id: str, *, filter_name: str = "all", query: str = "", offset: int = 0, limit: int = 100) -> dict:
		playlist = self._playlist(playlist_id)
		if filter_name not in views.FILTERS:
			raise EngineError(400, "Filtro desconhecido.")
		offset = max(0, int(offset))
		limit = max(1, min(500, int(limit)))
		paths = self._paths(playlist)
		selected = [
			index for index, track in enumerate(playlist.get("tracks", []))
			if views.matches_filter(track, paths[index] is not None, filter_name) and views.matches_query(track, query)
		]
		return {
			"total": len(selected),
			"counts": self._counts(playlist),
			"items": [self._track_view(playlist, index) for index in selected[offset:offset + limit]],
		}

	def track(self, playlist_id: str, index: int) -> dict:
		playlist = self._playlist(playlist_id)
		self._track(playlist, index)
		return self._track_view(playlist, index)

	def track_snapshot(self, playlist_id: str, index: int) -> dict:
		"""Cópia da música para buscas fora da thread do Qt."""
		playlist = self._playlist(playlist_id)
		track = dict(self._track(playlist, index))
		track["playlist"] = playlist.get("name") or "Playlist"
		return track

	def open_library(self, path: str) -> dict:
		if self.busy():
			raise EngineError(409, "Espere a tarefa atual terminar antes de abrir outra biblioteca.")
		target = pathlib.Path(str(path or "")).expanduser()
		try:
			library = load_library(target)
		except Exception as exc:
			log(f"library open failed path={target} error={exc}")
			raise EngineError(400, "Não deu para abrir este arquivo de biblioteca.") from exc
		self.flush_library()
		self.library = library
		self.library_path = target
		self.library_load_error = None
		self.invalidate_paths()
		self.runtime_states.clear()
		self.emit("library", {"path": str(target)})
		return self.state()

	def save_library_as(self, path: str) -> dict:
		target = pathlib.Path(str(path or "")).expanduser()
		if not str(path or "").strip():
			raise EngineError(400, "Escolha onde salvar a biblioteca.")
		self.library_path = target.with_suffix(".json")
		self.library_load_error = None
		self.save()
		self.emit("library", {"path": str(self.library_path)})
		return {"path": str(self.library_path)}

	# --- playlists -------------------------------------------------------------------

	def add_playlists(self, urls: list[str]) -> dict:
		added_ids: list[str] = []
		errors: list[dict] = []
		warnings: list[str] = []
		for raw in urls or []:
			url = str(raw or "").strip()
			if not url:
				continue
			lower = url.casefold()
			if ("youtube.com" in lower or "youtu.be" in lower) and "music.youtube.com" not in lower:
				if "list=" not in lower:
					errors.append({"url": url, "error": texts.add_url_error_pt("single youtube video")})
					continue
				warnings.append(
					"Playlist comum do YouTube: nome da música, artista e capa podem vir errados. "
					"Confira as músicas depois da análise; o YouTube Music é mais confiável."
				)
			before = {_key_of(playlist) for playlist in self.library.get("playlists", [])}
			added, problems = add_playlist_urls(self.library, [url])
			if problems:
				log(f"library add url rejected url={url} error={problems[0]}")
				errors.append({"url": url, "error": texts.add_url_error_pt(problems[0])})
				continue
			if not added:
				errors.append({"url": url, "error": "Esta playlist já está na biblioteca."})
				continue
			for playlist in added:
				key = _key_of(playlist)
				if key not in before:
					added_ids.append(key)
		if added_ids:
			self.save()
			self.emit("playlists", {"ids": added_ids})
			self._scan_new(added_ids)
		return {"added": added_ids, "errors": errors, "warnings": sorted(set(warnings))}

	def _scan_new(self, playlist_ids: list[str]) -> None:
		if self.downloads_running():
			return
		playlists = [playlist for playlist in (playlist_by_id(self.library, key) for key in playlist_ids) if playlist]
		if self.scan_running():
			self.scan_queue.extend(playlists)
			self.emit_job(force=True)
			return
		self._begin_scan(playlists)

	def import_csv_content(self, filename: str, content_base64: str, name: str | None = None) -> dict:
		try:
			content = base64.b64decode(content_base64 or "", validate=True)
		except (ValueError, TypeError) as exc:
			raise EngineError(400, "O arquivo da planilha chegou corrompido.") from exc
		if not content:
			raise EngineError(400, "A planilha está vazia.")
		stem = sanitize_name(pathlib.Path(str(filename or "planilha.csv")).stem) or "planilha"
		folder = settings_path().parent / "planilhas"
		folder.mkdir(parents=True, exist_ok=True)
		target = folder / f"{stem}.csv"
		target.write_bytes(content)
		return self.import_csv_path(str(target), name=name)

	def import_csv_path(self, path: str, *, name: str | None = None) -> dict:
		if self.downloads_running():
			raise EngineError(409, "Espere o download terminar antes de importar uma planilha.")
		try:
			playlist, created = import_csv_playlist(self.library, path)
		except Exception as exc:
			log(f"library CSV import failed path={path} error={exc}")
			raise EngineError(400, texts.scan_error_pt(str(exc))) from exc
		key = _key_of(playlist)
		if name and str(name).strip() and str(name).strip() != playlist.get("name"):
			try:
				rename_library_playlist(self.library, key, str(name).strip(), self.output_dir() or None)
			except (ValueError, OSError) as exc:
				log(f"library CSV rename failed id={key} error={exc}")
		self.invalidate_paths(key)
		self.save()
		log(f"library CSV imported path={path} created={created} tracks={len(playlist.get('tracks', []))}")
		self.emit("playlists", {"ids": [key]})
		return {"added": [key], "warnings": []}

	def rename_playlist(self, playlist_id: str, new_name: str) -> dict:
		playlist = self._playlist(playlist_id)
		if self.downloads_running():
			raise EngineError(409, "Espere o download terminar antes de renomear a playlist.")
		old_name = str(playlist.get("name") or "Playlist")
		clean = str(new_name or "").strip()
		if not clean:
			raise EngineError(400, "O nome da playlist não pode ficar vazio.")
		if clean == old_name:
			return self.playlist_summary(playlist_id)
		try:
			updated, folder = rename_library_playlist(self.library, playlist_id, clean, self.output_dir() or None)
			cfg = load_settings()
			m3u_output = str(cfg.get("m3u_output_dir") or "").strip()
			if m3u_output:
				playlist_output_dir = pathlib.Path(m3u_output)
				# Só o que existe de fato entra na lista (m3u_ready_tracks), como no fim de um download.
				probes = [dict(track, playlist=updated["name"]) for track in updated.get("tracks", []) if track.get("enabled", True)]
				playlist_tracks = [row for _name, row in m3u_ready_tracks(probes, self.output_dir(), self.fmt())] if self.output_dir() else []
				for suffix, setting, encoding in ((".m3u8", "write_m3u8", "utf-8"), (".m3u", "write_m3u_plain", "utf-8-sig")):
					old_file = playlist_output_dir / f"{sanitize_name(old_name)}{suffix}"
					if old_file.exists():
						old_file.unlink()
					if cfg.get(setting, setting == "write_m3u8"):
						write_m3u(pathlib.Path(self.output_dir()), updated["name"], playlist_tracks, self.fmt(), suffix=suffix, encoding=encoding, playlist_output_dir=playlist_output_dir)
		except ValueError as exc:
			raise EngineError(409, "Outra playlist da biblioteca já usa uma pasta com esse nome.") from exc
		except Exception as exc:
			log(f"library playlist rename failed id={playlist_id} old={old_name!r} new={clean!r} error={exc}")
			raise EngineError(500, "Não deu para renomear a playlist (a pasta pode estar em uso).") from exc
		self.invalidate_paths(_key_of(updated))
		self.save()
		log(f"library playlist renamed id={playlist_id} old={old_name!r} new={updated['name']!r} folder={folder}")
		summary = self.playlist_summary(_key_of(updated))
		self.emit("playlist", summary)
		return summary

	def remove_playlist(self, playlist_id: str, files: str = "keep") -> dict:
		"""Remove da biblioteca. Com `files=trash`, a pasta vai para a Lixeira do macOS; nunca é apagada."""
		playlist = self._playlist(playlist_id)
		if self.busy():
			raise EngineError(409, "Espere a tarefa atual terminar antes de remover a playlist.")
		if files not in ("keep", "trash"):
			raise EngineError(400, "Escolha se os arquivos ficam ou vão para a Lixeira.")
		name = str(playlist.get("name") or "Playlist")
		output = self.output_dir()
		trashed: str | None = None
		folder = pathlib.Path(output) / (sanitize_name(name) or "Playlist") if output else None
		if files == "trash" and folder is not None and folder.exists():
			shared = [
				other for other in self.library.get("playlists", [])
				if other is not playlist and (sanitize_name(str(other.get("name") or "Playlist")) or "Playlist") == folder.name
			]
			if shared:
				raise EngineError(
					409, "Esta playlist divide a pasta de downloads com outra playlist da biblioteca. "
					"Renomeie uma delas antes, para não levar músicas da outra junto.",
				)
			try:
				root = pathlib.Path(output).resolve()
				target = folder.resolve()
				if target.parent != root or target == root:
					raise ValueError("playlist folder outside the output folder")
				self.trash_mover(target)
				trashed = str(target)
				log(f"library playlist folder moved to trash playlist={name!r} path={target}")
			except (OSError, ValueError, TrashError) as exc:
				log(f"library playlist trash failed playlist={name!r} path={folder} error={exc}")
				raise EngineError(500, "Não deu para mandar a pasta para a Lixeira, então a playlist ficou.") from exc
		key = _key_of(playlist)
		self.library["playlists"] = [item for item in self.library.get("playlists", []) if item is not playlist]
		self.invalidate_paths(key)
		self.save()
		self.emit("playlists", {"ids": [key]})
		return {"removed": True, "trashed_folder": trashed}

	# --- músicas ---------------------------------------------------------------------

	def update_track(self, playlist_id: str, index: int, changes: dict) -> dict:
		playlist = self._playlist(playlist_id)
		track = self._track(playlist, index)
		key = _key_of(playlist)
		allowed = {"enabled", "title", "artists", "album", "volume_gain", "preferred_video_url", "preferred_video_label", "force_redownload"}
		unknown = set(changes) - allowed
		if unknown:
			raise EngineError(400, "Campo desconhecido na música.")
		if any(field in changes for field in ("title", "artists", "album")):
			self._edit_metadata(playlist, index, changes)
		if "enabled" in changes:
			track["enabled"] = bool(changes["enabled"])
		if "volume_gain" in changes:
			try:
				gain = max(-12, min(12, int(changes["volume_gain"])))
			except (TypeError, ValueError) as exc:
				raise EngineError(400, "O volume vai de -12 a +12 dB.") from exc
			if gain != int(track.get("audio_volume_gain", 0) or 0):
				track["audio_volume_gain"] = gain
				track["force_redownload"] = True
		if "preferred_video_url" in changes:
			value = str(changes.get("preferred_video_url") or "").strip()
			if value:
				try:
					video_id = parse_youtube_video_id(value)
				except YouTubeVideoUrlError as exc:
					raise EngineError(400, "Este link não é de um vídeo do YouTube ou do YouTube Music.") from exc
				info = self._video_info_cache.get(video_id) or {}
				label = str(changes.get("preferred_video_label") or "").strip()
				if not label and info.get("title"):
					label = info["title"] + (f" — {info['author']}" if info.get("author") else "")
				old = str(track.get("preferred_video_id") or "")
				track["preferred_video_id"] = video_id
				track["preferred_video_label"] = label or value
				track["preferred_selection_locked"] = True
				if old != video_id:
					track["force_redownload"] = True
			else:
				track["preferred_video_id"] = None
				track["preferred_video_label"] = None
				track["preferred_selection_locked"] = False
		if "force_redownload" in changes:
			track["force_redownload"] = bool(changes["force_redownload"])
		self.save()
		self.emit_playlist(key)
		view = self._track_view(playlist, index)
		self.emit("track", {"playlist_id": key, "track": view})
		return view

	def _edit_metadata(self, playlist: dict, index: int, changes: dict) -> None:
		if self.downloads_running():
			raise EngineError(409, "Espere o download terminar antes de editar os dados da música.")
		key = _key_of(playlist)
		track = playlist["tracks"][index]
		title = str(changes.get("title", track.get("title")) or "").strip()
		album = str(changes.get("album", track.get("album")) or "").strip()
		artists = str(changes.get("artists", track.get("artists")) or "").strip()
		if not title:
			raise EngineError(400, "O título da música não pode ficar vazio.")
		if not artists:
			raise EngineError(400, "O artista não pode ficar vazio.")
		output_root = pathlib.Path(self.output_dir())
		fmt = self.fmt()
		old_probe = dict(track, playlist=playlist.get("name") or "Playlist")
		old_path = library_track_path(old_probe, output_root, fmt) if self.output_dir() else None
		snapshot = {field: track.get(field) for field in ("title", "album", "artists", "custom_title", "custom_album", "custom_artists", "downloaded_path")}
		moved: tuple[pathlib.Path, pathlib.Path] | None = None

		def rollback() -> None:
			track.update(snapshot)
			if moved is not None and moved[1].exists() and not moved[0].exists():
				moved[1].rename(moved[0])

		try:
			edit_library_track(self.library, key, index, title, album)
			if artists != str(snapshot["artists"] or ""):
				track["artists"] = artists
				track["custom_artists"] = True
			new_probe = dict(track, playlist=playlist.get("name") or "Playlist")
			if old_path is not None and old_path.is_file():
				new_path = expected_track_path(new_probe, output_root, fmt)
				if old_path != new_path:
					if new_path.exists():
						raise FileExistsError(new_path.name)
					new_path.parent.mkdir(parents=True, exist_ok=True)
					old_path.rename(new_path)
					moved = (old_path, new_path)
				tag_file(new_path, new_probe, None)
				track["downloaded_path"] = str(new_path)
			cfg = load_settings()
			probes = [dict(item, playlist=playlist.get("name") or "Playlist") for item in playlist.get("tracks", []) if item.get("enabled", True)]
			playlist_tracks = [row for _name, row in m3u_ready_tracks(probes, output_root, fmt)] if self.output_dir() else []
			if self.output_dir() and cfg.get("write_m3u8", True):
				write_m3u(output_root, playlist.get("name") or "Playlist", playlist_tracks, fmt, suffix=".m3u8", encoding="utf-8", playlist_output_dir=cfg.get("m3u_output_dir"))
			if self.output_dir() and cfg.get("write_m3u_plain", False):
				write_m3u(output_root, playlist.get("name") or "Playlist", playlist_tracks, fmt, suffix=".m3u", encoding="utf-8-sig", playlist_output_dir=cfg.get("m3u_output_dir"))
		except FileExistsError as exc:
			rollback()
			raise EngineError(409, f"Já existe um arquivo com esse nome ({exc}).") from exc
		except EngineError:
			rollback()
			raise
		except Exception as exc:
			rollback()
			log(f"library track edit failed playlist={key} index={index} error={exc}")
			raise EngineError(500, "Não deu para atualizar o arquivo da música.") from exc
		self._refresh_track_path(playlist, index)

	def set_tracks_enabled(self, playlist_id: str, enabled: bool, *, indices: list[int] | None = None, all_tracks: bool = False) -> dict:
		playlist = self._playlist(playlist_id)
		tracks = playlist.get("tracks", [])
		targets = range(len(tracks)) if all_tracks else [int(index) for index in (indices or []) if 0 <= int(index) < len(tracks)]
		changed = 0
		for index in targets:
			if bool(tracks[index].get("enabled", True)) != bool(enabled):
				tracks[index]["enabled"] = bool(enabled)
				changed += 1
		if changed:
			self.save()
			self.emit_playlist(_key_of(playlist))
		return {"changed": changed}

	def accept_review(self, playlist_id: str, index: int) -> dict:
		playlist = self._playlist(playlist_id)
		track = self._track(playlist, index)
		track["low_confidence_review"] = False
		track["review_reason"] = None
		self.save()
		key = _key_of(playlist)
		self.emit_playlist(key)
		view = self._track_view(playlist, index)
		self.emit("track", {"playlist_id": key, "track": view})
		return view

	def fetch_alternatives(self, track: dict) -> dict:
		"""Busca no YouTube (fora da thread do Qt). `track` vem de `track_snapshot`."""
		from csvmusic.core.ytmusic_match import more_candidates
		try:
			options = more_candidates(track, exclude_ids=set(), source_mode="all")
		except Exception as exc:
			log(f"alternatives fetch failure: track='{track.get('artists', '')} — {track.get('title', '')}' error={exc}")
			raise EngineError(502, "Não deu para buscar outras versões agora. Tente de novo.") from exc
		result = []
		for option in options:
			album = option.get("album")
			if isinstance(album, dict):
				album = album.get("name") or album.get("title") or ""
			result.append({
				"videoId": option.get("videoId"),
				"title": option.get("title") or "",
				"author": option.get("author") or "",
				"source": "music" if option.get("source") == "music" else "videos",
				"duration_seconds": int(option.get("duration_seconds") or 0) or None,
				"album": str(album or "").strip() or None,
				"duration_mismatch": bool(option.get("duration_mismatch")),
				"version_markers": sorted(option.get("version_markers") or []),
				"score": round(float(option.get("score") or 0.0), 3),
			})
		return {"options": result}

	def fetch_video_info(self, url: str, track: dict | None, fetcher: Callable[[str], dict] | None = None) -> dict:
		"""Confere um link colado (fora da thread do Qt)."""
		from csvmusic.core.manual_match import choice_warnings, fetch_video_info
		try:
			video_id = parse_youtube_video_id(url)
		except YouTubeVideoUrlError as exc:
			raise EngineError(400, "Este link não é de um vídeo do YouTube ou do YouTube Music.") from exc
		try:
			info = (fetcher or fetch_video_info)(video_id)
		except Exception as exc:
			log(f"video info failure: video_id={video_id} error={exc}")
			return {
				"video_id": video_id, "info": None, "description": None,
				"warnings": ["Não deu para conferir este vídeo agora. Você ainda pode usar o link."],
			}
		self._video_info_cache[video_id] = info
		warnings = [texts.manual_warning_pt(item) for item in choice_warnings(track or {}, info)] if track else []
		seconds = int(info.get("duration_seconds") or 0)
		parts = [f"{info.get('title') or video_id} — {info['author']}" if info.get("author") else str(info.get("title") or video_id)]
		if seconds:
			parts.append(f"{seconds // 60}:{seconds % 60:02d}")
		parts.append(texts.video_kind_pt(info.get("kind")))
		return {
			"video_id": video_id,
			"info": {
				"title": info.get("title") or "", "author": info.get("author") or "", "duration_seconds": seconds or None,
				"kind": info.get("kind") or "unknown", "playable": bool(info.get("playable", True)),
				"age_restricted": bool(info.get("age_restricted")),
			},
			"description": " · ".join(parts),
			"warnings": warnings,
		}

	def remember_video_info(self, video_id: str, info: dict) -> None:
		self._video_info_cache[video_id] = info

	# --- análise ---------------------------------------------------------------------

	def scan_running(self) -> bool:
		return self._scan_running

	def start_scan(self, playlist_ids: list[str] | None = None, scope: str | None = None) -> dict:
		if self.downloads_running():
			# A análise muda a ordem das músicas; o download em andamento gravaria nos lugares errados.
			raise EngineError(409, "Espere o download terminar, ou pare, antes de analisar playlists.")
		if self.scan_running():
			raise EngineError(409, "Já tem uma análise em andamento.")
		playlists = list(self.library.get("playlists", []))
		if scope == "unscanned":
			playlists = [playlist for playlist in playlists if not playlist.get("last_scanned_at")]
			if not playlists:
				raise EngineError(409, "Todas as playlists já foram analisadas.")
		elif scope != "all":
			wanted = list(playlist_ids or [])
			playlists = [playlist for playlist in (playlist_by_id(self.library, key) for key in wanted) if playlist]
		if not playlists:
			raise EngineError(400, "Escolha ou adicione pelo menos uma playlist.")
		self._begin_scan(playlists)
		return self.job()

	def _begin_scan(self, playlists: list[dict]) -> None:
		if not playlists:
			return
		self.scan_queue = list(playlists)
		self.scan_results = []
		self.scan_cancelled = False
		self._scan_running = True
		log(f"library scan started playlists={len(playlists)}")
		self._scan_next()

	def cancel_scan(self) -> dict:
		if not self.scan_running():
			return self.job()
		self.scan_cancelled = True
		self.scan_queue.clear()
		log("library scan cancelled by user")
		if self._scan_timer is not None and self._scan_timer.isActive():
			self._scan_timer.stop()
			self._scan_finish_round()
			return self.job()
		if self.scraper is not None and getattr(self.scraper, "running", False):
			self.scraper._finish("Library scan cancelled by user.")
		self.emit_job(force=True)
		return self.job()

	def _scan_next(self) -> None:
		if not self.scan_queue:
			self._scan_finish_round()
			return
		playlist = self.scan_queue.pop(0)
		self.scan_current = playlist
		self.scan_progress = (0, playlist.get("reported_total"))
		self.emit_job(force=True)
		is_spotify_album = playlist.get("platform") == "spotify" and playlist.get("source_type") == "album"
		if playlist.get("platform") in ("youtube_music", "youtube", "apple_music", "deezer", "amazon_music", "csv") or is_spotify_album:
			platform = "spotify_album" if is_spotify_album else str(playlist["platform"])
			worker = self.direct_scan_worker_factory(
				playlist.get("csv_path") or playlist["url"], platform, self, source_id=str(playlist.get("id") or ""),
			)
			self.direct_worker = worker
			worker.finished_scan.connect(self._scan_finished)
			worker.start()
			return
		if self.scraper is None:
			self.scraper = self.host.create_spotify_reader()
			if self.scraper is None:
				self._scan_finished({"error": "Spotify reader unavailable", "id": playlist.get("id")})
				return
			self.scraper.scrape_finished.connect(self._scan_finished)
			self.scraper.scrape_progress.connect(self._scan_progress_changed)
			log("library scan created reusable Spotify browser")
		else:
			log("library scan reusing Spotify browser for next playlist")
		self.scraper.url_input.setText(playlist["url"])
		self.host.show_spotify_reader(self.scraper)
		self.scraper.start_scrape()

	def _scan_progress_changed(self, captured: int, reported_total: int, _name: str = "") -> None:
		self.scan_progress = (int(captured), int(reported_total) if reported_total else None)
		self.emit_job()

	def _scan_finished(self, result: object) -> None:
		data = dict(result or {})
		playlist = self.scan_current or {}
		current_key = _key_of(playlist) if playlist else ""
		name = views.playlist_name(playlist) if playlist else "Playlist"
		playlist_id = str(data.get("id") or "")
		entry: dict | None = None
		if data.get("error"):
			kind = data.get("error_kind")
			if kind == "private" and playlist_id and not self.scan_cancelled:
				if mark_playlist_access_error(self.library, current_key or playlist_id, "private", str(data["error"])):
					self.save()
				log(f"library playlist scan private id={playlist_id}")
			log(f"library playlist scan failed id={playlist_id or current_key} error={data['error']}")
			entry = {
				"playlist_id": current_key, "name": name, "captured": 0, "reported_total": playlist.get("reported_total"),
				"status": "private" if kind == "private" else "error",
				"message": texts.scan_error_pt(str(data["error"]), "private" if kind == "private" else None),
			}
		elif not self.scan_cancelled and playlist_id:
			# A fonte respondeu: a playlist voltou a ser acessível, mesmo vazia.
			if clear_playlist_access_error(self.library, current_key or playlist_id):
				self.save()
				log(f"library playlist access restored id={playlist_id} tracks={len(data.get('tracks') or [])}")
		if not self.scan_cancelled and playlist_id and data.get("tracks") and not data.get("error"):
			warning = None if data.get("complete") else str(data.get("message") or "incomplete")
			target_id = current_key or (f"{data.get('platform')}:{playlist_id}" if data.get("platform") else playlist_id)
			merged = merge_playlist_scan(
				self.library, target_id, str(data.get("name") or "Spotify Playlist"), list(data.get("tracks") or []),
				reported_total=data.get("reported_total"), warning=warning, cover_url=data.get("cover_url"),
				complete=bool(data.get("complete")),
			)
			self.invalidate_paths(_key_of(merged))
			self.save()
			diff = dict(merged.get("last_diff") or {})
			captured = len(merged.get("tracks") or []) - int(diff.get("kept_from_incomplete_scan", 0) or 0)
			entry = {
				"playlist_id": _key_of(merged), "name": str(merged.get("name") or name), "captured": captured,
				"reported_total": data.get("reported_total"), "status": "incomplete" if warning else "ok",
				"message": texts.scan_warning_pt(warning) if warning else "Análise completa.",
				"diff": {
					"added": int(diff.get("added", 0) or 0), "removed": int(diff.get("removed", 0) or 0),
					"unchanged": int(diff.get("unchanged", 0) or 0), "kept": int(diff.get("kept_from_incomplete_scan", 0) or 0),
				},
			}
			log(f"library playlist scan merged id={playlist_id} tracks={len(data.get('tracks') or [])} complete={bool(data.get('complete'))}")
		elif entry is None and not self.scan_cancelled:
			entry = {
				"playlist_id": current_key, "name": name, "captured": 0, "reported_total": data.get("reported_total"),
				"status": "ok", "message": "A playlist está vazia.",
			}
		if entry is not None and not self.scan_cancelled:
			self.scan_results.append(entry)
		if self.scraper is not None and not data.get("direct"):
			# O mesmo navegador serve para a próxima playlist do Spotify; apagá-lo aqui pode travar o Qt.
			self.host.hide_spotify_reader(self.scraper)
		if self.direct_worker is not None:
			self.direct_worker.deleteLater()
			self.direct_worker = None
		if current_key:
			self.emit_playlist(current_key)
		self.scan_current = None
		if self.scan_queue and not self.scan_cancelled:
			delay_ms = random.randint(900, 1400)
			log(f"library scan inter_playlist_delay_ms={delay_ms} remaining={len(self.scan_queue)}")
			self._scan_timer = QTimer(self)
			self._scan_timer.setSingleShot(True)
			self._scan_timer.timeout.connect(self._scan_next)
			self._scan_timer.start(delay_ms)
			self.emit_job(force=True)
		else:
			self._scan_finish_round()

	def _scan_finish_round(self) -> None:
		was_running = self._scan_running
		self._scan_running = False
		self.scan_current = None
		self.scan_queue = []
		if was_running:
			if not self.scan_cancelled:
				self.emit("scan_done", {"results": list(self.scan_results)})
			log(f"library scan finished cancelled={self.scan_cancelled} results={len(self.scan_results)}")
		self.emit_job(force=True)

	# --- download --------------------------------------------------------------------

	def downloads_running(self) -> bool:
		# O worker só sai daqui no fim (sinal de pronto), então "existe" quer dizer "em andamento".
		return self.download_worker is not None or self.single_worker is not None

	@staticmethod
	def _ffmpeg_supports_mp3() -> bool:
		from csvmusic.core.paths import ffmpeg_path
		from csvmusic.core.preflight import ffmpeg_supports_mp3
		try:
			return ffmpeg_supports_mp3(ffmpeg_path())
		except Exception:
			return False

	def start_download(
		self, playlist_ids: list[str] | None = None, *, missing_only: bool = True,
		targets: list[tuple[str, int]] | None = None, confirm_risk: bool = False,
	) -> dict:
		if self.downloads_running():
			raise EngineError(409, "Já tem um download em andamento.")
		if self.scan_running():
			raise EngineError(409, "Espere a análise terminar antes de baixar.")
		only_targets: set[tuple[str, int]] | None = None
		if targets:
			only_targets = set()
			for target in targets:
				playlist = playlist_by_id(self.library, str(target[0]))
				if playlist is not None:
					only_targets.add((_key_of(playlist), int(target[1])))
			selected_keys = {key for key, _index in only_targets}
			missing_only = False
		else:
			wanted = list(playlist_ids or [])
			selected_keys = {_key_of(playlist) for playlist in (playlist_by_id(self.library, key) for key in wanted) if playlist}
		if not selected_keys:
			raise EngineError(400, "Escolha a playlist que você quer baixar.")
		output = self.output_dir()
		if not output:
			raise EngineError(409, "Escolha a pasta das músicas em Ajustes › Downloads.")
		fmt = self.fmt()
		if fmt == "mp3" and not self.mp3_check():
			raise EngineError(409, "O FFmpeg escolhido não grava MP3 (falta o libmp3lame). Escolha outro formato ou outro FFmpeg.")
		cfg = load_settings()
		audio = audio_processing_settings(cfg)
		tracks, all_playlist_tracks = self.build_download_queue(selected_keys, cfg, missing_only=missing_only, only_targets=only_targets)
		if not tracks:
			raise EngineError(409, "Não tem nada faltando para baixar nessa seleção.")
		for track in tracks:
			track["library_path"] = str(self.library_path)
		use_cookies = bool(cfg.get("use_cookies", False))
		policy = youtube_batch_mitigation(len(tracks), using_cookies=bool(use_cookies and (cfg.get("cookies_browser") or cfg.get("cookies_file"))))
		if youtube_risk_acknowledgement(policy) and not confirm_risk:
			log(f"library download waiting for risk acknowledgement tracks={len(tracks)}")
			raise EngineError(409, texts.risk_acknowledgement_pt(len(tracks)), needs_confirmation="youtube_risk", tracks=len(tracks))
		self.download_targets = {
			row: (str(track.get("library_playlist_id") or ""), int(track.get("library_track_index", -1)))
			for row, track in enumerate(tracks)
		}
		self._download_tracks = tracks
		self.download_playlist_ids = sorted({key for key, _index in self.download_targets.values()})
		self.download_total = len(tracks)
		self.download_processed = 0
		self.download_started_at = time.monotonic()
		self.download_stopping = False
		self.download_m3u_tracks = all_playlist_tracks
		self.download_m3u_pending = set()
		self.download_m3u_count = 0
		self.age_restricted_pending = set()
		for target in self.download_targets.values():
			self.runtime_states[target] = "queued"
		self._set_current(0, "matching")
		names = ", ".join(views.playlist_name(playlist) for playlist in (playlist_by_id(self.library, key) for key in self.download_playlist_ids) if playlist)
		self.session_log("note", f"Começando: {names} · {len(tracks)} músicas")
		self.session_log("note", f"Formato {fmt.upper()} · pasta {output}")
		if policy.active:
			self.session_log("warning", texts.warning_pt(policy.warning or ""))
		worker = self.pipeline_worker_factory(
			"", output, None, fmt,
			bool(cfg.get("write_m3u8", True)), bool(cfg.get("write_m3u_plain", False)),
			bool(cfg.get("embed_art", True)), cfg.get("yt_dlp_path"), cfg.get("ffmpeg_path"),
			cfg.get("cookies_browser") if use_cookies else None,
			cfg.get("cookies_file") if use_cookies else None,
			audio_processing=audio, mp3_quality=int(cfg.get("mp3_quality", 0) or 0),
			legacy_options=legacy_options(cfg), force_download=bool(cfg.get("force_download_mode", False)),
			tracks_override=tracks, m3u_tracks_override=all_playlist_tracks,
			m3u_output_dir=cfg.get("m3u_output_dir"),
			row_indices=list(range(len(tracks))), parent=self,
		)
		self.download_worker = worker
		worker.sig_log.connect(self._download_log)
		worker.sig_progress.connect(self._download_progress)
		worker.sig_row_status.connect(self._download_row_status)
		worker.sig_warning.connect(self._download_warning)
		worker.sig_track_result.connect(self._download_track_result)
		worker.sig_done.connect(self._download_done)
		log(f"library download started tracks={len(tracks)} output={output} format={fmt}")
		for key in self.download_playlist_ids:
			self.emit_playlist(key)
		for target in self.download_targets.values():
			self.emit_track(*target)
		worker.start()
		self.emit_job(force=True)
		return self.job()

	def build_download_queue(
		self, selected_keys: set[str], cfg: dict, *, missing_only: bool, only_targets: set[tuple[str, int]] | None = None,
	) -> tuple[list[dict], list[dict]]:
		"""Ponto único que monta a fila do download: (músicas a baixar, todas as ativas para o M3U).

		Qualquer regra nova da fila (por exemplo, tirar músicas repetidas) entra aqui, depois de juntar.
		"""
		output_path = pathlib.Path(self.output_dir())
		fmt = self.fmt()
		audio = audio_processing_settings(cfg)
		signature = audio_processing_signature(audio)
		prefix_numbers = bool(cfg.get("prefix_track_numbers", False))
		selected_playlists = [playlist for playlist in self.library.get("playlists", []) if _key_of(playlist) in selected_keys]
		all_playlist_tracks = enabled_tracks(self.library, selected_keys)
		sizes = {
			_key_of(playlist): len([track for track in playlist.get("tracks", []) if track.get("enabled", True)])
			for playlist in selected_playlists
		}
		listing_cache: dict = {}
		for track in all_playlist_tracks:
			existing = library_track_path(track, output_path, fmt, listing_cache=listing_cache, playlist_tracks=all_playlist_tracks)
			if existing.is_file():
				track["downloaded_path"] = str(existing)
			track["_previous_audio_processing_signature"] = str(track.get("audio_processing_signature") or "")
			track["_previous_prefix_numbered"] = bool(track.get("filename_prefix_number")) or bool(existing.is_file() and re.match(r"^\d+- ", existing.name))
			position = int(track.get("library_track_index", 0)) + 1
			key = str(track.get("library_playlist_id") or "")
			track["filename_prefix_number"] = position if prefix_numbers else None
			track["filename_prefix_width"] = max(2, len(str(max(1, sizes.get(key, position))))) if prefix_numbers else None
			track["audio_processing_signature"] = signature
		tracks = pending_download_tracks(
			list(all_playlist_tracks), output_path, fmt, audio_signature=signature,
			audio_enabled=bool(audio), prefix_numbers=prefix_numbers, missing_only=missing_only,
		)
		if only_targets is not None:
			tracks = [
				track for track in tracks
				if (str(track.get("library_playlist_id") or ""), int(track.get("library_track_index", -1))) in only_targets
			]
		return tracks, all_playlist_tracks

	def _set_current(self, row: int, phase: str) -> None:
		target = self.download_targets.get(row)
		if target is None:
			self.download_current = None
			return
		playlist = playlist_by_id(self.library, target[0])
		track = playlist["tracks"][target[1]] if playlist and 0 <= target[1] < len(playlist.get("tracks", [])) else {}
		self.download_current = {
			"row": row, "playlist_id": target[0], "index": target[1],
			"title": str(track.get("title") or ""), "artists": str(track.get("artists") or ""),
			"cover_url": track.get("cover_url") or None, "phase": phase, "percent": None,
		}
		if phase in ("matching", "downloading", "tagging"):
			if self.runtime_states.get(target) != phase:
				self.runtime_states[target] = phase
				self.emit_track(*target)

	def _download_log(self, message: str) -> None:
		level = "warning" if "[warn]" in str(message).casefold() else "note"
		self.session_log(level, texts.log_line_pt(message))

	def _download_progress(self, processed: int, total: int) -> None:
		self.download_processed = int(processed)
		self.download_total = int(total) or self.download_total
		if self.download_current is None or self.download_current.get("row", -1) < processed:
			self._set_current(int(processed), "matching")
		self.emit_job()

	def _download_row_status(self, row: int, status: str) -> None:
		phase = texts.status_phase(status)
		target = self.download_targets.get(row)
		number = row + 1
		self.session_log("error" if phase == "failed" else "note", f"Música {number}: {texts.status_line_pt(status)}")
		if phase in ("matching", "downloading", "tagging"):
			self._set_current(row, phase)
		elif target is not None and phase == "stopped":
			self.runtime_states.pop(target, None)
			self.emit_track(*target)
		self.emit_job()

	def _download_warning(self, message: str) -> None:
		text = texts.warning_pt(message)
		self.session_log("warning", text)
		self.warn(text)

	def _download_track_result(self, row: int, payload: dict) -> None:
		track = payload.get("track") or {}
		if payload.get("error"):
			log(f"library download error row={row} title={track.get('title')!r} error={payload['error']}")
			summary = texts.error_summary_pt(payload.get("error"), payload.get("failure_kind"))[0]
			self.session_log("error", f"{track.get('artists') or 'Artista desconhecido'} — {track.get('title') or 'Música'}: {summary}")
		if track.get("library_playlist_id") and (payload.get("downloaded") or payload.get("error") or payload.get("skipped")):
			self._apply_payload(str(track["library_playlist_id"]), track, payload, self.download_targets.get(row))
		if payload.get("downloaded"):
			self.download_m3u_pending.add(str(payload.get("playlist_name") or track.get("playlist") or "Playlist"))
			self.download_m3u_count += 1
			if self.download_m3u_count >= M3U_WRITE_EVERY_TRACKS:
				self.write_partial_m3us()

	def write_partial_m3us(self) -> None:
		"""Mantém a lista da playlist usável durante um lote longo; o worker ainda grava a final."""
		names = set(self.download_m3u_pending)
		self.download_m3u_pending.clear()
		self.download_m3u_count = 0
		if not names or not self.download_m3u_tracks:
			return
		cfg = load_settings()
		try:
			written = write_library_m3us(
				self.download_m3u_tracks, self.output_dir(), self.fmt(),
				write_m3u8=bool(cfg.get("write_m3u8", True)), write_m3u_plain=bool(cfg.get("write_m3u_plain", False)),
				m3u_output_dir=cfg.get("m3u_output_dir") or None, playlist_names=names,
			)
		except OSError as exc:
			log(f"library partial m3u failed playlists={sorted(names)} error={exc}")
			return
		for path in written:
			self.session_log("note", f"Lista da playlist atualizada: {path}")

	def _apply_payload(self, playlist_id: str, track: dict, payload: dict, target: tuple[str, int] | None) -> None:
		"""Grava um resultado na memória e avisa só aquela música e aquela playlist."""
		playlist = playlist_by_id(self.library, playlist_id)
		stored = find_library_track(playlist, track) if playlist else None
		if playlist is None or stored is None:
			log(f"library download result has no matching song playlist={playlist_id} title={track.get('title')!r}")
			return
		apply_library_download_result(
			self.library, playlist_id, track,
			downloaded=bool(payload.get("downloaded")), error=payload.get("error"), match=payload.get("match"),
			low_confidence=bool(payload.get("low_confidence")), confidence=payload.get("confidence"),
			skipped=bool(payload.get("skipped")),
			skip_reason=(payload.get("skip_reason") or describe_skip(payload.get("options"), payload.get("confidence"))) if payload.get("skipped") else None,
			failure_kind=payload.get("failure_kind"),
			downloaded_duration_ms=payload.get("downloaded_duration_ms"),
			duration_needs_review=bool(payload.get("duration_needs_review")),
		)
		index = next(position for position, candidate in enumerate(playlist["tracks"]) if candidate is stored)
		key = _key_of(playlist)
		self._refresh_track_path(playlist, index)
		self.runtime_states.pop((key, index), None)
		if target:
			self.runtime_states.pop(target, None)
		self.mark_dirty()
		self.emit_track(key, index)
		self.emit_playlist(key)

	def _download_done(self, message: str, done: list, skipped: list, failed: list) -> None:
		log(f"library download finished downloaded={len(done)} skipped={len(skipped)} failed={len(failed)} message={message[:200]!r}")
		stopped = bool(self.download_stopping) or str(message).startswith("Stopped (")
		for target in list(self.download_targets.values()):
			if target in self.runtime_states:
				self.runtime_states.pop(target, None)
				self.emit_track(*target)
		playlist_ids = list(self.download_playlist_ids)
		worker = self.download_worker
		self.download_worker = None
		if worker is not None:
			worker.deleteLater()
		self.download_targets = {}
		self.download_current = None
		self.download_m3u_tracks = []
		self.download_m3u_pending = set()
		self.download_m3u_count = 0
		self.download_stopping = False
		self.flush_library()
		self.save()
		self.age_restricted_pending = age_restricted_targets(failed)
		count = len(self.age_restricted_pending)
		cfg = load_settings()
		age_action = None
		if count:
			has_session = bool(str(cfg.get("cookies_file") or "").strip())
			age_action = "enable_session" if has_session and not cfg.get("use_cookies") else "sign_in"
		if message.startswith("Fatal error"):
			summary = "O download parou por um erro inesperado. Veja o registro."
		elif message.startswith("Stopped because YouTube asked to sign in"):
			summary = "O download parou: o YouTube está pedindo para entrar na sua conta. Entre e baixe de novo."
		elif message.startswith("Stopped because search is unavailable"):
			summary = "O download parou porque a busca no YouTube Music não está respondendo. Tente mais tarde."
		elif stopped:
			summary = "Download parado. O que já baixou ficou salvo."
		else:
			summary = "Download terminado."
		self.session_log("note", f"Fim: {len(done)} baixadas, {len(skipped)} puladas, {len(failed)} com erro")
		for key in playlist_ids:
			self.emit_playlist(key)
		self.emit("download_done", {
			"done": len(done), "skipped": len(skipped), "failed": len(failed), "age_restricted": count,
			"age_action": age_action, "stopped": stopped, "message": summary,
		})
		self.emit_job(force=True)

	def stop_download(self) -> dict:
		if self.download_worker is not None and self.download_worker.isRunning():
			self.download_stopping = True
			self.download_worker.stop()
			self.session_log("note", "Parando depois da etapa atual…")
		self.emit_job(force=True)
		return self.job()

	def download_now(self, playlist_id: str, index: int, video_id: str) -> dict:
		"""Baixa só esta música com o vídeo escolhido (e guarda a escolha)."""
		if self.downloads_running():
			raise EngineError(409, "Espere o download atual terminar.")
		if self.scan_running():
			raise EngineError(409, "Espere a análise terminar antes de baixar.")
		playlist = self._playlist(playlist_id)
		stored = self._track(playlist, index)
		video_id = str(video_id or "").strip()
		if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
			raise EngineError(400, "Vídeo do YouTube inválido.")
		output = self.output_dir()
		if not output:
			raise EngineError(409, "Escolha a pasta das músicas em Ajustes › Downloads.")
		key = _key_of(playlist)
		info = self._video_info_cache.get(video_id) or {}
		label = info.get("title") and (info["title"] + (f" — {info['author']}" if info.get("author") else ""))
		if str(stored.get("preferred_video_id") or "") != video_id:
			stored["preferred_video_id"] = video_id
			stored["preferred_video_label"] = label or f"https://music.youtube.com/watch?v={video_id}"
			stored["preferred_selection_locked"] = True
			self.mark_dirty()
		track = dict(stored)
		track["playlist"] = playlist.get("name") or "Playlist"
		track["library_playlist_id"] = key
		track["library_track_index"] = index
		title = str(info.get("title") or track.get("title") or "")
		match = {"videoId": video_id, "title": title, "author": info.get("author") or track.get("artists") or ""}
		cfg = load_settings()
		audio = audio_processing_settings(cfg)
		track["audio_processing_signature"] = audio_processing_signature(audio)
		if cfg.get("prefix_track_numbers", False):
			track["filename_prefix_number"] = index + 1
			track["filename_prefix_width"] = max(2, len(str(max(1, len(playlist.get("tracks", []))))))
		else:
			track["filename_prefix_number"] = None
			track["filename_prefix_width"] = None
		gain = int(track.get("audio_volume_gain", 0) or 0)
		if gain:
			audio["enabled"] = True
			audio["volume_gain"] = int(audio.get("volume_gain", 0) or 0) + gain
		use_cookies = bool(cfg.get("use_cookies", False))
		worker = self.single_worker_factory(
			index, track, match, output, self.fmt(), bool(cfg.get("embed_art", True)),
			cfg.get("yt_dlp_path"), cfg.get("ffmpeg_path"),
			cfg.get("cookies_browser") if use_cookies else None,
			cfg.get("cookies_file") if use_cookies else None,
			audio_processing=audio, mp3_quality=int(cfg.get("mp3_quality", 0) or 0),
			legacy_options=legacy_options(cfg), force_download=True, parent=self,
		)
		target = (key, index)
		self.single_worker = worker
		self.download_targets = {0: target}
		self.download_playlist_ids = [key]
		self.download_total = 1
		self.download_processed = 0
		self.download_started_at = time.monotonic()
		self.runtime_states[target] = "downloading"
		self._set_current(0, "downloading")
		worker.sig_status.connect(lambda _row, status: self._single_status(status))
		worker.sig_finished.connect(lambda _row, payload: self._single_finished(target, payload))
		self.session_log("note", f"Baixando só esta música: {track.get('artists')} — {track.get('title')}")
		self.emit_track(key, index)
		worker.start()
		self.emit_job(force=True)
		return self.job()

	def _single_status(self, status: str) -> None:
		phase = texts.status_phase(status)
		self.session_log("error" if phase == "failed" else "note", texts.status_line_pt(status))
		if phase in ("downloading", "tagging"):
			self._set_current(0, phase)
		self.emit_job()

	def _single_finished(self, target: tuple[str, int], payload: dict) -> None:
		track = payload.get("track") or {}
		self._apply_payload(target[0], track, payload, target)
		self.runtime_states.pop(target, None)
		worker = self.single_worker
		self.single_worker = None
		if worker is not None:
			worker.deleteLater()
		self.download_targets = {}
		self.download_current = None
		self.download_processed = 1
		self.flush_library()
		ok = bool(payload.get("downloaded"))
		failed = [] if ok else [{"track": track, "error": payload.get("error")}]
		self.age_restricted_pending = age_restricted_targets(failed)
		summary = "Música baixada." if ok else texts.error_summary_pt(payload.get("error"))[0]
		self.emit("download_done", {
			"done": 1 if ok else 0, "skipped": 0, "failed": 0 if ok else 1,
			"age_restricted": len(self.age_restricted_pending), "age_action": "sign_in" if self.age_restricted_pending else None,
			"stopped": False, "message": summary,
		})
		self.emit_job(force=True)

	def job(self) -> dict:
		if self.scan_running():
			playlist = self.scan_current or {}
			captured, reported = self.scan_progress
			return {
				"kind": "scan", "playlist_id": _key_of(playlist) if playlist else None,
				"name": views.playlist_name(playlist) if playlist else None,
				"captured": captured, "reported_total": reported,
				"queue_left": len(self.scan_queue), "cancelling": bool(self.scan_cancelled),
			}
		if self.downloads_running():
			eta = None
			if self.download_processed > 0 and self.download_total > self.download_processed:
				elapsed = time.monotonic() - self.download_started_at
				remaining = elapsed / self.download_processed * (self.download_total - self.download_processed)
				eta = (_now_local() + datetime.timedelta(seconds=remaining)).isoformat(timespec="seconds")
			current = dict(self.download_current) if self.download_current else None
			if current:
				current.pop("row", None)
			return {
				"kind": "download", "playlist_ids": list(self.download_playlist_ids),
				"processed": self.download_processed, "total": self.download_total, "eta_at": eta,
				"current": current, "stopping": bool(self.download_stopping),
				"single": self.single_worker is not None,
			}
		return {"kind": None}

	# --- restrição de idade -----------------------------------------------------------

	def resolve_age_restricted(self) -> dict:
		cfg = load_settings()
		cookie_path = str(cfg.get("cookies_file") or "").strip()
		if cookie_path and not cfg.get("use_cookies"):
			# Já existe uma sessão salva, só desligada: liga em vez de pedir para entrar de novo.
			save_settings({"use_cookies": True})
			log("library age-restricted: enabled the saved YouTube session")
			self._test_session(cookie_path, "age_retry")
			return {"started": True, "method": "enable_session"}
		QTimer.singleShot(0, lambda: self._sign_in_now("popup", "age_retry"))
		return {"started": True, "method": "sign_in"}

	def retry_age_restricted(self, confirm_risk: bool = True) -> dict:
		targets = sorted(self.age_restricted_pending)
		if not targets:
			raise EngineError(409, "Não tem música com restrição de idade para baixar de novo.")
		return self.start_download(targets=targets, confirm_risk=confirm_risk)

	# --- conta do YouTube ------------------------------------------------------------

	def account(self, cfg: dict | None = None) -> dict:
		cfg = cfg if cfg is not None else load_settings()
		connected = bool(str(cfg.get("cookies_file") or "").strip()) and bool(self.account_ok if self.account_ok is not None else cfg.get("cookies_test_ok"))
		return {"connected": connected, "use_cookies": bool(cfg.get("use_cookies", False)), "checked_at": self.account_checked_at}

	def start_session_check(self) -> None:
		"""Na abertura: confere a sessão salva, se houver."""
		cfg = load_settings()
		path = str(cfg.get("cookies_file") or "")
		if cfg.get("use_cookies") and path:
			self._test_session(path, "startup")

	def sign_in(self, method: str) -> dict:
		if method not in ("popup", "firefox"):
			raise EngineError(400, "Forma de entrar desconhecida.")
		QTimer.singleShot(0, lambda: self._sign_in_now(method, "sign_in"))
		return {"started": True}

	def _sign_in_now(self, method: str, purpose: str) -> None:
		try:
			cookie_path = self.host.youtube_sign_in(method)
		except Exception as exc:
			log(f"youtube sign-in failed method={method} error={exc}")
			cookie_path = None
		if not cookie_path:
			self.emit("account", dict(self.account(), ok=False, message="Entrada no YouTube cancelada."))
			return
		save_settings({"cookies_file": str(cookie_path), "use_cookies": True, "cookies_browser": None})
		log(f"youtube signed in method={method} purpose={purpose}")
		self._test_session(str(cookie_path), purpose)

	def test_account(self) -> dict:
		path = str(load_settings().get("cookies_file") or "").strip()
		if not path:
			self.emit("account", dict(self.account(), ok=False, message="Entre na conta ou escolha um arquivo de cookies primeiro."))
			return {"started": False}
		self._test_session(path, "test")
		return {"started": True}

	def sign_out(self) -> dict:
		# Esquece a referência; não apaga o arquivo de cookies que o usuário trouxe.
		save_settings({"use_cookies": False, "cookies_file": None, "cookies_browser": None, "cookies_test_ok": False})
		self.account_ok = False
		self.account_checked_at = None
		data = dict(self.account(), ok=True, message="Conta do YouTube desconectada do CSVMusic. O arquivo de cookies não foi apagado.")
		self.emit("account", data)
		return data

	def _test_session(self, path: str, purpose: str) -> None:
		if self.session_worker is not None:
			return
		worker = self.session_worker_factory(path, self)
		self.session_worker = worker
		self._session_purpose = purpose
		worker.sig_done.connect(lambda ok, message, checked=path: self._session_result(checked, bool(ok), str(message)))
		worker.finished.connect(self._session_worker_finished)
		worker.start()

	def _session_worker_finished(self) -> None:
		worker = self.session_worker
		self.session_worker = None
		if worker is not None:
			worker.deleteLater()

	def _session_result(self, path: str, ok: bool, message: str) -> None:
		cfg = load_settings()
		if cfg.get("cookies_file") != path:
			return
		save_settings({"cookies_test_ok": ok})
		self.account_ok = ok
		self.account_checked_at = _now_local().isoformat(timespec="seconds")
		text = texts.session_message_pt(message, ok)
		self.emit("account", dict(self.account(), ok=ok, message=text))
		if self._session_purpose == "age_retry":
			if ok and self.age_restricted_pending:
				self.emit("age_retry_ready", {"targets": len(self.age_restricted_pending)})
			elif not ok:
				self.warn(text)

	# --- configurações ---------------------------------------------------------------

	def settings(self) -> dict:
		cfg = load_settings()
		result = {
			"output_dir": self.output_dir(),
			"format": self.fmt(),
			"mp3_quality": max(0, min(10, int(cfg.get("mp3_quality", 0) or 0))),
			"legacy_mp3_mode": str(cfg.get("legacy_mp3_mode") or "vbr"),
			"cookies_browser": cfg.get("cookies_browser") or None,
			"theme": cfg.get("theme") if cfg.get("theme") in THEMES else "system",
			"web_port": int(cfg.get("web_port") or DEFAULT_WEB_PORT),
		}
		for key, default in _BOOL_SETTINGS.items():
			result[key] = bool(cfg.get(key, default))
		for key in _PATH_SETTINGS:
			result[key] = cfg.get(key) or None
		for band in EQ_BANDS:
			result[f"eq_{band}_gain"] = int(cfg.get(f"eq_{band}_gain", 0) or 0)
		return result

	def update_settings(self, changes: dict) -> dict:
		changes = dict(changes or {})
		updates: dict[str, Any] = {}
		library_changed = False
		for key, value in changes.items():
			if key == "output_dir":
				text = str(value or "").strip()
				if not text:
					raise EngineError(400, "Escolha a pasta das músicas.")
				if text != self.output_dir():
					self.library["output_dir"] = text
					library_changed = True
			elif key == "format":
				if value not in SUPPORTED_FORMATS:
					raise EngineError(400, "Formato de áudio desconhecido.")
				if value != self.fmt():
					self.library["format"] = value
					library_changed = True
			elif key == "mp3_quality":
				updates[key] = self._int_in(value, 0, 10, "A qualidade do MP3 vai de 0 a 10.")
			elif key == "legacy_mp3_mode":
				if value not in LEGACY_MP3_MODES:
					raise EngineError(400, "Modo de MP3 desconhecido.")
				updates[key] = value
			elif key in _BOOL_SETTINGS:
				if not isinstance(value, bool):
					raise EngineError(400, "Valor inválido nos ajustes.")
				updates[key] = value
			elif key in _PATH_SETTINGS or key == "cookies_browser":
				if value is not None and not isinstance(value, str):
					raise EngineError(400, "Valor inválido nos ajustes.")
				updates[key] = (value or "").strip() or None
			elif re.fullmatch(r"eq_(volume|bass|treble)_gain", key):
				updates[key] = self._int_in(value, -12, 12, "O equalizador vai de -12 a +12 dB.")
			elif key == "theme":
				if value not in THEMES:
					raise EngineError(400, "Tema desconhecido.")
				updates[key] = value
			elif key == "web_port":
				updates[key] = self._int_in(value, 1024, 65535, "A porta vai de 1024 a 65535.")
			else:
				raise EngineError(400, f"Ajuste desconhecido: {key}")
		if "cookies_file" in updates and updates["cookies_file"] != load_settings().get("cookies_file"):
			updates["cookies_test_ok"] = False
			self.account_ok = None
		if updates:
			save_settings(updates)
		if library_changed:
			self.invalidate_paths()
			self.save()
			self.emit("playlists", {"ids": [_key_of(playlist) for playlist in self.library.get("playlists", [])]})
		return self.settings()

	@staticmethod
	def _int_in(value: Any, low: int, high: int, message: str) -> int:
		if isinstance(value, bool):
			raise EngineError(400, message)
		try:
			number = int(value)
		except (TypeError, ValueError) as exc:
			raise EngineError(400, message) from exc
		if not (low <= number <= high):
			raise EngineError(400, message)
		return number

	def accept_first_run(self) -> dict:
		save_settings({"hide_startup_disclaimer": True})
		return {"ok": True}

	# --- janelas nativas, Finder, planilha ----------------------------------------------

	def choose_folder(self, purpose: str, start: str = "") -> dict:
		if purpose not in ("output", "m3u", "tool"):
			raise EngineError(400, "Pasta para quê?")
		return {"path": self.host.choose_folder(purpose, start or self.output_dir())}

	def choose_file(self, purpose: str) -> dict:
		if purpose not in ("cookies", "ytdlp", "ffmpeg", "library", "csv"):
			raise EngineError(400, "Arquivo para quê?")
		return {"path": self.host.choose_file(purpose)}

	def open_location(self, what: str, playlist_id: str | None = None, index: int | None = None) -> dict:
		from csvmusic.core.log import log_path
		if what == "log":
			ok = self.host.reveal_path(str(log_path()))
		elif what == "output":
			output = self.output_dir()
			if not output:
				raise EngineError(409, "Escolha a pasta das músicas em Ajustes › Downloads.")
			folder = pathlib.Path(output).expanduser()
			try:
				folder.mkdir(parents=True, exist_ok=True)
			except OSError as exc:
				raise EngineError(500, "A pasta das músicas não está disponível.") from exc
			ok = self.host.open_path(str(folder.resolve()))
		elif what == "playlist":
			playlist = self._playlist(str(playlist_id or ""))
			output = self.output_dir()
			if not output:
				raise EngineError(409, "Escolha a pasta das músicas em Ajustes › Downloads.")
			root = pathlib.Path(output).expanduser().resolve()
			folder = (root / (sanitize_name(str(playlist.get("name") or "Playlist")) or "Playlist")).resolve()
			if folder == root or not folder.is_relative_to(root):
				raise EngineError(400, "A pasta da playlist está fora da pasta das músicas.")
			folder.mkdir(parents=True, exist_ok=True)
			ok = self.host.open_path(str(folder))
		elif what == "file":
			playlist = self._playlist(str(playlist_id or ""))
			self._track(playlist, int(index or 0))
			path = self._paths(playlist)[int(index or 0)]
			if path is None:
				raise EngineError(404, "Esta música ainda não tem arquivo.")
			ok = self.host.reveal_path(str(path))
		else:
			raise EngineError(400, "Abrir o quê?")
		if not ok:
			raise EngineError(500, "O Finder não abriu este lugar.")
		return {"ok": True}

	def export_csv_bytes(self, playlist_id: str | None = None) -> tuple[bytes, str]:
		ids = None
		name = "biblioteca"
		if playlist_id:
			playlist = self._playlist(playlist_id)
			ids = {_key_of(playlist)}
			name = sanitize_name(views.playlist_name(playlist)) or "playlist"
		with tempfile.TemporaryDirectory(prefix="csvmusic-export-") as folder:
			path = pathlib.Path(folder) / "export.csv"
			export_csv(path, self.library, ids)
			return path.read_bytes(), f"{name}.csv"

	# --- lixeira interna -----------------------------------------------------------------

	def trash_stats(self) -> dict:
		return internal_trash_stats(self.output_dir()) if self.output_dir() else {"files": 0, "bytes": 0}

	def empty_trash(self) -> dict:
		if not self.output_dir():
			return {"moved": 0}
		moved = empty_internal_trash(self.output_dir(), self.trash_mover)
		log(f"internal trash emptied into the system trash items={moved}")
		return {"moved": moved}

	# --- aparelhos ---------------------------------------------------------------------
	# discover/list/delete/eject rodam na thread do servidor (bloqueiam); a sincronização é um QThread.

	@staticmethod
	def device_id(device) -> str:
		return hashlib.sha1(device.key.encode("utf-8")).hexdigest()[:12]

	def discover_devices(self) -> dict:
		from csvmusic.core.device_sync import discover_devices
		devices = discover_devices()
		with self._device_lock:
			self._devices = {self.device_id(device): device for device in devices}
		return {
			"devices": [
				{"id": self.device_id(device), "name": device.name, "kind": device.kind, "description": device.description}
				for device in devices
			],
			"busy": self.device_busy,
		}

	def _device(self, device_id: str):
		with self._device_lock:
			device = self._devices.get(device_id)
		if device is None:
			self.discover_devices()
			with self._device_lock:
				device = self._devices.get(device_id)
		if device is None:
			raise EngineError(404, "Este aparelho não está mais conectado.")
		if device.kind == "ipod_classic":
			from csvmusic.core.device_sync import ipod_sync_available
			available, _reason = ipod_sync_available()
			if not available:
				raise EngineError(409, "A sincronização com iPod não está disponível neste Mac.")
		return device

	def device_playlists(self, device_id: str) -> dict:
		from csvmusic.core.device_sync import list_device_playlists
		device = self._device(device_id)
		if self.device_busy:
			raise EngineError(409, "O aparelho está ocupado com outra tarefa.")
		try:
			playlists = list_device_playlists(device)
		except Exception as exc:
			log(f"device playlist read failed device={device.root} error={exc}")
			raise EngineError(500, "Não deu para ler as playlists do aparelho.") from exc
		return {"playlists": [{"name": playlist.name, "track_count": playlist.track_count} for playlist in playlists], "_raw": playlists}

	def device_library_states(self, raw_playlists: list) -> list[dict]:
		"""Compara cada playlist da biblioteca com o aparelho (roda na thread do Qt)."""
		from csvmusic.core.device_sync import device_playlist_state
		by_name = {playlist.name.casefold(): playlist for playlist in raw_playlists or []}
		result = []
		for playlist in self.library.get("playlists", []):
			paths = self._paths(playlist)
			enabled = [index for index, track in enumerate(playlist.get("tracks", [])) if track.get("enabled", True)]
			ready = bool(enabled) and all(paths[index] is not None and not playlist["tracks"][index].get("force_redownload") for index in enabled)
			state = device_playlist_state(playlist, by_name.get(str(playlist.get("name") or "").casefold()))
			result.append({"playlist_id": _key_of(playlist), "name": views.playlist_name(playlist), "state": state.lower(), "ready": ready})
		return result

	def start_device_sync(self, device_id: str, playlist_ids: list[str]) -> dict:
		device = self._device(device_id)
		if self.device_busy:
			raise EngineError(409, "O aparelho está ocupado com outra tarefa.")
		keys = {_key_of(playlist) for playlist in (playlist_by_id(self.library, key) for key in playlist_ids or []) if playlist}
		if not keys:
			raise EngineError(400, "Escolha pelo menos uma playlist para levar ao aparelho.")
		self.device_busy = True
		worker = self.device_sync_worker_factory(device, self.library, keys, self)
		self.device_worker = worker
		worker.progress.connect(lambda done, total, message: self.emit("device", {"phase": "sync", "done": int(done), "total": int(total), "message": str(message)}))
		worker.completed.connect(lambda result, chosen=device: self._device_sync_completed(chosen, result))
		worker.failed.connect(self._device_sync_failed)
		worker.finished.connect(self._device_worker_finished)
		self.emit("device", {"phase": "start", "done": 0, "total": 0, "message": f"Começando a sincronizar com {device.name}…"})
		worker.start()
		return {"started": True}

	def _device_sync_completed(self, device, result) -> None:
		skipped = f" Ficaram de fora (incompletas): {', '.join(result.playlists_skipped)}." if result.playlists_skipped else ""
		message = f"{result.playlists} playlists sincronizadas. {result.tracks_copied} músicas copiadas, {result.tracks_reused} já estavam lá.{skipped}"
		self.emit("device", {"phase": "done", "done": result.tracks_copied + result.tracks_reused, "total": result.tracks_copied + result.tracks_reused, "message": message})
		if load_settings().get("device_sync_auto_eject"):
			try:
				self.eject_device(self.device_id(device), _from_worker=True)
			except EngineError as exc:
				self.warn(exc.message)

	def _device_sync_failed(self, message: str) -> None:
		lower = str(message).casefold()
		if "winerror 433" in lower or "does not exist" in lower:
			text = "O aparelho desconectou durante a cópia. O CSVMusic parou na hora. Conecte de novo antes de tentar outra vez."
		else:
			text = "A sincronização falhou. Veja o registro."
		self.emit("device", {"phase": "error", "done": 0, "total": 0, "message": text})

	def _device_worker_finished(self) -> None:
		worker = self.device_worker
		self.device_worker = None
		self.device_busy = False
		if worker is not None:
			worker.deleteLater()

	def delete_device_playlist(self, device_id: str, name: str) -> dict:
		from csvmusic.core.device_sync import delete_device_playlist
		device = self._device(device_id)
		if self.device_busy:
			raise EngineError(409, "O aparelho está ocupado com outra tarefa.")
		try:
			delete_device_playlist(device, name)
		except Exception as exc:
			log(f"device playlist delete failed device={device.root} name={name!r} error={exc}")
			raise EngineError(500, "Não deu para remover a playlist do aparelho.") from exc
		return {"removed": True}

	def eject_device(self, device_id: str, *, _from_worker: bool = False) -> dict:
		from csvmusic.core.device_sync import eject_device
		device = self._device(device_id)
		if self.device_busy and not _from_worker:
			raise EngineError(409, "O aparelho está ocupado com outra tarefa.")
		try:
			eject_device(device)
		except Exception as exc:
			log(f"device eject failed device={device.root} error={exc}")
			raise EngineError(500, "Não deu para ejetar o aparelho.") from exc
		self.emit("device", {"phase": "ejected", "done": 0, "total": 0, "message": f"{device.name} pode ser desconectado."})
		return {"ok": True}

	# --- fechar ------------------------------------------------------------------------

	def shutdown(self, wait_ms: int = 10000) -> None:
		"""Fechar o app: para o download, cancela a análise, grava a biblioteca e as configurações."""
		if self.download_worker is not None and self.download_worker.isRunning():
			self.download_stopping = True
			self.download_worker.stop()
			self.download_worker.wait(wait_ms)
		if self.single_worker is not None and self.single_worker.isRunning():
			self.single_worker.wait(wait_ms)
		if self.scan_running():
			# Marca cancelado antes: o leitor entrega o resultado parcial na hora, e ele não pode ser gravado.
			self.scan_cancelled = True
			self.scan_queue.clear()
			if self.scraper is not None and getattr(self.scraper, "running", False):
				self.scraper._finish("Library scan cancelled because CSVMusic was closed.")
		if self.direct_worker is not None and self.direct_worker.isRunning():
			self.direct_worker.wait(wait_ms)
		for worker in (self.session_worker, self.device_worker):
			if worker is not None and worker.isRunning():
				worker.wait(wait_ms)
		self._job_timer.stop()
		self.save()
		flush_settings()
		log("engine shutdown complete")
