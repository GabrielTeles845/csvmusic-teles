// Barra de baixo ("tocando agora"): download ou análise em andamento, Parar e Registro.
// Depois de um download com restrição de idade, mostra "Entrar no YouTube".
import { capaAttrs } from "./api.js";
import { store, on } from "./store.js";
import { esc, icon, n, hora } from "./util.js";
import * as acoes from "./acoes.js";
import { abrirRegistro } from "./registro.js";

const FASES = { matching: "Procurando no YouTube Music", downloading: "Baixando", tagging: "Gravando capa e dados" };

function conteudo() {
	const j = store.job || {};
	if (j.kind === "download") {
		const c = j.current || {};
		const pct = j.total ? Math.min(100, (j.processed / j.total) * 100) : 0;
		// percent vem null (o yt-dlp não informa): o andamento é o do lote. eta_at só depois da 1ª música.
		const fase = FASES[c.phase] || "Preparando";
		const ate = j.eta_at ? `até ${hora(j.eta_at)}` : "";
		const curto = j.single ? fase : [`${n(j.processed)} de ${n(j.total)}`, ate].filter(Boolean).join(" · ");
		return `<div class="agora">${c.cover_url ? `<img class="cv" ${capaAttrs(c.cover_url)} alt="">` : `<span class="cv-ic">${icon("music")}</span>`}
				<span><b>${esc(c.title || "Preparando o download")}</b><small><span class="so-d">${esc(j.stopping ? "Parando depois desta música" : fase)}</span><span class="so-m">${esc(j.stopping ? "Parando" : curto)}</span></small></span></div>
			<div class="meio"><div class="barra" role="progressbar" aria-label="Progresso do download" aria-valuemin="0" aria-valuemax="${j.total || 0}" aria-valuenow="${j.processed || 0}"><i style="width:${pct}%"></i></div>
				<div class="lin"><span>${j.single ? "Só esta música" : `${n(j.processed)} de ${n(j.total)} músicas`}</span><span>${j.eta_at ? `termina por volta das ${esc(hora(j.eta_at))}` : ""}</span></div></div>
			<div class="dir"><button class="btn" data-b="registro" aria-label="Registro">${icon("list")}<span class="so-d">Registro</span></button>
				<button class="btn" data-b="parar" aria-label="Parar o download" ${j.stopping ? "disabled" : ""}>${icon("square")}<span class="so-d">${j.stopping ? "Parando" : "Parar"}</span></button></div>`;
	}
	if (j.kind === "scan") {
		const tem = j.reported_total;
		const pct = tem ? Math.min(100, (j.captured / tem) * 100) : 0;
		const lidas = tem ? `${n(j.captured)} de ${n(tem)} músicas lidas` : `${n(j.captured)} músicas lidas`;
		const fila = j.queue_left ? `mais ${n(j.queue_left)} na fila` : "";
		return `<div class="agora"><span class="cv-ic">${icon("refresh-cw")}</span>
				<span><b>Analisando ${esc(j.name || "")}</b><small>${esc(lidas)}</small></span></div>
			<div class="meio"><div class="barra" role="progressbar" aria-label="Progresso da análise"><i style="width:${pct}%"></i></div>
				<div class="lin"><span>${esc(lidas)}</span><span>${esc(fila)}</span></div></div>
			<div class="dir"><button class="btn" data-b="registro" aria-label="Registro">${icon("list")}<span class="so-d">Registro</span></button>
				<button class="btn" data-b="parar-analise" aria-label="Parar a análise" ${j.cancelling ? "disabled" : ""}>${icon("square")}<span class="so-d">${j.cancelling ? "Parando" : "Parar"}</span></button></div>`;
	}
	if (store.idade) {
		const pronto = store.idade.pronto !== undefined;
		const q = pronto ? store.idade.pronto : store.idade.quantas;
		// age_action: "enable_session" (já há sessão salva) | "sign_in" | null (nada a fazer pela tela).
		const acao = store.idade.acao;
		const botao = pronto ? `<button class="btn pri com-texto" data-b="rebaixar">${icon("download")}Baixar de novo</button>`
			: acao === "enable_session" ? `<button class="btn pri com-texto" data-b="entrar">${icon("log-in")}Usar minha sessão do YouTube</button>`
			: acao === "sign_in" ? `<button class="btn pri com-texto" data-b="entrar">${icon("log-in")}Entrar no YouTube</button>` : "";
		return `<div class="agora"><span class="cv-ic rev">${icon("lock")}</span>
				<span><b>${pronto ? "Sessão do YouTube pronta" : `${q === 1 ? "1 música pede" : `${n(q)} músicas pedem`} login no YouTube`}</b>
				<small>${pronto ? "Dá para baixar de novo as que tinham restrição de idade." : "São músicas com restrição de idade."}</small></span></div>
			<div class="meio"></div>
			<div class="dir"><button class="btn" data-b="dispensar" aria-label="Agora não">${icon("x")}<span class="so-d">Agora não</span></button>
				${botao}</div>`;
	}
	return null;
}

export function pintarBarra() {
	const bar = document.querySelector(".bar");
	const html = conteudo();
	if (!html) { bar.hidden = true; bar.innerHTML = ""; }
	else {
		const foco = document.activeElement && bar.contains(document.activeElement) ? document.activeElement.dataset.b : null;
		bar.hidden = false;
		bar.innerHTML = html;
		if (foco) bar.querySelector(`[data-b="${foco}"]`)?.focus();
	}
	document.documentElement.style.setProperty("--bar-h", (bar.hidden ? 0 : bar.offsetHeight) + "px");
}

export function ligarBarra() {
	const bar = document.querySelector(".bar");
	bar.addEventListener("click", (ev) => {
		const b = ev.target.closest("[data-b]");
		if (!b || b.disabled) return;
		const a = b.dataset.b;
		if (a === "registro") abrirRegistro();
		if (a === "parar") acoes.pararDownload();
		if (a === "parar-analise") acoes.pararAnalise();
		if (a === "entrar") acoes.entrarNoYoutube();
		if (a === "dispensar") { store.idade = null; pintarBarra(); }
		if (a === "rebaixar") {
			store.idade = null;
			pintarBarra();
			acoes.baixarRestritas();
		}
	});
	addEventListener("resize", () => document.documentElement.style.setProperty("--bar-h", (bar.hidden ? 0 : bar.offsetHeight) + "px"));
}

on("job", pintarBarra);
on("estado", pintarBarra);
on("idade", pintarBarra);
