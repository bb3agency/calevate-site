"""The call-backs an agent promised, as the client sees them (D-514).

    GET    /v1/callbacks              every promise, soonest activity first
    GET    /v1/callbacks/{id}         one of them
    PATCH  /v1/callbacks/{id}         move one that is still waiting
    DELETE /v1/callbacks/{id}         call one off before it rings
    POST   /v1/callbacks/bulk         move or call off the ticked ones

NO WAY TO CREATE ONE HERE. A caller asks for one mid-call (the in-call tool in
`apps/voice-runtime`), or a person books one on a lead (`POST /v1/leads/{id}/callbacks`,
`crm/swipe_routes.py`), which keeps the lead it is about. Moving and calling off go through
`crm/swipe.change_callback`, which Pip's call-back actions call too.

**THE SCREEN READS SENTENCES, NOT STATUS WORDS.** `status` is our vocabulary and it is
returned because a screen needs something to sort and filter on, but every row also
carries `explanation` — the gate's OWN client-facing sentence for why a promise was not
kept ("This number is on the do-not-call list."), or the plain reading of the ending it
reached. A client looking at a call-back that did not happen must not be shown a word
like `refused` and left to guess.

PERMISSIONS. Reading is `leads:read` — a call-back belongs to the same screen as the lead
it came from, and a person who may see the lead may see what was promised to them.
Moving and cancelling are `leads:dispatch`, the permission that already governs who may
cause a call to be placed: when it rings, or whether it does, is the same decision, which
is `dnc_routes.py`'s argument for the same pairing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.callbacks import service as callbacks
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm import swipe

router = APIRouter(prefix="/v1/callbacks", tags=["callbacks"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py` and this module is one — but the aliases are still clearer, and they are
# what `dnc_routes.py` does.
Reader = Annotated[Principal, Depends(requires("leads:read"))]
Dispatcher = Annotated[Principal, Depends(requires("leads:dispatch"))]

#: The most promises one page returns. Bounded because the list is CALLER-CONTROLLED in
#: the strictest sense this product has — every row was minted by somebody on a phone call
#: asking for one (`scripts/check_list_bounds.py`'s test for needing a ceiling at all).
MAX_PAGE = 200

#: What each ending means, in the client's words rather than ours. A status the screen can
#: sort on AND a sentence it can print, because "refused" is our vocabulary and "we could
#: not make this call" is theirs.
#:
#: **EVERY STATUS IS HERE, INCLUDING THE TWO THAT USUALLY CARRY SOMETHING BETTER.** An
#: earlier draft left `refused` and `missed` out on the ground that both always arrive with
#: the compliance gate's own sentence on the row, which is more specific than anything
#: writable here. The first half is true and the "always" is not: `DispatchDecision.reason`
#: is `str | None`, so a refusal that named a rule and no sentence would reach the screen as
#: a BLANK CELL under a status word — the exact failure this module's docstring says it
#: exists to prevent, arriving through the one path nobody would look at. The stored
#: sentence still WINS wherever there is one (see `_view`); these are the floor under it,
#: and they are deliberately vaguer because a specific claim we cannot support is worse
#: than an honest general one.
_ENDINGS: dict[str, str] = {
    "scheduled": "Waiting for the time they asked for.",
    "dialing": "Calling them now.",
    "completed": "We called them at the time they asked for.",
    "cancelled": "Called off before it went out.",
    "failed": "The phone system could not place this call.",
    "refused": "We were not allowed to make this call.",
    "missed": "We ran out of time to make this call.",
}


class ScheduledCallbackOut(BaseModel):
    """One promise. Instants are UTC on the wire and rendered in IST by the browser —
    the repo convention, and the reason this model carries no formatted string: a time
    formatted on the server is a time formatted in the server's idea of the day."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    agent_id: UUID
    lead_id: UUID | None
    #: The number we promised to ring. E.164, and it is the client's own contact — the
    #: same field their Leads screen already shows them.
    phone_e164: str
    #: When we said we would call.
    requested_at: datetime
    status: str
    #: How many times a tick has tried. Zero on a promise whose time has not come.
    attempts: int
    #: WHY, in a sentence a person can act on. Never a rule name — those go in the log and
    #: the runbook, not on a client's screen.
    explanation: str
    #: The call this became, once there was one.
    last_call_id: UUID | None
    settled_at: datetime | None
    #: What the caller said they wanted the call about, in the agent's own short words.
    note: str | None


def _view(row: dict[str, object]) -> ScheduledCallbackOut:
    """One database row as the client's version of it.

    THE SENTENCE IS RESOLVED HERE AND NOT IN THE SERVICE, because it is presentation: the
    service's job is the state machine, and `last_refusal_reason` is already the gate's
    own client-facing words when there is one.

    THE STORED SENTENCE WINS AND `_ENDINGS` IS THE FLOOR. Order matters both ways: the
    gate's own words are more specific than anything this map can say, and the map is what
    stops a status with no sentence behind it rendering as a blank cell.
    """
    status = str(row["status"])
    stored = row["last_refusal_reason"]
    explanation = str(stored) if stored else _ENDINGS.get(status, "")
    return ScheduledCallbackOut(
        id=UUID(str(row["id"])),
        agent_id=UUID(str(row["agent_id"])),
        lead_id=UUID(str(row["lead_id"])) if row["lead_id"] else None,
        phone_e164=str(row["phone_e164"]),
        requested_at=row["requested_at"],  # type: ignore[arg-type]
        status=status,
        attempts=int(str(row["attempts"])),
        explanation=explanation,
        last_call_id=UUID(str(row["last_call_id"])) if row["last_call_id"] else None,
        settled_at=row["settled_at"],  # type: ignore[arg-type]
        note=str(row["note"]) if row["note"] else None,
    )


@router.get(
    "",
    response_model=list[ScheduledCallbackOut],
    openapi_extra=permission_meta("leads:read"),
    summary="The call-backs your agents promised",
    description=(
        "Every time a caller asked to be rung back at a particular time, and what "
        "happened to that promise. Most recent first.\n\n"
        "Set `open_only` to see just the ones still to come."
    ),
)
async def list_callbacks(
    session: Session,
    _: Reader,
    limit: int = Query(MAX_PAGE, ge=1, le=MAX_PAGE),
    open_only: bool = Query(False),
) -> list[ScheduledCallbackOut]:
    rows = await callbacks.list_callbacks(session, limit=limit, open_only=open_only)
    return [_view(row) for row in rows]


@router.get(
    "/{callback_id}",
    response_model=ScheduledCallbackOut,
    openapi_extra=permission_meta("leads:read"),
    summary="One promised call-back",
)
async def get_callback(callback_id: UUID, session: Session, _: Reader) -> ScheduledCallbackOut:
    row = await callbacks.get_callback(session, callback_id)
    if row is None:
        raise ProblemError.not_found("Call-back")
    return _view(row)


#: Kept under its old name for the screens' tests; the one sentence lives in `crm/swipe`.
CANCELLED_BY_CLIENT = swipe.CANCELLED_BY_CLIENT

_NOT_STOPPABLE_REMEDIATION = (
    "It is either being placed right now, or it has already finished. The call itself will "
    "show on this lead once it has."
)


def _refuse(out: swipe.CallbackChangeOut, *, verb: str) -> None:
    """404 for a promise that is not there, 409 for one already claimed or ended: "it is
    gone" means look again; "it is being placed now" means the phone may be ringing and
    there is nothing to undo."""
    if out.status == "not_found":
        raise ProblemError.not_found("Call-back")
    if out.status == "not_waiting":
        raise ProblemError.conflict(
            "callback_not_stoppable",
            f"This call-back can no longer be {verb}.",
            remediation=_NOT_STOPPABLE_REMEDIATION,
        )
    if out.status == "blocked":
        raise ProblemError.business_rule(
            "callback_blocked", out.reason or "The calling rules refuse this call-back."
        )


async def _audit_change(
    session: AsyncSession, request: Request, principal: Principal, out: swipe.CallbackChangeOut
) -> None:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    await write_audit(
        session,
        action="callback.cancelled" if out.status == "cancelled" else "callback.rescheduled",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="callback",
        object_id=str(out.callback_id),
        ip=client_request_ip(request),
        summary=None if out.requested_at is None else {"at": out.requested_at.isoformat()},
    )


async def _read_back(session: AsyncSession, callback_id: UUID) -> ScheduledCallbackOut:
    row = await callbacks.get_callback(session, callback_id)
    if row is None:
        raise ProblemError.not_found("Call-back")
    return _view(row)


@router.delete(
    "/{callback_id}",
    response_model=ScheduledCallbackOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Call off a promised call-back",
    description=(
        "Stops a call-back that has not gone out yet. A call-back that is already being "
        "placed cannot be stopped here — the phone may already be ringing — and one that "
        "has already ended stays as it ended."
    ),
)
async def cancel_callback(
    callback_id: UUID,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> ScheduledCallbackOut:
    """Cancel, then read back — so the response is what the row IS, not what we asked for."""
    assert principal.tenant_id is not None
    out = await swipe.change_callback(
        session, tenant_id=principal.tenant_id, callback_id=callback_id, change="cancel"
    )
    _refuse(out, verb="called off")
    await _audit_change(session, request, principal, out)
    return await _read_back(session, callback_id)


class CallbackMoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The new time, with its offset (IST: +05:30). Between 09:00 and 21:00 IST, at least two
    #: minutes from now and at most 30 days ahead.
    at: datetime


@router.patch(
    "/{callback_id}",
    response_model=ScheduledCallbackOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Move a waiting call-back to another time, 09:00-21:00 IST",
    description=(
        "Moves a call-back that has not gone out yet. Refused when it is already being "
        "placed or has ended (409), or when a calling rule that waiting cannot lift refuses "
        "the number (422)."
    ),
)
async def move_callback(
    callback_id: UUID,
    payload: CallbackMoveIn,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> ScheduledCallbackOut:
    """`leads:dispatch` for `cancel_callback`'s reason: when a phone rings is the same
    decision as whether it does. No `Idempotency-Key`: moving to one time twice is one move."""
    assert principal.tenant_id is not None
    swipe.check_schedule_time(payload.at, now=datetime.now(UTC))
    out = await swipe.change_callback(
        session,
        tenant_id=principal.tenant_id,
        callback_id=callback_id,
        change="move",
        at=payload.at,
    )
    _refuse(out, verb="moved")
    await _audit_change(session, request, principal, out)
    return await _read_back(session, callback_id)


class CallbacksBulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: swipe.CallbackChange
    #: The rows ticked on the Call-backs screen; at most one page of it.
    callback_ids: list[UUID] = Field(min_length=1, max_length=MAX_PAGE)
    #: With `move`: the new time for every one of them, as for a single move.
    at: datetime | None = None


class CallbacksBulkOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: One per requested call-back, in the order asked; each says what happened and why not.
    results: list[swipe.CallbackChangeOut]
    changed: int


@router.post(
    "/bulk",
    response_model=CallbacksBulkOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Move or call off many waiting call-backs at once",
    description=(
        "The Call-backs screen's selection. Each one is changed on its own: one that is "
        "already being placed, has ended or is refused by a calling rule is left as it is "
        "and says why, and the rest still change."
    ),
)
async def change_callbacks(
    payload: CallbacksBulkIn,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> CallbacksBulkOut:
    """Bounded by one page (`MAX_PAGE`), so it runs in the request; Pip's
    `callbacks_change_bulk` takes any number as a plan and calls the same function per row."""
    assert principal.tenant_id is not None
    if payload.action == "move":
        if payload.at is None:
            raise ProblemError(
                kind="validation",
                code="callback_time_missing",
                title="Say when to move them to",
                detail="Moving call-backs needs the new time.",
                remediation="Send `at`, between 9am and 9pm India time.",
            )
        swipe.check_schedule_time(payload.at, now=datetime.now(UTC))
    results: list[swipe.CallbackChangeOut] = []
    for callback_id in dict.fromkeys(payload.callback_ids):
        out = await swipe.change_callback(
            session,
            tenant_id=principal.tenant_id,
            callback_id=callback_id,
            change=payload.action,
            at=payload.at,
        )
        if out.status in ("cancelled", "moved"):
            await _audit_change(session, request, principal, out)
        results.append(out)
    return CallbacksBulkOut(
        results=results,
        changed=sum(1 for out in results if out.status in ("cancelled", "moved")),
    )


__all__ = [
    "MAX_PAGE",
    "CallbackMoveIn",
    "CallbacksBulkIn",
    "CallbacksBulkOut",
    "ScheduledCallbackOut",
    "router",
]
