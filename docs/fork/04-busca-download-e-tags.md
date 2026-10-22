# 04 — Busca no YouTube Music, download e tags (análise profunda)

> **Como usar este documento:** é a referência técnica do "motor" do app. Leia antes de mexer em `ytmusic_match.py`, `downloader.py`, `track_output.py` ou `ui/workers.py`.
> Referências `arquivo:linha` são da v1.7.9. Onde aparecer caminho do Windows (`%LOCALAPPDATA%`), no Mac o equivalente é `~/Library/Application Support/<App>` (dados) ou `~/Library/Caches/<App>` (cache).
>
> **Conferido com o log real do usuário** (playlist "Out Of Time Man", 1123 faixas na fila, ~30 s por faixa, perfil "aggressive" ligado só pelo tamanho; faixa "Country House - 2012 Remaster" do Blur pulada com 0.59).
>
> Os 5 problemas que mais importam, em ordem: (1) sufixos do Spotify " - Remaster" etc. derrubando a nota; (2) ritmo lento fixo por tamanho da playlist + detecção de bloqueio quebrada; (3) "já baixado" = nome exato do arquivo; (4) arquivos parciais contam como baixados; (5) `_cleanup_outputs` apaga arquivos de outros formatos.


Guia de desenvolvimento em pt-BR. Escopo: `csvmusic/core/ytmusic_match.py`, `downloader.py`, `track_output.py`, `preflight.py`, `paths.py`, `audio_quality.py`, `source_quality.py`, `artwork.py`, `js_runtime.py`, `subprocess_env.py`, `log.py`, `csvmusic/ui/workers.py`, os trechos de pipeline de `csvmusic/ui/main_window.py` (e pontos de `library_mode.py` que reaproveitam o pipeline) e os testes `tests/core/test_ytmusic_match.py`, `tests/core/test_downloader.py` e `tests/ui/test_workers.py`. Nenhum arquivo do repositório foi alterado.

---

## 0. Resumo executivo

- **A pipeline é 100% sequencial:** para cada faixa, faz busca → download → ffmpeg → capa → tags → pausa. Não existe fase de busca separada, cache, fila persistente nem ETA.
- **O perfil de mitigação é escolhido só pelo tamanho do lote.** Com 500 faixas ou mais (`_YOUTUBE_EXTREME_BATCH_THRESHOLD = 500`, `downloader.py:32`) entra o perfil `AGGRESSIVE`. Com 250 ou mais (`_YOUTUBE_LARGE_BATCH_THRESHOLD = 250`, `downloader.py:31`) entra o `LARGE_BATCH`. O perfil agressivo já começa ativo e registra a mensagem "YouTube started throttling…", que é falsa nesse momento.
  - Efeito colateral grave: como o perfil já é o máximo, quando aparece um throttling **de verdade** não há escalonamento nem backoff (`workers.py:490`).
- **A detecção de throttling por bot-check está quebrada.** `_summarize_tool_output` reescreve a mensagem do yt-dlp (`downloader.py:170-173`) antes de `detect_youtube_risk` procurar o padrão original (`downloader.py:21-30`). Resultado: "Sign in to confirm you're not a bot" nunca é detectado como risco.
- **O caso real "Country House - 2012 Remaster" (confidence=0.59) dá para reconstruir exatamente.** A faixa veio **sem duração** (d_score neutro = 0.7). O título tem 4 tokens e só 2 batem com "Country House". Há ainda uma penalidade de 0.08 porque a marca "remaster" foi pedida e não aparece no candidato. Conta: 0.7·0.35 + 0.5·0.35 + 1.0·0.25 − 0.08 = **0.59**. Normalizar o sufixo com hífen leva o score a 0.845.
- **A detecção de "já baixado" compara o caminho exato** `Out/<Playlist>/<NN- >Artista - Título.<fmt>`. Mudar o prefixo numérico ou o formato faz baixar tudo de novo. Pior: `_cleanup_outputs` **apaga** arquivos `base.*` de outros formatos (`downloader.py:356-361`).
- **As gravações finais não são atômicas** em mp3 e opus, e a tag é aplicada depois que o arquivo já está no lugar. Arquivos parciais ou sem tag passam a contar como "já baixados".

---

## 1. Módulo a módulo

### 1.1 `csvmusic/core/ytmusic_match.py` (398 linhas): busca e ranqueamento

**Constantes (linhas 6-27)**

| Constante | Valor | Uso |
|---|---|---|
| `CONFIDENCE_MIN` | 0.6 | limiar de aceitação automática |
| `SEARCH_LIMIT` | 12 | resultados por filtro e por query |
| `ALT_SEARCH_LIMIT` | 24 | diálogo de alternativas |
| `RATE_LIMIT_S` | 0.35 | pausa mínima entre faixas |
| `DURATION_TOLERANCE_RATIO` | 0.10 | corte duro de duração (±10%) |
| `SHORT_TRACK_MAX_SECONDS` / `SHORT_TRACK_TOLERANCE_SECONDS` | 45 / 8 | faixas curtas usam tolerância absoluta |
| `SEARCH_RETRY_COUNT` / `SEARCH_RETRY_SLEEP_S` | 2 / 0.9 | retentativas quando não sobra nenhum candidato |
| `_PENALTY_TERMS` | cover, sped, slowed, nightcore, 8d, reverb, mashup, karaoke, instrumental, demo, tribute, soundalike | −0.10 cada (por **substring**) |
| `_VERSION_PATTERNS` | live, acoustic, extended (`long version`), remix (`remix(ed)?` e `\bmix\b`), edit (`radio version`), single (`single version`, `original single`, `u.s. single`), remaster, album (`album version`) | marcas de versão |
| `_CAST_PENALTY_TERMS` | cast, original cast, tribute band, musical, orchestra | −0.18 cada, só quando artist_overlap == 0 |

**Funções**

- `_norm_text(s)` (29): casefold, NFKC e colapso de espaços.
- `_toks(s)` (33): conjunto de tokens `\w+` normalizados.
- `_candidate_artist_text(cand)` (37): junta `artists[].name`; se não houver, usa `author`.
- `_candidate_album_text(cand)` (45) e `_candidate_version_markers(cand)` (53): as marcas do candidato vêm de **título + álbum**.
- `_artist_names` (58) e `_result_author(result, artists)` (70): `author` vem de author/channel/uploader/name ou dos nomes dos artistas.
- `_overlap_ratio(needle, haystack)` (80): fração dos tokens **da faixa pedida** que aparecem no candidato. Tokens extras no candidato não penalizam.
- `_contains_non_latin_letters` (84): ativa o "piso de tradução".
- `_version_markers(value)` (94).
- `_duration_s(d)` (98): aceita int, `"m:ss"` ou `"h:mm:ss"`.
- `_track_duration_s(track)` (116): `duration_ms / 1000`.
- `_duration_within_tolerance(track, cand)` (122): corte duro. Se algum lado não tem duração, aceita.
- `_score(track, cand) -> float` (131-206): detalhado na seção 2.
- `_clean_title_artist(title, artists)` (208): `"title artists"`, trocando `" - "`, `–` e `—` por espaço.
- `_strip_noise(title)` (216): remove colchetes/parênteses com feat, official, live ou remix e depois remove os caracteres de colchete restantes, mantendo o conteúdo.
- `_query_variants(track) -> List[str]` (227-268): gera as variantes de query, na ordem:
  1. `f"{isrc} {clean}"`, se houver ISRC;
  2. `base`;
  3. `clean`, se diferente de `base`;
  4. `&`→`and`;
  5. `and`→`&`;
  6. `-`→espaço.

  São até **6 variantes**, deduplicadas, e todas sempre executadas.
- `_search_filter(yt, q, filter, limit)` (273): chama `yt.search` e normaliza cada resultado em `{videoId, title, artists (só para songs), author, channel, duration_seconds, album, source: "music"|"videos"}`.
- `_search(yt, q, limit, source_mode)` (296): com `"all"`, roda **songs E videos**, ou seja, 2 chamadas HTTP por variante.
- `_rank_candidates(yt, track, limit, source_mode, *, enforce_duration=True)` (305-342): executa todas as variantes, deduplica por videoId, aplica o corte de duração, pontua e ordena por `priority = (score>=0.6, is_music se score>=0.6, score, is_music)`.
- `find_best(yt, track) -> (match|None, score, options)` (344-363): se `options` vier vazio, dorme 0.9 s e refaz tudo com `YTMusic()` novo, até 2 vezes.
- `more_candidates(track, exclude_ids, limit=24, source_mode)` (365): usado pelo diálogo de alternativas. `enforce_duration=False`, resultados "music" primeiro.
- `batch_match(tracks)` (376): usado só pelos CLIs `csvmusic/download_csv.py` e `match_csv.py`.

**Custo por faixa:** 2 a 6 variantes × 2 filtros = **4 a 12 requisições de busca**. Se nada passar no filtro de duração, isso é multiplicado por 3 por causa das retentativas.

```
find_best
 └─ _rank_candidates
     ├─ for q in _query_variants(track):      # 2..6
     │    ├─ yt.search(q, "songs", 12)
     │    └─ yt.search(q, "videos", 12)
     ├─ dedupe(videoId)
     ├─ filter _duration_within_tolerance     # corte duro
     ├─ _score each
     └─ sort(priority)
 └─ if empty: 2x (sleep 0.9; YTMusic(); _rank_candidates)
 └─ best if score>=0.6 else None
```

### 1.2 `csvmusic/core/downloader.py` (892 linhas)

**Constantes**

- `YTM_URL` e `YT_URL` (17-18).
- `YOUTUBE_CLIENTS = ["web_embedded", None, "ios", "tv", "android_vr"]` (19). `None` significa o padrão do yt-dlp.
- `MP3_SOURCE_FORMAT = "bestaudio/best"` (20).
- `_YOUTUBE_RISK_PATTERNS` (21-30). São os sinais que `detect_youtube_risk` (212-217) reconhece:
  1. `http error 429`
  2. `too many requests`
  3. `sign in to confirm you're not a bot`, com apóstrofo ASCII e com apóstrofo tipográfico
  4. `confirm you're not a bot`, nas duas variantes de apóstrofo
  5. `this content isn't available, try again later`
  6. `unable to download video data: http error 403`
- `_YOUTUBE_LARGE_BATCH_THRESHOLD = 250` e `_YOUTUBE_EXTREME_BATCH_THRESHOLD = 500` (31-32).
- `_TARGET_LOUDNESS_I = -16.0`, `_TARGET_TRUE_PEAK_DB = -2.5` e `_MAX_SAFE_NAME_LENGTH = 140` (107-109).

**Perfis de mitigação: `YouTubeMitigationProfile` (63-105)**

| Perfil | track_sleep | --sleep-requests | --sleep-interval / --max-sleep-interval | --limit-rate |
|---|---|---|---|---|
| `normal` | 0 (usa `RATE_LIMIT_S` = 0.35) | – | – | – |
| `large-batch` (≥250) | 5.0 s | 0.75 s | 5 a 10 s | 1.5M |
| `aggressive` (≥500 **ou** risco detectado) | 6.0 s ±20% de jitter (máx. 1 s) | 1.25 s | 8 a 15 s | 900K |

- `youtube_batch_mitigation(track_count, *, using_cookies)` (186): o parâmetro `using_cookies` **é ignorado**.
- `youtube_risk_acknowledgement(profile)` (194): texto do diálogo de confirmação.
- `build_ytdlp_mitigation_args(profile)` (220).

**Execução**

- `_run_capture(cmd)` (119): `subprocess.run` com UTF-8, ambiente saneado e janela oculta. **Não tem timeout.**
- `_run_ytdlp_module(args)` (130): quando `ytdlp_path()` devolve `INTERNAL_YTDLP`, o yt-dlp roda **no mesmo processo**, via `yt_dlp.main` com `contextlib.redirect_stdout/stderr`. Esse redirecionamento é global ao processo.
- `_run_ytdlp_detail(cmd) -> (rc, detail)` (288):
  - injeta `--no-simulate --print after_move:%(.{id,format_id,acodec,vcodec,abr,tbr})j` para capturar o formato de origem (`capture_source`);
  - resume o erro com `_summarize_tool_output`;
  - levanta `AgeRestrictedError` imediatamente quando detecta restrição de idade.
- `_summarize_tool_output(stderr, stdout, *, using_cookies)` (152): descarta as linhas `[download]`, converte erros conhecidos (idade, bot-check, falta de runtime JS, formato indisponível) em mensagens amigáveis e trunca em 280 caracteres.
- `_youtube_clients(cookie_args)` (309): com cookies usa só `[None]`; sem cookies, os 5 clientes.
- `_extractor_args(client)` (636): `--extractor-args youtube:player_client=<client>`.
- **Código morto:** `_run` (111), `_run_ytdlp` (284), `_strip_cookie_args` (234) e `_should_retry_without_cookies` (254). Este último é testado, mas nunca chamado.

**Nomes de arquivo**

- `sanitize_name` (325): NFC, troca de `\ / : * ? " < > |` por equivalentes fullwidth, remoção de caracteres de controle e de ponto/espaço no fim, truncamento em 140 caracteres com sufixo `-<sha256[:10]>`.
- `_filename_starts_with_base` e `_list_downloads` (341-354): comparam nas 4 formas Unicode.
- `_cleanup_outputs(dir, base)` (356): **apaga todo arquivo `base.*`**.
- `_replace_file` (364): `unlink` seguido de `replace`, portanto não é atômico no Windows.

**Formatos**

- **`download_m4a(video_id, dst_dir, base_name, *, yt_dlp_bin, ffmpeg_bin, extra_yt_dlp_args, audio_processing)` (642-727)**
  - Primário: `-f "ba[ext=m4a]/bestaudio[ext=m4a]/bestaudio" --no-playlist --force-overwrites --retries 5 --fragment-retries 5 --socket-timeout 30`.
  - Fallback: `-f bestaudio --no-continue` com os mesmos demais argumentos.
  - Ordem dos argumentos: `[bin, fmt…] + extractor_args + js_runtime_args + cookies/mitigation + ["-o", "<dir>/<base>.%(ext)s", url]`.
  - Laços: 2 URLs (music.youtube e www.youtube) × 5 clientes × (primário + fallback) = **20 invocações**. Depois vem `ytsearch1:{base_name}` × 5 clientes. **Pior caso: 25 invocações do yt-dlp por candidato.**
  - Pós-processamento em `_normalize_to_m4a` (449): sem processamento de áudio faz `ffmpeg -c:a copy` para `.normalized.m4a` e depois replace; com processamento, reencoda com o encoder nativo `aac -b:a 192k`.
- **`download_opus` (729-780):** `-f "ba[acodec^=opus]"` sem fallback de formato nem de busca, 10 invocações no máximo, remux com `-map 0:a:0 -c:a copy` para `.opus`. **Ignora `audio_processing`.**
- **`download_mp3` (782-864):** `-f bestaudio/best -o <base>.tmp`, 10 invocações mais 5 de busca. Depois `ffmpeg [-af chain] -codec:a libmp3lame`, que pode ser:
  - `-b:a {cbr}k` no modo legado (192, 256 ou 320);
  - `-b:a 320k` com `cbr_320`;
  - `-q:a {0..10}`, VBR, com padrão V0.

  O ffmpeg escreve **diretamente no `.mp3` final**.

**Loudness**

- `_measure_static_normalize_gain` (405): um passo de medição com `loudnorm=I=-16:TP=-2.5:LRA=11:print_format=json`.
- O ganho é `min(-16 - input_i, -2.5 - input_tp)`.
- `_audio_filter_chain` (429): monta `bass=g:f=110:w=0.6`, `treble=g:f=6000:w=0.6` e `volume=XdB`, e **sempre** acrescenta `alimiter=limit=0.750` quando há processamento.
- É uma normalização **estática**: ganho único mais limitador, sem o modo dinâmico do loudnorm. A escolha é boa para preservar a dinâmica, mas exige decodificar o arquivo duas vezes e regrava áudio com perdas.

**Capa**

- `yt_thumbnail_bytes` (488): tenta maxres, sd, hq, mq e default.
- `cover_art_url_bytes` (500) com `artwork.artwork_download_urls`: troca variantes do Spotify por `ab67616d0000b273`, que tem 640 px.
- `_fetch_cover_art_url_bytes` (512): limite de 10 MB.
- `_square_cover_art_bytes` (524): corte central para quadrado de 600 px via QImage, com fallback em ffmpeg.

**Tags: `tag_file(path, meta, cover_bytes, *, cover_size=600)` (582-633)**

| Formato | O que grava |
|---|---|
| MP3 | EasyID3 com title, artist (string única `"A, B"`), album, date (ano), tracknumber e discnumber; APIC tipo 3. Salva em ID3 **v2.4 sem capa e v2.3 com capa**. |
| Opus | title, artist, album, date, tracknumber, discnumber e `metadata_block_picture`. |
| MP4 | ©nam (atribuído como **str**, não lista), ©ART, ©alb, ©day, `trkn (n,0)`, `disk (n,0)` e covr. |

Não grava albumartist, gênero, ISRC, totais, letras, ReplayGain nem IDs MusicBrainz.

**M3U: `write_m3u(...)` (866)**

- Recalcula o caminho pelo nome do arquivo, sem usar o caminho real.
- Escreve `#EXTINF`, `#EXTISRC` e `#EXTALBUM` com caminho relativo, ou absoluto quando o drive é outro.

### 1.3 `track_output.py`

- `track_filename_base(track)` (8): `"Artista - Título"`, com `"NN- "` na frente quando `filename_prefix_number` existe. A largura vem de `filename_prefix_width`, mínimo 2.
- `expected_track_path(track, out_root, fmt)` (22): `out_root/sanitize(playlist)/sanitize(base).fmt`.
- `duplicate_output_rows` (28): agrupa linhas com o mesmo caminho em casefold.
- `TrackOutputPlan` e `plan_track_outputs(tracks, out_root, fmt)` (42-70): classifica cada linha como duplicada, existente (`.exists()` e sem `force_redownload`) ou na fila.

### 1.4 `preflight.py`, `paths.py`, `js_runtime.py` e `subprocess_env.py`

- **`run_preflight_checks(yt_override, ff_override, *, skip_network, require_mp3)`** (`preflight.py:216`) verifica:
  - a versão do yt-dlp (ou do módulo interno);
  - `ffmpeg -version` e `-encoders`, procurando libmp3lame, com fallback para o ffmpeg do sistema;
  - um runtime JS (Deno 2.3+ embutido, Node 22+ ou QuickJS) e se o yt-dlp é ≥ 2026.06.09, quando passou a suportar `--js-runtimes`;
  - `GET https://music.youtube.com`.

  Falta de runtime JS conta como **erro**.
- **`ytdlp_path()`** (`paths.py:527`) procura nesta ordem: variáveis `YTDLP_BIN`/`YT_DLP_BIN`, `yt-dlp(.exe)` ao lado do executável do Python, `.venv`/`venv`, PATH e, por último, o módulo interno (`INTERNAL_YTDLP`). No app congelado (PyInstaller), na prática cai no módulo interno, fixado em **`yt-dlp[default]==2026.8.19`** (pyproject). Não há como atualizar o yt-dlp sem uma nova release.
- **`ffmpeg_path()`** (`paths.py:435`): `FFMPEG_BIN`, depois uma longa lista de candidatos empacotados, `C:/ffmpeg`, choco, scoop e Program Files, e por fim o PATH.
- **`ytdlp_js_runtime_args`** (`js_runtime.py:313`): `--js-runtimes deno:<path>`, repetível.
- **`sanitized_subprocess_env()`**: restaura as variáveis que o PyInstaller alterou e força `PYTHONUTF8=1`.

### 1.5 `audio_quality.py`, `source_quality.py` e `log.py`

- **`source_quality`**
  - `capture_source(stdout)` guarda `{video_id, codec, kbps (abr ou tbr), format_id}` em `threading.local`.
  - `store_source(path)` grava esse JSON em `TXXX:CSVMUSIC_YOUTUBE_SOURCE` (MP3), `----:com.csvmusic:…` (MP4) ou num campo Vorbis (Opus).
  - `read_source` lê de volta.
- **`audio_quality`**
  - `classify_audio_quality(codec, bitrate)` usa os limiares MP3 128, AAC 96, OPUS 96 e VORBIS 112 kbps.
  - `_inspect` tem `lru_cache` por `(path, size, mtime)`.
- **`log`:** grava em `~/.local/share/csvmusic/app.log`, inclusive no Windows. Abre e fecha o arquivo a cada linha e **não faz rotação**.

### 1.6 `csvmusic/ui/workers.py`

- **Funções auxiliares**
  - `_legacy_cover_size` (67): off = 0, small = 300, medium = 450, padrão = 600.
  - `_track_cover_bytes` (80): capa da origem; se não houver, miniatura do YouTube.
  - `_legacy_cbr_bitrate` (87).
  - `_run_yt_dlp_command` (105): duplica `_run_ytdlp_module`.
- **`_FORCE_FALLBACK_MIN_SCORE = 0.45`** (26).
- **`PipelineWorker(QThread)`** (143-572)
  - **Sinais:** `sig_log`, `sig_warning`, `sig_total`, `sig_match_stats`, `sig_row_status`, `sig_progress`, `sig_done(msg, done, skipped, failed)`, `sig_track_result(row, payload)`.
  - `_download_with_profile(vid, dest_dir, base, profile)` (197): monta cookies (arquivo **ou** navegador) mais os argumentos de mitigação e despacha por formato.
  - `_set_track_audio_processing` (210): `audio_volume_gain` por faixa, limitado a ±12 e somado ao global.
  - `_apply_mitigation` (218): só emite o aviso quando o rótulo do perfil muda.
  - `_track_pause_s` (229).
  - `_is_official_candidate` (235): source music, ou "topic", "official", "vevo" no autor, ou "official" no título.
  - `_candidate_relevant_to_track` (243).
  - `_force_download_candidates` (252): até 2 oficiais e 2 comuns, sendo que o segundo de cada grupo só entra com score ≥ 0.45.
  - `_ordered_force_candidates` (282).
  - `run()` (306-572): o fluxo está abaixo.
- **`SingleDownloadWorker`** (576-660): download manual de uma alternativa. Não aplica ganho por faixa nem mitigação, e o parâmetro `force_download` não é usado.
- **`AlternativesFetchWorker`** (663): chama `more_candidates(..., source_mode="all")`.
- **`CookiesCheckWorker`** (704) e **`YouTubeSessionTestWorker`** (681): validação de cookies, incluindo leitura direta de `moz_cookies` do Firefox.

**Fluxo de `PipelineWorker.run()`**

```
load tracks (override | CSV)
mitigation = youtube_batch_mitigation(len(queued))         # 319
YTMusic() anônimo
for idx, track:
  if stop: break
  if preferred_video_id: match = {videoId, score 1.0}
  else: match, conf, options = find_best(yt, t)            # 373
  contadores: search_error / empty                          # 376-384
  if match None and force_download and options:
       match = _force_download_candidates(...)[0]           # 399-405
  if match None:
       skipped; emit; if errors>=3 or empty>=5: abort        # 426-437
       sleep(track_pause); continue                          # 438
  candidates = _ordered_force_candidates(...)
  try: for cand: download → "Tagging…" → cover → tag_file → break
  except AgeRestrictedError: propaga
  except other:
       risk = detect_youtube_risk(err)
       if risk and perfil != aggressive: aplica aggressive, repete o laço inteiro
       senão: failed
  audio_quality(fp); emit result
  sleep(track_pause) + 0.02
after loop: write_m3u por playlist (só arquivos existentes)
sig_done
```

### 1.7 `main_window.py`: partes do pipeline

- **`_build_track_preview`** (1860-1942): roda `plan_track_outputs`, marca linhas como "Already downloaded", "Duplicate entry" ou "Queued" e devolve `queued_rows`.
- **`on_start`** (2261-2376), em ordem:
  1. valida a pasta de saída;
  2. roda o preflight;
  3. monta o preview;
  4. se não houver nada na fila, chama `_rewrite_playlists` e encerra;
  5. pergunta sobre risco com base em `len(self.tracks)`, isto é, **todas** as linhas, embora o worker conte só as da fila;
  6. cria o `PipelineWorker` com `tracks_override=active_tracks` e `row_indices=queued_rows`. **Não passa** `m3u_tracks_override`.
- **`on_stop`** (2378): só liga a flag `_stop`.
- **`on_load_playlist`** (2384): é o botão `btn_scan_existing`, "Scan Playlist Folder" (755-758). Resolve a raiz a partir da pasta ou do .m3u e roda o mesmo `_build_track_preview`. É **checagem de existência por nome**, não leitura de tags.
- **`on_track_result`** (2443): atualiza `track_results`, propaga para as linhas duplicadas e chama `record_library_download_result` quando a faixa vem da biblioteca.
- **`on_done`** (2575): monta o resumo e chama `_rewrite_playlists()`, que **sobrescreve** o M3U gravado pelo worker.
- **Alternativas:**
  - `on_open_alternatives` (2502) e `on_resolution_options` (2630): mesclam as opções e ordenam por score.
  - `on_refresh_alternatives` (2820): `AlternativesFetchWorker` com exclude_ids.
  - `on_resolution_paste_url` (2752): opção manual com score 1.0.
  - `on_resolution_download` (2849): `SingleDownloadWorker`.
  - `on_resolution_skip` (2894): **apaga o arquivo de áudio** do disco.
  - `on_resolution_finished` (2952): não propaga para as linhas duplicadas.
- **`_rewrite_playlists`** (2998-3043) e **`_write_playlist_file`** (3045): reescrevem a partir das linhas da tabela, com CRLF, sem `#EXTALBUM`/`#EXTISRC` e com **um único nome de playlist** para todas as linhas.
- **`closeEvent`** (3106): chama `_shutdown_thread`, que pode chegar a `QThread.terminate()` (3100-3102).

---

## 2. O algoritmo de pontuação em detalhe

### 2.1 Fórmula (`ytmusic_match.py:131-206`)

```
title_overlap  = |T_faixa ∩ T_cand_título| / |T_faixa|
artist_overlap = |A_faixa ∩ A_cand|        / |A_faixa|
d_score:  Δ≤6s→1.0 | ≤12→0.9 | ≤20→0.78 | ≤30→0.62 | >30→0.45 | sem duração→0.70
ch_boost = 0.15 se "topic" ou "official" ∈ author normalizado
version_boost = 0.14 se marcas pedidas == marcas do candidato (e não vazias)

total = 0.35·d + 0.35·title + 0.25·artist + ch_boost + version_boost − penalidades
total = clamp(total, 0, 0.99)
Piso de tradução: título pedido tem letras não latinas ∧ source=="music"
                  ∧ |Δ|≤3s ∧ marcas iguais ∧ nenhum termo de penalidade → max(total, 0.68)
```

**Penalidades**

- Cada termo de `_PENALTY_TERMS` encontrado **como substring** em `título + artista` do candidato: −0.10.
- Quando a faixa pede marcas de versão:
  - marca pedida e ausente no candidato: −0.34 (−0.08 se for remaster);
  - marca extra no candidato: −0.26 (−0.03 se for remaster).
- Quando a faixa não pede nenhuma marca: −0.30 por marca do candidato que não seja remaster.
- Com `artist_overlap == 0`: −0.18 por termo de elenco. "original cast" também contém "cast", então conta duas vezes (−0.36).
- "tribute" no candidato com `artist_overlap < 0.5`: −0.25, somado aos −0.10 do termo genérico.

O máximo teórico sem bônus é 0.95. Com `ch_boost` e `version_boost` chega ao teto de 0.99.

**Corte prévio de duração** (`_duration_within_tolerance`): faixas acima de 45 s aceitam até ±10% (uma faixa de 4 min aceita ±24 s); faixas de até 45 s aceitam ±8 s. Se um dos lados não tem duração, o candidato passa.

### 2.2 Casos de falha reais ou previsíveis

1. **Sufixo do Spotify com hífen.** "Country House - 2012 Remaster" gera os tokens {country, house, 2012, remaster}. O candidato "Country House" cobre 2 de 4, então title = 0.5. Sem duração, d = 0.7. A marca remaster foi pedida e falta: −0.08. Total 0.59, e a faixa é pulada. O mesmo acontece com "- Radio Edit", "- Live at …", "- Remastered 2011", "- Mono", "- From \"Film\"" e "- 2009 Mix" (este ainda vira marca de remix). Na query, `_clean_title_artist` só transforma `" - "` em espaço, então o ruído continua na busca.
2. **"feat." no título pedido.** `_strip_noise` só é usado para montar as queries. **O score usa o título cru.** Assim, "Song (feat. B)" tem tokens {song, feat, b}, e o candidato "Song" fica com title = 0.33. "(with X)" não é removido em nenhum lugar.
3. **Penalidades por substring.** "Demons" (Imagine Dragons) contém "demo" e perde 0.10. Também são afetados "Discover"/"Undercover" (cover), "Castle on the Hill" e "Broadcast" (cast, quando não há overlap de artista) e "Reverberation".
4. **Marcas assimétricas.** As marcas do candidato incluem o **álbum** (`_candidate_version_markers`, linha 56), mas as da faixa vêm só do **título** (linha 168). Uma faixa do Spotify vinda de "Live at Leeds" com título limpo recebe −0.30 justamente na versão correta, e a versão de estúdio vence. O álbum "Live Through This" (Hole) faz toda faixa dele ser tratada como "live". A faixa pedida nunca considera o próprio campo `album`.
5. **`\bmix\b` conta como remix**, então "2009 Mix", "Mono Mix" e "Stereo Mix" levam −0.30 quando a faixa não pede versão.
6. **O `ch_boost` quase nunca é aplicado.** Para resultados "songs", `author` é o nome do artista (via `_result_author`), e o ytmusicapi raramente devolve "- Topic" no autor.
7. **Duração filtrada vira "busca vazia".** Se todos os candidatos caem no corte de ±10% (versão extended, live longa, metadado errado), `options == []`. Isso dispara 2 rodadas extras de busca e conta para o **aborto do lote após 5 vazias seguidas**, com a mensagem falsa de que a busca está bloqueada (`workers.py:379-381, 430-437`).
8. **ISRC misturado ao texto.** A query `"{isrc} {título artista}"` dilui o sinal. A busca do YTM por ISRC puro costuma devolver a faixa exata no filtro songs.

### 2.3 Correções propostas

**a) Normalização de sufixos com hífen e de "feat"/"with", tanto na query quanto no score**

```python
_DASH_SUFFIX = re.compile(
	r"\s+[-–—]\s+(?P<q>(?:\d{4}\s+)?(?:remaster(?:ed)?|re-?master(?:ed)?)(?:\s+\d{4})?(?:\s+version)?"
	r"|radio edit|single version|album version|mono|stereo|(?:\d{4}\s+)?mix|live(?:\s+.*)?|acoustic(?:\s+.*)?"
	r"|from .*|edit|extended(?:\s+.*)?|bonus track|demo)\s*$", re.I)
_FEAT = re.compile(r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+[^\)\]]+[\)\]]", re.I)

def split_title(title: str) -> tuple[str, set[str], list[str]]:
	"""Devolve (título_núcleo, marcas_de_versão, artistas_convidados)."""
	guests = [m.group(0) for m in _FEAT.finditer(title)]
	core = _FEAT.sub("", title)
	markers = _version_markers(core)
	m = _DASH_SUFFIX.search(core)
	if m:
		core = core[:m.start()]
	core = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", core)  # demais qualificadores
	return re.sub(r"\s+", " ", core).strip(), markers, guests
```

O score passa a comparar **título-núcleo com título-núcleo**. As marcas vêm de `split_title` aplicado ao título **e** ao álbum da faixa (simetria com o candidato). Os convidados do feat entram no conjunto de artistas, não no título.

**b) Penalidades por token ou regex com `\b`**, em vez de `in titleblob`.

**c) Busca em cascata com saída antecipada**

1. ISRC sozinho, filtro `songs`, limite 5. Aceita se título-núcleo ≥ 0.6, artista ≥ 0.5 e |Δ| ≤ 3 s.
2. `songs` com a query núcleo (título-núcleo + artista principal). **Se o melhor tiver score ≥ 0.85, para aqui.**
3. Variantes (`&`/`and`, hífen) em `songs`, ainda com saída antecipada.
4. `videos` só como fallback, quando nada passou de 0.6.

O custo médio cai de 4 a 12 requisições para 1 ou 2.

**d) Checagem cruzada de álbum e duração.** Bônus de +0.08 quando os tokens do álbum do candidato cobrem ≥ 60% do álbum pedido; bônus de +0.05 quando |Δ| ≤ 2 s.

**e) "Vazio após filtro" ≠ "vazio de verdade".** `_rank_candidates` deve devolver também `raw_count`. Os retries e o contador de aborto só olham `raw_count == 0`. Candidatos fora da tolerância vão para `options` com uma flag (`duration_mismatch`), em vez de serem descartados.

**f) Ajuste do limiar.** Com núcleo normalizado, 0.6 continua razoável. O ideal é registrar `(score, aceito_pelo_usuário)` e calibrar com um conjunto rotulado, por exemplo exportado do diálogo de alternativas. Uma zona cinza de 0.5 a 0.6 pode ir para uma fila de "revisar" em vez de pular.

**g) Cache de busca em disco.** SQLite em `%LOCALAPPDATA%/csvmusic/match_cache.sqlite`:

```sql
CREATE TABLE search_cache(
  key TEXT PRIMARY KEY,          -- 'isrc:USXX...' ou 'ta:<núcleo_título>|<artista_principal>|<dur//5>'
  candidates_json TEXT NOT NULL, -- lista ranqueada
  chosen_video_id TEXT,
  score REAL,
  algo_version INTEGER NOT NULL, -- invalida quando o score mudar
  created_at INTEGER NOT NULL
);
CREATE TABLE manual_override(
  playlist_key TEXT, track_key TEXT, video_id TEXT, source TEXT, created_at INTEGER,
  PRIMARY KEY(playlist_key, track_key)
);
```

TTL sugerido: 30 dias para candidatos, sem expiração para escolhas manuais. Hoje a escolha feita em "Alternatives" no modo principal se perde ao fechar o app. A biblioteca guarda `preferred_video_id`; o modo principal não guarda nada.

**h) Testes ausentes:** `_strip_noise`, `_query_variants`, sufixos com hífen, retry e aborto do `find_best`, e composição dos comandos `download_*`.

---

## 3. Invocação do yt-dlp

### 3.1 Comando efetivo (m4a, sem cookies, perfil agressivo)

```
<yt-dlp|módulo interno> --no-simulate --print "after_move:%(.{id,format_id,acodec,vcodec,abr,tbr})j"
  -f "ba[ext=m4a]/bestaudio[ext=m4a]/bestaudio" --no-playlist --force-overwrites
  --retries 5 --fragment-retries 5 --socket-timeout 30
  --extractor-args youtube:player_client=web_embedded
  --js-runtimes deno:<path>
  --sleep-requests 1.25 --sleep-interval 8 --max-sleep-interval 15 --limit-rate 900K
  -o "<out>/<Playlist>/<NN- Artista - Título>.%(ext)s"
  https://music.youtube.com/watch?v=<id>
```

### 3.2 Pontos principais

- **Cookies.** `--cookies <arquivo>` tem prioridade sobre `--cookies-from-browser firefox:<perfil>`; o perfil do Firefox é detectado lendo `moz_cookies` (`main_window.py:1982`). Com cookies, só o cliente padrão é usado, o que permite formatos Premium (141, AAC 256k). O teste e a validação ficam em `CookiesCheckWorker` e `YouTubeSessionTestWorker`.
- **Runtime JS.** É obrigatório (preflight). Usa Deno embutido; se não houver, Node ≥ 22 ou QuickJS. O argumento `--js-runtimes` só é passado se o yt-dlp for ≥ 2026.06.09.
- **Fallback de player_client.** Ordem web_embedded → padrão → ios → tv → android_vr, repetida para as duas URLs.
- **Restrição de idade.** É detectada no resumo e vira `AgeRestrictedError`, que interrompe as tentativas e é repassada pelo worker (`workers.py:475, 511`), com mensagem diferente para "com cookies" e "sem cookies".
- **Fallback por busca do YouTube** (`ytsearch1:{base_name}`). Baixa **o primeiro resultado do YouTube, sem nenhuma verificação** e usando o nome do arquivo, que pode trazer o prefixo `"07- "`. É uma fonte de áudio errado silencioso.
- **Pós-processamento por formato:**
  - **m4a:** remux com `-c:a copy`. Se o yt-dlp caiu em `bestaudio` webm/opus, **Opus é copiado para dentro do .m4a**. Isso é incompatível com iTunes e iPod, e o app tem recursos de iPod. Com processamento, reencoda em AAC nativo a 192k.
  - **mp3:** sempre transcodifica (lossy→lossy) com libmp3lame em V0 por padrão. V0 vindo de Opus 128-160k só aumenta o tamanho do arquivo.
  - **opus:** remux sem perdas para Ogg e **ignora** a normalização e o EQ.
- **Arquivos temporários:**
  - mp3: `<base>.tmp`, apagado depois do ffmpeg, mas o ffmpeg grava o `.mp3` final direto;
  - m4a: `<base>.normalized.m4a` e depois `_replace_file`;
  - opus: remux direto no destino;
  - `.part` do yt-dlp: limpo na próxima tentativa por `_cleanup_outputs`.
- **Atomicidade.** Nenhuma. Com crash ou `terminate()`, fica um arquivo final parcial ou sem tags, que é tratado como "já baixado".

### 3.3 Por que cerca de 30 s por faixa (perfil agressivo)

| Etapa | Tempo estimado |
|---|---|
| Busca: 4 a 6 chamadas HTTP | 2 a 5 s |
| Inicialização do yt-dlp e desafio JS com Deno | 1 a 3 s |
| `--sleep-requests 1.25` × ~4 a 6 requisições de extração | 5 a 7 s |
| `--sleep-interval 8-15` antes do download | média 11.5 s |
| Download de ~4 MB a 900 KB/s | ~4.5 s |
| ffmpeg (mais o passo de loudnorm, se ativo), capa e tags | 2 a 4 s |
| Pausa entre faixas | 6 ± 1.2 s |

Soma: cerca de 30 a 40 s. Para 1123 faixas, isso dá aproximadamente 9 a 11 h, o que confere com o relato do usuário. A pausa de 6 s também é aplicada **depois de faixas puladas**, em que nada foi baixado (`workers.py:438-439`).

---

## 4. Retomada e detecção de existentes

### 4.1 Situação atual

- A chave é o caminho exato `expected_track_path`, com `.exists()` (`track_output.py:66`).
- **Mudar o formato** (mp3→m4a) faz tudo ser baixado de novo, e `_cleanup_outputs` **apaga o mp3 antigo** de cada faixa reprocessada.
- **Ligar ou desligar o prefixo numérico ou mudar a posição na playlist** também baixa tudo. Na biblioteca, `_pending_download_tracks` coloca explicitamente na fila toda faixa cujo estado de prefixo mudou (`library_mode.py:83`). Só existe um resgate parcial: `library_track_path` (`library.py:519-540`) aceita o nome sem prefixo quando a correspondência é única.
- Arquivos parciais ou sem tag contam como existentes.
- Duas versões diferentes com o mesmo "Artista - Título" (de álbuns diferentes) colapsam como duplicadas.
- O botão "Scan Playlist Folder" também é só checagem de existência por nome.

### 4.2 Proposta: banco de estado por pasta de saída

Arquivo `<out_root>/.csvmusic/state.sqlite` (oculto), que acompanha a pasta se ela for movida.

```sql
CREATE TABLE tracks(
  track_key TEXT PRIMARY KEY,   -- isrc:XXX | sp:<id> | norm:<núcleo_título>|<artista_principal>|<dur//2>
  title TEXT, artists_json TEXT, album TEXT, duration_ms INTEGER, isrc TEXT
);
CREATE TABLE files(
  track_key TEXT, fmt TEXT, rel_path TEXT, size INTEGER, mtime_ns INTEGER,
  sha1_head TEXT,               -- hash dos primeiros 256 KB + tamanho (barato)
  video_id TEXT, source_json TEXT, tags_version INTEGER,
  complete INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(track_key, fmt)
);
CREATE TABLE playlist_entries(
  playlist_key TEXT, position INTEGER, track_key TEXT, PRIMARY KEY(playlist_key, position)
);
CREATE TABLE jobs(...);  -- ver seção 5
```

**Regras**

1. **Identidade lógica, não nome de arquivo.** A `track_key` usa o ISRC quando existe; senão, o id da plataforma; senão, uma chave normalizada (sem prefixo `^\d+-\s`, título-núcleo, artista principal).
2. **Gravar a identidade dentro do arquivo.** O app já grava `CSVMUSIC_YOUTUBE_SOURCE`; o JSON pode ganhar `track_key` e `isrc`. Assim, um rescan reconstrói o banco **lendo as tags com mutagen**, mesmo se ele for apagado.
3. **Rescan** (substitui o "Scan Playlist Folder"): percorre `*.mp3|m4a|opus` e lê, em ordem, o TXXX csvmusic, depois TSRC/ISRC e por fim título, artista e duração.
   - Casa primeiro pela chave exata.
   - Senão, faz casamento difuso: título-núcleo com token-set ratio ≥ 0.9, artista ≥ 0.8 e |Δduração| ≤ 3 s.
   - Ignora o prefixo numérico e diferenças de forma Unicode.
4. **Mudança de posição ou de prefixo: renomear em vez de baixar.** Se o arquivo da `track_key` existe com outro nome, faz `os.replace(old, new)` e atualiza o banco, sem nenhuma requisição ao YouTube.
5. **Mudança de formato.** Se o formato pedido não existe mas outro existe:
   - se o arquivo é Opus e o pedido é Opus/m4a e o `video_id` é conhecido: novo download só do stream, sem nova busca (o videoId vem do banco);
   - ou, opcionalmente, transcodificação local (m4a/opus → mp3), sem rede;
   - **nunca** apagar o arquivo de outro formato sem permissão.
6. **Completude.** Baixar e processar em `<base>.<fmt>.partial`, gravar as tags, depois `fsync` e `os.replace`. Só então marcar `complete=1`. Um arquivo sem linha no banco ou com `complete=0` é revalidado: abrir com mutagen, conferir `info.length` contra a duração esperada, ver se as tags existem.
7. **Mudança de processamento de áudio** (assinatura de EQ/normalize): guardar `processing_sig` em `files`. Se a mudança for só de loudness, regravar a tag ReplayGain (seção 6) em vez de baixar de novo.

---

## 5. Redesenho de vazão

### 5.1 Arquitetura

```
           ┌──────────────┐  token bucket A (busca: 1 req/s, burst 3)
fila ───▶  │ SearchStage  │──▶ cache SQLite (hit = 0 requisições)
persistida └──────┬───────┘
                  ▼ (videoId resolvido | revisão manual)
           ┌──────────────┐  token bucket B (inícios de yt-dlp: 1 a cada 3 s)
           │ DownloadPool │  N = 2..3 workers (subprocessos; nunca yt-dlp in-process)
           └──────┬───────┘
                  ▼
           ┌──────────────┐  pool de CPU = núcleos-1 (ffmpeg, loudness, tags, capa)
           │ PostProcess  │
           └──────────────┘
```

- A **busca roda antes**, para a playlist inteira e com o cache aquecido. O usuário revisa as faixas de baixa confiança **enquanto** os downloads já acontecem.
- **Concorrência limitada:** 2 a 3 downloads simultâneos, com `--concurrent-fragments 1`, um `--sleep-requests` pequeno (0.3 s) e **sem** `--sleep-interval` fixo de 8 a 15 s. O espaçamento fica a cargo do token bucket global, compartilhado entre os workers.
- **Subprocesso sempre.** Usar o binário do yt-dlp (atualizável em `%LOCALAPPDATA%/csvmusic/bin/yt-dlp.exe` via `yt-dlp -U`) ou `python -m yt_dlp` no interpretador congelado. Isso dá timeout (`subprocess.run(..., timeout=600)`), cancelamento com `proc.kill()` no Stop e acaba com a corrida do `redirect_stdout`.
- Opcional: **lote de URLs** num único processo do yt-dlp (`--batch-file`) para amortizar a inicialização e o desafio JS, com um `--cache-dir` estável.

### 5.2 Backoff adaptativo só com sinal real

O controlador é AIMD:

- **Com sinal de risco:** concorrência = max(1, N/2); token bucket mais lento (×2); pausa global de 60 s, 120 s, 240 s e assim por diante, até 15 min, com jitter.
- **Depois de 20 sucessos seguidos:** concorrência +1 até N e taxa ×1.25.
- **Depois de 3 pausas máximas seguidas:** parar o lote e salvar a fila.

Sinais de risco a usar:

- os 8 padrões de `_YOUTUBE_RISK_PATTERNS`, aplicados ao **stderr cru**, antes de `_summarize_tool_output` (o que corrige o bug do bot-check), e em **todas** as tentativas, não só na última;
- adicionalmente, "HTTP Error 403" em fragmentos;
- "Requested format is not available" em sequência para vários vídeos diferentes, o que indica sessão sinalizada, e não um vídeo específico com problema;
- "Precondition check failed";
- `ytmusicapi`: exceções HTTP 429/403 e respostas vazias repetidas **sem** filtro de duração.

O perfil por tamanho de lote vira só um teto inicial conservador, sem o aviso de "throttling" na partida.

### 5.3 Fila persistente

```sql
CREATE TABLE jobs(
  id INTEGER PRIMARY KEY, playlist_key TEXT, position INTEGER, track_key TEXT,
  stage TEXT CHECK(stage IN ('search','review','download','post','done','skipped','failed')),
  video_id TEXT, attempts INTEGER DEFAULT 0, next_attempt_at INTEGER, last_error TEXT,
  updated_at INTEGER
);
```

- Ao abrir o app, o que estava em `download` ou `post` volta para `download`.
- Uma falha transitória reagenda com `next_attempt_at` exponencial.
- Uma falha definitiva (vídeo removido, restrição de idade sem cookies) vai para `failed` com um motivo claro.

### 5.4 ETA

Usar EWMA (α ≈ 0.2) do tempo por faixa **por etapa**: ETA = restantes_busca × t_busca + restantes_download × t_dl / concorrência_atual, somando as pausas de backoff ativas. Mostrar na barra de status com o texto "~2h10m restantes (3 downloads paralelos, sem throttling)".

**Ganho esperado:** sem os 8 a 15 s fixos mais os 6 s entre faixas, e com 3 downloads em paralelo, a vazão efetiva fica em ~6 a 10 s por faixa. As 1123 faixas levariam ~2 a 3 h na primeira vez, e um reprocessamento com cache sai quase de graça.

---

## 6. Redesenho de tags

### 6.1 Mudanças no modelo de dados

Manter `artists: str`, que é usado no nome do arquivo, e acrescentar:

- `artists_list: list[str]`;
- `album_artists: list[str]`;
- `genres: list[str]`;
- `isrc`;
- `release_date` completa (`YYYY-MM-DD`);
- `track_total` e `disc_total`;
- `mb_recording_id` e `mb_release_id`, opcionais.

As fontes já trazem boa parte disso. A API do Spotify (`spotify_api.py:165-171`) tem `artists[]`, `album.artists[]`, `release_date`, `total_tracks` e ISRC. O Deezer tem `disk_number`, ISRC e gênero por álbum.

**Problema atual:** `csv_import.py:202` (e outros importadores) usa a **posição na playlist** como `track_no` quando não existe número de faixa. A tag de faixa vira posição na playlist, o que bagunça a ordenação por álbum. É melhor gravar a posição numa tag separada (TXXX `PLAYLIST_POSITION`) ou deixar em branco.

### 6.2 Por contêiner (mutagen)

**ID3 (MP3).** Usar `mutagen.id3.ID3` diretamente em vez de EasyID3 e escolher **uma** versão de forma consistente. Hoje sai v2.4 sem capa e v2.3 com capa (`downloader.py:601-605`). Uma opção configurável é razoável: v2.4 por padrão; v2.3 com `v23_sep="/"` (ou `"; "`) no modo iPod/legado.

```python
tags.setall("TPE1", [TPE1(encoding=3, text=artists_list)])   # v2.4: valores separados por \0
tags.setall("TPE2", [TPE2(encoding=3, text=album_artists)])
tags.setall("TCON", [TCON(encoding=3, text=genres)])
tags.setall("TSRC", [TSRC(encoding=3, text=[isrc])])
tags.setall("TRCK", [TRCK(encoding=3, text=[f"{n}/{total}"])])
tags.setall("TPOS", [TPOS(encoding=3, text=[f"{d}/{dtotal}"])])
tags.setall("TDRC", [TDRC(encoding=3, text=[release_date])])
tags.add(TXXX(encoding=3, desc="ARTISTS", text=artists_list))        # Picard/foobar
tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=[f"{g:+.2f} dB"]))
tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_PEAK", text=[f"{p:.6f}"]))
tags.add(USLT(encoding=3, lang="eng", desc="", text=plain_lyrics))
tags.add(TXXX(encoding=3, desc="MusicBrainz Release Track Id", text=[mbid]))
tags.save(path, v2_version=4)
```

**Vorbis Comment (Opus)**

- Campos repetidos: `ARTIST=[a, b]`, `ARTISTS=[…]`, `ALBUMARTIST`, `GENRE`, `ISRC`, `TRACKNUMBER`, `TRACKTOTAL`, `DISCNUMBER`, `DISCTOTAL`, `DATE`, `LYRICS`.
- Para Opus, o ganho vai em **`R128_TRACK_GAIN`**: inteiro Q7.8 relativo a −23 LUFS, `round((-23 - I) * 256)`, conforme a RFC 7845. Opcionalmente também `REPLAYGAIN_*`.
- Capa em `METADATA_BLOCK_PICTURE`, como já é feito.

**MP4**

- `©ART` com uma string única para exibição (Apple só mostra uma) e `----:com.apple.iTunes:ARTISTS` com múltiplos valores.
- `aART` (artista do álbum), `©gen`, `----:com.apple.iTunes:ISRC`, `trkn=[(n,total)]`, `disk=[(d,total)]`, `©day`, `©lyr`, `covr`.
- `----:com.apple.iTunes:replaygain_track_gain` e `…_peak`; `----:com.apple.iTunes:MusicBrainz Track Id`.
- Corrigir `mp4["\xa9nam"] = str` (linha 625) para usar lista.

### 6.3 Fontes extras (opcionais e com cache)

- **Letras:** LRCLIB (`GET https://lrclib.net/api/get?track_name=&artist_name=&album_name=&duration=`) devolve `plainLyrics` e `syncedLyrics`. O LRC pode ir em `.lrc` lateral, em SYLT ou em `LYRICS`. Alternativa: ytmusicapi `get_watch_playlist(videoId)["lyrics"]` seguido de `get_lyrics(browseId)`.
- **MusicBrainz:** `GET /ws/2/isrc/{isrc}?inc=artist-credits+releases&fmt=json`, respeitando 1 req/s e User-Agent identificado. Fornece MBIDs, artista do álbum canônico e data original.
- **Gênero:** o Spotify só tem gênero por artista; o Deezer tem por álbum. É bom deixar desligado por padrão, porque é ruidoso.

### 6.4 ReplayGain em vez de alterar o áudio

Medir com `ffmpeg -af ebur128=peak=true -f null -`, que já faz um passo como o loudnorm atual, e gravar os ganhos de RG2 (referência −18 LUFS) ou R128. Isso deixa o remux m4a e opus **sem reencode** e torna a normalização reversível. A normalização destrutiva atual fica como opção só para dispositivos sem suporte a ReplayGain, como iPods antigos (o app tem esse modo legado).

### 6.5 Capa

- Hoje há **dupla recompressão JPEG**: `yt_thumbnail_bytes` ou `cover_art_url_bytes` já quadram em 600 px, e `tag_file` quadra de novo (`downloader.py:495, 520, 584`), sempre com a qualidade padrão do QImage.
- Proposta: baixar uma vez, processar uma vez, com qualidade 90 a 92 e tamanho configurável (1000 a 1400 px).
- Para Spotify, testar a variante de alta resolução `ab67616d000082c1…` (a confirmar) antes de `b273` (640 px).
- Para YouTube Music, os `thumbnails` do ytmusicapi (`lh3.googleusercontent.com/...=w544-h544`) podem ser reescritos para `=w1200-h1200` e já são quadrados. Isso evita cortar o centro de uma miniatura 16:9 do vídeo.

---

## 7. Coisas estranhas no código, a provável razão e alternativas

1. **Mitigação agressiva fixada pelo tamanho do lote, com texto de "throttling".** Razão provável: o autor reaproveitou o perfil reativo como preventivo depois de relatos de bloqueio em lotes grandes. Alternativa: um teto por tamanho com texto honesto e o AIMD da seção 5.2.
2. **Até 25 invocações do yt-dlp por candidato** (2 URLs × 5 clientes × primário e fallback, mais ytsearch). Razão provável: a quebra frequente de clientes do YouTube, contornada por tentativa e erro. Alternativa: deixar o yt-dlp escolher os clientes (o padrão já faz fallback interno) e usar uma lista curta (padrão e `web_embedded`) só para erros de extração, nunca para 429 ou bot-check.
3. **`ytsearch1:` como último recurso.** Razão provável: "melhor baixar algo do que falhar". Alternativa: remover, ou marcar como `low_confidence` e passar pelo `_score`.
4. **yt-dlp in-process com `redirect_stdout`.** Razão provável: o PyInstaller não traz executável do yt-dlp e este é o caminho mais simples. Alternativa: rodar o próprio executável congelado com uma flag `--run-yt-dlp` (sub-entrypoint) como subprocesso.
5. **Duas implementações de M3U** (`downloader.write_m3u` e `MainWindow._write_playlist_file`) com formatos diferentes (LF vs CRLF, com e sem `#EXTALBUM`). Razão provável: o editor de alternativas precisava reescrever a partir da tabela. Alternativa: uma única função que recebe `(track, caminho_real)`.
6. **`_strip_noise` removendo colchetes, mas não sufixos com hífen.** A heurística foi pensada para títulos de vídeo do YouTube, não para o formato do Spotify.
7. **Score com título cru e query com título limpo.** Provavelmente foi intencional para preservar a marca de versão no score. Alternativa: separar o núcleo das marcas, como em `split_title`.
8. **`_should_retry_without_cookies` testado e nunca chamado,** junto com `_strip_cookie_args`: restos de uma política antiga. O comentário "Never silently discard an explicitly selected authenticated session" (linha 291) explica a remoção. Alternativa: apagar a função e o teste.
9. **Função de execução do yt-dlp duplicada** (`workers._run_yt_dlp_command` e `downloader._run_ytdlp_module`). Alternativa: centralizar.
10. **`log()` abre o arquivo a cada linha, sem rotação e em `~/.local/share` no Windows.** É simples e robusto contra crash. Alternativa: `logging` com `RotatingFileHandler` em `%LOCALAPPDATA%`.
11. **`using_cookies` recebido e ignorado** em `youtube_batch_mitigation`. Provavelmente a ideia era um limiar mais alto para sessões autenticadas.
12. **"Skip Song" apaga o arquivo do disco** (`main_window.py:2924`). A intenção é tirar a faixa da playlist, mas uma ação destrutiva sem confirmação surpreende. Alternativa: só retirar do M3U, ou pedir confirmação.

---

## 8. Bugs e riscos (arquivo:linha)

| # | Local | Problema | Correção |
|---|---|---|---|
| 1 | `downloader.py:170-173` × `21-30, 212-217` | O bot-check é reescrito para "YouTube asked for bot verification…", que não casa nenhum padrão: **o throttling por bot nunca é detectado**. | Detectar o risco no stderr cru dentro de `_run_ytdlp_detail` e propagar uma exceção tipada (`YouTubeRiskError`). |
| 2 | `downloader.py:689-715, 757, 813-831` | `last_detail` guarda só a última tentativa (o ytsearch), e um 429 anterior se perde. | Acumular as tentativas; parar o laço no primeiro sinal de risco. |
| 3 | `workers.py:319-321, 490` | O perfil agressivo pré-aplicado anula a escalada; o aviso de "throttling" aparece sem ter havido throttling. | Ver seção 5.2. |
| 4 | `ytmusic_match.py:324-327, 345-361`; `workers.py:379-381, 430-437` | Candidatos filtrados por duração viram "sem resultados": geram 2 rodadas extras de busca e podem **abortar o lote** com mensagem falsa. | Separar `raw_count`. |
| 5 | `ytmusic_match.py:345` | A primeira chamada não tem retry em caso de exceção; só o "vazio" tem. Em `358-359`, `last_exc` é relançada mesmo quando a última tentativa terminou sem erro. | Retry uniforme com backoff. |
| 6 | `downloader.py:702, 818` + `workers.py:457` | `ytsearch1:` baixa áudio não verificado; a query traz o prefixo "NN- ". | Remover ou validar. |
| 7 | `downloader.py:457-465` | Remux com `-c:a copy` de Opus/WebM para `.m4a` gera m4a com Opus, que não toca em Apple ou iPod. | Checar o codec com ffprobe; se não for AAC, reencodar. |
| 8 | `downloader.py:843-855, 766-771`; `workers.py:469-472`; `track_output.py:66` | Gravação final não atômica e tag aplicada depois; arquivo parcial ou sem tag conta como "existente". | `.partial` + tag + `os.replace` + marca `complete`. |
| 9 | `downloader.py:356-361, 654, 734, 789` | `_cleanup_outputs` apaga `base.*` de **qualquer** extensão: trocar o formato destrói os arquivos antigos (inclusive um `.lrc` do usuário). | Limpar só as extensões temporárias conhecidas e a do formato atual. |
| 10 | `workers.py:206-207`; `downloader.py:729` | Opus ignora normalização, EQ e ganho por faixa sem avisar. | Aplicar via ReplayGain/R128 ou avisar na UI. |
| 11 | `workers.py:580-631` | `SingleDownloadWorker` ignora `audio_volume_gain` por faixa, a mitigação e o parâmetro `force_download`; pode rodar ao mesmo tempo que o pipeline. | Reusar `_download_with_profile` e o controlador global. |
| 12 | `downloader.py:130-150`; `workers.py:105-131`; `source_quality.py:144` | `redirect_stdout` é global ao processo: downloads concorrentes (manual + pipeline) misturam saídas, e `capture_source` pode gravar o formato errado. | Subprocesso. |
| 13 | `downloader.py:119-128` | Sem timeout no subprocess; o Stop só é checado entre faixas (`workers.py:345`); `closeEvent` chama `terminate()` (`main_window.py:3100-3102`) no meio de uma escrita. | Timeout + `Popen` com `kill` no Stop. |
| 14 | `main_window.py:2316` × `workers.py:317-319` | O diálogo de risco usa o total de linhas, e o worker usa só as da fila: o perfil e o aviso divergem. | Usar a mesma contagem nos dois lugares. |
| 15 | `main_window.py:3005-3024` | `_rewrite_playlists` junta as linhas de **várias playlists** do CSV num único M3U, com o nome da primeira. | Agrupar por playlist. |
| 16 | `main_window.py:3045-3065` × `downloader.py:866-892` | O M3U do worker é sobrescrito por outro formato (perde `#EXTALBUM`/`#EXTISRC`). | Uma única implementação. |
| 17 | `ytmusic_match.py:219` | O regex de feat casa qualquer parêntese com a substring "feat" (por exemplo "(Defeated)"). | `\b(feat\.?|ft\.?|featuring)\b`. |
| 18 | `ytmusic_match.py:171-173, 184-186` | Penalidades por substring: "Demons" contém "demo", "Discover" contém "cover", "Castle" contém "cast". | Regex com `\b`. |
| 19 | `ytmusic_match.py:56` × `168` | Marcas assimétricas (álbum só do lado do candidato). | Incluir o álbum da faixa pedida. |
| 20 | `ytmusic_match.py:162-163` | `ch_boost` praticamente inerte para resultados "songs". | Bonificar `source=="music"` diretamente, ou remover. |
| 21 | `downloader.py:601-605` | Versão de ID3 inconsistente (2.4 ou 2.3, conforme haja capa). | Versão única configurável. |
| 22 | `downloader.py:495, 520, 584` | Dupla recompressão JPEG da capa. | Processar uma vez. |
| 23 | `workers.py:438-439` | Pausa de 6 s depois de faixa pulada. | Pausar só depois de requisições de mídia. |
| 24 | `downloader.py:325-335` | Nomes reservados do Windows (CON, NUL, AUX, COM1…) não são tratados; uma playlist chamada "Con" quebra. Caminhos de 140 + 140 caracteres mais a raiz podem passar de 260 sem suporte a long paths. | Sufixar `_` nos nomes reservados; prefixo `\\?\` ou limite dinâmico. |
| 25 | `track_output.py:28-39` | Versões diferentes com o mesmo "Artista - Título" são tratadas como duplicatas e só uma é baixada. | Chave lógica (ISRC) e sufixo de desambiguação. |
| 26 | `main_window.py:2952-2983` | O download manual não atualiza as linhas duplicadas. | Reusar a lógica de `on_track_result`. |
| 27 | `workers.py:409, 414` | O log "match skip: query=…" mostra `título + artistas`, não a query real, e isso confunde o diagnóstico (caso do Blur). | Registrar as variantes e o melhor candidato. |
| 28 | `downloader.py:625` | `©nam` atribuído como str, diferente dos outros campos. | Usar `[title]`. |
| 29 | `library_mode.py:83` | Mudar o prefixo numérico faz baixar toda a biblioteca de novo. | Renomear (seção 4). |
| 30 | `csv_import.py:202` (e outros importadores) | `track_no` cai na posição da playlist. | Ver seção 6.1. |
| 31 | `pyproject.toml` | yt-dlp fixado e embutido como módulo: quando o YouTube muda, todo usuário quebra até sair uma nova release. | yt-dlp externo e atualizável, com o embutido só como fallback. |
| 32 | `downloader.py:111, 234, 254, 284` | Código morto. | Remover. |

**Lacunas de teste:** não há testes para a composição dos comandos e a contagem de invocações do yt-dlp, para a integração entre `detect_youtube_risk` e `_summarize_tool_output` (que teria pegado o bug 1), para o aborto por busca vazia depois do filtro de duração, para `_strip_noise` e `_query_variants` com sufixos do Spotify, nem para a atomicidade e o `_cleanup_outputs` entre formatos.
