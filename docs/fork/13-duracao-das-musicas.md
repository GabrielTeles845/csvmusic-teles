# 13 — Duração das músicas: usar para garantir que é a música certa

> Ideia do Gabriel: pegar a duração de cada música, colocar na planilha e usar essa duração na busca do YouTube para ter certeza de que é a música certa.
>
> Resumo: **é a melhor melhoria de precisão que dá para fazer**, e boa parte do caminho já existe no código. O que falta é **a duração chegar até a busca**. Hoje ela se perde no meio do caminho.

---

## 1. Como funciona hoje

O código **já sabe usar duração**, em dois pontos de `csvmusic/core/ytmusic_match.py`:

1. **Corte duro** (`_duration_within_tolerance`, l.122): descarta candidatos com duração muito diferente.
   - Músicas com mais de 45 s: tolerância de **±10%**. Numa música de 4:00, isso aceita de 3:36 a 4:24.
   - Músicas com até 45 s: tolerância de ±8 s.
2. **Nota** (`_score`): a duração vale **35% da nota** (`d_score`).

   | Diferença | d_score |
   |---|---|
   | até 6 s | 1.0 |
   | até 12 s | 0.9 |
   | até 20 s | 0.78 |
   | até 30 s | 0.62 |
   | mais de 30 s | 0.45 |
   | **sem duração** | **0.70 (neutro)** |

**O problema:** quando a música chega sem duração, o corte é desligado ("se um dos lados não tem duração, aceita") e a nota cai num 0.70 neutro. A busca fica só no texto.

### Onde a duração se perde

| Origem | Traz duração? |
|---|---|
| Leitor do Spotify com navegador (o que você usou) | **Não.** O texto "2:57" está na linha da página, mas é descartado (`05 §5 item 12`) |
| CSV | **Só** se a coluna se chamar `Duration (ms)` e estiver em milissegundos. "Duração" com "2:57" é ignorada, e mesmo `Duration (ms)` com "2:57" daria erro e virava 0 (`csv_import.py:182-187` usa `int(...)`) |
| Spotify API, embed, Apple, Deezer, YouTube Music | Sim |

**Nos seus dados:** as 1.124 músicas da biblioteca "Out Of Time Man" estão com `duration_ms = 0`. A playlist inteira está sendo baixada sem filtro de duração.

### A boa notícia: sua planilha já tem tudo

O `musicas_curtidas_spotify.csv` (Desktop) tem a coluna **`Duração`** (`2:57`, `2:44`...) e a coluna **`Link`** com o ID do Spotify. Conferi:

- **1.124 linhas, 1.124 com duração preenchida.**
- **Os 1.124 IDs do `Link` batem com o `sp_id` das 1.124 músicas do `library.json`.**

Ou seja, dá para preencher a duração da biblioteca inteira **sem baixar nada nem consultar nenhum site**: é só cruzar pelo ID.

### O caso do Blur com duração

Refazendo a conta da "Country House - 2012 Remaster" (pulada com 0.59, `04 §1`), agora com a duração certa (d_score 1.0 em vez de 0.7):

`1.0·0.35 + 0.5·0.35 + 1.0·0.25 − 0.08 = 0.695` → **passa** (mínimo 0.60), mesmo sem consertar o sufixo " - 2012 Remaster".

---

## 2. Um ponto importante: o YouTube não pesquisa por duração

Não dá para escrever "Country House 4:01" na busca e o YouTube devolver só vídeos de 4:01. A busca é por texto, e colocar "4:01" na pesquisa **piora** o resultado, porque o número vira palavra.

O YouTube só tem filtro de faixa ("menos de 4 min", "4 a 20 min", "mais de 20 min"), que não ajuda.

**O jeito certo**, e o que este documento propõe:

1. Buscar pelo texto (artista + título), como hoje.
2. Cada resultado já vem com a duração (`duration_seconds`, tanto do YouTube Music quanto do yt-dlp).
3. **Comparar a duração de cada resultado com a da planilha** e usar isso para filtrar e ordenar.
4. **Depois de baixar**, medir a duração do arquivo e confirmar de novo.

Na prática, o efeito é o mesmo que você pensou: só aceita o vídeo se a duração bater.

---

## 3. De onde tirar a duração (em ordem de preferência)

| # | Fonte | Como | Custo |
|---|---|---|---|
| 1 | **Sua planilha** | coluna `Duração` (`m:ss`) ou `Duration (ms)` | zero |
| 2 | **Leitor do Spotify** | ler o `m:ss` de cada linha e o JSON da página (`05 §4`) | zero, já está na página |
| 3 | **Embed do Spotify** pelo ID | `https://open.spotify.com/embed/track/<id>`: o JSON da página tem `duration` em ms. Sem login | 1 requisição por música |
| 4 | **Spotify Web API** | `GET /v1/tracks?ids=...` (50 por vez). Exige Client ID/Secret, que o app já suporta | 23 requisições para 1.124 músicas |
| 5 | **Deezer** (sem chave) | `https://api.deezer.com/search?q=artist:"X" track:"Y"` → `duration` (s) e às vezes `isrc` | 1 por música |
| 6 | **iTunes Search** (sem chave) | `https://itunes.apple.com/search?term=X+Y&entity=song` → `trackTimeMillis` | 1 por música |
| 7 | **MusicBrainz** | por ISRC ou busca; `length` em ms. Limite de 1 req/s | lento |

Regras:
- **Planilha e Spotify mandam.** Deezer/iTunes/MusicBrainz só preenchem o que está vazio, e só aceitam se artista e título baterem bem (podem achar outra versão).
- Guardar **de onde veio** a duração (`duration_source`: `csv`, `spotify`, `deezer`...), para saber o quanto confiar.

### Detalhe: "m:ss" tem erro de até 1 segundo

O Spotify mostra `2:57` para qualquer coisa entre 2:57.000 e 2:57.999. Ao converter `m:ss`, guarde `duration_ms = segundos·1000 + 500` (o meio do intervalo) e marque `duration_precision_s = 1`. A comparação usa ±1 s a mais de folga. Quando vier em ms (API, embed), a precisão é exata.

---

## 4. Como usar a duração na busca (o que mudar)

### 4.1 Leitura da planilha (`core/csv_import.py`)

- Aceitar os nomes: `Duration (ms)`, `Duration`, `Duração`, `Duracao`, `Duración`, `Tempo`, `Length`, `Time`.
- Aceitar os formatos: `177000` (ms), `177` (s; numa coluna sem unidade no nome, a coluna inteira decide: mediana dos números acima de 10 000 é ms, senão s, para uma música de 1 h+ em segundos não virar 3,6 s), `2:57`, `1:02:57`, `2.57`/`2,57` só se a coluna for de duração e não houver outra leitura possível.
- Junto com o CSV robusto do roadmap (separador `;`, BOM, acentos, colunas em pt/es: item 1.23).
- Tirar o ID do Spotify do `Link` (`open.spotify.com/track/<id>`) para `sp_id`.

### 4.2 Nota e filtro (`core/ytmusic_match.py`)

Com duração **confiável** (da planilha ou do Spotify):

| Diferença | Hoje | Proposta |
|---|---|---|
| até 2 s | 1.0 | **1.0 + bônus de 0.05** (versão exata) |
| até 6 s | 1.0 | 0.95 |
| até 12 s | 0.9 | 0.8 |
| até 20 s | 0.78 | 0.6 |
| até 30 s | 0.62 | 0.4 |
| mais que isso | 0.45 | 0.2 |

- Isso separa sozinho: versão ao vivo, extended, radio edit, remaster com faixa escondida, "slowed + reverb", sped up, clipe com introdução de 30 s.
- **Clipes oficiais** costumam ter introdução/final e ficar 10–40 s mais longos. Com duração confiável, o resultado "song" (áudio oficial do YouTube Music) com duração exata ganha naturalmente do clipe.
- **Corte duro:** manter ±10%, mas quem cai fora **não some**: vai para a lista de alternativas marcado como `duration_mismatch` (ligado ao `04 bug 4`, para não virar "busca vazia" e abortar o lote).
- **Sem duração:** continua neutro como hoje, mas a música entra numa fila "sem duração" para o enriquecimento (seção 5).

### 4.3 Se nenhum candidato bater na duração

Antes de desistir:
1. Rodar as variantes extras de busca (sem sufixo de remaster, sem "feat.").
2. Buscar com o filtro `videos` além de `songs` (alguns áudios só existem como vídeo de canal "- Topic").
3. Se ainda nada estiver dentro de ±3 s, **não baixar o "melhor errado"**: marcar como "Revisar" com os 5 candidatos e suas durações na tela.

### 4.4 Conferir depois de baixar

Depois de baixar e converter, medir a duração real do arquivo (`mutagen` → `info.length`, ou `ffprobe`):

- **Diferença ≤ 3 s** (≤ 4 s com `m:ss`): ok, grava `duration_verified = true`.
- **Entre 3 e 10 s**: ok, mas marca para revisão (pode ter silêncio no fim).
- **Mais de 10 s ou arquivo muito curto**: **rejeita** (download cortado, versão errada) e tenta o próximo candidato. Isso também resolve o `04 bug 8` (arquivo pela metade contado como baixado).

### 4.5 Gravar no arquivo e na biblioteca

- Gravar em `library.json` (ou no SQLite da fase 3): `duration_ms`, `duration_source`, `duration_precision_s`, `downloaded_duration_ms`, `duration_verified`.
- Gravar a duração esperada numa tag `TXXX:CSVMUSIC_EXPECTED_DURATION`, para o rescan da biblioteca (`07 §4`) reconhecer o arquivo em outra pasta mesmo sem o nome igual (artista + título + duração ±3 s).

### 4.6 Mostrar na tela

- Coluna "Duração" na lista de músicas: `2:57`.
- Na revisão de candidatos: `2:57 (planilha) · 2:58 (vídeo) ✓` ou `2:57 · 3:34 ⚠ +37 s`.
- Contador no resumo: "1.124 com duração · 0 sem".

---

## 5. Preencher a duração do que já existe

### 5.1 Para a sua biblioteca atual (resolve hoje as 1.124)

Um comando que lê o CSV e preenche a biblioteca pelo ID do Spotify:

```bash
python -m csvmusic.tools.fill_durations \
  --csv ~/Downloads/musicas_curtidas_spotify.csv \
  --library ~/Library/Application\ Support/CSVMusic/library.json
```

- **Faz backup** do `library.json` antes (`library.json.bak-AAAAMMDD-HHMMSS`).
- Só preenche onde está 0. Não mexe em mais nada.
- Mostra no fim: quantas preenchidas, quantas sem par no CSV.
- Não roda com o app aberto (o app sobrescreve a biblioteca ao fechar): checar se o app está rodando e recusar.

> **Atenção (Windows, agora):** não edite o `library.json` enquanto o CSVMusic original está baixando. Faça isso só no fork, no Mac, ou com o app fechado e com backup.

### 5.2 Enriquecimento automático (para playlists futuras)

Botão "Completar durações" e etapa automática depois de importar: para cada música com `duration_ms = 0`, tentar as fontes 3 → 7 da tabela da seção 3, com cache em disco (`durations_cache.json` ou tabela no SQLite, chave `sp_id` ou `isrc`), respeitando limites de requisição.

### 5.3 Exportar a planilha com duração

"Exportar playlist como CSV" com as colunas: `#`, `Track Name`, `Artist Name`, `Album`, `Duration (ms)`, `Duração`, `ISRC`, `Spotify ID`, `Link`, `Status`, `Arquivo`, `Duração do arquivo`, `Diferença (s)`.

Assim dá para abrir no Numbers/Excel e ver de cara quais downloads têm duração suspeita.

---

## 6. Testes (sem rede)

- `csv_import`: `2:57` → 177500 ms; `1:02:57`; `177000`; coluna `Duração` com BOM e `;`; célula vazia → 0.
- `_score`: Δ 1 s vence Δ 25 s com o mesmo texto; clipe de +35 s perde do "song" exato.
- Candidato fora de ±10% vai para `options` com `duration_mismatch` e **não** conta como busca vazia.
- Verificação pós-download: arquivo falso de 60 s para uma música de 177 s → rejeitado.
- `fill_durations`: cria backup, preenche só zeros, não mexe em outros campos, recusa se o app estiver aberto.
- Caso real do Blur: com duração, nota ≥ 0.6.

---

## 7. Ordem de implementação

1. **CSV lê a coluna `Duração`** (junto com o item 1.23 do roadmap). → já resolve playlists vindas de planilha.
2. **Leitor do Spotify guarda a duração** (item 1.22).
3. **`fill_durations`** para a biblioteca atual.
4. **Nota mais rígida + `duration_mismatch`** quando a duração é confiável.
5. **Verificação depois do download.**
6. Enriquecimento automático, colunas na tela, exportação.

No roadmap: itens **1.27 a 1.30** e **4.x** (ver `10-roadmap.md`). Prompt pronto em `11-prompts-prontos.md`, seção "Duração".
