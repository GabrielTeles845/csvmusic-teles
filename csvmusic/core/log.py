# tabs only
import datetime
import pathlib
import sys
import threading

# Fork's own folder, so the original CSVMusic and this one never share a log.
LOG_FOLDER_NAME = "CSVMusicTeles"
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3

_lock = threading.Lock()


def log_dir() -> pathlib.Path:
	home = pathlib.Path.home()
	if sys.platform.startswith("darwin"):
		return home / "Library" / "Logs" / LOG_FOLDER_NAME
	return home / ".local" / "share" / "csvmusicteles" / "logs"


def log_path() -> pathlib.Path:
	base = log_dir()
	base.mkdir(parents=True, exist_ok=True)
	return base / "app.log"


def _rotate(path: pathlib.Path) -> None:
	"""app.log -> app.log.1 -> ... -> app.log.<LOG_BACKUPS>; the oldest is dropped."""
	for index in range(LOG_BACKUPS, 0, -1):
		source = path if index == 1 else path.with_name(f"{path.name}.{index - 1}")
		if source.exists():
			source.replace(path.with_name(f"{path.name}.{index}"))


def log(msg: str) -> None:
	ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	line = f"[{ts}] {msg}\n"
	try:
		with _lock:
			path = log_path()
			try:
				if path.stat().st_size + len(line) > MAX_LOG_BYTES:
					_rotate(path)
			except FileNotFoundError:
				pass
			with path.open("a", encoding="utf-8") as f:
				f.write(line)
	except Exception:
		# last resort
		sys.stderr.write(line)
