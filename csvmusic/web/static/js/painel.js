// Painel da música: à direita no computador, de baixo no celular.
// Seções: situação e ações, Versão do YouTube, Volume, Dados, Arquivo, Erro.
import { get, patch, post, enc, qs, capaAttrs } from "./api.js";
import { store, on, emit } from "./store.js";
import { esc, icon, el, segundos, estado, debounce, dataHora } from "./util.js";
import { empilhar, erro, aviso, sh, pintarRegua } from "./ui.js";
import * as acoes from "./acoes.js";

let aberto = null; // {playlistId, index, track, caixa, veu, tirar}
export const painelAberto = () => aberto;

const ERRO_DE_IDADE = new Set(["age_limit"]);

// O que fazer, por situação. Frases fixas da tela; o motivo em si vem do motor (detail/error).
const O_QUE_FAZER = {
	error: "Tente baixar de novo daqui a pouco. Se continuar, escolha outra versão do YouTube abaixo.",
	age_limit: "O YouTube só libera esta música para quem está logado. Entre na sua conta do YouTube e baixe de novo.",
	not_found: "Nenhuma versão no YouTube Music parece ser esta música. Cole o link de uma versão que você encontrou no YouTube.",
	review: "A versão encontrada pode não ser a certa. Ouça no YouTube e aceite, ou escolha outra abaixo.",
};

// Track.error: {summary, advice, technical, at, kind} ou null (docs/fork/14 §4).
function erroDa(t) {
	const e = t.error;
	if (!e) return null;
	if (typeof e === "string") return { summary: e, advice: "", technical: "" };
	return e;
}

function linkDoVideo(id) { return `https://www.youtube.com/watch?v=${id}`; }

// ---------- Partes que mudam com a música ----------
function parteViva(t) {
	const e = estado(t, store.job);
	const c = [];
	if (t.state === "review") {
		c.push(`<button class="btn pri" data-a="aceitar">${icon("check")}Aceitar</button>`);
		c.push(`<button class="btn" data-a="ir-versao">${icon("replace")}Trocar versão</button>`);
	} else if (["missing", "error", "not_found", "age_limit", "redownload"].includes(t.state)) {
		const pedeConta = ERRO_DE_IDADE.has(t.state) || t.error?.kind === "youtube_blocked";
		if (pedeConta) c.push(`<button class="btn pri" data-a="entrar">${icon("log-in")}Entrar no YouTube</button>`);
		c.push(`<button class="btn ${pedeConta ? "" : "pri"}" data-a="baixar" ${t.enabled === false ? "disabled" : ""}>${icon("download")}Baixar agora</button>`);
	} else if (t.state === "downloaded") {
		c.push(`<button class="btn" data-a="finder">${icon("folder-open")}Mostrar no Finder</button>`);
		c.push(`<button class="btn" data-a="rebaixar">${icon("refresh-cw")}Baixar de novo</button>`);
	}
	const fazer = O_QUE_FAZER[t.state];
	return `<div class="pn-topo">
			${t.cover_url ? `<img class="cv" ${capaAttrs(t.cover_url)} alt="">` : `<span class="cv"></span>`}
			<div><h2>${esc(t.title || "Sem título")}</h2><p>${esc(t.artists || "")}${t.album ? ` · ${esc(t.album)}` : ""}</p></div>
		</div>
		<div class="pn-situacao">
			<span class="estado tom-${e.tom}">${icon(e.icone)}${esc(e.texto)}</span>
			${t.detail ? `<p>${esc(t.detail)}</p>` : ""}
			${fazer && t.state !== "error" ? `<p>${esc(fazer)}</p>` : ""}
		</div>
		${c.length ? `<div class="pn-acoes">${c.join("")}</div>` : ""}
		<div class="opcao"><div class="opcao-txt"><b>Baixar esta música</b><span>Desmarcada, ela fica de fora dos downloads.</span></div>
			<button class="chave" role="switch" data-a="ligar" aria-checked="${t.enabled !== false}" aria-label="Baixar esta música"></button></div>`;
}

function versaoAtual(t) {
	const pref = t.preferred_video;
	const baixado = t.downloaded_video;
	let html = "";
	if (pref) {
		html += `<div class="versao-atual">${icon("pin")}<div><b>${esc(pref.label || pref.id)}</b><small>Escolhida por você</small></div>
			<button class="btn sm" data-a="auto">Voltar ao automático</button></div>`;
	}
	if (baixado) {
		html += `<div class="versao-atual">${icon("music")}<div><b>${esc(baixado.title || baixado.id)}</b><small>${esc(baixado.publisher || "")}${baixado.publisher ? " · " : ""}a que está baixada</small></div></div>`;
	}
	if (!html) html = `<p class="ajuda">Ainda sem versão escolhida. O CSVMusic procura sozinho no YouTube Music na hora de baixar.</p>`;
	return html;
}

function parteArquivo(t) {
	if (!t.file_path) return "";
	const q = t.quality;
	return `<section class="pn-sec" data-sec="arquivo"><h3>Arquivo</h3>
		<div class="arquivo">
			${q ? `<span class="qualidade${q.low ? " baixa" : ""}">${esc(q.label)}${q.low ? " · qualidade baixa" : ""}</span>` : ""}
			<code>${esc(t.file_path)}</code>
		</div>
		<button class="btn sm" data-a="finder">${icon("folder-open")}Mostrar no Finder</button>
	</section>`;
}

function parteErro(t) {
	const e = erroDa(t);
	if (!e && t.state !== "error") return "";
	const resumo = e?.summary || t.detail || "";
	const fazer = e?.advice || O_QUE_FAZER[t.state === "age_limit" ? "age_limit" : "error"];
	return `<section class="pn-sec" data-sec="erro"><h3>Erro</h3>
		${resumo ? `<p class="erro-resumo">${esc(resumo)}</p>` : ""}
		${e?.at ? `<p class="ajuda">Em ${esc(dataHora(e.at))}</p>` : ""}
		<p class="rot erro-rot">O que fazer</p><p class="ajuda">${esc(fazer)}</p>
		${e?.technical ? `<p class="rot erro-rot">Texto completo</p><div class="erro-txt">${esc(e.technical)}</div>` : ""}
	</section>`;
}

function montar(t) {
	const vol = Number(t.volume_gain || 0);
	return `<div class="pn-vivo">${parteViva(t)}</div>
	<section class="pn-sec" data-sec="versao"><h3>Versão do YouTube</h3>
		<div class="pn-versao-atual">${versaoAtual(t)}</div>
		<div class="alts" data-alts></div>
		<button class="btn sm" data-a="alternativas">${icon("list")}Ver outras versões</button>
		<div class="campo" style="margin:16px 0 0">
			<label for="pn-link">Colar um link do YouTube</label>
			<input id="pn-link" class="entrada" type="url" inputmode="url" placeholder="https://music.youtube.com/watch?v=…" autocomplete="off">
			<span class="ajuda">Achou a versão certa no YouTube? Cole o link aqui para conferir antes de usar.</span>
		</div>
		<div data-info></div>
	</section>
	<section class="pn-sec" data-sec="volume"><h3>Volume</h3>
		<div class="regua"><label for="pn-vol">Ajuste</label><input id="pn-vol" type="range" min="-12" max="12" step="1" value="${vol}"><output for="pn-vol">${vol > 0 ? "+" : ""}${vol} dB</output></div>
		<p class="ajuda">Para músicas mais altas ou mais baixas que as outras. Vale no próximo download desta música.</p>
	</section>
	<section class="pn-sec dados" data-sec="dados"><h3>Dados</h3>
		<div class="campo"><label for="pn-titulo">Título</label><input id="pn-titulo" class="entrada" value="${esc(t.title || "")}"></div>
		<div class="campo"><label for="pn-artistas">Artista</label><input id="pn-artistas" class="entrada" value="${esc(t.artists || "")}"></div>
		<div class="campo"><label for="pn-album">Álbum</label><input id="pn-album" class="entrada" value="${esc(t.album || "")}"></div>
		<button class="btn sm" data-a="salvar-dados" disabled>${icon("check")}Salvar dados</button>
	</section>
	<div data-arquivo>${parteArquivo(t)}</div>
	<div data-erro>${parteErro(t)}</div>`;
}

// ---------- Abrir e fechar ----------
export function abrirPainel(playlistId, track, { secao } = {}) {
	if (aberto && aberto.playlistId === playlistId && aberto.index === track.index) {
		if (secao) irPara(secao);
		return;
	}
	fecharPainel(false);
	const celular = matchMedia("(max-width: 760px)").matches;
	const veu = celular ? el(`<div class="veu"></div>`) : null;
	const caixa = el(`<aside class="painel" role="dialog" aria-label="Música" ${celular ? 'aria-modal="true"' : ""}>
		<div class="painel-cab"><span>Música</span><button class="btn ic limpo" data-a="fechar" aria-label="Fechar o painel">${icon("x")}</button></div>
		<div class="painel-corpo">${montar(track)}</div>
	</aside>`);
	const voltar = document.activeElement;
	aberto = { playlistId, index: track.index, track, caixa, veu, voltar, escolhido: null };
	aberto.tirar = empilhar(() => fecharPainel());
	if (veu) { veu.onclick = () => fecharPainel(); document.body.append(veu); }
	document.body.append(caixa);
	document.body.classList.add("painel-aberto");
	ligar(caixa);
	emit("painel");
	if (secao) irPara(secao);
	requestAnimationFrame(() => caixa.querySelector('[data-a="fechar"]').focus({ preventScroll: true }));
}

export function fecharPainel(devolverFoco = true) {
	if (!aberto) return;
	const a = aberto;
	aberto = null;
	a.tirar();
	a.caixa.remove();
	a.veu?.remove();
	document.body.classList.remove("painel-aberto");
	emit("painel");
	if (devolverFoco) {
		const row = document.querySelector(`.vbody .row[data-i="${a.index}"]`);
		(row || (document.contains(a.voltar) ? a.voltar : null))?.focus({ preventScroll: true });
	}
}

function irPara(secao) {
	const s = aberto?.caixa.querySelector(`[data-sec="${secao}"]`);
	if (!s) return;
	s.scrollIntoView({ block: "start" });
	if (secao === "versao") carregarAlternativas();
}

// ---------- Comportamento ----------
function ligar(caixa) {
	caixa.addEventListener("click", (ev) => {
		const b = ev.target.closest("[data-a]");
		if (!b || b.disabled) return;
		const t = aberto.track, pid = aberto.playlistId;
		switch (b.dataset.a) {
			case "fechar": fecharPainel(); break;
			case "aceitar": aceitar(); break;
			case "ir-versao": irPara("versao"); break;
			case "entrar": acoes.entrarNoYoutube(); break;
			case "baixar": acoes.baixarMusicas([[pid, t.index, t.key]]); break;
			case "rebaixar": mudar({ force_redownload: true }, "Vai baixar de novo no próximo download"); break;
			case "finder": acoes.abrirNoFinder("file", { playlist_id: pid, index: t.index, key: t.key }); break;
			case "ligar": mudar({ enabled: b.getAttribute("aria-checked") !== "true" }); break;
			case "auto": mudar({ preferred_video_url: "" }, "Voltou à versão automática"); break;
			case "alternativas": carregarAlternativas(); break;
			case "alt": escolherAlternativa(b); break;
			case "usar": usarEscolhido(); break;
			case "baixar-escolhido": baixarEscolhido(); break;
			case "salvar-dados": salvarDados(); break;
		}
	});
	const link = caixa.querySelector("#pn-link");
	const conferir = debounce(() => conferirLink(link.value.trim()), 400);
	link.addEventListener("input", conferir);
	link.addEventListener("paste", () => setTimeout(() => conferirLink(link.value.trim()), 0));
	const vol = caixa.querySelector("#pn-vol");
	pintarRegua(vol);
	const out = caixa.querySelector('output[for="pn-vol"]');
	const salvarVol = debounce(() => mudar({ volume_gain: Number(vol.value) }), 350);
	vol.addEventListener("input", () => { pintarRegua(vol); out.textContent = `${vol.value > 0 ? "+" : ""}${vol.value} dB`; salvarVol(); });
	const campos = ["pn-titulo", "pn-artistas", "pn-album"].map((id) => caixa.querySelector("#" + id));
	const btnDados = caixa.querySelector('[data-a="salvar-dados"]');
	campos.forEach((c) => c.addEventListener("input", () => { btnDados.disabled = !dadosMudaram(); }));
	campos.forEach((c) => c.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && dadosMudaram()) salvarDados(); }));
}

function dadosMudaram() {
	const t = aberto.track, c = aberto.caixa;
	return c.querySelector("#pn-titulo").value !== (t.title || "")
		|| c.querySelector("#pn-artistas").value !== (t.artists || "")
		|| c.querySelector("#pn-album").value !== (t.album || "");
}

async function mudar(corpo, ok) {
	const { playlistId, index } = aberto;
	try {
		const novo = await patch(`/playlists/${enc(playlistId)}/tracks/${index}`, { ...corpo, key: aberto.track.key });
		emit("track", { playlist_id: playlistId, track: novo });
		if (ok) aviso({ tom: "ok", titulo: ok });
	} catch (e) {
		erro(e, "Não deu para salvar");
		if (aberto) atualizarVivo(aberto.track);
	}
}

async function aceitar() {
	const { playlistId, index } = aberto;
	try {
		const novo = await post(`/playlists/${enc(playlistId)}/tracks/${index}/accept`, { key: aberto.track.key });
		emit("track", { playlist_id: playlistId, track: novo });
	} catch (e) { erro(e, "Não deu para aceitar"); }
}

async function salvarDados() {
	const c = aberto.caixa;
	await mudar({
		title: c.querySelector("#pn-titulo").value.trim(),
		artists: c.querySelector("#pn-artistas").value.trim(),
		album: c.querySelector("#pn-album").value.trim(),
	}, "Dados salvos");
	if (aberto) c.querySelector('[data-a="salvar-dados"]').disabled = !dadosMudaram();
}

// Alternativas do YouTube Music (com brilho enquanto chegam).
async function carregarAlternativas() {
	const caixa = aberto.caixa;
	const lista = caixa.querySelector("[data-alts]");
	const botao = caixa.querySelector('[data-a="alternativas"]');
	if (lista.dataset.estado === "pronto" || lista.dataset.estado === "pedindo") return;
	lista.dataset.estado = "pedindo";
	botao.hidden = true;
	lista.innerHTML = [68, 54, 76, 60].map((w) => `<div class="alt sh-alt" aria-hidden="true"><b>${sh(w + "%")}</b><span class="dur">${sh("2.4em")}</span><small>${sh(w / 2 + "%")}</small></div>`).join("");
	const { playlistId, index } = aberto;
	try {
		const r = await get(`/playlists/${enc(playlistId)}/tracks/${index}/alternatives` + qs({ key: aberto.track.key }));
		if (!aberto || aberto.index !== index) return;
		lista.dataset.estado = "pronto";
		const ops = r.options || [];
		if (!ops.length) { lista.innerHTML = `<p class="ajuda">O YouTube Music não trouxe outras versões. Cole um link abaixo.</p>`; return; }
		lista.setAttribute("role", "radiogroup");
		lista.setAttribute("aria-label", "Outras versões");
		lista.innerHTML = ops.map((o, i) => {
			const marcas = [];
			marcas.push(`<span class="marcador neutro">${o.source === "videos" ? "Vídeo do YouTube" : "YouTube Music"}</span>`);
			if (o.duration_mismatch) marcas.push(`<span class="marcador">Duração diferente</span>`);
			for (const v of o.version_markers || []) marcas.push(`<span class="marcador">${esc(v)}</span>`);
			return `<button class="alt" role="radio" aria-checked="false" data-a="alt" data-i="${i}">
				<b>${esc(o.title)}</b><span class="dur">${segundos(o.duration_seconds)}</span>
				<small>${esc(o.author || "")}${o.album ? ` · ${esc(o.album)}` : ""}</small>
				<span class="marcas">${marcas.join("")}</span></button>`;
		}).join("") + `<div class="botoes-2" data-escolha hidden>
			<button class="btn" data-a="usar">${icon("pin")}Usar esta versão</button>
			<button class="btn pri" data-a="baixar-escolhido">${icon("download")}Baixar agora</button></div>`;
		lista._ops = ops;
	} catch (e) {
		if (e.dados?.code === "track_moved") { erro(e, "Não deu para buscar outras versões"); return; }
		lista.dataset.estado = "";
		lista.innerHTML = `<p class="erro-campo">${esc(e.message)}</p>`;
		botao.hidden = false;
		botao.innerHTML = `${icon("refresh-cw")}Tentar de novo`;
	}
}

function escolherAlternativa(b) {
	const lista = aberto.caixa.querySelector("[data-alts]");
	lista.querySelectorAll(".alt").forEach((x) => x.setAttribute("aria-checked", x === b));
	const o = lista._ops[Number(b.dataset.i)];
	aberto.escolhido = { id: o.videoId, rotulo: o.title };
	const ac = lista.querySelector("[data-escolha]");
	ac.hidden = false;
	b.after(ac);
}

async function usarEscolhido() {
	if (!aberto?.escolhido) return;
	await mudar({ preferred_video_url: linkDoVideo(aberto.escolhido.id), preferred_video_label: aberto.escolhido.rotulo || undefined }, "Versão escolhida");
}

async function baixarEscolhido() {
	if (!aberto?.escolhido) return;
	const { playlistId, index } = aberto;
	try {
		const job = await post(`/playlists/${enc(playlistId)}/tracks/${index}/download-now`, { video_id: aberto.escolhido.id, key: aberto.track.key });
		if (job && "kind" in job) { store.job = job; emit("job"); }
		aviso({ tom: "ok", titulo: "Baixando esta versão", texto: "Ela também fica guardada como a escolha desta música." });
	} catch (e) { erro(e, "Não deu para baixar"); }
}

// Link colado: GET /api/video-info e mostra os avisos do motor.
let pedidoLink = 0;
async function conferirLink(url) {
	const box = aberto.caixa.querySelector("[data-info]");
	const meu = ++pedidoLink;
	if (!url) { box.innerHTML = ""; return; }
	box.innerHTML = `<div class="info-video" aria-busy="true"><b>${sh("70%")}</b><small>${sh("40%")}</small>
		<ul class="alertas"><li>${sh("16px", "sh-blk")}<span>${sh("85%")}</span></li></ul></div>`;
	const { playlistId, index } = aberto;
	try {
		const r = await get("/video-info" + qs({ url, playlist_id: playlistId, index, key: aberto.track.key }));
		if (meu !== pedidoLink || !aberto) return;
		const i = r.info || {};
		const tipos = { song: "Música do YouTube Music", video: "Vídeo do YouTube", podcast: "Episódio de podcast" };
		const avisos = r.warnings || [];
		aberto.escolhido = { id: r.video_id, rotulo: i.title };
		box.innerHTML = `<div class="info-video">
			<b>${esc(i.title || r.video_id)}</b>
			<small>${[i.author, segundos(i.duration_seconds), tipos[i.kind] || ""].filter(Boolean).map(esc).join(" · ")}</small>
			<ul class="alertas">${avisos.length
				? avisos.map((w) => `<li>${icon("triangle-alert")}<span>${esc(w)}</span></li>`).join("")
				: `<li class="ok">${icon("circle-check")}<span>Nada de estranho com este link.</span></li>`}</ul>
			<div class="botoes-2">
				<button class="btn" data-a="usar" ${i.playable === false ? "disabled" : ""}>${icon("pin")}Usar esta versão</button>
				<button class="btn pri" data-a="baixar-escolhido" ${i.playable === false ? "disabled" : ""}>${icon("download")}Baixar agora</button>
			</div></div>`;
	} catch (e) {
		if (meu !== pedidoLink) return;
		if (e.dados?.code === "track_moved") { erro(e, "Não deu para conferir o link"); return; }
		box.innerHTML = `<p class="erro-campo" style="margin-top:8px">${esc(e.message)}</p>`;
	}
}

function atualizarVivo(t) {
	const c = aberto.caixa;
	const foco = document.activeElement && c.querySelector(".pn-vivo").contains(document.activeElement) ? document.activeElement.dataset.a : null;
	c.querySelector(".pn-vivo").innerHTML = parteViva(t);
	c.querySelector(".pn-versao-atual").innerHTML = versaoAtual(t);
	c.querySelector("[data-arquivo]").innerHTML = parteArquivo(t);
	c.querySelector("[data-erro]").innerHTML = parteErro(t);
	if (foco) c.querySelector(`.pn-vivo [data-a="${foco}"]`)?.focus();
}

on("track", ({ playlist_id, track }) => {
	if (!aberto || aberto.playlistId !== playlist_id || aberto.index !== track.index) return;
	aberto.track = track;
	atualizarVivo(track);
	const c = aberto.caixa;
	if (!dadosMudaram()) {
		c.querySelector("#pn-titulo").value = track.title || "";
		c.querySelector("#pn-artistas").value = track.artists || "";
		c.querySelector("#pn-album").value = track.album || "";
	}
});
on("job", () => {
	if (!aberto) return;
	const j = store.job;
	if (j?.kind === "download" && j.current?.playlist_id === aberto.playlistId && j.current?.index === aberto.index) {
		const est = aberto.caixa.querySelector(".pn-situacao .estado");
		const e = estado(aberto.track, j);
		if (est) est.innerHTML = `${icon(e.icone)}${esc(e.texto)}`;
	}
});
on("removida", (id) => { if (aberto?.playlistId === id) fecharPainel(false); });
// Nova análise mudou a lista desta playlist: o índice do painel pode ser de outra música agora.
on("tracks_changed", ({ playlist_id }) => {
	if (aberto?.playlistId !== playlist_id) return;
	fecharPainel(false);
	aviso({ tom: "info", titulo: "A playlist mudou", texto: "A análise trouxe a lista nova. Abra a música de novo." });
});
on("musica-mudou", () => fecharPainel(false));
