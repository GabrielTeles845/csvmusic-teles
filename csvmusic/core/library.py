# tabs only
import csv
import datetime
import hashlib
import json
import os
import pathlib
import unicodedata
import re
import shutil
import tempfile
from typing import Any
from urllib.parse import urlparse

from csvmusic.core.spotify_import import parse_spotify_source
from csvmusic.core.downloader import is_age_restriction_error, keep_previous_copy, sanitize_name, write_m3u
from csvmusic.core.track_output import expected_track_path, library_format
from csvmusic.core.youtube_music_import import parse_youtube_music_source
from csvmusic.core.apple_music_import import parse_apple_music_source_url
from csvmusic.core.deezer_import import parse_deezer_source
from csvmusic.core.amazon_music_import import parse_amazon_music_source
from csvmusic.core.csv_import import load_csv, tracks_from_csv


LIBRARY_VERSION = 1


def new_library(name: str = "My Library", output_dir: str = "") -> dict:
	now = _now()
	return {
		"version": LIBRARY_VERSION,
		"name": (name or "My Library").strip(),
		"output_dir": str(output_dir or ""),
		"created_at": now,
		"updated_at": now,
		"playlists": [],
	}


class LibraryVersionError(ValueError):
	"""The file is a CSVMusic library, but of a version this build cannot read (no migration exists)."""


def load_library(path: str | pathlib.Path) -> dict:
	with pathlib.Path(path).open("r", encoding="utf-8") as handle:
		data = json.load(handle)
	if not isinstance(data, dict):
		raise ValueError("This is not a supported CSVMusic library file.")
	if data.get("version") != LIBRARY_VERSION:
		if isinstance(data.get("playlists"), list):
			raise LibraryVersionError(
				f"This library was saved as version {data.get('version')!r}; this CSVMusic reads version {LIBRARY_VERSION}."
			)
		raise ValueError("This is not a supported CSVMusic library file.")
	if not isinstance(data.get("playlists"), list):
		raise ValueError("The library playlist list is invalid.")
	return data


def backup_library_file(path: str | pathlib.Path) -> pathlib.Path:
	"""Copy a library file that could not be read next to it, without touching the original."""
	source = pathlib.Path(path)
	stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
	target = source.with_name(f"{source.name}.unreadable-{stamp}.bak")
	counter = 1
	while target.exists():
		counter += 1
		target = source.with_name(f"{source.name}.unreadable-{stamp}-{counter}.bak")
	shutil.copy2(source, target)
	return target


def save_library(path: str | pathlib.Path, library: dict) -> None:
	target = pathlib.Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	library["updated_at"] = _now()
	with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".tmp", prefix="csvmusic-library-", dir=target.parent, delete=False) as handle:
		temporary = pathlib.Path(handle.name)
		try:
			json.dump(library, handle, ensure_ascii=False, indent=2)
			handle.flush()
			os.fsync(handle.fileno())
		except BaseException:
			handle.close()
			temporary.unlink(missing_ok=True)
			raise
	temporary.replace(target)


def add_playlist_urls(library: dict, values: list[str]) -> tuple[list[dict], list[str]]:
	existing = {_playlist_key(item) for item in library.get("playlists", [])}
	added: list[dict] = []
	errors: list[str] = []
	for value in values:
		text = str(value or "").strip()
		if not text:
			continue
		try:
			host = urlparse(text).netloc.lower().removeprefix("www.")
			if "music.apple.com" in text.casefold():
				source_type, source_id, url = parse_apple_music_source_url(text)
				platform = "apple_music"
				placeholder = f"Unscanned Apple Music {source_type.title()}"
			elif "youtube.com" in text.casefold() or "youtu.be" in text.casefold():
				host = urlparse(text).netloc.lower().split(":", 1)[0]
				source_type, source_id = parse_youtube_music_source(text)
				is_youtube_music = host == "music.youtube.com"
				platform = "youtube_music" if is_youtube_music else "youtube"
				url = (
					f"https://music.youtube.com/browse/{source_id}" if source_type == "album"
					else f"https://{'music.' if is_youtube_music else 'www.'}youtube.com/playlist?list={source_id}"
				)
				placeholder = f"Unscanned {'YouTube Music' if is_youtube_music else 'YouTube'} {source_type.title()}"
			elif host in ("deezer.com", "deezer.page.link"):
				source_type, source_id = parse_deezer_source(text)
				platform = "deezer"
				url = text
				placeholder = f"Unscanned Deezer {source_type.title()}"
			elif "music.amazon." in host:
				url, source_type, source_id = parse_amazon_music_source(text)
				platform = "amazon_music"
				placeholder = f"Unscanned Amazon Music {source_type.title()}"
			else:
				source = parse_spotify_source(text)
				source_type = source.type
				source_id = source.id
				platform = "spotify"
				url = f"https://open.spotify.com/{source_type}/{source_id}"
				placeholder = f"Unscanned Spotify {source_type.title()}"
		except Exception as exc:
			errors.append(f"{text}: {exc}")
			continue
		key = f"{platform}:{source_id}"
		if key in existing:
			continue
		playlist = {
			"id": source_id,
			"platform": platform,
			"source_type": source_type,
			"url": url,
			"name": placeholder,
			"last_scanned_at": None,
			"reported_total": None,
			"scan_warning": None,
			"cover_url": None,
			"tracks": [],
		}
		library.setdefault("playlists", []).append(playlist)
		existing.add(key)
		added.append(playlist)
	return added, errors


def import_csv_playlist(library: dict, path: str | pathlib.Path) -> tuple[dict, bool]:
	"""Import or refresh one CSV file as a first-class library playlist."""
	source_path = pathlib.Path(path).expanduser().resolve()
	df = load_csv(source_path)
	tracks = tracks_from_csv(df)
	if not tracks:
		raise ValueError("The CSV did not contain any usable tracks.")
	name = str(tracks[0].get("playlist") or source_path.stem).strip() or source_path.stem
	source_id = hashlib.sha256(str(source_path).casefold().encode("utf-8")).hexdigest()[:20]
	key = f"csv:{source_id}"
	playlist = playlist_by_id(library, key)
	created = playlist is None
	if playlist is None:
		playlist = {
			"id": source_id,
			"platform": "csv",
			"url": str(source_path),
			"csv_path": str(source_path),
			"name": name,
			"last_scanned_at": None,
			"reported_total": None,
			"scan_warning": None,
			"cover_url": None,
			"tracks": [],
		}
		library.setdefault("playlists", []).append(playlist)
	merge_playlist_scan(library, key, name, tracks, reported_total=len(tracks))
	playlist["csv_path"] = str(source_path)
	playlist["url"] = str(source_path)
	return playlist, created


def rename_library_playlist(
	library: dict,
	playlist_id: str,
	new_name: str,
	output_dir: str | pathlib.Path | None = None,
) -> tuple[dict, pathlib.Path | None]:
	"""Rename a playlist, its output folder, and its matching M3U files."""
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		raise KeyError(f"Playlist {playlist_id} is not in this library.")
	clean_name = str(new_name or "").strip()
	if not clean_name:
		raise ValueError("Playlist name cannot be blank.")
	old_name = str(playlist.get("name") or "Playlist").strip() or "Playlist"
	old_safe = sanitize_name(old_name) or "Playlist"
	new_safe = sanitize_name(clean_name) or "Playlist"
	for other in library.get("playlists", []):
		if other is playlist:
			continue
		other_safe = sanitize_name(str(other.get("name") or "Playlist")) or "Playlist"
		if other_safe.casefold() == new_safe.casefold():
			raise ValueError("Another library playlist already uses that output-folder name.")

	renamed_folder: pathlib.Path | None = None
	if output_dir:
		root = pathlib.Path(output_dir).expanduser().resolve()
		old_folder = root / old_safe
		new_folder = root / new_safe
		if old_folder.exists() and old_folder.is_dir():
			if old_folder != new_folder and new_folder.exists():
				raise FileExistsError(f"The destination folder already exists: {new_folder}")
			m3u_moves: list[tuple[pathlib.Path, pathlib.Path]] = []
			m3u_unchanged: list[pathlib.Path] = []
			for suffix in (".m3u", ".m3u8"):
				source = old_folder / f"{old_safe}{suffix}"
				destination = old_folder / f"{new_safe}{suffix}"
				if source.exists() and source != destination:
					if destination.exists():
						raise FileExistsError(f"The destination playlist file already exists: {destination}")
					m3u_moves.append((source, destination))
				elif source.exists():
					m3u_unchanged.append(source)
			if old_folder != new_folder:
				old_folder.rename(new_folder)
				renamed_folder = new_folder
			else:
				renamed_folder = old_folder
			for old_file, old_destination in m3u_moves:
				source = renamed_folder / old_file.name
				destination = renamed_folder / old_destination.name
				source.rename(destination)
				_update_m3u_playlist_name(destination, clean_name)
			for old_file in m3u_unchanged:
				_update_m3u_playlist_name(renamed_folder / old_file.name, clean_name)

	playlist["name"] = clean_name
	playlist["custom_name"] = True
	for track in playlist.get("tracks", []):
		track["playlist"] = clean_name
	return playlist, renamed_folder


def edit_library_track(library: dict, playlist_id: str, track_index: int, title: str, album: str) -> dict:
	"""Apply user-owned track metadata overrides that survive future rescans."""
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		raise KeyError(f"Playlist {playlist_id} is not in this library.")
	tracks = playlist.get("tracks", [])
	if track_index < 0 or track_index >= len(tracks):
		raise IndexError("The selected song is no longer in this playlist.")
	clean_title = str(title or "").strip()
	clean_album = str(album or "").strip()
	if not clean_title:
		raise ValueError("Song title cannot be blank.")
	track = tracks[track_index]
	track["title"] = clean_title
	track["album"] = clean_album
	track["custom_title"] = True
	track["custom_album"] = True
	return track


def merge_playlist_scan(
	library: dict,
	playlist_id: str,
	name: str,
	tracks: list[dict],
	*,
	reported_total: int | None = None,
	warning: str | None = None,
	cover_url: str | None = None,
	complete: bool = True,
) -> dict:
	"""Merge a fresh scan into a playlist, keeping user choices and file state.

	When the scan is incomplete (`complete=False`), songs it did not see are kept at their old place
	instead of being removed: a partial read must never delete what an earlier scan found.
	"""
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		raise KeyError(f"Playlist {playlist_id} is not in this library.")
	previous: dict[str, dict] = {}
	previous_occurrences: dict[str, int] = {}
	for old_track in playlist.get("tracks", []):
		base_key = _track_base_key(old_track)
		occurrence = int(old_track.get("playlist_occurrence") or (previous_occurrences.get(base_key, 0) + 1))
		previous_occurrences[base_key] = max(previous_occurrences.get(base_key, 0), occurrence)
		old_track["playlist_occurrence"] = occurrence
		previous[_track_key(old_track)] = old_track
	effective_name = str(playlist.get("name") or name or "Spotify Playlist").strip() if playlist.get("custom_name") else str(name or playlist.get("name") or "Spotify Playlist").strip()
	merged: list[dict] = []
	seen: set[str] = set()
	used_old: set[int] = set()
	old_by_text: dict[str, list[dict]] = {}
	for candidate in playlist.get("tracks", []):
		old_by_text.setdefault(_track_text_key(candidate), []).append(candidate)
	old_folder_name = str(playlist.get("name") or effective_name or "Playlist")
	old_siblings = playlist_probes(dict(playlist, name=old_folder_name))
	new_occurrences: dict[str, int] = {}
	normalized: list[dict] = []
	for position, raw in enumerate(tracks, start=1):
		track = _normalized_track(raw, effective_name, position)
		base_key = _track_base_key(track)
		occurrence = int(raw.get("playlist_occurrence") or (new_occurrences.get(base_key, 0) + 1))
		new_occurrences[base_key] = max(new_occurrences.get(base_key, 0), occurrence)
		track["playlist_occurrence"] = occurrence
		normalized.append(track)
	# An old song that the scan still has under its own key is never handed to a namesake by text:
	# the namesake would inherit its file, chosen video and lock.
	claimed_by_key = {id(previous[_track_key(track)]) for track in normalized if _track_key(track) in previous}
	for track in normalized:
		key = _track_key(track)
		if key in seen:
			continue
		seen.add(key)
		old = previous.get(key, {})
		if not old:
			matching_old = [
				candidate for candidate in old_by_text.get(_track_text_key(track), [])
				if id(candidate) not in used_old and id(candidate) not in claimed_by_key
			]
			if len(matching_old) == 1 and len(old_by_text.get(_track_text_key(track), [])) == 1:
				old = matching_old[0]
		if old:
			used_old.add(id(old))
		if old.get("custom_title"):
			track["title"] = old.get("title") or track["title"]
			track["custom_title"] = True
		if old.get("custom_album"):
			track["album"] = old.get("album") or ""
			track["custom_album"] = True
		if not track.get("duration_ms") and old.get("duration_ms"):
			# A scan without durations (e.g. the browser reader) must not erase one read before (doc 13).
			track["duration_ms"] = int(old["duration_ms"])
			for field in ("duration_source", "duration_precision_s"):
				if old.get(field) not in (None, ""):
					track[field] = old[field]
		track["enabled"] = bool(old.get("enabled", True))
		track["preferred_video_id"] = old.get("preferred_video_id") or track.get("preferred_video_id") or None
		track["preferred_video_label"] = old.get("preferred_video_label") or track.get("preferred_video_label") or None
		track["preferred_selection_locked"] = bool(old.get("preferred_selection_locked", False))
		track["audio_volume_gain"] = int(old.get("audio_volume_gain", track.get("audio_volume_gain", 0)) or 0)
		# These describe the downloaded file, not the latest scraped metadata.
		for field in ("audio_processing_signature", "filename_prefix_number", "filename_prefix_width"):
			track[field] = old.get(field)
		track["force_redownload"] = bool(old.get("force_redownload", False))
		track["last_error"] = old.get("last_error") or None
		track["last_error_at"] = old.get("last_error_at") or None
		track["last_downloaded_at"] = old.get("last_downloaded_at") or None
		track["downloaded_video_id"] = old.get("downloaded_video_id") or None
		track["downloaded_video_title"] = old.get("downloaded_video_title") or None
		track["downloaded_video_publisher"] = old.get("downloaded_video_publisher") or None
		old_downloaded_path = old.get("downloaded_path")
		if not old_downloaded_path and old:
			old_probe = dict(old)
			old_probe["playlist"] = old_folder_name
			candidate = library_track_path(
				old_probe, pathlib.Path(library.get("output_dir") or ""), library_format(library), playlist_tracks=old_siblings,
			)
			if candidate.is_file():
				old_downloaded_path = str(candidate)
		track["downloaded_path"] = old_downloaded_path or None
		track["low_confidence_review"] = bool(old.get("low_confidence_review", False))
		track["download_confidence"] = old.get("download_confidence")
		track["downloaded_duration_ms"] = old.get("downloaded_duration_ms") or None
		track["review_reason"] = old.get("review_reason") or None
		for field in _SKIP_FIELDS:
			track[field] = old.get(field) or None
		track["failure_kind"] = old.get("failure_kind") or None
		merged.append(track)
	old_positions = {id(old): index for index, old in enumerate(playlist.get("tracks", []))}
	unseen = [old for key, old in previous.items() if key not in seen]
	kept: list[dict] = []
	if not complete:
		leftovers = [old for old in unseen if id(old) not in used_old]
		for old in sorted(leftovers, key=lambda item: old_positions.get(id(item), 0)):
			old["playlist"] = effective_name
			merged.insert(min(old_positions.get(id(old), len(merged)), len(merged)), old)
			kept.append(old)
	removed = [] if not complete else unseen
	playlist.update({
		"name": effective_name,
		"last_scanned_at": _now(),
		"reported_total": reported_total,
		"scan_warning": warning,
		"access_error": None,
		"access_error_message": None,
		"cover_url": cover_url or playlist.get("cover_url"),
		"tracks": merged,
		"last_diff": {
			"added": sum(1 for track in merged if _track_key(track) not in previous),
			"removed": len(removed),
			"unchanged": sum(1 for track in merged if _track_key(track) in previous) - len(kept),
			**({"kept_from_incomplete_scan": len(kept)} if kept else {}),
		},
	})
	return playlist


def mark_playlist_access_error(library: dict, playlist_id: str, kind: str, message: str) -> dict | None:
	"""Record why a scan could not read the playlist (e.g. "private") without touching its tracks."""
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		return None
	playlist["access_error"] = kind
	playlist["access_error_message"] = message
	playlist["access_error_at"] = _now()
	return playlist


def clear_playlist_access_error(library: dict, playlist_id: str) -> bool:
	"""Drop an access mark after a scan that reached the playlist, even if it came back empty.

	Returns True when something changed. A failed scan (network, timeout) must not call this:
	it says nothing about whether the playlist is private.
	"""
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None or not (playlist.get("access_error") or playlist.get("access_error_message")):
		return False
	playlist["access_error"] = None
	playlist["access_error_message"] = None
	playlist["access_error_at"] = None
	return True


def _update_m3u_playlist_name(path: pathlib.Path, playlist_name: str) -> None:
	raw = path.read_bytes()
	has_bom = raw.startswith(b"\xef\xbb\xbf")
	text = raw.decode("utf-8-sig")
	lines = text.splitlines()
	replacement = f"#EXTPLAYLIST:{playlist_name}"
	for index, line in enumerate(lines):
		if line.startswith("#EXTPLAYLIST:"):
			lines[index] = replacement
			break
	else:
		lines.insert(1 if lines and lines[0] == "#EXTM3U" else 0, replacement)
	ending = "\n" if text.endswith(("\n", "\r")) else ""
	path.write_text("\n".join(lines) + ending, encoding="utf-8-sig" if has_bom else "utf-8")


def playlist_by_id(library: dict, playlist_id: str) -> dict | None:
	return next((item for item in library.get("playlists", []) if _playlist_key(item) == playlist_id or item.get("id") == playlist_id), None)


def enabled_tracks(library: dict, playlist_ids: set[str] | None = None) -> list[dict]:
	result: list[dict] = []
	for playlist in library.get("playlists", []):
		if playlist_ids is not None and _playlist_key(playlist) not in playlist_ids and playlist.get("id") not in playlist_ids:
			continue
		for track_index, stored in enumerate(playlist.get("tracks", [])):
			if not stored.get("enabled", True):
				continue
			track = dict(stored)
			track["playlist"] = playlist.get("name") or "Playlist"
			track["library_playlist_id"] = _playlist_key(playlist)
			track["library_track_index"] = track_index
			result.append(track)
	return result


def clear_redownload_flag(path: str | pathlib.Path, playlist_id: str, track: dict) -> None:
	"""Mark one successfully replaced library track as current."""
	library = load_library(path)
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		return
	key = _track_key(track)
	for stored in playlist.get("tracks", []):
		if _track_key(stored) == key:
			stored["force_redownload"] = False
			save_library(path, library)
			return


def record_library_download_result(
	path: str | pathlib.Path,
	playlist_id: str,
	track: dict,
	*,
	downloaded: bool,
	error: str | None = None,
	match: dict | None = None,
	low_confidence: bool = False,
	confidence: float | None = None,
) -> None:
	"""Persist one download outcome straight to disk (legacy mode; Library Mode keeps the library in memory)."""
	library = load_library(path)
	stored = apply_library_download_result(
		library, playlist_id, track,
		downloaded=downloaded, error=error, match=match, low_confidence=low_confidence, confidence=confidence,
	)
	if stored is not None:
		save_library(path, library)


def apply_library_download_result(
	library: dict,
	playlist_id: str,
	track: dict,
	*,
	downloaded: bool,
	error: str | None = None,
	match: dict | None = None,
	low_confidence: bool = False,
	confidence: float | None = None,
	skipped: bool = False,
	skip_reason: str | None = None,
	failure_kind: str | None = None,
	downloaded_duration_ms: int | None = None,
	duration_needs_review: bool = False,
) -> dict | None:
	"""Apply one download outcome to the in-memory library and return the stored track (None if not found).

	A skip (no confident YouTube match) is recorded as `skip_state="not_found_on_youtube"` with its reason and date,
	so the song stops looking like an unexplained "missing".
	"""
	playlist = playlist_by_id(library, playlist_id)
	if playlist is None:
		return None
	stored = find_library_track(playlist, track)
	if stored is None:
		return None
	if downloaded or error:
		_clear_skip(stored)
	if downloaded:
		stored["force_redownload"] = False
		stored["last_error"] = None
		stored["last_error_at"] = None
		stored["failure_kind"] = None
		stored["last_downloaded_at"] = _now()
		stored["downloaded_video_id"] = (match or {}).get("videoId") or stored.get("downloaded_video_id")
		stored["downloaded_video_title"] = (match or {}).get("title") or stored.get("downloaded_video_title")
		stored["downloaded_video_publisher"] = (
			(match or {}).get("author") or (match or {}).get("artists") or stored.get("downloaded_video_publisher")
		)
		stored["low_confidence_review"] = bool(low_confidence or duration_needs_review)
		stored["download_confidence"] = confidence
		stored["downloaded_duration_ms"] = int(downloaded_duration_ms) if downloaded_duration_ms else None
		stored["review_reason"] = _length_review_reason(stored, downloaded_duration_ms) if duration_needs_review else None
		stored["filename_prefix_number"] = track.get("filename_prefix_number") or None
		stored["filename_prefix_width"] = track.get("filename_prefix_width") or None
		stored["audio_processing_signature"] = track.get("audio_processing_signature") or None
		probe = dict(track)
		probe["playlist"] = playlist.get("name") or "Playlist"
		downloaded_file = expected_track_path(
			probe, pathlib.Path(library.get("output_dir") or ""), library_format(library),
		)
		if downloaded_file.is_file():
			old_downloaded = str(stored.get("downloaded_path") or "").strip()
			if old_downloaded:
				old_path = pathlib.Path(old_downloaded)
				output_root = pathlib.Path(library.get("output_dir") or "").resolve()
				try:
					old_resolved = old_path.resolve()
					owned_by_other = any(
						other is not stored and _same_file(other.get("downloaded_path"), old_resolved)
						for other in playlist.get("tracks", [])
					)
					if (
						old_resolved != downloaded_file.resolve() and old_resolved.is_relative_to(output_root)
						and old_resolved.is_file() and not owned_by_other
					):
						# Renamed song: the old file goes to the internal trash, never straight to deletion.
						keep_previous_copy(old_resolved)
						old_resolved.unlink()
				except (OSError, RuntimeError):
					pass
			stored["downloaded_path"] = str(downloaded_file)
	elif error:
		stored["last_error"] = str(error).strip()[:4000]
		stored["last_error_at"] = _now()
		stored["failure_kind"] = failure_kind or download_failure_kind(error)
	elif skipped:
		stored["skip_state"] = SKIP_NOT_FOUND_ON_YOUTUBE
		stored["skip_reason"] = str(skip_reason or "No confident match on YouTube Music").strip()[:500]
		stored["skipped_at"] = _now()
	return stored


def _same_file(value: Any, target: pathlib.Path) -> bool:
	text = str(value or "").strip()
	if not text:
		return False
	try:
		return pathlib.Path(text).resolve() == target
	except (OSError, RuntimeError):
		return False


def _length_review_reason(stored: dict, downloaded_duration_ms: int | None) -> str:
	expected_s = int(round((stored.get("duration_ms") or 0) / 1000))
	actual_s = int(round((downloaded_duration_ms or 0) / 1000))
	if expected_s <= 0 or actual_s <= 0:
		return "Length could not be confirmed"
	difference = actual_s - expected_s
	return f"File is {abs(difference)} s {'longer' if difference > 0 else 'shorter'} than the song"


SKIP_NOT_FOUND_ON_YOUTUBE = "not_found_on_youtube"
_SKIP_FIELDS = ("skip_state", "skip_reason", "skipped_at")


def _clear_skip(stored: dict) -> None:
	for field in _SKIP_FIELDS:
		stored[field] = None


FAILURE_AGE_RESTRICTED = "age_restricted"


def download_failure_kind(error: str | None) -> str | None:
	"""Name failures the user can act on. Today only age restriction (needs a signed-in YouTube session)."""
	if error and is_age_restriction_error(str(error)):
		return FAILURE_AGE_RESTRICTED
	return None


def age_restricted_targets(failed: list[dict]) -> set[tuple[str, int]]:
	"""(playlist key, song index) of the batch's failures caused by age restriction.

	`failed` is the worker's list of {"track": ..., "error": ...}; library tracks carry their ids.
	"""
	targets: set[tuple[str, int]] = set()
	for entry in failed or []:
		track = entry.get("track") or {}
		if download_failure_kind(entry.get("error")) != FAILURE_AGE_RESTRICTED or not track.get("library_playlist_id"):
			continue
		targets.add((str(track["library_playlist_id"]), int(track.get("library_track_index", -1))))
	return targets


def describe_skip(options: list | None, confidence: float | None) -> str:
	"""Explain a skipped song the way the user needs it: nothing found, or nothing close enough."""
	if not options:
		return "No search results on YouTube Music"
	best = float(confidence or 0.0)
	return f"No confident match on YouTube Music (best score {best:.2f})"


def find_library_track(playlist: dict, track: dict) -> dict | None:
	"""Return the stored song a download row refers to (by index when still valid, else by identity)."""
	index = track.get("library_track_index")
	tracks = playlist.get("tracks", [])
	key = _track_key(track)
	if isinstance(index, int) and 0 <= index < len(tracks) and _track_key(tracks[index]) == key:
		return tracks[index]
	return next((stored for stored in tracks if _track_key(stored) == key), None)


def track_status_counts(
	track: dict,
	playlist_name: str,
	output_dir: str | pathlib.Path,
	fmt: str,
	listing_cache: dict | None = None,
	playlist_tracks: list[dict] | None = None,
) -> dict[str, int]:
	"""Count one stored track the way library_status does (enabled/downloaded/missing/redownload).

	A disabled song only counts as "disabled": it is never downloaded, so it is not "missing".
	`playlist_tracks` goes to library_track_path (songs of the playlist, with "playlist" set to its name).
	"""
	status = {"enabled": 0, "downloaded": 0, "missing": 0, "disabled": 0, "redownload": 0}
	if not track.get("enabled", True):
		status["disabled"] += 1
		return status
	status["enabled"] += 1
	probe = dict(track)
	probe["playlist"] = playlist_name
	if track.get("force_redownload"):
		status["redownload"] += 1
	if library_track_path(probe, pathlib.Path(output_dir), fmt, listing_cache=listing_cache, playlist_tracks=playlist_tracks).exists():
		status["downloaded"] += 1
	else:
		status["missing"] += 1
	return status


def adjust_status_counts(status: dict, playlist_key: str, track_index: int, after: dict[str, int]) -> None:
	"""Replace one track's contribution in a library_status() result without recounting the playlist."""
	per_track = status.setdefault("track_counts", {}).setdefault(playlist_key, {})
	before = per_track.get(track_index, {})
	per_track[track_index] = dict(after)
	playlist_counts = status.setdefault("playlists", {}).setdefault(playlist_key, {})
	totals = status.setdefault("totals", {})
	for field in set(before) | set(after):
		delta = int(after.get(field, 0)) - int(before.get(field, 0))
		if delta:
			playlist_counts[field] = int(playlist_counts.get(field, 0) or 0) + delta
			totals[field] = int(totals.get(field, 0) or 0) + delta


def library_status(
	library: dict,
	output_dir: str | pathlib.Path,
	fmt: str,
	playlist_ids: set[str] | None = None,
) -> dict:
	root = pathlib.Path(output_dir)
	by_playlist: dict[str, dict] = {}
	totals = {"enabled": 0, "downloaded": 0, "missing": 0, "disabled": 0, "redownload": 0}
	listing_cache: dict = {}
	track_counts: dict[str, dict[int, dict[str, int]]] = {}
	for playlist in library.get("playlists", []):
		key = _playlist_key(playlist)
		if playlist_ids is not None and key not in playlist_ids and playlist.get("id") not in playlist_ids:
			continue
		status = {"enabled": 0, "downloaded": 0, "missing": 0, "disabled": 0, "redownload": 0}
		name = playlist.get("name") or "Playlist"
		per_track = track_counts.setdefault(key, {})
		siblings = playlist_probes(playlist)
		for track_index, stored in enumerate(playlist.get("tracks", [])):
			counts = track_status_counts(stored, name, root, fmt, listing_cache, playlist_tracks=siblings)
			per_track[track_index] = counts
			for field, value in counts.items():
				status[field] += value
		by_playlist[key] = status
		for field in totals:
			totals[field] += status[field]
	# track_counts lets the UI move one song between counts without recounting the playlist.
	return {"totals": totals, "playlists": by_playlist, "track_counts": track_counts}


def write_library_m3us(
	manifest_tracks: list[dict],
	output_dir: str | pathlib.Path,
	fmt: str,
	*,
	write_m3u8: bool = True,
	write_m3u_plain: bool = False,
	m3u_output_dir: str | pathlib.Path | None = None,
	playlist_names: set[str] | None = None,
) -> list[pathlib.Path]:
	"""Write each playlist's M3U with the songs whose file already exists (used during a download, not only at the end)."""
	root = pathlib.Path(output_dir)
	by_playlist: dict[str, list[dict]] = {}
	for track in manifest_tracks:
		name = str(track.get("playlist") or "Playlist")
		if playlist_names is not None and name not in playlist_names:
			continue
		if expected_track_path(track, root, fmt).exists():
			by_playlist.setdefault(name, []).append(track)
	written: list[pathlib.Path] = []
	output_for_lists = pathlib.Path(m3u_output_dir) if m3u_output_dir else None
	for name, tracks in by_playlist.items():
		if write_m3u8:
			written.append(write_m3u(root, name, tracks, fmt, suffix=".m3u8", encoding="utf-8", playlist_output_dir=output_for_lists))
		if write_m3u_plain:
			written.append(write_m3u(root, name, tracks, fmt, suffix=".m3u", encoding="utf-8-sig", playlist_output_dir=output_for_lists))
	return written


def export_csv(path: str | pathlib.Path, library: dict, playlist_ids: set[str] | None = None) -> None:
	fields = ["Playlist name", "Track name", "Artist name", "Album", "ISRC", "Spotify - id", "Duration (ms)", "Release date", "Cover URL"]
	with pathlib.Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
		writer = csv.DictWriter(handle, fieldnames=fields)
		writer.writeheader()
		for track in enabled_tracks(library, playlist_ids):
			writer.writerow({
				"Playlist name": track.get("playlist"),
				"Track name": track.get("title"),
				"Artist name": track.get("artists"),
				"Album": track.get("album"),
				"ISRC": track.get("isrc"),
				"Spotify - id": track.get("sp_id"),
				"Duration (ms)": track.get("duration_ms") or 0,
				"Release date": track.get("year"),
				"Cover URL": track.get("cover_url"),
			})


def _normalized_track(raw: dict[str, Any], playlist_name: str, position: int) -> dict:
	track = {
		"title": str(raw.get("title") or "").strip(),
		"artists": str(raw.get("artists") or "").strip(),
		"album": str(raw.get("album") or "").strip(),
		"playlist": playlist_name,
		"isrc": raw.get("isrc") or None,
		"sp_id": raw.get("sp_id") or raw.get("id") or None,
		"duration_ms": int(raw.get("duration_ms") or 0),
		"year": raw.get("year"),
		"cover_url": raw.get("cover_url") or None,
		"track_no": int(raw.get("track_no") or position),
		"disc_no": int(raw.get("disc_no") or 1),
	}
	if raw.get("youtube_video_id"):
		track["youtube_video_id"] = raw["youtube_video_id"]
		track["preferred_video_id"] = raw["youtube_video_id"]
		track["preferred_video_label"] = raw.get("preferred_video_label") or f"https://music.youtube.com/watch?v={raw['youtube_video_id']}"
		track["youtube_video_title"] = raw.get("youtube_video_title") or track["title"]
		track["youtube_video_author"] = raw.get("youtube_video_author") or track["artists"]
	if raw.get("apple_music_id"):
		track["apple_music_id"] = raw["apple_music_id"]
	if raw.get("duration_source"):
		track["duration_source"] = str(raw["duration_source"])
	if raw.get("duration_precision_s") not in (None, ""):
		track["duration_precision_s"] = raw["duration_precision_s"]
	return track


def _track_base_key(track: dict) -> str:
	youtube_id = str(track.get("youtube_video_id") or "").strip()
	if youtube_id:
		return f"youtube:{youtube_id}"
	apple_id = str(track.get("apple_music_id") or "").strip()
	if apple_id:
		return f"apple:{apple_id}"
	spotify_id = str(track.get("sp_id") or track.get("id") or "").strip()
	if spotify_id:
		return f"spotify:{spotify_id}"
	return f"text:{str(track.get('artists') or '').casefold().strip()}|{str(track.get('title') or '').casefold().strip()}"


def _track_text_key(track: dict) -> str:
	return f"{str(track.get('artists') or '').casefold().strip()}|{str(track.get('title') or '').casefold().strip()}"


def library_track_path(
	track: dict,
	output_dir: str | pathlib.Path,
	fmt: str,
	*,
	listing_cache: dict | None = None,
	playlist_tracks: list[dict] | None = None,
) -> pathlib.Path:
	"""Resolve the file actually downloaded for a library row before its current expected filename.

	Pass the same `listing_cache` dict to many calls in one pass so each playlist folder is listed once.
	Pass `playlist_tracks` (the songs of the same playlist, or rows of several playlists) so a file without
	the expected position prefix is only recovered when no other song there has the same artist and title:
	otherwise one song would take the file of its namesake.
	"""
	stored = str(track.get("downloaded_path") or "").strip()
	if stored:
		stored_path = pathlib.Path(stored)
		if stored_path.is_file():
			return stored_path
	expected = expected_track_path(track, pathlib.Path(output_dir), fmt)
	if expected.is_file():
		return expected
	# Older rescans discarded prefix metadata. Recover only an unambiguous
	# exact filename suffix, never a fuzzy title match or another format.
	unprefixed = dict(track, filename_prefix_number=None)
	plain = expected_track_path(unprefixed, pathlib.Path(output_dir), fmt)
	listing = listing_cache.get(expected.parent) if listing_cache is not None else None
	if listing is None:
		listing = _unprefixed_listing(expected.parent)
		if listing_cache is not None:
			listing_cache[expected.parent] = listing
	matches = listing.get(plain.name, [])
	if len(matches) != 1:
		return expected
	if playlist_tracks is not None and _plain_name_key(track) in _shared_plain_names(playlist_tracks, listing_cache):
		return expected
	return matches[0]


def playlist_probes(playlist: dict) -> list[dict]:
	"""Copies of a playlist's songs carrying its current name, for `playlist_tracks=` in library_track_path."""
	name = str(playlist.get("name") or "Playlist")
	return [dict(track, playlist=name) for track in playlist.get("tracks", [])]


def _plain_name_key(track: dict) -> tuple[str, str]:
	"""Playlist folder and file name without position prefix (format left out), compared without case."""
	folder = sanitize_name(str(track.get("playlist") or "Playlist"))
	base = sanitize_name(f"{track.get('artists', '')} - {track.get('title', '')}")
	return (
		unicodedata.normalize("NFC", folder).casefold(),
		unicodedata.normalize("NFC", base).casefold(),
	)


def _shared_plain_names(tracks: list[dict], listing_cache: dict | None = None) -> set[tuple[str, str]]:
	"""Names (per playlist folder) that more than one song resolves to without its position prefix."""
	cache_key = ("shared-plain-names", id(tracks))
	if listing_cache is not None:
		cached = listing_cache.get(cache_key)
		if cached is not None and cached[0] is tracks:
			return cached[1]
	counts: dict[tuple[str, str], int] = {}
	for other in tracks:
		key = _plain_name_key(other)
		counts[key] = counts.get(key, 0) + 1
	shared = {key for key, count in counts.items() if count > 1}
	if listing_cache is not None:
		listing_cache[cache_key] = (tracks, shared)
	return shared


def _unprefixed_listing(folder: pathlib.Path) -> dict[str, list[pathlib.Path]]:
	listing: dict[str, list[pathlib.Path]] = {}
	try:
		for path in folder.iterdir():
			if path.is_file():
				name = unicodedata.normalize("NFC", re.sub(r"^\d+- ", "", path.name))
				listing.setdefault(name, []).append(path)
	except OSError:
		pass
	return listing


def _track_key(track: dict) -> str:
	base = _track_base_key(track)
	occurrence = int(track.get("playlist_occurrence") or 1)
	return f"{base}|occurrence:{occurrence}"


def _now() -> str:
	return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _playlist_key(playlist: dict) -> str:
	return f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}"
