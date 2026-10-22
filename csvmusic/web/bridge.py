# tabs only
"""Ponte entre as threads do servidor HTTP e o motor na thread do Qt.

O servidor nunca mexe na biblioteca direto: entrega a função para a thread
do Qt (sinal com conexão em fila) e espera o resultado com tempo limite.
Os eventos do motor seguem o caminho contrário por filas, uma por página
conectada.
"""
from __future__ import annotations

import json
import queue
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot


class BridgeTimeout(TimeoutError):
	"""O motor não respondeu a tempo."""


class _Task:
	__slots__ = ("fn", "args", "kwargs", "done", "result", "error")

	def __init__(self, fn: Callable, args: tuple, kwargs: dict):
		self.fn = fn
		self.args = args
		self.kwargs = kwargs
		self.done = threading.Event()
		self.result: Any = None
		self.error: BaseException | None = None


class EngineBridge(QObject):
	_invoke = Signal(object)

	def __init__(self, parent: QObject | None = None):
		super().__init__(parent)
		# Criada na thread do Qt. Comparar com threading (e não com QThread.currentThread()) evita
		# criar, numa thread do servidor, um QThread do Python que fica solto quando a thread acaba.
		self._owner_ident = threading.get_ident()
		self._invoke.connect(self._run, Qt.QueuedConnection)

	def call(self, fn: Callable, *args: Any, timeout: float = 30.0, **kwargs: Any) -> Any:
		if threading.get_ident() == self._owner_ident:
			return fn(*args, **kwargs)
		task = _Task(fn, args, kwargs)
		self._invoke.emit(task)
		if not task.done.wait(timeout):
			raise BridgeTimeout(f"engine call timed out: {getattr(fn, '__name__', fn)}")
		if task.error is not None:
			raise task.error
		return task.result

	@Slot(object)
	def _run(self, task: _Task) -> None:
		try:
			task.result = task.fn(*task.args, **task.kwargs)
		except BaseException as exc:
			task.error = exc
		finally:
			task.done.set()


class EventHub:
	"""Distribui os eventos do motor para cada conexão SSE (thread-safe)."""

	CLOSED = object()

	def __init__(self, max_queue: int = 2000):
		self._lock = threading.Lock()
		self._queues: list[queue.Queue] = []
		self._max_queue = max_queue

	def subscribe(self) -> queue.Queue:
		subscriber: queue.Queue = queue.Queue(maxsize=self._max_queue)
		with self._lock:
			self._queues.append(subscriber)
		return subscriber

	def unsubscribe(self, subscriber: queue.Queue) -> None:
		with self._lock:
			if subscriber in self._queues:
				self._queues.remove(subscriber)

	def publish(self, kind: str, data: dict) -> None:
		# Serializa já na thread de quem publica: o dicionário pode mudar depois.
		payload = json.dumps(data, ensure_ascii=False, default=str)
		with self._lock:
			targets = list(self._queues)
		for subscriber in targets:
			try:
				subscriber.put_nowait((kind, payload))
			except queue.Full:
				# Página parada (aba dormindo): melhor perder eventos do que travar o motor.
				pass

	def subscriber_count(self) -> int:
		with self._lock:
			return len(self._queues)

	def close(self) -> None:
		with self._lock:
			targets = list(self._queues)
			self._queues.clear()
		for subscriber in targets:
			try:
				subscriber.put_nowait(self.CLOSED)
			except queue.Full:
				pass
