"""Adapter that runs an agent role through the local Claude Code CLI (`claude -p`).

Uses the account Claude Code is logged into (subscription). ANTHROPIC_API_KEY is
removed from the child environment so the run is not silently billed to the API.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_orchestrator.execution.process import run_process, sanitized_env
from ai_orchestrator.models.providers import AgentCall, AgentError, AgentResponse

# Auth variables Claude Code itself may need; everything else credential-like is stripped.
_PASSTHROUGH_ENV = ("CLAUDE_CODE_OAUTH_TOKEN",)


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline Pydantic $defs so the schema is self-contained for --json-schema."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


class ClaudeCodeProvider:
    def __init__(self, executable: str | None = None):
        self._executable = executable

    @property
    def executable(self) -> str:
        exe = self._executable or shutil.which("claude")
        if not exe:
            raise AgentError("CLI 'claude' não encontrada no PATH.")
        return exe

    def build_args(self, call: AgentCall, settings_path: Path) -> list[str]:
        schema = json.dumps(inline_refs(call.output_model.model_json_schema()), ensure_ascii=False)
        args = [
            self.executable,
            "-p",
            "--output-format", "json",
            "--model", call.model,
            "--json-schema", schema,
            "--settings", str(settings_path),
            # File tools confined to the worktree; user and project settings ignored
            # (only --settings applies); no user plugins, hooks or MCP servers.
            "--restricted",
            "--setting-sources", "project",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--permission-mode", call.tool_profile.permission_mode,
            "--permission-prompts", "none",
            "--tools", ",".join(call.tool_profile.tools),
            "--append-system-prompt", call.system_prompt,
        ]
        if call.effort:
            args += ["--effort", call.effort]
        if call.max_budget_usd:
            args += ["--max-budget-usd", str(call.max_budget_usd)]
        if call.resume_session_id:
            args += ["--resume", call.resume_session_id]
        return args

    def run(self, call: AgentCall) -> AgentResponse:
        settings_path = Path(call.scratch_dir) / f"claude-settings-{call.role}.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(
                {
                    "permissions": {
                        "allow": call.tool_profile.allow,
                        "deny": call.deny_rules + call.tool_profile.deny,
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        env = sanitized_env({k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ})

        out = run_process(
            self.build_args(call, settings_path),
            cwd=call.cwd,
            timeout=call.timeout_seconds,
            stdin=call.prompt,
            env=env,
        )
        if out.timed_out:
            raise AgentError(f"{call.role}: claude -p excedeu {call.timeout_seconds}s")

        data = _parse_result(out.stdout)
        if data is None:
            raise AgentError(f"{call.role}: saída inválida do claude -p (exit {out.returncode}): {out.stderr[-2000:]}")

        cost = float(data.get("total_cost_usd") or 0.0)
        session_id = data.get("session_id")
        if data.get("is_error") or data.get("subtype") != "success":
            raise AgentError(
                f"{call.role}: claude -p terminou com '{data.get('subtype')}': {str(data.get('result'))[:2000]}",
                cost_usd=cost,
                session_id=session_id,
            )

        structured = data.get("structured_output")
        if structured is None:
            try:
                structured = json.loads(data.get("result") or "")
            except json.JSONDecodeError as exc:
                raise AgentError(f"{call.role}: resposta sem saída estruturada", cost, session_id) from exc
        try:
            output = call.output_model.model_validate(structured)
        except ValidationError as exc:
            raise AgentError(f"{call.role}: saída fora do contrato: {exc}", cost, session_id) from exc

        return AgentResponse(output=output, session_id=session_id, cost_usd=cost, raw=data)


def _parse_result(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.strip().splitlines()):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    return None
