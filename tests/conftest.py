"""Shared pytest config.

Windows dev machines: psycopg async cannot run on the default ProactorEventLoop —
pytest-asyncio picks up this policy fixture and uses the selector loop instead.
Linux (CI, VPS) is unaffected.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.db.session import untenanted_session
from sqlalchemy import text


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    policy = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        policy = asyncio.WindowsSelectorEventLoopPolicy()
    return policy


@pytest.fixture(scope="session", autouse=True)
async def platform_tm_registration_is_live() -> None:
    """This test database's platform is a REGISTERED telemarketer (SEC-COMP §3).

    Migration d7f2a3c9b410 gave `platform_state` Calevate's own DLT telemarketer
    registration and seeded it `not_registered` — the honest value, since R-01 is
    exactly that our TM registration is still being obtained — and
    `campaigns.service.launch_blockers` now refuses EVERY tenant's campaign while it is
    not live. That is the point of the blocker: a campaign dialled without it is not a
    client with a paperwork gap, it is Calevate dialling India's network as an
    unregistered telemarketer.

    It is therefore a fact every launch test needs and none of them can invent per
    tenant, because there is exactly one row for the whole platform. Supplied HERE,
    once, rather than in each suite's fixtures: the fixtures that already supply the
    per-tenant PE registration cannot supply a global one without every file writing
    the same row, and a suite that forgot would fail depending on which other suite had
    run first on the shared database.

    This SUPPLIES the fact; it does not soften the gate. Production still has to record
    the registration through the audited ops surface
    (`POST /v1/ops/platform/tm-registration`), and `tests/tm_registration_test.py`
    proves the refusal is real by taking the fact away again — inside a transaction it
    rolls back, so no other pytest process ever sees a platform that cannot dial.

    Concurrency: idempotent, one UPDATE, and only ever in the PERMISSIVE direction. The
    predicate makes it a no-op on every run after the first, so concurrent suites do
    not queue on the row, and nothing here can halt another run's dialling.
    """
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE platform_state SET tm_registration_status = 'active', "
                "tm_id = COALESCE(tm_id, 'TM-TEST-0000000001'), "
                "tm_registered_at = COALESCE(tm_registered_at, :reg), "
                "tm_verified_at = now() "
                "WHERE id = 1 AND tm_registration_status <> 'active'"
            ),
            {"reg": datetime.now(UTC) - timedelta(days=365)},
        )
