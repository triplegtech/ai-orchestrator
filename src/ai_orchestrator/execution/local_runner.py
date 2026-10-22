"""Runs validation commands inside a workspace on this machine."""

from __future__ import annotations

import time

from ai_orchestrator.contracts import CommandResult
from ai_orchestrator.execution.process import run_process, sanitized_env

OUTPUT_TAIL_CHARS = 4000


class LocalRunner:
    """Phase 1 runner. Isolation comes from the worktree, not from the OS.

    Commands run through the system shell with credentials stripped from the
    environment. Use the Docker runner (Phase 3) for unattended work.
    """

    def run(self, command: str, cwd: str, timeout: int) -> CommandResult:
        started = time.monotonic()
        out = run_process(command, cwd=cwd, timeout=timeout, env=sanitized_env(), shell=True)
        combined = (out.stdout + ("\n" + out.stderr if out.stderr else "")).strip()
        return CommandResult(
            command=command,
            exit_code=out.returncode,
            duration_seconds=round(time.monotonic() - started, 2),
            output_tail=combined[-OUTPUT_TAIL_CHARS:],
            timed_out=out.timed_out,
        )
