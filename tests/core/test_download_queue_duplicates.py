# tabs only
"""A song repeated in a playlist goes to the download queue once: both rows share one file."""
import pathlib


def _song(**extra) -> dict:
	return {"title": "Song", "artists": "Artist", "playlist": "Mix", **extra}


def test_queue_keeps_one_row_per_output_file_preferring_the_hand_choice(tmp_path: pathlib.Path) -> None:
	from csvmusic.core.track_output import unique_output_rows

	first = _song(playlist_occurrence=1)
	chosen = _song(playlist_occurrence=2, preferred_video_id="hand", preferred_selection_locked=True)
	other = {"title": "Other", "artists": "Artist", "playlist": "Mix"}
	assert unique_output_rows([first, other, chosen], tmp_path, "m4a") == [other, chosen]
	assert unique_output_rows([chosen, first], tmp_path, "m4a") == [chosen]
	assert unique_output_rows([first, _song(playlist_occurrence=2)], tmp_path, "m4a") == [first]


def test_numbered_files_are_not_duplicates(tmp_path: pathlib.Path) -> None:
	from csvmusic.core.track_output import unique_output_rows

	rows = [_song(filename_prefix_number=1), _song(filename_prefix_number=2)]
	assert unique_output_rows(rows, tmp_path, "m4a") == rows


def test_library_download_queue_sends_a_repeated_song_once(tmp_path: pathlib.Path) -> None:
	from csvmusic.engine.workers import pending_download_tracks as _pending_download_tracks

	first = _song(playlist_occurrence=1)
	chosen = _song(playlist_occurrence=2, preferred_video_id="hand", preferred_selection_locked=True)
	pending = _pending_download_tracks(
		[first, chosen], tmp_path, "m4a", audio_signature="", audio_enabled=False, prefix_numbers=False,
	)
	assert pending == [chosen]
