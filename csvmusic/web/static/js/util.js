// Peças pequenas usadas em toda a tela: escapar texto, ícones, números e datas em pt-BR.
import { capaAttrs } from "./api.js";

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

// Ícones Lucide (lucide-static 0.460.0, ISC) num arquivo só: static/icons/lucide.svg.
export const icon = (nome, cls = "i") =>
	`<svg class="${cls}" aria-hidden="true" focusable="false"><use href="/static/icons/lucide.svg#${nome}"/></svg>`;

export function el(html) {
	const t = document.createElement("template");
	t.innerHTML = html.trim();
	return t.content.firstElementChild;
}

const NF = new Intl.NumberFormat("pt-BR");
export const n = (v) => NF.format(v ?? 0);

export function duracao(ms) {
	if (ms === null || ms === undefined) return "";
	const s = Math.round(ms / 1000);
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	const ss = String(s % 60).padStart(2, "0");
	return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export const segundos = (s) => (s === null || s === undefined ? "" : duracao(s * 1000));

const HORA = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const DATA = new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
export const hora = (iso) => (iso ? HORA.format(new Date(iso)) : "");
export const dataHora = (iso) => (iso ? DATA.format(new Date(iso)) : "");

export const plural = (q, um, varios) => `${n(q)} ${q === 1 ? um : varios}`;

export function debounce(fn, ms) {
	let t;
	return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const PLATAFORMAS = {
	spotify: "Spotify", apple: "Apple Music", apple_music: "Apple Music", deezer: "Deezer",
	ytmusic: "YouTube Music", youtube_music: "YouTube Music", youtube: "YouTube", amazon: "Amazon Music",
	amazon_music: "Amazon Music", csv: "Planilha",
};
export const plataforma = (p) => PLATAFORMAS[p] || (p ? p[0].toUpperCase() + p.slice(1) : "");

const TIPOS = { playlist: "Playlist", album: "Álbum", artist: "Artista", liked: "Músicas curtidas" };
export function tipoDaPlaylist(pl) {
	if (pl.platform === "csv" || pl.source_type === "csv") return "Planilha";
	return `${TIPOS[pl.source_type] || "Playlist"} do ${plataforma(pl.platform)}`;
}

// Situação de cada música: rótulo, ícone e tom (cor). docs/fork/14 §4, Track.state.
const ESTADOS = {
	downloaded: ["Baixada", "check", "ok"],
	missing: ["Faltando", "circle-dashed", "mut"],
	review: ["Revisar", "circle-alert", "rev"],
	error: ["Com erro", "circle-x", "err"],
	age_limit: ["Restrição de idade", "lock", "err"],
	not_found: ["Não encontrada", "search-x", "err"],
	redownload: ["Vai baixar de novo", "refresh-cw", "mut"],
	queued: ["Na fila", "clock", "mut"],
	matching: ["Procurando", "search", "dl"],
	downloading: ["Baixando", "download", "dl"],
	tagging: ["Finalizando", "tag", "dl"],
	disabled: ["Desmarcada", "circle-minus", "mut"],
};
export function estado(track, job) {
	const [rotulo, ic, tom] = ESTADOS[track.state] || [track.state || "", "circle-dashed", "mut"];
	let texto = rotulo;
	if (track.state === "downloading" && job?.kind === "download" && job.current?.index === track.index
		&& typeof job.current.percent === "number") texto = `Baixando ${Math.round(job.current.percent)}%`;
	return { texto, icone: ic, tom };
}

// Mosaico 2×2 das capas (ou uma capa, ou a inicial).
// A assinatura (data-mosaico) diz quando o mosaico mudou de verdade, sem comparar o src.
export const assinaturaMosaico = (pl) => `${(pl.cover_urls || []).join("|")}#${pl.access_error || ""}#${(pl.name || "").charAt(0)}`;

export function mosaico(pl, extra = "") {
	const capas = (pl.cover_urls || []).filter(Boolean);
	extra += `" data-mosaico="${esc(assinaturaMosaico(pl))}`;
	if (capas.length >= 4) {
		return `<div class="pm ${extra}">${capas.slice(0, 4).map((u) => `<img ${capaAttrs(u)} alt="" decoding="async">`).join("")}</div>`;
	}
	if (capas.length) return `<div class="pm um ${extra}"><img ${capaAttrs(capas[0])} alt="" decoding="async"></div>`;
	if (pl.access_error) return `<span class="pm vazio ${extra}">${icon("lock")}</span>`;
	const ini = (pl.name || "?").trim().charAt(0).toUpperCase() || "?";
	return `<span class="pm vazio ${extra}">${esc(ini)}</span>`;
}

// Frase curta da playlist na lateral: "Spotify · 912 de 1.124".
export function resumoLateral(pl, job) {
	const origem = pl.platform === "csv" ? "Planilha" : plataforma(pl.platform);
	if (job?.kind === "scan" && job.playlist_id === pl.id) return `${origem} · Analisando`;
	if (pl.access_error === "private") return `${origem} · Particular`;
	if (pl.access_error) return `${origem} · Sem acesso`;
	if (pl.scan_state === "never") return `${origem} · Não analisada`;
	const c = pl.counts || {};
	return `${origem} · ${n(c.downloaded)} de ${n(c.total)}`;
}
