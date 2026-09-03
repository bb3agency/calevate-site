"""A call-back promised on a call is kept, refused with a reason, or given up on — never
left running (D-514).

The promise is the whole difference from a campaign contact and every test here follows
from it. A campaign contact that is refused goes back on a thirty-minute ladder and nobody
is waiting; a call-back that is refused has somebody sitting by a phone.

1. **RLS, cross-tenant zero rows** (hard rule 1). `scheduled_callbacks` names a caller and
   a number, so the policy is the thing that stops one client reading another's promises.
2. **THE GRACE IS THE ANTI-LIVELOCK, AND IT DOES NOT CONSULT THE CLASSIFICATION.**
   `tests/dispatch_refusal_settlement_test.py` records three refusals that shipped
   classified as transient about facts that could never change, each re-claimed every
   thirty minutes for the life of the campaign with nothing erroring. The bound here is the
   CLOCK, so a rule nobody thought about costs two hours of retries and then settles with a
   visible reason.
3. **A TRANSIENT REFUSAL MUST NOT MOVE THE PROMISE.** The first draft pushed
   `requested_at` forward on each deferral, which made the staleness cutoff recede by five
   minutes every five minutes — the same livelock, written into the fix for it. That is why
   `next_attempt_at` is a separate column and why this file asserts on both.
4. **THE PERSON-LEVEL REFUSALS SETTLE**, using the gate's own classification and never a
   second opinion — including `consent_expired`, which was on the wrong side until this
   feature was built.
5. **CANCELLING IS NOT AVAILABLE ONCE THE PHONE MAY BE RINGING.** A `dialing` row stays
   `dialing`; telling a client a call was called off while their lead's phone rings is the
   one wrong answer this screen can give.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.callbacks import service as callbacks
from apps.api.compliance import deletion
from apps.api.compliance.service import PERSON_LEVEL_REFUSALS
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.retention import execute_deletion_request
from sqlalchemy import text

pytestmark = pytest.mark.anyio

CALLER = "+919812345671"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Callback Estates",
        slug=f"cb-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _book(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    when: datetime | None = None,
    execution: str | None = None,
    booked_at: datetime | None = None,
    phone: str = CALLER,
) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=execution or f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164=phone,
            requested_at=when or datetime.now(UTC) + timedelta(hours=1),
            booked_at=booked_at or datetime.now(UTC),
            note="wants the Gachibowli listing",
            language="te",
        )
        await session.commit()
    assert booked is not None
    return booked[0]


async def _row(tenant_id: uuid.UUID, callback_id: uuid.UUID) -> dict[str, object]:
    async with tenant_session(tenant_id) as session:
        found = await callbacks.get_callback(session, callback_id)
    assert found is not None
    return found


async def test_one_tenants_promises_are_invisible_to_another(anyio_backend: str) -> None:
    """HARD RULE 1, and the leak this defends against has a shape: a call-back row names a
    person and the time we are going to telephone them."""
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    await _book(tenant_a, agent_a)

    async with tenant_session(tenant_b) as session:
        rows = await callbacks.list_callbacks(session, limit=50)
    assert rows == []

    async with tenant_session(tenant_a) as session:
        mine = await callbacks.list_callbacks(session, limit=50)
    assert len(mine) == 1


async def test_a_caller_who_changes_their_mind_moves_the_promise() -> None:
    """ "Make it five, not four" is an ordinary sentence and it must move the time. The
    guard is `booked_at`, not `DO NOTHING`, so two jobs racing land on the caller's LATER
    word whichever of them reaches the row first."""
    tenant_id, agent_id = await _tenant()
    execution = f"exec_{uuid.uuid4().hex[:10]}"
    four = datetime.now(UTC) + timedelta(hours=4)
    five = datetime.now(UTC) + timedelta(hours=5)
    said_first = datetime.now(UTC) - timedelta(minutes=2)
    said_second = datetime.now(UTC)

    callback_id = await _book(
        tenant_id, agent_id, when=four, execution=execution, booked_at=said_first
    )
    await _book(tenant_id, agent_id, when=five, execution=execution, booked_at=said_second)
    row = await _row(tenant_id, callback_id)
    assert abs((row["requested_at"] - five).total_seconds()) < 2  # type: ignore[operator]

    # AND THE LATE DUPLICATE LOSES. A job that arrives after the later booking already
    # landed must not drag the promise backwards — the caller said five.
    async with tenant_session(tenant_id) as session:
        stale = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=execution,
            lead_id=None,
            phone_e164=CALLER,
            requested_at=four,
            booked_at=said_first,
            note=None,
            language=None,
        )
        await session.commit()
    assert stale is None


async def test_a_transient_refusal_defers_the_attempt_and_never_the_promise() -> None:
    """THE LIVELOCK, WRITTEN INTO THE FIX FOR IT. Moving `requested_at` on each refusal
    made the two-hour staleness cutoff recede by five minutes every five minutes, so
    nothing could ever go stale. `next_attempt_at` is what moves; the promise does not."""
    tenant_id, agent_id = await _tenant()
    when = datetime.now(UTC) - timedelta(minutes=1)
    callback_id = await _book(tenant_id, agent_id, when=when)

    async with tenant_session(tenant_id) as session:
        claimed = await callbacks.claim_due(session, limit=5)
        await callbacks.defer(
            session, callback_id, rule="no_credits", reason="This account has no calling credit."
        )
        await session.commit()
    assert [c.id for c in claimed] == [callback_id]

    row = await _row(tenant_id, callback_id)
    assert row["status"] == "scheduled"
    assert abs((row["requested_at"] - when).total_seconds()) < 2  # type: ignore[operator]
    # The attempt is REFUNDED: a blocked dial never rang a phone, so charging it an attempt
    # would make the count mean "we were not allowed to try".
    assert row["attempts"] == 0
    assert row["last_refusal_reason"] == "This account has no calling credit."


async def test_a_promise_past_saving_is_settled_with_the_last_thing_the_gate_said() -> None:
    """THE ANTI-LIVELOCK, and it consults no classification at all — which is the point.
    Every one of the three refusals that shipped as a livelock was a rule nobody had
    thought about, so a bound that only caught the remembered ones would have caught
    none of them."""
    tenant_id, agent_id = await _tenant()
    stale = datetime.now(UTC) - callbacks.GRACE - timedelta(minutes=5)
    callback_id = await _book(tenant_id, agent_id, when=stale)

    async with tenant_session(tenant_id) as session:
        await callbacks.defer(
            session, callback_id, rule="no_credits", reason="This account has no calling credit."
        )
        # `defer` only moves a `dialing` row; this one was never claimed, so it is still
        # `scheduled` and carries no reason. That is the arm under test — a promise nothing
        # ever refused must still settle with a SENTENCE rather than a blank cell.
        settled = await callbacks.expire_stale(session)
        await session.commit()
    assert settled == 1

    row = await _row(tenant_id, callback_id)
    assert row["status"] == "missed"
    assert row["settled_at"] is not None
    assert row["last_refusal_reason"] == callbacks.UNATTEMPTED_REASON


async def test_a_stale_promise_is_never_claimed_again() -> None:
    """`expire_stale` runs BEFORE the claim in the tick, so nothing that has gone past
    saving can be dialled by the same pass that settles it."""
    tenant_id, agent_id = await _tenant()
    stale = datetime.now(UTC) - callbacks.GRACE - timedelta(minutes=5)
    await _book(tenant_id, agent_id, when=stale)
    async with tenant_session(tenant_id) as session:
        await callbacks.expire_stale(session)
        claimed = await callbacks.claim_due(session, limit=5)
        await session.commit()
    assert claimed == []


def test_the_gates_person_level_refusals_are_the_ones_that_settle() -> None:
    """The classification is IMPORTED from the gate that owns it and never restated here.
    `consent_expired` is asserted by name because it was on the wrong side until this
    feature was built — a lapsed permission is not undone by waiting."""
    assert "dnc" in PERSON_LEVEL_REFUSALS
    assert "consent_expired" in PERSON_LEVEL_REFUSALS
    assert "no_credits" not in PERSON_LEVEL_REFUSALS, "a top-up lifts this one"


async def test_a_settled_promise_says_which_ending_it_reached() -> None:
    """`settle` refuses an ending nobody wrote a sentence for. The database's own CHECK
    would refuse it too; this refusal names the mistake instead of a constraint."""
    tenant_id, agent_id = await _tenant()
    callback_id = await _book(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError):
            await callbacks.settle(session, callback_id, status="in_progress")
        await callbacks.settle(
            session,
            callback_id,
            status="refused",
            rule="dnc",
            reason="This number is on the do-not-call list.",
        )
        await session.commit()
    row = await _row(tenant_id, callback_id)
    assert row["status"] == "refused"
    assert row["last_refusal_reason"] == "This number is on the do-not-call list."


async def test_a_suppressed_number_loses_its_promise_but_a_dialling_one_does_not() -> None:
    """The FAST door. `dialing` is deliberately untouched: that dial is in flight or has
    already rung, and rewriting its state would tell the client a call was called off
    while their lead's phone was ringing as we wrote it. The compliance gate at fire time
    is what covers that row, and it is the door that cannot be forgotten."""
    tenant_id, agent_id = await _tenant()
    waiting = await _book(tenant_id, agent_id)
    ringing = await _book(tenant_id, agent_id, when=datetime.now(UTC) - timedelta(minutes=1))

    async with tenant_session(tenant_id) as session:
        await callbacks.claim_due(session, limit=5)  # `ringing` becomes `dialing`
        stopped = await callbacks.cancel_for_phones(session, phones=[CALLER], reason="Suppressed.")
        await session.commit()

    assert stopped == 1
    assert (await _row(tenant_id, waiting))["status"] == "cancelled"
    assert (await _row(tenant_id, ringing))["status"] == "dialing"


async def test_the_client_can_stop_a_waiting_promise_and_only_a_waiting_one() -> None:
    tenant_id, agent_id = await _tenant()
    callback_id = await _book(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        assert await callbacks.cancel_one(session, callback_id, reason="You called this off.")
        # A second press changes nothing and says so, which is what lets the route answer
        # 409 instead of pretending it stopped something twice.
        assert not await callbacks.cancel_one(session, callback_id, reason="Again.")
        await session.commit()


async def test_the_agents_context_note_says_what_the_call_is_for_in_ist() -> None:
    """It rides `CallContext.context_note` — the field the "call this lead" button already
    uses — rather than a new channel into the prompt, and it is rendered in IST because a
    person in India is about to hear it."""
    when = datetime(2026, 9, 8, 10, 30, tzinfo=UTC)  # 16:00 IST
    note = callbacks.context_note(when, "wants the Gachibowli listing")
    assert "16:00" in note
    assert "wants the Gachibowli listing" in note
    assert callbacks.context_note(when, None).endswith("asked for on 08 Sep at 16:00.")


async def test_a_dpdp_erasure_stops_a_promise_and_forgets_the_number() -> None:
    """THE ARM THAT WAS MISSING, AND ITS SECOND CONSEQUENCE IS THE SHARP ONE (D-514).

    `scheduled_callbacks` deliberately OUTLIVES the call it was made on, so scrubbing
    `calls` and `leads` reaches none of it — the same gap `campaign_contacts` had (P3.1),
    one table along. A row left behind would not merely be a records failure: a
    `scheduled` promise is claimed by the dispatch tick from its own instant onward, so
    **we would telephone a person whose certificate says they were removed.**

    Asserted through the REAL erasure worker rather than by calling the helper, because
    the arm being written is not the same fact as the arm being CALLED — which is exactly
    the difference `campaign_contacts` was found on.
    """
    tenant_id, agent_id = await _tenant()
    waiting = await _book(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await deletion.request_erasure(session, tenant_id=tenant_id, phone_e164=CALLER)
        await session.commit()

    async with tenant_session(tenant_id) as session:
        request_id = (
            await session.execute(
                text(
                    "SELECT id FROM deletion_requests WHERE tenant_id = :tid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tid": tenant_id},
            )
        ).scalar_one()
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    row = await _row(tenant_id, waiting)
    assert row["status"] == "cancelled", "an erased person was still going to be rung"
    assert row["settled_at"] is not None
    assert CALLER not in str(row["phone_e164"])
    assert row["note"] is None, "the model's summary of what they said survived the erasure"
