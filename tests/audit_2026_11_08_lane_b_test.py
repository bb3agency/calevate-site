"""Audit of 8 Nov 2026, lane B (agent script and knowledge): one test per fixed finding.

B-01 a notice record only the platform wrote reaches a call; B-02 the notice writer never
lands over a line put live while it wrote; B-03 woven recording words cut from the spoken
line give the stored sentence back; B-04 a fix can take out a placeholder step and move a
misplaced one; B-05/B-06 two lint misfires; B-12 a reading that breaks off settles its row.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_builder, script_proposals, script_publish
from apps.api.agents.publishing import set_disclosure_posture
from apps.api.agents.script_lint import other_persona, repeated_line_problems
from apps.api.db.session import tenant_session
from apps.workers import kb_read, opening_line
from apps.workers import opening_notices as weave_worker
from calevate_shared.call_script import CallScript, ConversationStage, StageBranch
from calevate_shared.engine import join_first_words
from calevate_shared.opening_notices import OpeningNotices, SaidNotices
from sqlalchemy import text
from tests.ai_notice_introduction_test import BUSINESS, NAME, TE_AI
from tests.conftest import FakeS3
from tests.kb_read_copy_test import PRICE_PAGE, _pdf, _pdf_upload, _upload_row
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.opening_notices_test import (
    AI,
    PLAIN,
    WOVEN,
    WOVEN_AI_WORDS,
    WOVEN_SAID,
    _agent,
    _first_words,
    _on_thinnest,
    _weave,
    _weave_jobs,
)

# --- B-01: the platform's notice records only ---------------------------------------------


async def _ai_on(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    await set_disclosure_posture(
        tenant_id=tenant_id,
        agent_id=agent_id,
        ai_disclosure_enabled=True,
        recording_notice_enabled=None,
    )


async def _loaded(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> CallScript:
    async with tenant_session(tenant_id) as session:
        return (await script_builder.load_agent_script(session, agent_id)).script


@pytest.mark.anyio
async def test_a_notice_record_the_client_wrote_never_drops_the_ai_sentence() -> None:
    with _on_thinnest():
        tenant_id, agent_id = await _agent(PLAIN)
        await _ai_on(tenant_id, agent_id)
        # Words that are no notice, claimed as the woven AI notice of the line.
        forged = (await _loaded(tenant_id, agent_id)).model_copy(
            update={"opening_notices": OpeningNotices(line=PLAIN, ai="Hello")}
        )
        async with tenant_session(tenant_id) as session:
            kept = await script_builder.platform_notice_records(session, agent_id, forged)
        assert kept.opening_notices == OpeningNotices()
        await script_publish.put_draft_live(
            tenant_id=tenant_id,
            agent_id=agent_id,
            summary="Owner edit",
            created_by=None,
            script=forged,
        )
        assert (await _loaded(tenant_id, agent_id)).opening_notices == OpeningNotices()
        assert await _first_words(tenant_id, agent_id) == f"{PLAIN} {AI}"


@pytest.mark.anyio
async def test_the_records_the_platform_wrote_go_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _on_thinnest():
        tenant_id, agent_id = await _agent(PLAIN)
        await _ai_on(tenant_id, agent_id)
        await _weave(monkeypatch, (await _weave_jobs(tenant_id, agent_id))[0], WOVEN, WOVEN_SAID)
        woven = await _loaded(tenant_id, agent_id)
        assert woven.opening_notices.ai == WOVEN_AI_WORDS
        async with tenant_session(tenant_id) as session:
            assert await script_builder.platform_notice_records(session, agent_id, woven) == woven
        # A suggestion's record survives its review: the proposal is cleared before the kept
        # parts reach the draft.
        proposal_id = uuid.uuid4()
        written = woven.model_copy(
            update={
                "opening_line": "Hi, the AI assistant here. How can I help?",
                "opening_notices": OpeningNotices(
                    line="Hi, the AI assistant here. How can I help?", ai="the AI assistant"
                ),
            }
        )
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET script_proposal = CAST(:p AS jsonb) WHERE id = :aid"),
                {
                    "aid": agent_id,
                    "p": json.dumps(
                        {
                            "id": str(proposal_id),
                            "status": "ready",
                            "script": written.model_dump(mode="json"),
                        }
                    ),
                },
            )
            assert await script_proposals.discard(
                session, agent_id=agent_id, proposal_id=proposal_id
            )
            assert await script_proposals.read_proposal(session, agent_id) is None
            kept = await script_builder.platform_notice_records(session, agent_id, written)
        assert kept.opening_notices == written.opening_notices


# --- B-02: never over a line put live meanwhile ----------------------------------------------


@pytest.mark.anyio
async def test_the_notice_writer_never_lands_over_a_line_put_live_while_it_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    newer = "Hi, Raghava Organics. What can we send you today?"
    with _on_thinnest():
        tenant_id, agent_id = await _agent(PLAIN)
        await _ai_on(tenant_id, agent_id)
        job = (await _weave_jobs(tenant_id, agent_id))[0]

        async def owner_changes_it_meanwhile(_brief: Any, **_kw: Any) -> Any:
            async with tenant_session(tenant_id) as session:
                await script_builder.replace_opening_line(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    opening_line=newer,
                    created_by=None,
                )
            value = opening_line.WrittenOpening(line=WOVEN, said=WOVEN_SAID)
            return SimpleNamespace(value=value, capability=None, earlier=(), model=None)

        async def no_meter(_tenant_id: uuid.UUID, _spends: Any) -> None:
            return None

        monkeypatch.setattr(weave_worker, "write_opening", owner_changes_it_meanwhile)
        monkeypatch.setattr(weave_worker, "_meter", no_meter)
        assert await weave_worker.weave_opening_notices({}, job) == "unwritten"
        assert (await _loaded(tenant_id, agent_id)).opening_line == newer


# --- B-03: the recording sentence comes back when its woven words are not spoken -----------


def test_woven_recording_words_left_out_of_the_spoken_line_give_the_sentence_back() -> None:
    rec = "ఈ కాల్ రికార్డ్ అవుతుంది."
    opening = f"{BUSINESS} నుంచి కాల్ చేస్తున్నాను, ఈ కాల్ రికార్డ్ అవుతుంది. ఇప్పుడు మాట్లాడొచ్చా?"
    first = join_first_words(
        f"{TE_AI} {rec}",
        opening,
        ai_notice=TE_AI,
        language="te-IN",
        names=(BUSINESS, NAME),
        said=SaidNotices(recording="ఈ కాల్ రికార్డ్ అవుతుంది"),
    )
    assert first.endswith(rec)
    assert TE_AI in first


# --- B-04: a fix may take out a placeholder step and move a misplaced one -------------------


def _stage(sid: str, name: str, instruction: str, **kw: Any) -> ConversationStage:
    return ConversationStage(id=sid, name=name, instruction=instruction, **kw)


def test_a_fix_takes_out_the_placeholder_step_the_check_named() -> None:
    base = CallScript(
        schema_version=2,
        stages=[
            _stage("a", "Greet", "Greet them and ask what they need."),
            _stage("b", "Extra", "Not needed."),
            _stage("c", "Close", "Thank them and end the call."),
        ],
    )
    written = base.model_copy(update={"stages": [base.stages[0], base.stages[2]]})
    kept = script_proposals.kept_to_paths(written, base, ["stages.1.instruction"])
    assert [s.id for s in kept.stages] == ["a", "c"]


def test_a_fix_moves_a_question_the_caller_cannot_answer_yet() -> None:
    ask = _stage("ask", "Feedback", "Ask how they like using the app.")
    setup = _stage("setup", "Set up", "Help them install the app and sign up.")
    close = _stage("close", "Close", "Thank them and end the call.")
    base = CallScript(schema_version=2, stages=[ask, setup, close])
    written = base.model_copy(
        update={
            "stages": [
                setup.model_copy(
                    update={"branches": [StageBranch(when="they used it before", target="ask")]}
                ),
                ask,
                close,
            ]
        }
    )
    kept = script_proposals.kept_to_paths(written, base, ["stages.0.instruction"])
    assert [s.id for s in kept.stages] == ["setup", "ask", "close"]
    assert kept.stages[0].branches[0].target == "ask"
    assert kept.stages[1].instruction == ask.instruction


# --- B-05 / B-06 ---------------------------------------------------------------------------


def test_a_both_agents_two_openings_are_not_the_same_thing_said_twice() -> None:
    script = CallScript(
        schema_version=2,
        opening_line="Hello from Raghava Organics, I am Asha. How can I help you today?",
        outbound_opening_line="Hello from Raghava Organics, I am Asha. Is now a good time?",
    )
    assert repeated_line_problems(script) == []


def test_a_name_given_at_the_start_of_a_sentence_is_checked() -> None:
    assert other_persona("My name is Priya.", agent_name="Asha", business_name="Acme") == "Priya"
    assert other_persona("This is Ravi.", agent_name="Asha", business_name="Acme") == "Ravi"
    assert other_persona("My name is Asha.", agent_name="Asha", business_name="Acme") is None


# --- B-12: a reading that breaks off ---------------------------------------------------------


@pytest.mark.anyio
async def test_a_reading_that_breaks_off_never_stays_being_read(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _agent_id = await _tenant_with_published_agent()
    row = await _pdf_upload(tenant_id, _pdf(PRICE_PAGE))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE kb_uploads SET read_state = 'reading' WHERE id = :id"), {"id": row["id"]}
        )

    async def broken(*_a: Any, **_kw: Any) -> str:
        raise RuntimeError("storage went away")

    monkeypatch.setattr(kb_read, "read_saved_copy", broken)
    outcome = await kb_read.read_kb_upload(
        {}, {"tenant_id": str(tenant_id), "source_id": str(row["source_id"]), "force": True}
    )
    assert outcome == "failed"
    after = await _upload_row(tenant_id, row["id"])
    assert after["read_state"] == "failed"
    assert after["read_detail"]
