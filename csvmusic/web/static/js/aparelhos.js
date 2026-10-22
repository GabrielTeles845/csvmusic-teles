// Aparelhos: mandar playlists baixadas para iPod, pendrive ou cartão de memória.
import { get, post, del, enc } from "./api.js";
import { on } from "./store.js";
import { esc, icon, n } from "./util.js";
import { dialogo, erro, aviso, confirmar, sh } from "./ui.js";

let d = null;
let estado = { aparelhos: null, ocupado: false, sel: null, noAparelho: null, marcadas: new Set(), progresso: null };

export function abrirAparelhos() {
	if (d && !d.fechado) return;
	// pedindo: tirar, ejetar ou mandar em andamento; os botões do aparelho ficam desligados até a resposta.
	estado = { aparelhos: null, ocupado: false, sel: null, noAparelho: null, biblioteca: null, marcadas: new Set(), progresso: null, erro: null, pedindo: false };
	d = dialogo({
		titulo: "Aparelhos",
		corpo: `<div data-ap></div>`,
		pe: `<button class="btn" data-a="ejetar" disabled>${icon("arrow-up-from-line")}Ejetar</button><button class="btn pri" data-a="sync" disabled>${icon("refresh-cw")}Mandar para o aparelho</button>`,
		aoFechar: () => { d = null; },
	});
	d.caixa.addEventListener("click", aoClicar);
	pintar();
	procurar();
}

async function procurar() {
	estado.aparelhos = null;
	estado.erro = null;
	pintar();
	try {
		const r = await get("/devices");
		estado.aparelhos = r.devices || [];
		estado.ocupado = !!r.busy;
		if (estado.aparelhos.length && !estado.aparelhos.some((a) => a.id === estado.sel)) escolher(estado.aparelhos[0].id);
		else pintar();
	} catch (e) { estado.erro = e; pintar(); }
}

async function escolher(id) {
	estado.sel = id;
	estado.noAparelho = null;
	estado.biblioteca = null;
	pintar();
	try {
		const r = await get(`/devices/${enc(id)}/playlists`);
		if (estado.sel !== id) return;
		estado.noAparelho = r.playlists || [];
		// library: [{playlist_id, name, state: new|changed|current, ready}]. Só as prontas vão.
		estado.biblioteca = r.library || [];
		estado.marcadas = new Set(estado.biblioteca.filter((p) => p.ready && p.state !== "current").map((p) => p.playlist_id));
	} catch (e) { estado.noAparelho = { erro: e.message }; estado.biblioteca = []; }
	pintar();
}

const ICONES = { ipod_classic: "disc-3", mass_storage: "hard-drive" };
const SITUACAO = { new: "Ainda não está no aparelho", changed: "Mudou desde a última cópia", current: "Já está em dia no aparelho" };

function pintar() {
	if (!d) return;
	const box = d.corpo.querySelector("[data-ap]");
	const ap = estado.aparelhos;
	const sync = d.pe.querySelector('[data-a="sync"]');
	const ej = d.pe.querySelector('[data-a="ejetar"]');
	const livre = () => !!estado.sel && !estado.ocupado && !estado.progresso && !estado.pedindo;
	sync.disabled = !livre() || !estado.marcadas.size;
	ej.disabled = !livre();
	if (estado.erro) {
		box.innerHTML = `<div class="lista-msg" style="padding:12px 0"><h2>Não deu para procurar aparelhos</h2><p>${esc(estado.erro.message)}</p><button class="btn" data-a="procurar">${icon("refresh-cw")}Tentar de novo</button></div>`;
		return;
	}
	let html = `<span class="rot">Conectados</span><div class="lista-simples" style="margin:6px 0 18px">`;
	if (!ap) {
		html += [0, 1].map(() => `<div aria-hidden="true">${sh("18px", "sh-blk")}<span class="cresce"><b>${sh("9em")}</b><small>${sh("13em")}</small></span></div>`).join("");
	} else if (!ap.length) {
		html += `<div>${icon("unplug")}<span class="cresce"><b>Nenhum aparelho conectado</b><small>Ligue o iPod, o pendrive ou o cartão no Mac.</small></span>
			<button class="btn sm" data-a="procurar">Procurar de novo</button></div>`;
	} else {
		html += ap.map((a) => `<button class="item-ap" data-a="aparelho" data-id="${esc(a.id)}" aria-selected="${a.id === estado.sel}">
			${icon(ICONES[a.kind] || "usb")}<span class="cresce"><b>${esc(a.name)}</b><small>${esc(a.description || "")}</small></span>
			${a.id === estado.sel ? icon("check") : ""}</button>`).join("");
	}
	html += `</div>`;
	if (estado.progresso) {
		const p = estado.progresso;
		const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
		html += `<span class="rot">Mandando</span><div class="progresso"><i style="width:${pct}%"></i></div>
			<p class="ajuda">${esc(p.message || "")}${p.total ? ` · ${n(p.done)} de ${n(p.total)}` : ""}</p>`;
	}
	if (estado.sel) {
		const no = estado.noAparelho;
		html += `<span class="rot">Já no aparelho</span><div class="lista-simples" style="margin:6px 0 18px">`;
		if (!no) html += [0, 1, 2].map((i) => `<div aria-hidden="true">${sh("18px", "sh-blk")}<span class="cresce"><b>${sh(["8em", "11em", "7em"][i])}</b><small>${sh("5em")}</small></span>${sh("72px", "sh-blk sh-pill")}</div>`).join("");
		else if (no.erro) html += `<div><span class="cresce erro-campo">${esc(no.erro)}</span></div>`;
		else if (!no.length) html += `<div>${icon("list-music")}<span class="cresce"><b>Nenhuma playlist ainda</b><small>Escolha abaixo o que mandar.</small></span></div>`;
		else html += no.map((p) => `<div>${icon("list-music")}<span class="cresce"><b>${esc(p.name)}</b><small>${n(p.track_count)} músicas</small></span>
			<button class="btn sm" data-a="tirar" data-nome="${esc(p.name)}" ${livre() ? "" : "disabled"}>Tirar</button></div>`).join("");
		html += `</div><span class="rot">Mandar do CSVMusic</span><div class="lista-simples" style="margin-top:6px">`;
		const bib = estado.biblioteca;
		if (!bib) html += [0, 1, 2].map((i) => `<div aria-hidden="true">${sh("18px", "sh-blk")}<span class="cresce"><b>${sh(["9em", "7em", "10em"][i])}</b><small>${sh("12em")}</small></span></div>`).join("");
		else if (!bib.length) html += `<div><span class="cresce"><small>Nenhuma playlist na biblioteca.</small></span></div>`;
		else html += bib.map((p) => `<label class="${p.ready ? "" : "desligada"}"><span class="ck"><input type="checkbox" data-pl="${esc(p.playlist_id)}" ${estado.marcadas.has(p.playlist_id) ? "checked" : ""} ${p.ready ? "" : "disabled"}></span>
			<span class="cresce"><b>${esc(p.name)}</b><small>${esc(p.ready ? SITUACAO[p.state] || "" : "Falta baixar músicas desta playlist")}</small></span></label>`).join("");
		html += `</div><p class="ajuda" style="margin-top:8px">Só vão as playlists com todas as músicas baixadas.</p>`;
	}
	box.innerHTML = html;
	box.querySelectorAll("[data-pl]").forEach((c) => c.addEventListener("change", () => {
		if (c.checked) estado.marcadas.add(c.dataset.pl); else estado.marcadas.delete(c.dataset.pl);
		sync.disabled = !livre() || !estado.marcadas.size;
	}));
}

// Um pedido ao aparelho por vez: desliga os botões até a resposta (o motor também recusa com 409).
async function pedirAoAparelho(fn) {
	if (estado.pedindo) return;
	estado.pedindo = true;
	pintar();
	try { await fn(); }
	finally { estado.pedindo = false; pintar(); }
}

async function aoClicar(ev) {
	const b = ev.target.closest("[data-a]");
	if (!b || b.disabled) return;
	const a = b.dataset.a;
	if (a === "procurar") procurar();
	if (a === "aparelho") escolher(b.dataset.id);
	if (a === "sync") {
		await pedirAoAparelho(async () => {
			try {
				await post(`/devices/${enc(estado.sel)}/sync`, { playlist_ids: [...estado.marcadas] });
				estado.progresso = { done: 0, total: 0, message: "Começando" };
			} catch (e) { erro(e, "Não deu para mandar"); }
		});
	}
	if (a === "tirar") {
		const nome = b.dataset.nome;
		if (!await confirmar({ titulo: "Tirar do aparelho", texto: `“${esc(nome)}” sai do aparelho. As músicas continuam no Mac.`, sim: "Tirar" })) return;
		let tirou = false;
		await pedirAoAparelho(async () => {
			try { await del(`/devices/${enc(estado.sel)}/playlists/${enc(nome)}`); tirou = true; }
			catch (e) { erro(e, "Não deu para tirar"); }
		});
		if (tirou && d) escolher(estado.sel);
	}
	if (a === "ejetar") {
		await pedirAoAparelho(async () => {
			try { await post(`/devices/${enc(estado.sel)}/eject`); }
			catch (e) { erro(e, "Não deu para ejetar"); }
		});
	}
}

// phase: start | sync | done | error | ejected
on("device", (p) => {
	if (p.phase === "ejected") { aviso({ tom: "ok", titulo: "Pode desconectar o aparelho", texto: p.message || "" }); if (d) procurar(); return; }
	if (p.phase === "done" || p.phase === "error") {
		aviso({ tom: p.phase === "done" ? "ok" : "err", titulo: p.phase === "done" ? "Aparelho atualizado" : "A cópia parou", texto: p.message || "" });
		if (!d) return;
		estado.progresso = null;
		if (estado.sel) escolher(estado.sel);
		return;
	}
	if (!d) return;
	estado.progresso = p;
	pintar();
});
