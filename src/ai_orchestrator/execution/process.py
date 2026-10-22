"""Subprocess helpers: sanitized environment and process-tree timeouts."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass

_SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.IGNORECASE)


def sanitized_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Copy of os.environ without anything that looks like a credential."""
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env.update(extra or {})
    return env


@dataclass
class ProcessOutput:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def _kill_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGKILL)


def run_process(
    args: list[str] | str,
    *,
    cwd: str,
    timeout: int,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    shell: bool = False,
) -> ProcessOutput:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        shell=shell,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **kwargs,
    )
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
        return ProcessOutput(proc.returncode, out, err, timed_out=False)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, err = proc.communicate()
        return ProcessOutput(-1, out or "", err or "", timed_out=True)
