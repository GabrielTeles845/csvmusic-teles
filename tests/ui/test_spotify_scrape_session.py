import pytest

from csvmusic.core.spotify_import import PRIVATE_PLAYLIST_MESSAGE
from csvmusic.ui.spotify_public_scrape import SpotifyPublicScrapeDialog


@pytest.fixture
def qapp_dialog():
	dialog = SpotifyPublicScrapeDialog()
	yield dialog
	dialog.running = False
	dialog.timer.stop()
	dialog.deleteLater()


def test_late_baseline_from_cancelled_playlist_is_ignored(qapp_dialog):
	dialog = qapp_dialog
	emitted = []
	dialog.scrape_finished.connect(emitted.append)
	dialog.running = True
	dialog.session_id = "playlist-b"
	dialog.playlist_id = "BBBBBBBBBBBBBBBBBBBBBB"

	# Playlist A was cancelled; its request answers "private" after B started.
	dialog._baseline_finished(False, None, PRIVATE_PLAYLIST_MESSAGE, "https://open.spotify.com/playlist/A", "private", session="playlist-a")

	assert dialog.running
	assert dialog.baseline_error is None
	assert emitted == []


def test_private_baseline_reaches_library_with_error_kind(qapp_dialog):
	dialog = qapp_dialog
	emitted = []
	dialog.scrape_finished.connect(emitted.append)
	dialog.running = True
	dialog.session_id = "playlist-b"
	dialog.playlist_id = "BBBBBBBBBBBBBBBBBBBBBB"

	dialog._baseline_finished(False, None, PRIVATE_PLAYLIST_MESSAGE, "https://open.spotify.com/playlist/B", "private", session="playlist-b")

	assert len(emitted) == 1
	assert emitted[0]["id"] == "BBBBBBBBBBBBBBBBBBBBBB"
	assert emitted[0]["error_kind"] == "private"
	assert emitted[0]["error"] == PRIVATE_PLAYLIST_MESSAGE
	assert emitted[0]["tracks"] == []