# 10 — Roadmap do fork (ordem recomendada)

> **Regra de ouro:** uma fase por vez, cada fase termina com testes passando, teste manual com a playlist pequena e um commit. Não comece o redesign visual antes de o "motor" estar confiável — senão você redesenha em cima de bugs.
>
> Cada item aponta para o documento com os detalhes (ex.: `04 §2.3` = doc 04, seção 2.3).
> Prompts prontos para colar no Claude Code: `11-prompts-prontos.md`.

---

## Fase 0 — Base (meio dia)

| # | Tarefa | Detalhe |
|---|---|---|
| 0.1 | Mac pronto, fork criado, app rodando do código | `01` — feito em 22/10/2026 (clone local em `csvmusic-teles/`, Python 3.12, sem repositório no GitHub ainda) |
| 0.2 | `CLAUDE.md` + `CLAUDE.local.md` no repo | `02` — feito em 22/10/2026 |
| 0.3 | Rodar `pytest -q` e anotar o resultado (linha de base) | `03 §8` — 287 passando, 0 falhas (22/10/2026) |
| 0.4 | Identidade do fork: pasta de configurações própria (`CSVMusicTeles`), URL do update desligada/trocada, `bundle_identifier` próprio, versão `1.7.9+teles.0` | `08 §3` |
| 0.5 | `ci.yml` rodando `pytest` no macOS a cada push | `03 §9` |
| 0.6 | `ruff` configurado para TAB (só lint, sem reformatar tudo ainda) | `09 G1` |

**Pronto quando:** app abre, testes passam (ou falhas conhecidas anotadas), roda ao lado do original sem mexer na biblioteca dele.

---

## Requisito transversal — playlists enormes (5.000+ músicas) (22/10/2026)

O Gabriel tem playlist com mais de 5.000 músicas. Tudo tem que "ir pegando" aos poucos, sem travar e sem perder o que já veio.

**Medido em 22/10/2026** (biblioteca falsa, Mac do Gabriel):

| | 1.124 músicas | 5.000 músicas |
|---|---|---|
| `library.json` | 1,2 MB | 5,4 MB |
| Gravar o resultado de 1 música (`record_library_download_result` lê e regrava o arquivo inteiro) + reler | 30 ms | 134 ms |
| Redesenhar a lista (`_show_tracks`, roda a cada música baixada, na thread da janela) | 287 ms | 368 ms |
| Atualizar a lista de playlists (`_refresh`) | 642 ms | 857 ms |

A cada música baixada a janela congela ~0,5 s, e até ~1,3 s quando também redesenha as playlists. Com 5.000 músicas, só a regravação do arquivo soma ~11 min.

- [ ] G.1 **Leitura aos poucos:** o leitor do Spotify entrega as faixas em lotes durante a leitura, e a biblioteca grava cada lote (junção segura, item 1.21). Se a leitura parar, o que já veio fica salvo e a próxima continua de onde parou. Junto com a fase 2.
- [ ] G.2 **Baixar enquanto lê:** o download pode começar com as faixas que já chegaram, sem esperar a leitura acabar. Junto com 4.3.
- [ ] G.3 **Gravação por música, não do arquivo inteiro:** estado em SQLite (fase 3.1), uma linha por música e atualização de uma linha por resultado. Feito isso, fica fora da thread da tela.
- [ ] G.4 **Tela que vai carregando conforme rola:** a lista da web pede as músicas ao servidor em páginas e desenha só o que está visível (lista virtual). Sem "Load More". Contagens e filtros vêm prontos do servidor. A tela atualiza só a linha que mudou, nunca a lista inteira.
- [ ] G.5 **Teste de carga** com 5.000 e 10.000 músicas falsas: abrir, rolar, filtrar e receber 1 resultado de download. Meta: nenhuma ação acima de 100 ms na tela.

---

## Fase 1 — Consertos rápidos de alto impacto (2–4 dias)

Cada item é pequeno e independente. Faça **um commit por item**.

### Busca (doc 04 §2)
- [ ] 1.1 `split_title`: remover sufixos do Spotify " - 2012 Remaster", " - Radio Edit", " - Live…", " - Mono", " - From …" e "(feat./with …)" **na busca e na nota**; convidados do feat vão para artistas. (`04 §2.3a`) — **resolve o caso Blur 0.59**
- [ ] 1.2 Penalidades por palavra inteira (`\b`): "Demons"≠"demo", "Discover"≠"cover", "Castle"≠"cast" (`04 bug 18`)
- [ ] 1.3 Regex de feat com `\b` ("(Defeated)" não é feat) (`04 bug 17`)
- [ ] 1.4 Marcas de versão simétricas (incluir o álbum da faixa pedida) e `\bmix\b` não é remix (`04 §2.2 itens 4-5`)
- [ ] 1.5 "Vazio após filtro de duração" ≠ "busca vazia" (não abortar o lote à toa) (`04 bug 4`)
- [ ] 1.6 Log de pulo mostra as queries reais e o melhor candidato (`04 bug 27`)

### Download (doc 04)
- [ ] 1.7 Detecção de bloqueio no stderr **cru** (bug do "not a bot" nunca detectado) (`04 bug 1-2`)
- [ ] 1.8 Perfil por tamanho vira só teto inicial, **sem** mensagem falsa de "throttling" (`04 bug 3`)
- [ ] 1.9 Sem pausa depois de faixa pulada (`04 bug 23`)
- [ ] 1.10 `_cleanup_outputs` só apaga temporários e o formato atual (hoje apaga mp3 antigo ao trocar formato!) (`04 bug 9`)
- [ ] 1.11 Gravação atômica: `.partial` → tags → `os.replace` (arquivo parcial nunca conta como baixado) (`04 bug 8`)
- [ ] 1.12 m4a com Opus dentro → reencodar para AAC (compatibilidade Apple) (`04 bug 7`)
- [ ] 1.13 Remover o fallback `ytsearch1:` (baixa áudio não verificado) ou passar pela nota (`04 bug 6`)
- [ ] 1.14 Timeout no subprocess + parar de verdade no Stop (sem `terminate()`) (`04 bug 13`, `03 §5`)

### Biblioteca (doc 07)
- [ ] 1.15 Gravar pulos (`not_found_on_youtube` com motivo e data) (`07 §3.3.1`)
- [ ] 1.16 Desativadas fora da contagem de missing (+ corrigir o teste) (`07 §3.3.2`)
- [ ] 1.17 Um único padrão de formato; seletor com opus (`07 §3.3.3`)
- [ ] 1.18 M3U escrito a cada N faixas, não só no fim (`07 bug 8`)
- [ ] 1.19 Bloquear "nova análise" durante download (`07 bug 5`)
- [ ] 1.20 `load_library` com versão diferente **não** pode sobrescrever a biblioteca (backup + erro claro) (`07 bug 18`)

### Importação (doc 05)
- [ ] 1.21 `scan_cancelled=True` ao fechar + junção segura (análise parcial não apaga faixas) (`05 §4.4 passo 9`)
- [ ] 1.22 Capturar a **duração** (`mm:ss`) no leitor do Spotify (`05 §5 item 12`)
- [ ] 1.23 CSV robusto: separador `;`, acentos, colunas em pt/es (Faixa, Artista, Álbum, Duração, Link) (`05 §3.6`) — **resolve o erro do `musicas_curtidas_spotify.csv`**
- [ ] 1.24 Flags anti-throttling do Chromium (`05 §4.4 passo 11`)
- [x] 1.31 Playlist particular: 404 do Spotify vira `SpotifyPlaylistPrivateError` com instrução para tornar pública; antes a análise terminava sem aviso nenhum. Lista mostra "PRIVATE ON SPOTIFY" e o resumo conta as privadas (22/10/2026)

### Geral
- [ ] 1.25 Settings: escrita atômica + gravação com atraso (debounce) + backup (`06 §2`, `03 §6`)
- [ ] 1.26 Log com rotação no lugar certo do Mac (`~/Library/Logs/CSVMusicTeles`) (`03 §6`)

### Duração da música (doc 13) — garantir que é a música certa
- [ ] 1.27 CSV lê `Duração`/`Duration (ms)` em `m:ss`, `h:mm:ss`, segundos ou ms; guarda `duration_source` e precisão (`13 §4.1`) — fazer junto com 1.23
- [ ] 1.28 Comando `fill_durations`: preenche a biblioteca atual a partir da planilha pelo ID do Spotify, com backup (`13 §5.1`) — **resolve as 1.124 músicas sem duração**
- [ ] 1.29 Nota mais rígida quando a duração é confiável + fora da tolerância vira `duration_mismatch`, não "busca vazia" (`13 §4.2-4.3`)
- [ ] 1.30 Conferir a duração do arquivo depois de baixar e rejeitar se não bater (`13 §4.4`)
- [ ] Depois (fase 4/7): enriquecimento automático por embed/Deezer/iTunes, coluna "Duração" na tela, exportar CSV com duração (`13 §5.2-5.3, §4.6`)

**Pronto quando:** playlist de teste (~50 músicas, com remasters/feat/live) baixa sem pulos bobos; parar no meio e retomar não deixa arquivo quebrado; testes novos cobrindo cada correção.

---

## Fase 2 — Leitura confiável de playlists grandes do Spotify (2–4 dias)

- [ ] 2.1 Máquina de rolagem por **posição**: só avança com a tela carregada, passo ≤ 0,8 × tela, rola para alvo absoluto num único elemento (`05 §4.4 passos 1-3`)
- [ ] 2.2 Fase de **preencher buracos** no fim (`05 §4.4 passo 4`)
- [ ] 2.3 Desistência por tempo/progresso + watchdog do JavaScript + recarregar se o renderer morrer (`05 §4.4 passos 5-6`)
- [ ] 2.4 Total via `aria-rowcount` (independe de idioma) (`05 §6 item 9`)
- [ ] 2.5 Progresso honesto ("faltam 31: 676–706") + "Concluir com o que tenho" (`05 §4.4 passo 8`)
- [ ] 2.6 Teste com lista virtual simulada (blocos de 50 com atraso aleatório) (`05 §4.4 passo 12`)
- [ ] 2.7 *(Opcional, maior impacto)* Interceptar o JSON do web player em vez de ler a tela (`05 §4.4 alternativa`)

**Pronto quando:** a playlist de 1.124 músicas é lida **completa em 5 de 5 tentativas**.

---

## Fase 3 — Estado em SQLite + reconhecer o que já existe (4–7 dias)

- [ ] 3.1 Banco por pasta de saída (`tracks`, `files`, `matches`, `playlist_entries`, `jobs`) (`04 §4.2`, `09 A1`)
- [ ] 3.2 Migração do `library.json` existente para o banco (com backup)
- [ ] 3.3 Gravar identidade nas tags dos arquivos baixados (`CSVMUSIC_SPID`, `CSVMUSIC_YTID`, ISRC) (`07 §3.5a`)
- [ ] 3.4 Índice de arquivos com **pastas extras de reconhecimento** (ex.: `~/Music/Musicas`) e leitura incremental (`07 §3.5a`)
- [ ] 3.5 Reconhecimento em camadas + estados novos (`found_elsewhere`, `needs_review`, …) (`07 §3.5b-c`)
- [ ] 3.6 Renomear em vez de baixar de novo (numeração/posição mudou) (`04 §4.2 regra 4`, `07 §3.5d`)
- [ ] 3.7 Ações: vincular manualmente, padronizar nomes, adotar órfãos, analisar disco
- [ ] 3.8 Tirar `library_status`/merge da thread da interface (`05 §6 item 5`)

**Pronto quando:** apontar a pasta antiga de músicas faz ~20% da playlist aparecer como "encontrada"; ligar/desligar numeração só renomeia; abrir a biblioteca grande não congela.

---

## Fase 4 — Pipeline rápido e resistente (4–6 dias)

- [ ] 4.1 Busca em cascata com saída antecipada (ISRC → songs → variantes → videos) (`04 §2.3c`)
- [ ] 4.2 Cache de busca + escolhas manuais persistentes (`04 §2.3g`)
- [ ] 4.3 Fase de busca separada da de download; revisão enquanto baixa (`04 §5.1`)
- [ ] 4.4 2–3 downloads em paralelo com limitador global (token bucket) (`04 §5.1`)
- [ ] 4.5 Freio adaptativo (AIMD) só com sinal real de bloqueio (`04 §5.2`)
- [ ] 4.6 Fila persistente (sobrevive a fechar o app) com retry exponencial (`04 §5.3`)
- [ ] 4.7 ETA real (`04 §5.4`)
- [ ] 4.8 yt-dlp sempre em subprocesso + **yt-dlp externo atualizável** (`04 §5.1`, `09 G3`)
- [ ] 4.9 Seletor de ritmo: Rápido / Normal / Cauteloso (com aviso honesto)

**Meta:** 1.123 faixas em ~2–3 h (hoje ~9–10 h), reprocessar com cache quase de graça.

---

## Fase 5 — Tags e áudio de qualidade (2–3 dias)

- [ ] 5.1 Album Artist, vários artistas (lista), gênero, ISRC, totais, data completa (`04 §6`, `09 D1`)
- [ ] 5.2 `track_no` = faixa do álbum; posição na playlist em tag separada (`04 §6.1`)
- [ ] 5.3 ID3 versão única (2.4; 2.3 só no modo iPod) (`04 bug 21`)
- [ ] 5.4 Capa uma vez só, maior (1000–1400 px), sem recompressão dupla (`04 §6.5`)
- [ ] 5.5 ReplayGain/R128 em vez de mexer no áudio (normalização destrutiva vira opção) (`04 §6.4`, `09 C5`)
- [ ] 5.6 Letras via LRCLIB (`.lrc` + embutida) (`09 C4`)

---

## Fase 6 — Motor separado da interface + linha de comando (3–5 dias)

- [ ] 6.1 Pacote `csvmusic/engine/` com API e eventos; UI só assina eventos (`09 A2`)
- [ ] 6.2 CLI: `csvmusic sync <link|csv>`, `csvmusic sync --library`, `csvmusic status` (`09 A3`) — os mini-CLIs existentes (`download_csv.py` etc.) são ponto de partida
- [ ] 6.3 Instância única + trava da biblioteca (`07 §6.1`)

---

## Fase 7 — Redesign + idiomas (1–3 semanas)

- [ ] 7.1 Estados como enum (pré-requisito) (`06 §4.2 passo 0`)
- [ ] 7.2 Design system: tokens, QSS único, temas Claro/Escuro/Clássico, seguir o sistema (`06 §3 opção A`)
- [ ] 7.3 Library Mode vira `QMainWindow` com menu nativo do Mac; aposentar o modo legado
- [ ] 7.4 Listas com `QListView` + modelo + delegate (sem "Load More") (`07 §4 item 3`)
- [ ] 7.5 Ícones SVG; remover `_px`; fonte do sistema
- [ ] 7.6 Tela "Revisar" com prévia de 15 s (`09 C2`)
- [ ] 7.7 i18n com JSON (pt-BR, en, es) + `qtbase_*.qm` + teste de chaves (`06 §4.2`)
- [ ] 7.8 Painel com cards por playlist e ETA (`06 §3 esboço`, `09 F3`)

---

## Fase 8 — Rodar sempre (3–5 dias)

- [ ] 8.1 Ícone na barra de menus + fechar janela só esconde (`07 §6.2`)
- [ ] 8.2 Agendamento com variação, horário silencioso, cota do YouTube, rede/bateria (`07 §6.3`)
- [ ] 8.3 Leitor do Spotify fora da tela, criado sob demanda (`07 §6.1`)
- [ ] 8.4 Notificações agrupadas (`07 §6.4`)
- [ ] 8.5 Abrir ao iniciar sessão (LaunchAgent; SMAppService quando assinado) + `--background` (`07 §6.5`, `12`)
- [ ] 8.6 Pausar/retomar persistente (`07 §6.6`)

---

## Fase 9 — Extras (escolha os que quiser)

- Uma cópia só por música + playlists como referência (`09 B1`)
- Verificação por impressão digital (AcoustID) (`09 C1`)
- Importar no app Música da Apple (`09 E3`)
- Lista de bloqueio de vídeos/canais (`09 C3`)
- Integração Navidrome/Jellyfin/Plex (`09 E4`)
- API oficial do Spotify (PKCE) para playlists suas, com refresh token (`05 §6 item 8`)
- Sync com aparelhos: parcial, limpeza de órfãos (`07 §4`)

---

## Fase 10 — Seu próprio `.app` (1–2 dias)

- [ ] 10.1 `app.icns` próprio
- [ ] 10.2 ffmpeg e deno dentro do `.app` (apps abertos pelo Finder não enxergam `/opt/homebrew/bin`)
- [ ] 10.3 Build local com PyInstaller, assinatura ad-hoc
- [ ] 10.4 *(Opcional)* Developer ID + notarização
Detalhes: `12-build-e-rodar-sempre-no-mac.md`.
