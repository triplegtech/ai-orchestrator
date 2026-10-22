"""Role -> (provider, model, limits) resolution. The only place that knows models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_orchestrator.config import Policy, RoleConfig, Settings
from ai_orchestrator.models.providers import AgentProvider, NotConfiguredProvider


@dataclass
class ResolvedRole:
    role: str
    config: RoleConfig
    model: str
    provider: AgentProvider


@dataclass
class TaskContext:
    attempt: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


class ModelRegistry:
    def __init__(self, settings: Settings, policy: Policy, providers: dict[str, AgentProvider] | None = None):
        self.settings = settings
        self.policy = policy
        self.providers = providers if providers is not None else _default_providers()

    def get(self, role: str, task_context: TaskContext | None = None) -> ResolvedRole:
        ctx = task_context or TaskContext()
        try:
            config = self.settings.roles[role]
        except KeyError as exc:
            raise KeyError(f"Papel '{role}' não está configurado em roles") from exc
        model = config.model
        if (
            config.escalate_after_attempt
            and config.escalation_model
            and ctx.attempt >= config.escalate_after_attempt
        ):
            model = config.escalation_model
        provider = self.providers.get(config.provider) or NotConfiguredProvider(config.provider)
        return ResolvedRole(role, config, model, provider)


def _default_providers() -> dict[str, AgentProvider]:
    from ai_orchestrator.execution.claude_code import ClaudeCodeProvider

    return {
        "claude_code": ClaudeCodeProvider(),
        "anthropic_api": NotConfiguredProvider("anthropic_api"),
        "openai_api": NotConfiguredProvider("openai_api"),
    }
