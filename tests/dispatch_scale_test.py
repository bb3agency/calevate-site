"""The dispatch tick at real tenant counts: what does ONE tick cost?

`dispatch_campaign_tick` runs every 30 seconds and is the only thing that turns a
running campaign into dials. Its cost was O(ALL ORGANIZATIONS): `admin_session` can
enumerate tenants but cannot read `campaigns` across them, so the tick opened one
transaction per organization to ask "anything running here?". Measured on this
development database before the fix:

    15,941 tenant sessions · 47,825 queries · 44.9s   — for a job scheduled every 30s

A tick that cannot finish inside its own interval is not a slow campaign. Ticks queue
behind each other, the due contacts pile up, and the campaign silently stops dialling
while the UI still says "running".

So the metric under test is the SESSION AND QUERY COUNT, not wall-clock — this box is
shared with other pytest processes and the clock says more about them than about the
dispatcher. The shape asserted here is: one session per DISPATCHABLE tenant (a tenant
with a published agent — `engine_agent_routes`, the same global bridge the stall alarm
and the reconciliation poller resolve tenants through), plus one per campaign actually
dialled for. Not one per organization.

Everything is scoped to tenants this module creates, because the 15,000+ organizations
that make the test meaningful belong to everybody.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, get_engine, tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import dispatch_campaign_tick
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

# How many extra sessions a tick may open beyond the tenants it must visit. Other
# pytest processes publish agents against this same database while this test runs, so
# the dispatchable set grows under our feet; this covers that drift plus the per-
# campaign dispatch sessions. It is two orders of magnitude below the organization
# count, which is the difference the test is about.
DRIFT_SLACK = 400


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST — inside every calling window, so nothing here is skipped for hours."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(autouse=True)
def _roomy_platform_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the platform line pool (FLOWS §5 rule 1) above anything anyone else is
    dialling: the pool is deliberately platform-wide, and another suite's in-flight
    calls would otherwise decide how many contacts this one gets."""
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10_000)


class Visits:
    """Every tenant session and every SQL statement a tick issued."""

    def __init__(self) -> None:
        self.tenants: list[uuid.UUID] = []
        self.queries = 0

    @property
    def sessions(self) -> int:
        return len(self.tenants)


@contextlib.contextmanager
def _measure(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Count what a tick costs, from the two places that can lie about it least:
    the session factory it opens and the cursor the driver executes."""
    visits = Visits()
    real = campaign_dispatch.tenant_session

    @contextlib.asynccontextmanager
    async def counting(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
        visits.tenants.append(uuid.UUID(str(tenant_id)))
        async with real(tenant_id) as session:
            yield session

    monkeypatch.setattr(campaign_dispatch, "tenant_session", counting)

    engine = get_engine().sync_engine

    def _count(*_args: Any, **_kwargs: Any) -> None:
        visits.queries += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        yield visits
    finally:
        event.remove(engine, "before_cursor_execute", _count)


async def _tenant(*, published: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant, optionally with its agent published to the engine.

    Publishing is what writes the `engine_agent_routes` row (`publish_agent` does both
    in one transaction), and it is also what `launch_blockers` demands before a campaign
    may run — which is why the route table is a superset of the tenants a tick can act
    on. `published=False` gives the other case: an organization that exists and can
    never be dialled for.
    """
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Scale Motors",
        slug=f"dscale-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    if not published:
        return tenant_id, agent_id

    ref = f"fakeagent_dscale_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _running_campaign(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, concurrency: int = 2, contacts: int = 3
) -> uuid.UUID:
    """A launched campaign — through `launch_campaign`, so the compliance gate runs.

    Everything the gate asks for is SUPPLIED, never skipped: the client's DLT Principal
    Entity registration and its Calevate TM link, an approved promotional template on a
    140-series number, and the consent provenance of the list. Hard rule 5 has no
    "for testing" door, and a fixture that opened one would be testing a dispatcher
    nobody runs.
    """
    async with tenant_session(tenant_id) as session:
        await service.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"PE{uuid.uuid4().int % 10**10:010d}",
            entity_name="Scale Motors",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
        number_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, created_at, "
                "updated_at) VALUES (:id, :tid, :e, '140', 'registered', now(), now())"
            ),
            {"id": number_id, "tid": tenant_id, "e": f"+9180{uuid.uuid4().int % 100000000:08d}"},
        )
        template_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {
                "id": template_id,
                "tid": tenant_id,
                "body": "Hello from {#var#}, this is an AI assistant calling about your enquiry.",
            },
        )
        campaign_id = await service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Scale offers",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=concurrency,
            consent_source="inbound_enquiry",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[
                {"phone": f"98765{n:05d}", "name": f"Lead {n}"} for n in range(10, 10 + contacts)
            ],
        )
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    return campaign_id


async def _census() -> tuple[int, int]:
    """(organizations, dispatchable tenants) — the two candidate shapes for a tick."""
    async with admin_session() as directory:
        orgs = (
            await directory.execute(
                text("SELECT count(*) FROM organizations WHERE deleted_at IS NULL")
            )
        ).scalar()
    async with untenanted_session() as session:
        routed = (
            await session.execute(text("SELECT count(DISTINCT tenant_id) FROM engine_agent_routes"))
        ).scalar()
    return int(orgs or 0), int(routed or 0)


async def test_a_tick_costs_one_session_per_dispatchable_tenant_not_one_per_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this file exists for.

    Before: one transaction per organization, two queries inside each. This database
    holds 15,000+ organizations and ~2,200 tenants with a published agent, so the tick
    was doing roughly seven times the work it could ever use — and taking 45s over it,
    which is longer than the interval it is scheduled on.
    """
    tenant_id, agent_id = await _tenant()
    await _running_campaign(tenant_id, agent_id)

    orgs, routed = await _census()
    with _measure(monkeypatch) as visits:
        await dispatch_campaign_tick({})

    assert tenant_id in visits.tenants, "the tick must still visit a tenant that is dialling"
    assert visits.sessions <= routed + DRIFT_SLACK, (
        f"one session per dispatchable tenant: {visits.sessions} sessions "
        f"for {routed} tenants with a published agent"
    )
    # One `set_config` + one combined statement per tenant, plus the claim/gate/dial
    # statements for campaigns actually dispatched.
    assert visits.queries <= 2 * visits.sessions + 10 * DRIFT_SLACK

    if orgs < 500:
        pytest.skip(f"database holds only {orgs} organizations — the shapes are indistinguishable")
    assert visits.sessions < orgs // 2, (
        f"the tick is still O(organizations): {visits.sessions} sessions for {orgs} orgs"
    )


async def test_an_organization_that_cannot_dial_is_never_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The narrowing has to be a rule, not an average.

    A tenant with no published agent cannot hold an outbound call row and cannot launch
    a campaign (`agent_not_live` blocks it), so a session opened for it can only ever
    return zeros. That is the 13,000 organizations the old tick spent its interval on.
    """
    idle_tenant, _ = await _tenant(published=False)
    live_tenant, live_agent = await _tenant()
    await _running_campaign(live_tenant, live_agent)

    with _measure(monkeypatch) as visits:
        await dispatch_campaign_tick({})

    assert live_tenant in visits.tenants
    assert idle_tenant not in visits.tenants, "an organization with no engine route costs nothing"


async def test_the_worker_never_takes_the_admin_role_to_find_its_tenants() -> None:
    """`admin_session` widens `organizations` for a verified ADMIN-REALM PRINCIPAL
    (db/session.py says so in capitals). A cron worker is not one, and it no longer
    needs to be: `engine_agent_routes` is a global table by design, so the resolution
    happens under `untenanted_session` with no widening at all (hard rule 1)."""
    assert not hasattr(campaign_dispatch, "admin_session")


async def test_the_narrowed_tick_still_dials_exactly_the_campaign_slider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cheaper is only a fix if the work still happens: FLOWS §5 rule 4 end to end,
    through the same tick the cost tests measure."""
    tenant_id, agent_id = await _tenant()
    campaign_id = await _running_campaign(tenant_id, agent_id, concurrency=2, contacts=5)

    with _measure(monkeypatch):
        await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        dialing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :c "
                    "AND status = 'dialing'"
                ),
                {"c": campaign_id},
            )
        ).scalar()
        calls = (
            await session.execute(text("SELECT count(*) FROM calls WHERE direction = 'outbound'"))
        ).scalar()
    assert dialing == 2, "the slider is a ceiling, not a suggestion"
    assert calls == 2


async def test_two_campaigns_in_one_tenant_still_share_one_tenant_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FLOWS §5 rule 3 is a per-TENANT budget spent once, oldest campaign first — the
    bug where it was computed per campaign let one client claim twice its ceiling out
    of the pool holding another client's receptionist open. The campaign list now
    arrives as one aggregated column instead of its own query, so the property is
    re-asserted on the new read path.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, concurrency_ceiling, effective_from, "
                "created_at, updated_at) VALUES (:id, :tid, 3, now(), now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id},
        )
    first = await _running_campaign(tenant_id, agent_id, concurrency=3, contacts=5)
    second = await _running_campaign(tenant_id, agent_id, concurrency=3, contacts=5)

    with _measure(monkeypatch):
        await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        rows = dict(
            (
                await session.execute(
                    text(
                        "SELECT campaign_id, count(*) FROM campaign_contacts "
                        "WHERE status = 'dialing' GROUP BY campaign_id"
                    )
                )
            ).all()
        )
    dialing = {uuid.UUID(str(k)): int(v) for k, v in rows.items()}
    assert sum(dialing.values()) == 3, "the ceiling is the tenant's, not each campaign's"
    assert dialing.get(first) == 3, "oldest campaign first, deterministically"
    assert second not in dialing
