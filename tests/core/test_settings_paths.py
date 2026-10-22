# tabs only
import pathlib

import pytest

from csvmusic.core import settings


@pytest.fixture(autouse=True)
def real_folder_logic(monkeypatch):
	# conftest points the data folder at a temporary one; these tests check the real folder logic.
	monkeypatch.delenv(settings.DATA_DIR_ENV, raising=False)


def test_macos_uses_its_own_application_support_folder(monkeypatch, tmp_path: pathlib.Path) -> None:
	monkeypatch.setattr(settings.sys, "platform", "darwin")
	monkeypatch.setattr(settings.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	assert settings._settings_dir() == tmp_path / "Library" / "Application Support" / "CSVMusicTeles"


def test_linux_honors_xdg_data_home(monkeypatch, tmp_path: pathlib.Path) -> None:
	monkeypatch.setattr(settings.sys, "platform", "linux")
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
	monkeypatch.setattr(settings.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	assert settings._settings_dir() == tmp_path / "xdg-data" / "csvmusicteles"


def test_first_run_copies_the_original_library_and_never_moves_it(monkeypatch, tmp_path: pathlib.Path) -> None:
	original = tmp_path / "Library" / "Application Support" / "CSVMusic"
	original.mkdir(parents=True)
	(original / "library.json").write_text('{"version": 1, "playlists": []}', encoding="utf-8")
	(original / "settings.json").write_text('{"output_dir": "/music"}', encoding="utf-8")
	(original / "webengine-cache.bin").write_bytes(b"big")
	monkeypatch.setattr(settings.sys, "platform", "darwin")
	monkeypatch.setattr(settings.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	target = settings._settings_dir()

	assert target == tmp_path / "Library" / "Application Support" / "CSVMusicTeles"
	assert (target / "library.json").read_text(encoding="utf-8") == '{"version": 1, "playlists": []}'
	assert (target / "settings.json").read_text(encoding="utf-8") == '{"output_dir": "/music"}'
	assert not (target / "webengine-cache.bin").exists()
	# The original app keeps everything it had.
	assert (original / "library.json").exists() and (original / "settings.json").exists()


def test_later_runs_do_not_copy_over_the_fork_data(monkeypatch, tmp_path: pathlib.Path) -> None:
	original = tmp_path / "Library" / "Application Support" / "CSVMusic"
	fork = tmp_path / "Library" / "Application Support" / "CSVMusicTeles"
	original.mkdir(parents=True)
	fork.mkdir(parents=True)
	(original / "library.json").write_text("original", encoding="utf-8")
	(fork / "library.json").write_text("fork", encoding="utf-8")
	monkeypatch.setattr(settings.sys, "platform", "darwin")
	monkeypatch.setattr(settings.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	settings._settings_dir()

	assert (fork / "library.json").read_text(encoding="utf-8") == "fork"


def test_older_cross_platform_folder_is_copied_when_nothing_newer_exists(monkeypatch, tmp_path: pathlib.Path) -> None:
	legacy = tmp_path / ".local" / "share" / "csvmusic"
	legacy.mkdir(parents=True)
	(legacy / "library.json").write_text("{}", encoding="utf-8")
	monkeypatch.setattr(settings.sys, "platform", "darwin")
	monkeypatch.setattr(settings.pathlib.Path, "home", classmethod(lambda cls: tmp_path))

	target = settings._settings_dir()

	assert (target / "library.json").exists()
	assert (legacy / "library.json").exists()


def test_data_folder_can_be_pointed_elsewhere(monkeypatch, tmp_path: pathlib.Path) -> None:
	monkeypatch.setenv(settings.DATA_DIR_ENV, str(tmp_path / "custom"))

	assert settings._settings_dir() == tmp_path / "custom"
