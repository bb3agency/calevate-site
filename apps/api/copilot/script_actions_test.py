"""Pip's fixes for failed tests, held to `docs/COPILOT-CONTRACT.md` §5: `agent_tests_fix`'s
planner and confirm, and the neighbour's agent refused."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.agents import test_conversations
from apps.api.copilot import script_actions, write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.schemas import CopilotProposalEvent
from apps.api.copilot.write_tools_test import _audit, _confirm, _outbox_jobs, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session


async def _agent_of(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).first()
    assert row is not None
    return UUID(str(row[0]))


@pytest.fixture(autouse=True)
def _allowance_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowance gate is `billing/ai_quota`'s own suite; here it answers "open"."""

    async def _open(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(script_actions, "require_ai_assist", _open)


# --- agent_tests_fix: the Test section's "Improve my agent", asked of Pip ---------------


async def _failed_run(tenant_id: UUID, agent_id: UUID, *, verdicts: tuple[str, ...]) -> UUID:
    run_id = uuid.uuid4()
    results = [
        {"key": f"k{i}", "title": f"Test {i}", "verdict": verdict, "reason": "x"}
        for i, verdict in enumerate(verdicts, start=1)
    ]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_test_runs (id, tenant_id, agent_id, status, results, "
                "created_at, updated_at) VALUES (:id, :t, :a, 'done', CAST(:r AS jsonb), "
                "now(), now())"
            ),
            {"id": run_id, "t": tenant_id, "a": agent_id, "r": json.dumps(results)},
        )
    return run_id


async def _propose_fix(tenant_id: UUID, token: str, args: dict[str, Any]) -> CopilotProposalEvent:
    return await write_tools.plan_write(
        "agent_tests_fix",
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token))),
    )


async def test_fixes_are_planned_for_the_named_failures_of_the_latest_run() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _failed_run(tenant_id, agent_id, verdicts=("failed", "needs_fix", "passed"))
    proposal = await _propose_fix(
        tenant_id, token, {"agent_id": str(agent_id), "test_keys": ["k2"]}
    )
    assert proposal.tool == "agent_tests_fix"
    assert proposal.proposed == "Test 2"
    assert proposal.cost is not None and "AI help allowance" in proposal.cost


@pytest.mark.parametrize(
    ("verdicts", "keys", "reason"),
    [
        ((), None, "no finished test run"),
        (("passed",), None, "nothing to fix"),
        (("failed",), ["k9"], "not a failed test"),
        (("failed", "passed"), ["k2"], "not a failed test"),
    ],
)
async def test_the_fix_refusals_the_model_can_act_on(
    verdicts: tuple[str, ...], keys: list[str] | None, reason: str
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    if verdicts:
        await _failed_run(tenant_id, agent_id, verdicts=verdicts)
    with pytest.raises(WriteRefusedError) as refused:
        await _propose_fix(tenant_id, token, {"agent_id": str(agent_id), "test_keys": keys})
    assert reason in refused.value.reason


async def test_confirming_fixes_queues_the_improver_once_and_audits() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    run_id = await _failed_run(tenant_id, agent_id, verdicts=("failed",))
    proposal = await _propose_fix(tenant_id, token, {"agent_id": str(agent_id), "test_keys": None})
    outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert outcome.applied and outcome.queued is True
    assert (await _outbox_jobs(tenant_id)).count(test_conversations.IMPROVE_JOB) == 1
    assert ("agent.tests_improvement", "agent", str(agent_id)) in await _audit(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert (await test_conversations.get_run(session, agent_id, run_id)).improving
    with pytest.raises(WriteRefusedError) as again:
        await _propose_fix(tenant_id, token, {"agent_id": str(agent_id), "test_keys": None})
    assert "already being worked out" in again.value.reason


async def test_fixes_for_a_neighbours_agent_are_not_found() -> None:
    tenant_id, _slug, token = await _make_tenant()
    neighbour, _, _ = await _make_tenant()
    neighbour_agent = await _agent_of(neighbour)
    await _failed_run(neighbour, neighbour_agent, verdicts=("failed",))
    with pytest.raises(ProblemError) as missing:
        await _propose_fix(tenant_id, token, {"agent_id": str(neighbour_agent), "test_keys": None})
    assert missing.value.status == 404


async def test_with_several_lines_pip_asks_which_one_gets_the_script_fixes() -> None:
    """FAILS IF Pip guesses where a script fix goes when the agent has several Inbound lines
    (D-1017), or the line it was told is not the one signed into the confirm."""
    from calevate_shared.call_script import CallScript

    from apps.api.inbound.lines import create_line

    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    lines = []
    async with tenant_session(tenant_id) as session:
        for name in ("Main line", "After hours"):
            lines.append(
                await create_line(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    name=name,
                    script=CallScript(schema_version=2, opening_line="Namaskaram"),
                    created_by=None,
                )
            )
    await _failed_run(tenant_id, agent_id, verdicts=("failed",))
    with pytest.raises(WriteRefusedError) as asked:
        await _propose_fix(tenant_id, token, {"agent_id": str(agent_id), "test_keys": None})
    assert "ask the person which" in asked.value.reason
    assert "After hours" in asked.value.reason and str(lines[1]) in asked.value.reason
    proposal = await _propose_fix(
        tenant_id,
        token,
        {"agent_id": str(agent_id), "test_keys": None, "holder_id": str(lines[1])},
    )
    assert "the Inbound line “After hours”" in proposal.summary
    outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert outcome.applied and outcome.queued is True
