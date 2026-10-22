// Estado da tela, vindo de GET /api/state e atualizado pelos eventos.
// Regra do contrato: nada de regra de negócio aqui; só guardar o que o motor manda.

export const store = {
	carregado: false,
	erro: null,
	version: "",
	library: null,
	playlists: new Map(),
	ordem: [],
	job: { kind: null },
	account: null,
	firstRun: false,
	selecionada: null,
	conectado: true,
	// Depois de um download com restrição de idade: {quantas} ou {pronto: n}.
	idade: null,
};

const ouvintes = new Map();
export function on(tipo, fn) {
	if (!ouvintes.has(tipo)) ouvintes.set(tipo, new Set());
	ouvintes.get(tipo).add(fn);
	return () => ouvintes.get(tipo).delete(fn);
}
export function emit(tipo, dado) {
	for (const fn of ouvintes.get(tipo) || []) fn(dado);
}

export function aplicarEstado(st) {
	store.carregado = true;
	store.erro = null;
	store.version = st.version || "";
	store.library = st.library || null;
	store.playlists = new Map((st.playlists || []).map((p) => [p.id, p]));
	store.ordem = (st.playlists || []).map((p) => p.id);
	store.job = st.job || { kind: null };
	store.account = st.account || null;
	store.firstRun = !!st.first_run;
	emit("estado");
}

export const playlistsEmOrdem = () => store.ordem.map((id) => store.playlists.get(id)).filter(Boolean);
export const atual = () => (store.selecionada ? store.playlists.get(store.selecionada) : null);
