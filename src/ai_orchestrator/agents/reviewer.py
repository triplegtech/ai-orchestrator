"""Independent reviewer: judges the real diff and real command results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_orchestrator.agents.base import as_json, bullet_list, call_role
from ai_orchestrator.agents.specialists import brief_section
from ai_orchestrator.contracts import Plan, ReviewVerdict, TaskRequest, ValidationReport
from ai_orchestrator.models.providers import AgentResponse

if TYPE_CHECKING:
    from ai_orchestrator.deps import Deps


def build_prompt(
    task_id: str,
    request: TaskRequest,
    plan: Plan,
    implementation: dict,
    validation: ValidationReport,
    diff: str,
    briefs: list[dict] = (),
) -> str:
    commands = [
        {"command": c.command, "exit_code": c.exit_code, "duration_seconds": c.duration_seconds,
         "output_tail": c.output_tail[-1500:]}
        for c in validation.commands
    ]
    return f"""# Revisão da tarefa {task_id}

## Solicitação original
{request.task}

## Critérios de aceite (avalie cada um)
{bullet_list(plan.acceptance_criteria)}

## Escopo autorizado
{bullet_list(plan.allowed_paths)}

{brief_section(list(briefs))}
## O que o implementador afirma (não é prova)
```json
{as_json(implementation)}
```

## Evidência do executor: comandos rodados pelo orquestrador
```json
{as_json(commands)}
```

## Evidência do executor: diff real contra a base
```diff
{diff}
```

Revise o diff no diretório atual quando precisar de mais contexto. Responda com o veredito estruturado.
"""


def run(
    deps: Deps,
    task_id: str,
    request: TaskRequest,
    plan: Plan,
    implementation: dict,
    validation: ValidationReport,
    diff: str,
    cwd: str,
    scratch_dir: str,
    briefs: list[dict] = (),
) -> AgentResponse:
    return call_role(
        deps,
        "reviewer",
        prompt=build_prompt(task_id, request, plan, implementation, validation, diff, briefs),
        cwd=cwd,
        scratch_dir=scratch_dir,
        output_model=ReviewVerdict,
    )
