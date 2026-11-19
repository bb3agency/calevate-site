"""Every start of a campaign goes through one door, and test holders give way safely.

1. Start, a scheduled start and Pip's launch share `put_live_for_start`: Pip's launch publishes
   the campaign's own engine agent (a test holder it held is republished for its calls), and
   `launch_campaign` refuses a campaign still holding one outside the client's workspace.
2. The launch gate counts a calling setup only for a campaign Start would make one for.
3. "A test call may still be on it" is bounded by the longest test call allowed, and a holder
   given back at once waits for a connected call and keeps its webhook until it is deleted.
4. The deletion job leaves alone a client-workspace test copy a test call made again, and the
   idle sweep skips a copy whose agent is being republished.
5. An edit's publish puts nothing live for a campaign no longer running or paused.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import paid_test_calls
from apps.api.agents import service as agents_service
from apps.api.campaigns import engine_agent, service
from apps.api.compliance.trial_access import TRIAL_LINE_MARGIN, live_test_call_horizon
from apps.api.copilot import agent_actions
from apps.api.copilot.actions import ToolActor
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.reliability import engine_webhooks
from apps.workers import engine_workspaces as jobs
from calevate_shared.call_script import CallScript
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine
from tests.campaign_engine_agents_test import _campaign, _live_agent
from tests.campaign_schedule_test import (  # noqa: F401 (fixtures, autouse)
    _daytime,
    _leave_the_platform_quiet,
    _ready_campaign,
    _roomy_platform_pool,
)

pytestmark = pytest.mark.rls

SCRIPT = CallScript(opening_line="Namaste, Start Motors here about your service visit.")


def _workspace() -> str:
    return f"org_{uuid.uuid4().hex[:12]}"


async def _exec(tenant_id: UUID, sql: str, **params: Any) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(text(sql), params)


async def _scalar(tenant_id: UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).scalar()


async def _with_script(campaign_id: UUID, tenant_id: UUID) -> None:
    await _exec(
        tenant_id,
        "UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c",
        s=SCRIPT.model_dump_json(),
        c=campaign_id,
    )


async def _held(tenant_id: UUID, campaign_id: UUID) -> tuple[str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).one()
    return str(row[0]), (str(row[1]) if row[1] else None)


def _actor(tenant_id: UUID) -> ToolActor:
    return ToolActor(tenant_id=tenant_id, user_id=uuid.uuid4(), role="owner", impersonating=False)


# --- 1. one door for every start -------------------------------------------------------------


async def test_pips_launch_republishes_the_test_holder_before_it_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, _agent, campaign_id = await _ready_campaign()
    await _with_script(campaign_id, tenant_id)
    async with tenant_session(tenant_id) as session:
        holder = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id, test=True
        )
    publishes: list[bool] = []
    real = agents_service.publish_campaign_agent

    async def recorded(session: Any, **kwargs: Any) -> str | None:
        publishes.append(bool(kwargs.get("test")))
        return await real(session, **kwargs)

    monkeypatch.setattr(agents_service, "publish_campaign_agent", recorded)

    async with tenant_session(tenant_id) as session:
        done = await agent_actions._execute_campaign_launch(
            session, _actor(tenant_id), {"campaign_id": str(campaign_id)}
        )

    assert done.applied
    assert publishes == [False], "Pip's launch did not publish the campaign for its calls"
    assert await _held(tenant_id, campaign_id) == ("running", holder)


async def test_pips_launch_refused_by_the_gate_makes_no_engine_agent() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id, campaign_id = await _ready_campaign()
    await _with_script(campaign_id, tenant_id)
    await _exec(
        tenant_id,
        "UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :a",
        a=agent_id,
    )
    made_before = len(engine._agents)

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError):
            await agent_actions._execute_campaign_launch(
                session, _actor(tenant_id), {"campaign_id": str(campaign_id)}
            )

    assert len(engine._agents) == made_before
    assert await _held(tenant_id, campaign_id) == ("draft", None)


async def test_a_campaign_holding_a_test_holder_outside_its_workspace_does_not_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, _agent, campaign_id = await _ready_campaign()
    workspace = _workspace()

    async def resolve(_session: Any, _tenant: UUID) -> str:
        return workspace

    monkeypatch.setattr(service, "engine_has_workspaces", lambda *_a, **_k: True)
    monkeypatch.setattr(service, "resolve_workspace", resolve)
    # A test holder in our developer workspace, left by a start whose publish did not happen.
    await _exec(
        tenant_id,
        "UPDATE campaigns SET engine_agent_ref = 'dev_holder_1', engine_agent_at = now() "
        "WHERE id = :c",
        c=campaign_id,
    )

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    rules = [field["rule"] for field in refused.value.fields or []]
    assert rules == [service.START_NOT_READY_RULE]
    assert (await _held(tenant_id, campaign_id))[0] == "draft"

    # One held in the client's own workspace starts.
    await _exec(
        tenant_id,
        "UPDATE campaigns SET engine_agent_ref = :r WHERE id = :c",
        r=f"camp_1@{workspace}",
        c=campaign_id,
    )
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    assert (await _held(tenant_id, campaign_id))[0] == "running"


# --- 2. a calling setup is counted only where Start would make one ---------------------------


@pytest.mark.parametrize("needs_one", [True, False])
async def test_the_gate_counts_a_setup_only_for_a_campaign_that_makes_one(
    monkeypatch: pytest.MonkeyPatch, needs_one: bool
) -> None:
    _fresh_engine()
    tenant_id, _agent, campaign_id = await _ready_campaign()

    async def full(*_a: Any, **_k: Any) -> tuple[str, str, tuple[Any, ...]]:
        return (agents_service.ENGINE_AGENT_ALLOWANCE_FULL_RULE, "Both setups are in use.", ())

    async def needs(_session: Any, _campaign_id: UUID) -> bool:
        return needs_one

    monkeypatch.setattr(service, "engine_agent_allowance_blocker", full)
    monkeypatch.setattr(engine_agent, "needs_its_own", needs)

    async with tenant_session(tenant_id) as session:
        rules = {
            b.rule
            for b in await service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        }
    assert (agents_service.ENGINE_AGENT_ALLOWANCE_FULL_RULE in rules) is needs_one


# --- 3. the longest test call, and giving a holder back at once ------------------------------


def test_the_live_horizon_is_the_longest_test_call_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = agents_service.get_settings()
    monkeypatch.setattr(settings, "trial_call_max_seconds", 180)
    monkeypatch.setattr(settings, "own_number_test_max_seconds", 900)
    assert live_test_call_horizon() == timedelta(seconds=900) + TRIAL_LINE_MARGIN
    monkeypatch.setattr(settings, "own_number_test_max_seconds", 120)
    assert live_test_call_horizon() == timedelta(seconds=180) + TRIAL_LINE_MARGIN


async def test_an_own_number_test_call_past_the_shared_lines_limit_still_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    settings = agents_service.get_settings()
    monkeypatch.setattr(settings, "trial_call_max_seconds", 180)
    monkeypatch.setattr(settings, "own_number_test_max_seconds", 900)
    tenant_id, agent_id = await _live_agent()
    workspace = _workspace()
    holder_ref, copy_ref = f"camp_2@{workspace}", f"copy_2@{workspace}"
    await _exec(
        tenant_id,
        "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref, business_only) "
        "VALUES (:id, :t, :a, :r, false)",
        id=uuid7(),
        t=tenant_id,
        a=agent_id,
        r=copy_ref,
    )
    # Ten minutes in: past the shared line's 3 minutes plus margin, inside the own number's 15.
    for ref in (holder_ref, copy_ref):
        await _exec(
            tenant_id,
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
            "paid_test_call, engine_agent_ref, status, created_at, updated_at) VALUES (:id, :t, "
            ":a, :e, 'outbound', '+919876543210', true, :r, 'in_progress', "
            "now() - interval '10 minutes', now())",
            id=uuid7(),
            t=tenant_id,
            a=agent_id,
            e=f"own-{uuid.uuid4().hex}",
            r=ref,
        )
    async with tenant_session(tenant_id) as session:
        assert await agents_service._holder_call_live(session, holder_ref)
        assert await paid_test_calls.copy_call_live(session, agent_id)


async def test_a_holder_given_back_at_once_waits_for_a_connected_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id, test=True
        )
    steps: list[str] = []

    async def connected(*, engine: str, engine_agent_ref: str) -> bool:
        steps.append("asked")
        return True

    async def webhook(*_a: Any, **_k: Any) -> None:
        steps.append("webhook")

    monkeypatch.setattr(agents_service, "call_connected_on", connected)
    monkeypatch.setattr(engine_webhooks, "retire_agent_webhook", webhook)
    async with tenant_session(tenant_id) as session:
        deleted = await agents_service._delete_holder_now(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, ref=ref
        )
    assert deleted is False
    assert steps == ["asked"], "a holder with a call on it lost its webhook"
    assert ref in engine._agents


async def test_a_refused_delete_keeps_the_holders_webhook_and_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id, test=True
        )
    steps: list[str] = []

    async def refuse(_ref: str) -> None:
        steps.append("delete")
        raise ProblemError.conflict("agent_on_live_call", "A call is on this agent.")

    async def actions(*, agent_id: Any, ref: Any) -> int:
        steps.append("actions")
        return 0

    async def webhook(*_a: Any, **_k: Any) -> None:
        steps.append("webhook")

    monkeypatch.setattr(engine, "delete_agent", refuse)
    monkeypatch.setattr(agents_service, "retire_in_call_actions", actions)
    monkeypatch.setattr(engine_webhooks, "retire_agent_webhook", webhook)
    async with tenant_session(tenant_id) as session:
        deleted = await agents_service._delete_holder_now(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, ref=ref
        )
    assert deleted is False
    assert steps == ["delete"]


# --- 4. a test copy made again is not deleted under its test call ----------------------------


async def _copy(tenant_id: UUID, agent_id: UUID, ref: str, *, aged: str = "3 hours") -> None:
    await _exec(
        tenant_id,
        "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref, business_only, "
        "last_used_at) VALUES (:id, :t, :a, :r, false, now() - CAST(:aged AS interval))",
        id=uuid7(),
        t=tenant_id,
        a=agent_id,
        r=ref,
        aged=aged,
    )


async def test_the_deletion_job_leaves_a_client_workspace_copy_made_again() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    ref = f"copy_3@{_workspace()}"
    await _copy(tenant_id, agent_id, ref)
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": ref}
    assert await jobs.retire_moved_engine_agent({"job_try": 1}, payload) == "held_again"
    assert await _scalar(
        tenant_id, "SELECT count(*) FROM agent_test_copies WHERE engine_agent_ref = :r", r=ref
    )


async def test_the_idle_sweep_skips_a_copy_whose_agent_is_being_republished() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    ref = f"copy_4@{_workspace()}"
    await _copy(tenant_id, agent_id, ref)
    idle = timedelta(hours=1).total_seconds()

    async with tenant_session(tenant_id) as publishing:
        # `refresh_test_copy`'s publish holds the agent row across the platform round trip.
        await publishing.execute(
            text("SELECT 1 FROM agents WHERE id = :a FOR UPDATE"), {"a": agent_id}
        )
        async with tenant_session(tenant_id) as sweeping:
            retired = await asyncio.wait_for(
                agents_service.retire_idle_client_test_copies(
                    sweeping, tenant_id=tenant_id, idle_seconds=idle
                ),
                timeout=10,
            )
        assert retired == 0
    assert await _scalar(
        tenant_id, "SELECT count(*) FROM agent_test_copies WHERE engine_agent_ref = :r", r=ref
    )

    async with tenant_session(tenant_id) as session:
        assert (
            await agents_service.retire_idle_client_test_copies(
                session, tenant_id=tenant_id, idle_seconds=idle
            )
            == 1
        )
    # Owed without the once-ever key, so a copy made again can be given back again.
    owed = await _scalar(
        tenant_id,
        "SELECT count(*) FROM outbox_messages WHERE job = :job AND payload->>'old_ref' = :r "
        "AND dedupe_key IS NULL",
        job=agents_service.RETIRE_MOVED_AGENT_JOB,
        r=ref,
    )
    assert owed == 1


# --- 5. an edit's publish leaves a campaign that stopped alone -------------------------------


async def test_an_edit_puts_nothing_live_for_a_campaign_no_longer_holding_one() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    draft = await _campaign(tenant_id, agent_id)
    made_before = len(engine._agents)
    assert (
        await engine_agent.put_campaign_live(
            tenant_id=tenant_id, campaign_id=draft, require_holding=True
        )
        is None
    )
    assert len(engine._agents) == made_before
    assert await _held(tenant_id, draft) == ("draft", None)

    running = await _campaign(tenant_id, agent_id, status="running")
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=running
        )
    assert (
        await engine_agent.put_campaign_live(
            tenant_id=tenant_id, campaign_id=running, require_holding=True
        )
        == ref
    )
    # Stopped between the caller's read and the publish: nothing is put live.
    await _exec(tenant_id, "UPDATE campaigns SET status = 'cancelled' WHERE id = :c", c=running)
    async with tenant_session(tenant_id) as session:
        assert (
            await agents_service.publish_campaign_agent(
                session, tenant_id=tenant_id, campaign_id=running, require_holding=True
            )
            is None
        )


# --- 6. a campaign's test holder the platform no longer has ----------------------------------


async def test_a_campaigns_test_holder_gone_at_the_platform_is_made_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    # A holder the platform no longer has (the fake would find its own again by name tag).
    gone = f"gone_{uuid.uuid4().hex[:8]}"
    await _exec(
        tenant_id,
        "UPDATE campaigns SET engine_agent_ref = :r, engine_agent_at = now() WHERE id = :c",
        r=gone,
        c=campaign_id,
    )
    await _exec(
        tenant_id,
        "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
        "campaign_id, active, created_at, updated_at) VALUES ('fake', :r, :t, :a, :c, true, "
        "now(), now())",
        r=gone,
        t=tenant_id,
        a=agent_id,
        c=campaign_id,
    )
    real_update = engine.update_agent

    async def update(ref: str, cfg: Any) -> None:
        if ref == gone:
            raise ProblemError.not_found("Agent")
        await real_update(ref, cfg)

    monkeypatch.setattr(engine, "update_agent", update)
    async with tenant_session(tenant_id) as session:
        ref = await agents_service.publish_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=campaign_id, test=True
        )
    assert ref is not None and ref != gone and ref in engine._agents
    assert await _held(tenant_id, campaign_id) == ("draft", ref)
    assert not await _scalar(
        tenant_id, "SELECT active FROM engine_agent_routes WHERE engine_agent_ref = :r", r=gone
    )

    # A running campaign dials through its engine agent: losing that one is the failure.
    await _exec(tenant_id, "UPDATE campaigns SET status = 'running' WHERE id = :c", c=campaign_id)

    async def update_live(_ref: str, _cfg: Any) -> None:
        raise ProblemError.not_found("Agent")

    monkeypatch.setattr(engine, "update_agent", update_live)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await agents_service.publish_campaign_agent(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
    assert refused.value.kind == "not_found"
