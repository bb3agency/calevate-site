"""A suppression added ONE NUMBER AT A TIME must reach the promises, not only the queue.

D-514 built two doors between a do-not-call entry and a booked call-back, and named both:
`check_dispatch` at fire time is the ENFORCEMENT ("the door that cannot be forgotten"), and
`dnc.add_numbers` cancelling live promises in the suppression's own transaction is the
HONESTY — *"so the client's screen stops saying 'Tuesday' the moment they suppress the
number"*.

The honesty door was built on ONE of the three writers of `dnc_list`. The console's bulk
paste got it; `compliance.service.add_to_dnc` — the single-number writer that every
dial-gate reader is documented against, and the one `compliance.optout.record_call_optout`
calls when a caller says "stop calling me" WHILE THEY ARE ON THE PHONE — did not. So the
path where the person themselves asked was the path that kept promising to ring them, and
the client's Call-backs screen went on naming a time for somebody who had just withdrawn.

Nobody was going to be telephoned: `dnc` is in `PERSON_LEVEL_REFUSALS`, so the next tick
settles the promise `refused` against an uncached per-number read. What was wrong is what
the client was being SHOWN, which is the whole of what the second door is for.

`dialing` is asserted UNTOUCHED here for `cancel_for_phones`' own reason: that dial is in
flight or has already rung, and rewriting its state would tell the client a call was called
off while their lead's phone was ringing as we wrote it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.compliance.optout import CALL_OPTOUT_SOURCE
from apps.api.compliance.service import add_to_dnc
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.scheduled_callback_test import CALLER, _book, _row, _tenant

pytestmark = pytest.mark.anyio

#: A second real-shaped mobile, so "this suppression cancelled everything in sight" and
#: "this suppression cancelled the number it names" cannot pass for each other.
BYSTANDER = "+919812345672"


async def test_an_in_call_opt_out_stops_the_promise_the_client_is_being_shown() -> None:
    """THE DEFECT. A caller says "do not call me again" mid-call; `record_call_optout`
    suppresses the number through `add_to_dnc`; the call-back they were promised must stop
    being advertised in the same transaction.
    """
    tenant_id, agent_id = await _tenant()
    promised = await _book(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=CALLER, source=CALL_OPTOUT_SOURCE)
        await session.commit()

    row = await _row(tenant_id, promised)
    assert row["status"] == "cancelled"
    # The reason is the one a client reads on their own screen, so it says what happened
    # rather than naming a table.
    assert "do-not-call" in str(row["last_refusal_reason"]).lower()


async def test_it_stops_only_the_suppressed_number() -> None:
    """The other direction, which is the half a blanket UPDATE would pass without."""
    tenant_id, agent_id = await _tenant()
    suppressed = await _book(tenant_id, agent_id)
    untouched = await _book(tenant_id, agent_id, phone=BYSTANDER)

    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=CALLER, source="manual")
        await session.commit()

    assert (await _row(tenant_id, suppressed))["status"] == "cancelled"
    assert (await _row(tenant_id, untouched))["status"] == "scheduled"


async def test_a_dial_already_in_flight_is_left_alone() -> None:
    """`cancel_for_phones`' own rule, asserted through THIS caller: a `dialing` row is a
    phone that may be ringing, and the fire-time gate is what covers it."""
    tenant_id, agent_id = await _tenant()
    ringing = await _book(tenant_id, agent_id, when=datetime.now(UTC) - timedelta(minutes=1))

    async with tenant_session(tenant_id) as session:
        await callbacks.claim_due(session, limit=5)  # `ringing` becomes `dialing`
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=CALLER, source=CALL_OPTOUT_SOURCE)
        await session.commit()

    assert (await _row(tenant_id, ringing))["status"] == "dialing"


async def test_suppressing_a_number_with_nothing_promised_is_a_no_op() -> None:
    """The common case — most suppressed numbers were never promised anything — must not
    cost a failure, and must still write the suppression."""
    tenant_id, _agent_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=BYSTANDER, source="manual")
        await session.commit()

    async with tenant_session(tenant_id) as session:
        found = (
            await session.execute(
                text("SELECT source FROM dnc_list WHERE phone_e164 = :p"),
                {"p": BYSTANDER},
            )
        ).first()
    assert found is not None and found[0] == "manual"


async def test_a_second_opt_out_on_an_already_settled_promise_changes_nothing() -> None:
    """Idempotence, from the caller `add_to_dnc` was built for: `record_call_optout` may be
    replayed by the post-call pipeline, and a cancelled promise must not be re-cancelled
    under a later timestamp the client would read as new activity."""
    tenant_id, agent_id = await _tenant()
    promised = await _book(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=CALLER, source=CALL_OPTOUT_SOURCE)
        await session.commit()
    first = await _row(tenant_id, promised)

    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=CALLER, source=CALL_OPTOUT_SOURCE)
        await session.commit()
    second = await _row(tenant_id, promised)

    assert first["status"] == second["status"] == "cancelled"
    assert first["settled_at"] == second["settled_at"]


async def test_one_tenants_suppression_cannot_stop_anothers_promise(
    anyio_backend: str,
) -> None:
    """HARD RULE 1 over the new arm. The same person may be a customer of two clients, and
    withdrawing from one is not withdrawing from the other — `tenant_session` is what makes
    that structural, and this asserts the arm did not reach around it."""
    tenant_a, agent_a = await _tenant()
    tenant_b, agent_b = await _tenant()
    theirs = await _book(tenant_b, agent_b)
    _mine = await _book(tenant_a, agent_a)

    async with tenant_session(tenant_a) as session:
        await add_to_dnc(session, tenant_id=tenant_a, phone_e164=CALLER, source=CALL_OPTOUT_SOURCE)
        await session.commit()

    assert (await _row(tenant_b, theirs))["status"] == "scheduled"
    assert uuid.UUID(str(tenant_a)) != uuid.UUID(str(tenant_b))
