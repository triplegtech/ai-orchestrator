"""Planner: request -> verifiable plan with acceptance criteria and scope."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_orchestrator.agents.base import as_json, bullet_list, call_role
from ai_orchestrator.contracts import Plan, TaskRequest
from ai_orchestrator.models.providers import AgentResponse

if TYPE_CHECKING:
    from ai_orchestrator.deps import Deps


def build_prompt(task_id: str, request: TaskRequest, discovery: dict) -> str:
    user_scope = (
        f"O usuário restringiu o escopo a:\n{bullet_list(request.allowed_paths)}\nUse exatamente esses caminhos em allowed_paths."
        if request.allowed_paths
        else "Defina allowed_paths como o menor conjunto de globs que cobre a mudança e os testes."
    )
    user_checks = (
        f"O usuário definiu os comandos de validação:\n{bullet_list(request.checks)}\nUse exatamente esses comandos."
        if request.checks
        else "Proponha validation_commands reais deste projeto (testes, lint, build) que você confirmou existirem."
    )
    return f"""# Tarefa {task_id}

{request.task}

## Fatos coletados do repositório (determinístico)
```json
{as_json(discovery)}
```

## Escopo
{user_scope}

## Validação
{user_checks}

Inspecione o repositório no diretório atual antes de planejar. Responda somente com o plano estruturado.
"""


def run(deps: Deps, task_id: str, request: TaskRequest, discovery: dict, cwd: str, scratch_dir: str) -> AgentResponse:
    return call_role(
        deps,
        "planner",
        prompt=build_prompt(task_id, request, discovery),
        cwd=cwd,
        scratch_dir=scratch_dir,
        output_model=Plan,
    )
