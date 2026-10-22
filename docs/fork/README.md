# CSVMusic — guia do fork pessoal

Documentação completa do **CSVMusic v1.7.9** (https://github.com/angall1/CSVMusic): o que existe hoje, o que está quebrado ou estranho, e como transformar num app seu — mais rápido, mais confiável, bonito, em português e rodando sozinho no Mac.

Escrita em 22/10/2026 a partir da leitura do código inteiro (~25 mil linhas) e do log/biblioteca reais de uso (playlist "Out Of Time Man", 1.124 músicas).

---

## Como usar esta pasta

1. Copie esta pasta para o Mac.
2. Siga o **`01-setup-mac.md`** (instalar ferramentas, criar o fork, rodar o app).
3. Copie esta pasta para dentro do fork como `docs/fork/` e o **`CLAUDE.md`** para a raiz do fork.
4. Abra o Claude Code na raiz do fork e cole o primeiro prompt do **`11-prompts-prontos.md`**.
5. Siga o **`10-roadmap.md`**, uma fase por vez.

---

## Índice

| Arquivo | Conteúdo | Quando ler |
|---|---|---|
| `CLAUDE.md` | Instruções que o Claude Code lê sozinho a cada sessão | vai na raiz do fork |
| `01-setup-mac.md` | Homebrew, Python, ffmpeg, Deno, Claude Code, fork, rodar do código, manter atualizado | primeiro |
| `02-claude-md.md` | O que é o CLAUDE.md, hierarquia, settings, hooks, skills, fluxo de trabalho | primeiro |
| `03-arquitetura-geral.md` | Mapa do repositório, dependências, startup, threads, onde ficam os dados, testes, CI | antes de qualquer mudança |
| `04-busca-download-e-tags.md` | Algoritmo de busca com pesos, yt-dlp, perfis anti-bloqueio, tags, "já baixado", 32 bugs | fases 1, 4, 5 |
| `05-importacao-de-playlists.md` | Todos os importadores, formato da música, **causa do travamento na playlist grande** | fases 1, 2 |
| `06-interface-design-e-idiomas.md` | Inventário da UI, por que é "feia", redesign, plano de idiomas pt/en/es | fase 7 |
| `07-biblioteca-missing-e-sync.md` | Library Mode, **por que aparece "missing"**, índice de arquivos, sync com aparelhos, modo "sempre rodando" | fases 1, 3, 8 |
| `08-licenca-e-fork.md` | O projeto **não tem licença**: o que pode, o que trocar no fork | antes de publicar algo |
| `09-ideias-extras.md` | Ideias além dos consertos (uma cópia por música, AcoustID, letras, barra de menus, app Música…) | quando quiser |
| `10-roadmap.md` | Fases com checkboxes, em ordem | sempre |
| `11-prompts-prontos.md` | Prompts para colar no Claude Code, por fase | sempre |
| `12-build-e-rodar-sempre-no-mac.md` | Gerar o `.app`, ícone, assinatura, launchd, deixar rodando | fases 8, 10 |
| `13-duracao-das-musicas.md` | Usar a **duração** da planilha/Spotify para garantir que baixou a música certa | fase 1 (itens 1.27–1.30) |

---

## As descobertas mais importantes (resumo)

### Por que a análise da playlist grande "travava"
O leitor do Spotify rola a página mais rápido do que o Spotify carrega os blocos de músicas, **pula blocos** e nunca volta neles. No fim, fica ~30 s "verificando" até desistir. Por isso as tentativas deram 981, 1073, 1044 e 1093 de 1124 — e uma tentativa interrompida ainda **apagou** a lista anterior. → `05 §4`

### Por que demora ~30 s por música (≈10 h para 1.123)
Com 500+ músicas o app liga sozinho o modo mais lento (esperas de 8–15 s + 6 s por música + velocidade limitada), **sem ter havido bloqueio** — e a mensagem "YouTube started throttling" é falsa. Pior: a detecção de bloqueio real está quebrada. Com as correções, a estimativa é ~2–3 h. → `04 §3.3, §5`

### Por que músicas boas são puladas
Títulos do Spotify como "Country House **- 2012 Remaster**" derrubam a nota (0.59, mínimo 0.60). "(feat. X)" também. E as músicas importadas pelo leitor do Spotify chegam **sem duração**, o que desliga o filtro de duração. → `04 §2`

### Duração: garantir que é a música certa
Sua planilha `musicas_curtidas_spotify.csv` já tem a duração das 1.124 músicas, e os IDs batem 100% com a biblioteca, mas o app ignora a coluna "Duração". Usando-a, o app compara a duração de cada vídeo com a da planilha, descarta versões ao vivo/extended/clipes longos e confere o arquivo depois de baixar. Só com isso o caso do Blur já passaria (0.695). → `13`

### Por que aparece "missing"
O app só reconhece arquivos com o nome exato na pasta da playlist. Não lê tags, não olha outras pastas. Você tem **6.383 músicas em `D:\Musicas`** e ~20% da playlist já está lá, mas aparece "missing". Também: músicas puladas ficam "missing" para sempre, desativadas contam como missing, e mudar a numeração **rebaixa a playlist inteira**. → `07 §3`

### Riscos para os seus arquivos (corrigir cedo)
- Trocar de formato (mp3→m4a) **apaga** os arquivos antigos (`04 bug 9`).
- Arquivos pela metade contam como baixados (`04 bug 8`).
- "Skip Song" apaga o arquivo do disco (`04 §7 item 12`).
- Se o `library.json` não carregar, o app cria um novo e **sobrescreve** o antigo (`07 bug 18`).
- Settings podem ser zeradas por uma leitura com erro (`03 §6`).

### O seu CSV que falhou
`musicas_curtidas_spotify.csv` usa `;` e cabeçalhos em português ("Álbum", "Duração", "Link"); o importador só tenta `,` direito e não entende acentos. → `05 §3.6`

### Licença
O CSVMusic **não tem licença** ("todos os direitos reservados"). Fork para uso pessoal: tranquilo. Distribuir: peça ao autor. → `08`

---

## Onde está o código analisado

- Repositório original: https://github.com/angall1/CSVMusic (tag `v1.7.9`, commit `7e779ae`).
- Referências `arquivo:linha` nos documentos são dessa versão. Se o upstream mudar, procure pelo nome da função.
- O GitHub do autor tem bastante coisa útil para consultar: o histórico de commits (ex.: `f368680`, correção de numeração na v1.7.8), as issues e o `release.yml` (como o FFmpeg estático do Mac é compilado).
