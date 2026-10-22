// Conversa com o servidor local (docs/fork/14 §3–5).
// Toda chamada leva o cabeçalho X-CSVMusic-Token; o EventSource e as imagens levam ?token=.

const TOKEN = document.querySelector('meta[name="csvmusic-token"]')?.content || "";
const params = new URLSearchParams(location.search);

// Para conferir os estados da tela sem mexer no código:
// ?carregando (nada responde), ?lento (2 s de espera), ?erro (toda chamada falha).
export const modo = {
	carregando: params.has("carregando"),
	lento: params.has("lento"),
	erro: params.has("erro"),
};

export class ApiError extends Error {
	constructor(message, status, dados = null) {
		super(message);
		this.status = status;
		this.dados = dados; // corpo inteiro do erro (ex.: needs_confirmation)
	}
}

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

export async function api(method, path, body) {
	if (modo.carregando) return new Promise(() => {});
	if (modo.lento) await esperar(2000);
	if (modo.erro) throw new ApiError("O CSVMusic não respondeu. Ele pode ter sido fechado.", 0);
	const headers = { "X-CSVMusic-Token": TOKEN };
	const init = { method, headers };
	if (body !== undefined) {
		headers["Content-Type"] = "application/json";
		init.body = JSON.stringify(body);
	}
	let res;
	try {
		res = await fetch("/api" + path, init);
	} catch {
		throw new ApiError("O CSVMusic não respondeu. Ele pode ter sido fechado.", 0);
	}
	let data = null;
	try { data = await res.json(); } catch { /* resposta sem corpo */ }
	if (!res.ok) throw new ApiError((data && data.error) || `Algo deu errado (código ${res.status}).`, res.status, data);
	return data;
}

export const get = (path) => api("GET", path);
export const post = (path, body = {}) => api("POST", path, body);
export const patch = (path, body) => api("PATCH", path, body);
export const del = (path) => api("DELETE", path);

export function qs(obj) {
	const p = new URLSearchParams();
	for (const [k, v] of Object.entries(obj)) if (v !== undefined && v !== null && v !== "") p.set(k, v);
	const s = p.toString();
	return s ? "?" + s : "";
}

export const enc = encodeURIComponent;

// Capas pelo próprio servidor (/api/image, com cache em disco). O servidor exige o cabeçalho do
// token também ali, e <img> não manda cabeçalho: a página busca com fetch e usa um blob: (a CSP
// libera img-src blob:). O <img> nasce com data-capa="<url>" e este observador põe o src.
const capas = new Map(); // url -> Promise<blobURL|"">
const prontas = new Map(); // url -> blobURL (para a linha redesenhada já nascer com a capa)
const fila = [];
let rodando = 0;
const MAX_JUNTAS = 6;

function proxima() {
	while (rodando < MAX_JUNTAS && fila.length) {
		const { url, resolve } = fila.shift();
		rodando++;
		fetch(`/api/image?url=${enc(url)}`, { headers: { "X-CSVMusic-Token": TOKEN } })
			.then((r) => (r.ok ? r.blob() : null))
			.then((b) => { const u = b ? URL.createObjectURL(b) : ""; if (u) prontas.set(url, u); resolve(u); })
			.catch(() => resolve(""))
			.finally(() => { rodando--; proxima(); });
	}
}

export function capa(url) {
	if (!url || modo.carregando || modo.erro) return Promise.resolve("");
	if (!capas.has(url)) capas.set(url, new Promise((resolve) => { fila.push({ url, resolve }); proxima(); }));
	return capas.get(url);
}

function pintarCapa(img) {
	const url = img.dataset.capa;
	if (!url || img.dataset.capaPosta === url) return;
	img.dataset.capaPosta = url;
	capa(url).then((src) => { if (src && img.dataset.capa === url) img.src = src; });
}

new MutationObserver((mudancas) => {
	for (const m of mudancas) for (const n of m.addedNodes) {
		if (n.nodeType !== 1) continue;
		if (n.matches("img[data-capa]")) pintarCapa(n);
		n.querySelectorAll?.("img[data-capa]").forEach(pintarCapa);
	}
}).observe(document.documentElement, { childList: true, subtree: true });

// Atributos de um <img> de capa: data-capa e, se já estiver pronta, o src direto.
export function capaAttrs(url) {
	const a = (v) => String(v).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
	if (!url) return "";
	const pronta = prontas.get(url);
	return pronta ? `data-capa="${a(url)}" data-capa-posta="${a(url)}" src="${a(pronta)}"` : `data-capa="${a(url)}"`;
}

// Baixa a planilha com o cabeçalho do token e entrega como arquivo.
export async function baixarArquivo(path, nomePadrao) {
	if (modo.carregando) return;
	const res = await fetch("/api" + path, { headers: { "X-CSVMusic-Token": TOKEN } });
	if (!res.ok) {
		let msg = `Algo deu errado (código ${res.status}).`;
		try { msg = (await res.json()).error || msg; } catch { /* sem corpo */ }
		throw new ApiError(msg, res.status);
	}
	const blob = await res.blob();
	const disp = res.headers.get("Content-Disposition") || "";
	const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disp);
	const nome = m ? decodeURIComponent(m[1]) : nomePadrao;
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = nome;
	document.body.append(a);
	a.click();
	setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

const TIPOS = ["playlist", "playlists", "track", "job", "scan_done", "download_done", "log", "warning",
	"account", "age_retry_ready", "device", "library", "menu"];

// Liga os eventos do servidor. Reconecta sozinho (EventSource) e avisa quando cai.
export function eventos(handlers, aoMudarConexao) {
	if (modo.carregando || modo.erro) return null;
	const es = new EventSource(`/api/events?token=${enc(TOKEN)}`);
	for (const tipo of TIPOS) {
		es.addEventListener(tipo, (ev) => {
			let data = null;
			try { data = JSON.parse(ev.data); } catch { return; }
			handlers[tipo]?.(data);
		});
	}
	es.onopen = () => aoMudarConexao?.(true);
	es.onerror = () => aoMudarConexao?.(false);
	return es;
}
