"""Check a YouTube link the user chose by hand before it replaces the match.

The pasted link always wins over automatic matching; these checks only warn
when it looks like a music video, another song or a different length.
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List

from csvmusic.core.ytmusic_match import _duration_delta_s, _norm_text, _overlap_ratio, _toks, split_title


# Beyond this the pasted video is probably another version (intro, outro,
# live, radio edit). Same 10 s used to reject a download of the wrong length.
MANUAL_DURATION_WARN_SECONDS = 10
# Share of the song title's words that must appear in the video title.
MANUAL_TITLE_MIN_OVERLAP = 0.5

_VIDEO_KINDS = {
	"MUSIC_VIDEO_TYPE_ATV": "song",
	"MUSIC_VIDEO_TYPE_OMV": "music_video",
	"MUSIC_VIDEO_TYPE_UGC": "user_video",
	"MUSIC_VIDEO_TYPE_OFFICIAL_SOURCE_MUSIC": "song",
	"MUSIC_VIDEO_TYPE_PODCAST_EPISODE": "podcast",
}
_KIND_LABELS = {
	"song": "YouTube Music song",
	"music_video": "official music video",
	"user_video": "regular YouTube video",
	"podcast": "podcast episode",
	"unknown": "YouTube video",
}


def video_info_from_song(data: Dict, video_id: str = "") -> Dict:
	"""Turn a ytmusicapi get_song() answer into a small, flat description."""
	details = (data or {}).get("videoDetails") or {}
	playability = (data or {}).get("playabilityStatus") or {}
	try:
		seconds = int(details.get("lengthSeconds") or 0)
	except (TypeError, ValueError):
		seconds = 0
	status = str(playability.get("status") or "").upper()
	reason = str(playability.get("reason") or "").strip()
	age_restricted = status == "LOGIN_REQUIRED" or "age" in reason.casefold()
	return {
		"videoId": str(details.get("videoId") or video_id),
		"title": str(details.get("title") or "").strip(),
		"author": str(details.get("author") or "").strip(),
		"duration_seconds": seconds,
		"kind": _VIDEO_KINDS.get(str(details.get("musicVideoType") or ""), "unknown"),
		"playable": status in ("", "OK"),
		"age_restricted": age_restricted,
		"reason": reason,
	}


def fetch_video_info(video_id: str, yt=None) -> Dict:
	"""Look up one video on YouTube Music (network)."""
	if yt is None:
		from ytmusicapi import YTMusic
		yt = YTMusic()
	return video_info_from_song(yt.get_song(video_id), video_id)


def _format_seconds(seconds: int) -> str:
	return f"{seconds // 60}:{seconds % 60:02d}" if seconds > 0 else "?"


def describe_video(info: Dict) -> str:
	"""One line: title — channel · 3:57 · kind."""
	title = info.get("title") or info.get("videoId") or "Unknown video"
	author = info.get("author") or ""
	parts = [f"{title} — {author}" if author else title]
	if info.get("duration_seconds"):
		parts.append(_format_seconds(int(info["duration_seconds"])))
	parts.append(_KIND_LABELS.get(str(info.get("kind") or "unknown"), _KIND_LABELS["unknown"]))
	return " · ".join(parts)


def choice_warnings(track: Dict, info: Dict) -> List[str]:
	"""Reasons the chosen video may not be the right recording (empty when it looks fine)."""
	warnings: List[str] = []
	if info.get("age_restricted"):
		warnings.append("Age-restricted on YouTube: it only downloads with your YouTube account connected.")
	elif not info.get("playable", True):
		reason = info.get("reason") or "YouTube says it is unavailable."
		warnings.append(f"Not playable: {reason}")
	# The threshold forgives the song length's precision; the message shows
	# the plain difference the user can check against the two clocks.
	delta = _duration_delta_s(track, {"duration_seconds": info.get("duration_seconds")})
	if delta is not None and delta > MANUAL_DURATION_WARN_SECONDS:
		song_s = int(round((track.get("duration_ms") or 0) / 1000))
		difference = int(info.get("duration_seconds") or 0) - song_s
		longer = "longer" if difference > 0 else "shorter"
		warnings.append(f"{abs(difference)} s {longer} than the song ({_format_seconds(song_s)}). It may be a different version or have an intro.")
	kind = info.get("kind")
	if kind == "music_video":
		warnings.append("This is the music video. Videos often have extra intros, sound effects or a different mix; a YouTube Music song is usually cleaner.")
	elif kind == "podcast":
		warnings.append("This is a podcast episode, not a song.")
	if not _title_matches(track, info):
		warnings.append(f"The video title does not mention \"{split_title(track.get('title') or '')[0]}\".")
	return warnings


def _plain(value: str) -> str:
	# "Coração" and "Coracao" are the same title on YouTube.
	decomposed = unicodedata.normalize("NFKD", value or "")
	return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _title_matches(track: Dict, info: Dict) -> bool:
	core = _plain(split_title(track.get("title") or "")[0])
	wanted = _toks(core)
	if not wanted or not info.get("title"):
		return True
	title = _plain(info["title"])
	return _overlap_ratio(wanted, _toks(title)) >= MANUAL_TITLE_MIN_OVERLAP or _norm_text(core) in _norm_text(title)
