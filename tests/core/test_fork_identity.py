# tabs only
"""The fork runs next to the original CSVMusic without sharing data, updates or the macOS identity."""
import pathlib
from types import SimpleNamespace

from csvmusic.core import update_check
from csvmusic.version import APP_VERSION


ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_fork_version_and_bundle_identifier():
	assert APP_VERSION == "1.7.9+teles.0"
	spec = (ROOT / "CSVMusic.spec").read_text(encoding="utf-8")
	assert "bundle_identifier='com.teles.csvmusic'" in spec
	assert "com.angall1.csvmusic" not in spec


def test_update_check_never_starts(monkeypatch):
	from csvmusic.ui import library_mode

	def _fail(*_args, **_kwargs):
		raise AssertionError("the update check must not run in the fork")

	monkeypatch.setattr(library_mode, "load_settings", _fail)
	monkeypatch.setattr(library_mode, "UpdateCheckWorker", _fail)
	assert update_check.update_checks_enabled() is False

	library_mode.LibraryModeDialog._start_update_check(SimpleNamespace(update_check_worker=None))
