# tabs only
import json
import pathlib
import subprocess
import sys

import pytest

from csvmusic.core.library import load_library
from csvmusic.engine import EngineError

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_engine_does_not_import_the_old_windows():
	code = (
		"import sys; import csvmusic.engine, csvmusic.web.server, csvmusic.web.bridge; "
		"bad=[m for m in ('csvmusic.ui.library_mode','csvmusic.ui.main_window','csvmusic.ui.device_sync','csvmusic.ui.theme') if m in sys.modules]; "
		"print(','.join(bad))"
	)
	result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120, env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin"})
	assert result.returncode == 0, result.stderr
	assert result.stdout.strip() == ""


def test_state_counts_and_track_states(make_engine):
	engine = make_engine(6)
	tracks = engine.library["playlists"][0]["tracks"]
	engine.write_song(0)
	engine.write_song(1)
	tracks[1]["low_confidence_review"] = True
	tracks[1]["review_reason"] = "File is 7 s longer than the song"
	tracks[2]["last_error"] = "ERROR: Sign in to confirm your age"
	tracks[2]["failure_kind"] = "age_restricted"
	tracks[3]["skip_state"] = "not_found_on_youtube"
	tracks[3]["skip_reason"] = "No search results"
	tracks[4]["enabled"] = False

	state = engine.state()

	summary = state["playlists"][0]
	assert summary["id"] == "spotify:big"
	assert summary["counts"] == {
		"total": 6, "downloaded": 2, "missing": 3, "review": 1, "error": 1, "age_limit": 1,
		"not_found": 1, "disabled": 1, "queued": 0,
	}
	assert summary["scan_state"] == "ok"
	assert summary["cover_urls"] == [f"https://i.scdn.co/image/{i}" for i in range(4)]
	assert state["job"] == {"kind": None}
	assert state["first_run"] is False
	items = {item["index"]: item for item in engine.tracks("spotify:big")["items"]}
	assert [items[i]["state"] for i in range(6)] == ["downloaded", "review", "age_limit", "not_found", "disabled", "missing"]
	assert items[1]["detail"] == "Arquivo 7 s mais longo que a música"
	assert items[2]["detail"] == "Restrição de idade: precisa entrar no YouTube"
	assert items[2]["error"]["technical"].startswith("ERROR")
	assert items[3]["detail"] == "A busca no YouTube Music não trouxe resultado"
	assert items[0]["file_path"] and items[0]["quality"]["label"]


def test_tracks_filter_query_and_paging(make_engine):
	engine = make_engine(30)
	engine.write_song(3)
	assert engine.tracks("spotify:big", filter_name="downloaded")["total"] == 1
	missing = engine.tracks("spotify:big", filter_name="missing", offset=10, limit=5)
	assert missing["total"] == 29 and len(missing["items"]) == 5 and missing["items"][0]["index"] == 11
	assert missing["counts"]["total"] == 30
	assert [item["index"] for item in engine.tracks("spotify:big", query="song 1")["items"]][:3] == [1, 10, 11]
	with pytest.raises(EngineError):
		engine.tracks("spotify:big", filter_name="weird")


def test_unreadable_library_opens_empty_and_never_saves(engine_env):
	from csvmusic.engine import Engine
	data = engine_env / "data"
	data.mkdir(parents=True, exist_ok=True)
	path = data / "library.json"
	original = json.dumps({"version": 9, "playlists": []})
	path.write_text(original, encoding="utf-8")
	engine = Engine(library_path=path)
	try:
		assert engine.library["playlists"] == []
		assert "não grava" in engine.state()["library"]["load_error"]
		engine.save()
		assert path.read_text(encoding="utf-8") == original
		assert list(data.glob("library.json.unreadable-*.bak"))
	finally:
		engine.deleteLater()


def test_add_playlists_reports_errors_in_portuguese_and_starts_the_scan(make_engine):
	engine = make_engine(1)
	result = engine.add_playlists([
		"https://www.youtube.com/watch?v=abc",
		"https://music.youtube.com/playlist?list=PLabc123",
		"https://music.youtube.com/playlist?list=PLabc123",
		"not a link",
	])
	assert result["added"] == ["youtube_music:PLabc123"]
	errors = [entry["error"] for entry in result["errors"]]
	assert errors[0].startswith("Este é o link de um vídeo")
	assert errors[1] == "Esta playlist já está na biblioteca."
	assert len(errors) == 3
	assert engine.job()["kind"] == "scan"
	assert engine.events_of("playlists") == [{"ids": ["youtube_music:PLabc123"]}]


def test_import_csv_content(make_engine):
	import base64
	engine = make_engine(1)
	content = "Track name,Artist name,Playlist name\nUm,Artista,Minha Lista\nDois,Artista,Minha Lista\n".encode("utf-8")
	result = engine.import_csv_content("minha.csv", base64.b64encode(content).decode("ascii"))
	playlist = engine.playlist_summary(result["added"][0])
	assert playlist["name"] == "Minha Lista" and playlist["counts"]["total"] == 2
	with pytest.raises(EngineError) as error:
		engine.import_csv_content("ruim.csv", base64.b64encode(b"a,b\n1,2\n").decode("ascii"))
	assert error.value.status == 400


def test_two_spreadsheets_with_the_same_file_name_stay_apart(make_engine):
	import base64
	engine = make_engine(1)
	first = "title,artist,album\nMusica A,Artista A,Album A\nMusica B,Artista B,Album B\n".encode("utf-8")
	second = "title,artist,album\nOutra C,Artista C,Album C\n".encode("utf-8")
	one = engine.import_csv_content("playlist.csv", base64.b64encode(first).decode("ascii"), "Minha festa")["added"][0]
	two = engine.import_csv_content("playlist.csv", base64.b64encode(second).decode("ascii"), "Treino")["added"][0]
	assert one != two
	csvs = {playlist["name"]: [track["title"] for track in playlist["tracks"]] for playlist in engine.library["playlists"] if playlist["platform"] == "csv"}
	assert csvs == {"Minha festa": ["Musica A", "Musica B"], "Treino": ["Outra C"]}
	again = engine.import_csv_content("playlist.csv", base64.b64encode(first).decode("ascii"))["added"][0]
	assert again == one
	assert len([playlist for playlist in engine.library["playlists"] if playlist["platform"] == "csv"]) == 2


def test_settings_round_trip_and_validation(make_engine):
	engine = make_engine(2)
	updated = engine.update_settings({"format": "mp3", "eq_bass_gain": 4, "theme": "dark", "write_m3u8": False})
	assert updated["format"] == "mp3" and engine.library["format"] == "mp3"
	assert updated["eq_bass_gain"] == 4 and updated["theme"] == "dark" and updated["write_m3u8"] is False
	assert load_library(engine.library_path)["format"] == "mp3"
	for bad in ({"format": "wav"}, {"eq_bass_gain": 40}, {"mp3_quality": "x"}, {"nope": 1}, {"embed_art": "sim"}):
		with pytest.raises(EngineError) as error:
			engine.update_settings(bad)
		assert error.value.status == 400


def test_track_edits_queue_a_new_download(make_engine):
	engine = make_engine(3)
	view = engine.update_track("spotify:big", 0, {"volume_gain": 3})
	assert view["volume_gain"] == 3 and view["state"] == "redownload"
	view = engine.update_track("spotify:big", 1, {"preferred_video_url": "https://music.youtube.com/watch?v=uLivzCQcQW8"})
	assert view["preferred_video"]["id"] == "uLivzCQcQW8"
	assert engine.library["playlists"][0]["tracks"][1]["force_redownload"] is True
	with pytest.raises(EngineError) as error:
		engine.update_track("spotify:big", 1, {"preferred_video_url": "https://example.com/x"})
	assert error.value.status == 400
	engine.update_track("spotify:big", 1, {"preferred_video_url": ""})
	assert engine.library["playlists"][0]["tracks"][1]["preferred_video_id"] is None


def test_metadata_edit_renames_the_file(make_engine, monkeypatch):
	from csvmusic.engine import engine as engine_module
	tagged = []
	monkeypatch.setattr(engine_module, "tag_file", lambda path, track, cover: tagged.append((path.name, track["title"])))
	engine = make_engine(2)
	old = engine.write_song(0)
	view = engine.update_track("spotify:big", 0, {"title": "Nova", "album": "Disco"})
	assert not old.exists()
	assert pathlib.Path(view["file_path"]).name == "Artist - Nova.m4a"
	assert view["title"] == "Nova" and view["album"] == "Disco"
	assert tagged == [("Artist - Nova.m4a", "Nova")]


def test_failed_metadata_edit_puts_the_file_back(make_engine, monkeypatch):
	from csvmusic.engine import engine as engine_module

	def broken_tags(*_args):
		raise RuntimeError("bad file")

	monkeypatch.setattr(engine_module, "tag_file", broken_tags)
	engine = make_engine(2)
	old = engine.write_song(0)
	with pytest.raises(EngineError) as error:
		engine.update_track("spotify:big", 0, {"title": "Nova"})
	assert error.value.status == 500
	assert old.exists()
	assert engine.library["playlists"][0]["tracks"][0]["title"] == "Song 0"


def test_set_enabled_and_accept_review(make_engine):
	engine = make_engine(5)
	assert engine.set_tracks_enabled("spotify:big", False, indices=[0, 1]) == {"changed": 2}
	assert engine.set_tracks_enabled("spotify:big", True, all_tracks=True) == {"changed": 2}
	engine.library["playlists"][0]["tracks"][2]["low_confidence_review"] = True
	assert engine.accept_review("spotify:big", 2)["state"] == "missing"


def test_export_csv_bytes(make_engine):
	engine = make_engine(2)
	data, filename = engine.export_csv_bytes("spotify:big")
	assert filename == "Big.csv"
	assert "Song 0" in data.decode("utf-8-sig")


def test_rename_playlist(make_engine):
	engine = make_engine(2)
	engine.write_song(0)
	summary = engine.rename_playlist("spotify:big", "Nova Lista")
	assert summary["name"] == "Nova Lista"
	assert (engine.output / "Nova Lista").is_dir()
	assert summary["counts"]["downloaded"] == 1


def test_first_run_flag(make_engine):
	from csvmusic.core.settings import save_settings
	engine = make_engine(1)
	save_settings({"hide_startup_disclaimer": False})
	assert engine.state()["first_run"] is True
	engine.accept_first_run()
	assert engine.state()["first_run"] is False


def test_save_a_copy_keeps_writing_to_the_original(make_engine, tmp_path):
	engine = make_engine(3)
	original = engine.library_path
	copy = tmp_path / "copia" / "biblioteca-csvmusic.json"
	copy.parent.mkdir()
	assert engine.save_library_as(str(copy)) == {"path": str(copy)}
	assert engine.library_path == original
	assert engine.events_of("library") == []
	engine.update_track("spotify:big", 0, {"enabled": False})
	assert load_library(original)["playlists"][0]["tracks"][0]["enabled"] is False
	assert load_library(copy)["playlists"][0]["tracks"][0].get("enabled", True) is True


def test_save_a_copy_asks_before_replacing_a_file(make_engine, tmp_path):
	engine = make_engine(2)
	existing = tmp_path / "outra.json"
	existing.write_text("{\"meu\": \"arquivo\"}", encoding="utf-8")
	with pytest.raises(EngineError) as error:
		engine.save_library_as(str(existing))
	assert error.value.status == 409 and error.value.extra["needs_confirmation"] == "overwrite"
	assert existing.read_text(encoding="utf-8") == "{\"meu\": \"arquivo\"}"
	engine.save_library_as(str(existing), overwrite=True)
	assert len(load_library(existing)["playlists"]) == 1
