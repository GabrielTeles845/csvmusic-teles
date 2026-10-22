# tabs only
import json
import pathlib

import pytest

from csvmusic.core import settings


@pytest.fixture
def settings_dir(monkeypatch, tmp_path: pathlib.Path) -> pathlib.Path:
	folder = tmp_path / "data"
	monkeypatch.setattr(settings, "_settings_dir", lambda: folder)
	settings._reset_for_tests()
	yield folder
	settings._reset_for_tests()


def test_saves_are_grouped_and_written_on_flush(settings_dir):
	settings.save_settings({"output_dir": "/music"})
	settings.save_settings({"format": "m4a"})

	assert not (settings_dir / "settings.json").exists()
	assert settings.load_settings() == {"output_dir": "/music", "format": "m4a"}

	settings.flush_settings()

	assert json.loads((settings_dir / "settings.json").read_text(encoding="utf-8")) == {"output_dir": "/music", "format": "m4a"}
	assert not list(settings_dir.glob("*.tmp"))


def test_previous_file_is_kept_as_backup(settings_dir):
	settings.save_settings({"format": "mp3"})
	settings.flush_settings()
	settings.save_settings({"format": "opus", "output_dir": None})
	settings.flush_settings()

	assert json.loads((settings_dir / "settings.json.bak").read_text(encoding="utf-8")) == {"format": "mp3"}
	assert settings.load_settings() == {"format": "opus"}


def test_unreadable_settings_are_not_silently_replaced(settings_dir):
	settings_dir.mkdir(parents=True)
	(settings_dir / "settings.json").write_text("{broken", encoding="utf-8")
	(settings_dir / "settings.json.bak").write_text(json.dumps({"output_dir": "/music", "format": "mp3"}), encoding="utf-8")

	# The backup fills in, so one new key does not wipe every other setting.
	assert settings.load_settings() == {"output_dir": "/music", "format": "mp3"}
	settings.save_settings({"write_m3u8": True})
	settings.flush_settings()

	assert json.loads((settings_dir / "settings.json").read_text(encoding="utf-8")) == {
		"output_dir": "/music", "format": "mp3", "write_m3u8": True,
	}
	preserved = list(settings_dir.glob("settings.json.unreadable-*"))
	assert len(preserved) == 1 and preserved[0].read_text(encoding="utf-8") == "{broken"


def test_timer_writes_without_an_explicit_flush(settings_dir, monkeypatch):
	import time
	monkeypatch.setattr(settings, "SAVE_DELAY_S", 0.01)
	settings.save_settings({"format": "m4a"})
	deadline = time.monotonic() + 2
	while not (settings_dir / "settings.json").exists() and time.monotonic() < deadline:
		time.sleep(0.01)
	assert json.loads((settings_dir / "settings.json").read_text(encoding="utf-8")) == {"format": "m4a"}
