// Ações que aparecem em mais de um lugar (lateral, topo da playlist, painel, avisos).
import { get, post, patch, del, enc, qs, baixarArquivo } from "./api.js";
import { store, emit } from "./store.js";
import { aviso, erro, confirmar, dialogo } from "./ui.js";
import { esc, icon, n } from "./util.js";

function aplicarJob(job) {
	if (job && typeof job === "object" && "kind" in job) { store.job = job; emit("job"); }
}

// Lote grande (250+): o motor responde 409 com needs_confirmation="youtube_risk" e o aviso no `error`.
// A tela mostra o aviso e, se a pessoa confirmar, repete com confirm_risk: true.
async function comRisco(rota, corpo, titulo) {
	try { aplicarJob(await post(rota, corpo)); }
	catch (e) {
		if (e.status === 409 && e.dados?.needs_confirmation === "youtube_risk") {
			const sim = await confirmar({
				titulo: e.dados.tracks ? `Baixar ${n(e.dados.tracks)} músicas de uma vez` : "Lote grande",
				texto: esc(e.message), sim: "Baixar mesmo assim", nao: "Agora não",
			});
			if (sim) return comRisco(rota, { ...corpo, confirm_risk: true }, titulo);
			return;
		}
		erro(e, titulo);
	}
}

export const baixarFaltando = (ids) => comRisco("/download", { playlist_ids: ids, missing_only: true }, "Não deu para começar o download");
export const baixarMusicas = (targets) => comRisco("/download", { targets }, "Não deu para começar o download");

// Depois de entrar no YouTube: baixa de novo só as músicas com restrição de idade do último lote.
export const baixarRestritas = () => comRisco("/age-restricted/retry", { confirm_risk: true }, "Não deu para baixar de novo");

export async function pararDownload() {
	try { aplicarJob(await post("/download/stop")); }
	catch (e) { erro(e, "Não deu para parar"); }
}

export async function analisar(corpo) {
	try { aplicarJob(await post("/scan", corpo)); }
	catch (e) { erro(e, "Não deu para analisar"); }
}

export async function pararAnalise() {
	try { aplicarJob(await post("/scan/cancel")); }
	catch (e) { erro(e, "Não deu para parar a análise"); }
}

export async function abrirNoFinder(what, extra = {}) {
	try { await post("/open", { what, ...extra }); }
	catch (e) { erro(e, "Não deu para abrir no Finder"); }
}

export async function exportarPlanilha(pl) {
	try {
		const nome = pl ? `${pl.name}.csv` : "biblioteca.csv";
		await baixarArquivo("/export-csv" + qs({ playlist_id: pl?.id }), nome);
	} catch (e) { erro(e, "Não deu para exportar a planilha"); }
}

export async function renomear(pl, nome) {
	nome = nome.trim();
	if (!nome || nome === pl.name) return;
	try {
		const novo = await patch(`/playlists/${enc(pl.id)}`, { name: nome });
		store.playlists.set(novo.id, novo);
		emit("playlist", novo);
	} catch (e) { erro(e, "Não deu para renomear"); emit("playlist", pl); }
}

// Remover nunca apaga música: ou mantém a pasta, ou manda para a Lixeira do Mac.
export function remover(pl) {
	let escolha = "keep";
	const d = dialogo({
		titulo: "Remover playlist",
		corpo: `<p class="sub">“${esc(pl.name)}” sai da lista. O que fazer com a pasta das músicas?</p>
			<div class="lista-simples" role="radiogroup" aria-label="O que fazer com a pasta">
				<button class="item-ap" role="radio" aria-selected="true" aria-checked="true" data-v="keep">${icon("folder-open")}<span class="cresce"><b>Manter os arquivos</b><small>A pasta fica onde está.</small></span></button>
				<button class="item-ap" role="radio" aria-selected="false" aria-checked="false" data-v="trash">${icon("trash-2")}<span class="cresce"><b>Mandar a pasta para a Lixeira</b><small>Dá para recuperar pela Lixeira do Mac.</small></span></button>
			</div>`,
		pe: `<button class="btn" data-nao>Cancelar</button><button class="btn perigo" data-sim>Remover</button>`,
	});
	d.corpo.querySelectorAll("[data-v]").forEach((b) => b.addEventListener("click", () => {
		escolha = b.dataset.v;
		d.corpo.querySelectorAll("[data-v]").forEach((x) => { const on = x === b; x.setAttribute("aria-selected", on); x.setAttribute("aria-checked", on); });
	}));
	d.pe.querySelector("[data-nao]").onclick = () => d.fechar();
	d.pe.querySelector("[data-sim]").onclick = async () => {
		try {
			const r = await del(`/playlists/${enc(pl.id)}` + qs({ files: escolha }));
			d.fechar();
			store.playlists.delete(pl.id);
			store.ordem = store.ordem.filter((x) => x !== pl.id);
			emit("removida", pl.id);
			aviso({ tom: "ok", titulo: "Playlist removida", texto: r?.trashed_folder ? "A pasta foi para a Lixeira do Mac." : "Os arquivos continuam na pasta." });
		} catch (e) {
			d.fechar();
			erro(e, "Não deu para remover");
		}
	};
}

export async function marcarTodas(pl, ligado) {
	try {
		const r = await post(`/playlists/${enc(pl.id)}/tracks/set-enabled`, { enabled: ligado, all: true });
		emit("recarregar-lista");
		aviso({ tom: "ok", titulo: ligado ? "Todas marcadas" : "Todas desmarcadas", texto: r?.changed !== undefined ? `${n(r.changed)} músicas mudaram.` : "" });
	} catch (e) { erro(e); }
}

export async function entrarNoYoutube() {
	try {
		const r = await post("/age-restricted/resolve");
		aviso({ tom: "info", titulo: r?.method === "enable_session" ? "Ligando a sua sessão do YouTube" : "Abrimos o login do YouTube", texto: "Quando terminar, a barra de baixo oferece baixar de novo." });
	} catch (e) { erro(e, "Não deu para abrir o login"); }
}

