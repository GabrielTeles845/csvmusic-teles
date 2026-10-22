# tabs only
"""Fechar o app durante um download: o resultado da última música entra no library.json e nada cai."""
import threading

from PySide6.QtCore import QThread, Signal

from csvmusic.core.library import load_library
from csvmusic.engine import engine as engine_module


class _ThreadWorker(QThread):
	"""Worker de verdade (outra thread), sem rede: entrega um resultado depois de pedirem para parar."""

	sig_log = Signal(str)
	sig_warning = Signal(str)
	sig_progress = Signal(int, int)
	sig_row_status = Signal(int, str)
	sig_done = Signal(str, list, list, list)
	sig_track_result = Signal(int, dict)
	ignore_stop = False
	release = threading.Event()
	last = None

	def __init__(self, *args, **kwargs):
		super().__init__(kwargs.get("parent"))
		self.tracks = kwargs["tracks_override"]
		self._stop = threading.Event()
		type(self).last = self

	def stop(self):
		self._stop.set()

	def run(self):
		if self.ignore_stop:
			self.release.wait(10)
			return
		self._stop.wait(5)
		track = dict(self.tracks[0])
		self.sig_track_result.emit(0, {"track": track, "downloaded": True, "match": {"videoId": "abcdefghijk", "title": "T"}})
		self.sig_done.emit("Stopped (user)", [track], [], [])


def test_shutdown_saves_the_result_the_worker_sent_while_stopping(make_engine):
	engine = make_engine(3)
	engine.pipeline_worker_factory = _ThreadWorker
	engine.start_download(["spotify:big"])
	engine.shutdown()
	saved = load_library(engine.library_path)["playlists"][0]["tracks"][0]
	assert saved.get("downloaded_video_id") == "abcdefghijk"
	assert engine.download_worker is None


def test_worker_that_does_not_stop_is_kept_alive_and_logged(make_engine, monkeypatch):
	lines = []
	monkeypatch.setattr(engine_module, "log", lambda message: lines.append(message))

	class Stubborn(_ThreadWorker):
		ignore_stop = True
		release = threading.Event()

	engine = make_engine(3)
	engine.pipeline_worker_factory = Stubborn
	engine.start_download(["spotify:big"])
	worker = Stubborn.last
	engine.shutdown(wait_ms=50, extra_wait_ms=50)
	assert worker.isRunning()
	assert worker.parent() is None and worker in engine_module.lingering_workers()
	assert any("did not stop" in line for line in lines)
	Stubborn.release.set()
	assert worker.wait(5000)
	engine_module.lingering_workers().clear()
