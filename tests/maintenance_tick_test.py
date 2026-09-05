"""The tick, driven end to end: one window from scheduled to completed.

WHY THIS FILE EXISTS BESIDE THE OTHER TWO. `maintenance_drain_test.py` drives the state
machine and `maintenance_surface_test.py` drives the refusals; both call the pieces
directly. Neither runs `maintenance_tick`, which is the ONE thing that actually moves a
window — and a feature whose orchestrator no test executes is a feature whose seams are
asserted individually and wired by hope. This is the pass that proves they meet:

    scheduled -> draining (campaigns paused, agents told what to say)
              -> active   (only because nothing was in flight; the shed mode flips)
              -> completed (mode restored, campaigns resumed, agents put back)

...and that the three client notices are queued exactly once each, on the outbox, in the
same transaction as the claim that says they were sent.

⚠ **THIS SUITE MOVES GLOBAL STATE AND IS THE ONLY MAINTENANCE FILE THAT DOES.** It writes
`platform_state.load_shed_mode`, which every other suite reads, and it holds
`platform_maintenance_windows`' single open slot. `platform_halt_test`'s discipline
applies and is followed literally: one window, the fewest statements that prove the
property, and both restored in `finally`. Run under CPU contention it can be slow; it can
never leave the platform shed.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents.service import publish_agent
from apps.api.core.loadshed import get_platform_status, set_platform_status
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops.maintenance import InFlight, read_window, schedule_window
from apps.workers.maintenance import NOTIFY_JOB, maintenance_tick
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio


def _answers(in_flight: InFlight) -> Callable[..., Awaitable[InFlight]]:
    """A `probe_in_flight` that answers a fixed measurement.

    Takes and ignores the walk budget the caller passes, because what is being replaced is
    the MEASUREMENT and not the walking — a stub with the wrong signature would pass this
    test and fail against the real call site.
    """

    async def _probe(*_args: object, **_kwargs: object) -> InFlight:
        return in_flight

    return _probe


async def _clear() -> None:
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE job = :job"), {"job": NOTIFY_JOB}
        )
        await session.execute(text("DELETE FROM platform_maintenance_windows"))


async def _notices(tenant_id: uuid.UUID) -> list[str]:
    """Which notices are queued FOR ONE CLIENT, in the order the outbox holds them.

    Scoped to a tenant on purpose. The fan-out writes one row per open client and this
    development database carries several thousand from other suites, so an unscoped count
    would assert a number that changes with whatever else has run. What each edge owes is
    one notice per client, and the client this test made is the one it can speak for.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload->>'kind' FROM outbox_messages "
                    "WHERE job = :job AND payload->>'tenant_id' = :tid "
                    "ORDER BY created_at, id"
                ),
                {"job": NOTIFY_JOB, "tid": str(tenant_id)},
            )
        ).all()
    return [str(row[0]) for row in rows]


async def _live_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with a LIVE inbound agent the engine knows, and a running campaign.

    The routing row is what puts this tenant into `_CALLABLE_TENANTS_SQL`, which is the
    directory every walk in the worker uses — without it the tick would find no tenants and
    the test would pass having exercised nothing.
    """
    created = await admin_service.create_organization(
        name="Tick Clinic",
        slug=f"tick-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    # PUBLISHED THROUGH THE REAL PATH, not by writing `engine_agent_ref` into the row.
    # `publish_agent` is what puts the agent on the (fake) engine AND writes the
    # `engine_agent_routes` bridge the worker's every walk reads — an UPDATE would give
    # this test a ref the engine has never heard of, and the override it is here to prove
    # would fail against an agent that does not exist.
    # The publish gate refuses an account that has not accepted its agreements — supplied
    # rather than assumed away, exactly as `agent_lifecycle_test` does.
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
        # A script, because publishing without one is refused by name — the same two-line
        # fixture `agent_lifecycle_test._write_script` uses.
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Tick Clinic.\n",
            notes=None,
            created_by=None,
        )
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return tenant_id, agent_id


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "status, concurrency, created_at, updated_at) VALUES "
                "(:id, :t, :a, :n, 'service', 'running', 3, now(), now())"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id, "n": f"tick-{campaign_id.hex[:6]}"},
        )
    return campaign_id


async def _campaign_status(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM campaigns WHERE id = :id"), {"id": campaign_id}
                )
            ).scalar()
        )


async def test_one_window_from_scheduled_to_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole pass, asserted at every edge.

    The window is scheduled two seconds out and its end is moved by hand rather than
    waited for: what is under test is that each EDGE does its work, not that the clock
    advances. Nothing here sleeps.

    ⚠ **THE PROBE IS STUBBED, AND THAT IS THE SUBJECT OF THIS TEST RATHER THAN A HOLE IN
    IT.** `probe_in_flight` counts non-terminal calls and pending queued work across the
    whole database, and a shared development database is never empty — every other suite
    leaves calls and outbox rows behind, so a real probe here answers "232 calls, 1416
    jobs" and the window correctly refuses to activate. Emptying those populations would
    mean deleting other suites' fixtures; waiting for them is not a thing a test can do.

    So the ARITHMETIC is tested where it belongs (`maintenance_drain_test`: the status set,
    the truncated walk, `InFlight.drained`, and one real run of the probe), and what is
    tested HERE is what nothing else can see — that the tick asks the probe, believes the
    answer in both directions, and does the right work at each edge. The stub is asked for
    BOTH answers below for exactly that reason.
    """
    restore = (await get_platform_status(force_refresh=True)).mode
    await _clear()
    tenant_id, agent_id = await _live_tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        window = await schedule_window(
            session,
            reason="Upgrading the telephony stack. Nothing is deleted.",
            starts_at=now + timedelta(seconds=2),
            ends_at=now + timedelta(hours=1),
            max_drain_minutes=15,
            actor_id=None,
        )
    try:
        # ── 1. NOT YET. A scheduled window whose time has not come changes nothing, and
        #       the advance notice is not due either (it goes 24h out; this window is 2
        #       seconds out, so the lead time has already passed and it IS due).
        first = await maintenance_tick({})
        assert first.startswith("scheduled"), first
        assert await _notices(tenant_id) == ["advance"], "the advance notice did not go out"
        assert await _campaign_status(tenant_id, campaign_id) == "running"

        # ── 2. THE WINDOW OPENS. Backdate the start rather than sleeping.
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE platform_maintenance_windows "
                    "SET starts_at = now() - interval '1 second' WHERE id = :id"
                ),
                {"id": window.id},
            )
        second = await maintenance_tick({})
        assert second.startswith("draining"), second
        async with untenanted_session() as session:
            draining = await read_window(session, window.id)
        assert draining.state == "draining"
        assert draining.drain_deadline_at is not None, "no deadline for the operator to see"
        # The campaign stopped, and it is MARKED as ours to resume.
        assert await _campaign_status(tenant_id, campaign_id) == "paused"
        async with tenant_session(tenant_id) as session:
            marked = (
                await session.execute(
                    text("SELECT paused_by_maintenance_id FROM campaigns WHERE id = :id"),
                    {"id": campaign_id},
                )
            ).scalar()
        assert marked == window.id
        # THE PORTAL IS STILL OPEN. This is the two-state model's whole point, and the
        # shed mode is what would close it.
        assert (await get_platform_status(force_refresh=True)).mode != "maintenance"
        # And the caller message reached the (fake) engine.
        async with tenant_session(tenant_id) as session:
            ref = (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar()
        from apps.api.engine import get_engine

        snapshot = await get_engine().get_agent(str(ref))
        assert snapshot.carries_greeting_marker("maintenance") is True, (
            "an inbound caller during this window would hear the ordinary greeting"
        )

        # ── 3. IT DOES NOT ACTIVATE WHILE WORK IS IN FLIGHT. The founder's "ONLY when",
        #       at the orchestration level: the tick asks, is told there is a call up, and
        #       stays draining — reporting the numbers rather than a spinner.
        monkeypatch.setattr(
            "apps.workers.maintenance.probe_in_flight",
            _answers(InFlight(calls=1, jobs=0, tenants_unreached=0, complete=True)),
        )
        held = await maintenance_tick({})
        assert held == "draining calls=1 jobs=0", held
        async with untenanted_session() as session:
            still = await read_window(session, window.id)
        assert still.state == "draining", "a live call did not stop the window activating"
        assert still.in_flight == {
            "calls": 1,
            "jobs": 0,
            "tenants_unreached": 0,
            "complete": True,
        }, "the console would show no numbers for the operator to wait on"
        assert (await get_platform_status(force_refresh=True)).mode != "maintenance"

        # ── 3a. AND IT ACTIVATES THE MOMENT THE ANSWER CHANGES.
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE job = :job"), {"job": NOTIFY_JOB}
            )
        monkeypatch.setattr(
            "apps.workers.maintenance.probe_in_flight",
            _answers(InFlight(calls=0, jobs=0, tenants_unreached=0, complete=True)),
        )
        third = await maintenance_tick({})
        assert third.startswith("active"), third
        async with untenanted_session() as session:
            active = await read_window(session, window.id)
        assert active.state == "active"
        assert active.forced is False, "a clean drain was reported as forced"
        assert active.stragglers is None
        # NOW the portal is shut, and it is shut by the mode this feature reuses rather
        # than by a second mechanism.
        assert (await get_platform_status(force_refresh=True)).mode == "maintenance"
        assert await _notices(tenant_id) == ["active"]

        # ── 3b. AN AMENDMENT MADE *DURING* THE WINDOW RE-ANNOUNCES, which is the
        #        amendment operators actually make: extending the end because the work is
        #        running long. Handled only on the scheduled arm, that correction never
        #        reached a client — and the clients holding the old end time are exactly
        #        the ones who planned around it.
        from apps.api.ops.maintenance import amend_window

        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE job = :job"), {"job": NOTIFY_JOB}
            )
            await amend_window(
                session,
                window_id=window.id,
                ends_at=datetime.now(UTC) + timedelta(hours=3),
            )
        assert (await maintenance_tick({})).startswith("active")
        assert await _notices(tenant_id) == ["amended"], (
            "an end time moved mid-window was never told to the clients holding the old one"
        )
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE job = :job"), {"job": NOTIFY_JOB}
            )

        # ── 4. IT ENDS. `ends_at` in the past is exactly what "end now" writes.
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE platform_maintenance_windows "
                    "SET ends_at = now() - interval '1 second' WHERE id = :id"
                ),
                {"id": window.id},
            )
        fourth = await maintenance_tick({})
        assert fourth.startswith("completed"), fourth
        async with untenanted_session() as session:
            done = await read_window(session, window.id)
        assert done.state == "completed"
        assert done.ended_at is not None
        # The portal is back, the campaign is back where it was, and the marker is gone.
        assert (await get_platform_status(force_refresh=True)).mode == restore
        assert await _campaign_status(tenant_id, campaign_id) == "running"
        async with tenant_session(tenant_id) as session:
            cleared = (
                await session.execute(
                    text("SELECT paused_by_maintenance_id FROM campaigns WHERE id = :id"),
                    {"id": campaign_id},
                )
            ).scalar()
        assert cleared is None, "the marker became history instead of answering 'right now'"
        assert await _notices(tenant_id) == ["ended"]
        # And the agent says its own words again — the failure a client would otherwise
        # feel one caller at a time for as long as nobody looked.
        restored = await get_engine().get_agent(str(ref))
        assert restored.carries_greeting_marker("maintenance") is False, (
            "an agent is still telling callers the platform is down after the window"
        )

        # ── 5. AND THE TICK IS IDEMPOTENT. A terminal window is not open, so the next
        #       pass finds nothing and does nothing.
        assert await maintenance_tick({}) == "no_window"
    finally:
        await set_platform_status(mode=restore, actor_id=None)
        await _clear()
