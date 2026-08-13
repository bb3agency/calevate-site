"""Operator endpoints — the big red switch, the outbox DLQ, the audit chain, Calevate's
own DLT telemarketer registration, and the spend-cap recompute.

The DLT registration is a legal fact rather than an operational lever, and it is here
because it has the same SHAPE as the levers: one value, global, true or false for every
tenant at the same instant. SEC-COMP §3's first bullet makes it the company-level campaign
blocker — while it is not `active`, `campaigns.service.launch_blockers` refuses every
tenant's launch with `tm_registration_missing`, however complete that client's own
Principal Entity registration is. A per-tenant copy of it would be N copies of one fact
that eventually disagree, so it lives in `platform_state` beside the halt.

Two properties hold for every route in this file:

1. **Never shed.** `/v1/ops` is in `ALWAYS_ALLOWED_PREFIXES`, so putting the platform
   into `maintenance` does not remove the ability to take it back out.
2. **Step-up confirmation on every WRITE** (BACKEND-PATTERNS §7). Halting all outbound
   calling, recording our telemarketer registration, recomputing a cap and replaying the
   dead-letter queue are actions a stolen session must not be able to perform, so each
   requires a fresh confirmation bound to the specific action. `GET /audit/verify` is the
   one route here without one, because it writes nothing — demanding a confirmation to
   run a read only teaches operators to type past confirmations.

Step-up is currently a required `X-Confirm-Action` header that must echo the action
being taken. That is not a strong second factor and is not pretending to be one — it
stops the accidental and the drive-by, and the Clerk re-auth binding replaces it when
the admin realm's MFA lands (TRD §2). It is here now because adding it later would
mean changing the callers, and because a switch this size should never have been
reachable by a single unconfirmed POST.

**Every confirmation on this router is bound to the action AND its target**, which is
what §7 asks for and what the spend-cap recompute has always done (its string carries
the tenant id, so a header an operator sent for one client cannot be replayed against
another). `set_platform` used to be the exception: one string, `set_platform_state`,
covered both releasing a global outbound halt and a routine load-shed tweak, so a
header captured for the Tuesday change satisfied the switch. It now names the exact
transition — `halt_outbound`, `release_outbound`, `set_load_shed:<mode>`, and the two
joined for a request that does both — built in ONE place, `platform_confirmation`,
which the runbooks quote and a test pins.

A confirmation carries a `:<target>` suffix only where the target VARIES: the tenant on
the spend-cap recompute, the mode on the load-shed change. `halt_outbound` and
`replay_dead_letters` name actions with exactly one possible target — the platform, and
the one global dead-letter queue — so a suffix there would bind nothing. What every
string on this router does have is uniqueness: no header accepted by one route is
accepted by another, which is what stops a confirmation captured for the smallest action
authorising the largest.

That was a BREAKING change to an ops surface and was made deliberately rather than
grandfathered: the old string's whole problem was that it authorised more than the
operator meant, so keeping it accepted "for compatibility" would have kept the hole
open under a different name. Two callers moved with it — the admin console's
`useSetPlatformState` and `runbooks/campaign-stall.md` §1 — and the refusal names the
header to send in its `remediation`, so an operator with an old curl is one paste from
recovering rather than one grep.

Most routes here move ONE global row and take `global_db`. The spend-cap recompute is
the exception: it works on a named tenant's `spend_state`, which is RLS'd, so it names
its tenant in the path and enters that tenant's scope with `tenant_session` — the house
pattern for an admin-realm mutation (`route_shape_test`, `billing/credit_routes.py`).
An untenanted session would see zero rows there and report a cheerful nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.billing.caps import read_caps, read_spend_counters, recompute_capped
from apps.api.billing.service import current_billing_month, to_paise
from apps.api.compliance.audit import verify_chain, write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import LoadShedMode, get_platform_status, set_platform_status
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.ops.service import (
    TmRegistration,
    read_halt_state,
    read_tm_registration,
    set_tm_registration,
)
from apps.api.reliability.service import replay_dead_letters

router = APIRouter(prefix="/v1/ops", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]


class TmRegistrationOut(BaseModel):
    """Calevate's own telemarketer registration (SEC-COMP §3, company half).

    `is_live` is computed rather than left to the reader: "is `submitted` good enough"
    is exactly the question a console must not answer for itself, and the launch gate
    and this response must never disagree about it — both read
    `ops.service.TmRegistration.is_live`.
    """

    model_config = ConfigDict(extra="forbid")

    status: str
    tm_id: str | None
    registered_at: datetime | None
    verified_at: datetime | None
    is_live: bool


class PlatformStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load_shed_mode: str
    outbound_halted: bool
    # WHY outbound is stopped, for the person who found it stopped. Null whenever
    # `outbound_halted` is false, and the pair always comes from one row read
    # (`ops.service.read_halt_state`) so the dashboard cannot show a halt from one
    # instant next to a reason from another.
    halt_reason: str | None
    # The third global switch on this row, and the only one that is a legal fact rather
    # than an operational one: when it is not live, no tenant may launch a campaign.
    tm_registration: TmRegistrationOut


class TmRegistrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_registered", "submitted", "active", "suspended", "revoked"]
    # Required in practice for `active` (service + DB CHECK); optional in the schema
    # because the other four states legitimately have no number yet, or no longer do.
    tm_id: str | None = Field(default=None, max_length=120)
    registered_at: datetime | None = None
    # Same requirement as the load-shed switch: an operator changing a platform-wide
    # compliance fact says why, in the audit row, at the time.
    reason: str = Field(min_length=3, max_length=500)


class PlatformStateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load_shed_mode: LoadShedMode | None = None
    outbound_halted: bool | None = None
    # REQUIRED, and required with content: a halt nobody explained is a halt nobody can
    # safely lift, and whoever finds it at 3am has to decide whether the condition still
    # holds. Same bounds as `TmRegistrationIn.reason` — one shape for one idea. When the
    # request halts, this string is what lands in `platform_state.halt_reason`.
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        """`min_length` alone accepts `"   "`, which passes the check and answers
        nothing. Stripped here so the column holds the reason as it will be read."""
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("a reason is required — say what stopped, and why")
        return stripped


class ReplayOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replayed: int


class ChainVerifyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    first_bad_entry_id: str | None = None
    checked: Literal["audit_log"] = "audit_log"


class SpendCapRecomputeOut(BaseModel):
    """What the flag was, what it is now, and the numbers that decided it.

    An operator running this mid-incident needs to know not just whether the tenant is
    released but WHY — a recompute that leaves `capped` true has done its job and the
    ceiling is simply still below the spend. Reporting the counters and the effective
    ceiling next to the flag is what turns "it did not work" into "the ceiling is 2 and
    they have used 3".
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    # The IST billing month the recompute applied to (`spend_capped` reads this too).
    month: str
    # The flag as it stood when the request arrived, so the audit trail and the operator
    # can both see whether anything actually changed.
    capped_before: bool
    capped: bool
    # This month's metered counters — NOT written by this route, only read.
    minutes_used: str
    spend_used_inr: str
    # The ceiling in force: LEAST(the plan's, the client's own). Money as an exact
    # decimal string, never a JSON float (hard rule 7).
    effective_cap_minutes: int | None
    effective_cap_spend_inr: str | None


def _require_step_up(confirm: str | None, action: str) -> None:
    if confirm != action:
        raise ProblemError(
            kind="permission",
            code="step_up_required",
            title="Confirmation required",
            detail="This action needs an explicit confirmation.",
            remediation=f"Repeat the request with the header X-Confirm-Action: {action}",
        )


def platform_confirmation(*, outbound_halted: bool | None, load_shed_mode: str | None) -> str:
    """The step-up string for ONE state transition of the global row.

    A named function for the same reason `spend_cap_confirmation` is one: these strings
    are an ops PROCEDURE. `runbooks/calls-stopped.md` §1 and `runbooks/campaign-stall.md`
    §1 print what an operator types mid-incident, and `tests/platform_halt_test.py` pins
    every literal — so changing the shape has to be a deliberate edit that fails a test,
    not a quiet reformat that leaves both runbooks instructing operators to send a header
    the API refuses.

    WHY THREE STRINGS AND NOT ONE. §7 wants the confirmation bound to the specific
    action. Halting every tenant's outbound dialling, releasing that halt, and moving
    the load-shed mode are three different decisions with three different blast radii,
    and one shared string meant a header captured for the smallest authorised the
    largest. The load-shed string carries its TARGET MODE for the same reason the
    spend-cap string carries its tenant: `reduced` is a routine change and `maintenance`
    sheds reads, and consent to one is not consent to the other.

    A request that does both halves needs both halves confirmed, joined in a fixed order
    (the halt first — it is the half that must be read before it is sent). Joining
    rather than accepting either alone is the conservative reading: a combined request
    is strictly more dangerous than either part.
    """
    parts: list[str] = []
    if outbound_halted is not None:
        parts.append("halt_outbound" if outbound_halted else "release_outbound")
    if load_shed_mode is not None:
        parts.append(f"set_load_shed:{load_shed_mode}")
    if not parts:
        # No transition, so there is nothing for a confirmation to be bound to. This
        # body used to reach `set_platform_status`, change nothing and still write an
        # audit row — a recorded platform change nobody made.
        raise ProblemError(
            kind="validation",
            code="platform_state_no_change",
            title="Nothing to change",
            detail="This request changes neither the load-shed mode nor the outbound halt.",
            remediation="Send load_shed_mode, outbound_halted, or both.",
        )
    return "+".join(parts)


def _tm_out(registration: TmRegistration) -> TmRegistrationOut:
    return TmRegistrationOut(
        status=registration.status,
        tm_id=registration.tm_id,
        registered_at=registration.registered_at,
        verified_at=registration.verified_at,
        is_live=registration.is_live,
    )


@router.get(
    "/platform",
    response_model=PlatformStateOut,
    openapi_extra=permission_meta("ops:manage"),
)
async def read_platform(
    session: GlobalSession,
    _: Principal = Depends(requires("ops:manage", realm="admin")),
) -> PlatformStateOut:
    status = await get_platform_status(force_refresh=True)
    # Read from Postgres on this session, never from the load-shed cache: the TM
    # registration is a compliance fact and a 15-second-stale copy of it is a campaign
    # that launched after the registrar suspended us.
    #
    # The halt and its reason come from ONE row read for the same reason they are
    # written in one statement — this is the screen an operator reads mid-incident, and
    # "halted" beside a reason from a different instant is worse than either alone.
    halt = await read_halt_state(session)
    return PlatformStateOut(
        load_shed_mode=status.mode,
        outbound_halted=halt.outbound_halted,
        halt_reason=halt.reason,
        tm_registration=_tm_out(await read_tm_registration(session)),
    )


@router.post(
    "/platform",
    response_model=PlatformStateOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Load-shed mode and the big red switch (step-up confirmed, audited)",
)
async def set_platform(
    payload: PlatformStateIn,
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> PlatformStateOut:
    """Bound to the transition, and the reason lands where the dashboard reads it.

    THE CONFIRMATION. `platform_confirmation` names the exact move being made — see its
    docstring for why one string across three moves was a hole rather than a
    convenience. This is a BREAKING change to an ops surface and is meant to be: the old
    `set_platform_state` header now authorises nothing, in either direction, and the
    refusal carries the header that would have worked.

    THE REASON. `halt_reason` is written in the same statement as `outbound_halted`
    (`core.loadshed.set_platform_status`) and cleared on release. Until now the reason
    went only into `write_audit`'s `summary` — and `audit_log` HAS NO SUMMARY COLUMN
    (`compliance/audit.py`: the sanitised summary goes to the log stream keyed by entry
    id), so the one question an operator asks first was answerable only by someone who
    knew to grep the right log stream. The column is the live answer; `audit_log`
    remains the history of who moved it and when.

    ONE AUDIT ROW PER TRANSITION. A request that halts AND sheds performed two actions,
    and one row named after the more dramatic of them would make "when did we last halt
    everyone" a full-text hunt through a generic action. The rows are written on
    `global_db`, which commits at the end of the request, so they land together.
    """
    confirmation = platform_confirmation(
        outbound_halted=payload.outbound_halted, load_shed_mode=payload.load_shed_mode
    )
    _require_step_up(x_confirm_action, confirmation)

    status = await set_platform_status(
        mode=payload.load_shed_mode,
        outbound_halted=payload.outbound_halted,
        halt_reason=payload.reason,
        actor_id=str(principal.user_id) if principal.user_id else None,
    )
    halt = await read_halt_state(session)
    ip = request.client.host if request.client else None
    if payload.outbound_halted is not None:
        await write_audit(
            session,
            action="ops.halt_outbound" if payload.outbound_halted else "ops.release_outbound",
            actor=principal,
            object_type="platform_state",
            object_id="1",
            ip=ip,
            summary={"outbound_halted": halt.outbound_halted, "reason": payload.reason},
        )
    if payload.load_shed_mode is not None:
        await write_audit(
            session,
            action="ops.set_load_shed",
            actor=principal,
            object_type="platform_state",
            object_id="1",
            ip=ip,
            summary={"load_shed_mode": status.mode, "reason": payload.reason},
        )
    return PlatformStateOut(
        load_shed_mode=status.mode,
        outbound_halted=halt.outbound_halted,
        halt_reason=halt.reason,
        tm_registration=_tm_out(await read_tm_registration(session)),
    )


@router.post(
    "/platform/tm-registration",
    response_model=TmRegistrationOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Record Calevate's own DLT telemarketer registration (step-up confirmed, audited)",
    description=(
        "The company half of SEC-COMP §3's first bullet. While this is not `active`, "
        "NO tenant can launch an outbound campaign, however complete their own "
        "Principal Entity registration is. Inbound answering is unaffected."
    ),
)
async def set_tm_registration_route(
    payload: TmRegistrationIn,
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> TmRegistrationOut:
    """Step-up confirmed in BOTH directions, with the action naming which one.

    Marking the registration active is the more dangerous write, not the less: it is
    the one that turns the platform-wide launch gate green, and a stolen admin session
    that could do it silently would have every tenant dialling on a registration that
    does not exist. Taking it away halts all outbound launching, which is the big red
    switch by another route. Neither belongs behind a single unconfirmed POST, so the
    confirmation is bound to the direction — `record_tm_registration` to make it live,
    `withdraw_tm_registration` to take it out of `active` — and an operator who meant
    one cannot perform the other by replaying a header.
    """
    action = "record_tm_registration" if payload.status == "active" else "withdraw_tm_registration"
    _require_step_up(x_confirm_action, action)

    registration = await set_tm_registration(
        session,
        status=payload.status,
        tm_id=payload.tm_id,
        registered_at=payload.registered_at,
    )
    # Same transaction as the write (`global_db` commits at the end of the request):
    # the row is mutable by design, so `audit_log` is the only history of who changed
    # a platform-wide compliance fact and why.
    await write_audit(
        session,
        action=f"ops.{action}",
        actor=principal,
        object_type="platform_state",
        object_id="1",
        ip=request.client.host if request.client else None,
        summary={
            "tm_registration_status": registration.status,
            "tm_id": registration.tm_id,
            "reason": payload.reason,
        },
    )
    return _tm_out(registration)


def spend_cap_confirmation(tenant_id: UUID) -> str:
    """The step-up string for one tenant's recompute.

    A named function rather than an f-string inline, because this value is part of an
    ops PROCEDURE — `runbooks/calls-stopped.md` §2 prints the header an operator types
    mid-incident, and `tests/ops_spend_cap_recompute_test.py` pins the literal. Changing
    the shape has to be a deliberate edit here that fails that test, not a quiet
    reformat that leaves the runbook telling operators to send a header the API refuses.
    """
    return f"recompute_spend_cap:{tenant_id}"


@router.post(
    "/tenants/{tenant_id}/spend-cap/recompute",
    response_model=SpendCapRecomputeOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Re-derive a tenant's spend cap flag from their counters (step-up confirmed, audited)",
    description=(
        "Recomputes `spend_state.capped` from the minutes and spend ALREADY metered "
        "this month against the ceiling now in force. Use it after raising "
        "`plans.hard_cap_min` / `hard_cap_spend` for a capped client: the flag is a "
        "derived column and raising the ceiling does not by itself release the gate. "
        "It never sets the flag directly and never moves a counter, so a tenant still "
        "over their ceiling stays capped. Inbound calling is unaffected either way."
    ),
)
async def recompute_spend_cap(
    tenant_id: UUID,
    request: Request,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> SpendCapRecomputeOut:
    """The third writer of `spend_state.capped`, and the only one ops can reach.

    THE DEAD END IT CLOSES (`runbooks/calls-stopped.md` §2). The gate reads the flag,
    not the ceilings. The meter arms it and a capped tenant meters nothing, so the meter
    can never clear it; the client's `PUT /v1/billing/caps` clears it but needs
    `org:manage`, which is in `MUTATING_PERMISSIONS`, so an impersonating admin (D-22)
    cannot do it for them. An outbound-only client whose ceiling ops had just raised
    therefore stayed stopped until they acted themselves or the IST month rolled over.

    IT RECOMPUTES; IT DOES NOT UN-CAP. The work is `caps.recompute_capped`, the same
    function the client's route calls, reading the same `over_cap_sql` the post-call
    meter uses. An ops button that wrote `capped = false` would be the third DEFINITION
    rather than the third caller, and the first incident it caused would be a tenant
    dialling past a ceiling with the meter re-arming the flag behind it.

    Scoping is the house pattern for an admin-realm mutation: the tenant is named in the
    path (an admin principal has no tenant of its own — `route_shape_test`) and the work
    runs inside `tenant_session`, so `spend_state`'s RLS policy is what isolates it.
    The audit row is written on the SAME session, so the flag and the record of who
    moved it commit together or not at all.
    """
    # Bound to the tenant, not just to the verb: a confirmation captured for one client
    # cannot be replayed against another. See the module docstring on why the big red
    # switch's generic string is not the standard to copy.
    _require_step_up(x_confirm_action, spend_cap_confirmation(tenant_id))

    async with tenant_session(tenant_id) as session:
        if not await tenant_exists(session, tenant_id):
            # A mistyped uuid must not answer 200 with a cheerful "not capped" — read
            # mid-incident that says "fixed" while the real client is still stopped.
            raise ProblemError.not_found("Organization")

        before = await read_spend_counters(session, tenant_id=tenant_id)
        # `None` means there is no row for the CURRENT month — nothing metered yet, or a
        # row still stamped with a closed one. Both are "no cap in force" and both are
        # left alone: `compliance.spend_capped` already reads the month, so rewriting a
        # stale row would evaluate last month's counters against this month's ceiling.
        recomputed = await recompute_capped(session, tenant_id=tenant_id)
        capped = bool(recomputed)
        caps = await read_caps(session, tenant_id=tenant_id)

        await write_audit(
            session,
            action="ops.recompute_spend_cap",
            actor=principal,
            tenant_id=tenant_id,
            object_type="spend_state",
            object_id=str(tenant_id),
            ip=request.client.host if request.client else None,
            # Ids, ceilings and two booleans. No phone number, transcript or extraction
            # exists anywhere on this path (hard rule 6).
            summary={
                "month": current_billing_month(),
                "capped_before": before.capped,
                "capped_after": capped,
                "row_present_for_month": recomputed is not None,
                "effective_cap_minutes": caps.effective_cap_min,
                "effective_cap_spend_inr": (
                    str(to_paise(caps.effective_cap_spend))
                    if caps.effective_cap_spend is not None
                    else None
                ),
            },
        )

    return SpendCapRecomputeOut(
        tenant_id=str(tenant_id),
        month=current_billing_month(),
        capped_before=before.capped,
        capped=capped,
        minutes_used=str(to_paise(before.minutes_used)),
        spend_used_inr=str(to_paise(before.spend_used)),
        effective_cap_minutes=caps.effective_cap_min,
        effective_cap_spend_inr=(
            str(to_paise(caps.effective_cap_spend))
            if caps.effective_cap_spend is not None
            else None
        ),
    )


# The step-up string for the dead-letter replay.
#
# A CONSTANT rather than a function, unlike its two neighbours, and that is the whole
# argument for its shape: `platform_confirmation` computes (three transitions, and both
# joined) and `spend_cap_confirmation` interpolates (the tenant it is bound to), while
# nothing about this action varies. A zero-argument function would be ceremony that
# implies a parameter exists, and the value would still have to be pinned by a test.
#
# WHY NO `:<target>` SUFFIX, i.e. why this is `halt_outbound`'s shape and not
# `recompute_spend_cap:<id>`'s. The suffix on the other two carries the part of the
# action an operator could get wrong by replaying a header they already had: the tenant,
# or the target load-shed mode. This action has no such part — there is exactly one
# dead-letter queue and it is global, the same way the big red switch is global — so a
# suffix here would be a fourth spelling of a binding with nothing to bind. What the
# string is bound to is the ACTION, which is the property §7 asks for and the property
# `set_platform_state` failed: no other header on this router equals it, so a
# confirmation captured for a load-shed tweak or one client's recompute cannot replay
# into a cross-tenant redelivery.
#
# It matches `reliability.service.replay_dead_letters` and the console's button label on
# purpose: an operator types what they were told they are doing.
OUTBOX_REPLAY_CONFIRMATION = "replay_dead_letters"


@router.post(
    "/outbox/replay",
    response_model=ReplayOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Flip dead-lettered outbox messages back to pending (step-up confirmed, audited)",
    description=(
        "Moves up to 100 of the OLDEST dead-lettered outbox messages back to `pending` "
        "with a fresh attempt budget, for every tenant at once. The next dispatch tick "
        "re-sends them: HMAC-signed webhooks to clients' own systems, Google Sheets "
        "appends, notification emails. A message can dead-letter AFTER its side effect "
        "landed, so the outcome to be sure of before sending this is a second delivery, "
        "not a flag in a row."
    ),
)
async def replay_outbox(
    session: GlobalSession,
    request: Request,
    principal: Principal = Depends(requires("ops:manage", realm="admin")),
    x_confirm_action: str | None = Header(default=None),
) -> ReplayOut:
    """The most outward-facing write on this router, and the last one to get a step-up.

    WHY IT NEEDS ONE AT ALL, given it moves no switch. `replay_dead_letters` selects on
    `status = 'failed'` with NO tenant predicate — `outbox_messages` is an infra table
    and carries no `tenant_id` column to have one with — so a single POST reaches every
    client's parked messages. And the flip is not the blast radius: the next dispatch
    tick DELIVERS them, so the effect is other people's customer data arriving a second
    time in other people's systems, which is not undoable from here and is visible to the
    client. Halting outbound calling is loud, reversible and ours; this is quiet,
    irreversible and theirs. It was the only write here reachable by one unconfirmed POST.

    NO REASON FIELD, deliberately, and this is the one place this router is asymmetric.
    `set_platform` and the TM registration both require one because they leave a STATE
    behind that somebody finds later and has to decide whether to lift — `halt_reason`
    exists for the person who arrives at 3am. A replay leaves no state: it is an
    instantaneous act whose record is the audit row (who, when, how many) and whose
    "why" is the incident that is already open in `runbooks/webhook-delivery-failures.md`.
    Adding a required body here would break the console's form and the runbook's curl to
    buy a free-text field nobody reads back.
    """
    # Bound to the action, checked BEFORE any row moves. See OUTBOX_REPLAY_CONFIRMATION
    # for why this action's string carries no target suffix.
    _require_step_up(x_confirm_action, OUTBOX_REPLAY_CONFIRMATION)

    count = await replay_dead_letters(session)
    # BACKEND-PATTERNS §4 requires the replay to carry an audit note — a message that
    # was delivered twice needs a record of who asked for the second attempt.
    await write_audit(
        session,
        action="ops.outbox_replay",
        actor=principal,
        object_type="outbox_messages",
        ip=request.client.host if request.client else None,
        summary={"replayed": count},
    )
    return ReplayOut(replayed=count)


@router.get(
    "/audit/verify",
    response_model=ChainVerifyOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Recompute the audit hash chain and report the first broken link",
)
async def verify_audit_chain(
    session: GlobalSession,
    _: Principal = Depends(requires("ops:manage", realm="admin")),
) -> ChainVerifyOut:
    ok, bad = await verify_chain(session)
    return ChainVerifyOut(ok=ok, first_bad_entry_id=bad)


__all__ = [
    "OUTBOX_REPLAY_CONFIRMATION",
    "platform_confirmation",
    "router",
    "spend_cap_confirmation",
]
