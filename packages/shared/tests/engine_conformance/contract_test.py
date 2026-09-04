"""The VoiceEngine conformance suite (TRD §5) — run against EVERY adapter.

What this suite is for: the exit door. If a rented engine fails us (R-02) the cost of
leaving must be one new adapter, not a rewrite — and that is only true if every
adapter is held to identical, checkable behaviour. Each test below encodes one clause
of the contract, and the docstring says which promise would break without it.

Run: `make conformance` (or `uv run pytest -m conformance`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypedDict, Unpack

import httpx
import pytest
from calevate_shared.engine import (
    DECLARED_POSTURE,
    TRUTHFUL_ANSWER_MARKER,
    WEBHOOK_AUTH_BY_ENGINE,
    AgentConfig,
    AgentHosting,
    AvailableNumber,
    CallContext,
    CostBreakdown,
    EngineCapabilities,
    ExecutionSnapshot,
    HandoffSpec,
    KBSourceRef,
    ModelConfig,
    NumberSearch,
    NumberSeries,
    NumberSpec,
    PostureLeg,
    ProvisionedNumber,
    RecallOutcome,
    VoiceEngine,
    azure_openai_base_url,
    compose_engine_prompt,
    openai_base_url,
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
        # THE MODEL AND THE SPEAKER, in the two fields the vendor reads them from (D-358).
        # `tts_voice` used to carry `bulbul:v3` — a MODEL in the speaker's field — which is
        # what let an adapter pasting one string into the vendor's `voice` key pass this
        # suite. Naming the speaker separately is what makes a dropped model detectable.
        tts_model="bulbul:v3" if caps.is_ours("tts") else None,
        tts_voice="anushka" if caps.is_ours("tts") else None,
    )


def _agent_config(
    engine: VoiceEngine,
    *,
    name: str = "Sunrise Clinic receptionist",
    agent_id: str = "0199a0b0-0000-7000-8000-000000000002",
    system_prompt: str = "You are the receptionist for Sunrise Clinic.",
    opening_line: str = "Idi AI assistant. Ee call record avutundi.",
    handoff: HandoffSpec | None = None,
) -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id=agent_id,
        name=name,
        direction="inbound",
        language_primary="te-IN",
        system_prompt=system_prompt,
        opening_line=opening_line,
        models=_byok_models(engine),
        webhook_url="https://hooks.calevate.tech/v1/engine/bolna",
        handoff=handoff,
    )


#: The one person on duty, as a publish carries them (D-533). A number OUTSIDE every other
#: fixture in this file, so a clause that finds it in a read-back found it because the
#: publish carried it and not because something else in the suite put it there.
HANDOFF = HandoffSpec(
    destination_e164="+919000000042",
    trigger="Hand over when the caller asks to speak to a person.",
    spoken_line="Okay, I am putting you through to someone now.",
    brief_url="https://hooks.calevate.tech/tools/v1/bolna/handoff",
)


#: Every hosting shape an engine may declare, DERIVED FROM THE TYPE rather than retyped —
#: the `NUMBER_SERIES_VALUES` argument, and the reason a third shape cannot be added to the
#: port without the roster clause below noticing that nothing exercises it.
AGENT_HOSTING_VALUES: tuple[AgentHosting, ...] = AgentHosting.__args__  # type: ignore[attr-defined]

#: The ref of an agent an EXTERNALLY-DEPLOYED engine already holds.
#:
#: On that shape an account HAS agents whether or not our API client made them — they are
#: programs deployed from a repository — so a clause that needs a ref cannot get one from
#: `create_agent`, which refuses. Both subjects of this shape answer about this ref: the
#: Cartesia stub seeds it (`_cartesia_handler`), and `FakeEngine`'s call and knowledge-base
#: methods are keyed on whatever ref they are given.
DEPLOYED_AGENT_REF = "agent_deployed"


async def _agent_ref(engine: VoiceEngine, cfg: AgentConfig | None = None) -> str:
    """A ref this engine will answer about — created where it hosts agents, adopted where
    it does not.

    THE SPLIT IS READ OFF THE CAPABILITY, never off a name, so a third vendor joining the
    roster lands on the right side of it without anybody remembering to add a branch —
    the property `http_speaking_engine_ids` gets from deriving by TYPE.
    """
    if not engine.capabilities.hosts_agents():
        return DEPLOYED_AGENT_REF
    return await engine.create_agent(cfg if cfg is not None else _agent_config(engine))


class _DialFields(TypedDict, total=False):
    """The per-call scalars a conformance case may vary, and NOTHING ELSE.

    **`**fields: str` COLLIDED WITH `CallContext.fields`, WHICH IS ITSELF A `dict[str,
    str]`.** Splatting a `dict[str, str]` into a model that HAS a member called `fields`
    is unsound and mypy said so the moment `init_typed = true` made Pydantic constructors
    checkable: one key named `fields` would arrive as a `str` where a mapping belongs, and
    before that flag was set nothing anywhere would have caught it.

    Typed this way (PEP 692) the helper's contract is stated rather than implied: these
    three are `CallContext`'s scalar prompt inputs, `total=False` because every case sets a
    different subset, and a typo like `lead_nmae=` is now an error at the call site instead
    of a silently-dropped kwarg that leaves the assertion passing against an empty context.
    """

    lead_id: str
    lead_name: str
    context_note: str


def _dial_context(
    engine: VoiceEngine, cfg: AgentConfig, **fields: Unpack[_DialFields]
) -> CallContext:
    """The context `dispatch_call` would build for THIS engine.

    The suite must not hand every adapter the same context: on a `control_plane` engine the
    prompt is agent-record state and a per-call copy would be a second authority for one
    string, while on an `external_deployment` engine it is the only place hard rule 5 can
    live and a dial without it must be refused. `agents/service._call_prompt_for` makes
    exactly this decision in production, from the same capability, and a fixture that made
    it differently would be testing a system we do not run.
    """
    prompt = None if engine.capabilities.hosts_agents() else compose_engine_prompt(cfg)
    return CallContext(system_prompt=prompt, **fields)


async def _place_call(engine: VoiceEngine, *, to: str = "+919876543210") -> str | None:
    """Dial once through whichever shape this engine is, or None if it refuses by name.

    `cartesia` is the refusing case and it is not a failure: its outbound body has no field
    a prompt could ride in, so it declines every dial rather than placing one with no
    truthful-answer rule on it (D-282). A clause that needs a placed call has nothing to
    measure there and says so by skipping, rather than by asserting something weaker.
    """
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    try:
        return await engine.start_outbound_call(ref, to, _dial_context(engine, cfg))
    except Exception as exc:
        assert _refusal(exc)[0] == "engine_compliance_floor_absent", (
            f"this adapter refused a dial for a reason other than the compliance floor: {exc!r}"
        )
        return None


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
    if not engine.capabilities.hosts_agents():
        # This engine's agents are deployed to it from elsewhere: there is no agent record
        # to create, configure or read back, and all three methods refuse by name. The
        # clause that measures that refusal — and the alternative home hard rule 5 gets
        # instead — is `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`.
        return
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
    if not engine.capabilities.hosts_agents():
        # This engine's agents are deployed to it from elsewhere: there is no agent record
        # to create, configure or read back, and all three methods refuse by name. The
        # clause that measures that refusal — and the alternative home hard rule 5 gets
        # instead — is `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`.
        return
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


async def test_a_read_back_carries_the_opening_line_the_engine_was_given(
    engine: VoiceEngine,
) -> None:
    """HARD RULE 5, SCORED ON THE ENGINE RATHER THAN ON OUR REQUEST BODY.

    Every adapter PREPENDS `opening_line` to the prompt so it is spoken first. That is
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
    if not engine.capabilities.hosts_agents():
        # This engine's agents are deployed to it from elsewhere: there is no agent record
        # to create, configure or read back, and all three methods refuse by name. The
        # clause that measures that refusal — and the alternative home hard rule 5 gets
        # instead — is `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`.
        return
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
    assert snapshot.carries_prompt_marker(cfg.opening_line) is True, (
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
    assert snapshot.carries_greeting_marker(cfg.opening_line) is True, (
        "the greeting the engine holds does not contain the disclosure line, so the "
        "first thing this agent says to a caller is not the thing SEC-COMP §1 requires"
    )


async def test_every_adapter_puts_the_truthful_answer_rule_on_the_engine(
    engine: VoiceEngine,
) -> None:
    """HARD RULE 5's UNFALSIFIABLE HALF, ON EVERY ADAPTER (D-163).

    The two opening notices are per-agent toggles. The ANSWER a caller gets when they ask
    outright — "am I talking to a person?", "is this recorded?" — is not, and this is the
    clause that makes "not toggleable" true of an ADAPTER rather than only of our own
    layer. `compose_engine_prompt` is one function in the contract, so an adapter that
    builds its prompt by hand is the one way the directive could go missing on one engine
    and nowhere else; a suite that only exercised the fake would never see it.

    THE MARKER, NOT THE WHOLE BLOCK, for `carries_prompt_marker`'s reason: any rendering
    that kept the text satisfies the rule, and requiring the block verbatim would fail on
    a vendor that re-wraps long strings.

    A failure here is not cosmetic. `agents/verification.judge` scores this same marker on
    every publish and REFUSES one whose engine copy has lost it, so an adapter that drops
    it does not merely go unmeasured — it fails every publish closed on that engine, for
    the whole deployment. Which is the right direction, and exactly why it must be caught
    here rather than by a client on the phone.
    """
    if not engine.capabilities.hosts_agents():
        # This engine's agents are deployed to it from elsewhere: there is no agent record
        # to create, configure or read back, and all three methods refuse by name. The
        # clause that measures that refusal — and the alternative home hard rule 5 gets
        # instead — is `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`.
        return
    cfg = _agent_config(
        engine,
        agent_id="0199a0b0-0000-7000-8000-00000000001d",
        system_prompt="Receptionist. marker-truthful",
    )
    ref = await engine.create_agent(cfg)
    snapshot = await engine.get_agent(ref)

    assert snapshot.system_prompt_readable, (
        "the prompt could not be read back, so the one rule a client may not switch off "
        "is unverifiable on this engine"
    )
    assert snapshot.carries_prompt_marker(TRUTHFUL_ANSWER_MARKER) is True, (
        "the engine is not holding the truthful-answer rule. Either the adapter built "
        "its prompt without `compose_engine_prompt`, or the vendor truncated the tail of "
        "the prompt — where the rule deliberately sits. Both mean this agent can be "
        "scripted into claiming it is human"
    )


async def test_an_agent_with_no_opening_notice_still_carries_the_truthful_answer_rule(
    engine: VoiceEngine,
) -> None:
    """The whole point of D-163, stated as a property of every adapter.

    A tenant who switches both notices off gets an EMPTY `opening_line`: no greeting, and
    nothing prepended to the prompt. The rule that makes the agent answer honestly when
    ASKED must be untouched by that — it is composed from a `Final` constant and not from
    the config at all — and the greeting must actually be CLEARED rather than left
    holding whatever the vendor had before, which is what `verification._greeting_verdict`
    scores in the negative.
    """
    if not engine.capabilities.hosts_agents():
        # This engine's agents are deployed to it from elsewhere: there is no agent record
        # to create, configure or read back, and all three methods refuse by name. The
        # clause that measures that refusal — and the alternative home hard rule 5 gets
        # instead — is `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`.
        return
    cfg = _agent_config(
        engine,
        agent_id="0199a0b0-0000-7000-8000-00000000001e",
        system_prompt="Receptionist. marker-silent",
        opening_line="",
    )
    ref = await engine.create_agent(cfg)
    snapshot = await engine.get_agent(ref)

    assert snapshot.carries_prompt_marker(TRUTHFUL_ANSWER_MARKER) is True, (
        "an agent that volunteers no notice lost the truthful-answer rule as well — "
        "switching off what the agent SAYS FIRST must never change what it ANSWERS"
    )
    assert not (snapshot.greeting or "").strip(), (
        "the engine is still holding a greeting for an agent whose owner withdrew both "
        "notices, so every call still opens with a notice our own row says is off"
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


async def test_reading_an_execution_the_engine_never_placed_is_reported(
    engine: VoiceEngine,
) -> None:
    """The same clause as `get_agent`'s, one method along — and it was missing while the
    two adapters actively disagreed (P2.6).

    `BolnaEngine` 404s, which `_request` turns into `engine_rejected`. `FakeEngine`
    fabricated a `status="failed"` snapshot, under a comment claiming it matched the real
    thing. That answer is worse than an error precisely because it is well-formed: it is
    indistinguishable from a real failed call, so the poller would record a repair for a
    phantom execution and `_pipeline_settled` would reason about artefacts for a call the
    engine has never heard of. Both are conclusions drawn from nothing that look like
    measurements.
    """
    reported: Exception | None = None
    try:
        await engine.get_execution("exec_this_engine_never_placed")
    except Exception as exc:  # adapters raise our ProblemError; the type is theirs
        reported = exc
    assert reported is not None, (
        "reading back an execution the engine never placed returned a snapshot — a "
        "caller cannot tell it from a call that really happened and really failed"
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
    if not engine.capabilities.hosts_agents():
        # This engine's agents are deployed to it from elsewhere: there is no agent record
        # to create, configure or read back, and all three methods refuse by name. The
        # clause that measures that refusal — and the alternative home hard rule 5 gets
        # instead — is `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`.
        return
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
    if not engine.capabilities.hosts_agents():
        # D-41's OTHER precondition: the question is "does the AGENT still reference the
        # handle", and an engine that holds no agent record of ours has no object to ask.
        # `get_agent` refuses by name there rather than answering `readable=False`.
        return
    cfg = _agent_config(engine)
    ref = await engine.create_agent(cfg)
    handle = await engine.attach_kb(
        ref, _kb_source("kb_readback", "Fees", "A consultation costs 500."), agent=cfg
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
    await engine.detach_kb(ref, handle, agent=cfg)
    after = await engine.get_agent(ref)
    assert after.references_kb(handle) is False, (
        "the agent still references the detached knowledge base (D-41): `detach_kb` is a "
        "delete PLUS an agent update on this engine, and publish must do both"
    )


async def test_outbound_call_returns_a_handle(engine: VoiceEngine) -> None:
    """A dial that IS placed answers with a handle, and the context reaches it.

    An adapter that refuses to dial at all is not a failure of this clause — it is
    `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`'s subject, and the
    refusal it must give is asserted there by name. What this clause forbids is the third
    outcome: a dial that neither places a call nor says why.
    """
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    try:
        handle = await engine.start_outbound_call(
            ref,
            "+919876543210",
            _dial_context(engine, cfg, lead_name="Ravi", context_note="Called about the 6pm slot"),
        )
    except Exception as exc:
        assert _refusal(exc)[0] == "engine_compliance_floor_absent", (
            f"this adapter neither placed the call nor named the compliance floor: {exc!r}"
        )
        return
    assert isinstance(handle, str) and handle


async def test_ending_a_call_the_engine_does_not_hold_is_reported(
    engine: VoiceEngine,
) -> None:
    """`end_call` had NO clause at all, and the adapters disagreed underneath it (D-187).

    Both real adapters POST to the vendor — `/executions/{id}/stop` on Bolna,
    `/agents/calls/{id}/end` on Cartesia — and surface the 404 as `engine_rejected`.
    `FakeEngine` looked the id up, found nothing and returned None, so the whole pipeline
    running offline (DEV-SETUP §3) reported a hang-up that never happened. Same shape as
    the `get_execution` divergence P2.6 found and the `transfer` one D-93 found, on the
    one method with no clause to catch it.

    A CONTROL-PLANE HANG-UP HAS EXACTLY ONE OBSERVABLE FAILURE: saying it worked. The
    caller is an operator or a cost guard stopping a live call, and a silent no-op puts
    "call ended" on a screen while the caller is still connected and the minutes are
    still being billed. Deliberately NOT `delete_agent`'s idempotent answer — that
    method's caller is a compensation path whose postcondition an absent object already
    satisfies; this one's is not.
    """
    reported: Exception | None = None
    try:
        await engine.end_call("call_this_engine_is_not_running")
    except Exception as exc:  # adapters raise our ProblemError; the type is theirs
        reported = exc
    assert reported is not None, (
        "ending a call the engine does not hold passed quietly — the one failure this "
        "method has is claiming to have stopped a call it did not stop"
    )


async def test_a_stop_says_what_it_caught_and_never_overclaims(engine: VoiceEngine) -> None:
    """The verdict `end_call` returns is a COMPLIANCE claim, so its floor is honesty.

    A DNC suppression may later have to answer "prove this number was not called", and
    `RecallOutcome.PREVENTED` is the only value anything is allowed to record that on. So
    the clause every adapter must meet is not "return PREVENTED" — Cartesia's stop route
    is inferred and cannot know, and answers `UNKNOWN` on purpose — it is that whatever
    comes back is a member of the vocabulary, so a caller can branch on it without
    guessing, and that a stop of a REAL dial never raises.

    Deliberately not asserting WHICH value: that is the adapter's to decide from what its
    vendor said, and a conformance suite demanding `PREVENTED` would force exactly the
    unearned claim this return value exists to stop.
    """
    handle = await _place_call(engine)
    if handle is None:
        # `cartesia` refuses every dial by name (see `_place_call`), so there is no real
        # execution here to stop. Skipping is the honest answer; stopping a fabricated id
        # would measure the D-187 clause above a second time instead of this one.
        pytest.skip("this adapter places no dial, so it holds nothing to stop")
    outcome = await engine.end_call(handle)
    assert isinstance(outcome, RecallOutcome), (
        f"{engine.name} answered {outcome!r}, which no caller can branch on; the DNC "
        "recall reads this to decide whether a number may be recorded as not called"
    )


async def test_execution_snapshot_is_fully_normalized(engine: VoiceEngine) -> None:
    """The isolation boundary (hard rule 2): whatever the vendor sends, what comes out
    is OUR shape, OUR status vocabulary and OUR currency."""
    handle = await _place_call(engine)
    if handle is None:
        return  # this adapter refuses to dial at all — see `_place_call`
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
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    try:
        first = await engine.start_outbound_call(
            ref, "+919876543210", _dial_context(engine, cfg, lead_id="lead-1")
        )
    except Exception as exc:
        assert _refusal(exc)[0] == "engine_compliance_floor_absent", repr(exc)
        return  # this adapter refuses to dial at all — see `_place_call`
    second = await engine.start_outbound_call(
        ref, "+919876543211", _dial_context(engine, cfg, lead_id="lead-2")
    )
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
    handle = await _place_call(engine)
    if handle is None:
        return  # this adapter refuses to dial at all — see `_place_call`
    snapshot = await engine.get_execution(handle)
    if snapshot.billable_ready:
        assert snapshot.terminal
        assert snapshot.status in TERMINAL_STATUSES


async def test_transcript_turns_are_ordered_and_speaker_tagged(engine: VoiceEngine) -> None:
    """Extraction, redaction and the call-detail view all index by `idx` and switch on
    `speaker`; a gap or a vendor speaker label leaking through breaks all three."""
    handle = await _place_call(engine)
    if handle is None:
        return  # this adapter refuses to dial at all — see `_place_call`
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
    await _place_call(engine)
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

    Bolna's webhooks are unsigned and lossy, so the executions poller is not a safety net
    — it is the mechanism by which a lost call is EVER discovered. If the listing
    paginates and an adapter reads page one, the executions past that page have no
    webhook, no repair, and nothing anywhere that says they existed: they are simply gone,
    and the gap grows exactly when traffic does.

    So an adapter may not return a page-shaped answer as if it were the whole window. It
    does not have to know it was truncated — some vendors publish no pagination contract
    and the honest answer is then "cannot rule it out" — it has to SAY so, in
    `ExecutionListing.complete`, with a reason the poller can put in an alert. (Bolna DOES
    publish one, `page_number`/`page_size`/`has_more`, which is why its saturated stub is
    now a store the adapter walks to its own page cap rather than a single opaque full
    page — D-350/D-353.)

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


#: The smallest thing that is unambiguously a PDF. The conformance stub asserts the file
#: part starts with it, which is what stops an adapter passing the KB clauses while
#: uploading the approved TEXT — the exact body shape D-354 found on the wire.
#:
#: Rendering a real one here would put a document format in the conformance suite, which
#: is the sibling module's job and nobody else's. What this fixture stands for is "the
#: publisher handed us bytes", and the bytes only have to be recognisable.
_STUB_PDF = b"%PDF-1.4\n% conformance fixture, not a rendering\n%%EOF\n"


def _kb_source(kb_id: str, title: str, text: str, *, language: str = "te-IN") -> KBSourceRef:
    """One approved source as the publisher hands it over: text AND a rendered document.

    Both, always. An engine that ingests text reads `text`; one that ingests files reads
    `document`; and a clause that supplied only one of them would silently exempt half
    the adapters from the half of the contract that applies to them.
    """
    return KBSourceRef(
        kb_id=kb_id,
        title=title,
        text=text,
        language=language,
        document=_STUB_PDF,
        content_sha256=hashlib.sha256(_STUB_PDF).hexdigest(),
    )


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
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    handle = await engine.attach_kb(
        ref, _kb_source("kb_1", "Clinic hours", "Mon-Sat 9am-8pm"), agent=cfg
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
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    superseded = await engine.attach_kb(
        ref, _kb_source("kb_detach_v1", "Fees", "A consultation costs 500."), agent=cfg
    )
    kept = await engine.attach_kb(
        ref, _kb_source("kb_detach_other", "Parking", "Parking is free."), agent=cfg
    )
    assert superseded != kept, "two sources must not share one handle — one cannot be removed"
    assert {superseded, kept} <= set(await engine.list_kb(ref)), (
        "an attached source must be visible to `list_kb`, or a detach can never be proven"
    )

    await engine.detach_kb(ref, superseded, agent=cfg)

    remaining = await engine.list_kb(ref)
    assert superseded not in remaining, (
        "`detach_kb` returned without removing anything — the superseded version is "
        "still what the agent answers from"
    )
    assert kept in remaining, "detach removed a source it was not asked to remove"


async def test_the_account_listing_sees_what_no_agent_references(
    engine: VoiceEngine,
) -> None:
    """`list_account_kb` must see an object `list_kb` cannot — that is its whole job.

    D-519. Every failure this feature can suffer leaves the same residue: an object the
    ACCOUNT holds that no agent references — a create whose response was lost, a crash
    between the upload and the agent write, a COMMIT that failed after a successful
    attach, a cleanup that itself failed, an agent deleted while it still referenced
    knowledge. `list_kb` reads the AGENT, so every one of those is invisible to it, and
    an adapter that answered this method from the agent's own references would pass every
    other clause in this file while making the orphan report structurally incapable of
    finding anything.

    Staged with the one such state a conformance test can produce without breaking the
    transport: an agent is deleted while it still holds an attached document. WHAT
    HAPPENS TO THE VENDOR'S OBJECT THEN IS UNKNOWN on the primary engine and is
    OPERATIONS §2 gate 43f, so this clause asserts NEITHER branch — it asserts the
    property that is true under both: whatever the account still holds, this method
    reports, and it never reports an object as attached to an agent that is gone.
    """
    if not engine.capabilities.knowledge_base:
        return  # covered instead by the refusal clause for KB-less engines
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    handle = await engine.attach_kb(
        ref, _kb_source("kb_account", "Fees", "A consultation costs 500."), agent=cfg
    )

    listing = await engine.list_account_kb()
    assert listing.complete, "the account listing was truncated on an account with one object"
    assert handle in {obj.handle for obj in listing.objects}, (
        "an attached document is not in the account listing, so the orphan report can "
        "never see one that stops being attached"
    )

    await engine.delete_agent(ref)

    assert handle not in set(await _kb_of_deleted_agent(engine, ref)), (
        "a deleted agent still references the knowledge it held"
    )
    # THE ACCOUNT LISTING MUST STILL ANSWER, and that is the assertion. Whether the object
    # survived its agent is the vendor's business and neither branch is asserted; what is
    # refused is an adapter that answers this method FROM the agent — such an adapter
    # raises here (the agent is a phantom) or reports an empty account, and either way the
    # orphan report can never see the residue it exists for.
    final = await engine.list_account_kb()
    assert final.complete, "the account listing stopped being answerable once an agent went"


async def _kb_of_deleted_agent(engine: VoiceEngine, ref: str) -> list[str]:
    """What `list_kb` says about an agent that no longer exists: nothing, or a refusal.

    Both are correct — the Protocol lets `get_agent` raise on a phantom — and the caller
    above needs the distinction flattened, because its subject is the ACCOUNT listing.
    """
    try:
        return await engine.list_kb(ref)
    except Exception:
        return []


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
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    reported: Exception | None = None
    try:
        await engine.detach_kb(ref, "kb_this_engine_never_issued", agent=cfg)
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
    if not engine.capabilities.hosts_agents():
        # This engine's agents are deployed to it from elsewhere: there is no agent record
        # to create, configure or read back, and all three methods refuse by name. The
        # clause that measures that refusal — and the alternative home hard rule 5 gets
        # instead — is `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`.
        return
    caps = engine.capabilities
    for leg, field, value in (
        ("stt", "stt_model", "saaras:v3"),
        ("llm", "llm_model", "sarvam-105b"),
        ("tts", "tts_voice", "anushka"),
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
    if not engine.capabilities.hosts_agents():
        # This engine's agents are deployed to it from elsewhere: there is no agent record
        # to create, configure or read back, and all three methods refuse by name. The
        # clause that measures that refusal — and the alternative home hard rule 5 gets
        # instead — is `test_agent_hosting_decides_where_the_truthful_answer_rule_lives`.
        return
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


def _endpoint_for_leg(leg: PostureLeg) -> str | None:
    """The IN-CALL endpoint to PUBLISH for one declared leg, built from its own builder
    exactly as `in_call_llm` does: a per-resource Azure host, the fixed OpenAI `us` host, or
    None for a leg whose in-call endpoint is not ours to build.

    GATED ON `in_call_endpoint_is_ours`, NOT ON `builder is None` (D-478). The google leg
    now CARRIES a builder — but it is `google_openai_compat_base_url`, the DASHBOARD copilot
    surface, and the IN-CALL google leg still names no endpoint because the engine builds
    its own client from a single API key. `ModelConfig` refuses an in-call base URL on that
    leg, so feeding it one here is exactly the config the round-trip must never send. Beyond
    that gate it is DISPATCHED ON THE LEG'S DECLARED `builder`, never on a vendor name, and
    it RAISES on a builder it has no recipe for — so a fourth leg whose in-call endpoint IS
    ours cannot join the posture without teaching this clause how it is addressed.
    """
    if not leg.in_call_endpoint_is_ours:
        return None
    if leg.builder == "azure_openai_base_url":
        return azure_openai_base_url("calevate-conformance")
    if leg.builder == "openai_base_url":
        return openai_base_url()
    raise AssertionError(
        f"conformance has no publish recipe for the {leg.provider!r} leg's builder "
        f"{leg.builder!r} — a new declared leg must say how its endpoint is built here"
    )


async def test_the_llm_leg_round_trips_its_provider_and_endpoint(engine: VoiceEngine) -> None:
    """A BYOK LLM leg read back off the engine must be the SAME leg that was published —
    same provider, same endpoint — and this is the property whose absence let a real defect
    live unnoticed.

    THE BUG THIS CATCHES. When the posture opened from one LLM leg to three (D-456), the
    write path learned to publish each — `azure_openai` on its Azure resource, `openai` on
    the `us` residency host, `google` on no endpoint at all — but a real adapter's read-back
    was left recognising only Azure. A legitimately-published OpenAI-direct agent read back
    with no provider and no endpoint, logged its own host as unrecognised on every drift
    sweep, and lost the very residency proof the read exists to confirm. Nothing failed,
    because no clause asked the read-back to round-trip a leg. This is that clause.

    PROVIDER-AGNOSTIC BY CONSTRUCTION: it iterates `DECLARED_POSTURE.legs` and, for each,
    publishes on that leg via the leg's OWN builder and asserts the read-back equals what was
    published. It states the property — "the leg you published is the leg you read back" —
    over whatever legs the contract declares, rather than naming a vendor. The endpoint check
    is the round-trip itself: a leg with an endpoint must return exactly that endpoint (the
    residency proof), and a leg with none must return None (there is nothing to verify, and
    reporting an endpoint would be inventing one).

    SCOPED to engines that can answer at all. An `external_deployment` engine hosts no agent
    of ours and `get_agent` refuses by name, and an engine that DICTATES its LLM leg has no
    selection of ours to publish — neither has a BYOK LLM leg to round-trip, so both are
    exempt exactly as `test_a_byok_leg_that_can_be_read_back_holds_what_we_sent` exempts them.
    """
    if not engine.capabilities.hosts_agents():
        # No agent record to create or read back — `get_agent` refuses by name (D-280).
        return
    if not engine.capabilities.is_ours("llm"):
        # The engine dictates its own model; there is no leg of ours to publish or read.
        return

    speech = _byok_models(engine)
    for index, leg in enumerate(DECLARED_POSTURE.legs):
        published_endpoint = _endpoint_for_leg(leg)
        # Azure addresses a DEPLOYMENT id, every other leg the model's own name — the same
        # distinction `bind_model` draws, read here off the leg rather than hard-coded.
        model = "conformance-deployment" if leg.addresses_a_deployment else f"model-{leg.provider}"
        models = ModelConfig(
            stt_provider=speech.stt_provider,
            stt_model=speech.stt_model,
            llm_provider=leg.provider,
            llm_model=model,
            llm_base_url=published_endpoint,
            tts_provider=speech.tts_provider,
            tts_model=speech.tts_model,
            tts_voice=speech.tts_voice,
        )
        cfg = _agent_config(
            engine,
            name=f"LLM leg {leg.provider}",
            # Distinct per leg AND distinct from every other clause's agent: the fake keys
            # refs on (tenant_id, agent_id) and the Bolna stub on the agent NAME, so both a
            # distinct id and a distinct name are needed for the three agents to coexist —
            # and the `11e6` marker keeps them clear of the default id other clauses use.
            agent_id=f"0199a0b0-0000-7000-8000-11e6{index:08d}",
        ).model_copy(update={"models": models})

        ref = await engine.create_agent(cfg)
        snapshot = await engine.get_agent(ref)

        assert snapshot.models_readable, (
            f"this adapter claims BYOK LLM and could not read the {leg.provider!r} leg back, "
            "so 'is the engine running the leg we published?' is unanswerable — the exact "
            "blind spot that let a whole leg read back as absent"
        )
        assert snapshot.models is not None
        assert snapshot.models.llm_provider == leg.provider, (
            f"published the {leg.provider!r} leg and read back "
            f"{snapshot.models.llm_provider!r} — the read-back cannot identify the leg, so a "
            "publish onto the wrong leg would be invisible"
        )
        assert snapshot.models.llm_base_url == published_endpoint, (
            f"published endpoint {published_endpoint!r} on the {leg.provider!r} leg and read "
            f"back {snapshot.models.llm_base_url!r} — the endpoint is the leg's residency "
            "proof, and a mismatch is exactly the drift the read-back exists to catch"
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
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    source = _kb_source("kb_absent", "Fees", "A consultation costs 500.")
    for label, call in (
        ("attach_kb", lambda: engine.attach_kb(ref, source, agent=cfg)),
        ("detach_kb", lambda: engine.detach_kb(ref, "kb_anything", agent=cfg)),
        ("list_kb", lambda: engine.list_kb(ref)),
        ("list_account_kb", engine.list_account_kb),
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


async def test_the_llm_credential_seam_matches_the_declaration_either_way(
    engine: VoiceEngine,
) -> None:
    """`set_llm_credential` installs where the LLM is OURS, and refuses by name where it
    is not (D-404).

    BOTH DIRECTIONS, for `transfer`'s reason and with a sharper failure behind it. The
    caller is a cron whose whole job is to keep a credential from expiring, and the
    consequence of a silent success is not a missing feature — it is a refresher reporting
    green, every four hours, against an engine that has nowhere to put a bearer. Nothing
    else in the system notices until in-call model turns start 401ing on live phone calls,
    at which point the symptom is a caller hearing silence.

    The gate is `is_ours("llm")` rather than a capability flag of its own: an engine that
    DICTATES its language model has no credential of ours to hold, so "can we install one"
    and "is the LLM ours" are one question, and inventing a second flag would let the two
    answers drift apart.
    """
    if not engine.capabilities.is_ours("llm"):
        refusal: Exception | None = None
        try:
            await engine.set_llm_credential("ya29.rotated", provider="azure_openai")
        except Exception as exc:
            refusal = exc
        assert refusal is not None, (
            "`set_llm_credential` succeeded on an engine that chooses its own language "
            "model — the refresher would report a healthy rotation forever against a "
            "credential store that does not exist"
        )
        assert getattr(refusal, "capability", None) == "llm", (
            "`set_llm_credential` refused without naming the capability, so an operator "
            "cannot tell 'this engine holds no LLM credential of ours' from 'the vendor "
            "rejected our credential'"
        )
        return

    placement = await engine.set_llm_credential("ya29.rotated", provider="azure_openai")
    # The write must REPLACE. A store that appended would leave the engine holding the
    # fresh bearer beside expired ones and choosing between them itself, which takes the
    # leg's health out of our hands — `LlmCredentialPlacement` exists to say which
    # happened, and an adapter that cannot tell must not claim the good one.
    assert placement.replaced_in_place is True
    assert placement.superseded_removed == 0
    # Rotation is the operation whose purpose is to replace something that still works, so
    # a second call with a second value must leave ONE credential rather than two.
    again = await engine.set_llm_credential("ya29.rotated-2", provider="azure_openai")
    assert again.replaced_in_place is True


async def test_transfer_matches_the_declaration_either_way(engine: VoiceEngine) -> None:
    """A transfer that silently does nothing is a caller left on hold forever.

    Both directions are asserted because both have been wrong here at once: the `fake`
    adapter used to record a successful transfer while the Bolna adapter raised, so the
    two shipped adapters disagreed about whether the platform can transfer a call and
    nothing in the suite could see it. That is the single clearest piece of evidence
    that declarations needed to be checkable.
    """
    handle = await _place_call(engine)
    if handle is None:
        # This adapter refuses to dial, so there is no live call to transfer and the
        # positive half of this clause has no subject. The NEGATIVE half still runs:
        # an engine declaring no transfer must refuse one for a call it does not hold.
        assert not engine.capabilities.transfer, (
            "this adapter advertises engine-side transfer and cannot place a call to "
            "transfer, so the claim can never be exercised"
        )
        return
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
            # THE EXACT NUMBER IS PART OF THE REQUEST NOW (D-535). The vendor's buy
            # endpoint requires it and has no "one like this" mode, so a spec without one
            # is a refusal on every real adapter — which is a different clause (below),
            # not this one. Here the question is only whether the DECLARED series can be
            # bought at all.
            outcome = await engine.provision_number(
                NumberSpec(series=series, e164="+918000000001", purpose="probe")
            )
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


async def test_a_purchase_without_a_chosen_number_is_refused(engine: VoiceEngine) -> None:
    """search -> pick -> buy, and the middle step is not optional (D-535).

    The vendor's own buy schema requires `phone_number` as well as `country`
    (`bolna-findings/mirror/pages/api-reference/phone-numbers/buy.md:74-77`), so an
    adapter handed a spec with no `e164` has exactly two honest options: refuse, or pick
    a number for us. The second is this repository inventing a purchase nobody chose —
    with real money — so the contract is that it refuses.

    An adapter that provisions nothing refuses for its own reason and satisfies this
    clause the same way; what must not happen is a `ProvisionedNumber` coming back.
    """
    outcome: Exception | ProvisionedNumber
    try:
        outcome = await engine.provision_number(NumberSpec(series="standard", purpose="probe"))
    except Exception as exc:
        outcome = exc
    assert isinstance(outcome, Exception), (
        "this adapter bought a number nobody named — the vendor requires the exact E.164 "
        "and the only honest source of one is a search result somebody picked"
    )


async def test_searching_is_offered_exactly_where_buying_is(engine: VoiceEngine) -> None:
    """A search that works beside a buy that refuses is a screen that teaches a lie.

    Both hang off the same descriptor field (`number_series`), so an adapter cannot be
    able to browse a vendor's inventory and unable to buy from it, or the other way round.
    An engine that sells nothing must refuse the SEARCH by name too, rather than answering
    an empty list — "no inventory today" and "this platform sells no numbers" send an
    operator at completely different problems.
    """
    caps = engine.capabilities
    outcome: Exception | list[AvailableNumber]
    try:
        outcome = list(await engine.search_numbers(NumberSearch(country="IN")))
    except Exception as exc:
        outcome = exc
    if caps.number_series:
        assert isinstance(outcome, list), (
            "this adapter sells numbers and could not be asked what is available, so "
            "nothing can ever name one to buy"
        )
        for offer in outcome:
            assert offer.e164.startswith("+"), "E.164 only"
        return
    assert isinstance(outcome, Exception), (
        "this adapter declares it sells no numbers and answered a search anyway — an "
        "operator would be offered an inventory that cannot be bought from"
    )


async def test_a_bought_number_can_be_given_back(engine: VoiceEngine) -> None:
    """The other end of a recurring cost, and absent-is-success on the second call.

    A number bought and never released renews for ever against our wallet, so `release`
    is not optional symmetry — it is what makes `provision_number` safe to call at all.
    Releasing twice must succeed: the postcondition is "we are not billed for this", which
    a number the engine no longer holds already satisfies, and an offboarding step that
    raises on "there was nothing to undo" is one somebody abandons half done.
    """
    caps = engine.capabilities
    if not caps.number_series:
        with pytest.raises(Exception):  # noqa: B017 - any refusal; the clause above names it
            await engine.release_number(LINKED_NUMBER)
        return
    bought = await engine.provision_number(
        NumberSpec(series="standard", e164="+918000000002", purpose="release-probe")
    )
    await engine.release_number(bought)
    await engine.release_number(bought)


#: The header a conformance dial asks to present. A 160-series-shaped Indian number,
#: because that is the class every agent this platform publishes runs on today (D-05).
CONFORMANCE_CALLER_ID = "+911160000001"

#: A number the engine has been told about, and one it has not — the pair every inbound
#: clause below needs. `engine_number_ref` is the vendor's OWN handle for a number
#: (Bolna's `phone_number_id`), which is why it is opaque here: `phone_numbers.
#: engine_number_ref` stores whatever the vendor issued and hands it straight back, and
#: OPERATIONS §2 gate 25 is open on what that string even looks like.
LINKED_NUMBER = ProvisionedNumber(
    e164="+911160000001", provider="plivo", engine_number_ref="num_known_to_engine", series="160"
)
UNLINKED_NUMBER = ProvisionedNumber(
    e164="+911160000002", provider="plivo", engine_number_ref=None, series="160"
)


async def test_a_declared_caller_id_reaches_the_dial_or_is_refused_by_name(
    engine: VoiceEngine,
) -> None:
    """THE NUMBER OUR COMPLIANCE GATE APPROVES IS THE NUMBER THAT RINGS (D-420).

    `campaigns.service._channel_blockers` refuses a launch, and every dispatch tick, unless
    the campaign's number carries the right 140/160 series for its classification and
    `dlt_status = 'registered'`. For as long as `CallContext` had no from-number, that gate
    described a number the callee never saw: the engine dialled from its own pool, and the
    callee, the TSP and the complaint trail saw the vendor's number instead — **a
    compliance control that controls nothing and reports green.**

    So the claim is checkable in exactly two shapes and an adapter must satisfy the one it
    declares:

    **`caller_id=True`** — the value REACHES THE VENDOR. Asserted through the execution
    read-back rather than by peeking at a request body, for `transfer`'s reason: this
    method returns a handle and nothing else, so "it sent our number" and "it dropped our
    number" are otherwise the same observation. `ExecutionSnapshot.from_e164` is the
    contract's own answer to "what did the callee see", which makes this a property of the
    port rather than of one stub.

    **`caller_id=False`** — the dial is REFUSED, naming `caller_id`, never placed with the
    platform's own number substituted. Silent substitution is the entire defect: the dial
    succeeds, the handset shows a number nobody gated, and nothing anywhere reports it. An
    adapter that refuses EVERY dial for a prior reason (the compliance floor) has nothing
    to measure here and says so — `fake-deployed` is the profile that exercises the refusal
    with the floor satisfied, which is why that fixture declares `caller_id=False`.
    """
    caps = engine.capabilities
    cfg = _agent_config(engine)
    ref = await _agent_ref(engine, cfg)
    ctx = _dial_context(engine, cfg).model_copy(update={"from_e164": CONFORMANCE_CALLER_ID})

    refusal: Exception | None = None
    handle: str | None = None
    try:
        handle = await engine.start_outbound_call(ref, "+919876543210", ctx)
    except Exception as exc:
        refusal = exc

    if caps.caller_id:
        assert refusal is None, (
            "this adapter advertises a per-call caller id and refused a dial carrying "
            f"one: {refusal!r}"
        )
        assert handle is not None
        snapshot = await engine.get_execution(handle)
        assert snapshot.from_e164 == CONFORMANCE_CALLER_ID, (
            "this adapter advertises a per-call caller id and the execution came back "
            f"presenting {snapshot.from_e164!r} — the DLT-registered header the campaign "
            "gate approved is not the number that rang"
        )
        return

    assert refusal is not None, (
        "this adapter declares it cannot present a caller id we name and accepted one "
        "anyway; the callee sees a number nobody gated and nothing reports it"
    )
    code, _ = _refusal(refusal)
    if code == "engine_compliance_floor_absent":
        # This adapter refuses EVERY dial one step earlier, so the caller-id refusal is
        # unreachable here. Not a pass by omission: the same refusal is exercised on the
        # `fake-deployed` profile, which satisfies the floor and declares `caller_id=False`.
        return
    assert getattr(refusal, "capability", None) == "caller_id", (
        "the refusal does not name `caller_id`, so a console cannot tell it apart from a "
        "transient engine failure and will offer the number again"
    )


async def test_a_declared_handoff_reaches_the_engine_or_is_refused_by_name(
    engine: VoiceEngine,
) -> None:
    """THE PERSON A CALLER ASKS FOR IS EITHER ON THE ENGINE OR THE PUBLISH SAID NO (D-533).

    Escalation is the one feature whose failure is invisible until the worst moment. A
    client configures the people who take their calls, the screen says saved, the agent
    goes live — and if the destination never reached the engine, the first anybody hears
    of it is a caller asking for a human and being told, plausibly, to wait. So this
    clause admits exactly two outcomes and no third.

    1. `in_call_handoff=True` ⇒ the destination REACHES THE ENGINE. Asserted through the
       read-back and never through the argument we passed: an adapter that echoed its own
       input would agree with every caller and prove nothing, which is the property
       `get_agent` was built for.
    2. `in_call_handoff=False` ⇒ the publish is REFUSED, naming `in_call_handoff`, rather
       than succeeding with the tool quietly dropped. Dropping is the dangerous direction,
       and it is the direction an adapter falls into by accident — a `if cfg.handoff` that
       is simply never written.
    3. AND AN AGENT WITH NO HANDOFF READS BACK WITH NONE. This is the half that makes the
       business-hours rule enforceable: outside every roster member's hours the publish
       carries `handoff=None`, and "the agent cannot hand off" is a claim about the ENGINE
       that only a read-back can settle. An adapter that added a tool on create and never
       removed it on update would leave a mobile ringing at midnight with every screen in
       this product reporting the roster closed.

    Skipped where the engine does not host agents of ours at all: there is no agent record
    to hang a tool on, `create_agent` refuses one step earlier on `agent_hosting`, and a
    refusal naming the wrong capability is not evidence about this one.
    """
    caps = engine.capabilities
    if not caps.hosts_agents():
        pytest.skip("no agent record on this shape; `agent_hosting` covers it")

    cfg = _agent_config(engine, handoff=HANDOFF)

    if not caps.in_call_handoff:
        refused: Exception | None = None
        try:
            await engine.create_agent(cfg)
        except Exception as exc:
            refused = exc
        assert refused is not None, (
            "this adapter declares no in-call handoff and published one anyway — a client "
            "would see their handover list saved and live, and find out it was never "
            "wired when a caller asked for a person"
        )
        assert getattr(refused, "capability", None) == "in_call_handoff", (
            "the refusal does not name `in_call_handoff`, so a console cannot tell it "
            "apart from a transient engine failure and will offer the control again"
        )
        return

    ref = await engine.create_agent(cfg)
    snapshot = await engine.get_agent(ref)
    assert snapshot.handoff_destinations_readable, (
        "this engine claims it can hand a caller to a person but cannot say who its "
        "agents hand off to — so a destination added in the vendor's own console, to a "
        "number nobody here chose, is invisible to every instrument in this repository"
    )
    assert HANDOFF.destination_e164 in snapshot.handoff_destinations, (
        "the handoff destination did not reach the engine. The agent published fine and "
        "will tell a caller it is putting them through to nobody"
    )

    # AND IT COMES BACK OFF, which is the hours rule (decision 4) as a property of the
    # engine rather than of our intent.
    await engine.update_agent(ref, _agent_config(engine, handoff=None))
    closed = await engine.get_agent(ref)
    assert closed.handoff_destinations == (), (
        "an agent republished with no handoff still holds one on the engine, so a staff "
        "mobile rings after hours however carefully the roster is enforced here"
    )


async def test_inbound_binding_matches_the_declaration_either_way(engine: VoiceEngine) -> None:
    """AN AGENT ASSIGNED TO A NUMBER IS AN AGENT THE ENGINE KNOWS ABOUT (D-420).

    Inbound is half this product, and its first configuration step wrote
    `phone_numbers.agent_id` and stopped at our database — no protocol method could carry
    it to the engine, so an admin assigned a receptionist, the console said it worked, and
    the number answered with whatever was last set in the vendor's own dashboard, or did
    not answer at all.

    Three properties, and the negative one is the one that catches an adapter that binds
    nothing:

    1. `inbound_binding=False` ⇒ both methods REFUSE, naming `inbound_binding`. An
       operator must get the same answer from the descriptor before calling as from the
       call, which is what stops a console offering a receptionist control the engine
       cannot honour.
    2. A number the engine has never been told about (`engine_number_ref is None`) is
       REFUSED by name, not bound on the E.164. An engine addresses a number by its own
       handle; ours are bought from the telephony vendor directly (D-05), so "the engine
       has never heard of this number" is the ordinary state and a person's job to fix,
       not an error to retry.
    3. UNBINDING A NUMBER THE ENGINE DOES NOT HOLD SUCCEEDS. The postcondition is
       "nothing of ours answers this number", which is already true — and this is an
       OFFBOARDING path, so a step that raised on "there was nothing to undo" would block
       the release of a number a client has stopped paying for. The opposite of
       `end_call`, deliberately, and the same reasoning `delete_agent` uses.
    """
    caps = engine.capabilities
    ref = await _agent_ref(engine)

    if not caps.inbound_binding:
        for call, name in (
            (engine.bind_inbound_number(ref, LINKED_NUMBER), "bind_inbound_number"),
            (engine.unbind_inbound_number(LINKED_NUMBER), "unbind_inbound_number"),
        ):
            refused: Exception | None = None
            try:
                await call
            except Exception as exc:
                refused = exc
            assert refused is not None, (
                f"{name} declares no inbound binding and accepted one anyway — the console "
                "reports a receptionist assigned to a number the engine was never told about"
            )
            assert getattr(refused, "capability", None) == "inbound_binding", (
                f"{name}'s refusal does not name `inbound_binding`, so it cannot be told "
                "apart from a transient engine failure"
            )
        return

    # A number the engine holds: binds, and unbinds again.
    await engine.bind_inbound_number(ref, LINKED_NUMBER)
    await engine.unbind_inbound_number(LINKED_NUMBER)
    # ABSENT IS SUCCESS — the second unbind has nothing left to undo and must not raise.
    await engine.unbind_inbound_number(LINKED_NUMBER)

    unlinked: Exception | None = None
    try:
        await engine.bind_inbound_number(ref, UNLINKED_NUMBER)
    except Exception as exc:
        unlinked = exc
    assert unlinked is not None, (
        "this adapter bound a number the engine has no handle for, so nothing it does on "
        "this method can be distinguished from doing nothing"
    )
    assert _refusal(unlinked)[0] == "engine_number_not_linked", (
        "a number the engine was never told about must be refused by that name — an "
        "operator's next step is to connect it, not to retry"
    )


async def test_agent_hosting_decides_where_the_truthful_answer_rule_lives(
    engine: VoiceEngine,
) -> None:
    """HARD RULE 5 ON BOTH SHAPES, AND THE SPLIT DERIVED FROM THE CAPABILITY (D-280/D-282).

    Every clause above this one assumes the engine holds an agent of ours: `create_agent`
    makes it, `get_agent` reads the prompt back, and `verification.judge` scores the
    truthful-answer marker on what came back. **That assumption is not a fact about voice
    engines, it is a fact about Bolna** — TRD §10.5 asked whether this contract is
    vendor-neutral or merely Bolna-shaped and answered itself, *"those look identical while
    only one vendor exists"*. On Cartesia Line the agent is a deployed repository: no
    create endpoint, no prompt on the agent record, nothing to read back.

    So the contract has two shapes, and an engine must satisfy exactly the one it declares.
    The branch is taken from `EngineCapabilities.agent_hosting`, never from a name, so a
    third vendor cannot join the roster unmeasured — the same derivation
    `test_every_adapter_that_speaks_http_is_held_to_the_transport_clauses` uses for the
    transport ladder (D-240).

    **`control_plane`** — the existing clauses apply unchanged, and this one only checks
    they were reachable at all: the engine took an agent and the marker came back.

    **`external_deployment`** — three properties, and none of them is a softening:

    1. `create_agent` and `get_agent` REFUSE, naming `agent_hosting`. Not a 404, not a
       snapshot with `readable=False` for ever: an operator must be able to ask before
       calling and get the same answer the method gives.
    2. **A dial without the truthful-answer rule on it is REFUSED.** With no agent record
       there is nowhere else for the rule to live, so a call placed without it is an agent
       that can be scripted into claiming it is human — the one thing hard rule 5 exists to
       make impossible.
    3. **A dial WITH the rule is either placed, or refused by name.** Both are legitimate
       and the difference is what the adapter can actually put on the wire. What is NOT
       legitimate is the third outcome: accepting the dial and dropping the prompt, which
       is `require_speech_leg`'s silent-drop failure one layer up and is invisible from
       everywhere except a caller's phone.

    THE NEGATIVE PROBE IS THE FALSIFIER, for `transfer`'s reason: `start_outbound_call`
    returns a handle and offers no read-back, so "it carried our prompt" and "it dropped
    our prompt" are the same observation from here. An adapter that can really carry the
    floor can therefore be required to REFUSE a call that has none — and one that cannot
    carry it must refuse both. `tests/engine_capability_test.py` observes the positive
    round trip on the fixture that IS its own vendor, which is the only place it can be
    observed at all.
    """
    cfg = _agent_config(
        engine, name="Hosting probe", agent_id="0199a0b0-0000-7000-8000-0000000000e0"
    )

    if engine.capabilities.hosts_agents():
        ref = await engine.create_agent(cfg)
        snapshot = await engine.get_agent(ref)
        assert snapshot.carries_prompt_marker(TRUTHFUL_ANSWER_MARKER) is True, (
            "this engine declares that it holds our agent, and the rule a client cannot "
            "switch off is not in what it holds"
        )
        return

    for label, call in (
        ("create_agent", lambda: engine.create_agent(cfg)),
        ("get_agent", lambda: engine.get_agent(DEPLOYED_AGENT_REF)),
    ):
        refusal: Exception | None = None
        try:
            await call()
        except Exception as exc:  # adapters raise our ProblemError; the type is theirs
            refusal = exc
        assert refusal is not None, (
            f"`{label}` succeeded on an engine that declares its agents are deployed "
            "elsewhere — so either the descriptor is wrong or this adapter is writing to "
            "an endpoint the vendor does not serve"
        )
        assert getattr(refusal, "capability", None) == "agent_hosting", (
            f"`{label}` refused without naming `agent_hosting`, so a console cannot tell "
            "a platform that will never host this agent from a platform having a bad day"
        )

    ref = DEPLOYED_AGENT_REF
    floorless: Exception | None = None
    try:
        await engine.start_outbound_call(ref, "+919876543210", CallContext())
    except Exception as exc:
        floorless = exc
    assert floorless is not None, (
        "this adapter placed a call with no system prompt on an engine that holds no "
        "prompt of ours — nothing in that call makes the agent answer truthfully about "
        "being an AI, and no read-back anywhere could detect it afterwards"
    )
    assert _refusal(floorless)[0] == "engine_compliance_floor_absent", (
        "the refusal does not name the compliance floor, so an operator reading it "
        f"cannot tell it from a transient dialling failure and will retry: {floorless!r}"
    )

    # And a dial that DOES carry the floor: placed, or refused by the same named code.
    # Anything else — a different error, or a success this suite cannot account for — is
    # an adapter doing something with our prompt that nobody has described.
    try:
        handle = await engine.start_outbound_call(ref, "+919876543210", _dial_context(engine, cfg))
    except Exception as exc:
        assert _refusal(exc)[0] == "engine_compliance_floor_absent", (
            "this adapter refused a dial that carried the truthful-answer rule, for a "
            f"reason that is not the compliance floor: {exc!r}"
        )
        return
    assert isinstance(handle, str) and handle, (
        "this adapter accepted a floor-carrying dial and returned no handle"
    )


async def test_an_externally_deployed_engine_claims_no_byok_leg(
    engine: VoiceEngine,
) -> None:
    """`ModelConfig` reaches an engine through the agent object, so no agent object means
    no BYOK leg — derived, not declared per vendor.

    `SpeechControl`'s own docstring is what makes this a contract rule rather than an
    observation about Cartesia: `ours` means *"our provider and model strings REACH THE
    VENDOR and run on OUR key"*. Every path by which they could is a write to an agent
    record — `_agent_body` on Bolna, `PATCH /agents/{id}` on Cartesia — and on an engine
    whose agents are deployed elsewhere there is no such record and `create_agent`/
    `update_agent` refuse. A leg declared `ours` there is a claim nothing in this suite
    could ever contradict, sitting in the same descriptor as six that are enforced and
    borrowing their credibility — exactly what
    `test_an_engine_side_campaign_object_is_not_claimable_yet` refuses for `campaigns`.

    The day a vendor of this shape accepts a model on the CALL the way a prompt can ride
    one, this clause is the thing that has to be rewritten first, and failing it is the
    intended way to find that out.
    """
    if engine.capabilities.hosts_agents():
        return
    dictated = [leg for leg in ("stt", "llm", "tts") if engine.capabilities.is_ours(leg)]
    assert not dictated, (
        f"this engine holds no agent record of ours and still claims BYOK on {dictated} — "
        "there is no endpoint through which a ModelConfig value could reach it, so the "
        "claim cannot be exercised or contradicted by anything"
    )


def test_every_agent_hosting_shape_is_exercised_by_the_roster(
    declared_agent_hostings: frozenset[str],
) -> None:
    """A hosting shape no subject declares is a branch of the contract nothing runs.

    Derived from `AgentHosting` rather than counted, so adding a third shape to the port
    fails here until a subject declares it — the roster clause's argument
    (`test_every_adapter_that_speaks_http_is_held_to_the_transport_clauses`) applied to the
    axis this whole section is about. Without it the `external_deployment` half could be
    deleted from every adapter and the suite would go green.

    SYNC, like that roster clause and for its reason: its subject is the ROSTER rather than
    an adapter, and `tests/engine_audit_test.py`'s saboteur harness hands an adapter to
    every coroutine clause it finds. A saboteur is not a roster.
    """
    missing = sorted(set(AGENT_HOSTING_VALUES) - declared_agent_hostings)
    assert not missing, (
        f"no adapter in the roster declares {missing}, so every clause that branches on "
        "agent hosting is measuring one half of the contract"
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


# =============================================================================
# The TRANSPORT LADDER — what an adapter says when the VENDOR misbehaves (D-240)
#
# Every clause above measures an adapter against a well-behaved stub, so the whole
# failure half of this seam was unmeasured — and the two real adapters had quietly
# drifted apart across all of it. One retried a 429 and reported it `transient`; the
# other reported the same 429 as a flat rejection with no backoff. One refused a 2xx it
# could not parse; the other turned it into `{}` and built an `ExecutionSnapshot` out of
# nothing. Neither divergence could fail a clause, because no clause existed.
#
# These take `ladder` — a builder that puts one HTTP-speaking adapter over a transport
# the clause writes itself (conftest). `test_every_adapter_that_speaks_http_is_held_to_
# the_transport_clauses` refuses to let a new vendor adapter join the roster without one.
#
# A vendor 404 is deliberately NOT re-tested here: it already has three clauses of its
# own (`test_reading_an_agent_the_engine_never_created_is_reported`,
# `test_reading_an_execution_the_engine_never_placed_is_reported`,
# `test_ending_a_call_the_engine_does_not_hold_is_reported`), each stated in the
# vocabulary of the METHOD whose contract it belongs to rather than in HTTP.
#
# `get_execution` is the probe throughout because it is the method where an invented
# answer does the most damage: the post-call pipeline writes what it returns.
# =============================================================================

#: The same alias `conftest` declares, spelled again rather than imported. This module is
#: also loaded BY PATH, outside pytest, by `tests/engine_audit_test.py`'s saboteur harness
#: — where the conformance directory is not on `sys.path` and `import conftest` would be
#: an ImportError that took the whole audit with it. One line of stdlib typing is the
#: cheaper duplication.
VendorHandler = Callable[[httpx.Request], httpx.Response]

#: An id no stub has to know: these clauses supply the whole vendor.
LADDER_CALL_ID = "call_under_test"


def _refusal(exc: BaseException) -> tuple[str | None, str | None]:
    """`(code, kind)` off whatever an adapter raised.

    Read off the object rather than by importing our `ProblemError`, for the reason the
    404 clauses above already give — "adapters raise our ProblemError; the type is
    theirs". What the CONTRACT constrains is not the class but the DISCRIMINATOR: a
    caller that cannot tell a throttle from a rejection cannot retry correctly, and
    `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` dispatches on exactly these two
    fields. An adapter that raises something carrying neither fails here with the
    reason, which is the right answer too.
    """
    return getattr(exc, "code", None), getattr(exc, "kind", None)


async def _refused(engine: VoiceEngine, *, what: str) -> BaseException:
    """`get_execution` must have raised. Returns what it raised."""
    try:
        await engine.get_execution(LADDER_CALL_ID)
    except Exception as exc:  # the type is theirs; `_refusal` reads the discriminator
        return exc
    raise AssertionError(
        f"{what}: this adapter ANSWERED instead of raising, so a caller receives a call "
        "record the vendor never produced"
    )


async def test_a_throttled_vendor_is_retried_rather_than_reported_as_a_failure(
    ladder: Callable[[VendorHandler], VoiceEngine],
) -> None:
    """A 429 states the request was REFUSED, not performed — the one status where a
    repeat cannot dial a person twice (SURFACES §3.3). An adapter that gives up on the
    first one throws away work the vendor never did, and on the campaign path it spends a
    contact's attempt on the vendor's load rather than on the contact.

    `Retry-After: 0` so the adapter's real backoff still runs — jitter over a zero floor,
    so sub-second — without this clause becoming a wall-clock test. Nothing below asserts
    a duration; D-29's note about speed-dependent branches is why.
    """
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "slow down"})
        return httpx.Response(200, json={})

    await ladder(handler).get_execution(LADDER_CALL_ID)

    assert len(attempts) == 2, (
        "this adapter did not retry a 429 — a throttle is the one refusal that is safe "
        "to repeat, and giving up on it discards a request the vendor never performed"
    )


async def test_an_exhausted_throttle_is_transient_rather_than_a_rejection(
    ladder: Callable[[VendorHandler], VoiceEngine],
) -> None:
    """`transient` (retryable) and `dependency` (terminal) send a caller to opposite
    places. `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` and `apps.api.agents.service`
    both dispatch on `engine_rate_limited` by name, so an adapter that collapses a rate
    limit into `engine_rejected` turns "the vendor is busy" into "this call failed" — a
    campaign contact marked failed for a reason that has nothing to do with the contact.
    """
    engine = ladder(
        lambda request: httpx.Response(
            429, headers={"Retry-After": "0"}, json={"error": "slow down"}
        )
    )

    code, kind = _refusal(await _refused(engine, what="a vendor throttling every attempt"))

    assert code == "engine_rate_limited", (
        f"a throttle surfaced as {code!r}; every caller that dispatches on the code then "
        "treats it as a terminal failure of the request itself"
    )
    assert kind == "transient"


async def test_a_success_the_adapter_cannot_read_never_becomes_an_answer(
    ladder: Callable[[VendorHandler], VoiceEngine],
) -> None:
    """THE CLAUSE THIS SECTION EXISTS FOR (D-240).

    A 200 carrying a WAF challenge, a CDN interstitial or a truncated document is the
    ordinary failure mode of an API behind an edge, and it is indistinguishable from a
    real answer until the parse fails. An adapter that answers it with an empty payload
    does not fail — it INVENTS. Measured on the adapter that did: `get_execution`
    returned a snapshot naming no call (`engine_call_id=''`), priced at nothing, holding
    no transcript and carrying `{}` as the vendor's own archived document. The post-call
    pipeline writes that as a failed call, meters it at zero, and the reconciliation
    poller then reads it as settled forever — with no alert anywhere.

    `VoiceEngine.get_agent` already forbids exactly this shape in words: "a snapshot for
    an agent nobody created is a conclusion drawn from nothing that looks like a
    measurement". This is that rule with a transport behind it.
    """
    unreadable = {
        "a WAF challenge": "<html><body>Attention Required! | Cloudflare</body></html>",
        "a truncated document": '{"id": "exec_abc123", "status": "comp',
        "whitespace": "   ",
    }
    for label, body in unreadable.items():

        def handler(request: httpx.Request, text: str = body) -> httpx.Response:
            return httpx.Response(200, text=text)

        code, kind = _refusal(await _refused(ladder(handler), what=f"a 200 carrying {label}"))
        assert code == "engine_bad_response", (
            f"a 200 carrying {label} surfaced as {code!r} — an adapter that answers an "
            "unreadable success with a VALUE fabricates a call record"
        )
        assert kind == "dependency"


async def test_a_redirect_is_never_treated_as_an_answer(
    ladder: Callable[[VendorHandler], VoiceEngine],
) -> None:
    """A 3xx is a status BELOW 400, which is how it got in.

    No adapter here follows redirects (httpx defaults `follow_redirects` to False), so a
    301/302/307/308 arrives as an ordinary response carrying a `Location` and, usually, no
    body at all — and a ladder that asks "is this >= 400?" reads that as the vendor having
    done what it was asked. Measured on this tree before the rung existed: a 302 on the
    execution route produced `engine_call_id=''`, `status='failed'`, no cost and no
    transcript, which is the same fabricated record the unreadable-success clause above
    exists to prevent, reached by a status that clause never touched.

    Following it is not the fix and is not permitted: 307/308 re-send the request BODY, so
    an edge misconfiguration in front of `POST /call` would dial one contact twice, and a
    cross-host redirect strips the `Authorization` header on the way. A redirect off an API
    root the adapter pins is a moved API or an intermediary, and either is an operator's
    problem that they can only act on if somebody reports it.
    """
    for status in (301, 302, 307, 308):

        def handler(request: httpx.Request, code: int = status) -> httpx.Response:
            return httpx.Response(code, headers={"Location": "https://elsewhere.example/v1"})

        code, kind = _refusal(await _refused(ladder(handler), what=f"a {status} redirect"))
        assert code == "engine_bad_response", (
            f"a {status} surfaced as {code!r} — an adapter that reads a redirect as a "
            "successful answer reports a call record the vendor never sent"
        )
        assert kind == "dependency"


async def test_a_vendor_error_body_is_never_echoed_to_our_caller(
    ladder: Callable[[VendorHandler], VoiceEngine],
) -> None:
    """A vendor's error body quotes the request, and our requests carry callers' numbers
    (hard rule 6). It is also not our vocabulary and not user-safe (BACKEND-PATTERNS §3:
    full detail logged server-side, generic body to the client). So the STATUS is the
    evidence and the body is not — on every adapter, not just the one that was audited.
    """
    leaky = "rejected +919876543210: Ray ID 8f3a2b1c origin 10.0.0.7 token abcdef"
    engine = ladder(lambda request: httpx.Response(502, text=leaky))

    refusal = await _refused(engine, what="a 502 carrying the vendor's own error text")
    code, _kind = _refusal(refusal)

    assert code == "engine_rejected"
    # Everything a caller can see of a refusal: what it says, and the fields our error
    # ladder renders into problem+json.
    rendered = " ".join(
        [str(refusal), *(str(getattr(refusal, f, "")) for f in ("title", "detail", "remediation"))]
    )
    for secret in ("+919876543210", "Ray ID", "10.0.0.7", "abcdef"):
        assert secret not in rendered, f"the vendor's error body reached our caller: {secret}"


async def test_a_vendor_that_never_answers_is_reported_as_unreachable(
    ladder: Callable[[VendorHandler], VoiceEngine],
) -> None:
    """A refused socket, a DNS failure and a read timeout are one fact to every caller —
    "we do not know whether this happened" — and none of them may arrive as a bare
    transport exception. `apps.workers.pipeline.TRANSIENT_ENGINE_CODES` reads
    `engine_unreachable` by name, so an adapter that lets the transport exception escape
    turns a network blip into a DLQ'd post-call pipeline.
    """
    for failure in (
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("the vendor never finished"),
    ):

        def handler(request: httpx.Request, exc: httpx.HTTPError = failure) -> httpx.Response:
            raise exc

        code, kind = _refusal(
            await _refused(ladder(handler), what=f"a transport {type(failure).__name__}")
        )
        assert code == "engine_unreachable", (
            f"{type(failure).__name__} surfaced as {code!r} rather than as our own "
            "unreachable code, so no caller can tell a blip from a rejection"
        )
        assert kind == "dependency"


def test_every_adapter_that_speaks_http_is_held_to_the_transport_clauses(
    transport_recipe_ids: frozenset[str],
    http_speaking_engine_ids: frozenset[str],
) -> None:
    """The clauses above are only worth having if a new vendor cannot opt out of them.

    `http_speaking_engine_ids` is derived from the roster by TYPE — every subject that is
    not the fake engine — so a third vendor joining `ENGINE_IDS` lands in it without
    anybody remembering to. This then fails until that adapter has a transport recipe,
    which is the only way the failure-path clauses can reach it.
    """
    assert http_speaking_engine_ids, (
        "the roster holds no real adapter any more; every clause above is now measuring "
        "a test double against itself"
    )
    assert transport_recipe_ids == http_speaking_engine_ids, (
        "an adapter in the roster speaks HTTP and has no entry in TRANSPORT_RECIPES, so "
        "the transport-ladder clauses never run against it: "
        f"{sorted(http_speaking_engine_ids - transport_recipe_ids)}"
    )
