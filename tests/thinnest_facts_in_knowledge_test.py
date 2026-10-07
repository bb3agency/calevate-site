"""On ThinnestAI the business facts live in the agent's knowledge, not its prompt (D-678).

The founder's decision (6 Oct 2026): the `instructions` field (20,000 characters, re-sent
on every turn: `snapshots/2026-10-07/pages/api-reference/agents/update-agent.md:426-431`) holds
our platform rules and
the client's script; the script's [T0 FACTS] block is pushed as one knowledge document,
replaced on republish and removed when the facts go. Every other engine composes exactly as
before, which the pinned digests below hold byte for byte.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents.engine_facts import FACTS_TITLE
from apps.api.agents.engine_limits import refuse_over_engine_limits
from apps.api.agents.service import _load_agent, _to_config, publish_agent
from apps.api.agents.t0_block import T0_HEADER, block_of, without_block
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest import THINNEST_CAPABILITIES
from apps.api.kb.service import recorded_handles_of_agent
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    FACTS_IN_KNOWLEDGE_GUIDANCE,
    TRUTHFUL_ANSWER_MARKER,
    AgentConfig,
    EngineAgentRef,
    EngineKBRef,
    KBSourceRef,
    compose_engine_prompt,
)
from sqlalchemy import text
from tests.conftest import accept_agreements

FACTS = f"{T0_HEADER}\nHours: mon 09:30-18:00; sun closed\nService: Root canal - Rs 8000"
SCRIPT = f"[IDENTITY] Sunrise Clinic receptionist\n{FACTS}\n[TASK FLOW]\nGreet, then book.\n"


# --- every other engine: byte-identical -------------------------------------------

#: sha256 of `compose_engine_prompt` for the two configs below, taken from the composer
#: BEFORE `facts_in_knowledge` existed. A change here is a change to every Pipecat prompt.
PINNED = (
    "6375e0531296d45c580bcb689e5b632f7ef77f57316c6083f5a5e6cbdcd29e70",
    "2488b22cd8c8f850afdee8a7fb9ef9065c13973d093f456e70e07ce1cc5692f6",
)


def _pinned_cfg(**kw: Any) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Sunrise",
        direction="both",
        system_prompt=SCRIPT,
        opening_line="Idi AI assistant. Ee call record avutundi.",
        **kw,
    )


def test_the_composition_without_facts_in_knowledge_is_byte_identical() -> None:
    configs = (
        _pinned_cfg(),
        _pinned_cfg(
            languages_extra=["hi-IN", "en-IN"], caller_memory_enabled=True, call_is_recorded=False
        ),
    )
    digests = tuple(hashlib.sha256(compose_engine_prompt(c).encode()).hexdigest() for c in configs)
    assert digests == PINNED


def test_the_block_helpers_take_out_exactly_the_facts() -> None:
    assert block_of(SCRIPT) == FACTS
    stripped = without_block(SCRIPT)
    assert T0_HEADER not in stripped and "Root canal" not in stripped
    assert "[IDENTITY]" in stripped and "[TASK FLOW]\nGreet, then book." in stripped
    assert without_block("No block here.") == "No block here."


# --- the config each engine is given ------------------------------------------------


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "Reception",
        "direction": "inbound",
        "language_primary": "te-IN",
        "languages_extra": None,
        "prompt": SCRIPT,
        "ai_disclosure_line": "This is an AI assistant.",
        "ai_disclosure_enabled": True,
        "recording_notice_line": "This call is recorded.",
        "recording_notice_enabled": True,
        "caller_memory_notice_line": "I keep a short note of what you ask about.",
        "caller_memory_enabled": False,
        "stt_provider": None,
        "stt_model": None,
        "llm_model": None,
        "organization_llm_model": None,
        "tts_provider": None,
        "tts_voice": None,
        "max_call_duration_s": 600,
    }
    return {**row, **over}


def _thinnest() -> FakeEngine:
    return FakeEngine(name="thinnest", capabilities=THINNEST_CAPABILITIES)


def test_the_thinnest_prompt_has_no_facts_block_and_says_where_they_are() -> None:
    cfg = _to_config(uuid.uuid4(), _row(), engine=_thinnest())  # type: ignore[arg-type]
    prompt = compose_engine_prompt(cfg)
    assert cfg.facts_in_knowledge
    assert T0_HEADER not in prompt and "Root canal" not in prompt
    assert FACTS_IN_KNOWLEDGE_GUIDANCE in prompt
    # Every hard-rule block stays, in its place.
    assert TRUTHFUL_ANSWER_MARKER in prompt and CONFIDENTIALITY_MARKER in prompt
    assert prompt.index(FACTS_IN_KNOWLEDGE_GUIDANCE) < prompt.index(CONFIDENTIALITY_MARKER)
    refuse_over_engine_limits(_thinnest(), cfg)


def test_a_long_facts_block_no_longer_costs_the_prompt_cap() -> None:
    facts = FACTS + "".join(f"\nService {i}: a treatment - Rs {i}00" for i in range(800))
    script = f"[IDENTITY] Sunrise Clinic receptionist\n{facts}\n[TASK FLOW]\nGreet.\n"
    assert len(script) > 20_000
    cfg = _to_config(uuid.uuid4(), _row(prompt=script), engine=_thinnest())  # type: ignore[arg-type]
    assert len(compose_engine_prompt(cfg)) <= 20_000
    refuse_over_engine_limits(_thinnest(), cfg)


def test_any_other_engine_keeps_the_facts_in_the_prompt() -> None:
    for engine in (FakeEngine(name="pipecat"), FakeEngine()):
        cfg = _to_config(uuid.uuid4(), _row(), engine=engine)  # type: ignore[arg-type]
        assert not cfg.facts_in_knowledge
        assert FACTS in cfg.system_prompt
        assert FACTS_IN_KNOWLEDGE_GUIDANCE not in compose_engine_prompt(cfg)


# --- the facts document on publish --------------------------------------------------


class _KbEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__(name="thinnest", capabilities=THINNEST_CAPABILITIES)
        self.attached: list[tuple[str, str]] = []
        self.detached: list[str] = []

    async def attach_kb(
        self, ref: EngineAgentRef, source: KBSourceRef, *, agent: AgentConfig | None = None
    ) -> EngineKBRef:
        handle = await super().attach_kb(ref, source, agent=agent)
        self.attached.append((source.title, source.text))
        return handle

    async def detach_kb(
        self, ref: EngineAgentRef, kb: EngineKBRef, *, agent: AgentConfig | None = None
    ) -> None:
        await super().detach_kb(ref, kb, agent=agent)
        self.detached.append(kb)


@contextmanager
def _selected(instance: FakeEngine) -> Iterator[FakeEngine]:
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


@pytest.fixture(autouse=True)
def _priced_and_no_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.agents import engine_limits, service

    async def _priced(session: Any, *, engine: str, rate_key: str, at: Any) -> bool:
        return True

    async def _ensure(session: Any, *, engine: str, engine_agent_ref: str) -> None:
        return None

    monkeypatch.setattr(engine_limits, "engine_minute_is_billable", _priced)
    monkeypatch.setattr(service, "ensure_agent_webhook", _ensure)
    monkeypatch.setattr(service, "ensure_agent_actions", _ensure)


async def _agent(script: str) -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Facts Clinic",
        slug=f"fct-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    await accept_agreements(uuid.UUID(str(tenant_id)))
    await _write(tenant_id, agent_id, script)
    return tenant_id, agent_id


async def _write(tenant_id: uuid.UUID, agent_id: uuid.UUID, script: str) -> None:
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=script,
            notes=None,
            created_by=None,
        )
        # Applied, so the publish reads it (`live_prompt_id` is what `_load_agent` prefers).
        await session.execute(
            text("UPDATE agents SET live_prompt_id = system_prompt_id WHERE id = :a"),
            {"a": agent_id},
        )


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, engine: FakeEngine) -> str:
    with _selected(engine):
        async with tenant_session(tenant_id) as session:
            return await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def _recorded(tenant_id: uuid.UUID, ref: str) -> tuple[str | None, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT facts_kb_ref, facts_digest FROM engine_agent_routes "
                    "WHERE engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).one()
    return row[0], row[1]


async def test_publish_creates_replaces_and_removes_the_facts_document() -> None:
    tenant_id, agent_id = await _agent(SCRIPT)
    engine = _KbEngine()

    ref = await _publish(tenant_id, agent_id, engine)
    assert engine.attached == [(FACTS_TITLE, FACTS)]
    first, digest = await _recorded(tenant_id, ref)
    assert first is not None and digest is not None
    assert first in await engine.list_kb(ref)
    async with tenant_session(tenant_id) as session:
        assert first in await recorded_handles_of_agent(session, agent_id)

    # The same facts again: nothing is sent.
    await _publish(tenant_id, agent_id, engine)
    assert len(engine.attached) == 1 and engine.detached == []

    # New facts: the new document is attached and the old one removed — one copy only.
    await _write(tenant_id, agent_id, SCRIPT.replace("Rs 8000", "Rs 9000"))
    await _publish(tenant_id, agent_id, engine)
    second, _ = await _recorded(tenant_id, ref)
    assert second is not None and second != first
    assert engine.detached == [first]
    assert await engine.list_kb(ref) == [second]

    # No facts any more: the document goes and the row forgets it.
    await _write(tenant_id, agent_id, "[IDENTITY] Sunrise Clinic receptionist\nGreet, then book.\n")
    await _publish(tenant_id, agent_id, engine)
    assert engine.detached == [first, second]
    assert await engine.list_kb(ref) == []
    assert await _recorded(tenant_id, ref) == (None, None)


async def test_the_published_prompt_lacks_the_facts_and_passes_the_read_back() -> None:
    tenant_id, agent_id = await _agent(SCRIPT)
    engine = _KbEngine()
    ref = await _publish(tenant_id, agent_id, engine)
    snapshot = await engine.get_agent(ref)
    assert snapshot.system_prompt is not None
    assert T0_HEADER not in snapshot.system_prompt
    assert FACTS_IN_KNOWLEDGE_GUIDANCE in snapshot.system_prompt
    async with tenant_session(tenant_id) as session:
        agent = await _load_agent(session, tenant_id, agent_id)
    assert block_of(agent["prompt"]) == FACTS, "our own record keeps the facts"


async def test_pipecat_never_gets_a_facts_document() -> None:
    tenant_id, agent_id = await _agent(SCRIPT)
    engine = FakeEngine(name="pipecat")
    ref = await _publish(tenant_id, agent_id, engine)
    assert await _recorded(tenant_id, ref) == (None, None)
