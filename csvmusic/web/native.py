# tabs only
"""Janelas nativas que o motor pede: seletores do macOS, login do Google, leitor do Spotify, Finder.

É o único lugar da interface nova que cria widget fora da janela principal.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QWidget

from csvmusic.core.log import log

# CSVMUSIC_SHOW_SPOTIFY_READER=1 mostra o leitor do Spotify na tela (para conferir o que ele está vendo).
SHOW_READER_ENV = "CSVMUSIC_SHOW_SPOTIFY_READER"

_FILE_FILTERS = {
	"cookies": ("Escolher o arquivo de cookies do YouTube", "Cookies (*.txt);;Todos os arquivos (*)"),
	"ytdlp": ("Escolher o programa yt-dlp", "Todos os arquivos (*)"),
	"ffmpeg": ("Escolher o programa FFmpeg", "Todos os arquivos (*)"),
	"library": ("Abrir biblioteca do CSVMusic", "Biblioteca do CSVMusic (*.json)"),
	"csv": ("Importar planilha", "Planilha CSV (*.csv);;Todos os arquivos (*)"),
}
_FOLDER_TITLES = {
	"output": "Escolher a pasta das músicas",
	"m3u": "Escolher a pasta das listas de playlist",
	"tool": "Escolher a pasta",
}


class NativeHost:
	def __init__(self, window: QWidget | None = None):
		self.window = window

	def choose_folder(self, purpose: str, start: str = "") -> str | None:
		path = QFileDialog.getExistingDirectory(self.window, _FOLDER_TITLES.get(purpose, "Escolher a pasta"), start or str(pathlib.Path.home()))
		return path or None

	def choose_file(self, purpose: str) -> str | None:
		title, filters = _FILE_FILTERS.get(purpose, ("Escolher arquivo", "Todos os arquivos (*)"))
		path, _ = QFileDialog.getOpenFileName(self.window, title, str(pathlib.Path.home()), filters)
		return path or None

	def save_file(self, purpose: str, suggested: str = "") -> str | None:
		title = "Salvar biblioteca como" if purpose == "library" else "Salvar como"
		filters = "Biblioteca do CSVMusic (*.json)" if purpose == "library" else "Todos os arquivos (*)"
		path, _ = QFileDialog.getSaveFileName(self.window, title, suggested or str(pathlib.Path.home()), filters)
		return path or None

	def youtube_sign_in(self, method: str) -> str | None:
		if method == "firefox":
			from csvmusic.ui.youtube_login import YouTubeLoginDialog
			dialog = YouTubeLoginDialog(self.window)
		else:
			from csvmusic.ui.youtube_popup import YouTubePopupDialog
			dialog = YouTubePopupDialog(self.window)
		try:
			accepted = dialog.exec() == QDialog.Accepted
			return str(dialog.cookie_path or "") if accepted and dialog.cookie_path else None
		finally:
			dialog.deleteLater()

	def create_spotify_reader(self):
		from csvmusic.ui.spotify_public_scrape import SpotifyPublicScrapeDialog
		reader = SpotifyPublicScrapeDialog(None)
		reader.setWindowTitle("CSVMusic — leitor do Spotify")
		reader.resize(1100, 780)
		if os.environ.get(SHOW_READER_ENV) != "1":
			# Fora da vista: sem moldura, sem foco, sem clique, longe da tela. As flags do Chromium
			# (core/webengine_env.py) impedem que a página desacelere por estar coberta.
			reader.setWindowFlags(
				Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput,
			)
			reader.setAttribute(Qt.WA_ShowWithoutActivating, True)
		return reader

	def show_spotify_reader(self, reader) -> None:
		try:
			reader.page.setVisible(True)
		except Exception:
			pass
		if os.environ.get(SHOW_READER_ENV) != "1":
			reader.move(-20000, -20000)
		reader.show()

	def hide_spotify_reader(self, reader) -> None:
		reader.hide()

	def open_path(self, path: str) -> bool:
		return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))

	def reveal_path(self, path: str) -> bool:
		target = pathlib.Path(path)
		if sys.platform == "darwin":
			try:
				subprocess.run(["open", "-R", str(target)], check=True, timeout=10)
				return True
			except (OSError, subprocess.SubprocessError) as exc:
				log(f"reveal in Finder failed path={target} error={exc}")
				return False
		return self.open_path(str(target.parent if target.is_file() else target))
