# 08 — Licença, fork e o que você pode fazer

> Não sou advogado; isto é um resumo prático. Para uso pessoal você está tranquilo. O cuidado é só se um dia quiser **distribuir**.

## 1. O CSVMusic não tem licença

- Não existe arquivo `LICENSE` no repositório (nem no histórico), o `pyproject.toml` não declara licença, e o GitHub mostra `license: null`.
- Sem licença, o padrão legal (Convenção de Berna; no Brasil, Lei 9.610/98) é **"todos os direitos reservados"** ao autor (`angall1`).
- O que os **Termos de Uso do GitHub** garantem a qualquer pessoa num repositório público: **ver o código e fazer fork pelo GitHub**.
- O que **não** está garantido explicitamente: modificar e redistribuir, publicar binários (.app/.exe) próprios, mudar a licença.

### Na prática
| Você quer… | Situação |
|---|---|
| Fork para estudar e usar **só você** | Tranquilo (risco prático baixíssimo). |
| Deixar o fork **público** no GitHub com suas mudanças | Aceitável pelos termos do GitHub (fork público), mas mantenha o crédito ao autor original. |
| Publicar **binários** do seu fork / divulgar como app | Peça licença ao autor antes. |
| Vender / relicenciar | Não. |

### Recomendações
1. **Abra uma issue** no repositório original pedindo uma licença (ex.: "Could you add a LICENSE file (MIT/GPL)? I'd like to maintain a personal fork."). É um pedido comum e o projeto tem 600+ estrelas e 30+ forks.
2. Mantenha o **histórico do git** (autoria) e um aviso no README: "Fork pessoal de [angall1/CSVMusic](https://github.com/angall1/CSVMusic)".
3. **Não apague** nada da pasta `licenses/`.

### Decisão (22/10/2026, à tarde): fork público por enquanto

O Gabriel mudou de ideia: por enquanto o código fica num **fork público** do original no GitHub (`GabrielTeles845/csvmusic-teles`, criado com `gh repo fork`), o caminho que os termos do GitHub cobrem para um projeto sem licença. O crédito ao autor fica no histórico do git e no aviso do README. Forks do GitHub começam com o GitHub Actions desligado, então o `release.yml` herdado (que dispara em push na `main` quando muda `csvmusic/version.py`) não roda. A decisão abaixo, de repositório privado, fica como registro e pode voltar.

### Decisão anterior (22/10/2026): repositório privado

O fork vai para um **repositório privado** no GitHub do Gabriel, não um fork público (fork do GitHub não pode ser privado). No clone local, o remoto do original passou a se chamar `upstream`, para trazer correções do autor com `git fetch upstream`. O remoto `origin` fica para o repositório privado, criado pelo Gabriel com:

```
gh repo create csvmusic-teles --private --source . --remote origin
git push -u origin main
```

Como é privado e só para uso pessoal, a issue pedindo licença ao autor (recomendação 1) deixa de ser urgente; ela só volta se um dia houver distribuição.

## 2. Licenças das peças de terceiros (importam se distribuir binários)

| Componente | Licença | Observação |
|---|---|---|
| **PySide6 / Qt** | LGPLv3 | ok em pasta (one-folder) com bibliotecas substituíveis; incluir texto da licença |
| **mutagen** (tags) | **GPL-2.0+** | se distribuir binário, há argumento forte de que o app vira obra GPL |
| **yt-dlp** | Unlicense (domínio público) | — |
| **ytmusicapi** | MIT | — |
| **requests** | Apache-2.0 | — |
| **pandas** | BSD-3 | (pesado para só ler CSV; dá pra trocar pelo módulo `csv`) |
| **FFmpeg** | macOS: build LGPL compilado no CI; Windows/Linux: builds **GPL** | o CI **não** inclui a licença GPL/oferta de fonte para Windows/Linux |
| **Deno** | MIT | — |
| **Comic Neue** | SIL OFL 1.1 | manter `licenses/ComicNeue-OFL.txt` |
| **VCR OSD Mono** | freeware, **sem licença no repo** | confirme termos ou troque (no redesign provavelmente sai) |
| **libgpod** (sync iPod) | LGPL-2.1 | — |

## 3. Coisas para trocar no seu fork (pra não "se passar" pelo original)

| O quê | Onde | Por quê |
|---|---|---|
| URL do verificador de atualização | `csvmusic/core/update_check.py:9` e `:49` | senão seu app avisa sobre versões do original |
| Identificador do app no Mac | `CSVMusic.spec` → `bundle_identifier='com.angall1.csvmusic'` | trocar para `com.<voce>.csvmusic` para não misturar preferências/permissões com o app original |
| Nome exibido (opcional) | `CSVMusic.spec`, `app.py`, títulos de janela | se quiser um nome próprio |
| Pasta de configurações (opcional) | `csvmusic/core/settings.py` | se quiser rodar o original e o seu lado a lado sem um mexer na biblioteca do outro (**recomendado**: use outro nome de pasta, ex. `CSVMusicTeles`) |
| Ícone do Mac | `resources/app.icns` **não existe** hoje | gerar com `iconutil` a partir de um PNG 1024×1024 |
| Versão | `csvmusic/version.py` + `pyproject.toml` | use algo como `1.7.9+teles.1` ou numeração própria |

## 4. Uso do YouTube

Independente da licença do código: baixar áudio do YouTube vai contra os termos de uso do YouTube. Para uso pessoal é o mesmo risco que qualquer usuário de yt-dlp tem. Não distribua as músicas baixadas.
