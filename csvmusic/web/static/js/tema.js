// Tema: segue o sistema ou a escolha dos Ajustes. Guardado também no navegador
// para a tela abrir já no tema certo, antes de os ajustes chegarem.
export function aplicarTema(tema) {
	const raiz = document.documentElement;
	if (tema === "light" || tema === "dark") raiz.dataset.theme = tema;
	else delete raiz.dataset.theme;
	try { localStorage.setItem("csvmusic-tema", tema || "system"); } catch { /* sem armazenamento */ }
}
