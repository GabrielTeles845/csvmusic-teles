// Biblioteca sem playlist e tela de erro geral.
import { esc, icon } from "./util.js";
import { demoAdicionar } from "./demo.js";
import { abrirAdicionar } from "./adicionar.js";
import { abrirGaveta } from "./lateral.js";
import { abrirAjustes } from "./ajustes.js";

const topo = () => `<div class="topo-m"><span class="marca">CSVMusic</span>
	<button class="btn ic" data-m="playlists" aria-label="Playlists">${icon("list-music")}</button>
	<button class="btn ic" data-m="ajustes" aria-label="Ajustes">${icon("settings")}</button></div>`;

function ligarTopo(m) {
	m.querySelector('[data-m="playlists"]')?.addEventListener("click", abrirGaveta);
	m.querySelector('[data-m="ajustes"]')?.addEventListener("click", () => abrirAjustes());
}

export function mostrarVazio() {
	const m = document.getElementById("main");
	m.className = "";
	m.innerHTML = `${topo()}<div class="vazio-pg">
		<div>
			<h1>Sua primeira playlist</h1>
			<p>Cole o link de uma playlist do Spotify, Apple Music, Deezer ou YouTube Music. O CSVMusic lê as músicas e baixa cada uma em arquivo de áudio, com capa e nome certos.</p>
			<ol>
				<li><span>Cole o link em <b>Adicionar playlist</b>.</span></li>
				<li><span>A análise lê as músicas e procura cada uma no YouTube Music.</span></li>
				<li><span>Toque em <b>Baixar</b>. Cada playlist ganha a sua pasta.</span></li>
			</ol>
			<div class="acoes-v">
				<button class="btn pri" data-v="link">${icon("plus")}Adicionar playlist</button>
				<button class="btn" data-v="planilha">${icon("file-spreadsheet")}Importar planilha</button>
			</div>
		</div>
		${demoAdicionar()}
	</div>`;
	ligarTopo(m);
	m.querySelector('[data-v="link"]').onclick = () => abrirAdicionar("link");
	m.querySelector('[data-v="planilha"]').onclick = () => abrirAdicionar("planilha");
}

export function mostrarErroGeral(e, tentar) {
	const m = document.getElementById("main");
	m.className = "";
	m.innerHTML = `${topo()}<div class="erro-pg" role="alert">${icon("circle-x")}
		<h1>Não deu para abrir sua biblioteca</h1>
		<p>${esc(e?.message || "")}</p>
		<button class="btn pri" data-tentar>${icon("refresh-cw")}Tentar de novo</button></div>`;
	ligarTopo(m);
	m.querySelector("[data-tentar]").onclick = tentar;
}
