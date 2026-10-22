# 06 — Interface, design e idiomas

> Estado atual da UI do CSVMusic v1.7.9, por que ela é do jeito que é, e o plano para redesenhar + traduzir (pt-BR / en / es).
> Referências no formato `arquivo:linha` (v1.7.9). Se as linhas mudarem no upstream, procure pelo nome da função.

---

## 1. Como a UI está organizada hoje

### 1.1 Duas janelas ("modos")

| Modo | Classe | Arquivo | O que é |
|---|---|---|---|
| **Library Mode** (principal desde 1.7.x) | `LibraryModeDialog(QDialog)` 1280×800 | `csvmusic/ui/library_mode.py:1424` | Catálogo persistente de playlists (`library.json`), escaneia, baixa o que falta, sync com aparelhos |
| **Modo legado** | `MainWindow(QMainWindow)` | `csvmusic/ui/main_window.py:317` | Fluxo "uma playlist por vez": escolhe CSV/link → pasta → START → tabela de faixas |

- O app abre no **Library Mode** (`app.py`), que tem um botão no cabeçalho para abrir o modo legado (`library_mode.py:2008`).
- O modo legado tem um botão "LIBRARY MODE" que abre **outro** `LibraryModeDialog` modal por cima (`main_window.py:1564`). Resultado: dá pra ter **duas cópias da biblioteca abertas ao mesmo tempo** gravando o mesmo `library.json` → risco de uma apagar o que a outra salvou.
- A janela principal é um **QDialog**, não uma QMainWindow — por isso não tem barra de menus nativa do Mac nem "Preferências… ⌘,".

### 1.2 Inventário do modo legado (`main_window.py`)

- **Cabeçalho** (:521-550) — logo, "CSVMusic", "CSV playlist downloader".
- **Barra de botões** (:553-597): `LIBRARY MODE`, `RESUME PLAYLIST ▸`, `EQUALIZER ▸`, `SETTINGS ▸`, `TUTORIAL ▸`. Cada "▸" abre um diálogo flutuante (antes eram painéis embutidos; `_create_panel_dialog` :1394 move o painel para dentro de um diálogo).
  - **Tutorial** (:599-682)
  - **Resume Playlist** (:684-772) — origem (URL/CSV) + pasta existente + "Scan Playlist Folder".
  - **Equalizer** (:774-812) — ganho/grave/agudo −15…+15 dB e "Match volume". (Isso **reprocessa o áudio** com ffmpeg.)
  - **Settings** (:814-1078) — fonte legível, caminhos do yt-dlp/ffmpeg, Opus, qualidade MP3 (escala 0–10 invertida para o LAME :1474), "Force download low-confidence", modo iPod antigo (CBR, tamanho de capa), cookies do YouTube (detecta Firefox lendo o banco `moz_cookies` :1984-2012).
- **Origem** (:1092-1157) — os campos "Spotify:" e "CSV:" **existem mas estão escondidos** (:1124-1125) e ainda são usados como "variável" pela lógica (`ed_csv.text()` em `on_start` :2263). O que aparece é "Source:" + "Choose…", que abre uma caixa com 4 botões (:1522).
- **Saída** — pasta, formato (m4a/mp3 com radio buttons desenhados à mão), .m3u8/.m3u/capa, pasta das playlists.
- **START / STOP / CLEAR** (:1212-1224).
- **Tabela** de faixas (4 colunas: #, título+capa, status, "Alternatives") (:1227-1236).
- **Painel "Alternative matches pending"** (:1250-1260, :2683-2745) — para cada música de baixa confiança: combo de candidatos, Paste URL, Download, Listen (abre o navegador), Skip.
- **Rodapé** — texto de log + barra de progresso.

### 1.3 Outras telas
- `spotify_api_test.py` — assistente de 4 páginas para login na API do Spotify (PKCE).
- `spotify_public_scrape.py` — janela com um navegador embutido (QtWebEngine) que abre a página pública da playlist e **rola a página** para capturar as faixas (ver doc 05 — é aqui que mora o travamento em playlists grandes).
- `youtube_login.py` — abre um Firefox com perfil dedicado para você logar no YouTube e importa os cookies quando fecha.
- `youtube_popup.py` — login do Google num navegador embutido (experimental).
- `device_sync.py` — sincronizar com aparelhos (ver doc 07).

---

## 2. Por que ela é "feia e estranha" (e por que o autor fez assim)

| O que você vê | Por que provavelmente é assim | O que fazer |
|---|---|---|
| Visual de **Windows 95**, Comic Sans, fonte de **fita VHS** (VCR OSD Mono) | **Escolha estética intencional**: nostalgia, combinando com o público de iPod clássico. É a "cara" do app. | Ter temas: "Clássico (retrô)" continua existindo como opção; padrão vira um tema moderno claro/escuro. |
| **Três fontes diferentes** (VCR no legado, Comic no Library Mode, Segoe se "texto legível") | Crescimento orgânico; "Comic Sans MS" está **fixo 39 vezes** no `library_mode.py` | Fonte vem do tema. Padrão = fonte do sistema (SF Pro no Mac). |
| **Sem modo escuro** | Proposital (`theme.py:77-79`): forçar paleta clara evitou texto preto em fundo preto no Mac/Linux (changelog 1.7.7 cita isso). | Implementar escuro direito via tokens de cor, seguindo o sistema. |
| Cores **escritas na mão** em ~80 lugares (`setStyleSheet` por widget) | Um dev só, cada tela feita isolada | Um "design system": tokens + uma folha de estilo única. |
| **Tudo ~15% menor no Mac** | `_px()` (`main_window.py:1304-1310`) divide o DPI por 96; no Mac o Qt reporta 72 → escala 0,75 (limitada a 0,85). Herança do Qt5/Windows. | Remover `_px`; Qt 6 já trata telas Retina. |
| Ícones **desenhados por código** (`library_mode.py:209-466`) | Evitar gerenciar arquivos de ícone e licenças | Ícones SVG (Lucide ou Phosphor, licença MIT). |
| Painéis que viram **janelas flutuantes** | Eram painéis embutidos; viraram janelas para não espremer a tabela | Barra lateral ou abas; Preferências numa janela própria (⌘,). |
| Cor da linha decidida pelo **texto** do status (`startswith("Done")`, :2531-2546) | Rápido de fazer | Estados como enum (pré-requisito de tradução, ver §4). "Skipped" e "Queued" hoje têm a **mesma cor** amarela. |
| `QThread.terminate()` ao fechar (`main_window.py:3093-3098`) | Garantir que a janela feche | Cancelamento cooperativo + matar o processo do yt-dlp. `terminate()` pode deixar arquivos pela metade e processos órfãos. |
| Configurações gravadas **a cada tecla** (`main_window.py:868, 888, 1386`) e sem escrita atômica (`core/settings.py:65-82`) | Simplicidade | Gravar com atraso de 300 ms, escrita atômica (arquivo temporário + `os.replace`), backup `.bak`. Hoje, se a leitura falhar, retorna `{}` e **a próxima gravação apaga todas as suas configurações**. |
| No Windows o app **espera 1 s à toa** ao abrir (`app.py:47-57`) | Defesa contra uma janela Tk antiga que nunca aparece mais | Remover o loop. |

---

## 3. Redesign — opções e recomendação

### Opção A — continuar em PySide6 Widgets, com design system de verdade ⭐ recomendado
1. `csvmusic/ui/design/tokens.py`: dataclasses com cores, espaçamentos, raios, tipografia, para cada tema (`light`, `dark`, `retro`).
2. `csvmusic/ui/design/qss.py`: gera **uma folha QSS única** aplicada ao `QApplication`.
3. Variantes por propriedade, não por `setStyleSheet`:
   ```python
   btn.setProperty("variant", "primary")
   # QSS: QPushButton[variant="primary"] { background: {accent}; color: {on_accent}; }
   ```
4. Seguir o tema do sistema: `QGuiApplication.styleHints().colorScheme()` + sinal `colorSchemeChanged` (Qt 6.5+, o projeto usa 6.8.3).
5. Ícones SVG recoloridos pelo tema.
6. Remover `_px`.
7. Library Mode vira **QMainWindow** com barra de ferramentas e menu nativo; **aposentar o modo legado** (duplica fluxos com o Library Mode).

**Prós:** reaproveita toda a lógica e o QtWebEngine (que o importador do Spotify usa); empacotamento continua igual; dá pra migrar tela por tela. **Contras:** QSS é limitado para animações/sombras.

### Opção B — PySide6 + QML (Qt Quick)
UI declarativa, animações, listas grandes mais rápidas, tradução mais limpa (`qsTr`). Mas é reescrever ~7 mil linhas de UI e aprender QML. Bom como **evolução** depois: dá pra embutir telas QML dentro de Widgets (`QQuickWidget`) uma a uma.

### Opção C — Tauri/Electron com Python por trás
UI web moderna (React/Svelte), mas: dois runtimes, comunicação entre eles (HTTP local/JSON-RPC), o importador do Spotify via QtWebEngine teria que ser reescrito (Playwright ou WKWebView), assinatura no Mac mais chata, Electron +150 MB. **Não recomendo para quem está sozinho.**

### Esboço de telas do novo app

```
┌──────────────────────────────────────────────────────────────────────┐
│  CSVMusic                                    [⟳ Sincronizar tudo] ⚙ │
├───────────────┬──────────────────────────────────────────────────────┤
│ 🔍 Buscar     │  Out Of Time Man                       [⟳] [⋯]       │
│               │  1.180 de 1.224 baixadas · 12 revisar · 3 falharam  │
│ PLAYLISTS     │  ████████████████████████████████░░  96%             │
│ ● Out Of Time │  Fila: 44 · ritmo normal · termina ~10:40           │
│ ○ Rock BR     ├──────────────────────────────────────────────────────┤
│ ○ Treino      │  #   Música                      Status              │
│               │  1   Kodak Black — MoshPit        ✓ Baixada          │
│ ─────────     │  7   Blur — Country House         ⚠ Revisar (0.59)   │
│ ⚠ Revisar (12)│  12  Slightly Stoopid — Bandelero ↓ Baixando 43%     │
│ ✕ Falhas (3)  │  13  …                            · Na fila          │
│ 📊 Diagnóstico│                                                      │
├───────────────┴──────────────────────────────────────────────────────┤
│ ▶ Ativo · próximo check automático em 5h 12min        [Pausar]       │
└──────────────────────────────────────────────────────────────────────┘
```

- **Barra lateral**: playlists + filas especiais (Revisar, Falhas, Diagnóstico).
- **Tela "Revisar"**: candidatos com capa, canal, duração, nota e botão ▶ para ouvir 15 s ali mesmo.
- **Preferências** (⌘,): Geral (pasta, formato, padrão de nome), Download (ritmo, cookies), Tags (letras, ReplayGain), Agendamento, Idioma, Aparência (Sistema/Claro/Escuro/Clássico).

---

## 4. Idiomas (pt-BR, en, es)

### 4.1 Situação atual
**Zero suporte.** Nada de `tr(`, `QTranslator`, `gettext`, `QLocale`. Aproximadamente **680 lugares** com texto em inglês: ~252 em `main_window.py`, ~311 em `library_mode.py`, ~51 em `device_sync.py`, ~33 em `spotify_api_test.py`; mais textos vindos dos workers (`workers.py:290-298`) e mensagens do core (avisos do YouTube, preflight).

**Bloqueios técnicos que precisam ser resolvidos antes:**
1. Lógica baseada em texto (cor da linha por `startswith`) — traduziu, quebrou.
2. Telas montadas num `__init__` gigante (~940 linhas em `main_window.py:318-1263`), sem função para "re-escrever os textos".
3. HTML com texto no código (`library_mode.py:1390-1404`).
4. Números/durações formatados à mão.
5. Larguras fixas (`setFixedWidth(self._px(78))` etc.) — português e espanhol são 20-30% mais longos que inglês.
6. A fonte VCR OSD Mono pode não ter ç/ã/é.

### 4.2 Plano recomendado (híbrido, simples para quem está sozinho)

**Passo 0 — estados como código, não texto.**
```python
class TrackState(Enum):
	QUEUED = "queued"; SEARCHING = "searching"; DOWNLOADING = "downloading"
	TAGGING = "tagging"; DONE = "done"; EXISTING = "existing"; REVIEW = "review"
	SKIPPED = "skipped"; FAILED = "failed"; DUPLICATE = "duplicate"
```
Workers emitem `(linha, TrackState, params: dict)`. A UI escolhe cor/ícone/texto pelo estado. Erros do core viram exceções com `code` + `params`.

**Passo 1 — dicionário JSON para os textos.**
```
csvmusic/i18n/__init__.py     # t(chave, **params), set_language(), sinal language_changed
csvmusic/i18n/locales/en.json
csvmusic/i18n/locales/pt_BR.json
csvmusic/i18n/locales/es.json
```
```json
{
  "track.state.done": "Baixada → {file}",
  "library.summary": {"one": "{n} música", "other": "{n} músicas"},
  "youtube.throttle.warning": "O YouTube começou a limitar as requisições. Diminuindo o ritmo."
}
```
`t("library.summary", n=3)` escolhe `one`/`other` (pt, en, es só precisam dessas duas formas). Fallback para `en` quando faltar a chave.

**Passo 2 — `QTranslator` só para os textos do próprio Qt** (botões "Cancel/OK", diálogos de arquivo): carregar `qtbase_pt_BR.qm` de `QLibraryInfo.path(QLibraryInfo.TranslationsPath)`.

**Passo 3 — teste automático** que compara as chaves dos 3 JSONs e confere que os `{placeholders}` batem. Falta de tradução vira teste quebrado, não bug na tela.

**Passo 4 — troca de idioma.**
- Configuração `language`: `system` | `en` | `pt_BR` | `es`. `system` usa `QLocale.system().name()`.
- Versão simples: "aplicar ao reiniciar" + botão "Reiniciar agora".
- Versão completa: cada tela tem `retranslate()` chamada no sinal `language_changed`. Vale a pena fazer isso **junto com o redesign** (as telas novas já nascem com `retranslate()`), não em cima da UI antiga.

**Passo 5 — formatação regional.** `QLocale(lang).toString(1234.5, 'f', 1)` → "1.234,5"; datas com `QLocale.ShortFormat`; tamanhos com `QLocale.formattedDataSize()`.

**Alternativa "oficial" (Qt Linguist):** `self.tr("...")` + `pyside6-lupdate` → `.ts` → `pyside6-linguist` → `pyside6-lrelease` → `.qm`. Melhor ferramenta visual, mas o core (Python puro) não usa Qt, e o `lupdate` não extrai f-strings. Para este projeto o JSON é mais prático.

> Dica para o Claude Code: peça "extraia todas as strings visíveis de `<arquivo>` para `en.json` com chaves hierárquicas e traduza para pt_BR e es" — **um arquivo por vez**, rodando o teste de chaves no final.

---

## 5. Decisão (22/10/2026): interface web local, direção "Capa ambiente"

Substitui a recomendação da §3. O Gabriel quer usar o app também pelo navegador, só em `localhost`, e achou o visual atual feio demais para reaproveitar.

- **Interface nova em web, servida localmente**, com todas as funções do Library Mode (lista em §1 e no inventário de `library_mode.py`). A janela Qt continua funcionando até a web cobrir tudo; depois é aposentada.
- **Texto todo em português do Brasil.**
- **Direção visual 3, "Capa ambiente"**, escolhida entre três propostas:
  - barra lateral com as playlists (mosaico 2×2 das quatro primeiras capas, como o Spotify faz);
  - topo da playlist tingido pela cor mais saturada do mosaico, em degradê vertical até o fundo;
  - lista com #, capa, música/artista, álbum, duração e situação;
  - o download em andamento fica numa barra fixa embaixo, no formato de "tocando agora";
  - tema escuro e claro; no celular a lateral some, as contagens vão ao lado da capa e a situação desce para baixo do artista.
- **Fonte:** Figtree. **Ícones:** Lucide.
- **Amarelo de destaque aprovado (22/10/2026):** `--acc: #f0c03a` com texto `#1c1a10` por cima; no tema claro, texto amarelo em `#7d5f00` (contraste). O Gabriel elogiou: não trocar sem ele pedir.
- **Cores conferidas** (contraste ≥ 4,5:1 em todos os pares de texto). Música desmarcada apaga só a capa; o texto fica cinza legível.
- **Referência:** `../referencia-design/d3-dark.html` e `d3-light.html`, fora do repositório porque usam capas reais. Prints em `../revisao/`.
