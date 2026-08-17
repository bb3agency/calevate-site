"""What does "live" actually claim? — the publish read-back (migration c1f6a94d2b07).

D-118 fixed two ways a screen could say `live` about the wrong thing. This file attacks
the question underneath: when we record `status = 'live'`, `engine_agent_ref`,
`live_prompt_id` and `live_tts_voice`, WHAT HAS BEEN VERIFIED? Before this wave the
answer was "that our HTTP call to the vendor returned without raising" — four claims
about the engine derived from one fact about ourselves.

**EVERY ASSERTION HERE IS AGAINST THE ENGINE, NOT ONLY AGAINST OUR ROWS.** A test that
checks what we wrote to our own database cannot fail on any of the defects in this file,
because the defect IS that our database agreed with itself. So the doubles below record
what the adapter was ASKED for and what it ANSWERED, and the assertions read that.

THE FAILURE MODES, EACH DRIVEN BY A DOUBLE RATHER THAN DESCRIBED
----------------------------------------------------------------
A real vendor produces all of these and every one of them is a 2xx, or is
indistinguishable from one:

    SilentlyDroppingEngine   accepts the write, keeps the old config      -> REFUSAL
    DisclosureDroppingEngine accepts the write, drops the greeting        -> REFUSAL
                             (hard rule 5 — the one property with a legal consequence)
    VoiceDroppingEngine      accepts the write, keeps the old voice       -> REFUSAL
    UnreadableEngine         answers, and the answer has no prompt in it  -> recorded
    UnreachableEngine        accepts the write, 500s the read-back        -> recorded
    FreshRefEngine           a vendor that mints a NEW id per create      -> the lock

`FakeEngine` is the substrate for all of them: they are the same adapter with one
behaviour changed, which is the `DICTATED_SPEECH_CAPABILITIES` argument applied to
failure modes instead of to capabilities. Nothing here imagines a vendor payload.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts, publishing
from apps.api.agents.service import publish_agent, publish_variant
from apps.api.agents.verification import judge
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_DIRECTIVE,
    AgentConfig,
    AgentSnapshot,
    EngineAgentRef,
    ModelConfig,
    compose_engine_prompt,
)
from sqlalchemy import text

SCRIPT = "Sunrise Clinic receptionist. Greet in Telugu, then take the appointment."
NEXT_SCRIPT = "Sunrise Clinic receptionist. Greet in Telugu, then quote the new price list."
VOICE = "bulbul:v3:anushka"


# --- engines that fail the way a vendor fails --------------------------------


class RecordingEngine(FakeEngine):
    """`FakeEngine` that remembers what it was ASKED, in order.

    The base class already keeps what it HOLDS (`_agents`), which is a different fact and
    the one every existing test reads. What no existing test could see is the sequence of
    calls — whether `get_agent` was called at all, whether one publish produced one
    `create_agent` or two — and that sequence is where every defect in this file lives.
    """

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.calls: list[tuple[str, str]] = []

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        ref = await super().create_agent(cfg)
        self.calls.append(("create_agent", ref))
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        await super().update_agent(ref, cfg)
        self.calls.append(("update_agent", ref))

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        self.calls.append(("get_agent", ref))
        return await super().get_agent(ref)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class MutatingEngine(RecordingEngine):
    """Accepts every write and stores something ELSE. The 2xx that did not apply.

    Overridden on BOTH write paths, for the reason `FakeEngine._assert_speech_is_ours`
    guards both: an engine that mangled an update and honoured a create would let the
    first publish of every agent pass, which is the one publish a human is watching.
    """

    def mutate(self, cfg: AgentConfig) -> AgentConfig:  # pragma: no cover - overridden
        raise NotImplementedError

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        ref = await super().create_agent(cfg)
        self._agents[ref] = self.mutate(cfg)
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        await super().update_agent(ref, cfg)
        self._agents[ref] = self.mutate(cfg)


class SilentlyDroppingEngine(MutatingEngine):
    """Takes the bytes, keeps a different script. THE canonical silent failure.

    A vendor does this by validating the envelope and ignoring a field it no longer
    recognises, or by applying the write to a different task on the same agent. It is
    invisible to any caller that scores an update by its status code.
    """

    def mutate(self, cfg: AgentConfig) -> AgentConfig:
        return cfg.model_copy(update={"system_prompt": "Whatever this agent had before."})


class DisclosureDroppingEngine(MutatingEngine):
    """Applies the script and loses the disclosure line — hard rule 5's failure mode.

    The nastiest of the set, because the change an operator made DID land: the script
    reads back correctly, and only the legally-required greeting is missing. A read-back
    that checked the prompt alone would score this green.
    """

    def mutate(self, cfg: AgentConfig) -> AgentConfig:
        return cfg.model_copy(update={"opening_line": "…"})


class GreetingOnlyDroppingEngine(RecordingEngine):
    """Keeps the disclosure line in the PROMPT and drops it from the GREETING.

    **This is the engine P3.3 is about, and no fake in this file could express it before
    the snapshot gained a greeting field.** It is not a contrived shape: it is what a
    vendor that stopped recognising `agent_welcome_message` does — the prompt is the
    field every engine has, the greeting is the one whose name we guessed from our own
    request body, and the write silently landing in only one of them is the ordinary way
    that goes wrong.

    Scored against the prompt, this agent passes: our own adapter prepended the line
    there, so the marker is present and `disclosure_applied` reads True. Scored against
    the greeting, it fails — and the caller never hears the disclosure, which is the one
    property here with a legal consequence (SEC-COMP §1).
    """

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        return snapshot.model_copy(update={"greeting": "Namaskaram!", "greeting_readable": True})


class VoiceDroppingEngine(MutatingEngine):
    """Applies the script and speaks in a voice nobody chose."""

    def mutate(self, cfg: AgentConfig) -> AgentConfig:
        return cfg.model_copy(
            update={"models": cfg.models.model_copy(update={"tts_voice": "bulbul:v2:vidya"})}
        )


class UnreadableEngine(RecordingEngine):
    """Answers the read-back with a snapshot whose prompt could not be parsed.

    `system_prompt_readable=False` is the honest answer a real adapter gives when the
    vendor's response shape drifts — `bolna._agent_system_prompt` returns None rather
    than guessing. It is NOT a mismatch, and the whole `AgentSnapshot.*_readable`
    doctrine is that it must not be scored as one in either direction.
    """

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        snapshot = await super().get_agent(ref)
        return snapshot.model_copy(update={"system_prompt": None, "system_prompt_readable": False})


class UnreachableEngine(RecordingEngine):
    """Accepts the write and fails the read-back — a timeout, a 5xx, a reset."""

    async def get_agent(self, ref: EngineAgentRef) -> AgentSnapshot:
        self.calls.append(("get_agent", ref))
        raise ProblemError(
            kind="dependency",
            code="engine_unavailable",
            title="Voice engine unavailable",
            detail="The voice platform did not answer.",
        )


#: How long the doubles below spend "at the vendor". Two jobs, and both are needed for
#: the race test to mean anything:
#:
#: * it makes the vendor call the SLOW part of a publish, which is what it is in
#:   production (an HTTP round trip against a Postgres statement on localhost);
#: * it is an `await`, so the event loop actually runs the OTHER publish while this one
#:   is in flight. Without a yield inside the window, both coroutines run their whole
#:   transaction to completion in turn and the interleaving the lock exists to prevent
#:   never happens — a green test that measured nothing.
VENDOR_LATENCY_S = 0.05


class FreshRefEngine(RecordingEngine):
    """A vendor that mints a NEW id on every create — i.e. every real vendor — and takes
    a moment to do it.

    `FakeEngine` derives its ref deterministically from `(tenant_id, agent_id)`, which is
    right for reproducibility and WRONG for this one question: it makes a double-create
    idempotent, so the create/create race that manufactures orphans would be invisible.
    This is the double that can see it.
    """

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        self._assert_speech_is_ours(cfg)
        await asyncio.sleep(VENDOR_LATENCY_S)
        ref = f"vendoragent_{uuid.uuid4().hex[:16]}"
        self._agents[ref] = cfg
        self.calls.append(("create_agent", ref))
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        await asyncio.sleep(VENDOR_LATENCY_S)
        await super().update_agent(ref, cfg)


@contextmanager
def _engine(instance: FakeEngine) -> Iterator[FakeEngine]:
    """Run the block against `instance`, restoring the cache afterwards.

    Reaches into `apps.api.engine`'s instance cache because that is what `get_engine()`
    resolves through — the shape `agent_voice_test._dictating_engine` established.
    """
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


# --- fixtures ----------------------------------------------------------------


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Verification Clinic",
        slug=f"vf-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _publishable_agent() -> tuple[uuid.UUID, uuid.UUID]:
    """An agent with a script and a voice, not yet on any engine."""
    reset_engine_cache()
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=SCRIPT,
            notes=None,
            created_by=None,
        )
        await session.execute(
            text("UPDATE agents SET tts_voice = :v, tts_provider = 'sarvam' WHERE id = :a"),
            {"v": VOICE, "a": agent_id},
        )
    return tenant_id, agent_id


async def _verify_row(
    tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> tuple[str, bool, str, str | None]:
    """(state, verified_at is set, status, engine_agent_ref) straight off the row."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT live_verify_state, live_verified_at, status, engine_agent_ref "
                    "FROM agents WHERE id = :a"
                ),
                {"a": agent_id},
            )
        ).first()
    assert row is not None
    return str(row[0]), row[1] is not None, str(row[2]), row[3]


# --- 1. the read-back happens at all -----------------------------------------


async def test_a_publish_reads_the_agent_back_from_the_engine() -> None:
    """The instrument is ATTACHED. D-64 put `get_agent` on the Protocol so an update
    could be checked rather than assumed, and for two waves nothing called it: the
    conformance suite exercised it and no production path did."""
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()) as engine:
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert isinstance(engine, RecordingEngine)
    assert engine.names() == ["create_agent", "get_agent"], (
        "publish did not read the agent back; `live` is a claim about our own intent"
    )
    assert engine.calls[-1] == ("get_agent", ref), "the read-back asked about another agent"

    state, verified, status, stored_ref = await _verify_row(tenant_id, agent_id)
    assert (state, verified, status, stored_ref) == ("applied", True, "live", ref)


async def test_a_confirmed_publish_says_so_on_the_screen() -> None:
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()):
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    state = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert state.engine_verification.confirmed is True
    assert state.engine_verification.state == "applied"
    assert state.engine_verification.verified_at is not None
    assert "read back" in state.engine_verification.headline


# --- 2. a 2xx that did not apply is a REFUSAL, not a state -------------------


async def test_an_accepted_update_the_engine_did_not_apply_is_refused() -> None:
    """§52: failure is a refusal. The vendor took the bytes and kept the old agent —
    the single most likely silent failure of a publish, and the one a status code
    cannot see."""
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()) as first:
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert first._agents[ref].system_prompt == SCRIPT

    # A new applied script — `write_prompt_version` STAGES on a live agent, so the
    # publish would otherwise re-send the script the engine already holds and prove
    # nothing. `apply_to_live` is what a client presses.
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=NEXT_SCRIPT,
            notes=None,
            created_by=None,
        )

    dropping = SilentlyDroppingEngine()
    dropping._agents = dict(first._agents)  # the engine still holds the FIRST script
    with _engine(dropping), pytest.raises(ProblemError) as exc:
        await publishing.apply_to_live(tenant_id=tenant_id, agent_id=agent_id)

    assert exc.value.code == "engine_publish_not_applied"
    # THE ENGINE, not our row: what a caller would actually hear is not the new script.
    assert dropping._agents[ref].system_prompt != NEXT_SCRIPT
    assert dropping.names() == ["update_agent", "get_agent"]

    # And nothing on our side moved: the refusal rolled the whole transaction back, so
    # the applied pointer did NOT advance to a script the engine is not running.
    state, _, _, _ = await _verify_row(tenant_id, agent_id)
    assert state == "applied", "a refused publish must not overwrite a confirmed verdict"
    shown = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert shown.has_pending is True, "the applied pointer moved on a publish that failed"


async def test_an_engine_that_drops_the_disclosure_line_is_refused_by_name() -> None:
    """Hard rule 5 is the property with a legal consequence, so it is checked
    SEPARATELY from the script. Here the script lands and only the greeting is lost —
    a read-back that scored the prompt alone would call this a success."""
    tenant_id, agent_id = await _publishable_agent()
    with _engine(DisclosureDroppingEngine()) as engine, pytest.raises(ProblemError) as exc:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert exc.value.code == "engine_publish_not_applied"
    assert "greeting disclosure" in exc.value.detail
    assert isinstance(engine, RecordingEngine)
    assert engine.names() == ["create_agent", "get_agent"]

    # An agent that never got a confirmed publish is not live, and says so.
    state, verified, status, ref = await _verify_row(tenant_id, agent_id)
    assert (state, verified, status, ref) == ("unverified", False, "draft", None)


async def test_the_disclosure_verdict_reads_the_field_that_speaks_not_the_one_we_wrote() -> None:
    """P3.3, and the only test in this file that could have caught it.

    The engine here keeps the disclosure line in the PROMPT — where our own adapter
    prepends it — and drops it from the GREETING, which is the deterministic first
    utterance and the only one a caller actually hears. Every other fake in this file
    mutates the config wholesale, so prompt and greeting fail together and either one
    scored green looks the same.

    Before this change the verdict was `carries_prompt_marker(cfg.opening_line)`
    against a prompt WE had just prepended the line to, so it was true whenever the
    prompt round-tripped at all. The publish below would have been confirmed `applied`,
    the agent would have gone live, and OPERATIONS §7's escalation on
    `disclosure_applied: false` could never have fired for its own reason.
    """
    tenant_id, agent_id = await _publishable_agent()
    with _engine(GreetingOnlyDroppingEngine()), pytest.raises(ProblemError) as exc:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert exc.value.code == "engine_publish_not_applied"
    assert "greeting disclosure" in exc.value.detail
    assert "script" not in exc.value.detail, (
        "the script DID land — naming it would send an operator to the wrong field"
    )
    state, verified, status, ref = await _verify_row(tenant_id, agent_id)
    assert (state, verified, status, ref) == ("unverified", False, "draft", None)


def test_the_prompt_copy_is_reported_but_never_refuses_a_publish() -> None:
    """The other half of the split, and it must NOT be a gate.

    Both adapters send the disclosure twice — greeting and prompt — deliberately. But a
    prompt is a long rendered document, and an engine that normalises whitespace or wraps
    it in its own headers has not broken hard rule 5 as long as the greeting stands. If
    the prompt copy joined the refusal set, every such engine would fail every publish on
    a compliance ground it did not actually breach, and the verdict would be the first
    thing an operator learned to override.
    """
    cfg = _cfg()
    # No prepended line — but the platform rules stay, because D-163 made those a
    # refusal in their own right and dropping both here would prove the wrong thing.
    greeting_only = _snapshot(
        cfg, system_prompt=f"{cfg.system_prompt}\n\n{TRUTHFUL_ANSWER_DIRECTIVE}"
    )

    verdict = judge(FakeEngine(), cfg, greeting_only)

    assert verdict.state == "applied", "the greeting carries the obligation and it is intact"
    assert verdict.disclosure_applied is True
    assert verdict.prompt_disclosure_applied is False, (
        "the missing second copy is a fact worth recording, and it is recorded"
    )


def test_a_greeting_the_adapter_cannot_find_is_never_confirmed() -> None:
    """`unreadable`, never `applied` — the finding says this in as many words.

    An adapter that could not locate the greeting field has learned nothing about the
    disclosure, and the one outcome that must be impossible is the green tick. It is also
    not a REFUSAL: an adapter looking in the wrong place is our defect, and failing every
    publish on it would take a client offline for a field name.
    """
    cfg = _cfg()
    blind = _snapshot(cfg, greeting=None, greeting_readable=False)

    verdict = judge(FakeEngine(), cfg, blind)

    assert verdict.state == "unreadable"
    assert verdict.disclosure_applied is None
    assert verdict.proven is False


def test_an_engine_holding_an_empty_greeting_is_a_refusal_not_a_shrug() -> None:
    """The distinction the `(value, readable)` pair in both adapters exists for.

    A greeting key present and EMPTY is an agent that opens the call saying nothing —
    provably not compliant, and exactly the shape a vendor dropping an unrecognised field
    leaves behind. Collapsing it into `readable=False` would turn the one provable
    failure on this path into a recorded uncertainty that does not block the publish.
    """
    cfg = _cfg()
    silent = _snapshot(cfg, greeting="", greeting_readable=True)

    verdict = judge(FakeEngine(), cfg, silent)

    assert verdict.state == "not_applied"
    assert verdict.disclosure_applied is False


async def test_an_engine_speaking_a_voice_nobody_chose_is_refused() -> None:
    tenant_id, agent_id = await _publishable_agent()
    with _engine(VoiceDroppingEngine()) as engine, pytest.raises(ProblemError) as exc:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert exc.value.code == "engine_publish_not_applied"
    assert "voice" in exc.value.detail
    assert isinstance(engine, RecordingEngine)
    assert engine.names() == ["create_agent", "get_agent"]

    # The MIRROR was not written either — `live_tts_voice` must never record a voice the
    # engine was observed not to be holding.
    async with tenant_session(tenant_id) as session:
        live = (
            await session.execute(
                text("SELECT live_tts_voice, status FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).first()
    assert live is not None
    assert live[0] is None and live[1] == "draft"


# --- 3. an UNPROVEN publish is recorded, never rounded up --------------------


async def test_an_unreadable_read_back_is_recorded_and_not_counted_as_confirmation() -> None:
    """ "We could not tell" is neither a match nor a mismatch. It must not block the
    publish — the write has already happened at the vendor, and refusing here would
    trade a recorded uncertainty for a guaranteed orphan plus the same uncertainty —
    and it must not be displayed as a confirmation."""
    tenant_id, agent_id = await _publishable_agent()
    with _engine(UnreadableEngine()) as engine:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert isinstance(engine, RecordingEngine)
    assert "get_agent" in engine.names(), "the read-back must still be attempted"

    state, verified, status, ref = await _verify_row(tenant_id, agent_id)
    assert state == "unreadable"
    assert verified is False, "an unread property is not a passed one"
    assert (status, bool(ref)) == ("live", True)

    shown = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert shown.engine_verification.confirmed is False
    assert shown.engine_verification.verified_at is None
    assert "did not report back enough" in shown.engine_verification.headline


async def test_a_read_back_that_never_answered_is_recorded_as_unreachable() -> None:
    tenant_id, agent_id = await _publishable_agent()
    with _engine(UnreachableEngine()) as engine:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert isinstance(engine, RecordingEngine)
    assert engine.names() == ["create_agent", "get_agent"]

    state, verified, status, _ = await _verify_row(tenant_id, agent_id)
    assert (state, verified, status) == ("unreachable", False, "live")

    shown = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert shown.engine_verification.confirmed is False
    assert "did not answer" in shown.engine_verification.headline


async def test_an_agent_published_before_the_column_existed_says_unverified() -> None:
    """The default, and it is a distinct answer from `unreachable`: nobody tried, as
    opposed to somebody tried and could not. Both refuse to claim confirmation, and an
    operator chasing a silent agent needs to know which one they are looking at."""
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()):
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET live_verify_state = 'unverified', live_verified_at = NULL "
                "WHERE id = :a"
            ),
            {"a": agent_id},
        )

    shown = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert shown.engine_verification.state == "unverified"
    assert shown.engine_verification.confirmed is False
    assert "never been confirmed" in shown.engine_verification.headline


async def test_an_unpublished_agent_has_nothing_to_confirm() -> None:
    tenant_id, agent_id = await _publishable_agent()
    shown = await publishing.pending_state_for(tenant_id=tenant_id, agent_id=agent_id)
    assert shown.published is False
    assert shown.engine_verification.confirmed is False
    assert "nothing to confirm" in shown.engine_verification.headline


# --- 4. concurrency: the lock, and the orphan it prevents --------------------


async def test_two_concurrent_publishes_create_exactly_one_vendor_agent() -> None:
    """THE ORPHAN, at its most likely cause.

    `publish_agent` is a read-then-write over `engine_agent_ref`: read "no ref", ask the
    vendor to create one, write it back. Two publishes interleaving there both see "no
    ref" and both create, and we can record exactly one — the other is an object we are
    billed for, cannot address and have no record of.

    A CAS cannot cover this window: the value being decided does not exist until after
    the side effect. So `_load_agent(for_update=True)` takes the row lock, and this is
    the test that can see it — `FakeEngine`'s deterministic ref would make a double
    create look idempotent, so the double here mints a fresh id per create exactly as a
    vendor does.
    """
    tenant_id, agent_id = await _publishable_agent()

    async def once() -> str:
        async with tenant_session(tenant_id) as session:
            return await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    with _engine(FreshRefEngine()) as engine:
        refs = await asyncio.gather(once(), once())

    assert isinstance(engine, RecordingEngine)
    creates = [ref for name, ref in engine.calls if name == "create_agent"]
    assert len(creates) == 1, (
        f"two publishes created {len(creates)} vendor agents; "
        f"{len(creates) - 1} of them are orphans nobody can address or delete"
    )
    assert refs[0] == refs[1] == creates[0]
    assert engine.names().count("update_agent") == 1, "the second publish must UPDATE, not create"

    _, _, _, stored = await _verify_row(tenant_id, agent_id)
    assert stored == creates[0]


async def test_a_publish_racing_a_soft_delete_refuses_rather_than_resurrecting() -> None:
    """The vendor's object outlives our row, and `deleted_at IS NULL` is what stands
    between a deleted agent and a caller.

    `_load_agent` filters on it; the UPDATE that writes `engine_agent_ref`,
    `status = 'live'` and the routing row used to name the id ALONE. So a delete landing
    between the two would be silently undone — a deleted agent back to `live`, with a
    routing row making the vendor's next inbound webhook resolve to it.

    THE DELETE IS APPLIED ON THE PUBLISH'S OWN CONNECTION, and that is the accurate
    simulation rather than a shortcut. Under READ COMMITTED a delete committed by another
    session between the load and the UPDATE is indistinguishable, from inside this
    transaction, from one applied on it — the row simply no longer satisfies
    `deleted_at IS NULL` when the UPDATE runs. Issuing it from a second session is what
    would be inaccurate here: `_load_agent(for_update=True)` holds the row lock, so a
    genuinely concurrent delete BLOCKS until the publish commits and can never land in
    the window at all. That is the lock doing its job, and it is why this guard is a
    floor under the lock rather than a duplicate of it.
    """
    tenant_id, agent_id = await _publishable_agent()

    async with tenant_session(tenant_id) as session:

        class DeletingEngine(RecordingEngine):
            """Deletes the agent during the vendor call — the long call, and so the
            moment a real race lands."""

            async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
                ref = await super().create_agent(cfg)
                await session.execute(
                    text("UPDATE agents SET deleted_at = now() WHERE id = :a"), {"a": agent_id}
                )
                return ref

        # Caught by hand rather than with `pytest.raises`, so the STATE assertions below
        # run whichever way the publish went. `raises` alone would stop at "did not
        # raise" and never say what the missing refusal actually left behind, which is
        # the half a reader needs to understand the defect.
        refusal: ProblemError | None = None
        with _engine(DeletingEngine()) as engine:
            try:
                await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
            except ProblemError as exc:
                refusal = exc

        assert isinstance(engine, RecordingEngine)
        assert "create_agent" in engine.names()

        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref, deleted_at FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).first()
        routes = (
            await session.execute(
                text("SELECT count(*) FROM engine_agent_routes WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar_one()
        assert row is not None
        assert row[0] != "live", "a deleted agent was resurrected as live"
        assert row[1] is None, "a deleted agent was given an engine ref"
        assert row[2] is not None, "the delete was undone"
        assert routes == 0, "a deleted agent got a routing row an inbound webhook resolves to"
        assert refusal is not None, "the publish reported success for an agent that was deleted"
        assert refusal.code == "agent_deleted_during_publish"


async def test_a_republish_racing_a_soft_delete_refuses_and_reports_no_orphan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The same race on the RE-publish, where the refusal is right and the orphan cry
    would be wrong.

    `publish_agent` reaches its rowcount guard by two roads. On a first publish the
    vendor object was created inside this transaction, so a rollback strands it and
    `_reclaim_orphan` is the only thing that can still reach it. On a re-publish nothing
    was created — `engine_agent_ref` was already ours and is still in the row the rollback
    restores — so the object remains addressable and nothing is stranded. Compensating
    here would be WORSE than a false alarm now that the compensation is a real delete: it
    would remove a live agent's vendor object because its republish lost a race.

    Worth its own test rather than a parameter on the one above, because the two arms
    disagree about what happened rather than about a value: the refusal is identical and
    the compensation is not.
    """
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()) as first:
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert isinstance(first, RecordingEngine)
    assert first.names() == ["create_agent", "get_agent"], "the setup publish must CREATE"

    async with tenant_session(tenant_id) as session:

        class DeletingEngine(RecordingEngine):
            """Deletes the agent during the vendor call, as above — but this publish
            UPDATEs an object that already exists, so `created` is False."""

            async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
                await super().update_agent(ref, cfg)
                await session.execute(
                    text("UPDATE agents SET deleted_at = now() WHERE id = :a"), {"a": agent_id}
                )

        refusal: ProblemError | None = None
        caplog.clear()
        with caplog.at_level("ERROR"), _engine(DeletingEngine()) as engine:
            try:
                await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
            except ProblemError as exc:
                refusal = exc

        assert isinstance(engine, RecordingEngine)
        assert "update_agent" in engine.names(), "this arm must not have created anything"
        assert "create_agent" not in engine.names()

        row = (
            await session.execute(
                text("SELECT status, deleted_at FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).first()

    assert refusal is not None, "the publish reported success for an agent that was deleted"
    assert refusal.code == "agent_deleted_during_publish"
    assert row is not None and row[1] is not None, "the delete was undone"
    assert not [r for r in caplog.records if "orphan" in r.getMessage().lower()], (
        f"a re-publish of the already-created {ref} reported an orphan; the vendor object "
        "is still addressable through the ref the rollback restored, and an operator sent "
        "to hunt it finds nothing missing"
    )


# --- 5. reconciliation: drift the publish path structurally cannot see -------


async def test_an_agent_edited_in_the_vendors_dashboard_is_reported_as_drift() -> None:
    """Nothing of ours ran, so no table of ours can know. The only instrument is a read
    of THEIRS, and it is a read: it reports, it does not re-publish."""
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()) as engine:
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

        clean = await publishing.engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)
        assert clean.in_sync is True
        assert clean.state == "applied"
        assert clean.engine_agent_ref == ref

        # Somebody edits the agent on the vendor's console. Our rows are untouched.
        engine._agents[ref] = engine._agents[ref].model_copy(
            update={"system_prompt": "Whatever the vendor's console was used to write."}
        )
        drifted = await publishing.engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)

    assert drifted.in_sync is False
    assert drifted.state == "not_applied"
    assert drifted.prompt_applied is False
    assert "different script" in drifted.detail
    # A READ. The engine still holds the vendor's edit; nothing re-published over it.
    assert engine._agents[ref].system_prompt.startswith("Whatever the vendor")


async def test_drift_on_an_unpublished_agent_is_not_a_failure() -> None:
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()) as engine:
        drift = await publishing.engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)
    assert drift.checked is False
    assert drift.state == "not_published"
    assert drift.in_sync is False
    assert isinstance(engine, RecordingEngine)
    assert engine.names() == [], "an unpublished agent must not cost a vendor round trip"


async def test_a_soft_deleted_agent_is_invisible_to_the_reconciliation_read() -> None:
    """`AND a.deleted_at IS NULL` in `_load_agent` is the only thing between a deleted
    agent and a caller, and the drift read goes through it. Verified rather than
    assumed, because this read is new and reaches the engine."""
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()):
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET deleted_at = now() WHERE id = :a"), {"a": agent_id}
        )

    with _engine(RecordingEngine()) as engine, pytest.raises(ProblemError) as exc:
        await publishing.engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)
    assert exc.value.code == "not_found"
    assert isinstance(engine, RecordingEngine)
    assert engine.names() == []


# --- 6. `judge` on its own: the capability-restricted engine -----------------


def _cfg(**kw: Any) -> AgentConfig:
    base = {
        "tenant_id": str(uuid.uuid4()),
        "agent_id": str(uuid.uuid4()),
        "name": "Sunrise Clinic receptionist",
        "direction": "inbound",
        "system_prompt": SCRIPT,
        # D-163: the composed opening — both notices on, which is what a new agent is
        # born with. `opening_line`, not `disclosure_line`: the field is what the agent
        # SAYS FIRST, and it may legitimately be empty when a tenant volunteers neither.
        "opening_line": "Idi AI assistant. Ee call record avutundi.",
        "models": ModelConfig(tts_provider="sarvam", tts_voice=VOICE),
    }
    return AgentConfig(**{**base, **kw})


def _snapshot(cfg: AgentConfig, **kw: Any) -> AgentSnapshot:
    """A healthy read-back: the engine holds the prompt AND the greeting.

    THE GREETING IS IN THE BASE, and its absence is how P3.3 survived. This helper used
    to build a snapshot with the prompt alone, which is what every adapter's read-back
    looked like — no greeting field existed on `AgentSnapshot` at all — so the disclosure
    verdict had nowhere to read but the prompt our own adapter prepends the line to. A
    fixture that cannot express the failure is a fixture that certifies the wrong
    behaviour, and every test below rested on this one.
    """
    base: dict[str, Any] = {
        "engine_agent_ref": "ref_1",
        # Through `compose_engine_prompt`, exactly as every adapter renders it — opening
        # line prepended, platform rules appended (D-163). A fixture that omitted the
        # rules would report `not_applied` on every healthy publish, which is the mirror
        # of the P3.3 defect this helper's docstring records.
        "system_prompt": compose_engine_prompt(cfg),
        "system_prompt_readable": True,
        "greeting": cfg.opening_line,
        "greeting_readable": True,
        "models": cfg.models,
        "models_readable": True,
    }
    return AgentSnapshot(**{**base, **kw})


def test_a_dictated_speech_engine_is_not_scored_on_a_voice_it_never_took() -> None:
    """`DICTATED_SPEECH_CAPABILITIES`: the engine supplies its own voices, so
    `AgentSnapshot.models.tts_voice` is None BY CONTRACT — reporting the engine's own
    product name there would smuggle a vendor string across the boundary.

    Comparing against it anyway would score every publish on such an engine as a
    mismatch, which is how an operator learns to ignore the verdict. The leg is skipped
    because there was no claim to check, not because the check was softened."""
    dictating = FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)
    cfg = _cfg(models=ModelConfig(llm_model="sarvam-105b"))
    snapshot = _snapshot(cfg, models=ModelConfig(llm_model="sarvam-105b"))

    verdict = judge(dictating, cfg, snapshot)
    assert verdict.state == "applied"
    assert verdict.voice_applied is True

    byok = FakeEngine()
    assert judge(byok, cfg, snapshot).state == "applied", (
        "a config with no voice asks nothing of the TTS leg on either engine"
    )


def test_an_unreadable_leg_is_neither_a_pass_nor_a_fail() -> None:
    cfg = _cfg()
    unreadable = _snapshot(cfg, models=None, models_readable=False)
    verdict = judge(FakeEngine(), cfg, unreadable)
    assert verdict.state == "unreadable"
    assert verdict.voice_applied is None
    assert verdict.proven is False


def test_a_verified_publish_is_not_an_equality_check_on_our_own_formatting() -> None:
    """CONTAINMENT, not equality. Every engine renders our config into its own object —
    ours PREPENDS the disclosure line — so an equality check would fail on a correctly
    applied update and turn this into a test of our string formatting."""
    cfg = _cfg()
    rendered = _snapshot(
        cfg,
        system_prompt=(f"### SYSTEM\n{compose_engine_prompt(cfg)}\n\n### END"),
    )
    assert judge(FakeEngine(), cfg, rendered).state == "applied"


def test_a_not_applied_verdict_can_never_reach_a_column() -> None:
    """The schema cannot express it, and neither can the code path: a proven mismatch is
    a refusal, so the transaction that would store it does not commit."""
    cfg = _cfg()
    wrong = _snapshot(cfg, system_prompt="Something else entirely.")
    verdict = judge(FakeEngine(), cfg, wrong)
    assert verdict.state == "not_applied"
    with pytest.raises(AssertionError):
        _ = verdict.stored_state


# --- 7. tenancy (hard rule 1) ------------------------------------------------


async def test_a_second_tenant_cannot_read_or_write_the_verification_columns() -> None:
    """The migration adds two columns to a tenant-scoped table, so the isolation claim
    is measured rather than inherited — the shape `agent_voice_test` uses for
    `live_tts_voice`. READ and WRITE both, because a policy that leaks on one is a
    different bug from one that leaks on the other."""
    tenant_id, agent_id = await _publishable_agent()
    with _engine(RecordingEngine()):
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    other_id, _ = await _tenant()

    async with tenant_session(other_id) as session:
        seen = (
            await session.execute(
                text("SELECT live_verify_state, live_verified_at FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).all()
        assert seen == [], "another tenant read the verification columns"

        written = await session.execute(
            text(
                "UPDATE agents SET live_verify_state = 'applied', live_verified_at = now() "
                "WHERE id = :a RETURNING id"
            ),
            {"a": agent_id},
        )
        assert written.all() == [], "another tenant wrote the verification columns"

    state, _, _, _ = await _verify_row(tenant_id, agent_id)
    assert state == "applied"


# --- 8. the ARM gets the same treatment, and the ratchet is what asked -----------------
#
# WHY THIS SECTION EXISTS. The hardening pass gave `publish_variant` the same read-back,
# the same refusal and the same orphan log as `publish_agent`, and tested none of it: the
# coverage ratchet reported `dial-path` at 7 uncovered against a budget of 1, and six of
# those were this function's refusal branch. D-29's rule is that the number only shrinks
# on a hard-rule-5 surface, so the branch gets covered rather than waived.
#
# An arm is not a lesser path. `assignment.py` hands real callers to an arm's own engine
# agent, with the arm's own script and its own disclosure line — so an arm the engine
# silently failed to apply is a live caller hearing the wrong script, and the disclosure
# is a legal obligation on that call exactly as it is on the agent's.


async def _running_arm(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    """One arm of a running experiment, as `republish_running_variants` would find it."""
    variant_id = uuid7()
    experiment_id = uuid7()
    async with tenant_session(tenant_id) as session:
        prompt_id = (
            await session.execute(
                text("SELECT id FROM prompt_versions WHERE agent_id = :a ORDER BY version DESC"),
                {"a": agent_id},
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO prompt_experiments (id, tenant_id, agent_id, name, status, "
                "conversion_metric, started_at, created_at, updated_at) VALUES (:i, :t, :a, "
                "'price test', 'running', 'lead_won', now(), now(), now())"
            ),
            {"i": experiment_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO prompt_experiment_variants (id, tenant_id, experiment_id, label, "
                "prompt_version_id, disclosure_line, weight_bp, created_at, updated_at) "
                "VALUES (:i, :t, :e, 'B', :p, :d, 5000, now(), now())"
            ),
            {
                "i": variant_id,
                "t": tenant_id,
                "e": experiment_id,
                "p": prompt_id,
                "d": "Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi.",
            },
        )
    return variant_id, "Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi."


async def test_an_arm_the_engine_did_not_apply_is_refused_like_the_agent() -> None:
    """The refusal, on the path that actually answers callers during a test.

    Driven through `publish_variant` directly rather than through `publish_agent`'s
    republish loop, because the loop would refuse at the AGENT first and this test would
    then be about the agent again — passing for the wrong reason, which is the failure
    mode this whole file exists to close.
    """
    tenant_id, agent_id = await _publishable_agent()
    variant_id, disclosure = await _running_arm(tenant_id, agent_id)

    with _engine(SilentlyDroppingEngine()) as engine:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as exc:
                await publish_variant(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    variant_id=variant_id,
                    label="B",
                    body=SCRIPT,
                    disclosure_line=disclosure,
                    existing_ref=None,
                )
    assert exc.value.code == "engine_publish_not_applied"
    assert isinstance(engine, RecordingEngine)
    assert engine.names() == ["create_agent", "get_agent"], (
        "the arm was published without ever being read back"
    )

    # Nothing recorded. An arm whose ref was stored after a proven mismatch would be
    # dialled by `assignment.py` on the next call.
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT engine_agent_ref FROM prompt_experiment_variants WHERE id = :v"),
                {"v": variant_id},
            )
        ).scalar()
    assert stored is None


async def test_a_first_publish_of_an_arm_that_fails_verification_reclaims_the_orphan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The compensation is now a DELETE, not a note for a human (D-123).

    This test used to assert an ERROR line naming a ref, because `VoiceEngine` could
    create, update and read an agent and could not remove one. `delete_agent` closed that,
    so the assertion moved from "the orphan was recorded" to "the orphan is GONE FROM THE
    ENGINE" — which is checked against the engine's own state, not against our log,
    because a log line is exactly what this change exists to stop being the remedy.

    Only on a CREATE: an update that fails verification leaves the ref we already had, so
    there is nothing orphaned and deleting anything would destroy a live arm. That
    asymmetry is the branch, and it is asserted in both directions below.
    """
    tenant_id, agent_id = await _publishable_agent()
    variant_id, disclosure = await _running_arm(tenant_id, agent_id)

    with caplog.at_level("DEBUG"), _engine(SilentlyDroppingEngine()) as engine:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError):
                await publish_variant(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    variant_id=variant_id,
                    label="B",
                    body=SCRIPT,
                    disclosure_line=disclosure,
                    existing_ref=None,
                )
        # THE ASSERTION THAT MATTERS: the vendor is not holding an object we cannot name.
        assert engine._agents == {}, (
            "the arm's vendor-side agent survived a publish that refused — it is billed "
            "for, unaddressable, and nothing in the system will ever collect it"
        )
    reclaimed = [r for r in caplog.records if r.getMessage() == "engine_agent_orphan_reclaimed"]
    assert reclaimed, "the reclaim happened and left no record an operator can find"

    # And the other direction: an UPDATE that fails verification orphans nothing, so it
    # must not cry orphan. A log that fires on both is a log an operator stops reading.
    caplog.clear()
    with caplog.at_level("DEBUG"), _engine(SilentlyDroppingEngine()):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError):
                await publish_variant(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    variant_id=variant_id,
                    label="B",
                    body=SCRIPT,
                    disclosure_line=disclosure,
                    existing_ref="arm_ref_we_already_had",
                )
    assert not [r for r in caplog.records if "orphan" in r.getMessage().lower()], (
        "an update that failed verification reported an orphan it did not create"
    )


async def test_a_refused_agent_publish_deletes_the_vendor_agent_it_created(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The same compensation on `publish_agent`, and the one that costs real money.

    `FreshRefEngine` is the substrate rather than the plain fake, for the reason D-121
    needed it: `FakeEngine` derives its ref from `(tenant_id, agent_id)`, so a create that
    is never recorded is indistinguishable from one that is — the ref would be
    re-derivable and nothing would be orphaned. A vendor mints a new id per create, and it
    is the un-re-derivable id that makes an orphan an orphan.
    """

    class FreshRefSilentlyDropping(FreshRefEngine):
        """Mints a new id per create AND does not run what it was sent: the exact pair
        that produces an unaddressable, billed-for, wrong-script agent."""

        async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
            ref = await super().create_agent(cfg)
            self._agents[ref] = cfg.model_copy(
                update={"system_prompt": "Whatever this agent had before."}
            )
            return ref

    tenant_id, agent_id = await _publishable_agent()
    with caplog.at_level("DEBUG"), _engine(FreshRefSilentlyDropping()) as engine:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as exc:
                await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        assert exc.value.code == "engine_publish_not_applied"
        assert engine._agents == {}, (
            "the vendor is still holding an agent whose only id died with the rolled-back "
            "transaction"
        )
    assert [r for r in caplog.records if r.getMessage() == "engine_agent_orphan_reclaimed"]


async def test_a_reclaim_the_vendor_refuses_falls_back_to_the_operator_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The remedy must never become a NEW way for the publish to fail.

    The vendor was misbehaving a moment ago — that is why we are compensating — so the
    delete is exactly the call most likely to fail next. When it does we must land back
    where we started and no further: the publish still refuses with its own code, and the
    ERROR line still carries the ref, because that line is the operator's only copy of an
    id that is about to be lost with the transaction.
    """

    class UndeletableEngine(FreshRefEngine):
        async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
            ref = await super().create_agent(cfg)
            self._agents[ref] = cfg.model_copy(update={"system_prompt": "Not what we sent."})
            return ref

        async def delete_agent(self, ref: EngineAgentRef) -> None:
            raise ProblemError(
                kind="dependency",
                code="engine_unreachable",
                title="Voice engine unreachable",
                detail="The voice platform did not respond.",
            )

    tenant_id, agent_id = await _publishable_agent()
    with caplog.at_level("DEBUG"), _engine(UndeletableEngine()) as engine:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as exc:
                await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    # The publish reports the PUBLISH failure, not the reclaim's.
    assert exc.value.code == "engine_publish_not_applied"
    orphaned = [r for r in caplog.records if r.getMessage() == "engine_agent_orphaned"]
    assert orphaned, "the reclaim failed and nobody was told which object leaked"
    assert getattr(orphaned[0], "reclaim_failed", None) == "ProblemError"
    # The ref an operator has to go and delete by hand is IN the record.
    assert getattr(orphaned[0], "engine_agent_ref", None) in engine._agents
    assert not [r for r in caplog.records if r.getMessage() == "engine_agent_orphan_reclaimed"]
