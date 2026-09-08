"""Answering stops at a zero balance, and starts again the moment a top-up lands.

THE DEFECT (8 Sep 2026). `compliance.check_dispatch` refuses an outbound dial at a balance
of zero or below; an inbound call passes through NONE of it, and `workers/pipeline.py` said
so in its own words — "the gate is outbound-only, so inbound still meters". So a clinic
answering at Rs.0 went on being debited every answered minute against a wallet that could
only get more negative, with nothing anywhere bounding it. The two halves of the fix are
tested here together because they are one decision:

* **the phone** — at zero or below, the client's answering agents say one short neutral
  line instead of doing business, and go back to their own words the moment credit lands;
* **the money** — an inbound call on an exhausted wallet is METERED (we paid the vendor and
  hard rule 7 says so) and NOT DEBITED (the founder's rule: inbound accrues no further
  debt).

**THE RECOVERY TESTS ARE THE POINT OF THIS FILE.** Silencing a phone that fails to come
back is the failure nobody notices: every screen reports the top-up, the balance is
restored, and the client's callers go on being turned away all night. Three separate
mechanisms have to bring it back and each has its own test below — the upward crossing that
queues the job, the job itself, and the re-decision at the end of every publish.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.billing.service import (
    INBOUND_CUTOVER_JOB,
    crossed_zero,
    record_entry,
)
from apps.api.crm import attention
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import DEFAULT_FAKE_CAPABILITIES, FakeEngine
from apps.workers import pipeline
from apps.workers.inbound_cutover import apply_inbound_credit_state
from calevate_shared.engine import TRUTHFUL_ANSWER_DIRECTIVE
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.spend_caps_test import _snapshot

#: What the engine charges us for the minute the pipeline meters below. Nothing like the
#: client's own rate, so an assertion about the wallet cannot pass by coincidence.
_SUPPLIER_COST = "1.9000"


async def _tenant(*, tier: str = "prepaid") -> tuple[UUID, UUID]:
    """A prepaid tenant with a scripted agent and a zero wallet."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Cutover Clinic",
        slug=f"cut-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": tier, "i": tenant_id},
        )
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Cutover Clinic.\n",
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


async def _publish(tenant_id: UUID, agent_id: UUID, *, direction: str = "inbound") -> str:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = :d WHERE id = :a"),
            {"d": direction, "a": agent_id},
        )
        return await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def _topup(tenant_id: UUID, amount: str) -> None:
    async with tenant_session(tenant_id) as session:
        await record_entry(session, tenant_id=tenant_id, delta=Decimal(amount), reason="topup")


async def _spend(tenant_id: UUID, amount: str) -> None:
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal(amount),
            reason="usage",
            allow_negative=True,
        )


async def _reconcile(tenant_id: UUID) -> str:
    """The registered job, driven exactly as the outbox drives it."""
    return await apply_inbound_credit_state({"job_try": 1}, {"tenant_id": str(tenant_id)})


async def _silenced_at(tenant_id: UUID, agent_id: UUID) -> datetime | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT inbound_silenced_at FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()


async def _outbox_jobs(tenant_id: UUID) -> list[str]:
    """Every job this tenant's ledger has promised. Read from `outbox_messages` rather
    than from a spy: the whole reliability claim is that the promise shares a transaction
    with the ledger row, and only the row proves it."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT job FROM outbox_messages "
                    "WHERE payload->>'tenant_id' = :t ORDER BY created_at, id"
                ),
                {"t": str(tenant_id)},
            )
        ).all()
    return [str(row[0]) for row in rows]


async def _live_script(ref: str) -> tuple[str, str]:
    """What the ENGINE is holding, read back through the Protocol rather than off a
    private attribute of the fake — the same read `publish_agent` verifies with."""
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    snapshot = await engine.get_agent(ref)
    return str(snapshot.greeting), str(snapshot.system_prompt)


# ============================================================================
# 1. What the caller hears
# ============================================================================


def test_the_message_gives_no_reason_and_says_nothing_about_the_account() -> None:
    """The reputational half of the decision, asserted as a property of the words.

    A caller who works out that the business has not paid its bill is a harm WE inflicted
    on our client, in their own voice, on their own customer. So the sentence may not name
    a reason at all — and the two reasons a language model would otherwise reach for are
    both forbidden by name in the prompt, because "closed" is a false statement about a
    clinic that may be full of people and "technical problem" is simply untrue.
    """
    message = agents_service.CREDIT_STOP_MESSAGE
    prompt = agents_service.credit_stop_prompt()
    for forbidden in ("credit", "balance", "bill", "pay", "account", "subscription"):
        assert forbidden not in message.lower(), (
            f"the caller is told about the client's finances: {message!r}"
        )
    for forbidden in ("closed", "closing", "holiday"):
        assert forbidden not in message.lower(), (
            "the message states the business is closed, which may be false and is a claim "
            "about our client made to their own customer"
        )
    assert "Give NO reason" in prompt
    assert "closed" in prompt and "billing" in prompt, (
        "the prompt does not forbid by name the two reasons a model would invent"
    )


def test_the_silenced_agent_still_carries_the_hard_rule_5_floor() -> None:
    """The call is ANSWERED and it is RECORDED — `override_call_script` writes two
    attributes and recording is neither — so both obligations have a real event to attach
    to and neither may be reasoned away.

    The composed opening line (the AI disclosure and the recording notice, each on its own
    client-set toggle) is PREPENDED rather than replaced, and the truthful-answer directive
    is in the prompt verbatim.
    """
    posture = agents_service.DisclosurePosture(
        ai_disclosure_line="Idi AI assistant.",
        ai_disclosure_enabled=True,
        recording_notice_line="This call is being recorded.",
        recording_notice_enabled=True,
        caller_memory_notice_line="I keep a short note.",
        caller_memory_enabled=False,
    )
    greeting = agents_service.credit_stop_greeting(posture)
    assert greeting.startswith("Idi AI assistant."), "the AI disclosure was dropped"
    assert "This call is being recorded." in greeting, "the recording notice was dropped"
    assert greeting.endswith(agents_service.CREDIT_STOP_MESSAGE)
    assert TRUTHFUL_ANSWER_DIRECTIVE in agents_service.credit_stop_prompt()


# ============================================================================
# 2. The cutover
# ============================================================================


async def test_an_exhausted_wallet_takes_the_agent_off_business() -> None:
    tenant_id, agent_id = await _tenant()
    await _topup(tenant_id, "500")
    ref = await _publish(tenant_id, agent_id)
    opening_before, prompt_before = await _live_script(ref)
    await _spend(tenant_id, "-500")

    assert await _reconcile(tenant_id) == "silenced=1 restored=0 unchanged=0"

    opening, prompt = await _live_script(ref)
    assert opening != opening_before and prompt != prompt_before
    assert agents_service.CREDIT_STOP_MESSAGE in opening
    assert "You are the receptionist" not in prompt, (
        "the agent is still running its own script, so it is still taking bookings"
    )
    assert await _silenced_at(tenant_id, agent_id) is not None


async def test_a_second_pass_makes_no_vendor_call_at_all() -> None:
    """Idempotence is what lets this run on every edge and every publish. The column
    records what the ENGINE was observed to hold, so an agent already in the right state
    costs nothing."""
    tenant_id, agent_id = await _tenant()
    await _topup(tenant_id, "500")
    await _publish(tenant_id, agent_id)
    await _spend(tenant_id, "-500")
    assert await _reconcile(tenant_id) == "silenced=1 restored=0 unchanged=0"
    assert await _reconcile(tenant_id) == "silenced=0 restored=0 unchanged=1"


async def test_a_funded_wallet_leaves_the_agent_alone() -> None:
    tenant_id, agent_id = await _tenant()
    await _topup(tenant_id, "500")
    ref = await _publish(tenant_id, agent_id)
    assert await _reconcile(tenant_id) == "silenced=0 restored=0 unchanged=1"
    opening, _ = await _live_script(ref)
    assert agents_service.CREDIT_STOP_MESSAGE not in opening


async def test_an_outbound_only_agent_is_never_silenced() -> None:
    """Nobody rings it, so overriding its script would change nothing a caller can hear
    and would spend a vendor round trip saying so."""
    tenant_id, agent_id = await _tenant()
    ref = await _publish(tenant_id, agent_id, direction="outbound")
    assert await _reconcile(tenant_id) == "silenced=0 restored=0 unchanged=0"
    opening, _ = await _live_script(ref)
    assert agents_service.CREDIT_STOP_MESSAGE not in opening
    assert await _silenced_at(tenant_id, agent_id) is None


async def test_a_managed_tenant_is_never_silenced() -> None:
    """A managed client is invoiced against a retainer, so a wallet they never bought
    must not take their phone away — `credits_exhausted` is the one predicate and it says
    so already."""
    tenant_id, agent_id = await _tenant(tier="managed")
    ref = await _publish(tenant_id, agent_id)
    assert await _reconcile(tenant_id) == "silenced=0 restored=0 unchanged=1"
    opening, _ = await _live_script(ref)
    assert agents_service.CREDIT_STOP_MESSAGE not in opening


# ============================================================================
# 3. The recovery — the half whose failure is silent
# ============================================================================


async def test_a_topup_brings_the_phone_back() -> None:
    """The whole product risk in one test: a client who tops up at 9pm must not find
    their phone still dead in the morning, with every screen reporting them in credit."""
    tenant_id, agent_id = await _tenant()
    await _topup(tenant_id, "500")
    ref = await _publish(tenant_id, agent_id)
    opening_before, prompt_before = await _live_script(ref)
    await _spend(tenant_id, "-500")
    await _reconcile(tenant_id)
    assert agents_service.CREDIT_STOP_MESSAGE in (await _live_script(ref))[0]

    await _topup(tenant_id, "500")
    assert await _reconcile(tenant_id) == "silenced=0 restored=1 unchanged=0"

    assert await _live_script(ref) == (opening_before, prompt_before), (
        "the agent came back saying something other than its own words"
    )
    assert await _silenced_at(tenant_id, agent_id) is None


async def test_the_ledger_queues_the_job_on_both_crossings_of_zero() -> None:
    """The trigger, and it is the LEDGER rather than a sweep: `record_entry` is the single
    writer of every credit movement, so the promise shares a transaction with the row that
    earned it and no cron has to notice."""
    tenant_id, _agent_id = await _tenant()
    await _topup(tenant_id, "300")
    assert await _outbox_jobs(tenant_id) == [INBOUND_CUTOVER_JOB], (
        "crossing zero UPWARDS queued nothing, so a top-up would never bring a phone back"
    )
    await _spend(tenant_id, "-300")
    assert (await _outbox_jobs(tenant_id)).count(INBOUND_CUTOVER_JOB) == 2, (
        "crossing zero DOWNWARDS queued nothing, so the phone would never go quiet"
    )


def test_the_crossing_is_a_movement_and_not_a_state() -> None:
    """`crossed_zero` reports each direction ONCE per episode, which is what makes the
    whole design need no stored flag and no clock. A wallet sitting AT zero is exhausted,
    so a movement that leaves it there is not a recovery."""
    assert crossed_zero(Decimal("10"), Decimal("-2")) == "empty"
    assert crossed_zero(Decimal("10"), Decimal("0")) == "empty"
    assert crossed_zero(Decimal("-2"), Decimal("50")) == "funded"
    assert crossed_zero(Decimal("0"), Decimal("50")) == "funded"
    assert crossed_zero(Decimal("-2"), Decimal("-9")) is None
    assert crossed_zero(Decimal("-2"), Decimal("0")) is None
    assert crossed_zero(Decimal("50"), Decimal("10")) is None


async def test_a_republish_does_not_put_a_silenced_agent_back_to_work() -> None:
    """Eleven paths republish an agent — a voice change, a cap change, a prompt rollback,
    the maintenance window's own restore — and every one of them writes the agent's REAL
    script. Without the re-decision at the end of `publish_agent` each is a silent undo of
    the cutover performed by an author who could not see it."""
    tenant_id, agent_id = await _tenant()
    await _topup(tenant_id, "500")
    ref = await _publish(tenant_id, agent_id)
    await _spend(tenant_id, "-500")
    await _reconcile(tenant_id)

    await _publish(tenant_id, agent_id)

    opening, prompt = await _live_script(ref)
    assert agents_service.CREDIT_STOP_MESSAGE in opening, (
        "a republish put a client with no credit back to taking bookings nobody pays for"
    )
    assert "Give NO reason" in prompt
    assert await _silenced_at(tenant_id, agent_id) is not None


async def test_the_pipeline_and_the_ledger_name_the_same_job() -> None:
    """`workers/pipeline.py` restates the job name as a literal because
    `check_job_wiring` resolves it only in the file that enqueues it. This is the test
    that holds the two spellings in step — without it the backstop enqueue would publish
    a name no worker answers to, and arq would drop it with a warning nothing reads."""
    assert pipeline.INBOUND_CUTOVER_JOB == INBOUND_CUTOVER_JOB


# ============================================================================
# 4. The money: metered, not debited
# ============================================================================


async def _call_row(tenant_id: UUID, agent_id: UUID, *, direction: str) -> UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, from_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                ":d, '+919876500001', '+919876500002', 'completed', now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "d": direction,
            },
        )
    return call_id


async def _meter_one_minute(tenant_id: UUID, agent_id: UUID, *, direction: str) -> int:
    call_id = await _call_row(tenant_id, agent_id, direction=direction)
    return await pipeline._meter(
        tenant_id,
        call_id,
        _snapshot(seconds=60, spend=_SUPPLIER_COST, ended=datetime.now(UTC)),
    )


async def _balance(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return Decimal(
            str(
                (
                    await session.execute(
                        text(
                            "SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE tenant_id = :t"
                        ),
                        {"t": tenant_id},
                    )
                ).scalar()
            )
        )


async def test_an_inbound_call_on_an_empty_wallet_is_metered_and_not_debited() -> None:
    """Both halves, and they are not the same claim.

    METERED: we paid the vendor for the call, so `usage_events` carries it with its real
    `unit_cost_paid` (hard rule 7) — a cost nobody records is a cost nobody can see.
    NOT DEBITED: the founder's rule is that inbound accrues no further debt, and this is
    the only place that can hold it, because `record_entry` is called with
    `allow_negative=True` here and correctly so.
    """
    tenant_id, agent_id = await _tenant()
    rows = await _meter_one_minute(tenant_id, agent_id, direction="inbound")
    assert rows > 0, "the call was not metered at all, so its supplier cost is invisible"
    assert await _balance(tenant_id) == Decimal("0"), (
        "an inbound call deepened an already-negative wallet — the unbounded overdraft"
    )


async def test_an_inbound_call_on_a_funded_wallet_is_charged_normally() -> None:
    """The bound is on FURTHER debt, not on inbound billing. A client with credit pays
    for the calls they answer exactly as before."""
    tenant_id, agent_id = await _tenant()
    await _topup(tenant_id, "500")
    await _meter_one_minute(tenant_id, agent_id, direction="inbound")
    assert await _balance(tenant_id) < Decimal("500"), (
        "an answered inbound minute stopped being billed to a client who has credit"
    )


async def test_an_outbound_call_on_an_empty_wallet_is_still_charged() -> None:
    """One call's worth of overdraft is unavoidable in either direction — the call already
    happened — and the arm added here must not have widened into "prepaid calls are free
    once the wallet is empty"."""
    tenant_id, agent_id = await _tenant()
    await _meter_one_minute(tenant_id, agent_id, direction="outbound")
    assert await _balance(tenant_id) < Decimal("0")


async def test_a_metered_call_on_an_empty_wallet_asks_for_a_reconciliation() -> None:
    """The backstop for the one edge the ledger cannot see: an account that becomes
    exhausted with no movement of money at all (a trial ending, a tier changing). At most
    one enqueue per call."""
    tenant_id, agent_id = await _tenant()
    await _meter_one_minute(tenant_id, agent_id, direction="inbound")
    assert await _outbox_jobs(tenant_id) == [INBOUND_CUTOVER_JOB]


# ============================================================================
# 5. What the client sees
# ============================================================================


async def test_the_console_says_the_phone_is_not_being_answered_and_what_fixes_it() -> None:
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id)
    await _reconcile(tenant_id)

    async with tenant_session(tenant_id) as session:
        queue = await attention.attention_queue(session)
    kinds = [item["kind"] for item in queue["items"]]
    assert "inbound_stopped" in kinds, (
        "a client whose phone has stopped being answered is told nothing at all"
    )
    row = next(item for item in queue["items"] if item["kind"] == "inbound_stopped")
    assert "not answering incoming calls" in row["detail"]
    assert "gives no reason" in row["detail"], (
        "the client is not told what their own customers hear, which is the first thing "
        "they will be asked"
    )
    assert "Top up" in row["detail"] and row["href"] == "/credits"
    assert queue["counts"]["inbound_stopped"] == 1

    await _topup(tenant_id, "500")
    await _reconcile(tenant_id)
    async with tenant_session(tenant_id) as session:
        after = await attention.attention_queue(session)
    assert "inbound_stopped" not in after["counts"], "the row outlived the state it describes"


def test_the_block_remedy_no_longer_promises_that_callers_get_through() -> None:
    """It said "People calling you still get through" until 8 Sep 2026. It is now false in
    the direction that matters most: a client would read it, do nothing, and their phone
    would go on turning callers away."""
    remedy = attention.BLOCK_REMEDIES["no_credits"]
    assert "still get through" not in remedy
    assert "no longer answering incoming ones" in remedy


@pytest.mark.parametrize("rule", ["no_credits"])
def test_the_two_client_surfaces_agree(rule: str) -> None:
    """A client must not get two accounts of one event on two screens."""
    assert "Top up" in attention.BLOCK_REMEDIES[rule]
    assert "Top up" in attention.INBOUND_STOPPED_DETAIL


# ============================================================================
# 6. The arms nobody reaches on a good day
# ============================================================================
#
# An engine that CANNOT swap a script, and a vendor that WILL NOT. Both are tested
# because the failure is the silent kind — a phone that goes on taking bookings for
# an account with no credit looks exactly like a phone that is working, and no screen
# in the product would say otherwise. `dial-path` is a zero-tolerance ratchet surface
# for this reason: an untested arm here is an arm nobody finds out is broken.


def _cutover_alerts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The alert CODES this surface raised. Codes, not messages: the message is prose
    an operator edits and the code is the contract (`ai_quota_test._alerts`' reason)."""
    return [
        str(record.__dict__.get("code"))
        for record in caplog.records
        if record.message == "alert" and record.__dict__.get("failure_stage") == "CORE_LOGIC"
    ]


#: The default fake with ONE capability taken away. Built by copy rather than by reaching
#: for `EXTERNAL_DEPLOYMENT_CAPABILITIES`, which also lacks `agent_hosting` — an engine that
#: cannot host our agent refuses at `create_agent` one step earlier, so a test using it
#: would never reach the arm it claims to cover and would pass for the wrong reason. This
#: isolates exactly the property under test.
_NO_SCRIPT_OVERRIDE = DEFAULT_FAKE_CAPABILITIES.model_copy(update={"script_override": False})


class _RefusingEngine(FakeEngine):
    """A fake whose script override always raises.

    A SUBCLASS rather than a monkeypatch of one bound method: the override is reached
    from two different call sites through the Protocol, and patching an instance would
    leave the other site running the real one — which is how a test proves an arm it
    never entered.
    """

    async def override_call_script(self, ref: str, **kwargs: object) -> None:
        raise RuntimeError("the vendor refused this write")


async def test_an_engine_that_cannot_swap_a_script_says_so_instead_of_reporting_success() -> None:
    """`unsupported=True`, not a quiet zero — and NOT a fallback to unbinding the number.

    Unbinding would take the number off the agent, and a caller would then hear whatever
    the carrier does for an unrouted number: no message at all. That is the exact shape
    D-544's own correction refused, so an engine that cannot deliver the founder's
    decision reports that it cannot, and the caller alerts on the count.
    """
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id)
    await _spend(tenant_id, "-50.00")

    async with tenant_session(tenant_id) as session:
        verdict = await agents_service.reconcile_inbound_answering(
            session,
            FakeEngine(capabilities=_NO_SCRIPT_OVERRIDE),
            tenant_id=tenant_id,
            exhausted=True,
        )

    assert verdict.unsupported is True
    assert (verdict.silenced, verdict.restored, verdict.failed) == (0, 0, 0)
    assert await _silenced_at(tenant_id, agent_id) is None, (
        "the column claims the engine is holding a message it was never asked to hold, so "
        "the next pass would count this agent as already silenced and never retry it"
    )


async def test_a_vendor_refusal_is_counted_alarmed_and_left_for_the_next_pass(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The stamp is what makes the retry possible, so it must NOT be written on failure.

    `inbound_silenced_at` records what the engine was last observed to hold. Writing it
    after a refused write would make every later pass read "already silenced" and skip the
    agent — the phone stays open for ever, on a client with no credit, with the platform
    believing it closed it.
    """
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id)
    await _spend(tenant_id, "-50.00")

    with caplog.at_level("ERROR"):
        async with tenant_session(tenant_id) as session:
            verdict = await agents_service.reconcile_inbound_answering(
                session, _RefusingEngine(), tenant_id=tenant_id, exhausted=True
            )

    assert (verdict.failed, verdict.silenced) == (1, 0)
    assert verdict.unsupported is False
    assert "inbound_credit_cutover_failed" in _cutover_alerts(caplog)
    assert await _silenced_at(tenant_id, agent_id) is None


class _UnpublishableEngine(FakeEngine):
    """A fake that cannot be published to.

    The RESTORE deliberately does not use `override_call_script` — it goes back through
    `publish_agent`, so the agent's own words come from our row through the one path that
    reads them back and verifies (D-64). So the engine that breaks a restore is one whose
    UPDATE fails, and a fake refusing only the override would have left this test green
    having exercised nothing. That mistake is why this class exists rather than a second
    use of `_RefusingEngine`.
    """

    async def update_agent(self, ref: object, cfg: object) -> None:
        raise RuntimeError("the vendor refused this publish")


async def test_a_refused_restore_alerts_in_the_other_direction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The worse half of the pair, and the one with a paying client behind it.

    A refused SILENCE leaves a phone answering that should not. A refused RESTORE leaves a
    client who has PAID with their callers still being turned away, and every screen
    reporting the top-up as landed. The detail says which of the two happened, because the
    operator's next action differs.
    """
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id)
    await _spend(tenant_id, "-50.00")
    async with tenant_session(tenant_id) as session:
        await agents_service.reconcile_inbound_answering(
            session, get_engine(), tenant_id=tenant_id, exhausted=True
        )
    assert await _silenced_at(tenant_id, agent_id) is not None

    await _topup(tenant_id, "500.00")

    # THE ENGINE HAS TO GO IN THE CACHE, not merely into the argument, and finding that out
    # is why this test earned its keep: `reconcile_inbound_answering` takes an `engine` and
    # uses it for the OVERRIDE, but the restore goes through `publish_agent`, which resolves
    # its own engine with `get_engine()`. A refusing engine handed only to the reconciler is
    # therefore never asked to do the thing the test is about, and the assertion below
    # passed for the wrong reason until this was fixed.
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = _UnpublishableEngine()
    try:
        with caplog.at_level("ERROR"):
            async with tenant_session(tenant_id) as session:
                verdict = await agents_service.reconcile_inbound_answering(
                    session, get_engine(), tenant_id=tenant_id, exhausted=False
                )
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)

    assert (verdict.failed, verdict.restored) == (1, 0)
    assert "inbound_credit_cutover_failed" in _cutover_alerts(caplog)
    assert await _silenced_at(tenant_id, agent_id) is not None, (
        "the stamp was cleared on a restore that did not happen, so the platform now "
        "believes this paid-up client's phone is answering while its callers are still "
        "hearing the apology"
    )


async def test_a_publish_on_an_engine_that_cannot_swap_a_script_does_not_pretend() -> None:
    """`_settle_inbound_credit_state`'s own capability arm.

    It returns without alerting, unlike the vendor-refusal arm below it: an engine that
    never had the capability is a deployment fact an operator already knows from the
    reconciler's `unsupported` count, and alarming on every publish would page them for it
    once per console action.
    """
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id)
    await _spend(tenant_id, "-50.00")
    async with tenant_session(tenant_id) as session:
        await agents_service.reconcile_inbound_answering(
            session, get_engine(), tenant_id=tenant_id, exhausted=True
        )
    assert await _silenced_at(tenant_id, agent_id) is not None

    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = FakeEngine(capabilities=_NO_SCRIPT_OVERRIDE)
    try:
        await _publish(tenant_id, agent_id)
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)

    assert await _silenced_at(tenant_id, agent_id) is not None, (
        "the stamp was cleared by a publish that could not put the message back, so the "
        "agent is recorded as answering normally on an account with no credit"
    )


async def test_a_publish_whose_override_the_vendor_refuses_alerts_and_leaves_the_stamp(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The publish path's re-application failing is the one that undoes a cutover silently.

    Eleven call sites republish an agent, and each writes its REAL script to the engine.
    If the re-application then fails, the agent is back to doing business for a client with
    no credit — so the stamp stays, the alert fires, and the next reconciliation retries.
    """
    tenant_id, agent_id = await _tenant()
    await _publish(tenant_id, agent_id)
    await _spend(tenant_id, "-50.00")
    async with tenant_session(tenant_id) as session:
        await agents_service.reconcile_inbound_answering(
            session, get_engine(), tenant_id=tenant_id, exhausted=True
        )

    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = _RefusingEngine()
    try:
        with caplog.at_level("ERROR"):
            await _publish(tenant_id, agent_id)
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)

    assert "inbound_credit_cutover_failed" in _cutover_alerts(caplog)
    assert await _silenced_at(tenant_id, agent_id) is not None
