# tabs only
import pathlib

from csvmusic.core import log as app_log


def test_macos_log_goes_to_library_logs_of_the_fork(monkeypatch, tmp_path: pathlib.Path):
	monkeypatch.setattr(app_log.sys, "platform", "darwin")
	monkeypatch.setattr(app_log.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	assert app_log.log_path() == tmp_path / "Library" / "Logs" / "CSVMusicTeles" / "app.log"


def test_log_rotates_and_keeps_a_few_old_files(monkeypatch, tmp_path: pathlib.Path):
	path = tmp_path / "app.log"
	monkeypatch.setattr(app_log, "log_path", lambda: path)
	monkeypatch.setattr(app_log, "MAX_LOG_BYTES", 200)

	for index in range(60):
		app_log.log(f"line {index:03d} " + "x" * 20)

	assert path.stat().st_size <= 200
	rotated = sorted(item.name for item in tmp_path.iterdir())
	assert rotated == ["app.log", "app.log.1", "app.log.2", "app.log.3"]
	assert "line 059" in path.read_text(encoding="utf-8")
