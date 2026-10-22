# tabs only
"""Servidor local de verdade, em porta livre; o motor usa workers falsos e nada vai para a rede."""
import http.client
import json
import socket
import threading
import time

import pytest

from csvmusic.web.server import WebServer, image_url_allowed, sniff_image_type

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def _wait(app, done: threading.Event, timeout: float = 10.0) -> None:
	deadline = time.monotonic() + timeout
	while not done.is_set() and time.monotonic() < deadline:
		app.processEvents()
		time.sleep(0.005)
	assert done.is_set(), "a resposta não chegou"


def _request(app, server, method: str, path: str, *, body=None, token: bool = True, host: str | None = None, headers=None):
	"""Faz o pedido numa thread e roda o laço do Qt enquanto espera (o motor responde na thread do Qt)."""
	result: dict = {}
	done = threading.Event()

	def run() -> None:
		try:
			connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
			all_headers = {"Host": host or f"127.0.0.1:{server.port}"}
			if token:
				all_headers["X-CSVMusic-Token"] = server.token
			all_headers.update(headers or {})
			data = None
			if body is not None:
				data = json.dumps(body).encode("utf-8")
				all_headers["Content-Type"] = "application/json"
			connection.request(method, path, body=data, headers=all_headers)
			response = connection.getresponse()
			result["status"] = response.status
			result["headers"] = dict(response.getheaders())
			result["body"] = response.read()
			connection.close()
		except Exception as exc:
			result["error"] = exc
		finally:
			done.set()

	threading.Thread(target=run, daemon=True).start()
	_wait(app, done)
	if "error" in result:
		raise result["error"]
	return result


def _json(response) -> dict:
	return json.loads(response["body"].decode("utf-8"))


@pytest.fixture
def web(make_engine, tmp_path, qt_application):
	engine = make_engine(5)
	fetched: list[str] = []

	def fake_fetch(url: str) -> bytes:
		fetched.append(url)
		return PNG

	static = tmp_path / "static"
	static.mkdir()
	(static / "index.html").write_text("<!doctype html><html><head><meta name=\"csvmusic-token\" content=\"{{CSVMUSIC_TOKEN}}\"></head><body>oi</body></html>", encoding="utf-8")
	(static / "app.js").write_text("export const ok = 1;", encoding="utf-8")
	server = WebServer(engine, port=0, static_dir=static, image_cache_dir=tmp_path / "images", image_fetcher=fake_fetch)
	server.fetched = fetched
	server.start()
	yield qt_application, server, engine
	server.stop()


def test_index_carries_the_token_and_static_files_are_served(web):
	app, server, _engine = web
	page = _request(app, server, "GET", "/", token=False)
	assert page["status"] == 200
	assert f'content="{server.token}"' in page["body"].decode("utf-8")
	assert page["headers"]["Cache-Control"] == "no-store"
	script = _request(app, server, "GET", "/static/app.js", token=False)
	assert script["status"] == 200 and script["headers"]["Content-Type"].startswith("text/javascript")
	assert _request(app, server, "GET", "/static/../../etc/passwd", token=False)["status"] == 404


def test_api_needs_the_token(web):
	app, server, _engine = web
	refused = _request(app, server, "GET", "/api/state", token=False)
	assert refused["status"] == 403 and _json(refused) == {"error": "Acesso negado."}
	wrong = _request(app, server, "GET", "/api/state", token=False, headers={"X-CSVMusic-Token": "x"})
	assert wrong["status"] == 403
	# O token na URL só vale para /api/events.
	assert _request(app, server, "GET", f"/api/state?token={server.token}", token=False)["status"] == 403


def test_wrong_host_or_origin_is_refused_and_there_is_no_cors(web):
	app, server, _engine = web
	assert _request(app, server, "GET", "/api/state", host="evil.example:80")["status"] == 403
	assert _request(app, server, "GET", "/", token=False, host=f"rebind.example:{server.port}")["status"] == 403
	assert _request(app, server, "GET", "/api/state", headers={"Origin": "https://evil.example"})["status"] == 403
	preflight = _request(app, server, "OPTIONS", "/api/state", token=False, headers={"Origin": "https://evil.example"})
	assert preflight["status"] == 403
	ok = _request(app, server, "GET", "/api/state", host=f"localhost:{server.port}")
	assert ok["status"] == 200
	assert not any(name.lower().startswith("access-control-") for name in ok["headers"])


def test_main_routes(web):
	app, server, engine = web
	state = _json(_request(app, server, "GET", "/api/state"))
	assert state["playlists"][0]["id"] == "spotify:big" and state["job"] == {"kind": None}
	tracks = _json(_request(app, server, "GET", "/api/playlists/spotify:big/tracks?filter=missing&limit=2"))
	assert tracks["total"] == 5 and len(tracks["items"]) == 2
	changed = _request(app, server, "PATCH", "/api/playlists/spotify:big/tracks/1", body={"enabled": False})
	assert _json(changed)["state"] == "disabled"
	assert _json(_request(app, server, "POST", "/api/playlists/spotify:big/tracks/set-enabled", body={"enabled": True, "all": True})) == {"changed": 1}
	settings = _json(_request(app, server, "PATCH", "/api/settings", body={"theme": "light"}))
	assert settings["theme"] == "light"
	bad = _request(app, server, "PATCH", "/api/settings", body={"format": "wav"})
	assert bad["status"] == 400 and _json(bad)["error"] == "Formato de áudio desconhecido."
	job = _json(_request(app, server, "POST", "/api/download", body={"playlist_ids": ["spotify:big"]}))
	assert job["kind"] == "download" and job["total"] == 5
	busy = _request(app, server, "POST", "/api/download", body={"playlist_ids": ["spotify:big"]})
	assert busy["status"] == 409
	assert _json(_request(app, server, "POST", "/api/download/stop"))["stopping"] is True
	assert _request(app, server, "GET", "/api/nada")["status"] == 404
	assert _request(app, server, "PUT", "/api/state")["status"] == 405
	missing = _request(app, server, "GET", "/api/playlists/spotify:nope/tracks")
	assert missing["status"] == 404 and "não está na biblioteca" in _json(missing)["error"]
	csv = _request(app, server, "GET", "/api/export-csv?playlist_id=spotify:big")
	assert csv["status"] == 200 and "Song 0" in csv["body"].decode("utf-8-sig")
	assert "attachment" in csv["headers"]["Content-Disposition"]
	assert _json(_request(app, server, "GET", "/api/trash")) == {"files": 0, "bytes": 0}
	assert _json(_request(app, server, "GET", "/api/log?since=0"))["last_seq"] >= 1


def test_delete_route_uses_the_trash(web):
	app, server, engine = web
	engine.write_song(0)
	removed = _json(_request(app, server, "DELETE", "/api/playlists/spotify:big?files=trash"))
	assert removed["removed"] is True and engine.trashed


def test_events_start_with_the_current_job(web):
	app, server, engine = web
	lines: list[str] = []
	got = threading.Event()

	def listen() -> None:
		sock = socket.create_connection(("127.0.0.1", server.port), timeout=10)
		sock.sendall(f"GET /api/events?token={server.token} HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n\r\n".encode("ascii"))
		data = b""
		while b"event: warning" not in data:
			chunk = sock.recv(4096)
			if not chunk:
				break
			data += chunk
			if b"event: job" in data and b"\n\n" in data.split(b"event: job", 1)[1]:
				got.set()
		lines.extend(data.decode("utf-8").splitlines())
		sock.close()

	thread = threading.Thread(target=listen, daemon=True)
	thread.start()
	_wait(app, got)
	engine.warn("Aviso de teste")
	thread.join(timeout=5)
	assert "event: job" in lines
	assert lines[lines.index("event: job") + 1] == 'data: {"kind": null}'
	assert "event: warning" in lines
	assert any("Aviso de teste" in line for line in lines)


def test_events_need_the_token(web):
	app, server, _engine = web
	assert _request(app, server, "GET", "/api/events", token=False)["status"] == 403


def test_image_proxy_allows_only_the_listed_hosts_and_caches(web):
	app, server, _engine = web
	refused = _request(app, server, "GET", "/api/image?url=https://evil.example/a.png")
	assert refused["status"] == 403 and server.fetched == []
	plain = _request(app, server, "GET", "/api/image?url=http://i.scdn.co/image/1")
	assert plain["status"] == 403
	first = _request(app, server, "GET", "/api/image?url=https://i.scdn.co/image/1")
	second = _request(app, server, "GET", "/api/image?url=https://i.scdn.co/image/1")
	assert first["status"] == second["status"] == 200
	assert first["headers"]["Content-Type"] == "image/png" and first["body"] == PNG
	assert server.fetched == ["https://i.scdn.co/image/1"]


def test_image_host_list():
	for url in (
		"https://i.scdn.co/image/x", "https://mosaic.scdn.co/640/x", "https://image-cdn-ak.spotifycdn.com/image/x",
		"https://i.ytimg.com/vi/x/hq.jpg", "https://lh3.googleusercontent.com/x", "https://is1-ssl.mzstatic.com/x",
		"https://e-cdns-images.dzcdn.net/x", "https://m.media-amazon.com/images/x",
	):
		assert image_url_allowed(url), url
	for url in (
		"http://i.scdn.co/x", "https://i.scdn.co.evil.com/x", "https://evilytimg.com/x", "https://user@i.scdn.co/x",
		"https://i.scdn.co:8443/x", "file:///etc/passwd", "https://ytimg.com.evil/x",
	):
		assert not image_url_allowed(url), url
	assert sniff_image_type(b"\xff\xd8\xff\xe0") == "image/jpeg"
	assert sniff_image_type(b"<html>") is None
