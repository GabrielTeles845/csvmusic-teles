# tabs only
import json
import pathlib

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QCloseEvent

from csvmusic.core.library import enabled_tracks, load_library, new_library, save_library
from csvmusic.core.track_output import expected_track_path
from csvmusic.ui import library_mode


def _make_library(home: pathlib.Path, count: int) -> tuple[pathlib.Path, pathlib.Path]:
	data_dir = home / "data"
	data_dir.mkdir(parents=True, exist_ok=True)
	output = home / "out"
	library = new_library(output_dir=str(output))
	library["format"] = "m4a"
	library["playlists"].append({
		"id": "big", "platform": "spotify", "source_type": "playlist", "url": "https://open.spotify.com/playlist/big",
		"name": "Big", "last_scanned_at": "2026-10-22T00:00:00+00:00", "reported_total": count,
		"scan_warning": None, "cover_url": None,
		"tracks": [
			{"title": f"Song {i}", "artists": "Artist", "album": "", "sp_id": f"sp{i}", "track_no": i + 1, "playlist_occurrence": 1}
			for i in range(count)
		],
	})
	path = data_dir / "library.json"
	save_library(path, library)
	(data_dir / "settings.json").write_text(json.dumps({"hide_startup_disclaimer": True}), encoding="utf-8")
	return path, output


class _QuietLibraryDialog(library_mode.LibraryModeDialog):
	"""No startup disclaimer, YouTube check or update check.

	Overridden in a subclass on purpose: monkeypatching these onto the class with lambdas made Python crash
	at shutdown, because PySide keeps a pointer to methods used in QTimer.singleShot after the patch is undone.
	"""

	def _show_startup_disclaimer(self) -> None:
		pass

	def _check_youtube_at_startup(self) -> None:
		pass

	def _start_update_check(self) -> None:
		pass


@pytest.fixture
def library_dialog(monkeypatch, tmp_path):
	# Point the app data folder at tmp_path. Changing the home variable here breaks later QtWebEngine tests.
	monkeypatch.setattr(library_mode, "settings_path", lambda: tmp_path / "data" / "settings.json")
	monkeypatch.setattr(library_mode, "load_settings", lambda: {"hide_startup_disclaimer": True})
	path, output = _make_library(tmp_path, 30)
	dialog = _QuietLibraryDialog()
	yield dialog, path, output
	dialog.library_save_timer.stop()
	dialog.deleteLater()
	QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _downloaded_payload(dialog, output: pathlib.Path, index: int) -> dict:
	track = enabled_tracks(dialog.library, {"spotify:big"})[index]
	file_path = expected_track_path(track, output, "m4a")
	file_path.parent.mkdir(parents=True, exist_ok=True)
	file_path.write_bytes(b"")
	return {
		"track": track, "downloaded": True, "error": None, "skipped": False, "options": [],
		"match": {"videoId": "vid", "title": track["title"], "author": "Artist"}, "low_confidence": False, "confidence": 0.9,
	}


def test_download_result_updates_one_row_without_full_redraw_or_disk_write(library_dialog, monkeypatch):
	dialog, path, output = library_dialog
	dialog.download_row_targets = {5: ("spotify:big", 5)}
	before_bytes = path.read_bytes()
	calls: list[str] = []
	monkeypatch.setattr(dialog, "_show_tracks", lambda: calls.append("show_tracks"))
	monkeypatch.setattr(dialog, "_refresh", lambda *args: calls.append("refresh"))
	monkeypatch.setattr(library_mode, "save_library", lambda *args: calls.append("save"))
	old_row_widget = dialog.track_tree.itemWidget(dialog.track_items[("spotify:big", 5)], 0)

	dialog._download_track_result(5, _downloaded_payload(dialog, output, 5))

	assert calls == []
	assert path.read_bytes() == before_bytes
	new_row_widget = dialog.track_tree.itemWidget(dialog.track_items[("spotify:big", 5)], 0)
	assert new_row_widget is not old_row_widget
	assert dialog.track_state_labels[("spotify:big", 5)].text() == "Downloaded"
	assert dialog.library_status_cache["playlists"]["spotify:big"]["downloaded"] == 1
	assert dialog.library_status_cache["playlists"]["spotify:big"]["missing"] == 29
	assert dialog.library_dirty
	assert dialog.library_save_timer.isActive()


def test_grouped_write_reaches_disk_on_flush_and_batch_end(library_dialog):
	dialog, path, output = library_dialog
	dialog.download_row_targets = {0: ("spotify:big", 0), 1: ("spotify:big", 1)}
	dialog._download_track_result(0, _downloaded_payload(dialog, output, 0))
	dialog._download_track_result(1, _downloaded_payload(dialog, output, 1))
	assert load_library(path)["playlists"][0]["tracks"][0].get("last_downloaded_at") is None

	dialog._download_done("All tasks finished.", [], [], [])

	saved = load_library(path)["playlists"][0]["tracks"]
	assert saved[0]["last_downloaded_at"] and saved[1]["last_downloaded_at"]
	assert not dialog.library_dirty
	assert not dialog.library_save_timer.isActive()


def test_close_writes_pending_results(library_dialog):
	dialog, path, output = library_dialog
	dialog.download_row_targets = {2: ("spotify:big", 2)}
	dialog._download_track_result(2, _downloaded_payload(dialog, output, 2))
	# Call the handler directly: close() on the last window would ask the shared test QApplication to quit.
	dialog.closeEvent(QCloseEvent())
	assert load_library(path)["playlists"][0]["tracks"][2]["last_downloaded_at"]


def test_m3u_is_written_during_the_batch_not_only_at_the_end(library_dialog):
	dialog, path, output = library_dialog
	dialog.download_m3u_tracks = enabled_tracks(dialog.library, {"spotify:big"})
	dialog.download_row_targets = {row: ("spotify:big", row) for row in range(30)}
	m3u = output / "Big" / "Big.m3u8"
	for row in range(library_mode.M3U_WRITE_EVERY_TRACKS - 1):
		dialog._download_track_result(row, _downloaded_payload(dialog, output, row))
	assert not m3u.exists()

	last = library_mode.M3U_WRITE_EVERY_TRACKS - 1
	dialog._download_track_result(last, _downloaded_payload(dialog, output, last))

	entries = [line for line in m3u.read_text(encoding="utf-8").splitlines() if line.endswith(".m4a")]
	assert len(entries) == library_mode.M3U_WRITE_EVERY_TRACKS


def test_unreadable_library_is_copied_and_never_overwritten(monkeypatch, tmp_path):
	monkeypatch.setattr(library_mode, "settings_path", lambda: tmp_path / "data" / "settings.json")
	monkeypatch.setattr(library_mode, "load_settings", lambda: {"hide_startup_disclaimer": True})
	path, _output = _make_library(tmp_path, 3)
	newer = json.loads(path.read_text(encoding="utf-8"))
	newer["version"] = 2
	original = json.dumps(newer)
	path.write_text(original, encoding="utf-8")

	dialog = _QuietLibraryDialog()
	try:
		assert dialog.library["playlists"] == []
		assert "version 2" in dialog.library_load_error
		dialog.urls_input.setText("https://open.spotify.com/playlist/611N3KSs459UD5IVPH1ES4")
		dialog._add_urls()
		dialog.closeEvent(QCloseEvent())

		assert path.read_text(encoding="utf-8") == original
		backups = list(path.parent.glob("library.json.unreadable-*.bak"))
		assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == original
	finally:
		dialog.deleteLater()
		QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_scan_cannot_start_while_a_download_runs(library_dialog, monkeypatch):
	dialog, path, output = library_dialog
	messages: list[str] = []
	monkeypatch.setattr(library_mode.QMessageBox, "information", lambda _parent, title, _text: messages.append(title))
	monkeypatch.setattr(dialog, "_downloads_running", lambda: True)
	monkeypatch.setattr(dialog, "_scan_next", lambda: messages.append("scan started"))

	dialog._begin_scan(list(dialog.library["playlists"]))

	assert messages == ["Download in Progress"]
	assert dialog.scan_dialog is None


def test_download_cannot_start_while_a_scan_runs(library_dialog, monkeypatch):
	dialog, path, output = library_dialog
	messages: list[str] = []
	monkeypatch.setattr(library_mode.QMessageBox, "information", lambda _parent, title, _text: messages.append(title))
	monkeypatch.setattr(dialog, "_scan_running", lambda: True)
	monkeypatch.setattr(dialog, "_open_settings", lambda **_kwargs: messages.append("settings opened") or False)

	dialog._start_download()

	assert messages == ["Scan Running"]


def test_library_selector_offers_opus_and_counts_use_library_format(library_dialog):
	dialog, path, output = library_dialog
	options = [dialog.format_combo.itemText(index) for index in range(dialog.format_combo.count())]
	assert options == ["m4a", "mp3", "opus"]
	track = enabled_tracks(dialog.library, {"spotify:big"})[0]
	opus_file = expected_track_path(track, output, "opus")
	opus_file.parent.mkdir(parents=True, exist_ok=True)
	opus_file.write_bytes(b"")

	dialog.format_combo.setCurrentText("opus")

	assert dialog.library["format"] == "opus"
	assert dialog.library_status_cache["playlists"]["spotify:big"]["downloaded"] == 1


def test_skipped_song_is_saved_and_shown_as_not_found(library_dialog):
	dialog, path, output = library_dialog
	dialog.download_row_targets = {3: ("spotify:big", 3)}
	track = enabled_tracks(dialog.library, {"spotify:big"})[3]
	payload = {
		"track": track, "downloaded": False, "error": None, "skipped": True,
		"options": [{"videoId": "x"}], "match": None, "confidence": 0.5,
	}

	dialog._download_track_result(3, payload)

	assert dialog.track_state_labels[("spotify:big", 3)].text() == "Not found"
	dialog._flush_library()
	saved = load_library(path)["playlists"][0]["tracks"][3]
	assert saved["skip_state"] == "not_found_on_youtube"
	assert "best score 0.50" in saved["skip_reason"]
