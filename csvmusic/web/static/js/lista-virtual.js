// Lista virtual: só as linhas visíveis existem no DOM; páginas de 100 pedidas conforme rola.
// Atualizar uma música troca só aquela linha.

const PAGINA = 100;
const SOBRA = 8; // linhas a mais acima e abaixo da área visível
const BRILHO_INICIAL = 8; // antes do primeiro total: o que cabe na primeira dobra

// Troca o elemento da linha sem perder o foco de quem está nela (teclado).
function trocar(velho, novo) {
	const ativo = document.activeElement;
	const tinha = ativo && velho.contains(ativo);
	const chave = tinha ? ativo.dataset.k : null;
	velho.replaceWith(novo);
	if (tinha) ((chave && novo.querySelector(`[data-k="${chave}"]`)) || novo).focus({ preventScroll: true });
	return novo;
}

export class ListaVirtual {
	constructor({ rolagem, caixa, buscar, linha, brilho, vazio, falha, aoReceber }) {
		Object.assign(this, { rolagem, caixa, buscar, linha, brilho, vazio, falha, aoReceber });
		this.paginas = new Map();
		this.posicao = new Map(); // índice da música -> posição na lista filtrada
		this.linhas = new Map(); // posição -> elemento
		this.total = null;
		this.geracao = 0;
		this.erro = null;
		this._quadro = 0;
		this._rolar = () => this.agendar();
		this._tamanho = () => { this.rh = null; this.redesenharTudo(); };
		rolagem.addEventListener("scroll", this._rolar, { passive: true });
		addEventListener("resize", this._tamanho);
	}

	destruir() {
		this.geracao++;
		this.rolagem.removeEventListener("scroll", this._rolar);
		removeEventListener("resize", this._tamanho);
		cancelAnimationFrame(this._quadro);
	}

	alturaLinha() {
		if (!this.rh) this.rh = parseFloat(getComputedStyle(this.caixa).getPropertyValue("--rh")) || 52;
		return this.rh;
	}

	iniciar() {
		this.geracao++;
		this.paginas.clear();
		this.posicao.clear();
		this.total = null;
		this.erro = null;
		this.redesenharTudo();
		this.pedir(0);
	}

	agendar() {
		cancelAnimationFrame(this._quadro);
		this._quadro = requestAnimationFrame(() => this.desenhar());
	}

	redesenharTudo() {
		for (const e of this.linhas.values()) e.remove();
		this.linhas.clear();
		this.caixa.querySelector(":scope > .lista-msg")?.remove();
		this.desenhar();
	}

	item(pos) {
		const pg = this.paginas.get(Math.floor(pos / PAGINA));
		return Array.isArray(pg) ? pg[pos % PAGINA] : undefined;
	}

	async pedir(p) {
		if (this.paginas.has(p)) return;
		const g = this.geracao;
		this.paginas.set(p, "pedindo");
		try {
			const r = await this.buscar(p * PAGINA, PAGINA);
			if (g !== this.geracao) return;
			this.paginas.set(p, r.items || []);
			(r.items || []).forEach((t, i) => this.posicao.set(t.index, p * PAGINA + i));
			const mudouTotal = this.total !== r.total;
			this.total = r.total;
			this.aoReceber?.(r);
			if (mudouTotal) this.redesenharTudo();
			else this.trocarPagina(p);
		} catch (e) {
			if (g !== this.geracao) return;
			this.paginas.delete(p);
			if (this.total === null) { this.erro = e; this.redesenharTudo(); }
		}
	}

	trocarPagina(p) {
		for (const [pos, e] of this.linhas) {
			if (Math.floor(pos / PAGINA) !== p) continue;
			this.linhas.set(pos, trocar(e, this.montar(pos)));
		}
	}

	montar(pos) {
		const it = this.item(pos);
		const e = it ? this.linha(it, pos) : this.brilho(pos);
		e.style.top = pos * this.alturaLinha() + "px";
		return e;
	}

	desenhar() {
		const rh = this.alturaLinha();
		if (this.erro) {
			this.caixa.style.height = "auto";
			if (!this.caixa.querySelector(":scope > .lista-msg")) this.caixa.append(this.falha(this.erro, () => this.iniciar()));
			return;
		}
		if (this.total === 0) {
			this.caixa.style.height = "auto";
			if (!this.caixa.querySelector(":scope > .lista-msg")) this.caixa.append(this.vazio());
			return;
		}
		const total = this.total ?? BRILHO_INICIAL;
		this.caixa.style.height = total * rh + "px";
		const topo = this.caixa.getBoundingClientRect().top - this.rolagem.getBoundingClientRect().top;
		const ini = Math.max(0, Math.floor(-topo / rh) - SOBRA);
		const fim = Math.min(total - 1, Math.ceil((this.rolagem.clientHeight - topo) / rh) + SOBRA);
		for (const [pos, e] of this.linhas) {
			if (pos < ini || pos > fim) { e.remove(); this.linhas.delete(pos); }
		}
		const frag = document.createDocumentFragment();
		for (let pos = ini; pos <= fim; pos++) {
			if (this.linhas.has(pos)) continue;
			const e = this.montar(pos);
			this.linhas.set(pos, e);
			frag.append(e);
		}
		this.caixa.append(frag);
		if (this.total !== null) {
			for (let p = Math.floor(ini / PAGINA); p <= Math.floor(fim / PAGINA); p++) this.pedir(p);
		}
	}

	// Uma música mudou (evento `track` ou resposta de PATCH): troca só a linha dela.
	atualizar(track) {
		const pos = this.posicao.get(track.index);
		if (pos === undefined) return false;
		const pg = this.paginas.get(Math.floor(pos / PAGINA));
		if (!Array.isArray(pg)) return false;
		pg[pos % PAGINA] = track;
		const velho = this.linhas.get(pos);
		if (velho) {
			this.linhas.set(pos, trocar(velho, this.montar(pos)));
		}
		return true;
	}

	porIndice(indice) {
		const pos = this.posicao.get(indice);
		return pos === undefined ? undefined : this.item(pos);
	}

	elementoDe(indice) {
		const pos = this.posicao.get(indice);
		return pos === undefined ? null : this.linhas.get(pos) || null;
	}

	// Redesenha as linhas que estão na tela (ex.: porcentagem do download mudou).
	redesenharVisiveis(filtro) {
		for (const [pos, e] of this.linhas) {
			const it = this.item(pos);
			if (!it || (filtro && !filtro(it))) continue;
			this.linhas.set(pos, trocar(e, this.montar(pos)));
		}
	}
}
