# 12 — Gerar o seu `.app` e deixar rodando sempre no Mac

## 1. Rodar do código (dia a dia de desenvolvimento)

```bash
cd ~/Projetos/csvmusic-teles
source .venv/bin/activate
python -m csvmusic.app                # app completo
python -m csvmusic.library_mode_ui    # só o Library Mode
```

Variáveis úteis para apontar ferramentas específicas:
```bash
export FFMPEG_BIN=/opt/homebrew/bin/ffmpeg
export DENO_BIN=/opt/homebrew/bin/deno
export YTDLP_BIN=$PWD/.venv/bin/yt-dlp
```

## 2. Gerar o `.app` localmente

### 2.1 Pré-requisitos dentro do projeto
O `.app` aberto pelo Finder **não enxerga `/opt/homebrew/bin`** (o PATH do launchd é mínimo). Então ffmpeg e deno precisam ir **dentro** do app:

```bash
mkdir -p resources/ffmpeg/darwin resources/deno/darwin
cp "$(which ffmpeg)" resources/ffmpeg/darwin/ffmpeg
cp "$(which deno)"   resources/deno/darwin/deno
```
> Confira em `csvmusic/core/paths.py` e `js_runtime.py` os nomes exatos de pasta que o app procura (`resources/ffmpeg/<plat>/`, `resources/deno/<plat>/`) e ajuste se forem diferentes.
> ⚠️ O ffmpeg do Homebrew é dinâmico (depende de bibliotecas em `/opt/homebrew`). Funciona na **sua** máquina. Para levar para outro Mac, use o build estático como o CI faz (`release.yml`, job build, passo do FFmpeg macOS).

### 2.2 Ícone
```bash
# a partir de um PNG 1024x1024 (ex.: resources/icon_square.png ou um seu)
mkdir icon.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s resources/icon_square.png --out icon.iconset/icon_${s}x${s}.png
  sips -z $((s*2)) $((s*2)) resources/icon_square.png --out icon.iconset/icon_${s}x${s}@2x.png
done
iconutil -c icns icon.iconset -o resources/app.icns
rm -r icon.iconset
```

### 2.3 Build
```bash
pip install pyinstaller
MACOSX_DEPLOYMENT_TARGET=12.0 pyinstaller CSVMusic.spec --noconfirm
codesign --force --deep --sign - dist/CSVMusic.app     # assinatura ad-hoc (local)
open dist/CSVMusic.app
```
Teste rápido sem abrir janela: `dist/CSVMusic.app/Contents/MacOS/CSVMusic --smoke-test` (retorna 0 se ok).

Copie para `/Applications` se quiser. Como foi gerado na sua máquina, **não recebe quarentena** do Gatekeeper.

### 2.4 Assinatura de verdade (opcional, US$ 99/ano)
Só necessário para distribuir ou para usar `SMAppService`/notificações nativas com ações. Passos: certificado *Developer ID Application* → assinar de dentro para fora com `--options runtime --timestamp` e entitlements (`com.apple.security.cs.allow-jit`, `allow-unsigned-executable-memory`, `disable-library-validation`, por causa do QtWebEngine e do Deno) → `xcrun notarytool submit … --wait` → `xcrun stapler staple`. Evite `--deep` na assinatura final.

## 3. Deixar rodando sempre

### 3.1 Enquanto o modo "barra de menus" (Fase 8) não existe
Dá para agendar o CLI (Fase 6) com launchd. Exemplo: sincronizar a biblioteca todo dia às 3h.

`~/Library/LaunchAgents/com.teles.csvmusic.sync.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.teles.csvmusic.sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/SEU_USUARIO/Projetos/csvmusic-teles/.venv/bin/python</string>
    <string>-m</string><string>csvmusic</string>
    <string>sync</string><string>--library</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Users/SEU_USUARIO/Library/Logs/CSVMusicTeles/sync.log</string>
  <key>StandardErrorPath</key><string>/Users/SEU_USUARIO/Library/Logs/CSVMusicTeles/sync.err</string>
</dict>
</plist>
```
```bash
mkdir -p ~/Library/Logs/CSVMusicTeles
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.teles.csvmusic.sync.plist
launchctl kickstart -k gui/$(id -u)/com.teles.csvmusic.sync   # rodar agora para testar
launchctl bootout gui/$(id -u)/com.teles.csvmusic.sync        # desligar
```
> Playlists do Spotify precisam do navegador embutido (QtWebEngine). O CLI terá que criar um `QApplication` e um leitor fora da tela (doc 07 §6.1), ou usar a API oficial.

### 3.2 Com o modo barra de menus (Fase 8)
LaunchAgent abrindo o app ao iniciar a sessão:
```xml
<key>ProgramArguments</key>
<array>
  <string>/Applications/CSVMusic.app/Contents/MacOS/CSVMusic</string>
  <string>--background</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
<key>ProcessType</key><string>Interactive</string>
<key>LimitLoadToSessionType</key><string>Aqua</string>
```
- `LSUIElement=true` no `Info.plist` (via `info_plist` no `BUNDLE` do `CSVMusic.spec`) → sem ícone no Dock.
- Com o app assinado de verdade, troque o LaunchAgent por `SMAppService.mainAppService().register()` (aparece em Ajustes › Geral › Itens de Início).
- Durante downloads, evitar App Nap: `NSProcessInfo.processInfo().beginActivityWithOptions_reason_(...)` (pyobjc).

### 3.3 Cuidados com o Mac dormindo
- launchd executa agendamentos perdidos ao acordar (`StartCalendarInterval`).
- Para downloads longos com a tampa aberta: `caffeinate -i -w <pid>` impede o repouso enquanto o processo existir.
- Pasta de músicas em HD externo: verifique se está montado antes de sincronizar (o app deve falhar com mensagem clara, nunca criar a pasta no disco interno por engano).
