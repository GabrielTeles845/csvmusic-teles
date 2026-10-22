# tabs only
"""Ponte servidor → thread do Qt: pedido que estourou o tempo não roda depois."""
import threading
import time

import pytest

from csvmusic.web.bridge import BridgeTimeout, EngineBridge


def _call_in_thread(bridge, fn, timeout):
	box: dict = {}

	def run():
		try:
			box["result"] = bridge.call(fn, timeout=timeout)
		except BaseException as exc:
			box["error"] = exc

	thread = threading.Thread(target=run, daemon=True)
	thread.start()
	return thread, box


def test_call_that_timed_out_is_not_run_later(qt_application):
	bridge = EngineBridge()
	ran = []
	# O laço do Qt está "ocupado" (não roda processEvents) até o pedido estourar o tempo.
	thread, box = _call_in_thread(bridge, lambda: ran.append("rodou"), timeout=0.05)
	thread.join(5)
	assert isinstance(box.get("error"), BridgeTimeout)
	deadline = time.monotonic() + 0.3
	while time.monotonic() < deadline:
		qt_application.processEvents()
		time.sleep(0.01)
	assert ran == []
	bridge.deleteLater()


def test_call_answered_in_time_returns_the_result(qt_application):
	bridge = EngineBridge()
	thread, box = _call_in_thread(bridge, lambda: 42, timeout=5)
	deadline = time.monotonic() + 5
	while thread.is_alive() and time.monotonic() < deadline:
		qt_application.processEvents()
		time.sleep(0.005)
	assert box == {"result": 42}
	with pytest.raises(ZeroDivisionError):
		bridge.call(lambda: 1 / 0)
	bridge.deleteLater()
