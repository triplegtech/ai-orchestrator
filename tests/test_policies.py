from ai_orchestrator.config import Budgets, load_policy
from ai_orchestrator.contracts import CommandResult, CriterionCheck, ReviewIssue, ReviewVerdict, ValidationReport
from ai_orchestrator.orchestration.policies import check_scope, decide, path_matches, split_commands

POLICY = load_policy()


def ok_cmd(code=0):
    return CommandResult(command="t", exit_code=code, duration_seconds=0.1, output_tail="")


def verdict(approved=True, met=True, issues=()):
    return ReviewVerdict(approved=approved, summary="s",
                         criteria=[CriterionCheck(criterion="c", met=met, evidence="e")], issues=list(issues))


def test_path_matching():
    assert path_matches("app/Services/Token.php", ["app/"])
    assert path_matches("app/Services/Token.php", ["app"])
    assert path_matches("app/Services/Token.php", ["app/**/*.php"])
    assert path_matches("tests/Feature/X.php", ["tests/**"])
    assert not path_matches("config/app.php", ["app/", "tests/**"])
    assert path_matches("src\\a.py", ["src/*.py"])


def test_scope_denied_paths_win_over_allowed():
    violations = check_scope([".env", "app/x.php", "routes/web.php", "config/.env.local"], ["app/", ".env"], POLICY.denied_paths)
    reasons = {v.path: v.reason for v in violations}
    assert "proibido" in reasons[".env"]
    assert "proibido" in reasons["config/.env.local"]
    assert "fora" in reasons["routes/web.php"]
    assert "app/x.php" not in reasons


def test_dangerous_commands_are_rejected():
    allowed, rejected = split_commands(
        ["php artisan test", "npm test -- --run", "git push origin main", "curl http://x", "rm -rf vendor", "npm run deploy"],
        POLICY.denied_command_patterns,
    )
    assert allowed == ["php artisan test", "npm test -- --run"]
    assert len(rejected) == 4


def test_gate_done_requires_validation_and_review():
    passed = ValidationReport(changed_files=["a"], commands=[ok_cmd()])
    assert decide(passed, verdict(), 1, 0.0, Budgets()).decision == "done"
    assert decide(passed, verdict(met=False), 1, 0.0, Budgets()).decision == "fix"
    assert decide(passed, verdict(issues=[ReviewIssue(severity="major", description="x")]), 1, 0.0, Budgets()).decision == "fix"
    assert decide(passed, verdict(issues=[ReviewIssue(severity="minor", description="x")]), 1, 0.0, Budgets()).decision == "done"


def test_gate_never_passes_without_evidence():
    assert not ValidationReport(changed_files=[], commands=[ok_cmd()]).passed
    assert not ValidationReport(changed_files=["a"], commands=[]).passed
    assert not ValidationReport(changed_files=["a"], commands=[ok_cmd(1)]).passed


def test_gate_limits():
    failed = ValidationReport(changed_files=["a"], commands=[ok_cmd(1)])
    assert decide(failed, None, 1, 0.0, Budgets(max_attempts=3)).decision == "fix"
    assert decide(failed, None, 3, 0.0, Budgets(max_attempts=3)).decision == "blocked"
    assert decide(failed, None, 1, 50.0, Budgets(max_cost_usd=10)).decision == "blocked"
    passed = ValidationReport(changed_files=["a"], commands=[ok_cmd()])
    assert decide(passed, None, 1, 0.0, Budgets()).decision == "blocked"
