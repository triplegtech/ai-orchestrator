"""Planner: request -> verifiable plan with acceptance criteria and scope."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_orchestrator.agents.base import as_json, bullet_list, call_role
from ai_orchestrator.contracts import Plan, TaskRequest
from ai_orchestrator.models.providers import AgentResponse

if TYPE_CHECKING:
    from ai_orchestrator.deps import Deps


def build_prompt(task_id: str, request: TaskRequest, discovery: dict, environment: str = "") -> str:
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
{environment}
Inspecione o repositório no diretório atual antes de planejar. Responda somente com o plano estruturado.
"""


def environment_note(setup: list[str], default_checks: list[str]) -> str:
    if not setup and not default_checks:
        return ""
    return f"""
## Ambiente do workspace
Já preparado pelo orquestrador com (não repita em validation_commands):
{bullet_list(setup)}
Validação padrão da stack, usada se você não propuser nada mais focado:
{bullet_list(default_checks)}
"""


def run(
    deps: Deps,
    task_id: str,
    request: TaskRequest,
    discovery: dict,
    cwd: str,
    scratch_dir: str,
    environment: str = "",
) -> AgentResponse:
    return call_role(
        deps,
        "planner",
        prompt=build_prompt(task_id, request, discovery, environment),
        cwd=cwd,
        scratch_dir=scratch_dir,
        output_model=Plan,
    )
