""" "Improve my agent", rebuilt (D-823, founder 18 Oct 2026): tests come from real calls first,
a test the owner marks wrong leaves the score and the fixes, a failure ours to fix raises an
alarm, kept edits are applied one by one, and a round stops with a stated reason.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from apps.api.agents import test_conversations
from apps.api.agents.test_conversations import (
    ENOUGH_REAL_CALLS,
    Scenario,
    TestRun,
    WrongTests,
    auto_improve_stop,
    needs_improving,
    real_call_scenarios,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.workers import agent_test_conversations as worker
from apps.workers import chat
from sqlalchemy import text
from tests.agent_test_loop_test import BRIEF, _agent, _failed_run
from tests.api_security_test import _client, _make_tenant

# --- real calls first ---------------------------------------------------------------------


async def test_an_agent_with_enough_real_calls_is_tested_on_them_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: practice callers are written (and paid for) for an agent that has enough
    real calls, or a question it could not answer on a real call is not asked again."""

    async def _no_model(*_: Any, **__: Any) -> Any:
        raise AssertionError("no AI-written callers for an agent with enough real calls")

    monkeypatch.setattr(chat, "complete", _no_model)
    brief = replace(
        BRIEF,
        real_calls=ENOUGH_REAL_CALLS,
        real_questions=(
            ("0192f0aa-0000-7000-8000-00000000abcd", "Delivery", "Kukatpally ki delivery undha?"),
        ),
    )
    callers, note = await worker.write_practice_callers(
        brief, tenant_id=uuid.uuid4(), round_key="r1", tenant_leg=None
    )
    assert callers == [] and note == worker.FROM_REAL_CALLS_NOTE
    real = real_call_scenarios(brief)
    assert [s.turns for s in real] == [("Kukatpally ki delivery undha?",)]
    assert real[0].source == "real" and real[0].title == "Asked on a real call: Delivery"
    assert real_call_scenarios(brief, skip=frozenset({real[0].key})) == []


# --- marking a test wrong -----------------------------------------------------------------


async def test_a_test_marked_wrong_leaves_the_score_the_fixes_and_later_runs() -> None:
    tenant_id, agent_id = await _agent()
    async with tenant_session(tenant_id) as session:
        case_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO agent_test_cases (id, tenant_id, agent_id, title, caller_lines, "
                "expected) VALUES (:i, :t, :a, 'Hours', '[\"When do you open?\"]'::jsonb, "
                "'Says nine')"
            ),
            {"i": case_id, "t": tenant_id, "a": agent_id},
        )
    run_id = await _failed_run(
        tenant_id,
        agent_id,
        [
            {"key": "k1", "title": "Price", "verdict": "failed", "fix": "knowledge"},
            {
                "key": "saved_x",
                "title": "Hours",
                "verdict": "failed",
                "fix": "script_step",
                "source": "saved",
                "case_id": str(case_id),
                "judge": {"verdict": "failed", "model": "m", "position": 0},
            },
            {"key": "k3", "title": "Hello", "verdict": "passed"},
        ],
    )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as passed:
            await test_conversations.mark_wrong(
                session, tenant_id=tenant_id, agent_id=agent_id, run_id=run_id, key="k3", by=None
            )
        assert passed.value.code == "agent_tests_passed_not_wrong"
        run = await test_conversations.mark_wrong(
            session, tenant_id=tenant_id, agent_id=agent_id, run_id=run_id, key="saved_x", by=None
        )
        # Twice is one label.
        await test_conversations.mark_wrong(
            session, tenant_id=tenant_id, agent_id=agent_id, run_id=run_id, key="saved_x", by=None
        )
        wrong = await test_conversations.wrong_tests(session, agent_id)
        snapshot = (
            await session.execute(
                text("SELECT snapshot FROM agent_test_labels WHERE run_id = :r"), {"r": run_id}
            )
        ).scalar_one()
    assert run.wrong_keys == frozenset({"saved_x"})
    assert (run.score.passed, run.score.counted) == (1, 2)
    assert [r["key"] for r in needs_improving(run)] == ["k1"]
    assert snapshot["judge_verdict"] == "failed" and snapshot["owner"] == "script"
    saved = Scenario(
        key="saved_y",
        title="Hours",
        category="business",
        turns=("x",),
        expect="",
        case_id=str(case_id),
    )
    assert not wrong.keeps(saved)
    # A rule check always runs, even after a run's copy of it was marked wrong.
    probe = test_conversations.probe_scenario("ai", "te-IN")
    assert WrongTests(keys=frozenset({probe.key})).keeps(probe)


@pytest.mark.rls
async def test_a_neighbour_sees_no_label_and_cannot_mark_a_run() -> None:
    tenant_a, agent_a = await _agent()
    tenant_b, _ = await _agent()
    run_id = await _failed_run(
        tenant_a, agent_a, [{"key": "k1", "title": "Price", "verdict": "failed"}]
    )
    async with tenant_session(tenant_a) as session:
        await test_conversations.mark_wrong(
            session, tenant_id=tenant_a, agent_id=agent_a, run_id=run_id, key="k1", by=None
        )
    async with tenant_session(tenant_b) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM agent_test_labels WHERE tenant_id = :a"),
                {"a": tenant_a},
            )
        ).scalar_one()
        with pytest.raises(ProblemError):
            await test_conversations.mark_wrong(
                session, tenant_id=tenant_b, agent_id=agent_a, run_id=run_id, key="k1", by=None
            )
    assert rows == 0


# --- failures that are ours ---------------------------------------------------------------


def test_a_failure_the_platform_owns_raises_one_alarm(monkeypatch: pytest.MonkeyPatch) -> None:
    raised: list[tuple[str, str, dict[str, Any]]] = []

    def _alert(stage: str, code: str, **fields: Any) -> None:
        raised.append((stage, code, fields))

    monkeypatch.setattr(worker, "alert", _alert)
    ids = {"tenant_id": uuid.uuid4(), "agent_id": uuid.uuid4(), "run_id": uuid.uuid4()}
    worker._alarm_platform_failures(
        [{"verdict": "failed", "owner": "script"}, {"verdict": "passed", "owner": None}], **ids
    )
    assert raised == []
    worker._alarm_platform_failures(
        [
            {"verdict": "failed", "owner": "platform", "probe": "ai"},
            {"verdict": "needs_fix", "owner": "platform", "fix": "platform"},
        ],
        **ids,
    )
    assert [(stage, code) for stage, code, _f in raised] == [
        ("CORE_LOGIC", worker.PLATFORM_FAILURE_CODE)
    ]
    assert "2 test(s)" in raised[0][2]["detail"]


# --- stop reasons -------------------------------------------------------------------------


def _run(results: list[dict[str, Any]], *, round_no: int = 1) -> TestRun:
    return TestRun(
        id=uuid.uuid4(),
        status="done",
        prompt_version=1,
        results=results,
        error_code=None,
        created_at=datetime.now(UTC),
        completed_at=None,
        improve_round=round_no,
        auto_improve=True,
    )


def test_auto_improve_stops_with_a_reason_instead_of_looping() -> None:
    platform_only = _run([{"key": "a", "verdict": "failed", "fix": "platform"}])
    assert auto_improve_stop(platform_only) == "nothing_fixable_by_script"
    over = _run([{"key": "a", "verdict": "failed", "fix": "knowledge"}], round_no=3)
    assert auto_improve_stop(over) == "budget"
    fixable = _run([{"key": "a", "verdict": "failed", "fix": "knowledge"}])
    assert auto_improve_stop(fixable) is None
    assert test_conversations.wants_auto_improvement(fixable)


# --- keeping edits ------------------------------------------------------------------------


async def test_kept_edits_are_applied_to_the_owners_copy_one_by_one() -> None:
    """FAILS IF: keeping one suggestion applies another, or an edit whose step is gone breaks
    the whole save rather than being left out and named."""
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
    run_id = await _failed_run(tenant_id, agent_id, [{"key": "k1", "verdict": "failed"}])
    edits = [
        {"id": "e1", "op": "set_step", "step_id": "s1", "text": "Greet and ask the need."},
        {"id": "e2", "op": "set_step", "step_id": "gone", "text": "x"},
        {"id": "e3", "op": "set_part", "part": "ending", "text": "Thank them."},
    ]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agent_test_runs SET improvement = CAST(:i AS jsonb) WHERE id = :id"),
            {"id": run_id, "i": json.dumps({"edits": edits, "facts": []})},
        )
    working = {
        "schema_version": 2,
        "opening_line": "Namaskaram",
        "stages": [{"id": "s1", "name": "Greet", "instruction": "Greet them."}],
    }
    path = f"/v1/agents/{agent_id}/script/tests/{run_id}/improvement/apply"
    async with _client() as http:
        response = await http.post(
            path,
            json={"script": working, "edits": ["e1", "e2"]},
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
        unknown = await http.post(
            path,
            json={"script": working, "edits": ["e9"]},
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["skipped"] == ["e2"]
    assert body["script"]["stages"][0]["instruction"] == "Greet and ask the need."
    assert body["script"]["ending"] == "" and body["script"]["opening_line"] == "Namaskaram"
    assert unknown.json()["type"].endswith("/agent_tests_unknown_edit"), unknown.text
