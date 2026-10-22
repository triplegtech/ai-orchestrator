import json
from pathlib import Path

from ai_orchestrator.config import load_policy, load_settings
from ai_orchestrator.contracts import Plan, ReviewVerdict
from ai_orchestrator.execution.claude_code import ClaudeCodeProvider, inline_refs
from ai_orchestrator.execution.process import sanitized_env
from ai_orchestrator.models.providers import AgentCall
from ai_orchestrator.models.registry import ModelRegistry, TaskContext


def test_schema_is_self_contained():
    for model in (Plan, ReviewVerdict):
        text = json.dumps(inline_refs(model.model_json_schema()))
        assert "$ref" not in text and "$defs" not in text


def test_credentials_are_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    env = sanitized_env()
    assert not {"ANTHROPIC_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY"} & env.keys()
    assert any(k.upper() == "PATH" for k in env)


def test_registry_escalates_model_on_retry():
    registry = ModelRegistry(load_settings(), load_policy(), providers={})
    assert registry.get("implementer", TaskContext(attempt=1)).model == "sonnet"
    assert registry.get("implementer", TaskContext(attempt=2)).model == "opus"
    assert registry.get("planner").model == "opus"


def test_claude_args_isolate_user_config(tmp_path: Path):
    policy = load_policy()
    call = AgentCall(
        role="reviewer", system_prompt="s", prompt="p", cwd=str(tmp_path), output_model=ReviewVerdict,
        model="opus", tool_profile=policy.tool_profiles["review"], deny_rules=policy.claude_deny,
        timeout_seconds=10, scratch_dir=str(tmp_path), resume_session_id="abc",
    )
    args = ClaudeCodeProvider(executable="claude").build_args(call, tmp_path / "s.json")
    assert "--restricted" in args
    assert args[args.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in args
    assert args[args.index("--permission-prompts") + 1] == "none"
    assert args[args.index("--tools") + 1] == "Read,Glob,Grep,Bash"
    assert args[args.index("--resume") + 1] == "abc"
    assert not any("dangerously" in a for a in args)
