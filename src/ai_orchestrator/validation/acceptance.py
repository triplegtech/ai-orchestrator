"""Builds the objective validation report from the workspace itself."""

from __future__ import annotations

from ai_orchestrator.contracts import ValidationReport
from ai_orchestrator.execution.git_workspace import GitWorkspaceManager, Workspace
from ai_orchestrator.execution.local_runner import LocalRunner
from ai_orchestrator.orchestration.policies import check_scope
from ai_orchestrator.validation.test_runner import run_checks


def validate_workspace(
    workspaces: GitWorkspaceManager,
    ws: Workspace,
    runner: LocalRunner,
    *,
    allowed_paths: list[str],
    denied_paths: list[str],
    commands: list[str],
    timeout: int,
) -> ValidationReport:
    # Changed files come from git, never from the implementer's own report.
    changed = workspaces.changed_files(ws)
    violations = check_scope(changed, allowed_paths, denied_paths)
    # Commands still run with scope violations so the next attempt gets full feedback.
    results = run_checks(runner, commands, cwd=ws.path, timeout=timeout) if changed else []
    return ValidationReport(changed_files=changed, scope_violations=violations, commands=results)
