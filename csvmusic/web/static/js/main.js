// Início da tela: tema, estado, eventos do servidor, troca de playlist e atalhos.
import { get, eventos } from "./api.js";
import { store, on, emit, aplicarEstado } from "./store.js";
import { esc, icon, n } from "./util.js";
import { aviso, fecharTopo } from "./ui.js";
import { aplicarTema } from "./tema.js";
import { pintarLateral } from "./lateral.js";
import { mostrarCarregando, mostrarPlaylist, atualizarResumo, destruirLista } from "./playlist.js";
import { mostrarVazio, mostrarErroGeral } from "./vazio.js";
import { pintarBarra, ligarBarra } from "./barra.js";
import { fecharPainel } from "./painel.js";
import { abrirAdicionar } from "./adicionar.js";
import { abrirAjustes } from "./ajustes.js";
import { primeiraVez, abrirAjuda } from "./ajuda.js";

let tema = "system";
try { tema = localStorage.getItem("csvmusic-tema") || "system"; } catch { /* sem armazenamento */ }
aplicarTema(tema);

// ---------- Escolher a playlist ----------
function idDaUrl() {
	const m = /^#\/p\/(.+)$/.exec(location.hash);
	return m ? decodeURIComponent(m[1]) : null;
}

function guardada() {
	try { return localStorage.getItem("csvmusic-playlist"); } catch { return null; }
}

function rota() {
	if (!store.carregado) return;
	if (!store.ordem.length) {
		store.selecionada = null;
		destruirLista();
		fecharPainel(false);
		mostrarVazio();
		emit("selecao");
		return;
	}
	let id = idDaUrl();
	if (!id || !store.playlists.has(id)) id = store.playlists.has(guardada()) ? guardada() : store.ordem[0];
	selecionar(id);
}

function selecionar(id) {
	const mesma = store.selecionada === id && document.querySelector("#main .hero:not([aria-busy])");
	store.selecionada = id;
	try { localStorage.setItem("csvmusic-playlist", id); } catch { /* sem armazenamento */ }
	const hash = `#/p/${encodeURIComponent(id)}`;
	if (location.hash !== hash) history.replaceState(null, "", hash);
	emit("selecao");
	if (mesma) return;
	fecharPainel(false);
	mostrarPlaylist(id);
}

addEventListener("hashchange", () => {
	const id = idDaUrl();
	if (id && store.playlists.has(id)) selecionar(id);
});

// ---------- Carregar ----------
async function carregar() {
	try {
		aplicarEstado(await get("/state"));
	} catch (e) {
		store.erro = e;
		pintarLateral();
		mostrarErroGeral(e, () => { store.erro = null; pintarLateral(); mostrarCarregando(); carregar(); });
		return;
	}
	rota();
	avisarErroDaBiblioteca();
	if (store.firstRun) await primeiraVez();
}

// library.load_error: o library.json não pôde ser lido; o app abriu vazio e não grava.
function avisarErroDaBiblioteca() {
	const erro = store.library?.load_error;
	if (!erro) return;
	aviso({ tom: "err", titulo: "A biblioteca não pôde ser lida", texto: `${erro} Nada será gravado até ela abrir de novo.`, id: "load-error",
		acoes: [{ rotulo: "Abrir outra biblioteca", acao: () => abrirAjustes("biblioteca") }] });
}

async function recarregarEstado() {
	try {
		aplicarEstado(await get("/state"));
		avisarErroDaBiblioteca();
		if (store.selecionada && store.playlists.has(store.selecionada)) {
			atualizarResumo(store.playlists.get(store.selecionada));
			emit("recarregar-lista");
		} else rota();
	} catch { /* o aviso de conexão já está na tela */ }
}

// ---------- Eventos do motor ----------
function listaAnalise(resultados) {
	const tom = { ok: "ok", incomplete: "rev", private: "err", error: "err" };
	const ic = { ok: "check", incomplete: "triangle-alert", private: "lock", error: "circle-x" };
	return resultados.map((r) => {
		let txt;
		if (r.status === "ok") {
			txt = `${n(r.captured)} músicas lidas`;
			const d = r.diff;
			if (d && (d.added || d.removed)) txt += [d.added ? `, ${n(d.added)} ${d.added === 1 ? "nova" : "novas"}` : "", d.removed ? `, ${n(d.removed)} ${d.removed === 1 ? "saiu" : "saíram"}` : ""].join("");
		}
		else if (r.status === "incomplete") txt = r.reported_total ? `Leu ${n(r.captured)} de ${n(r.reported_total)}` : `Leu ${n(r.captured)}`;
		else if (r.status === "private") txt = "Particular no Spotify";
		else txt = "Não deu para ler";
		if (r.message && r.status !== "ok") txt += `. ${r.message}`;
		return `<li class="${tom[r.status] || "err"}">${icon(ic[r.status] || "circle-x")}<span>${esc(r.name)}<small>${esc(txt)}</small></span></li>`;
	}).join("");
}

let avisoConexao = null;
let jaConectou = false;
eventos({
	playlist: (pl) => {
		store.playlists.set(pl.id, pl);
		if (!store.ordem.includes(pl.id)) store.ordem.push(pl.id);
		emit("playlist", pl);
		atualizarResumo(pl);
	},
	playlists: () => recarregarEstado(),
	track: (d) => emit("track", d),
	// Nova análise: a ordem das músicas pode ter mudado e os índices que a tela tem não valem mais.
	tracks_changed: (d) => emit("tracks_changed", d),
	job: (j) => { store.job = j || { kind: null }; emit("job"); },
	scan_done: (d) => {
		const r = d.results || [];
		const ruim = r.some((x) => x.status !== "ok");
		aviso({ tom: ruim ? "rev" : "ok", titulo: "Análise terminada", lista: listaAnalise(r), id: "scan-done" });
	},
	download_done: (d) => {
		const partes = [];
		if (d.done) partes.push(`${n(d.done)} ${d.done === 1 ? "baixada" : "baixadas"}`);
		if (d.skipped) partes.push(`${n(d.skipped)} ${d.skipped === 1 ? "pulada" : "puladas"}`);
		if (d.failed) partes.push(`${n(d.failed)} com erro`);
		aviso({
			tom: d.failed || d.age_restricted ? "rev" : "ok",
			titulo: d.stopped ? "Download parado" : "Download terminado",
			texto: d.message || partes.join(" · "),
			id: "download-done",
		});
		if (d.age_restricted) { store.idade = { quantas: d.age_restricted, acao: d.age_action || null }; emit("idade"); }
	},
	log: (e) => emit("log", e),
	warning: (w) => aviso({ tom: "rev", titulo: "Atenção", texto: w.message, tempo: 12000 }),
	account: (a) => {
		emit("account", a);
		aviso({ tom: a.ok ? "ok" : "err", titulo: a.ok ? "Sessão do YouTube ligada" : "A sessão do YouTube não funcionou", texto: a.message || "" });
	},
	age_retry_ready: (d) => { store.idade = { pronto: d.targets }; emit("idade"); },
	device: (d) => emit("device", d),
	library: () => { recarregarEstado(); aviso({ tom: "info", titulo: "Biblioteca trocada", texto: "A lista foi atualizada." }); },
	// Menu nativo do Mac (CSVMusic › Sobre, Ajustes; Arquivo › Adicionar playlist).
	menu: (m) => {
		if (m.action === "about") abrirAjuda("sobre");
		if (m.action === "settings") abrirAjustes();
		if (m.action === "add_playlist") abrirAdicionar();
	},
}, (ok) => {
	store.conectado = ok;
	if (!ok && !avisoConexao && jaConectou) {
		avisoConexao = aviso({ tom: "err", titulo: "Sem conexão com o CSVMusic", texto: "Tentando de novo. Se o app foi fechado, abra de novo.", acoes: [{ rotulo: "Recarregar a página", acao: () => location.reload() }] });
	}
	if (ok) {
		if (avisoConexao) { avisoConexao(); avisoConexao = null; recarregarEstado(); }
		jaConectou = true;
	}
});

on("adicionadas", (ids) => {
	recarregarEstado().then(() => { if (ids[0] && store.playlists.has(ids[0])) selecionar(ids[0]); });
});
on("removida", () => { if (!store.playlists.has(store.selecionada)) { store.selecionada = null; rota(); } });

// ---------- Atalhos ----------
addEventListener("keydown", (ev) => {
	const cmd = ev.metaKey || ev.ctrlKey;
	if (cmd && !ev.shiftKey && !ev.altKey && ev.key.toLowerCase() === "n") { ev.preventDefault(); abrirAdicionar(); return; }
	if (cmd && ev.key === ",") { ev.preventDefault(); abrirAjustes(); return; }
	if (ev.key === "Escape" && fecharTopo()) ev.preventDefault();
});

// ---------- Começo ----------
ligarBarra();
pintarLateral();
pintarBarra();
mostrarCarregando();
carregar();
