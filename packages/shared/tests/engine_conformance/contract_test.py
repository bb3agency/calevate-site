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
    ExecutionSnapshot,
    KBSourceRef,
    ModelConfig,
    VoiceEngine,
)
from calevate_shared.events import TERMINAL_STATUSES, CallStatus

pytestmark = [pytest.mark.conformance]

VALID_STATUSES: frozenset[str] = frozenset(CallStatus.__args__)  # type: ignore[attr-defined]


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
    if snapshot.cost is not None:
        assert isinstance(snapshot.cost.total_inr, Decimal), "money is NUMERIC, never float"
        assert snapshot.cost.total_inr >= 0


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
    turns = (await engine.get_execution(handle)).transcript

    assert turns, "a completed call must produce turns"
    assert [t.idx for t in turns] == list(range(len(turns)))
    assert all(t.speaker in ("agent", "caller") for t in turns)
    assert all(t.text.strip() for t in turns)
    assert all(t.call_id == handle or t.call_id for t in turns)


async def test_list_executions_backs_the_reconciliation_poller(engine: VoiceEngine) -> None:
    """D-31 promotes the poller from safety net to guarantee of record — so this
    method is not optional, and it must return the same normalized shape."""
    ref = await engine.create_agent(_agent_config())
    await engine.start_outbound_call(ref, "+919876543210", CallContext())
    rows = await engine.list_executions(since=datetime.now(UTC) - timedelta(hours=1))
    assert isinstance(rows, list)
    assert all(isinstance(r, ExecutionSnapshot) for r in rows)
    assert all(r.status in VALID_STATUSES for r in rows)


async def test_webhook_verification_reports_its_method(engine: VoiceEngine) -> None:
    """An adapter may not dress an unsigned event up as verified. `method` is how the
    receiver knows whether it holds proof (`hmac`) or a hint (`source_ip`/`none`)."""
    verdict = engine.verify_webhook({}, b"{}", "13.203.39.153")
    assert verdict.method in ("hmac", "source_ip", "none")
    if not verdict.ok:
        assert verdict.reason


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


async def test_unknown_vendor_status_degrades_to_failed(engine: VoiceEngine) -> None:
    """Fail closed on the unknown: a status we cannot classify must never be billed or
    shown as a success."""
    event = engine.parse_webhook(
        {"id": "exec_zzz", "agent_id": "agent_xyz", "status": "some-new-status-2027"}
    )
    assert event.status == "failed"


async def test_attach_kb_accepts_our_source_ref(engine: VoiceEngine) -> None:
    """Under BYOK the KB is not a model slot (D-33) — it is a document push, and the
    approval gate stays ours."""
    ref = await engine.create_agent(_agent_config())
    await engine.attach_kb(
        ref,
        KBSourceRef(kb_id="kb_1", title="Clinic hours", text="Mon-Sat 9am-8pm", language="te-IN"),
    )
