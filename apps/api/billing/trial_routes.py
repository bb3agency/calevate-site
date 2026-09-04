"""Admin surface for TRIAL PERIODS — start one, end one, and see what it is costing us.

`billing/trials.py` is where the design is argued; this file is the boundary, and it makes
four decisions of its own.

**THE PERMISSION IS `admin:tenants`, NOT A NEW ONE.** Putting a client on a trial is
support work of the same family as recording a payment, a DLT status or a client's number,
all of which are `admin:tenants` — and `credit_routes.py` already records why no
`billing:write` was invented for the same shape. It is in `MUTATING_PERMISSIONS`, so an
impersonating admin cannot reach it (D-22): a read-only "view as client" session must not be
able to give the client it is viewing a fortnight of free calling. The READ declares
`billing:read`, which is looser on purpose for `tenant_erasure_routes.py`'s reason — an
operator who may not START a trial should still be able to see what one is costing.

**STARTING ONE NEEDS A STEP-UP, AND IT CARRIES THE DAYS.** The founder was shown the
unbounded-liability argument and chose days with NO spend ceiling, which makes the number of
days the only bound this arrangement has — so it is the number the confirmation double-keys,
exactly as `credit_grant_confirmation` double-keys an amount. The shape is
`admin/routes.py::record_commercial_terms`: the role check first, then a confirmation bound
to this tenant, because a confirm dialog in a browser is absent from curl.

**ENDING ONE DOES NOT.** It is the direction that STOPS us spending money, it is what an
operator does when a client converts, and putting a second factor in front of it would make
the safe act harder than the expensive one. `POST /end` with `outcome=stopped` is also the
"stopped by calevate" half of the founder's sentence, and it must be reachable in one call
at 2am.

**WHAT A TRIAL IS COSTING US IS ON THE READ, and it is the whole reason the read exists.**
There is no spend ceiling by explicit choice; "no ceiling" and "no visibility" together is
how this becomes expensive silently, so `cost_to_us_inr` sums `usage_events.unit_cost_paid`
over the trial's own window. It is OUR supplier cost and is published to an OPERATOR only —
no client panel has ever shown `unit_cost_paid` and none starts here.

NOT mounted here — the integrator wires this router into `main.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.admin.service import tenant_exists
from apps.api.billing.service import to_paise
from apps.api.billing.trials import (
    DEFAULT_ERASURE_GRACE_DAYS,
    MAX_ERASURE_GRACE_DAYS,
    MAX_TRIAL_DAYS,
    MIN_ERASURE_GRACE_DAYS,
    MIN_TRIAL_DAYS,
    TRIAL_HUMAN_OUTCOMES,
    TrialState,
    end_trial,
    read_trial,
    start_trial,
    trial_cost_to_us_inr,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import tenant_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/trial", tags=["admin"])

# Annotated dependencies rather than `Depends()` in a default: this file is not
# `routes.py`, so it is not covered by the B008 per-file ignore — `credit_routes.py`
# records the same reason.
TrialWrite = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
TrialRead = Annotated[Principal, Depends(requires("billing:read", realm="admin"))]


def start_trial_confirmation(tenant_id: UUID, days: int) -> str:
    """The step-up string for putting a client on a trial.

    A named function for the reason `credit_routes.credit_grant_confirmation` gives: the
    value is part of an operator procedure, so changing its shape has to be a deliberate
    edit that fails a test rather than a reformat that leaves the console sending a header
    the API refuses.

    It carries BOTH the tenant and the days. The tenant, because a confirmation captured
    while opening a trial for one client must not be replayable against another
    (`tenant_erasure_confirmation`'s rule). The days, because there is NO SPEND CEILING on a
    trial by the founder's explicit choice, so the number of days is the entire bound on
    what this act can cost — an operator who meant 14 and typed 140 has to key 140 twice.
    """
    return f"start_trial:{tenant_id}:{days}"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrialStartIn(Strict):
    """How long, and why."""

    #: The number of days the client was promised. Bounded here AND by
    #: `ck_tenant_trials_days_range` on the table, because it is the only bound this
    #: arrangement has and a bound only a route enforces is not a bound against a script.
    days: int = Field(ge=MIN_TRIAL_DAYS, le=MAX_TRIAL_DAYS)
    #: The operator's own words. Required for `credit_routes.AdjustmentIn.reason`'s reason:
    #: a client being carried for free with no stated reason is the ticket nobody can close.
    reason: str = Field(min_length=3, max_length=500)
    #: How long after a NON-CONVERTING trial ends before this client's personal data is
    #: erased. Omit for the platform default. It is stamped onto the trial row at START and
    #: frozen there, so a default that moves later cannot move the erasure date of a client
    #: already inside their window — a data-protection promise must not change after it was
    #: made.
    erasure_grace_days: int = Field(
        default=DEFAULT_ERASURE_GRACE_DAYS,
        ge=MIN_ERASURE_GRACE_DAYS,
        le=MAX_ERASURE_GRACE_DAYS,
    )

    @field_validator("reason")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("say why this client is being given a trial")
        return trimmed


class TrialEndIn(Strict):
    """Why it is ending, and which of the two endings it is."""

    #: `converted` (they bought — they keep everything) or `stopped` (we ended it).
    #: `expired` is deliberately absent: that is the CLOCK's verdict, an operator who wants
    #: it can let the clock run, and accepting it here would let a stopped trial be recorded
    #: as one that ran its course. The difference is not cosmetic — it is what an operator
    #: reads when they ask why a client left.
    outcome: str
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("outcome")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in TRIAL_HUMAN_OUTCOMES:
            raise ValueError(f"outcome is one of {', '.join(TRIAL_HUMAN_OUTCOMES)}")
        return value

    @field_validator("reason")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 3:
            raise ValueError("say why this trial is ending")
        return trimmed


class TrialOut(Strict):
    """One trial. No personal data by construction — dates, a count and an operator's
    words."""

    tenant_id: UUID
    trial_id: UUID
    #: `active` / `converted` / `expired` / `stopped`.
    status: str
    #: Whether this client's calling is on us RIGHT NOW. Derived from the status AND the
    #: clock, never from the status alone: the sweep that expires a row runs daily, so a row
    #: can read `active` for up to a day past its end date and this field must not
    #: (`TrialState.is_active` argues why).
    active: bool
    days: int
    started_at: datetime
    ends_at: datetime
    #: Whole days left, CEILING, or None once it is over. A client with four hours left has
    #: "1 day" — rounding down would tell someone with a working service it had stopped.
    days_remaining: int | None
    ended_at: datetime | None
    ended_reason: str | None
    #: The earliest instant this client's personal data may be erased, for a trial that
    #: ended WITHOUT them buying. NULL while it runs, and NULL FOR EVER once it converted —
    #: a client who bought keeps their leads, calls and transcripts, which is the value they
    #: just built.
    erase_after: datetime | None
    #: Set once the tenant erasure has been FILED (`compliance/tenant_erasure.py` does the
    #: work; nothing here erases anything). What makes the sweep idempotent.
    erasure_filed_at: datetime | None
    #: The operator who started it, or null once that person's user row is gone. On the
    #: screen because "who agreed to carry this account for a month" is the first question
    #: asked about a trial nobody remembers, and the `audit_log` row that records it durably
    #: is not the screen an operator is looking at.
    started_by: UUID | None


class TrialStatusOut(TrialOut):
    """The read, which is the same facts plus the one an operator actually opened it for."""

    #: WHAT THIS TRIAL HAS COST CALEVATE, at our real supplier cost, over the trial's own
    #: window. The other half of "no spend ceiling": the founder chose days only, so this is
    #: the visibility that makes the choice survivable. NEVER published to a client — the
    #: client panel has never shown `unit_cost_paid` and does not start here.
    cost_to_us_inr: Decimal


def _out(state: TrialState, *, at: datetime) -> TrialOut:
    """One shape, built once, so the three writes and the read cannot publish a trial three
    slightly different ways."""
    return TrialOut(
        tenant_id=state.tenant_id,
        trial_id=state.id,
        status=state.status,
        active=state.is_active(at=at),
        days=state.days,
        started_at=state.started_at,
        ends_at=state.ends_at,
        days_remaining=state.days_remaining(at=at),
        ended_at=state.ended_at,
        ended_reason=state.ended_reason,
        erase_after=state.erase_after,
        erasure_filed_at=state.erasure_filed_at,
        started_by=state.started_by,
    )


async def _assert_tenant_exists(tenant_id: UUID, session: object) -> None:
    """A mistyped tenant id is a 404, not an FK violation rendered as a 500 — the rule
    `credit_routes._assert_tenant_exists` states, through the same shared predicate."""
    if not await tenant_exists(session, tenant_id):  # type: ignore[arg-type]
        raise ProblemError.not_found("Organization")


@router.post(
    "",
    response_model=TrialOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Put a client on a trial — N days billed to nobody",
    status_code=201,
    description=(
        "For the length of the trial this client's outbound calling is not stopped by an "
        "empty wallet and nothing is debited from it. Every minute is still METERED, and "
        "every other gate — KYC, the agreements, the spend cap, calling hours, do-not-call, "
        "consent, the DLT chain — still applies: a trial is a billing state, never a "
        "compliance exemption. There is deliberately NO spend ceiling, so the header "
        "`X-Confirm-Action: start_trial:<tenant_id>:<days>` is required on every call and "
        "the read publishes what the trial is costing us."
    ),
)
async def open_trial(
    tenant_id: UUID,
    payload: TrialStartIn,
    request: Request,
    principal: TrialWrite,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> TrialOut:
    step_up.require(x_confirm_action, start_trial_confirmation(tenant_id, payload.days))
    at = datetime.now(UTC)
    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(tenant_id, scoped)
        state = await start_trial(
            scoped,
            tenant_id=tenant_id,
            days=payload.days,
            actor_user_id=principal.user_id,
            erasure_grace_days=payload.erasure_grace_days,
            at=at,
        )
        # Same transaction as the row: a client carried for free with no audit entry is not
        # a reachable state, for the reason the credit grant gives at greater length.
        await write_audit(
            scoped,
            action="trial.started",
            actor=principal,
            tenant_id=tenant_id,
            object_type="tenant_trials",
            object_id=str(state.id),
            ip=client_request_ip(request),
            summary={
                "days": str(payload.days),
                "ends_at": state.ends_at.isoformat(),
                "erasure_grace_days": str(payload.erasure_grace_days),
                "reason": payload.reason,
            },
        )
    return _out(state, at=at)


@router.post(
    "/end",
    response_model=TrialOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="End a trial — converted, or stopped by Calevate",
    description=(
        "Closes the trial and starts a fresh counting period: from this instant the "
        "client's own usage figures count from zero, exactly as they do on the 1st of a "
        "month. NOTHING IS DELETED — every ledger keeps every row (hard rule 4); what "
        "moves is the window their screens count over. `converted` keeps this client's "
        "data for good. `stopped` schedules a tenant erasure for the end of the grace "
        "period agreed when the trial was opened."
    ),
)
async def close_trial(
    tenant_id: UUID,
    payload: TrialEndIn,
    request: Request,
    principal: TrialWrite,
) -> TrialOut:
    at = datetime.now(UTC)
    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(tenant_id, scoped)
        state = await end_trial(
            scoped,
            tenant_id=tenant_id,
            outcome=payload.outcome,
            reason=payload.reason,
            at=at,
        )
        await write_audit(
            scoped,
            action="trial.ended",
            actor=principal,
            tenant_id=tenant_id,
            object_type="tenant_trials",
            object_id=str(state.id),
            ip=client_request_ip(request),
            summary={
                "outcome": payload.outcome,
                # The date this client's data becomes erasable, in the audit row rather
                # than only on a screen: it is the consequence of this act that somebody
                # will have to answer for, and "when did we decide to erase them" is the
                # question a later review asks.
                "erase_after": state.erase_after.isoformat() if state.erase_after else "",
                "reason": payload.reason,
            },
        )
    return _out(state, at=at)


@router.get(
    "",
    response_model=TrialStatusOut | None,
    openapi_extra=permission_meta("billing:read"),
    summary="This client's newest trial, and what it has cost us",
    description=(
        "`null` for a client who has never been given a trial. The newest one otherwise, "
        "open or closed — a screen has to be able to say 'their trial ended on the 3rd', "
        "which a reader that could only see open trials could not."
    ),
)
async def read_trial_status(
    tenant_id: UUID,
    principal: TrialRead,
    request: Request,
) -> TrialStatusOut | None:
    at = datetime.now(UTC)
    async with tenant_session(tenant_id) as scoped:
        await _assert_tenant_exists(tenant_id, scoped)
        state = await read_trial(scoped, tenant_id=tenant_id)
        cost = (
            await trial_cost_to_us_inr(scoped, tenant_id=tenant_id, trial=state)
            if state is not None
            else Decimal("0")
        )
        # D-482 L-1: a direct-admin read of one client's commercial state joins the audit
        # trail, the rule `credit_routes.read_credits` follows.
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    if state is None:
        return None
    base = _out(state, at=at)
    return TrialStatusOut(**base.model_dump(), cost_to_us_inr=to_paise(cost))


__all__ = ["router", "start_trial_confirmation"]
