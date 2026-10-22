"""Persistent state of one engineering task. Values are plain JSON for checkpointing."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

Status = Literal["intake", "planned", "implemented", "awaiting_approval", "done", "blocked"]


class EngineeringState(TypedDict, total=False):
    request: dict[str, Any]          # TaskRequest
    task_id: str
    base_sha: str
    status: Status
    blocked_reason: str
    discovery: dict[str, Any]
    workspace: dict[str, Any]        # Workspace
    setup: list[dict[str, Any]]      # CommandResult of the stack preset's setup
    plan: dict[str, Any]             # Plan
    contract: dict[str, Any]         # RunnerContract
    briefs: list[dict[str, Any]]     # SpecialistBrief + "role", in consultation order
    attempts: int
    cost_usd: float
    implementer_session_id: str | None
    implementation: dict[str, Any]   # ImplementerResult, or {"status": "error", ...}
    validation: dict[str, Any]       # ValidationReport
    validation_passed: bool
    review: dict[str, Any] | None    # ReviewVerdict
    decision: Literal["done", "fix", "blocked"]
    gate_reason: str
    feedback: str
    approval: dict[str, Any] | None  # {"approved": bool, "files": [...]} for confirm_paths changes
    commit_sha: str | None
    report_path: str
    events: Annotated[list[dict[str, Any]], operator.add]
