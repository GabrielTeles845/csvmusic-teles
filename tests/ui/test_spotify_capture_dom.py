# tabs only
import json

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWebEngineCore import QWebEnginePage

from csvmusic.ui.spotify_public_scrape import _CAPTURE_SCRIPT


def test_capture_excludes_numeric_recommendation_and_sidebar_links(qt_application):
	page = QWebEnginePage()
	loop = QEventLoop()
	results = []
	def capture(_ok):
		script = _CAPTURE_SCRIPT.replace("__SHOULD_SCROLL__", "false")
		script = script.replace("__MIN_SCROLL_PX__", "100").replace("__SCROLL_MULTIPLIER__", "1")
		def done(value):
			results.append(value)
			loop.quit()
		page.runJavaScript(script, done)
	page.loadFinished.connect(capture)
	page.setHtml('''<html><body>
		<aside><div role="row"><a href="https://open.spotify.com/track/sidebar">45</a></div></aside>
		<main><h1>Playlist</h1><div data-testid="playlist-tracklist">
		<div role="row"><div role="gridcell" aria-colindex="1">1</div>
		<div role="gridcell"><a href="https://open.spotify.com/track/member">1979</a></div></div>
		</div><h2>Recomendaciones</h2><div role="row">
		<a href="https://open.spotify.com/track/recommendation">45</a></div></main>
		</body></html>''')
	deadline = QTimer()
	deadline.setSingleShot(True)
	deadline.timeout.connect(loop.quit)
	deadline.start(10000)
	loop.exec()
	deadline.stop()
	page.deleteLater()
	assert results, "Browser capture timed out"
	tracks = json.loads(results[0])["tracks"]
	assert [(track["id"], track["position"]) for track in tracks] == [("member", 1)]


def test_capture_reads_duration_column_from_row(qt_application):
	page = QWebEnginePage()
	loop = QEventLoop()
	results = []
	def capture(_ok):
		script = _CAPTURE_SCRIPT.replace("__SHOULD_SCROLL__", "false")
		script = script.replace("__MIN_SCROLL_PX__", "100").replace("__SCROLL_MULTIPLIER__", "1")
		def done(value):
			results.append(value)
			loop.quit()
		page.runJavaScript(script, done)
	page.loadFinished.connect(capture)
	page.setHtml('''<html><body><main><h1>Playlist</h1><div data-testid="playlist-tracklist">
		<div role="row"><div role="gridcell" aria-colindex="1">1</div>
		<div role="gridcell"><a href="https://open.spotify.com/track/first">Song 1:00 Edit</a>
		<div><a href="https://open.spotify.com/artist/x">Artist</a></div></div>
		<div role="gridcell"><a href="https://open.spotify.com/album/y">Album</a></div>
		<div role="gridcell">3 days ago</div>
		<div role="gridcell" aria-colindex="5">2:57</div></div>
		<div role="row"><div role="gridcell" aria-colindex="1">2</div>
		<div role="gridcell"><a href="https://open.spotify.com/track/long">Long</a></div>
		<div role="gridcell" aria-colindex="5">1:02:57</div></div>
		<div role="row"><div role="gridcell" aria-colindex="1">3</div>
		<div role="gridcell"><a href="https://open.spotify.com/track/none">No Time</a></div></div>
		</div></main></body></html>''')
	deadline = QTimer()
	deadline.setSingleShot(True)
	deadline.timeout.connect(loop.quit)
	deadline.start(10000)
	loop.exec()
	deadline.stop()
	page.deleteLater()
	assert results, "Browser capture timed out"
	tracks = json.loads(results[0])["tracks"]
	assert [(track["id"], track["duration"]) for track in tracks] == [("first", "2:57"), ("long", "1:02:57"), ("none", "")]
