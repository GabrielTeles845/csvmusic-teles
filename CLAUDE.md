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
- Rodar app: `python -m csvmusic.app` (ou `python -m csvmusic`): interface web numa janela nativa, servidor em `http://127.0.0.1:8765/` (doc 14).
- Testar o servidor sem tocar nos dados reais: `CSVMUSIC_DATA_DIR=<pasta temporária> CSVMUSIC_LOG_DIR=<pasta temporária> python -m csvmusic`; o token está na `<meta name="csvmusic-token">` de `GET /`, e toda chamada `/api/…` precisa do cabeçalho `X-CSVMusic-Token`. Feche o app antes de terminar (`lsof -nP -iTCP:8765 -sTCP:LISTEN` tem de vir vazio).
- Testes: `QT_QPA_PLATFORM=offscreen python -m pytest -q` (um arquivo: `... pytest tests/core/test_x.py -q`). Linha de base em 22/10/2026: 287 passando; com a playlist privada, 295; depois da frente biblioteca/configurações/log, 337; antes do motor web, 479; com o motor e o servidor, 524; com os consertos da revisão, 558; depois de aposentar a janela antiga (e os testes que só existiam para ela), 505; com os consertos da segunda revisão da tela web, 526. O `tests/conftest.py` aponta `CSVMUSIC_DATA_DIR` e `CSVMUSIC_LOG_DIR` para pastas temporárias: a suíte não lê nem grava a biblioteca, as configurações ou o log reais.
- Print da tela: suba `python3 tests/web/mock_server.py --porta <p>` (dados falsos, sem janela, não aparece no Dock) ou o app real com `CSVMUSIC_DATA_DIR`/`CSVMUSIC_LOG_DIR` temporários e `QT_QPA_PLATFORM=offscreen`, e fotografe com Playwright em 1440 e 390, claro e escuro. O app real aparece no Dock como o foguete do Python e pula enquanto abre: feche assim que terminar (o Gabriel já perguntou se era vírus).
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
- Alguns testes antigos verificam texto do código-fonte (`tests/core/test_packaging.py`); se uma refatoração os quebrar, reescreva-os testando comportamento.
- Ao terminar um item do roadmap, atualize o checkbox em `docs/fork/10-roadmap.md`.

## Armadilhas conhecidas
- O log antigo (`~/.local/share/csvmusic/app.log`) tem linhas de testes ("Test Playlist", Avril Lavigne) de antes do isolamento; o log do fork é `~/Library/Logs/CSVMusicTeles/app.log`.
- O motor guarda a biblioteca **em memória** e grava o `library.json` agrupado (no máximo a cada 3 s durante um download, sempre no fim do lote e ao fechar). Não edite o `library.json` com o app aberto: a próxima gravação passa por cima (o `fill_durations` recusa rodar por isso).
- As configurações também ficam em memória (`core/settings.py`): `save_settings` vale na hora para `load_settings` e grava o arquivo 0,3 s depois (atômico, com `settings.json.bak`). Um script que lê o `settings.json` do disco logo depois de salvar precisa chamar `flush_settings()`.
- `library.json` de outra versão ou ilegível: o app copia para `library.json.unreadable-<data>.bak`, abre vazio e **não grava** até o arquivo voltar a ser lido.
- Verificador de atualização desligado (`UPDATE_CHECK_ENABLED = False` em `core/update_check.py`): os lançamentos do original não são atualização deste fork.
- PySide6 6.8: não troque por `monkeypatch` um método da classe que o código passa para `QTimer.singleShot`; quando o patch é desfeito, o Python cai ao encerrar (segfault no fim da suíte). Use uma subclasse. Nos testes, não feche a última janela com `close()`: isso pede para o `QApplication` compartilhado sair e quebra os testes de QtWebEngine que vêm depois.
- Playlist particular no Spotify: sem login, o Spotify devolve 404, igual a playlist apagada. `SpotifyPlaylistPrivateError` (em `core/spotify_import.py`) cobre os dois casos. A biblioteca grava `access_error="private"` e a tela mostra o aviso de playlist particular. Qualquer análise que chegou à playlist limpa a marca, mesmo vindo vazia; uma falha de rede não cria nem apaga a marca.
- Sem login, o YouTube pode recusar todo download da conexão com "confirme que não é um robô" (visto de verdade em 22/10/2026, inclusive com o yt-dlp sozinho). A música fica com `failure_kind="youtube_blocked"`, a tela oferece entrar no YouTube e o lote para depois de 2 recusas seguidas. Para testar download de verdade é preciso a sessão do YouTube.
- yt-dlp roda in-process no app empacotado (`redirect_stdout` global): não rode dois downloads em paralelo por esse caminho.
- `sanitize_name` troca `:"?*<>|/\` por caracteres "largos" (：＂？…); nomes de arquivo esperados dependem disso.
- `track_no` hoje às vezes é posição na playlist, às vezes faixa do álbum.
- `sp_id` guarda ids de outras plataformas também (ASIN, Deezer, YouTube).
- A janela é a interface web (`csvmusic/app.py` + `csvmusic/engine/` + `csvmusic/web/`, doc 14). A janela antiga (`LibraryModeDialog`, `MainWindow`, tema Comic/VCR) foi removida em 22/10/2026; está no histórico do git. Em `csvmusic/ui/` ficam só os workers e as janelas nativas que precisam de navegador (leitor do Spotify, login do Google).
- O servidor HTTP roda em threads próprias e **nunca** mexe na biblioteca direto: passa por `EngineBridge.call` (thread do Qt). Na thread do servidor, não chame `QThread.currentThread()`: o PySide cria um QThread do Python para aquela thread e o processo cai (segfault) depois que ela acaba. Compare com `threading.get_ident()`.
- Testes do servidor: o motor responde na thread do Qt, então o teste faz o pedido HTTP numa thread e roda `app.processEvents()` enquanto espera (ver `tests/engine/test_web_server.py`). Os testes do motor trocam os workers por falsos (`tests/engine/conftest.py`) e a Lixeira por uma lista: nenhum teste manda nada para a Lixeira de verdade.
- Remover playlist e esvaziar a lixeira interna mandam para a Lixeira do macOS (`engine/trash.py`, `QFile.moveToTrash`); nunca `shutil.rmtree`.
- O índice de uma música não é estável: uma nova análise reordena a playlist. Rota nova que mexe numa música recebe a `key` do `Track` e passa por `Engine._track(playlist, index, key)` (409 `track_moved`); quem muda a lista emite `tracks_changed` (doc 14 §4–5).
- Sinal de um worker (QThread) para o motor chega pela fila do Qt. Depois de `worker.wait()`, o que ele emitiu ainda não foi aplicado: processe a fila (`QCoreApplication.sendPostedEvents()`) antes de gravar, como faz o `Engine.shutdown`.
- Servidor falso (`tests/web/mock_server.py`): a conexão é reaproveitada (HTTP/1.1), então ele lê o corpo de todo pedido, mesmo nas rotas que não usam; corpo deixado no socket vira lixo no começo do pedido seguinte (dava 501). Consertos que só existem no JS se conferem com `tests/web/verificar_revisao.mjs`.
