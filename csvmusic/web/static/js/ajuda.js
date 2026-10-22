// Ajuda (com a demonstração), Sobre e o aviso da primeira abertura.
import { post } from "./api.js";
import { store } from "./store.js";
import { esc, icon } from "./util.js";
import { dialogo, erro } from "./ui.js";
import { demoAdicionar } from "./demo.js";
import { teclaCmd } from "./lateral.js";

export function abrirAjuda(secao) {
	const d = dialogo({
		titulo: "Ajuda",
		largo: true,
		corpo: `<div class="ajuda-txt ajuda-rolagem"><div class="ajuda-grade">
			<div class="ajuda-demo">${demoAdicionar()}</div>
			<div>
			<p>Cole o link de uma playlist. O CSVMusic lê as músicas, procura cada uma no YouTube Music e baixa em arquivo de áudio, com capa e nome certos.</p>
			<h3>Depois de analisar</h3>
			<ul>
				<li><b>Baixar as que faltam</b> baixa só o que ainda não está na pasta.</li>
				<li><b>Revisar</b> marca as músicas em que a versão encontrada pode não ser a certa. Toque em <b>Aceitar</b> ou em <b>Trocar</b> para escolher outra.</li>
				<li>Toque numa música para ver as outras versões, colar um link do YouTube, mudar o volume ou corrigir o nome.</li>
				<li>Desmarque uma música para ela ficar de fora dos downloads.</li>
			</ul>
			<h3>Quando algo não baixa</h3>
			<ul>
				<li><b>Restrição de idade:</b> entre na sua conta do YouTube em Ajustes › Conta do YouTube e baixe de novo.</li>
				<li><b>Playlist particular:</b> o Spotify só mostra para quem está logado. Torne a playlist pública e analise de novo.</li>
				<li><b>Muitos erros seguidos:</b> o YouTube às vezes segura pedidos repetidos. Espere um pouco antes de tentar de novo.</li>
			</ul>
			<h3>Atalhos</h3>
			<div class="atalhos">
				<kbd>${teclaCmd}N</kbd><span>Adicionar playlist</span>
				<kbd>${teclaCmd},</kbd><span>Ajustes</span>
				<kbd>Esc</kbd><span>Fechar o painel ou a janela aberta</span>
			</div>
			<h3 data-sobre>Sobre</h3>
			<p>CSVMusic ${esc(store.version)}. Versão pessoal do <a href="https://github.com/angall1/CSVMusic" target="_blank" rel="noopener">CSVMusic de angall1</a>, com yt-dlp e FFmpeg. Fonte Figtree (OFL) e ícones Lucide (ISC).</p>
			<p style="margin-top:8px">Baixe só o que você tem direito de guardar.</p>
			</div></div>
		</div>`,
		pe: `<button class="btn" data-fechar-pe>Fechar</button>`,
	});
	d.pe.querySelector("[data-fechar-pe]").onclick = () => d.fechar();
	if (secao === "sobre") requestAnimationFrame(() => d.corpo.querySelector("[data-sobre]").scrollIntoView({ block: "start" }));
}

// Primeira abertura, uma vez: o que vale saber antes de começar.
export function primeiraVez() {
	return new Promise((resolve) => {
		const d = dialogo({
			titulo: "Antes de começar",
			corpo: `<div class="ajuda-txt">
				<p>Três coisas que evitam dor de cabeça:</p>
				<h3>Playlists enormes demoram</h3>
				<p>Funcionam, mas são muitas buscas e downloads. Elas levam mais tempo e têm mais chance de parar no meio. Dá para analisar de novo depois.</p>
				<h3>O YouTube às vezes segura os pedidos</h3>
				<p>Quando isso acontece, os downloads falham por um tempo. O CSVMusic já faz pausas; esperar um pouco antes de tentar de novo costuma resolver.</p>
				<h3>Confira o que ficou para revisar</h3>
				<p>A busca automática pode errar a versão. As músicas marcadas como <b>Revisar</b> merecem uma olhada. Baixe só o que você tem direito de guardar.</p>
			</div>`,
			pe: `<button class="btn pri" data-ok autofocus>Entendi</button>`,
			aoFechar: () => resolve(),
		});
		d.pe.querySelector("[data-ok]").onclick = async () => {
			try { await post("/first-run/accept"); store.firstRun = false; d.fechar(); }
			catch (e) { erro(e, "Não deu para salvar"); }
		};
	});
}

export const iconeAjuda = icon("circle-help");
