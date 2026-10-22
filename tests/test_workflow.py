"""End-to-end graph runs against a real temporary git repo, with scripted agents."""

import json
import subprocess
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from ai_orchestrator.contracts import TaskRequest
from ai_orchestrator.orchestration.workflow import build_graph

from conftest import FakeProvider


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


def test_invalid_repo_is_blocked_with_report(tmp_path, make_deps):
    provider = FakeProvider()
    not_repo = tmp_path / "nope"
    not_repo.mkdir()
    state = run_task(make_deps(provider), not_repo)

    assert state["status"] == "blocked"
    assert Path(state["report_path"]).exists()
    assert provider.calls == []
