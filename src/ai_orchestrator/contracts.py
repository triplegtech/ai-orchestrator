"""Structured contracts exchanged between the orchestrator, agents and runners.

Agent outputs are validated against these schemas, but they are never proof on
their own: changed files and command results are re-checked by the executor.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Read-only consultants that run between planning and implementation when the task calls for them.
Specialist = Literal["design", "devops"]


class TaskRequest(BaseModel):
    task: str = Field(min_length=1)
    repo_path: str
    base_ref: str = "HEAD"
    # User-supplied validation commands override the planner's proposals.
    checks: list[str] = Field(default_factory=list)
    # User-supplied scope overrides the planner's proposal.
    allowed_paths: list[str] = Field(default_factory=list)
    # Specialists the user forces on, in addition to the ones the planner asks for.
    specialists: list[Specialist] = Field(default_factory=list)


class PlanStep(BaseModel):
    id: str
    description: str
    files: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    summary: str
    acceptance_criteria: list[str] = Field(min_length=1)
    steps: list[PlanStep]
    allowed_paths: list[str] = Field(
        description="Globs relativos à raiz do repositório que a implementação pode alterar."
    )
    validation_commands: list[str] = Field(
        description="Comandos de teste/lint/build que provam os critérios de aceite."
    )
    risks: list[str] = Field(default_factory=list)
    needs_clarification: list[str] = Field(
        default_factory=list,
        description="Perguntas que impedem implementar com segurança. Vazio se nenhuma.",
    )
    specialists: list[Specialist] = Field(
        default_factory=list,
        description="Especialistas a consultar antes da implementação: design (UI/UX), devops (infra/deploy). "
        "Vazio se nenhum for necessário.",
    )


class SpecialistBrief(BaseModel):
    """A specialist's guidance. Its acceptance criteria join the plan, so reviewer and gate enforce them."""

    summary: str
    guidance: list[str] = Field(description="Orientações concretas para o implementador, dentro do escopo autorizado.")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Critérios verificáveis adicionais que a revisão deve cobrar.",
    )
    risks: list[str] = Field(default_factory=list)
    needs_clarification: list[str] = Field(
        default_factory=list,
        description="Perguntas que impedem implementar com segurança. Vazio se nenhuma.",
    )


class CommandRun(BaseModel):
    command: str
    exit_code: int


class ImplementerResult(BaseModel):
    task_id: str
    status: Literal["implemented", "partial", "blocked"]
    summary: str
    changed_files: list[str]
    tests_run: list[CommandRun] = Field(default_factory=list)
    remaining_issues: list[str] = Field(default_factory=list)


class CommandResult(BaseModel):
    command: str
    exit_code: int
    duration_seconds: float
    output_tail: str
    timed_out: bool = False


class ScopeViolation(BaseModel):
    path: str
    reason: str


class ValidationReport(BaseModel):
    changed_files: list[str]
    scope_violations: list[ScopeViolation] = Field(default_factory=list)
    commands: list[CommandResult] = Field(default_factory=list)
    # Changed files under the policy's confirm_paths: they don't fail validation, they need human approval.
    needs_confirmation: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            bool(self.changed_files)
            and not self.scope_violations
            and bool(self.commands)
            and all(c.exit_code == 0 and not c.timed_out for c in self.commands)
        )


class CriterionCheck(BaseModel):
    criterion: str
    met: bool
    evidence: str


class ReviewIssue(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    file: str | None = None
    description: str


class ReviewVerdict(BaseModel):
    approved: bool
    summary: str
    criteria: list[CriterionCheck]
    issues: list[ReviewIssue] = Field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return (
            not self.approved
            or any(not c.met for c in self.criteria)
            or any(i.severity in ("blocker", "major") for i in self.issues)
        )


class RunnerContract(BaseModel):
    """What the control plane hands a runner. The runner enforces it."""

    task_id: str
    repository: str
    base_ref: str
    base_sha: str
    workspace_id: str
    allowed_paths: list[str]
    denied_paths: list[str]
    confirm_paths: list[str] = Field(default_factory=list)
    network_policy: Literal["restricted", "open"] = "restricted"
    timeout_seconds: int
    max_retries: int
