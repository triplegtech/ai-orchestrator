"""Loads orchestrator settings and execution policies from YAML."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "orchestrator.yaml"
DEFAULT_POLICY = PROJECT_ROOT / "policies" / "default.yaml"
PROMPTS_DIR = PROJECT_ROOT / "prompts"


class RoleConfig(BaseModel):
    provider: str = "claude_code"
    model: str
    effort: str | None = None
    tool_profile: str = "read_only"
    prompt: str
    max_budget_usd: float | None = None
    escalate_after_attempt: int | None = None
    escalation_model: str | None = None


class Budgets(BaseModel):
    max_attempts: int = 3
    max_cost_usd: float = 10.0
    agent_timeout_seconds: int = 1800
    validation_timeout_seconds: int = 900


class StackPreset(BaseModel):
    detect: list[str]  # all of these must exist at the repo root
    setup: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    workspaces_root: Path
    commit_on_success: bool = True
    budgets: Budgets = Field(default_factory=Budgets)
    roles: dict[str, RoleConfig]
    # Ordered: the first preset whose files all exist wins.
    stack_presets: dict[str, StackPreset] = Field(default_factory=dict)

    def detect_stack(self, root_files: set[str]) -> str | None:
        for name, preset in self.stack_presets.items():
            if all(f in root_files for f in preset.detect):
                return name
        return None


class ToolProfile(BaseModel):
    tools: list[str]
    permission_mode: str = "dontAsk"
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class Policy(BaseModel):
    denied_paths: list[str] = Field(default_factory=list)
    # Changes here pass validation but pause the task for human approval before the commit.
    confirm_paths: list[str] = Field(default_factory=list)
    ignored_paths: list[str] = Field(default_factory=list)
    denied_command_patterns: list[str] = Field(default_factory=list)
    claude_deny: list[str] = Field(default_factory=list)
    tool_profiles: dict[str, ToolProfile]


def _resolve_workspaces_root(raw: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if "$" in expanded or "%" in expanded:
        # Variable not defined on this OS (e.g. LOCALAPPDATA outside Windows).
        return Path.home() / ".ai-orchestrator" / "workspaces"
    return Path(expanded)


def load_settings(path: Path | str | None = None) -> Settings:
    path = Path(path or os.environ.get("AI_ORCH_CONFIG") or DEFAULT_CONFIG)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["workspaces_root"] = _resolve_workspaces_root(str(data["workspaces_root"]))
    return Settings.model_validate(data)


def load_policy(path: Path | str | None = None) -> Policy:
    path = Path(path or os.environ.get("AI_ORCH_POLICY") or DEFAULT_POLICY)
    return Policy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")
