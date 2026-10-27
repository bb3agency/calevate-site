"""The plan card on the wire (D-893 F3): `GET /v1/copilot/plans/{id}` and its targets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.api.copilot.plans import PlanRow, TargetRow

#: The most reasons for leaving targets out that one plan lists; the targets page has all.
MAX_EXCLUSION_REASONS = 10


class CopilotPlanExclusionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    count: int


class CopilotPlanOut(BaseModel):
    """One plan: who, why, when, the estimate, who is left out and why, and how far it got."""

    model_config = ConfigDict(extra="forbid")

    id: str
    #: The registry action the plan runs (`leads_bulk_update`, `calls_place_bulk`, ...).
    tool: str
    origin: Literal["pip", "console"]
    target_type: Literal["lead", "call", "callback"]
    title: str
    #: What happens to each target, in one sentence.
    why: str
    #: Which rows, as a person reads the filters.
    who: str
    #: When it runs; null is "as soon as it is approved".
    run_at: datetime | None
    target_count: int
    excluded_count: int
    exclusions: list[CopilotPlanExclusionOut]
    #: Rupees as a decimal string; null when the cost is not known.
    estimate_inr: str | None
    estimate_note: str
    #: What an approval binds: `POST /v1/copilot/plans/{id}/approve` sends it back.
    plan_hash: str
    status: Literal["proposed", "approved", "running", "done", "cancelled", "expired"]
    expires_at: datetime
    approved_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    done_count: int
    skipped_count: int
    failed_count: int
    pending_count: int
    result: str | None
    #: The campaign a dialling plan made.
    campaign_id: str | None
    can_approve: bool
    can_cancel: bool
    created_at: datetime


class CopilotPlanTargetOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str
    position: int
    #: Left out when the plan was made.
    excluded: bool
    status: Literal["pending", "done", "skipped", "failed"]
    reason: str | None
    #: The lead's name, read through the lead; null when it has none.
    label: str | None
    finished_at: datetime | None


class CopilotPlanTargetPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[CopilotPlanTargetOut]
    total: int
    limit: int
    offset: int


class CopilotPlanPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plans: list[CopilotPlanOut]


class CopilotPlanProposeIn(BaseModel):
    """A plan a screen asks for: a set action's registry name and its arguments, exactly as
    Pip would pass them (`copilot/set_actions.py`, `copilot/call_actions.py`)."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any]


class CopilotPlanApproveIn(BaseModel):
    """The hash of the plan the person was shown; a plan that is not that one is refused."""

    model_config = ConfigDict(extra="forbid")

    plan_hash: str = Field(min_length=64, max_length=64)


def plan_out(plan: PlanRow) -> CopilotPlanOut:
    return CopilotPlanOut(
        id=str(plan.id),
        tool=plan.tool,
        origin="console" if plan.origin == "console" else "pip",
        target_type=plan.target_type,  # type: ignore[arg-type]  # CHECK-constrained
        title=plan.title,
        why=plan.why,
        who=plan.lens_text,
        run_at=plan.run_at,
        target_count=plan.target_count,
        excluded_count=plan.excluded_count,
        exclusions=[
            CopilotPlanExclusionOut(reason=reason, count=count)
            for reason, count in sorted(plan.exclusions.items(), key=lambda kv: -kv[1])[
                :MAX_EXCLUSION_REASONS
            ]
        ],
        estimate_inr=None if plan.estimate_inr is None else f"{plan.estimate_inr:.2f}",
        estimate_note=plan.estimate_note,
        plan_hash=plan.plan_hash,
        status=plan.status,  # type: ignore[arg-type]  # CHECK-constrained
        expires_at=plan.expires_at,
        approved_at=plan.approved_at,
        started_at=plan.started_at,
        finished_at=plan.finished_at,
        done_count=plan.done_count,
        skipped_count=plan.skipped_count,
        failed_count=plan.failed_count,
        pending_count=plan.pending_count,
        result=plan.result,
        campaign_id=None if plan.campaign_id is None else str(plan.campaign_id),
        can_approve=plan.status == "proposed",
        can_cancel=plan.status in ("proposed", "approved", "running"),
        created_at=plan.created_at,
    )


def target_out(row: TargetRow) -> CopilotPlanTargetOut:
    return CopilotPlanTargetOut(
        target_id=str(row.target_id),
        position=row.position,
        excluded=row.excluded,
        status=row.status,  # type: ignore[arg-type]  # CHECK-constrained
        reason=row.reason,
        label=row.label,
        finished_at=row.finished_at,
    )


__all__ = [
    "MAX_EXCLUSION_REASONS",
    "CopilotPlanApproveIn",
    "CopilotPlanExclusionOut",
    "CopilotPlanOut",
    "CopilotPlanPageOut",
    "CopilotPlanProposeIn",
    "CopilotPlanTargetOut",
    "CopilotPlanTargetPageOut",
    "plan_out",
    "target_out",
]
