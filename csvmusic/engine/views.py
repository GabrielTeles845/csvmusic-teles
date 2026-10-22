# tabs only
"""Objetos que a página recebe (PlaylistSummary, Track), sem Qt.

Regras do contrato (docs/fork/14-interface-web.md §4):
- `counts`: downloaded + missing + disabled = total; review, error, age_limit,
  not_found e queued são marcas dentro das músicas ativas.
- `state` de uma música: andamento do download primeiro, depois desmarcada,
  revisar, restrição de idade, erro, baixar de novo, baixada, não encontrada,
  faltando.
"""
from __future__ import annotations

import pathlib

from csvmusic.core.audio_quality import audio_quality
from csvmusic.core.library import FAILURE_AGE_RESTRICTED, library_track_path
from csvmusic.engine import texts

RUNTIME_STATES = ("queued", "matching", "downloading", "tagging")
FILTERS = ("all", "missing", "review", "error", "downloaded", "disabled", "not_found")
COUNT_FIELDS = ("total", "downloaded", "missing", "review", "error", "age_limit", "not_found", "disabled", "queued")


def playlist_key(playlist: dict) -> str:
	return f"{playlist.get('platform') or 'spotify'}:{playlist.get('id')}"


def track_has_error(track: dict) -> bool:
	return bool(track.get("download_error") or track.get("last_error") or track.get("error"))


def track_flags(track: dict, file_exists: bool) -> dict:
	enabled = bool(track.get("enabled", True))
	has_error = track_has_error(track)
	return {
		"enabled": enabled,
		"exists": file_exists,
		"review": bool(track.get("low_confidence_review")),
		"error": has_error,
		"age_limit": has_error and track.get("failure_kind") == FAILURE_AGE_RESTRICTED,
		"not_found": bool(track.get("skip_state")) and not file_exists and not has_error,
		"redownload": bool(track.get("force_redownload")),
	}


def track_state(track: dict, file_exists: bool, runtime_state: str | None = None) -> str:
	if runtime_state in RUNTIME_STATES:
		return runtime_state
	flags = track_flags(track, file_exists)
	if not flags["enabled"]:
		return "disabled"
	if flags["review"]:
		return "review"
	if flags["age_limit"]:
		return "age_limit"
	if flags["error"]:
		return "error"
	if flags["redownload"]:
		return "redownload"
	if file_exists:
		return "downloaded"
	if flags["not_found"]:
		return "not_found"
	return "missing"


def track_detail(track: dict, state: str) -> str | None:
	"""Frase curta da situação, sempre em português."""
	if state == "queued":
		return "Na fila"
	if state == "matching":
		return "Procurando no YouTube Music"
	if state == "downloading":
		return "Baixando"
	if state == "tagging":
		return "Gravando capa e dados"
	if state == "disabled":
		return "Desmarcada: não vai ser baixada"
	if state == "review":
		return texts.review_reason_pt(track.get("review_reason"))
	if state in ("age_limit", "error"):
		error = track.get("download_error") or track.get("last_error") or track.get("error")
		return texts.error_summary_pt(error, track.get("failure_kind"))[0]
	if state == "redownload":
		return "Vai ser baixada de novo no próximo download"
	if state == "not_found":
		skipped_on = str(track.get("skipped_at") or "")[:10]
		reason = texts.skip_reason_pt(track.get("skip_reason"))
		return f"{reason} ({_date_pt(skipped_on)})" if skipped_on else reason
	if state == "missing":
		return "Ainda não baixada"
	return None


def _date_pt(iso_date: str) -> str:
	parts = iso_date.split("-")
	if len(parts) == 3:
		return f"{parts[2]}/{parts[1]}/{parts[0]}"
	return iso_date


def _video_label(title: str, publisher: str) -> str:
	return f"{title} — {publisher}" if title and publisher else title


def track_view(
	playlist: dict, index: int, track: dict, file_path: pathlib.Path | None,
	runtime_state: str | None = None, *, with_quality: bool = True,
) -> dict:
	exists = bool(file_path and file_path.is_file())
	state = track_state(track, exists, runtime_state)
	downloaded = None
	if exists and (track.get("downloaded_video_id") or track.get("downloaded_video_title")):
		title = str(track.get("downloaded_video_title") or "").strip()
		if title.startswith(("http://", "https://")):
			title = str(track.get("title") or "").strip()
		downloaded = {
			"id": track.get("downloaded_video_id") or None,
			"title": title or None,
			"publisher": str(track.get("downloaded_video_publisher") or "").strip() or None,
		}
	preferred = None
	if track.get("preferred_video_id"):
		label = str(track.get("preferred_video_label") or "").strip()
		if not label or label.startswith(("http://", "https://")):
			label = _video_label(
				str(track.get("youtube_video_title") or "").strip(), str(track.get("youtube_video_author") or "").strip(),
			) or str(track["preferred_video_id"])
		preferred = {"id": str(track["preferred_video_id"]), "label": label}
	error = None
	raw_error = track.get("download_error") or track.get("last_error") or track.get("error")
	if raw_error:
		summary, advice = texts.error_summary_pt(raw_error, track.get("failure_kind"))
		error = {
			"summary": summary, "advice": advice, "technical": str(raw_error),
			"at": track.get("last_error_at") or None, "kind": track.get("failure_kind") or None,
		}
	quality = texts.quality_pt(audio_quality(file_path)) if exists and with_quality and file_path else None
	return {
		"index": index,
		"position": int(track.get("track_no") or (index + 1)),
		"title": str(track.get("title") or ""),
		"artists": str(track.get("artists") or ""),
		"album": str(track.get("album") or ""),
		"duration_ms": int(track.get("duration_ms") or 0) or None,
		"cover_url": track.get("cover_url") or None,
		"enabled": bool(track.get("enabled", True)),
		"state": state,
		"detail": track_detail(track, state),
		"downloaded_video": downloaded,
		"preferred_video": preferred,
		"volume_gain": int(track.get("audio_volume_gain", 0) or 0),
		"quality": quality,
		"file_path": str(file_path) if exists and file_path else None,
		"error": error,
	}


def empty_counts() -> dict:
	return {field: 0 for field in COUNT_FIELDS}


def add_to_counts(counts: dict, track: dict, file_exists: bool) -> None:
	flags = track_flags(track, file_exists)
	counts["total"] += 1
	if not flags["enabled"]:
		counts["disabled"] += 1
		return
	if file_exists:
		counts["downloaded"] += 1
	else:
		counts["missing"] += 1
	for field in ("review", "error", "age_limit", "not_found"):
		if flags[field]:
			counts[field] += 1
	if flags["redownload"]:
		counts["queued"] += 1


def matches_filter(track: dict, file_exists: bool, name: str) -> bool:
	flags = track_flags(track, file_exists)
	if name == "all":
		return True
	if name == "disabled":
		return not flags["enabled"]
	if not flags["enabled"]:
		return False
	if name == "missing":
		return not file_exists
	if name == "downloaded":
		return file_exists
	if name == "review":
		return flags["review"]
	if name == "error":
		return flags["error"]
	if name == "not_found":
		return flags["not_found"]
	return True


def matches_query(track: dict, query: str) -> bool:
	if not query:
		return True
	haystack = " ".join(str(track.get(field) or "") for field in (
		"title", "artists", "album", "downloaded_video_title", "downloaded_video_publisher",
	)).casefold()
	return all(word in haystack for word in query.casefold().split())


def cover_urls(playlist: dict, limit: int = 4) -> list[str]:
	seen: list[str] = []
	for track in playlist.get("tracks", []):
		url = str(track.get("cover_url") or "").strip()
		if url and url not in seen:
			seen.append(url)
			if len(seen) >= limit:
				break
	own = str(playlist.get("cover_url") or "").strip()
	if own and len(seen) < limit:
		return [own]
	return seen


def placeholder_name(playlist: dict) -> str:
	platform = playlist.get("platform") or "spotify"
	label = {
		"apple_music": "Apple Music", "youtube_music": "YouTube Music", "youtube": "YouTube",
		"csv": "planilha", "deezer": "Deezer", "amazon_music": "Amazon Music",
	}.get(str(platform), "Spotify")
	return f"Playlist do {label} ainda não analisada" if platform != "csv" else "Planilha ainda não analisada"


def playlist_name(playlist: dict) -> str:
	name = str(playlist.get("name") or "").strip()
	if not name or (name.startswith("Unscanned ") and not playlist.get("last_scanned_at")):
		return placeholder_name(playlist)
	return name


def playlist_view(playlist: dict, counts: dict, output_dir: str) -> dict:
	track_count = len(playlist.get("tracks", []))
	reported = playlist.get("reported_total")
	if not playlist.get("last_scanned_at"):
		scan_state = "never"
	elif playlist.get("scan_warning") or (reported and track_count < int(reported)):
		scan_state = "incomplete"
	else:
		scan_state = "ok"
	folder = None
	if output_dir:
		from csvmusic.core.downloader import sanitize_name
		folder = str(pathlib.Path(output_dir) / (sanitize_name(str(playlist.get("name") or "Playlist")) or "Playlist"))
	access_error = playlist.get("access_error") or None
	return {
		"id": playlist_key(playlist),
		"platform": str(playlist.get("platform") or "spotify"),
		"source_type": str(playlist.get("source_type") or "playlist"),
		"name": playlist_name(playlist),
		"url": playlist.get("url") or None,
		"cover_urls": cover_urls(playlist),
		"counts": dict(counts),
		"reported_total": int(reported) if reported else None,
		"last_scanned_at": playlist.get("last_scanned_at") or None,
		"scan_state": scan_state,
		"scan_warning": texts.scan_warning_pt(playlist.get("scan_warning")) if scan_state == "incomplete" else None,
		"access_error": access_error,
		"access_error_message": texts.scan_error_pt(playlist.get("access_error_message"), access_error) if access_error else None,
		"folder": folder,
	}


def resolve_track_path(playlist: dict, track: dict, output_dir: str, fmt: str, listing_cache: dict | None = None) -> pathlib.Path | None:
	if not output_dir:
		return None
	probe = dict(track)
	probe["playlist"] = playlist.get("name") or "Playlist"
	path = library_track_path(probe, pathlib.Path(output_dir), fmt, listing_cache=listing_cache)
	return path if path.is_file() else None
