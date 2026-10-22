// Lateral: marca, busca de playlist, Adicionar playlist (⌘N), menu "…" das playlists,
// lista com mosaico e, no pé, Aparelhos, Equalizador, Registro, Ajuda e Ajustes.
// No celular a mesma lateral abre como gaveta pelo botão de playlists.
import { store, on, playlistsEmOrdem } from "./store.js";
import { esc, icon, el, mosaico, resumoLateral } from "./util.js";
import { menu, sh, empilhar } from "./ui.js";
import * as acoes from "./acoes.js";
import { abrirAdicionar } from "./adicionar.js";
import { abrirAjustes } from "./ajustes.js";
import { abrirAparelhos } from "./aparelhos.js";
import { abrirRegistro } from "./registro.js";
import { abrirAjuda } from "./ajuda.js";

let filtro = "";
const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const teclaCmd = MAC ? "⌘" : "Ctrl+";

function itens() {
	if (store.erro) return "";
	if (!store.carregado) {
		return [0, 1, 2, 3].map((i) => `<div class="pl" aria-hidden="true"><span class="pm um">${sh("100%", "sh-blk sh-cheio")}</span>
			<span class="pt"><b>${sh(["8em", "6em", "9em", "5em"][i])}</b><small>${sh(["7em", "8em", "6em", "7em"][i])}</small></span></div>`).join("");
	}
	const f = filtro.toLocaleLowerCase("pt-BR");
	const lista = playlistsEmOrdem().filter((p) => !f || p.name.toLocaleLowerCase("pt-BR").includes(f));
	if (!lista.length && f) return `<p class="ajuda" style="padding:8px 10px">Nenhuma playlist com esse nome.</p>`;
	return lista.map((p) => `<a class="pl${p.id === store.selecionada ? " ativo" : ""}${p.access_error ? " priv" : ""}" href="#/p/${encodeURIComponent(p.id)}"
		data-id="${esc(p.id)}" ${p.id === store.selecionada ? 'aria-current="page"' : ""}>
		${mosaico(p)}<span class="pt"><b>${esc(p.name)}</b><small>${esc(resumoLateral(p, store.job))}</small></span></a>`).join("");
}

function html(gaveta) {
	return `
	${gaveta ? `<div class="gaveta-cab"><span class="marca">CSVMusic</span><button class="btn ic limpo" data-l="fechar" aria-label="Fechar">${icon("x")}</button></div>` : `<span class="marca">CSVMusic</span>`}
	<label class="busca">${icon("search")}<span class="sr">Buscar playlist</span><input type="search" data-l="busca" placeholder="Buscar playlist" value="${esc(filtro)}" autocomplete="off"></label>
	<button class="addb" data-l="adicionar">${icon("plus")}Adicionar playlist<kbd>${teclaCmd}N</kbd></button>
	<div class="side-cab"><span>Playlists</span><button class="btn sm ic limpo" data-l="mais" aria-label="Ações de todas as playlists" aria-haspopup="menu" ${store.carregado && store.ordem.length ? "" : "disabled"}>${icon("ellipsis")}</button></div>
	<nav class="pls" aria-label="Playlists">${itens()}</nav>
	<div class="rod">
		<button data-l="aparelhos">${icon("smartphone")}Aparelhos</button>
		<button data-l="som">${icon("audio-lines")}Equalizador</button>
		<button data-l="registro">${icon("list")}Registro</button>
		<button data-l="ajuda">${icon("circle-help")}Ajuda</button>
		<button data-l="ajustes">${icon("settings")}Ajustes</button>
	</div>`;
}

function ligar(raiz, fecharGaveta) {
	raiz.addEventListener("click", (ev) => {
		const pl = ev.target.closest(".pl[data-id]");
		if (pl) { fecharGaveta?.(); return; } // o link (#/p/…) troca a playlist
		const b = ev.target.closest("[data-l]");
		if (!b) return;
		const acao = b.dataset.l;
		if (acao === "mais") { menuTodas(b); return; }
		if (acao === "busca") return;
		fecharGaveta?.();
		({
			fechar: () => {},
			adicionar: () => abrirAdicionar(),
			aparelhos: abrirAparelhos,
			som: () => abrirAjustes("som"),
			registro: abrirRegistro,
			ajuda: () => abrirAjuda(),
			ajustes: () => abrirAjustes(),
		})[acao]?.();
	});
	raiz.querySelector('[data-l="busca"]').addEventListener("input", (ev) => {
		filtro = ev.target.value;
		raiz.querySelector(".pls").innerHTML = itens();
	});
}

function menuTodas(botao) {
	const ids = store.ordem.slice();
	const ocupado = store.job?.kind === "download";
	menu(botao, [
		{ rotulo: "Baixar o que falta em todas", icone: "download", desligado: ocupado, acao: () => acoes.baixarFaltando(ids) },
		{ rotulo: "Analisar todas de novo", icone: "refresh-cw", acao: () => acoes.analisar({ scope: "all" }) },
		{ rotulo: "Analisar as não analisadas", icone: "refresh-cw", acao: () => acoes.analisar({ scope: "unscanned" }) },
		"-",
		{ rotulo: "Abrir a pasta das músicas", icone: "folder-open", acao: () => acoes.abrirNoFinder("output") },
		{ rotulo: "Importar planilha…", icone: "file-spreadsheet", acao: () => abrirAdicionar("planilha") },
	], { alinhar: "direita" });
}

export function pintarLateral() {
	const side = document.querySelector(".side");
	if (!side.dataset.ligada) {
		side.innerHTML = html(false);
		ligar(side);
		side.dataset.ligada = "1";
	} else {
		side.querySelector(".pls").innerHTML = itens();
		const mais = side.querySelector('[data-l="mais"]');
		mais.disabled = !(store.carregado && store.ordem.length);
	}
	const gav = document.querySelector(".gaveta .pls");
	if (gav) gav.innerHTML = itens();
}

export function abrirGaveta() {
	const veu = el(`<div class="veu"></div>`);
	const g = el(`<div class="gaveta" role="dialog" aria-modal="true" aria-label="Playlists">${html(true)}</div>`);
	const fechar = () => { tirar(); veu.remove(); g.remove(); };
	const tirar = empilhar(fechar);
	veu.onclick = fechar;
	ligar(g, fechar);
	g.querySelector('[data-l="fechar"]').addEventListener("click", fechar);
	document.body.append(veu, g);
	g.querySelector('[data-l="fechar"]').focus();
}

// Uma playlist mudou: troca só o texto e o mosaico dela (eventos chegam várias vezes por segundo).
function pintarItem(pl) {
	for (const a of document.querySelectorAll(`.pl[data-id="${CSS.escape(pl.id)}"]`)) {
		a.querySelector(".pt b").textContent = pl.name;
		a.querySelector(".pt small").textContent = resumoLateral(pl, store.job);
		a.classList.toggle("priv", !!pl.access_error);
		const novo = el(mosaico(pl));
		const velho = a.querySelector(".pm");
		if (velho.dataset.mosaico !== novo.dataset.mosaico) velho.replaceWith(novo);
	}
}

let assinaturaJob = "";
on("estado", pintarLateral);
on("playlist", (pl) => { if (pl && document.querySelector(`.pl[data-id="${CSS.escape(pl.id)}"]`)) pintarItem(pl); else pintarLateral(); });
on("job", () => {
	const j = store.job || {};
	const a = `${j.kind}:${j.playlist_id || ""}`;
	if (a === assinaturaJob) return;
	assinaturaJob = a;
	pintarLateral();
});
on("selecao", pintarLateral);
on("removida", pintarLateral);
