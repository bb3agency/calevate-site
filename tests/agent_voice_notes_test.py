"""How an agent should sound, taught by its owner (`agents/voice_notes`): kept per agent,
deduplicated, capped, retired rather than deleted, written into the agent's script, and seen
by no other client (hard rule 1)."""

from __future__ import annotations

import pytest
from apps.api.agents import voice_notes
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.lead_columns_test import _tenant
from tests.thinnest_engine_test import _cfg


async def test_notes_are_kept_once_retired_not_deleted_and_private_to_the_client() -> None:
    t = await _tenant()
    async with tenant_session(t.tenant_id) as session:
        first = await voice_notes.add_note(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            language="te-IN",
            note="Say it   slower",
            source="Campaign: Rytu, scenario 2.1",
            created_by=None,
        )
        again = await voice_notes.add_note(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            language="te-IN",
            note="say it slower",
            source="",
            created_by=None,
        )
        assert again.id == first.id and first.note == "Say it slower"
        assert await voice_notes.load(session, agent_id=t.agent_id) == (("te-IN", "Say it slower"),)
        assert await voice_notes.retire_note(session, agent_id=t.agent_id, note_id=first.id)
        assert await voice_notes.load(session, agent_id=t.agent_id) == ()
        kept = (await session.execute(text("SELECT count(*) FROM agent_voice_notes"))).scalar()
        assert kept == 1

    other = await _tenant()
    async with tenant_session(other.tenant_id) as session:
        rows = (await session.execute(text("SELECT count(*) FROM agent_voice_notes"))).scalar()
    assert rows == 0


async def test_an_unknown_language_and_a_full_set_are_refused() -> None:
    t = await _tenant()
    async with tenant_session(t.tenant_id) as session:
        with pytest.raises(ProblemError) as bad:
            await voice_notes.add_note(
                session,
                tenant_id=t.tenant_id,
                agent_id=t.agent_id,
                language="xx-XX",
                note="slower",
                source="",
                created_by=None,
            )
        assert bad.value.code == "voice_note_language"
        for i in range(voice_notes.MAX_ACTIVE_NOTES):
            await voice_notes.add_note(
                session,
                tenant_id=t.tenant_id,
                agent_id=t.agent_id,
                language="",
                note=f"note {i}",
                source="",
                created_by=None,
            )
        with pytest.raises(ProblemError) as full:
            await voice_notes.add_note(
                session,
                tenant_id=t.tenant_id,
                agent_id=t.agent_id,
                language="",
                note="one more",
                source="",
                created_by=None,
            )
        assert full.value.code == "voice_notes_full"


def test_the_notes_follow_the_script_inside_it() -> None:
    cfg = _cfg()
    taught = voice_notes.with_voice_notes(cfg, [("te-IN", "slower"), ("", "warmer")])
    body = taught.system_prompt or ""
    assert body.startswith((cfg.system_prompt or "").rstrip())
    assert voice_notes.VOICE_NOTES_HEADER in body
    assert "- (Telugu) slower" in body and "- warmer" in body
    assert voice_notes.with_voice_notes(cfg, ()) is cfg
