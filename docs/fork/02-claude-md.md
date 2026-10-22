# 02 — O que é o CLAUDE.md e como montar o seu

## O que é

O `CLAUDE.md` é um arquivo de texto que o **Claude Code lê automaticamente toda vez que abre uma sessão** naquela pasta. É o "manual da casa": como o projeto funciona, como rodar, as regras de estilo, o que não mexer. Sem ele, cada sessão começa do zero e você vai ficar repetindo as mesmas coisas.

## Onde fica (hierarquia)

| Arquivo | Vale para | Vai pro git? |
|---|---|---|
| `~/.claude/CLAUDE.md` | **todos** os seus projetos (preferências pessoais: idioma, jeito de trabalhar) | não |
| `<repo>/CLAUDE.md` | este projeto, para qualquer pessoa | **sim** |
| `<repo>/CLAUDE.local.md` | este projeto, só você (caminhos da sua máquina, pasta de música etc.) | não (coloque no `.gitignore`) |
| `<repo>/subpasta/CLAUDE.md` | carregado quando o Claude trabalha naquela subpasta | sim |

O Claude junta todos os que se aplicam.

> O repositório original já tem um `AGENTS.md` (instruções genéricas para agentes de IA). Pode manter os dois; o `CLAUDE.md` pode simplesmente dizer "leia também AGENTS.md". Alguns times fazem `CLAUDE.md` conter só `@AGENTS.md` (a sintaxe `@arquivo` importa o conteúdo de outro arquivo).

## Como criar

**Jeito rápido:** dentro do projeto, rode `claude` e digite `/init`. Ele lê o repositório e gera um `CLAUDE.md` inicial. Depois você edita.

**Jeito recomendado aqui:** use o template pronto `CLAUDE.md` que está nesta pasta de documentos. Copie para a raiz do seu fork:

```bash
cp docs/fork/CLAUDE.md ./CLAUDE.md
```

E crie o seu local:

```bash
cat > CLAUDE.local.md <<'EOF'
# Coisas só da minha máquina
- Minha pasta de músicas de teste: ~/Music/csvmusic-teste  (NUNCA use a pasta real ~/Music/Biblioteca para testes)
- Playlist pequena para testes rápidos: <cole um link de playlist com ~10 músicas>
- Playlist grande para testes de estresse: <link da playlist de ~1220 músicas>
- Falo português; responda em português.
EOF
echo "CLAUDE.local.md" >> .gitignore
```

## Regras de ouro para um bom CLAUDE.md

1. **Curto e direto.** Ele entra no contexto de toda conversa. 50–150 linhas é ótimo. Detalhe longo vai em `docs/` e o CLAUDE.md só aponta ("para a arquitetura de download, leia docs/fork/04-busca-download-e-tags.md").
2. **Comandos exatos.** `pytest -q`, `python -m csvmusic.app`, como fazer build.
3. **Regras que ele não adivinharia.** Ex.: "indentação com TAB", "logs só via `csvmusic.core.log.log`", "nunca baixe de verdade nos testes".
4. **O que é proibido.** Ex.: "não mexa em `resources/ffmpeg`", "não rode testes que batem no YouTube sem eu pedir".
5. **Atualize quando ele errar.** Se o Claude fizer algo errado duas vezes, vira uma regra no CLAUDE.md. Você pode pedir: "adicione isso ao CLAUDE.md".

## Outros arquivos úteis do Claude Code (opcional, para depois)

- **`.claude/settings.json`** — permissões. Ex.: liberar `pytest` e `git status` sem pedir confirmação toda vez:
  ```json
  {
    "permissions": {
      "allow": ["Bash(pytest:*)", "Bash(python -m pytest:*)", "Bash(git status)", "Bash(git diff:*)", "Bash(ruff:*)"]
    }
  }
  ```
- **Hooks** — comandos que rodam automaticamente. Ex.: rodar `ruff format` depois de cada edição de arquivo `.py`. Peça ao Claude: "configure um hook que roda ruff check nos arquivos .py que você editar".
- **Skills / comandos próprios** — em `.claude/skills/<nome>/SKILL.md`. Ex.: uma skill `release` que sobe versão, gera changelog e faz build do `.app`. Peça: "crie uma skill de release para este projeto".
- **`/code-review`** — revisa o que foi mudado. Rode antes de cada commit grande.
- **Worktrees** — pra testar duas ideias em paralelo sem bagunçar a pasta principal.

## Fluxo de trabalho sugerido com o Claude Code

1. Uma fase do roadmap por vez (`10-roadmap.md`).
2. Peça **plano primeiro** (Shift+Tab até "plan mode", ou escreva "faça um plano antes de mexer").
3. Ele implementa + escreve testes.
4. Você testa na mão com a playlist pequena.
5. Commit (`git commit`), e só então a próxima fase.
6. Quando algo der certo/errado, atualize o CLAUDE.md.
