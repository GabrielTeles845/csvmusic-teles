// Adicionar playlist (⌘N): aba Link (aceita vários, um por linha) e aba Planilha.
import { post } from "./api.js";
import { emit } from "./store.js";
import { esc, icon, n } from "./util.js";
import { dialogo, aviso } from "./ui.js";

let atual = null;

export function abrirAdicionar(aba = "link") {
	if (atual && !atual.fechado) { trocarAba(aba); return; }
	const d = dialogo({
		titulo: "Adicionar playlist",
		corpo: `<div class="abas" role="tablist" aria-label="Como adicionar">
				<button class="aba" role="tab" data-aba="link" aria-selected="true">${icon("link")}Link</button>
				<button class="aba" role="tab" data-aba="planilha" aria-selected="false">${icon("file-spreadsheet")}Planilha</button>
			</div>
			<div data-painel="link">
				<div class="campo">
					<label for="add-links">Link da playlist</label>
					<textarea id="add-links" class="area" rows="4" placeholder="Cole o link aqui. Para adicionar várias, um link por linha." autofocus></textarea>
					<span class="ajuda">Spotify, Apple Music, Deezer, YouTube Music e Amazon Music. Também serve álbum.</span>
				</div>
				<div data-erros></div>
			</div>
			<div data-painel="planilha" hidden>
				<div class="campo">
					<span class="rot">Arquivo</span>
					<div class="linha-campo">
						<span class="caminho vazio" data-arquivo>Nenhum arquivo escolhido</span>
						<button class="btn" data-escolher>${icon("file-up")}Escolher…</button>
					</div>
					<input type="file" accept=".csv,text/csv" data-file hidden>
					<span class="ajuda">Planilha .csv com as colunas de música, artista e álbum (a do Exportify serve).</span>
				</div>
				<div class="campo">
					<label for="add-nome">Nome da playlist</label>
					<input id="add-nome" class="entrada" placeholder="Se ficar em branco, usa o nome do arquivo">
				</div>
				<div data-erros-csv></div>
			</div>`,
		pe: `<button class="btn" data-cancelar>Cancelar</button><button class="btn pri" data-ok disabled>${icon("plus")}Adicionar</button>`,
		aoFechar: () => { atual = null; },
	});
	atual = d;
	atual.aba = "link";
	atual.arquivo = null;
	const c = d.corpo;
	const ok = d.pe.querySelector("[data-ok]");
	d.pe.querySelector("[data-cancelar]").onclick = () => d.fechar();
	c.querySelectorAll("[data-aba]").forEach((b) => b.addEventListener("click", () => trocarAba(b.dataset.aba)));
	const links = c.querySelector("#add-links");
	links.addEventListener("input", () => { if (atual.aba === "link") ok.disabled = !lerLinks().length; });
	links.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey) && !ok.disabled) ok.click(); });
	const file = c.querySelector("[data-file]");
	c.querySelector("[data-escolher]").onclick = () => file.click();
	file.addEventListener("change", () => {
		const f = file.files[0];
		atual.arquivo = f || null;
		const caminho = c.querySelector("[data-arquivo]");
		caminho.textContent = f ? f.name : "Nenhum arquivo escolhido";
		caminho.classList.toggle("vazio", !f);
		if (atual.aba === "planilha") ok.disabled = !f;
	});
	ok.onclick = () => (atual.aba === "link" ? enviarLinks() : enviarPlanilha());
	trocarAba(aba);
}

function trocarAba(aba) {
	const c = atual.corpo;
	atual.aba = aba;
	c.querySelectorAll("[data-aba]").forEach((b) => b.setAttribute("aria-selected", b.dataset.aba === aba));
	c.querySelectorAll("[data-painel]").forEach((p) => { p.hidden = p.dataset.painel !== aba; });
	const ok = atual.pe.querySelector("[data-ok]");
	ok.disabled = aba === "link" ? !lerLinks().length : !atual.arquivo;
	(aba === "link" ? c.querySelector("#add-links") : c.querySelector("[data-escolher]")).focus();
}

function lerLinks() {
	return atual.corpo.querySelector("#add-links").value.split(/\s+/).map((s) => s.trim()).filter(Boolean);
}

async function enviarLinks() {
	const d = atual;
	const ok = d.pe.querySelector("[data-ok]");
	const urls = lerLinks();
	ok.disabled = true;
	ok.innerHTML = `${icon("plus")}Adicionando`;
	try {
		const r = await post("/playlists", { urls });
		const erros = r.errors || [];
		const novas = r.added || [];
		for (const w of r.warnings || []) aviso({ tom: "rev", titulo: "Atenção", texto: w, tempo: 12000 });
		if (novas.length) {
			emit("adicionadas", novas);
			aviso({ tom: "ok", titulo: novas.length === 1 ? "Playlist adicionada" : `${n(novas.length)} playlists adicionadas`, texto: "A análise começa sozinha." });
		}
		if (!erros.length) { d.fechar(); return; }
		const area = d.corpo.querySelector("#add-links");
		area.value = erros.map((e) => e.url).join("\n");
		d.corpo.querySelector("[data-erros]").innerHTML = `<ul class="alertas">${erros.map((e) =>
			`<li>${icon("triangle-alert")}<span><b>${esc(e.url)}</b><br>${esc(e.error)}</span></li>`).join("")}</ul>`;
	} catch (e) {
		d.corpo.querySelector("[data-erros]").innerHTML = `<p class="erro-campo">${esc(e.message)}</p>`;
	} finally {
		if (!d.fechado) { ok.innerHTML = `${icon("plus")}Adicionar`; ok.disabled = !lerLinks().length; }
	}
}

function base64(arquivo) {
	return new Promise((resolve, reject) => {
		const r = new FileReader();
		r.onload = () => resolve(String(r.result).split(",")[1] || "");
		r.onerror = () => reject(new Error("Não deu para ler o arquivo."));
		r.readAsDataURL(arquivo);
	});
}

async function enviarPlanilha() {
	const d = atual;
	const ok = d.pe.querySelector("[data-ok]");
	const f = d.arquivo;
	if (!f) return;
	ok.disabled = true;
	const caixaErro = d.corpo.querySelector("[data-erros-csv]");
	caixaErro.innerHTML = "";
	try {
		const content_base64 = await base64(f);
		const name = d.corpo.querySelector("#add-nome").value.trim() || undefined;
		const r = await post("/playlists/import-csv", { filename: f.name, content_base64, name });
		emit("adicionadas", r.added || []);
		const avisos = r.warnings || [];
		aviso({ tom: avisos.length ? "rev" : "ok", titulo: "Planilha importada", texto: avisos.join(" ") });
		d.fechar();
	} catch (e) {
		caixaErro.innerHTML = `<p class="erro-campo">${esc(e.message)}</p>`;
		ok.disabled = false;
	}
}

