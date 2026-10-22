"""Wiring of the orchestrator's collaborators. Tests build their own Deps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_orchestrator.config import Policy, Settings, load_policy, load_settings
from ai_orchestrator.execution.git_workspace import GitWorkspaceManager
from ai_orchestrator.execution.local_runner import LocalRunner
from ai_orchestrator.models.registry import ModelRegistry


@dataclass
class Deps:
    settings: Settings
    policy: Policy
    registry: ModelRegistry
    workspaces: GitWorkspaceManager
    runner: LocalRunner


def default_deps(config_path: Path | str | None = None, policy_path: Path | str | None = None) -> Deps:
    settings = load_settings(config_path)
    policy = load_policy(policy_path)
    return Deps(
        settings=settings,
        policy=policy,
        registry=ModelRegistry(settings, policy),
        workspaces=GitWorkspaceManager(settings.workspaces_root, policy.ignored_paths),
        runner=LocalRunner(),
    )
