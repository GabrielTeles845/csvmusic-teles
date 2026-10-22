# 11 — Prompts prontos para o Claude Code

> Copie e cole na sessão do Claude Code (aberta na raiz do fork). Um prompt por vez. Leia o plano que ele propõe antes de aprovar.
> Dica: aperte **Shift+Tab** até aparecer "plan mode" para ele planejar sem mexer em nada.

---

## Primeira sessão

```
Leia o CLAUDE.md e os documentos em docs/fork/ (comece pelo README.md e depois
03, 04, 05 e 07). Resuma a arquitetura em até 15 linhas, rode `python -m pytest -q`
e me diga quantos testes passam e quais falham. Não altere nenhum arquivo ainda.
```

## Fase 0 — identidade do fork

```
Fase 0.4 do docs/fork/10-roadmap.md: faça o fork rodar ao lado do CSVMusic original
sem compartilhar dados. Troque o nome da pasta de configurações para "CSVMusicTeles"
(core/settings.py), desligue o verificador de atualização (core/update_check.py) por
enquanto, troque o bundle_identifier no CSVMusic.spec para com.teles.csvmusic e
mude a versão para 1.7.9+teles.0 onde os testes exigirem consistência. Ajuste os
testes afetados. Mostre o diff antes de commitar.
```

```
Crie .github/workflows/ci.yml que rode `python -m pytest -q` em macos-latest com
Python 3.12 a cada push e pull request. Use `pip install -e . pytest`.
```

## Fase 1 — consertos (um por vez)

```
Item 1.1 do roadmap. Leia docs/fork/04-busca-download-e-tags.md §2.2 e §2.3a.
Implemente split_title em ytmusic_match.py para remover sufixos com hífen do Spotify
(" - 2012 Remaster", " - Remastered 2011", " - Radio Edit", " - Live at ...",
" - Mono", " - From ...", " - 2009 Mix") e (feat./ft./featuring/with ...), usando o
núcleo tanto nas queries quanto no _score, e movendo convidados do feat para os
artistas. Escreva testes, incluindo o caso real "Country House - 2012 Remaster" / Blur
que hoje dá 0.59 e deve passar de 0.8. Rode todos os testes.
```

```
Item 1.7 do roadmap (docs/fork/04 bug 1 e 2): detect_youtube_risk nunca vê
"Sign in to confirm you're not a bot" porque _summarize_tool_output reescreve a
mensagem antes. Faça a detecção no stderr cru dentro de _run_ytdlp_detail, propague
uma exceção tipada YouTubeRiskError e pare o laço de tentativas no primeiro sinal de
risco. Escreva um teste que teria pego esse bug.
```

```
Itens 1.10 e 1.11 do roadmap. _cleanup_outputs hoje apaga base.* de qualquer
extensão (apaga o mp3 antigo ao trocar para m4a). Restrinja a temporários conhecidos
e ao formato atual. E torne a escrita atômica: baixar/processar em <base>.<fmt>.partial,
gravar tags, depois os.replace para o nome final. Garanta que plan_track_outputs nunca
considere um .partial como baixado. Testes para os dois.
```

```
Item 1.15 e 1.16 do roadmap (docs/fork/07 §3.3.1 e §3.3.2): gravar faixas puladas
na biblioteca com estado not_found_on_youtube, motivo e data, e excluir desativadas da
contagem de missing em library_status. Corrija o teste que hoje espera o comportamento
errado. Mostre na UI o motivo do pulo.
```

```
Item 1.21 do roadmap (docs/fork/05 §4.3 e §4.4 passo 9): ao fechar o Library Mode
durante uma análise, marcar scan_cancelled=True; e em merge_playlist_scan, quando a
análise vier incompleta, não remover faixas antigas cujas posições caíram em buracos.
Testes.
```

```
Item 1.22 do roadmap: o leitor do Spotify (ui/spotify_public_scrape.py) descarta a
duração. Extraia o "m:ss" do texto de cada linha no _CAPTURE_SCRIPT, preserve a
duração do embed para as posições 1–100 em _baseline_finished e leve duration_ms até
a biblioteca. Testes com HTML de exemplo.
```

```
Item 1.23 do roadmap (docs/fork/05 §3.6): o CSV "musicas_curtidas_spotify.csv" com
cabeçalho "#";"Track Name";"Artist Name";"Álbum";"Adicionada em";"Duração";"Link"
(separador ; e BOM) falha. Torne csv_import robusto: detectar separador com
csv.Sniffer e escolher a leitura com mais colunas reconhecidas, remover acentos dos
cabeçalhos (NFKD), aceitar nomes em pt/es (Faixa, Música, Artista, Álbum, Duração,
Link, Pista, Canción...), converter "Duração" mm:ss para duration_ms e extrair o id do
Spotify da coluna Link. Considere trocar pandas pelo módulo csv. Testes com esse
cabeçalho exato.
```

### Duração (doc 13)

```
Leia docs/fork/13-duracao-das-musicas.md. Implemente os itens 1.27 e 1.28 do roadmap:
(1) csv_import aceita a coluna de duração em pt/en/es ("Duração", "Duration (ms)"...)
nos formatos m:ss, h:mm:ss, segundos e ms; m:ss vira segundos*1000+500 com
duration_precision_s=1; guarde duration_source="csv". (2) Crie
csvmusic/tools/fill_durations.py que lê o CSV, casa pelo id do Spotify da coluna Link
com o sp_id da biblioteca, preenche só duration_ms == 0, faz backup do library.json
antes e recusa rodar se o app estiver aberto. Testes sem rede para tudo. Mostre o
plano antes de mexer.
```

```
Itens 1.29 e 1.30 do roadmap (docs/fork/13 §4.2-4.4): quando a duração é confiável,
use a tabela nova de d_score em ytmusic_match._score (bônus para Δ<=2s), mande
candidatos fora da tolerância para options com flag duration_mismatch em vez de
descartar (não podem contar como busca vazia), e depois do download meça a duração
real com mutagen: >10s de diferença rejeita e tenta o próximo candidato. Testes com
o caso do Blur (docs/fork/04 §1) e com um clipe +35s contra o "song" exato.
```

```
Item 1.25 do roadmap: settings.py grava sem atomicidade e, se a leitura falhar,
devolve {} e a próxima gravação apaga tudo. Faça escrita atômica (tempfile + os.replace),
backup settings.json.bak, log do erro em vez de engolir, e debounce de 300 ms nas
gravações disparadas por textChanged/sliders no main_window e library_mode.
```

## Fase 2 — leitor do Spotify

```
Fase 2 do roadmap. Leia com atenção docs/fork/05-importacao-de-playlists.md §1.5 e §4
inteiros. Proponha (plan mode) a nova máquina de estados do SpotifyPublicScrapeDialog
baseada em posições, hidratação da viewport, passo <= 0.8x, rolagem para alvo
absoluto num único scroller, fase de backfill, watchdog do runJavaScript e total por
aria-rowcount. Antes de implementar, crie um teste com uma página HTML local que
simula uma lista virtualizada carregando blocos de 50 com atraso aleatório, e mostre
que o código atual falha nele.
```

## Fase 3 — SQLite e reconhecimento

```
Fase 3 do roadmap. Leia docs/fork/04 §4 e docs/fork/07 §3.5. Proponha o esquema
SQLite final unificando as duas propostas (estado por pasta de saída + índice de
arquivos com pastas extras de reconhecimento), a estratégia de migração do
library.json (com backup) e a ordem de implementação em commits pequenos. Não
implemente ainda.
```

```
Implemente o índice de arquivos (fase 3.4): varredura incremental com os.scandir,
cache por (size, mtime_ns), leitura de tags com mutagen em thread, normalização
artista/título como em docs/fork/07 §3.5b camada 4. Adicione nas Settings uma lista
de "pastas para reconhecer (somente leitura)". Mostre o progresso. Testes com uma
pasta temporária de arquivos de áudio gerados no teste.
```

## Fase 4 — pipeline

```
Fase 4 do roadmap. Leia docs/fork/04 §5. Proponha como separar busca e download,
o limitador global (token bucket) compartilhado entre 2–3 downloads, o controlador
AIMD acionado só por sinais reais de bloqueio, e a fila persistente na tabela jobs.
Mantenha o PipelineWorker antigo funcionando atrás de uma opção até o novo estar
estável.
```

## Fase 7 — redesign e idiomas

```
Fase 7.1 e 7.2. Crie csvmusic/ui/design/ com tokens (claro, escuro, clássico) e um
gerador de QSS único aplicado ao QApplication, seguindo o tema do sistema via
styleHints().colorScheme(). Migre primeiro só o cabeçalho e a lista de playlists do
Library Mode para usar propriedades (setProperty("variant", ...)) em vez de
setStyleSheet. Mostre screenshots claro/escuro.
```

```
Fase 7.7. Crie csvmusic/i18n com t(chave, **params), plurais one/other, fallback en,
e locales en/pt_BR/es em JSON. Adicione o teste que compara chaves e placeholders.
Depois extraia as strings de UM arquivo (comece por ui/library_mode.py, só o
_build_ui) para en.json e traduza para pt_BR e es. Carregue também qtbase_<lang>.qm.
```

## Fase 8 — rodar sempre

```
Fase 8. Leia docs/fork/07 §6 e docs/fork/12. Implemente o ícone na barra de menus
com QSystemTrayIcon, setQuitOnLastWindowClosed(False), menu com status/atualizar
agora/pausar/abrir/sair, e a opção de linha de comando --background. Depois o
agendador com intervalo por playlist e horário silencioso.
```

## Manutenção

```
Puxe as mudanças do upstream (git fetch upstream) e me diga o que mudou desde a
v1.7.9, quais arquivos conflitam com o nosso fork e se há correções de YouTube/Spotify
que valem trazer. Não faça merge ainda.
```

```
Rode /code-review nas mudanças desde o último commit na main antes de eu commitar.
```

```
Adicione ao CLAUDE.md a regra: <descreva o que deu errado e como deve ser>.
```
