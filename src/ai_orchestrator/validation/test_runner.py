"""Runs the plan's validation commands for real. Agent opinions don't count here."""

from __future__ import annotations

from ai_orchestrator.contracts import CommandResult
from ai_orchestrator.execution.local_runner import LocalRunner


def run_checks(runner: LocalRunner, commands: list[str], cwd: str, timeout: int) -> list[CommandResult]:
    return [runner.run(command, cwd=cwd, timeout=timeout) for command in commands]
