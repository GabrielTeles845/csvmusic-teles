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
- Testes: `QT_QPA_PLATFORM=offscreen python -m pytest -q` (um arquivo: `... pytest tests/core/test_x.py -q`). Linha de base em 22/10/2026: 287 passando; com a playlist privada, 295; depois da frente biblioteca/configurações/log, 337. O `tests/conftest.py` aponta `CSVMUSIC_DATA_DIR` e `CSVMUSIC_LOG_DIR` para pastas temporárias: a suíte não lê nem grava a biblioteca, as configurações ou o log reais.
- Print de tela sem abrir janela: `CSVMUSIC_DATA_DIR=<pasta temporária> CSVMUSIC_LOG_DIR=<pasta temporária> QT_QPA_PLATFORM=offscreen` e `widget.grab().save(...)`. O `LibraryModeDialog` para no aviso inicial (`_show_startup_disclaimer`, modal): no script, use uma subclasse que troca esse método (e `_check_youtube_at_startup`, `_start_update_check`) por um que não faz nada. As duas variáveis evitam tocar na biblioteca e no log reais.
- Onde ficam os dados do fork: `~/Library/Application Support/CSVMusicTeles/` (configurações, `library.json`) e `~/Library/Logs/CSVMusicTeles/app.log` (com rotação, 5 MB × 4). Na primeira abertura, se a pasta do fork não tem `settings.json` nem `library.json`, o app **copia** (nunca move) `settings.json`, `library.json`, `youtube-cookies.txt` e a pasta `youtube-login/` (perfil Firefox do login, `youtube-cookies.txt` e `popup-cookies.txt`, sem os arquivos de trava do Firefox) do CSVMusic original (`~/Library/Application Support/CSVMusic/`). Se o `cookies_file` copiado aponta para dentro da pasta do original, ele é reescrito para a cópia na pasta do fork (o yt-dlp regrava o arquivo de cookies que recebe). Depois disso os dois apps não compartilham nada.
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
- O log antigo (`~/.local/share/csvmusic/app.log`) tem linhas de testes ("Test Playlist", Avril Lavigne) de antes do isolamento; o log do fork é `~/Library/Logs/CSVMusicTeles/app.log`.
- A Library Mode guarda a biblioteca **em memória** e grava o `library.json` agrupado (no máximo a cada 3 s durante um download, sempre no fim do lote e ao fechar). Não abra o modo legado e a Library Mode mexendo na mesma biblioteca ao mesmo tempo: o modo legado grava direto no arquivo e a próxima gravação da Library Mode passa por cima.
- As configurações também ficam em memória (`core/settings.py`): `save_settings` vale na hora para `load_settings` e grava o arquivo 0,3 s depois (atômico, com `settings.json.bak`). Um script que lê o `settings.json` do disco logo depois de salvar precisa chamar `flush_settings()`.
- `library.json` de outra versão ou ilegível: o app copia para `library.json.unreadable-<data>.bak`, abre vazio e **não grava** até o arquivo voltar a ser lido.
- Verificador de atualização desligado (`UPDATE_CHECK_ENABLED = False` em `core/update_check.py`): os lançamentos do original não são atualização deste fork.
- PySide6 6.8: não troque por `monkeypatch` um método da classe que o código passa para `QTimer.singleShot` (ex.: `_check_youtube_at_startup`); quando o patch é desfeito, o Python cai ao encerrar (segfault no fim da suíte). Use uma subclasse. E nos testes chame `dialog.closeEvent(QCloseEvent())` em vez de `close()`: fechar a última janela pede para o `QApplication` compartilhado sair e quebra os testes de QtWebEngine que vêm depois.
- Playlist particular no Spotify: sem login, o Spotify devolve 404, igual a playlist apagada. `SpotifyPlaylistPrivateError` (em `core/spotify_import.py`) cobre os dois casos. A biblioteca grava `access_error="private"` e a lista mostra "PRIVATE ON SPOTIFY" (junto com o botão de erros, se houver). Qualquer análise que chegou à playlist limpa a marca, mesmo vindo vazia; uma falha de rede não cria nem apaga a marca.
- yt-dlp roda in-process no app empacotado (`redirect_stdout` global): não rode dois downloads em paralelo por esse caminho.
- `sanitize_name` troca `:"?*<>|/\` por caracteres "largos" (：＂？…); nomes de arquivo esperados dependem disso.
- `track_no` hoje às vezes é posição na playlist, às vezes faixa do álbum.
- `sp_id` guarda ids de outras plataformas também (ASIN, Deezer, YouTube).
- A janela principal é `LibraryModeDialog` (QDialog), não o `MainWindow` (modo legado).
