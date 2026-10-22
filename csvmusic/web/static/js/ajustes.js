// Ajustes (⌘,): Downloads, Som, Conta do YouTube, Avançado, Aparência, Biblioteca.
// Cada mudança vai na hora para PATCH /api/settings (docs/fork/14 §4.1).
import { get, patch, post } from "./api.js";
import { store, on, aplicarEstado } from "./store.js";
import { esc, icon, el, n, dataHora } from "./util.js";
import { dialogo, opcao, segmentado, pintarRegua, menu, erro, aviso, sh, confirmar } from "./ui.js";
import { exportarPlanilha, abrirNoFinder } from "./acoes.js";
import { aplicarTema } from "./tema.js";

const ABAS = [
	["downloads", "Downloads", "download"],
	["som", "Som", "audio-lines"],
	["conta", "Conta do YouTube", "user", "Conta"],
	["avancado", "Avançado", "sliders-horizontal"],
	["aparencia", "Aparência", "sun-moon"],
	["biblioteca", "Biblioteca", "library"],
];

let d = null;
let cfg = null;
let aba = "downloads";

export function abrirAjustes(qual) {
	if (qual) aba = qual;
	if (d && !d.fechado) { trocar(aba); return; }
	cfg = null;
	d = dialogo({
		titulo: "Ajustes",
		largo: true,
		corpo: `<div class="ajustes">
			<nav role="tablist" aria-label="Seções dos ajustes" aria-orientation="vertical">${ABAS.map(([k, r, ic, curto]) =>
				`<button role="tab" data-aba="${k}" aria-selected="${k === aba}" aria-label="${r}">${icon(ic)}${curto ? `<span class="so-d">${r}</span><span class="so-m">${curto}</span>` : r}</button>`).join("")}</nav>
			<section role="tabpanel" tabindex="-1"></section>
		</div>`,
		pe: `<span class="salvo" data-salvo aria-live="polite"></span><button class="btn" data-fechar-pe>Fechar</button>`,
		aoFechar: () => { d = null; },
	});
	d.pe.querySelector("[data-fechar-pe]").onclick = () => d.fechar();
	d.corpo.querySelector("nav").addEventListener("click", (ev) => {
		const b = ev.target.closest("[data-aba]");
		if (b) trocar(b.dataset.aba);
	});
	d.corpo.querySelector("nav").addEventListener("keydown", (ev) => {
		if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(ev.key)) return;
		ev.preventDefault();
		const i = ABAS.findIndex(([k]) => k === aba);
		const prox = ABAS[(i + (ev.key === "ArrowDown" || ev.key === "ArrowRight" ? 1 : ABAS.length - 1)) % ABAS.length][0];
		trocar(prox);
		d.corpo.querySelector(`[data-aba="${prox}"]`).focus();
	});
	ligarSecao();
	trocar(aba);
	get("/settings").then((s) => { cfg = s; if (d) pintar(); }).catch((e) => {
		if (!d) return;
		d.corpo.querySelector("section").innerHTML = `<div class="lista-msg"><h2>Não deu para abrir os ajustes</h2><p>${esc(e.message)}</p></div>`;
	});
}

function trocar(k) {
	aba = k;
	d.corpo.querySelectorAll("[data-aba]").forEach((b) => b.setAttribute("aria-selected", b.dataset.aba === k));
	pintar();
}

// ---------- Peças ----------
const v = (k, padrao = "") => (cfg ? cfg[k] ?? padrao : padrao);
const brilhoValor = (w = "40%") => sh(w);

function chaveDe(k, titulo, texto, desligado) {
	if (!cfg) return `<div class="opcao"><div class="opcao-txt"><b>${esc(titulo)}</b>${texto ? `<span>${esc(texto)}</span>` : ""}</div>${sh("44px", "sh-blk sh-pill chave")}</div>`;
	return opcao({ id: "aj-" + k, titulo, texto, ligado: !!cfg[k], desligado }).replace('role="switch"', `role="switch" data-k="${k}"`);
}

function pasta(k, titulo, proposito, ajuda, vazio = "Nenhuma pasta escolhida") {
	const val = v(k);
	return `<div class="campo"><span class="rot">${esc(titulo)}</span>
		<div class="linha-campo">
			${cfg ? `<span class="caminho${val ? "" : " vazio"}">${esc(val || vazio)}</span>` : `<span class="caminho">${brilhoValor("70%")}</span>`}
			<button class="btn" data-pasta="${k}" data-proposito="${proposito}" ${cfg ? "" : "disabled"}>${icon("folder-open")}Escolher…</button>
			${val && k !== "output_dir" ? `<button class="btn" data-limpar="${k}">Limpar</button>` : ""}
		</div>${ajuda ? `<span class="ajuda">${esc(ajuda)}</span>` : ""}</div>`;
}

function arquivo(k, titulo, proposito, ajuda, vazio) {
	return pasta(k, titulo, proposito, ajuda, vazio).replace(`data-pasta="${k}"`, `data-arquivo="${k}"`).replace(icon("folder-open"), icon("file-up"));
}

function seg(k, titulo, itens, ajuda) {
	return `<div class="campo"><span class="rot" id="rot-${k}">${esc(titulo)}</span>
		${cfg ? segmentado(k, itens, cfg[k], titulo) : `<div class="seg">${itens.map(() => `<button disabled>${sh("3em")}</button>`).join("")}</div>`}
		${ajuda ? `<span class="ajuda">${ajuda}</span>` : ""}</div>`;
}

function regua(k, titulo, min, max, fmt, inverso = false) {
	const bruto = Number(v(k, 0));
	const val = inverso ? max - bruto : bruto;
	return `<div class="regua"><label for="aj-${k}">${esc(titulo)}</label>
		<input id="aj-${k}" type="range" min="${min}" max="${max}" step="1" value="${val}" data-r="${k}" data-inverso="${inverso ? 1 : ""}" ${cfg ? "" : "disabled"}>
		<output for="aj-${k}">${cfg ? esc(fmt(val)) : sh("3em")}</output></div>`;
}

function escolha(k, titulo, itens, ajuda) {
	const atual = v(k);
	const rot = (itens.find(([x]) => x === atual) || [null, atual || "Nenhum"])[1];
	return `<div class="campo"><span class="rot">${esc(titulo)}</span>
		<div><button class="btn escolha" data-escolha="${k}" aria-haspopup="menu" ${cfg ? "" : "disabled"}>
			<span>${cfg ? esc(rot) : sh("6em")}</span>${icon("chevron-down")}</button></div>
		${ajuda ? `<span class="ajuda">${esc(ajuda)}</span>` : ""}</div>`;
}

const db = (x) => `${x > 0 ? "+" : ""}${x} dB`;

const FORMATOS = [["m4a", "M4A"], ["mp3", "MP3"], ["opus", "Opus"]];
const NAVEGADORES = [["firefox", "Firefox"], ["chrome", "Chrome"], ["safari", "Safari"], ["edge", "Edge"], ["brave", "Brave"], ["chromium", "Chromium"], ["opera", "Opera"], ["vivaldi", "Vivaldi"]];
const MP3_MODOS = [["vbr", "Usar a qualidade do MP3 acima"], ["cbr_192", "Fixo em 192 kbps"], ["cbr_256", "Fixo em 256 kbps"], ["cbr_320", "Fixo em 320 kbps"]];

function secaoDownloads() {
	return `<h3>Onde salvar</h3>
		${pasta("output_dir", "Pasta das músicas", "output", "Cada playlist ganha uma pasta dentro desta.")}
		<h3>Formato</h3>
		${seg("format", "Formato do arquivo", FORMATOS, "M4A toca em tudo da Apple. MP3 toca em qualquer aparelho. Opus guarda o áudio do YouTube sem converter, mas o equalizador não vale para ele.")}
		${regua("mp3_quality", "Qualidade do MP3", 0, 10, (x) => `${x} de 10`, true)}
		<p class="ajuda">Mais alto, arquivo melhor e maior.</p>
		<h3>Arquivos</h3>
		${chaveDe("embed_art", "Pôr a capa dentro do arquivo", "O tocador mostra a capa do álbum.")}
		${chaveDe("prefix_track_numbers", "Numerar os arquivos na ordem da playlist", "O nome do arquivo começa com a posição: 001, 002…")}
		${chaveDe("write_m3u8", "Criar a lista da playlist (.m3u8)", "Arquivo que os tocadores abrem para tocar na ordem.")}
		${chaveDe("write_m3u_plain", "Criar também a lista .m3u", "Para tocadores antigos que não abrem .m3u8.")}
		${pasta("m3u_output_dir", "Pasta das listas", "m3u", "Em branco, a lista fica junto das músicas.", "Junto das músicas")}
		<h3>Busca</h3>
		${chaveDe("force_download_mode", "Baixar mesmo sem certeza", "Se nenhuma versão parecer a certa, baixa a melhor que achou e marca a música para revisar.")}`;
}

function secaoSom() {
	const off = !cfg || !cfg.eq_enabled;
	return `${chaveDe("eq_enabled", "Equalizador ligado", "Vale para os próximos downloads em M4A e MP3.")}
		${chaveDe("eq_normalize", "Igualar o volume entre as músicas", "Evita uma música bem mais alta que a outra.", off)}
		<h3>Ajuste fino</h3>
		${regua("eq_volume_gain", "Volume", -12, 12, db).replace("data-r", off && cfg ? "disabled data-r" : "data-r")}
		${regua("eq_bass_gain", "Graves", -12, 12, db).replace("data-r", off && cfg ? "disabled data-r" : "data-r")}
		${regua("eq_treble_gain", "Agudos", -12, 12, db).replace("data-r", off && cfg ? "disabled data-r" : "data-r")}`;
}

function blocoConta() {
	const a = store.account || {};
	const ok = a.connected;
	return `<div class="conta ${ok ? "ok" : "nao"}" data-conta>${icon(ok ? "circle-check" : "user")}
		<div><b>${ok ? "Sessão do YouTube ligada" : "Sem sessão do YouTube"}</b>
		<small>${ok ? (a.checked_at ? `Conferida em ${esc(dataHora(a.checked_at))}` : "Pronta para usar") : "Sem login, músicas com restrição de idade não baixam."}</small></div></div>`;
}

function secaoConta() {
	return `${blocoConta()}
		<div class="botoes-linha">
			<button class="btn pri" data-conta-acao="popup">${icon("log-in")}Entrar com o Google</button>
			<button class="btn" data-conta-acao="firefox">${icon("globe")}Usar a sessão do Firefox</button>
			<button class="btn" data-conta-acao="testar">${icon("shield-check")}Testar a sessão</button>
			${store.account?.connected ? `<button class="btn perigo" data-conta-acao="sair">${icon("log-out")}Sair da sessão</button>` : ""}
		</div>
		<p class="ajuda" data-conta-msg></p>
		<h3>Detalhes</h3>
		${chaveDe("use_cookies", "Usar a sessão do YouTube nos downloads", "Ajuda com músicas que pedem login.")}
		${escolha("cookies_browser", "Navegador de onde vem a sessão", NAVEGADORES)}
		${arquivo("cookies_file", "Arquivo da sessão (.txt)", "cookies", "Se escolher um arquivo, ele vale no lugar do navegador.", "Nenhum arquivo")}`;
}

function secaoAvancado() {
	return `<h3>Programas</h3>
		${arquivo("yt_dlp_path", "yt-dlp", "ytdlp", "Em branco, usa o que vem com o CSVMusic.", "O que vem com o CSVMusic")}
		${arquivo("ffmpeg_path", "FFmpeg", "ffmpeg", "Em branco, usa o que vem com o CSVMusic.", "O que vem com o CSVMusic")}
		<h3>iPod antigo</h3>
		${chaveDe("legacy_ipod_mode", "Modo iPod antigo", "MP3 e capas mais simples para iPod Classic e tocadores parecidos.")}
		${escolha("legacy_mp3_mode", "MP3 no modo iPod", MP3_MODOS, "Se o iPod travar em algumas músicas, tente 192 kbps.")}
		<h3>Aparelhos</h3>
		${chaveDe("device_sync_auto_eject", "Ejetar o aparelho ao terminar", "Depois de mandar as músicas, o aparelho já pode ser desconectado.")}
		<h3>Endereço local</h3>
		<div class="campo"><label for="aj-porta">Porta</label>
			<div class="linha-campo"><input id="aj-porta" class="entrada" inputmode="numeric" value="${esc(v("web_port"))}" style="max-width:160px" ${cfg ? "" : "disabled"}>
			<button class="btn" data-porta ${cfg ? "" : "disabled"}>Salvar porta</button></div>
			<span class="ajuda">Vale na próxima vez que o CSVMusic abrir.</span></div>
		<h3>Lixeira interna</h3>
		<div data-lixeira><p class="ajuda">${sh("14em")}</p></div>
		<h3>Registro</h3>
		<button class="btn" data-log>${icon("file-text")}Abrir o registro completo no Finder</button>`;
}

function secaoAparencia() {
	const tema = cfg ? cfg.theme || "system" : localStorage.getItem("csvmusic-tema") || "system";
	return `<div class="campo"><span class="rot">Tema</span>
		${segmentado("theme", [["system", "Do sistema", "monitor"], ["light", "Claro", "sun"], ["dark", "Escuro", "moon"]], tema, "Tema")}
		<span class="ajuda">“Do sistema” acompanha o claro e o escuro do Mac.</span></div>`;
}

function secaoBiblioteca() {
	const lib = store.library || {};
	return `<div class="campo"><span class="rot">Arquivo da biblioteca</span>
			<span class="caminho">${esc(lib.path || "")}</span>
			<span class="ajuda">É onde ficam suas playlists e o que já foi baixado. As músicas ficam na pasta das músicas.</span></div>
		${lib.load_error ? `<div class="aviso err">${icon("circle-x")}<div><b>Esta biblioteca não pôde ser lida</b><p>${esc(lib.load_error)}</p></div></div>` : ""}
		<div class="botoes-linha">
			<button class="btn" data-lib="abrir">${icon("folder-open")}Abrir outra biblioteca…</button>
			<button class="btn" data-lib="salvar">${icon("copy")}Salvar uma cópia em…</button>
			<button class="btn" data-lib="csv">${icon("file-spreadsheet")}Exportar tudo em planilha</button>
		</div>`;
}

const SECOES = { downloads: secaoDownloads, som: secaoSom, conta: secaoConta, avancado: secaoAvancado, aparencia: secaoAparencia, biblioteca: secaoBiblioteca };

function pintar() {
	const s = d.corpo.querySelector("section");
	const rolagem = s.scrollTop;
	s.innerHTML = SECOES[aba]();
	s.setAttribute("aria-label", ABAS.find(([k]) => k === aba)[1]);
	s.querySelectorAll('input[type="range"]').forEach(pintarRegua);
	s.scrollTop = rolagem;
	if (aba === "avancado" && cfg) carregarLixeira();
}

// ---------- Salvar ----------
let timerSalvo;
async function salvar(mudanca) {
	const marca = d?.pe.querySelector("[data-salvo]");
	try {
		cfg = await patch("/settings", mudanca);
		if (!d) return;
		marca.innerHTML = `${icon("check")}Salvo`;
		clearTimeout(timerSalvo);
		timerSalvo = setTimeout(() => { if (marca.isConnected) marca.innerHTML = ""; }, 2000);
		if ("theme" in mudanca) aplicarTema(cfg.theme);
		return true;
	} catch (e) {
		erro(e, "Não deu para salvar o ajuste");
		if (d) pintar();
		return false;
	}
}

function ligarSecao() {
	const s = d.corpo.querySelector("section");
	s.addEventListener("click", async (ev) => {
		const t = ev.target;
		const ch = t.closest(".chave[data-k]");
		if (ch && !ch.disabled) {
			const k = ch.dataset.k;
			const novo = ch.getAttribute("aria-checked") !== "true";
			ch.setAttribute("aria-checked", novo);
			if (await salvar({ [k]: novo }) && k === "eq_enabled") pintar();
			return;
		}
		const sg = t.closest(".seg[data-seg] button");
		if (sg) {
			const k = sg.closest(".seg").dataset.seg;
			sg.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", b === sg));
			if (k === "theme") aplicarTema(sg.dataset.v);
			salvar({ [k]: sg.dataset.v });
			return;
		}
		const bp = t.closest("[data-pasta]");
		if (bp) { escolherCaminho("/dialogs/choose-folder", { purpose: bp.dataset.proposito, start: cfg?.[bp.dataset.pasta] || undefined }, bp.dataset.pasta); return; }
		const ba = t.closest("[data-arquivo]");
		if (ba) { escolherCaminho("/dialogs/choose-file", { purpose: ba.dataset.proposito }, ba.dataset.arquivo); return; }
		const bl = t.closest("[data-limpar]");
		if (bl) { if (await salvar({ [bl.dataset.limpar]: null })) pintar(); return; }
		const be = t.closest("[data-escolha]");
		if (be) { abrirEscolha(be); return; }
		const bc = t.closest("[data-conta-acao]");
		if (bc) { acaoConta(bc.dataset.contaAcao); return; }
		if (t.closest("[data-porta]")) {
			const p = Number(s.querySelector("#aj-porta").value);
			if (!Number.isInteger(p) || p < 1024 || p > 65535) { erro(new Error("Use um número entre 1024 e 65535."), "Porta inválida"); return; }
			salvar({ web_port: p });
			return;
		}
		if (t.closest("[data-log]")) { abrirNoFinder("log"); return; }
		if (t.closest("[data-esvaziar]")) { esvaziarLixeira(); return; }
		const lb = t.closest("[data-lib]");
		if (lb) acaoBiblioteca(lb.dataset.lib);
	});
	s.addEventListener("input", (ev) => {
		const r = ev.target.closest("[data-r]");
		if (!r) return;
		pintarRegua(r);
		const val = Number(r.value);
		const k = r.dataset.r;
		const out = r.parentElement.querySelector("output");
		out.textContent = k === "mp3_quality" ? `${val} de 10` : db(val);
		clearTimeout(r._t);
		r._t = setTimeout(() => salvar({ [k]: r.dataset.inverso ? Number(r.max) - val : val }), 300);
	});
}

async function escolherCaminho(rota, corpo, chave) {
	try {
		const r = await post(rota, corpo);
		if (r?.path && await salvar({ [chave]: r.path })) pintar();
	} catch (e) { erro(e, "Não deu para abrir o seletor"); }
}

function abrirEscolha(botao) {
	const k = botao.dataset.escolha;
	const itens = k === "cookies_browser" ? NAVEGADORES : MP3_MODOS;
	menu(botao, itens.map(([val, rot]) => ({
		rotulo: rot, marcado: cfg?.[k] === val,
		acao: async () => { if (await salvar({ [k]: val })) pintar(); },
	})), { alinhar: "esquerda" });
}

async function acaoConta(qual) {
	const msg = d.corpo.querySelector("[data-conta-msg]");
	try {
		if (qual === "testar") { await post("/account/youtube/test"); msg.textContent = "Testando a sessão do YouTube…"; }
		else if (qual === "sair") {
			const r = await post("/account/youtube/sign-out");
			store.account = { connected: r.connected, use_cookies: r.use_cookies, checked_at: r.checked_at };
			if (cfg) cfg.use_cookies = r.use_cookies;
			pintar();
			aviso({ tom: r.ok === false ? "err" : "ok", titulo: "Sessão do YouTube esquecida", texto: r.message || "" });
		}
		else { await post("/account/youtube/sign-in", { method: qual }); msg.textContent = qual === "popup" ? "Abrimos a janela do Google. Entre na sua conta e volte aqui." : "Lendo a sessão do Firefox…"; }
	} catch (e) { erro(e, "Não deu para falar com o YouTube"); }
}

async function carregarLixeira() {
	const box = d?.corpo.querySelector("[data-lixeira]");
	if (!box) return;
	try {
		const r = await get("/trash");
		if (!box.isConnected) return;
		const mb = (r.bytes || 0) / 1e6;
		box.innerHTML = r.files
			? `<p class="ajuda" style="margin-bottom:8px">${n(r.files)} ${r.files === 1 ? "arquivo trocado" : "arquivos trocados"} por versões novas, ${mb.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB.</p>
				<button class="btn" data-esvaziar>${icon("trash-2")}Mandar para a Lixeira do Mac</button>`
			: `<p class="ajuda">Vazia. Quando uma música é baixada de novo, o arquivo antigo vem para cá.</p>`;
	} catch (e) { box.innerHTML = `<p class="erro-campo">${esc(e.message)}</p>`; }
}

async function esvaziarLixeira() {
	const sim = await confirmar({ titulo: "Esvaziar a lixeira interna", texto: "Os arquivos vão para a Lixeira do Mac. Dá para recuperar por lá.", sim: "Mandar para a Lixeira" });
	if (!sim) return;
	try {
		const r = await post("/trash/empty");
		aviso({ tom: "ok", titulo: "Lixeira esvaziada", texto: `${n(r.moved || 0)} arquivos foram para a Lixeira do Mac.` });
		carregarLixeira();
	} catch (e) { erro(e); }
}

async function acaoBiblioteca(qual) {
	try {
		if (qual === "csv") { exportarPlanilha(null); return; }
		if (qual === "abrir") {
			const r = await post("/dialogs/choose-file", { purpose: "library" });
			if (!r?.path) return;
			aplicarEstado(await post("/library/open", { path: r.path }));
			aviso({ tom: "ok", titulo: "Biblioteca aberta" });
			pintar();
		}
		if (qual === "salvar") {
			// A API não tem seletor de "salvar como" (só o menu Arquivo do app tem): a pessoa escolhe a
			// pasta e a cópia vai com um nome fixo dentro dela.
			const r = await post("/dialogs/choose-folder", { purpose: "output" });
			if (!r?.path) return;
			// A cópia é só uma cópia: o app continua gravando na biblioteca de sempre.
			const caminho = `${r.path.replace(/\/$/, "")}/biblioteca-csvmusic.json`;
			let s;
			try { s = await post("/library/save-as", { path: caminho }); }
			catch (e) {
				if (e.status !== 409 || e.dados?.needs_confirmation !== "overwrite") throw e;
				if (!await confirmar({ titulo: "Substituir o arquivo?", texto: esc(e.message), sim: "Substituir", nao: "Cancelar" })) return;
				s = await post("/library/save-as", { path: caminho, overwrite: true });
			}
			aviso({ tom: "ok", titulo: "Cópia salva", texto: s?.path ? `${s.path}. O CSVMusic continua usando a biblioteca de sempre.` : "" });
		}
	} catch (e) { erro(e); }
}

on("account", (a) => {
	store.account = { ...(store.account || {}), connected: a.connected, use_cookies: a.use_cookies };
	if (!d || aba !== "conta") return;
	const bloco = d.corpo.querySelector("[data-conta]");
	if (bloco) bloco.replaceWith(el(blocoConta()));
	const msg = d.corpo.querySelector("[data-conta-msg]");
	if (msg) msg.textContent = a.message || "";
	if (cfg) { cfg.use_cookies = a.use_cookies; }
});
on("estado", () => { if (d && aba === "biblioteca") pintar(); });
