# tabs only
import pathlib
import tomllib

from csvmusic.core.manual_match import choice_warnings
from csvmusic.engine import texts

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_web_page_is_packaged():
	with (ROOT / "pyproject.toml").open("rb") as handle:
		config = tomllib.load(handle)["tool"]["setuptools"]
	assert "web/static/**/*" in config["package-data"]["csvmusic"]
	assert {"csvmusic.engine", "csvmusic.web"} <= set(config["packages"])
	spec = (ROOT / "CSVMusic.spec").read_text(encoding="utf-8")
	assert "('csvmusic/web/static', 'csvmusic/web/static')" in spec
	assert (ROOT / "csvmusic" / "web" / "static" / "index.html").is_file()


def test_skip_and_review_reasons():
	assert texts.skip_reason_pt("No confident match on YouTube Music (best score 0.42)") == "Nenhuma versão confiável no YouTube Music (melhor nota 0,42)"
	assert texts.skip_reason_pt("No search results on YouTube Music") == "A busca no YouTube Music não trouxe resultado"
	assert texts.review_reason_pt("File is 12 s shorter than the song") == "Arquivo 12 s mais curto que a música"
	assert texts.review_reason_pt(None).startswith("Escolha automática")


def test_error_summaries():
	assert texts.error_summary_pt("x", "age_restricted")[0] == "Restrição de idade: precisa entrar no YouTube"
	assert texts.error_summary_pt("ERROR: Sign in to confirm you're not a bot")[0] == "O YouTube recusou por excesso de pedidos"
	assert texts.error_summary_pt("wrong length: file 4:10, expected 3:57 (+13 s)")[0] == "O arquivo baixado tem outra duração"
	assert texts.error_summary_pt("something odd")[0] == "O download falhou"


def test_every_manual_match_warning_is_translated():
	track = {"title": "Country House", "artists": "Blur", "duration_ms": 237000}
	info = {"title": "Other Song (Official Video)", "author": "Blur", "duration_seconds": 300, "kind": "music_video", "playable": True, "age_restricted": True}
	warnings = choice_warnings(track, info)
	assert len(warnings) >= 3
	translated = [texts.manual_warning_pt(warning) for warning in warnings]
	assert translated != warnings
	for original, text in zip(warnings, translated):
		assert text != original, original


def test_worker_statuses_map_to_phases():
	assert texts.status_phase("Downloading (m4a)…") == "downloading"
	assert texts.status_phase("Tagging…") == "tagging"
	assert texts.status_phase("Done → a.m4a") == "done"
	assert texts.status_phase("Fail: boom") == "failed"
	assert texts.status_phase("Skipped (low confidence)") == "skipped"
	assert texts.status_line_pt("Skipped (wrong length)") == "Pulada: nenhum resultado com a duração certa"
	assert texts.quality_pt({"codec": "AAC", "kbps": 128, "low": False}) == {"label": "AAC ~128 kbps", "low": False}
