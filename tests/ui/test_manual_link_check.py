# tabs only
"""Song Settings: a pasted YouTube link is looked up and checked before saving (no network)."""
import pytest
from PySide6.QtCore import QObject, Signal

from csvmusic.ui import library_mode


class _FakeAlternatives(QObject):
	sig_done = Signal(int, list, str)

	def __init__(self, *_args, parent=None, **_kwargs):
		super().__init__(parent)

	def start(self):
		self.sig_done.emit(0, [
			{"videoId": "uLivzCQcQW8", "title": "Country House", "author": "Blur", "source": "music", "duration_seconds": 237},
			{"videoId": "gpuh1WE-RVw", "title": "Country House", "author": "Blur", "source": "videos", "duration_seconds": 290, "duration_mismatch": True},
		], "")

	def isRunning(self):
		return False


VIDEOS = {
	"gpuh1WE-RVw": {"videoId": "gpuh1WE-RVw", "title": "Country House", "author": "Blur", "duration_seconds": 232, "kind": "music_video", "playable": True, "age_restricted": False, "reason": ""},
	"uLivzCQcQW8": {"videoId": "uLivzCQcQW8", "title": "Country House", "author": "Blur", "duration_seconds": 237, "kind": "song", "playable": True, "age_restricted": False, "reason": ""},
}


class _FakeVideoInfo(QObject):
	sig_done = Signal(str, dict, str)
	started: list = []

	def __init__(self, video_id, parent=None):
		super().__init__(parent)
		self.video_id = video_id

	def start(self):
		_FakeVideoInfo.started.append(self.video_id)
		info = VIDEOS.get(self.video_id)
		self.sig_done.emit(self.video_id, info or {}, "" if info else "offline")

	def isRunning(self):
		return False


@pytest.fixture
def dialog(monkeypatch):
	monkeypatch.setattr(library_mode, "AlternativesFetchWorker", _FakeAlternatives)
	monkeypatch.setattr(library_mode, "VideoInfoWorker", _FakeVideoInfo)
	_FakeVideoInfo.started = []
	track = {"title": "Country House - 2012 Remaster", "artists": "Blur", "duration_ms": 237500, "duration_precision_s": 1}
	widget = library_mode.TrackAlternativesDialog(track)
	yield widget
	widget.deleteLater()


def _paste(widget, text):
	widget.manual.setText(text)
	widget.manual_check_timer.stop()
	widget._check_manual_link()


def test_pasted_music_video_shows_warning_and_details(dialog):
	_paste(dialog, "https://www.youtube.com/watch?v=gpuh1WE-RVw")
	assert dialog.pending_match.text() == "New selection: Country House — Blur · 3:52 · official music video"
	assert "music video" in dialog.manual_check.text()
	assert not dialog.manual_check.isHidden()


def test_pasted_studio_song_is_confirmed(dialog):
	_paste(dialog, "https://music.youtube.com/watch?v=uLivzCQcQW8&si=abc")
	assert dialog.manual_check.text() == "✓ Same song, same length."


def test_invalid_link_explains_without_lookup(dialog):
	_paste(dialog, "https://www.youtube.com/playlist?list=PL123")
	assert _FakeVideoInfo.started == []
	assert "one video" in dialog.manual_check.text()


def test_failed_lookup_still_allows_saving(dialog):
	_paste(dialog, "https://youtu.be/abcdefghijk")
	assert "You can still save it" in dialog.manual_check.text()
	saved = []
	dialog.selected.connect(lambda video_id, label, _gain: saved.append((video_id, label)))
	dialog._accept_choice()
	assert saved == [("abcdefghijk", "https://youtu.be/abcdefghijk")]


def test_saved_label_uses_video_title_after_check(dialog):
	_paste(dialog, "https://www.youtube.com/watch?v=gpuh1WE-RVw")
	saved = []
	dialog.selected.connect(lambda video_id, label, _gain: saved.append((video_id, label)))
	dialog._accept_choice()
	assert saved == [("gpuh1WE-RVw", "Country House — Blur")]


def test_clearing_link_hides_check(dialog):
	_paste(dialog, "https://www.youtube.com/watch?v=gpuh1WE-RVw")
	dialog.manual.setText("")
	assert dialog.manual_check.isHidden()
	assert dialog.pending_match.text() == "New selection: No change"


def test_alternatives_show_length_and_wrong_length_mark(dialog):
	texts = [dialog.list.item(row).text() for row in range(dialog.list.count())]
	assert "3:57" in texts[0] and "WRONG LENGTH" not in texts[0]
	assert "4:50" in texts[1] and "⚠ WRONG LENGTH" in texts[1]
