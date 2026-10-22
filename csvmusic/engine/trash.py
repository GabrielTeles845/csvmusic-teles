# tabs only
"""Lixeira: nada que é do usuário some de vez.

- A pasta de uma playlist removida vai para a Lixeira do macOS.
- "Esvaziar" a lixeira interna (`.csvmusic-lixeira` dentro de cada pasta de
  playlist) também manda os arquivos para a Lixeira do macOS.
"""
from __future__ import annotations

import pathlib

from csvmusic.core.downloader import TRASH_DIR_NAME
from csvmusic.core.log import log


class TrashError(OSError):
	"""O sistema não aceitou mandar para a Lixeira; nada foi apagado."""


def move_to_system_trash(path: str | pathlib.Path) -> str | None:
	"""Manda um arquivo ou pasta para a Lixeira do sistema e devolve onde ficou (quando o Qt informa)."""
	from PySide6.QtCore import QFile
	target = pathlib.Path(path)
	if not target.exists():
		return None
	moved, where = QFile.moveToTrash(str(target))
	if not moved:
		raise TrashError(f"could not move to the system trash: {target}")
	log(f"moved to system trash path={target} trashed_as={where}")
	return str(where or "") or None


def internal_trash_folders(output_dir: str | pathlib.Path) -> list[pathlib.Path]:
	root = pathlib.Path(output_dir)
	if not str(output_dir) or not root.is_dir():
		return []
	folders: list[pathlib.Path] = []
	try:
		for playlist_folder in root.iterdir():
			trash = playlist_folder / TRASH_DIR_NAME
			if playlist_folder.is_dir() and trash.is_dir():
				folders.append(trash)
	except OSError as exc:
		log(f"internal trash listing failed root={root} error={exc}")
	return folders


def internal_trash_stats(output_dir: str | pathlib.Path) -> dict:
	files = 0
	size = 0
	for folder in internal_trash_folders(output_dir):
		for item in folder.rglob("*"):
			if item.is_file():
				files += 1
				try:
					size += item.stat().st_size
				except OSError:
					pass
	return {"files": files, "bytes": size}


def empty_internal_trash(output_dir: str | pathlib.Path, mover=move_to_system_trash) -> int:
	"""Manda cada arquivo da lixeira interna para a Lixeira do sistema; devolve quantos foram."""
	moved = 0
	for folder in internal_trash_folders(output_dir):
		for item in sorted(folder.iterdir()):
			try:
				mover(item)
				moved += 1
			except OSError as exc:
				log(f"internal trash item not moved path={item} error={exc}")
		try:
			folder.rmdir()
		except OSError:
			pass
	return moved
