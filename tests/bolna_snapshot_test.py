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
        "total_cost": 600,  # 600 of SOMETHING; what, is the question below
        "cost_breakdown": {"platform": 400, "network": 200},
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
    # 600 cents = $6.00, at 83.50 = ₹501.
    assert snapshot.cost.total_inr == Decimal("501.0000")
    assert snapshot.cost.fx_rate == FX


def test_a_stated_usd_is_recorded_as_a_reading_not_a_guess() -> None:
    """Same number, different epistemic status — which is the entire point of the flag."""
    snapshot = _engine()._snapshot(_payload(currency="usd"))

    assert snapshot.cost is not None
    assert snapshot.cost.total_inr == Decimal("501.0000")
    assert snapshot.cost.currency_stated is True


def test_a_stated_inr_is_not_multiplied_by_the_dollar_rate() -> None:
    """THE 83x BUG. If Bolna bills an India account in INR paise and the adapter converts
    anyway, our recorded cost basis is out by the exchange rate — upward, which flatters
    the margin panel and understates what a minute costs us."""
    snapshot = _engine()._snapshot(_payload(currency="INR"))

    assert snapshot.cost is not None
    # 600 paise = ₹6.00, converted by nothing.
    assert snapshot.cost.total_inr == Decimal("6.0000")
    assert snapshot.cost.source_currency == "INR"
    assert snapshot.cost.currency_stated is True
    assert snapshot.cost.fx_rate == Decimal(1)


def test_a_currency_we_cannot_convert_is_refused_rather_than_guessed() -> None:
    """An absent cost is a visible gap. A cost converted at the wrong currency's rate is
    a fabricated number that reaches an invoice, and nothing downstream can tell."""
    snapshot = _engine()._snapshot(_payload(currency="EUR"))

    assert snapshot.cost is None
    # The rest of the snapshot still lands: an unconvertible cost is not a broken call.
    assert snapshot.status == "completed"
    assert snapshot.duration_s == 42


def test_the_breakdown_uses_the_same_rate_as_the_total() -> None:
    """Two rates in one CostBreakdown is a row whose parts do not sum to its whole."""
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
