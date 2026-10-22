# 03 — Arquitetura geral do CSVMusic v1.7.9

> Mapa do código inteiro, como o app inicia, como as threads conversam, onde ficam configurações/logs, dependências, testes e CI.
> Os detalhes de cada subsistema estão nos docs 04 (busca/download/tags), 05 (importação de playlists), 06 (interface/idiomas) e 07 (biblioteca e "missing").

---

## 1. Visão de 30 segundos

```
 Fonte da playlist                 Motor                                     Saída
 ─────────────────                 ─────                                     ─────
 Link Spotify/Apple/Amazon/  ──▶  importadores (core/*_import.py)  ──▶ lista de "track dicts"
 Deezer/YT Music/SoundCloud         │                                         │
 ou CSV do TuneMyMusic              ▼                                         ▼
                                  plano de saída (track_output.py)   já existe? → pula
                                    │
                                    ▼ (para cada faixa, em sequência)
                                  busca no YouTube Music (ytmusic_match.py)
                                    │  nota ≥ 0.6 ? senão "Skipped (low confidence)"
                                    ▼
                                  yt-dlp baixa o áudio (downloader.py) → ffmpeg converte/normaliza
                                    ▼
                                  capa + tags (mutagen)  →  Pasta/Playlist/NN- Artista - Título.ext
                                    ▼
                                  .m3u8/.m3u da playlist
```

Tudo isso roda dentro de uma `QThread` (`PipelineWorker`, `ui/workers.py:143`), **uma faixa por vez**, com pausas entre faixas.

---

## 2. Mapa do repositório

136 commits, 63 tags, ~25,6 mil linhas. Autor principal `angall1` (134 commits). Primeiro commit em 26/09/2025, v1.7.9 em 15/10/2026. Lança em rajadas (às vezes 1 versão por semana).

### Raiz
| Arquivo | O que é |
|---|---|
| `pyproject.toml` | metadados e dependências (setuptools) |
| `CSVMusic.spec` | receita do PyInstaller (gera `.exe` / `.app`) |
| `.github/workflows/release.yml` | **único** workflow de CI: compila e publica releases (605 linhas) |
| `AGENTS.md` | instruções para agentes de IA (TAB, logs via `log()`, commits) — **desatualizado** em 2 pontos |
| `README.md`, `README-LINUX.md` | instruções e changelog |
| `MANIFEST.in`, `.gitignore`, `.gitattributes` | empacotamento/git (`.gitignore` tem uma linha lixo `' + $tmpdir + '/`) |
| `spotify_scrape_experiment_results.json` | resultado de experimento commitado por acidente |

### `csvmusic/` — entradas
| Arquivo | O que é |
|---|---|
| `__main__.py` | `python -m csvmusic` → `app.main()` |
| `app.py` (185) | inicialização (ver §4) |
| `version.py` | `APP_VERSION = "1.7.9"` — mudar isso na `main` **dispara um release** no CI |
| `library_mode_ui.py`, `spotify_api_test_ui.py`, `spotify_public_scrape_ui.py` | abrem só uma tela (útil para desenvolver) |
| `fetch_csv.py`, `match_csv.py`, `download_csv.py`, `fetch_spotify_api.py` | **mini-CLIs** já existentes (inspecionar CSV, só buscar, pipeline completo sem UI, metadados Spotify). Base para o modo linha de comando! |

### `csvmusic/core/` — lógica (quase sem Qt)
| Arquivo | Linhas | O que faz |
|---|---|---|
| `ytmusic_match.py` | 398 | busca e nota de confiança (doc 04) |
| `downloader.py` | 892 | yt-dlp, ffmpeg, capas, tags, perfis anti-bloqueio, M3U (doc 04) |
| `track_output.py` | 70 | nome/caminho esperado de cada faixa; "já existe?" |
| `library.py` | 553 | `library.json` (doc 07) |
| `device_sync.py` | 569 | sincronizar com players portáteis (doc 07) |
| `ipod_sync_helper.c`, `ipod_manifest.py` | 302 / 89 | ajudante nativo (libgpod) para iPod |
| `spotify_import.py`, `spotify_api.py`, `spotify_oauth.py` | 478 / 205 / 73 | Spotify: página pública e API com login PKCE (doc 05) |
| `apple_music_import.py`, `amazon_music_import.py`, `deezer_import.py`, `youtube_music_import.py`, `web_playlist_import.py`, `url_import.py` | | outros serviços + "despachante" por URL (doc 05) |
| `csv_import.py` | 205 | CSV do TuneMyMusic (usa pandas) |
| `browsers.py`, `youtube_login.py`, `youtube_session.py`, `youtube_url.py` | | cookies/perfis de navegador, sessão do YouTube |
| `js_runtime.py` | 112 | acha Deno/Node para o yt-dlp |
| `paths.py` | 331 | acha ffmpeg, yt-dlp, deno, recursos |
| `preflight.py` | 225 | checagens antes de baixar (ffmpeg ok? runtime JS? internet?) |
| `settings.py` | 82 | `settings.json` |
| `log.py` | 17 | log em arquivo |
| `audio_quality.py`, `source_quality.py` | 48 / 64 | qualidade do áudio de origem (avisa bitrate baixo) |
| `update_check.py` | 63 | checa nova versão no GitHub |
| `artwork.py`, `models.py`, `config.py`, `import_warnings.py`, `output_folder.py`, `subprocess_env.py` | | utilitários (`config.py` praticamente morto) |

### `csvmusic/ui/` — telas (PySide6)
| Arquivo | Linhas | O que é |
|---|---|---|
| `library_mode.py` | 3641 | **tela principal** (Library Mode) + diálogos |
| `main_window.py` | 3129 | modo legado (uma playlist por vez) |
| `workers.py` | 805 | threads de trabalho (pipeline, download avulso, alternativas, cookies, update) |
| `device_sync.py` | 541 | tela de sync com aparelhos |
| `spotify_public_scrape.py` | 603 | navegador embutido que rola a página do Spotify (doc 05) |
| `spotify_api_test.py` | 472 | assistente de login na API do Spotify |
| `youtube_login.py`, `youtube_popup.py` | 105 / 164 | login no YouTube |
| `theme.py` | 84 | tema retrô, fonte Comic |

### `resources/`, `licenses/`, `tests/`
- `resources/`: ícones, splash (não usado mais), fontes (Comic Neue, VCR OSD Mono). **ffmpeg, deno e o ajudante do iPod NÃO estão no git** — o CI baixa/compila na hora do release.
- `licenses/`: só `ComicNeue-OFL.txt` (o CI adiciona as do Deno e FFmpeg).
- `tests/`: 234 testes (26 arquivos em `tests/core`, 12 em `tests/ui`).

---

## 3. Dependências

| Pacote | Versão | Para quê |
|---|---|---|
| `PySide6` | `==6.8.3` (fixo: último Qt que roda no macOS 12) | toda a UI + QtWebEngine (navegador embutido do Spotify) |
| `yt-dlp[default]` | `==2026.8.19` (fixo!) | baixar do YouTube; roda **dentro do próprio processo** no app empacotado |
| `ytmusicapi` | `>=1.7.4` | busca no YouTube Music |
| `mutagen` | `>=1.47.0` | tags |
| `requests` | `>=2.32.0` | HTTP |
| `pandas` | `>=2.2.0` | ler CSV (pesado demais pra isso) |

Externos: **ffmpeg** (com libmp3lame), **Deno 2.3+ ou Node 22+** (o yt-dlp precisa para os desafios JS do YouTube), libgpod (só iPod).

**Python:** use **3.11–3.13**. (O pyproject diz `>=3.10`, mas os testes usam `tomllib` de 3.11 e o PySide6 6.8.3 não roda em 3.14.)

> ⚠️ O yt-dlp fixado dentro do app é um problema: quando o YouTube muda algo (frequente), **todo mundo quebra até sair release nova**. No fork, permita um yt-dlp externo atualizável (doc 09, G3).

---

## 4. Como o app inicia (`app.py`)

1. Ajusta `sys.path` (permite rodar como script).
2. Define variáveis do Qt antes de importar (desliga GPU do WebEngine no Linux, silencia avisos).
3. **Monkeypatch em `builtins.__import__`** para bloquear `tkinter` no processo inteiro (`app.py:39-44`).
4. No Windows, procura e fecha uma janela Tk por até 1 s — que nunca existe → **1 s perdido sempre** (`app.py:47-57`).
5. Importa o `LibraryModeDialog` **antes** de criar o `QApplication` (comentário: evita travamento do WebEngine no Windows).
6. `main()` cria o `QApplication`. `--smoke-test` (usado no CI do Mac) abre e fecha para testar.
7. `apply_retro_theme(app)` — estilo Fusion + paleta clara fixa + fonte Comic.
8. Abre o `LibraryModeDialog` (janela principal). O botão de modo legado cria `MainWindow`s guardadas em `legacy_windows`.
9. Código morto: `probe_ffmpeg()` e `show_qt_splash()` (`app.py:79-128`).

---

## 5. Threads e comunicação

- Todo trabalho pesado roda em **subclasses de `QThread` com `run()` próprio** (`ui/workers.py`): `PipelineWorker`, `SingleDownloadWorker`, `AlternativesFetchWorker`, `MusicURLImportWorker`, `UpdateCheckWorker`, `CookiesCheckWorker`, `YouTubeSessionTestWorker`, e outros em `library_mode.py` (`DirectLibraryScanWorker`), `youtube_login.py`, `spotify_api_test.py`.
- Comunicação **só por sinais** do worker para a UI.
- Parar = flag `self._stop`, checada **só entre faixas**. Ao fechar a janela, `_shutdown_thread` (`main_window.py:3074-3100`) usa **`QThread.terminate()`**: pode deixar arquivos pela metade e o yt-dlp órfão.
- O yt-dlp no app empacotado roda **no mesmo processo** com `redirect_stdout` (global) → dois downloads simultâneos (pipeline + download manual) podem misturar saídas (doc 04, bug 12).

---

## 6. Onde ficam as coisas no disco

| O quê | Windows | macOS | Linux |
|---|---|---|---|
| Configurações (`settings.json`), biblioteca (`library.json`), perfil WebEngine, perfil Firefox do login, `youtube-cookies.txt` | `%APPDATA%\CSVMusic` | `~/Library/Application Support/CSVMusic` | `~/.local/share/csvmusic` |
| Log (`app.log`) | `~/.local/share/csvmusic/app.log` (!) | `~/.local/share/csvmusic/app.log` (!) | idem |

- O log vai para o caminho estilo Linux **em todos os sistemas**, sem rotação (cresce para sempre), abrindo o arquivo a cada linha.
- `settings.json`: objeto plano, sem versão. Chaves conhecidas: `cookies_browser, cookies_file, cookies_test_ok, csv_path, device_sync_auto_eject, embed_art, eq_bass_gain, eq_enabled, eq_normalize, eq_treble_gain, eq_volume_gain, ffmpeg_path, force_download_mode, format, hide_startup_disclaimer, last_update_check_at, legacy_cover_art_mode, legacy_ipod_mode, legacy_mp3_mode, load_csv_path, load_source_path, m3u_output_dir, mp3_quality, opus_output_enabled, output_dir, prefix_track_numbers, readability_mode, skipped_update_version, use_cookies, write_m3u8, write_m3u_plain, yt_dlp_path`.
- **Risco real:** `save_settings` lê → mescla → reescreve **sem escrita atômica** e engolindo erros; se a leitura falhar, vira `{}` e a próxima gravação **apaga todas as configurações**. E o modo legado grava a cada tecla digitada.

> Para rodar o seu fork **ao lado** do original sem um bagunçar a biblioteca do outro: mude o nome da pasta em `core/settings.py` (ex.: `CSVMusicTeles`).

---

## 7. Verificador de atualização

`core/update_check.py:9` consulta `https://api.github.com/repos/angall1/CSVMusic/releases/latest`, no máximo 1×/dia, 1,5 s após abrir. Só abre o navegador (não atualiza sozinho). **No fork, troque a URL** (ou desligue), senão você será avisado das versões do original.

---

## 8. Testes

```bash
pip install -e . pytest
python -m pytest -q
python -m pytest tests/core/test_ytmusic_match.py -q   # um arquivo
```
- 234 testes, usando `monkeypatch`, sem pytest-qt. `tests/conftest.py` cria um `QApplication` único.
- Alguns testes **conferem o texto do código-fonte** (`test_packaging.py` procura strings no `release.yml`/spec; `tests/ui/test_theme.py:44-50` procura QSS literal). Eles **vão quebrar no redesign** — é esperado; reescreva-os.
- `test_packaging.py:23-34` exige versão do pyproject == `APP_VERSION` e links do README de uma única versão.
- Lacunas: quase nada de `main_window.py` testado; sem teste de settings corrompido, de log, de composição de comandos do yt-dlp, de sufixos do Spotify na busca.

---

## 9. CI / Release (resumo — detalhes no doc 12)

- Só existe `release.yml`. Dispara em tag `v*`, em push na `main` que muda `version.py`, em release publicado ou manualmente.
- Builds: Linux (ubuntu-22.04), **macOS arm64 (macos-15)**, **macOS Intel (macos-15-intel)**, Windows. Python 3.11. Roda `pytest -q` antes.
- Mac: compila FFmpeg 8.1.2 do código-fonte (LGPL, LAME estático), baixa Deno com checagem SHA256, PyInstaller, **assinatura ad-hoc** (`codesign --sign -`), sem notarização.
- **Não há CI para push/PR** — no fork vale criar um `ci.yml` simples rodando os testes no macOS.

---

## 10. Os pontos fracos estruturais (o que justifica o fork)

1. **Lógica misturada com tela.** `main_window.py` e `library_mode.py` somam ~6,8 mil linhas com regra de negócio dentro. → separar um "motor" (doc 09, A2).
2. **Estado frágil.** "Já baixado" = nome de arquivo; buscas não são guardadas; fila não sobrevive a fechar o app. → SQLite (doc 09, A1; doc 04 §4).
3. **Pipeline sequencial com esperas fixas.** → busca separada + 2-3 downloads + freio adaptativo (doc 04 §5).
4. **Dois modos que fazem a mesma coisa** (legado e biblioteca), que podem até gravar `library.json` ao mesmo tempo. → ficar só com a biblioteca, redesenhada.
5. **Textos como lógica** (status em inglês decide cor da linha) → impede tradução (doc 06).
6. **yt-dlp congelado** dentro do app → quebra quando o YouTube muda.
