"""`dispatch_scan()` is a cross-tenant loop, and hard rule 1 says it may not be a bypass.

D-57 moved the dispatch tick's screening loop from Python into Postgres — the function
`dispatch_scan(active_statuses, active_horizon)` created by migration `a8d4f21c9b06`. It
walks every tenant with a published agent and, for each, reads `calls` and `campaigns`.
That is precisely the shape hard rule 1 exists to police, so the tenancy properties get a
file of their own rather than a line inside the performance file:

1. the function is SECURITY INVOKER — it runs as the CALLER, with the caller's policies;
2. the per-tenant scoping is REAL, not a plan cached from the first iteration;
3. it leaves the caller's `app.tenant_id` exactly as it found it;
4. it sees only what `engine_agent_routes` routes, which is the documented superset.

(2) is the one worth being suspicious about, and it is why this file asserts on DATA
rather than on the function's text: `current_setting('app.tenant_id')` inside the RLS
policy is STABLE, meaning constant WITHIN a statement — each `PERFORM set_config` and
each read is a separate statement in plpgsql, so the value is re-read per iteration. If
that reasoning were wrong, every tenant in the loop would report the FIRST tenant's
numbers, and two tenants with deliberately different live-call counts is what makes that
visible.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import campaign_dispatch
from sqlalchemy import text

# Every tenant this module creates, so the fixture below can quiet them again.
_TENANTS: list[uuid.UUID] = []

SCAN_SQL = text(
    "SELECT scanned_tenant_id, active_outbound, has_running_campaign "
    "FROM dispatch_scan(:statuses, :horizon)"
)
SCAN_ARGS = {
    "statuses": list(campaign_dispatch.ACTIVE_STATUSES),
    "horizon": campaign_dispatch.ACTIVE_CALL_HORIZON,
}


@pytest.fixture(scope="module", autouse=True)
async def _settle_what_this_module_started() -> AsyncIterator[None]:
    """Leave the shared platform as quiet as we found it.

    This file's whole method is creating tenants that LOOK busy — live outbound calls
    and `running` campaigns — so the scan has something to report. Both are
    platform-wide facts on a Postgres shared with every other suite and every other
    pytest process: a `running` campaign is dialled by every later tick, and an
    `in_progress` call row spends a line out of the pool (FLOWS §5 rule 1) for a full
    `ACTIVE_CALL_HORIZON`. Neither would fail a test here; both would fail someone
    else's, minutes later, for no visible reason.

    Scoped to `_TENANTS` — the ones this module created — and never a `LIKE` sweep,
    which is how a cleanup ends up cancelling a campaign another process launched one
    second ago. The pattern is `tests/campaign_dispatch_audit_test.py`'s.
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


async def _published_tenant(*, live_calls: int = 0, running_campaign: bool = False) -> uuid.UUID:
    """A tenant with a route, and exactly the situation the caller asked for.

    Rows rather than the onboarding wizard: this file is about what the database
    function can see, and a bare organization + agent + route is the whole input.
    """
    tenant_id, agent_id = uuid7(), uuid7()
    _TENANTS.append(tenant_id)
    ref = f"scanrls-{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Scan Motors', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": ref},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, 'Rec', "
                "'outbound', 'Idi AI assistant.', 'live', 'fake', :ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": ref},
        )
        for _ in range(live_calls):
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ec, 'outbound', "
                    "'in_progress', now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ec": f"{ref}-{uuid.uuid4().hex[:8]}",
                },
            )
        if running_campaign:
            await session.execute(
                text(
                    "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                    "status, concurrency, created_at, updated_at) VALUES (:id, :tid, :aid, "
                    "'Scan', 'promotional', 'running', 1, now(), now())"
                ),
                {"id": uuid7(), "tid": tenant_id, "aid": agent_id},
            )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, true, now(), "
                "now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id


async def test_the_scan_function_is_security_invoker() -> None:
    """The catalog, not the source file: what runs is what the database installed.

    `SECURITY DEFINER` owned by a role that can bypass RLS is the obvious way to make
    this function faster, it is what most "cross-tenant aggregate" advice reaches for,
    and it would put a role that cannot see row policies on the dial path — hard rule 1's
    "never use the admin DB role in app code paths" with an extra keyword in front of it.
    This assertion is what makes that edit fail a build instead of a review.
    """
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT p.prosecdef, p.provolatile FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE p.proname = 'dispatch_scan' AND n.nspname = 'public'"
                )
            )
        ).first()
    assert row is not None, "migration a8d4f21c9b06 did not install dispatch_scan()"
    assert row[0] is False, "dispatch_scan() must be SECURITY INVOKER (hard rule 1)"
    # VOLATILE, because it calls set_config: a STABLE or IMMUTABLE marking would tell the
    # planner it may be folded or evaluated once, which for a function whose whole job is
    # a side effect per iteration is a wrong answer rather than a slow one.
    assert row[1] == "v", "dispatch_scan() must stay VOLATILE — it sets a GUC per tenant"


async def test_each_tenant_in_the_loop_is_scoped_to_itself() -> None:
    """Two tenants, deliberately different numbers, both in the same walk.

    A loop whose RLS predicate were evaluated once — a cached plan, a folded
    `current_setting`, a GUC set outside the loop — would report the same count for both.
    Different counts is the evidence that `app.tenant_id` is re-read per statement, and it
    is evidence about the running database rather than about the SQL we think we wrote.
    """
    quiet = await _published_tenant(live_calls=1)
    busy = await _published_tenant(live_calls=4, running_campaign=True)

    rows = {w.tenant_id: w for w in await campaign_dispatch._tenants_with_work()}

    assert rows[quiet].active_outbound == 1
    assert rows[quiet].has_running_campaign is False
    assert rows[busy].active_outbound == 4
    assert rows[busy].has_running_campaign is True


async def test_a_tenant_with_nothing_live_is_not_returned_at_all() -> None:
    """The narrowing, stated as a rule about one row rather than as a total.

    A published tenant with no live call and no running campaign is the overwhelming
    majority of the table, and returning it is what made the tick cost a session per
    tenant. Its absence is safe precisely because `active_outbound` would have been zero:
    the platform-wide sum the caller builds from these rows stays exact.
    """
    silent = await _published_tenant()
    scanned = {w.tenant_id for w in await campaign_dispatch._tenants_with_work()}
    assert silent not in scanned


async def test_a_stale_call_row_does_not_hold_a_line_forever() -> None:
    """`ACTIVE_CALL_HORIZON` is a hard rule of its own: a `queued` row stranded by a lost
    engine event must stop counting, or a handful of them permanently zero the platform
    pool and silently stop every campaign. The horizon is a PARAMETER of the scan now, so
    the constant has one definition; this proves the parameter is actually applied."""
    tenant_id = await _published_tenant(live_calls=1)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET updated_at = now() - interval '2 hours' WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    scanned = {w.tenant_id for w in await campaign_dispatch._tenants_with_work()}
    assert tenant_id not in scanned, "a call row older than the horizon is not a live line"


async def test_the_scan_restores_the_callers_tenant_context() -> None:
    """The function sets `app.tenant_id` 12,000 times. It must give it back.

    The GUC is transaction-local either way, so an aborted transaction resets it — but a
    caller that keeps using its session after the scan would otherwise be reading the
    LAST tenant of the walk under its own name, which is the worst kind of tenancy bug:
    silent, and it returns rows rather than an error.
    """
    mine = await _published_tenant(live_calls=2)
    async with tenant_session(mine) as session:
        await session.execute(SCAN_SQL, SCAN_ARGS)
        still_mine = (
            await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
        ).scalar()
        visible = (
            await session.execute(text("SELECT count(*) FROM calls WHERE direction = 'outbound'"))
        ).scalar()
    assert uuid.UUID(str(still_mine)) == mine, "the scan left someone else's tenant id behind"
    assert visible == 2, "and the session still sees exactly its own rows"


async def test_a_tenant_with_no_engine_route_is_invisible_to_the_scan() -> None:
    """The documented boundary, asserted rather than described.

    `engine_agent_routes` is the enumeration, and it is a SUPERSET of what a tick needs
    only because a campaign cannot launch without a published agent and an outbound call
    row cannot exist without one either. A tenant that has a `running` campaign row and
    NO route is therefore unreachable — which is correct, and is exactly the assumption a
    future change to `publish_agent` could break without any other test noticing.
    """
    tenant_id, agent_id = uuid7(), uuid7()
    _TENANTS.append(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Unrouted', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"scanrls-{uuid.uuid4().hex[:10]}"},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, status, "
                "engine, created_at, updated_at) VALUES (:id, :tid, 'Rec', 'outbound', "
                "'Idi AI assistant.', 'draft', 'fake', now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status, "
                "concurrency, created_at, updated_at) VALUES (:id, :tid, :aid, 'Ghost', "
                "'promotional', 'running', 1, now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "aid": agent_id},
        )
    scanned = {w.tenant_id for w in await campaign_dispatch._tenants_with_work()}
    assert tenant_id not in scanned
