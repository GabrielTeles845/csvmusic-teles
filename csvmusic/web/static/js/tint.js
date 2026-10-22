// Cor do topo da playlist: o matiz mais saturado do mosaico (docs/fork/06 §5).
// Só o matiz e a saturação vêm da capa; a luminosidade é fixa por tema em tokens.css,
// o que mantém o texto branco (escuro) e o texto escuro (claro) acima de 4,5:1.
import { capa } from "./api.js";

const cache = new Map();
const PADRAO = { h: 47, s: 52 };

function carregar(url) {
	return new Promise((resolve) => {
		const img = new Image();
		img.decoding = "async";
		img.onload = () => resolve(img);
		img.onerror = () => resolve(null);
		capa(url).then((src) => { if (src) img.src = src; else resolve(null); });
	});
}

async function calcular(urls) {
	const imgs = (await Promise.all(urls.slice(0, 4).map(carregar))).filter(Boolean);
	if (!imgs.length) return PADRAO;
	const c = document.createElement("canvas");
	c.width = c.height = 24;
	const ctx = c.getContext("2d", { willReadFrequently: true });
	let melhor = null;
	for (const img of imgs) {
		ctx.drawImage(img, 0, 0, 24, 24);
		let px;
		try { px = ctx.getImageData(0, 0, 24, 24).data; } catch { continue; }
		for (let i = 0; i < px.length; i += 4) {
			const r = px[i] / 255, g = px[i + 1] / 255, b = px[i + 2] / 255;
			const max = Math.max(r, g, b), min = Math.min(r, g, b);
			const l = (max + min) / 2;
			if (l < .12 || l > .9) continue;
			const d = max - min;
			const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
			if (melhor && s <= melhor.s) continue;
			let h = 0;
			if (d) {
				if (max === r) h = ((g - b) / d) % 6;
				else if (max === g) h = (b - r) / d + 2;
				else h = (r - g) / d + 4;
				h *= 60;
				if (h < 0) h += 360;
			}
			melhor = { h, s };
		}
	}
	if (!melhor || melhor.s < .15) return { h: melhor ? melhor.h : PADRAO.h, s: 8 };
	return { h: Math.round(melhor.h), s: Math.round(Math.min(.62, Math.max(.3, melhor.s)) * 100) };
}

let vez = 0;
export async function tingir(pl) {
	const minha = ++vez;
	const raiz = document.documentElement;
	const urls = (pl?.cover_urls || []).filter(Boolean);
	const chave = urls.join("|");
	let cor = cache.get(chave);
	if (!cor) {
		cor = urls.length ? await calcular(urls) : PADRAO;
		cache.set(chave, cor);
	}
	if (minha !== vez) return;
	raiz.style.setProperty("--tint-h", cor.h);
	raiz.style.setProperty("--tint-s", cor.s + "%");
}
