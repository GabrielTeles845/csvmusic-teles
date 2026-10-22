# tabs only
"""Motor com workers falsos: nenhum teste acessa a rede nem a Lixeira de verdade."""
import json
import pathlib

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal

from csvmusic.core import settings as settings_store
from csvmusic.core.library import new_library, save_library


class FakePipelineWorker(QObject):
	sig_log = Signal(str)
	sig_warning = Signal(str)
	sig_total = Signal(int)
	sig_match_stats = Signal(int, int)
	sig_row_status = Signal(int, str)
	sig_progress = Signal(int, int)
	sig_done = Signal(str, list, list, list)
	sig_track_result = Signal(int, dict)
	instances: list = []

	def __init__(self, *args, **kwargs):
		super().__init__(kwargs.get("parent"))
		self.args = args
		self.kwargs = kwargs
		self.started = False
		self.stopped = False
		FakePipelineWorker.instances.append(self)

	def start(self):
		self.started = True

	def isRunning(self):
		return self.started

	def stop(self):
		self.stopped = True

	def wait(self, *_args):
		return True


class FakeSingleWorker(QObject):
	sig_status = Signal(int, str)
	sig_finished = Signal(int, dict)
	instances: list = []

	def __init__(self, row, track, match, *args, **kwargs):
		super().__init__(kwargs.get("parent"))
		self.track = track
		self.match = match
		self.started = False
		FakeSingleWorker.instances.append(self)

	def start(self):
		self.started = True

	def isRunning(self):
		return self.started

	def wait(self, *_args):
		return True


class FakeSessionWorker(QObject):
	sig_done = Signal(bool, str)
	finished = Signal()
	instances: list = []

	def __init__(self, path, parent=None):
		super().__init__(parent)
		self.path = path
		self.started = False
		FakeSessionWorker.instances.append(self)

	def start(self):
		self.started = True

	def isRunning(self):
		return False

	def wait(self, *_args):
		return True

	def answer(self, ok: bool, message: str = "PASS"):
		self.sig_done.emit(ok, message)
		self.finished.emit()


class FakeDirectScanWorker(QObject):
	finished_scan = Signal(object)
	instances: list = []

	def __init__(self, url, platform, parent=None, *, source_id=""):
		super().__init__(parent)
		self.url = url
		self.platform = platform
		self.source_id = source_id
		self.started = False
		FakeDirectScanWorker.instances.append(self)

	def start(self):
		self.started = True

	def isRunning(self):
		return False

	def wait(self, *_args):
		return True


class FakeHost:
	def __init__(self):
		self.sign_in_result: str | None = None
		self.folder: str | None = None
		self.opened: list[str] = []
		self.revealed: list[str] = []

	def choose_folder(self, purpose, start=""):
		return self.folder

	def choose_file(self, purpose):
		return None

	def save_file(self, purpose, suggested=""):
		return None

	def youtube_sign_in(self, method):
		return self.sign_in_result

	def create_spotify_reader(self):
		return None

	def show_spotify_reader(self, reader):
		pass

	def hide_spotify_reader(self, reader):
		pass

	def open_path(self, path):
		self.opened.append(path)
		return True

	def reveal_path(self, path):
		self.revealed.append(path)
		return True


def make_library(folder: pathlib.Path, count: int = 30, *, platform: str = "spotify", name: str = "Big") -> tuple[pathlib.Path, pathlib.Path]:
	data_dir = folder / "data"
	data_dir.mkdir(parents=True, exist_ok=True)
	output = folder / "out"
	library = new_library(output_dir=str(output))
	library["format"] = "m4a"
	library["playlists"].append({
		"id": "big", "platform": platform, "source_type": "playlist", "url": "https://open.spotify.com/playlist/big",
		"name": name, "last_scanned_at": "2026-10-22T00:00:00+00:00", "reported_total": count,
		"scan_warning": None, "cover_url": None,
		"tracks": [
			{"title": f"Song {i}", "artists": "Artist", "album": "", "sp_id": f"sp{i}", "track_no": i + 1,
			 "playlist_occurrence": 1, "cover_url": f"https://i.scdn.co/image/{i}", "duration_ms": 200000}
			for i in range(count)
		],
	})
	path = data_dir / "library.json"
	save_library(path, library)
	return path, output


@pytest.fixture
def engine_env(monkeypatch, tmp_path):
	monkeypatch.setenv("CSVMUSIC_DATA_DIR", str(tmp_path / "data"))
	settings_store._reset_for_tests()
	(tmp_path / "data").mkdir(parents=True, exist_ok=True)
	(tmp_path / "data" / "settings.json").write_text(json.dumps({"hide_startup_disclaimer": True}), encoding="utf-8")
	for fake in (FakePipelineWorker, FakeSingleWorker, FakeSessionWorker, FakeDirectScanWorker):
		fake.instances = []
	yield tmp_path
	settings_store._reset_for_tests()


@pytest.fixture
def make_engine(engine_env):
	from csvmusic.engine import Engine
	created = []

	def factory(count: int = 30, **kwargs):
		path, output = make_library(engine_env, count, **kwargs)
		host = FakeHost()
		engine = Engine(host=host, library_path=path)
		engine.pipeline_worker_factory = FakePipelineWorker
		engine.single_worker_factory = FakeSingleWorker
		engine.session_worker_factory = FakeSessionWorker
		engine.direct_scan_worker_factory = FakeDirectScanWorker
		engine.trashed = []
		engine.trash_mover = lambda target: engine.trashed.append(pathlib.Path(target)) or None
		engine.mp3_check = lambda: True
		events: list[tuple[str, dict]] = []
		engine.add_listener(lambda kind, data: events.append((kind, data)))
		engine.events = events
		engine.output = output
		engine.write_song = lambda index, playlist_id="spotify:big": write_song(engine, index, playlist_id)
		engine.events_of = lambda kind: events_of(engine, kind)
		created.append(engine)
		return engine

	yield factory
	for engine in created:
		engine._save_timer.stop()
		engine._job_timer.stop()
		engine.deleteLater()
	QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def write_song(engine, index: int, playlist_id: str = "spotify:big") -> pathlib.Path:
	from csvmusic.core.library import enabled_tracks
	from csvmusic.core.track_output import expected_track_path
	track = next(track for track in enabled_tracks(engine.library, {playlist_id}) if track["library_track_index"] == index)
	path = expected_track_path(track, engine.output, "m4a")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_bytes(b"audio")
	return path


def events_of(engine, kind: str) -> list[dict]:
	return [data for event, data in engine.events if event == kind]
