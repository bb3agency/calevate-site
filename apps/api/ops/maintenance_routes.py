"""Planned maintenance: the operator's four verbs, and the one thing a client may read.

D-544. `ops/maintenance.py` holds the state machine and argues the design;
`workers/maintenance.py` does the work. This file only moves the row and nudges the
worker, and that division is the design rather than a convenience:

**NO HANDLER HERE ACTUATES ANYTHING.** Opening a window pauses every running campaign in
the fleet and rewrites what every live inbound agent says; closing one republishes them
all. That is a fleet-wide walk with vendor round trips in it, which belongs in a worker
(BACKEND-PATTERNS, and `workers/fleet_walk.py` exists because these walks outgrow a job
timeout — never mind a request). A handler that did it would hold a connection for the
length of the client list and time out first on the deployment with the most clients.

So each write does two things: it moves the window row inside the request's transaction,
and it enqueues `maintenance_tick`. The tick is the ONE implementation of "what entering
or leaving a window means", so there is no second one to drift, and an operator still gets
their action within a second instead of at the next cron beat.

**STEP-UP ON EVERY WRITE** (BACKEND-PATTERNS §7), bound to the action AND its target the
way every other confirmation on the ops surface is. Scheduling a window takes the whole
platform away from every client at a time of our choosing; ending one early hands it back
mid-migration. Both belong on the same list as the big red switch, and a stolen console
session must not be able to do either.

**NEVER SHED.** These routes live under `/v1/ops`, which is in
`loadshed.ALWAYS_ALLOWED_PREFIXES` — so putting the platform into maintenance never removes
the ability to take it back out. That is the same property `ops/routes.py` relies on and it
matters more here: this surface is the one that ends the outage.

THE CLIENT-FACING READ IS THE LAST ROUTE IN THE FILE, and it is deliberately in this module
rather than beside the client console's other reads: there is one projection of a
maintenance window for clients, and having it here keeps it next to the rules that decide
what a client may know (the reason and the two instants; never the drain counts, never the
straggler list, never who scheduled it).
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.core.rbac import permission_meta
from apps.api.core.stepup import StepUpGate
from apps.api.ops.maintenance import (
    MaintenanceWindow,
    amend_window,
    cancel_window,
    list_windows,
    read_open_window,
    read_window,
    schedule_window,
)
from apps.api.ops.models import DEFAULT_MAX_DRAIN_MINUTES

log = get_logger(__name__)

router = APIRouter(prefix="/v1/ops/maintenance", tags=["ops"])
client_router = APIRouter(prefix="/v1/maintenance", tags=["maintenance"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
#: THE ANNOTATED FORM, and it is not a style preference. `Depends(...)` in an argument
#: DEFAULT is the FastAPI dependency-injection API and ruff's B008 forbids it; the
#: per-file-ignore in `pyproject.toml` covers `**/routes.py` and this file is
#: `maintenance_routes.py`. `ops/config_routes.py` set the precedent every sibling in this
#: package follows: one alias per guard, declared once, so the rule keeps catching an
#: accidental call everywhere else.
MaintenanceOperator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]
#: The client-realm read behind the console banner. `org:read` because every client role
#: holds it — knowing the platform is about to close is not a privilege.
AnyClient = Annotated[Principal, Depends(requires("org:read"))]
HistoryLimit = Annotated[int, Query(ge=1, le=100)]
ConfirmAction = Annotated[str | None, Header()]

#: The ARQ function name of the window's actuator. A constant here rather than a literal at
#: three call sites, and derived from the worker's own name by `check_job_wiring` — an
#: enqueue for a name no worker registers is accepted by arq, dropped with a warning
#: nothing reads, and would leave an operator pressing "end now" on a window that never
#: ends (D-199, shape 3).
MAINTENANCE_TICK_JOB = "maintenance_tick"

#: The newest windows the history list will return without being asked for fewer.
DEFAULT_HISTORY = 20
MAX_HISTORY = 100


def maintenance_confirmation(action: str, window_id: UUID | None = None) -> str:
    """The step-up string for ONE maintenance action, bound to its target.

    A named function for `platform_confirmation`'s reason: these strings are an ops
    PROCEDURE that `runbooks/maintenance-window.md` prints and a test pins, so changing
    their shape has to be a deliberate edit that fails a test rather than a quiet reformat
    that leaves the runbook telling operators to send a header the API refuses.

    Every string carries the window id EXCEPT `schedule_maintenance`, which has no target
    yet — the window it creates does not exist when the header is typed. The suffix is what
    stops a confirmation captured for one window authorising an action on another: an
    operator who confirmed "end the Tuesday window" must not thereby end the one that
    replaced it.
    """
    return action if window_id is None else f"{action}:{window_id}"


class MaintenanceScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime
    ends_at: datetime
    #: CLIENT-FACING, VERBATIM. It is the body of three emails and the `detail` of every
    #: 503 a locked-out client gets, which is why it has a floor as well as a ceiling: a
    #: lockout page reading "maintenance" is the generic error this whole feature exists to
    #: replace. Same bounds as `PlatformStateIn.reason` — one shape for one idea.
    reason: str = Field(min_length=10, max_length=500)
    max_drain_minutes: int = Field(default=DEFAULT_MAX_DRAIN_MINUTES, ge=1, le=240)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("say why, in words a client can read")
        return value.strip()


class MaintenanceAmendIn(BaseModel):
    """A PATCH body: whichever fields moved, and nothing else.

    Every field optional for `DisclosureIn`'s reason — a screen with four inputs sends the
    one that changed, and a body that could only send all four would make extending a
    window a read-modify-write race against an operator rewriting its reason. The service
    decides which of them an ANNOUNCED window may still take.
    """

    model_config = ConfigDict(extra="forbid")

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = Field(default=None, min_length=10, max_length=500)
    max_drain_minutes: int | None = Field(default=None, ge=1, le=240)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("say why, in words a client can read")
        return value.strip() if value is not None else None


class InFlightOut(BaseModel):
    """What the drain is still waiting for, as the console renders it.

    `measured_at` is not decoration. These numbers are taken by the worker tick, not by
    this request (`PlatformMaintenanceWindow.in_flight` says why), so the screen has to be
    able to say how old they are — an operator deciding whether to force a window on
    numbers of unknown age is exactly the mistake the founder's "an operator staring at a
    spinner with no numbers will force it" is about.
    """

    model_config = ConfigDict(extra="forbid")

    calls: int
    jobs: int
    tenants_unreached: int
    #: False when the walk ran out of budget: `calls` is then a FLOOR, not a total, and the
    #: window will NOT activate on it. Rendered as a caveat rather than hidden.
    complete: bool
    measured_at: datetime | None


class MaintenanceWindowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    reason: str
    starts_at: datetime
    ends_at: datetime
    state: Literal["scheduled", "draining", "active", "completed", "cancelled"]
    max_drain_minutes: int
    drain_deadline_at: datetime | None
    activated_at: datetime | None
    #: True when the drain deadline passed with work still in flight. The operator reads
    #: this beside `stragglers` to know which kind of ACTIVE they are looking at.
    forced: bool
    stragglers: InFlightOut | None
    in_flight: InFlightOut | None
    ended_at: datetime | None
    cancelled_at: datetime | None
    #: Whether clients have been told. It is what freezes the start time, so the console
    #: has to render it or an operator will type a start change the API then refuses.
    announced: bool


class MaintenanceBoardOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: MaintenanceWindowOut | None
    history: list[MaintenanceWindowOut]


class ClientMaintenanceOut(BaseModel):
    """What a CLIENT is told about a window, and the fields are the whole disclosure rule.

    Three facts and no more: is one coming or here, when does it end, and why. Deliberately
    absent: the drain counts (how many other clients are on a call is not this client's
    business), the straggler list, `forced`, who scheduled it, and the window id — none of
    which a client can act on and all of which are operational detail about other people's
    accounts.

    `state` is narrowed to the three a client can be in the presence of. A `completed` or
    `cancelled` window is answered as no window at all, because "there was one and it is
    over" is a banner nobody needs and a client would read as current.
    """

    model_config = ConfigDict(extra="forbid")

    state: Literal["none", "scheduled", "draining", "active"]
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = None


def _int(payload: dict[str, Any], key: str) -> int:
    """One count out of a stored probe, defensively.

    `jsonb` comes back as `Any`-shaped Python, and this row was written by a worker that
    may be a deploy behind — a key it did not write yet, or wrote as null, must render as
    zero rather than 500 the ops screen an operator is reading mid-window.
    """
    value = payload.get(key)
    return int(value) if isinstance(value, int | float | str) else 0


def _in_flight_out(
    payload: dict[str, Any] | None, measured_at: datetime | None
) -> InFlightOut | None:
    """A stored probe as the console reads it. `None` in, `None` out — a window that has
    not been probed yet renders nothing rather than four zeros, which would read as
    "drained" on a drain that has not run."""
    if payload is None:
        return None
    return InFlightOut(
        calls=_int(payload, "calls"),
        jobs=_int(payload, "jobs"),
        tenants_unreached=_int(payload, "tenants_unreached"),
        complete=bool(payload.get("complete", False)),
        measured_at=measured_at,
    )


def _out(window: MaintenanceWindow) -> MaintenanceWindowOut:
    return MaintenanceWindowOut(
        id=window.id,
        reason=window.reason,
        starts_at=window.starts_at,
        ends_at=window.ends_at,
        state=window.state,
        max_drain_minutes=window.max_drain_minutes,
        drain_deadline_at=window.drain_deadline_at,
        activated_at=window.activated_at,
        forced=window.forced,
        # The straggler report carries the instant of ACTIVATION, not of the last probe:
        # it is the measurement the activation decision was taken on, and dating it from a
        # later probe would misattribute it.
        stragglers=_in_flight_out(window.stragglers, window.activated_at),
        in_flight=_in_flight_out(window.in_flight, window.probed_at),
        ended_at=window.ended_at,
        cancelled_at=window.cancelled_at,
        announced=window.announced,
    )


async def _nudge() -> None:
    """Ask the actuator to run NOW rather than at the next fifteen-second beat.

    Best-effort by construction and that is safe: the cron runs regardless, so a Redis blip
    costs an operator a few seconds of latency on a button and costs the window nothing.
    Raising here would refuse a write that has already committed, which is the worse
    failure — `dial_recall_not_queued` records the same reasoning on the halt path.

    The job id carries a one-second bucket so a double-click enqueues once while a genuine
    second action a moment later still enqueues. `maintenance_tick` is idempotent anyway
    (every transition inside it is a compare-and-swap), so the bucket is a courtesy to the
    queue rather than a correctness device.
    """
    try:
        await enqueue(
            MAINTENANCE_TICK_JOB,
            job_id=job_id_for(MAINTENANCE_TICK_JOB, "nudge", str(int(time.time()))),
        )
    except Exception:
        log.warning("maintenance_tick_not_nudged")


@router.get("", response_model=MaintenanceBoardOut, openapi_extra=permission_meta("ops:manage"))
async def read_maintenance(
    session: GlobalSession,
    _: MaintenanceOperator,
    limit: HistoryLimit = DEFAULT_HISTORY,
) -> MaintenanceBoardOut:
    """The open window, if any, and the recent ones.

    `current` is read separately rather than filtered out of `history` because they answer
    different questions and the second is bounded: an operator opening this screen during a
    window must see it whether or not it is inside the newest `limit` rows.
    """
    current = await read_open_window(session)
    return MaintenanceBoardOut(
        current=_out(current) if current else None,
        history=[_out(window) for window in await list_windows(session, limit=limit)],
    )


@router.post(
    "",
    response_model=MaintenanceWindowOut,
    status_code=201,
    openapi_extra=permission_meta("ops:manage"),
    summary="Schedule a maintenance window (step-up confirmed, audited)",
)
async def create_maintenance(
    payload: MaintenanceScheduleIn,
    session: GlobalSession,
    request: Request,
    step_up: StepUpGate,
    principal: MaintenanceOperator,
    x_confirm_action: ConfirmAction = None,
) -> MaintenanceWindowOut:
    step_up.require(x_confirm_action, maintenance_confirmation("schedule_maintenance"))
    window = await schedule_window(
        session,
        reason=payload.reason,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        max_drain_minutes=payload.max_drain_minutes,
        actor_id=principal.user_id,
    )
    await write_audit(
        session,
        action="ops.maintenance_scheduled",
        actor=principal,
        object_type="platform_maintenance_window",
        object_id=str(window.id),
        ip=client_request_ip(request),
        # The reason is an operator's free text and goes to the log stream with the rest of
        # the summary, never to a column read as current (`platform_state.halt_reason`
        # argues the distinction). The window row holds it because clients are shown it.
        summary={
            "starts_at": window.starts_at.isoformat(),
            "ends_at": window.ends_at.isoformat(),
            "max_drain_minutes": window.max_drain_minutes,
            "reason": window.reason,
        },
    )
    await _nudge()
    return _out(window)


@router.patch(
    "/{window_id}",
    response_model=MaintenanceWindowOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Amend an open window (step-up confirmed, audited)",
)
async def amend_maintenance(
    window_id: UUID,
    payload: MaintenanceAmendIn,
    session: GlobalSession,
    request: Request,
    step_up: StepUpGate,
    principal: MaintenanceOperator,
    x_confirm_action: ConfirmAction = None,
) -> MaintenanceWindowOut:
    """Move the end, rewrite the reason, extend the drain — and, before it is announced,
    move the start. `ops/maintenance.amend_window` owns which of those an announced window
    may still take, and refuses the rest by name."""
    if payload.model_dump(exclude_none=True) == {}:
        raise ProblemError(
            kind="validation",
            code="maintenance_amend_empty",
            title="Nothing to change",
            detail="Change at least one of the start, the end, the reason or the drain bound.",
        )
    step_up.require(x_confirm_action, maintenance_confirmation("amend_maintenance", window_id))
    window = await amend_window(
        session,
        window_id=window_id,
        reason=payload.reason,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        max_drain_minutes=payload.max_drain_minutes,
    )
    await write_audit(
        session,
        action="ops.maintenance_amended",
        actor=principal,
        object_type="platform_maintenance_window",
        object_id=str(window.id),
        ip=client_request_ip(request),
        summary={
            "changed": sorted(payload.model_dump(exclude_none=True)),
            "starts_at": window.starts_at.isoformat(),
            "ends_at": window.ends_at.isoformat(),
            "reason": window.reason,
        },
    )
    await _nudge()
    return _out(window)


@router.post(
    "/{window_id}/cancel",
    response_model=MaintenanceWindowOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Call off a window that has not finished (step-up confirmed, audited)",
)
async def cancel_maintenance(
    window_id: UUID,
    session: GlobalSession,
    request: Request,
    step_up: StepUpGate,
    principal: MaintenanceOperator,
    x_confirm_action: ConfirmAction = None,
) -> MaintenanceWindowOut:
    """`scheduled -> cancelled`. A window that has BEGUN is ended, not cancelled.

    The difference is not pedantry and `cancel_window` argues it in full: a cancellation
    means nothing happened, and the moment a window starts draining it has paused every
    running campaign in the fleet and rewritten what every live inbound agent says. That
    work is put back by exactly one terminal state — `completed` — so `draining` and
    `active` are reached through `/end`, and the refusal below names it.
    """
    step_up.require(x_confirm_action, maintenance_confirmation("cancel_maintenance", window_id))
    changed = await cancel_window(session, window_id=window_id)
    window = await read_window(session, window_id)
    if changed:
        await write_audit(
            session,
            action="ops.maintenance_cancelled",
            actor=principal,
            object_type="platform_maintenance_window",
            object_id=str(window.id),
            ip=client_request_ip(request),
            summary={"was": window.state, "starts_at": window.starts_at.isoformat()},
        )
        # A window cancelled mid-DRAIN owes the same restoration as one that completes:
        # campaigns to resume, agents to put back. The tick does it either way — it reads
        # the row's terminal state, not the verb that got it there.
        await _nudge()
    return _out(window)


@router.post(
    "/{window_id}/end",
    response_model=MaintenanceWindowOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="End a window early and give clients their portal back (step-up confirmed)",
)
async def end_maintenance(
    window_id: UUID,
    session: GlobalSession,
    request: Request,
    step_up: StepUpGate,
    principal: MaintenanceOperator,
    x_confirm_action: ConfirmAction = None,
) -> MaintenanceWindowOut:
    """Finish now: set `ends_at` to this instant and let the actuator complete it.

    ═══ WHY THIS MOVES A TIMESTAMP RATHER THAN CALLING `complete_window` ═══

    Because completion is not one write. It restores the load-shed mode, resumes every
    campaign this window paused and republishes every live answering agent — minutes of
    fleet walk and vendor round trips, which cannot run in a request. If this handler
    transitioned the row itself, the window would read `completed` while the platform was
    still shut and every campaign still paused, and the tick would find nothing to act on.

    Moving `ends_at` puts the window into exactly the state the scheduled path produces at
    its natural end, so ONE code path does the completion and there is no second one to get
    subtly different. The operator waits about a second.
    """
    step_up.require(x_confirm_action, maintenance_confirmation("end_maintenance", window_id))
    existing = await read_window(session, window_id)
    if not existing.open:
        raise ProblemError(
            kind="business_rule",
            code="maintenance_window_closed",
            title="That window is already over",
            detail=f"The window is {existing.state}; there is nothing to end.",
            status=409,
        )
    if existing.state == "scheduled":
        # A window that has not begun has nothing to end and nothing to put back. Setting
        # its end to now would also put `ends_at` BEFORE `starts_at`, which the row's own
        # CHECK forbids — so without this the operator would meet a constraint-shaped
        # validation error instead of the verb they actually wanted.
        raise ProblemError(
            kind="business_rule",
            code="maintenance_not_started",
            title="That window has not started",
            detail=(
                "This window is still scheduled, so there is nothing to end. Call it off "
                "instead — clients who were told about it are told it is off."
            ),
            status=409,
            remediation="Use Call it off rather than End now.",
        )
    window = await amend_window(session, window_id=window_id, ends_at=_now())
    await write_audit(
        session,
        action="ops.maintenance_end_requested",
        actor=principal,
        object_type="platform_maintenance_window",
        object_id=str(window.id),
        ip=client_request_ip(request),
        summary={"was": existing.state, "scheduled_end": existing.ends_at.isoformat()},
    )
    await _nudge()
    return _out(window)


def _now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


@client_router.get(
    "",
    response_model=ClientMaintenanceOut,
    openapi_extra=permission_meta("org:read"),
    summary="Is Calevate about to go down, or down now?",
)
async def my_maintenance(
    session: GlobalSession,
    _: AnyClient,
) -> ClientMaintenanceOut:
    """The banner's source, and the only maintenance fact a client is given by name.

    ═══ WHY THIS EXISTS AT ALL, GIVEN THE 503 CARRIES THE SAME WORDS ═══

    The 503 answers a client who is ALREADY locked out. This answers the one who is not
    yet: the console shows a banner for a window that is `scheduled` or `draining`, which
    are precisely the states in which nothing is shed and no 503 is produced. Without it a
    client's first notice would be the door closing.

    ═══ IT IS SHED DURING THE WINDOW, AND THAT IS CORRECT ═══

    `maintenance` sheds reads, `/v1/maintenance` is not exempt, and so during an ACTIVE
    window this route answers the same 503 as everything else — carrying the reason, the
    `Retry-After` and the `platform_maintenance` code. The console renders the lockout page
    from that refusal. Exempting it would be a second way to learn the same fact, and the
    503 is the one that reaches every screen rather than the one screen that thought to ask.

    `org:read` because every client role holds it: the banner is not a privilege.
    """
    window = await read_open_window(session)
    if window is None or window.state not in ("scheduled", "draining"):
        # `active` cannot reach here (the shed refuses first), and a terminal window is not
        # a window. Both answer `none` rather than leaking a state a client cannot act on.
        return ClientMaintenanceOut(state="none")
    return ClientMaintenanceOut(
        state="scheduled" if window.state == "scheduled" else "draining",
        starts_at=window.starts_at,
        ends_at=window.ends_at,
        reason=window.reason,
    )


__all__ = [
    "DEFAULT_HISTORY",
    "MAINTENANCE_TICK_JOB",
    "MAX_HISTORY",
    "client_router",
    "maintenance_confirmation",
    "router",
]
