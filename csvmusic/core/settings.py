# tabs only
import atexit
import datetime
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading

_SETTINGS_FILE = "settings.json"
# Writes are grouped: the legacy window saves on every keystroke.
SAVE_DELAY_S = 0.3

_lock = threading.RLock()
_cache: dict | None = None
_cache_path: pathlib.Path | None = None
_dirty = False
_unreadable_on_disk = False
_timer: threading.Timer | None = None


def _settings_dir() -> pathlib.Path:
	if sys.platform.startswith("win"):
		appdata = os.environ.get("APPDATA")
		if appdata:
			appdata_path = pathlib.Path(appdata)
			old = appdata_path / "Spotify2Media"
			new = appdata_path / "CSVMusic"
			if old.exists() and not new.exists():
				try:
					old.rename(new)
				except Exception:
					return old
			return new
	home = pathlib.Path.home()
	if sys.platform.startswith("darwin"):
		new = home / "Library" / "Application Support" / "CSVMusic"
		old_candidates = [
			home / "Library" / "Application Support" / "Spotify2Media",
			home / ".local" / "share" / "csvmusic",
			home / ".local" / "share" / "spotify2media",
		]
	else:
		xdg_data_home = os.environ.get("XDG_DATA_HOME")
		base = pathlib.Path(xdg_data_home).expanduser() if xdg_data_home else home / ".local" / "share"
		new = base / "csvmusic"
		old_candidates = [base / "spotify2media"]
	for old in old_candidates:
		if not old.exists() or new.exists():
			continue
		try:
			new.parent.mkdir(parents=True, exist_ok=True)
			old.rename(new)
		except Exception:
			return old
		break
	return new


def settings_path() -> pathlib.Path:
	d = _settings_dir()
	d.mkdir(parents=True, exist_ok=True)
	return d / _SETTINGS_FILE


def _backup_path(path: pathlib.Path) -> pathlib.Path:
	return path.with_name(path.name + ".bak")


def _read_json(path: pathlib.Path) -> dict | None:
	try:
		with path.open("r", encoding="utf-8") as handle:
			data = json.load(handle)
	except (OSError, ValueError):
		return None
	return data if isinstance(data, dict) else None


def _load_into_cache(path: pathlib.Path) -> None:
	"""Read settings once per file; an unreadable file falls back to the backup and is never silently replaced."""
	global _cache, _cache_path, _dirty, _unreadable_on_disk
	data: dict | None = {}
	unreadable = False
	if path.exists():
		data = _read_json(path)
		if data is None:
			unreadable = True
			data = _read_json(_backup_path(path)) or {}
			_log(f"settings unreadable path={path}; using backup with {len(data)} keys")
	_cache = dict(data)
	_cache_path = path
	_dirty = False
	_unreadable_on_disk = unreadable


def _current_cache() -> dict:
	path = settings_path()
	with _lock:
		if _cache is None or _cache_path != path:
			_flush_locked()
			_load_into_cache(path)
		return _cache  # type: ignore[return-value]


def load_settings() -> dict:
	with _lock:
		return dict(_current_cache())


def _should_clear(value: object) -> bool:
	if value is None:
		return True
	if isinstance(value, str) and value.strip() == "":
		return True
	return False


def save_settings(data: dict) -> None:
	"""Merge `data` into the settings now (readers see it at once) and write the file shortly after."""
	global _dirty, _timer
	try:
		with _lock:
			cache = _current_cache()
			for key, value in data.items():
				if _should_clear(value):
					cache.pop(key, None)
				else:
					cache[key] = value
			for key in [key for key, value in cache.items() if _should_clear(value)]:
				cache.pop(key, None)
			_dirty = True
			if _timer is not None:
				_timer.cancel()
			_timer = threading.Timer(SAVE_DELAY_S, flush_settings)
			_timer.daemon = True
			_timer.start()
	except Exception as exc:
		_log(f"settings save failed error={exc}")


def flush_settings() -> None:
	"""Write pending settings now (also runs at exit)."""
	with _lock:
		_flush_locked()


def _flush_locked() -> None:
	global _dirty, _timer, _unreadable_on_disk
	if _timer is not None:
		_timer.cancel()
		_timer = None
	if not _dirty or _cache is None or _cache_path is None:
		return
	path = _cache_path
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		if path.exists():
			if _unreadable_on_disk:
				stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
				shutil.copy2(path, path.with_name(f"{path.name}.unreadable-{stamp}"))
				_unreadable_on_disk = False
			elif _read_json(path) is not None:
				shutil.copy2(path, _backup_path(path))
		with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".tmp", prefix="settings-", dir=path.parent, delete=False) as handle:
			temporary = pathlib.Path(handle.name)
			try:
				json.dump(_cache, handle, ensure_ascii=False, indent=2)
				handle.flush()
				os.fsync(handle.fileno())
			except BaseException:
				handle.close()
				temporary.unlink(missing_ok=True)
				raise
		os.replace(temporary, path)
		_dirty = False
	except Exception as exc:
		_log(f"settings write failed path={path} error={exc}")


def _reset_for_tests() -> None:
	"""Forget the in-memory settings (tests switch the settings folder)."""
	global _cache, _cache_path, _dirty, _unreadable_on_disk, _timer
	with _lock:
		if _timer is not None:
			_timer.cancel()
		_cache = None
		_cache_path = None
		_dirty = False
		_unreadable_on_disk = False
		_timer = None


def _log(message: str) -> None:
	try:
		from csvmusic.core.log import log
		log(message)
	except Exception:
		pass


atexit.register(flush_settings)
