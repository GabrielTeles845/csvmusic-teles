# 01 — Preparando o Mac e criando o seu fork

> Objetivo: sair do zero no Mac até ter o CSVMusic original **rodando a partir do código**, num fork seu no GitHub, com o Claude Code pronto pra trabalhar.

---

## 1. Ferramentas básicas

Abra o **Terminal** (Cmd+Espaço → "Terminal").

### 1.1 Xcode Command Line Tools (git, compiladores)

```bash
xcode-select --install
```

Vai abrir uma janela pedindo pra instalar. Aceite. Demora uns minutos.

### 1.2 Homebrew (gerenciador de pacotes do Mac)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

No final ele mostra 2 comandos tipo `echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile`. **Rode os dois.** Depois feche e abra o Terminal de novo e confira:

```bash
brew --version
```

### 1.3 Python, ffmpeg, git, GitHub CLI, Node (pro Claude Code)

```bash
brew install python@3.12 ffmpeg deno git gh node
```

- `python@3.12` → o app é Python + PySide6 (Qt). O projeto fixa `PySide6==6.8.3`, que funciona com Python **3.11 a 3.13** (não use 3.14). O `pyproject.toml` diz `>=3.10`, mas os testes já exigem 3.11.
- `deno` → o yt-dlp atual precisa de um runtime JavaScript (Deno 2.3+ ou Node 22+) para resolver os desafios do YouTube. O app procura o Deno automaticamente (`csvmusic/core/js_runtime.py`).
- `ffmpeg` → converte/processa áudio (mp3/m4a/opus, normalização de volume).
- `gh` → GitHub pela linha de comando (fork, PR, releases).
- `node` → só necessário se for instalar o Claude Code via npm.

> **yt-dlp**: o app já instala o `yt-dlp` como dependência Python (`pip install -e .`). Não precisa do brew. Mas é bom saber que o YouTube muda coisas toda semana e o yt-dlp precisa ser atualizado com frequência (ver doc 09, ideia "auto-update do yt-dlp").

### 1.4 Claude Code

```bash
npm install -g @anthropic-ai/claude-code
# ou o instalador nativo, se preferir:
# curl -fsSL https://claude.ai/install.sh | bash
claude --version
```

Na primeira vez que rodar `claude`, ele pede login.

### 1.5 Editor (opcional, recomendado)

- **VS Code**: `brew install --cask visual-studio-code` (tem extensão do Claude Code).
- Ou **Cursor** / **Zed**. Qualquer um serve.

---

## 2. Criando o seu fork

### 2.1 Login no GitHub

```bash
gh auth login
# escolha: GitHub.com → HTTPS → Login with a web browser
```

### 2.2 Fork + clone

```bash
mkdir -p ~/Projetos && cd ~/Projetos
gh repo fork angall1/CSVMusic --clone --fork-name csvmusic-teles
cd csvmusic-teles
```

Isso:
- cria `github.com/<seu-usuario>/csvmusic-teles` (o nome é sugestão, troque se quiser),
- clona no Mac,
- configura dois remotes: `origin` (seu fork) e `upstream` (o original do angall1).

Confira:

```bash
git remote -v
git describe --tags      # deve mostrar v1.7.9, a versão analisada nestes documentos
```

> Se mostrar uma versão mais nova (o autor lançou atualização), tudo bem: os documentos continuam valendo, mas os números de linha (`arquivo.py:123`) podem ter mudado. Peça ao Claude Code: "compare a versão atual com a v1.7.9 (`git diff v1.7.9 --stat`) e me diga se algo dos docs/fork ficou desatualizado".

> **Quer que seja privado?** Forks de repositório público no GitHub não podem ser privados. Se quiser privado, faça em vez disso:
> ```bash
> git clone https://github.com/angall1/CSVMusic.git csvmusic-teles
> cd csvmusic-teles
> gh repo create csvmusic-teles --private --source=. --remote=origin --push
> git remote add upstream https://github.com/angall1/CSVMusic.git
> ```
> (se o `clone` já criou `origin` apontando pro angall1, rode antes `git remote rename origin upstream`).
> Leia o doc `08-licenca-e-fork.md` antes — a licença define o que você pode/deve manter.

### 2.3 Trazer estes documentos pra dentro do projeto

Copie a pasta `csvmusic-fork-docs` (esta pasta) pra dentro do repositório como `docs/fork/`:

```bash
mkdir -p docs/fork
cp -R /caminho/para/csvmusic-fork-docs/* docs/fork/
```

E o `CLAUDE.md` vai na **raiz** do repositório (ver doc `02-claude-md.md`).

---

## 3. Rodando o app original a partir do código

```bash
cd ~/Projetos/csvmusic-teles
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install pytest
python -m csvmusic.app       # ou: csvmusic
```

Se abrir a janela, está tudo certo.

### Problemas comuns no Mac

| Sintoma | Causa | Solução |
|---|---|---|
| `zsh: command not found: python3.12` | brew não está no PATH | rode o `eval "$(/opt/homebrew/bin/brew shellenv)"` e reabra o Terminal |
| Erro compilando alguma dependência | falta Command Line Tools | `xcode-select --install` |
| App abre mas download falha com "ffmpeg not found" | ffmpeg do brew não detectado | `which ffmpeg` deve dar `/opt/homebrew/bin/ffmpeg`; dá pra apontar o caminho nas configurações do app |
| "Sign in to confirm you're not a bot" | YouTube bloqueando | usar cookies do navegador (opção do app) ou esperar; ver doc 04 |
| App empacotado (.app baixado) "está danificado" | quarentena do Gatekeeper | `xattr -dr com.apple.quarantine /Applications/CSVMusic.app` (só para apps que você confia) |

### Rodar os testes

```bash
pytest -q
```

Anote quantos passam **antes** de mudar qualquer coisa. Essa é sua linha de base.

---

## 4. Manter o fork atualizado com o original

O autor original lança versões com frequência (correções de YouTube, Spotify etc). Pra puxar:

```bash
git fetch upstream
git checkout main
git merge upstream/main     # resolva conflitos se houver
git push origin main
```

> Estratégia recomendada: **não reescreva tudo de uma vez.** Mudanças em camadas (ver `10-roadmap.md`) facilitam continuar puxando correções do upstream nas partes que você não mexeu (principalmente `ytmusic_match.py`, `downloader.py` e importadores de Spotify, que quebram quando os serviços mudam).

---

## 5. Abrindo o Claude Code no projeto

```bash
cd ~/Projetos/csvmusic-teles
source .venv/bin/activate
claude
```

Primeira mensagem sugerida (copie e cole):

```
Leia o CLAUDE.md e depois docs/fork/README.md. Em seguida leia os documentos
docs/fork/03 a 07. Confirme que entendeu a arquitetura resumindo em 15 linhas,
rode `pytest -q` e me diga o resultado. Não altere nada ainda.
```

Depois siga a ordem do `10-roadmap.md`, uma fase por vez. Prompts prontos para cada fase estão em `11-prompts-prontos.md`.
