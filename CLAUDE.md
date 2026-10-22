# CSVMusic (fork pessoal) — instruções para o Claude Code

Fork pessoal de https://github.com/angall1/CSVMusic (v1.7.9). App desktop Python + PySide6 que transforma playlists (Spotify, Apple, Deezer, YT Music, CSV...) em arquivos de áudio com tags, buscando no YouTube Music e baixando com yt-dlp + ffmpeg. Uso pessoal, desenvolvido no macOS.

Responda em português do Brasil.

## Documentação do fork (leia antes de mexer na área correspondente)
- `docs/fork/README.md` — índice
- `docs/fork/03-arquitetura-geral.md` — mapa do código, startup, threads, settings
- `docs/fork/04-busca-download-e-tags.md` — ytmusic_match, downloader, workers, tags
- `docs/fork/05-importacao-de-playlists.md` — importadores, leitor do Spotify (travamento)
- `docs/fork/06-interface-design-e-idiomas.md` — UI, redesign, i18n
- `docs/fork/07-biblioteca-missing-e-sync.md` — Library Mode, "missing", device sync, rodar sempre
- `docs/fork/13-duracao-das-musicas.md` — duração da planilha/Spotify na busca e na conferência do download
- `docs/fork/10-roadmap.md` — ordem de trabalho; marque [x] ao concluir itens

## Comandos
- Ambiente: `source .venv/bin/activate` (Python 3.12 do Homebrew: `/opt/homebrew/bin/python3.12`; o `python3` do sistema é 3.14 e o PySide6 6.8.3 não roda nele)
- Instalar: `pip install -e . pytest`
- Rodar app: `python -m csvmusic.app` · só biblioteca: `python -m csvmusic.library_mode_ui`
- Testes: `QT_QPA_PLATFORM=offscreen python -m pytest -q` (um arquivo: `... pytest tests/core/test_x.py -q`). Linha de base em 22/10/2026: 287 passando; com a playlist privada, 295.
- Print de tela sem abrir janela: `HOME=<pasta temporária> QT_QPA_PLATFORM=offscreen` e `widget.grab().save(...)`. O `LibraryModeDialog` para no aviso inicial (`_show_startup_disclaimer`, modal), então troque esse método por um que não faz nada no script do print. O HOME temporário evita tocar na biblioteca real (`~/Library/Application Support/CSVMusic/`).
- Build .app: ver `docs/fork/12-build-e-rodar-sempre-no-mac.md`

## Estilo de código
- **Indentação com TAB** (nunca espaços). Strings com aspas duplas. Type hints em funções públicas novas.
- Logs sempre via `csvmusic.core.log.log`, nunca `print`.
- Lógica nova vai em `csvmusic/core/` (testável, sem Qt). UI só conecta sinais.
- Commits: `tipo(escopo): resumo` (ex.: `fix(match): strip Spotify dash suffixes`), ≤72 caracteres.

## Regras
- Uma fase/item do roadmap por vez. Planeje antes de mudanças grandes.
- Todo conserto vem com teste que falharia sem ele.
- **Testes nunca acessam a rede** (YouTube, Spotify): use fixtures/monkeypatch.
- **Nunca apague arquivos de música do usuário** em código novo: mova para uma pasta de lixeira interna e deixe o usuário esvaziar.
- Não teste downloads na pasta real de músicas; use a pasta de teste do `CLAUDE.local.md`.
- Não mexa em `.github/workflows/release.yml` nem em `resources/ffmpeg|deno` sem pedir.
- Alguns testes antigos verificam texto do código-fonte (`tests/core/test_packaging.py`, `tests/ui/test_theme.py`); se uma refatoração os quebrar, reescreva-os testando comportamento.
- Ao terminar um item do roadmap, atualize o checkbox em `docs/fork/10-roadmap.md`.

## Armadilhas conhecidas
- Os testes escrevem no log real (`~/.local/share/csvmusic/app.log`); não confunda essas linhas ("Test Playlist", Avril Lavigne) com uso de verdade.
- Playlist particular no Spotify: sem login, o Spotify devolve 404, igual a playlist apagada. `SpotifyPlaylistPrivateError` (em `core/spotify_import.py`) cobre os dois casos. A biblioteca grava `access_error="private"` e a lista mostra "PRIVATE ON SPOTIFY"; a próxima análise que der certo limpa a marca.
- yt-dlp roda in-process no app empacotado (`redirect_stdout` global): não rode dois downloads em paralelo por esse caminho.
- `sanitize_name` troca `:"?*<>|/\` por caracteres "largos" (：＂？…); nomes de arquivo esperados dependem disso.
- `track_no` hoje às vezes é posição na playlist, às vezes faixa do álbum.
- `sp_id` guarda ids de outras plataformas também (ASIN, Deezer, YouTube).
- A janela principal é `LibraryModeDialog` (QDialog), não o `MainWindow` (modo legado).
