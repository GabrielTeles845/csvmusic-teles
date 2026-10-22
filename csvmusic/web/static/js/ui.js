// Componentes comuns: diálogo, menu "…", avisos, interruptor, escolha segmentada, brilho.
import { esc, icon, el } from "./util.js";

// ---------- Pilha do Esc ----------
// Quem abre algo por cima (menu, diálogo, painel) empilha quem fecha. Esc fecha o de cima.
const pilha = [];
export function empilhar(fechar) {
	pilha.push(fechar);
	return () => { const i = pilha.lastIndexOf(fechar); if (i >= 0) pilha.splice(i, 1); };
}
export function fecharTopo() {
	const f = pilha[pilha.length - 1];
	if (f) { f(); return true; }
	return false;
}
export const algoAberto = () => pilha.length > 0;

const FOCAVEL = 'button:not(:disabled), [href], input:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

function prenderFoco(caixa, ev) {
	if (ev.key !== "Tab") return;
	const itens = [...caixa.querySelectorAll(FOCAVEL)].filter((x) => x.offsetParent !== null);
	if (!itens.length) return;
	const primeiro = itens[0], ultimo = itens[itens.length - 1];
	if (ev.shiftKey && document.activeElement === primeiro) { ev.preventDefault(); ultimo.focus(); }
	else if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primeiro.focus(); }
}

// ---------- Diálogo ----------
export function dialogo({ titulo, corpo = "", pe = "", largo = false, aoFechar, rotulo }) {
	const voltarFoco = document.activeElement;
	const veu = el(`<div class="veu"></div>`);
	const caixa = el(`<div class="dlg${largo ? " largo" : ""}" role="dialog" aria-modal="true" aria-label="${esc(rotulo || titulo)}">
		<div class="dlg-cab"><h2>${esc(titulo)}</h2><button class="btn ic limpo" data-fechar aria-label="Fechar">${icon("x")}</button></div>
		<div class="dlg-corpo"></div>
		${pe !== null ? `<div class="dlg-pe"></div>` : ""}
	</div>`);
	const corpoEl = caixa.querySelector(".dlg-corpo");
	const peEl = caixa.querySelector(".dlg-pe");
	if (typeof corpo === "string") corpoEl.innerHTML = corpo; else corpoEl.append(corpo);
	if (peEl) { if (typeof pe === "string") peEl.innerHTML = pe; else peEl.append(pe); if (!pe) peEl.remove(); }
	let fechado = false;
	const tirar = empilhar(() => fechar());
	function fechar() {
		if (fechado) return;
		fechado = true;
		tirar();
		veu.remove();
		caixa.remove();
		aoFechar?.();
		if (voltarFoco && document.contains(voltarFoco)) voltarFoco.focus();
	}
	veu.addEventListener("click", fechar);
	caixa.querySelector("[data-fechar]").addEventListener("click", fechar);
	caixa.addEventListener("keydown", (ev) => prenderFoco(caixa, ev));
	document.body.append(veu, caixa);
	requestAnimationFrame(() => {
		const alvo = caixa.querySelector("[autofocus]") || caixa.querySelector(".dlg-corpo " + FOCAVEL) || caixa.querySelector(FOCAVEL);
		alvo?.focus();
	});
	return { caixa, corpo: corpoEl, pe: peEl, fechar, get fechado() { return fechado; } };
}

// Pergunta com duas saídas. Devolve a promessa da escolha (true/false).
export function confirmar({ titulo, texto, sim, nao = "Cancelar", perigo = false }) {
	return new Promise((resolve) => {
		let resposta = false;
		const d = dialogo({
			titulo,
			corpo: `<p>${texto}</p>`,
			pe: `<button class="btn" data-nao>${esc(nao)}</button><button class="btn ${perigo ? "perigo" : "pri"}" data-sim autofocus>${esc(sim)}</button>`,
			aoFechar: () => resolve(resposta),
		});
		d.pe.querySelector("[data-nao]").onclick = () => d.fechar();
		d.pe.querySelector("[data-sim]").onclick = () => { resposta = true; d.fechar(); };
	});
}

// ---------- Menu "…" ----------
// itens: [{rotulo, icone, acao, perigo, desligado, marcado}] ou "-" para separar.
let menuAberto = null;
export function menu(botao, itens, { alinhar } = {}) {
	if (menuAberto) { const era = menuAberto.botao; menuAberto.fechar(); if (era === botao) return; }
	const caixa = el(`<div class="menu" role="menu"></div>`);
	for (const it of itens) {
		if (it === "-") { caixa.append(el("<hr>")); continue; }
		const b = el(`<button role="menuitem" class="${it.perigo ? "perigo" : ""}" ${it.desligado ? "disabled" : ""}>
			${it.icone ? icon(it.icone) : ""}<span>${esc(it.rotulo)}</span>${it.marcado ? icon("check", "i marca-ok") : ""}</button>`);
		b.addEventListener("click", () => { fechar(); it.acao?.(); });
		caixa.append(b);
	}
	document.body.append(caixa);
	const r = botao.getBoundingClientRect();
	const w = caixa.offsetWidth, h = caixa.offsetHeight;
	// Encosta na borda do botão: a direita do menu na direita do botão quando ele está na metade direita.
	const lado = alinhar || (r.left + r.width / 2 > innerWidth / 2 ? "direita" : "esquerda");
	let left = lado === "direita" ? r.right - w : r.left;
	left = Math.max(16, Math.min(left, innerWidth - w - 16));
	let top = r.bottom + 6;
	if (top + h > innerHeight - 8) top = Math.max(8, r.top - h - 6);
	caixa.style.left = left + "px";
	caixa.style.top = top + "px";
	botao.setAttribute("aria-expanded", "true");
	const tirar = empilhar(() => fechar());
	function fechar() {
		if (!caixa.isConnected) return;
		tirar();
		caixa.remove();
		botao.setAttribute("aria-expanded", "false");
		document.removeEventListener("pointerdown", fora, true);
		menuAberto = null;
	}
	function fora(ev) { if (!caixa.contains(ev.target) && !botao.contains(ev.target)) fechar(); }
	document.addEventListener("pointerdown", fora, true);
	caixa.addEventListener("keydown", (ev) => {
		const bs = [...caixa.querySelectorAll("button:not(:disabled)")];
		const i = bs.indexOf(document.activeElement);
		if (ev.key === "ArrowDown") { ev.preventDefault(); bs[(i + 1) % bs.length]?.focus(); }
		if (ev.key === "ArrowUp") { ev.preventDefault(); bs[(i - 1 + bs.length) % bs.length]?.focus(); }
		if (ev.key === "Tab") fechar();
	});
	menuAberto = { botao, fechar };
	caixa.querySelector("button:not(:disabled)")?.focus({ preventScroll: true });
	return fechar;
}
export const fecharMenu = () => menuAberto?.fechar();

// ---------- Avisos no canto ----------
let pilhaAvisos = null;
// tom: ok | rev | err | info
export function aviso({ tom = "info", titulo, texto = "", lista = null, acoes = [], tempo = tom === "err" ? 9000 : 6000, id }) {
	if (!pilhaAvisos) { pilhaAvisos = el(`<div class="avisos-pilha" aria-live="polite"></div>`); document.body.append(pilhaAvisos); }
	if (id) pilhaAvisos.querySelector(`[data-id="${id}"]`)?.remove();
	const icones = { ok: "circle-check", rev: "circle-alert", err: "circle-x", info: "info" };
	const t = el(`<div class="toast ${tom}" role="${tom === "err" ? "alert" : "status"}" ${id ? `data-id="${esc(id)}"` : ""}>
		${icon(icones[tom])}
		<div><b>${esc(titulo)}</b>${texto ? `<p>${esc(texto)}</p>` : ""}</div>
		<button class="btn sm ic limpo fechar" aria-label="Fechar aviso">${icon("x")}</button>
	</div>`);
	if (lista) t.children[1].append(el(`<ul>${lista}</ul>`));
	if (acoes.length) {
		const box = el(`<div class="toast-acoes"></div>`);
		for (const a of acoes) {
			const b = el(`<button class="btn sm ${a.pri ? "pri" : ""}">${esc(a.rotulo)}</button>`);
			b.onclick = () => { fechar(); a.acao(); };
			box.append(b);
		}
		t.append(box);
	}
	let timer = null;
	const fechar = () => { clearTimeout(timer); t.remove(); };
	t.querySelector(".fechar").onclick = fechar;
	if (tempo && !acoes.length && !lista) timer = setTimeout(fechar, tempo);
	t.addEventListener("pointerenter", () => clearTimeout(timer));
	pilhaAvisos.append(t);
	while (pilhaAvisos.children.length > 4) pilhaAvisos.firstElementChild.remove();
	return fechar;
}
export const erro = (e, titulo = "Não deu certo") => aviso({ tom: "err", titulo, texto: e?.message || String(e) });

// ---------- Controles ----------
export const chave = (id, ligado, rotulo, desligado = false) =>
	`<button class="chave" role="switch" id="${esc(id)}" aria-checked="${ligado ? "true" : "false"}" aria-label="${esc(rotulo)}" ${desligado ? "disabled" : ""}></button>`;

export function opcao({ id, titulo, texto = "", ligado, desligado = false }) {
	return `<div class="opcao"><div class="opcao-txt"><b id="${esc(id)}-t">${esc(titulo)}</b>${texto ? `<span>${esc(texto)}</span>` : ""}</div>${chave(id, ligado, titulo, desligado)}</div>`;
}

// itens: [[valor, rótulo, ícone?]]
export const segmentado = (nome, itens, atual, rotulo) =>
	`<div class="seg" role="radiogroup" aria-label="${esc(rotulo)}" data-seg="${esc(nome)}">${itens
		.map(([v, r, ic]) => `<button role="radio" data-v="${esc(v)}" aria-checked="${String(v) === String(atual)}">${ic ? icon(ic) : ""}${esc(r)}</button>`)
		.join("")}</div>`;

export function pintarRegua(input) {
	const min = Number(input.min), max = Number(input.max), v = Number(input.value);
	input.style.setProperty("--p", `${((v - min) / (max - min)) * 100}%`);
}

// ---------- Brilho ----------
export const sh = (largura, cls = "sh-txt") => `<span class="sh ${cls}" style="width:${largura}" aria-hidden="true"></span>`;
