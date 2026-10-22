# 07 — Library Mode, o "missing" e a sincronização com aparelhos

> Como a biblioteca funciona, **por que tanta música aparece como "missing"**, o redesenho para reconhecer o que já existe, sync com aparelhos e o modo "sempre rodando".
> Inclui números da análise feita no PC do usuário em 22/10/2026 (só estatísticas, sem a lista de músicas).

---

## 0. Resumo

- O **Library Mode é a janela principal**: `app.py:164` cria o `LibraryModeDialog()` direto. O modo legado só abre por um botão.
- **"Missing" = um caminho calculado não existe no disco** (`core/library.py:518-539` e `:435-454`). O app **não lê tags**, não indexa a pasta e não reconhece arquivo fora do padrão `<saída>/<playlist>/[NNNN- ]Artista - Título.<formato>`.
- **Nos dados do usuário, a maior parte dos "missing" era verdadeira**: 1 playlist, 1124 músicas, e só 21 a 26 arquivos em `D:\music\Out Of Time Man` no momento da análise (o download estava rodando). Todos os arquivos dessa pasta foram reconhecidos.
- **O problema real:** o usuário **já tem 6.383 MP3 em `D:\Musicas`**, e o app ignora essa coleção.
  - Uma varredura simples das tags (só artista e título normalizados) achou lá **~227 das 1124 músicas (≈20%)**. Dessas, **~205 constavam como "missing"**.
  - Só 3 arquivos têm ISRC, então casar só por ISRC não resolve.
  - Ler a pasta inteira a frio levou ~113 s, o que justifica um cache.
- **Também existem "missing" falsos causados por bugs** (§3.3):
  - músicas puladas por baixa confiança ficam "missing" para sempre;
  - músicas desativadas contam como missing;
  - o seletor de formato não tem "opus";
  - e outros.

---

## 1. Módulo por módulo

### 1.1 Relação entre Library Mode e o modo legado
- O modo legado tem um botão "LIBRARY MODE" (`main_window.py:586-594`) que abre **outro** `LibraryModeDialog` modal (`:1553-1557`).
- Começando pelo Library Mode, o botão "Legacy Mode" emite um sinal e **fecha** a biblioteca (`library_mode.py:2005-2009`). A troca de modo é assimétrica.
- O modo legado também grava no `library.json` (`main_window.py:2449-2457`).
- `_use_in_csvmusic` (`library_mode.py:3604`) não está ligado a nenhum botão: é caminho morto.
- `library_mode_ui.py` é um lançador de teste (abre um aviso "Library Test Successful").

### 1.2 `core/library.py` (modelo e regras)
| Função | Linhas | O que faz |
|---|---|---|
| `new_library` | 26-35 | cria a biblioteca vazia (versão 1) |
| `load_library` | 38-45 | lê e valida `version == 1`; **não há migração** |
| `save_library` | 48-55 | escrita **atômica** (arquivo temporário + replace) e atualiza `updated_at` |
| `add_playlist_urls` | 58-119 | detecta a plataforma e cria uma playlist "Unscanned …" vazia |
| `import_csv_playlist` | 122-151 | id = hash do caminho do CSV (mover o arquivo cria outra playlist) |
| `rename_library_playlist` | 154-213 | renomeia a pasta e os `.m3u`/`.m3u8` e marca `custom_name` |
| `edit_library_track` | 216-233 | define título e álbum personalizados |
| `merge_playlist_scan` | 236-323 | junta uma nova análise com o que já existia (§2.3) |
| `enabled_tracks` | 346-359 | lista das músicas ativas, com índices injetados |
| `record_library_download_result` | 376-432 | **lê o JSON inteiro, altera uma música e salva**, a cada música baixada. Se o nome mudou, apaga o arquivo antigo |
| `library_status` | 435-454 | contagens (§3) |
| `export_csv` | 457-473 | exporta CSV (só alcançável por código morto) |
| `_track_base_key` | 501-511 | identidade: `youtube:` > `apple:` > `spotify:` > `text:artista\|título` |
| `library_track_path` | 518-539 | descobre o arquivo de uma música (§3) |

### 1.3 Nomes de arquivo
- `track_filename_base` (`track_output.py:8-19`) gera `"Artista - Título"`, com prefixo opcional `NNNN- `. A largura é o número de dígitos da quantidade de músicas: com 1124 músicas, 4 dígitos (`0001- `).
- `sanitize_name` (`downloader.py:325-335`):
  - normaliza em NFC;
  - troca `\ / : * ? " < > |` por versões **"largas"** parecidas (`：`, `＂`, `？`);
  - colapsa espaços e remove ponto ou espaço no fim;
  - acima de 140 caracteres, corta e adiciona um hash.
  - Exemplo real: `0017- Tears For Fears, Dave Bascombe - Head Over Heels - Dave Bascombe 7＂ N.Mix.mp3`.

### 1.4 `ui/library_mode.py` (3641 linhas)

**Workers e funções de apoio**
- `_audio_processing_signature` (`:44-64`) gera uma assinatura do EQ, como `normalize=0|volume=0|bass=0|treble=0`.
- `_pending_download_tracks` (`:67-84`) decide o que entra no download:
  - "Download All" (`missing_only`): só as músicas sem arquivo.
  - Modo normal: também entram as marcadas para baixar de novo, as com EQ diferente e **todas as afetadas por mudança na opção de numeração**. Ou seja, **ligar ou desligar a numeração rebaixa a playlist inteira do YouTube só para renomear**.
- `DirectLibraryScanWorker` (`:96-136`) lê fontes que não precisam de navegador.
- Os ícones são desenhados com QPainter (`:209-465`).

**Diálogos**
- `RescanSummaryDialog`: resumo depois de uma nova análise.
- `LibraryScanProgressDialog`: progresso com o **"Live page preview"** do Spotify, embutido sem barras de rolagem e deslocado 42% para esconder a barra lateral do Spotify.
- `LibraryEqualizerDialog`: ganho, grave e agudo de ±12 dB, mais normalização.
- `LibrarySettingsDialog`, com abas:
  - **General**: pasta, formato (m4a/mp3/opus), qualidade MP3 (escala invertida), modo iPod, capa, forçar baixa confiança, numeração, M3U8.
  - **YouTube Account**: login, teste de conexão, cookies.
  - **Advanced**: caminhos do yt-dlp e do ffmpeg.
  - **O mesmo diálogo reaparece como "Confirm Download Settings" antes de todo download** (`:3370`).
- `TrackAlternativesDialog` ("Song Settings"): candidatos do YouTube e YT Music, avisos de LIVE/ACOUSTIC, colar uma URL manualmente e volume por música. Salvar marca a música para baixar de novo.
- `LibraryGuideDialog` (tutorial), `DownloadLogDialog` (5000 linhas) e `StartupDisclaimerDialog` (1000×650, 4 cards).
- **Teste de conexão do YouTube:** valida o `cookies.txt`, faz GET em `youtube.com` com os cookies e procura `"LOGGED_IN": true`.
- **Verificação de atualização:** no máximo 1×/dia. A data é gravada **antes** de checar, então uma falha faz esperar 24 h.

**Layout da janela principal** (`_build_ui`, `:1560-1977`)
1. Cabeçalho azul-marinho: Sync, Equalizer, Settings, Tutorial, Info e Legacy Mode.
2. "Add to library": campo de URL com "+" e "Add CSV...". Há duas linhas **escondidas** que ainda controlam o estado (pasta da biblioteca e formato).
3. "Download activity": capa, barra de progresso e Download/Stop/Log.
4. Divisão em dois painéis:
   - à esquerda, playlists (Download All, Rescan All, Scan Unscanned);
   - à direita, músicas com busca e "Load More Songs".
   - **Cada item é um `QFrame` dentro de uma `QTreeWidget`**, recriado a cada atualização e paginado de 200 em 200.
5. Rodapé: estado da conta do YouTube e "Tracks | Downloaded | Missing".

**Comportamentos importantes**
- `_refresh` (`:2639-2791`) recalcula `library_status` e **destrói e recria todos os cards**.
  - Cores: vermelho = não analisada; laranja = análise incompleta; rosa = erros; amarelo = baixar de novo; rosado = missing; verde = ok.
- `_show_tracks` (`:2793-3011`) ordena por problema, chamando `library_track_path` para **todas** as músicas, e lê a qualidade de áudio de cada card exibido.
- `_remove_playlist` (`:2477-2528`) **apaga a pasta da playlist com `shutil.rmtree`**. Pede confirmação e verifica que a pasta é filha da saída e não é compartilhada.
- **Código morto:** `_track_checked`, `_set_all_tracks`, `_toggle_redownload`, `_set_youtube_match`, `_export_csv`, `_start_alternative_download`, `_use_in_csvmusic`. Por isso **a interface não tem como desativar uma música**, embora o modelo tenha `enabled`.

### 1.5 Sincronização com aparelhos (`core/device_sync.py` + `ui/device_sync.py`)

**Quais aparelhos**
- Só **discos montados**:
  - Windows: letras D–Z do tipo "removível". HDs USB que aparecem como "fixo" ficam de fora.
  - Mac: `/Volumes/*` filtrado com `diskutil info -plist`.
  - Linux: `/media/$USER`.
- **Não há MTP**: Androids atuais não aparecem. iPhone também não.
- Se existir `iPod_Control/iTunes/iTunesDB`, é tratado como iPod clássico (experimental). Senão, como armazenamento comum.

**Armazenamento comum**
- Copia para `<raiz>/CSVMusic/<playlist>/` e grava `Playlists/<playlist>.m3u8`.
- Pula a cópia se o tamanho for igual (não usa hash).
- **Nunca remove órfãos**: apagar uma playlist do aparelho só remove o `.m3u8`.

**iPod clássico**
- Usa um ajudante em C com libgpod. No Windows roda **via WSL, com a distribuição "Ubuntu" fixa no código**.
- Faz backup do banco do iPod, gera um manifesto, copia, grava o `iTunesDB` e verifica byte a byte.

**Limitações**
- **Pré-requisito crítico:** `_ready_playlists` (`:119-137`) **pula a playlist inteira se qualquer música estiver missing**. Com 1100 missing, a playlist do usuário não sincroniza nada.
- **Ejetar no Windows:** usa o verbo "Eject" em inglês pelo PowerShell, que falha num Windows em português.
- A interface procura aparelhos a cada 3 s. No Mac, isso roda `diskutil` por volume a cada 3 s.
- A aba "On Device" mostra `"{n}/{n} tracks"`, que é sempre igual a si mesma e não informa nada.

---

## 2. Formato do `library.json`

### 2.1 Raiz
| Campo | Notas |
|---|---|
| `version` | 1, sem migração |
| `name` | "My Library" |
| `output_dir` | pasta de saída (no caso do usuário, `D:/music`) |
| `format` | `m4a`/`mp3`/`opus`. **Não existe em bibliotecas novas**, e o padrão muda conforme o lugar do código (§3.3) |
| `created_at` / `updated_at` | |
| `playlists` | lista |

### 2.2 Playlist
`id`, `platform` (`spotify|youtube_music|youtube|apple_music|deezer|amazon_music|csv`), `source_type`, `url`, `csv_path`, `name`, `custom_name`, `last_scanned_at`, `reported_total`, `scan_warning`, `cover_url`, `last_diff {added, removed, unchanged}`, `tracks`.

### 2.3 Música (30 campos)
- **Da fonte:** `title`, `artists`, `album`, `playlist`, `isrc`, `sp_id`, `duration_ms`, `year`, `cover_url`, `track_no`, `disc_no` e, opcionalmente, `youtube_video_*` e `apple_music_id`.
- **Identidade:** `playlist_occurrence`.
- **Escolhas do usuário** (preservadas): `custom_title`, `custom_album`, `enabled`, `preferred_video_id`, `preferred_video_label`, `preferred_selection_locked`, `audio_volume_gain`.
- **Estado do arquivo** (preservado): `audio_processing_signature`, `filename_prefix_number`, `filename_prefix_width`, `force_redownload`, `last_error`, `last_error_at`, `last_downloaded_at`, `downloaded_video_id`, `downloaded_video_title`, `downloaded_video_publisher`, `downloaded_path`, `low_confidence_review`, `download_confidence`.

**O que acontece numa nova análise** (`merge_playlist_scan`):
1. Indexa as músicas antigas pela chave.
2. Para cada música nova, procura a antiga pela chave ou pelo texto artista|título (se houver um único candidato).
3. Copia as escolhas e o estado.
4. Se não havia `downloaded_path`, tenta descobrir o arquivo.
5. Músicas removidas da fonte **somem da biblioteca, mas os arquivos ficam no disco como órfãos**, sem aviso.

### 2.4 Dados do usuário (só estatísticas)
- **Conteúdo:**
  - 1 playlist do Spotify com 1124 músicas, formato `mp3`, saída `D:/music`.
  - Numeração ligada, M3U8 ligado, sem cookies, EQ desligado.
  - **ISRC vazio em 100%** das músicas, porque o leitor com navegador não traz ISRC.
  - Um mesmo artista|título aparece 3 vezes com `sp_id` diferentes.
- **Pasta `D:\music\Out Of Time Man`:**
  - 21 MP3 (`0001`–`0022`), **faltando o `0008`**.
  - Um `.m3u8` com **só 1 entrada**, porque o M3U só é escrito no fim da execução.
- **A música 8 é um pulo por baixa confiança que não foi registrado** (§3.3.1).

### 2.5 Fluxo de download (`_start_download`, `:3364-3505`)
1. Mostra as Settings como confirmação.
2. Se o formato é MP3, verifica se o ffmpeg tem `libmp3lame`.
3. Para cada música ativa: resolve o arquivo existente e **sobrescreve** `filename_prefix_number` = índice + 1. A largura usa a contagem de músicas **ativas**, mas a posição usa o índice que inclui as desativadas.
4. Filtra com `_pending_download_tracks`.
5. Mostra o aviso de risco do YouTube.
6. Inicia o `PipelineWorker`.
7. A cada música baixada ou com erro, roda `record_library_download_result` (lê e grava 1,3 MB), recarrega a biblioteca e recria até 200 cards.
8. **Músicas puladas não são registradas** (`:3566`).

---

## 3. Por que aparece "missing"

### 3.1 Como é calculado
Em `library_status`, para **cada** música (inclusive as desativadas):
```python
if library_track_path(track, root, fmt).exists(): downloaded += 1
else: missing += 1
```
`library_track_path` tenta, nesta ordem:
1. `downloaded_path` gravado, se o arquivo ainda existir.
2. O caminho esperado com o prefixo salvo.
3. Listar a pasta da playlist, tirar `^\d+- ` do nome, normalizar em NFC e comparar **exatamente**. Só aceita se houver **um** resultado. Por decisão explícita, nunca compara de forma aproximada nem aceita outro formato.

A interface usa o formato do seletor escondido; o download usa `library["format"]`.

### 3.2 Por que o autor fez assim (interpretação generosa)
- **Velocidade:** checar se um arquivo existe custa microssegundos; ler tags de milhares de arquivos custa minutos.
- **Segurança:** ele preferiu um "missing" falso a um "baixado" falso. Uma comparação aproximada errada pularia uma música ou mandaria o arquivo errado para o iPod.
- **O app é dono da pasta:** a ideia é que o CSVMusic gera e controla `<saída>/<playlist>`. Arquivos de fora não fazem parte do combinado.
- **Sem banco de dados:** tudo cabe num JSON legível.
- `downloaded_path` e a regra do prefixo foram remendos adicionados quando apareceram bugs de numeração (v1.7.8).

### 3.3 Por que aparece "missing" quando o áudio existe (ou a conta engana)
1. **Pulos não são gravados.** O worker emite `skipped=True, error=None`, e a interface só grava quando há download ou erro. A música fica "Missing" para sempre, sem motivo visível, e **é buscada de novo a cada Download All**, o que aumenta o risco de bloqueio.
2. **Desativadas contam como missing.** O teste `tests/core/test_library.py:238-248` **espera** esse comportamento errado.
3. **Formato divergente.**
   - O seletor escondido só tem m4a e mp3, e as Settings têm opus.
   - O padrão é m4a na interface e mp3 em `merge_playlist_scan`, `record_library_download_result` e device sync.
   - Trocar o formato faz toda música sem `downloaded_path` virar missing e ser baixada de novo, duplicada.
4. **Arquivos fora da pasta gerenciada.** É **o caso principal do usuário** (~205 em `D:\Musicas`).
5. **Pasta renomeada** pela fonte ou fora do app.
6. **Metadados mudaram na fonte** (ganhou "- Remastered 2011", ganhou "feat."): vira uma música "nova" e o arquivo antigo fica órfão.
7. **Nome mexido à mão** (`"` → `'`, `:` → `-`) ou prefixos em outro formato (`01 - `, `01. `).
8. **Unicode** NFC vs NFD.
9. **Duplicatas com números diferentes** (`0005- X` e `0105- X`): o fallback exige exatamente 1 resultado, então não acha nenhum.
10. **A mesma música em várias playlists:** cada playlist tem sua pasta, e a música é baixada de novo.
11. **Pasta de saída movida** (outro HD): os `downloaded_path` absolutos quebram.
12. **Editar metadados** usa o caminho esperado e não o arquivo real.

### 3.4 Custo do esquema atual
- Cada atualização faz um `stat` por música. Cada música sem arquivo **lista a pasta inteira**.
- Com 1100 missing numa pasta de 1000 arquivos, são **~1,1 milhão de entradas por atualização**. Durante o download, isso se repete **a cada música**, junto com a leitura e gravação do JSON de 1,3 MB.

### 3.5 Redesenho proposto

**a) Índice de arquivos em SQLite** (`index.sqlite` na pasta de dados do app)
```sql
files(path PK, root, size, mtime_ns, file_id, fmt, duration_ms,
      title, artist, album, isrc, sp_id, yt_video_id, acoustid NULL,
      norm_artist, norm_title, scanned_at);
CREATE INDEX files_isrc ON files(isrc);
CREATE INDEX files_norm ON files(norm_artist, norm_title);
links(playlist_key, track_key, path, method, confidence, confirmed_by_user, linked_at);
roots(path, recursive, include_in_matching, last_full_scan);
```
- **Pastas configuráveis:** a saída da biblioteca mais pastas extras (ex.: `~/Music/Musicas`, o equivalente no Mac ao `D:\Musicas`), marcadas como "só para reconhecer" (o app não escreve nelas).
- **Leitura incremental:** `os.scandir` recursivo. Se tamanho e data não mudaram, não relê. Se mudaram, lê as tags com mutagen numa thread. A primeira passada leva ~2 min para 6 mil arquivos; as seguintes, segundos.
- Opcional: `QFileSystemWatcher` ou `watchdog` para atualizar ao vivo.
- **O app grava a própria identidade nas tags** dos arquivos que baixa (`CSVMUSIC_SPID`, `CSVMUSIC_YTID`, ISRC). Assim o reconhecimento sobrevive a qualquer renomeação.

**b) Reconhecimento em camadas** (vale a primeira que bater)

| # | Critério | Confiança |
|---|---|---|
| 1 | `downloaded_path` válido, com tamanho e data iguais | 1.0 |
| 2 | Tag `CSVMUSIC_SPID`/`YTID` igual | 1.0 |
| 3 | ISRC igual | 0.98 |
| 4 | Artista e título normalizados + duração ±3 s | 0.9 |
| 5 | Comparação aproximada (`rapidfuzz token_set_ratio ≥ 92`) + duração ±5 s | 0.7, **nunca automático**: vai para "Revisar" |
| 6 | Arquivo sem tags | aplica o mesmo processo ao nome `[NN- ]Artista - Título` |

A normalização da camada 4: NFKD, remover acentos, minúsculas, remover `(feat…)`, `[...]`, `- Remaster…`, `- Ao Vivo`, juntar pontuação, considerar o primeiro artista e tratar `e`, `&`, `,` e `and` como equivalentes.

**c) Novos estados** (no lugar de Baixada/Missing)

| Estado | Significado |
|---|---|
| `downloaded` | arquivo na pasta da playlist, vínculo confirmado |
| `found_elsewhere` | achado em outra pasta ou em outra playlist. Ações: usar como está (só referenciar no M3U/sync), copiar, criar hardlink ou mover |
| `needs_review` | comparação aproximada ou baixa confiança do YouTube |
| `missing` | nada encontrado; pode ser baixada |
| `not_found_on_youtube` | pulada (sem resultado ou nota baixa). Grava o motivo e a data e espera antes de tentar de novo |
| `failed` | erro de download |
| `disabled` | desativada, fora das contagens |
| `outdated` | precisa baixar de novo (EQ, alternativa) |

**d) Ações novas**
- **Vincular manualmente:** escolher o arquivo de uma música.
- **Padronizar nomes:** renomear os arquivos vinculados para o padrão atual **sem baixar de novo**. Substitui o rebaixamento em massa que acontece hoje ao mudar a numeração.
- **Adotar órfãos:** arquivos na pasta sem vínculo passam pelo reconhecimento.
- **Reanalisar disco:** botão separado do "Rescan" da fonte, com progresso.

**e) Correções rápidas (antes do redesenho)**
- Gravar os pulos.
- Ignorar as desativadas em `library_status`.
- Um único padrão de formato, com o seletor coerente com as Settings.
- Corrigir o teste `test_library_status_uses_real_output_files`.
- Escrever o M3U a cada N músicas, e não só no fim.

---

## 4. Estranhezas de interface e código

| # | O que é estranho | Motivo provável | Alternativa |
|---|---|---|---|
| 1 | Visual Windows 95, Comic Sans, fonte VCR | identidade retrô proposital | tema central, fonte do sistema, modo escuro, "Clássico" como opção |
| 2 | Janela principal é um QDialog | começou como diálogo dentro do modo legado | `QMainWindow` com menu e barra de status; Esc não fecha o app |
| 3 | Cards como `QFrame` em `QTreeWidget`, recriados sempre, paginados de 200 em 200 | liberdade visual sem escrever um delegate | `QListView` + modelo + delegate: virtualização real, sem "Load More" |
| 4 | Ícones desenhados em código (~250 linhas) | zero arquivos de ícone | SVG |
| 5 | Confirmação de settings antes de todo download | evitar formato ou pasta errados | resumo no painel + "não perguntar de novo" |
| 6 | "Rescan" (fonte) e "Missing" (disco) misturados | resumo útil | separar "Atualizar da fonte" de "Analisar disco" |
| 7 | Prévia do Chromium deslocada 42% | mostrar que está andando | lista de músicas lidas, com prévia opcional |
| 8 | Linhas escondidas que ainda controlam o estado | recursos removidos sem refatorar | remover |
| 9 | Muito código morto | evolução rápida | remover; trazer "desativar música" e "exportar CSV" num menu de contexto |
| 10 | Mudar a numeração rebaixa tudo | reaproveitou o caminho de "baixar de novo" | renomear localmente |
| 11 | Número = posição no array (inclui desativadas) e largura = quantidade de ativas | o número era só cosmético | número = posição atual na fonte; renomear em lote |
| 12 | Caracteres "largos" (`：`, `＂`, `？`) nos nomes | preservar a aparência | opção "nomes seguros ASCII" (som de carro e iPod mostram `□`) |
| 13 | "Excluir playlist" apaga a pasta por padrão | limpeza completa | checkbox desmarcado + mover para a Lixeira (`send2trash`) |
| 14 | Sync exige 100% baixado | não mandar M3U com buracos | sincronizar o que existe e marcar como "parcial" |
| 15 | "On Device" mostra n/n | provisório | mostrar biblioteca × aparelho e a diferença |
| 16 | Ejetar com "Eject" em inglês | testado em Windows em inglês | API nativa |
| 17 | iPod via WSL "Ubuntu" fixo | libgpod é só POSIX | detectar a distribuição |
| 18 | Aviso inicial 1000×650 | garantir que leiam | aviso de primeira execução, não modal |
| 19 | Espera de 0,9–1,4 s entre playlists | evitar bloqueio | ok, configurável no modo automático |
| 20 | Verificação de update grava a data antes de checar | não martelar a API | gravar só no sucesso |
| 21 | Dois lançadores e duas formas de trocar de modo | legado | um `AppController` único |

---

## 5. Bugs e riscos

1. Pulos não persistem (`library_mode.py:3566`, `workers.py:416-423`): "missing" eterno e buscas repetidas no YouTube.
2. `library_status` ignora `enabled`, e o teste confirma o erro.
3. Seletor de formato sem opus, com padrões diferentes (m4a/mp3) em vários lugares.
4. Lê e grava o JSON inteiro (1,3 MB) a cada música. O modo legado e o Library Mode podem gravar ao mesmo tempo, e quem grava por último vence.
5. Dá para iniciar uma nova análise **durante um download**. A junção reordena as músicas, e os índices do download passam a apontar para as linhas erradas.
6. **Esc fecha a janela principal** (comportamento do QDialog). Pode matar o app no meio de um download (precisa confirmar).
7. O worker de download nunca recebe `deleteLater` (vazamento de memória).
8. O M3U só é escrito no fim e só com arquivos achados pelo caminho esperado (`workers.py:552-556`).
9. Largura e posição da numeração inconsistentes; números duplicados depois de reordenar.
10. Editar metadados usa o caminho esperado e não o arquivo real.
11. `record_library_download_result` **apaga o arquivo antigo** quando o caminho muda. Com duas músicas que têm o mesmo artista e título, pode apagar o arquivo da outra.
12. Músicas com o mesmo artista e título usam o mesmo arquivo (implícito).
13. Músicas removidas da fonte deixam órfãos, e o sync também nunca limpa.
14. No Windows, a busca de aparelhos ignora discos USB "fixos" e não tem MTP.
15. iPod via WSL "Ubuntu" fixo.
16. No Mac, `diskutil` roda a cada 3 s.
17. Uma falha na verificação de update bloqueia por 24 h.
18. **`load_library` sem migração.** Se a versão mudar, cai silenciosamente para uma biblioteca **nova**, e a próxima gravação **sobrescreve a original**. É risco de perda de dados.
19. Desempenho de `_refresh` e `_show_tracks`.
20. `rmtree` sem lixeira.
21. 1 s de espera à toa ao abrir no Windows.

---

## 6. Modo "sempre rodando" (barra de menus + atualização automática)

### 6.1 Arquitetura
- **Separar o motor da interface:** um `LibraryService` sem widgets que carrega e salva a biblioteca (de preferência em SQLite), atualiza as playlists com os leitores diretos e roda o download.
- **O Spotify é o problema.** O leitor público precisa do QWebEngine. Opções:
  - QWebEngine **fora da tela** (`Qt.WA_DontShowOnScreen`), criado sob demanda e destruído depois (usa 200–400 MB enquanto está ativo);
  - a API oficial (OAuth), se configurada.
- **Instância única:** `QLockFile` + `QLocalServer`, para que "abrir janela" foque a instância que já está rodando.
- **Uma trava na biblioteca** compartilhada entre a barra de menus, a janela e o modo legado. SQLite em modo WAL resolve.

### 6.2 Ícone na barra de menus
- `QSystemTrayIcon` com um menu:
  - status: última atualização, próximas, novas e na fila;
  - Atualizar agora;
  - Pausar 1 h / até amanhã / Retomar;
  - Abrir biblioteca, Log e Sair.
- `app.setQuitOnLastWindowClosed(False)`, para que fechar a janela só a esconda.
- No Mac, usar um ícone monocromático (`QIcon.setIsMask(True)`).

### 6.3 Agendamento
- Intervalo por playlist (padrão de 6 a 12 h), com **±20% de variação** para não consultar todas as fontes ao mesmo tempo.
- Fila em série: atualizar da fonte → calcular a diferença → enfileirar só as novas e as que faltam → baixar.
- **Cota do YouTube:** no máximo N músicas por hora e por dia (ex.: 30/h). Se houver bloqueio, espera progressiva de 1 h → 4 h → 24 h, com notificação.
- **Horário silencioso** (ex.: 23:00–07:00) ou o inverso: "só baixar à noite".
- **Condições:**
  - rede (`QNetworkInformation`: pular se estiver offline ou em rede limitada);
  - bateria (pular abaixo de 20%);
  - ao acordar do repouso, retomar o que venceu (`NSWorkspaceDidWakeNotification`).
- **Evitar o App Nap** no Mac durante downloads: `NSProcessInfo.processInfo().beginActivityWithOptions_reason_(...)` via pyobjc.

### 6.4 Notificações
- Mínimo: `QSystemTrayIcon.showMessage`.
- Melhor no Mac: `UNUserNotificationCenter` via pyobjc (exige o app assinado), com as ações "Ver" e "Pausar".
- **Agrupar:** "Playlist X: 5 novas baixadas, 1 para revisar". Nunca uma notificação por música.
- Avisar só o que exige ação: bloqueio, cookies expirados, músicas não encontradas ou para revisar.

### 6.5 Abrir ao iniciar sessão (Mac)
1. **`SMAppService.mainAppService().register()`** (macOS 13+)
   - Aparece em Ajustes › Geral › Itens de Início.
   - Exige o `.app` assinado. Chamar via pyobjc (`from ServiceManagement import SMAppService`).
2. **LaunchAgent** (alternativa para app sem assinatura ou rodando do código)
   - Arquivo `~/Library/LaunchAgents/com.<voce>.csvmusic.plist` com:
     - `ProgramArguments` apontando para o app com `--background`;
     - `RunAtLoad=true`;
     - `KeepAlive={SuccessfulExit=false}`;
     - `ProcessType=Interactive`;
     - `LimitLoadToSessionType=Aqua`.
   - Ativar com `launchctl bootstrap gui/$(id -u) <plist>` e remover com `bootout`.
3. **`LSUIElement=true`** no `Info.plist`, para rodar sem ícone no Dock. Ao abrir a janela, trocar para `NSApplicationActivationPolicyRegular`.
4. Opção de linha de comando `--background`: inicia sem janela, sem o aviso inicial e sem diálogo de atualização (vira notificação).

### 6.6 Pausar e retomar
- Guardar `paused_until`, para sobreviver a reinícios.
- "Pausa suave": termina a música atual e para. A fila persistida continua de onde parou.
- Pausar o automático quando o usuário inicia um download manual, para não ter dois downloads disputando o YouTube.

### 6.7 Integração com o índice
- Antes de baixar uma música nova, consultar o índice. Se ela for `found_elsewhere`, referenciar, copiar ou criar hardlink em vez de baixar. **No caso do usuário, isso evitaria ~20% dos downloads.**
- Reindexar as pastas 1×/dia ou com um observador de arquivos.
- Escrever o M3U a cada N músicas.
- Opcional: sincronizar sozinho quando um aparelho conhecido for conectado, inclusive com playlists parciais.
