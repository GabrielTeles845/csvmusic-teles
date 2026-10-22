// Tema antes do primeiro desenho, para não piscar. Arquivo à parte: a CSP não aceita <script> embutido.
try {
	var t = localStorage.getItem("csvmusic-tema");
	if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) { /* sem armazenamento */ }
