# tabs only
"""Depois de uma nova análise a ordem das músicas muda: a tela não pode mexer na música errada."""
import pytest

from csvmusic.engine import EngineError

PID = "youtube_music:big"


def _rescan_with_new_song_on_top(engine) -> None:
	engine.start_scan([PID])
	worker = engine.direct_scan_worker_factory.instances[-1]
	tracks = [{"title": "Nova no topo", "artists": "X", "sp_id": "novo"}] + [dict(track) for track in engine.library["playlists"][0]["tracks"]]
	worker.finished_scan.emit({
		"id": "big", "name": "Big", "tracks": tracks, "reported_total": len(tracks), "complete": True,
		"platform": "youtube_music", "direct": True,
	})


def test_track_view_carries_a_stable_key(make_engine):
	engine = make_engine(3, platform="youtube_music")
	items = engine.tracks(PID)["items"]
	keys = [item["key"] for item in items]
	assert len(set(keys)) == 3 and all(keys)
	_rescan_with_new_song_on_top(engine)
	moved = engine.tracks(PID)["items"]
	assert moved[3]["key"] == keys[2] and moved[3]["title"] == "Song 2"


def test_rescan_tells_the_page_the_list_changed(make_engine):
	engine = make_engine(3, platform="youtube_music")
	_rescan_with_new_song_on_top(engine)
	assert engine.events_of("tracks_changed") == [{"playlist_id": PID}]


def test_stale_index_is_refused_with_409(make_engine):
	engine = make_engine(3, platform="youtube_music")
	old = engine.tracks(PID)["items"][2]
	_rescan_with_new_song_on_top(engine)
	calls = [
		lambda: engine.update_track(PID, 2, {"enabled": False, "key": old["key"]}),
		lambda: engine.accept_review(PID, 2, key=old["key"]),
		lambda: engine.download_now(PID, 2, "uLivzCQcQW8", key=old["key"]),
		lambda: engine.set_tracks_enabled(PID, False, indices=[2], keys=[old["key"]]),
		lambda: engine.start_download(targets=[(PID, 2, old["key"])]),
		lambda: engine.track_snapshot(PID, 2, key=old["key"]),
		lambda: engine.open_location("file", PID, 2, key=old["key"]),
	]
	for call in calls:
		with pytest.raises(EngineError) as error:
			call()
		assert error.value.status == 409
		assert error.value.message == "A playlist mudou; abra a música de novo."
	tracks = engine.library["playlists"][0]["tracks"]
	assert all(track.get("enabled", True) for track in tracks)
	assert not any(track.get("preferred_video_id") for track in tracks)


def test_matching_key_still_works(make_engine):
	engine = make_engine(3, platform="youtube_music")
	_rescan_with_new_song_on_top(engine)
	current = engine.tracks(PID)["items"][3]
	view = engine.update_track(PID, 3, {"enabled": False, "key": current["key"]})
	assert view["enabled"] is False and view["title"] == "Song 2"
	assert engine.set_tracks_enabled(PID, True, indices=[3], keys=[current["key"]]) == {"changed": 1}
