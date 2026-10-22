# tabs only
"""Servidor HTTP local da interface (docs/fork/14-interface-web.md §1, §3–§5).

Biblioteca padrão do Python (ThreadingHTTPServer), só em 127.0.0.1.
Segurança: token aleatório por execução (cabeçalho X-CSVMusic-Token, ou
`?token=` só em /api/events), conferência do Host contra DNS rebinding,
nenhuma resposta CORS. As chamadas ao motor passam pela ponte para a
thread do Qt.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import mimetypes
import pathlib
import queue
import re
import secrets
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from csvmusic.core.log import log
from csvmusic.engine.engine import EngineError
from csvmusic.web.bridge import BridgeTimeout, EngineBridge, EventHub

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
TOKEN_HEADER = "X-CSVMusic-Token"
TOKEN_PLACEHOLDER = "{{CSVMUSIC_TOKEN}}"
MAX_BODY_BYTES = 60 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
SSE_KEEPALIVE_S = 15.0
DIALOG_TIMEOUT_S = 15 * 60.0
DEFAULT_TIMEOUT_S = 30.0

# Só https e só destes servidores de capa.
_IMAGE_HOSTS_EXACT = {"i.scdn.co", "mosaic.scdn.co", "m.media-amazon.com"}
_IMAGE_HOST_PATTERNS = (
	re.compile(r"^image-cdn-[a-z0-9-]+\.spotifycdn\.com$"),
	re.compile(r"^([a-z0-9-]+\.)+ytimg\.com$"),
	re.compile(r"^([a-z0-9-]+\.)+googleusercontent\.com$"),
	re.compile(r"^([a-z0-9-]+\.)+mzstatic\.com$"),
	re.compile(r"^([a-z0-9-]+\.)+dzcdn\.net$"),
)
_IMAGE_SIGNATURES = (
	(b"\xff\xd8\xff", "image/jpeg"),
	(b"\x89PNG\r\n\x1a\n", "image/png"),
	(b"GIF87a", "image/gif"),
	(b"GIF89a", "image/gif"),
)

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("application/json", ".json")


def image_url_allowed(url: str) -> bool:
	try:
		parsed = urllib.parse.urlsplit(str(url or ""))
	except ValueError:
		return False
	if parsed.scheme != "https" or parsed.username or parsed.password:
		return False
	host = (parsed.hostname or "").casefold()
	if parsed.port not in (None, 443):
		return False
	return host in _IMAGE_HOSTS_EXACT or any(pattern.match(host) for pattern in _IMAGE_HOST_PATTERNS)


def sniff_image_type(data: bytes) -> str | None:
	for signature, content_type in _IMAGE_SIGNATURES:
		if data.startswith(signature):
			return content_type
	if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
		return "image/webp"
	return None


class _AllowedRedirects(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, req, fp, code, msg, headers, newurl):
		if not image_url_allowed(newurl):
			raise urllib.error.HTTPError(newurl, code, "redirect outside the allowed image hosts", headers, fp)
		return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_image(url: str) -> bytes:
	"""Baixa uma capa (rede). Trocado nos testes."""
	opener = urllib.request.build_opener(_AllowedRedirects)
	request = urllib.request.Request(url, headers={"User-Agent": "CSVMusic"})
	with opener.open(request, timeout=10) as response:
		data = response.read(MAX_IMAGE_BYTES + 1)
	if len(data) > MAX_IMAGE_BYTES:
		raise ValueError("image too large")
	return data


class ImageCache:
	def __init__(self, folder: pathlib.Path, fetcher: Callable[[str], bytes] = fetch_image):
		self.folder = folder
		self.fetcher = fetcher
		self._locks: dict[str, threading.Lock] = {}
		self._guard = threading.Lock()

	def _path(self, url: str) -> pathlib.Path:
		return self.folder / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".img")

	def get(self, url: str) -> tuple[bytes, str]:
		path = self._path(url)
		with self._guard:
			lock = self._locks.setdefault(path.name, threading.Lock())
		with lock:
			if path.is_file():
				data = path.read_bytes()
				kind = sniff_image_type(data)
				if kind:
					return data, kind
			data = self.fetcher(url)
			kind = sniff_image_type(data)
			if not kind:
				raise ValueError("not an image")
			self.folder.mkdir(parents=True, exist_ok=True)
			temporary = path.with_suffix(".tmp")
			temporary.write_bytes(data)
			temporary.replace(path)
			return data, kind


class Route:
	def __init__(self, method: str, pattern: str, handler: Callable, *, raw: bool = False):
		self.method = method
		self.regex = re.compile("^" + pattern + "$")
		self.handler = handler
		self.raw = raw


class HttpError(Exception):
	def __init__(self, status: int, message: str, **extra: Any):
		super().__init__(message)
		self.status = status
		self.message = message
		self.extra = extra


class WebServer:
	"""Sobe o servidor numa thread própria. `url` traz o endereço da página (sem o token)."""

	def __init__(self, engine, *, port: int = 8765, bridge: EngineBridge | None = None, static_dir: pathlib.Path = STATIC_DIR,
	             image_cache_dir: pathlib.Path | None = None, image_fetcher: Callable[[str], bytes] = fetch_image,
	             token: str | None = None):
		self.engine = engine
		self.bridge = bridge or EngineBridge()
		self.static_dir = pathlib.Path(static_dir)
		self.token = token or secrets.token_urlsafe(32)
		self.hub = EventHub()
		if image_cache_dir is None:
			from csvmusic.core.settings import settings_path
			image_cache_dir = settings_path().parent / "image-cache"
		self.images = ImageCache(pathlib.Path(image_cache_dir), image_fetcher)
		self.requested_port = int(port or 0)
		self.httpd: ThreadingHTTPServer | None = None
		self.thread: threading.Thread | None = None
		self.routes = self._routes()
		self.engine.add_listener(self.hub.publish)

	# --- ciclo de vida ---------------------------------------------------------------

	def start(self) -> None:
		handler = self._handler_class()
		try:
			self.httpd = _Server(("127.0.0.1", self.requested_port), handler)
		except OSError as exc:
			log(f"web server port busy port={self.requested_port} error={exc}; using a free port")
			self.httpd = _Server(("127.0.0.1", 0), handler)
		self.thread = threading.Thread(target=self.httpd.serve_forever, name="csvmusic-web", daemon=True)
		self.thread.start()
		log(f"web server listening url={self.url}")

	@property
	def port(self) -> int:
		return int(self.httpd.server_address[1]) if self.httpd else 0

	@property
	def url(self) -> str:
		return f"http://127.0.0.1:{self.port}/"

	def stop(self) -> None:
		self.engine.remove_listener(self.hub.publish)
		self.hub.close()
		if self.httpd is not None:
			self.httpd.shutdown()
			self.httpd.server_close()
			self.httpd = None
		if self.thread is not None:
			self.thread.join(timeout=5)
			self.thread = None
		log("web server stopped")

	# --- rotas ---------------------------------------------------------------------------

	def _routes(self) -> list[Route]:
		pid = r"(?P<pid>[^/]+)"
		idx = r"(?P<index>\d+)"
		did = r"(?P<did>[0-9a-f]{6,40})"
		return [
			Route("GET", r"/api/state", self.api_state),
			Route("GET", rf"/api/playlists/{pid}/tracks", self.api_tracks),
			Route("POST", r"/api/playlists", self.api_add_playlists),
			Route("POST", r"/api/playlists/import-csv", self.api_import_csv),
			Route("POST", rf"/api/playlists/{pid}/tracks/set-enabled", self.api_set_enabled),
			Route("PATCH", rf"/api/playlists/{pid}/tracks/{idx}", self.api_update_track),
			Route("POST", rf"/api/playlists/{pid}/tracks/{idx}/accept", self.api_accept),
			Route("GET", rf"/api/playlists/{pid}/tracks/{idx}/alternatives", self.api_alternatives),
			Route("POST", rf"/api/playlists/{pid}/tracks/{idx}/download-now", self.api_download_now),
			Route("PATCH", rf"/api/playlists/{pid}", self.api_rename),
			Route("DELETE", rf"/api/playlists/{pid}", self.api_remove),
			Route("POST", r"/api/scan", self.api_scan),
			Route("POST", r"/api/scan/cancel", self.api_scan_cancel),
			Route("POST", r"/api/download", self.api_download),
			Route("POST", r"/api/download/stop", self.api_download_stop),
			Route("GET", r"/api/video-info", self.api_video_info),
			Route("GET", r"/api/settings", self.api_settings),
			Route("PATCH", r"/api/settings", self.api_update_settings),
			Route("POST", r"/api/dialogs/choose-folder", self.api_choose_folder),
			Route("POST", r"/api/dialogs/choose-file", self.api_choose_file),
			Route("POST", r"/api/library/open", self.api_library_open),
			Route("POST", r"/api/library/save-as", self.api_library_save_as),
			Route("POST", r"/api/open", self.api_open),
			Route("GET", r"/api/export-csv", self.api_export_csv, raw=True),
			Route("POST", r"/api/account/youtube/sign-in", self.api_sign_in),
			Route("POST", r"/api/account/youtube/sign-out", self.api_sign_out),
			Route("POST", r"/api/account/youtube/test", self.api_account_test),
			Route("POST", r"/api/age-restricted/resolve", self.api_age_resolve),
			Route("POST", r"/api/age-restricted/retry", self.api_age_retry),
			Route("GET", r"/api/log", self.api_log),
			Route("GET", r"/api/devices", self.api_devices),
			Route("GET", rf"/api/devices/{did}/playlists", self.api_device_playlists),
			Route("POST", rf"/api/devices/{did}/sync", self.api_device_sync),
			Route("DELETE", rf"/api/devices/{did}/playlists/(?P<name>[^/]+)", self.api_device_delete),
			Route("POST", rf"/api/devices/{did}/eject", self.api_device_eject),
			Route("GET", r"/api/trash", self.api_trash),
			Route("POST", r"/api/trash/empty", self.api_trash_empty),
			Route("GET", r"/api/image", self.api_image, raw=True),
			Route("POST", r"/api/first-run/accept", self.api_first_run),
		]

	def call(self, fn: Callable, *args: Any, timeout: float = DEFAULT_TIMEOUT_S, **kwargs: Any) -> Any:
		return self.bridge.call(fn, *args, timeout=timeout, **kwargs)

	@staticmethod
	def _int(query: dict, name: str, default: int) -> int:
		try:
			return int(query.get(name, [default])[0])
		except (TypeError, ValueError) as exc:
			raise HttpError(400, f"Parâmetro inválido: {name}") from exc

	@staticmethod
	def _q(query: dict, name: str, default: str = "") -> str:
		return str(query.get(name, [default])[0] or default)

	def api_state(self, match, query, body):
		return self.call(self.engine.state)

	def api_tracks(self, match, query, body):
		return self.call(
			self.engine.tracks, match["pid"], filter_name=self._q(query, "filter", "all"), query=self._q(query, "q"),
			offset=self._int(query, "offset", 0), limit=self._int(query, "limit", 100),
		)

	def api_add_playlists(self, match, query, body):
		urls = body.get("urls")
		if not isinstance(urls, list):
			raise HttpError(400, "Mande a lista de links em \"urls\".")
		return self.call(self.engine.add_playlists, [str(url) for url in urls])

	def api_import_csv(self, match, query, body):
		return self.call(self.engine.import_csv_content, str(body.get("filename") or ""), str(body.get("content_base64") or ""), body.get("name"))

	def api_rename(self, match, query, body):
		return self.call(self.engine.rename_playlist, match["pid"], str(body.get("name") or ""))

	def api_remove(self, match, query, body):
		return self.call(self.engine.remove_playlist, match["pid"], self._q(query, "files", "keep"))

	def api_scan(self, match, query, body):
		return self.call(self.engine.start_scan, body.get("playlist_ids"), body.get("scope"))

	def api_scan_cancel(self, match, query, body):
		return self.call(self.engine.cancel_scan)

	def api_download(self, match, query, body):
		targets = body.get("targets")
		if targets is not None:
			try:
				targets = [(str(item[0]), int(item[1])) for item in targets]
			except (TypeError, ValueError, IndexError) as exc:
				raise HttpError(400, "Lista de músicas inválida.") from exc
		return self.call(
			self.engine.start_download, body.get("playlist_ids"), missing_only=bool(body.get("missing_only", True)),
			targets=targets, confirm_risk=bool(body.get("confirm_risk", False)),
		)

	def api_download_stop(self, match, query, body):
		return self.call(self.engine.stop_download)

	def api_update_track(self, match, query, body):
		return self.call(self.engine.update_track, match["pid"], int(match["index"]), body)

	def api_set_enabled(self, match, query, body):
		indices = body.get("indices")
		if indices is not None and not isinstance(indices, list):
			raise HttpError(400, "\"indices\" precisa ser uma lista.")
		return self.call(self.engine.set_tracks_enabled, match["pid"], bool(body.get("enabled")), indices=indices, all_tracks=bool(body.get("all")))

	def api_accept(self, match, query, body):
		return self.call(self.engine.accept_review, match["pid"], int(match["index"]))

	def api_alternatives(self, match, query, body):
		track = self.call(self.engine.track_snapshot, match["pid"], int(match["index"]))
		return self.engine.fetch_alternatives(track)

	def api_video_info(self, match, query, body):
		track = None
		if query.get("playlist_id") and query.get("index"):
			track = self.call(self.engine.track_snapshot, self._q(query, "playlist_id"), self._int(query, "index", 0))
		return self.engine.fetch_video_info(self._q(query, "url"), track)

	def api_download_now(self, match, query, body):
		return self.call(self.engine.download_now, match["pid"], int(match["index"]), str(body.get("video_id") or ""))

	def api_settings(self, match, query, body):
		return self.call(self.engine.settings)

	def api_update_settings(self, match, query, body):
		return self.call(self.engine.update_settings, body)

	def api_choose_folder(self, match, query, body):
		return self.call(self.engine.choose_folder, str(body.get("purpose") or ""), str(body.get("start") or ""), timeout=DIALOG_TIMEOUT_S)

	def api_choose_file(self, match, query, body):
		return self.call(self.engine.choose_file, str(body.get("purpose") or ""), timeout=DIALOG_TIMEOUT_S)

	def api_library_open(self, match, query, body):
		return self.call(self.engine.open_library, str(body.get("path") or ""))

	def api_library_save_as(self, match, query, body):
		return self.call(self.engine.save_library_as, str(body.get("path") or ""))

	def api_open(self, match, query, body):
		index = body.get("index")
		return self.call(self.engine.open_location, str(body.get("what") or ""), body.get("playlist_id"), int(index) if index is not None else None)

	def api_export_csv(self, match, query, body):
		data, filename = self.call(self.engine.export_csv_bytes, self._q(query, "playlist_id") or None)
		quoted = urllib.parse.quote(filename)
		return 200, "text/csv; charset=utf-8", data, {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"}

	def api_sign_in(self, match, query, body):
		return self.call(self.engine.sign_in, str(body.get("method") or "popup"))

	def api_sign_out(self, match, query, body):
		return self.call(self.engine.sign_out)

	def api_account_test(self, match, query, body):
		return self.call(self.engine.test_account)

	def api_age_resolve(self, match, query, body):
		return self.call(self.engine.resolve_age_restricted)

	def api_age_retry(self, match, query, body):
		return self.call(self.engine.retry_age_restricted, bool(body.get("confirm_risk", True)))

	def api_log(self, match, query, body):
		return self.engine.log_entries(self._int(query, "since", 0))

	def api_devices(self, match, query, body):
		return self.engine.discover_devices()

	def api_device_playlists(self, match, query, body):
		result = self.engine.device_playlists(match["did"])
		raw = result.pop("_raw", [])
		result["library"] = self.call(self.engine.device_library_states, raw)
		return result

	def api_device_sync(self, match, query, body):
		return self.call(self.engine.start_device_sync, match["did"], list(body.get("playlist_ids") or []))

	def api_device_delete(self, match, query, body):
		return self.engine.delete_device_playlist(match["did"], match["name"])

	def api_device_eject(self, match, query, body):
		return self.engine.eject_device(match["did"])

	def api_trash(self, match, query, body):
		return self.call(self.engine.trash_stats)

	def api_trash_empty(self, match, query, body):
		return self.call(self.engine.empty_trash, timeout=5 * 60.0)

	def api_image(self, match, query, body):
		url = self._q(query, "url")
		if not image_url_allowed(url):
			raise HttpError(403, "Endereço de imagem fora da lista permitida.")
		try:
			data, kind = self.images.get(url)
		except Exception as exc:
			log(f"image proxy failed url={url} error={exc}")
			raise HttpError(502, "Não deu para carregar a imagem.") from exc
		return 200, kind, data, {"Cache-Control": "private, max-age=86400"}

	def api_first_run(self, match, query, body):
		return self.call(self.engine.accept_first_run)

	# --- página ----------------------------------------------------------------------

	def index_html(self) -> bytes:
		index = self.static_dir / "index.html"
		try:
			text = index.read_text(encoding="utf-8")
		except OSError:
			text = "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><title>CSVMusic</title></head><body></body></html>"
		token = html.escape(self.token, quote=True)
		if TOKEN_PLACEHOLDER in text:
			return text.replace(TOKEN_PLACEHOLDER, token).encode("utf-8")
		meta = f"<meta name=\"csvmusic-token\" content=\"{token}\">"
		match = re.search(r"<head[^>]*>", text, re.IGNORECASE)
		if match:
			text = text[:match.end()] + meta + text[match.end():]
		else:
			text = meta + text
		return text.encode("utf-8")

	def static_file(self, relative: str) -> tuple[bytes, str] | None:
		root = self.static_dir.resolve()
		try:
			target = (root / urllib.parse.unquote(relative)).resolve()
		except (OSError, ValueError):
			return None
		if not target.is_relative_to(root) or not target.is_file():
			return None
		kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
		if kind.startswith("text/") or kind in ("application/json", "image/svg+xml"):
			kind += "; charset=utf-8"
		return target.read_bytes(), kind

	# --- tratador HTTP ---------------------------------------------------------------

	def _handler_class(self):
		server = self

		class Handler(BaseHTTPRequestHandler):
			protocol_version = "HTTP/1.1"
			server_version = "CSVMusic"
			sys_version = ""

			def log_message(self, format: str, *args: Any) -> None:
				pass

			def _send(self, status: int, content_type: str, data: bytes, headers: dict | None = None) -> None:
				self.send_response(status)
				self.send_header("Content-Type", content_type)
				self.send_header("Content-Length", str(len(data)))
				self.send_header("X-Content-Type-Options", "nosniff")
				self.send_header("Referrer-Policy", "no-referrer")
				for name, value in (headers or {}).items():
					self.send_header(name, value)
				self.end_headers()
				if self.command != "HEAD":
					self.wfile.write(data)

			def _json(self, status: int, payload: Any) -> None:
				data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
				self._send(status, "application/json; charset=utf-8", data, {"Cache-Control": "no-store"})

			def _error(self, status: int, message: str, **extra: Any) -> None:
				self._json(status, {"error": message, **extra})

			def _host_ok(self) -> bool:
				host = str(self.headers.get("Host") or "").strip().casefold()
				return host in (f"127.0.0.1:{server.port}", f"localhost:{server.port}")

			def _origin_ok(self) -> bool:
				origin = self.headers.get("Origin")
				if origin is None:
					return True
				return origin.casefold() in (f"http://127.0.0.1:{server.port}", f"http://localhost:{server.port}")

			def _token_ok(self, query: dict, allow_query: bool) -> bool:
				given = str(self.headers.get(TOKEN_HEADER) or "")
				if not given and allow_query:
					given = str(query.get("token", [""])[0] or "")
				return bool(given) and hmac.compare_digest(given.encode("utf-8"), server.token.encode("utf-8"))

			def do_GET(self) -> None:
				self._dispatch("GET")

			def do_HEAD(self) -> None:
				self._dispatch("GET")

			def do_POST(self) -> None:
				self._dispatch("POST")

			def do_PATCH(self) -> None:
				self._dispatch("PATCH")

			def do_DELETE(self) -> None:
				self._dispatch("DELETE")

			def do_PUT(self) -> None:
				self._error(405, "Método não aceito.")

			def do_OPTIONS(self) -> None:
				# Sem CORS: o "preflight" de outro site recebe 403 e o navegador bloqueia.
				self._error(403, "Acesso negado.")

			def _dispatch(self, method: str) -> None:
				try:
					self._dispatch_inner(method)
				except (BrokenPipeError, ConnectionResetError):
					pass
				except Exception as exc:
					log(f"web server unexpected error path={self.path} error={exc!r}")
					try:
						self._error(500, "Erro inesperado. Veja o registro.")
					except OSError:
						pass

			def _dispatch_inner(self, method: str) -> None:
				if not self._host_ok() or not self._origin_ok():
					self._error(403, "Acesso negado.")
					return
				parsed = urllib.parse.urlsplit(self.path)
				path = parsed.path
				query = urllib.parse.parse_qs(parsed.query)
				if not path.startswith("/api/"):
					if method != "GET":
						self._error(405, "Método não aceito.")
						return
					if path in ("/", "/index.html"):
						self._send(200, "text/html; charset=utf-8", server.index_html(), {
							"Cache-Control": "no-store",
							"Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",
						})
						return
					if path.startswith("/static/"):
						found = server.static_file(path[len("/static/"):])
						if found is None:
							self._error(404, "Arquivo não encontrado.")
							return
						self._send(200, found[1], found[0], {"Cache-Control": "no-cache"})
						return
					self._error(404, "Página não encontrada.")
					return
				if path == "/api/events":
					if method != "GET" or not self._token_ok(query, allow_query=True):
						self._error(403, "Acesso negado.")
						return
					self._events()
					return
				if not self._token_ok(query, allow_query=False):
					self._error(403, "Acesso negado.")
					return
				route, match = self._find(method, path)
				if route is None:
					self._error(404 if match is None else 405, "Rota desconhecida." if match is None else "Método não aceito.")
					return
				body: dict = {}
				if method in ("POST", "PATCH", "DELETE"):
					length = int(self.headers.get("Content-Length") or 0)
					if length > MAX_BODY_BYTES:
						self._error(413, "Arquivo grande demais.")
						return
					raw = self.rfile.read(length) if length else b""
					if raw:
						try:
							body = json.loads(raw.decode("utf-8"))
						except (UnicodeDecodeError, ValueError):
							self._error(400, "O corpo do pedido não é JSON.")
							return
						if not isinstance(body, dict):
							self._error(400, "O corpo do pedido precisa ser um objeto JSON.")
							return
				params = {key: urllib.parse.unquote(value) for key, value in match.groupdict().items()}
				try:
					result = route.handler(params, query, body)
				except EngineError as exc:
					self._error(exc.status, exc.message, **exc.extra)
					return
				except HttpError as exc:
					self._error(exc.status, exc.message, **exc.extra)
					return
				except BridgeTimeout:
					self._error(504, "O app demorou para responder. Tente de novo.")
					return
				if route.raw:
					status, content_type, data, headers = result
					self._send(status, content_type, data, headers)
				else:
					self._json(200, result)

			def _find(self, method: str, path: str):
				path_matched = False
				for route in server.routes:
					match = route.regex.match(path)
					if match is None:
						continue
					path_matched = True
					if route.method == method:
						return route, match
				return None, (True if path_matched else None)

			def _events(self) -> None:
				subscriber = server.hub.subscribe()
				try:
					self.send_response(200)
					self.send_header("Content-Type", "text/event-stream; charset=utf-8")
					self.send_header("Cache-Control", "no-store")
					self.send_header("Connection", "close")
					self.send_header("X-Accel-Buffering", "no")
					self.end_headers()
					self.close_connection = True
					job = server.call(server.engine.job)
					self._write_event("job", json.dumps(job, ensure_ascii=False, default=str))
					while True:
						try:
							item = subscriber.get(timeout=SSE_KEEPALIVE_S)
						except queue.Empty:
							self.wfile.write(b": ping\n\n")
							self.wfile.flush()
							continue
						if item is EventHub.CLOSED:
							break
						kind, payload = item
						self._write_event(kind, payload)
				except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError, BridgeTimeout):
					pass
				finally:
					server.hub.unsubscribe(subscriber)

			def _write_event(self, kind: str, payload: str) -> None:
				data = "".join(f"data: {line}\n" for line in payload.splitlines() or [""])
				self.wfile.write(f"event: {kind}\n{data}\n".encode("utf-8"))
				self.wfile.flush()

		return Handler


class _Server(ThreadingHTTPServer):
	daemon_threads = True
	allow_reuse_address = True

