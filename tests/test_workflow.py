"""End-to-end graph runs against a real temporary git repo, with scripted agents."""

import json
import subprocess
from pathlib import Path

import pytest
import typer
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ai_orchestrator.app import _execute
from ai_orchestrator.contracts import TaskRequest
from ai_orchestrator.orchestration.workflow import build_graph

from conftest import CHECK_COMMAND, FakeProvider

PYTHON = CHECK_COMMAND.split(" check.py")[0]


def run_task(deps, repo: Path, **request):
    graph = build_graph(deps).compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}, "recursion_limit": 100}
    req = TaskRequest(task="crie hello.txt com ok", repo_path=str(repo), **request)
    graph.invoke({"task_id": "TASK-TEST", "request": req.model_dump()}, config)
    return graph.get_state(config).values


def test_happy_path_commits_on_task_branch(repo, make_deps):
    provider = FakeProvider(writes=["ok"])
    state = run_task(make_deps(provider), repo)

    assert state["status"] == "done", state.get("blocked_reason")
    assert state["attempts"] == 1
    assert state["validation"]["changed_files"] == ["hello.txt"]
    # The planner's `git push` proposal was filtered out by policy before execution.
    assert all("push" not in c for c in state["plan"]["validation_commands"])
    assert state["commit_sha"]
    # Original repo untouched; the change lives only on the task branch.
    assert not (repo / "hello.txt").exists()
    shown = subprocess.run(["git", "-C", str(repo), "show", "agents/task-test:hello.txt"],
                           capture_output=True, text=True, check=True)
    assert shown.stdout.strip() == "ok"
    report = json.loads((Path(state["workspace"]["task_dir"]) / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "done"
    assert Path(state["report_path"]).read_text(encoding="utf-8").startswith("# TASK-TEST — DONE")


def test_build_artifacts_are_neither_scope_violations_nor_committed(repo, make_deps):
    state = run_task(make_deps(FakeProvider(writes=["ok"], artifacts=True)), repo)

    assert state["status"] == "done", state.get("blocked_reason")
    assert state["validation"]["changed_files"] == ["hello.txt"]
    tree = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "agents/task-test"],
                          capture_output=True, text=True, check=True).stdout
    assert "__pycache__" not in tree


def test_failed_validation_retries_with_feedback_and_resumes_session(repo, make_deps):
    provider = FakeProvider(writes=["wrong", "ok"])
    state = run_task(make_deps(provider), repo)

    assert state["status"] == "done", state.get("blocked_reason")
    assert state["attempts"] == 2
    impl_calls = [c for c in provider.calls if c.role == "implementer"]
    assert impl_calls[0].resume_session_id is None
    assert impl_calls[1].resume_session_id == "session-implementer"
    assert "falhou (exit 1)" in impl_calls[1].prompt
    assert impl_calls[1].model == "opus"  # escalated on retry
    assert [c.role for c in provider.calls].count("reviewer") == 1  # review only after validation passes


def test_scope_violation_blocks_after_budget(repo, make_deps):
    provider = FakeProvider(writes=["ok", "ok"], write_path=".env")
    state = run_task(make_deps(provider, max_attempts=2), repo, checks=["git status"])

    assert state["status"] == "blocked"
    assert "limite de 2 tentativas" in state["blocked_reason"]
    assert state["validation"]["scope_violations"][0]["path"] == ".env"


def test_clarification_blocks_before_touching_code(repo, make_deps):
    provider = FakeProvider(clarification=["Qual banco usar?"])
    state = run_task(make_deps(provider), repo)

    assert state["status"] == "blocked"
    assert "Qual banco usar?" in state["blocked_reason"]
    assert [c.role for c in provider.calls] == ["planner"]


def test_review_rejection_blocks_when_out_of_attempts(repo, make_deps):
    provider = FakeProvider(writes=["ok"], approve=False)
    state = run_task(make_deps(provider, max_attempts=1), repo)

    assert state["status"] == "blocked"
    assert "revisão reprovada" in state["blocked_reason"]
    assert not state.get("commit_sha")


def test_stack_preset_prepares_workspace_and_supplies_default_checks(repo, make_deps):
    presets = {"demo": {"detect": ["check.py", "README.md"],
                        "setup": [f"{PYTHON} -c \"open('setup.done', 'w').close()\""],
                        "checks": [CHECK_COMMAND]}}
    # The planner proposes only a forbidden command, so the preset's checks take over.
    provider = FakeProvider(plan_checks=["git push origin main"])
    state = run_task(make_deps(provider, presets=presets), repo)

    assert state["status"] == "done", state.get("blocked_reason")
    assert state["discovery"]["stack"] == "demo"
    assert state["setup"][0]["exit_code"] == 0
    assert state["workspace"]["baseline"] == ["setup.done"]
    assert state["validation"]["changed_files"] == ["hello.txt"]
    assert state["plan"]["validation_commands"] == [CHECK_COMMAND]
    tree = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "agents/task-test"],
                          capture_output=True, text=True, check=True).stdout
    assert "setup.done" not in tree
    assert "Ambiente do workspace" in provider.calls[0].prompt


def test_failed_setup_blocks_before_any_agent_call(repo, make_deps):
    presets = {"demo": {"detect": ["check.py"], "setup": [f"{PYTHON} -c \"raise SystemExit(3)\""]}}
    provider = FakeProvider()
    state = run_task(make_deps(provider, presets=presets), repo)

    assert state["status"] == "blocked"
    assert "preparação do ambiente falhou" in state["blocked_reason"]
    assert provider.calls == []
    assert "Preparação do ambiente" in Path(state["report_path"]).read_text(encoding="utf-8")


def test_no_specialists_unless_requested(repo, make_deps):
    provider = FakeProvider()
    state = run_task(make_deps(provider), repo)

    assert state["status"] == "done", state.get("blocked_reason")
    assert [c.role for c in provider.calls] == ["planner", "implementer", "reviewer"]
    assert not state.get("briefs")


def test_specialists_guide_implementer_and_add_criteria(repo, make_deps):
    # The planner asks for design; the user forces devops on top.
    provider = FakeProvider(specialists=["design"])
    state = run_task(make_deps(provider), repo, specialists=["devops", "design"])

    assert state["status"] == "done", state.get("blocked_reason")
    assert [c.role for c in provider.calls] == ["planner", "design", "devops", "implementer", "reviewer"]
    assert [b["role"] for b in state["briefs"]] == ["design", "devops"]
    assert state["plan"]["acceptance_criteria"] == ["hello.txt contém ok", "critério de design", "critério de devops"]
    assert state["plan"]["allowed_paths"] == ["hello.txt"]  # specialists never widen the scope
    implementer_prompt, reviewer_prompt = provider.calls[3].prompt, provider.calls[4].prompt
    assert "siga o padrão de design" in implementer_prompt and "siga o padrão de devops" in implementer_prompt
    assert "critério de devops" in reviewer_prompt and "Orientações dos especialistas" in reviewer_prompt
    assert "Especialista: design" in Path(state["report_path"]).read_text(encoding="utf-8")


def test_specialist_clarification_blocks_before_implementation(repo, make_deps):
    provider = FakeProvider(specialists=["devops"], brief_questions=["Onde roda o worker?"])
    state = run_task(make_deps(provider), repo)

    assert state["status"] == "blocked"
    assert "devops: Onde roda o worker?" in state["blocked_reason"]
    assert [c.role for c in provider.calls] == ["planner", "devops"]
    assert state["briefs"][0]["role"] == "devops"


CI_FILE = ".github/workflows/tests.yml"


def start_ci_task(deps, repo: Path):
    """Runs a task that edits a confirm_paths file; returns the paused graph and its config."""
    graph = build_graph(deps).compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}, "recursion_limit": 100}
    req = TaskRequest(task="crie o workflow de CI", repo_path=str(repo),
                      allowed_paths=[".github/workflows/**"], checks=["git status"])
    graph.invoke({"task_id": "TASK-TEST", "request": req.model_dump()}, config)
    return graph, config


def test_confirm_paths_pause_before_commit_until_approved(repo, make_deps):
    graph, config = start_ci_task(make_deps(FakeProvider(write_path=CI_FILE)), repo)

    state = graph.get_state(config)
    assert state.next == ("approval",)
    assert state.values["status"] == "awaiting_approval"
    assert state.values["validation"]["needs_confirmation"] == [CI_FILE]
    assert not state.values.get("commit_sha")
    report = Path(state.values["report_path"]).read_text(encoding="utf-8")
    assert "Aguardando aprovação" in report and "aio approve TASK-TEST" in report

    graph.invoke(Command(resume={"approved": True}), config)
    state = graph.get_state(config).values
    assert state["status"] == "done", state.get("blocked_reason")
    assert state["approval"] == {"approved": True, "files": [CI_FILE]}
    assert state["commit_sha"]
    shown = subprocess.run(["git", "-C", str(repo), "show", f"agents/task-test:{CI_FILE}"],
                           capture_output=True, text=True, check=True)
    assert shown.stdout.strip() == "ok"


def test_rejected_confirmation_blocks_without_commit(repo, make_deps):
    graph, config = start_ci_task(make_deps(FakeProvider(write_path=CI_FILE)), repo)

    graph.invoke(Command(resume={"approved": False}), config)
    state = graph.get_state(config).values
    assert state["status"] == "blocked"
    assert "rejeitada pelo usuário" in state["blocked_reason"]
    assert not state.get("commit_sha")


def test_cli_pauses_then_approve_resumes_from_sqlite_checkpoint(repo, make_deps):
    # Same path as `aio run` + `aio approve`: two separate graphs over the SQLite checkpointer.
    deps = make_deps(FakeProvider(write_path=CI_FILE))
    req = TaskRequest(task="crie o workflow de CI", repo_path=str(repo),
                      allowed_paths=[".github/workflows/**"], checks=["git status"])
    with pytest.raises(typer.Exit) as paused:
        _execute(deps, "TASK-CLI", {"task_id": "TASK-CLI", "request": req.model_dump()})
    assert paused.value.exit_code == 3

    with pytest.raises(typer.Exit) as approved:
        _execute(deps, "TASK-CLI", Command(resume={"approved": True}), awaiting_approval=True)
    assert approved.value.exit_code == 0
    shown = subprocess.run(["git", "-C", str(repo), "show", f"agents/task-cli:{CI_FILE}"],
                           capture_output=True, text=True, check=True)
    assert shown.stdout.strip() == "ok"
    # A finished task can't be approved again.
    with pytest.raises(typer.Exit) as again:
        _execute(deps, "TASK-CLI", Command(resume={"approved": True}), awaiting_approval=True)
    assert again.value.exit_code == 1


def test_invalid_repo_is_blocked_with_report(tmp_path, make_deps):
    provider = FakeProvider()
    not_repo = tmp_path / "nope"
    not_repo.mkdir()
    state = run_task(make_deps(provider), not_repo)

    assert state["status"] == "blocked"
    assert Path(state["report_path"]).exists()
    assert provider.calls == []
