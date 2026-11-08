"""Audit of 8 Nov 2026, lane B (agent script and knowledge): one test per fixed finding.

B-04 a fix can take out a placeholder step and move a misplaced one; B-05/B-06 two lint
misfires; B-12 a reading that breaks off settles its row.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import script_proposals
from apps.api.agents.script_lint import other_persona, repeated_line_problems
from apps.api.db.session import tenant_session
from apps.workers import kb_read
from calevate_shared.call_script import CallScript, ConversationStage, StageBranch
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_read_copy_test import PRICE_PAGE, _pdf, _pdf_upload, _upload_row
from tests.kb_workflow_test import _tenant_with_published_agent

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
