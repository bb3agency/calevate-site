"""The call-backs an agent promised, as the client sees them (D-510).

    GET    /v1/callbacks              every promise, soonest activity first
    GET    /v1/callbacks/{id}         one of them
    DELETE /v1/callbacks/{id}         call one off before it rings

THREE ROUTES AND NO WAY TO CREATE ONE, WHICH IS THE POINT. A call-back is booked by a
caller ASKING for one, mid-call, through the in-call tool in `apps/voice-runtime` — that
is the entire feature. A `POST` here would be a second way to make the platform ring
somebody, with no conversation behind it and no execution to attribute it to, and it
would bypass the confirm-before-commit turn that stops a misheard "four" ringing a
household at 04:00. Placing a call to a lead on purpose already has a button, and it is
`POST /v1/leads/{id}/dial`.

**THE SCREEN READS SENTENCES, NOT STATUS WORDS.** `status` is our vocabulary and it is
returned because a screen needs something to sort and filter on, but every row also
carries `explanation` — the gate's OWN client-facing sentence for why a promise was not
kept ("This number is on the do-not-call list."), or the plain reading of the ending it
reached. A client looking at a call-back that did not happen must not be shown a word
like `refused` and left to guess.

PERMISSIONS. Reading is `leads:read` — a call-back belongs to the same screen as the lead
it came from, and a person who may see the lead may see what was promised to them.
Cancelling is `leads:dispatch`, the permission that already governs who may cause a call
to be placed: calling one off is the same decision in the other direction, which is
`dnc_routes.py`'s argument for the same pairing.

This router is NOT mounted here — the integrator mounts it in `main._mount_routers`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.callbacks import service as callbacks
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

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


#: What the row records when a client called a promise off themselves. Their own words are
#: not asked for: a free-text reason on this row would be shown back to whoever reads the
#: screen next, and nothing acts on it.
CANCELLED_BY_CLIENT = "You called this off."


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
    """Cancel, then read back — so the response is what the row IS, not what we asked for.

    A 404 for a promise that is not there, and a 409 for one that has already been claimed
    or has already ended: those are different problems for the person holding the screen.
    "It is gone" means look again; "it is being placed now" means the phone may be ringing
    and there is nothing to undo.
    """
    stopped = await callbacks.cancel_one(session, callback_id, reason=CANCELLED_BY_CLIENT)
    row = await callbacks.get_callback(session, callback_id)
    if row is None:
        raise ProblemError.not_found("Call-back")
    if not stopped:
        raise ProblemError.conflict(
            "callback_not_stoppable",
            "This call-back can no longer be called off.",
            remediation=(
                "It is either being placed right now, or it has already finished. The "
                "call itself will show on this lead once it has."
            ),
        )
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    await write_audit(
        session,
        action="callback.cancelled",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="callback",
        object_id=str(callback_id),
        ip=client_request_ip(request),
    )
    return _view(row)


__all__ = ["MAX_PAGE", "ScheduledCallbackOut", "router"]
