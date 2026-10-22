"""Specialists (design, devops): read-only consultants between planning and implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_orchestrator.agents.base import as_json, bullet_list, call_role
from ai_orchestrator.contracts import Plan, SpecialistBrief, TaskRequest
from ai_orchestrator.models.providers import AgentResponse

if TYPE_CHECKING:
    from ai_orchestrator.deps import Deps

TITLES = {"design": "Design (UI/UX)", "devops": "DevOps"}


def build_prompt(role: str, task_id: str, request: TaskRequest, plan: Plan, discovery: dict) -> str:
    return f"""# Consulta de {TITLES.get(role, role)} — tarefa {task_id}

{request.task}

## Plano aprovado
{plan.summary}

```json
{as_json([s.model_dump() for s in plan.steps])}
```

## Critérios de aceite atuais
{bullet_list(plan.acceptance_criteria)}

## Escopo autorizado (fixo: você não pode ampliá-lo)
{bullet_list(plan.allowed_paths)}

## Fatos coletados do repositório
```json
{as_json(discovery)}
```

Inspecione o repositório no diretório atual e responda somente com a orientação estruturada.
"""


def brief_section(briefs: list[dict]) -> str:
    """Markdown block shared by the implementer and reviewer prompts."""
    if not briefs:
        return ""
    parts = ["## Orientações dos especialistas"]
    for b in briefs:
        parts += [f"### {TITLES.get(b['role'], b['role'])}", b["summary"], bullet_list(b.get("guidance", []))]
        if b.get("risks"):
            parts += ["Riscos:", bullet_list(b["risks"])]
    return "\n".join(parts) + "\n"


def run(
    deps: Deps,
    role: str,
    task_id: str,
    request: TaskRequest,
    plan: Plan,
    discovery: dict,
    cwd: str,
    scratch_dir: str,
) -> AgentResponse:
    return call_role(
        deps,
        role,
        prompt=build_prompt(role, task_id, request, plan, discovery),
        cwd=cwd,
        scratch_dir=scratch_dir,
        output_model=SpecialistBrief,
    )
