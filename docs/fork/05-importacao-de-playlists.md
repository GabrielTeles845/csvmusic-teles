# 05 — Importação e análise de playlists (e por que a playlist grande "travou")

> Referência do subsistema que transforma um link/CSV numa lista de músicas. Inclui a **causa raiz do travamento** ao analisar a playlist de ~1.220 músicas, comprovada com o `app.log` real do usuário.
> Referências `arquivo:linha` da v1.7.9.

---

## 0. Resumo: por que a "análise" da playlist grande trava

1. **Não é travamento de verdade: o leitor pula blocos de músicas e nunca volta para buscá-los.**
   - O Library Mode lê playlists do Spotify abrindo `open.spotify.com` num navegador embutido (QWebEngine) com zoom de 25% e rolando a lista. Cada rolagem é de 1,4 × a altura da tela.
   - O Spotify carrega as músicas em blocos de 25 a 50. O leitor avança assim que aparece **qualquer** linha nova, mesmo que o resto da tela ainda esteja em branco (sem link `/track/`). Se o bloco seguinte ainda não chegou da internet, aquelas posições ficam para trás.
   - Ao chegar no fim, não existe lógica para voltar e preencher os buracos. O leitor fica verificando, com um "empurrão" **para baixo** a cada 8 tentativas, até atingir o limite de 40 ou 80 tentativas sem novidade.
   - Isso dá **16 a 33 s com a barra parada** (ex.: "Captured 1073 of 1124"), e a análise termina incompleta. É o "travou perto do fim".
2. **Terminar com sucesso depende da sorte.** A mesma playlist de 1.124 músicas deu 981, 1073, 1044 e 1093. Só a última tentativa pegou tudo, porque o bloco 676–725 já tinha carregado quando o leitor chegou nele.
3. **Agravantes:**
   - Toda leitura incompleta **sobrescreve** a biblioteca com o resultado parcial.
   - Fechar o Library Mode durante a leitura grava só 100 músicas.
   - As primeiras ~11 tentativas são desperdiçadas.
   - Não há proteção para quando o JavaScript não responde (risco de travar para sempre; não aconteceu neste log).
   - `library_status()`/`merge_playlist_scan()` rodam na thread da interface com custo O(n²) quando a pasta já tem arquivos.

---

## 1. Módulo a módulo

### 1.1 `core/url_import.py` — roteador de links (modo legado)
- `ImportedMusicSource(platform, source_type, id, name, tracks, total_count=None, warning=None)` (l.17–25).
- `fetch_music_url(value)` (l.28–62) escolhe pelo endereço:

  | Endereço | Para onde vai |
  |---|---|
  | `open.spotify.com`, `play.spotify.com`, `spotify:` | `fetch_spotify_playlist` |
  | `music.apple.com` | Apple |
  | `music.youtube.com` | ytmusicapi |
  | `youtube.com`, `youtu.be` | yt-dlp |
  | `soundcloud.com` | yt-dlp |
  | `deezer.com`, `deezer.page.link` | API pública do Deezer |
  | `music.amazon.*` | Amazon |

  Qualquer exceção vira `URLImportError(str(exc))`, e o tipo original se perde.
- **Importante:** no modo legado, o Spotify usa **só** o caminho HTTP, limitado a 100 músicas. O navegador embutido só existe no Library Mode.
- Quem chama é `ui/workers.py: MusicURLImportWorker` (l.44–64). O sinal `sig_done(bool, dict, str)` é tratado em `main_window.on_spotify_loaded` (l.1617) e `on_load_playlist_url_loaded` (l.1700). Depois, `_build_track_preview` (l.1860) roda **na thread da interface**, criando um botão por linha e um `exists()` por música.

### 1.2 `core/spotify_import.py` — Spotify sem login (HTML/embed)
- Dataclasses `SpotifyPlaylist(id, name, tracks, total_count, source_type, warning, cover_url)` (l.24–32) e `SpotifySource(type, id)` (l.35–38).
- `parse_spotify_source(value, expected_type=None)` (l.49–78) aceita `spotify:playlist:ID`, um ID puro (regex `[A-Za-z0-9]{16,32}`) e URLs `intl-xx`. Só playlist ou álbum.
- `fetch_spotify_playlist(value, timeout=20, session=None)` (l.81–95):
  - Faz **até 3 tentativas**. Cada uma busca `open.spotify.com/{type}/{id}` **e** `/embed/{type}/{id}` e fica com a que trouxer mais músicas.
  - Repete enquanto houver aviso, esperando 0,4 / 0,8 / 1,2 s.
- **Leitura da página:** `_extract_initial_state` (l.212–221) pega `<script id="initialState">`, decodifica base64 e o JSON. Depois:
  - `_find_playlist_entity` usa `entities.items["spotify:playlist:ID"]`;
  - `content.items` e `content.totalCount` vão para `_tracks_from_items` (l.262–291);
  - álbuns são lidos de `tracksV2`.
- **Leitura do embed:** `_extract_next_data` lê `__NEXT_DATA__` → `props.pageProps.state.data.entity.trackList`. Não traz álbum nem ISRC, e a capa é a da playlist.
- **Avisos:**
  - Se a quantidade lida for menor que o total, **ou for exatamente 100**, o resultado vem com `incomplete_import_warning`.
  - Quando não há `trackCount`, o total do embed vira a quantidade lida (l.166). Por isso o "total" pode aparecer como 100.
- `track_no` é a posição na playlist; para álbum é `trackNumber`. `disc_no` vem de `discNumber`.

### 1.3 `core/spotify_api.py` + `core/spotify_oauth.py` — API oficial (experimental)
- `fetch_spotify_user_playlists(token)` lista `/v1/me/playlists` de 50 em 50.
- `fetch_spotify_playlist_api(value, token)` busca `/v1/playlists/{id}?fields=id,name,tracks.total` e depois `/v1/playlists/{id}/items?limit=50&offset=`.
  - `_track_from_item` traz ISRC, duração, ano, capa, `track_number` e `disc_number`.
  - **Aqui `track_no` é o número da faixa no álbum, não a posição na playlist.**
- `_get_json` transforma 401/403/404/429 em `SpotifyAPIError`. **Não há retry no 429.**
- OAuth PKCE com escopos `playlist-read-private` e `playlist-read-collaborative`. **Não há refresh token** (o acesso expira em ~1 h).
- Só é usado pelo assistente `ui/spotify_api_test.py` e pela CLI `fetch_spotify_api.py`. **Não está ligado ao Library Mode.**
- Restrição citada no README: em Development Mode, a API só devolve playlists **suas ou colaborativas**.

### 1.4 `ui/spotify_api_test.py`
- Abre um `HTTPServer` em `127.0.0.1:3000/callback` (porta fixa), com prazo de 180 s e verificação de `state`.
- `DEFAULT_CLIENT_ID = "bda6888318054aa7a413b8bb8a004a1a"` está fixo no código.
- Se o acesso for negado, cai para `fetch_spotify_playlist` (limite de 100).
- Só mostra resultados; não grava na biblioteca.

### 1.5 `ui/spotify_public_scrape.py` — o leitor com navegador (usado pelo Library Mode)

**Componentes**
- `SpotifyBaselineWorker(QThread)` (l.107–120) roda `fetch_spotify_playlist` fora da interface (fase 1).
- `ScraperWebPage(QWebEnginePage)` só registra mensagens do console.
- `_CAPTURE_SCRIPT` (l.30–104) é o JavaScript injetado a cada passada. Ele:
  - acha a lista (`[data-testid=playlist-tracklist]`, `tracklist` ou `[role=grid]`);
  - para cada link `/track/`, sobe até a linha (`[role=row]`) e lê posição (`[aria-colindex="1"]`), artistas, álbum e imagem;
  - ignora linhas abaixo de um título "recommended" (só funciona em inglês);
  - **depois de ler**, rola **todos** os elementos roláveis em `max(650px, altura × 1,4)`, chama `window.scrollBy` e simula a tecla PageDown;
  - lê o total com a regex `/([\d,]+)\s+(songs|tracks)/`, também só em inglês. Por isso o navegador força `Accept-Language: en-US` (l.278–280).
- Funções puras, com testes:
  - `normalized_capture`;
  - `ordered_playlist_tracks` (só aceita posições ≤ total);
  - `recover_single_missing_position`;
  - `metadata_gap_positions` (marca a linha como problema se faltar álbum ou capa, ou se a capa for a da playlist).

**`SpotifyPublicScrapeDialog`**
- Padrões: zoom 0,25; multiplicador de rolagem 1,4; mínimo de 650 px; intervalo de 350 ms ±8%.
- Navegador anônimo, sem cookies persistentes.
- Fluxo:
  1. `start_scrape` dispara a fase 1.
  2. `_baseline_finished` guarda as músicas com chave `"pos:id"`, define o total a partir da fase 1 e carrega a página.
  3. Um `QTimer` chama `_capture_visible`, que executa `page.runJavaScript` **sem limite de tempo**.
  4. `_capture_finished` (l.407–495) junta os resultados e decide o próximo passo:
     - depois de uma passada de "rolar", a próxima é sempre "verificar";
     - numa "verificação", se apareceu algo novo, volta a rolar; senão soma `stalled` e só rola de novo a cada 8 tentativas paradas.
- Condições de fim:
  - **Sucesso:** a quantidade lida chegou ao total e não há falhas de dados.
  - **Desistência:** `stalled` passou do limite: 20 se faltam até 2 músicas, 80 se já leu 90% ou mais, 40 nos outros casos.
  - **Teto geral:** `max(300, total/4)` passadas.
- Tudo roda na thread da interface. O trabalho pesado fica no processo do Chromium, então isso é aceitável.

### 1.6 `ui/library_mode.py` — quem coordena a análise
- `_begin_scan` (l.2299) abre `LibraryScanProgressDialog`, que mostra o "Live page preview" com o navegador embutido.
- `_scan_next` (l.2318):
  - **Playlist** do Spotify usa o `SpotifyPublicScrapeDialog`, reaproveitado entre playlists. Destruir o navegador travava o loop de eventos (comentário em l.2455–2459).
  - Todo o resto (inclusive **álbum** do Spotify e CSV) usa `DirectLibraryScanWorker(QThread)`.
- `_scan_finished` (l.2414–2475) roda **na thread da interface**:
  - `merge_playlist_scan` e depois `_save()`;
  - `library_status` e `_refresh()` (que chama `library_status` de novo e reconstrói todos os cards);
  - espera de 0,9 a 1,4 s entre playlists.

### 1.7 `core/library.py` (partes de importação)
- `add_playlist_urls` (l.58) cria uma playlist "Unscanned …" vazia.
- `import_csv_playlist` (l.122) usa como id `sha256(caminho)[:20]`. **Mover o CSV de lugar cria outra playlist.**
- `merge_playlist_scan` (l.236–323):
  - a chave da música é `_track_base_key` (id do YouTube > id da Apple > `sp_id` > texto), mais `playlist_occurrence`;
  - preserva as escolhas do usuário;
  - quando a chave não bate, procura por texto **linearmente** (O(n²));
  - chama `library_track_path`, que pode listar a pasta inteira.
- `library_status` (l.435–454) chama `library_track_path(...).exists()` por música. Isso custa O(músicas × arquivos) na thread da interface.

### 1.8 Outras fontes
- **Apple Music:**
  - Lê `<script id="serialized-server-data">`. A alternativa é o JSON-LD, que não tem artista e vira "Unknown Artist".
  - Para playlists com 300 músicas ou mais, baixa o JavaScript `/assets/index*.js`, **extrai o token público por regex** e pagina `amp-api.music.apple.com/.../tracks?limit=100` (até 1000 páginas).
- **Amazon Music:**
  - Tenta o JSON da página (quase sempre incompleto).
  - Senão, imita o web player: lê `/config.json` e faz POST em `https://{região}.web.skill.music.a2z.com/api/showHome` com cabeçalhos `x-amzn-*`.
  - O ASIN é gravado em `sp_id`.
  - **Não verifica paginação:** declara "completo" mesmo se vier cortado.
- **YouTube Music:**
  - Usa `YTMusic().get_playlist(id, limit=None)` ou `get_album`.
  - Preenche `preferred_video_id`, então pula a busca e baixa o vídeo exato.
  - Deduplica por `videoId`, o que remove repetições legítimas.
- **YouTube e SoundCloud:**
  - Usam yt-dlp em modo `extract_flat`.
  - No YouTube, descobre se o título vem como "Artista - Título" ou o contrário votando por canal (`_infer_channel_title_rules`).
  - O id do vídeo vai em `sp_id`, não em `youtube_video_id`, então **não** fixa o vídeo.
- **Deezer:** API pública com paginação `next`. É a fonte não oficial mais estável.
- **`browsers.py`** não tem a ver com importação: lista perfis de navegador para os cookies do yt-dlp.
- **`core/models.py`** (`Track`, `MatchResult`) é **código morto**.

---

## 2. O formato de uma "música" (track dict)

Não existe tipo formal: é um `dict` livre. Na biblioteca, `_normalized_track` (library.py l.476) padroniza.

| Chave | Quem preenche | Quem usa | Observação |
|---|---|---|---|
| `title` | todos | busca, nome de arquivo, tags | obrigatório |
| `artists` | todos (texto único "A, B") | busca, nome de arquivo, tags | "Unknown Artist" como reserva |
| `album` | quase todos | tags | o embed do Spotify não traz |
| `playlist` | todos | pasta de saída, m3u | |
| `isrc` | Spotify página/API, Apple, Deezer, CSV | busca, `#EXTISRC` | **o leitor com navegador não traz** |
| `sp_id` | Spotify; **também ASIN da Amazon, id do Deezer, id de vídeo do YouTube** | chave de junção, exportação CSV | nome enganoso |
| `apple_music_id` | Apple | chave | |
| `youtube_video_id` | YT Music | chave; gera `preferred_video_*` | |
| `preferred_video_id` / `_label` | YT Music; usuário (Alternativas) | baixa direto, sem buscar | |
| `duration_ms` | Spotify página/API/embed, Apple, Amazon, YTM, Deezer, CSV | filtro e nota de duração | **0 em todo o fluxo do leitor com navegador** |
| `year` | Spotify API, YT, CSV | tag de data | |
| `cover_url` | quase todos | capa | |
| `track_no` | todos (às vezes posição na playlist, às vezes faixa do álbum) | tag `tracknumber` | inconsistente |
| `disc_no` | todos (padrão 1) | tag de disco | |
| `playlist_occurrence` | `merge_playlist_scan` | chave (repetições) | |
| `filename_prefix_number` / `_width` | library_mode no download | nome "0001- Artista - Título" | |
| `enabled`, `custom_title`, `custom_album`, `audio_volume_gain`, `force_redownload`, `last_error*`, `downloaded_*`, `low_confidence_review`, `download_confidence`, `audio_processing_signature`, `preferred_selection_locked` | biblioteca / usuário / download | | preservados nas novas análises |

**Nos dados reais do usuário:** as 1124 músicas estão com **`duration_ms = 0` e sem ISRC**. A busca da playlist inteira roda **sem o filtro de duração**, o que contribuiu para o caso do Blur com nota 0.59.

---

## 3. Cada fonte: como funciona, limites e pontos frágeis

### 3.1 Spotify (três caminhos)

1. **HTTP sem login** (modo legado e álbuns na biblioteca)
   - Na prática, **no máximo 100 músicas por playlist**. O código sabe disso e avisa.
   - É frágil porque depende de nomes internos do Spotify (`initialState`, `itemV2`, `albumOfTrack`, `trackList`).
   - Se a página principal falhar, a função **aborta mesmo que o embed funcionasse** (l.87).
2. **Leitor com navegador** (Library Mode)
   - É o único jeito de passar de 100 músicas sem login.
   - É frágil porque depende de:
     - seletores da página (`data-testid`, `aria-colindex`);
     - textos em inglês;
     - carregamento em blocos;
     - captcha;
     - o navegador desacelerar quando a janela fica escondida.
   - Não pega duração, ISRC nem ano.
   - Arquivos locais e podcasts nunca são lidos. Por isso a playlist nunca chega ao total e sempre cai no limite de desistência.
3. **API oficial**
   - É a fonte mais rica (ISRC, duração, ano).
   - Mas exige criar um app no painel do Spotify (hoje pede Premium), só funciona com playlists suas e não tem refresh token nem retry no 429.

### 3.2 Apple Music
Os dados da página são bons. Para playlists grandes, usa o token público extraído do JavaScript, que é o ponto frágil. Se falhar, avisa que o resultado está incompleto.

### 3.3 Amazon Music
É a fonte mais frágil (imita o web player) e não detecta resultado cortado.

### 3.4 YouTube Music / YouTube / SoundCloud
O YT Music funciona bem com playlists públicas. YouTube e SoundCloud também funcionam, mas título e artista são adivinhados.

### 3.5 Deezer
Estável.

### 3.6 CSV (TuneMyMusic / Exportify)
- Colunas obrigatórias: **`Track name`, `Artist name`, `Playlist name`**. Se `Playlist name` faltar, usa o nome do arquivo.
- Nomes de coluna aceitos (`_CANON`, l.7–28): track name, artist name(s), album (name), isrc, spotify - id/track uri, release date, cover/artwork url, duration (ms), track number/no, disc number/no, type.
- `_normalize_headers` passa para minúsculas e tira pontuação, **mas mantém acentos**. "Álbum" não bate com "album".
- `_read_csv_robust` (l.35–52) tenta 6 combinações (`,`/`;`, utf-8/utf-8-sig, engines C/python) e **aceita a primeira que não dá erro, sem conferir se as colunas foram separadas direito**.
- Um CSV com mais de uma playlist é recusado.
- **Evidência no log do usuário:**
  - `01:03:07 library CSV import failed ... musicas_curtidas_spotify.csv error=CSV missing required columns: ['Track name', 'Artist name']`
  - O cabeçalho do arquivo é `"#";"Track Name";"Artist Name";"Álbum";"Adicionada em";"Duração";"Link"`, separado por **`;`** e com BOM.
  - Causa provável: a tentativa com `,` "deu certo" e devolveu uma coluna só.
  - Mesmo com o separador certo, "Álbum", "Duração" (mm:ss) e "Link" seriam ignorados.

---

## 4. Causa raiz do travamento (com o log real)

### 4.1 Linha do tempo (playlist de 1124 músicas, 22/10/2026)

| Sessão | Início → fim | Resultado |
|---|---|---|
| 3c435e8c | 00:57:49 → 00:58:30 | `captured=981 missing=143 passes=91 waits=40 reason='No new public rows appeared…'` |
| e516b7ed | 00:58:43 → 00:59:41 | `captured=1073 missing=51 passes=137 waits=80` |
| 9a5568ff | 00:59:56 → 01:00:15 | `captured=100 … 'Library scan cancelled because Library Mode was closed.'`, e em seguida `merged … tracks=100 complete=False` |
| c1ddfc10 | 01:00:50 → 01:01:48 | `captured=1044 missing=80 passes=136 waits=80` |
| 08844a8f | 01:02:01 → 01:02:58 | `captured=1093 missing=31 passes=136 waits=80` |
| (CSV) | 01:03:43 | `merged … tracks=1124 complete=True` |
| 80402014 | 01:04:23 → 01:04:47 | `captured=1124 missing=0 passes=46 waits=0 'Success…'` |

Em todas as sessões, a fase 1 voltou com `tracks=100 reported_total=100`. O total real só aparece lendo "1,124 songs" na página, a partir da 5ª ou 6ª passada.

### 4.2 O mecanismo, com os buracos exatos

Trecho da sessão 08844a8f (`nf`/`nl` = primeira e última posição adicionada):
```
01:02:19 pass=31 scroll  raw=86 added=44 nf=626  nl=669
01:02:20 pass=32 verify  raw=30 added=6  nf=670  nl=675   <- só 30 links: o bloco 676+ ainda está em branco
01:02:20 pass=33 scroll  raw=30 added=0                    <- rola mesmo assim (1,4 × tela)
01:02:21 pass=34 verify  raw=19 added=19 nf=707  nl=725   <- 676–706 nunca foram vistas
...
01:02:26 pass=46 verify  added=26 nf=1099 nl=1124 captured=1093
(80 passadas sem nada novo → fim às 01:02:58, 32 s parado)
```

O buraco 676–706 tem **31 músicas, exatamente o `missing=31`**. As outras sessões fecham a conta do mesmo jeito:
- **3c435e8c:** buracos 676–706 (31), 926–951 (26), 976–1012 (37) e 1026–1074 (49), total 143.
- **e516b7ed:** 626–645 (20) + 676–706 (31) = 51.
- **80402014 (a que deu certo):** no mesmo ponto, `pass=33 scroll raw=80 added=50 nf=676 nl=725`. O bloco já estava carregado. Foi pura questão de tempo.

**Causas, em ordem de peso:**
1. **O critério para avançar é "apareceu alguma linha nova"**, e não "a tela inteira carregou e não há buracos" (`_capture_finished` l.452–462).
2. **O salto é maior que a tela:** 1,4 × a altura, aplicado em até 8 elementos, mais `scrollBy` e PageDown.
3. **Não existe fase de voltar e preencher.** O "empurrão" no fim rola para baixo, onde não há mais nada, embora o código saiba exatamente quais posições faltam.
4. **O "travamento" visível é o tempo até desistir:** 40 ou 80 passadas × ~0,4 s, com o texto "Scrolling and verifying…" e nenhuma indicação do que falta.
5. **A configuração nunca foi testada com playlists grandes.** O arquivo `spotify_scrape_experiment_results.json` tem 8 execuções, todas numa playlist de **182** músicas.

### 4.3 Fatores secundários
- **Passadas iniciais desperdiçadas:** as posições 1–100 já vieram da fase 1, então as primeiras linhas visíveis contam como "parado" e a primeira rolagem só acontece na passada 10.
  - Na sessão 9a5568ff, com o navegador reaproveitado, as rolagens não moveram a lista e o usuário fechou a janela depois de 15 s parado em "100 of 1124".
  - O Chromium pode desacelerar a página quando a janela fica coberta, porque não recebe as flags anti-throttling.
- **Fechar o Library Mode grava o resultado parcial:** `closeEvent` (l.3636–3637) chama `_finish` **sem** `scan_cancelled = True`. Assim, 100 músicas sobrescreveram as 1073 anteriores (log 01:00:15), e as escolhas do usuário nas músicas que "sumiram" se perdem.
- **Toda leitura incompleta substitui a lista inteira:** músicas antigas fora da leitura viram "removidas".
- **Sem proteção de tempo no JavaScript:** se o `runJavaScript` não responder, `capture_pending` fica `True` para sempre. Também não há tratamento para quando o processo do navegador morre (`renderProcessTerminated`).
- **Interface congelando depois da leitura:** `_scan_finished` executa merge O(n²), `library_status` duas vezes e recria todos os cards. Com centenas de arquivos na pasta, cada música faltando lista a pasta inteira (~1,2 milhão de entradas por chamada).
- **O total só aumenta (`max`, l.427).** Se a regex pegar um "N songs" maior (por exemplo, da seção de recomendações), a meta fica impossível. Se o texto não aparecer, o total fica em 100 e **tudo acima da posição 100 é descartado sem aviso**.

### 4.4 Correção proposta, passo a passo
1. **Medir se a tela carregou.** O JavaScript devolve o intervalo de posições visíveis e quantas linhas ainda estão em branco.
2. **Avançar por posição:**
   - O que falta é `{1..total} − lidas`, e o alvo é a menor posição que falta.
   - Só avança quando não há linha em branco na tela e todas as visíveis foram lidas. Senão espera, com um limite de ~8 s por bloco.
   - Cada avanço é de no máximo **0,8 × tela**, para haver sobreposição.
3. **Rolar até um alvo absoluto:** medir a altura da linha e fazer `scrollTop = offset + (alvo−1) × altura − margem`, num único elemento rolável (o que contém a lista). Remover `scrollBy` e PageDown.
4. **Preencher os buracos no fim:** pular direto para cada buraco, com 2 ou 3 tentativas por buraco e um teto de tempo total de `max(60 s, total × 0,1 s)`.
5. **Desistir por tempo e progresso**, não por número de passadas.
6. **Proteção de tempo:** se o JavaScript passar de 10 s, registra no log, libera e tenta de novo. Depois de 3 vezes, recarrega a página e continua do alvo. Tratar `renderProcessTerminated`.
7. **Começar a rolar a partir da posição 101**, sem contar as linhas da fase 1 como "parado".
8. **Interface honesta:** "Recuperando buracos: faltam 31 (676–706)… tentativa 2/3" e um botão "Concluir com o que tenho".
9. **Junção segura:**
   - Se a leitura veio incompleta, **não remover** músicas antigas que caíram nos buracos.
   - No `closeEvent`, marcar `scan_cancelled = True`.
10. **Tirar I/O da thread da interface:** listar cada pasta uma vez (cache) e trocar a busca linear por um índice.
11. **Flags do Chromium em todos os sistemas:** `--disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows`.
12. **Testes** com uma página falsa que carrega blocos de 50 com atraso aleatório.

**Alternativa estrutural (maior impacto): ler os dados, não a tela.**
- Injetar um `QWebEngineScript` que intercepta `fetch`/`XMLHttpRequest` e guarda o JSON que o próprio web player busca (endpoint GraphQL `api-partner.spotify.com/pathfinder/...`).
- Esse JSON vem paginado e traz uri, nome, artistas, álbum, **duração** e capa. A rolagem só serve para disparar as páginas.
- Acaba com a dependência de seletores e de textos em inglês, com o problema dos buracos e com a falta de duração.
- Ressalva: continua sendo uma interface interna não documentada do Spotify.

---

## 5. Coisas estranhas no código (e o provável motivo)

1. **Navegador com zoom de 25% rolando o Spotify.**
   - *Motivo:* em 2026 a API só entrega playlists próprias, o HTML para em 100 músicas e o token anônimo ficou difícil de obter. O zoom põe mais linhas na tela.
   - *Melhor:* interceptar o JSON (§4.4) ou usar OAuth para playlists próprias.
2. **Rolar 8 elementos + `scrollBy` + PageDown.**
   - *Motivo:* o elemento rolável do Spotify muda, e o autor "atirou em todos".
   - *Melhor:* achar o elemento certo uma vez e rolar só ele.
3. **Multiplicador 1,4.**
   - *Motivo:* foi calibrado por velocidade numa playlist de 182 músicas.
   - *Melhor:* passos de no máximo 0,8 × tela, esperando carregar.
4. **Variação aleatória de ±8% e modos Fast/Balanced/Safe.**
   - *Motivo:* parecer humano e evitar captcha.
   - *Melhor:* manter, mas com ritmo baseado no carregamento.
5. **Chave `"posição:id"`.**
   - *Motivo:* a mesma música pode aparecer duas vezes.
   - Ok, mas faz as linhas já conhecidas contarem como "parado".
6. **Total lido de "N songs" em inglês.**
   - *Melhor:* usar `aria-rowcount`, que não depende do idioma.
7. **Filtro de "recommended" pelo título da seção.**
   - *Melhor:* procurar só dentro do container da lista.
8. **A fase 1 sempre repete 3 vezes** quando a playlist tem mais de 100 músicas, porque o aviso nesse caso é garantido. São ~5 s perdidos em cada análise.
9. **A falha da página principal aborta a função mesmo com o embed disponível** (l.87).
10. **O total do embed vira a quantidade lida** (l.166), o que cria um total falso de 100.
11. **`metadata_gap_positions` impede o "Success"** se qualquer linha não tiver álbum ou capa. Playlists com arquivos locais ou podcasts nunca terminam com sucesso.
12. **A duração é jogada fora.**
    - "3:45" está no texto da linha, e a duração do embed é descartada em `_baseline_finished` (l.349–356).
    - Resultado: 1124 de 1124 músicas sem duração.
    - *Melhor:* ler o `mm:ss` da linha.
13. **`sp_id` guarda ids de outros serviços.**
    - *Melhor:* usar `source_id` + `source_platform`.
14. **`track_no` às vezes é a posição na playlist, às vezes o número no álbum**, e vai para a tag de faixa.
    - *Melhor:* separar `playlist_position` de `album_track_no`.
15. **CSV frágil** (separador, acentos, sem colunas em pt/es).
    - *Melhor:* detectar o separador com `csv.Sniffer`, escolher a leitura com mais colunas reconhecidas, remover acentos com NFKD e aceitar nomes em pt/es (Faixa, Música, Artista, Álbum, Duração, Link).
16. **`models.py` morto**, e a "música" é um dict sem tipo.
    - *Melhor:* um `TypedDict` validado na entrada de cada importador.
17. **Client ID fixo e porta 3000 fixa** no teste da API.
18. **429 sem espera** na API do Spotify.
19. **Amazon declara "completo" sem verificar**, e o token da Apple é extraído por regex.
20. **Álbum do Spotify sem navegador**: compilações com mais de 100 faixas ficam cortadas.
21. **O mesmo navegador é reaproveitado entre playlists** e herda o estado da anterior.
    - *Melhor:* carregar `about:blank` e reiniciar o estado, ou criar uma página nova no mesmo perfil.
22. **O YT Music remove repetições e o Spotify mantém.** É inconsistente.

---

## 6. Melhorias por ordem de impacto

| # | Melhoria | Impacto | Esforço |
|---|---|---|---|
| 1 | Reescrever a rolagem: por posição, esperando carregar, voltando nos buracos, com proteção de tempo | crítico | médio |
| 2 | Junção segura de leituras parciais + `scan_cancelled` ao fechar | crítico | baixo |
| 3 | Capturar a **duração** (da linha `mm:ss` e do embed) | alto | baixo |
| 4 | Interceptar o JSON do web player em vez de ler a tela | alto | médio |
| 5 | Tirar `library_status`/merge da thread da interface e eliminar o O(n²) | alto | baixo/médio |
| 6 | Progresso honesto ("faltam 31: 676–706", botão "concluir agora") | alto (percebido) | baixo |
| 7 | CSV robusto (separador, acentos, colunas em pt/es, `mm:ss`, link do Spotify) | médio/alto | baixo |
| 8 | API oficial (PKCE) no Library Mode para playlists próprias (com refresh token, porta livre, retry no 429) | médio | médio |
| 9 | Total via `aria-rowcount`, sem regex em inglês | médio | baixo |
| 10 | Fase 1 sem repetições inúteis, com página e embed independentes | baixo/médio | trivial |
| 11 | Flags anti-throttling do Chromium | médio | trivial |
| 12 | Tipo formal para a música; separar `sp_id`/`source_id` e posição/faixa | médio | médio (migração do `library.json`) |
| 13 | Testes com lista virtual simulada | médio | médio |
| 14 | Descontar do total as músicas que não dá para ler (arquivos locais, podcasts) | baixo/médio | baixo |
| 15 | Amazon/Apple: verificar paginação e registrar o motivo das alternativas no log | baixo | baixo |
