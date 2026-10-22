"""CLI: `ai-orchestrator run "<tarefa>" --repo <caminho>`."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import get_args

import typer
from langgraph.types import Command

from ai_orchestrator.contracts import Specialist, TaskRequest
from ai_orchestrator.deps import default_deps
from ai_orchestrator.orchestration.workflow import build_graph, new_task_id
from ai_orchestrator.persistence.checkpoints import open_checkpointer

app = typer.Typer(help="Equipe autônoma de agentes de engenharia (LangGraph + Claude Code).", no_args_is_help=True)

EXIT_CODES = {"done": 0, "blocked": 2, "awaiting_approval": 3}

SpecialistChoice = Enum("SpecialistChoice", {name: name for name in get_args(Specialist)}, type=str)


def _execute(deps, task_id: str, graph_input: dict | Command | None, *, awaiting_approval: bool = False) -> None:
    config = {"configurable": {"thread_id": task_id}, "recursion_limit": 100}
    with open_checkpointer(deps.settings.workspaces_root) as saver:
        graph = build_graph(deps).compile(checkpointer=saver)
        if awaiting_approval and "approval" not in graph.get_state(config).next:
            typer.echo(f"{task_id} não está aguardando aprovação.", err=True)
            raise typer.Exit(1)
        for update in graph.stream(graph_input, config, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    continue  # the pause itself; request_approval already logged it
                for event in (delta or {}).get("events", []):
                    typer.echo(f"[{node}] {event['message']}")
        final = graph.get_state(config).values

    status = final.get("status", "?")
    typer.echo("")
    typer.echo(f"Resultado: {status}" + (f" — {final.get('blocked_reason')}" if status == "blocked" else ""))
    if status == "awaiting_approval":
        files = ", ".join((final.get("validation") or {}).get("needs_confirmation", []))
        typer.echo(f"Exige confirmação: {files}")
        typer.echo(f"Revise o diff e rode `aio approve {task_id}` (commita) ou `aio reject {task_id}`.")
    typer.echo(f"Tentativas: {final.get('attempts', 0)} · Custo: US$ {final.get('cost_usd', 0.0):.2f}")
    if final.get("workspace"):
        typer.echo(f"Branch: {final['workspace']['branch']}")
    if final.get("report_path"):
        typer.echo(f"Relatório: {final['report_path']}")
    raise typer.Exit(EXIT_CODES.get(status, 1))


@app.command()
def run(
    task: str = typer.Argument(..., help="O que deve ser feito, em linguagem natural."),
    repo: Path | None = typer.Option(None, "--repo", "-r", help="Repositório Git alvo (padrão: pasta atual)."),
    base: str = typer.Option("HEAD", "--base", "-b", help="Ref base do worktree."),
    check: list[str] | None = typer.Option(None, "--check", "-c", help="Comando de validação (repetível). Sobrepõe o planner."),
    allow_path: list[str] | None = typer.Option(None, "--allow-path", "-a", help="Glob autorizado (repetível). Sobrepõe o planner."),
    with_: list[SpecialistChoice] | None = typer.Option(None, "--with", "-w",
                                                        help="Força um especialista (repetível)."),
    config: Path | None = typer.Option(None, "--config", help="Arquivo de configuração alternativo."),
) -> None:
    """Executa uma tarefa de ponta a ponta até cumprir os critérios ou atingir um limite."""
    deps = default_deps(config)
    request = TaskRequest(task=task, repo_path=str((repo or Path.cwd()).resolve()), base_ref=base,
                          checks=check or [], allowed_paths=allow_path or [],
                          specialists=[s.value for s in with_ or []])
    task_id = new_task_id()
    typer.echo(f"{task_id} · workspaces em {deps.settings.workspaces_root}")
    _execute(deps, task_id, {"task_id": task_id, "request": request.model_dump()})


@app.command()
def resume(
    task_id: str = typer.Argument(..., help="ID da tarefa interrompida."),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Retoma uma tarefa do último checkpoint (ex.: depois de fechar o terminal)."""
    _execute(default_deps(config), task_id, None)


@app.command()
def approve(
    task_id: str = typer.Argument(..., help="ID da tarefa aguardando aprovação."),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Aprova uma alteração em caminho que exige confirmação (ex.: CI/CD) e faz o commit no branch da tarefa."""
    _execute(default_deps(config), task_id, Command(resume={"approved": True}), awaiting_approval=True)


@app.command()
def reject(
    task_id: str = typer.Argument(..., help="ID da tarefa aguardando aprovação."),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Rejeita a alteração: a tarefa termina bloqueada, sem commit; o worktree fica para inspeção."""
    _execute(default_deps(config), task_id, Command(resume={"approved": False}), awaiting_approval=True)
