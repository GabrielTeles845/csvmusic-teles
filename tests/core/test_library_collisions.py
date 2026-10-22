# tabs only
"""Songs and playlists that share a name must never share files, state or folders."""
import pathlib

from csvmusic.core import library as L


def _rock_library(root: pathlib.Path) -> tuple[dict, pathlib.Path]:
	folder = root / "Rock"
	folder.mkdir(parents=True)
	album_file = folder / "01- Queen - Bohemian Rhapsody.m4a"
	album_file.write_bytes(b"versao do album")
	library = L.new_library(output_dir=str(root))
	library["format"] = "m4a"
	library["playlists"].append({"id": "p1", "platform": "spotify", "name": "Rock", "tracks": [{
		"title": "Bohemian Rhapsody", "artists": "Queen", "album": "A Night at the Opera", "sp_id": "SP1", "playlist": "Rock",
		"downloaded_path": str(album_file), "downloaded_video_id": "VID1", "preferred_video_id": "VID1",
		"preferred_selection_locked": True, "filename_prefix_number": 1, "filename_prefix_width": 2,
	}]})
	return library, album_file


def _scan(live_first: bool) -> list[dict]:
	album = {"title": "Bohemian Rhapsody", "artists": "Queen", "album": "A Night at the Opera", "sp_id": "SP1"}
	live = {"title": "Bohemian Rhapsody", "artists": "Queen", "album": "Live Aid", "sp_id": "SP2"}
	return [live, album] if live_first else [album, live]


def test_new_song_with_same_text_does_not_inherit_state_of_song_still_in_playlist(tmp_path):
	for live_first in (False, True):
		root = tmp_path / str(live_first)
		library, album_file = _rock_library(root)
		playlist = L.merge_playlist_scan(library, "spotify:p1", "Rock", _scan(live_first))
		by_id = {track["sp_id"]: track for track in playlist["tracks"]}
		assert by_id["SP1"]["downloaded_path"] == str(album_file)
		assert by_id["SP1"]["preferred_selection_locked"] is True
		live = by_id["SP2"]
		assert live["downloaded_path"] is None
		assert live["preferred_video_id"] is None
		assert live["preferred_selection_locked"] is False


def test_text_match_still_recovers_a_song_whose_id_changed(tmp_path):
	library, album_file = _rock_library(tmp_path)
	scan = [{"title": "Bohemian Rhapsody", "artists": "Queen", "album": "A Night at the Opera", "sp_id": "SP1-NEW"}]
	playlist = L.merge_playlist_scan(library, "spotify:p1", "Rock", scan)
	assert playlist["tracks"][0]["downloaded_path"] == str(album_file)


def test_status_does_not_count_other_songs_file_as_downloaded(tmp_path):
	library, album_file = _rock_library(tmp_path)
	L.merge_playlist_scan(library, "spotify:p1", "Rock", _scan(False))
	status = L.library_status(library, tmp_path, "m4a")
	assert status["totals"]["downloaded"] == 1
	assert status["totals"]["missing"] == 1


def test_downloading_one_song_never_trashes_the_file_of_its_namesake(tmp_path):
	library, album_file = _rock_library(tmp_path)
	playlist = L.merge_playlist_scan(library, "spotify:p1", "Rock", _scan(False))
	live = dict(playlist["tracks"][1], playlist="Rock", filename_prefix_number=2, filename_prefix_width=2)
	(tmp_path / "Rock" / "02- Queen - Bohemian Rhapsody.m4a").write_bytes(b"ao vivo")
	L.apply_library_download_result(library, "spotify:p1", live, downloaded=True, match={"videoId": "VID2"})
	assert album_file.read_bytes() == b"versao do album"


def test_unprefixed_fallback_is_refused_when_another_song_has_the_same_name(tmp_path):
	folder = tmp_path / "Rock"
	folder.mkdir()
	(folder / "01- Queen - Bohemian Rhapsody.m4a").write_bytes(b"x")
	first = {"title": "Bohemian Rhapsody", "artists": "Queen", "sp_id": "SP1", "playlist": "Rock"}
	second = {"title": "Bohemian Rhapsody", "artists": "Queen", "sp_id": "SP2", "playlist": "Rock"}
	alone = L.library_track_path(first, tmp_path, "m4a", playlist_tracks=[first])
	assert alone.name == "01- Queen - Bohemian Rhapsody.m4a"
	shared = L.library_track_path(second, tmp_path, "m4a", playlist_tracks=[first, second])
	assert not shared.exists()


def test_download_queue_does_not_skip_a_song_because_its_namesake_has_a_file(tmp_path):
	from csvmusic.ui.library_mode import _pending_download_tracks

	folder = tmp_path / "Rock"
	folder.mkdir()
	(folder / "01- Queen - Bohemian Rhapsody.m4a").write_bytes(b"x")
	first = {"title": "Bohemian Rhapsody", "artists": "Queen", "sp_id": "SP1", "playlist": "Rock", "filename_prefix_number": 1}
	second = {"title": "Bohemian Rhapsody", "artists": "Queen", "sp_id": "SP2", "playlist": "Rock"}
	pending = _pending_download_tracks(
		[first, second], tmp_path, "m4a", audio_signature="", audio_enabled=False, prefix_numbers=False, missing_only=True,
	)
	assert pending == [second]


def _two_favoritas() -> dict:
	library = L.new_library()
	L.add_playlist_urls(library, [
		"https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
		"https://open.spotify.com/playlist/0vvXsWCC9xrXsKd4FyS8kM",
	])
	return library


_FIRST, _SECOND = "spotify:37i9dQZF1DXcBWIGoYBM5M", "spotify:0vvXsWCC9xrXsKd4FyS8kM"


def test_two_playlists_with_the_same_name_get_separate_folders():
	library = _two_favoritas()
	L.merge_playlist_scan(library, _FIRST, "Favoritas", [{"title": "Um", "artists": "A"}])
	L.merge_playlist_scan(library, _SECOND, "favoritas", [{"title": "Dois", "artists": "B"}])
	names = [playlist["name"] for playlist in library["playlists"]]
	assert names == ["Favoritas", "favoritas (2)"]
	assert [track["playlist"] for track in L.enabled_tracks(library)] == names


def test_numbered_name_stays_put_on_rescan():
	library = _two_favoritas()
	L.merge_playlist_scan(library, _FIRST, "Favoritas", [{"title": "Um", "artists": "A"}])
	L.merge_playlist_scan(library, _SECOND, "Favoritas", [{"title": "Dois", "artists": "B"}])
	L.merge_playlist_scan(library, _FIRST, "Favoritas", [{"title": "Um", "artists": "A"}])
	L.merge_playlist_scan(library, _SECOND, "Favoritas", [{"title": "Dois", "artists": "B"}])
	assert [playlist["name"] for playlist in library["playlists"]] == ["Favoritas", "Favoritas (2)"]
	# The first one leaves: the second keeps its folder instead of jumping back to "Favoritas".
	library["playlists"].pop(0)
	L.merge_playlist_scan(library, _SECOND, "Favoritas", [{"title": "Dois", "artists": "B"}])
	assert library["playlists"][0]["name"] == "Favoritas (2)"


def test_rename_that_only_changes_letter_case_moves_folder_and_m3u(tmp_path):
	library = _two_favoritas()
	library["playlists"].pop()
	L.merge_playlist_scan(library, _FIRST, "favoritas", [{"title": "Um", "artists": "A"}])
	folder = tmp_path / "favoritas"
	folder.mkdir()
	(folder / "A - Um.m4a").write_bytes(b"x")
	(folder / "favoritas.m3u8").write_text("#EXTM3U\n#EXTPLAYLIST:favoritas\nA - Um.m4a\n", encoding="utf-8")

	_playlist, renamed = L.rename_library_playlist(library, _FIRST, "Favoritas", tmp_path)

	assert renamed is not None and renamed.name == "Favoritas"
	assert sorted(path.name for path in tmp_path.iterdir()) == ["Favoritas"]
	assert sorted(path.name for path in (tmp_path / "Favoritas").iterdir()) == ["A - Um.m4a", "Favoritas.m3u8"]
	assert "#EXTPLAYLIST:Favoritas" in (tmp_path / "Favoritas" / "Favoritas.m3u8").read_text(encoding="utf-8")


def test_names_that_only_match_after_sanitizing_also_collide():
	library = _two_favoritas()
	L.merge_playlist_scan(library, _FIRST, "Rock: 80s", [{"title": "Um", "artists": "A"}])
	L.merge_playlist_scan(library, _SECOND, "Rock： 80s", [{"title": "Dois", "artists": "B"}])
	assert library["playlists"][1]["name"] == "Rock： 80s (2)"
