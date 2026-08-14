"""A/B script testing, as endpoints (ROADMAP M3).

    GET   /v1/agents/{agent_id}/experiment                          the results, and
                                                                    the rules they obey
    POST  /v1/admin/tenants/{tid}/agents/{aid}/experiment           start
    POST  /v1/admin/tenants/{tid}/agents/{aid}/experiment/conclude  stop, and promote

REALMS, AND WHY THE READ IS NOT ADMIN-ONLY
-------------------------------------------
The read is client-realm `agents:read`, exactly like
`publishing_routes.py::pending` and for the same D-22 reason: a support person looking
at the client's console through read-only impersonation must be able to see the
experiment, and a GET gated on `agents:write` is invisible in precisely that moment
(`tests/impersonation_reads_test.py` exists because that mistake has been made three
times). The admin console reads it through `viewAsSession`, which is the split
`admin.ts` already uses.

The two mutations are admin-realm with the tenant named in the path, matching
`prompt_routes.py` and `publishing_routes.py`. The narrow reason, rather than "D-21 says
so": an arm names a prompt VERSION, and prompt versions are minted by an admin-realm
route. A client who cannot author a script cannot be given a button that publishes one.

NO LITERAL PATHS, DELIBERATELY
------------------------------
There is no `/v1/agents/experiment-metrics`. The metric list, the minimum sample and the
peeking caveat ride on the results read instead, which the screen loads anyway. That is
one fewer round trip, but the reason is narrower: a literal segment under `/v1/agents` is
only reachable if its router is mounted BEFORE `agents.routes`' `/v1/agents/{agent_id}`
(the hazard `voice_routes.py` and `publishing_routes.py` both carry a warning about), and
a route whose correctness depends on a mount ORDER in a file this slice does not own is a
route that breaks the day somebody reorders `_mount_routers`.

MOUNTING
--------
`agents/routes.py` adopts this router's routes because `main.py` is outside this slice's
ownership, and a router nobody mounts is invisible to every route-table sweep the repo's
authorization guarantees depend on — `check_wiring` argues that at length and names
`publishing_routes.py` as the module that shipped in exactly that state. It is not the
house style; the integrator should lift it into `_mount_routers` beside its siblings.

MONEY AND PII
-------------
No money on this surface. Conversion RATES are floats and say so — a rate is not a
ledger amount (hard rule 7 is about money). No response here carries a prompt body, a
disclosure line or a phone number; arms are described by label and version NUMBER, which
is also all that reaches the audit log (hard rule 6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import experiments
from apps.api.agents.models import (
    CONVERSION_METRICS,
    DEFAULT_CONVERSION_METRIC,
    SPLIT_MIN_BP,
    SPLIT_TOTAL_BP,
)
from apps.api.agents.proportions import MIN_CALLS_PER_VARIANT
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.rbac import permission_meta

router = APIRouter(tags=["agents"])

ExperimentReader = Annotated[Principal, Depends(requires("agents:read"))]
ExperimentWriter = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricOut(Strict):
    key: str
    label: str


class ExperimentRulesOut(Strict):
    """What a script test can be scored on, and the rules the comparison obeys —
    published rather than described, so the console cannot paraphrase them into
    something friendlier than the server enforces.

    Present on every read, including the one that reports no experiment: this is what
    the Start form needs, and it is needed precisely when there is nothing running.
    """

    metrics: list[MetricOut]
    default_metric: str
    minimum_calls_per_variant: int
    split_min_bp: int
    split_total_bp: int
    peeking_caveat: str


class VariantOut(Strict):
    """One arm's counts. THREE, resolved by direction, because since D-60 an arm can be
    credited with a call nobody dialled — `experiments.VariantResult` carries the full
    argument. Briefly: `outbound_dialled` is the connect-rate diagnostic and is an
    outbound question; `completed` is what `rate` is over; `inbound_completed` says how
    much of it was never split into this arm, so a client cannot read the rate as a clean
    randomised comparison when it is not one."""

    variant_id: UUID
    label: str
    prompt_version: int
    weight_bp: int
    published: bool
    outbound_dialled: int
    completed: int
    inbound_completed: int
    conversions: int
    # Proportions in [0,1], not money. Null — never 0.0 — when the arm has no completed
    # call: a rate over zero calls is not zero percent.
    rate: float | None
    rate_low: float | None
    rate_high: float | None


class ExperimentOut(Strict):
    experiment_id: UUID
    agent_id: UUID
    name: str
    status: str
    conversion_metric: str
    conversion_metric_label: str
    started_at: datetime
    concluded_at: datetime | None
    promoted_label: str | None
    variants: list[VariantOut]
    minimum_calls_per_variant: int
    # `measured` or `insufficient_data` — the `after_hours_basis` / `CallVolume.basis`
    # precedent. Nothing may render a comparison from a basis other than `measured`.
    basis: str
    verdict: str
    # AHEAD on today's counts. An ordering, present on every basis.
    leader_label: str | None
    # BETTER. Present only when `verdict == "winner"`.
    winner_label: str | None
    difference_point: float | None
    difference_low: float | None
    difference_high: float | None
    headline: str
    caveat: str
    attributed_directions: list[str]
    coverage_note: str


class ExperimentStateOut(Strict):
    """A wrapper so that "this agent has never run a test" is a fact the client gets,
    rather than a 404 it has to interpret — a 404 on this read would be
    indistinguishable from a wrong agent id, and the console would have to guess."""

    agent_id: UUID
    rules: ExperimentRulesOut
    experiment: ExperimentOut | None


class StartExperimentIn(Strict):
    name: str = Field(min_length=3, max_length=120)
    control_version: int = Field(ge=1)
    challenger_version: int = Field(ge=1)
    split_bp: int = Field(
        default=SPLIT_TOTAL_BP // 2, ge=SPLIT_MIN_BP, le=SPLIT_TOTAL_BP - SPLIT_MIN_BP
    )
    conversion_metric: str = Field(default=DEFAULT_CONVERSION_METRIC)
    # Empty/omitted inherits the agent's disclosure. There is no value of these that
    # produces an arm without one (hard rule 5) — the column is NOT NULL with a
    # non-empty CHECK and the service refuses a blank override.
    control_disclosure: str | None = Field(default=None, max_length=400)
    challenger_disclosure: str | None = Field(default=None, max_length=400)


class StartExperimentOut(Strict):
    experiment_id: UUID
    variant_ids: list[UUID]
    engine_synced: bool


class ConcludeExperimentIn(Strict):
    """`promote` is null for "stop it and keep the control" — the commonest honest
    ending of an A/B test, and a first-class option rather than a cancel button."""

    promote: str | None = Field(default=None, pattern="^[AB]$")


class ConcludeExperimentOut(Strict):
    """What THIS call did, which on a repeat is nothing.

    `promoted_label` is the ending the test HAS (so a repeat still reports the arm that
    won); the other three are what this request performed. On `changed: false` they are
    therefore null/false together — the first call's version number is not recoverable
    from the concluded row, and a guess is worse than a null a console can read.
    """

    experiment_id: UUID
    promoted_label: str | None
    new_version: int | None
    applied: bool
    engine_synced: bool
    # False when the test had already ended this way: a success (RFC 9110 §9.2.2) that
    # promoted nothing a second time and wrote no audit row. Same flag, same reason, as
    # `admin/routes.py::LifecycleOut.changed`.
    changed: bool


def _rules() -> ExperimentRulesOut:
    """Static per deployment — the same answer for every client, which is why it is
    published rather than restated in the UI."""
    return ExperimentRulesOut(
        metrics=[
            MetricOut(key=key, label=experiments.METRIC_LABELS[key])
            for key in sorted(CONVERSION_METRICS)
        ],
        default_metric=DEFAULT_CONVERSION_METRIC,
        minimum_calls_per_variant=MIN_CALLS_PER_VARIANT,
        split_min_bp=SPLIT_MIN_BP,
        split_total_bp=SPLIT_TOTAL_BP,
        peeking_caveat=experiments.PEEKING_CAVEAT,
    )


@router.get(
    "/v1/agents/{agent_id}/experiment",
    response_model=ExperimentStateOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The running script test, its conversion attribution and the comparison rules",
    description=(
        "`agents:read`, not `agents:write`: this is the view that explains whether a "
        "test can be stopped, so it must be readable through read-only impersonation "
        "(D-22). `basis` says whether the comparison is entitled to be made at all — "
        "`insufficient_data` carries no difference interval and no winner."
    ),
)
async def experiment(agent_id: UUID, principal: ExperimentReader) -> ExperimentStateOut:
    assert principal.tenant_id is not None  # `requires()` resolves a tenant for reads
    state = await experiments.results_for(tenant_id=principal.tenant_id, agent_id=agent_id)
    return ExperimentStateOut(
        agent_id=agent_id,
        rules=_rules(),
        experiment=None if state is None else _render(state),
    )


def _render(state: experiments.ExperimentResults) -> ExperimentOut:
    return ExperimentOut(
        experiment_id=state.experiment_id,
        agent_id=state.agent_id,
        name=state.name,
        status=state.status,
        conversion_metric=state.conversion_metric,
        conversion_metric_label=state.conversion_metric_label,
        started_at=state.started_at,
        concluded_at=state.concluded_at,
        promoted_label=state.promoted_label,
        variants=[
            VariantOut(
                variant_id=v.variant_id,
                label=v.label,
                prompt_version=v.prompt_version,
                weight_bp=v.weight_bp,
                published=v.published,
                outbound_dialled=v.outbound_dialled,
                completed=v.completed,
                inbound_completed=v.inbound_completed,
                conversions=v.conversions,
                rate=v.rate,
                rate_low=v.rate_low,
                rate_high=v.rate_high,
            )
            for v in state.variants
        ],
        minimum_calls_per_variant=state.minimum_calls_per_variant,
        basis=state.basis,
        verdict=state.verdict,
        leader_label=state.leader_label,
        winner_label=state.winner_label,
        difference_point=state.difference_point,
        difference_low=state.difference_low,
        difference_high=state.difference_high,
        headline=state.headline,
        caveat=state.caveat,
        attributed_directions=list(state.attributed_directions),
        coverage_note=state.coverage_note,
    )


@router.post(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/experiment",
    response_model=StartExperimentOut,
    status_code=201,
    openapi_extra=permission_meta("agents:write"),
    summary="Start an A/B script test between two existing prompt versions",
    description=(
        "Both arms name versions this agent already has, so no new script is authored "
        "here. Each arm is published to the voice platform as its own engine agent "
        "carrying its own disclosure line."
    ),
    tags=["admin"],
)
async def start_experiment(
    tenant_id: UUID,
    agent_id: UUID,
    payload: StartExperimentIn,
    session: AdminSession,
    request: Request,
    principal: ExperimentWriter,
) -> StartExperimentOut:
    result = await experiments.start(
        tenant_id=tenant_id,
        agent_id=agent_id,
        name=payload.name,
        control_version=payload.control_version,
        challenger_version=payload.challenger_version,
        split_bp=payload.split_bp,
        conversion_metric=payload.conversion_metric,
        control_disclosure=payload.control_disclosure,
        challenger_disclosure=payload.challenger_disclosure,
    )
    await write_audit(
        session,
        action="agent.experiment_started",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=request.client.host if request.client else None,
        # Version NUMBERS and a split. No body, no disclosure text (hard rule 6).
        summary={
            "experiment_id": str(result.experiment_id),
            "control_version": payload.control_version,
            "challenger_version": payload.challenger_version,
            "split_bp": payload.split_bp,
            "metric": payload.conversion_metric,
        },
    )
    return StartExperimentOut(
        experiment_id=result.experiment_id,
        variant_ids=list(result.variant_ids),
        engine_synced=result.engine_synced,
    )


@router.post(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/experiment/conclude",
    response_model=ConcludeExperimentOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Stop the test, and optionally promote an arm through the publish path",
    description=(
        "Promotion mints a NEW prompt version from the winning arm (copy-forward, "
        "FLOWS §7) and applies it with the same 'Apply to live calls' mechanism the "
        "prompt screen uses. If the apply fails, the version is left STAGED and the "
        "ordinary Apply banner appears — the test still ends. Idempotent: a test that "
        "already ended the way you asked returns 200 with `changed: false`, promotes "
        "nothing a second time and writes no audit row. 409 names the ending it found "
        "when that ending is a different one. 404 means this account has no such test."
    ),
    tags=["admin"],
)
async def conclude_experiment(
    tenant_id: UUID,
    agent_id: UUID,
    payload: ConcludeExperimentIn,
    session: AdminSession,
    request: Request,
    principal: ExperimentWriter,
) -> ConcludeExperimentOut:
    result = await experiments.conclude(
        tenant_id=tenant_id,
        agent_id=agent_id,
        promote_label=payload.promote,
        created_by=principal.user_id,
    )
    if result.changed:
        # The audit row belongs to the transition, never to the button press — the
        # convention `admin/routes.py::set_tenant_status` and `integrations/routes.py::
        # deactivate_endpoint` follow. A retried conclude that ended nothing would
        # otherwise put a second "concluded, promoted B" in the one log that has to stay
        # readable a year from now, with a different actor and a later timestamp.
        await write_audit(
            session,
            action="agent.experiment_concluded",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=request.client.host if request.client else None,
            summary={
                "experiment_id": str(result.experiment_id),
                "promoted": result.promoted_label,
                "version": result.new_version,
                "applied": result.applied,
            },
        )
    return ConcludeExperimentOut(
        experiment_id=result.experiment_id,
        promoted_label=result.promoted_label,
        new_version=result.new_version,
        applied=result.applied,
        engine_synced=result.engine_synced,
        changed=result.changed,
    )


__all__ = [
    "ConcludeExperimentIn",
    "ExperimentOut",
    "ExperimentRulesOut",
    "ExperimentStateOut",
    "StartExperimentIn",
    "router",
]
