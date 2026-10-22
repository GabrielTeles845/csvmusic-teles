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
	// Item 4: com filtro, a lista filtrada muda entre o pedido da página 0 e o da 1; nenhuma música pode sumir.
	async lista(p) {
		const pid = encodeURIComponent(OOTM);
		await p.goto(`${BASE}/#/p/${pid}`);
		await sleep(1200);
		await p.locator(".chip[data-f=missing]").click();
		await sleep(900);
		const antes = await api(p, "GET", `/playlists/${pid}/tracks?filter=missing&offset=0&limit=500`);
		// 50 das que faltam saem do filtro (como quando são baixadas), sem a tela reler a lista.
		const sair = antes.body.items.slice(0, 50).map((t) => t.index);
		await api(p, "POST", `/playlists/${pid}/tracks/set-enabled`, { enabled: false, indices: sair });
		await p.locator("#main").evaluate((m) => { m.scrollTop = m.scrollHeight; });
		await sleep(1200);
		const depois = (await api(p, "GET", `/playlists/${pid}/tracks?filter=missing&offset=0&limit=500`)).body.items.map((t) => t.index);
		const problemas = [];
		for (const alvo of [100, 75, 30]) {
			await p.locator("#main").evaluate((m, alvo) => {
				const rh = parseFloat(getComputedStyle(m.querySelector(".vbody")).getPropertyValue("--rh")) || 52;
				m.scrollTop = m.querySelector(".vbody").offsetTop + alvo * rh - 200;
			}, alvo);
			await sleep(900);
			const linhas = await p.locator(".vbody .row[data-i]").evaluateAll((rows) => rows.map((r) => ({
				pos: Math.round(parseFloat(r.style.top) / (parseFloat(getComputedStyle(r.parentElement).getPropertyValue("--rh")) || 52)),
				i: Number(r.dataset.i),
			})));
			const erradas = linhas.filter((l) => depois[l.pos] !== l.i);
			if (erradas.length) problemas.push(`perto da posição ${alvo}: ${erradas.length} linhas não batem com a lista filtrada atual`);
		}
		const total = await p.locator(".vbody").evaluate((c) => Math.round(c.offsetHeight / (parseFloat(getComputedStyle(c).getPropertyValue("--rh")) || 52)));
		if (total !== depois.length) problemas.push(`a lista tem altura de ${total} linhas, o filtro tem ${depois.length}`);
		return problemas;
	},
	// Item 6: enquanto o pedido de tirar playlist roda, ejetar, mandar e os outros "Tirar" ficam desligados.
	async aparelhos(p) {
		await p.goto(`${BASE}/`);
		await sleep(1000);
		await p.locator('.side [data-l="aparelhos"]').click();
		await p.locator('[data-a="tirar"]').first().waitFor({ timeout: 5000 });
		await p.locator('[data-a="tirar"]').first().click();
		await p.locator(".dlg", { hasText: "Tirar do aparelho" }).locator("[data-sim]").click();
		await sleep(250);
		const problemas = [];
		const ligados = await p.evaluate(() => [...document.querySelectorAll('[data-a="ejetar"], [data-a="sync"], [data-a="tirar"]')]
			.filter((b) => !b.disabled).map((b) => b.dataset.a));
		if (ligados.length) problemas.push(`botões ligados durante o pedido: ${ligados.join(", ")}`);
		await sleep(1800);
		if (await p.locator('[data-a="ejetar"]').isDisabled()) problemas.push("ejetar continuou desligado depois da resposta");
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
