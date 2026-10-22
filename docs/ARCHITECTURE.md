# Arquitetura — Equipe autônoma de agentes de engenharia

Origem: conversa "Avaliando LangChain para agentes" (ChatGPT). Requisitos fixados lá:
**desenvolvimento de software** (não integração em produto), **autonomia até cumprir critérios com
limites de segurança**, **execução híbrida**, **modelos diferentes por agente**. Decisão final da
conversa: **LangGraph orquestra, Claude Code implementa**, começar local.

Este repositório implementa a **Fase 1 (MVP)** com o ciclo de correção da Fase 2 já incluído.

## Princípios

1. **Orquestração determinística** — o fluxo é uma máquina de estados; IA só onde há ambiguidade
   (planejar, implementar, revisar).
2. **O agente propõe, o executor decide** — escopo, comandos, arquivos alterados e resultados de
   testes são verificados pelo orquestrador, nunca aceitos da resposta do agente.
3. **Execução isolada** — cada tarefa roda em um `git worktree` próprio, em um branch `agents/<task>`.
4. **Validação objetiva** — "concluído" exige comandos reais com exit 0, diff dentro do escopo e
   revisão independente aprovada.
5. **Modelos intercambiáveis** — papel → provider/modelo em `config/orchestrator.yaml`.

## Visão geral

```
CLI (ai-orchestrator run)  ·  LangGraph Studio (langgraph dev)
                 │
        LangGraph StateGraph  ── checkpoints SQLite (retomada)
                 │
  ┌──────────────┼───────────────┐
Planner      Implementer      Reviewer        ← papéis, cada um com modelo/ferramentas próprios
  │              │               │
  └──── ModelRegistry ───────────┘            ← role → provider + modelo (+ escalonamento)
                 │
      ClaudeCodeProvider (claude -p)          ← assinatura do Claude Code, sem API key
                 │
  Execution gateway: GitWorkspaceManager + LocalRunner + políticas + permissões do Claude Code
                 │
        git worktree isolado por tarefa
```

## Papéis

| Papel | Modelo padrão | Ferramentas | Responsabilidade |
|---|---|---|---|
| **Planner** | opus / effort high | Read, Glob, Grep (somente leitura) | Inspeciona o repo; gera critérios de aceite verificáveis, passos, `allowed_paths`, comandos de validação, riscos, perguntas bloqueantes |
| **Implementer** | sonnet → opus a partir da 2ª tentativa | Read, Edit, Write, Glob, Grep, Bash, PowerShell (com deny list) | Edita o worktree, roda os testes, reporta com honestidade; retoma a mesma sessão nas correções (`--resume`) |
| **Reviewer** | opus / effort high | Read, Glob, Grep, `git diff/log/show/status` | Avalia cada critério com evidência, correção, testes, segurança e escopo sobre o **diff real** |

Mapeamento dos especialistas do `tripleg-orchestrator.md`: Product Analyst + Software Architect →
Planner; Backend/Database/Web/Mobile/DevOps → Implementer (detecta a stack); QA + Code Reviewer +
Security → Reviewer. Separar em especialistas por stack é a Fase 4.

**Um só cérebro:** o orquestrador é o LangGraph. Os agentes rodam com `--setting-sources project`,
então o `tripleg-orchestrator` (agente de usuário) não é carregado dentro deles — evita duas camadas
de delegação competindo. Ele continua disponível para uso interativo no Claude Code.

## Fluxo (máquina de estados)

```
intake → discovery → setup_workspace → planning → implement → validate ─┬─(passou)→ review → gate
                                                      ▲                  └─(falhou)────────→ gate
                                                      └────────────── fix ◄─────────────────┘
gate → report (done | blocked)        qualquer etapa com erro → report (blocked)
```

| Nó | Tipo | O que faz |
|---|---|---|
| intake | código | Valida a solicitação, resolve repo e `base_ref` → SHA, avisa sobre mudanças não commitadas |
| discovery | código | Fatos determinísticos do commit base: manifests, arquivos de instrução, diretórios de teste |
| setup_workspace | código | `git worktree add -b agents/<task>` fora do OneDrive |
| planning | IA | Plano estruturado; `--check`/`--allow-path` do usuário sobrepõem o planner; comandos perigosos são descartados; `needs_clarification` bloqueia |
| implement | IA | Implementa; nas correções recebe o erro real e retoma a sessão |
| validate | código | Arquivos alterados via git (não via agente), checagem de escopo e de caminhos proibidos, execução real dos comandos; artefatos de build (`ignored_paths`) não contam |
| review | IA | Só roda se a validação passou (economiza custo); recebe diff e saída real dos comandos |
| gate | código | `done` / `fix` / `blocked` — orçamento de tentativas e de custo |
| report | código | Commit local no branch da tarefa (se `done`), `report.json` + `report.md` |

Uma tarefa nunca é marcada como concluída por conveniência: sem evidência, ela fica `blocked` com o
motivo e tudo o que foi produzido até ali.

## Contratos (`src/ai_orchestrator/contracts.py`)

`TaskRequest`, `Plan`, `ImplementerResult` (o JSON da conversa), `CommandResult`, `ValidationReport`,
`ReviewVerdict`, `RunnerContract`. As saídas dos agentes são forçadas com `--json-schema` e
validadas com Pydantic — mas o JSON não é prova: o executor confere tudo.

## Segurança (requisito desde o MVP)

- **Isolamento do agente:** `--restricted` + `--strict-mcp-config` → ferramentas de arquivo confinadas ao
  worktree, sem plugins, hooks, MCP ou settings do usuário/repositório dentro dos agentes (também
  reduziu o contexto de ~208k para ~3k tokens por chamada). Só o `--settings` gerado pelo orquestrador vale.
- **Permissões:** `--permission-prompts none` + `dontAsk`/`acceptEdits` + deny list em
  `policies/default.yaml`: sem push/merge/reset/checkout, sem rede, sem `.env`/chaves, sem `.git/`/`.claude/`.
  Ações negadas aparecem na linha do tempo do relatório.
- **Escopo verificado depois:** qualquer arquivo fora de `allowed_paths` ou em `denied_paths` reprova.
- **Comandos de validação:** propostas do planner passam por `denied_command_patterns`.
- **Credenciais:** variáveis com KEY/TOKEN/SECRET/PASSWORD são removidas do ambiente dos agentes e dos
  comandos. `ANTHROPIC_API_KEY` nunca chega ao Claude Code (evita cobrança na API em vez da assinatura).
- **Limites:** tentativas, custo total, `--max-budget-usd` por chamada, timeout por agente e por comando
  (mata a árvore de processos).
- **Nada sai da máquina:** commit apenas local no branch da tarefa; merge é decisão humana.
- **Conteúdo do repositório é dado, não instrução** (reforçado nos prompts).

**Limitação conhecida da Fase 1 (verificada):** `--restricted` confina as ferramentas de arquivo
(Read/Edit/Write) ao worktree e ignora as configurações de usuário e do repositório alvo — mas **o
shell não é sandbox**. Num teste real, pedido explicitamente, o implementer criou `../escape.txt` via
PowerShell `Set-Content`. Os comandos de validação também executam código do repositório sem
isolamento, e o worktree compartilha o `.git` do repositório original. Deny rules de comandos são
contornáveis (`python -c ...`), então não são fronteira de segurança. Consequências:

- use a Fase 1 em repositórios seus, supervisionando (o gate ajuda: sem evidência, a tarefa bloqueia);
- o perfil `implement_no_shell` (em `policies/default.yaml`) remove Bash/PowerShell do implementer —
  ele passa a depender do feedback real da validação para corrigir;
- trabalho autônomo sem supervisão exige o `DockerRunner` (Fase 3), com o agente e os testes dentro
  do container.

## Desvios em relação à conversa (e por quê)

| Conversa | Aqui | Motivo |
|---|---|---|
| PostgreSQL para estado | SQLite (`langgraph-checkpoint-sqlite`) | A própria conversa pede para não superconstruir o MVP; trocar para Postgres é usar `PostgresSaver` |
| Deep Agents para o protótipo | LangGraph direto + Claude Code como harness | A última resposta da conversa escolheu Claude Code como implementador; ele já é o harness de coding |
| Python 3.11 | Python ≥3.12 (3.14 instalado) | Única versão disponível; dependências instalaram sem problemas |
| `ANTHROPIC_API_KEY` no `.env` | Removida | Com ela o Claude Code cobra pela API em vez da assinatura (alerta da própria conversa) |
| `src/` com módulos soltos | Pacote `src/ai_orchestrator/` | Instalável (`uv`), imports absolutos funcionam no `langgraph dev`/deploy |
| Gateway como um módulo | `GitWorkspaceManager` + `LocalRunner` + políticas + permissões do Claude Code | O Claude Code já aplica permissões nas ferramentas; o orquestrador revalida depois |
| Modelos diferentes por provider | Modelos diferentes por papel via Claude Code (`--model`); API providers como stub | Sem API key configurada; `ModelRegistry.get(role, ctx)` já está pronto para outros providers |

## Fases

- **Fase 1 — Fundação (feito):** CLI, worktree isolado, edição + testes, diff e relatório.
- **Fase 2 — Orquestração (feito):** planner + reviewer, critérios estruturados, retries com
  feedback real, limites, checkpoints e `resume`.
  Pendente: `interrupt()` para aprovação humana em pontos configuráveis.
- **Fase 3 — Híbrido:** `DockerRunner` (rede `none`, limites de CPU/memória, agente dentro do
  container), runner remoto que puxa tarefas de uma fila (conexão de saída, nunca terminal exposto),
  deploy do control plane (LangSmith Deployment ou `langgraph build/up`).
- **Fase 4 — Escala:** especialistas por stack, tarefas paralelas em worktrees distintos, GitHub/PRs,
  providers `anthropic_api`/`openai_api`, benchmark de tarefas e comparação de modelos.

## Métricas para acompanhar

Taxa de conclusão (`done`), taxa de aceitação humana do diff, regressões, custo por tarefa concluída
(inclui tentativas falhas), tempo até conclusão, intervenções necessárias, ações negadas pela política.
