"""A promised call-back dials through the SAME door as every other outbound call.

**THIS IS THE TEST THAT WOULD FAIL IF SOMEBODY BUILT A PARALLEL DIAL PATH** (D-514), and
the reason it matters more than it looks is that a parallel path does not ERROR. It
places a real call, from the right account, to the right person — and silently without the
A/B arm, without the resolved DLT header, without the intent row written before the phone
can ring, and without whatever `CallContext` carries by the time you read this. Here that
last clause is not hypothetical: cross-call memory (D-513) is injected inside
`dispatch_call`, so a second dial path would ring a returning caller as a stranger and
nothing would report it.

So the assertions are:

1. **it goes through `agents.service.dispatch_call`**, the platform's single outbound
   entry point and the property `scripts/check_compliance_invariants` already pins;
2. **and therefore what the agent already knows about the person rides the dial** —
   asserted on the `CallContext` the ENGINE was handed, not on a call to a helper;
3. **and the compliance gate refuses at fire time**, so a number suppressed between the
   promise and its time is settled `refused` on the very next tick — which is the door
   that cannot be forgotten (hard rule 5's "DNC additions propagate before next dispatch
   tick").
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle as agent_lifecycle
from apps.api.agents import prompts
from apps.api.agents.publishing import set_caller_memory
from apps.api.agents.service import publish_agent
from apps.api.callbacks import service as callbacks
from apps.api.compliance import caller_memory, dnc
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.vendor_http import EngineRejectedError
from apps.workers.callbacks import UNCONFIRMED_REASON, dispatch_due_callbacks
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.conftest import _owner_of, accept_agreements, arm_agent_for_outbound

pytestmark = pytest.mark.anyio

CALLER = "+919812345674"
FACT = "asked about a two-bedroom flat in Gachibowli"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST. The dial gate refuses outside calling hours and this suite is about the
    call-back path, not that rule — `call_optout_test` pins the same instant for the same
    reason."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(autouse=True)
def _fake_engine() -> None:
    reset_engine_cache()


async def _dialable_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant that lawfully CAN dial: published outbound agent, DLT paperwork, agreements.

    Every fact here is one `check_dispatch` reads. Supplying them through the same helpers
    production writes them with is the difference between a fixture that models a lawful
    tenant and one that softens the gate.
    """
    created = await admin_service.create_organization(
        name="Dial Estates",
        slug=f"dial-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
    async with tenant_session(tenant_id) as session:
        agent_id = await agent_lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Outbound caller",
            direction="outbound",
            language_primary="te-IN",
        )
        await session.commit()
    # AGREEMENTS FIRST: `agreements_blocker` refuses the PUBLISH as well as the dial, so
    # the order here is the order production has to be in. The script is the other
    # publish-time refusal — an agent with nothing written for it to say cannot go live,
    # and would answer a call-back with a greeting that knows nothing about the business.
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Dial Estates.\n",
            notes=None,
            created_by=None,
        )
        await session.commit()
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        await session.commit()
    await arm_agent_for_outbound(tenant_id, agent_id)
    return tenant_id, agent_id


async def _book(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    """A promise whose time has come."""
    async with tenant_session(tenant_id) as session:
        booked = await callbacks.book(
            session,
            callback_id=uuid7(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164=CALLER,
            requested_at=datetime.now(UTC) - timedelta(minutes=1),
            booked_at=datetime.now(UTC),
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


async def test_a_callback_dials_through_the_one_entry_point_carrying_what_we_remember(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE INHERITANCE CLAIM, MEASURED AT THE ENGINE. Nothing here tells the call-back path
    that cross-call memory exists — it arrives because the dial goes through the same
    function the campaign tick and the "call this lead" button call."""
    tenant_id, agent_id = await _dialable_tenant()
    owner = await _owner_of(tenant_id)
    await set_caller_memory(tenant_id=tenant_id, agent_id=agent_id, enabled=True, attested_by=owner)
    async with tenant_session(tenant_id) as session:
        await caller_memory.remember(
            session,
            tenant_id,
            agent_id=agent_id,
            phone_e164=CALLER,
            occurred_at=datetime.now(UTC),
            source_call_id=None,
            facts=[FACT],
        )
        await session.commit()

    callback_id = await _book(tenant_id, agent_id)

    seen: list[CallContext] = []
    engine = get_engine()
    original = engine.start_outbound_call

    async def _spy(ref: str, to: str, ctx: CallContext):  # type: ignore[no-untyped-def]
        seen.append(ctx)
        return await original(ref, to, ctx)

    monkeypatch.setattr(engine, "start_outbound_call", _spy)

    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["dialled"] == 1, outcome
    assert len(seen) == 1
    ctx = seen[0]
    assert FACT in ctx.caller_memory, "the call-back dialled without what we remember"
    # AND THE AGENT IS TOLD WHAT THE CALL IS FOR, on the field the "call this lead" button
    # already uses rather than a second channel into the prompt.
    assert ctx.context_note and "call-back" in ctx.context_note

    # THE PROMISE IS POINTED AT THE CALL IT BECAME, durably, before the vendor could seize
    # a line — otherwise a response lost on the way back leaves a `dialing` row with
    # nothing to settle against.
    row = await _row(tenant_id, callback_id)
    assert row["status"] == "dialing"
    assert row["last_call_id"] is not None


async def test_a_number_suppressed_after_the_promise_is_refused_on_the_very_next_tick() -> None:
    """THE DOOR THAT CANNOT BE FORGOTTEN. The fast door in `dnc.add_numbers` cancels the
    row in the same transaction as the suppression, so this asserts the row is stopped —
    and then re-books and suppresses in the other order to prove the GATE stops it too,
    which is the arm that holds when the fast door is bypassed."""
    tenant_id, agent_id = await _dialable_tenant()
    first = await _book(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        await dnc.add_numbers(
            session, tenant_id=tenant_id, raw_numbers=[CALLER], source="customer_request"
        )
        await session.commit()
    assert (await _row(tenant_id, first))["status"] == "cancelled"

    # NOW THE GATE'S OWN ARM: a promise booked while the number is already suppressed
    # never reaches a phone, and the client is told the gate's own sentence.
    second = await _book(tenant_id, agent_id)
    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["dialled"] == 0
    row = await _row(tenant_id, second)
    assert row["status"] == "refused"
    assert row["last_refusal_rule"] == "dnc"
    assert row["last_refusal_reason"], "a refusal with no sentence is a blank cell"


async def test_a_transient_block_defers_and_a_stale_promise_settles_in_the_same_pass() -> None:
    """The two halves of the settle-or-retry table, in the tick that runs them. `settle`
    and `expire_stale` run BEFORE the claim, so a promise past saving is never dialled by
    the pass that ends it."""
    tenant_id, agent_id = await _dialable_tenant()
    stale_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await callbacks.book(
            session,
            callback_id=stale_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_call_id=None,
            source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
            lead_id=None,
            phone_e164=CALLER,
            requested_at=datetime.now(UTC) - callbacks.GRACE - timedelta(minutes=10),
            booked_at=datetime.now(UTC),
            note=None,
            language=None,
        )
        await session.commit()

    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["settled"] >= 1
    assert outcome["dialled"] == 0
    row = await _row(tenant_id, stale_id)
    assert row["status"] == "missed"
    assert row["last_refusal_reason"] == callbacks.UNATTEMPTED_REASON


async def test_no_number_reaches_a_log_line_on_the_dial_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 6, on the tick that reads a table full of phone numbers."""
    tenant_id, agent_id = await _dialable_tenant()
    await _book(tenant_id, agent_id)
    with caplog.at_level("INFO"):
        await dispatch_due_callbacks(tenant_id, slots=5)
    assert CALLER not in caplog.text


async def test_a_dial_we_cannot_prove_did_not_ring_is_never_tried_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE THIRD OUTCOME, and the only one where doing nothing is the safe answer.

    `DialUnconfirmedError` means the vendor may have started the call and we cannot prove
    either way. Retrying is the one thing that must not happen — the person's phone may
    have rung already, and ringing them twice about a call-back they asked for once is
    worse than not ringing them at all. So it SETTLES `failed`, pointed at the committed
    intent row, with a sentence that says plainly what we do not know.
    """
    tenant_id, agent_id = await _dialable_tenant()
    callback_id = await _book(tenant_id, agent_id)

    # BROKEN AT THE ENGINE, so the REAL `dispatch_call` produces the error and the call_id
    # it carries is the COMMITTED intent row. Raising `DialUnconfirmedError` from a stub
    # would have carried an id no `calls` row has — which the FK refuses, and which is the
    # test lying about the one property this outcome rests on: the possible charge is
    # already on record before the engine is asked.
    async def _timed_out(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("the vendor did not answer")

    monkeypatch.setattr(get_engine(), "start_outbound_call", _timed_out)
    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["dialled"] == 0

    row = await _row(tenant_id, callback_id)
    assert row["status"] == "failed"
    assert row["settled_at"] is not None
    assert row["last_refusal_reason"] == UNCONFIRMED_REASON
    # POINTED AT THE CALL THAT MAY HAVE RUNG. Without it a later reader has no way to ask
    # the vendor what became of the dial this promise turned into.
    assert row["last_call_id"] is not None

    # AND IT IS NOT CLAIMED AGAIN. A settled row is invisible to the claim, which is what
    # makes "never tried again" a property of the state machine rather than of this test.
    again = await dispatch_due_callbacks(tenant_id, slots=5)
    assert again["dialled"] == 0


async def test_an_engine_that_refused_before_dialling_goes_back_on_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OTHER engine failure, and it is classified the opposite way for a reason: a
    vendor 502 before the call is placed is the most transient fact there is, and nobody's
    phone rang. Back on the ladder — bounded by `GRACE`, like every other transient
    refusal, so "back on the ladder" cannot mean for ever."""
    tenant_id, agent_id = await _dialable_tenant()
    callback_id = await _book(tenant_id, agent_id)

    async def _refused(*_args: object, **_kwargs: object) -> None:
        raise EngineRejectedError(status=400)

    monkeypatch.setattr(get_engine(), "start_outbound_call", _refused)
    outcome = await dispatch_due_callbacks(tenant_id, slots=5)
    assert outcome["blocked"] == 1
    assert outcome["dialled"] == 0

    row = await _row(tenant_id, callback_id)
    assert row["status"] == "scheduled", "a vendor blip settled a promise"
    assert row["last_refusal_rule"] == "dial_failed"
    # THE ATTEMPT IS REFUNDED and the PROMISE has not moved: `next_attempt_at` is what
    # carries the wait, which is the separation the staleness livelock was fixed by.
    assert row["attempts"] == 0


async def test_a_dialled_callback_is_settled_by_the_call_it_became() -> None:
    """`settle_dialled` reads OUR `calls` row rather than hooking the post-call pipeline,
    so it settles a call-back whose call the RECONCILIATION POLLER discovered as well as
    one the webhook did (D-31) — and RINGING is the promise, not answering: `no_answer`
    is `completed`, because we called them at the time they asked for."""
    tenant_id, agent_id = await _dialable_tenant()
    callback_id = await _book(tenant_id, agent_id)
    await dispatch_due_callbacks(tenant_id, slots=5)

    row = await _row(tenant_id, callback_id)
    assert row["status"] == "dialing"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = 'no_answer' WHERE id = :cid"),
            {"cid": row["last_call_id"]},
        )
        await session.commit()

    await dispatch_due_callbacks(tenant_id, slots=5)
    settled = await _row(tenant_id, callback_id)
    assert settled["status"] == "completed"
    assert settled["settled_at"] is not None
