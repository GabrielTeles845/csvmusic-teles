# 14 — Interface web: motor, servidor local e contrato

> Decidido em 22/10/2026. Substitui a janela antiga (`LibraryModeDialog`, `MainWindow` e diálogos em Qt Widgets). Visual: direção 3, "Capa ambiente" (`06 §5`). Texto todo em português do Brasil.

## 1. Como fica o app

```
python -m csvmusic.app
  └─ QApplication (continua existindo: o leitor do Spotify e o login do Google usam QtWebEngine)
       ├─ Engine (csvmusic/engine/)        biblioteca em memória, análises, downloads, configurações
       ├─ Servidor HTTP local (csvmusic/web/server.py)  127.0.0.1, porta da config `web_port` (padrão 8765; se ocupada, outra livre)
       │    ├─ GET /            → csvmusic/web/static/index.html (com o token)
       │    ├─ /static/…        → CSS, JS, fontes, ícones
       │    ├─ /api/…           → JSON (seção 4)
       │    └─ /api/events      → Server-Sent Events (seção 5)
       └─ Janela principal: QMainWindow + QWebEngineView apontando para o servidor
            menu nativo do Mac (CSVMusic › Sobre, Ajustes ⌘, , Sair ⌘Q; Arquivo › Adicionar playlist ⌘N,
            Importar planilha…, Abrir biblioteca…, Salvar biblioteca como…, Abrir no navegador)
```

- O mesmo endereço abre no navegador do Mac (menu "Abrir no navegador"). Só `127.0.0.1`.
- Janelas nativas que continuam em Qt, porque precisam de um navegador próprio ou do sistema: o login do Google (`ui/youtube_popup.py`), o leitor escondido do Spotify (`ui/spotify_public_scrape.py`), o seletor de pasta/arquivo do macOS. A página pede ao motor e o motor abre.
- Fechar a janela grava a biblioteca e encerra o app (o "fechar só esconde" é a fase 8).

## 2. Regras do motor (`csvmusic/engine/`)

- Sem widgets. Pode usar `QObject`, `QThread`, `QTimer` (os workers atuais são `QThread`). Roda na thread principal do Qt.
- O servidor HTTP roda em threads próprias e **nunca** mexe na biblioteca direto: chama o motor por uma ponte thread-safe (fila + `QMetaObject.invokeMethod`/sinal com `Qt.BlockingQueuedConnection`, com tempo limite).
- Toda lógica que hoje está em `ui/library_mode.py` (orquestrar análise e download, aplicar resultados, contagens, M3U parcial, restrição de idade, revisão, escolha manual) vai para o motor, reaproveitando `core/` e `ui/workers.py`. Nada de copiar regra para o JavaScript.
- Biblioteca em memória, gravação agrupada (no máximo a cada 3 s, sempre no fim do lote e ao fechar), como já faz a Library Mode.
- **Remover playlist nunca apaga música:** a pasta da playlist vai para a Lixeira do macOS (`QFile.moveToTrash`). Mesma regra para "esvaziar a lixeira interna" (`.csvmusic-lixeira`): vai para a Lixeira do Mac, não some.
- Toda mensagem que chega à tela sai em português (motivo de pulo, erro de download resumido, avisos). O texto técnico completo continua no log.

## 3. Segurança do servidor local

- Escuta só em `127.0.0.1`.
- Token aleatório por execução, colocado no `index.html` (`<meta name="csvmusic-token">`). Toda chamada `/api/…` exige o cabeçalho `X-CSVMusic-Token`; sem ele, 403. Cabeçalho próprio força o "preflight" do navegador, e o servidor não responde CORS: outro site aberto no navegador não consegue chamar a API.
- `/api/events` (EventSource não manda cabeçalho) aceita o token em `?token=`.
- Confere o `Host` (`127.0.0.1:<porta>` ou `localhost:<porta>`) contra DNS rebinding.
- Imagens de capa passam pelo próprio servidor (`/api/image?url=`), com cache em disco na pasta de dados; só `https` de `i.scdn.co`, `mosaic.scdn.co`, `image-cdn-*.spotifycdn.com`, `*.ytimg.com`, `*.googleusercontent.com`, `*.mzstatic.com`, `*.dzcdn.net`, `m.media-amazon.com`.

## 4. API (JSON, prefixo `/api`)

Erros: status 4xx/5xx com `{"error": "mensagem em português"}`.

### Objetos

**PlaylistSummary**
```json
{
  "id": "spotify:611N3KSs459UD5IVPH1ES4",
  "platform": "spotify", "source_type": "playlist", "name": "Out Of Time Man", "url": "https://…",
  "cover_urls": ["https://…", "…"],
  "counts": {"total": 1124, "downloaded": 912, "missing": 198, "review": 9, "error": 5, "age_limit": 1,
             "not_found": 3, "disabled": 12, "queued": 0},
  "reported_total": 1124, "last_scanned_at": "2026-10-22T13:00:00+00:00",
  "scan_state": "never|ok|incomplete", "scan_warning": null,
  "access_error": null, "access_error_message": null,
  "folder": "/Users/…/Musicas/Out Of Time Man"
}
```
`cover_urls`: até 4 capas distintas das primeiras músicas (mosaico 2×2); se a playlist tem capa própria e menos de 4 músicas com capa, usa a da playlist.

**Track**
```json
{
  "index": 0, "position": 1, "title": "Country House - 2012 Remaster", "artists": "Blur", "album": "The Great Escape",
  "duration_ms": 237500, "cover_url": "https://…", "enabled": true,
  "state": "downloaded|missing|review|error|age_limit|not_found|redownload|queued|matching|downloading|tagging|disabled",
  "detail": "Arquivo 7 s mais longo que a música",
  "downloaded_video": {"id": "uLivzCQcQW8", "title": "Country House", "publisher": "Blur"},
  "preferred_video": {"id": "…", "label": "Country House — Blur"},
  "volume_gain": 0, "quality": {"label": "AAC 128 kbps", "low": false}, "file_path": "/…/Country House.m4a",
  "error": null
}
```
`detail` é a frase curta da situação (motivo do pulo, da revisão, do erro), sempre em português. `quality` só quando o arquivo existe.

**Job** (só um por vez)
```json
{"kind": null}
{"kind": "scan", "playlist_id": "…", "name": "…", "captured": 676, "reported_total": 1124, "queue_left": 2}
{"kind": "download", "playlist_ids": ["…"], "processed": 12, "total": 198, "eta_at": "2026-10-22T15:40:00-03:00",
 "current": {"playlist_id": "…", "index": 41, "title": "Could You Be Loved", "artists": "Bob Marley", "cover_url": "…", "phase": "matching|downloading|tagging", "percent": 43},
 "stopping": false}
```

### Rotas

| Método e rota | Corpo / parâmetros | Resposta |
|---|---|---|
| `GET /api/state` | — | `{version, library: {path, output_dir, format}, playlists: [PlaylistSummary], job: Job, account: {connected, use_cookies, checked_at}, first_run: bool}` |
| `GET /api/playlists/{id}/tracks` | `filter=all\|missing\|review\|error\|downloaded\|disabled\|not_found`, `q=`, `offset=0`, `limit=100` | `{total, counts, items: [Track]}` (`total` já filtrado; `counts` da playlist inteira) |
| `POST /api/playlists` | `{"urls": ["…"]}` | `{added: [id], errors: [{url, error}]}` (análise começa sozinha para as novas) |
| `POST /api/playlists/import-csv` | `{"filename": "…", "content_base64": "…", "name": "opcional"}` | `{added: [id], warnings: []}` |
| `PATCH /api/playlists/{id}` | `{"name": "…"}` | `PlaylistSummary` |
| `DELETE /api/playlists/{id}` | `?files=keep\|trash` | `{removed: true, trashed_folder: "…"\|null}` (recusa com 409 se a pasta é compartilhada com outra playlist) |
| `POST /api/scan` | `{"playlist_ids": [...]}` ou `{"scope": "all"\|"unscanned"}` | `Job` |
| `POST /api/scan/cancel` | — | `Job` |
| `POST /api/download` | `{"playlist_ids": [...], "missing_only": true}` ou `{"targets": [[playlist_id, index], ...]}` | `Job` (409 se já há tarefa) |
| `POST /api/download/stop` | — | `Job` |
| `PATCH /api/playlists/{id}/tracks/{index}` | qualquer de `enabled`, `title`, `artists`, `album`, `volume_gain`, `preferred_video_url` (`""` volta ao automático), `force_redownload` | `Track` |
| `POST /api/playlists/{id}/tracks/set-enabled` | `{"enabled": bool, "indices": [..]}` ou `{"enabled": bool, "all": true}` | `{changed: n}` |
| `POST /api/playlists/{id}/tracks/{index}/accept` | — | `Track` (aceita a revisão) |
| `GET /api/playlists/{id}/tracks/{index}/alternatives` | — | `{options: [{videoId, title, author, source: "music"\|"videos", duration_seconds, album, duration_mismatch, version_markers, score}]}` |
| `GET /api/video-info` | `url=`, `playlist_id=`, `index=` | `{video_id, info: {title, author, duration_seconds, kind, playable, age_restricted}, description, warnings: ["…"]}` (avisos de `core/manual_match.py`, em português) |
| `POST /api/playlists/{id}/tracks/{index}/download-now` | `{"video_id": "…"}` | `Job` (baixa só essa música com esse vídeo) |
| `GET /api/settings` | — | objeto da seção 4.1 |
| `PATCH /api/settings` | chaves da seção 4.1 | objeto completo |
| `POST /api/dialogs/choose-folder` | `{"purpose": "output"\|"m3u"\|"tool", "start": "…"}` | `{path: "…"\|null}` (seletor nativo) |
| `POST /api/dialogs/choose-file` | `{"purpose": "cookies"\|"ytdlp"\|"ffmpeg"\|"library"}` | `{path: "…"\|null}` |
| `POST /api/library/open` | `{"path": "…"}` | `state` |
| `POST /api/library/save-as` | `{"path": "…"}` | `{path}` |
| `POST /api/open` | `{"what": "output"\|"playlist"\|"file"\|"log", "playlist_id": "…", "index": 0}` | `{ok: true}` (abre no Finder) |
| `GET /api/export-csv` | `playlist_id=` (sem ele, a biblioteca toda) | arquivo `.csv` |
| `POST /api/account/youtube/sign-in` | `{"method": "popup"\|"firefox"}` | `{started: true}`; resultado chega no evento `account` |
| `POST /api/account/youtube/test` | — | `{started: true}`; resultado no evento `account` |
| `POST /api/age-restricted/resolve` | — | liga a sessão ou abre o login; ao confirmar, evento `age_retry_ready` |
| `GET /api/log` | `since=<seq>` | `{entries: [{seq, ts, level, message}], last_seq}` (log da sessão de download) |
| `GET /api/devices` | — | `{devices: [{id, name, kind, description}], busy}` |
| `GET /api/devices/{id}/playlists` | — | `{playlists: [{name, track_count}]}` |
| `POST /api/devices/{id}/sync` | `{"playlist_ids": [...]}` | `{started: true}`; progresso no evento `device` |
| `DELETE /api/devices/{id}/playlists/{name}` | — | `{removed: true}` |
| `POST /api/devices/{id}/eject` | — | `{ok: true}` |
| `GET /api/trash` | — | `{files: n, bytes: n}` (lixeira interna de todas as playlists) |
| `POST /api/trash/empty` | — | `{moved: n}` (vai para a Lixeira do macOS) |
| `GET /api/image` | `url=` | bytes da imagem (cache) |
| `POST /api/first-run/accept` | — | `{ok: true}` (aviso inicial aceito) |

### 4.1 Configurações (`GET/PATCH /api/settings`)

`output_dir`, `format` (`m4a|mp3|opus|…` de `SUPPORTED_FORMATS`), `mp3_quality` (0–10), `legacy_ipod_mode`, `legacy_mp3_mode` (`vbr|cbr…`), `embed_art`, `force_download_mode`, `prefix_track_numbers`, `write_m3u8`, `m3u_output_dir`, `yt_dlp_path`, `ffmpeg_path`, `use_cookies`, `cookies_browser`, `cookies_file`, `eq_enabled`, `eq_normalize`, `eq_<banda>_gain` (bandas do equalizador atual), `theme` (`system|light|dark`), `web_port`. Nomes iguais aos do `settings.json` de hoje; o motor valida.

## 5. Eventos (`GET /api/events?token=…`, Server-Sent Events)

Cada mensagem: `event: <tipo>` e `data: <json>`.

| Tipo | Dados | Quando |
|---|---|---|
| `playlist` | `PlaylistSummary` | contagem, nome, capa ou marca de uma playlist mudou |
| `playlists` | `{ids: [...]}` | playlist entrou ou saiu (a tela pede `/api/state`) |
| `track` | `{playlist_id, track: Track}` | uma música mudou (resultado, estado em andamento) |
| `job` | `Job` | progresso; no máximo 4 por segundo |
| `scan_done` | `{results: [{playlist_id, name, captured, reported_total, status: "ok"\|"incomplete"\|"private"\|"error", message}]}` | fim de uma rodada de análise |
| `download_done` | `{done, skipped, failed, age_restricted: n, stopped: bool, message}` | fim do download |
| `log` | `{seq, ts, level, message}` | linha nova do log da sessão |
| `warning` | `{message}` | aviso que a tela mostra em destaque |
| `account` | `{connected, use_cookies, ok, message}` | login/teste do YouTube terminou |
| `age_retry_ready` | `{targets: n}` | sessão confirmada; a tela oferece "Baixar de novo" |
| `device` | `{phase, done, total, message}` | sincronização com aparelho |
| `library` | `{path}` | outra biblioteca foi aberta |

A cada conexão, o servidor manda primeiro `job` com o estado atual.

## 6. Tela (`csvmusic/web/static/`)

- Sem etapa de build: HTML, CSS e módulos JS do navegador. Nada carregado da internet (fonte Figtree e ícones Lucide ficam dentro do repositório, com as licenças em `licenses/`).
- Lista virtual: só as linhas visíveis existem no DOM; páginas de 100 músicas pedidas conforme rola. Atualização de uma música troca só aquela linha.
- Carregando: shimmer no formato final (skill `carregamento-fiel`). Primeiro acesso e estado vazio: demonstração animada de colar o link e analisar (skill `demo-animada`).
- Temas claro e escuro, seguindo o sistema, com escolha nos ajustes.
- Larguras conferidas: 390 (celular) e 1440 (computador), claro e escuro.

### Telas e onde cada função antiga foi parar

| Antes (janela antiga) | Agora |
|---|---|
| Campo "Paste playlist URL" + botão verde | "Adicionar playlist" na lateral (⌘N): campo de link, aceita vários |
| "Add CSV..." | Mesmo diálogo, aba "Planilha" (escolher arquivo) |
| Open Library / Save As | Menu Arquivo do app e Ajustes › Biblioteca |
| Choose Output / Format | Ajustes › Downloads |
| Playlists: Download All, Rescan All, Scan Unscanned, abrir pasta | Lateral: menu "…" acima da lista de playlists |
| Cartão da playlist: renomear (duplo clique), analisar, remover, "N errors", "PRIVATE ON SPOTIFY", contagem incompleta | Cabeçalho da playlist: título editável, botões Baixar faltando / Analisar / "…" (remover, abrir pasta, exportar planilha); avisos de particular e incompleta logo abaixo do título |
| Lista de músicas, busca, "Load More" | Lista virtual com filtros (Todas, Faltando, Revisar, Com erro, Baixadas, Desmarcadas, Não encontradas) e busca |
| Caixa de seleção da música, marcar/desmarcar todas | Caixa na linha; "Marcar todas / Desmarcar todas" no "…" da lista |
| Duplo clique para editar título/artista/álbum | Painel da música › Dados |
| Engrenagem (Song Settings): alternativas, colar link, volume | Painel da música (abre à direita no computador, de baixo no celular): Versão do YouTube, Volume, Dados, Erro |
| ✓ aceitar revisão / ✗ rejeitar | Na linha "Revisar": Aceitar e Trocar |
| Botão do erro da música | Painel da música › Erro (texto completo e o que fazer) |
| Download / Stop / Log / atividade | Barra de baixo ("tocando agora"): capa, música, progresso, previsão de término, Parar, Registro |
| Botão de restrição de idade | Aviso no fim do download + barra de baixo: "Entrar no YouTube" |
| Resumo de análise (RescanSummaryDialog) | Aviso no fim da análise com o resultado por playlist |
| Settings (General, YouTube Account, Advanced) | Ajustes: Downloads, Conta do YouTube, Avançado, Aparência, Biblioteca |
| Equalizer | Ajustes › Som |
| Sync (aparelhos) | Lateral › Aparelhos |
| Tutorial / Info | Ajuda (com a demonstração animada) e Sobre |
| Legacy Mode | Removido |
| Aviso inicial (disclaimer) | Primeira abertura, uma vez |

## 7. O que sai

Depois que a tela nova cobre tudo: `ui/main_window.py`, `ui/library_mode.py`, `ui/device_sync.py`, `ui/theme.py`, `ui/spotify_api_test.py`, `library_mode_ui.py`, `spotify_api_test_ui.py`, as fontes Comic Neue/VCR e os testes que só existiam para essas telas. Ficam: `ui/workers.py`, `ui/spotify_public_scrape.py`, `ui/youtube_popup.py`, `ui/youtube_login.py` (janelas nativas necessárias).
