"""Engineering workflow as a persistent LangGraph state machine.

    intake -> discovery -> setup_workspace -> planning -> implement -> validate -> review -> gate
                                                              ^             |                  |
                                                              |             +-- (falhou) ----> |
                                                              +---------------- fix -----------+
    gate -> report (done | blocked)

Agents decide where there is ambiguity; everything else is deterministic code.
"""

from __future__ import annotations

import functools
import os
import secrets
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Callable

from langgraph.graph import END, START, StateGraph

from ai_orchestrator.agents import implementer, planner, reviewer
from ai_orchestrator.contracts import (
    Plan,
    ReviewVerdict,
    RunnerContract,
    TaskRequest,
    ValidationReport,
)
from ai_orchestrator.deps import Deps, default_deps
from ai_orchestrator.execution.git_workspace import Workspace
from ai_orchestrator.models.providers import AgentError
from ai_orchestrator.orchestration.policies import decide, split_commands
from ai_orchestrator.orchestration.state import EngineeringState
from ai_orchestrator.persistence.tasks import write_report
from ai_orchestrator.validation.acceptance import validate_workspace

MANIFESTS = {
    "composer.json", "package.json", "pubspec.yaml", "pyproject.toml", "requirements.txt",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile",
    "Dockerfile", "docker-compose.yml", "compose.yaml", "Makefile", "phpunit.xml",
    "artisan", "vite.config.ts", "vite.config.js", "tsconfig.json", "analysis_options.yaml",
}
INSTRUCTION_FILES = {"CLAUDE.md", "AGENTS.md", "README.md", "CONTRIBUTING.md"}


def new_task_id() -> str:
    return f"TASK-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def _event(node: str, message: str, **data) -> dict:
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "node": node, "message": message, **data}


def _blocked(node: str, reason: str, **extra) -> dict:
    return {"status": "blocked", "blocked_reason": reason, "events": [_event(node, f"bloqueado: {reason}")], **extra}


def guarded(node: str) -> Callable:
    """Unexpected errors block the task instead of crashing the run."""

    def wrap(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def inner(state: EngineeringState, deps: Deps) -> dict:
            try:
                return fn(state, deps)
            except AgentError as exc:
                return _blocked(node, str(exc), cost_usd=state.get("cost_usd", 0.0) + exc.cost_usd)
            except Exception as exc:  # noqa: BLE001 - surfaced in the report
                return _blocked(node, f"{type(exc).__name__}: {exc}")

        return inner

    return wrap


def _workspace(state: EngineeringState) -> Workspace:
    return Workspace(**state["workspace"])


def _denial_events(node: str, resp) -> list[dict]:
    """Tool calls the policy blocked during an agent run (from the provider's raw output)."""
    denials = (resp.raw or {}).get("permission_denials") or []
    return [_event(node, f"ação negada pela política: {d.get('tool_name')} {d.get('tool_input')}") for d in denials[:10]]


# --- nodes -----------------------------------------------------------------


def intake(state: EngineeringState, deps: Deps) -> dict:
    task_id = state.get("task_id") or new_task_id()
    base = {"task_id": task_id, "attempts": 0, "cost_usd": 0.0}
    try:
        request = TaskRequest.model_validate(state["request"])
        repo = deps.workspaces.resolve_repo(request.repo_path)
        base_sha = deps.workspaces.resolve_ref(repo, request.base_ref)
    except Exception as exc:  # noqa: BLE001
        return {**base, **_blocked("intake", f"solicitação inválida: {exc}")}

    events = [_event("intake", f"repositório {repo} @ {base_sha[:10]}")]
    if deps.workspaces.has_uncommitted_changes(repo):
        events.append(_event("intake", "aviso: alterações não commitadas no repositório não entram no workspace"))
    return {
        **base,
        "request": request.model_copy(update={"repo_path": repo}).model_dump(),
        "base_sha": base_sha,
        "status": "intake",
        "events": events,
    }


@guarded("discovery")
def discovery(state: EngineeringState, deps: Deps) -> dict:
    files = deps.workspaces.tracked_files(state["request"]["repo_path"], state["base_sha"])
    paths = [PurePosixPath(f) for f in files]
    facts = {
        "file_count": len(files),
        "top_level": sorted({p.parts[0] for p in paths})[:80],
        "manifests": sorted(str(p) for p in paths if p.name in MANIFESTS and len(p.parts) <= 3)[:40],
        "instruction_files": sorted(str(p) for p in paths if p.name in INSTRUCTION_FILES and len(p.parts) <= 3),
        "has_tests_dir": any(part.lower() in ("test", "tests", "spec", "__tests__") for p in paths for part in p.parts[:2]),
    }
    return {"discovery": facts, "events": [_event("discovery", f"{len(files)} arquivos; manifests: {facts['manifests'][:6]}")]}


@guarded("workspace")
def prepare_workspace(state: EngineeringState, deps: Deps) -> dict:
    ws = deps.workspaces.create(state["request"]["repo_path"], state["task_id"], state["base_sha"])
    return {"workspace": ws.to_dict(), "events": [_event("workspace", f"worktree {ws.path} no branch {ws.branch}")]}


@guarded("plan")
def plan(state: EngineeringState, deps: Deps) -> dict:
    request = TaskRequest.model_validate(state["request"])
    ws = _workspace(state)
    resp = planner.run(deps, state["task_id"], request, state["discovery"], cwd=ws.path, scratch_dir=ws.task_dir)
    result: Plan = resp.output
    cost = state.get("cost_usd", 0.0) + resp.cost_usd
    events = [_event("plan", result.summary, cost_usd=resp.cost_usd), *_denial_events("plan", resp)]

    updates: dict = {}
    if request.allowed_paths:
        updates["allowed_paths"] = request.allowed_paths
    if request.checks:
        updates["validation_commands"] = request.checks
    else:
        allowed, rejected = split_commands(result.validation_commands, deps.policy.denied_command_patterns)
        updates["validation_commands"] = allowed
        events += [_event("plan", f"comando descartado pela política: {c}") for c in rejected]
    result = result.model_copy(update=updates)

    if result.needs_clarification:
        return _blocked("plan", "o plano precisa de esclarecimentos: " + " | ".join(result.needs_clarification),
                        plan=result.model_dump(), cost_usd=cost)
    if not result.validation_commands:
        return _blocked("plan", "nenhum comando de validação objetivo; informe --check", plan=result.model_dump(), cost_usd=cost)

    contract = RunnerContract(
        task_id=state["task_id"],
        repository=request.repo_path,
        base_ref=request.base_ref,
        base_sha=state["base_sha"],
        workspace_id=os.path.basename(ws.task_dir),
        allowed_paths=result.allowed_paths,
        denied_paths=deps.policy.denied_paths,
        timeout_seconds=deps.settings.budgets.validation_timeout_seconds,
        max_retries=deps.settings.budgets.max_attempts,
    )
    return {"plan": result.model_dump(), "contract": contract.model_dump(), "status": "planned", "cost_usd": cost, "events": events}


@guarded("implement")
def implement(state: EngineeringState, deps: Deps) -> dict:
    attempt = state.get("attempts", 0) + 1
    ws = _workspace(state)
    session_id = state.get("implementer_session_id")
    cost = state.get("cost_usd", 0.0)
    try:
        resp = implementer.run(
            deps,
            state["task_id"],
            TaskRequest.model_validate(state["request"]),
            Plan.model_validate(state["plan"]),
            attempt=attempt,
            feedback=state.get("feedback", ""),
            session_id=session_id,
            cwd=ws.path,
            scratch_dir=ws.task_dir,
        )
        implementation, session_id, cost = resp.output.model_dump(), resp.session_id, cost + resp.cost_usd
        events = [_event("implement", f"tentativa {attempt}: {implementation['status']} — {implementation['summary']}"),
                  *_denial_events("implement", resp)]
    except AgentError as exc:
        # The workspace may still hold useful changes; validation decides, not the crash.
        implementation = {"status": "error", "summary": str(exc)}
        session_id, cost = exc.session_id or session_id, cost + exc.cost_usd
        events = [_event("implement", f"tentativa {attempt}: erro do agente — {exc}")]
    return {
        "attempts": attempt,
        "implementation": implementation,
        "implementer_session_id": session_id,
        "cost_usd": cost,
        "review": None,
        "status": "implemented",
        "events": events,
    }


@guarded("validate")
def validate(state: EngineeringState, deps: Deps) -> dict:
    plan_ = Plan.model_validate(state["plan"])
    report = validate_workspace(
        deps.workspaces,
        _workspace(state),
        deps.runner,
        allowed_paths=plan_.allowed_paths,
        denied_paths=deps.policy.denied_paths,
        commands=plan_.validation_commands,
        timeout=deps.settings.budgets.validation_timeout_seconds,
    )
    summary = ", ".join(f"{c.command} -> {c.exit_code}" for c in report.commands) or "nenhum comando executado"
    return {
        "validation": report.model_dump(),
        "validation_passed": report.passed,
        "events": [_event("validate", f"{len(report.changed_files)} arquivos alterados; {summary}; "
                          f"{len(report.scope_violations)} violações de escopo")],
    }


@guarded("review")
def review(state: EngineeringState, deps: Deps) -> dict:
    ws = _workspace(state)
    cost = state.get("cost_usd", 0.0)
    try:
        resp = reviewer.run(
            deps,
            state["task_id"],
            TaskRequest.model_validate(state["request"]),
            Plan.model_validate(state["plan"]),
            state.get("implementation", {}),
            ValidationReport.model_validate(state["validation"]),
            deps.workspaces.diff(ws),
            cwd=ws.path,
            scratch_dir=ws.task_dir,
        )
    except AgentError as exc:
        return {"review": None, "cost_usd": cost + exc.cost_usd, "events": [_event("review", f"erro do revisor — {exc}")]}
    verdict: ReviewVerdict = resp.output
    label = "aprovado" if not verdict.blocking else "reprovado"
    events = [_event("review", f"{label}: {verdict.summary}"), *_denial_events("review", resp)]
    return {"review": verdict.model_dump(), "cost_usd": cost + resp.cost_usd, "events": events}


@guarded("gate")
def gate(state: EngineeringState, deps: Deps) -> dict:
    review_data = state.get("review")
    result = decide(
        ValidationReport.model_validate(state["validation"]),
        ReviewVerdict.model_validate(review_data) if review_data else None,
        attempts=state.get("attempts", 0),
        cost_usd=state.get("cost_usd", 0.0),
        budgets=deps.settings.budgets,
    )
    update = {
        "decision": result.decision,
        "gate_reason": result.reason,
        "feedback": result.feedback,
        "events": [_event("gate", f"{result.decision}: {result.reason}")],
    }
    if result.decision == "blocked":
        update.update(status="blocked", blocked_reason=result.reason)
    return update


def report(state: EngineeringState, deps: Deps) -> dict:
    update: dict = {}
    if state.get("decision") == "done" and state.get("status") != "blocked":
        update["status"] = "done"
        if deps.settings.commit_on_success and state.get("workspace"):
            try:
                update["commit_sha"] = deps.workspaces.commit(
                    _workspace(state), f"{state['task_id']}: {state['request']['task'][:60]}"
                )
            except Exception as exc:  # noqa: BLE001
                update["events"] = [_event("report", f"commit local falhou: {exc}")]
    final = {**state, **update, "events": state.get("events", []) + update.get("events", [])}
    update["report_path"] = str(write_report(final, deps.settings.workspaces_root))
    return update


# --- graph -----------------------------------------------------------------


def _unless_blocked(next_node: str) -> Callable[[EngineeringState], str]:
    return lambda state: "report" if state.get("status") == "blocked" else next_node


def build_graph(deps: Deps) -> StateGraph:
    builder = StateGraph(EngineeringState)
    for name, fn in [
        ("intake", intake),
        ("discovery", discovery),
        ("setup_workspace", prepare_workspace),
        ("planning", plan),
        ("implement", implement),
        ("validate", validate),
        ("review", review),
        ("gate", gate),
        ("report", report),
    ]:
        builder.add_node(name, functools.partial(fn, deps=deps))

    builder.add_edge(START, "intake")
    builder.add_conditional_edges("intake", _unless_blocked("discovery"), ["discovery", "report"])
    builder.add_conditional_edges("discovery", _unless_blocked("setup_workspace"), ["setup_workspace", "report"])
    builder.add_conditional_edges("setup_workspace", _unless_blocked("planning"), ["planning", "report"])
    builder.add_conditional_edges("planning", _unless_blocked("implement"), ["implement", "report"])
    builder.add_conditional_edges("implement", _unless_blocked("validate"), ["validate", "report"])
    builder.add_conditional_edges(
        "validate",
        lambda s: "report" if s.get("status") == "blocked" else ("review" if s.get("validation_passed") else "gate"),
        ["review", "gate", "report"],
    )
    builder.add_conditional_edges("review", _unless_blocked("gate"), ["gate", "report"])
    builder.add_conditional_edges(
        "gate",
        lambda s: {"fix": "implement", "done": "report"}.get(s.get("decision"), "report"),
        ["implement", "report"],
    )
    builder.add_edge("report", END)
    return builder


# Entry point for `langgraph dev` / LangSmith Deployment (see langgraph.json).
# The server injects its own checkpointer; the CLI compiles with SQLite instead.
graph = build_graph(default_deps()).compile()
