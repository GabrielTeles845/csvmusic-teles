# 09 — Ideias extras (além de consertar o que existe)

Sugestões minhas para transformar o fork em algo bem melhor que o original. Cada ideia tem **por que**, **como** e **esforço** (P = pequeno, M = médio, G = grande). As mais valiosas estão primeiro.

---

## A. Arquitetura e robustez

### A1. Estado em SQLite por pasta de saída (G) ⭐ base de quase tudo
**Por quê:** hoje o app decide o que já foi baixado olhando se existe um arquivo com o nome exato. Isso quebra com numeração, troca de formato, renomeação. Também perde o resultado das buscas no YouTube entre execuções.
**Como:** um arquivo `.csvmusic/state.sqlite` dentro da pasta de música (ou no diretório de dados do app), com tabelas:
- `tracks` (chave estável: ISRC ou `artista_normalizado|titulo_normalizado|duração_arredondada`, título, artistas, álbum, duração…)
- `matches` (track_key → videoId, score, fonte, data, escolhido_manualmente: bool)
- `files` (track_key → caminho, formato, tamanho, mtime, hash parcial, tags lidas)
- `playlist_entries` (playlist_id, posição, track_key) — permite renomear/renumerar sem baixar de novo
- `jobs` (fila persistente: track_key, estado, tentativas, último erro, próximo_retry)
**Resultado:** retomar de verdade, mesmo se o app fechar no meio; buscas não se repetem; numeração muda só via renomear.

### A2. Separar o app em "motor" + "interface" (M) ⭐
**Por quê:** hoje boa parte da lógica vive dentro das telas Qt (`main_window.py` tem 3 mil linhas, `library_mode.py` 3,6 mil). Isso dificulta testar, rodar em segundo plano e trocar o visual.
**Como:** um pacote `csvmusic/engine/` com uma API simples (`importar_playlist`, `planejar`, `sincronizar`, eventos de progresso). A UI só assina eventos. O mesmo motor serve para:
- a janela,
- um **modo linha de comando** (`csvmusic sync --all`),
- um **serviço em segundo plano** (menu bar no Mac).

### A3. Modo linha de comando / headless (P–M)
`csvmusic sync <link-ou-csv> --out ~/Music/CSVMusic --format m4a`
`csvmusic sync --library` (todas as playlists salvas)
`csvmusic status` (quantas faltam, falhas)
Permite agendar com `launchd` no Mac sem janela aberta e facilita testes.

### A4. Fila persistente com retry inteligente (M)
Falhou? Vai para `jobs` com `próximo_retry = agora + backoff exponencial (5 min, 30 min, 2 h, 12 h)`. Erro "vídeo indisponível" → tenta o próximo candidato. Erro de bloqueio → pausa a fila inteira por X minutos em vez de desistir.

### A5. Logs estruturados e tela de diagnóstico (P)
Log em JSON-lines com rotação (o `app.log` atual cresce para sempre). Uma tela "Diagnóstico" que mostra: versão do yt-dlp, ffmpeg encontrado?, último bloqueio do YouTube, taxa de acerto da busca, botão "exportar log anonimizado".

---

## B. Biblioteca e arquivos

### B1. Cada música salva uma vez só; playlists viram referências (M) ⭐⭐
**Por quê:** se a mesma música está em 5 playlists, hoje ela pode ser baixada 5 vezes (uma pasta por playlist). Com playlists grandes isso é muito espaço e muito tempo de download à toa, além de mais risco de bloqueio.
**Como:** layout opcional
```
Musicas/
  Biblioteca/
    Artista/Álbum/01 - Título.m4a
  Playlists/
    Out Of Time Man.m3u8      ← só aponta para os arquivos acima
```
Manter o layout atual ("uma pasta por playlist") como opção, porque tem gente que copia a pasta da playlist direto para pendrive/carro.

### B2. Escanear a pasta e reconhecer o que já existe (M) ⭐
Ler tags de todos os arquivos de áudio da pasta (mutagen), indexar no SQLite (com cache por `mtime+tamanho` — só relê o que mudou) e casar com a playlist por: ISRC → artista+título normalizados → artista+título "fuzzy" + duração ±3 s. Resolve o "missing" falso. Detalhes no doc 07.

### B3. Ações de arrumação (P–M)
- "Renomear tudo segundo o padrão atual" (com prévia antes/depois).
- "Encontrar duplicatas" (mesmo áudio em lugares diferentes).
- "Arquivos órfãos" (estão na pasta mas não em nenhuma playlist) → mover para `_orfas/`, nunca apagar direto.
- Padrões de nome configuráveis: `{artist} - {title}`, `{position:04d} - {artist} - {title}`, `{album_artist}/{album}/{track:02d} {title}`.

### B4. Detectar mudanças da playlist (P)
Ao sincronizar, mostrar "+12 novas, −3 removidas, 2 mudaram de posição". Músicas removidas da playlist: opção de manter, mover para `_removidas/` ou apagar.

---

## C. Qualidade da busca e do áudio

### C1. Verificação por impressão digital de áudio (M) ⭐
**Por quê:** a nota de busca compara texto e duração. Às vezes baixa um cover, uma versão ao vivo ou um "slowed".
**Como:** `brew install chromaprint` (fornece `fpcalc`). Depois de baixar, gerar a impressão digital e consultar o **AcoustID** (grátis, precisa de chave de API) → retorna o ID do MusicBrainz e o título/artista reconhecidos. Se não bater com o esperado, marca "suspeito" e tenta o próximo candidato. Bônus: dá para pegar ISRC, ano, álbum corretos do MusicBrainz.

### C2. Fila de revisão manual com prévia (M)
Músicas de baixa confiança vão para uma tela "Revisar": mostra os 5 melhores candidatos com capa, canal, duração, nota, e um botão ▶ que toca 15 s da prévia (via URL de stream do yt-dlp ou embed). Você escolhe uma vez; a escolha fica salva no SQLite e nunca mais é perguntada.

### C3. Lista de bloqueio e preferências (P)
- Bloquear um `videoId` ("nunca baixe esse").
- Bloquear canais (ex.: canais de "nightcore").
- Preferir versão "explícita" vs "clean".
- Preferir "Topic"/YouTube Music sobre vídeo-clipe (clipes têm intros e barulhos).

### C4. Letras (P)
**LRCLIB** (`https://lrclib.net/api/get?artist_name=…&track_name=…&duration=…`) é grátis e sem chave. Salvar letra sincronizada como `.lrc` ao lado do arquivo e/ou embutir (USLT/SYLT em mp3, `©lyr` em m4a). Players como Poweramp, foobar, Plexamp mostram letra sincronizada.

### C5. ReplayGain em vez de alterar o áudio (P)
Hoje existe normalização de volume (ffmpeg loudnorm), que **reprocessa** o áudio. Alternativa melhor: calcular e gravar **tags ReplayGain** (`rsgain` via brew) — o volume fica igual entre músicas e o arquivo original não é mexido.

### C6. Escolha de formato consciente (informação)
O áudio do YouTube vem em **Opus (~130–160 kbps)** ou **AAC m4a (~128 kbps)**. Converter para MP3 é perda em cima de perda e não melhora nada. Recomendação na UI: "m4a (melhor compatibilidade, inclusive Apple Music/iPhone)" ou "opus (melhor qualidade por tamanho, sem suporte no Apple Music)". MP3 só para aparelhos antigos (som de carro).

---

## D. Tags completas

### D1. Tags que faltam (P) ⭐
- **Album Artist** (essencial para players agruparem álbuns).
- **Vários artistas como lista** (ID3v2.4 permite vários valores; Vorbis/Opus: um campo `ARTIST` por artista; MP4: lista). Manter também a versão "A, B" para players antigos (`ARTISTS` vs `ARTIST`).
- **ISRC**, **gênero**, **total de faixas**, **data completa**, **compilação**, **explícito** (`rtng` em m4a), **compositor** se disponível.
- **Capa em maior resolução** (Spotify fornece 640×640; a capa do YouTube às vezes é um thumbnail de vídeo cortado).
- Comentário com a origem: `source=youtube videoId=xxxx` (útil para auditar e para o "retomar").

### D2. Enriquecimento opcional via MusicBrainz (M)
Com ISRC → MusicBrainz → data de lançamento correta, gravadora, gêneros. Respeitar o limite de 1 requisição por segundo deles.

---

## E. Rodar sempre / Mac

### E1. App de barra de menus no Mac (M) ⭐
Ícone na barra de menus (`QSystemTrayIcon` funciona no Mac). Menu: "Sincronizar agora", "Pausar", "Abrir janela", "Última sync: há 2 h — 3 novas". Opção "Abrir ao iniciar sessão" (LaunchAgent em `~/Library/LaunchAgents/` ou `SMAppService` quando empacotado). Notificações nativas quando terminar ("12 músicas novas em Out Of Time Man").

### E2. Agendamento (P)
"Verificar playlists a cada 6 h", "só entre 1 h e 7 h da manhã" (horário silencioso, sem competir com sua internet), "só no Wi-Fi", "só na tomada" (MacBook).

### E3. Importar direto no app Música da Apple (P–M)
No Mac dá pra adicionar arquivos à biblioteca do **Música** via AppleScript/JXA (`osascript`), e criar/atualizar playlists com o mesmo nome. Aí sincroniza com iPhone pelo cabo/Finder. (m4a com tags completas fica perfeito lá.)

### E4. Integração com servidores (P)
Se um dia usar **Navidrome**, **Jellyfin** ou **Plex**: chamar a API de "rescan" depois de cada sync, e exportar playlists `.m3u8` com caminhos relativos compatíveis.

---

## F. Interface

### F1. Redesign completo (G) — ver doc 06
### F2. Idiomas pt-BR / en / es (M) — ver doc 06
### F3. Tela inicial tipo "painel" (M)
Cards por playlist: capa, nome, "1.180 / 1.224 baixadas", barra de progresso, botão sincronizar, última sync, falhas. Um card geral com "fila: 44, ETA 22 min, ritmo: normal/cauteloso".
### F4. ETA real e ritmo visível (P)
Mostrar "≈ 30 s por música → termina por volta de 10:40". E deixar o usuário escolher o ritmo: Rápido / Normal / Cauteloso, com aviso honesto do risco.
### F5. Atalhos e arrastar-e-soltar (P)
Arrastar um CSV ou colar um link (Cmd+V) em qualquer lugar da janela já importa.

---

## G. Qualidade de código

### G1. Ferramentas (P) ⭐
- `ruff` (lint + formatação), configurado para TAB, já que o projeto usa TAB.
- `mypy` ou `pyright` em modo leve nos módulos novos.
- `pre-commit` rodando `ruff` e `pytest -q -x` nos testes rápidos.
- GitHub Actions do seu fork rodando os testes em macOS a cada push.

### G2. Testes com gravações (M)
Gravar respostas reais do YouTube Music/Spotify em arquivos JSON (fixtures) e testar o algoritmo de busca contra elas. Criar um "conjunto de ouro" com ~200 músicas difíceis (remasters, feat., japonês, ao vivo, músicas com mesmo nome) e medir a taxa de acerto antes/depois de cada mudança na busca. **Isso é o que permite melhorar a busca sem medo.**

### G3. Auto-update do yt-dlp (P) ⭐
O YouTube quebra o yt-dlp com frequência. Na inicialização (no máximo 1×/dia): checar a versão mais nova no PyPI e atualizar dentro do venv/app (`pip install -U yt-dlp` ou baixar o binário oficial). Mostrar na tela de diagnóstico.

### G4. Configurações tipadas (P)
Trocar o dicionário solto de configurações por um `dataclass`/`pydantic` com versão de esquema e migração. Evita bugs de "chave não existe" depois de atualizar.

---

## H. Cuidados (pra não dar dor de cabeça)

- **Ritmo x bloqueio:** baixar muito rápido do YouTube pode causar bloqueio temporário do IP ou exigir verificação. O ritmo adaptativo (começar normal, frear só quando houver sinal real) é o meio-termo. Nunca dispare 10 downloads em paralelo.
- **Cookies do navegador:** usar cookies da sua conta Google ajuda contra bloqueio, mas, se o YouTube punir, pune a sua conta. Prefira uma conta secundária.
- **Uso pessoal:** baixar do YouTube vai contra os termos de uso do YouTube. Mantenha o projeto para uso pessoal e não distribua as músicas.
- **Não apagar nada automaticamente** na pasta de música real. Mover para uma pasta de "lixeira" interna e deixar você esvaziar.
