"""The AI and recording notices said in the agent's own opening line (D-971).

Founder, 5 Nov 2026: "When an opening is saved, Pip weaves the notices into that agent's own
opening line in its own words, which the engine then speaks." Lines here are English; the
model writes the other languages. The model leg is replaced at the writer's seam.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_builder
from apps.api.agents.opening_notices import WEAVE_JOB
from apps.api.agents.publishing import set_disclosure_posture
from apps.api.agents.roster import agent_by_id
from apps.api.agents.verification import judge
from apps.api.compliance import service as compliance_service
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from apps.workers import opening_line
from apps.workers import opening_notices as weave_worker
from apps.workers.script_assist import JsonAnswer, ScriptBrief, UnusableAnswerError
from calevate_shared.call_script import SCRIPT_SCHEMA_VERSION, CallScript, compile_call_script
from calevate_shared.engine import (
    AgentConfig,
    AgentSnapshot,
    DisclosurePosture,
    compose_engine_prompt,
    compose_first_utterance,
    join_first_words,
    notice_fields,
)
from calevate_shared.opening_notices import WOVEN_AI_RULE, WovenNotices
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

AI = "This is the AI assistant for Raghava Organics."
RECORDING = "This call is being recorded."
PLAIN = "Hello, Raghava Organics here. What would you like to order today?"
WOVEN = "Hello, I am the AI assistant at Raghava Organics. What would you like to order today?"
WOVEN_BOTH = (
    "Hello, I am the AI assistant at Raghava Organics and this call is recorded. "
    "What would you like to order today?"
)


def _posture(*, ai: bool, recording: bool = False) -> DisclosurePosture:
    return DisclosurePosture(
        ai_disclosure_line=AI,
        ai_disclosure_enabled=ai,
        recording_notice_line=RECORDING,
        recording_notice_enabled=recording,
    )


def _first(opening: str, *, ai: bool, recording: bool = False) -> str:
    fields = notice_fields(_posture(ai=ai, recording=recording), call_is_recorded=True)
    return join_first_words(
        fields["opening_line"], opening, ai_notice=fields["ai_notice"], language="en-IN"
    )


# --- what the caller hears ----------------------------------------------------------------


def test_switch_on_and_the_opening_says_it_the_opening_alone_is_spoken() -> None:
    assert _first(WOVEN, ai=True) == WOVEN
    assert _first(WOVEN_BOTH, ai=True, recording=True) == WOVEN_BOTH


def test_switch_on_and_the_opening_not_yet_rewritten_the_stored_sentence_is_spoken() -> None:
    assert _first(PLAIN, ai=True) == f"{PLAIN} {AI}"
    assert _first(PLAIN, ai=True, recording=True) == f"{PLAIN} {AI} {RECORDING}"
    # Only the notice the line does not say is added.
    assert _first(WOVEN, ai=True, recording=True) == f"{WOVEN} {RECORDING}"


def test_switch_off_no_notice_is_spoken() -> None:
    assert _first(PLAIN, ai=False) == PLAIN


# --- the read-back and the dial ---------------------------------------------------------------


def _cfg(opening: str, *, ai: bool) -> AgentConfig:
    return AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name="Receptionist",
        direction="inbound",
        language_primary="en-IN",
        system_prompt=compile_call_script(CallScript(opening_line=opening), collect=[]),
        **notice_fields(_posture(ai=ai), call_is_recorded=True),
    )


def _held(cfg: AgentConfig, greeting: str) -> AgentSnapshot:
    return AgentSnapshot(
        engine_agent_ref="ag_1",
        system_prompt=compose_engine_prompt(cfg),
        system_prompt_readable=True,
        greeting=greeting,
        greeting_readable=True,
    )


def test_the_read_back_accepts_a_woven_greeting_and_refuses_one_without_the_notice() -> None:
    engine = FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    woven = _cfg(WOVEN, ai=True)
    assert compose_first_utterance(woven) == WOVEN
    assert judge(engine, woven, _held(woven, WOVEN)).state == "applied"
    plain = _cfg(PLAIN, ai=True)
    verdict = judge(engine, plain, _held(plain, PLAIN))
    assert verdict.state == "not_applied"
    assert "greeting disclosure" in verdict.detail


def _dial_row(opening: str, *, ai: bool) -> tuple[Any, ...]:
    body = compile_call_script(CallScript(opening_line=opening), collect=[])
    return (AI, "live", "outbound", "ag_1", ai, False, RECORDING, "en-IN", body)


def test_the_dial_gate_refuses_first_words_that_drop_the_ai_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disclose = compliance_service._first_words_disclose
    assert disclose(_dial_row(WOVEN, ai=True))  # type: ignore[arg-type]
    assert disclose(_dial_row(PLAIN, ai=True))  # type: ignore[arg-type]
    assert disclose(_dial_row(PLAIN, ai=False))  # type: ignore[arg-type]
    # A composer that lost the stored sentence is refused, not dialled.
    monkeypatch.setattr(compliance_service, "join_first_words", lambda _n, o, **_k: o)
    assert not disclose(_dial_row(PLAIN, ai=True))  # type: ignore[arg-type]


# --- the writer -------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_the_writer_is_told_to_say_it_and_a_line_without_it_is_sent_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = ScriptBrief(
        business_name="Raghava Organics",
        agent_name="Asha",
        language="en-IN",
        woven=WovenNotices(ai=True, recording=False),
    )
    asked: list[str] = []

    async def fake_ask(request: str, _instruction: str, *, parse: Any, **_kw: Any) -> Any:
        asked.append(request)
        with pytest.raises(UnusableAnswerError) as sent_back:
            parse({"opening_line": PLAIN})
        assert WOVEN_AI_RULE in str(sent_back.value)
        return JsonAnswer(value=parse({"opening_line": WOVEN}), capability=None)  # type: ignore[arg-type]

    monkeypatch.setattr(opening_line, "ask_json", fake_ask)
    answer = await opening_line.write_opening(brief, line=PLAIN, problems=["x"])
    assert answer.value == WOVEN
    assert WOVEN_AI_RULE in asked[0]


# --- switching a notice on and off, end to end ---------------------------------------------------


@contextmanager
def _on_thinnest() -> Iterator[None]:
    import apps.api.engine as engine_module

    reset_engine_cache()
    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = FakeEngine(
        name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES
    )
    try:
        yield
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


async def _agent(opening: str) -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Raghava Organics",
        slug=f"on-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(
                schema_version=SCRIPT_SCHEMA_VERSION, opening_line=opening, goal="Take the order."
            ),
            notes=None,
            created_by=None,
        )
        await session.execute(
            text(
                "UPDATE agents SET ai_disclosure_line = :ai, ai_disclosure_enabled = false, "
                "recording_notice_enabled = false WHERE id = :aid"
            ),
            {"aid": agent_id, "ai": AI},
        )
    return tenant_id, agent_id


async def _weave_jobs(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE job = :job ORDER BY created_at"),
                {"job": WEAVE_JOB},
            )
        ).all()
    payloads = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]
    return [p for p in payloads if p["agent_id"] == str(agent_id)]


async def _first_words(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        agent = await agent_by_id(session, agent_id)
    assert agent is not None
    return str(agent.first_words)


async def _weave(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], written: str
) -> tuple[str, list[ScriptBrief]]:
    briefs: list[ScriptBrief] = []

    async def fake_write(brief: ScriptBrief, **_kw: Any) -> Any:
        briefs.append(brief)
        return SimpleNamespace(value=written, capability=None, earlier=(), model=None)

    async def no_meter(_tenant_id: uuid.UUID, _spends: Any) -> None:
        return None

    monkeypatch.setattr(weave_worker, "write_opening", fake_write)
    monkeypatch.setattr(weave_worker, "_meter", no_meter)
    return await weave_worker.weave_opening_notices({}, payload), briefs


@pytest.mark.anyio
async def test_switching_on_speaks_the_sentence_until_pip_weaves_it_into_the_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _on_thinnest():
        tenant_id, agent_id = await _agent(PLAIN)
        await set_disclosure_posture(
            tenant_id=tenant_id,
            agent_id=agent_id,
            ai_disclosure_enabled=True,
            recording_notice_enabled=None,
        )
        assert await _first_words(tenant_id, agent_id) == f"{PLAIN} {AI}"
        jobs = await _weave_jobs(tenant_id, agent_id)
        assert len(jobs) == 1
        result, briefs = await _weave(monkeypatch, jobs[0], WOVEN)
        assert result == "woven"
        assert briefs[0].woven == WovenNotices(ai=True, recording=False)
        assert await _first_words(tenant_id, agent_id) == WOVEN
        # The rewritten line already says it: nothing more is queued for it.
        assert len(await _weave_jobs(tenant_id, agent_id)) == 1


@pytest.mark.anyio
async def test_switching_off_has_pip_take_the_notice_out(monkeypatch: pytest.MonkeyPatch) -> None:
    with _on_thinnest():
        tenant_id, agent_id = await _agent(WOVEN)
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET ai_disclosure_enabled = true WHERE id = :aid"),
                {"aid": agent_id},
            )
        assert await _first_words(tenant_id, agent_id) == WOVEN
        await set_disclosure_posture(
            tenant_id=tenant_id,
            agent_id=agent_id,
            ai_disclosure_enabled=False,
            recording_notice_enabled=None,
        )
        jobs = await _weave_jobs(tenant_id, agent_id)
        assert len(jobs) == 1
        result, briefs = await _weave(monkeypatch, jobs[0], PLAIN)
        assert result == "woven"
        assert briefs[0].woven == WovenNotices(ai=False, recording=False)
        assert await _first_words(tenant_id, agent_id) == PLAIN
