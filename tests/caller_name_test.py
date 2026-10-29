"""A call's captured name never becomes the agent's name, and never replaces a lead's name.

The founder's test call of 30 Oct 2026: an outbound agent called "Anjali" opened with the
lead's name, the caller asked "Anjali?" back, the extraction filed "Anjali" as the caller's
name, and the lead "Umesh" was renamed to the agent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.workers import extraction as extraction_module
from apps.workers import pipeline
from apps.workers.caller_name import fold, is_self_name, self_names, without_self_names
from apps.workers.pipeline import extractor_transcript
from calevate_shared.call_script import PRONOUNCE_LEAD, pronunciations_of
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import ExtractionSchemaSpec
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

OPENING = "ఉమేష్ గారు, మీరు ఇంతకు ముందు ప్రాపర్టీ గురించి ఎంక్వైరీ చేశారు కదా..."


def _turns(*lines: tuple[str, str]) -> list[TranscriptTurn]:
    return [
        TranscriptTurn(call_id="c", idx=i, speaker=speaker, text=said)  # type: ignore[arg-type]
        for i, (speaker, said) in enumerate(lines)
    ]


# --- the rule -----------------------------------------------------------------------------


def test_fold_ignores_case_spacing_punctuation_and_latin_diacritics() -> None:
    assert fold("  ANJALI. ") == fold("Añjali") == "anjali"
    assert fold("Anjali   Rao!") == "anjali rao"
    # Telugu vowel signs are the vowels, not decoration.
    assert fold("రవి") != fold("రవ")
    assert fold("అంజలి.") == "అంజలి"


def test_the_agents_own_name_is_not_the_callers() -> None:
    agents, businesses = self_names(
        agent_name="Anjali", business_name="Sri Sai Properties", script_body=None
    )
    turns = _turns(("agent", OPENING), ("caller", "Anjali."))
    assert is_self_name("anjali", agent_names=agents, business_names=businesses, turns=turns)
    assert is_self_name(
        "Sri Sai Properties", agent_names=agents, business_names=businesses, turns=turns
    )
    # A business name is matched whole: a caller named Sai keeps their name.
    assert not is_self_name("Sai", agent_names=agents, business_names=businesses, turns=turns)
    assert not is_self_name("Ravi", agent_names=agents, business_names=businesses, turns=turns)


def test_an_agent_name_with_more_words_still_matches_its_spoken_name() -> None:
    agents, businesses = self_names(agent_name="Anjali Sales", business_name="", script_body="")
    assert is_self_name("Anjali", agent_names=agents, business_names=businesses, turns=[])


def test_the_taught_telugu_spelling_of_the_agents_name_is_matched() -> None:
    body = f'[Style]\n{PRONOUNCE_LEAD}Anjali as "అంజలి"; Guntur as "గుంటూరు"'
    assert pronunciations_of(body) == [("Anjali", "అంజలి"), ("Guntur", "గుంటూరు")]
    agents, businesses = self_names(agent_name="Anjali", business_name="", script_body=body)
    assert is_self_name("అంజలి", agent_names=agents, business_names=businesses, turns=[])
    # A pronounced name that is not the agent's or the business's is a caller's to have.
    assert not is_self_name("గుంటూరు", agent_names=agents, business_names=businesses, turns=[])


def test_a_name_the_agent_said_first_is_its_own_and_one_the_caller_said_first_is_theirs() -> None:
    introduced = _turns(("agent", "Namaskaram, nenu Priya."), ("caller", "Priya?"))
    assert is_self_name("Priya", agent_names=(), business_names=(), turns=introduced)
    confirmed = _turns(
        ("agent", "Mee peru cheppandi?"), ("caller", "Ravi."), ("agent", "Thanks Ravi garu.")
    )
    assert not is_self_name("Ravi", agent_names=(), business_names=(), turns=confirmed)


def test_the_name_an_outbound_agent_opens_with_stays_the_callers() -> None:
    greeted = _turns(("agent", "Hello Umesh garu, Anjali here."), ("caller", "Haan, Umesh."))
    agents, businesses = self_names(agent_name="Anjali", business_name="", script_body=None)
    names = {"agent_names": agents, "business_names": businesses, "turns": greeted}
    assert not is_self_name("umesh", caller_names=["Umesh"], **names)
    # The agent's own name still loses, whatever name is on file.
    assert is_self_name("Anjali", caller_names=["Anjali"], **names)


def test_without_self_names_drops_only_the_name_keys_it_rejects() -> None:
    agents, businesses = self_names(agent_name="Anjali", business_name="", script_body=None)
    data = {"name": "Anjali", "caller_name": "Anjali", "need": "2BHK flat"}
    cleaned, dropped = without_self_names(
        data, agent_names=agents, business_names=businesses, turns=[]
    )
    assert dropped and cleaned == {"need": "2BHK flat"}
    kept, dropped = without_self_names(
        {"name": "Umesh"}, agent_names=agents, business_names=businesses, turns=[]
    )
    assert not dropped and kept == {"name": "Umesh"}


# --- the pipeline -------------------------------------------------------------------------


class _Runner:
    model_name = "fake-model"

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        return dict(self.answer)


async def _outbound_call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    lead_phone: str,
    started_at: datetime,
    turns: list[TranscriptTurn],
) -> tuple[uuid.UUID, ExecutionSnapshot]:
    snapshot = ExecutionSnapshot(
        engine_call_id=f"name_{uuid.uuid4().hex[:10]}",
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        from_e164="+911140000000",
        to_e164=lead_phone,
        started_at=started_at,
        engine="fake",
        transcript=turns,
    )
    return await pipeline._upsert_call(tenant_id, agent_id, snapshot, None), snapshot


async def _read_and_file(
    tenant_id: uuid.UUID, call_id: uuid.UUID, snapshot: ExecutionSnapshot
) -> tuple[uuid.UUID | None, dict[str, Any]]:
    spec, version, agent_id, direction, _d, _n = await pipeline._load_call_context(
        tenant_id, call_id
    )
    extraction = await pipeline._extract_stage(
        tenant_id,
        call_id,
        snapshot,
        spec=spec,
        agent_id=agent_id,
        transcript_text=extractor_transcript(snapshot.transcript),
        opt_out_signal=None,
        business_outcomes=[],
        reuse=False,
    )
    assert extraction is not None
    lead_id = await pipeline._upsert_lead(
        tenant_id,
        agent_id,
        call_id,
        snapshot,
        direction=direction,
        data=extraction.data,
        schema_version=version,
    )
    return lead_id, extraction.data


async def _lead_name(tenant_id: uuid.UUID, lead_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(text("SELECT name FROM leads WHERE id = :l"), {"l": lead_id})
        ).scalar()


async def _seed_anjali() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _seed_tenant(f"name_{uuid.uuid4().hex[:10]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET name = 'Anjali', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    return tenant_id, agent_id


@pytest.mark.rls
async def test_the_founders_call_leaves_umesh_named_umesh(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _seed_anjali()
    phone = f"+9198{uuid.uuid4().int % 100000000:08d}"
    now = datetime.now(UTC)

    monkeypatch.setattr(extraction_module, "get_extractor", lambda: _Runner({"name": "Umesh"}))
    first_id, first = await _outbound_call(
        tenant_id,
        agent_id,
        lead_phone=phone,
        started_at=now - timedelta(days=1),
        turns=_turns(("agent", "Mee peru?"), ("caller", "Umesh.")),
    )
    lead_id, _data = await _read_and_file(tenant_id, first_id, first)
    assert lead_id is not None
    assert await _lead_name(tenant_id, lead_id) == "Umesh", "a lead with no name takes one"

    monkeypatch.setattr(extraction_module, "get_extractor", lambda: _Runner({"name": "Anjali"}))
    second_id, second = await _outbound_call(
        tenant_id,
        agent_id,
        lead_phone=phone,
        started_at=now,
        turns=_turns(("agent", OPENING), ("caller", "Anjali.")),
    )
    again, data = await _read_and_file(tenant_id, second_id, second)
    assert again == lead_id
    assert "name" not in data, "the agent's name was captured as the caller's"
    assert await _lead_name(tenant_id, lead_id) == "Umesh"
    async with tenant_session(tenant_id) as session:
        moments = (
            await session.execute(
                text("SELECT moments FROM call_extractions WHERE call_id = :c"), {"c": second_id}
            )
        ).scalar()
    assert not any(m.get("field") == "name" for m in moments or []), "a Name captured marker"


@pytest.mark.rls
async def test_a_repeat_call_greeting_the_lead_by_name_keeps_the_name_captured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _seed_anjali()
    phone = f"+9198{uuid.uuid4().int % 100000000:08d}"
    now = datetime.now(UTC)
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: _Runner({"name": "Umesh"}))
    first_id, first = await _outbound_call(
        tenant_id,
        agent_id,
        lead_phone=phone,
        started_at=now - timedelta(days=1),
        turns=_turns(("agent", "Mee peru?"), ("caller", "Umesh.")),
    )
    await _read_and_file(tenant_id, first_id, first)
    second_id, second = await _outbound_call(
        tenant_id,
        agent_id,
        lead_phone=phone,
        started_at=now,
        turns=_turns(("agent", "Umesh garu, Anjali here."), ("caller", "Haan, Umesh.")),
    )
    _lead, data = await _read_and_file(tenant_id, second_id, second)
    assert data.get("name") == "Umesh", "the name the agent greeted with was dropped"


@pytest.mark.rls
async def test_a_different_name_heard_later_never_replaces_the_leads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _seed_anjali()
    phone = f"+9198{uuid.uuid4().int % 100000000:08d}"
    now = datetime.now(UTC)
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: _Runner({"name": "Umesh"}))
    first_id, first = await _outbound_call(
        tenant_id,
        agent_id,
        lead_phone=phone,
        started_at=now - timedelta(days=1),
        turns=_turns(("agent", "Mee peru?"), ("caller", "Umesh.")),
    )
    lead_id, _ = await _read_and_file(tenant_id, first_id, first)
    assert lead_id is not None

    monkeypatch.setattr(extraction_module, "get_extractor", lambda: _Runner({"name": "Ramesh"}))
    second_id, second = await _outbound_call(
        tenant_id,
        agent_id,
        lead_phone=phone,
        started_at=now,
        turns=_turns(("agent", "Mee peru?"), ("caller", "Ramesh.")),
    )
    await _read_and_file(tenant_id, second_id, second)
    assert await _lead_name(tenant_id, lead_id) == "Umesh"
    async with tenant_session(tenant_id) as session:
        captured = (
            await session.execute(text("SELECT data FROM leads WHERE id = :l"), {"l": lead_id})
        ).scalar()
    assert captured["name"] == "Ramesh", "the name heard stays as the call's captured detail"
