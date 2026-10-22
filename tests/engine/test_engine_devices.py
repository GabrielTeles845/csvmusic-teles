# tabs only
"""Aparelhos: remover playlist e ejetar ocupam o aparelho como a sincronização (nada em paralelo no iTunesDB)."""
import threading
import types

import pytest

from csvmusic.engine import EngineError
from csvmusic.engine.workers import DeviceSyncWorker

DID = "abc123abc123"


def _with_fake_device(engine):
	device = types.SimpleNamespace(key="fake", name="PENDRIVE", kind="mass_storage", description="Pendrive", root="/Volumes/PENDRIVE")
	engine._devices = {DID: device}
	return device


def _run_in_thread(fn):
	box: dict = {}

	def run():
		try:
			box["result"] = fn()
		except Exception as exc:
			box["error"] = exc

	thread = threading.Thread(target=run, daemon=True)
	thread.start()
	return thread, box


def test_removing_a_playlist_blocks_sync_and_eject(make_engine, monkeypatch):
	import csvmusic.core.device_sync as device_sync
	engine = make_engine(2)
	_with_fake_device(engine)
	started, release = threading.Event(), threading.Event()

	def slow_delete(device, name):
		started.set()
		release.wait(5)

	monkeypatch.setattr(device_sync, "delete_device_playlist", slow_delete)
	monkeypatch.setattr(device_sync, "eject_device", lambda device: None)
	created = []
	engine.device_sync_worker_factory = lambda *args: created.append(args)
	thread, box = _run_in_thread(lambda: engine.delete_device_playlist(DID, "Big"))
	assert started.wait(5)
	assert engine.device_busy is True
	for call in (lambda: engine.start_device_sync(DID, ["spotify:big"]), lambda: engine.eject_device(DID), lambda: engine.delete_device_playlist(DID, "Outra")):
		with pytest.raises(EngineError) as error:
			call()
		assert error.value.status == 409
	assert created == []
	release.set()
	thread.join(5)
	assert box == {"result": {"removed": True}}
	assert engine.device_busy is False
	assert engine.eject_device(DID) == {"ok": True}
	assert engine.device_busy is False


def test_failed_removal_frees_the_device(make_engine, monkeypatch):
	import csvmusic.core.device_sync as device_sync
	engine = make_engine(2)
	_with_fake_device(engine)

	def broken(device, name):
		raise OSError("disk gone")

	monkeypatch.setattr(device_sync, "delete_device_playlist", broken)
	with pytest.raises(EngineError) as error:
		engine.delete_device_playlist(DID, "Big")
	assert error.value.status == 500 and engine.device_busy is False


def test_sync_worker_reads_its_own_copy_of_the_library(make_engine):
	engine = make_engine(2)
	device = _with_fake_device(engine)
	worker = DeviceSyncWorker(device, engine.library, {"spotify:big"})
	engine.library["playlists"][0]["tracks"][0]["title"] = "Mudou na tela"
	engine.library["playlists"][0]["tracks"].append({"title": "Nova"})
	copied = worker.library["playlists"][0]["tracks"]
	assert [track["title"] for track in copied] == ["Song 0", "Song 1"]
	worker.deleteLater()
