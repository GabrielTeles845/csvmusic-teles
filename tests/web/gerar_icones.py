"""Monta csvmusic/web/static/icons/lucide.svg com os ícones Lucide que a tela usa.

Uso (uma vez, quando a tela passar a usar um ícone novo):
	npm pack lucide-static@0.460.0 && tar xzf lucide-static-0.460.0.tgz
	python tests/web/gerar_icones.py package/icons

Lucide é ISC (licenses/Lucide-ISC.txt). Nada é baixado em tempo de uso.
"""
import pathlib
import re
import sys

VERSAO = "0.460.0"
ICONES = sorted(set("""
	arrow-up-from-line audio-lines check chevron-down circle-alert circle-check circle-dashed circle-help
	circle-minus circle-x clock copy disc-3 download ellipsis file-spreadsheet file-text file-up folder-open
	globe hard-drive info library link list list-music lock log-in log-out monitor moon music pencil pin plus
	refresh-cw replace search search-x settings shield-check sliders-horizontal smartphone square
	square-check-big sun sun-moon tag trash-2 triangle-alert unplug usb user x
""".split()))

DESTINO = pathlib.Path(__file__).resolve().parents[2] / "csvmusic" / "web" / "static" / "icons" / "lucide.svg"


def miolo(svg: str) -> str:
	"""Devolve só os desenhos de dentro do <svg>, sem comentários e numa linha."""
	corpo = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
	corpo = re.sub(r"<!--.*?-->", "", corpo, flags=re.S)
	return re.sub(r"\s+", " ", corpo).strip()


def main(pasta: str) -> None:
	origem = pathlib.Path(pasta)
	simbolos = []
	for nome in ICONES:
		svg = (origem / f"{nome}.svg").read_text(encoding="utf-8")
		simbolos.append(
			f'<symbol id="{nome}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
			f'stroke-linecap="round" stroke-linejoin="round">{miolo(svg)}</symbol>'
		)
	DESTINO.parent.mkdir(parents=True, exist_ok=True)
	DESTINO.write_text(
		f"<!-- Lucide {VERSAO} (lucide-static, ISC). Gerado por tests/web/gerar_icones.py. -->\n"
		'<svg xmlns="http://www.w3.org/2000/svg">\n' + "\n".join(simbolos) + "\n</svg>\n",
		encoding="utf-8",
	)


if __name__ == "__main__":
	main(sys.argv[1])
