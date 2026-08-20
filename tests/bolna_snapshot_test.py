"""What the Bolna adapter can and cannot HONESTLY claim about an execution.

Three things this adapter used to state as fact and could not know, each of which made
a pilot gate unable to do its job (OPERATIONS §2, gate 7):

1. **The currency.** `source_currency="USD"` was a literal, so reading it back was the
   harness agreeing with itself. The vendor's own OAS says the numbers are "in cents" and
   names no currency (D-350), so the UNIT is settled and the currency is worth the
   exchange rate. Every INR row in `usage_events` inherits it (hard rule 7).
2. **The transcript.** `parse_transcript` returned a bare list, so a shape it did not
   recognise came back as `[]` — indistinguishable from a call where nobody spoke.
3. **When the execution became billable.** Nothing recorded the instant cost, recording
   and transcript landed, so time-to-`completed` could only be measured live.

These are unit tests on `_snapshot`, not conformance tests: the conformance suite asks
what BOTH adapters must do, and these are questions only a vendor with a hand-maintained
payload shape raises.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.core import alerting
from apps.api.engine import bolna
from apps.api.engine.bolna import (
    _STATUS_MAP,
    _VENDOR_STATUSES,
    BolnaEngine,
    parse_transcript,
)

FX = Decimal("83.50")


def _engine() -> BolnaEngine:
    return BolnaEngine(api_key="k", fx_rate=FX)


def _payload(**over: object) -> dict[str, object]:
    """A `completed` execution, the only state that carries cost."""
    return {
        "id": "exec-abc123",
        "status": "completed",
        "agent_id": "agent-1",
        "conversation_duration": 42,
        # 6 of SOMETHING; what, is the question below. The MAGNITUDE is chosen to be a
        # plausible 42-second call under the house assumption (6 US cents = ₹5.01, i.e.
        # ₹7.16/min against the ₹0.5-6/min the adapter expects) — this used to be 600,
        # which is ₹715/min and trips `engine_cost_implausible` on every use of the
        # fixture. A fixture that fires the platform's own alarm teaches the next reader
        # that the alarm is noise.
        "total_cost": 6,
        "cost_breakdown": {"platform": 4, "network": 2},
        **over,
    }


# --- 1. the currency ----------------------------------------------------------


def test_an_unstated_currency_converts_on_the_house_assumption_and_says_so() -> None:
    """Today's behaviour, preserved — but no longer indistinguishable from a fact."""
    snapshot = _engine()._snapshot(_payload())

    assert snapshot.cost is not None
    assert snapshot.cost.source_currency == "USD"
    assert snapshot.cost.currency_stated is False, (
        "nothing in the payload named a currency, so this is our guess and must say so"
    )
    # 6 cents = $0.06, at 83.50 = ₹5.01.
    assert snapshot.cost.total_inr == Decimal("5.0100")
    assert snapshot.cost.fx_rate == FX


def test_a_stated_usd_is_recorded_as_a_reading_not_a_guess() -> None:
    """Same number, different epistemic status — which is the entire point of the flag."""
    snapshot = _engine()._snapshot(_payload(currency="usd"))

    assert snapshot.cost is not None
    assert snapshot.cost.total_inr == Decimal("5.0100")
    assert snapshot.cost.currency_stated is True


def test_a_stated_inr_is_refused_because_nothing_says_what_unit_it_is_in() -> None:
    """THE 100x BUG (D-411), and the reason it hid behind a fix.

    The `rate = 1` branch is right and was added deliberately: a figure already in rupees
    must not be multiplied by the dollar rate (the 83x error). But the DIVISOR is a
    separate assumption argued end to end in USD — the OAS sentence carrying it says "in
    cents" — and it kept applying, so a stated-INR payload was divided by 100 after being
    correctly left unconverted. An account Bolna bills in RUPEES metered every call at one
    hundredth of cost, on a row stamped `currency_stated=True`.

    The fix is not a second guess in the other direction: nothing first-party says which
    unit an INR figure is in, so the adapter refuses, exactly as it does for a currency it
    has no RATE for. The gap is loud (`call_billable_without_cost` from `pipeline._meter`)
    where a wrong number is silent.
    """
    snapshot = _engine()._snapshot(_payload(currency="INR"))

    assert snapshot.cost is None, "1/100th of a rupee figure is not a cost basis"
    # The rest of the snapshot still lands: an unpriceable cost is not a broken call.
    assert snapshot.status == "completed"
    assert snapshot.duration_s == 42


# --- 1b. the UNIT, settled by the vendor's own worked example (D-412) ---------
#
# The vendor's hosted API reference prints a real completed execution. It is the only
# first-party artefact that lets the minor-unit question be decided by ARITHMETIC instead
# of by adjudicating two prose sentences against each other, and the two tests below are
# what stop that evidence from decaying back into a comment nobody re-derives.

#: Verbatim from the "Completed execution example" block of
#: `bolna-findings/mirror/pages/api-reference/executions/get_execution.md`. Copied rather
#: than adapted: the point of the fixture is that it is THEIRS, so trimming it to what our
#: assertions touch would quietly turn their evidence back into ours.
VENDOR_WORKED_EXAMPLE: dict[str, object] = {
    "id": "b7140255-af33-4608-8e97-04dd944b8e48",
    "agent_id": "5bc97541-e320-4d95-a3a5-242cfe45621d",
    "status": "completed",
    "conversation_duration": 16,
    "total_cost": 3.23,
    "cost_breakdown": {
        "platform": 2,
        "network": 1,
        "transcriber": 0.23,
        "llm": 0,
        "synthesizer": 0,
    },
}


def test_the_vendors_worked_example_totals_exactly_what_its_legs_sum_to() -> None:
    """`total_cost` IS the sum of the five legs, and this is the first evidence of it.

    `_cost` converts the total and every leg on ONE divisor and ONE rate so that a row's
    parts reproduce its whole — a property `usage_events.meta` re-derivation depends on,
    and one this repository chose on first principles before it had any vendor arithmetic
    to check it against. The vendor's example now checks it: 2 + 1 + 0.23 + 0 + 0 = 3.23.

    Asserted on the CONVERTED rupee figures rather than on the raw ones, because that is
    the property that matters downstream: a divisor or a rate applied to the total but not
    to a leg would satisfy the raw sum and still ship a row whose parts do not add up.
    """
    snapshot = _engine()._snapshot(_payload(**VENDOR_WORKED_EXAMPLE))

    cost = snapshot.cost
    assert cost is not None
    legs = [cost.platform_inr, cost.network_inr, cost.stt_inr, cost.llm_inr, cost.tts_inr]
    assert all(leg is not None for leg in legs)
    assert sum(leg for leg in legs if leg is not None) == cost.total_inr


def test_only_the_minor_unit_reading_of_the_worked_example_is_a_possible_phone_bill() -> None:
    """WHY THE DIVISOR IS 100, argued from the vendor's numbers rather than from its prose.

    Both readings of `total_cost` were first-party: the OAS says "in cents", and
    `references/execution-payload.md` says "account currency" (major units). Until this
    example there was no way to choose between them except the vendor's own precedence
    rule — which settles which DOCUMENT wins, not which reading is true.

    16 seconds for 3.23 is 12.11 units per minute. As minor units that is ~12 US cents/min,
    which lands beside the rate Bolna publishes for the Voice AI leg — "$0.06/min
    (₹5.52/min)" plus telephony and platform fee
    (`bolna-findings/mirror/pages/pricing/preferred-models.md`). As MAJOR units it is
    $12.11/min: about ₹1,060 for one minute of an Indian phone call.

    This test asserts BOTH arms on purpose. Checking only that the minor-unit reading is
    plausible would pass just as happily if the band were wide enough to admit both, and
    then it would be testing nothing — the discriminating fact is that the major-unit
    reading is excluded by the same band.
    """
    snapshot = _engine()._snapshot(_payload(**VENDOR_WORKED_EXAMPLE))

    cost = snapshot.cost
    assert cost is not None
    assert snapshot.duration_s == 16
    as_minor = bolna._implied_inr_per_minute(cost.total_inr, snapshot.duration_s)
    assert bolna._PLAUSIBLE_INR_PER_MIN_FLOOR <= as_minor <= bolna._PLAUSIBLE_INR_PER_MIN_CEILING, (
        f"the minor-unit reading prices the vendor's own example at INR {as_minor}/min"
    )

    # The rejected reading, priced the same way. `_to_inr` with a divisor of 1 IS the
    # major-unit story, so this is not a hand-computed number we could get wrong.
    as_major = bolna._to_inr(
        VENDOR_WORKED_EXAMPLE["total_cost"], FX, minor_units_per_major=Decimal(1)
    )
    assert as_major is not None
    assert bolna._implied_inr_per_minute(as_major, 16) > bolna._PLAUSIBLE_INR_PER_MIN_CEILING, (
        "if BOTH readings were plausible this example could not settle the unit"
    )


def test_the_documented_execution_shape_carries_no_currency_field() -> None:
    """The half of gate 7 a payload CANNOT settle, pinned so nobody plans around it.

    `AgentExecution` declares seventeen properties and `currency` is not among them
    (`bolna-findings/mirror/pages/api-reference/executions/get_execution.md`, OpenAPI
    block). So against the documented shape `currency_stated` is always False and the
    INR-refusal branch is unreachable — an INR-billed account does not meter NOTHING
    today, it meters on the house USD assumption, which is a quieter and more dangerous
    failure than a gap. Gate 7's currency criterion therefore cannot be closed by
    capturing an execution; it needs an invoice or a wallet statement.
    """
    snapshot = _engine()._snapshot(_payload(**VENDOR_WORKED_EXAMPLE))

    assert snapshot.cost is not None
    assert snapshot.cost.currency_stated is False
    assert snapshot.cost.source_currency == "USD", "the house assumption, not a reading"


def test_a_currency_we_cannot_convert_is_refused_rather_than_guessed() -> None:
    """An absent cost is a visible gap. A cost converted at the wrong currency's rate is
    a fabricated number that reaches an invoice, and nothing downstream can tell."""
    snapshot = _engine()._snapshot(_payload(currency="EUR"))

    assert snapshot.cost is None
    # The rest of the snapshot still lands: an unconvertible cost is not a broken call.
    assert snapshot.status == "completed"
    assert snapshot.duration_s == 42


def test_the_day_the_inr_unit_is_observed_the_rate_stays_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the pair, exercised through the flip that closes the hole.

    `_MINOR_UNITS_PER_MAJOR` gains an INR entry the day gate 7 reads an INR-billed
    execution. When it does, the fx half must still be 1 — the two assumptions are
    independent and fixing the unit must not quietly reinstate the 83x error — and the
    divisor must be the one the entry names, not USD's.
    """
    monkeypatch.setitem(bolna._MINOR_UNITS_PER_MAJOR, "INR", Decimal(1))
    snapshot = _engine()._snapshot(_payload(currency="INR"))

    assert snapshot.cost is not None
    # ₹6, converted by nothing and divided by nothing.
    assert snapshot.cost.total_inr == Decimal("6.0000")
    assert snapshot.cost.source_currency == "INR"
    assert snapshot.cost.currency_stated is True
    assert snapshot.cost.fx_rate == Decimal(1)
    assert snapshot.cost.source_amount == Decimal(6), (
        "`source_amount` x `fx_rate` must reproduce the row's rupees — it used to be "
        "divided by USD's 100 while the legs were divided by the currency's own divisor"
    )


def test_the_breakdown_uses_the_same_rate_and_unit_as_the_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two rates — or two DIVISORS — in one CostBreakdown is a row whose parts do not sum
    to its whole."""
    monkeypatch.setitem(bolna._MINOR_UNITS_PER_MAJOR, "INR", Decimal(1))
    snapshot = _engine()._snapshot(_payload(currency="INR"))

    assert snapshot.cost is not None
    assert snapshot.cost.platform_inr == Decimal("4.0000")
    assert snapshot.cost.network_inr == Decimal("2.0000")
    assert (snapshot.cost.platform_inr or 0) + (snapshot.cost.network_inr or 0) == (
        snapshot.cost.total_inr
    )


# --- 2. the transcript --------------------------------------------------------


def test_a_clean_transcript_reports_nothing_lost() -> None:
    turns, lost = parse_transcript("assistant: namaskaram\nuser: appointment kavali", "c1")
    assert [t.speaker for t in turns] == ["agent", "caller"]
    assert lost == 0


def test_a_wrapped_line_is_joined_and_is_not_counted_as_lost() -> None:
    """The behaviour that made the silent-loss bug plausible in the first place: most
    unprefixed lines are continuations and joining them is right."""
    turns, lost = parse_transcript("assistant: namaskaram\nandi ela unnaru", "c1")
    assert len(turns) == 1
    assert turns[0].text == "namaskaram andi ela unnaru"
    assert lost == 0


def test_a_shape_we_do_not_recognise_is_counted_rather_than_swallowed() -> None:
    """The defect. `[]` and "nobody spoke" were the same answer, so a prefix-format
    change would have read as quiet callers on every call at once."""
    turns, lost = parse_transcript('{"role": "assistant", "content": "namaskaram"}', "c1")
    assert turns == []
    assert lost == 1


def test_a_partial_loss_is_visible_even_though_most_turns_parsed() -> None:
    """The case a total-failure check cannot reach: plenty of turns AND a real loss."""
    turns, lost = parse_transcript(
        "orphan line before anyone spoke\nassistant: namaskaram\nuser:\nuser: sare", "c1"
    )
    assert len(turns) == 2
    # One unprefixed line with no previous turn, one prefix with an empty body.
    assert lost == 2


def test_the_count_reaches_the_snapshot() -> None:
    """The seam. A count the adapter computes and the snapshot drops is a count nobody
    can score — which is exactly the state gate 7 was in."""
    snapshot = _engine()._snapshot(_payload(transcript="orphan\nassistant: hi"))
    assert snapshot.transcript_lines_unparsed == 1
    assert len(snapshot.transcript) == 1


# --- 3. when it became billable ----------------------------------------------


def test_a_vendor_completed_at_is_preferred_over_our_observation() -> None:
    stated = "2026-08-13T10:15:00+00:00"
    snapshot = _engine()._snapshot(_payload(completed_at=stated))
    assert snapshot.billable_ready_at == datetime(2026, 8, 13, 10, 15, tzinfo=UTC)


def test_without_one_we_record_when_we_observed_it_and_it_is_a_ceiling() -> None:
    """Honest, and bounded by the poller's tick rather than by the call. It over-states
    time-to-completed and never under-states it, which is the safe direction for an SLO
    check — gate 7's finding says so in the artefact."""
    before = datetime.now(UTC)
    snapshot = _engine()._snapshot(_payload())
    assert snapshot.billable_ready_at is not None
    assert snapshot.billable_ready_at >= before


def test_an_execution_that_is_not_billable_has_no_billable_instant() -> None:
    """`call-disconnected` maps to our `completed` STATUS and is not billable: cost,
    recording and extracted data land 2-3 minutes later. A timestamp here would date a
    readiness that has not happened, which is worse than the absence it replaces.

    It is also deliberately not `terminal`, and that pairing is worth pinning together —
    `terminal` is what stops the reconciliation poller, so a disconnect that reported
    terminal would end the polling exactly one transition before the data arrives. "No
    more audio" and "nothing more to learn" are different, and this adapter means the
    second."""
    snapshot = _engine()._snapshot(_payload(status="call-disconnected", total_cost=None))
    assert snapshot.status == "completed"
    assert snapshot.terminal is False, "the poller must keep going until `completed`"
    assert snapshot.billable_ready is False
    assert snapshot.billable_ready_at is None


# --- Reconciliation against bolna-ai/bolna@cd2e192 (D-260) --------------------
#
# Everything below pins a divergence found by reading the OSS framework the hosted
# platform is built on, rather than by reasoning about it. The evidence and its exact
# weight are recorded in docs/vendor/bolna/oss-harvest.md; the source is
# https://github.com/bolna-ai/bolna at commit cd2e192.


def test_non_dialogue_lines_are_not_glued_onto_the_previous_turn() -> None:
    """`format_messages` (bolna/helpers/utils.py) emits `assistant_tool_call:`,
    `tool_response:` and `system:` lines into the same string as the dialogue.

    None of them matches `_TURN_RE`, so each used to fall into the CONTINUATION branch
    and be appended to whatever the previous speaker said — putting a serialized tool
    call, arguments and all, inside the text the transcript attributes to the agent.
    Extraction reads that text.
    """
    raw = "\n".join(
        [
            "system: you are a helpful receptionist",
            "assistant: namaskaram, cheppandi",
            "assistant_tool_call: {'name': 'book_slot', 'args': {'phone': '+919876543210'}}",
            "user: appointment kavali",
            "tool_response: (call_abc): {'ok': true}",
        ]
    )
    turns, lost = parse_transcript(raw, "exec-abc123")

    assert [t.text for t in turns] == ["namaskaram, cheppandi", "appointment kavali"]
    # The agent said only what the agent said — no tool call spliced onto it.
    assert "book_slot" not in turns[0].text
    assert "+919876543210" not in turns[0].text
    # Three non-dialogue lines, counted rather than silently discarded, so gate 7 sees them.
    assert lost == 3


def test_a_genuine_wrapped_continuation_still_joins_its_turn() -> None:
    """The continuation branch is why unprefixed lines are appended at all; narrowing it
    to exclude non-dialogue roles must not cost us the wrapping it exists for."""
    raw = "assistant: namaskaram, mee appointment\nrepu udayam pattukondi"
    turns, lost = parse_transcript(raw, "exec-abc123")

    assert len(turns) == 1
    assert turns[0].text == "namaskaram, mee appointment repu udayam pattukondi"
    assert lost == 0


# --- the vendor's status enum, and the member that was missing (D-351) --------


def test_every_status_the_vendor_can_send_is_mapped() -> None:
    """`_STATUS_MAP`'s unmapped default is `failed`, which is the safe direction for a
    status we have never seen and the WRONG answer for one the vendor documents.

    The enum is now first-hand (VERIFIED-OAS: `AgentExecution.status`), so "we did not
    know the list" is no longer available as an excuse — and a status Bolna adds later
    fails here rather than turning up on a client's screen as a dead call.
    """
    unmapped = sorted(_VENDOR_STATUSES - set(_STATUS_MAP))
    assert not unmapped, f"the vendor sends these and we map none of them: {unmapped}"


def test_a_rescheduled_call_is_waiting_not_failed() -> None:
    """THE MEMBER THAT WAS MISSING, and it is the normal outcome for an Indian outbound
    campaign rather than an edge case.

    Bolna auto-reschedules a dial placed outside an agent's `calling_guardrails` window to
    the next allowed window. Unmapped, it fell to the `failed` default: a call that is
    alive and queued read as a dead one, the client's screen said the lead was not reached,
    and the campaign's failure rate counted a success as a loss.
    """
    snapshot = _engine()._snapshot(_payload(status="rescheduled"))

    assert snapshot.status == "queued"
    assert snapshot.raw_status == "rescheduled"
    assert not snapshot.terminal, "the vendor is still holding this call"
    assert not snapshot.billable_ready


def test_a_prepared_call_is_waiting_not_failed() -> None:
    """THE SECOND MEMBER THAT WAS MISSING, found the same way and costing more.

    `prepared` is the rung between "we accepted your request" and "it is in the dial
    queue": the vendor's own table calls it *Intermediate* — "Execution record created and
    validated (recipient number, from/to number assigned) but not yet handed off to the
    dial queue" (`bolna-findings/mirror/pages/api-reference/errors.md:42`). The pinned OAS
    this adapter was built from does not list it, which is why fifteen looked complete.

    Unmapped it took `_STATUS_MAP`'s `failed` default, and `failed` is TERMINAL. On the
    campaign path a terminal status settles the contact and frees the line, so a contact
    the vendor was about to dial was recorded as attempted-and-dead — while the dial it
    had already accepted went ahead anyway. That is the `rescheduled` defect (D-351) with
    a real call attached to it rather than a deferred one.
    """
    snapshot = _engine()._snapshot(_payload(status="prepared"))

    assert snapshot.status == "queued"
    assert snapshot.raw_status == "prepared", "the vendor's own word survives for the audit"
    assert not snapshot.terminal, "the vendor has accepted this call and has not dialled it"
    assert not snapshot.billable_ready, "nothing was spoken, so nothing is billable"


# --- direction, which the vendor keeps somewhere else (D-359) ----------------


def test_an_inbound_call_is_read_from_the_field_the_vendor_actually_uses() -> None:
    """`_snapshot` tested `payload["direction"]`, and `AgentExecution` declares no such
    field — the direction is `telephony_data.call_type` (VERIFIED-OAS, enum
    `["outbound", "inbound"]`).

    So the test was never true and every execution normalized as `outbound`, including
    the inbound receptionist calls that are half the product. Direction is not cosmetic:
    it is what separates a call the caller initiated from one we placed, which is a
    different consent posture and a different row on every report.
    """
    payload = _payload(telephony_data={"call_type": "inbound", "to_number": "+911140000000"})
    assert _engine()._snapshot(payload).direction == "inbound"


def test_an_outbound_call_still_reads_outbound() -> None:
    """Non-vacuity: a test that only ever asserts `inbound` passes on an adapter that
    hard-codes it."""
    payload = _payload(telephony_data={"call_type": "outbound"})
    assert _engine()._snapshot(payload).direction == "outbound"


def test_a_payload_naming_no_direction_at_all_falls_back_to_outbound() -> None:
    """The safe default, unchanged: an unclassifiable call is treated as one we placed,
    which is the direction that carries the stricter obligations."""
    assert _engine()._snapshot(_payload()).direction == "outbound"


def test_a_webhook_reads_direction_from_the_same_place_the_snapshot_does() -> None:
    """The SECOND copy of D-359's wrong read. `parse_webhook` had its own
    `payload.get("direction")` line, so fixing `_snapshot` alone would have left the live
    path — the one that fires on every status transition — still calling every inbound
    call outbound. It now asks the snapshot, which is the only way two spellings of one
    rule cannot drift apart again."""
    event = _engine().parse_webhook(_payload(telephony_data={"call_type": "inbound"}))

    assert event.direction == "inbound"


def test_a_webhook_for_a_call_we_placed_still_reads_outbound() -> None:
    """Non-vacuity for the clause above."""
    event = _engine().parse_webhook(_payload(telephony_data={"call_type": "outbound"}))

    assert event.direction == "outbound"


def test_the_end_instant_comes_from_the_timestamp_the_vendor_actually_sends() -> None:
    """`AgentExecution` carries exactly two timestamps, `created_at` and `updated_at`
    (VERIFIED-OAS). `ended_at` is in neither the spec nor `references/execution-payload.md`.

    The adapter reads `ended_at or updated_at`, so on every real payload the FALLBACK is
    what runs — and the conformance fixture used to supply `ended_at`, which meant the
    suite exercised the branch no live payload can take and never exercised the one all of
    them take. Same shape as the `direction` defect above (D-359, D-361): a stub that
    invents a field agrees with an adapter that reads it, forever.
    """
    payload = _payload(created_at="2026-08-10T09:15:00Z", updated_at="2026-08-10T09:16:35Z")
    snapshot = _engine()._snapshot(payload)

    assert snapshot.started_at is not None and snapshot.started_at.minute == 15
    assert snapshot.ended_at is not None, (
        "a payload carrying only the vendor's real timestamps must still yield an end "
        "instant — `updated_at` is the fallback and it has to work"
    )
    assert snapshot.ended_at.minute == 16


def test_the_billable_instant_is_our_observation_not_a_vendor_field() -> None:
    """`completed_at` does not exist on this vendor, so `billable_ready_at` is always the
    moment WE looked — a ceiling set by the poller's tick, never a vendor precision.

    Pinned because the comment used to read "their `completed` timestamp where they give
    one", which invites a reader to plan around an accuracy nothing supplies.
    """
    before = datetime.now(UTC)
    snapshot = _engine()._snapshot(_payload(updated_at="2020-01-01T00:00:00Z"))
    after = datetime.now(UTC)

    assert snapshot.billable_ready_at is not None
    assert before <= snapshot.billable_ready_at <= after, (
        "billable_ready_at must be the observation instant, not anything read out of the "
        "payload — the 2020 `updated_at` above is there to catch a read that drifts onto it"
    )


def test_a_call_that_is_not_completed_has_no_billable_instant() -> None:
    """Non-vacuity for the pair above: `billable_ready_at` is None until the vendor's
    terminal status, so it can never read as "ready at" for a call that is not."""
    assert _engine()._snapshot(_payload(status="in-progress")).billable_ready_at is None


# --- 4. a second call leg the adapter does not carry --------------------------
#
# `BOLNA_CAPABILITIES.transfer=False` describes what OUR publish path configures. The
# vendor's Transfer Call built-in is enabled from the agent's Tools tab — a console toggle
# — so an agent we published can grow a transfer leg without a deploy, and the vendor then
# returns `transfer_call_data`: a second leg with its own `recording_url` and its own
# `cost` (OAS `TransferCallData`). `_snapshot` reads neither. These pin the alarm that
# makes that loud instead of silent, and the hard-rule-6 bound on what it may say.


@pytest.fixture
def _fresh_alerts() -> None:
    """Per-fingerprint suppression is 15 minutes wide; a second test asserting the same
    code would read the first test's window and see nothing. Requested by name rather than
    autouse — the rest of this file asserts on return values, not on the alert path."""
    alerting.reset_alerts()


def _alert_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    """The alert path writes ONE `log.error("alert", ...)` per firing, carrying the code
    and our authored detail in `extra`."""
    return [record.__dict__ for record in caplog.records if record.message == "alert"]


def _transfer_leg(**over: object) -> dict[str, object]:
    """A completed transfer leg, shaped as `TransferCallData` declares it."""
    return {
        "provider_call_id": "CA42fb13614bfcfeccd94cf33befe14s2f",
        "status": "completed",
        "duration": "42",
        "cost": 3,
        "to_number": "+919876543210",
        "from_number": "+919812345678",
        "recording_url": "https://api.bolna.ai/recordings/transfer/exec-abc123",
        "hangup_by": "Caller",
        **over,
    }


def test_an_execution_with_a_transfer_leg_pages(
    _fresh_alerts: None, caplog: pytest.LogCaptureFixture
) -> None:
    """THE DEFECT THIS ALARM EXISTS FOR. A second recording of the same caller that our
    retention policy never sees and a DPDP erasure can never reach, plus a cost hard rule 7
    never meters — arriving because somebody flipped a toggle in the vendor's console."""
    with caplog.at_level("ERROR"):
        snapshot = _engine()._snapshot(_payload(transfer_call_data=_transfer_leg()))

    assert [str(r.get("code")) for r in _alert_records(caplog)] == ["engine_transfer_leg_unhandled"]
    assert snapshot.recording_url is None, (
        "non-vacuity: the alarm must fire BECAUSE the leg's recording is dropped, so the "
        "snapshot must still be carrying only the main leg's (absent) recording"
    )


def test_the_transfer_alarm_names_no_phone_number_and_no_recording(
    _fresh_alerts: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Hard rule 6. `TransferCallData` carries two E.164 numbers and a URL that resolves to
    caller audio; an alarm that pastes them into the log turns a compliance warning into a
    compliance breach. The alarm may say WHICH execution and WHAT is at stake, nothing more.
    """
    leg = _transfer_leg()
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(transfer_call_data=leg))

    detail = str(_alert_records(caplog)[0].get("detail"))
    for forbidden in (leg["to_number"], leg["from_number"], leg["recording_url"]):
        assert str(forbidden) not in detail, f"{forbidden!r} must never reach a log line"
    assert "exec-abc123" in str(_alert_records(caplog)[0].get("engine_call_id")), (
        "the id is the whole point — an operator has to know which execution to open"
    )


def test_an_ordinary_execution_is_silent(
    _fresh_alerts: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Every call this system places today is this shape. An alarm that fires on all of
    them is one an operator mutes, and then the transfer leg goes past."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload())
    assert _alert_records(caplog) == []


@pytest.mark.parametrize("empty", [None, {}, "", []])
def test_an_absent_or_empty_transfer_leg_is_silent(
    empty: object, _fresh_alerts: None, caplog: pytest.LogCaptureFixture
) -> None:
    """The vendor returns the key with a null/empty value on calls that were never
    transferred. Paging on "there was no transfer" would fire on every call there is."""
    with caplog.at_level("ERROR"):
        _engine()._snapshot(_payload(transfer_call_data=empty))
    assert _alert_records(caplog) == []


# --- `extracted_data`: the vendor nests by category, our contract is flat -------------
#
# `ExecutionSnapshot.engine_extracted` is a FLAT `{field_name: value}` map — that is what
# every consumer above reads it as, and `tests/pilot_fidelity_test.py` pins it. Bolna's
# `extracted_data` is two levels deep, keyed by CATEGORY first:
#
#     extracted_data -> "<Category>" -> "<Disposition>" -> {subjective, objective, ...}
#
# stated three times in their own docs — "Results are nested by category and extraction
# name under `extracted_data`", the worked `GET /executions/{id}` example, and
# `POST /v2/agent/{id}/dispositions/test` returning results "grouped by category and
# disposition name, in the same format as post-call execution data".
#
# The adapter passed that nesting straight through, so `sorted(engine_extracted)` — the
# one thing every consumer does with it — returned CATEGORY names under the label "field
# names", and pilot gate 7 scored a call in which every field arrived as a FAIL naming
# every one of them absent.


def _extracted(**over: object) -> dict[str, object]:
    """One category, one disposition, in the vendor's documented result shape."""
    return {
        "Lead Quality": {
            "Call Outcome": {
                "subjective": "Customer asked about enterprise pricing.",
                "objective": "interested",
                "confidence": 0.92,
                "confidence_label": "High",
                "reasoning_subjective": "Customer asked about pricing.",
                "reasoning_objective": "Customer agreed to a next step.",
                "validation": None,
                **over,
            }
        }
    }


def test_extracted_data_reports_the_field_name_not_its_category() -> None:
    """THE DEFECT, in the one expression every consumer writes. `sorted(...)` has to name
    the disposition an operator lists as an expected field, never the category above it."""
    snapshot = _engine()._snapshot(_payload(extracted_data=_extracted()))
    assert sorted(snapshot.engine_extracted) == ["Call Outcome"], (
        "gate 7 compares these against the operator's `expects_extracted_fields`, "
        "which name dispositions — a category here fails a call that fully succeeded"
    )


def test_the_predefined_value_wins_over_the_free_text() -> None:
    """`objective` is the pre-defined selection — the CRM-column-shaped answer. The free
    text is the fallback for a disposition configured without pre-defined options."""
    snapshot = _engine()._snapshot(_payload(extracted_data=_extracted()))
    assert snapshot.engine_extracted["Call Outcome"] == "interested"


def test_a_disposition_with_no_predefined_value_falls_back_to_the_free_text() -> None:
    snapshot = _engine()._snapshot(_payload(extracted_data=_extracted(objective=None)))
    assert snapshot.engine_extracted["Call Outcome"] == ("Customer asked about enterprise pricing.")


def test_the_vendors_account_of_itself_is_dropped() -> None:
    """`confidence`, `reasoning_*` and `validation` are the vendor describing its own
    working, not the extracted value — and the reasoning fields are free text the model
    wrote about what the CALLER said (hard rule 6)."""
    snapshot = _engine()._snapshot(_payload(extracted_data=_extracted()))
    flattened = repr(snapshot.engine_extracted)
    for leaked in ("confidence", "reasoning", "validation", "Customer agreed"):
        assert leaked not in flattened, f"{leaked!r} is not an extracted value"


def test_the_older_flat_shape_still_passes_through() -> None:
    """Extractions is "the NEW ... feature ... powered by the Dispositions API", so an
    account may still hold agents whose payload is flat. A field whose value is a scalar
    is not a category and must survive untouched."""
    snapshot = _engine()._snapshot(_payload(extracted_data={"lead_name": "Ravi Kumar"}))
    assert snapshot.engine_extracted == {"lead_name": "Ravi Kumar"}


def test_a_field_whose_value_is_an_unrelated_dict_is_not_mistaken_for_a_category() -> None:
    """Depth alone would swallow this. A category's members are RESULT objects, so the
    test is the leaf keys — `subjective`/`objective` — not the nesting."""
    snapshot = _engine()._snapshot(_payload(extracted_data={"address": {"city": "Hyderabad"}}))
    assert snapshot.engine_extracted == {"address": {"city": "Hyderabad"}}


def test_the_same_field_name_in_two_categories_keeps_both() -> None:
    """Bolna scopes disposition names to their category, so two may both be "Notes".
    A bare last-wins would silently drop one extracted value; the second is qualified."""
    snapshot = _engine()._snapshot(
        _payload(
            extracted_data={
                "Lead Quality": {"Notes": {"objective": "hot", "subjective": ""}},
                "Escalation": {"Notes": {"objective": "none", "subjective": ""}},
            }
        )
    )
    assert sorted(snapshot.engine_extracted) == ["Escalation / Notes", "Notes"]
    assert set(snapshot.engine_extracted.values()) == {"hot", "none"}


@pytest.mark.parametrize("empty", [None, {}, "", [], "nonsense"])
def test_an_absent_or_unreadable_extraction_is_no_extraction(empty: object) -> None:
    """`{}` is what "no extraction ran" already means to every consumer. Inventing a
    field out of a shape nothing here models would be worse than reporting none."""
    snapshot = _engine()._snapshot(_payload(extracted_data=empty))
    assert snapshot.engine_extracted == {}
