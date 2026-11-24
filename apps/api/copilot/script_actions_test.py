"""Pip's script actions, held to `docs/COPILOT-CONTRACT.md` §5: `agent_tests_fix`'s and
`script_draft`'s planner and confirm, and the neighbour's agent or campaign refused."""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.agents import test_conversations
from apps.api.campaigns import script_draft
from apps.api.campaigns import workspace as campaign_workspace
from apps.api.copilot import run_control, script_actions, write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.schemas import CopilotDraftEvent, CopilotProposalEvent
from apps.api.copilot.write_tools_test import _audit, _confirm, _outbox_jobs, _principal, _user_of
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.campaign_script_ask import INSTRUCTION_MAX


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
    with pytest.raises(write_tools.WriteRefusedError) as missing:
        await _propose_fix(tenant_id, token, {"agent_id": str(neighbour_agent), "test_keys": None})
    assert "does not exist" in missing.value.reason


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


# --- script_draft: a page's Generate, asked from chat ---------------------------------------


async def _campaign_of(tenant_id: UUID, agent_id: UUID, *, main_task: str | None) -> UUID:
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "main_task) VALUES (:id, :t, :a, 'Renewals', 'service', :m)"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id, "m": main_task},
        )
    return campaign_id


async def _propose_draft(
    tenant_id: UUID, token: str, args: dict[str, Any], *, role: str = "owner"
) -> CopilotProposalEvent:
    return await write_tools.plan_write(
        "script_draft",
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token), role=role)),
    )


async def test_a_campaign_draft_is_asked_with_the_owners_words_and_waits_on_its_page() -> None:
    """FAILS IF: Pip in chat cannot ask a campaign's own writer for a draft, the owner's
    request does not reach it, or it is recorded under another action than the page's."""
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    campaign_id = await _campaign_of(tenant_id, agent_id, main_task="Renew every policy.")
    asked = "Open with their name and drop the second question."
    proposal = await _propose_draft(
        tenant_id, token, {"holder_id": str(campaign_id), "instruction": asked}
    )
    assert proposal.tool == "script_draft"
    assert proposal.proposed == asked
    assert "the campaign “Renewals”" in proposal.summary
    assert "under Campaigns" in proposal.summary
    assert proposal.cost is not None and "AI help allowance" in proposal.cost

    outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert outcome.applied and outcome.queued is True
    assert "Nothing changes on calls until you keep it" in outcome.detail
    assert (await _outbox_jobs(tenant_id)).count(campaign_workspace.CAMPAIGN_SCRIPT_JOB) == 1
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT script_proposal FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert stored["status"] == "drafting"
    assert stored["ask"] == {"instruction": asked}
    assert ("campaign.script_requested", "agent", str(agent_id)) in await _audit(tenant_id)
    # The confirm's answer names the draft, so the panel follows it under the card.
    assert outcome.draft == CopilotDraftEvent(
        holder_kind="campaign", holder_id=campaign_id, proposal_id=UUID(stored["id"])
    )

    with pytest.raises(WriteRefusedError) as again:
        await _propose_draft(tenant_id, token, {"holder_id": str(campaign_id)})
    assert "already writing a draft" in again.value.reason


async def test_an_agents_only_inbound_line_gets_the_draft_with_its_tone() -> None:
    from apps.api.inbound import lines

    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Front desk",
            main_task="Book visits.",
            created_by=None,
        )
    proposal = await _propose_draft(
        tenant_id,
        token,
        {"agent_id": str(agent_id), "tone": "warm", "instruction": "Shorter steps."},
    )
    assert "the Inbound line “Front desk”" in proposal.summary
    assert "under Inbound" in proposal.summary
    outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert outcome.applied and outcome.queued is True
    assert (await _outbox_jobs(tenant_id)).count(lines.LINE_SCRIPT_JOB) == 1
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT script_proposal FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
    assert stored["ask"] == {"tone": "warm", "instruction": "Shorter steps."}
    assert ("inbound_line.script_requested", "agent", str(agent_id)) in await _audit(tenant_id)
    assert outcome.draft == CopilotDraftEvent(
        holder_kind="inbound_line", holder_id=line_id, proposal_id=UUID(stored["id"])
    )


async def test_a_draft_queued_inside_a_live_run_is_announced_and_stop_cancels_it() -> None:
    """FAILS IF: a draft queued while a run is live is not noted on the run (no `event:
    draft`, nothing for Stop to cancel), or Stop's cancel does not reach the script writer's
    `cancel_draft` and the draft keeps writing."""
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    campaign_id = await _campaign_of(tenant_id, agent_id, main_task="Renew every policy.")
    proposal = await _propose_draft(tenant_id, token, {"holder_id": str(campaign_id)})

    control = run_control.RunControl(owner="client:test", run_id=uuid.uuid4(), tenant_id=tenant_id)
    active = run_control.activate(control)
    try:
        outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    finally:
        run_control.deactivate(active)
    assert outcome.draft is not None
    assert control.take_unsent_drafts() == [
        run_control.StartedDraft("campaign", campaign_id, outcome.draft.proposal_id)
    ]

    assert run_control.draft_canceller() is script_draft.cancel_draft
    await control.cancel_drafts()
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT script_proposal FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert stored is None


async def test_with_a_line_and_a_campaign_pip_asks_which_one_to_rewrite() -> None:
    """FAILS IF: Pip guesses which of an agent's scripts to rewrite."""
    from apps.api.inbound import lines

    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    campaign_id = await _campaign_of(tenant_id, agent_id, main_task="Renew every policy.")
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Front desk",
            main_task="Book visits.",
            created_by=None,
        )
    with pytest.raises(WriteRefusedError) as asked:
        await _propose_draft(tenant_id, token, {"agent_id": str(agent_id)})
    assert "ask the person which one" in asked.value.reason
    assert str(line_id) in asked.value.reason and str(campaign_id) in asked.value.reason
    proposal = await _propose_draft(
        tenant_id, token, {"agent_id": str(agent_id), "holder_id": str(line_id)}
    )
    assert "the Inbound line “Front desk”" in proposal.summary


async def test_the_draft_refusals_the_model_can_act_on() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    with pytest.raises(WriteRefusedError) as none:
        await _propose_draft(tenant_id, token, {"agent_id": str(agent_id)})
    assert "no Inbound line or campaign" in none.value.reason

    bare = await _campaign_of(tenant_id, agent_id, main_task=None)
    with pytest.raises(WriteRefusedError) as no_task:
        await _propose_draft(tenant_id, token, {"holder_id": str(bare)})
    assert "no main task" in no_task.value.reason

    with pytest.raises(WriteRefusedError) as long:
        too_long = "x" * (INSTRUCTION_MAX + 1)
        await _propose_draft(tenant_id, token, {"holder_id": str(bare), "instruction": too_long})
    assert f"at most {INSTRUCTION_MAX} characters" in long.value.reason
    assert "never drop a change" in long.value.reason


async def test_staff_and_a_neighbours_campaign_get_no_draft() -> None:
    tenant_id, _slug, token = await _make_tenant()
    neighbour, _, _ = await _make_tenant()
    theirs = await _campaign_of(neighbour, await _agent_of(neighbour), main_task="Renew.")
    with pytest.raises(WriteRefusedError) as missing:
        await _propose_draft(tenant_id, token, {"holder_id": str(theirs)})
    assert "names nothing in this account" in missing.value.reason

    ours = await _campaign_of(tenant_id, await _agent_of(tenant_id), main_task="Renew.")
    with pytest.raises(WriteRefusedError) as refused:
        await _propose_draft(tenant_id, token, {"holder_id": str(ours)}, role="staff")
    assert "role may not" in refused.value.reason
