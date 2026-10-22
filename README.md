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
git clone https://github.com/triplegtech/ai-orchestrator.git
cd ai-orchestrator
uv tool install --editable .

# Skill /aio para o Claude Code (opcional)
New-Item -ItemType Directory -Force $HOME\.claude\skills | Out-Null
Copy-Item -Recurse -Force skills\aio $HOME\.claude\skills\
```

Coloca `aio` (e `ai-orchestrator`) no PATH. Editável: mudanças no código, config e prompts deste
repositório valem na hora. Depois de alterar dependências: `uv tool install --editable --reinstall .`.

A skill fica versionada em `skills/aio/`; depois de atualizar o repositório, repita o `Copy-Item`
para pegar a versão nova. No macOS/Linux: `mkdir -p ~/.claude/skills && cp -r skills/aio ~/.claude/skills/`.

## Uso

```powershell
cd C:\caminho\para\projeto
aio run "Adicione paginação ao endpoint de usuários"

# Retoma uma tarefa interrompida
aio resume TASK-20261022-111253-64c0
```

No Claude Code, em qualquer projeto: `/aio Adicione paginação ao endpoint de usuários`
(skill de usuário instalada a partir de `skills/aio/`; roda em segundo plano e resume o relatório).

A stack é detectada pela raiz do repositório (`stack_presets` em `config/orchestrator.yaml`) e o
workspace é preparado antes de qualquer agente rodar — Laravel+Vite: `composer install`, `.env`,
`key:generate`, chaves do Passport (se houver), `npm ci`, `npm run build`; Flutter: `pub get`;
Python: `uv sync`. Se o planner não propuser testes focados, usa a validação padrão da stack.

Especialistas entram só quando necessário: o planner decide se a tarefa precisa de **design**
(telas, componentes, formulários, acessibilidade) ou **devops** (build, CI, Docker, deploy, variáveis
de ambiente, migrações arriscadas). Eles leem o repositório sem alterar nada, orientam o implementador
e acrescentam critérios de aceite que a revisão cobra. Passos manuais (ex.: variável nova no
`.env.example` ou no servidor) aparecem no relatório.

Opções: `--repo <caminho>` (padrão: pasta atual), `--base <ref>` (padrão `HEAD`), `--check` e
`--allow-path` repetíveis (sobrepõem o planner), `--with design|devops` repetível (força um
especialista), `--config <yaml>`.

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
