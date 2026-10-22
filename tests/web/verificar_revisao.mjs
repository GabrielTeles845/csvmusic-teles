// Confere na tela (servidor falso + Playwright) os consertos da revisão de 22/10/2026 que só existem no JS.
// Uso: suba `python3 tests/web/mock_server.py --porta 8797 --job nenhum` e rode
//   BASE=http://127.0.0.1:8797 CEN=chave,lista,aparelhos,registro node tests/web/verificar_revisao.mjs
// Cada cenário imprime OK ou FALHOU; o processo sai com 1 se algum falhar.
import { createRequire } from "node:module";
const { chromium } = createRequire(process.env.HOME + "/Projetos/trabalho/lp-valhalla/package.json")("playwright");
const BASE = process.env.BASE || "http://127.0.0.1:8797";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const OOTM = "spotify:mock-ootm";

// Chamada à API de dentro da página (com o token da página).
const api = (p, method, path, body) => p.evaluate(async ([method, path, body]) => {
	const t = document.querySelector('meta[name="csvmusic-token"]').content;
	const init = { method, headers: { "X-CSVMusic-Token": t } };
	if (body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
	const r = await fetch("/api" + path, init);
	return { status: r.status, body: await r.json().catch(() => null) };
}, [method, path, body]);

const titulo = (p, i) => p.locator(`.vbody .row[data-i="${i}"] .t b`).innerText();

const CENARIOS = {
	// Item 1: nova análise reordena; a tela relê a lista, fecha o painel e o índice velho leva 409.
	async chave(p) {
		await p.goto(`${BASE}/#/p/${encodeURIComponent(OOTM)}`);
		await sleep(1200);
		const velho = await api(p, "GET", `/playlists/${encodeURIComponent(OOTM)}/tracks?offset=0&limit=5`);
		const alvo = velho.body.items[2];
		await p.locator('.vbody .row[data-i="2"] .t').click();
		await p.locator(".painel").waitFor();
		await api(p, "POST", "/scan", { playlist_ids: [OOTM] });
		await p.locator(".painel").waitFor({ state: "detached", timeout: 20000 });
		await sleep(600);
		const problemas = [];
		if (await titulo(p, 3) !== (alvo.title || "Sem título")) problemas.push("a linha 3 não mostra a música que era a 2 (lista não foi relida)");
		const stale = await api(p, "PATCH", `/playlists/${encodeURIComponent(OOTM)}/tracks/2`, { enabled: false, key: alvo.key });
		if (stale.status !== 409 || stale.body?.code !== "track_moved") problemas.push(`PATCH com chave velha respondeu ${stale.status}`);
		return problemas;
	},
	// Item 2: salvar uma cópia por cima de um arquivo que existe pergunta antes.
	async copia(p) {
		await p.goto(`${BASE}/`);
		await sleep(1000);
		await p.keyboard.press("Control+,");
		await sleep(400);
		await p.locator('[data-aba="biblioteca"]').click();
		await sleep(300);
		const problemas = [];
		await p.locator('[data-lib="salvar"]').click();
		await p.locator(".toast", { hasText: "Cópia salva" }).waitFor({ timeout: 3000 });
		await p.locator(".toast .fechar").first().click();
		await p.locator('[data-lib="salvar"]').click();
		const pergunta = p.locator(".dlg", { hasText: "Substituir o arquivo?" });
		try { await pergunta.waitFor({ timeout: 3000 }); } catch { problemas.push("não perguntou antes de substituir"); return problemas; }
		await pergunta.locator("[data-sim]").click();
		try { await p.locator(".toast", { hasText: "Cópia salva" }).waitFor({ timeout: 3000 }); } catch { problemas.push("depois de confirmar, a cópia não foi salva"); }
		return problemas;
	},
};

const pedidos = (process.env.CEN || Object.keys(CENARIOS).join(",")).split(",");
const browser = await chromium.launch();
let falhas = 0;
for (const nome of pedidos) {
	const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const p = await ctx.newPage();
	const erros = [];
	p.on("pageerror", (e) => erros.push("PAGEERROR " + e.message));
	let problemas;
	try { problemas = await CENARIOS[nome](p); } catch (e) { problemas = ["exceção: " + e.message.split("\n")[0]]; }
	problemas.push(...erros);
	if (problemas.length) falhas++;
	console.log(`${problemas.length ? "FALHOU" : "OK"} ${nome}${problemas.length ? ": " + problemas.join(" | ") : ""}`);
	await ctx.close();
}
await browser.close();
process.exit(falhas ? 1 : 0);
