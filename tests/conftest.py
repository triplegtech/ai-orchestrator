from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ai_orchestrator.config import StackPreset, load_policy, load_settings
from ai_orchestrator.contracts import CriterionCheck, ImplementerResult, Plan, PlanStep, ReviewVerdict
from ai_orchestrator.deps import Deps
from ai_orchestrator.execution.git_workspace import GitWorkspaceManager
from ai_orchestrator.execution.local_runner import LocalRunner
from ai_orchestrator.models.providers import AgentCall, AgentResponse
from ai_orchestrator.models.registry import ModelRegistry

CHECK_SCRIPT = """import pathlib, sys
p = pathlib.Path("hello.txt")
sys.exit(0 if p.exists() and p.read_text().strip() == "ok" else 1)
"""
CHECK_COMMAND = f'"{sys.executable}" check.py'


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@localhost", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / "check.py").write_text(CHECK_SCRIPT, encoding="utf-8")
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(path, "init", "-q")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "init")
    return path


class FakeProvider:
    """Scripted agents. `writes` is the content the implementer writes on each attempt."""

    def __init__(self, writes=("ok",), write_path="hello.txt", approve=True, clarification=(), artifacts=False,
                 plan_checks=None):
        self.plan_checks = plan_checks if plan_checks is not None else [CHECK_COMMAND, "git push origin main"]
        self.artifacts = artifacts
        self.writes = list(writes)
        self.write_path = write_path
        self.approve = approve
        self.clarification = list(clarification)
        self.calls: list[AgentCall] = []

    def run(self, call: AgentCall) -> AgentResponse:
        self.calls.append(call)
        if call.role == "planner":
            out = Plan(
                summary="Criar hello.txt",
                acceptance_criteria=["hello.txt contém ok"],
                steps=[PlanStep(id="1", description="escrever arquivo", files=["hello.txt"])],
                allowed_paths=["hello.txt"],
                validation_commands=self.plan_checks,
                needs_clarification=self.clarification,
            )
        elif call.role == "implementer":
            content = self.writes.pop(0) if self.writes else "ok"
            (Path(call.cwd) / self.write_path).write_text(content, encoding="utf-8")
            if self.artifacts:
                (Path(call.cwd) / "__pycache__").mkdir(exist_ok=True)
                (Path(call.cwd) / "__pycache__" / "check.cpython-314.pyc").write_bytes(b"\0")
            out = ImplementerResult(task_id="x", status="implemented", summary=f"wrote {content}",
                                    changed_files=[self.write_path])
        else:
            out = ReviewVerdict(approved=self.approve, summary="ok" if self.approve else "não",
                                criteria=[CriterionCheck(criterion="hello.txt contém ok", met=self.approve, evidence="diff")])
        return AgentResponse(output=out, session_id=f"session-{call.role}", cost_usd=0.01)


@pytest.fixture
def make_deps(tmp_path: Path):
    def factory(provider: FakeProvider, max_attempts: int = 3, presets: dict | None = None) -> Deps:
        settings = load_settings()
        settings = settings.model_copy(update={
            "workspaces_root": tmp_path / "workspaces",
            "budgets": settings.budgets.model_copy(update={"max_attempts": max_attempts}),
            "stack_presets": {k: StackPreset(**v) for k, v in (presets or {}).items()},
        })
        policy = load_policy()
        return Deps(
            settings=settings,
            policy=policy,
            registry=ModelRegistry(settings, policy, providers={"claude_code": provider}),
            workspaces=GitWorkspaceManager(settings.workspaces_root, policy.ignored_paths),
            runner=LocalRunner(),
        )

    return factory
