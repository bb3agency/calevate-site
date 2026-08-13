"""The dispatch tick at real tenant counts: what does ONE tick cost?

`dispatch_campaign_tick` runs every 30 seconds and is the only thing that turns a
running campaign into dials. Its cost was O(ALL ORGANIZATIONS): `admin_session` can
enumerate tenants but cannot read `campaigns` across them, so the tick opened one
transaction per organization to ask "anything running here?". Measured on a development
database before the fix:

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

**THE POPULATION IS BUILT HERE, NOT WAITED FOR.** A ratio needs a denominator, and this
file used to borrow one: it skipped itself below 500 ambient organizations. That is
backwards. A freshly migrated and seeded database — which is exactly what CI runs, and
the only place this assertion could stop the regression reaching production — always
skipped, while a developer's accumulated junk drawer was the only thing that ever
executed it. `_population()` now creates the organizations the comparison needs and
removes every one of them again, so the test proves the same thing on an empty database
and on a 33,000-organization one.

Two assertion styles, deliberately:

- what the test OWNS is asserted EXACTLY — each provisioned dispatchable tenant is
  opened exactly once, each provisioned idle organization is never opened at all;
- what the AMBIENT database holds is asserted as SET DIFFERENCES against two censuses
  taken either side of the tick, so a concurrent suite publishing an agent mid-tick
  moves which set its tenant is in rather than how much slack the assertion needs. The
  only allowance left is `2 * DISPATCHABLE` tenants, and it is sized by what one
  concurrent run of THIS file transiently creates — not by how big the database is.
  That is the whole complaint against the old absolute `DRIFT_SLACK = 400`: it was 3.5%
  of an 11k-tenant database and a hundredfold allowance on a freshly seeded one, so it
  meant two different things depending on whose laptop ran it.

WHAT NONE OF THAT COVERS, and why the per-tenant term is counted on DISTINCT tenants
rather than on sessions: a tick's total session count is

    distinct dispatchable tenants  +  2 per campaign it dispatches  +  1 per dial

Measured, exactly, on a 33,298-organization / 12,070-route database: 12,995 sessions =
12,070 tenants + (2 x 289 campaigns + 347 dials). The second term is the documented
per-campaign cost in `_dispatch_for_campaign` (claim transaction, one transaction per
dial, completion transaction) and it scales with RUNNING CAMPAIGNS, not with tenants —
so folding it into a per-tenant budget is what made the old absolute slack look like a
leak on a database with a thousand abandoned campaigns in it. Distinct tenants is the
number the property is actually about, and it is exact.
"""

from __future__ import annotations

import contextlib
import uuid
from collections import Counter
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

# The organizations this test provisions so the two candidate shapes are distinguishable
# on ANY database, including a freshly seeded one.
#
# 250 is chosen against what it has to buy, not for a round number. The exact assertions
# below (opened-exactly-once, never-opened, the two census set differences) already fail
# on a per-organization tick with a population of one; its job is to guarantee a
# FLOOR of discrimination — after `_population()` runs, at least 225 organizations exist
# that a correct tick provably ignores — so that the "not O(organizations)" claim is
# never vacuously true on a small database. On a large one the census differences are far
# stronger than the floor, and get stronger the more polluted the database is.
#
# The cost is ~250 one-row transactions to create and the same to remove: ~1.6s on the
# development box, measured. Raising it buys a larger floor and nothing else, and this
# file already pays for five ticks.
POPULATION = 250
# ...of which this many are DISPATCHABLE: an agent published to the engine, i.e. an
# `engine_agent_routes` row. They carry no campaign, which is what makes them a clean
# probe — a correct tick must open exactly ONE session for each (the scan), and a tick
# that opened two would be doing per-tenant work twice.
DISPATCHABLE = 25
IDLE = POPULATION - DISPATCHABLE


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

    @property
    def distinct(self) -> int:
        """Tenants the tick touched AT ALL — the per-tenant term of the cost, isolated
        from the per-campaign one, which reopens tenants the scan already visited."""
        return len(set(self.tenants))

    def opened(self) -> Counter[uuid.UUID]:
        return Counter(self.tenants)


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


class Population:
    """The organizations one test owns, split by whether a tick may open them."""

    def __init__(self, dispatchable: list[uuid.UUID], idle: list[uuid.UUID]) -> None:
        self.dispatchable = dispatchable
        self.idle = idle


@contextlib.asynccontextmanager
async def _population() -> AsyncIterator[Population]:
    """`POPULATION` organizations, `DISPATCHABLE` of them published — then gone again.

    Rows, not `create_organization` calls. The old tick's cost was one transaction per
    row in `organizations`, so a bare organization row IS the thing it paid for, and the
    realistic case — a fully onboarded client whose agent was never published — is
    covered next door by `test_an_organization_that_cannot_dial_is_never_opened`, which
    goes through the wizard for exactly two tenants. Building 250 of those instead would
    be ~30x the runtime and would prove nothing this does not.

    It also makes the population REMOVABLE, which is the other half of the defect. Every
    FK into `organizations` is `ON DELETE RESTRICT`, and `usage_events` / `audit_log` /
    `consent_ledger` are append-only by hard rule 4 — so a tenant that has been through
    onboarding and a call can never be deleted again, and the local databases have
    33,000 organizations to prove it. These rows have exactly three dependents, all
    written here, all removed here, in FK order.

    Writes and deletes go through `tenant_session`: `organizations`' policy is
    `USING (id = app.tenant_id ...)` with `WITH CHECK (id = app.tenant_id)`, so a
    tenant-scoped session covers both halves with no widening at all. `admin_session`
    would do the delete in one statement, but it is the ADMIN-REALM widening (hard rule
    1) and a fixture is not an admin-realm principal.
    """
    tag = f"dscale-pop-{uuid.uuid4().hex[:8]}"
    dispatchable: list[uuid.UUID] = []
    idle: list[uuid.UUID] = []
    routes: list[dict[str, Any]] = []
    try:
        for n in range(POPULATION):
            tenant_id = uuid7()
            publish = n < DISPATCHABLE
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug, status, created_at, "
                        "updated_at) VALUES (:id, 'Scale Motors', :slug, 'active', now(), now())"
                    ),
                    {"id": tenant_id, "slug": f"{tag}-{n:04d}"},
                )
                if publish:
                    agent_id, ref = uuid7(), f"{tag}-{n:04d}"
                    await session.execute(
                        text(
                            "INSERT INTO agents (id, tenant_id, name, direction, "
                            "disclosure_line, status, engine, engine_agent_ref, created_at, "
                            "updated_at) VALUES (:id, :tid, 'Receptionist', 'outbound', "
                            "'Idi AI assistant.', 'live', 'fake', :ref, now(), now())"
                        ),
                        {"id": agent_id, "tid": tenant_id, "ref": ref},
                    )
                    routes.append({"ref": ref, "tid": tenant_id, "aid": agent_id})
            (dispatchable if publish else idle).append(tenant_id)

        # `engine_agent_routes` is the global bridge (no RLS, by design — see
        # `_dispatchable_tenants`), so the whole published set lands in one executemany.
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, created_at, updated_at) VALUES ('fake', :ref, :tid, "
                    ":aid, true, now(), now())"
                ),
                routes,
            )
        yield Population(dispatchable, idle)
    finally:
        # FK order — routes are unreferenced, then the agent, then the organization every
        # other row points at. No swallowing: a population this test cannot remove is the
        # very defect this file is about, so it fails loudly rather than leaking rows.
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM engine_agent_routes WHERE engine_agent_ref LIKE :p"),
                {"p": f"{tag}-%"},
            )
        published = set(dispatchable)
        for tenant_id in dispatchable + idle:
            async with tenant_session(tenant_id) as session:
                if tenant_id in published:
                    await session.execute(
                        text("DELETE FROM agents WHERE tenant_id = :id"), {"id": tenant_id}
                    )
                await session.execute(
                    text("DELETE FROM organizations WHERE id = :id"), {"id": tenant_id}
                )


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


async def _census() -> tuple[int, set[uuid.UUID]]:
    """(organizations, the dispatchable tenant SET) — the two candidate shapes for a tick.

    The tenants come back as a set rather than a count so the assertions can be
    differences instead of inequalities: a set difference survives a concurrent suite
    publishing an agent mid-tick, and it names the offending tenant when it does fail.
    Twelve thousand uuids is ~30ms and one round trip.
    """
    async with admin_session() as directory:
        orgs = (
            await directory.execute(
                text("SELECT count(*) FROM organizations WHERE deleted_at IS NULL")
            )
        ).scalar()
    async with untenanted_session() as session:
        routed = (
            (await session.execute(text("SELECT DISTINCT tenant_id FROM engine_agent_routes")))
            .scalars()
            .all()
        )
    return int(orgs or 0), {uuid.UUID(str(row)) for row in routed}


async def test_a_tick_costs_one_session_per_dispatchable_tenant_not_one_per_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this file exists for.

    Before: one transaction per organization, two queries inside each — 15,941 sessions
    and 44.9s on a job scheduled every 30 seconds.

    The comparison needs a database where "one per organization" and "one per
    dispatchable tenant" are different numbers, so this test MAKES one: `POPULATION`
    organizations, `DISPATCHABLE` of them published. Whatever else the database holds,
    it now holds at least `IDLE` organizations that a correct tick provably never opens.
    Every claim below names the rows it is about rather than comparing two totals, which
    is what lets it mean the same thing on an empty database and on a 33,000-org one.
    """
    tenant_id, agent_id = await _tenant()
    await _running_campaign(tenant_id, agent_id)

    async with _population() as population:
        _, routed_before = await _census()
        with _measure(monkeypatch) as visits:
            await dispatch_campaign_tick({})
        orgs_after, routed_after = await _census()

        opened = visits.opened()
        assert tenant_id in opened, "the tick must still visit a tenant that is dialling"

        # THE PROPERTY, stated on rows this test owns, with no tolerance at all.
        # These 25 tenants have a published agent and no campaign: the scan must open
        # each exactly once, and nothing else may reopen them.
        wrong = {t: opened[t] for t in population.dispatchable if opened[t] != 1}
        assert not wrong, (
            f"{len(wrong)} of {DISPATCHABLE} dispatchable tenants were not opened exactly "
            f"once (counts: {sorted(wrong.values())[:5]})"
        )
        # ...and the other shape, from the other side: an organization with no engine
        # route is not worth a transaction. This is the 13,000-organization bill.
        trespass = [t for t in population.idle if t in opened]
        assert not trespass, (
            f"the tick opened {len(trespass)} of {IDLE} organizations that can never dial — "
            "it is still O(organizations)"
        )

        # The AMBIENT population — every other suite's tenants — bounded as two set
        # differences rather than a count comparison. A tenant published or unpublished
        # by a concurrent suite mid-tick moves which set it belongs to, not how much
        # slack the assertion needs.
        #
        # Never SKIP a tenant that could dial: a tenant with a route on both sides of the
        # tick had one during it, and an outbound line it holds must be counted or rules
        # 1+2 hand its lines to somebody else. Exact, no allowance.
        missed = (routed_before & routed_after) - set(visits.tenants)
        assert not missed, (
            f"the tick skipped {len(missed)} tenants with a published agent, e.g. "
            f"{sorted(str(t) for t in missed)[:3]}"
        )
        # ...and never open a tenant that has no route at all, which is the cost claim
        # against the ambient database (`orgs_after` organizations, `len(routed_after)`
        # of them dispatchable). The allowance is not a database-sized fudge factor: the
        # ONLY code anywhere that deletes an `engine_agent_routes` row is `_population`
        # above, so the one thing neither census can see is a sibling run of THIS file
        # whose whole create-tick-delete cycle fell inside this tick. `DISPATCHABLE` is
        # what one such run creates; two of them is already generous, and it means the
        # same thing at 4 dispatchable tenants as at 12,070 — which the old absolute
        # `DRIFT_SLACK = 400` did not.
        stray = set(visits.tenants) - (routed_before | routed_after)
        assert len(stray) <= 2 * DISPATCHABLE, (
            f"the tick opened {len(stray)} tenants with no engine route, out of "
            f"{orgs_after} organizations and {len(routed_after)} dispatchable tenants"
        )

        # One `set_config` + one combined statement per tenant scanned, plus the
        # reap/gate/claim/dial statements of the campaigns actually dispatched. The `2`
        # is the load-bearing coefficient — splitting the combined per-tenant SELECT back
        # into two queries is the regression this catches. `sessions - distinct` is the
        # repeat visits, which for a correct tick are exactly the per-campaign
        # transactions; `wrong` above pins that to one visit per tenant for the 25 this
        # test owns. Measured: 2.00 queries per scanned tenant, 5.03 per dispatch
        # session; 12 leaves the dispatch term room to grow a gate without pretending to
        # police it — the per-TENANT term is what this line is for.
        dispatch_sessions = visits.sessions - visits.distinct
        assert visits.queries <= 2 * visits.distinct + 12 * dispatch_sessions + 8, (
            f"{visits.queries} queries for {visits.distinct} tenants scanned and "
            f"{dispatch_sessions} dispatch sessions"
        )


async def test_an_organization_that_cannot_dial_is_never_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The narrowing has to be a rule, not an average.

    A tenant with no published agent cannot hold an outbound call row and cannot launch
    a campaign (`agent_not_live` blocks it), so a session opened for it can only ever
    return zeros. That is the 13,000 organizations the old tick spent its interval on.

    Two FULLY onboarded tenants, through the wizard, which is what the test above trades
    away for scale: this one proves the rule holds for a real client record and not only
    for the bare organization rows `_population()` builds.
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
