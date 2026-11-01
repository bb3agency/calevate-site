"""Changing an agent's voice changes the voice and nothing else the caller hears (D-960).

The founder's report of 2 Nov 2026: after changing only the voice of a live "both" agent,
its next call opened without the AI introduction, invented an earlier enquiry and would not
explain the product. Every door that changes a voice (the client's voice cards, Pip's
`agent_edit`, the first run, the operator) goes through `lifecycle.update_agent`, whose
republish sends the APPLIED script. These tests pin, through the fake engine, what that
publish sends on a live agent with a script edit staged behind "Put it live", both notices
on and a knowledge document attached: the same script, notices, opening, knowledge and
tools as before, on the same vendor agent, with only the voice, whether it speaks on our
voice key, and that key's rung fields differing.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import lifecycle, prompts
from apps.api.agents.service import _load_agent, dial_first_words, publish_agent
from apps.api.db.session import tenant_session
from calevate_shared.engine import AgentConfig, KBSourceRef
from sqlalchemy import text
from tests.hosted_voice_fakes import CatalogueRows, HostingEngine, selected
from tests.thinnest_engine_seams_test import (  # noqa: F401 - pytest fixtures
    _agent,
    attested,
    no_webhook,
)

pytestmark = [pytest.mark.rls]

STAGED = "Staged script: call the person back and sell them the yearly plan."

#: The `AgentConfig` fields a voice is allowed to move: the voice in the slot its source
#: takes, and whether the agent speaks on our voice key (the Clear/Studio rung, sent as the
#: agent's `byok`). Everything else in the dump must be equal.
VOICE_FIELDS = frozenset({"engine_voice_id", "engine_byok_voice_id", "engine_own_voice_key"})


async def _pointers(tenant_id: UUID, agent_id: UUID) -> tuple[int, int]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT d.version, l.version FROM agents a "
                    "JOIN prompt_versions d ON d.id = a.system_prompt_id "
                    "JOIN prompt_versions l ON l.id = a.live_prompt_id WHERE a.id = :aid"
                ),
                {"aid": agent_id},
            )
        ).one()
    return int(row[0]), int(row[1])


async def _placed_call_opening(tenant_id: UUID, agent_id: UUID, engine: HostingEngine) -> str:
    async with tenant_session(tenant_id) as session:
        agent = await _load_agent(session, tenant_id, agent_id)
    words = dial_first_words(
        agent, test_call=True, call_is_recorded=engine.capabilities.records_audio
    )
    assert words
    return words


async def _live_agent(
    rows: CatalogueRows, source: str
) -> tuple[UUID, UUID, str, HostingEngine, AgentConfig]:
    """A live "both" agent on a voice of `source`, notices on, a knowledge document attached
    and a script edit staged; returns what the engine was last sent."""
    tenant_id, agent_id = (UUID(str(v)) for v in await _agent())
    voice = await rows.add(source)  # type: ignore[arg-type]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET engine_voice_id = :v, direction = 'both', "
                "ai_disclosure_enabled = true, recording_notice_enabled = true WHERE id = :aid"
            ),
            {"v": voice, "aid": agent_id},
        )
    engine = HostingEngine()
    with selected(engine):
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(
                session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False
            )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live' WHERE id = :aid"), {"aid": agent_id}
        )
    await engine.attach_kb(
        ref, KBSourceRef(kb_id=str(uuid.uuid4()), title="Guide", text="How the app works.")
    )
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=STAGED,
            notes=None,
            created_by=None,
        )
    draft, applied = await _pointers(tenant_id, agent_id)
    assert draft > applied, "the script edit waits behind Put it live"
    return tenant_id, agent_id, ref, engine, engine.sent[-1]


@pytest.mark.parametrize(
    ("before", "after"),
    [("engine", "engine"), ("engine", "byok"), ("byok", "engine")],
    ids=["clear-to-clear", "clear-to-studio", "studio-to-clear"],
)
async def test_a_voice_change_sends_only_the_voice(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
    before: str,
    after: str,
) -> None:
    tenant_id, agent_id, ref, engine, sent = await _live_agent(hosted_rows, before)
    held = await engine.get_agent(ref)
    knowledge = await engine.list_kb(ref)
    opening = await _placed_call_opening(tenant_id, agent_id, engine)
    pointers = await _pointers(tenant_id, agent_id)
    new_voice = await hosted_rows.add(after)  # type: ignore[arg-type]

    with selected(engine):
        async with tenant_session(tenant_id) as session:
            await lifecycle.update_agent(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine_voice_id=new_voice,
                set_engine_voice_id=True,
            )

    now = engine.sent[-1]
    assert now is not sent, "a live agent is republished with its new voice"
    # The same vendor agent, so the knowledge, number and caller memory it holds stay with it.
    assert engine.deleted == [] and ref in engine._agents
    assert await engine.list_kb(ref) == knowledge and knowledge
    # Only the voice moved.
    dump: dict[str, Any] = now.model_dump()
    assert {k: v for k, v in dump.items() if k not in VOICE_FIELDS} == {
        k: v for k, v in sent.model_dump().items() if k not in VOICE_FIELDS
    }
    assert now.engine_own_voice_key is (after == "byok")
    assert (now.engine_byok_voice_id is not None) is (after == "byok")
    assert now.engine_workspace == sent.engine_workspace
    # The applied script, never the staged one, and the notices with it.
    assert STAGED not in now.system_prompt
    assert now.system_prompt == sent.system_prompt
    assert (now.opening_line, now.ai_notice) == (sent.opening_line, sent.ai_notice)
    assert now.ai_notice and now.ai_notice in now.opening_line
    assert (await engine.get_agent(ref)).greeting == held.greeting
    assert await _placed_call_opening(tenant_id, agent_id, engine) == opening
    assert sent.ai_notice in opening
    assert await _pointers(tenant_id, agent_id) == pointers, "the staged edit still waits"
