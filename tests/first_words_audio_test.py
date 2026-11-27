"""Hearing a work's first words without a phone (W1.3): the text is the one its calls compose,
whole, spoken in parts in the agent's Studio voice; a Clear voice gets the text and a reason.

No vendor is reached: the engine is `HostingEngine`, which records each line it is asked to
speak.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.agents import first_words_audio, voice_tuning
from apps.api.agents.first_words_audio import (
    NO_WORDS_RULE,
    NOT_STUDIO_RULE,
    PART_MAX_CHARS,
    router,
    spoken_parts,
)
from apps.api.agents.service import _load_agent, held_greeting
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from calevate_shared.call_script import CallScript
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.call_handling_test import _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.studio_voice_tuning_test import VOICE, _speaking

OPENING = (
    "Namaste, this is the Call Handling Store. We stock rice, dal and oil for homes and "
    "shops across the town. Ask me about any of them, or about delivery to your door. "
    "We are open every day from nine in the morning. What would you like to know today?"
)


def _app() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(router)
    assert_policy_registry_complete(application)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


async def _line(tenant_id: uuid.UUID, agent_id: uuid.UUID, script: CallScript | None) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, main_task="Answer", created_by=None
        )
        if script is not None:
            await lines.save_script(session, line_id, script, author="owner")
    return line_id


async def _studio(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_voice_id = :v WHERE id = :aid"),
            {"v": f"byok:{VOICE}", "aid": agent_id},
        )


async def _composed(tenant_id: uuid.UUID, agent_id: uuid.UUID, line_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        agent = await _load_agent(session, tenant_id, agent_id)
        words = await held_greeting(session, tenant_id=tenant_id, agent=agent, line_id=line_id)
    assert words
    return words


def test_the_parts_say_every_word_and_each_fits_what_the_engine_speaks() -> None:
    long = " ".join(f"Sentence number {n} says one plain thing." for n in range(30))
    parts = spoken_parts(long)
    assert len(parts) > 1
    assert all(0 < len(part) <= PART_MAX_CHARS for part in parts)
    assert " ".join(parts) == " ".join(long.split())
    # Cut between sentences where one fits.
    assert all(part.endswith(".") for part in parts)


def test_a_sentence_longer_than_a_part_is_cut_between_words_and_nothing_is_lost() -> None:
    sentence = "word " * 120 + "end."
    parts = spoken_parts(sentence, limit=50)
    assert all(len(part) <= 50 for part in parts)
    assert " ".join(parts) == " ".join(sentence.split())
    assert spoken_parts("x" * 120, limit=50) == ["x" * 50, "x" * 50, "x" * 20]
    assert spoken_parts("   ") == []


async def test_a_studio_agent_is_heard_saying_its_whole_first_words_and_a_replay_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _studio(tenant_id, agent_id)
    # A cache of its own, so audio kept by an earlier run is not what is heard.
    monkeypatch.setattr(first_words_audio, "_CACHE_PREFIX", f"test:{uuid.uuid4().hex}:")
    line_id = await _line(tenant_id, agent_id, CallScript(opening_line=OPENING))
    engine = HostingEngine()
    _speaking(monkeypatch, engine)
    expected = await _composed(tenant_id, agent_id, line_id)
    assert OPENING.split(".")[0] in expected

    path = f"/v1/agents/{agent_id}/first-words"
    async with _app() as client:
        asked = await client.get(path, headers=headers, params={"line_id": str(line_id)})
        neither = await client.get(path, headers=headers)
        heard = await client.post(path, headers=headers, json={"line_id": str(line_id)})
        again = await client.post(path, headers=headers, json={"line_id": str(line_id)})
    # Asking first speaks and counts nothing: it says the words and that they can be heard.
    assert asked.status_code == 200, asked.text
    assert asked.json()["playable"] is True and asked.json()["parts"] == []
    assert asked.json()["text"] == expected
    assert neither.status_code == 422, neither.text
    assert neither.json()["type"].endswith("/first_words_one_work")
    assert heard.status_code == 200, heard.text
    body = heard.json()
    assert body["playable"] is True and body["unavailable_rule"] is None
    # The text played is the text composed, never cut: the parts spoken join to it.
    assert body["text"] == expected
    spoken = [line for line, _language in engine.preview_lines]
    assert " ".join(str(line) for line in spoken) == " ".join(expected.split())
    assert [part["text"] for part in body["parts"]] == spoken
    assert len(spoken) > 1
    assert {language for _line, language in engine.preview_lines} == {"te-IN"}
    assert all(part["content_type"] == "audio/mpeg" and part["audio"] for part in body["parts"])
    # Pressed again within the hour: the same audio, nothing spoken, no sample counted.
    assert again.json()["parts"] == body["parts"]
    assert len(engine.preview_lines) == len(spoken)
    counted = await get_redis().get(voice_tuning._preview_key(tenant_id, None))
    assert int(counted or 0) == 1


async def test_a_clear_voice_gets_the_words_and_why_it_cannot_be_heard_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, headers = await _tenant()
    line_id = await _line(tenant_id, agent_id, CallScript(opening_line=OPENING))
    engine = HostingEngine()
    _speaking(monkeypatch, engine)
    async with _app() as client:
        answer = await client.post(
            f"/v1/agents/{agent_id}/first-words", headers=headers, json={"line_id": str(line_id)}
        )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["playable"] is False and body["unavailable_rule"] == NOT_STUDIO_RULE
    assert body["text"] == await _composed(tenant_id, agent_id, line_id)
    assert body["parts"] == [] and engine.preview_lines == []
    # Client-facing words name no provider (D-679).
    assert not any(name in body["unavailable_reason"].lower() for name in ("cartesia", "thinnest"))


async def test_a_line_with_no_script_has_nothing_to_play(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _studio(tenant_id, agent_id)
    line_id = await _line(tenant_id, agent_id, None)
    engine = HostingEngine()
    _speaking(monkeypatch, engine)
    async with _app() as client:
        answer = await client.post(
            f"/v1/agents/{agent_id}/first-words", headers=headers, json={"line_id": str(line_id)}
        )
    assert answer.status_code == 200, answer.text
    assert answer.json()["unavailable_rule"] == NO_WORDS_RULE
    assert engine.preview_lines == []


async def test_another_agents_line_or_a_missing_one_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _tenant_id, agent_id, headers = await _tenant()
    other_tenant, other_agent, _other_headers = await _tenant()
    other_line = await _line(other_tenant, other_agent, CallScript(opening_line=OPENING))
    _speaking(monkeypatch, HostingEngine())
    path = f"/v1/agents/{agent_id}/first-words"
    async with _app() as client:
        foreign = await client.post(path, headers=headers, json={"line_id": str(other_line)})
        both = await client.post(
            path,
            headers=headers,
            json={"line_id": str(other_line), "campaign_id": str(uuid.uuid4())},
        )
    assert foreign.status_code == 404, foreign.text
    assert both.status_code == 422, both.text


async def test_a_sample_the_engine_refuses_is_given_back(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _studio(tenant_id, agent_id)
    line_id = await _line(
        tenant_id, agent_id, CallScript(opening_line=f"Namaste {uuid.uuid4().hex[:6]}.")
    )

    class _Down(HostingEngine):
        async def preview_own_key_voice(self, **_kwargs: object) -> object:
            raise RuntimeError("vendor down")

    _speaking(monkeypatch, _Down())
    async with _app() as client:
        with pytest.raises(RuntimeError):
            await client.post(
                f"/v1/agents/{agent_id}/first-words",
                headers=headers,
                json={"line_id": str(line_id)},
            )
    counted = await get_redis().get(voice_tuning._preview_key(tenant_id, None))
    assert int(counted or 0) == 0
    assert first_words_audio.CACHE_TTL_S == 3600
