# tabs only
"""Frases que vão para a tela, em português.

O núcleo (`core/`, `ui/workers.py`) continua escrevendo o log técnico em
inglês. Tudo o que chega à página passa por aqui antes. Frase desconhecida
cai num texto genérico em português; o original fica no log e no campo
técnico do erro.
"""
from __future__ import annotations

import re

from csvmusic.core.downloader import detect_youtube_risk, is_age_restriction_error


# --- Motivo do pulo (não encontrada no YouTube) ---------------------------------

def skip_reason_pt(reason: str | None) -> str:
	text = str(reason or "").strip()
	lower = text.casefold()
	if not text:
		return "Nenhuma versão confiável no YouTube Music"
	if lower in ("no search results", "no search results on youtube music"):
		return "A busca no YouTube Music não trouxe resultado"
	if lower == "no result with the right length":
		return "Nenhum resultado com a duração certa"
	match = re.match(r"no confident match on youtube music(?: \(best score ([\d.]+)\))?", lower)
	if match:
		if match.group(1):
			return f"Nenhuma versão confiável no YouTube Music (melhor nota {match.group(1).replace('.', ',')})"
		return "Nenhuma versão confiável no YouTube Music"
	if "search" in lower or "http" in lower or "timed out" in lower or "connection" in lower:
		return "A busca no YouTube Music falhou; tente de novo mais tarde"
	return "Nenhuma versão confiável no YouTube Music"


# --- Motivo da revisão -------------------------------------------------------------

def review_reason_pt(reason: str | None) -> str:
	text = str(reason or "").strip()
	if not text:
		return "Escolha automática com pouca confiança; confira se é a música certa"
	match = re.match(r"file is (\d+) s (longer|shorter) than the song", text.casefold())
	if match:
		direction = "mais longo" if match.group(2) == "longer" else "mais curto"
		return f"Arquivo {match.group(1)} s {direction} que a música"
	if text.casefold() == "length could not be confirmed":
		return "Não deu para conferir a duração do arquivo"
	return "Confira se é a música certa"


# --- Erro de download ------------------------------------------------------------

def error_summary_pt(error: str | None, failure_kind: str | None = None) -> tuple[str, str]:
	"""(frase curta, o que fazer) para um erro de download."""
	text = str(error or "")
	lower = text.casefold()
	if failure_kind == "age_restricted" or is_age_restriction_error(text):
		return (
			"Restrição de idade: precisa entrar no YouTube",
			"Entre na sua conta do YouTube em Ajustes › Conta do YouTube e baixe de novo.",
		)
	risk = detect_youtube_risk(text)
	if risk:
		return (
			"O YouTube recusou por excesso de pedidos",
			"Espere alguns minutos antes de tentar de novo. Entrar na conta do YouTube costuma ajudar.",
		)
	if "wrong length" in lower or "could not read the length" in lower:
		return (
			"O arquivo baixado tem outra duração",
			"Escolha outra versão do YouTube no painel da música.",
		)
	if "did not finish within" in lower:
		return (
			"O download demorou demais e foi interrompido",
			"Confira a internet e tente de novo.",
		)
	if "ffmpeg" in lower:
		return (
			"Falha ao converter o áudio",
			"Confira o FFmpeg em Ajustes › Avançado e tente de novo.",
		)
	if "video unavailable" in lower or "private video" in lower or "not available" in lower:
		return (
			"Vídeo indisponível no YouTube",
			"Escolha outra versão do YouTube no painel da música.",
		)
	if "stopped by user" in lower:
		return ("Download parado", "Baixe de novo quando quiser.")
	return (
		"O download falhou",
		"Tente de novo. Se continuar, escolha outra versão do YouTube no painel da música.",
	)


# --- Avisos da escolha manual de vídeo (core/manual_match.py) ----------------------

def manual_warning_pt(warning: str) -> str:
	text = str(warning or "")
	if text.startswith("Age-restricted on YouTube"):
		return "Tem restrição de idade no YouTube: só baixa com a sua conta do YouTube conectada."
	if text.startswith("Not playable:"):
		return "O YouTube diz que este vídeo não está disponível."
	match = re.match(r"(\d+) s (longer|shorter) than the song \(([\d:?]+)\)", text)
	if match:
		direction = "mais longo" if match.group(2) == "longer" else "mais curto"
		return f"{match.group(1)} s {direction} que a música ({match.group(3)}). Pode ser outra versão ou ter introdução."
	if text.startswith("This is the music video"):
		return "Este é o videoclipe. Clipe costuma ter introdução, efeitos ou outra mixagem; a música do YouTube Music costuma ser mais limpa."
	if text.startswith("This is a podcast episode"):
		return "Este é um episódio de podcast, não uma música."
	match = re.match(r'The video title does not mention "(.*)"\.', text)
	if match:
		return f"O título do vídeo não menciona \"{match.group(1)}\"."
	return text


_KIND_PT = {
	"song": "música do YouTube Music",
	"music_video": "videoclipe oficial",
	"user_video": "vídeo comum do YouTube",
	"podcast": "episódio de podcast",
	"unknown": "vídeo do YouTube",
}


def video_kind_pt(kind: str | None) -> str:
	return _KIND_PT.get(str(kind or "unknown"), _KIND_PT["unknown"])


# --- Sessão do YouTube --------------------------------------------------------------

def session_message_pt(message: str, ok: bool) -> str:
	text = str(message or "")
	if ok or text.startswith("PASS"):
		return "O YouTube reconheceu a sua conta."
	if text.startswith("NOT VERIFIED"):
		return "O YouTube não confirmou a conta. Entre de novo; a sessão pode ter expirado."
	if text.startswith("CHECK FAILED"):
		return "Não deu para falar com o YouTube agora. Confira a internet e tente de novo."
	if text.startswith("Cookies file not found"):
		return "O arquivo de cookies não foi encontrado."
	if text.startswith("Cannot read this file"):
		return "Este arquivo não é um cookies.txt válido. Exporte de novo."
	if text.startswith("No unexpired YouTube account cookies"):
		return "O arquivo não tem uma sessão do YouTube válida. Exporte de novo com a conta aberta."
	if text.startswith("Unexpired YouTube account cookies found"):
		return "O arquivo tem uma sessão do YouTube. O YouTube ainda pode recusar uma sessão expirada."
	return "Não deu para conferir a conta do YouTube."


# --- Qualidade do arquivo --------------------------------------------------------------

def quality_pt(quality: dict | None) -> dict | None:
	if not quality:
		return None
	codec = str(quality.get("codec") or "").upper()
	kbps = quality.get("kbps")
	low = bool(quality.get("low"))
	if not kbps:
		label = "Qualidade da fonte desconhecida"
	elif low:
		label = f"Fonte fraca · {codec} ~{kbps} kbps"
	else:
		label = f"{codec} ~{kbps} kbps"
	return {"label": label, "low": low}


# --- Análise ---------------------------------------------------------------------------

def scan_error_pt(error: str | None, kind: str | None = None) -> str:
	text = str(error or "")
	lower = text.casefold()
	if kind == "private":
		return "A playlist está particular no Spotify (ou foi apagada). No Spotify, abra a playlist, escolha … › Tornar pública e analise de novo."
	if "did not contain any usable tracks" in lower:
		return "A planilha não tem nenhuma música que dê para usar."
	if "missing required columns" in lower:
		return "A planilha não tem as colunas de música e artista."
	if "no such file" in lower or ("not found" in lower and "csv" in lower):
		return "O arquivo da planilha não foi encontrado."
	if "timed out" in lower or "timeout" in lower or "connection" in lower or "network" in lower:
		return "Sem resposta do serviço. Confira a internet e tente de novo."
	if "404" in lower or "not found" in lower:
		return "A playlist não foi encontrada."
	return "Não deu para ler a playlist. Tente de novo mais tarde."


def scan_warning_pt(warning: str | None) -> str | None:
	if not warning:
		return None
	return "A análise não leu a playlist inteira. Analise de novo para completar."


def add_url_error_pt(error: str) -> str:
	text = str(error or "")
	lower = text.casefold()
	if "single youtube video" in lower:
		return "Este é o link de um vídeo, não de uma playlist. Copie o link da playlist (tem \"list=\" no endereço)."
	return "Este link não é de uma playlist que o CSVMusic reconheça."


# --- Andamento do download (sinais de texto do PipelineWorker) ---------------------------

def status_phase(status: str) -> str:
	"""Fase curta a partir do texto do worker: matching, downloading, tagging, done, failed, skipped, stopped."""
	lower = str(status or "").casefold()
	if lower.startswith("fail") or "failed" in lower:
		return "failed"
	if lower.startswith("stopped"):
		return "stopped"
	if lower.startswith("done") or lower.startswith("low confidence") or lower.startswith("downloaded"):
		return "done"
	if "tagging" in lower:
		return "tagging"
	if "download" in lower or "trying" in lower or "safe mode" in lower or "retrying" in lower:
		return "downloading"
	if "skip" in lower:
		return "skipped"
	if "search" in lower or "match" in lower:
		return "matching"
	return "downloading"


def status_line_pt(status: str) -> str:
	"""A mesma frase do worker, em português, para o registro da sessão."""
	text = str(status or "")
	lower = text.casefold()
	fmt = re.search(r"\((m4a|mp3|opus)\)", text)
	fmt_text = f" ({fmt.group(1)})" if fmt else ""
	if lower.startswith("fail"):
		return "Falhou"
	if lower.startswith("stopped"):
		return "Parado"
	if lower.startswith("low confidence"):
		return "Baixada (pouca confiança, revisar)"
	if lower.startswith("done"):
		return "Baixada"
	if lower.startswith("downloaded — low quality"):
		return "Baixada (fonte fraca)"
	if "tagging" in lower:
		return "Gravando capa e dados"
	if "retrying with youtube safe mode" in lower:
		return "Tentando de novo com mais calma"
	if "downloading low-confidence" in lower:
		return f"Baixando versão com pouca confiança{fmt_text}"
	if "download" in lower or "trying" in lower:
		return f"Baixando{fmt_text}"
	if lower.startswith("skipped (no search results)"):
		return "Pulada: a busca não trouxe resultado"
	if lower.startswith("skipped (wrong length)"):
		return "Pulada: nenhum resultado com a duração certa"
	if lower.startswith("skipped"):
		return "Pulada: nenhuma versão confiável"
	if lower.startswith("search failed"):
		return "A busca falhou"
	return "Em andamento"


def log_line_pt(message: str) -> str:
	text = str(message or "")
	lower = text.casefold()
	if lower.startswith("[m3u] wrote:") or lower.startswith("[m3u] updated:"):
		return "Lista da playlist atualizada: " + text.split(":", 1)[1].strip()
	if lower.startswith("[csv] loading"):
		return "Preparando a lista de músicas"
	if lower.startswith("[match] searching"):
		return "Procurando as músicas no YouTube Music"
	if lower.startswith("[warn] low youtube source bitrate:"):
		rest = text.split(":", 1)[1].strip()
		return f"Fonte fraca no YouTube: {rest}"
	if lower.startswith("[warn]"):
		return warning_pt(text[6:].strip())
	return text


def warning_pt(message: str) -> str:
	"""Avisos do worker que a tela mostra em destaque."""
	text = str(message or "")
	lower = text.casefold()
	if lower.startswith("large youtube batch"):
		return "Lote grande: os downloads vão com pausas variadas para o YouTube não bloquear."
	if lower.startswith("youtube started throttling"):
		return "O YouTube começou a frear os pedidos. O CSVMusic diminuiu o ritmo sozinho."
	if lower.startswith("youtube music search failed repeatedly"):
		return "A busca no YouTube Music falhou várias vezes seguidas. O download parou; tente mais tarde."
	if lower.startswith("youtube music returned no results for five tracks"):
		return "O YouTube Music não achou cinco músicas seguidas. Isso costuma ser bloqueio temporário da rede: o download parou. Espere antes de tentar de novo."
	return "Aviso do YouTube: veja o registro."


def risk_acknowledgement_pt(track_count: int) -> str:
	return (
		f"São {track_count} músicas. Um lote grande faz muitos pedidos ao YouTube, que pode frear a conexão, "
		"pedir verificação de robô ou bloquear por um tempo. O CSVMusic vai baixar com pausas variadas e mais devagar "
		"para diminuir a chance, mas não dá para garantir. Um lote grande demora; evite recomeçar várias vezes."
	)
