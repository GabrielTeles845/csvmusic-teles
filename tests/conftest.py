# tabs only
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def isolated_app_folders(tmp_path_factory):
	"""Keep the suite away from the real library, settings and log (and from the original CSVMusic's folder)."""
	patcher = pytest.MonkeyPatch()
	patcher.setenv("CSVMUSIC_DATA_DIR", str(tmp_path_factory.mktemp("app-data")))
	patcher.setenv("CSVMUSIC_LOG_DIR", str(tmp_path_factory.mktemp("app-logs")))
	yield
	patcher.undo()


@pytest.fixture(scope="session", autouse=True)
def qt_application():
	"""Keep one Qt application alive until all test widgets are disposed."""
	app = QApplication.instance() or QApplication([])
	yield app
	for widget in app.topLevelWidgets():
		widget.close()
		widget.deleteLater()
	QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
	app.processEvents()
	app.quit()
