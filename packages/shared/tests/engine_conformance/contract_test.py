"""The VoiceEngine conformance suite (TRD §5) — run against EVERY adapter.

What this suite is for: the exit door. If a rented engine fails us (R-02) the cost of
leaving must be one new adapter, not a rewrite — and that is only true if every
adapter is held to identical, checkable behaviour. Each test below encodes one clause
of the contract, and the docstring says which promise would break without it.

Run: `make conformance` (or `uv run pytest -m conformance`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from calevate_shared.engine import (
    WEBHOOK_AUTH_BY_ENGINE,
    AgentConfig,
    CallContext,
    CostBreakdown,
    EngineCapabilities,
    ExecutionSnapshot,
    KBSourceRef,
    ModelConfig,
    NumberSeries,
    NumberSpec,
    ProvisionedNumber,
    VoiceEngine,
)
from calevate_shared.events import TERMINAL_STATUSES, CallStatus

pytestmark = [pytest.mark.conformance]

VALID_STATUSES: frozenset[str] = frozenset(CallStatus.__args__)  # type: ignore[attr-defined]
#: Derived from the type, never retyped: a series added to `NumberSeries` is one the
#: campaign launch gate can meet, so the capability clauses must probe it automatically.
NUMBER_SERIES_VALUES: tuple[NumberSeries, ...] = NumberSeries.__args__  # type: ignore[attr-defined]

# Bolna's documented static egress address (D-31) — the positive case for an adapter
# whose authenticity control is a source-IP allowlist.
ALLOWLISTED_SOURCE_IP = "13.203.39.153"
# RFC 5737 documentation range: the stranger who found the URL. Unroutable, so it can
# never accidentally become someone's real address.
UNKNOWN_SOURCE_IP = "203.0.113.9"


def _byok_models(engine: VoiceEngine) -> ModelConfig:
    """Our canonical D-36 stack, reduced to the legs THIS engine lets us choose.

    A leg the engine dictates is left None deliberately, and that is not the suite
    tiptoeing around an adapter: `require_speech_leg` refuses a value for a dictated leg
    on purpose (silently dropping it is what produces a picker offering a voice the
    caller will never hear), so a fixture that always sent all five fields could only
    ever build agents on a BYOK engine. Every clause below would then be untestable
    against the shape this contract most needs to survive.
    """
    caps = engine.capabilities
    return ModelConfig(
        stt_provider="sarvam" if caps.is_ours("stt") else None,
        stt_model="saaras:v3" if caps.is_ours("stt") else None,
        llm_model="sarvam-105b" if caps.is_ours("llm") else None,
        tts_provider="sarvam" if caps.is_ours("tts") else None,
        tts_voice="bulbul:v3" if caps.is_ours("tts") else None,
    )


def _agent_config(
    engine: VoiceEngine,
    *,
    name: str = "Sunrise Clinic receptionist",
    agent_id: str = "0199a0b0-0000-7000-8000-000000000002",
    system_prompt: str = "You are the receptionist for Sunrise Clinic.",
) -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id=agent_id,
        name=name,
        direction="inbound",
        language_primary="te-IN",
        system_prompt=system_prompt,
        disclosure_line="Idi AI assistant. Ee call record avutundi.",
        models=_byok_models(engine),
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
    cfg = _agent_config(engine)
    ref = await engine.create_agent(cfg)
    assert isinstance(ref, str) and ref
    assert await engine.create_agent(cfg) == ref
    await engine.update_agent(ref, cfg)


async def test_agent_read_back_reports_the_agent_it_was_asked_about(
    engine: VoiceEngine,
) -> None:
    """THE CLAUSE THAT MAKES `update_agent` MEAN SOMETHING (OPERATIONS §2, gate 2).

    A 2xx on the update says the vendor accepted the bytes. It does not say the agent is
    running that prompt, and the difference is not academic: the prompt carries the
    compliance disclosure a client is legally answerable for. Until `get_agent` existed,
    "update the prompt" could only ever be scored ACCEPTED.

    TWO AGENTS, ON PURPOSE. The read-back that would be worthless is the one that echoes
    whatever was last SENT — it agrees with every caller by construction and can never
    contradict anything, so a vendor that silently dropped the write would still score
    APPLIED. One agent cannot tell the two apart, because the last thing sent and the
    thing stored are the same object. So this writes a distinct marker into each of two
    agents, updates one of them, and requires each read-back to carry its OWN marker and
    not the other's. An echoing adapter fails on the second agent; an adapter that reads
    a shared "last write" fails on both.

    Containment, not equality: adapters render our config into the vendor's object (ours
    PREPENDS the disclosure line, hard rule 5), so `==` would fail on a correctly applied
    update. `AgentSnapshot.carries_prompt_marker` is the contract's answer to that.
    """
    first = _agent_config(
        engine,
        name="Sunrise Clinic receptionist",
        agent_id="0199a0b0-0000-7000-8000-00000000000a",
        system_prompt="Receptionist. marker-alpha",
    )
    second = _agent_config(
        engine,
        name="Sunrise Clinic outbound",
        agent_id="0199a0b0-0000-7000-8000-00000000000b",
        system_prompt="Outbound caller. marker-beta",
    )
    first_ref = await engine.create_agent(first)
    second_ref = await engine.create_agent(second)
    assert first_ref != second_ref, "two agents sharing one ref cannot be told apart at all"

    await engine.update_agent(
        first_ref, first.model_copy(update={"system_prompt": "Receptionist. marker-gamma"})
    )

    read_first = await engine.get_agent(first_ref)
    read_second = await engine.get_agent(second_ref)

    assert read_first.engine_agent_ref == first_ref, "the read-back describes another agent"
    assert read_second.engine_agent_ref == second_ref
    assert read_first.system_prompt_readable, (
        "the adapter could not read a prompt back, so 'did the update apply?' is "
        "unanswerable and gate 2 can never score better than ACCEPTED"
    )
    assert read_first.carries_prompt_marker("marker-gamma") is True, (
        "the updated prompt is not what the engine holds — the write was accepted and "
        "not applied, which is exactly the failure this method exists to detect"
    )
    assert read_first.carries_prompt_marker("marker-alpha") is False, (
        "the superseded prompt is still live"
    )
    # The anti-echo assertion. If these fail, the adapter is reporting the last write
    # rather than the agent's own state.
    assert read_first.carries_prompt_marker("marker-beta") is False, (
        "one agent's read-back carries another agent's prompt"
    )
    assert read_second.carries_prompt_marker("marker-beta") is True, (
        "reading agent B back returned whatever was written LAST, not agent B"
    )


async def test_a_read_back_carries_the_disclosure_line_the_engine_was_given(
    engine: VoiceEngine,
) -> None:
    """HARD RULE 5, SCORED ON THE ENGINE RATHER THAN ON OUR REQUEST BODY.

    Every adapter PREPENDS `disclosure_line` to the prompt so it is spoken first. That is
    a property of what we SEND, and until this clause nothing checked it survived the
    round trip — the suite scored the script with a marker the disclosure line does not
    contain, so an adapter that rendered the greeting into a field its own read-back
    cannot see would pass every clause above it.

    THIS IS NOW LOAD-BEARING RATHER THAN MERELY DESIRABLE.
    `apps/api/agents/verification.py` scores every publish by reading the agent back and
    requiring BOTH the script and the disclosure line to be present; a proven absence is
    a refusal. So an adapter whose read-back drops the disclosure does not merely go
    unmeasured — it makes every publish on that engine fail closed, for the whole
    deployment. Which is the correct direction to fail in, and exactly the reason it must
    be caught here by a test rather than in production by a client with a dead phone line.

    Containment, for the `carries_prompt_marker` reason: the greeting may be rendered
    into a welcome message, a preamble or a header, and any rendering that KEPT THE TEXT
    satisfies both the rule and this clause.
    """
    cfg = _agent_config(
        engine,
        agent_id="0199a0b0-0000-7000-8000-00000000000c",
        system_prompt="Receptionist. marker-disclosure",
    )
    ref = await engine.create_agent(cfg)
    snapshot = await engine.get_agent(ref)

    assert snapshot.system_prompt_readable, (
        "the prompt could not be read back at all, so hard rule 5 is unverifiable on "
        "this engine and every publish through `verification.judge` reports unreadable"
    )
    assert snapshot.carries_prompt_marker(cfg.disclosure_line) is True, (
        "the disclosure line the adapter prepended is not in what the engine holds — "
        "either the adapter dropped it (a compliance defect) or its read-back cannot "
        "see it (a publish that can never be confirmed)"
    )
    assert snapshot.carries_prompt_marker(cfg.system_prompt) is True, (
        "the script we sent is not in what the engine holds, so a publish of it could "
        "never be scored applied"
    )
    # AND THE GREETING, which is the half that actually speaks (P3.3). Both clauses
    # above are about the PROMPT — the field our own adapter prepends the line to — so
    # an adapter could satisfy every one of them while the engine opened the call
    # saying nothing. `verification.judge` scores hard rule 5 on the greeting now, so an
    # adapter whose read-back cannot see it fails every publish closed on that engine,
    # exactly as the prompt clause above already did. Caught here rather than by a client
    # with a dead phone line.
    assert snapshot.greeting_readable, (
        "the adapter cannot read the greeting back, so hard rule 5's verdict is "
        "`unreadable` on every publish through this engine — the disclosure can never "
        "be confirmed, only assumed"
    )
    assert snapshot.carries_greeting_marker(cfg.disclosure_line) is True, (
        "the greeting the engine holds does not contain the disclosure line, so the "
        "first thing this agent says to a caller is not the thing SEC-COMP §1 requires"
    )


async def test_reading_an_agent_the_engine_never_created_is_reported(
    engine: VoiceEngine,
) -> None:
    """An unknown ref must raise, never answer.

    A snapshot for an agent that does not exist is worse than an error in both places
    that use this method: gate 2 would record "prompt not applied" for a phantom, and
    gate 8 would record "no dangling `rag_id`" about an agent object nobody ever read.
    Both are conclusions drawn from nothing, and both look like measurements.
    """
    reported: Exception | None = None
    try:
        await engine.get_agent("agent_this_engine_never_created")
    except Exception as exc:  # adapters raise our ProblemError; the type is theirs
        reported = exc
    assert reported is not None, (
        "reading back an agent the engine never created returned a snapshot — a caller "
        "cannot distinguish it from a real agent's configuration"
    )


async def test_delete_agent_removes_exactly_the_agent_it_names_and_is_idempotent(
    engine: VoiceEngine,
) -> None:
    """THE CLAUSE THAT MAKES AN ORPHAN COMPENSABLE (D-121's second gap).

    `create_agent` is a side effect at a third party and our `engine_agent_ref` write is a
    side effect in our database, with no transaction over both. Until `delete_agent`
    existed, every failure in that window left a vendor-side object we were billed for and
    could not address, and the only remedy on the books was a log line and a human in a
    dashboard. `agents/service.py::_reclaim_orphan` is the caller; this is the clause that
    stops it being ceremony.

    THREE PROPERTIES, and each of them is a way an adapter can be wrong:

    1. **It really removes.** Observed through `get_agent` rather than through the delete's
       own return value, for `detach_kb`'s reason: an adapter that accepts the call and
       does nothing satisfies a `assert await engine.delete_agent(ref) is None` perfectly.
    2. **It removes the one it NAMES.** Two agents are created and one is deleted. A
       delete that took the account down with it, or that addressed the last-written agent
       instead of the argument, passes property 1 alone — and the compensator runs while a
       correctly published agent for the same tenant may exist.
    3. **A second delete is not an error.** The Protocol makes this idempotent because the
       caller is a compensation path, i.e. the one most likely to be retried; raising here
       DLQs a job whose work is done. For the two real adapters this exercises the
       `absent_is_success` branch against a stub 404 — and BOTH adapters' `delete_agent`
       carry a marked assumption that a vendor answers 404 rather than 400 to a repeat,
       which no stub can settle (OPERATIONS §2 gate 2).
    """
    kept = await engine.create_agent(_agent_config(engine, name="Kept receptionist"))
    doomed = await engine.create_agent(
        _agent_config(
            engine,
            name="Orphaned receptionist",
            agent_id="0199a0b0-0000-7000-8000-0000000000de",
        )
    )
    assert kept != doomed, (
        "this engine minted one ref for two differently-named agents, so the clause below "
        "cannot tell 'deleted the right one' from 'deleted the only one'"
    )

    await engine.delete_agent(doomed)

    gone: Exception | None = None
    try:
        await engine.get_agent(doomed)
    except Exception as exc:  # adapters raise our ProblemError; the type is theirs
        gone = exc
    assert gone is not None, (
        "the agent is still readable after delete_agent — an orphan this adapter reports "
        "as compensated is still costing money at the vendor"
    )

    # Property 2: the blast radius was one object.
    assert (await engine.get_agent(kept)).engine_agent_ref == kept, (
        "delete_agent took a DIFFERENT agent with it — the compensator runs beside live "
        "agents belonging to the same account"
    )

    # Property 3: the postcondition is already satisfied, so this must not raise.
    await engine.delete_agent(doomed)
    await engine.delete_agent("agent_this_engine_never_created")


async def test_agent_read_back_answers_or_declines_the_kb_reference_question(
    engine: VoiceEngine,
) -> None:
    """D-41's dangling handle, and the right to say "I cannot tell" (gate 8).

    `detach_kb` deletes the knowledge base. Whether the AGENT stops referencing it is a
    fact about a different object, and `list_kb` — the account's KB list — cannot answer
    it. If the reference survives, `detach_kb` is a delete PLUS an agent update, and every
    publish that did only the delete left the agent pointing at knowledge that is gone.

    Two answers are conformant and one is not. An adapter that can locate the agent's
    reference field must report it accurately (`knowledge_base_refs_readable=True`, and
    the attached handle really appears). An adapter that cannot must say
    `knowledge_base_refs_readable=False` — the Bolna adapter's position today, because
    nothing published says the agent object carries a KB reference or what it is called.
    What is forbidden is the third answer: an empty list presented as knowledge, which
    would close D-41 with "nothing dangles" on no evidence at all.
    """
    if not engine.capabilities.knowledge_base:
        # D-41 is a question about an engine-side knowledge base. On an engine that has
        # none there is no dangling handle to ask about, and the clause that DOES apply
        # is `test_an_engine_without_a_knowledge_base_refuses_all_three_kb_methods`.
        return
    ref = await engine.create_agent(_agent_config(engine))
    handle = await engine.attach_kb(
        ref, KBSourceRef(kb_id="kb_readback", title="Fees", text="A consultation costs 500.")
    )
    snapshot = await engine.get_agent(ref)

    if not snapshot.knowledge_base_refs_readable:
        # The declared "cannot tell". It must be declared consistently: a snapshot that
        # says unreadable and still hands over refs is claiming both.
        assert snapshot.references_kb(handle) is None
        assert not snapshot.knowledge_base_refs
        return

    assert snapshot.references_kb(handle) is True, (
        "the adapter claims it can read the agent's knowledge references, and the source "
        "just attached to this agent is not among them — so a dangling handle would be "
        "just as invisible"
    )
    await engine.detach_kb(ref, handle)
    after = await engine.get_agent(ref)
    assert after.references_kb(handle) is False, (
        "the agent still references the detached knowledge base (D-41): `detach_kb` is a "
        "delete PLUS an agent update on this engine, and publish must do both"
    )


async def test_outbound_call_returns_a_handle(engine: VoiceEngine) -> None:
    ref = await engine.create_agent(_agent_config(engine))
    handle = await engine.start_outbound_call(
        ref,
        "+919876543210",
        CallContext(lead_name="Ravi", context_note="Called about the 6pm slot"),
    )
    assert isinstance(handle, str) and handle


async def test_execution_snapshot_is_fully_normalized(engine: VoiceEngine) -> None:
    """The isolation boundary (hard rule 2): whatever the vendor sends, what comes out
    is OUR shape, OUR status vocabulary and OUR currency."""
    ref = await engine.create_agent(_agent_config(engine))
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


async def test_get_execution_carries_the_vendors_own_document_for_the_archive(
    engine: VoiceEngine,
) -> None:
    """THE CLAUSE THAT KEEPS D-126's ERASURE ARM POINTED AT SOMETHING.

    `storage.archive_payload` keeps the engine's own document for a call,
    `calls.engine_payload_ref` names it and `retention._erase_engine_payloads` destroys it
    on both erasure paths — and for as long as no adapter carried a document, all three
    guarded a store that could not exist. The archive is TRD §5's deliberate escape valve
    for hard rule 2 (raw vendor payloads live in object storage precisely so they never
    land in typed columns), so an adapter that supplies nothing is not merely unhelpful:
    it removes the only record of what the vendor actually said, on a platform whose
    webhooks are unsigned and at-most-once (D-31).

    THREE PROPERTIES, and each is a way an adapter can be wrong.

    1. **It is there, and it is bytes.** `ExecutionSnapshot.raw_document` is `bytes` on
       purpose — a `dict` would carry the vendor's field names to every caller, which is
       the leak an import contract cannot see. An adapter returning `None` here is what
       this clause primarily refuses.
    2. **It is the VENDOR'S document, not a re-render of the snapshot.** An adapter that
       dumped its own `ExecutionSnapshot` would archive OUR normalization, so the day a
       mapping turns out wrong the only record of what the vendor said is a copy of what
       we thought it said — and every other property here would still hold, which is how
       a deliberate sabotage of the Cartesia adapter walked through the first version of
       this clause. The check has to be structural, because the suite may not name a
       vendor field either: a document whose every top-level key is a field of
       `ExecutionSnapshot` is our own shape wearing the archive's name.
    3. **It describes THIS execution.** Two different calls must not yield one document.
       An adapter answering with a constant writes the same bytes under every call's
       erasure prefix, so the archive describes no call at all — the same defect
       `test_agent_read_back_reports_the_agent_it_was_asked_about` refuses for prompts,
       and a stub that echoes a fixture regardless of the id would hide it.

    Note what is NOT asserted: any field name, anywhere. The suite reads the document's
    length and its parseability and nothing else — it may not look inside either.
    """
    ref = await engine.create_agent(_agent_config(engine))
    first = await engine.start_outbound_call(ref, "+919876543210", CallContext(lead_id="lead-1"))
    second = await engine.start_outbound_call(ref, "+919876543211", CallContext(lead_id="lead-2"))
    assert first != second, "this engine minted one handle for two calls"

    one = (await engine.get_execution(first)).raw_document
    two = (await engine.get_execution(second)).raw_document

    assert one is not None, (
        "this adapter carries no raw document out of `get_execution`, so nothing can "
        "archive what the vendor said — `calls.engine_payload_ref` is a column with no "
        "writer and D-126's erasure arm guards an object that is never created"
    )
    assert isinstance(one, bytes) and one, "the document must be non-empty bytes"
    parsed = json.loads(one.decode())
    assert isinstance(parsed, dict) and parsed, (
        "the archived document must be the vendor's own object; anything else cannot be "
        "re-read when our mapping turns out to be wrong"
    )
    assert not set(parsed) <= set(ExecutionSnapshot.model_fields), (
        "every key in this document is a field of OUR `ExecutionSnapshot`, so this "
        "adapter is archiving its own normalization — the archive exists precisely to "
        "survive our normalization being wrong"
    )
    assert two is not None and two != one, (
        "two different executions produced the SAME document — the archive under each "
        "call's erasure prefix would describe neither call"
    )


async def test_billable_ready_implies_terminal(engine: VoiceEngine) -> None:
    """The trap this closes: Bolna's cost/recording/transcript are null until
    `completed` (~2-3 min after disconnect). A pipeline that triggered on 'terminal'
    would meter zeros. `billable_ready` must never be true before `terminal`."""
    ref = await engine.create_agent(_agent_config(engine))
    handle = await engine.start_outbound_call(ref, "+919876543210", CallContext())
    snapshot = await engine.get_execution(handle)
    if snapshot.billable_ready:
        assert snapshot.terminal
        assert snapshot.status in TERMINAL_STATUSES


async def test_transcript_turns_are_ordered_and_speaker_tagged(engine: VoiceEngine) -> None:
    """Extraction, redaction and the call-detail view all index by `idx` and switch on
    `speaker`; a gap or a vendor speaker label leaking through breaks all three."""
    ref = await engine.create_agent(_agent_config(engine))
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
    ref = await engine.create_agent(_agent_config(engine))
    await engine.start_outbound_call(ref, "+919876543210", CallContext())
    listing = await engine.list_executions(since=datetime.now(UTC) - timedelta(hours=1))
    rows = listing.snapshots
    assert all(isinstance(r, ExecutionSnapshot) for r in rows)
    assert all(r.status in VALID_STATUSES for r in rows)
    assert all(r.engine_call_id for r in rows), "a repaired call needs an id to repair"
    # The poller path is the one with NO webhook payload behind it, so this is the only
    # place the agent ref can come from. Without it a reconciled call resolves to no
    # tenant and the repair quietly does nothing.
    assert all(r.engine_agent_ref for r in rows), "a polled snapshot must be mappable"
    # A handful of executions is not a page. An adapter that reports THIS as possibly
    # truncated has a heuristic that fires on every healthy tick, which trains the
    # operator to ignore the one signal that says calls are being lost.
    assert listing.complete, "a short window must be reported as complete"
    assert listing.incomplete_reason is None
    assert listing.pages_fetched >= 1


async def test_a_full_listing_page_tells_the_caller_it_may_be_truncated(
    saturated_engine: VoiceEngine,
) -> None:
    """THE CLAUSE THE POLLER'S ENTIRE GUARANTEE RESTS ON (D-31).

    Bolna's webhooks are at-most-once and unsigned, so the List-Executions poller is not
    a safety net — it is the mechanism by which a lost call is EVER discovered. If the
    listing paginates and an adapter reads page one, the executions past that page have
    no webhook, no repair, and nothing anywhere that says they existed: they are simply
    gone, and the gap grows exactly when traffic does.

    So an adapter may not return a page-shaped answer as if it were the whole window. It
    does not have to know it was truncated — Bolna publishes no pagination contract and
    the honest answer is often "cannot rule it out" — it has to SAY so, in
    `ExecutionListing.complete`, with a reason the poller can put in an alert.

    Note what is NOT asserted: any cursor, page number or link. Those are the adapter's
    business (hard rule 2); what crosses the boundary is the verdict and the rows.
    """
    listing = await saturated_engine.list_executions(since=datetime.now(UTC) - timedelta(hours=1))

    assert listing.snapshots, "a truncated listing still returns the rows it did get"
    assert not listing.complete, (
        "a full page was returned as if it were the whole window — every execution past "
        "it is a call whose webhook was lost and which nothing will ever mention again"
    )
    assert listing.incomplete_reason is not None, "the poller alerts on the REASON"


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
    if not engine.capabilities.knowledge_base:
        return  # covered instead by the refusal clause for KB-less engines
    ref = await engine.create_agent(_agent_config(engine))
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
    if not engine.capabilities.knowledge_base:
        return  # covered instead by the refusal clause for KB-less engines
    ref = await engine.create_agent(_agent_config(engine))
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
    if not engine.capabilities.knowledge_base:
        return  # covered instead by the refusal clause for KB-less engines
    ref = await engine.create_agent(_agent_config(engine))
    reported: Exception | None = None
    try:
        await engine.detach_kb(ref, "kb_this_engine_never_issued")
    except Exception as exc:  # adapters raise our ProblemError; the type is theirs
        reported = exc
    assert reported is not None, (
        "detaching a handle this engine never issued was reported as a success — "
        "the caller cannot distinguish a removal from a silent no-op"
    )


# =============================================================================
# The capability descriptor (D-93)
#
# Everything above this line tests behaviour the contract requires of EVERY adapter.
# Everything below tests the adapter's own DECLARATION about itself — because a
# descriptor an adapter can lie in is worse than no descriptor at all. Without these
# clauses a wrong `EngineCapabilities` converts a runtime failure ("the call failed")
# into a confident wrong answer ("the platform supports this"), and a confident wrong
# answer is what a screen renders a button from.
#
# The rule each clause below implements: a capability that is CLAIMED is exercised, and
# a capability that is DENIED must produce a refusal rather than a success.
# =============================================================================


async def test_the_adapter_declares_a_complete_capability_descriptor(
    engine: VoiceEngine,
) -> None:
    """Every adapter answers every question — there is no "unset".

    `EngineCapabilities` deliberately gives no field a default, so this cannot fail by
    omission at construction time. What it CAN still fail is an adapter that never
    declares one at all, or declares it on the class while the Protocol says instance —
    both of which end with a caller reading capabilities off the wrong object.
    """
    caps = engine.capabilities
    assert isinstance(caps, EngineCapabilities)
    for leg in ("stt", "llm", "tts"):
        assert caps.speech_control(leg) in ("ours", "engine")
    assert caps.number_series <= set(NUMBER_SERIES_VALUES), (
        "a number class outside our own vocabulary would never match the campaign "
        "launch gate, which compares against exactly these three"
    )


async def test_the_declared_webhook_method_is_the_one_actually_reported(
    engine: VoiceEngine,
) -> None:
    """`capabilities.webhook_auth` and `verify_webhook().method` are one fact.

    They are read by different services. The adapter's verdict is what the WORKER acts
    on; the declaration is what the RECEIVER acts on, via `WEBHOOK_AUTH_BY_ENGINE` —
    `apps/voice-runtime` cannot import an adapter (hard rule 3 forbids the heavy import
    on the ack path), so it reads the table instead. If those two answers can differ,
    the receiver authenticates a delivery one way while the adapter reports another, and
    the disagreement surfaces as calls silently rejected at the edge — the one failure
    mode an at-most-once, unsigned vendor gives you no second chance to notice.
    """
    declared = engine.capabilities.webhook_auth
    reported = engine.verify_webhook({}, b"{}", ALLOWLISTED_SOURCE_IP).method
    assert declared == reported, (
        f"this adapter declares `{declared}` webhook authentication and reports "
        f"`{reported}` — the receiver and the worker would disagree about the same event"
    )
    assert WEBHOOK_AUTH_BY_ENGINE.get(engine.name) == declared, (
        f"`WEBHOOK_AUTH_BY_ENGINE[{engine.name!r}]` disagrees with the adapter's own "
        "declaration, and the voice-runtime receiver reads the table, not the adapter"
    )


async def test_a_byok_speech_leg_is_accepted_and_a_dictated_one_is_refused_by_name(
    engine: VoiceEngine,
) -> None:
    """THE CLAUSE THE TTS QUESTION RESTS ON.

    An engine that supplies its own voices implements exactly the same Protocol as one
    that speaks ours. The difference shows up only in what happens to
    `ModelConfig.tts_voice`, and there are two possible answers:

    * it reaches the engine and the caller hears it — `ours`; or
    * it is DROPPED, the publish succeeds, and the caller hears the engine's own voice
      while every screen keeps reporting the voice that was chosen.

    The second is not a lesser version of the first, it is the failure this descriptor
    exists to remove, and it is undetectable from above: nothing 500s, nothing logs, the
    row saves. So a dictated leg must REFUSE the value, by a name an operator can act
    on, and this clause is what stops an adapter declaring `engine` and quietly
    accepting anyway.
    """
    caps = engine.capabilities
    for leg, field, value in (
        ("stt", "stt_model", "saaras:v3"),
        ("llm", "llm_model", "sarvam-105b"),
        ("tts", "tts_voice", "bulbul:v3"),
    ):
        cfg = _agent_config(
            engine,
            name=f"Capability probe {leg}",
            agent_id=f"0199a0b0-0000-7000-8000-0000000000c{'stl'.index(leg[0])}",
        )
        probed = cfg.model_copy(update={"models": cfg.models.model_copy(update={field: value})})
        if caps.is_ours(leg):  # type: ignore[arg-type]
            # Claimed ours: the adapter must take it. An adapter that refuses a leg it
            # advertises is the same defect from the other side — a control the console
            # correctly offers and the route rejects.
            await engine.create_agent(probed)
            continue
        refusal: Exception | None = None
        try:
            await engine.create_agent(probed)
        except Exception as exc:  # adapters raise our ProblemError; the type is theirs
            refusal = exc
        assert refusal is not None, (
            f"this adapter declares that the ENGINE dictates `{leg}` and accepted our "
            f"`{field}` anyway — the selection is silently dropped, so an operator picks "
            "a voice, the publish succeeds, and the caller hears something else"
        )
        assert getattr(refusal, "capability", None) == leg, (
            f"the refusal for `{leg}` does not name the capability it refused, so an "
            "operator reading it cannot tell which control to stop offering"
        )


async def test_a_byok_leg_that_can_be_read_back_holds_what_we_sent(
    engine: VoiceEngine,
) -> None:
    """The BYOK claim, checked against the engine's own state where that is possible.

    The clause above proves the value was ACCEPTED. This one asks the harder question —
    is the engine RUNNING it? — and it is the same ACCEPTED-versus-APPLIED distinction
    `test_agent_read_back_reports_the_agent_it_was_asked_about` makes for the prompt,
    applied to the setting that decides what a caller actually hears.

    **AN ADAPTER THAT CLAIMS A LEG IS OURS MUST BE ABLE TO READ THAT LEG BACK**, and
    that is stricter than the `knowledge_base_refs_readable` tri-state on purpose. This
    clause was written the weaker way first — `models_readable=False` excused everything —
    and a deliberate sabotage walked straight through it: an adapter declaring BYOK TTS
    on an engine that dictates its voices, silently dropping our voice, and declining to
    report what it holds, passed every clause in this suite. That is precisely the
    "confident wrong answer" the descriptor is supposed to make impossible.

    Why the stricter rule is fair, where the KB one is not: a vendor may genuinely have no
    field for "which knowledge base does this agent reference" — D-41 exists because
    nobody can say whether Bolna's agent object carries one. But a vendor that lets us
    CHOOSE a model or a voice necessarily holds that choice; it is the agent's
    configuration. So "we set it and cannot see it" is a claim about our adapter's reading,
    not about the vendor's model, and BYOK asserted on faith is exactly what a caller must
    not be able to hear the consequences of on a live line.

    An adapter with no BYOK leg at all is exempt: there is nothing of ours to read back.
    """
    cfg = _agent_config(
        engine, name="Speech read-back", agent_id="0199a0b0-0000-7000-8000-0000000000d0"
    )
    ref = await engine.create_agent(cfg)
    snapshot = await engine.get_agent(ref)
    ours = [leg for leg in ("stt", "llm", "tts") if engine.capabilities.is_ours(leg)]

    if not ours:
        assert snapshot.holds_speech("tts") is None, (
            "this engine dictates every speech leg and the adapter reported a selection "
            "of ours anyway — it would read exactly like an applied BYOK choice"
        )
        return

    assert snapshot.models_readable, (
        f"this adapter claims BYOK on {ours} and cannot read any of it back, so 'is the "
        "engine running the model we chose?' is unanswerable — and an adapter that "
        "silently dropped the selection would be indistinguishable from this one"
    )

    for leg, sent in (
        ("stt", cfg.models.stt_model),
        ("llm", cfg.models.llm_model),
        ("tts", cfg.models.tts_voice),
    ):
        held = snapshot.holds_speech(leg)  # type: ignore[arg-type]
        if not engine.capabilities.is_ours(leg):  # type: ignore[arg-type]
            assert held is None, (
                f"`{leg}` is the engine's to dictate, so there is no selection of ours "
                "to report — reporting one would read exactly like an applied choice"
            )
            continue
        assert held == sent, (
            f"we configured `{leg}` as {sent!r} and the engine holds {held!r} — the "
            "write was accepted and not applied, and nothing downstream could see it"
        )


async def test_an_engine_without_a_knowledge_base_refuses_all_three_kb_methods(
    engine: VoiceEngine,
) -> None:
    """`knowledge_base=False` must mean a refusal, never an empty success.

    `list_kb` is the dangerous one and the reason this clause names all three. An empty
    list is a POSITIVE claim that the agent holds no documents, and
    `kb/service._reconcile_engine_state` reads exactly that claim to decide whether the
    engine is serving text our rows cannot account for. An engine with no knowledge base
    answering `[]` is therefore not merely unhelpful — it tells the publish path that
    everything is accounted for, every single time, which is the strongest possible
    "carry on" from a component that was never asked the question.
    """
    if engine.capabilities.knowledge_base:
        return
    ref = await engine.create_agent(_agent_config(engine))
    source = KBSourceRef(kb_id="kb_absent", title="Fees", text="A consultation costs 500.")
    for label, call in (
        ("attach_kb", lambda: engine.attach_kb(ref, source)),
        ("detach_kb", lambda: engine.detach_kb(ref, "kb_anything")),
        ("list_kb", lambda: engine.list_kb(ref)),
    ):
        refusal: Exception | None = None
        try:
            await call()
        except Exception as exc:
            refusal = exc
        assert refusal is not None, (
            f"`{label}` succeeded on an engine that declares no knowledge base — the "
            "publish path would record knowledge as live that no engine is serving"
        )
        assert getattr(refusal, "capability", None) == "knowledge_base", (
            f"`{label}` refused without naming the capability, so an operator cannot "
            "tell an absent knowledge base from a knowledge base that is down"
        )


async def test_transfer_matches_the_declaration_either_way(engine: VoiceEngine) -> None:
    """A transfer that silently does nothing is a caller left on hold forever.

    Both directions are asserted because both have been wrong here at once: the `fake`
    adapter used to record a successful transfer while the Bolna adapter raised, so the
    two shipped adapters disagreed about whether the platform can transfer a call and
    nothing in the suite could see it. That is the single clearest piece of evidence
    that declarations needed to be checkable.
    """
    ref = await engine.create_agent(_agent_config(engine))
    handle = await engine.start_outbound_call(ref, "+919876543210", CallContext())
    refusal: Exception | None = None
    try:
        await engine.transfer(handle, "+919000000000", warm=False)
    except Exception as exc:
        refusal = exc

    if engine.capabilities.transfer:
        assert refusal is None, (
            "this adapter advertises engine-side transfer and refused one — an escalation "
            f"path the console offers is not there: {refusal!r}"
        )
        # THE OTHER HALF, without which the claim is unfalsifiable. `transfer` returns
        # nothing and the Protocol offers no read-back, so "it worked" and "it did
        # nothing at all" are the same observation — and the second leaves a caller in
        # silence while the console reports an escalation. An adapter that can really
        # transfer can therefore be required to FAIL one: a call this engine does not
        # hold. Exactly the shape `test_a_claimed_verification_method_actually_rejects_
        # somebody` uses for webhook methods, and the reason `detach_kb` may not swallow
        # an unknown handle.
        unknown: Exception | None = None
        try:
            await engine.transfer("call_this_engine_never_placed", "+919000000000", warm=False)
        except Exception as exc:
            unknown = exc
        assert unknown is not None, (
            "this adapter accepted a transfer for a call the engine does not hold, so "
            "nothing it does on this method can be distinguished from doing nothing"
        )
        return
    assert refusal is not None, (
        "this adapter declares no engine-side transfer and accepted one anyway; the "
        "caller is transferred nowhere and nothing reports it"
    )
    assert getattr(refusal, "capability", None) == "transfer", (
        "the refusal does not name `transfer`, so the console cannot tell it apart from "
        "a transient engine failure and will offer the control again"
    )


async def test_number_provisioning_matches_the_declared_series(engine: VoiceEngine) -> None:
    """Per SERIES, because the campaign launch gate matches on the series.

    140 and 160 are Indian DLT classes (promotional versus service). An engine that can
    sell an ordinary number and has no Indian telephony path can satisfy a `numbers`
    boolean and still be unable to provide the only two classes an outbound campaign is
    allowed to dial from — so a single boolean here would let a launch gate pass on a
    number that does not exist.
    """
    caps = engine.capabilities
    for series in NUMBER_SERIES_VALUES:
        outcome: Exception | ProvisionedNumber
        try:
            outcome = await engine.provision_number(NumberSpec(series=series, purpose="probe"))
        except Exception as exc:
            outcome = exc
        if caps.provisions(series):
            assert isinstance(outcome, ProvisionedNumber), (
                f"this adapter advertises the {series} series and could not provide one"
            )
            assert outcome.series == series, (
                f"asked for a {series} number and got a {outcome.series} one — the "
                "campaign launch gate compares this field against the campaign's class"
            )
            assert outcome.e164.startswith("+"), "E.164 only"
            continue
        assert isinstance(outcome, Exception), (
            f"this adapter declares it cannot provision the {series} series and returned "
            "a number anyway, which would be recorded as dialable"
        )


async def test_an_engine_side_campaign_object_is_not_claimable_yet(
    engine: VoiceEngine,
) -> None:
    """The one capability with NO method behind it, and therefore no way to lie safely.

    Every other field in the descriptor is checkable because the Protocol has a method
    that must behave accordingly. `campaigns` has none: our campaigns are dispatched
    entirely by `apps/api/campaigns` and `apps/workers`, through the compliance gate, and
    nothing in this system asks an engine to hold a campaign object. So a `True` here
    could never be contradicted by any behaviour — it would be exactly the unfalsifiable
    claim this section exists to prevent, sitting in the same object as six claims that
    are enforced, borrowing their credibility.

    The clause therefore refuses the claim outright rather than pretending to test it.
    The day an engine's campaign objects are actually used, this stops being a lie
    detector and becomes a TODO with a name: the Protocol grows the campaign methods
    first, and this clause is rewritten to exercise them. Failing here is the intended
    way to find that out.
    """
    assert engine.capabilities.campaigns is False, (
        "this adapter claims engine-side campaign objects, but `VoiceEngine` has no "
        "campaign method for the suite to check the claim against — add the methods to "
        "the Protocol and rewrite this clause before declaring the capability"
    )
