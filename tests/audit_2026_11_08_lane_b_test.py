"""Audit of 8 Nov 2026, lane B (agent script and knowledge): one test per fixed finding.

B-04 a fix can take out a placeholder step and move a misplaced one; B-05/B-06 two lint
misfires; B-12 a reading that breaks off settles its row; B-14 a view-as session cannot
publish a pinned fact; B-15 facts stay live when their newest version is refused.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import script_proposals
from apps.api.agents.script_lint import other_persona, repeated_line_problems
from apps.api.db.session import tenant_session
from apps.api.teach import facts as fact_store
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


# --- B-14: a pinned fact is not published by a view-as session -------------------------------


@pytest.mark.anyio
async def test_a_view_as_session_cannot_pin_a_fact_but_its_unpinned_fact_waits_for_review() -> None:
    from tests.impersonation_grant_test import view_as_headers
    from tests.kb_staff_curation_test import _admin, _client, _tenant

    tenant_id, _agent_id, slug = await _tenant()
    token = await _admin()
    async with _client() as http:
        headers = await view_as_headers(http, token, slug)
        pinned = await http.post(
            "/v1/kb/facts",
            headers=headers,
            json={"text": "We open at 9.", "question": "When do you open?", "pinned": True},
        )
        reorder = await http.post(
            "/v1/kb/facts/pinned-order", headers=headers, json={"ids": [str(uuid.uuid4())]}
        )
        unpinned = await http.post(
            "/v1/kb/facts", headers=headers, json={"text": "We close at 8.", "pinned": False}
        )
    assert pinned.status_code == 403, pinned.text
    assert reorder.status_code == 403, reorder.text
    assert unpinned.status_code == 201, unpinned.text
    async with tenant_session(tenant_id) as session:
        pins = (await session.execute(text("SELECT count(*) FROM kb_facts WHERE pinned"))).scalar()
        status = (
            await session.execute(
                text("SELECT status FROM kb_sources WHERE name = :n ORDER BY version DESC LIMIT 1"),
                {"n": fact_store.FACTS_SOURCE_NAME},
            )
        ).scalar()
    assert pins == 0
    assert status == "pending_approval"


# --- B-15: facts still live when the newest version was refused -----------------------------


async def _add_fact(tenant_id: uuid.UUID, fact: str) -> None:
    async with tenant_session(tenant_id) as session:
        await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=[fact],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )


@pytest.mark.anyio
async def test_facts_stay_live_when_their_newest_version_is_refused() -> None:
    tenant_id, _agent_id = await _tenant_with_published_agent()
    name = {"n": fact_store.FACTS_SOURCE_NAME}
    await _add_fact(tenant_id, "We open at 9.")
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE kb_sources SET is_active = true WHERE name = :n"), name)
    await _add_fact(tenant_id, "We close at 8.")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE kb_sources SET status = 'rejected', is_active = false WHERE name = :n "
                "AND version = (SELECT max(version) FROM kb_sources WHERE name = :n)"
            ),
            name,
        )
        assert await fact_store.facts_state(session) == "live"
        await session.execute(text("UPDATE kb_sources SET is_active = false WHERE name = :n"), name)
        assert await fact_store.facts_state(session) == "none"
