"""The VoiceEngine conformance suite (TRD §5) — run against EVERY adapter.

What this suite is for: the exit door. If a rented engine fails us (R-02) the cost of
leaving must be one new adapter, not a rewrite — and that is only true if every
adapter is held to identical, checkable behaviour. Each test below encodes one clause
of the contract, and the docstring says which promise would break without it.

Run: `make conformance` (or `uv run pytest -m conformance`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from calevate_shared.engine import (
    AgentConfig,
    CallContext,
    CostBreakdown,
    ExecutionSnapshot,
    KBSourceRef,
    ModelConfig,
    VoiceEngine,
)
from calevate_shared.events import TERMINAL_STATUSES, CallStatus

pytestmark = [pytest.mark.conformance]

VALID_STATUSES: frozenset[str] = frozenset(CallStatus.__args__)  # type: ignore[attr-defined]

# Bolna's documented static egress address (D-31) — the positive case for an adapter
# whose authenticity control is a source-IP allowlist.
ALLOWLISTED_SOURCE_IP = "13.203.39.153"
# RFC 5737 documentation range: the stranger who found the URL. Unroutable, so it can
# never accidentally become someone's real address.
UNKNOWN_SOURCE_IP = "203.0.113.9"


def _agent_config() -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic receptionist",
        direction="inbound",
        language_primary="te-IN",
        system_prompt="You are the receptionist for Sunrise Clinic.",
        disclosure_line="Idi AI assistant. Ee call record avutundi.",
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="sarvam-105b",
            tts_provider="sarvam",
            tts_voice="bulbul:v3",
        ),
        webhook_url="https://hooks.calevate.tech/v1/engine/bolna",
    )


def _assert_cost_is_re_derivable(cost: CostBreakdown) -> None:
    """Hard rule 7, stated as a checkable property.

    `CostBreakdown` promises that the adapter converts at capture and STAMPS the rate
    it used, "so a ledger row can always be re-derived". A total with no source amount
    and no fx rate satisfies the type and breaks the promise: six months later nobody
    can answer "why is this usage_event ₹7.48" without the vendor's dashboard, and a
    disputed invoice is a dispute we lose.

    So: the stamp must be present, and it must actually reproduce the total.
    """
    assert cost.source_currency, "the source currency must be recorded"
    assert cost.source_amount is not None, "the vendor's own amount must be recorded"
    assert cost.fx_rate is not None, "the rate used at capture must be recorded"
    assert cost.fx_rate > 0
    re_derived = cost.source_amount * cost.fx_rate
    assert abs(re_derived - cost.total_inr) <= Decimal("0.01"), (
        f"source_amount * fx_rate = {re_derived} cannot reproduce total_inr {cost.total_inr}"
    )


async def test_adapter_satisfies_the_protocol(engine: VoiceEngine) -> None:
    """A runtime_checkable Protocol only checks method NAMES — which is exactly the
    check that catches a half-written adapter being wired into config."""
    assert isinstance(engine, VoiceEngine)
    assert engine.name


async def test_create_and_update_agent_returns_a_stable_ref(engine: VoiceEngine) -> None:
    """`engine_agent_ref` is the join key between their world and ours; if it were not
    stable, webhook→tenant resolution would break for every existing agent."""
    cfg = _agent_config()
    ref = await engine.create_agent(cfg)
    assert isinstance(ref, str) and ref
    assert await engine.create_agent(cfg) == ref
    await engine.update_agent(ref, cfg)


async def test_outbound_call_returns_a_handle(engine: VoiceEngine) -> None:
    ref = await engine.create_agent(_agent_config())
    handle = await engine.start_outbound_call(
        ref,
        "+919876543210",
        CallContext(lead_name="Ravi", context_note="Called about the 6pm slot"),
    )
    assert isinstance(handle, str) and handle


async def test_execution_snapshot_is_fully_normalized(engine: VoiceEngine) -> None:
    """The isolation boundary (hard rule 2): whatever the vendor sends, what comes out
    is OUR shape, OUR status vocabulary and OUR currency."""
    ref = await engine.create_agent(_agent_config())
    handle = await engine.start_outbound_call(ref, "+919876543210", CallContext())
    snapshot = await engine.get_execution(handle)

    assert isinstance(snapshot, ExecutionSnapshot)
    assert snapshot.status in VALID_STATUSES
    assert snapshot.engine_call_id
    # The ONLY bridge from their world to a tenant. The reconciliation poller — the
    # guarantee of record under D-31 — has no webhook payload to read this from, so an
    # adapter that omits it makes every repaired call unmappable, silently.
    assert snapshot.engine_agent_ref, "a snapshot must carry the engine's agent ref"
    if snapshot.cost is not None:
        assert isinstance(snapshot.cost.total_inr, Decimal), "money is NUMERIC, never float"
        assert snapshot.cost.total_inr >= 0
        _assert_cost_is_re_derivable(snapshot.cost)


async def test_billable_ready_implies_terminal(engine: VoiceEngine) -> None:
    """The trap this closes: Bolna's cost/recording/transcript are null until
    `completed` (~2-3 min after disconnect). A pipeline that triggered on 'terminal'
    would meter zeros. `billable_ready` must never be true before `terminal`."""
    ref = await engine.create_agent(_agent_config())
    handle = await engine.start_outbound_call(ref, "+919876543210", CallContext())
    snapshot = await engine.get_execution(handle)
    if snapshot.billable_ready:
        assert snapshot.terminal
        assert snapshot.status in TERMINAL_STATUSES


async def test_transcript_turns_are_ordered_and_speaker_tagged(engine: VoiceEngine) -> None:
    """Extraction, redaction and the call-detail view all index by `idx` and switch on
    `speaker`; a gap or a vendor speaker label leaking through breaks all three."""
    ref = await engine.create_agent(_agent_config())
    handle = await engine.start_outbound_call(ref, "+919876543210", CallContext())
    snapshot = await engine.get_execution(handle)
    turns = snapshot.transcript

    assert turns, "a completed call must produce turns"
    assert [t.idx for t in turns] == list(range(len(turns)))
    assert all(t.speaker in ("agent", "caller") for t in turns)
    assert all(t.text.strip() for t in turns)
    # Every turn belongs to THIS call. `transcripts` is tenant-scoped and a turn is
    # filed by call_id, so a turn carrying another call's id is a transcript written
    # into the wrong call — and potentially the wrong tenant's dashboard.
    assert all(t.call_id == snapshot.engine_call_id for t in turns), (
        "a transcript turn is attributed to a call other than the one it came from"
    )


async def test_list_executions_backs_the_reconciliation_poller(engine: VoiceEngine) -> None:
    """D-31 promotes the poller from safety net to guarantee of record — so this
    method is not optional, and it must return the same normalized shape."""
    ref = await engine.create_agent(_agent_config())
    await engine.start_outbound_call(ref, "+919876543210", CallContext())
    rows = await engine.list_executions(since=datetime.now(UTC) - timedelta(hours=1))
    assert isinstance(rows, list)
    assert all(isinstance(r, ExecutionSnapshot) for r in rows)
    assert all(r.status in VALID_STATUSES for r in rows)
    assert all(r.engine_call_id for r in rows), "a repaired call needs an id to repair"
    # The poller path is the one with NO webhook payload behind it, so this is the only
    # place the agent ref can come from. Without it a reconciled call resolves to no
    # tenant and the repair quietly does nothing.
    assert all(r.engine_agent_ref for r in rows), "a polled snapshot must be mappable"


async def test_webhook_verification_reports_its_method(engine: VoiceEngine) -> None:
    """An adapter may not dress an unsigned event up as verified. `method` is how the
    receiver knows whether it holds proof (`hmac`) or a hint (`source_ip`/`none`)."""
    verdict = engine.verify_webhook({}, b"{}", ALLOWLISTED_SOURCE_IP)
    assert verdict.method in ("hmac", "source_ip", "none")
    if not verdict.ok:
        assert verdict.reason


async def test_a_claimed_verification_method_actually_rejects_somebody(
    engine: VoiceEngine,
) -> None:
    """The clause the label above is worthless without.

    `method` is a claim, and the receiver acts on it: an event labelled `source_ip` is
    recorded as evidence in `webhook_deliveries.signature_valid` and is the entire
    reason the event is processed at all. An adapter that returns `ok=True` for every
    caller while calling it `source_ip` is not a lenient adapter — it is a public,
    unauthenticated write endpoint wearing the word "verified".

    So an adapter that names a verification method must be able to fail one. An adapter
    that verifies NOTHING is allowed (the `fake` engine exists precisely to exercise the
    code after verification) but it must say so, in `method="none"` and in `reason` —
    the receiver's own per-engine check is what keeps such an adapter out of production.
    """
    stranger = engine.verify_webhook({}, b"{}", UNKNOWN_SOURCE_IP)
    claimed = engine.verify_webhook({}, b"{}", ALLOWLISTED_SOURCE_IP).method

    if claimed in ("hmac", "source_ip"):
        assert not stranger.ok, (
            f"this adapter claims `{claimed}` verification but accepts an unknown caller"
        )
        assert stranger.reason, "a rejection must say why"
    else:
        assert stranger.ok is True
        assert stranger.reason, "an adapter that verifies nothing must declare it"


async def test_webhook_parses_into_our_event(engine: VoiceEngine) -> None:
    """`parse_webhook` may not invent tenant_id/agent_id — a vendor cannot know them,
    and a guessed tenant is a cross-tenant write (hard rule 1)."""
    event = engine.parse_webhook(
        {
            "id": "exec_abc123",
            "execution_id": "exec_abc123",
            "agent_id": "agent_xyz",
            "status": "completed",
            "direction": "inbound",
            "from_number": "+919876543210",
            "to_number": "+911140000000",
        }
    )
    assert event.call_id == "exec_abc123"
    assert event.engine == engine.name
    assert event.status in VALID_STATUSES
    assert event.tenant_id is None and event.agent_id is None
    assert event.engine_agent_ref == "agent_xyz"
    # Direction decides which obligations attach — DNC, calling hours, 140/160 series.
    # An adapter that hard-codes it is a compliance decision made by accident.
    assert event.direction == "inbound", "the payload says inbound; the event must too"
    # The vendor's own word, kept verbatim. It is what the forensic delivery row
    # records and what the ingest job is keyed on, so losing it makes "why was this
    # call marked failed" unanswerable from our side.
    assert event.raw_status, "the vendor's raw status must survive normalization"


async def test_unknown_vendor_status_degrades_to_failed(engine: VoiceEngine) -> None:
    """Fail closed on the unknown: a status we cannot classify must never be billed or
    shown as a success."""
    event = engine.parse_webhook(
        {"id": "exec_zzz", "agent_id": "agent_xyz", "status": "some-new-status-2027"}
    )
    assert event.status == "failed"


async def test_attach_kb_accepts_our_source_ref_and_returns_a_handle(
    engine: VoiceEngine,
) -> None:
    """Under BYOK the KB is not a model slot (D-33) — it is a document push, and the
    approval gate stays ours.

    The handle is the load-bearing part. The engine names its own copy of the document;
    an adapter that pushes text and returns nothing has attached something that can
    never be taken back, and "publish v2" becomes "add v2 next to v1".
    """
    ref = await engine.create_agent(_agent_config())
    handle = await engine.attach_kb(
        ref,
        KBSourceRef(kb_id="kb_1", title="Clinic hours", text="Mon-Sat 9am-8pm", language="te-IN"),
    )
    assert isinstance(handle, str) and handle, "an attached source must be addressable"


async def test_detach_kb_actually_removes_exactly_the_source_it_names(
    engine: VoiceEngine,
) -> None:
    """The clause that makes `detach_kb` mean something.

    What breaks without it: FLOWS §7 says publishing a version supersedes the previous
    one, and rollback reactivates a prior version. Both are OUR bookkeeping. What the
    caller hears is whatever the ENGINE holds — so if `detach_kb` is a no-op, a client
    approves v2 and the agent goes on quoting v1's prices, with every one of our screens
    reporting success. That is the approval gate failing at the only point it exists to
    protect, and no test above this one can see it: `attach_kb` still returned, the
    tables still flipped, the publish still 200'd.

    So the removal is observed, never assumed. `list_kb` is read BEFORE and AFTER, and
    the two handles make it a real test rather than a smoke test: an adapter whose
    `detach_kb` does nothing fails on the first assertion, and one that responds by
    wiping the agent's whole knowledge base fails on the second — a KB that empties
    itself on every publish is the same outage as a KB that never shrinks, arriving
    from the other side.
    """
    ref = await engine.create_agent(_agent_config())
    superseded = await engine.attach_kb(
        ref, KBSourceRef(kb_id="kb_detach_v1", title="Fees", text="A consultation costs 500.")
    )
    kept = await engine.attach_kb(
        ref, KBSourceRef(kb_id="kb_detach_other", title="Parking", text="Parking is free.")
    )
    assert superseded != kept, "two sources must not share one handle — one cannot be removed"
    assert {superseded, kept} <= set(await engine.list_kb(ref)), (
        "an attached source must be visible to `list_kb`, or a detach can never be proven"
    )

    await engine.detach_kb(ref, superseded)

    remaining = await engine.list_kb(ref)
    assert superseded not in remaining, (
        "`detach_kb` returned without removing anything — the superseded version is "
        "still what the agent answers from"
    )
    assert kept in remaining, "detach removed a source it was not asked to remove"


async def test_a_detach_that_did_not_happen_is_reported_rather_than_swallowed(
    engine: VoiceEngine,
) -> None:
    """The second half of the same promise, aimed at the adapter that means well.

    `try: delete() except: pass` passes the clause above (it does remove things when the
    vendor is up) and is still the bug: when the engine is down or the handle is stale,
    it reports success for a removal that never happened, and the publisher — whose very
    next act is to attach the replacement — has no way to know. An unknown handle is the
    one case a test can stage without breaking the transport, so it stands in for the
    whole class: a detach the adapter cannot show it performed must raise.

    An adapter whose vendor deletes idempotently satisfies this by reading the handle
    back before or after (Bolna documents `GET /knowledgebase/{rag_id}` for exactly
    that) — the contract asks for evidence, not for a particular status code.
    """
    ref = await engine.create_agent(_agent_config())
    reported: Exception | None = None
    try:
        await engine.detach_kb(ref, "kb_this_engine_never_issued")
    except Exception as exc:  # adapters raise our ProblemError; the type is theirs
        reported = exc
    assert reported is not None, (
        "detaching a handle this engine never issued was reported as a success — "
        "the caller cannot distinguish a removal from a silent no-op"
    )
