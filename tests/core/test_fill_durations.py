# tabs only
import datetime
import json

from csvmusic.core.library import new_library, save_library
from csvmusic.tools.fill_durations import backup_library, fill_library_durations, main, running_app_lines

# Same header as the real Spotify export; invented songs.
_HEADER = '"#";"Track Name";"Artist Name";"Álbum";"Adicionada em";"Duração";"Link"'


def _write_csv(path):
	rows = [
		'"1";"Canção Um";"Banda A";"Disco";"1 de jan. de 2025";"2:57";"https://open.spotify.com/track/0000000000000000000001"',
		'"2";"Canção Dois";"Banda B";"Disco";"1 de jan. de 2025";"4:01";"https://open.spotify.com/track/0000000000000000000002"',
		'"3";"Fora da Biblioteca";"Banda C";"Disco";"1 de jan. de 2025";"3:00";"https://open.spotify.com/track/0000000000000000000009"',
	]
	path.write_bytes(b"\xef\xbb\xbf" + "\r\n".join([_HEADER] + rows).encode("utf-8"))


def _library():
	library = new_library("Teste", "/tmp/nao-usado")
	library["playlists"].append({
		"id": "pl",
		"platform": "spotify",
		"name": "Lista",
		"tracks": [
			{"title": "Canção Um", "artists": "Banda A", "sp_id": "0000000000000000000001", "duration_ms": 0, "enabled": False, "custom_title": True},
			{"title": "Canção Dois", "artists": "Banda B", "sp_id": "0000000000000000000002", "duration_ms": 999000},
			{"title": "Sem Par", "artists": "Banda D", "sp_id": "0000000000000000000005", "duration_ms": 0},
		],
	})
	return library


def test_fill_only_zero_durations_and_keep_other_fields():
	library = _library()
	before = json.loads(json.dumps(library))
	durations = {
		"0000000000000000000001": {"duration_ms": 177500, "duration_precision_s": 1},
		"0000000000000000000002": {"duration_ms": 241500, "duration_precision_s": 1},
	}

	result = fill_library_durations(library, durations)

	tracks = library["playlists"][0]["tracks"]
	assert result.filled == 1
	assert result.already_had_duration == 1
	assert result.without_csv_match == 1
	assert result.csv_rows_unused == 0
	assert tracks[0]["duration_ms"] == 177500
	assert tracks[0]["duration_source"] == "csv"
	assert tracks[0]["duration_precision_s"] == 1
	assert tracks[1]["duration_ms"] == 999000
	assert tracks[2]["duration_ms"] == 0
	# Nothing else changed.
	changed = {k for k in tracks[0] if tracks[0].get(k) != before["playlists"][0]["tracks"][0].get(k)}
	assert changed == {"duration_ms", "duration_source", "duration_precision_s"}
	assert tracks[1] == before["playlists"][0]["tracks"][1]
	assert tracks[2] == before["playlists"][0]["tracks"][2]


def test_main_backs_up_and_saves(tmp_path):
	library_path = tmp_path / "library.json"
	save_library(library_path, _library())
	original = library_path.read_text(encoding="utf-8")
	csv_path = tmp_path / "curtidas.csv"
	_write_csv(csv_path)

	code = main(["--csv", str(csv_path), "--library", str(library_path)], process_lines=[])

	assert code == 0
	backups = list(tmp_path.glob("library.json.bak-*"))
	assert len(backups) == 1
	assert backups[0].read_text(encoding="utf-8") == original
	saved = json.loads(library_path.read_text(encoding="utf-8"))
	tracks = saved["playlists"][0]["tracks"]
	assert tracks[0]["duration_ms"] == 177500
	assert tracks[1]["duration_ms"] == 999000


def test_main_refuses_while_app_is_open(tmp_path):
	library_path = tmp_path / "library.json"
	save_library(library_path, _library())
	original = library_path.read_text(encoding="utf-8")
	csv_path = tmp_path / "curtidas.csv"
	_write_csv(csv_path)

	code = main(
		["--csv", str(csv_path), "--library", str(library_path)],
		process_lines=["4242 /Applications/CSVMusic.app/Contents/MacOS/CSVMusic"],
	)

	assert code == 3
	assert library_path.read_text(encoding="utf-8") == original
	assert not list(tmp_path.glob("library.json.bak-*"))


def test_dry_run_writes_nothing(tmp_path):
	library_path = tmp_path / "library.json"
	save_library(library_path, _library())
	original = library_path.read_text(encoding="utf-8")
	csv_path = tmp_path / "curtidas.csv"
	_write_csv(csv_path)

	code = main(["--csv", str(csv_path), "--library", str(library_path), "--dry-run"], process_lines=[])

	assert code == 0
	assert library_path.read_text(encoding="utf-8") == original
	assert not list(tmp_path.glob("library.json.bak-*"))


def test_running_app_detection():
	lines = [
		"100 /opt/homebrew/bin/python3.12 -m csvmusic.app",
		"101 python -m csvmusic",
		"102 /Applications/CSVMusic.app/Contents/MacOS/CSVMusic",
		"103 python -m csvmusic.tools.fill_durations --csv x.csv",
		"104 python -m pytest tests/core/test_apple_music_import.py",
		"105 /usr/bin/vim notes.txt",
	]

	found = running_app_lines(lines, own_pid=101)

	assert [line.split()[0] for line in found] == ["100", "102"]


def test_running_app_detection_sees_the_package_entry_point():
	lines = [
		"200 /opt/homebrew/bin/python3.12 -m csvmusic",
		"201 python -m csvmusic --debug",
		"202 python /src/csvmusic/__main__.py",
		"203 python -m csvmusic.fetch_csv x",
		"204 python -m csvmusicx",
	]

	found = running_app_lines(lines)

	assert [line.split()[0] for line in found] == ["200", "201", "202"]


def test_backup_never_overwrites(tmp_path):
	library_path = tmp_path / "library.json"
	library_path.write_text("{}", encoding="utf-8")
	moment = datetime.datetime(2026, 10, 22, 12, 0, 0)

	first = backup_library(library_path, moment)
	second = backup_library(library_path, moment)

	assert first.name == "library.json.bak-20261022-120000"
	assert second != first
	assert second.exists() and first.exists()
