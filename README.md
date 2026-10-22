# ai-orchestrator

Equipe autônoma de agentes de engenharia de software: **LangGraph** orquestra, **Claude Code**
(`claude -p`, com a sua assinatura) planeja, implementa e revisa. Cada tarefa roda em um
`git worktree` isolado e só é considerada concluída com evidência objetiva: testes reais passando,
diff dentro do escopo e revisão independente aprovada.

Arquitetura, decisões e roadmap: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/) e Git
- Claude Code instalado e logado (`claude auth`) — **sem** `ANTHROPIC_API_KEY` no ambiente

## Instalação (uma vez)

```powershell
git clone <url-deste-repo> ai-orchestrator
cd ai-orchestrator
uv tool install --editable .
```

Coloca `aio` (e `ai-orchestrator`) no PATH. Editável: mudanças no código, config e prompts deste
repositório valem na hora. Depois de alterar dependências: `uv tool install --editable --reinstall .`.

## Uso

```powershell
cd C:\caminho\para\projeto
aio run "Adicione paginação ao endpoint de usuários"

# Retoma uma tarefa interrompida
aio resume TASK-20261022-111253-64c0
```

No Claude Code, em qualquer projeto: `/aio Adicione paginação ao endpoint de usuários`
(skill de usuário em `~/.claude/skills/aio/`; roda em segundo plano e resume o relatório).

A stack é detectada pela raiz do repositório (`stack_presets` em `config/orchestrator.yaml`) e o
workspace é preparado antes de qualquer agente rodar — Laravel+Vite: `composer install`, `.env`,
`key:generate`, chaves do Passport (se houver), `npm ci`, `npm run build`; Flutter: `pub get`;
Python: `uv sync`. Se o planner não propuser testes focados, usa a validação padrão da stack.

Opções: `--repo <caminho>` (padrão: pasta atual), `--base <ref>` (padrão `HEAD`), `--check` e
`--allow-path` repetíveis (sobrepõem o planner), `--config <yaml>`.

Saída: branch `agents/<task-id>` com commit local (nunca push), `report.md` e `report.json` em
`%LOCALAPPDATA%\ai-orchestrator\workspaces\<task-id>\`. Código de saída `0` = done, `2` = blocked.

Para integrar depois de revisar:

```powershell
git -C C:\caminho\para\projeto diff <base>...agents/<task-id>
git -C C:\caminho\para\projeto merge --no-ff agents/<task-id>
git -C C:\caminho\para\projeto worktree remove <caminho-do-worktree>
```

## LangGraph Studio

```powershell
copy .env.example .env
uv run langgraph dev
```

Grafo `engineering`. Entrada: `{"request": {"task": "...", "repo_path": "C:/...", "checks": []}}`.

## Configuração

- `config/orchestrator.yaml` — modelo/effort/orçamento por papel, limites, pasta de workspaces.
- `policies/default.yaml` — caminhos proibidos, artefatos ignorados, comandos proibidos, permissões do
  Claude Code por perfil de ferramentas.
- `prompts/*.md` — instruções de cada papel.

## Testes

```powershell
uv run pytest
```

Os testes não chamam LLM: rodam o grafo completo contra um repositório Git temporário com agentes
simulados (caminho feliz, retry com feedback, violação de escopo, pedido de esclarecimento, revisão
reprovada, repositório inválido, artefatos de build).
