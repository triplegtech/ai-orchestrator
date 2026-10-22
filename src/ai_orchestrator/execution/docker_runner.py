"""Phase 3: isolated runner in disposable containers.

Same interface as LocalRunner, so the orchestration graph does not change.
Planned behaviour, driven by RunnerContract:

- mount only the task worktree, read-write; nothing else from the host;
- network_policy "restricted" -> `--network none` (or an egress allowlist);
- CPU/memory/pids limits and `timeout_seconds` enforced by the runner;
- no credentials in the container environment;
- the agent itself (claude -p) also runs inside the container for unattended work.
"""

from __future__ import annotations

from ai_orchestrator.contracts import CommandResult


class DockerRunner:
    def __init__(self, image: str):
        self.image = image

    def run(self, command: str, cwd: str, timeout: int) -> CommandResult:
        raise NotImplementedError("DockerRunner é escopo da Fase 3; use LocalRunner no MVP.")
