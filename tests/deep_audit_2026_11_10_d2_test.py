"""Deep audit D2 (10 Nov 2026): backend correctness findings, each failing before its fix.

SHARED DATABASE DISCIPLINE: every row is minted here and every assertion is scoped to it.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.api.billing.engine_minutes import engine_minute_cost
from apps.api.campaigns import service as campaigns
from apps.api.core.errors import ProblemError
from apps.api.crm.service import dashboard
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import pipeline, retention
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from tests.campaign_transitions_test import _launchable_campaign
from tests.campaign_transitions_test import _tenant as _outbound_tenant
from tests.conftest import create_org_with_receptionist
from tests.smoke_pipeline_test import _seed_tenant

# --- Z3-N1: a late call of a retired route is metered at its own route's rate --------------


async def _route(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, ref: str, active: bool, rate_key: str
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, engine_rate_key, created_at, updated_at) VALUES "
                "('thinnest', :r, :t, :a, :active, :k, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id, "active": active, "k": rate_key},
        )


async def test_a_late_call_of_a_retired_route_is_metered_at_that_routes_rate() -> None:
    """The agent was recreated on another rung (the old copy retired, a new one active).
    A result of the OLD copy that arrives afterwards was priced at the new copy's rate,
    because the rate key was read from the agent's active route, not the call's."""
    at = datetime(2002, 3, 7, tzinfo=UTC) + timedelta(
        microseconds=uuid.uuid4().int % 86_400_000_000
    )
    tenant_id, agent_id = await _seed_tenant(f"d2rate_{uuid.uuid4().hex[:10]}")
    old_ref, new_ref = f"d2old_{uuid.uuid4().hex}", f"d2new_{uuid.uuid4().hex}"
    await _route(tenant_id, agent_id, ref=old_ref, active=False, rate_key="studio")
    await _route(tenant_id, agent_id, ref=new_ref, active=True, rate_key="premium")
    now = datetime.now(UTC)
    snapshot = ExecutionSnapshot(
        engine_call_id=f"d2_{uuid.uuid4().hex}",
        direction="inbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=60),
        ended_at=now,
        duration_s=60,
        engine_agent_ref=old_ref,
    )
    call_id = await pipeline._upsert_call(tenant_id, agent_id, snapshot, old_ref)

    async def cost(ref: str | None) -> str:
        async with tenant_session(tenant_id) as session:
            priced = await engine_minute_cost(
                session,
                engine="thinnest",
                tenant_id=tenant_id,
                call_id=call_id,
                seconds=Decimal(60),
                at=at,
                engine_agent_ref=ref,
            )
        return priced.rate_key

    assert await cost(old_ref) == "studio"
    # No ref (or one no route carries): the agent's active route, as before.
    assert await cost(None) == "premium"


# --- Z2-N3: a contact upload racing a launch -----------------------------------------------


async def test_a_contact_upload_racing_a_launch_is_never_left_unscrubbed() -> None:
    """The upload read the campaign `draft` unlocked while a launch was gating, scrubbing
    and switching it to `running`; the upload's rows then landed under the running campaign
    after the DNC scrub. A number on the business's do-not-call list stayed `pending`."""
    tenant_id, agent_id, _ = await _outbound_tenant()
    campaign_id = await _launchable_campaign(tenant_id, agent_id)
    phone = f"+9198765{uuid.uuid4().int % 100_000:05d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (gen_random_uuid(), :t, :p, 'tenant', 'call_optout', "
                "now(), now())"
            ),
            {"t": tenant_id, "p": phone},
        )

    uploaded = asyncio.Event()
    release = asyncio.Event()

    async def upload() -> None:
        async with tenant_session(tenant_id) as session:
            await campaigns.add_contacts(
                session, tenant_id=tenant_id, campaign_id=campaign_id, contacts=[{"phone": phone}]
            )
            uploaded.set()
            await release.wait()

    async def launch() -> None:
        # Refused on the grown list is also a safe outcome.
        with contextlib.suppress(ProblemError):
            async with tenant_session(tenant_id) as session:
                await campaigns.launch_campaign(
                    session, tenant_id=tenant_id, campaign_id=campaign_id
                )

    uploader = asyncio.create_task(upload())
    await uploaded.wait()
    launcher = asyncio.create_task(launch())
    await asyncio.sleep(0.5)
    release.set()
    await uploader
    await asyncio.wait_for(launcher, timeout=30)

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
        contact = (
            await session.execute(
                text(
                    "SELECT status FROM campaign_contacts WHERE campaign_id = :c "
                    "AND phone_e164 = :p"
                ),
                {"c": campaign_id, "p": phone},
            )
        ).scalar_one()
    assert not (status == "running" and contact == "pending"), (status, contact)


# --- Z9-N3: tenant erasure locks its request -------------------------------------------------


async def test_a_redriven_tenant_erasure_meeting_the_original_runs_once() -> None:
    created = await create_org_with_receptionist(
        name="D2 Erasure",
        slug=f"d2-erase-{uuid.uuid4().hex[:8]}",
        vertical_template="custom",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned', updated_at = now() WHERE id = :t"),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": request_id, "t": tenant_id},
        )

    holder_has_row = asyncio.Event()
    release = asyncio.Event()

    async def first_run_completing() -> None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("SELECT 1 FROM tenant_erasure_requests WHERE id = :id FOR UPDATE"),
                {"id": request_id},
            )
            await session.execute(
                text("UPDATE tenant_erasure_requests SET completed_at = now() WHERE id = :id"),
                {"id": request_id},
            )
            holder_has_row.set()
            await release.wait()

    holder = asyncio.create_task(first_run_completing())
    await holder_has_row.wait()
    payload = {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    second = asyncio.create_task(retention.execute_tenant_erasure({}, payload))
    await asyncio.sleep(0.5)
    release.set()
    await holder
    assert await asyncio.wait_for(second, timeout=60) == "already_completed"


# --- the dashboard's "Calls today" and today's bar are one count -----------------------------


async def test_calls_today_counts_what_todays_bar_counts() -> None:
    """A dial that failed before ringing has no `started_at`. It is in today's bar (filed by
    `lens.CALL_AT`) and its "missed" link, and was missing from "Calls today"."""
    created = await create_org_with_receptionist(
        name="D2 Today",
        slug=f"d2-today-{uuid.uuid4().hex[:8]}",
        vertical_template="custom",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        for started in (datetime.now(UTC) - timedelta(minutes=1), None):
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                    "'outbound', :s, :at, now(), now())"
                ),
                {
                    "id": uuid7(),
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"d2_{uuid.uuid4().hex}",
                    "s": "completed" if started else "failed",
                    "at": started,
                },
            )
        out = await dashboard(session)
    assert out.daily_7d[-1].total == 2
    assert out.calls_today == 2
