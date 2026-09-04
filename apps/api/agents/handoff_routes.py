"""The handover list, as the client edits it (D-533).

    GET /v1/agents/{agent_id}/handoff   the roster, the switch, and who is on duty NOW
    PUT /v1/agents/{agent_id}/handoff   replace the whole list, the switch and the trigger

**ONE `PUT` OF THE WHOLE THING, NOT FIVE ROUTES OVER ROWS.** "Move Priya above Ravi and
take Ravi off while he is away" is one intention; expressed as a POST, a DELETE and two
PATCHes it is four requests that can half-apply, and the half-applied states are two
people at position 1 (which the unique index refuses, so the client gets a 500 for a
sensible edit) or a roster that is briefly empty (which, if a call lands in that instant,
is a caller told nobody is available). The whole-list write also makes the ORDER an
explicit property of the request rather than something inferred from insertion history.

**THE READ ANSWERS "AND IS IT WORKING RIGHT NOW", which is the question the screen is
actually for.** A list of names does not tell a client whether their next caller will
reach a person: that depends on the master switch, on who is active, and on a clock. So
the response carries `on_duty` and, when nobody is, the reason and the one sentence that
fixes it — the shape `DispatchDecision` already uses on the dial path, for the same reason.

PERMISSIONS. Reading is `agents:read`; writing is `org:manage`, which is what every
CLIENT-REALM agent-configuration write in this product already declares (`POST /v1/agents`,
the script builder, the notice toggles) — `agents:write` is an admin-realm permission no
client role holds, so declaring it here would have made the screen unusable by the person
it is for. It is the right permission substantively as well: putting a named person's
personal mobile on a list that will be DIALLED is an owner's decision, not something a
staff member who can edit leads should be able to do. It is deliberately not a `leads:`
permission — nothing here is about a caller.

**PUBLISHING IS SEPARATE, AND THE RESPONSE SAYS SO.** Editing the roster changes what the
NEXT publish sends; it does not reach a live agent, because the destination is engine
config and only a publish rewrites it. Pretending otherwise — republishing from this
route — would make a typo in a phone number an immediate change to a live call path with
no read-back and no confirmation. `pending_publish` is how the screen tells the client
their change is saved and not yet live.

Hard rule 6: the numbers are staff mobiles. They are returned to a caller who already
holds `agents:read` on this tenant and are written to no log line here.

This router is NOT mounted here — the integrator mounts it in `main._mount_routers`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import handoff as handoff_service
from apps.api.agents.business_hours import DAYS
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible

router = APIRouter(prefix="/v1/agents/{agent_id}/handoff", tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("agents:read"))]
Writer = Annotated[Principal, Depends(requires("org:manage"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DayWindow(Strict):
    """One day's opening window, in the shape `agents.business_hours` already stores.

    `HH:MM`, 24-hour, IST wall clock — the zone is a property of the column and is argued
    in `agents/business_hours.py`, not repeated per request. A pattern rather than a
    `time` type because this round-trips into JSONB that a different writer (the intake
    wizard) also fills, and one storage shape with two spellings is how the two start
    disagreeing about when a shop opens.
    """

    opens: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    closes: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class MemberIn(Strict):
    """One person on the list, as the client writes them."""

    label: str = Field(min_length=1, max_length=120)
    #: E.164. The same expression the column's CHECK carries and the intake wizard
    #: validates with — doubled deliberately, because this number is dialled.
    phone_e164: str = Field(pattern=r"^\+[1-9]\d{7,18}$")
    active: bool = True
    #: This person's OWN hours, or omitted to be reachable whenever the business is open.
    #: A day left out of the map is a day this person is not available — `is_after_hours`
    #: answers "unknown" for it, and an unknown hour is not one we ring a mobile in.
    hours: dict[str, DayWindow | None] | None = None
    note: str | None = Field(default=None, max_length=500)


class HandoffIn(Strict):
    """The whole configuration, replaced in one write."""

    enabled: bool
    #: The client's own words for WHEN to hand over, or null for the composed default.
    #: Bounded because it becomes a tool description the model reads on every turn.
    trigger: str | None = Field(default=None, max_length=1000)
    members: list[MemberIn] = Field(
        default_factory=list, max_length=handoff_service.MAX_HANDOFF_MEMBERS
    )


class MemberOut(Strict):
    id: UUID
    position: int
    label: str
    phone_e164: str
    active: bool
    hours: dict[str, DayWindow | None] | None
    note: str | None
    #: Is this the person a caller would reach RIGHT NOW? Exactly one member can be, and
    #: for a roster where nobody is, none of them is.
    on_duty: bool


class AttemptOut(Strict):
    """One handover that actually happened, as the client sees it.

    **THE NUMBER IS NOT ON THIS OBJECT AND THE LABEL MAY BE NULL**, which is deliberate
    rather than an oversight. `handoff_attempts.destination_e164` records the number that
    rang because an operator may have to answer for it; a client's own screen already knows
    who is on the list and gains nothing from seeing the digits again on every row (hard
    rule 6, minimum necessary). `member` is null when that person has since been removed
    from the roster — the FK is `SET NULL` precisely so removing somebody does not rewrite
    the history of the calls they took — and the row still says what happened.
    """

    id: UUID
    started_at: datetime
    #: The roster member's label at the time, or null if they have since been removed.
    member: str | None
    #: `started` (still in progress), `connected`, `unreached`, `unknown`, `abandoned`.
    outcome: str
    #: One sentence a client can read, because `unreached` is our word and not theirs.
    explanation: str
    #: How long the person and the caller spoke, when the platform reported it.
    duration_s: int | None
    #: The voice platform recorded the transferred leg SEPARATELY and Calevate does not
    #: hold that recording. Surfaced rather than hidden: a client answering a deletion
    #: request needs to know it exists (OPERATIONS §2 gate 46b).
    second_recording_at_platform: bool
    #: The call-back booked because nobody took the call.
    callback_id: UUID | None


#: What each ending means, in the client's words. `callbacks/routes.py` carries the same
#: table for the same reason: a screen must not print a status word and leave a client to
#: guess what happened to their caller.
_OUTCOME_SENTENCES: dict[str, str] = {
    "started": "The call was being put through when we last heard.",
    "connected": "Your caller was put through and someone took the call.",
    "unreached": (
        "Nobody was able to take the call, so we offered your caller a call-back instead."
    ),
    "unknown": ("We could not tell whether anyone took the call — the phone system did not say."),
    "abandoned": (
        "The agent started putting your caller through and the phone system never reported "
        "placing the call."
    ),
}


class HandoffOut(Strict):
    agent_id: UUID
    enabled: bool
    trigger: str | None
    #: What the model is actually told when `trigger` is null — returned so the screen can
    #: SHOW the default rather than an empty box that implies nothing happens.
    effective_trigger: str
    #: What the caller hears while the handover is placed, in this agent's language.
    #: Composed by us and not editable: see `agents/handoff.HANDOFF_SPOKEN_TEMPLATES`.
    spoken_line: str
    members: list[MemberOut]
    #: Null when nobody is on duty; then `unavailable_reason` and `remediation` say why.
    on_duty_member_id: UUID | None
    unavailable_reason: str | None
    remediation: str | None
    #: The most recent handovers this agent actually made, newest first. Bounded — see
    #: `RECENT_ATTEMPTS`; a client wanting the whole history reads it on the calls list,
    #: where each escalated call carries its own row.
    recent: list[AttemptOut]
    #: HAS THIS AGENT EVER BEEN PUBLISHED? The honest half of "is my handover list live".
    #:
    #: False means nothing here is in effect at all — the agent is not on the voice
    #: platform. True does NOT mean the platform is holding today's on-duty member, and
    #: this field deliberately does not claim it does: the destination is engine config,
    #: and whether the engine agrees is a question only the read-back can answer
    #: (`EngineDrift.handoff_applied`), which costs a vendor round trip and belongs on the
    #: screen that already pays for one. A boolean invented here would be our intent
    #: wearing the clothes of a measurement.
    published: bool


_AGENT_SQL = (
    "SELECT id, handoff_enabled, handoff_trigger, business_hours, language_primary, "
    "engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL"
)


async def _agent(session: AsyncSession, agent_id: UUID) -> tuple[Any, ...]:
    row = (await session.execute(text(_AGENT_SQL), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return tuple(row)


async def _render(session: AsyncSession, agent_id: UUID) -> HandoffOut:
    """The whole answer, from the same resolver a publish uses.

    `handoff_service.resolve_on_duty` and not a second walk of the list: a screen that
    said somebody was available while the publish thought otherwise would be worse than a
    screen that said nothing.
    """
    row = await _agent(session, agent_id)
    members = await handoff_service.roster(session, agent_id=agent_id)
    duty = handoff_service.resolve_on_duty(
        members,
        enabled=bool(row[1]),
        agent_hours=row[3],
        at=datetime.now(UTC),
    )
    return HandoffOut(
        agent_id=agent_id,
        enabled=bool(row[1]),
        trigger=row[2],
        effective_trigger=(row[2] or "").strip() or handoff_service.HANDOFF_TRIGGER_DEFAULT,
        spoken_line=handoff_service.spoken_line_for(str(row[4])),
        members=[
            MemberOut(
                id=m.id,
                position=m.position,
                label=m.label,
                phone_e164=m.phone_e164,
                active=m.active,
                hours=_hours_out(m.hours),
                note=m.note,
                on_duty=duty.member is not None and duty.member.id == m.id,
            )
            for m in members
        ],
        recent=await _recent(session, agent_id),
        on_duty_member_id=duty.member.id if duty.member is not None else None,
        unavailable_reason=duty.reason,
        remediation=duty.remediation,
        published=bool(row[5]),
    )


#: How many past handovers the configuration screen carries. BOUNDED because the list
#: grows with a client's call volume and nothing else caps it — `scripts/check_list_bounds`
#: exists for exactly this shape. Ten is what a shop owner glances at to answer "is this
#: working"; the full history is per-call.
RECENT_ATTEMPTS = 10

_RECENT_SQL = (
    "SELECT h.id, h.started_at, m.label, h.outcome, h.leg_duration_s, "
    "  h.leg_recording_present, h.callback_id "
    "FROM handoff_attempts h "
    "LEFT JOIN agent_handoff_members m ON m.id = h.member_id "
    "WHERE h.agent_id = :aid ORDER BY h.started_at DESC LIMIT :lim"
)


async def _recent(session: AsyncSession, agent_id: UUID) -> list[AttemptOut]:
    rows = (
        await session.execute(text(_RECENT_SQL), {"aid": agent_id, "lim": RECENT_ATTEMPTS})
    ).all()
    return [
        AttemptOut(
            id=row[0],
            started_at=row[1],
            member=row[2],
            outcome=row[3],
            explanation=_OUTCOME_SENTENCES.get(
                row[3],
                # Every member of the CHECK is in the table above, so this is unreachable
                # through the front door and is here for the reason `_load_agent` narrows
                # `direction`: a restore without constraints, or a value added to the
                # migration and not here, must produce an honest sentence rather than a
                # KeyError inside a client's screen.
                "We do not have a reading for what happened to this handover.",
            ),
            duration_s=row[4],
            second_recording_at_platform=bool(row[5]),
            callback_id=row[6],
        )
        for row in rows
    ]


def _hours_out(raw: dict[str, Any] | None) -> dict[str, DayWindow | None] | None:
    """The stored JSONB as the wire model, with anything unreadable dropped.

    A day whose stored value is not a window we can parse comes back ABSENT rather than as
    a malformed object: the column is also written by the admin intake wizard, and a shape
    this endpoint cannot render must not be handed to a browser that will then PUT it back.
    Dropping it is visible on the screen (the day shows as unset) which is the outcome a
    client can act on.
    """
    if not raw:
        return None
    out: dict[str, DayWindow | None] = {}
    for day in DAYS:
        if day not in raw:
            continue
        value = raw[day]
        if value is None:
            out[day] = None
            continue
        if isinstance(value, dict) and isinstance(value.get("opens"), str):
            try:
                out[day] = DayWindow(opens=value["opens"], closes=value["closes"])
            except (KeyError, TypeError, ValueError):
                continue
    return out or None


@router.get(
    "",
    response_model=HandoffOut,
    summary="The people this agent hands a caller to, and who is on duty now",
    openapi_extra=permission_meta("agents:read"),
)
async def get_handoff(agent_id: UUID, session: Session, principal: Reader) -> HandoffOut:
    await assert_visible(session, "agent", agent_id)
    return await _render(session, agent_id)


@router.put(
    "",
    response_model=HandoffOut,
    summary="Replace this agent's handover list, its switch and its trigger",
    openapi_extra=permission_meta("org:manage"),
)
async def put_handoff(
    agent_id: UUID,
    payload: HandoffIn,
    session: Session,
    principal: Writer,
    ip: Annotated[str | None, Depends(client_request_ip)],
) -> HandoffOut:
    """Replace the whole configuration in one statement, in the order given.

    **DELETE-THEN-INSERT INSIDE ONE TRANSACTION, and the alternative was worse.** An
    upsert keyed on position would have to reconcile removals anyway, and a diff keyed on
    the member id would let a client renumber two people into the same position halfway
    through. The ids are therefore NOT stable across a write, which is a real consequence
    and a deliberate one: `handoff_attempts.member_id` is `SET NULL` precisely so the
    history of a call somebody took survives the roster being re-ordered, and the number
    that rang is copied onto the attempt row rather than looked up through this table.

    Two things are refused rather than normalised, because both are a client saying
    something they did not mean: the same number twice (one person cannot be two rungs of
    a hunt list, and whichever is second is unreachable), and enabling the feature with
    nobody on the list (an agent that promises a caller a person and has none).
    """
    await assert_visible(session, "agent", agent_id)
    numbers = [m.phone_e164 for m in payload.members]
    if len(set(numbers)) != len(numbers):
        raise ProblemError.business_rule(
            "handoff_duplicate_number",
            "The same phone number appears more than once on this handover list.",
            remediation=(
                "Each person on the list needs their own number — a number listed twice "
                "would only ever be tried once."
            ),
        )
    if payload.enabled and not payload.members:
        raise ProblemError.business_rule(
            "handoff_no_members",
            "Handing calls to a person is switched on, but nobody is on the list.",
            remediation=(
                "Add at least one person who can take a call, or switch handovers off — "
                "callers asking for a person are offered a call-back instead."
            ),
        )
    await session.execute(
        text("DELETE FROM agent_handoff_members WHERE agent_id = :aid"), {"aid": agent_id}
    )
    for position, member in enumerate(payload.members):
        await session.execute(
            text(
                "INSERT INTO agent_handoff_members "
                "(id, tenant_id, agent_id, position, label, phone_e164, hours, active, note) "
                "VALUES (:id, :tid, :aid, :pos, :label, :phone, CAST(:hours AS jsonb), "
                ":active, :note)"
            ),
            {
                "id": uuid7(),
                "tid": principal.tenant_id,
                "aid": agent_id,
                "pos": position,
                "label": member.label.strip(),
                "phone": member.phone_e164,
                "hours": (
                    json.dumps(
                        {
                            day: (None if window is None else window.model_dump())
                            for day, window in member.hours.items()
                        }
                    )
                    if member.hours
                    else None
                ),
                "active": member.active,
                "note": member.note,
            },
        )
    await session.execute(
        text(
            "UPDATE agents SET handoff_enabled = :en, handoff_trigger = :trigger, "
            "updated_at = now() WHERE id = :aid AND deleted_at IS NULL"
        ),
        {
            "en": payload.enabled,
            "trigger": (payload.trigger or "").strip() or None,
            "aid": agent_id,
        },
    )
    # AUDITED, AND THE COUNT IS THE WHOLE RECORD. Who a client's callers get handed to is
    # a decision somebody should be able to answer for months later; the numbers themselves
    # are NOT written here (hard rule 6) — they are in the table this row points at, behind
    # the same role check.
    await write_audit(
        session,
        actor=principal,
        action="agent.handoff.replace",
        object_type="agent",
        object_id=str(agent_id),
        ip=ip,
        summary={"enabled": payload.enabled, "members": len(payload.members)},
    )
    return await _render(session, agent_id)


__all__ = ["router"]
