"""Final task report: report.json (machine) and report.md (human) in the task folder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _md_report(s: dict[str, Any]) -> str:
    req = s.get("request", {})
    plan = s.get("plan") or {}
    validation = s.get("validation") or {}
    review = s.get("review") or {}
    ws = s.get("workspace") or {}
    status = s.get("status", "?")

    lines = [
        f"# {s.get('task_id', '?')} — {status.upper()}",
        "",
        f"**Tarefa:** {req.get('task', '')}",
        f"**Repositório:** `{req.get('repo_path', '')}` @ `{(s.get('base_sha') or '')[:10]}`",
        f"**Tentativas:** {s.get('attempts', 0)} · **Custo:** US$ {s.get('cost_usd', 0.0):.2f}",
    ]
    if status == "blocked":
        lines.append(f"**Motivo do bloqueio:** {s.get('blocked_reason', '')}")
    if s.get("setup"):
        lines += ["", f"## Preparação do ambiente (stack: {(s.get('discovery') or {}).get('stack')})"]
        for c in s["setup"]:
            lines.append(f"- `{c['command']}` → exit {c['exit_code']}{' (timeout)' if c.get('timed_out') else ''}")
            if c["exit_code"] != 0:
                lines += ["", "```", c.get("output_tail", "")[-2000:], "```"]
    if plan:
        lines += ["", "## Plano", plan.get("summary", ""), "", "### Critérios de aceite"]
        lines += [f"- {c}" for c in plan.get("acceptance_criteria", [])]
        lines += ["", "### Escopo autorizado"] + [f"- `{p}`" for p in plan.get("allowed_paths", [])]
    for brief in s.get("briefs") or []:
        lines += ["", f"## Especialista: {brief['role']}", brief.get("summary", "")]
        lines += [f"- {g}" for g in brief.get("guidance", [])]
        if brief.get("risks"):
            lines += ["", "**Riscos / passos manuais:**"] + [f"- {r}" for r in brief["risks"]]
    if validation:
        lines += ["", "## Validação (executada pelo orquestrador)"]
        lines += [f"- `{c['command']}` → exit {c['exit_code']}{' (timeout)' if c.get('timed_out') else ''} em {c['duration_seconds']}s"
                  for c in validation.get("commands", [])]
        lines += ["", "### Arquivos alterados"] + [f"- `{p}`" for p in validation.get("changed_files", [])]
        lines += [f"- ⚠ `{v['path']}`: {v['reason']}" for v in validation.get("scope_violations", [])]
    if review:
        lines += ["", "## Revisão independente", review.get("summary", "")]
        lines += [f"- [{'x' if c['met'] else ' '}] {c['criterion']} — {c['evidence']}" for c in review.get("criteria", [])]
        lines += [f"- **{i['severity']}** {i.get('file') or ''}: {i['description']}" for i in review.get("issues", [])]
    if ws:
        repo, branch = req.get("repo_path", ""), ws.get("branch", "")
        lines += [
            "",
            "## Como revisar e integrar",
            f"Worktree: `{ws.get('path')}` · branch `{branch}`" + (f" · commit `{s['commit_sha'][:10]}`" if s.get("commit_sha") else ""),
            "",
            "```powershell",
            f'git -C "{repo}" diff {(s.get("base_sha") or "")[:10]}...{branch}',
            f'git -C "{repo}" merge --no-ff {branch}      # só depois de revisar',
            f'git -C "{repo}" worktree remove "{ws.get("path")}"',
            "```",
        ]
    lines += ["", "## Linha do tempo"] + [f"- `{e['at']}` **{e['node']}** {e['message']}" for e in s.get("events", [])]
    return "\n".join(lines) + "\n"


def write_report(state: dict[str, Any], workspaces_root: Path) -> Path:
    task_dir = Path(state.get("workspace", {}).get("task_dir") or Path(workspaces_root) / state["task_id"])
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "report.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    path = task_dir / "report.md"
    path.write_text(_md_report(state), encoding="utf-8")
    return path
