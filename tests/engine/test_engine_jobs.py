# tabs only
import shutil

import pytest

from csvmusic.core.library import enabled_tracks, load_library
from csvmusic.core.settings import load_settings, save_settings
from csvmusic.engine import EngineError

AGE_ERROR = "ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate for some users."


def _payload(engine, index: int, *, downloaded: bool = True, error: str | None = None, skipped: bool = False) -> dict:
	track = next(track for track in enabled_tracks(engine.library, {"spotify:big"}) if track["library_track_index"] == index)
	if downloaded:
		engine.write_song(index)
	return {
		"track": track, "downloaded": downloaded, "error": error, "skipped": skipped, "options": [],
		"match": {"videoId": "vid", "title": track["title"], "author": "Artist"} if downloaded else None,
		"low_confidence": False, "confidence": 0.9,
	}


def test_download_marks_queue_applies_results_and_saves_in_groups(make_engine):
	engine = make_engine(30)
	job = engine.start_download(["spotify:big"])
	worker = engine.download_worker
	assert worker.started and job["kind"] == "download" and job["total"] == 30
	assert job["current"]["phase"] == "matching" and job["current"]["index"] == 0
	assert engine.tracks("spotify:big", limit=3)["items"][1]["state"] == "queued"
	before = engine.library_path.read_bytes()

	worker.sig_row_status.emit(0, "Downloading (m4a)…")
	assert engine.job()["current"]["phase"] == "downloading"
	worker.sig_track_result.emit(0, _payload(engine, 0))
	worker.sig_progress.emit(1, 30)

	assert engine.library_path.read_bytes() == before
	assert engine.library_dirty and engine._save_timer.isActive()
	track_events = [event for event in engine.events_of("track") if event["track"]["index"] == 0]
	assert track_events[-1]["track"]["state"] == "downloaded"
	assert engine.events_of("playlist")[-1]["counts"]["downloaded"] == 1
	job = engine.job()
	assert job["processed"] == 1 and job["current"]["index"] == 1 and job["current"]["phase"] == "matching"
	assert job["eta_at"]

	worker.sig_done.emit("All tasks finished.", [{}], [], [])

	saved = load_library(engine.library_path)["playlists"][0]["tracks"]
	assert saved[0]["last_downloaded_at"]
	assert engine.job() == {"kind": None}
	assert engine.events_of("download_done")[-1] == {
		"done": 1, "skipped": 0, "failed": 0, "age_restricted": 0, "age_action": None, "stopped": False,
		"message": "Download terminado.",
	}
	assert engine.tracks("spotify:big", limit=2)["items"][1]["state"] == "missing"


def test_partial_m3u_is_written_during_the_batch(make_engine):
	from csvmusic.engine.engine import M3U_WRITE_EVERY_TRACKS
	engine = make_engine(30)
	engine.start_download(["spotify:big"])
	worker = engine.download_worker
	m3u = engine.output / "Big" / "Big.m3u8"
	for row in range(M3U_WRITE_EVERY_TRACKS - 1):
		worker.sig_track_result.emit(row, _payload(engine, row))
	assert not m3u.exists()
	worker.sig_track_result.emit(M3U_WRITE_EVERY_TRACKS - 1, _payload(engine, M3U_WRITE_EVERY_TRACKS - 1))
	entries = [line for line in m3u.read_text(encoding="utf-8").splitlines() if line.endswith(".m4a")]
	assert len(entries) == M3U_WRITE_EVERY_TRACKS


def test_skip_and_error_details_are_in_portuguese(make_engine):
	engine = make_engine(3)
	engine.start_download(["spotify:big"])
	worker = engine.download_worker
	skipped = _payload(engine, 0, downloaded=False, skipped=True)
	skipped["skip_reason"] = "No result with the right length"
	worker.sig_track_result.emit(0, skipped)
	worker.sig_track_result.emit(1, _payload(engine, 1, downloaded=False, error="ERROR: HTTP Error 429: Too Many Requests"))
	worker.sig_warning.emit("YouTube started throttling or blocking requests. Applying slower download pacing automatically.")
	items = {item["index"]: item for item in engine.tracks("spotify:big")["items"]}
	assert items[0]["state"] == "not_found" and items[0]["detail"].startswith("Nenhum resultado com a duração certa")
	assert items[1]["state"] == "error" and items[1]["detail"] == "O YouTube recusou por excesso de pedidos"
	assert engine.events_of("warning")[-1]["message"].startswith("O YouTube começou a frear")
	assert any(entry["message"].startswith("Artist — Song 1") for entry in engine.log_entries()["entries"])


def test_large_batch_needs_risk_confirmation(make_engine):
	engine = make_engine(260)
	with pytest.raises(EngineError) as error:
		engine.start_download(["spotify:big"])
	assert error.value.status == 409 and error.value.extra["needs_confirmation"] == "youtube_risk"
	assert engine.download_worker is None
	assert engine.start_download(["spotify:big"], confirm_risk=True)["total"] == 260


def test_scan_and_download_never_overlap(make_engine):
	engine = make_engine(3)
	engine.start_download(["spotify:big"])
	with pytest.raises(EngineError) as error:
		engine.start_scan(["spotify:big"])
	assert error.value.status == 409
	with pytest.raises(EngineError):
		engine.start_download(["spotify:big"])


def test_stop_reports_a_stopped_batch(make_engine):
	engine = make_engine(3)
	engine.start_download(["spotify:big"])
	worker = engine.download_worker
	assert engine.stop_download()["stopping"] is True and worker.stopped
	worker.sig_done.emit("Stopped (partial results saved).", [], [], [])
	assert engine.events_of("download_done")[-1]["stopped"] is True


def test_age_restricted_saved_session_is_switched_on_and_retry_downloads_only_those(make_engine):
	engine = make_engine(10)
	save_settings({"cookies_file": "/sessao/cookies.txt", "use_cookies": False})
	engine.start_download(["spotify:big"])
	worker = engine.download_worker
	track = enabled_tracks(engine.library, {"spotify:big"})[4]
	worker.sig_track_result.emit(4, {"track": track, "downloaded": False, "error": AGE_ERROR, "skipped": False})
	worker.sig_done.emit("All tasks finished.", [], [], [{"track": track, "error": AGE_ERROR}])
	done = engine.events_of("download_done")[-1]
	assert done["age_restricted"] == 1 and done["age_action"] == "enable_session"
	assert engine.tracks("spotify:big")["items"][4]["state"] == "age_limit"

	assert engine.resolve_age_restricted()["method"] == "enable_session"
	assert load_settings()["use_cookies"] is True
	engine.session_worker_factory.instances[-1].answer(True)

	assert engine.events_of("age_retry_ready") == [{"targets": 1}]
	assert engine.events_of("account")[-1]["ok"] is True
	job = engine.retry_age_restricted()
	assert job["total"] == 1
	assert engine.download_targets == {0: ("spotify:big", 4)}


def test_sign_in_saves_the_cookie_and_tests_it(make_engine, qt_application):
	engine = make_engine(1)
	engine.host.sign_in_result = "/novo/cookies.txt"
	assert engine.sign_in("popup") == {"started": True}
	qt_application.processEvents()
	cfg = load_settings()
	assert cfg["cookies_file"] == "/novo/cookies.txt" and cfg["use_cookies"] is True
	engine.session_worker_factory.instances[-1].answer(False, "NOT VERIFIED — x")
	account = engine.events_of("account")[-1]
	assert account["ok"] is False and account["message"].startswith("O YouTube não confirmou")
	signed_out = engine.sign_out()
	assert signed_out["connected"] is False and load_settings().get("cookies_file") is None


def test_download_now_uses_the_chosen_video_and_keeps_it(make_engine):
	engine = make_engine(3)
	job = engine.download_now("spotify:big", 2, "uLivzCQcQW8")
	assert job["kind"] == "download" and job["single"] is True
	worker = engine.single_worker_factory.instances[-1]
	assert worker.match["videoId"] == "uLivzCQcQW8"
	assert engine.library["playlists"][0]["tracks"][2]["preferred_video_id"] == "uLivzCQcQW8"
	payload = _payload(engine, 2)
	payload["match"] = worker.match
	worker.sig_finished.emit(0, payload)
	assert engine.job() == {"kind": None}
	assert engine.tracks("spotify:big")["items"][2]["state"] == "downloaded"
	assert engine.events_of("download_done")[-1]["done"] == 1


def test_direct_scan_merges_and_reports(make_engine):
	engine = make_engine(2, platform="deezer")
	job = engine.start_scan(["deezer:big"])
	assert job["kind"] == "scan" and job["name"] == "Big"
	worker = engine.direct_scan_worker_factory.instances[-1]
	worker.finished_scan.emit({
		"id": "big", "name": "Big", "platform": "deezer", "direct": True, "complete": True, "message": "",
		"reported_total": 3, "cover_url": None,
		"tracks": [{"title": f"Song {i}", "artists": "Artist", "sp_id": f"sp{i}"} for i in range(3)],
	})
	result = engine.events_of("scan_done")[-1]["results"][0]
	assert result["status"] == "ok" and result["captured"] == 3 and result["diff"]["added"] == 1
	assert engine.job() == {"kind": None}
	assert engine.playlist_summary("deezer:big")["counts"]["total"] == 3


def test_scan_failure_and_cancel(make_engine):
	engine = make_engine(2, platform="deezer")
	engine.start_scan(scope="all")
	engine.direct_scan_worker_factory.instances[-1].finished_scan.emit({"error": "Read timed out", "direct": True, "platform": "deezer"})
	result = engine.events_of("scan_done")[-1]["results"][0]
	assert result["status"] == "error" and result["message"].startswith("Sem resposta do serviço")

	engine.start_scan(["deezer:big"])
	engine.cancel_scan()
	engine.direct_scan_worker_factory.instances[-1].finished_scan.emit({
		"id": "big", "name": "Outra", "platform": "deezer", "direct": True, "complete": True, "tracks": [{"title": "X", "artists": "Y"}],
	})
	assert engine.playlist_summary("deezer:big")["counts"]["total"] == 2
	assert engine.job() == {"kind": None}


def test_closing_during_a_scan_does_not_merge_the_partial_result(make_engine):
	engine = make_engine(2, platform="deezer")
	engine.start_scan(["deezer:big"])
	engine.shutdown(wait_ms=0)
	engine.direct_scan_worker_factory.instances[-1].finished_scan.emit({
		"id": "big", "name": "Big", "platform": "deezer", "direct": True, "complete": False, "tracks": [{"title": "X", "artists": "Y"}],
	})
	assert len(load_library(engine.library_path)["playlists"][0]["tracks"]) == 2


def test_remove_playlist_sends_the_folder_to_the_trash_and_never_deletes(make_engine, monkeypatch):
	engine = make_engine(3)
	song = engine.write_song(0)

	def no_rmtree(*_args, **_kwargs):
		raise AssertionError("shutil.rmtree must never be used to remove a playlist")

	monkeypatch.setattr(shutil, "rmtree", no_rmtree)
	result = engine.remove_playlist("spotify:big", "trash")

	folder = (engine.output / "Big").resolve()
	assert result == {"removed": True, "trashed_folder": str(folder)}
	assert engine.trashed == [folder]
	assert song.exists()
	assert load_library(engine.library_path)["playlists"] == []
	assert engine.events_of("playlists")[-1] == {"ids": ["spotify:big"]}


def test_remove_playlist_with_qt_trash_moves_instead_of_deleting(make_engine, monkeypatch):
	from PySide6.QtCore import QFile
	from csvmusic.engine import trash
	engine = make_engine(2)
	engine.write_song(0)
	moved = []
	monkeypatch.setattr(QFile, "moveToTrash", staticmethod(lambda path: (moved.append(path), (True, "/Users/x/.Trash/Big"))[1]))
	engine.trash_mover = trash.move_to_system_trash
	result = engine.remove_playlist("spotify:big", "trash")
	assert moved == [str((engine.output / "Big").resolve())]
	assert result["trashed_folder"]


def test_remove_playlist_refuses_a_shared_folder_and_can_keep_files(make_engine):
	engine = make_engine(2)
	engine.write_song(0)
	copy = dict(engine.library["playlists"][0], id="other", tracks=[])
	engine.library["playlists"].append(copy)
	with pytest.raises(EngineError) as error:
		engine.remove_playlist("spotify:big", "trash")
	assert error.value.status == 409 and engine.trashed == []
	assert engine.remove_playlist("spotify:other", "keep") == {"removed": True, "trashed_folder": None}
	assert engine.trashed == []


def test_internal_trash_is_emptied_into_the_system_trash(make_engine):
	from csvmusic.core.downloader import TRASH_DIR_NAME
	engine = make_engine(1)
	folder = engine.output / "Big" / TRASH_DIR_NAME
	folder.mkdir(parents=True)
	(folder / "old.m4a").write_bytes(b"1234")
	assert engine.trash_stats() == {"files": 1, "bytes": 4}
	assert engine.empty_trash() == {"moved": 1}
	assert engine.trashed == [folder / "old.m4a"]
	assert (folder / "old.m4a").exists()


def test_job_events_are_throttled(make_engine):
	engine = make_engine(3)
	engine.start_download(["spotify:big"])
	count = len(engine.events_of("job"))
	for _ in range(20):
		engine.download_worker.sig_row_status.emit(0, "Downloading (m4a)…")
	assert len(engine.events_of("job")) == count
	assert engine._job_timer.isActive()


def test_repeated_song_is_queued_once_keeping_the_hand_picked_row(make_engine):
	engine = make_engine(3)
	tracks = engine.library["playlists"][0]["tracks"]
	tracks[2].update(title=tracks[1]["title"], artists=tracks[1]["artists"], sp_id=tracks[1]["sp_id"], playlist_occurrence=2)
	tracks[2].update(preferred_video_id="handpicked1", preferred_selection_locked=True)
	engine.start_download(["spotify:big"])
	queued = engine.download_worker.kwargs["tracks_override"]
	assert [track["library_track_index"] for track in queued] == [0, 2]


def test_namesake_song_does_not_count_the_other_ones_file(make_engine):
	engine = make_engine(2)
	tracks = engine.library["playlists"][0]["tracks"]
	tracks[1].update(title=tracks[0]["title"], sp_id="live-version")
	plain = engine.output / "Big" / f"{tracks[0]['artists']} - {tracks[0]['title']}.m4a"
	plain.parent.mkdir(parents=True, exist_ok=True)
	plain.write_bytes(b"audio")
	tracks[0]["filename_prefix_number"] = 1
	tracks[1]["filename_prefix_number"] = 2
	engine._paths_cache.clear()
	counts = engine.playlist_summary("spotify:big")["counts"]
	assert counts["downloaded"] == 0 and counts["missing"] == 2
