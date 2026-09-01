"""The dispatch tick at real tenant counts: what does ONE tick cost?

`dispatch_campaign_tick` runs every 30 seconds and is the only thing that turns a
running campaign into dials. Its cost has been measured, and reshaped, twice:

    one transaction per ORGANIZATION            15,941 sessions · 47,825 queries · 44.9s
    one transaction per DISPATCHABLE tenant     12,070 sessions ·  ~24,000 queries · 22.9s
    one query, server-side loop (D-57)          per-campaign sessions only  ·  ~0.25s

A tick that cannot finish inside its own interval is not a slow campaign. Ticks queue
behind each other, the due contacts pile up, and the campaign silently stops dialling
while the UI still says "running".

The middle shape is the one this file used to pin, and its remaining cost was not query
time. Measured, split by where the wall clock went at 12,070 dispatchable tenants:

    session setup (checkout + pre_ping + BEGIN + set_config)   11.02s   48%
    the per-tenant SELECT itself                                6.76s   30%
    COMMIT + return to pool                                     4.91s   21%
    the tenant-list query                                       0.28s    1%

Two thirds was session machinery, and 80% of the wall clock was CPU inside the worker
process rather than time waiting on Postgres — which is why parallelising the loop
measured 22.9s → 17.2s at 8-way (1.3x, not 8x: one event loop cannot parallelise its own
CPU). D-57 therefore deleted the sessions instead of spreading them: `dispatch_scan()`
walks the same tenants inside Postgres, under the same per-tenant `app.tenant_id`, and
returns only the ones holding a line or running a campaign.

So the metric under test is the SESSION AND QUERY COUNT, not wall-clock — this box is
shared with other pytest processes and the clock says more about them than about the
dispatcher. **The shape asserted here is: a tenant with a published agent and nothing to
do is not opened AT ALL**, and the tick's query count carries no per-tenant term.

**THE POPULATION IS BUILT HERE, NOT WAITED FOR.** A ratio needs a denominator, and this
file used to borrow one: it skipped itself below 500 ambient organizations. That is
backwards. A freshly migrated and seeded database — which is exactly what CI runs, and
the only place this assertion could stop the regression reaching production — always
skipped, while a developer's accumulated junk drawer was the only thing that ever
executed it. `_population()` now creates the organizations the comparison needs and
removes every one of them again, so the test proves the same thing on an empty database
and on a 33,000-organization one.

Two assertion styles, deliberately:

- what the test OWNS is asserted EXACTLY — each provisioned dispatchable tenant is never
  opened, each provisioned idle organization is never opened, and the one provisioned
  tenant that IS dialling is opened for its campaign and no more;
- what the AMBIENT database holds is asserted as SET DIFFERENCES against two censuses
  taken either side of the tick, so a concurrent suite launching a campaign mid-tick
  moves which set its tenant is in rather than how much slack the assertion needs.

WHAT NONE OF THAT COVERS, and it is worth stating rather than implying: the scan is
still O(dispatchable tenants) INSIDE POSTGRES — 12,070 index-only probe pairs, measured
at 0.25s warm and 0.45s on a connection's first call. That is a loop, not a cap; nothing
is skipped, nothing rotates, no tenant waits for a later tick. What changed is that a
tenant now costs ~20µs of Postgres instead of ~1.9ms of connection.
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
from tests.conftest import accept_agreements
from tests.national_dnd_test import record_test_scrub

# The organizations this test provisions so the two candidate shapes are distinguishable
# on ANY database, including a freshly seeded one.
#
# 250 is chosen against what it has to buy, not for a round number. The exact assertions
# below (never-opened, the census set differences) already fail on a per-organization
# tick with a population of one; its job is to guarantee a FLOOR of discrimination —
# after `_population()` runs, at least 250 organizations exist that a correct tick
# provably ignores, 25 of them with a PUBLISHED agent, which is the case the previous
# shape got wrong and the current one has to keep getting right. On a large database the
# census differences are far stronger than the floor, and get stronger the more polluted
# the database is.
#
# The cost is ~250 one-row transactions to create and the same to remove: ~1.6s on the
# development box, measured. Raising it buys a larger floor and nothing else, and this
# file already pays for five ticks.
POPULATION = 250
# ...of which this many are DISPATCHABLE: an agent published to the engine, i.e. an
# `engine_agent_routes` row. They carry no campaign, which is what makes them a clean
# probe — a correct tick must open ZERO sessions for them, and the shape this file
# replaced opened exactly one each.
DISPATCHABLE = 25
IDLE = POPULATION - DISPATCHABLE

# What one tick may spend, with NO per-tenant term — that absence is the whole property.
#
# Measured on the 33,298-organization / 12,070-route development database: a tick that
# dispatches one campaign issues 21 queries across 4 sessions (1 scan + 1 platform-state
# read, then the budget read, the reap/gate/claim transaction, one per dial, and the
# completion check). The coefficients below are those, rounded up so a gate may be added
# to the dispatch path without this line pretending to police it. What it does police is
# the term that is not here: a tick that opened a session per dispatchable tenant would
# need ~12,000 of both, and no value of these constants can absorb that.
QUERY_BASE = 8
QUERIES_PER_SESSION = 12

# Every tenant `_tenant()` builds, so the fixture below can quiet them again.
_TENANTS: list[uuid.UUID] = []


@pytest.fixture(scope="module", autouse=True)
async def _settle_what_this_module_started() -> AsyncIterator[None]:
    """Leave the shared platform as quiet as we found it.

    This file launches campaigns and lets them dial, on a Postgres shared with every
    other suite and every other pytest process. A `running` campaign left behind is
    picked up by every later tick — and now that a tick's cost is proportional to
    running campaigns, this file's litter would show up as somebody else's session count
    rather than as a slow scan. A `queued`/`in_progress` call row is worse: it spends a
    line out of the platform-wide pool (FLOWS §5 rule 1) for a full
    `ACTIVE_CALL_HORIZON`.

    Scoped to `_TENANTS` — the ones this module created — and never a `LIKE` sweep, which
    is how a cleanup ends up cancelling a campaign another process launched one second
    ago. The pattern is `tests/campaign_dispatch_audit_test.py`'s.
    """
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'cancelled', updated_at = now() "
                    "WHERE status IN ('running', 'paused')"
                )
            )
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    f"WHERE status IN {campaign_dispatch.ACTIVE_STATUSES!r}"
                )
            )


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
        """Tenants the tick touched AT ALL — which, after D-57, is exactly the tenants
        it had a reason to dial for."""
        return len(set(self.tenants))

    def opened(self) -> Counter[uuid.UUID]:
        return Counter(self.tenants)


@contextlib.contextmanager
def _measure(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Count what a tick costs, from the two places that can lie about it least:
    the session factory it opens and the cursor the driver executes.

    The cursor counter sees ROUND TRIPS, which is what the client pays for. The
    statements `dispatch_scan()` runs inside its own loop are not round trips and do not
    appear here — that is the point of the change, and the module docstring gives their
    measured cost so nobody mistakes one query for no work.
    """
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

    **The first published tenant gets TWO routes, not one.** `dispatch_scan()` walks
    `SELECT DISTINCT tenant_id FROM engine_agent_routes`, and on a population where
    every tenant has exactly one agent, deleting that DISTINCT changes no output — the
    sabotage would pass. One tenant with two published agents is what makes the
    de-duplication observable, and `test_a_tenant_with_two_published_agents_is_scanned_once`
    is what observes it.

    It also makes the population REMOVABLE, which is the other half of the defect. Every
    FK into `organizations` is `ON DELETE RESTRICT`, and `usage_events` / `audit_log` /
    `consent_ledger` are append-only by hard rule 4 — so a tenant that has been through
    onboarding and a call can never be deleted again, and the local databases have
    33,000 organizations to prove it. These rows have exactly three dependents, all
    written here, all removed here, in FK order.

    Writes go through `tenant_session`; the organization's DELETE goes through
    `admin_session`, and that split is the point rather than a convenience. This fixture
    used to do both on the tenant session, arguing that it needed no widening because
    `organizations`' policy is `USING (id = app.tenant_id ...)` with
    `WITH CHECK (id = app.tenant_id)` — but `WITH CHECK` is not consulted on DELETE, so
    what that actually relied on was a tenant session being able to hard-delete its own
    tenancy anchor. Migration `d1b8f30c94a7` closes that, and the cleanup moves rather
    than the schema staying open to accommodate a fixture. The widening it takes is the
    narrow one: `app.admin` widens `USING` on `organizations` ONLY (it unlocks no calls,
    no leads, no transcripts, and no `WITH CHECK` anywhere), and it is used here to
    remove rows this fixture minted itself.
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
                    # Tenant 0 publishes twice: see the docstring on DISTINCT.
                    for suffix in ("a", "b") if n == 0 else ("a",):
                        agent_id, ref = uuid7(), f"{tag}-{n:04d}{suffix}"
                        await session.execute(
                            text(
                                "INSERT INTO agents (id, tenant_id, name, direction, "
                                "disclosure_line, ai_disclosure_line, recording_notice_line, "
                                "caller_memory_notice_line, status, engine, engine_agent_ref, "
                                "created_at, updated_at) VALUES (:id, :tid, 'Receptionist', "
                                "'outbound', 'Idi AI assistant.', 'Idi AI assistant.', 'This "
                                "call is being recorded.', 'I keep a short note of what you ask "
                                "about.', 'live', 'fake', :ref, now(), now())"
                            ),
                            {"id": agent_id, "tid": tenant_id, "ref": ref},
                        )
                        routes.append({"ref": ref, "tid": tenant_id, "aid": agent_id})
            (dispatchable if publish else idle).append(tenant_id)

        # `engine_agent_routes` is the global bridge (no RLS, by design — see
        # `_tenants_with_work`), so the whole published set lands in one executemany.
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
            # The organization goes through an ADMIN session, not the tenant's own.
            # `organizations_delete_admin_only` (migration d1b8f30c94a7) is RESTRICTIVE
            # FOR DELETE: a tenant session may no longer destroy its own tenancy anchor,
            # because `WITH CHECK` is not consulted on DELETE and `USING` alone had been
            # letting it. RLS filters rather than raises, so a cleanup left on the tenant
            # session would have gone on "succeeding" while leaking every organization
            # this fixture mints — which is why the rowcount is asserted rather than
            # assumed. The comment above promises this fails loudly; this is what makes
            # that true.
            async with admin_session() as session:
                removed = await session.execute(
                    text("DELETE FROM organizations WHERE id = :id"), {"id": tenant_id}
                )
                assert removed.rowcount == 1, (
                    f"cleanup could not remove organization {tenant_id}: a population this "
                    "test cannot remove is the very defect this file is about"
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
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    _TENANTS.append(tenant_id)
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
        # ONE registered header per AGENT, bound to it, reused by every campaign this
        # agent runs (D-424). Bound, because the launch gate refuses a campaign whose
        # approved number is not the number its agent dials from. Reused, because
        # `resolve_caller_id` refuses an agent carrying two registered headers — and this
        # suite calls this fixture TWICE for one agent (the shared-tenant-budget test), so
        # a header per campaign would make every dial refuse while the "share one budget"
        # assertion still read green on zero dials.
        number_id = (
            await session.execute(
                text(
                    "SELECT id FROM phone_numbers WHERE agent_id = :aid "
                    "AND dlt_status = 'registered' ORDER BY created_at, id LIMIT 1"
                ),
                {"aid": agent_id},
            )
        ).scalar()
        if number_id is None:
            number_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                    "dlt_status, created_at, updated_at) "
                    "VALUES (:id, :tid, :aid, :e, '140', 'registered', now(), now())"
                ),
                {
                    "id": number_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
                },
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
        # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9).
        # A promotional campaign is launch-ready only once an access provider has
        # preference-scrubbed its list, so this fixture supplies the fact through the
        # production writer — `tests/national_dnd_test.py` proves the refusal is real.
        await record_test_scrub(session, campaign_id)
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    return campaign_id


async def _census() -> tuple[int, set[uuid.UUID], set[uuid.UUID]]:
    """(organizations, dispatchable tenants, tenants with a running campaign).

    The last one is the set a correct tick may open, and it comes from `dispatch_scan()`
    itself — the only cross-tenant view of `campaigns` that exists without widening RLS
    (hard rule 1), which is the whole reason the scan is a database function. Taken on
    both sides of the tick so the assertions can be set DIFFERENCES rather than
    inequalities: a difference survives a concurrent suite launching a campaign mid-tick,
    and it names the offending tenant when it does fail.
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
    work = await campaign_dispatch._tenants_with_work()
    return (
        int(orgs or 0),
        {uuid.UUID(str(row)) for row in routed},
        {w.tenant_id for w in work if w.has_running_campaign},
    )


async def test_a_tick_opens_no_session_for_a_tenant_with_nothing_to_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this file exists for.

    Before D-57: one transaction per tenant with a published agent, whether or not it
    had anything to do — 12,070 sessions and 22.9s on a job scheduled every 30 seconds.
    Before that: one per organization, 15,941 sessions and 44.9s.

    The comparison needs a database where "one per dispatchable tenant" and "one per
    tenant with work" are different numbers, so this test MAKES one: `POPULATION`
    organizations, `DISPATCHABLE` of them published and all of them idle. Whatever else
    the database holds, it now holds at least `DISPATCHABLE` tenants with a live
    published agent that a correct tick provably never opens. Every claim below names
    the rows it is about rather than comparing two totals, which is what lets it mean the
    same thing on an empty database and on a 33,000-org one.
    """
    tenant_id, agent_id = await _tenant()
    await _running_campaign(tenant_id, agent_id)

    async with _population() as population:
        _, routed_before, busy_before = await _census()
        with _measure(monkeypatch) as visits:
            await dispatch_campaign_tick({})
        orgs_after, routed_after, busy_after = await _census()

        opened = visits.opened()
        assert tenant_id in opened, "the tick must still visit a tenant that is dialling"

        # THE PROPERTY, stated on rows this test owns, with no tolerance at all.
        # These 25 tenants have a published, live, outbound agent and no campaign. Under
        # the previous shape each cost exactly one session; a correct tick costs none.
        trespass = [t for t in population.dispatchable if t in opened]
        assert not trespass, (
            f"the tick opened {len(trespass)} of {DISPATCHABLE} tenants that have a published "
            "agent and nothing to dial — it is still O(dispatchable tenants)"
        )
        # ...and the older shape, from the other side: an organization with no engine
        # route at all. This is the 13,000-organization bill.
        strangers = [t for t in population.idle if t in opened]
        assert not strangers, (
            f"the tick opened {len(strangers)} of {IDLE} organizations that can never dial — "
            "it is still O(organizations)"
        )

        # The AMBIENT population — every other suite's tenants — bounded as set
        # differences rather than count comparisons. A tenant whose campaign starts or
        # stops mid-tick moves which set it belongs to, not how much slack is needed.
        #
        # Never SKIP a tenant that is dialling: a tenant the scan reported as running on
        # BOTH sides of the tick was running during it, and rule 3's budget is spent per
        # tenant, so one that is never opened simply does not dial. Exact, no allowance.
        missed = (busy_before & busy_after) - set(visits.tenants)
        assert not missed, (
            f"the tick skipped {len(missed)} tenants with a running campaign, e.g. "
            f"{sorted(str(t) for t in missed)[:3]}"
        )
        # ...and never open a tenant that has no running campaign on either side of the
        # tick. THIS is the cost claim against the ambient database: `orgs_after`
        # organizations, `len(routed_after)` of them dispatchable, and a correct tick
        # touches only the handful that are actually dialling. No allowance is needed —
        # the union of the two censuses already covers a campaign launched or completed
        # while the tick ran.
        idle_opened = set(visits.tenants) - (busy_before | busy_after)
        assert not idle_opened, (
            f"the tick opened {len(idle_opened)} tenants with no running campaign, out of "
            f"{orgs_after} organizations and {len(routed_after)} dispatchable tenants"
        )
        assert routed_before & routed_after, "sanity: the census must see a populated database"

        # The query bill, with NO per-tenant term — that absence IS the property. One
        # scan and one platform-state read for the whole database, then the
        # budget/reap/gate/claim/dial statements of the campaigns actually dispatched.
        # A tick that reverted to a session per dispatchable tenant would need ~12,000 of
        # each and no coefficient here could absorb it.
        assert visits.queries <= QUERY_BASE + QUERIES_PER_SESSION * visits.sessions, (
            f"{visits.queries} queries for {visits.sessions} sessions "
            f"({visits.distinct} distinct tenants, {len(routed_after)} dispatchable)"
        )


async def test_a_tenant_with_two_published_agents_is_scanned_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`dispatch_scan()` walks `SELECT DISTINCT tenant_id FROM engine_agent_routes`.

    Every other test here provisions one agent per tenant, on which a missing DISTINCT
    is invisible: the same rows come back either way. `_population()` therefore gives its
    first published tenant TWO route rows, and this test gives a DIALLING tenant two —
    without the de-duplication the scan reports it twice, the tick opens it twice, and it
    is granted its per-tenant concurrency budget twice out of a pool that is shared with
    every other client's inbound receptionist (FLOWS §5 rule 3).
    """
    tenant_id, agent_id = await _tenant()
    second_ref = f"fakeagent_dscale_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        second_agent = uuid7()
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, 'Second', "
                "'outbound', 'Idi AI assistant.', 'Idi AI assistant.', 'This call is being "
                "recorded.', 'I keep a short note of what you ask about.', 'live', 'fake', "
                ":ref, now(), now())"
            ),
            {"id": second_agent, "tid": tenant_id, "ref": second_ref},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": second_ref, "t": tenant_id, "a": second_agent},
        )
    await _running_campaign(tenant_id, agent_id, concurrency=2, contacts=5)

    scanned = [w for w in await campaign_dispatch._tenants_with_work() if w.tenant_id == tenant_id]
    assert len(scanned) == 1, f"two published agents produced {len(scanned)} scan rows"

    with _measure(monkeypatch) as visits:
        await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        dialing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE status = 'dialing' "
                    "AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert dialing == 2, "a second published agent must not double the tenant's budget"
    # Exactly five, named: the budget read, the reap/gate/claim transaction, one per
    # dial, and the completion check. A duplicated scan row would run the whole sequence
    # twice; a sixth session means the dispatch path grew one and this number is the
    # place to say so on purpose.
    assert visits.opened()[tenant_id] == 1 + 1 + dialing + 1, (
        "nor double the sessions the tick spends on it"
    )


async def test_a_tenant_holding_a_line_is_counted_without_being_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rules 1+2 need a PLATFORM-WIDE count of live outbound calls, and that count is
    exactly why the old tick had to open every tenant: `calls` is FORCE-RLS'd, so the
    number only existed inside a tenant session.

    `dispatch_scan()` returns it per tenant without the client opening anything, so this
    test pins the two halves together — the tenant holding the lines is NOT opened, and
    its lines are still subtracted from the shared pool.

    The pool is SIZED against the scan taken a moment earlier: `ambient + HELD`, so the
    tick has exactly `HELD` lines of slack if it forgets this tenant and none if it does
    not. That calibration is what makes the assertion mean something on a shared database
    — an absolute pool would be saturated by other suites' calls and would pass whether
    or not the held lines were counted. (It does assume no other suite starts `HELD` new
    outbound calls in the millisecond between the scan and the tick; every test in this
    file shares that assumption with `_roomy_platform_pool`.)
    """
    held = 7
    idle_holder, holder_agent = await _tenant()
    dialler, dialler_agent = await _tenant()
    campaign_id = await _running_campaign(dialler, dialler_agent, concurrency=2, contacts=3)

    async with tenant_session(idle_holder) as session:
        for _ in range(held):
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ec, 'outbound', "
                    "'in_progress', now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": idle_holder,
                    "aid": holder_agent,
                    "ec": f"held-{uuid.uuid4()}",
                },
            )

    scan = {w.tenant_id: w for w in await campaign_dispatch._tenants_with_work()}
    assert scan[idle_holder].active_outbound == held
    assert not scan[idle_holder].has_running_campaign
    ambient = sum(w.active_outbound for t, w in scan.items() if t != idle_holder)

    monkeypatch.setattr(campaign_dispatch, "_outbound_pool", lambda: ambient + held)
    with _measure(monkeypatch) as visits:
        result = await dispatch_campaign_tick({})

    assert idle_holder not in visits.tenants, "a tenant with no campaign costs no session"
    assert result == f"pool_saturated active={ambient + held}", result
    async with tenant_session(dialler) as session:
        dialing = (
            await session.execute(
                text(
                    "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :c "
                    "AND status = 'dialing'"
                ),
                {"c": campaign_id},
            )
        ).scalar()
    assert dialing == 0, "the lines held by a tenant the tick never opened still cost the pool"

    # Give the platform its lines back HERE rather than in the module fixture. Everything
    # else this file leaks is cleaned at the end; these seven would narrow the pool for
    # every LATER TEST IN THIS FILE, which is the assertion they would break first.
    async with tenant_session(idle_holder) as session:
        await session.execute(
            text(
                "UPDATE calls SET status = 'completed', updated_at = now() "
                f"WHERE status IN {campaign_dispatch.ACTIVE_STATUSES!r}"
            )
        )


async def test_an_organization_that_cannot_dial_is_never_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The narrowing has to be a rule, not an average.

    A tenant with no published agent cannot hold an outbound call row and cannot launch
    a campaign (`agent_not_live` blocks it), so a session opened for it can only ever
    return zeros. That is the 13,000 organizations the oldest tick spent its interval on.

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
    needs to be: `engine_agent_routes` is a global table by design and `dispatch_scan()`
    is SECURITY INVOKER, so the resolution happens under `untenanted_session` with no
    widening at all (hard rule 1). `tests/dispatch_scan_rls_test.py` proves the second
    half against the catalog."""
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
    of the pool holding another client's receptionist open. The active-line count that
    the budget subtracts now arrives from `dispatch_scan()` rather than from the tenant's
    own session, so the property is re-asserted on the new read path.
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
