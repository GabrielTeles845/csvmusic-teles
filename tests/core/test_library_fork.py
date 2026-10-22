# tabs only
"""Library behavior added in the fork (kept apart from the upstream test_library.py)."""
from csvmusic.core.library import add_playlist_urls, merge_playlist_scan, new_library


URL = "https://open.spotify.com/playlist/611N3KSs459UD5IVPH1ES4"
PLAYLIST_ID = "spotify:611N3KSs459UD5IVPH1ES4"


def _library_with_playlist() -> dict:
	library = new_library()
	add_playlist_urls(library, [URL])
	return library


def test_scan_keeps_duration_source_and_precision():
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{
		"id": "one", "title": "Song", "artists": "Artist", "duration_ms": 215000,
		"duration_source": "csv", "duration_precision_s": 1,
	}])
	track = library["playlists"][0]["tracks"][0]
	assert track["duration_ms"] == 215000
	assert track["duration_source"] == "csv"
	assert track["duration_precision_s"] == 1


def test_rescan_without_duration_keeps_previous_duration():
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{
		"id": "one", "title": "Song", "artists": "Artist", "duration_ms": 215000,
		"duration_source": "spotify", "duration_precision_s": 1,
	}])
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{"id": "one", "title": "Song", "artists": "Artist"}])
	track = library["playlists"][0]["tracks"][0]
	assert track["duration_ms"] == 215000
	assert track["duration_source"] == "spotify"
	assert track["duration_precision_s"] == 1


def test_rescan_with_new_duration_replaces_previous_one():
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{
		"id": "one", "title": "Song", "artists": "Artist", "duration_ms": 215000, "duration_source": "csv",
	}])
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{
		"id": "one", "title": "Song", "artists": "Artist", "duration_ms": 216500, "duration_source": "spotify",
	}])
	track = library["playlists"][0]["tracks"][0]
	assert track["duration_ms"] == 216500
	assert track["duration_source"] == "spotify"


def test_skip_is_recorded_with_reason_and_date_and_survives_rescan():
	from csvmusic.core.library import SKIP_NOT_FOUND_ON_YOUTUBE, apply_library_download_result, describe_skip, enabled_tracks
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{"id": "one", "title": "Song", "artists": "Artist"}])
	track = enabled_tracks(library)[0]

	stored = apply_library_download_result(
		library, PLAYLIST_ID, track, downloaded=False, skipped=True, skip_reason=describe_skip([{"videoId": "x"}], 0.42),
	)

	assert stored["skip_state"] == SKIP_NOT_FOUND_ON_YOUTUBE
	assert stored["skip_reason"] == "No confident match on YouTube Music (best score 0.42)"
	assert stored["skipped_at"]
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{"id": "one", "title": "Song", "artists": "Artist"}])
	assert library["playlists"][0]["tracks"][0]["skip_state"] == SKIP_NOT_FOUND_ON_YOUTUBE


def test_successful_download_clears_recorded_skip():
	from csvmusic.core.library import apply_library_download_result, describe_skip, enabled_tracks
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{"id": "one", "title": "Song", "artists": "Artist"}])
	track = enabled_tracks(library)[0]
	apply_library_download_result(library, PLAYLIST_ID, track, downloaded=False, skipped=True, skip_reason=describe_skip([], 0))
	assert library["playlists"][0]["tracks"][0]["skip_reason"] == "No search results on YouTube Music"

	stored = apply_library_download_result(library, PLAYLIST_ID, track, downloaded=True, match={"videoId": "v"})

	assert stored["skip_state"] is None and stored["skip_reason"] is None and stored["skipped_at"] is None
