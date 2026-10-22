# tabs only
"""
Fill missing song durations in library.json from a CSV, matching by Spotify id.

	python -m csvmusic.tools.fill_durations --csv musicas.csv [--library library.json] [--dry-run]

Only tracks with duration_ms == 0 are touched, and only their duration fields.
A dated backup of library.json is written before saving. Refuses to run while
CSVMusic is open, because the app rewrites the library when it closes.
"""
import argparse
import datetime
import os
import pathlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from csvmusic.core.csv_import import load_csv, tracks_from_csv
from csvmusic.core.library import load_library, save_library
from csvmusic.core.log import log

# Command-line fragments that identify a running CSVMusic window (source or packaged).
_APP_MARKERS = (
	"csvmusic.app",  # python -m csvmusic.app and /CSVMusic.app/Contents/MacOS/CSVMusic
	"csvmusic/app.py",
	"csvmusic.exe",
	"csvmusic/__main__.py",
)
# `python -m csvmusic` (csvmusic/__main__.py opens the app); not `-m csvmusic.<tool>`.
_PACKAGE_ENTRY = re.compile(r"(?:^|\s)-m\s+csvmusic(?:\s|$)")


@dataclass
class FillResult:
	filled: int = 0
	already_had_duration: int = 0
	without_csv_match: int = 0
	csv_rows_unused: int = 0
	filled_by_playlist: Dict[str, int] = field(default_factory=dict)


def durations_from_csv(path: str | pathlib.Path) -> Dict[str, dict]:
	"""Spotify id → {duration_ms, duration_precision_s} for every CSV row with a duration."""
	out: Dict[str, dict] = {}
	for track in tracks_from_csv(load_csv(path)):
		track_id = str(track.get("sp_id") or "").strip()
		duration_ms = int(track.get("duration_ms") or 0)
		if track_id and duration_ms > 0 and track_id not in out:
			out[track_id] = {
				"duration_ms": duration_ms,
				"duration_precision_s": track.get("duration_precision_s"),
			}
	return out


def fill_library_durations(library: dict, durations: Dict[str, dict]) -> FillResult:
	"""Write CSV durations into tracks whose duration_ms is 0. Changes nothing else."""
	result = FillResult()
	used: set[str] = set()
	for playlist in library.get("playlists") or []:
		name = str(playlist.get("name") or playlist.get("id") or "?")
		for track in playlist.get("tracks") or []:
			track_id = str(track.get("sp_id") or "").strip()
			try:
				current = int(track.get("duration_ms") or 0)
			except (TypeError, ValueError):
				current = 0
			if current > 0:
				result.already_had_duration += 1
				if track_id in durations:
					used.add(track_id)
				continue
			found = durations.get(track_id) if track_id else None
			if not found:
				result.without_csv_match += 1
				continue
			used.add(track_id)
			track["duration_ms"] = int(found["duration_ms"])
			track["duration_source"] = "csv"
			track["duration_precision_s"] = found.get("duration_precision_s")
			result.filled += 1
			result.filled_by_playlist[name] = result.filled_by_playlist.get(name, 0) + 1
	result.csv_rows_unused = len(set(durations) - used)
	return result


def running_app_lines(process_lines: Iterable[str], own_pid: Optional[int] = None) -> List[str]:
	"""Lines of a process listing ("pid command") that look like an open CSVMusic window."""
	found: List[str] = []
	for line in process_lines:
		text = line.strip()
		if not text:
			continue
		pid_text, _, command = text.partition(" ")
		if own_pid is not None and pid_text.isdigit() and int(pid_text) == own_pid:
			continue
		lowered = command.casefold() if pid_text.isdigit() else text.casefold()
		if "fill_durations" in lowered:
			continue
		if any(marker in lowered for marker in _APP_MARKERS) or _PACKAGE_ENTRY.search(lowered):
			found.append(text)
	return found


def _process_lines() -> List[str]:
	if sys.platform.startswith("win"):
		output = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False).stdout
		return [line.replace('"', " ").strip() for line in output.splitlines()]
	output = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
	return output.splitlines()


def backup_library(path: pathlib.Path, now: Optional[datetime.datetime] = None) -> pathlib.Path:
	"""Copy library.json to library.json.bak-YYYYMMDD-HHMMSS next to it (never overwrites a backup)."""
	stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
	target = path.with_name(f"{path.name}.bak-{stamp}")
	counter = 1
	while target.exists():
		target = path.with_name(f"{path.name}.bak-{stamp}-{counter}")
		counter += 1
	shutil.copy2(path, target)
	return target


def _default_library_path() -> pathlib.Path:
	from csvmusic.core.settings import settings_path
	return settings_path().parent / "library.json"


def main(argv: Optional[List[str]] = None, process_lines: Optional[List[str]] = None) -> int:
	parser = argparse.ArgumentParser(
		prog="python -m csvmusic.tools.fill_durations",
		description="Preenche a duração das músicas da biblioteca a partir de uma planilha, pelo ID do Spotify.",
	)
	parser.add_argument("--csv", required=True, help="planilha com colunas de link/ID do Spotify e duração")
	parser.add_argument("--library", help="library.json (padrão: o da pasta de configurações do CSVMusic)")
	parser.add_argument("--dry-run", action="store_true", help="só mostra o que faria, sem gravar")
	args = parser.parse_args(argv)

	library_path = pathlib.Path(args.library).expanduser() if args.library else _default_library_path()
	csv_path = pathlib.Path(args.csv).expanduser()
	if not library_path.is_file():
		print(f"Biblioteca não encontrada: {library_path}", file=sys.stderr)
		return 2
	if not csv_path.is_file():
		print(f"Planilha não encontrada: {csv_path}", file=sys.stderr)
		return 2

	running = running_app_lines(process_lines if process_lines is not None else _process_lines(), os.getpid())
	if running and not args.dry_run:
		log(f"fill_durations refused app_running count={len(running)}")
		print(
			"O CSVMusic está aberto. Feche o app antes (ele regrava a biblioteca ao fechar) e rode de novo.",
			file=sys.stderr,
		)
		for line in running:
			print(f"  {line}", file=sys.stderr)
		return 3

	library = load_library(library_path)
	durations = durations_from_csv(csv_path)
	result = fill_library_durations(library, durations)

	print(f"Planilha: {len(durations)} músicas com duração e ID do Spotify.")
	print(f"Preenchidas: {result.filled}")
	print(f"Já tinham duração: {result.already_had_duration}")
	print(f"Sem par na planilha: {result.without_csv_match}")
	print(f"Linhas da planilha sem música na biblioteca: {result.csv_rows_unused}")
	for name, count in sorted(result.filled_by_playlist.items()):
		print(f"  {name}: {count}")

	if args.dry_run or result.filled == 0:
		print("Nada gravado." if result.filled == 0 else "Teste (--dry-run): nada gravado.")
		return 0
	backup = backup_library(library_path)
	save_library(library_path, library)
	log(
		f"fill_durations saved library={library_path} backup={backup.name} filled={result.filled} "
		f"unmatched={result.without_csv_match} csv_unused={result.csv_rows_unused}"
	)
	print(f"Backup: {backup}")
	print(f"Gravado: {library_path}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
