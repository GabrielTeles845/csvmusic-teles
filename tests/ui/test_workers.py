import pathlib

from csvmusic.ui import workers


def test_pipeline_preserves_age_error_and_continues_next_track(monkeypatch, tmp_path):
	from csvmusic.core.downloader import AgeRestrictedError, age_restriction_message
	worker = _pipeline(tmp_path, force_download=True)
	worker.tracks_override.append(dict(worker.tracks_override[0], title="Next song"))
	worker.row_indices = [0, 1]
	results = []
	calls = []
	worker.sig_track_result.connect(lambda row, payload: results.append(payload))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	monkeypatch.setattr(worker, "_ordered_force_candidates", lambda *args: [{"videoId": "restricted"}, {"videoId": "other"}])
	message = age_restriction_message(using_cookies=False)
	def fail(video_id, *args, **_kwargs):
		calls.append(video_id)
		raise AgeRestrictedError(message)
	monkeypatch.setattr(worker, "_download_with_profile", fail)
	worker.run()
	assert calls == ["restricted", "restricted"]
	assert len(results) == 2
	assert all(result["downloaded"] is False and result["error"] == message for result in results)


def _pipeline(tmp_path: pathlib.Path, *, force_download: bool) -> workers.PipelineWorker:
	return workers.PipelineWorker(
		csv_path="",
		out_dir=str(tmp_path),
		playlist="Test Playlist",
		fmt="mp3",
		write_m3u8=False,
		write_m3u_plain=False,
		embed_art=False,
		yt_dlp_path=None,
		ffmpeg_path_override=None,
		cookies_browser=None,
		cookies_file=None,
		force_download=force_download,
		tracks_override=[{
			"title": "Complicated",
			"artists": "Avril Lavigne",
			"playlist": "Test Playlist",
			"duration_ms": 244000,
		}],
		row_indices=[0],
	)


def _low_confidence_result():
	option = {
		"videoId": "test-video",
		"title": "Complicated",
		"author": "Avril Lavigne",
		"source": "music",
		"score": 0.4,
	}
	return None, 0.4, [option]


def test_force_download_uses_best_low_confidence_candidate(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=True)
	results = []
	finished = []
	worker.sig_track_result.connect(lambda row, payload: results.append((row, payload)))
	worker.sig_done.connect(lambda message, done, skipped, failed: finished.append((message, done, skipped, failed)))

	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers, "yt_thumbnail_bytes", lambda _video_id: None)
	monkeypatch.setattr(workers, "tag_file", lambda *_args, **_kwargs: None)
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)

	def fake_download(_video_id, destination, base_name, _profile, **_kwargs):
		path = destination / f"{base_name}.mp3"
		path.write_bytes(b"audio")
		return path

	monkeypatch.setattr(worker, "_download_with_profile", fake_download)
	worker.run()

	assert len(results) == 1
	assert results[0][1]["downloaded"] is True
	assert results[0][1]["forced_match"] is True
	assert results[0][1]["match"]["videoId"] == "test-video"
	assert len(finished[0][1]) == 1
	assert finished[0][2] == []
	assert finished[0][3] == []


def test_low_confidence_candidate_is_skipped_without_force(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	results = []
	finished = []
	worker.sig_track_result.connect(lambda row, payload: results.append((row, payload)))
	worker.sig_done.connect(lambda message, done, skipped, failed: finished.append((message, done, skipped, failed)))

	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	worker.run()

	assert len(results) == 1
	assert results[0][1]["skipped"] is True
	assert results[0][1]["downloaded"] is False
	assert finished[0][1] == []
	assert len(finished[0][2]) == 1
	assert finished[0][3] == []


def test_track_volume_gain_is_added_to_global_processing(tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	worker.audio_processing = {"enabled": True, "normalize": True, "volume_gain": 2, "bass_gain": 1}
	worker._set_track_audio_processing({"audio_volume_gain": -5})

	assert worker._active_audio_processing == {
		"enabled": True,
		"normalize": True,
		"volume_gain": -3,
		"bass_gain": 1,
	}


def test_track_volume_gain_enables_processing_without_global_equalizer(tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	worker._set_track_audio_processing({"audio_volume_gain": 4})

	assert worker._active_audio_processing["enabled"] is True
	assert worker._active_audio_processing["volume_gain"] == 4


def test_library_artwork_falls_back_to_youtube_thumbnail(monkeypatch):
	track = {"cover_url": "https://example.invalid/cover.jpg", "library_path": "library.json"}
	monkeypatch.setattr(workers, "cover_art_url_bytes", lambda _url: None)
	monkeypatch.setattr(workers, "yt_thumbnail_bytes", lambda video_id: f"thumbnail:{video_id}".encode())

	assert workers._track_cover_bytes(track, "video-123") == b"thumbnail:video-123"


def test_source_artwork_is_preferred_over_youtube_thumbnail(monkeypatch):
	monkeypatch.setattr(workers, "cover_art_url_bytes", lambda _url: b"source-art")
	monkeypatch.setattr(workers, "yt_thumbnail_bytes", lambda _video_id: b"youtube-art")

	assert workers._track_cover_bytes({"cover_url": "https://example.test/cover.jpg"}, "video-123") == b"source-art"


def test_preferred_music_link_records_song_title_instead_of_url(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	worker.tracks_override[0]["preferred_video_id"] = "selected-video"
	worker.tracks_override[0]["preferred_video_label"] = "https://music.youtube.com/watch?v=selected-video"
	results = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "cover_art_url_bytes", lambda _url: None)
	monkeypatch.setattr(workers, "yt_thumbnail_bytes", lambda _video_id: None)
	monkeypatch.setattr(workers, "tag_file", lambda *_args, **_kwargs: None)
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)

	def fake_download(_video_id, destination, base_name, _profile, **_kwargs):
		path = destination / f"{base_name}.mp3"
		path.write_bytes(b"audio")
		return path

	monkeypatch.setattr(worker, "_download_with_profile", fake_download)
	worker.run()

	assert results[0]["downloaded"] is True
	assert results[0]["match"]["title"] == "Complicated"


def test_redownload_rewrites_m3u_from_complete_existing_manifest(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=True)
	current = worker.tracks_override[0]
	current["preferred_video_id"] = "replacement-video"
	current["preferred_video_label"] = "Replacement Video"
	existing = {
		"title": "Existing Song",
		"artists": "Artist",
		"playlist": "Test Playlist",
	}
	playlist_dir = tmp_path / "Test Playlist"
	playlist_dir.mkdir()
	(playlist_dir / "Artist - Existing Song.mp3").write_bytes(b"existing")
	worker.m3u_tracks_override = [existing, current]
	worker.write_m3u8 = True
	written = []
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "cover_art_url_bytes", lambda _url: None)
	monkeypatch.setattr(workers, "yt_thumbnail_bytes", lambda _video_id: None)
	monkeypatch.setattr(workers, "tag_file", lambda *_args, **_kwargs: None)
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	monkeypatch.setattr(workers, "write_m3u", lambda _root, _name, tracks, _ext, **_kwargs: written.append(list(tracks)) or (playlist_dir / "Test Playlist.m3u8"))

	def fake_download(_video_id, destination, base_name, _profile, **_kwargs):
		path = destination / f"{base_name}.mp3"
		path.write_bytes(b"replacement")
		return path

	monkeypatch.setattr(worker, "_download_with_profile", fake_download)
	worker.run()

	assert [[track["title"] for track in tracks] for tracks in written] == [["Existing Song", "Complicated"]]


def _wrong_length_result():
	option = {
		"videoId": "long-live-version",
		"title": "Complicated (Live)",
		"author": "Avril Lavigne",
		"source": "music",
		"score": 0.7,
		"duration_mismatch": True,
	}
	return None, 0.0, [option]


def test_wrong_length_results_do_not_abort_batch_as_empty_search(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	base = worker.tracks_override[0]
	worker.tracks_override = [dict(base, title=f"Song {n}") for n in range(7)]
	worker.row_indices = list(range(7))
	results = []
	warnings = []
	statuses = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	worker.sig_warning.connect(warnings.append)
	worker.sig_row_status.connect(lambda _row, status: statuses.append(status))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _wrong_length_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	worker.run()

	assert len(results) == 7
	assert all(result["skipped"] for result in results)
	assert not any("no results" in warning for warning in warnings)
	assert "Skipped (wrong length)" in statuses


def test_force_download_never_picks_wrong_length_result(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=True)
	results = []
	calls = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _wrong_length_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	monkeypatch.setattr(worker, "_download_with_profile", lambda video_id, *_args: calls.append(video_id))
	worker.run()

	assert calls == []
	assert results[0]["skipped"] is True
	assert results[0]["forced_match"] is False


def test_skipped_track_logs_real_queries_and_best_candidate(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	worker.tracks_override[0]["title"] = "Complicated - 2002 Remaster"
	lines = []
	monkeypatch.setattr(workers, "log", lines.append)
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	worker.run()

	skip_lines = [line for line in lines if line.startswith("match skip:")]
	assert len(skip_lines) == 1
	assert "'Complicated Avril Lavigne'" in skip_lines[0]
	assert "best='Complicated' by 'Avril Lavigne' (test-video;" in skip_lines[0]


def test_bot_check_switches_to_safe_mode_and_retries(monkeypatch, tmp_path):
	from csvmusic.core.downloader import YouTubeRiskError, YOUTUBE_MITIGATION_AGGRESSIVE
	worker = _pipeline(tmp_path, force_download=False)
	worker.tracks_override[0]["preferred_video_id"] = "selected-video"
	results = []
	warnings = []
	profiles = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	worker.sig_warning.connect(warnings.append)
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "cover_art_url_bytes", lambda _url: None)
	monkeypatch.setattr(workers, "yt_thumbnail_bytes", lambda _video_id: None)
	monkeypatch.setattr(workers, "tag_file", lambda *_args, **_kwargs: None)
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)

	def fake_download(_video_id, destination, base_name, profile, **_kwargs):
		profiles.append(profile.label)
		if len(profiles) == 1:
			raise YouTubeRiskError("YouTube asked for bot verification: Try Firefox cookies", "YouTube asked for bot verification")
		path = destination / f"{base_name}.mp3"
		path.write_bytes(b"audio")
		return path

	monkeypatch.setattr(worker, "_download_with_profile", fake_download)
	worker.run()

	assert profiles == ["normal", YOUTUBE_MITIGATION_AGGRESSIVE.label]
	assert results[0]["downloaded"] is True
	assert len(warnings) == 1 and "YouTube asked for bot verification" in warnings[0]


def test_skipped_tracks_do_not_wait_between_tracks(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	worker.tracks_override += [dict(worker.tracks_override[0], title=f"Song {n}") for n in range(3)]
	worker.row_indices = [0, 1, 2, 3]
	sleeps = []
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers.time, "sleep", sleeps.append)
	worker.run()

	assert sleeps == []


def _fake_download_tools(monkeypatch, *, payload=b"new audio", codec="aac", duration_s=244.0):
	"""Real downloader functions with simulated yt-dlp and ffmpeg (no network)."""
	import shutil
	import subprocess
	from csvmusic.core import downloader

	def fake_ytdlp(args):
		target = args[args.index("-o") + 1].replace("%(ext)s", "webm")
		pathlib.Path(target).write_bytes(payload if payload is not None else args[-1].encode())
		return 0, "", ""

	def fake_capture(cmd, **_kwargs):
		source = cmd[cmd.index("-i") + 1] if "-i" in cmd else None
		if source and cmd[-1] == source:
			# ffmpeg -i <arquivo> sem saída: só descreve as faixas.
			return subprocess.CompletedProcess(cmd, 1, "", f"Stream #0:0: Audio: {codec}, 48000 Hz, stereo")
		if source and not cmd[-1].startswith("-"):
			shutil.copyfile(source, cmd[-1])
		return subprocess.CompletedProcess(cmd, 0, "", "")

	monkeypatch.setattr(downloader, "_run_ytdlp_module", fake_ytdlp)
	monkeypatch.setattr(downloader, "_run_capture", fake_capture)
	monkeypatch.setattr(downloader, "ytdlp_js_runtime_args", lambda _bin: [])
	monkeypatch.setattr(downloader, "store_source", lambda _path: None)
	if callable(duration_s):
		monkeypatch.setattr(downloader, "measure_audio_duration_s", duration_s)
	else:
		monkeypatch.setattr(downloader, "measure_audio_duration_s", lambda _path: duration_s)


def test_pipeline_tags_the_file_before_it_appears_in_the_playlist(monkeypatch, tmp_path):
	from csvmusic.core.downloader import INTERNAL_YTDLP, STAGING_DIR_NAME
	worker = _pipeline(tmp_path, force_download=False)
	worker.yt_dlp_path = INTERNAL_YTDLP
	worker.ffmpeg_path_override = "ffmpeg"
	worker.tracks_override[0]["preferred_video_id"] = "selected-video"
	final = tmp_path / "Test Playlist" / "Avril Lavigne - Complicated.mp3"
	tagged = []
	results = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	_fake_download_tools(monkeypatch)
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "_track_cover_bytes", lambda _track, _vid: b"cover")
	monkeypatch.setattr(workers, "tag_file", lambda path, *_args, **_kwargs: tagged.append((path, final.exists())))
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	monkeypatch.setattr("csvmusic.core.audio_quality.audio_quality", lambda _path: {"low": False, "codec": "mp3", "kbps": 256})
	worker.run()

	assert results[0]["downloaded"] is True
	assert results[0]["file_path"] == str(final)
	assert results[0]["cover_bytes"] == b"cover"
	assert len(tagged) == 1
	assert tagged[0][0].parent.name == STAGING_DIR_NAME
	assert tagged[0][1] is False
	assert final.read_bytes() == b"new audio"


def test_failed_match_falls_back_only_to_confident_scored_results(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	options = [
		{"videoId": "best", "title": "Complicated", "author": "Avril Lavigne", "source": "music", "score": 0.9},
		{"videoId": "wrong-length", "title": "Complicated", "author": "Avril Lavigne", "source": "music", "score": 0.85, "duration_mismatch": True},
		{"videoId": "weak", "title": "Complicated (Cover)", "author": "Someone", "source": "video", "score": 0.4},
		{"videoId": "second", "title": "Complicated", "author": "Avril Lavigne", "source": "video", "score": 0.7},
	]
	tried = []
	results = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: (options[0], 0.9, options))
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)

	def fake_download(video_id, destination, base_name, _profile, **_kwargs):
		tried.append(video_id)
		if video_id == "best":
			raise RuntimeError("yt-dlp failed for mp3: Video unavailable")
		path = destination / f"{base_name}.mp3"
		path.write_bytes(b"audio")
		return path

	monkeypatch.setattr(worker, "_download_with_profile", fake_download)
	worker.run()

	assert tried == ["best", "second"]
	assert results[0]["downloaded"] is True
	assert results[0]["match"]["videoId"] == "second"


def test_stop_during_download_ends_batch_without_counting_a_failure(monkeypatch, tmp_path):
	from csvmusic.core.downloader import DownloadCancelled
	worker = _pipeline(tmp_path, force_download=False)
	worker.tracks_override[0]["preferred_video_id"] = "first"
	worker.tracks_override.append(dict(worker.tracks_override[0], title="Next", preferred_video_id="second"))
	worker.row_indices = [0, 1]
	tried = []
	results = []
	statuses = []
	finished = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	worker.sig_row_status.connect(lambda row, text: statuses.append((row, text)))
	worker.sig_done.connect(lambda message, done, skipped, failed: finished.append((message, done, skipped, failed)))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)

	def fake_download(video_id, *_args, **_kwargs):
		tried.append(video_id)
		worker.stop()
		raise DownloadCancelled("Stopped by user.")

	monkeypatch.setattr(worker, "_download_with_profile", fake_download)
	worker.run()

	assert tried == ["first"]
	assert results == []
	assert statuses[-1] == (0, "Stopped")
	assert finished[0][0].startswith("Stopped")
	assert finished[0][3] == []


def test_stop_signals_the_running_download():
	worker = workers.PipelineWorker("", "", None, "mp3", False, False, False, None, None, None, None)
	assert not worker._cancel.is_set()
	worker.stop()
	assert worker._cancel.is_set()


def test_closing_main_window_never_terminates_a_worker_thread():
	from csvmusic.ui.main_window import MainWindow

	class StuckThread:
		def __init__(self):
			self.calls = []

		def stop(self):
			self.calls.append("stop")

		def requestInterruption(self):
			pass

		def quit(self):
			pass

		def isRunning(self):
			return True

		def wait(self, ms):
			self.calls.append(("wait", ms))
			return False

		def terminate(self):
			self.calls.append("terminate")

	thread = StuckThread()
	MainWindow._shutdown_thread(None, thread, wait_ms=10)

	assert "stop" in thread.calls
	assert "terminate" not in thread.calls


def _duration_by_video(lengths: dict[str, float]):
	"""Simulated mutagen: the staged file holds the URL it came from."""
	def measure(path):
		url = pathlib.Path(path).read_bytes().decode()
		return lengths[url.rsplit("v=", 1)[-1]]
	return measure


def test_wrong_length_download_is_rejected_and_next_candidate_used(monkeypatch, tmp_path):
	from csvmusic.core.downloader import INTERNAL_YTDLP, TRASH_DIR_NAME
	worker = _pipeline(tmp_path, force_download=False)
	worker.yt_dlp_path = INTERNAL_YTDLP
	worker.ffmpeg_path_override = "ffmpeg"
	options = [
		{"videoId": "clip", "title": "Complicated", "author": "Avril Lavigne", "source": "video", "score": 0.95},
		{"videoId": "audio", "title": "Complicated", "author": "Avril Lavigne", "source": "music", "score": 0.9},
	]
	results = []
	tagged = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	_fake_download_tools(monkeypatch, payload=None, duration_s=_duration_by_video({"clip": 281.0, "audio": 245.0}))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: (options[0], 0.95, options))
	monkeypatch.setattr(workers, "_track_cover_bytes", lambda _track, _vid: None)
	monkeypatch.setattr(workers, "tag_file", lambda path, *_args, **_kwargs: tagged.append(path))
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	monkeypatch.setattr("csvmusic.core.audio_quality.audio_quality", lambda _path: {"low": False, "codec": "mp3", "kbps": 256})
	worker.run()

	final = tmp_path / "Test Playlist" / "Avril Lavigne - Complicated.mp3"
	assert results[0]["downloaded"] is True
	assert results[0]["match"]["videoId"] == "audio"
	assert results[0]["downloaded_duration_ms"] == 245000
	assert results[0]["duration_verified"] is True
	assert final.read_bytes().decode().endswith("v=audio")
	assert len(tagged) == 1
	assert not (tmp_path / "Test Playlist" / TRASH_DIR_NAME).exists()


def test_every_candidate_with_wrong_length_fails_the_track(monkeypatch, tmp_path):
	from csvmusic.core.downloader import INTERNAL_YTDLP
	worker = _pipeline(tmp_path, force_download=False)
	worker.yt_dlp_path = INTERNAL_YTDLP
	worker.ffmpeg_path_override = "ffmpeg"
	option = {"videoId": "live", "title": "Complicated", "author": "Avril Lavigne", "source": "music", "score": 0.9}
	results = []
	_fake_download_tools(monkeypatch, payload=None, duration_s=_duration_by_video({"live": 300.0}))
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: (option, 0.9, [option]))
	monkeypatch.setattr(workers, "tag_file", lambda *_args, **_kwargs: None)
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	worker.run()

	assert results[0]["downloaded"] is False
	assert "wrong length" in results[0]["error"]
	assert not (tmp_path / "Test Playlist" / "Avril Lavigne - Complicated.mp3").exists()


def test_link_chosen_by_hand_is_kept_even_with_wrong_length(monkeypatch, tmp_path):
	from csvmusic.core.downloader import INTERNAL_YTDLP
	worker = _pipeline(tmp_path, force_download=False)
	worker.yt_dlp_path = INTERNAL_YTDLP
	worker.ffmpeg_path_override = "ffmpeg"
	worker.tracks_override[0]["preferred_video_id"] = "handpicked"
	worker.tracks_override[0]["preferred_selection_locked"] = True
	results = []
	logged = []
	_fake_download_tools(monkeypatch, payload=None, duration_s=_duration_by_video({"handpicked": 300.0}))
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "_track_cover_bytes", lambda _track, _vid: None)
	monkeypatch.setattr(workers, "tag_file", lambda *_args, **_kwargs: None)
	monkeypatch.setattr(workers, "log", logged.append)
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	monkeypatch.setattr("csvmusic.core.audio_quality.audio_quality", lambda _path: {"low": False, "codec": "mp3", "kbps": 256})
	worker.run()

	assert results[0]["downloaded"] is True
	assert results[0]["match"]["videoId"] == "handpicked"
	assert results[0]["duration_verified"] is False
	assert results[0]["duration_needs_review"] is True
	assert any("user choice kept" in line and "+56.0s" in line for line in logged)


def test_age_restricted_failure_reports_its_kind(monkeypatch, tmp_path):
	from csvmusic.core.downloader import AgeRestrictedError
	worker = _pipeline(tmp_path, force_download=True)
	results = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	def fail(_video_id, *_args, **_kwargs):
		raise AgeRestrictedError("Video unavailable")
	monkeypatch.setattr(worker, "_download_with_profile", fail)
	worker.run()
	assert results[0]["failure_kind"] == "age_restricted"


def test_skipped_track_reports_reason_with_best_score(monkeypatch, tmp_path):
	worker = _pipeline(tmp_path, force_download=False)
	results = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	worker.run()
	assert results[0]["skip_reason"] == "No confident match on YouTube Music (best score 0.40)"


def test_batch_stops_after_two_songs_refused_for_bot_check(monkeypatch, tmp_path):
	from csvmusic.core.downloader import YouTubeRiskError
	worker = _pipeline(tmp_path, force_download=True)
	worker.tracks_override += [dict(worker.tracks_override[0], title=f"Song {n}") for n in range(4)]
	worker.row_indices = list(range(5))
	results = []
	finished = []
	worker.sig_track_result.connect(lambda _row, payload: results.append(payload))
	worker.sig_done.connect(lambda message, *_rest: finished.append(message))
	monkeypatch.setattr(workers, "YTMusic", lambda: object())
	monkeypatch.setattr(workers, "find_best", lambda _yt, _track: _low_confidence_result())
	monkeypatch.setattr(workers.time, "sleep", lambda _seconds: None)
	def refuse(*_args, **_kwargs):
		raise YouTubeRiskError("YouTube asked for bot verification: Try Firefox cookies", "YouTube asked for bot verification")
	monkeypatch.setattr(worker, "_download_with_profile", refuse)
	worker.run()
	assert len(results) == 2
	assert all(result["failure_kind"] == "youtube_blocked" for result in results)
	assert finished == ["Stopped because YouTube asked to sign in."]
