# tabs only
if __package__ in (None, ""):
	import sys, pathlib
	sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import builtins, os, sys, time, subprocess, pathlib


def configure_linux_webengine_environment(environment: dict[str, str] | None = None, platform_name: str | None = None) -> None:
	"""Use Chromium software rendering on Linux desktops with fragile GPU drivers."""
	env = environment if environment is not None else os.environ
	platform_value = platform_name if platform_name is not None else sys.platform
	if not platform_value.startswith("linux"):
		return
	flags = str(env.get("QTWEBENGINE_CHROMIUM_FLAGS") or "").split()
	for flag in ("--disable-gpu", "--disable-gpu-compositing"):
		if flag not in flags:
			flags.append(flag)
	env["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)
	env.setdefault("QT_OPENGL", "software")


def configure_qt_logging(environment: dict[str, str] | None = None) -> None:
	"""Hide Qt's harmless warnings for malformed image ICC metadata."""
	env = environment if environment is not None else os.environ
	rules = [rule.strip() for rule in str(env.get("QT_LOGGING_RULES") or "").split(";") if rule.strip()]
	icc_rule = "qt.gui.icc.warning=false"
	if icc_rule not in rules:
		rules.append(icc_rule)
	env["QT_LOGGING_RULES"] = ";".join(rules)


# These values must be set before importing PySide6/QtWebEngine. The embedded
# Spotify scanner is the only interface that needs Chromium rendering.
configure_linux_webengine_environment()
configure_qt_logging()
from csvmusic.core.webengine_env import configure_webengine_background_flags
configure_webengine_background_flags()

# --- Hard block tkinter imports everywhere (some libs import it implicitly) ---
_orig_import = builtins.__import__
def _no_tk_import(name, globals=None, locals=None, fromlist=(), level=0):
	if name in ("tkinter", "_tkinter", "Tkinter") or name.startswith("tkinter."):
		raise ImportError("tkinter disabled")
	return _orig_import(name, globals, locals, fromlist, level)
builtins.__import__ = _no_tk_import  # install ASAP

# --- If a Tk root sneaks in before the block (rare), close its window quickly ---
try:
	import ctypes
	user32 = ctypes.windll.user32
	for _ in range(20):  # up to ~1s
		hwnd = user32.FindWindowW("TkTopLevel", None)
		if hwnd:
			user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
			break
		time.sleep(0.05)
except Exception:
	pass

# QtWebEngine precisa ser importado antes de criar o QApplication.
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

from csvmusic.core.log import log
from csvmusic.core.paths import app_icon_path
from csvmusic.core.settings import load_settings
from csvmusic.version import APP_VERSION


class AppPage(QWebEnginePage):
	"""Só o endereço local abre dentro do app; link de fora vai para o navegador do Mac."""

	def __init__(self, origin: str, parent=None):
		super().__init__(parent)
		self.origin = origin.rstrip("/")

	def acceptNavigationRequest(self, url: QUrl, navigation_type, is_main_frame: bool) -> bool:
		text = url.toString()
		if text == self.origin or text.startswith(self.origin + "/"):
			return True
		if url.scheme() in ("http", "https", "mailto"):
			QDesktopServices.openUrl(url)
		return False

	def createWindow(self, _window_type):
		# target="_blank": a página descartável manda o endereço para o navegador do Mac.
		page = AppPage(self.origin, self)
		page.urlChanged.connect(lambda url, temporary=page: (QDesktopServices.openUrl(url), temporary.deleteLater()))
		return page


class MainWindow(QMainWindow):
	def __init__(self, engine, server, host):
		super().__init__()
		self.engine = engine
		self.server = server
		self.host = host
		self._closing = False
		self.setWindowTitle("CSVMusic")
		self.resize(1280, 820)
		self.view = QWebEngineView(self)
		self.page = AppPage(server.url, self.view)
		self.page.profile().downloadRequested.connect(self._download_requested)
		self.view.setPage(self.page)
		self.setCentralWidget(self.view)
		self._build_menu()
		self.view.setUrl(QUrl(server.url))

	def _action(self, menu, text: str, slot, shortcut=None, role=None) -> QAction:
		action = QAction(text, self)
		if shortcut is not None:
			action.setShortcut(shortcut)
		if role is not None:
			action.setMenuRole(role)
		action.triggered.connect(slot)
		menu.addAction(action)
		return action

	def _build_menu(self) -> None:
		bar = self.menuBar()
		app_menu = bar.addMenu("CSVMusic")
		# No Mac, os papéis levam estas ações para o menu do app (CSVMusic › Sobre, Ajustes, Sair).
		self._action(app_menu, "Sobre o CSVMusic", lambda: self._page_action("about"), role=QAction.AboutRole)
		self._action(app_menu, "Ajustes…", lambda: self._page_action("settings"), QKeySequence.Preferences, QAction.PreferencesRole)
		self._action(app_menu, "Sair do CSVMusic", self.close, QKeySequence.Quit, QAction.QuitRole)
		file_menu = bar.addMenu("Arquivo")
		self._action(file_menu, "Adicionar playlist", lambda: self._page_action("add_playlist"), QKeySequence.New)
		self._action(file_menu, "Importar planilha…", self._import_csv)
		file_menu.addSeparator()
		self._action(file_menu, "Abrir biblioteca…", self._open_library)
		self._action(file_menu, "Salvar biblioteca como…", self._save_library_as)
		file_menu.addSeparator()
		self._action(file_menu, "Abrir no navegador", lambda: QDesktopServices.openUrl(QUrl(self.server.url)))

	def _page_action(self, action: str) -> None:
		self.engine.emit("menu", {"action": action})

	def _import_csv(self) -> None:
		path = self.host.choose_file("csv")
		if path:
			self._run(lambda: self.engine.import_csv_path(path))

	def _open_library(self) -> None:
		path = self.host.choose_file("library")
		if path:
			self._run(lambda: self.engine.open_library(path))

	def _save_library_as(self) -> None:
		path = self.host.save_file("library", str(self.engine.library_path))
		if path:
			self._run(lambda: self.engine.save_library_as(path))

	def _run(self, action) -> None:
		from csvmusic.engine import EngineError
		try:
			action()
		except EngineError as exc:
			self.engine.warn(exc.message)

	def _download_requested(self, download) -> None:
		# Exportar planilha: o arquivo vem do servidor local; o Mac pergunta onde salvar.
		suggested = str(pathlib.Path.home() / "Downloads" / (download.downloadFileName() or "playlist.csv"))
		path, _ = QFileDialog.getSaveFileName(self, "Salvar planilha", suggested, "Planilha CSV (*.csv)")
		if not path:
			download.cancel()
			return
		target = pathlib.Path(path)
		download.setDownloadDirectory(str(target.parent))
		download.setDownloadFileName(target.name)
		download.accept()

	def shutdown_once(self) -> None:
		"""Grava a biblioteca e desliga o servidor (uma vez só, venha de fechar a janela ou do Sair)."""
		if self._closing:
			return
		self._closing = True
		log("main window closing: saving library and stopping server")
		try:
			self.engine.shutdown()
		finally:
			self.server.stop()

	def closeEvent(self, event) -> None:
		# Fechar a janela grava a biblioteca e encerra o app.
		self.shutdown_once()
		super().closeEvent(event)
		QApplication.instance().quit()


def _smoke_test(app: QApplication) -> int:
	# Testa os plugins do Qt e o WebEngine do pacote sem carregar biblioteca nem acessar a rede.
	from PySide6.QtWidgets import QLabel
	label = QLabel("CSVMusic startup check")
	label.show()
	page = QWebEnginePage()
	page.loadFinished.connect(lambda ok: app.exit(0 if ok else 1))
	QTimer.singleShot(15000, lambda: app.exit(2))
	page.setHtml("<html><body>CSVMusic startup check</body></html>")
	return app.exec()


def main() -> int:
	app = QApplication(sys.argv)
	app.setApplicationName("CSVMusic")
	app.setApplicationDisplayName("CSVMusic")
	if "--smoke-test" in sys.argv:
		return _smoke_test(app)
	icon_path = app_icon_path()
	if icon_path:
		app.setWindowIcon(QIcon(str(icon_path)))
	from csvmusic.engine import Engine
	from csvmusic.web.native import NativeHost
	from csvmusic.web.server import WebServer
	host = NativeHost()
	engine = Engine(host=host)
	server = WebServer(engine, port=int(load_settings().get("web_port") or 8765))
	server.start()
	window = MainWindow(engine, server, host)
	host.window = window
	app.aboutToQuit.connect(window.shutdown_once)
	window.show()
	QTimer.singleShot(1000, engine.start_session_check)
	log(f"CSVMusic {APP_VERSION} started web interface url={server.url}")
	return app.exec()


if __name__ == "__main__":
	sys.exit(main())
