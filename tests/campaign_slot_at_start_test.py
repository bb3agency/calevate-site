"""A scheduled campaign claims its engine-agent slot when it starts, not when it is set (D-1010).

Founder, 17 Nov 2026: "Claim the slot at start: scheduling holds nothing; the slot is taken
when the campaign starts. If it is refused then, the owner is told at that moment."

1. Scheduling makes no engine agent, and still refuses what a publish would refuse.
2. The tick that fires the start makes it, and the campaign runs through it.
3. A refusal at that moment does not start the campaign: it is on the schedule, the
   campaign's band names it, and it is retried only every `PUT_LIVE_RETRY`.
4. A start that does not fire after the claim gives the slot back; so does a repeat between
   runs, and the hourly sweep retires one a scheduled campaign still holds.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.campaigns import scheduling, service
from apps.api.campaigns.routes import router as campaigns_router
from apps.api.campaigns.scheduling import (
    PUT_LIVE_RETRY,
    START_NOT_READY_RULE,
    schedule_campaign,
    schedule_recurrence,
)
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.db.session import tenant_session
from apps.workers import campaign_dispatch, campaign_engine_agents
from calevate_shared.call_script import CallScript
from fastapi import FastAPI
from sqlalchemy import text
from tests.agent_lifecycle_test import _client, _code, _fresh_engine
from tests.campaign_engine_agents_test import _campaign, _live_agent
from tests.campaign_schedule_test import (  # noqa: F401 (fixtures, autouse)
    _daytime,
    _leave_the_platform_quiet,
    _ready_campaign,
    _roomy_platform_pool,
)

pytestmark = pytest.mark.rls

SCRIPT = CallScript(opening_line="Namaste, Sched Motors here about your test drive.")


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(campaigns_router)
    return application


async def _held(tenant_id: UUID, campaign_id: UUID) -> tuple[str, str | None, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref, schedule FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).one()
    return str(row[0]), (str(row[1]) if row[1] else None), row[2]


async def _due_with_script(*, recurring: bool = False) -> tuple[UUID, UUID]:
    """A launch-ready campaign with a script of its own, whose start is due now."""
    tenant_id, _agent, campaign_id = await _ready_campaign()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c"),
            {"s": SCRIPT.model_dump_json(), "c": campaign_id},
        )
        if recurring:
            await schedule_recurrence(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                days=[1, 2, 3, 4, 5, 6, 7],
                at=datetime.strptime("10:00", "%H:%M").time(),
                until=None,
            )
        else:
            await schedule_campaign(
                session,
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                start_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        # Due now, through the column and shape the scheduler writes.
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{start_at}', "
                "to_jsonb(CAST(:at AS text))) WHERE id = :c"
            ),
            {"at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(), "c": campaign_id},
        )
    return tenant_id, campaign_id


# ------------------------------------------------------------------ 1. scheduling


async def test_scheduling_a_campaign_makes_no_engine_agent() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, overrides={"max_call_duration_s": 300})
    token = await _owner_token(tenant_id)
    made_before = len(engine._agents)

    async with _client(_app()) as http:
        response = await http.post(
            f"/v1/campaigns/{campaign_id}/schedule",
            json={"start_at": (datetime.now(UTC) + timedelta(days=6)).isoformat()},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    status, ref, _schedule = await _held(tenant_id, campaign_id)
    assert status == "scheduled"
    assert ref is None, "a start set for next week took a slot now"
    assert len(engine._agents) == made_before


async def test_scheduling_still_refuses_what_its_start_could_never_publish() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id)
    token = await _owner_token(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :a"),
            {"a": agent_id},
        )

    async with _client(_app()) as http:
        response = await http.post(
            f"/v1/campaigns/{campaign_id}/schedule",
            json={"start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 409, response.text
    assert _code(response.json()) == "agent_archived"
    status, ref, _schedule = await _held(tenant_id, campaign_id)
    assert (status, ref) == ("draft", None)


async def _owner_token(tenant_id: UUID) -> str:
    """The dev bearer of the owner `_tenant` made for this organisation."""
    async with tenant_session(tenant_id) as session:
        user_id = (
            await session.execute(
                text("SELECT user_id FROM memberships WHERE tenant_id = :t LIMIT 1"),
                {"t": tenant_id},
            )
        ).scalar_one()
    return f"dev:client:{user_id}"


# ------------------------------------------------------------------ 2. the start


async def test_the_start_makes_the_engine_agent_and_runs_through_it() -> None:
    _fresh_engine()
    tenant_id, campaign_id = await _due_with_script()
    assert (await _held(tenant_id, campaign_id))[1] is None

    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 1

    status, ref, _schedule = await _held(tenant_id, campaign_id)
    assert status == "running"
    assert ref is not None, "the start did not claim its slot"


# ------------------------------------------------------------------ 3. a refusal at start


async def test_a_refusal_at_start_is_settled_and_the_owner_is_told(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id = await _due_with_script()
    tries: list[UUID] = []

    async def refused(*, tenant_id: UUID, campaign_id: UUID) -> str | None:
        tries.append(campaign_id)
        raise ProblemError(
            kind="dependency",
            code="engine_publish_not_applied",
            title="The voice platform is not running this change",
            detail="read-back differed",
        )

    monkeypatch.setattr(scheduling, "put_campaign_live", refused)

    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0
    status, ref, schedule = await _held(tenant_id, campaign_id)
    assert (status, ref) == ("scheduled", None), "a refused start started or held a slot"
    assert schedule["last_blocked"]["rules"] == [START_NOT_READY_RULE]
    async with tenant_session(tenant_id) as session:
        progress = await service.campaign_progress(session, campaign_id)
    assert progress["schedule_blocked_rules"] == [START_NOT_READY_RULE]

    # The next tick does not try the platform again inside `PUT_LIVE_RETRY`...
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0
    assert len(tries) == 1
    # ...and does once it has passed.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{last_put_live,at}', "
                "to_jsonb(CAST(:at AS text))) WHERE id = :c"
            ),
            {
                "at": (datetime.now(UTC) - PUT_LIVE_RETRY - timedelta(seconds=1)).isoformat(),
                "c": campaign_id,
            },
        )
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0
    assert len(tries) == 2


async def test_a_full_workspace_at_start_is_named_as_the_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id = await _due_with_script()

    async def full(*, tenant_id: UUID, campaign_id: UUID) -> str | None:
        raise ProblemError.business_rule(
            agents_service.ENGINE_AGENT_ALLOWANCE_FULL_RULE,
            "Starting needs a free calling setup. Your account can have 2, and both are in use.",
        )

    monkeypatch.setattr(scheduling, "put_campaign_live", full)

    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0
    status, _ref, schedule = await _held(tenant_id, campaign_id)
    assert status == "scheduled"
    assert schedule["last_blocked"]["rules"] == [agents_service.ENGINE_AGENT_ALLOWANCE_FULL_RULE]


# ------------------------------------------------------------------ 4. giving it back


async def test_a_claimed_start_that_does_not_fire_gives_the_slot_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, campaign_id = await _due_with_script()

    async def blocked(*_args: object, **_kwargs: object) -> str:
        return "blocked"

    monkeypatch.setattr(campaign_dispatch, "fire_schedule", blocked)

    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 0
    status, ref, _schedule = await _held(tenant_id, campaign_id)
    assert (status, ref) == ("scheduled", None)


async def test_a_repeat_gives_its_slot_back_between_runs() -> None:
    tenant_id, campaign_id = await _due_with_script(recurring=True)
    async with tenant_session(tenant_id) as session:
        # Its run has dialled everyone and holds the engine agent the start made.
        await session.execute(
            text(
                "UPDATE campaigns SET status = 'running', engine_agent_ref = :r, "
                "engine_agent_at = now() WHERE id = :c"
            ),
            {"r": f"agent_run_{campaign_id.hex[:8]}", "c": campaign_id},
        )
        await session.execute(
            text("UPDATE campaign_contacts SET status = 'connected' WHERE campaign_id = :c"),
            {"c": campaign_id},
        )
    async with tenant_session(tenant_id) as session:
        assert await campaign_dispatch._settle_finished_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )

    status, ref, _schedule = await _held(tenant_id, campaign_id)
    assert (status, ref) == ("scheduled", None), "a repeat kept its slot between runs"


async def test_the_sweep_retires_an_engine_agent_a_scheduled_campaign_still_holds() -> None:
    tenant_id, campaign_id = await _due_with_script()
    ref = f"agent_old_{campaign_id.hex[:8]}"
    async with tenant_session(tenant_id) as session:
        # Published when its start was set, before D-1010.
        await session.execute(
            text(
                "UPDATE campaigns SET engine_agent_ref = :r, "
                "engine_agent_at = now() - interval '2 hours', "
                "schedule = jsonb_set(schedule, '{start_at}', to_jsonb(CAST(:at AS text))) "
                "WHERE id = :c"
            ),
            {
                "r": ref,
                "at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
                "c": campaign_id,
            },
        )
    async with tenant_session(tenant_id) as session:
        retired = await campaign_engine_agents._retire_unneeded(session, tenant_id=tenant_id)

    assert retired >= 1
    status, held, schedule = await _held(tenant_id, campaign_id)
    assert (status, held) == ("scheduled", None)
    assert json.loads(json.dumps(schedule))["kind"] == "one_time", "the start itself is kept"
