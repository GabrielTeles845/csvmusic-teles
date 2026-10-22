# tabs only
"""The M3U lists the file the library really has, not only the file name it would choose today."""
import pathlib

from csvmusic.core.downloader import write_m3u
from csvmusic.core.library import write_library_m3us


def _shifted_playlist(root: pathlib.Path) -> list[dict]:
	"""Files saved when the songs were 1 and 2; a new song entered at the top and they became 2 and 3."""
	folder = root / "Minha Lista"
	folder.mkdir(parents=True)
	(folder / "01- A - Um.m4a").write_bytes(b"x")
	(folder / "02- B - Dois.m4a").write_bytes(b"x")
	(folder / "01- N - Nova.m4a").write_bytes(b"x")
	return [
		{"playlist": "Minha Lista", "artists": "N", "title": "Nova", "album": "", "filename_prefix_number": 1, "filename_prefix_width": 2},
		{"playlist": "Minha Lista", "artists": "A", "title": "Um", "album": "", "filename_prefix_number": 2, "filename_prefix_width": 2},
		{"playlist": "Minha Lista", "artists": "B", "title": "Dois", "album": "", "filename_prefix_number": 3, "filename_prefix_width": 2},
	]


def _entries(m3u: pathlib.Path) -> list[str]:
	return [line for line in m3u.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


def test_library_m3u_lists_files_found_without_the_current_prefix(tmp_path):
	tracks = _shifted_playlist(tmp_path)
	written = write_library_m3us(tracks, tmp_path, "m4a")
	assert _entries(written[0]) == ["01- N - Nova.m4a", "01- A - Um.m4a", "02- B - Dois.m4a"]


def test_write_m3u_uses_the_downloaded_path_when_the_expected_file_is_missing(tmp_path):
	folder = tmp_path / "Lista"
	folder.mkdir()
	real = folder / "07- A - Um.m4a"
	real.write_bytes(b"x")
	track = {"playlist": "Lista", "artists": "A", "title": "Um", "album": "", "filename_prefix_number": 3, "downloaded_path": str(real)}
	m3u = write_m3u(tmp_path, "Lista", [track], "m4a")
	assert _entries(m3u) == ["07- A - Um.m4a"]


def test_worker_m3u_keeps_songs_whose_file_has_an_older_prefix(monkeypatch, tmp_path):
	from csvmusic.ui import workers

	tracks = _shifted_playlist(tmp_path)
	written: list[list[str]] = []
	monkeypatch.setattr(
		workers, "write_m3u",
		lambda _root, _name, rows, _ext, **_kwargs: written.append([row["title"] for row in rows]) or (tmp_path / "x.m3u8"),
	)
	worker = workers.PipelineWorker(
		csv_path="", out_dir=str(tmp_path), playlist="Minha Lista", fmt="m4a", write_m3u8=True, write_m3u_plain=False,
		embed_art=False, yt_dlp_path=None, ffmpeg_path_override=None, cookies_browser=None,
		cookies_file=None, tracks_override=[tracks[0]], m3u_tracks_override=tracks, row_indices=[0],
	)
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: ({"videoId": "v", "title": "Nova", "artists": "N"}, 0.99, []))
	monkeypatch.setattr(workers, "cover_art_url_bytes", lambda _url: None)
	monkeypatch.setattr(workers, "yt_thumbnail_bytes", lambda _video_id: None)
	monkeypatch.setattr(workers, "tag_file", lambda *_args, **_kwargs: None)
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	monkeypatch.setattr(worker, "_download_with_profile", lambda _vid, destination, base, _profile, **_kw: destination / f"{base}.m4a")
	worker.run()
	assert written == [["Nova", "Um", "Dois"]]
