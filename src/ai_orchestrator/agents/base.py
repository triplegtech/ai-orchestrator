"""Shared invocation path for every agent role."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ai_orchestrator.config import load_prompt
from ai_orchestrator.models.providers import AgentCall, AgentResponse
from ai_orchestrator.models.registry import TaskContext

if TYPE_CHECKING:
    from ai_orchestrator.deps import Deps


def call_role(
    deps: Deps,
    role: str,
    *,
    prompt: str,
    cwd: str,
    scratch_dir: str,
    output_model: type[BaseModel],
    attempt: int = 1,
    resume_session_id: str | None = None,
) -> AgentResponse:
    resolved = deps.registry.get(role, TaskContext(attempt=attempt))
    cfg = resolved.config
    call = AgentCall(
        role=role,
        system_prompt=load_prompt(cfg.prompt),
        prompt=prompt,
        cwd=cwd,
        output_model=output_model,
        model=resolved.model,
        tool_profile=deps.policy.tool_profiles[cfg.tool_profile],
        deny_rules=deps.policy.claude_deny,
        timeout_seconds=deps.settings.budgets.agent_timeout_seconds,
        scratch_dir=scratch_dir,
        effort=cfg.effort,
        max_budget_usd=cfg.max_budget_usd,
        resume_session_id=resume_session_id,
    )
    return resolved.provider.run(call)


def as_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "- (nenhum)"
