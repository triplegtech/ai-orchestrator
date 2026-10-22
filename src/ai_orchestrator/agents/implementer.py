"""Implementer: edits code in the task worktree; resumes its session on retries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_orchestrator.agents.base import as_json, bullet_list, call_role
from ai_orchestrator.contracts import ImplementerResult, Plan, TaskRequest
from ai_orchestrator.models.providers import AgentResponse

if TYPE_CHECKING:
    from ai_orchestrator.deps import Deps


def build_prompt(task_id: str, request: TaskRequest, plan: Plan, attempt: int, feedback: str) -> str:
    brief = f"""# Tarefa {task_id}

{request.task}

## Plano aprovado
{plan.summary}

```json
{as_json([s.model_dump() for s in plan.steps])}
```

## Critérios de aceite
{bullet_list(plan.acceptance_criteria)}

## Você só pode alterar arquivos que casem com
{bullet_list(plan.allowed_paths)}

## Comandos de validação (o executor vai rodá-los de novo depois de você)
{bullet_list(plan.validation_commands)}
"""
    if attempt > 1 and feedback:
        return f"""{brief}
## Tentativa {attempt}: a anterior não passou no gate. Evidências reais do executor
{feedback}

Diagnostique a causa, corrija dentro do escopo autorizado e rode novamente os comandos de validação.
Responda com o resultado estruturado (task_id = "{task_id}").
"""
    return f"""{brief}
Implemente, rode os comandos de validação e responda com o resultado estruturado (task_id = "{task_id}").
"""


def run(
    deps: Deps,
    task_id: str,
    request: TaskRequest,
    plan: Plan,
    *,
    attempt: int,
    feedback: str,
    session_id: str | None,
    cwd: str,
    scratch_dir: str,
) -> AgentResponse:
    return call_role(
        deps,
        "implementer",
        prompt=build_prompt(task_id, request, plan, attempt, feedback),
        cwd=cwd,
        scratch_dir=scratch_dir,
        output_model=ImplementerResult,
        attempt=attempt,
        resume_session_id=session_id,
    )
