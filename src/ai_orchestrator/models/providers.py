"""Provider-neutral agent call interface.

Agents never import a vendor SDK. They build an AgentCall and the registry hands
it to whichever provider is configured for their role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from ai_orchestrator.config import ToolProfile


class AgentError(RuntimeError):
    def __init__(self, message: str, cost_usd: float = 0.0, session_id: str | None = None):
        super().__init__(message)
        self.cost_usd = cost_usd
        self.session_id = session_id


@dataclass
class AgentCall:
    role: str
    system_prompt: str
    prompt: str
    cwd: str
    output_model: type[BaseModel]
    model: str
    tool_profile: ToolProfile
    deny_rules: list[str]
    timeout_seconds: int
    scratch_dir: str
    effort: str | None = None
    max_budget_usd: float | None = None
    resume_session_id: str | None = None


@dataclass
class AgentResponse:
    output: BaseModel
    session_id: str | None
    cost_usd: float
    raw: dict[str, Any] = field(default_factory=dict)


class AgentProvider(Protocol):
    def run(self, call: AgentCall) -> AgentResponse: ...


class NotConfiguredProvider:
    """Placeholder for API providers planned for later phases."""

    def __init__(self, name: str):
        self.name = name

    def run(self, call: AgentCall) -> AgentResponse:
        raise AgentError(
            f"Provider '{self.name}' ainda não implementado. Use 'claude_code' no papel '{call.role}' "
            "ou implemente um adaptador em ai_orchestrator/models/providers.py."
        )
