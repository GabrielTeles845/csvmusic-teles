// Demonstração animada (skill demo-animada): colar o link, a playlist aparece, a análise corre.
// Feita com as classes reais da tela (.campo, .entrada, .btn, .pl, .pm, .barra); o CSS está em demo.css.
// Dados de exemplo, rotulados como exemplo.
import { icon } from "./util.js";

const LINK = "open.spotify.com/playlist/exemplo";

export function demoAdicionar() {
	return `<div class="demo" aria-hidden="true" style="--passos:${LINK.length}">
		<span class="demo-rotulo">Exemplo</span>
		<div class="demo-palco">
			<div class="demo-q demo-a">
				<div class="demo-cab"><b>Adicionar playlist</b></div>
				<div class="abas"><span class="aba" aria-selected="true">${icon("link")}Link</span><span class="aba">${icon("file-spreadsheet")}Planilha</span></div>
				<div class="campo">
					<label>Link da playlist</label>
					<div class="area demo-campo"><span class="demo-ph">Cole o link aqui. Para adicionar várias, um link por linha.</span><span class="demo-txt">${LINK}</span></div>
				</div>
				<div class="demo-pe"><span class="btn">Cancelar</span><span class="btn pri demo-clique">${icon("plus")}Adicionar</span></div>
			</div>
			<div class="demo-q demo-b">
				<div class="side-cab"><span>Playlists</span></div>
				<div class="pl ativo"><span class="pm demo-pm"><i></i><i></i><i></i><i></i></span>
					<span class="pt"><b>Minha playlist</b><small><span class="demo-s1">Spotify · Analisando</span><span class="demo-s2">Spotify · 0 de 48</span></small></span></div>
				<div class="demo-fim">
					<div class="demo-analise"><div class="demo-lin"><span>Lendo as músicas e procurando no YouTube Music</span></div><div class="barra"><i></i></div></div>
					<span class="btn pri demo-baixar">${icon("download")}Baixar as 48 que faltam</span>
				</div>
				<div class="lista demo-linhas">${[["Primeira música", "Artista Exemplo"], ["Segunda música", "Banda Exemplo"], ["Terceira música", "Artista Exemplo"]].map(([t, a], i) => `
					<div class="row tom-mut${i % 2 ? " par" : ""}"><span class="ck"><input type="checkbox" checked tabindex="-1"></span>
						<span class="n">${i + 1}</span><span class="cv demo-cv${i}"></span>
						<span class="t"><b>${t}</b><small>${a}</small><em class="stm">${icon("circle-dashed")}Faltando</em></span>
						<span class="al"></span><span class="d"></span><span class="st">${icon("circle-dashed")}<span>Faltando</span></span></div>`).join("")}
				</div>
			</div>
		</div>
	</div>`;
}
