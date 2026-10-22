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
