"""A PLATFORM-WIDE suppression must reach the promises too — in every account at once.

D-514 built two doors between a do-not-call entry and a booked call-back and named both:
`check_dispatch` at fire time is the ENFORCEMENT ("the door that cannot be forgotten"), and
cancelling the live promise inside the suppression's own transaction is the HONESTY —
*"so the client's screen stops saying 'Tuesday' the moment they suppress the number"*.

The honesty door reached the console's bulk paste (`dnc.add_numbers`) and then, on
19 Sep 2026, the single-number writer every dial-gate reader is documented against
(`compliance.service.add_to_dnc`, which is what `record_call_optout` calls when a caller
says "stop calling me" mid-call). It never reached `dnc.add_global_numbers` — the
STRONGEST suppression this platform can write, the one an operator makes on a regulator's
instruction, binding every client at once. So the weakest door was honest and the strongest
one was not.

**AND IT COULD NOT HAVE BEEN FIXED BY CALLING `cancel_for_phones`**, which is why this file
exists at the table rather than at the route. That function has no `tenant_id` in its WHERE
— RLS supplies it — and `add_global_numbers` runs on a session with NO `app.tenant_id`
(ops only, `core/deps.global_db`), against a FORCE-RLS'd table whose policy is
`tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. The statement would
have matched zero rows in every account and returned 0: a silent no-op with the shape of a
fix. `cancel_for_phones_fleet_wide` asks each tenant in turn under that tenant's own
policy, so:

* the cancellation has to be proved in TWO accounts (`test_...every_account`), because one
  account passing is exactly what a tenant-scoped door already did; and
* the isolation has to be proved to SURVIVE the walk (`test_the_walk_leaves_no_tenant_
  context_behind`, `test_one_tenants_promises_are_still_invisible_to_another`) — a walk
  that sets `app.tenant_id` and forgets to put it back would leave the ops session, and
  the audit row it writes next, running as whichever tenant it reached last.

Nobody was going to be TELEPHONED either way: `dnc` is in `PERSON_LEVEL_REFUSALS` and the
gate reads the list uncached per number, so the promise settles `refused` on the next tick.
What was wrong is what every one of those clients was being SHOWN, which is the whole of
what the second door is for.

CONCURRENCY: every test mints its own number. A `dnc_list` global row belongs to no tenant
and no fixture tears it down, so a constant would couple runs (`dnc_global_scope_rls_test`
makes the same choice for the same reason).
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.callbacks import service as callbacks
from apps.api.compliance import dnc
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.scheduled_callback_test import _book, _row, _tenant

pytestmark = pytest.mark.anyio


def _number() -> str:
    """A fresh dialable Indian mobile per test, for the reason in the module docstring."""
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


async def _suppress_globally(*numbers: str) -> dnc.AddResult:
    """The ops door, driven exactly as `national_dnd_routes.suppress_globally` drives it:
    one `global_db` session with no tenant GUC, committed at the end of the request. The
    client directory the cancellation needs is read by `add_global_numbers` itself, on a
    session of its own — see its docstring for why it is not asked of the caller."""
    async with untenanted_session() as session:
        result = await dnc.add_global_numbers(
            session, raw_numbers=list(numbers), source="regulator"
        )
        await session.commit()
    return result


async def test_a_platform_wide_suppression_stops_the_promise_in_every_account() -> None:
    """THE DEFECT. Two unrelated clients have each promised to ring the same number back;
    operations suppress it for the whole platform; both screens must stop naming a time.
    """
    tenant_a, agent_a = await _tenant()
    tenant_b, agent_b = await _tenant()
    phone = _number()
    promise_a = await _book(tenant_a, agent_a, phone=phone)
    promise_b = await _book(tenant_b, agent_b, phone=phone)

    result = await _suppress_globally(phone)
    assert result.added == 1

    for tenant_id, promise in ((tenant_a, promise_a), (tenant_b, promise_b)):
        row = await _row(tenant_id, promise)
        assert row["status"] == "cancelled"
        # The sentence a client reads, not our word for the rule. One wording for every
        # door (`compliance/models.CALLBACK_SUPPRESSED_REASON`), so a reader cannot tell
        # which writer suppressed the number.
        assert "do-not-call" in str(row["last_refusal_reason"]).lower()


async def test_it_stops_only_the_suppressed_number() -> None:
    """The other direction, which is the half a walk with a blanket UPDATE would pass."""
    tenant_id, agent_id = await _tenant()
    suppressed = await _book(tenant_id, agent_id, phone=_number())
    bystander = _number()
    untouched = await _book(tenant_id, agent_id, phone=bystander)

    async with tenant_session(tenant_id) as session:
        row = await callbacks.get_callback(session, suppressed)
    assert row is not None
    await _suppress_globally(str(row["phone_e164"]))

    assert (await _row(tenant_id, suppressed))["status"] == "cancelled"
    assert (await _row(tenant_id, untouched))["status"] == "scheduled"


async def test_a_dial_already_in_flight_is_left_alone() -> None:
    """`cancel_for_phones`' own rule, asserted through the fleet-wide caller: a `dialing`
    row is a phone that may be ringing, and telling a client the call was called off while
    their lead's handset rings is the one wrong answer this screen can give. The fire-time
    gate is what covers that row."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    promised = await _book(tenant_id, agent_id, phone=phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE scheduled_callbacks SET status = 'dialing' WHERE id = :id"),
            {"id": promised},
        )
        await session.commit()

    await _suppress_globally(phone)

    assert (await _row(tenant_id, promised))["status"] == "dialing"


async def test_the_walk_leaves_no_tenant_context_behind() -> None:
    """HARD RULE 1. The ops session is untenanted and everything after the suppression on
    it — the audit row `national_dnd_routes.suppress_globally` writes next — depends on it
    staying that way. A walk that set `app.tenant_id` and did not put it back would leave
    that session reading and writing as whichever tenant it reached last.
    """
    tenant_id, agent_id = await _tenant()
    phone = _number()
    await _book(tenant_id, agent_id, phone=phone)

    async with untenanted_session() as session:
        await dnc.add_global_numbers(session, raw_numbers=[phone], source="regulator")
        # Still no tenant: the GUC is back to the empty string the factory left it at...
        guc = (
            await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
        ).scalar_one()
        assert guc in (None, "")
        # ...and the table therefore still fails closed on this session, which is the
        # property the walk borrowed and had to give back.
        visible = (
            await session.execute(text("SELECT count(*) FROM scheduled_callbacks"))
        ).scalar_one()
        assert visible == 0
        await session.commit()


async def test_one_tenants_promises_are_still_invisible_to_another() -> None:
    """CROSS-TENANT ZERO ROWS, taken AFTER a fleet-wide walk has run — the walk is the only
    thing in this tree that sets one tenant's GUC on a session another caller will use, so
    the isolation is re-proved on the far side of it rather than assumed."""
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    phone = _number()
    await _book(tenant_a, agent_a, phone=phone)

    await _suppress_globally(phone)

    async with tenant_session(tenant_b) as session:
        assert await callbacks.list_callbacks(session, limit=50) == []
    async with tenant_session(tenant_a) as session:
        mine = await callbacks.list_callbacks(session, limit=50)
    assert len(mine) == 1


async def test_a_re_add_of_an_unchanged_list_cancels_nothing() -> None:
    """`fresh` ONLY, like the recall beside it. A second run of the same regulator list
    must not re-walk every tenant, and — more visibly — must not cancel a promise booked
    since, which would be the suppression appearing to act twice."""
    tenant_id, agent_id = await _tenant()
    phone = _number()
    await _suppress_globally(phone)

    booked_after = await _book(tenant_id, agent_id, phone=phone)
    result = await _suppress_globally(phone)

    assert result.added == 0
    assert result.already_suppressed == 1
    # The gate refuses this dial at its fire time (`dnc` is person-level), so nobody is
    # rung; what is asserted here is that the second ADD did no work of its own.
    assert (await _row(tenant_id, booked_after))["status"] == "scheduled"
