# tabs only
"""The in-process yt-dlp (packaged app) must stop on Stop and on its time limit while it downloads.

A slow local HTTP server (127.0.0.1, no internet) stands in for YouTube.
"""
import http.server
import socketserver
import threading
import time

import pytest

from csvmusic.core import downloader
from csvmusic.core.paths import INTERNAL_YTDLP


_SERVER_SECONDS = 6


class _SlowAudio(http.server.BaseHTTPRequestHandler):
	def do_GET(self):
		self.send_response(200)
		self.send_header("Content-Type", "audio/mp4")
		self.send_header("Content-Length", str(_SERVER_SECONDS * 4096))
		self.end_headers()
		try:
			for _ in range(_SERVER_SECONDS):
				self.wfile.write(b"\0" * 4096)
				self.wfile.flush()
				time.sleep(1)
		except (BrokenPipeError, ConnectionResetError):
			pass

	do_HEAD = do_GET

	def log_message(self, *args):
		pass


@pytest.fixture()
def slow_url():
	server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SlowAudio)
	server.daemon_threads = True
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	yield f"http://127.0.0.1:{server.server_address[1]}/song.m4a"
	server.shutdown()
	server.server_close()


def _command(tmp_path, url):
	return [INTERNAL_YTDLP, "--no-part", "--socket-timeout", "5", "-o", str(tmp_path / "x.%(ext)s"), url]


def test_stop_ends_in_process_download_mid_transfer(tmp_path, slow_url):
	event = threading.Event()
	timer = threading.Timer(0.5, event.set)
	timer.start()
	started = time.monotonic()
	try:
		with pytest.raises(downloader.DownloadCancelled):
			with downloader.cancellation_scope(event):
				downloader._run_ytdlp_detail(_command(tmp_path, slow_url))
	finally:
		timer.cancel()
	assert time.monotonic() - started < 3.5


def test_time_limit_ends_in_process_download_mid_transfer(tmp_path, slow_url, monkeypatch):
	monkeypatch.setattr(downloader, "YTDLP_TIMEOUT_S", 1.0)
	started = time.monotonic()
	with pytest.raises(downloader.DownloadError):
		downloader._run_ytdlp_detail(_command(tmp_path, slow_url))
	assert time.monotonic() - started < 4.0
