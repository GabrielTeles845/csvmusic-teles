"""Servidor FALSO da interface web, para desenvolver e conferir a tela sem o motor.

Serve csvmusic/web/static/ e responde a API e os eventos de docs/fork/14 §4–5 com dados
inventados aqui mesmo (nomes, capas, números). Nada aqui é dado real. Só biblioteca padrão.

	python tests/web/mock_server.py                 # porta livre, download em andamento
	python tests/web/mock_server.py --porta 8799 --atraso 1500 --job scan
	python tests/web/mock_server.py --vazio --primeira-vez

Opções: --porta N (0 = livre), --atraso MS (espera em toda chamada JSON, para ver o brilho),
--job download|scan|nenhum (o que já está rodando ao abrir), --vazio (biblioteca sem playlist),
--primeira-vez (mostra o aviso inicial), --token T (padrão "mock-token").
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import mimetypes
import pathlib
import queue
import random
import re
import struct
import threading
import time
import urllib.parse
import zlib
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATIC = pathlib.Path(__file__).resolve().parents[2] / "csvmusic" / "web" / "static"
TZ = timezone(timedelta(hours=-3))
LOCK = threading.RLock()

# ---------------------------------------------------------------- dados falsos

PALAVRAS = ("Noite Clara", "Rio de Vidro", "Avenida Norte", "Céu de Chumbo", "Luz de Inverno", "Maré Alta", "Pequeno Farol",
	"Cidade Acesa", "Asfalto Quente", "Último Trem", "Janela Aberta", "Vento Sul", "Linha Reta", "Ponte Velha", "Cais",
	"Fogo Lento", "Ruído Branco", "Sal e Areia", "Dias Contados", "Horizonte", "Papel de Seda", "Ouro Velho",
	"Carta Marcada", "Meia-Noite", "Prédio Azul", "Verão Passado", "Ladeira", "Concreto", "Neblina", "Varanda")
SUFIXOS = ("", "", "", "", " - Ao Vivo", " - Remasterizada 2011", " (Versão Acústica)", " - Edit", " (feat. Duo Exemplo)",
	" - Versão Estendida do Álbum de Aniversário de Vinte Anos")
ARTISTAS = ("Os Faróis", "Lia Moreno", "Banda Exemplo", "Trio Cidade", "Marina Sal", "Coletivo Norte", "Duo Exemplo",
	"João Avenida", "As Marés", "Teo Vidro", "Quarteto Ponte", "Clara Neblina", "Os Ventos", "Rafa Concreto")
ALBUNS = ("Primeiro Disco", "Ao Vivo no Teatro", "Lado B", "Coletânea", "Estúdio 3", "Cartas", "Mapa", "Inverno",
	"Sessões de Garagem", "Sinal Aberto", "Volume Dois")

FILTRO_ESTADOS = {
	"missing": {"missing", "queued", "matching", "downloading", "tagging", "redownload"},
	"review": {"review"},
	"error": {"error", "age_limit"},
	"downloaded": {"downloaded"},
	"disabled": {"disabled"},
	"not_found": {"not_found"},
}

DETALHES = {
	"review": ["Arquivo 7 s mais longo que a música", "O título do vídeo não fala em “{t}”", "Achou só o clipe, não a música"],
	"error": ["O YouTube recusou o download (muitos pedidos seguidos)", "O vídeo não está mais disponível"],
	"age_limit": ["Restrição de idade no YouTube"],
	"not_found": ["Nenhuma versão parecida no YouTube Music"],
	"redownload": ["Vai trocar pela versão escolhida"],
}

ERRO_LONGO = ("ERROR: [youtube] {v}: Sign in to confirm you’re not a bot. This helps protect our community.\n"
	"Use --cookies-from-browser or --cookies for the authentication.\n"
	"(texto técnico de exemplo, gerado pelo servidor falso)")


def erro_obj(vid: str, kind=None) -> dict:
	if kind == "age_restricted":
		return {"summary": "O YouTube pede login para esta música (restrição de idade).",
			"advice": "Entre na sua conta do YouTube em Ajustes › Conta do YouTube e baixe de novo.",
			"technical": ERRO_LONGO.replace("{v}", vid), "at": "2026-10-22T14:10:00+00:00", "kind": "age_restricted"}
	return {"summary": "O YouTube recusou o download (muitos pedidos seguidos).",
		"advice": "Espere alguns minutos e tente de novo. Se continuar, escolha outra versão.",
		"technical": ERRO_LONGO.replace("{v}", vid), "at": "2026-10-22T14:10:00+00:00", "kind": None}


def capa(seed: int) -> str:
	return f"https://i.scdn.co/image/mock-{seed}"


def video_id(rng: random.Random) -> str:
	return "".join(rng.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") for _ in range(11))


def nova_musica(rng: random.Random, index: int, estado: str, pasta: str) -> dict:
	titulo = rng.choice(PALAVRAS) + rng.choice(SUFIXOS)
	artistas = rng.choice(ARTISTAS)
	if rng.random() < .15:
		artistas += ", " + rng.choice(ARTISTAS)
	album_n = rng.randrange(len(ALBUNS))
	album = ALBUNS[album_n]
	t = {
		"index": index, "key": f"mock:{rng.randrange(10 ** 12)}|occurrence:1", "position": index + 1, "title": titulo, "artists": artistas, "album": album,
		"duration_ms": rng.randrange(140, 330) * 1000 + rng.randrange(0, 999),
		"cover_url": capa((zlib.crc32(artistas.encode()) + album_n) % 97), "enabled": estado != "disabled",
		"state": estado, "detail": None, "downloaded_video": None, "preferred_video": None,
		"volume_gain": 0, "quality": None, "file_path": None, "error": None,
		"_base": estado if estado != "disabled" else "missing",
	}
	if estado in DETALHES:
		t["detail"] = rng.choice(DETALHES[estado]).replace("{t}", titulo.split(" - ")[0])
	if estado in ("downloaded", "review"):
		vid = video_id(rng)
		t["downloaded_video"] = {"id": vid, "title": titulo, "publisher": artistas.split(",")[0]}
		baixa = rng.random() < .04
		t["quality"] = {"label": "AAC ~48 kbps" if baixa else "AAC ~128 kbps", "low": baixa}
		t["file_path"] = f"{pasta}/{index + 1:03d} {titulo}.m4a"
	if estado == "error":
		t["error"] = erro_obj(video_id(rng))
	if estado == "age_limit":
		t["error"] = erro_obj(video_id(rng), "age_restricted")
	if rng.random() < .01:
		vid = video_id(rng)
		t["preferred_video"] = {"id": vid, "label": f"{titulo} — {artistas.split(',')[0]}"}
	if rng.random() < .02:
		t["volume_gain"] = rng.choice([-3, 2, 4])
	return t


def gerar_lista(rng: random.Random, total: int, pesos: dict, pasta: str) -> list:
	estados = list(pesos)
	ws = [pesos[e] for e in estados]
	return [nova_musica(rng, i, rng.choices(estados, ws)[0], pasta) for i in range(total)]


class Biblioteca:
	def __init__(self, vazio: bool, primeira_vez: bool):
		self.rng = random.Random(42)
		self.first_run = primeira_vez
		self.playlists: dict = {}
		self.ordem: list = []
		self.job = {"kind": None}
		self.log: list = []
		self.seq = 0
		self.account = {"connected": False, "use_cookies": False, "checked_at": None}
		self.trash = {"files": 14, "bytes": 52_400_000}
		self.settings = {
			"output_dir": "/Users/exemplo/Músicas/CSVMusic", "format": "m4a", "mp3_quality": 2, "legacy_ipod_mode": False,
			"legacy_mp3_mode": "vbr", "embed_art": True, "force_download_mode": False, "prefix_track_numbers": True,
			"write_m3u8": True, "write_m3u_plain": False, "device_sync_auto_eject": False, "m3u_output_dir": None, "yt_dlp_path": None, "ffmpeg_path": None, "use_cookies": False,
			"cookies_browser": "firefox", "cookies_file": None, "eq_enabled": False, "eq_normalize": False,
			"eq_volume_gain": 0, "eq_bass_gain": 0, "eq_treble_gain": 0, "theme": "system", "web_port": 8765,
		}
		self.parar = False
		if vazio:
			return
		base = "/Users/exemplo/Músicas/CSVMusic"
		self.adicionar_playlist("spotify:mock-ootm", "spotify", "Out Of Time Man", gerar_lista(self.rng, 1124, {
			"downloaded": 900, "missing": 198, "review": 9, "error": 4, "age_limit": 1, "not_found": 3, "disabled": 9,
		}, f"{base}/Out Of Time Man"), reported_total=1150, scan_state="incomplete")
		self.adicionar_playlist("csv:mock-curtidas", "csv", "Músicas curtidas (planilha)", gerar_lista(self.rng, 5000, {
			"downloaded": 4700, "missing": 240, "review": 30, "error": 12, "not_found": 8, "disabled": 10,
		}, f"{base}/Músicas curtidas"), source_type="csv")
		self.adicionar_playlist("spotify:mock-treino", "spotify", "Treino", [], scan_state="ok",
			access_error="private", access_error_message=None)
		self.adicionar_playlist("ytmusic:mock-pai", "ytmusic", "Discos do meu pai", [], scan_state="never")

	def adicionar_playlist(self, pid, plataforma, nome, musicas, reported_total=None, scan_state="ok",
			source_type="playlist", access_error=None, access_error_message=None):
		self.playlists[pid] = {
			"id": pid, "platform": plataforma, "source_type": source_type, "name": nome,
			"url": f"https://exemplo.invalid/{pid}", "tracks": musicas,
			"reported_total": reported_total if reported_total is not None else (len(musicas) or None),
			"last_scanned_at": None if scan_state == "never" else "2026-10-22T13:00:00+00:00",
			"scan_state": scan_state, "scan_warning": None, "access_error": access_error,
			"access_error_message": access_error_message, "folder": f"/Users/exemplo/Músicas/CSVMusic/{nome}",
		}
		self.ordem.append(pid)

	def contagens(self, pl) -> dict:
		"""downloaded + missing + disabled = total; o resto são marcas dentro das ativas (doc 14 §4)."""
		c = {k: 0 for k in ("total", "downloaded", "missing", "review", "error", "age_limit", "not_found", "disabled", "queued")}
		for t in pl["tracks"]:
			c["total"] += 1
			s = t["state"]
			if not t["enabled"]:
				c["disabled"] += 1
				continue
			c["downloaded" if t["file_path"] else "missing"] += 1
			if s == "review":
				c["review"] += 1
			if s in ("error", "age_limit"):
				c["error"] += 1
			if s == "age_limit":
				c["age_limit"] += 1
			if s == "not_found":
				c["not_found"] += 1
			if s in ("queued", "redownload"):
				c["queued"] += 1
		return c

	def resumo(self, pid) -> dict:
		pl = self.playlists[pid]
		out = {k: v for k, v in pl.items() if k != "tracks"}
		capas = []
		for t in pl["tracks"]:
			if t["cover_url"] and t["cover_url"] not in capas:
				capas.append(t["cover_url"])
			if len(capas) == 4:
				break
		out["cover_urls"] = capas
		out["counts"] = self.contagens(pl)
		return out

	def publica(self, t) -> dict:
		return {k: v for k, v in t.items() if not k.startswith("_")}

	def estado(self) -> dict:
		return {
			"version": "1.7.9+teles.0 (servidor falso)",
			"library": {"path": "/Users/exemplo/Library/Application Support/CSVMusicTeles/library.json",
				"output_dir": self.settings["output_dir"], "format": self.settings["format"],
				"load_error": "O arquivo da biblioteca está estragado e foi guardado como cópia." if ARGS.erro_biblioteca else None},
			"playlists": [self.resumo(p) for p in self.ordem], "job": self.job, "account": self.account,
			"first_run": self.first_run,
		}

	def registrar(self, mensagem, nivel="info"):
		self.seq += 1
		e = {"seq": self.seq, "ts": datetime.now(TZ).isoformat(), "level": nivel, "message": mensagem}
		self.log.append(e)
		del self.log[:-2000]
		emitir("log", e)


BIB: Biblioteca
CLIENTES: list = []
ARGS = None


def emitir(tipo: str, dado) -> None:
	for q in list(CLIENTES):
		q.put((tipo, dado))


# ---------------------------------------------------------------- tarefas simuladas

def rodar_download(alvos: list, single: bool = False) -> None:
	"""alvos: [(playlist_id, index)]. Uma música a cada ~4 s, eventos job/track/log."""
	b = BIB
	feitas = puladas = falhas = idade = 0
	inicio = time.time()
	with LOCK:
		for pid, i in alvos:
			t = b.playlists[pid]["tracks"][i]
			t["state"] = "queued"
			emitir("track", {"playlist_id": pid, "track": b.publica(t)})
		for pid in {p for p, _ in alvos}:
			emitir("playlist", b.resumo(pid))
		b.registrar(f"Começando o download de {len(alvos)} músicas.")
	for n, (pid, i) in enumerate(alvos):
		if b.parar:
			break
		pl = b.playlists.get(pid)
		if not pl:
			continue
		t = pl["tracks"][i]

		def job(fase, pct=None):
			restante = len(alvos) - n
			eta = (datetime.now(TZ) + timedelta(seconds=restante * 4)).isoformat(timespec="seconds") if n else None
			b.job = {"kind": "download", "playlist_ids": sorted({p for p, _ in alvos}), "processed": n, "total": len(alvos),
				"eta_at": eta, "current": {"playlist_id": pid, "index": i, "title": t["title"], "artists": t["artists"],
					"cover_url": t["cover_url"], "phase": fase, "percent": None}, "stopping": b.parar, "single": single}
			emitir("job", b.job)

		with LOCK:
			t["state"] = "matching"
			emitir("track", {"playlist_id": pid, "track": b.publica(t)})
			b.registrar(f"Procurando “{t['title']}” de {t['artists']} no YouTube Music.")
			job("matching")
		time.sleep(.7)
		with LOCK:
			t["state"] = "downloading"
			emitir("track", {"playlist_id": pid, "track": b.publica(t)})
		for pct in range(0, 101, 9):
			if b.parar and pct > 50:
				break
			with LOCK:
				job("downloading", pct)
			time.sleep(.25)
		with LOCK:
			t["state"] = "tagging"
			emitir("track", {"playlist_id": pid, "track": b.publica(t)})
			job("tagging")
		time.sleep(.4)
		with LOCK:
			sorte = (i * 7919) % 23
			if sorte == 0:
				t["state"], t["detail"], t["error"] = "age_limit", "Restrição de idade no YouTube", erro_obj("exemplo0002", "age_restricted")
				idade += 1
				b.registrar(f"“{t['title']}” tem restrição de idade.", "warning")
			elif sorte == 1:
				t["state"], t["detail"], t["error"] = "error", "O YouTube recusou o download", erro_obj("exemplo0001")
				falhas += 1
				b.registrar(f"Erro ao baixar “{t['title']}”.", "error")
			else:
				t["state"], t["detail"] = "downloaded", None
				vid = video_id(b.rng)
				t["downloaded_video"] = {"id": vid, "title": t["title"], "publisher": t["artists"].split(",")[0]}
				t["quality"] = {"label": "AAC ~128 kbps", "low": False}
				t["file_path"] = f"{pl['folder']}/{i + 1:03d} {t['title']}.m4a"
				feitas += 1
				b.registrar(f"Baixada: “{t['title']}”.")
			emitir("track", {"playlist_id": pid, "track": b.publica(t)})
			emitir("playlist", b.resumo(pid))
	with LOCK:
		parou = b.parar
		for pid, i in alvos:
			t = b.playlists.get(pid, {"tracks": []})["tracks"][i] if pid in b.playlists else None
			if t and t["state"] == "queued":
				t["state"] = "missing"
				emitir("track", {"playlist_id": pid, "track": b.publica(t)})
		for pid in {p for p, _ in alvos}:
			if pid in b.playlists:
				emitir("playlist", b.resumo(pid))
		b.job = {"kind": None}
		b.parar = False
		emitir("job", b.job)
		b.ultimas_idade = [(p, i) for p, i in alvos if p in b.playlists and b.playlists[p]["tracks"][i]["state"] == "age_limit"]
		emitir("download_done", {"done": feitas, "skipped": puladas, "failed": falhas, "age_restricted": idade,
			"age_action": ("enable_session" if b.account["connected"] else "sign_in") if idade else None,
			"stopped": parou, "message": None})
		b.registrar(f"Fim do download em {int(time.time() - inicio)} s.")


def rodar_analise(ids: list) -> None:
	b = BIB
	resultados = []
	for k, pid in enumerate(ids):
		if b.parar:
			break
		pl = b.playlists.get(pid)
		if not pl:
			continue
		alvo = pl["reported_total"] or (48 if pl["scan_state"] == "never" else len(pl["tracks"]) or 37)
		for cap in range(0, alvo + 1, max(1, alvo // 24)):
			if b.parar:
				break
			with LOCK:
				b.job = {"kind": "scan", "playlist_id": pid, "name": pl["name"], "captured": cap, "reported_total": alvo,
					"queue_left": len(ids) - k - 1, "cancelling": False}
				emitir("job", b.job)
			time.sleep(.35)
		with LOCK:
			if pl["access_error"] == "private":
				resultados.append({"playlist_id": pid, "name": pl["name"], "captured": 0, "reported_total": None,
					"status": "private", "message": "Torne a playlist pública no Spotify."})
			else:
				if pl["scan_state"] == "never" or not pl["tracks"]:
					pl["tracks"] = gerar_lista(b.rng, alvo, {"missing": 40, "review": 3, "not_found": 1}, pl["folder"])
					pl["reported_total"] = alvo
				else:
					# Como no motor: a análise trouxe uma música nova no topo e todas as outras mudaram de índice.
					pl["tracks"].insert(0, nova_musica(b.rng, 0, "missing", pl["folder"]))
					for novo_indice, musica in enumerate(pl["tracks"]):
						musica["index"], musica["position"] = novo_indice, novo_indice + 1
				pl["scan_state"] = "ok"
				pl["last_scanned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
				status = "incomplete" if pl["reported_total"] and len(pl["tracks"]) < pl["reported_total"] else "ok"
				pl["scan_state"] = status
				resultados.append({"playlist_id": pid, "name": pl["name"], "captured": len(pl["tracks"]),
					"reported_total": pl["reported_total"], "status": status, "message": None,
					"diff": {"added": 2, "removed": 1, "unchanged": max(0, len(pl["tracks"]) - 2), "kept": 0}})
				emitir("tracks_changed", {"playlist_id": pid})
			emitir("playlist", b.resumo(pid))
	with LOCK:
		cancelada = b.parar
		b.job = {"kind": None}
		b.parar = False
		emitir("job", b.job)
		if not cancelada:
			emitir("scan_done", {"results": resultados})


def iniciar(alvo, *args) -> None:
	threading.Thread(target=alvo, args=args, daemon=True).start()


def depois(segundos, fn) -> None:
	threading.Timer(segundos, fn).start()


# ---------------------------------------------------------------- capas (PNG gerado aqui)

def png(seed: int, tamanho: int = 96) -> bytes:
	rng = random.Random(seed)
	def cor():
		h = rng.random()
		import colorsys
		r, g, b = colorsys.hls_to_rgb(h, rng.uniform(.3, .6), rng.uniform(.35, .8))
		return int(r * 255), int(g * 255), int(b * 255)
	a, b2, c = cor(), cor(), cor()
	tipo = seed % 3
	cx, cy, raio = rng.uniform(.2, .8) * tamanho, rng.uniform(.2, .8) * tamanho, rng.uniform(.18, .4) * tamanho
	linhas = []
	for y in range(tamanho):
		linha = bytearray([0])
		for x in range(tamanho):
			if tipo == 0:
				p = a if x + y < tamanho else b2
			elif tipo == 1:
				p = a if (y // (tamanho // 4)) % 2 else b2
			else:
				p = a
			if (x - cx) ** 2 + (y - cy) ** 2 < raio ** 2:
				p = c
			linha += bytes(p)
		linhas.append(bytes(linha))
	bruto = zlib.compress(b"".join(linhas), 6)
	def bloco(tag, dado):
		return struct.pack(">I", len(dado)) + tag + dado + struct.pack(">I", zlib.crc32(tag + dado) & 0xFFFFFFFF)
	return b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", tamanho, tamanho, 8, 2, 0, 0, 0)) + bloco(b"IDAT", bruto) + bloco(b"IEND", b"")


CAPAS: dict = {}

# ---------------------------------------------------------------- HTTP


class Erro(Exception):
	def __init__(self, status, mensagem, extra=None):
		super().__init__(mensagem)
		self.status = status
		self.mensagem = mensagem
		self.extra = extra or {}


class Handler(BaseHTTPRequestHandler):
	protocol_version = "HTTP/1.1"

	def log_message(self, *a):
		pass

	# ------------ saída
	def json(self, dado, status=200):
		corpo = json.dumps(dado, ensure_ascii=False).encode()
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(corpo)))
		self.send_header("Cache-Control", "no-store")
		self.end_headers()
		self.wfile.write(corpo)

	def bytes_(self, corpo: bytes, tipo: str, extra=None):
		self.send_response(200)
		self.send_header("Content-Type", tipo)
		self.send_header("Content-Length", str(len(corpo)))
		for k, v in (extra or {}).items():
			self.send_header(k, v)
		self.end_headers()
		self.wfile.write(corpo)

	# ------------ entrada
	def corpo(self) -> dict:
		# Lido uma vez por pedido (a conexão é reaproveitada: rotear() limpa a cópia).
		if self._corpo is not None:
			return self._corpo
		n = int(self.headers.get("Content-Length") or 0)
		if not n:
			self._corpo = {}
			return self._corpo
		try:
			self._corpo = json.loads(self.rfile.read(n) or b"{}")
		except json.JSONDecodeError:
			raise Erro(400, "Pedido mal formado.")
		return self._corpo

	def do_GET(self):
		self.rotear("GET")

	def do_POST(self):
		self.rotear("POST")

	def do_PATCH(self):
		self.rotear("PATCH")

	def do_DELETE(self):
		self.rotear("DELETE")

	def rotear(self, metodo):
		self._corpo = None
		url = urllib.parse.urlsplit(self.path)
		caminho = urllib.parse.unquote(url.path)
		q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
		try:
			if metodo != "GET":
				# Lê o corpo sempre: rota que não usa o corpo deixaria os bytes na conexão reaproveitada.
				self.corpo()
			if metodo == "GET" and caminho in ("/", "/index.html"):
				html = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{CSVMUSIC_TOKEN}}", ARGS.token)
				self.bytes_(html.encode(), "text/html; charset=utf-8", {"Cache-Control": "no-store",
					"Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})
				return
			if metodo == "GET" and caminho.startswith("/static/"):
				self.estatico(caminho[len("/static/"):])
				return
			if not caminho.startswith("/api/"):
				raise Erro(404, "Página não encontrada.")
			token = self.headers.get("X-CSVMusic-Token") or (q.get("token") if caminho == "/api/events" else None)
			if token != ARGS.token:
				raise Erro(403, "Sem permissão.")
			if caminho == "/api/events":
				self.eventos()
				return
			if caminho == "/api/image":
				self.imagem(q.get("url", ""))
				return
			if ARGS.atraso:
				time.sleep(ARGS.atraso / 1000)
			self.api(metodo, caminho[len("/api"):], q)
		except Erro as e:
			self.json({"error": e.mensagem, **e.extra}, e.status)
		except (BrokenPipeError, ConnectionResetError):
			pass

	def estatico(self, rel):
		alvo = (STATIC / rel).resolve()
		if STATIC not in alvo.parents or not alvo.is_file():
			raise Erro(404, "Arquivo não encontrado.")
		tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
		if alvo.suffix == ".js":
			tipo = "text/javascript; charset=utf-8"
		if alvo.suffix == ".woff2":
			tipo = "font/woff2"
		self.bytes_(alvo.read_bytes(), tipo, {"Cache-Control": "no-cache"})

	def imagem(self, url):
		m = re.search(r"mock-(\d+)", url)
		if not m:
			raise Erro(404, "Imagem não encontrada.")
		seed = int(m.group(1))
		if seed not in CAPAS:
			CAPAS[seed] = png(seed)
		self.bytes_(CAPAS[seed], "image/png", {"Cache-Control": "max-age=3600"})

	def eventos(self):
		self.send_response(200)
		self.send_header("Content-Type", "text/event-stream; charset=utf-8")
		self.send_header("Cache-Control", "no-store")
		self.send_header("Connection", "keep-alive")
		self.end_headers()
		fila: queue.Queue = queue.Queue()
		with LOCK:
			fila.put(("job", BIB.job))
			CLIENTES.append(fila)
		try:
			while True:
				try:
					tipo, dado = fila.get(timeout=15)
					msg = f"event: {tipo}\ndata: {json.dumps(dado, ensure_ascii=False)}\n\n"
				except queue.Empty:
					msg = ": ainda aqui\n\n"
				self.wfile.write(msg.encode())
				self.wfile.flush()
		except (BrokenPipeError, ConnectionResetError, OSError):
			pass
		finally:
			with LOCK:
				if fila in CLIENTES:
					CLIENTES.remove(fila)

	# ------------ API
	def api(self, metodo, caminho, q):
		b = BIB
		with LOCK:
			r = self.api_dentro(metodo, caminho, q, b)
		if isinstance(r, tuple):
			self.bytes_(*r)
		else:
			self.json(r)

	def playlist(self, pid):
		pl = BIB.playlists.get(pid)
		if not pl:
			raise Erro(404, "Essa playlist não está mais na biblioteca.")
		return pl

	def musica(self, pid, idx):
		pl = self.playlist(pid)
		try:
			return pl, pl["tracks"][int(idx)]
		except (IndexError, ValueError):
			raise Erro(404, "Essa música não está na playlist.")

	def api_dentro(self, metodo, caminho, q, b):
		partes = [urllib.parse.unquote(p) for p in caminho.strip("/").split("/")]
		if metodo == "GET" and caminho == "/state":
			return b.estado()
		if caminho == "/first-run/accept":
			b.first_run = False
			return {"ok": True}
		if partes[0] == "playlists":
			return self.api_playlists(metodo, partes, q, b)
		if caminho == "/scan" and metodo == "POST":
			c = self.corpo()
			if c.get("scope") == "all":
				ids = list(b.ordem)
			elif c.get("scope") == "unscanned":
				ids = [p for p in b.ordem if b.playlists[p]["scan_state"] == "never"]
			else:
				ids = [p for p in c.get("playlist_ids", []) if p in b.playlists]
			if b.job["kind"] == "download":
				raise Erro(409, "Espere o download terminar para analisar.")
			if b.job["kind"] == "scan":
				raise Erro(409, "Já há uma análise rodando.")
			if not ids:
				raise Erro(400, "Nenhuma playlist para analisar.")
			b.job = {"kind": "scan", "playlist_id": ids[0], "name": b.playlists[ids[0]]["name"], "captured": 0,
				"reported_total": b.playlists[ids[0]]["reported_total"], "queue_left": len(ids) - 1, "cancelling": False}
			iniciar(rodar_analise, ids)
			return b.job
		if caminho == "/scan/cancel":
			if b.job["kind"] == "scan":
				b.parar = True
				b.job = {**b.job, "cancelling": True}
				emitir("job", b.job)
			return b.job
		if caminho == "/download" and metodo == "POST":
			if b.job["kind"]:
				raise Erro(409, "Já há uma tarefa rodando. Espere ela terminar ou pare.")
			c = self.corpo()
			if "targets" in c:
				alvos = []
				for p, i, *k in c["targets"]:
					if p not in b.playlists:
						continue
					if k and k[0] and b.playlists[p]["tracks"][int(i)]["key"] != k[0]:
						raise Erro(409, "A playlist mudou; abra a música de novo.", {"code": "track_moved"})
					alvos.append((p, int(i)))
			else:
				alvos = [(p, t["index"]) for p in c.get("playlist_ids", []) if p in b.playlists
					for t in b.playlists[p]["tracks"] if t["enabled"] and (not t["file_path"] or t["state"] == "redownload")]
			if not alvos:
				raise Erro(400, "Não há nada faltando para baixar.")
			if len(alvos) >= 250 and not c.get("confirm_risk"):
				raise Erro(409, f"São {len(alvos)} músicas de uma vez. Lotes grandes fazem o YouTube segurar os pedidos por um tempo; "
					"o CSVMusic vai mais devagar para evitar isso.",
					{"needs_confirmation": "youtube_risk", "tracks": len(alvos)})
			b.job = {"kind": "download", "playlist_ids": sorted({p for p, _ in alvos}), "processed": 0, "total": len(alvos),
				"eta_at": None, "current": None, "stopping": False, "single": False}
			iniciar(rodar_download, alvos)
			return b.job
		if caminho == "/download/stop":
			if b.job["kind"] == "download":
				b.parar = True
				b.job = {**b.job, "stopping": True}
				emitir("job", b.job)
			return b.job
		if caminho == "/video-info":
			return self.video_info(q, b)
		if caminho == "/settings":
			if metodo == "PATCH":
				c = self.corpo()
				for k, v in c.items():
					if k not in b.settings:
						raise Erro(400, "Ajuste desconhecido.")
					if re.fullmatch(r"eq_(volume|bass|treble)_gain", k) and not -12 <= int(v) <= 12:
						raise Erro(400, "O equalizador vai de -12 a +12 dB.")
					if k == "mp3_quality" and not 0 <= int(v) <= 10:
						raise Erro(400, "A qualidade do MP3 vai de 0 a 10.")
					b.settings[k] = v
			return b.settings
		if caminho == "/dialogs/choose-folder":
			return {"path": "/Users/exemplo/Músicas/Escolhida"}
		if caminho == "/dialogs/choose-file":
			c = self.corpo()
			nomes = {"cookies": "/Users/exemplo/youtube-cookies.txt", "ytdlp": "/opt/homebrew/bin/yt-dlp",
				"ffmpeg": "/opt/homebrew/bin/ffmpeg", "library": "/Users/exemplo/Documentos/biblioteca-copia.json",
				"csv": "/Users/exemplo/Documentos/planilha.csv"}
			return {"path": nomes.get(c.get("purpose"))}
		if caminho == "/library/open":
			emitir("library", {"path": self.corpo().get("path")})
			return b.estado()
		if caminho == "/library/save-as":
			# Como no motor: é só uma cópia; arquivo que já existe só com overwrite (a tela pergunta).
			c = self.corpo()
			salvas = b.__dict__.setdefault("copias", set())
			if c.get("path") in salvas and not c.get("overwrite"):
				raise Erro(409, f"Já existe um arquivo chamado {c['path'].rsplit('/', 1)[-1]} nesta pasta. Quer substituir?",
					{"needs_confirmation": "overwrite", "path": c.get("path")})
			salvas.add(c.get("path"))
			return {"path": c.get("path")}
		if caminho == "/open":
			return {"ok": True}
		if caminho == "/export-csv":
			return self.exportar(q, b)
		if caminho == "/account/youtube/sign-in":
			def pronto():
				with LOCK:
					b.account = {"connected": True, "use_cookies": True, "checked_at": datetime.now(timezone.utc).isoformat()}
					emitir("account", {"connected": True, "use_cookies": True, "ok": True, "message": "Entrou na conta do YouTube."})
			depois(2, pronto)
			return {"started": True}
		if caminho == "/account/youtube/test":
			depois(1.5, lambda: emitir("account", {**b.account, "ok": b.account["connected"],
				"message": "A sessão funciona." if b.account["connected"] else "Sem sessão do YouTube para testar."}))
			return {"started": True}
		if caminho == "/account/youtube/sign-out":
			b.account = {"connected": False, "use_cookies": False, "checked_at": None}
			return {**b.account, "ok": True, "message": "O CSVMusic não usa mais a sua sessão do YouTube."}
		if caminho == "/age-restricted/resolve":
			metodo_ = "enable_session" if b.account["connected"] else "sign_in"
			depois(2, lambda: emitir("age_retry_ready", {"targets": len(getattr(b, "ultimas_idade", [])) or 1}))
			return {"started": True, "method": metodo_}
		if caminho == "/age-restricted/retry":
			if b.job["kind"]:
				raise Erro(409, "Já há uma tarefa rodando. Espere ela terminar ou pare.")
			alvos = getattr(b, "ultimas_idade", [])
			if not alvos:
				raise Erro(409, "Não há músicas com restrição de idade do último download.")
			b.job = {"kind": "download", "playlist_ids": sorted({p for p, _ in alvos}), "processed": 0, "total": len(alvos),
				"eta_at": None, "current": None, "stopping": False, "single": False}
			iniciar(rodar_download, alvos)
			return b.job
		if caminho == "/log":
			since = int(q.get("since") or 0)
			return {"entries": [e for e in b.log if e["seq"] > since], "last_seq": b.seq}
		if partes[0] == "devices":
			return self.api_aparelhos(metodo, partes, b)
		if caminho == "/trash":
			return b.trash
		if caminho == "/trash/empty":
			movidos = b.trash["files"]
			b.trash = {"files": 0, "bytes": 0}
			return {"moved": movidos}
		raise Erro(404, "Rota não encontrada.")

	def api_playlists(self, metodo, partes, q, b):
		if len(partes) == 1 and metodo == "POST":
			urls = self.corpo().get("urls", [])
			novas, erros, avisos = [], [], []
			for u in urls:
				if "youtube.com/playlist" in u and "music." not in u:
					avisos.append("Playlist comum do YouTube: títulos de vídeo nem sempre dizem o artista e o álbum certos. O YouTube Music acerta mais.")
				if not re.search(r"spotify\.com|music\.apple\.com|deezer\.com|youtube\.com|amazon\.", u):
					erros.append({"url": u, "error": "Esse link não parece de uma playlist que o CSVMusic lê."})
					continue
				pid = f"mock:{len(b.playlists) + 1}"
				nome = "Playlist nova " + str(len(b.playlists) + 1)
				b.adicionar_playlist(pid, "spotify" if "spotify" in u else "ytmusic", nome, [], scan_state="never")
				novas.append(pid)
			if novas:
				emitir("playlists", {"ids": novas})
				if not b.job["kind"]:
					b.job = {"kind": "scan", "playlist_id": novas[0], "name": b.playlists[novas[0]]["name"], "captured": 0,
						"reported_total": None, "queue_left": len(novas) - 1, "cancelling": False}
					iniciar(rodar_analise, novas)
			return {"added": novas, "errors": erros, "warnings": avisos}
		if len(partes) == 2 and partes[1] == "import-csv":
			c = self.corpo()
			texto = base64.b64decode(c.get("content_base64") or "").decode("utf-8", "replace")
			linhas = [l for l in csv.reader(io.StringIO(texto))][1:]
			if not linhas:
				raise Erro(400, "A planilha está vazia ou não tem as colunas de música.")
			pid = f"csv:{len(b.playlists) + 1}"
			nome = c.get("name") or re.sub(r"\.csv$", "", c.get("filename") or "Planilha")
			b.adicionar_playlist(pid, "csv", nome, gerar_lista(b.rng, len(linhas), {"missing": 1}, f"/Users/exemplo/Músicas/CSVMusic/{nome}"), source_type="csv")
			emitir("playlists", {"ids": [pid]})
			return {"added": [pid], "warnings": []}
		pid = partes[1]
		pl = self.playlist(pid)
		if len(partes) == 2:
			if metodo == "PATCH":
				nome = (self.corpo().get("name") or "").strip()
				if not nome:
					raise Erro(400, "O nome não pode ficar em branco.")
				pl["name"] = nome
				r = b.resumo(pid)
				emitir("playlist", r)
				return r
			if metodo == "DELETE":
				lixo = q.get("files") == "trash"
				b.ordem.remove(pid)
				del b.playlists[pid]
				emitir("playlists", {"ids": [pid]})
				return {"removed": True, "trashed_folder": pl["folder"] if lixo else None}
		if partes[2] != "tracks":
			raise Erro(404, "Rota não encontrada.")
		if len(partes) == 3 and metodo == "GET":
			filtro = q.get("filter") or "all"
			busca = (q.get("q") or "").casefold()
			itens = pl["tracks"]
			if filtro == "missing":
				itens = [t for t in itens if t["enabled"] and not t["file_path"]]
			elif filtro == "downloaded":
				itens = [t for t in itens if t["enabled"] and t["file_path"]]
			elif filtro != "all":
				aceitos = FILTRO_ESTADOS.get(filtro)
				if aceitos is None:
					raise Erro(400, "Filtro desconhecido.")
				itens = [t for t in itens if t["state"] in aceitos]
			if busca:
				itens = [t for t in itens if busca in f"{t['title']} {t['artists']} {t['album']}".casefold()]
			off, lim = int(q.get("offset") or 0), min(500, int(q.get("limit") or 100))
			return {"total": len(itens), "counts": b.contagens(pl), "items": [b.publica(t) for t in itens[off:off + lim]]}
		if len(partes) == 4 and partes[3] == "set-enabled":
			c = self.corpo()
			alvo = pl["tracks"] if c.get("all") else [pl["tracks"][i] for i in c.get("indices", [])]
			mudou = 0
			for t in alvo:
				if self.ligar(t, bool(c.get("enabled"))):
					mudou += 1
			emitir("playlist", b.resumo(pid))
			return {"changed": mudou}
		pl, t = self.musica(pid, partes[3])
		chave = q.get("key") if metodo == "GET" else self.corpo().get("key")
		if chave and chave != t["key"]:
			raise Erro(409, "A playlist mudou; abra a música de novo.", {"code": "track_moved"})
		if len(partes) == 4 and metodo == "PATCH":
			c = self.corpo()
			if "enabled" in c:
				self.ligar(t, bool(c["enabled"]))
			for k in ("title", "artists", "album"):
				if k in c:
					t[k] = c[k]
			if "volume_gain" in c:
				t["volume_gain"] = max(-12, min(12, int(c["volume_gain"])))
			if "preferred_video_url" in c:
				u = c["preferred_video_url"]
				if u:
					m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", u)
					if not m:
						raise Erro(400, "Esse link não é de um vídeo do YouTube.")
					t["preferred_video"] = {"id": m.group(1), "label": c.get("preferred_video_label") or f"Versão escolhida ({m.group(1)})"}
					if t["enabled"]:
						t["state"] = t["_base"] = "redownload"
				else:
					t["preferred_video"] = None
			if c.get("force_redownload"):
				t["state"] = t["_base"] = "redownload"
				t["detail"] = "Vai baixar de novo no próximo download"
			emitir("track", {"playlist_id": pid, "track": b.publica(t)})
			emitir("playlist", b.resumo(pid))
			return b.publica(t)
		if len(partes) == 5 and partes[4] == "accept":
			if t["state"] != "review":
				raise Erro(409, "Essa música não está para revisar.")
			t["state"] = t["_base"] = "downloaded"
			t["detail"] = None
			emitir("track", {"playlist_id": pid, "track": b.publica(t)})
			emitir("playlist", b.resumo(pid))
			return b.publica(t)
		if len(partes) == 5 and partes[4] == "alternatives":
			rng = random.Random(t["index"])
			base = t["duration_ms"] // 1000
			opcoes = []
			for k in range(5):
				dur = base + rng.choice([0, 0, 2, -1, 14, 31])
				marcas = rng.choice([[], [], ["Ao vivo"], ["Remix"], ["Acústica"]])
				opcoes.append({"videoId": video_id(rng), "title": t["title"] + (" (Clipe Oficial)" if k == 3 else ""),
					"author": t["artists"].split(",")[0], "source": "videos" if k >= 3 else "music", "duration_seconds": dur,
					"album": t["album"] if k < 3 else None, "duration_mismatch": abs(dur - base) > 10, "version_markers": marcas,
					"score": round(.95 - k * .1, 2)})
			return {"options": opcoes}
		if len(partes) == 5 and partes[4] == "download-now":
			if b.job["kind"]:
				raise Erro(409, "Já há uma tarefa rodando. Espere ela terminar ou pare.")
			vid = self.corpo().get("video_id") or ""
			t["preferred_video"] = {"id": vid, "label": f"Versão escolhida ({vid})"}
			b.job = {"kind": "download", "playlist_ids": [pid], "processed": 0, "total": 1, "eta_at": None, "current": None,
				"stopping": False, "single": True}
			iniciar(rodar_download, [(pid, t["index"])], True)
			return b.job
		raise Erro(404, "Rota não encontrada.")

	def ligar(self, t, ligado):
		if ligado and t["state"] == "disabled":
			t["state"], t["enabled"] = t["_base"], True
			return True
		if not ligado and t["state"] != "disabled":
			t["_base"] = t["state"]
			t["state"], t["enabled"] = "disabled", False
			return True
		return False

	def video_info(self, q, b):
		url = q.get("url", "")
		m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url)
		if not m:
			raise Erro(400, "Esse link não é de um vídeo do YouTube.")
		vid = m.group(1)
		rng = random.Random(vid)
		avisos = []
		t = None
		if q.get("playlist_id") in b.playlists:
			try:
				t = b.playlists[q["playlist_id"]]["tracks"][int(q.get("index") or 0)]
			except (IndexError, ValueError):
				t = None
		base = (t["duration_ms"] // 1000) if t else 200
		dur = base + rng.choice([0, 12, -9, 0])
		tipo = rng.choice(["song", "video", "song"])
		idade = rng.random() < .25
		if idade:
			avisos.append("Restrição de idade no YouTube: só baixa com a sua conta do YouTube conectada.")
		if dur != base:
			avisos.append(f"{abs(dur - base)} s {'mais longo' if dur > base else 'mais curto'} que a música ({base // 60}:{base % 60:02d}). Pode ser outra versão ou ter introdução.")
		if tipo == "video":
			avisos.append("Este é o clipe. Clipes costumam ter introdução, efeitos ou outra mixagem; a música do YouTube Music costuma ser mais limpa.")
		return {"video_id": vid, "info": {"title": (t["title"] if t else "Vídeo de exemplo") + (" (Clipe Oficial)" if tipo == "video" else ""),
			"author": (t["artists"].split(",")[0] if t else "Canal Exemplo"), "duration_seconds": dur, "kind": tipo,
			"playable": True, "age_restricted": idade}, "description": "", "warnings": avisos}

	def exportar(self, q, b):
		ids = [q["playlist_id"]] if q.get("playlist_id") else b.ordem
		saida = io.StringIO()
		w = csv.writer(saida)
		w.writerow(["Playlist", "Música", "Artista", "Álbum", "Situação"])
		for pid in ids:
			pl = self.playlist(pid)
			for t in pl["tracks"]:
				w.writerow([pl["name"], t["title"], t["artists"], t["album"], t["state"]])
		nome = (b.playlists[ids[0]]["name"] if q.get("playlist_id") else "biblioteca") + ".csv"
		return (saida.getvalue().encode("utf-8"), "text/csv; charset=utf-8",
			{"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(nome)}"})

	def api_aparelhos(self, metodo, partes, b):
		aparelhos = [
			{"id": "ipod-exemplo", "name": "iPod de exemplo", "kind": "ipod_classic", "description": "iPod Classic · 160 GB"},
			{"id": "pendrive-exemplo", "name": "PENDRIVE", "kind": "mass_storage", "description": "Pendrive · 32 GB"},
		]
		if len(partes) == 1:
			return {"devices": aparelhos, "busy": False}
		if len(partes) == 3 and partes[2] == "playlists":
			biblioteca = []
			for pid in b.ordem:
				pl = b.playlists[pid]
				c = b.contagens(pl)
				pronta = bool(c["total"]) and c["missing"] == 0 and c["queued"] == 0
				biblioteca.append({"playlist_id": pid, "name": pl["name"], "ready": pronta,
					"state": "changed" if pl["name"] == "Out Of Time Man" and partes[1] == "ipod-exemplo" else "new"})
			return {"playlists": [{"name": "Out Of Time Man", "track_count": 880}, {"name": "Treino", "track_count": 37}]
				if partes[1] == "ipod-exemplo" else [], "library": biblioteca}
		if len(partes) == 3 and partes[2] == "sync":
			def copiar():
				total = 40
				emitir("device", {"phase": "start", "done": 0, "total": 0, "message": "Começando a sincronizar."})
				for k in range(0, total + 1, 4):
					emitir("device", {"phase": "sync", "done": k, "total": total, "message": "Copiando as músicas"})
					time.sleep(.4)
				emitir("device", {"phase": "done", "done": total, "total": total, "message": "Tudo copiado."})
			iniciar(copiar)
			return {"started": True}
		if len(partes) == 4 and metodo == "DELETE":
			return {"removed": True}
		if len(partes) == 3 and partes[2] == "eject":
			depois(.5, lambda: emitir("device", {"phase": "ejected", "done": 0, "total": 0, "message": "Pode desconectar o aparelho."}))
			return {"ok": True}
		raise Erro(404, "Rota não encontrada.")


def main() -> None:
	global BIB, ARGS
	p = argparse.ArgumentParser(description="Servidor falso da interface web do CSVMusic (dados inventados).")
	p.add_argument("--porta", type=int, default=0)
	p.add_argument("--atraso", type=int, default=0, help="espera em ms em cada chamada JSON")
	p.add_argument("--job", choices=["download", "scan", "nenhum"], default="download")
	p.add_argument("--vazio", action="store_true")
	p.add_argument("--primeira-vez", action="store_true")
	p.add_argument("--token", default="mock-token")
	p.add_argument("--erro-biblioteca", action="store_true", help="state.library.load_error preenchido")
	ARGS = p.parse_args()
	BIB = Biblioteca(ARGS.vazio, ARGS.primeira_vez)
	for k in range(30):
		BIB.registrar(f"Linha de exemplo {k + 1} do registro (servidor falso).", "info" if k % 9 else "warning")
	if not ARGS.vazio:
		if ARGS.job == "download":
			pl = BIB.playlists["spotify:mock-ootm"]
			alvos = [("spotify:mock-ootm", t["index"]) for t in pl["tracks"] if t["state"] == "missing"]
			BIB.job = {"kind": "download", "playlist_ids": ["spotify:mock-ootm"], "processed": 0, "total": len(alvos),
				"eta_at": None, "current": None, "stopping": False, "single": False}
			iniciar(rodar_download, alvos)
		elif ARGS.job == "scan":
			BIB.job = {"kind": "scan", "playlist_id": "ytmusic:mock-pai", "name": "Discos do meu pai", "captured": 0,
				"reported_total": 48, "queue_left": 0, "cancelling": False}
			iniciar(rodar_analise, ["ytmusic:mock-pai"])
	srv = ThreadingHTTPServer(("127.0.0.1", ARGS.porta), Handler)
	srv.daemon_threads = True
	print(f"http://127.0.0.1:{srv.server_address[1]}/", flush=True)
	try:
		srv.serve_forever()
	except KeyboardInterrupt:
		pass


if __name__ == "__main__":
	main()
