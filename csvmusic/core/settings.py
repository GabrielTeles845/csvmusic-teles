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


# The fork keeps its own data folder so it runs next to the original CSVMusic without touching its library.
FORK_FOLDER_NAME = "CSVMusicTeles"
# Points the data folder elsewhere (tests and screenshots use it so they never read or write the real library).
DATA_DIR_ENV = "CSVMUSIC_DATA_DIR"
# What the first run copies from the original app (never moved, never changed there).
SEED_FILES = ("settings.json", "library.json", "youtube-cookies.txt")
# The YouTube sign-in (Firefox profile, youtube-cookies.txt, popup-cookies.txt) lives in this subfolder.
SEED_FOLDERS = ("youtube-login",)
# Firefox lock files: a copy of them would make the fork's Firefox think the profile is in use.
_SEED_IGNORED = ("lock", ".parentlock", "parent.lock")


def _folder_candidates() -> tuple[pathlib.Path, list[pathlib.Path]]:
	"""This fork's folder, then the original app's folders to seed it from (newest name first)."""
	home = pathlib.Path.home()
	if sys.platform.startswith("win"):
		appdata = pathlib.Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
		return appdata / FORK_FOLDER_NAME, [appdata / "CSVMusic", appdata / "Spotify2Media"]
	if sys.platform.startswith("darwin"):
		support = home / "Library" / "Application Support"
		return support / FORK_FOLDER_NAME, [
			support / "CSVMusic",
			support / "Spotify2Media",
			home / ".local" / "share" / "csvmusic",
			home / ".local" / "share" / "spotify2media",
		]
	xdg_data_home = os.environ.get("XDG_DATA_HOME")
	base = pathlib.Path(xdg_data_home).expanduser() if xdg_data_home else home / ".local" / "share"
	return base / FORK_FOLDER_NAME.lower(), [base / "csvmusic", base / "spotify2media"]


def _seed_from_original(target: pathlib.Path, sources: list[pathlib.Path]) -> None:
	"""First run only: COPY the original app's settings and library so no playlist is lost."""
	for source in sources:
		files = [source / name for name in SEED_FILES if (source / name).is_file()]
		folders = [source / name for name in SEED_FOLDERS if (source / name).is_dir()]
		if not files and not folders:
			continue
		target.mkdir(parents=True, exist_ok=True)
		for path in files:
			destination = target / path.name
			if not destination.exists():
				shutil.copy2(path, destination)
		for folder in folders:
			destination = target / folder.name
			if not destination.exists():
				shutil.copytree(folder, destination, ignore=shutil.ignore_patterns(*_SEED_IGNORED), symlinks=True)
		_repoint_copied_settings(target / _SETTINGS_FILE, source, target)
		_log(f"settings first run: copied {[path.name for path in files + folders]} from {source} to {target}")
		return


def _repoint_copied_settings(path: pathlib.Path, source: pathlib.Path, target: pathlib.Path) -> None:
	"""Point a copied cookies_file that lives in the original's folder at the fork's copy.

	yt-dlp rewrites the cookie file it is given; left as is, the fork would keep changing the original's file.
	"""
	data = _read_json(path) if path.is_file() else None
	value = str((data or {}).get("cookies_file") or "").strip()
	if not value:
		return
	try:
		relative = pathlib.Path(value).expanduser().resolve().relative_to(source.resolve())
	except (OSError, RuntimeError, ValueError):
		return
	data["cookies_file"] = str(target / relative)
	temporary = path.with_name(path.name + ".tmp")
	temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
	temporary.replace(path)
	_log(f"settings first run: cookies_file now points at {data['cookies_file']}")


def _settings_dir() -> pathlib.Path:
	override = os.environ.get(DATA_DIR_ENV, "").strip()
	if override:
		return pathlib.Path(override).expanduser()
	target, originals = _folder_candidates()
	if not any((target / name).exists() for name in ("settings.json", "library.json")):
		try:
			_seed_from_original(target, originals)
		except OSError as exc:
			_log(f"settings first run copy failed target={target} error={exc}")
	return target


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
