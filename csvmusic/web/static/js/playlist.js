// Tela da playlist: topo tingido, ações, filtros, busca e a lista virtual de músicas.
import { get, patch, post, enc, qs, capaAttrs } from "./api.js";
import { store, on, emit } from "./store.js";
import { esc, icon, el, n, duracao, estado, mosaico, tipoDaPlaylist, debounce, plural } from "./util.js";
import { menu, erro, sh } from "./ui.js";
import { ListaVirtual } from "./lista-virtual.js";
import { tingir } from "./tint.js";
import * as acoes from "./acoes.js";
import { abrirPainel, painelAberto } from "./painel.js";
import { abrirAjustes } from "./ajustes.js";
import { abrirGaveta } from "./lateral.js";

const main = () => document.getElementById("main");

const FILTROS = [
	["all", "Todas", (c) => c.total],
	["missing", "Faltando", (c) => c.missing],
	["review", "Revisar", (c) => c.review],
	["error", "Com erro", (c) => c.error],
	["downloaded", "Baixadas", (c) => c.downloaded],
	["disabled", "Desmarcadas", (c) => c.disabled],
	["not_found", "Não encontradas", (c) => c.not_found],
];

const vista = { id: null, filtro: "all", q: "", lista: null, contagens: null };

// ---------- Pedaços ----------
function topoCelular() {
	return `<div class="topo-m">
		<span class="marca">CSVMusic</span>
		<button class="btn ic" data-m="buscar" aria-label="Buscar música">${icon("search")}</button>
		<button class="btn ic" data-m="playlists" aria-label="Playlists">${icon("list-music")}</button>
		<button class="btn ic" data-m="ajustes" aria-label="Ajustes">${icon("settings")}</button>
	</div>`;
}

function classeTitulo(nome) {
	const t = (nome || "").length;
	return t > 40 ? "muito-longo" : t > 22 ? "longo" : "";
}

function linhaContagens(pl) {
	if (pl.scan_state === "never") return `<span><b>Ainda não analisada</b></span>`;
	const c = pl.counts || {};
	const partes = [`<b>${n(c.downloaded)} de ${n(c.total)} baixadas</b>`];
	if (c.missing) partes.push(`${n(c.missing)} faltando`);
	if (c.review) partes.push(`${n(c.review)} para revisar`);
	if (c.error) partes.push(`${n(c.error)} com erro`);
	if (c.not_found) partes.push(`${n(c.not_found)} não ${c.not_found === 1 ? "encontrada" : "encontradas"}`);
	return partes.map((p, i) => `<span>${p}${i < partes.length - 1 ? `<i class="sep"> ·</i>` : ""}</span>`).join(" ");
}

function avisosDaPlaylist(pl) {
	const out = [];
	if (pl.access_error === "private") {
		out.push(`<div class="aviso err">${icon("lock")}<div><b>Particular no Spotify</b><p>${esc(pl.access_error_message
			|| "O Spotify só mostra esta playlist para quem está logado. Torne a playlist pública no Spotify e analise de novo.")}</p></div></div>`);
	} else if (pl.access_error) {
		out.push(`<div class="aviso err">${icon("circle-x")}<div><b>Sem acesso a esta playlist</b><p>${esc(pl.access_error_message || "Confira se o link ainda funciona e analise de novo.")}</p></div></div>`);
	}
	if (pl.scan_state === "incomplete") {
		const lidas = pl.counts?.total, total = pl.reported_total;
		const txt = pl.scan_warning || (total ? `Foram lidas ${n(lidas)} de ${n(total)} músicas. Analise de novo para tentar ler o resto.` : "A última análise parou antes do fim. Analise de novo para tentar ler o resto.");
		out.push(`<div class="aviso rev">${icon("triangle-alert")}<div><b>A análise não leu tudo</b><p>${esc(txt)}</p></div></div>`);
	}
	return out.length ? `<div class="avisos">${out.join("")}</div>` : "";
}

function botoesAcao(pl) {
	const job = store.job || {};
	const ocupado = !!job.kind;
	const analisando = job.kind === "scan" && job.playlist_id === pl.id;
	const baixando = job.kind === "download" && (job.playlist_ids || []).includes(pl.id);
	const faltam = pl.counts?.missing || 0;
	let pri;
	if (pl.scan_state === "never") {
		pri = `<button class="btn pri" data-a="analisar" ${analisando ? "disabled" : ""}>${icon("refresh-cw")}${analisando ? "Analisando" : "Analisar agora"}</button>`;
	} else if (baixando) {
		pri = `<button class="btn pri" disabled>${icon("download")}Baixando</button>`;
	} else if (faltam) {
		pri = `<button class="btn pri" data-a="baixar" ${ocupado && job.kind === "download" ? "disabled" : ""}>${icon("download")}${faltam === 1 ? "Baixar a que falta" : `Baixar as ${n(faltam)} que faltam`}</button>`;
	} else {
		pri = `<button class="btn pri" disabled>${icon("check")}Nada faltando</button>`;
	}
	const sec = pl.scan_state === "never" ? "" :
		`<button class="btn" data-a="analisar" ${analisando ? "disabled" : ""}>${icon("refresh-cw")}${analisando ? "Analisando" : "Analisar de novo"}</button>`;
	return `${pri}${sec}<button class="btn ic" data-a="mais" aria-label="Mais ações da playlist" aria-haspopup="menu">${icon("ellipsis")}</button>`;
}

function chips(c) {
	return FILTROS.map(([f, rotulo, conta]) => {
		const q = c ? conta(c) || 0 : null;
		if (c && f !== "all" && !q && vista.filtro !== f) return "";
		const num = q === null ? sh("2.2em") : n(q);
		return `<button class="chip${vista.filtro === f ? " on" : ""}" data-f="${f}" role="tab" aria-selected="${vista.filtro === f}">${rotulo}<span>${num}</span></button>`;
	}).join("");
}

// Busca e "marcar todas" ficam na linha das ações, à direita (no celular, linha própria).
function buscaHtml() {
	return `<div class="fil-dir">
		<label class="busca-lista">${icon("search", "i i-16")}<span class="sr">Buscar nesta playlist</span>
			<input type="search" data-q placeholder="Buscar nesta playlist" value="${esc(vista.q)}" autocomplete="off">
		</label>
		<button class="btn sm ic" data-a="lista" aria-label="Marcar ou desmarcar todas" aria-haspopup="menu">${icon("square-check-big")}</button>
	</div>`;
}

function filtrosHtml(c) {
	return `<div class="fil" role="tablist" aria-label="Filtrar músicas">${chips(c)}</div>`;
}

const CABECALHO = `<div class="cab"><span><span class="sr">Baixar</span></span><span class="n">#</span><span></span><span>Música</span><span>Álbum</span><span>Duração</span><span>Situação</span></div>`;

// ---------- Linhas ----------
function linha(t, pos) {
	const e = estado(t, store.job);
	const rev = t.state === "review";
	const sel = painelAberto()?.playlistId === vista.id && painelAberto()?.index === t.index;
	const titulo = t.title || "Sem título";
	const botoesRev = rev ? `<span class="rev-acoes"><button class="btn sm" data-a="aceitar" data-k="ac">Aceitar</button><button class="btn sm" data-a="trocar" data-k="tr">Trocar</button></span>` : "";
	const revM = rev ? `<span class="rev-m"><button class="btn sm ic" data-a="aceitar" data-k="acm" aria-label="Aceitar a versão encontrada">${icon("check")}</button><button class="btn sm ic" data-a="trocar" data-k="trm" aria-label="Trocar a versão">${icon("replace")}</button></span>` : "";
	return el(`<div class="row tom-${e.tom}${t.enabled === false ? " off" : ""}${pos % 2 ? " par" : ""}${sel ? " sel" : ""}" data-i="${t.index}" tabindex="0"
		aria-label="${esc(`${titulo}, ${t.artists || ""}, ${e.texto}`)}">
		<label class="ck" data-k="ckl"><input type="checkbox" data-k="ck" ${t.enabled !== false ? "checked" : ""} aria-label="Baixar ${esc(titulo)}"></label>
		<span class="n">${n(t.position ?? pos + 1)}</span>
		${t.cover_url ? `<img class="cv" ${capaAttrs(t.cover_url)} alt="" loading="lazy" decoding="async">` : `<span class="cv"></span>`}
		<span class="t"><b>${esc(titulo)}</b><small>${esc(t.artists || "")}</small><em class="stm">${icon(e.icone)}${esc(e.texto)}</em></span>
		<span class="al">${esc(t.album || "")}</span>
		<span class="d">${duracao(t.duration_ms)}</span>
		<span class="st">${icon(e.icone)}<span>${esc(e.texto)}</span>${botoesRev}</span>
		${revM}
	</div>`);
}

const LARG = ["72%", "58%", "84%", "64%", "76%", "52%", "68%", "80%"];
function linhaBrilho(pos) {
	const w = LARG[pos % LARG.length], w2 = LARG[(pos + 3) % LARG.length];
	return el(`<div class="row${pos % 2 ? " par" : ""}" aria-hidden="true">
		<span class="ck">${sh("18px", "sh-blk")}</span>
		<span class="n">${sh("1.6em")}</span>
		${sh("40px", "sh-blk cv")}
		<span class="t"><b>${sh(w)}</b><small>${sh(`calc(${w2} * .6)`)}</small><em class="stm">${sh("64px")}</em></span>
		<span class="al">${sh(w2)}</span>
		<span class="d">${sh("2.4em")}</span>
		<span class="st">${sh("92px", "sh-txt sh-pill")}</span>
	</div>`);
}

function msgLista(titulo, texto, botao) {
	const box = el(`<div class="lista-msg"><h2>${esc(titulo)}</h2>${texto ? `<p>${esc(texto)}</p>` : ""}</div>`);
	if (botao) {
		const b = el(`<button class="btn ${botao.pri ? "pri" : ""}">${botao.icone ? icon(botao.icone) : ""}${esc(botao.rotulo)}</button>`);
		b.onclick = botao.acao;
		box.append(b);
	}
	return box;
}

function listaVazia() {
	const pl = store.playlists.get(vista.id);
	if (vista.q) return msgLista(`Nada encontrado para “${vista.q}”`, "Confira a grafia ou procure pelo nome do artista.", { rotulo: "Limpar a busca", icone: "x", acao: () => limparBusca() });
	if (vista.filtro !== "all") return msgLista("Nenhuma música neste filtro", "", { rotulo: "Ver todas", acao: () => trocarFiltro("all") });
	if (pl?.access_error === "private") return msgLista("O Spotify não mostrou as músicas", "Torne a playlist pública no Spotify e toque em Analisar de novo.", { rotulo: "Analisar de novo", icone: "refresh-cw", pri: true, acao: () => acoes.analisar({ playlist_ids: [pl.id] }) });
	if (pl?.scan_state === "never") return msgLista("As músicas aparecem depois da análise", "A análise lê a playlist e procura cada música no YouTube Music. Nada é baixado ainda.", { rotulo: "Analisar agora", icone: "refresh-cw", pri: true, acao: () => acoes.analisar({ playlist_ids: [pl.id] }) });
	return msgLista("Esta playlist está vazia", "Quando ela tiver músicas, analise de novo.");
}

function listaFalha(e, tentar) {
	return msgLista("Não deu para carregar as músicas", e?.message || "", { rotulo: "Tentar de novo", icone: "refresh-cw", acao: tentar });
}

// ---------- Montagem ----------
export function mostrarCarregando() {
	vista.lista?.destruir();
	vista.lista = null;
	const m = main();
	m.className = "com-topo";
	m.innerHTML = `${topoCelular()}
		<div class="hero" aria-busy="true">
			<div class="pm">${sh("100%", "sh-blk")}</div>
			<div class="hero-txt"><small class="tipo">${sh("9em")}</small><h1>${sh("min(520px, 100%)", "sh-txt")}</h1><p class="cont">${sh("18em")}</p></div>
		</div>
		<div class="acoes"><button class="btn pri" disabled>${icon("download")}Baixar o que falta</button><button class="btn" disabled>${icon("refresh-cw")}Analisar de novo</button><button class="btn ic" disabled aria-label="Mais ações da playlist">${icon("ellipsis")}</button>${buscaHtml()}</div>
		${filtrosHtml(null)}
		<div class="lista">${CABECALHO}<div class="vbody"></div></div>`;
	m.querySelector(".hero .pm").style.overflow = "hidden";
	m.querySelector(".hero .pm .sh").style.height = "100%";
	const corpo = m.querySelector(".vbody");
	corpo.style.height = 8 * (parseFloat(getComputedStyle(corpo).getPropertyValue("--rh")) || 52) + "px";
	for (let i = 0; i < 8; i++) { const r = linhaBrilho(i); r.style.top = `calc(var(--rh) * ${i})`; corpo.append(r); }
	ligarTopoCelular(m);
}

export function mostrarPlaylist(id, { manterFiltro = false } = {}) {
	const pl = store.playlists.get(id);
	if (!pl) return;
	if (!manterFiltro || vista.id !== id) { vista.filtro = "all"; vista.q = ""; }
	vista.id = id;
	vista.contagens = pl.counts || null;
	vista.lista?.destruir();
	tingir(pl);
	const m = main();
	m.className = "com-topo";
	m.scrollTop = 0;
	m.innerHTML = `${topoCelular()}
		<div class="hero">${mosaico(pl)}
			<div class="hero-txt"><small class="tipo">${esc(tipoDaPlaylist(pl))}</small>
				<h1 class="${classeTitulo(pl.name)}"><button class="titulo-ed" data-a="renomear" aria-label="Renomear a playlist ${esc(pl.name)}">${esc(pl.name)}</button></h1>
				<p class="cont">${linhaContagens(pl)}</p>
				${avisosDaPlaylist(pl)}
			</div>
		</div>
		<div class="acoes">${botoesAcao(pl)}${buscaHtml()}</div>
		${filtrosHtml(vista.contagens)}
		<div class="lista">${CABECALHO}<div class="vbody"></div></div>`;
	ligarTopoCelular(m);
	ligarEventos(m, pl);
	vista.lista = new ListaVirtual({
		rolagem: m,
		caixa: m.querySelector(".vbody"),
		buscar: (offset, limit) => get(`/playlists/${enc(id)}/tracks` + qs({ filter: vista.filtro, q: vista.q, offset, limit })),
		linha, brilho: linhaBrilho, vazio: listaVazia, falha: listaFalha,
		aoReceber: (r) => { if (r.counts) { vista.contagens = r.counts; pintarChips(); } },
	});
	vista.lista.iniciar();
}

function ligarTopoCelular(m) {
	m.querySelector('[data-m="buscar"]')?.addEventListener("click", () => {
		const q = m.querySelector("[data-q]");
		q?.scrollIntoView({ block: "center" });
		q?.focus();
	});
	m.querySelector('[data-m="playlists"]')?.addEventListener("click", abrirGaveta);
	m.querySelector('[data-m="ajustes"]')?.addEventListener("click", () => abrirAjustes());
}

function ligarEventos(m, pl) {
	m.querySelector(".acoes").addEventListener("click", (ev) => {
		const b = ev.target.closest("[data-a]");
		if (!b) return;
		const p = store.playlists.get(vista.id);
		if (b.dataset.a === "baixar") acoes.baixarFaltando([p.id]);
		if (b.dataset.a === "analisar") acoes.analisar({ playlist_ids: [p.id] });
		if (b.dataset.a === "mais") menuPlaylist(b, p);
		if (b.dataset.a === "lista") menuLista(b);
	});
	m.querySelector(".hero").addEventListener("click", (ev) => {
		if (ev.target.closest('[data-a="renomear"]')) editarTitulo();
	});
	ligarFiltros(m);
	const corpo = m.querySelector(".vbody");
	corpo.addEventListener("click", aoClicarLinha);
	corpo.addEventListener("keydown", (ev) => {
		if ((ev.key === "Enter" || ev.key === " ") && ev.target.classList.contains("row")) {
			ev.preventDefault();
			abrirDaLinha(ev.target);
		}
		if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
			const row = ev.target.closest(".row");
			if (!row) return;
			ev.preventDefault();
			const top = parseFloat(row.style.top) + (ev.key === "ArrowDown" ? 1 : -1) * vista.lista.alturaLinha();
			const prox = [...corpo.children].find((r) => parseFloat(r.style.top) === top && r.dataset.i);
			prox?.focus();
			prox?.scrollIntoView({ block: "nearest" });
		}
	});
}

function ligarFiltros(m) {
	const fil = m.querySelector(".fil");
	fil.addEventListener("click", (ev) => {
		const c = ev.target.closest("[data-f]");
		if (c) trocarFiltro(c.dataset.f);
	});
	const q = m.querySelector("[data-q]");
	const buscar = debounce(() => { vista.q = q.value.trim(); vista.lista?.iniciar(); }, 250);
	q.addEventListener("input", buscar);
	q.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && q.value) { ev.stopPropagation(); limparBusca(); } });
}

function limparBusca() {
	const q = main().querySelector("[data-q]");
	if (q) q.value = "";
	vista.q = "";
	vista.lista?.iniciar();
}

function trocarFiltro(f) {
	if (vista.filtro === f) return;
	vista.filtro = f;
	pintarChips();
	main().querySelector(`[data-f="${f}"]`)?.focus();
	vista.lista?.iniciar();
}

function pintarChips() {
	const fil = main().querySelector(".fil");
	if (!fil) return;
	fil.innerHTML = chips(vista.contagens);
}

function aoClicarLinha(ev) {
	const row = ev.target.closest(".row");
	if (!row || !row.dataset.i) return;
	const indice = Number(row.dataset.i);
	const t = vista.lista.porIndice(indice);
	if (!t) return;
	const cb = ev.target.closest('input[type="checkbox"]');
	if (cb) { marcar(t, cb.checked); return; }
	if (ev.target.closest(".ck")) return;
	const b = ev.target.closest("[data-a]");
	if (b?.dataset.a === "aceitar") { aceitar(t); return; }
	if (b?.dataset.a === "trocar") { abrirPainel(vista.id, t, { secao: "versao" }); return; }
	abrirDaLinha(row);
}

function abrirDaLinha(row) {
	const t = vista.lista.porIndice(Number(row.dataset.i));
	if (t) abrirPainel(vista.id, t);
}

async function marcar(t, ligado) {
	try {
		const novo = await patch(`/playlists/${enc(vista.id)}/tracks/${t.index}`, { enabled: ligado });
		emit("track", { playlist_id: vista.id, track: novo });
	} catch (e) {
		erro(e, "Não deu para mudar a música");
		vista.lista.atualizar(t);
	}
}

export async function aceitar(t, playlistId = vista.id) {
	try {
		const novo = await post(`/playlists/${enc(playlistId)}/tracks/${t.index}/accept`);
		emit("track", { playlist_id: playlistId, track: novo });
	} catch (e) { erro(e, "Não deu para aceitar"); }
}

function editarTitulo() {
	const pl = store.playlists.get(vista.id);
	const h1 = main().querySelector(".hero h1");
	if (!h1 || h1.querySelector("input")) return;
	const inp = el(`<input class="titulo-in" value="${esc(pl.name)}" aria-label="Nome da playlist" maxlength="200">`);
	h1.replaceChildren(inp);
	inp.focus();
	inp.select();
	let feito = false;
	const terminar = (salvar) => {
		if (feito) return;
		feito = true;
		const nome = inp.value;
		h1.innerHTML = `<button class="titulo-ed" data-a="renomear" aria-label="Renomear a playlist">${esc(salvar && nome.trim() ? nome.trim() : pl.name)}</button>`;
		h1.className = classeTitulo(salvar ? nome : pl.name);
		h1.querySelector("button").focus();
		if (salvar) acoes.renomear(pl, nome);
	};
	inp.addEventListener("keydown", (ev) => {
		if (ev.key === "Enter") terminar(true);
		if (ev.key === "Escape") { ev.stopPropagation(); terminar(false); }
	});
	inp.addEventListener("blur", () => terminar(true));
}

function menuPlaylist(botao, pl) {
	menu(botao, [
		{ rotulo: "Renomear", icone: "pencil", acao: editarTitulo },
		{ rotulo: "Abrir a pasta no Finder", icone: "folder-open", acao: () => acoes.abrirNoFinder("playlist", { playlist_id: pl.id }) },
		{ rotulo: "Exportar planilha", icone: "file-spreadsheet", acao: () => acoes.exportarPlanilha(pl) },
		"-",
		{ rotulo: "Remover playlist…", icone: "trash-2", perigo: true, acao: () => acoes.remover(pl) },
	]);
}

function menuLista(botao) {
	const pl = store.playlists.get(vista.id);
	menu(botao, [
		{ rotulo: "Marcar todas", icone: "square-check-big", acao: () => acoes.marcarTodas(pl, true) },
		{ rotulo: "Desmarcar todas", icone: "square", acao: () => acoes.marcarTodas(pl, false) },
	]);
}

// ---------- Atualizações vindas do motor ----------
export function atualizarResumo(pl) {
	if (pl.id !== vista.id) return;
	const m = main();
	const hero = m.querySelector(".hero");
	if (!hero || hero.getAttribute("aria-busy")) return;
	const capaVelha = hero.querySelector(".pm");
	const capaNova = el(mosaico(pl));
	if (capaVelha.dataset.mosaico !== capaNova.dataset.mosaico) { capaVelha.replaceWith(capaNova); tingir(pl); }
	hero.querySelector(".tipo").textContent = tipoDaPlaylist(pl);
	const h1 = hero.querySelector("h1");
	if (!h1.querySelector("input")) {
		h1.className = classeTitulo(pl.name);
		h1.querySelector(".titulo-ed").textContent = pl.name;
	}
	hero.querySelector(".cont").innerHTML = linhaContagens(pl);
	hero.querySelector(".avisos")?.remove();
	hero.querySelector(".cont").insertAdjacentHTML("afterend", avisosDaPlaylist(pl));
	pintarAcoes();
	vista.contagens = pl.counts || vista.contagens;
	pintarChips();
	const eraNunca = vista.lista && vista.lista.total === 0 && pl.scan_state !== "never";
	if (eraNunca) vista.lista.iniciar();
}

function pintarAcoes() {
	const pl = store.playlists.get(vista.id);
	const a = main().querySelector(".acoes");
	if (!pl || !a || main().querySelector(".hero[aria-busy]")) return;
	const foco = document.activeElement && a.contains(document.activeElement) ? document.activeElement.dataset.a : null;
	a.querySelectorAll(":scope > .btn").forEach((b) => b.remove());
	a.insertAdjacentHTML("afterbegin", botoesAcao(pl));
	if (foco) a.querySelector(`[data-a="${foco}"]`)?.focus();
}

on("track", ({ playlist_id, track }) => {
	if (playlist_id !== vista.id || !vista.lista) return;
	vista.lista.atualizar(track);
});
on("job", () => {
	pintarAcoes();
	const job = store.job;
	if (vista.lista && job?.kind === "download" && job.current?.playlist_id === vista.id) {
		vista.lista.redesenharVisiveis((t) => t.index === job.current.index || ["downloading", "matching", "tagging"].includes(t.state));
	}
});
on("recarregar-lista", () => vista.lista?.iniciar());
on("painel", () => vista.lista?.redesenharVisiveis((t) => true));

export const vistaAtual = () => vista;
export const destruirLista = () => { vista.lista?.destruir(); vista.lista = null; vista.id = null; };
