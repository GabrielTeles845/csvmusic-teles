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


def test_library_format_has_one_default_and_accepts_opus():
	from csvmusic.core.track_output import library_format
	assert library_format({}) == "m4a"
	assert library_format({"format": "OPUS"}) == "opus"
	assert library_format({"format": "wav"}) == "m4a"


def test_rescan_finds_existing_m4a_when_library_has_no_saved_format(tmp_path):
	from csvmusic.core.track_output import expected_track_path
	library = new_library(output_dir=str(tmp_path))
	add_playlist_urls(library, [URL])
	merge_playlist_scan(library, PLAYLIST_ID, "Mix", [{"id": "one", "title": "Song", "artists": "Artist"}])
	stored = dict(library["playlists"][0]["tracks"][0], playlist="Mix")
	audio = expected_track_path(stored, tmp_path, "m4a")
	audio.parent.mkdir(parents=True)
	audio.write_bytes(b"audio")

	merge_playlist_scan(library, PLAYLIST_ID, "Mix", [{"id": "one", "title": "Song", "artists": "Artist"}])

	# Library Mode downloads m4a by default; the rescan used to look for an .mp3 instead.
	assert library["playlists"][0]["tracks"][0]["downloaded_path"] == str(audio)


def test_library_of_another_version_raises_clear_error_and_backup_keeps_original(tmp_path):
	import json
	import pytest
	from csvmusic.core.library import LibraryVersionError, backup_library_file, load_library
	path = tmp_path / "library.json"
	original = json.dumps({"version": 2, "name": "Mine", "playlists": [{"id": "x"}]})
	path.write_text(original, encoding="utf-8")

	with pytest.raises(LibraryVersionError, match="version 2"):
		load_library(path)
	backup = backup_library_file(path)

	assert backup != path and backup.read_text(encoding="utf-8") == original
	assert path.read_text(encoding="utf-8") == original
	assert backup_library_file(path) != backup


def test_clear_access_error_reports_whether_anything_changed():
	from csvmusic.core.library import clear_playlist_access_error, mark_playlist_access_error
	library = _library_with_playlist()
	assert clear_playlist_access_error(library, PLAYLIST_ID) is False
	mark_playlist_access_error(library, PLAYLIST_ID, "private", "Playlist is private.")

	assert clear_playlist_access_error(library, PLAYLIST_ID) is True
	assert library["playlists"][0]["access_error"] is None
	assert library["playlists"][0]["access_error_message"] is None


def test_age_restricted_failure_is_named_and_cleared_on_success():
	from csvmusic.core.downloader import AgeRestrictedError, age_restriction_message
	from csvmusic.core.library import age_restricted_targets, apply_library_download_result, enabled_tracks
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", _songs("a", "b"))
	track = enabled_tracks(library)[1]
	error = str(AgeRestrictedError(age_restriction_message(using_cookies=True)))

	stored = apply_library_download_result(library, PLAYLIST_ID, track, downloaded=False, error=error)
	assert stored["failure_kind"] == "age_restricted"
	assert age_restricted_targets([{"track": track, "error": error}, {"track": enabled_tracks(library)[0], "error": "HTTP 500"}]) == {(PLAYLIST_ID, 1)}
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", _songs("a", "b"))
	assert library["playlists"][0]["tracks"][1]["failure_kind"] == "age_restricted"

	stored = apply_library_download_result(library, PLAYLIST_ID, track, downloaded=True, match={"videoId": "v"})
	assert stored["failure_kind"] is None


def _songs(*ids: str) -> list[dict]:
	return [{"id": song_id, "title": f"Song {song_id}", "artists": "Artist"} for song_id in ids]


def test_incomplete_scan_keeps_songs_that_fell_in_holes_at_their_place():
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", _songs("a", "b", "c", "d", "e"))
	library["playlists"][0]["tracks"][2]["preferred_video_id"] = "chosen"

	playlist = merge_playlist_scan(library, PLAYLIST_ID, "Playlist", _songs("a", "b", "e"), reported_total=5, complete=False)

	assert [track["sp_id"] for track in playlist["tracks"]] == ["a", "b", "c", "d", "e"]
	assert playlist["tracks"][2]["preferred_video_id"] == "chosen"
	assert playlist["last_diff"]["removed"] == 0
	assert playlist["last_diff"]["kept_from_incomplete_scan"] == 2


def test_complete_scan_still_removes_songs_gone_from_the_source():
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", _songs("a", "b", "c"))

	playlist = merge_playlist_scan(library, PLAYLIST_ID, "Playlist", _songs("a", "c"), reported_total=2, complete=True)

	assert [track["sp_id"] for track in playlist["tracks"]] == ["a", "c"]
	assert playlist["last_diff"]["removed"] == 1


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


def test_length_review_marks_song_for_review_with_reason():
	from csvmusic.core.library import apply_library_download_result, enabled_tracks
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{"id": "a", "title": "Song a", "artists": "Artist", "duration_ms": 200000}])
	track = enabled_tracks(library)[0]

	stored = apply_library_download_result(
		library, PLAYLIST_ID, track, downloaded=True, match={"videoId": "v"},
		downloaded_duration_ms=207000, duration_needs_review=True,
	)
	assert stored["low_confidence_review"] is True
	assert stored["review_reason"] == "File is 7 s longer than the song"
	assert stored["downloaded_duration_ms"] == 207000

	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", [{"id": "a", "title": "Song a", "artists": "Artist", "duration_ms": 200000}])
	kept = library["playlists"][0]["tracks"][0]
	assert kept["review_reason"] == "File is 7 s longer than the song"
	assert kept["downloaded_duration_ms"] == 207000


def test_worker_failure_kind_wins_over_error_text():
	from csvmusic.core.library import apply_library_download_result, enabled_tracks
	library = _library_with_playlist()
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", _songs("a"))
	stored = apply_library_download_result(
		library, PLAYLIST_ID, enabled_tracks(library)[0], downloaded=False,
		error="ERROR: [youtube] abc: This video is unavailable", failure_kind="age_restricted",
	)
	assert stored["failure_kind"] == "age_restricted"


def test_renamed_song_keeps_old_file_in_internal_trash(tmp_path):
	from csvmusic.core.downloader import TRASH_DIR_NAME
	from csvmusic.core.library import apply_library_download_result, enabled_tracks
	from csvmusic.core.track_output import expected_track_path, library_format
	library = _library_with_playlist()
	library["output_dir"] = str(tmp_path)
	merge_playlist_scan(library, PLAYLIST_ID, "Playlist", _songs("a"))
	track = enabled_tracks(library)[0]
	probe = dict(track, playlist="Playlist")
	new_file = expected_track_path(probe, tmp_path, library_format(library))
	new_file.parent.mkdir(parents=True, exist_ok=True)
	new_file.write_bytes(b"new audio")
	old_file = new_file.parent / "01- Old name.m4a"
	old_file.write_bytes(b"old audio")
	library["playlists"][0]["tracks"][0]["downloaded_path"] = str(old_file)

	apply_library_download_result(library, PLAYLIST_ID, track, downloaded=True, match={"videoId": "v"})

	assert not old_file.exists()
	kept = list((new_file.parent / TRASH_DIR_NAME).iterdir())
	assert len(kept) == 1 and kept[0].read_bytes() == b"old audio"
