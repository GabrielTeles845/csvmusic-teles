# tabs only
"""Threads e regras de fila que o motor usa e que antes moravam nas telas antigas.

Vieram de `ui/library_mode.py` (análise direta, fila do download) e de
`ui/device_sync.py` (aparelhos). Os downloads continuam em `ui/workers.py`.
"""
from __future__ import annotations

import pathlib

from PySide6.QtCore import QThread, Signal

from csvmusic.core.amazon_music_import import fetch_amazon_music_source
from csvmusic.core.apple_music_import import fetch_apple_music_source
from csvmusic.core.deezer_import import fetch_deezer_source
from csvmusic.core.device_sync import PortableDevice, list_device_playlists, sync_device
from csvmusic.core.library import library_track_path
from csvmusic.core.log import log
from csvmusic.core.spotify_import import fetch_spotify_playlist
from csvmusic.core.youtube_music_import import fetch_youtube_music_source


def audio_processing_settings(cfg: dict) -> dict:
	if not cfg.get("eq_enabled"):
		return {}
	return {
		"enabled": True,
		"normalize": bool(cfg.get("eq_normalize", False)),
		"volume_gain": int(cfg.get("eq_volume_gain", 0) or 0),
		"bass_gain": int(cfg.get("eq_bass_gain", 0) or 0),
		"treble_gain": int(cfg.get("eq_treble_gain", 0) or 0),
	}


def audio_processing_signature(audio: dict) -> str:
	if not audio:
		return "off"
	return "|".join((
		f"normalize={int(bool(audio.get('normalize')))}",
		f"volume={int(audio.get('volume_gain', 0) or 0)}",
		f"bass={int(audio.get('bass_gain', 0) or 0)}",
		f"treble={int(audio.get('treble_gain', 0) or 0)}",
	))


def pending_download_tracks(
	tracks: list[dict], output_path: pathlib.Path, fmt: str, *, audio_signature: str,
	audio_enabled: bool, prefix_numbers: bool, missing_only: bool = False,
) -> list[dict]:
	"""Músicas que precisam de trabalho; "baixar faltando" quer dizer só arquivo que não existe."""
	if missing_only:
		return [track for track in tracks if not library_track_path(track, output_path, fmt).exists()]
	return [
		track for track in tracks
		if track.get("force_redownload")
		or not library_track_path(track, output_path, fmt).exists()
		or (
			audio_enabled
			and bool(track.get("_previous_audio_processing_signature"))
			and track["_previous_audio_processing_signature"] != audio_signature
		)
		or bool(track.get("_previous_prefix_numbered")) != prefix_numbers
	]


def legacy_options(cfg: dict) -> dict:
	return {
		"enabled": bool(cfg.get("legacy_ipod_mode", False)),
		"mp3_mode": cfg.get("legacy_mp3_mode") or "vbr",
		"cover_art_mode": cfg.get("legacy_cover_art_mode") or "standard",
	}


class DirectLibraryScanWorker(QThread):
	"""Lê uma fonte que não precisa do navegador (CSV, Apple, Deezer, Amazon, YouTube, álbum do Spotify)."""
	finished_scan = Signal(object)

	def __init__(self, url: str, platform: str, parent=None, *, source_id: str = ""):
		super().__init__(parent)
		self.url = url
		self.platform = platform
		self.source_id = source_id

	def run(self) -> None:
		try:
			if self.platform == "csv":
				from csvmusic.core.csv_import import load_csv, tracks_from_csv
				tracks = tracks_from_csv(load_csv(self.url))
				if not tracks:
					raise ValueError("The CSV did not contain any usable tracks.")
				self.finished_scan.emit({
					"id": self.source_id,
					"name": tracks[0].get("playlist") or pathlib.Path(self.url).stem,
					"tracks": tracks, "reported_total": len(tracks), "message": "",
					"complete": bool(tracks), "platform": "csv", "cover_url": None, "direct": True,
				})
				return
			if self.platform == "apple_music":
				source = fetch_apple_music_source(self.url)
			elif self.platform == "spotify_album":
				source = fetch_spotify_playlist(self.url)
			elif self.platform == "deezer":
				source = fetch_deezer_source(self.url)
			elif self.platform == "amazon_music":
				source = fetch_amazon_music_source(self.url)
			else:
				source = fetch_youtube_music_source(self.url)
			self.finished_scan.emit({
				"id": source.id, "name": source.name, "tracks": source.tracks,
				"reported_total": source.total_count, "message": source.warning or "",
				"complete": not bool(source.warning), "platform": "spotify" if self.platform == "spotify_album" else self.platform,
				"cover_url": getattr(source, "cover_url", None), "direct": True,
			})
		except Exception as exc:
			log(f"library direct scan failed platform={self.platform} url={self.url} error={exc}")
			self.finished_scan.emit({"error": str(exc), "complete": False, "platform": self.platform, "direct": True})


class DeviceSyncWorker(QThread):
	progress = Signal(int, int, str)
	completed = Signal(object)
	failed = Signal(str)

	def __init__(self, device: PortableDevice, library: dict, playlist_keys: set[str], parent=None):
		super().__init__(parent)
		self.device = device
		self.library = dict(library)
		self.library["playlists"] = [
			playlist for playlist in library.get("playlists", [])
			if f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}" in playlist_keys
		]

	def run(self) -> None:
		try:
			self.completed.emit(sync_device(self.device, self.library, self.progress.emit))
		except Exception as exc:
			log(f"device sync failed device={self.device.root} error={exc}")
			self.failed.emit(str(exc))


class DevicePlaylistReadWorker(QThread):
	status = Signal(str)
	completed = Signal(object)
	failed = Signal(str)

	def __init__(self, device: PortableDevice, parent=None):
		super().__init__(parent)
		self.device = device

	def run(self) -> None:
		try:
			self.completed.emit(list_device_playlists(self.device, self.status.emit))
		except Exception as exc:
			log(f"device playlist read failed device={self.device.root} error={exc}")
			self.failed.emit(str(exc))
