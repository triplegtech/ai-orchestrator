"""Pure policy checks: path scope, command filtering and the decision gate."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from ai_orchestrator.config import Budgets
from ai_orchestrator.contracts import ReviewVerdict, ScopeViolation, ValidationReport


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    pattern = pattern.replace("\\", "/").removeprefix("./")
    if pattern.endswith("/"):
        pattern += "**"
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(f"^{out}$", re.IGNORECASE)


def path_matches(path: str, patterns: list[str]) -> bool:
    path = path.replace("\\", "/").removeprefix("./")
    for pattern in patterns:
        if _glob_regex(pattern).match(path):
            return True
        # A bare directory name ("app") also covers everything below it.
        bare = pattern.replace("\\", "/").removeprefix("./").rstrip("/")
        if not any(ch in bare for ch in "*?") and path.lower().startswith(bare.lower() + "/"):
            return True
    return False


def check_scope(changed_files: list[str], allowed: list[str], denied: list[str]) -> list[ScopeViolation]:
    violations = []
    for path in changed_files:
        if path_matches(path, denied):
            violations.append(ScopeViolation(path=path, reason="caminho proibido pela política"))
        elif allowed and not path_matches(path, allowed):
            violations.append(ScopeViolation(path=path, reason="fora dos caminhos autorizados no plano"))
    return violations


def split_commands(commands: list[str], denied_patterns: list[str]) -> tuple[list[str], list[str]]:
    """Returns (allowed, rejected) validation commands."""
    allowed, rejected = [], []
    for command in commands:
        if any(re.search(p, command, re.IGNORECASE) for p in denied_patterns):
            rejected.append(command)
        else:
            allowed.append(command)
    return allowed, rejected


Decision = Literal["done", "fix", "blocked"]


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    reason: str
    feedback: str = ""


def _validation_feedback(report: ValidationReport) -> str:
    lines = []
    if not report.changed_files:
        lines.append("- Nenhum arquivo foi alterado no workspace.")
    for v in report.scope_violations:
        lines.append(f"- {v.path}: {v.reason}. Desfaça essa alteração.")
    if not report.commands:
        lines.append("- Nenhum comando de validação foi executado.")
    for c in report.commands:
        if c.timed_out:
            lines.append(f"- `{c.command}` excedeu o tempo limite.")
        elif c.exit_code != 0:
            lines.append(f"- `{c.command}` falhou (exit {c.exit_code}). Saída final:\n```\n{c.output_tail}\n```")
    return "Validação objetiva reprovada:\n" + "\n".join(lines)


def _review_feedback(review: ReviewVerdict) -> str:
    lines = [f"Revisão independente reprovou: {review.summary}"]
    lines += [f"- Critério não atendido: {c.criterion} ({c.evidence})" for c in review.criteria if not c.met]
    lines += [
        f"- [{i.severity}] {i.file or 'geral'}: {i.description}"
        for i in review.issues
        if i.severity in ("blocker", "major")
    ]
    return "\n".join(lines)


def decide(
    validation: ValidationReport,
    review: ReviewVerdict | None,
    attempts: int,
    cost_usd: float,
    budgets: Budgets,
) -> GateResult:
    """Decision gate: done only with objective evidence; otherwise fix or block."""
    if validation.passed and review is not None and not review.blocking:
        return GateResult("done", "validação e revisão aprovadas")

    if not validation.passed:
        reason, feedback = "validação reprovada", _validation_feedback(validation)
    elif review is None:
        # Nothing for the implementer to fix: the reviewer itself failed.
        return GateResult("blocked", "validação aprovada, mas a revisão independente não produziu veredito")
    else:
        reason, feedback = "revisão reprovada", _review_feedback(review)

    if cost_usd >= budgets.max_cost_usd:
        return GateResult("blocked", f"{reason}; orçamento esgotado (US$ {cost_usd:.2f})", feedback)
    if attempts >= budgets.max_attempts:
        return GateResult("blocked", f"{reason}; limite de {budgets.max_attempts} tentativas atingido", feedback)
    return GateResult("fix", reason, feedback)
