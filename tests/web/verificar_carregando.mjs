// Verificador da skill carregamento-fiel, adaptado à tela do CSVMusic (sem thead: o cabeçalho é .cab).
// Abre a tela com dados e com ?carregando, mede os marcos e reprova: marco sumido, marco andando > 4 px
// para baixo/cima, vazio falso no texto, esqueleto genérico.
import { createRequire } from "node:module";
const { chromium } = createRequire(process.env.HOME + "/Projetos/trabalho/lp-valhalla/package.json")("playwright");
const BASE = process.env.BASE || "http://127.0.0.1:8791";
const TELAS = (process.env.TELAS || "/").split(",");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const VAZIO_FALSO = /(^|\s)0 (itens|resultados|músicas|playlists)|Nenhum[a]? .{0,40}(ainda|cadastrad)|Carregando(…|\.\.\.)/;

async function marcos(p) {
	return p.evaluate(() => {
		const out = {};
		const add = (tipo, el) => {
			const r = el.getBoundingClientRect();
			if (!r.width || !r.height) return;
			const txt = (el.innerText || "").replace(/[\d.,]+/g, "").trim();
			out[`${tipo}:${txt}`] = { x: Math.round(r.left), y: Math.round(r.top) };
		};
		document.querySelectorAll("main h1").forEach((e) => { const r = e.getBoundingClientRect(); out["h1"] = { x: Math.round(r.left), y: Math.round(r.top) }; });
		document.querySelectorAll('main [role="tab"]').forEach((e) => add("tab", e));
		document.querySelectorAll("main .cab > span").forEach((e) => add("th", e));
		document.querySelectorAll("main .acoes .busca-lista, .side .marca, .side .addb").forEach((e) => add("fixo", e));
		return { out, texto: document.querySelector("main").innerText, generico: !!document.querySelector('[aria-label=Carregando][aria-busy=true]') };
	});
}

const browser = await chromium.launch();
let falhas = 0;
for (const w of [1440, 390]) for (const tela of TELAS) {
	const ctx = await browser.newContext({ viewport: { width: w, height: w > 800 ? 900 : 844 } });
	const p = await ctx.newPage();
	await p.goto(BASE + "/" + tela);
	await sleep(1800);
	const com = await marcos(p);
	await p.goto(BASE + "/?carregando" + tela);
	await sleep(800);
	const sem = await marcos(p);
	const erros = [];
	for (const [k, v] of Object.entries(com.out)) {
		if (k.startsWith("tab:") && !(k in sem.out)) { erros.push(`aba sumiu no carregando: ${k}`); continue; }
		if (!(k in sem.out)) { if (k === "h1" || k.startsWith("th:")) erros.push(`marco sumiu: ${k}`); continue; }
		const dy = Math.abs(sem.out[k].y - v.y);
		if (dy > 4) erros.push(`${k} andou ${dy}px na vertical`);
	}
	if (VAZIO_FALSO.test(sem.texto)) erros.push("vazio falso no carregando: " + sem.texto.match(VAZIO_FALSO)[0]);
	if (sem.generico) erros.push("esqueleto genérico");
	console.log(`${w} ${tela}: ${erros.length ? "REPROVA\n  " + erros.join("\n  ") : "ok"} (${Object.keys(com.out).length} marcos)`);
	falhas += erros.length;
	await ctx.close();
}
await browser.close();
process.exit(falhas ? 1 : 0);
