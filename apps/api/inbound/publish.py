"""Putting an inbound line on the calling platform and on its numbers (D-997).

Two transactions, in this order: the line's own engine agent is created or updated and read
back (`agents/service.publish_line`), then, once that has committed, its numbers are pointed
at it (`agents/service.route_line_numbers`). A number therefore never points at an engine
agent a rolled-back publish left unrecorded. The daily number sweep
(`campaigns/engine_numbers`) holds the same wanted state, so a binding the platform refused
here is repaired there.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents import service as agents_service
from apps.api.agents.models import number_on_hold_sql
from apps.api.agents.service import (
    INBOUND_SILENCE_TRUTHFUL_ANSWER,
    InboundRouting,
    LineTestDial,
)
from apps.api.db.session import tenant_session
from apps.api.inbound import lines

#: A live line's numbers its engine agent answers right now, as `route_line_numbers` and the
#: platform's attachment decide it: not while its voice is switched off, deleted or under the
#: compliance silence, nor a number on hold. A test call rings from one of these unlent; any
#: other number is lent to the line's engine agent for the call.
_ANSWERED_NUMBERS_SQL: Final = (
    "SELECT n.id FROM phone_numbers n JOIN inbound_lines l ON l.id = n.inbound_line_id "
    "JOIN agents a ON a.id = l.agent_id WHERE l.id = :lid AND n.released_at IS NULL "
    "AND a.status = 'live' AND a.deleted_at IS NULL "
    "AND a.inbound_silence_reason IS DISTINCT FROM :truthful "
    f"AND NOT {number_on_hold_sql('n')}"
)


async def put_line_live(*, tenant_id: UUID, line_id: UUID) -> str:
    """Publish the line's engine agent, then route its numbers to it. Returns the ref."""
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_line(session, tenant_id=tenant_id, line_id=line_id)
    await route_numbers(tenant_id=tenant_id, line_id=line_id)
    return ref


#: A line's numbers, whether or not anything is routed to them yet.
_LINE_NUMBERS_SQL: Final = (
    "SELECT id FROM phone_numbers WHERE inbound_line_id = :lid AND released_at IS NULL"
)


async def line_test_dial(
    *, tenant_id: UUID, line_id: UUID, in_client: bool = False
) -> LineTestDial:
    """Get the line's engine agent ready for the owner's test call, in its own committed
    transaction before the dial (`paid_test_calls.refresh_test_copy`'s shape). A live line is
    put live again, so the call hears the script saved now; a draft is published as a test
    holder (`publish_line(test=True)`), which leaves it a draft and its numbers unrouted: in
    our developer workspace, ringing from the shared test line (D-1018), or with `in_client`
    in the client's own, ringing from one of the line's numbers, else the account's first,
    lent to it for the call (D-1020). A full client workspace is refused there
    (`engine_agent_allowance_full`), for the caller to fall back on ours."""
    async with tenant_session(tenant_id) as session:
        live = (await lines.read_line(session, line_id)).live
    if live:
        ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
        async with tenant_session(tenant_id) as session:
            answered = await session.execute(
                text(_ANSWERED_NUMBERS_SQL),
                {"lid": line_id, "truthful": INBOUND_SILENCE_TRUTHFUL_ANSWER},
            )
            routed = frozenset(UUID(str(number_id)) for number_id in answered.scalars())
        return LineTestDial(ref=ref, line_id=line_id, routed_number_ids=routed)
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_line(
            session, tenant_id=tenant_id, line_id=line_id, test=True, in_client=in_client
        )
    if not in_client:
        return LineTestDial(ref=ref, line_id=line_id, developer=True)
    async with tenant_session(tenant_id) as session:
        numbers = await session.execute(text(_LINE_NUMBERS_SQL), {"lid": line_id})
        own = frozenset(UUID(str(number_id)) for number_id in numbers.scalars())
    return LineTestDial(ref=ref, line_id=line_id, line_number_ids=own)


async def route_numbers(*, tenant_id: UUID, line_id: UUID) -> InboundRouting:
    """Point the line's numbers at its engine agent, or release them while its voice is off,
    deleted or silenced. A draft line's numbers go to its voice agent's own engine agent."""
    async with tenant_session(tenant_id) as session:
        return await agents_service.route_line_numbers(session, line_id=line_id)


async def onto_first_line(*, tenant_id: UUID, number_id: UUID) -> UUID | None:
    """A newly bought number is answered by the account's first inbound line whose agent can
    still speak (D-997, D-1012; `lines.first_line`), or by none yet, which the owner is asked
    to fix by making one. A number already on a line (a replayed purchase) keeps it. Every
    purchase door calls this for a number bought to take calls: the client's Buy, Pip's
    `number_buy` and an operator's purchase, since only a line answers a number (D-1019)."""
    async with tenant_session(tenant_id) as session:
        current = (
            await session.execute(
                text("SELECT inbound_line_id FROM phone_numbers WHERE id = :n"), {"n": number_id}
            )
        ).scalar_one_or_none()
        if current is not None:
            return UUID(str(current))
        line_id = await lines.first_line(session)
        if line_id is None:
            return None
        await lines.assign_number(session, UUID(str(line_id)), number_id)
    await route_numbers(tenant_id=tenant_id, line_id=UUID(str(line_id)))
    return UUID(str(line_id))


__all__ = ["line_test_dial", "onto_first_line", "put_line_live", "route_numbers"]
