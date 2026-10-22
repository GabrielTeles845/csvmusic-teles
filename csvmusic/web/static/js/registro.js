// Registro: o que o download está fazendo, linha a linha (GET /api/log e evento `log`).
import { get, qs } from "./api.js";
import { on } from "./store.js";
import { esc, icon, hora } from "./util.js";
import { dialogo, sh } from "./ui.js";
import { abrirNoFinder } from "./acoes.js";

const MAX = 1000;
let d = null;
let ultimo = 0;
// Linhas que chegam pelo evento enquanto GET /api/log responde; juntam com a resposta pelo seq.
let fila = null;

function linha(e) {
	return `<div class="${esc(e.level || "info")}"><time>${esc(hora(e.ts))}</time><span>${esc(e.message)}</span></div>`;
}

export function abrirRegistro() {
	if (d && !d.fechado) return;
	d = dialogo({
		titulo: "Registro",
		largo: true,
		corpo: `<div style="padding:0 24px 20px;overflow:auto;flex:1;min-height:0" data-rolar>
			<div class="log" data-log aria-live="polite">${[64, 48, 72, 56, 80, 44, 68, 52].map((w) => `<div aria-hidden="true">${sh("3.4em")}<span>${sh(w + "%")}</span></div>`).join("")}</div></div>`,
		pe: `<button class="btn" data-finder>${icon("folder-open")}Abrir o registro completo</button><button class="btn" data-fechar-pe>Fechar</button>`,
		aoFechar: () => { d = null; fila = null; },
	});
	fila = [];
	ultimo = 0;
	d.pe.querySelector("[data-fechar-pe]").onclick = () => d.fechar();
	d.pe.querySelector("[data-finder]").onclick = () => abrirNoFinder("log");
	get("/log" + qs({ since: 0 })).then((r) => {
		if (!d) return;
		const box = d.corpo.querySelector("[data-log]");
		const porSeq = new Map();
		for (const e of [...(r.entries || []), ...(fila || [])]) porSeq.set(e.seq, e);
		fila = null;
		const itens = [...porSeq.values()].sort((a, b) => a.seq - b.seq).slice(-MAX);
		ultimo = Math.max(r.last_seq || 0, itens.length ? itens[itens.length - 1].seq : 0);
		box.innerHTML = itens.length ? itens.map(linha).join("") : `<p class="ajuda">Nada por aqui ainda. As linhas aparecem quando um download começa.</p>`;
		const rolar = d.corpo.querySelector("[data-rolar]");
		rolar.scrollTop = rolar.scrollHeight;
	}).catch((e) => {
		fila = null;
		if (d) d.corpo.querySelector("[data-log]").innerHTML = `<p class="erro-campo">${esc(e.message)}</p>`;
	});
}

on("log", (e) => {
	if (!d) return;
	if (fila) { fila.push(e); return; } // ainda carregando: junta com a resposta
	if (e.seq <= ultimo) return;
	ultimo = e.seq;
	const box = d.corpo.querySelector("[data-log]");
	box.querySelector("p.ajuda")?.remove();
	const rolar = d.corpo.querySelector("[data-rolar]");
	const noFim = rolar.scrollTop + rolar.clientHeight >= rolar.scrollHeight - 24;
	box.insertAdjacentHTML("beforeend", linha(e));
	while (box.children.length > MAX) box.firstElementChild.remove();
	if (noFim) rolar.scrollTop = rolar.scrollHeight;
});
