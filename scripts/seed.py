"""Idempotent seed: the one global table, `reserved_slugs`.

Run: `uv run python -m scripts.seed` (also invoked by `make db-reset`).

The per-tenant defaults account creation applies are not here, because runtime code must
not import a script: the business types and their starting lead fields are
`calevate_shared/verticals.json` (`calevate_shared.verticals`), and the retention policies
are `apps/api/compliance/retention_defaults.py`. Both are tenant-scoped rows
(`extraction_schemas.tenant_id`, `retention_policies.tenant_id`) that cannot exist without
an organization.

Safe to re-run: inserts use ON CONFLICT DO NOTHING and the script never updates
or deletes existing rows.
"""

from __future__ import annotations

import asyncio
import sys

from apps.api.compliance.retention_defaults import DEFAULT_RETENTION_POLICIES
from apps.api.db.session import untenanted_session
from calevate_shared import verticals
from sqlalchemy import text

# --- Global: reserved slugs -------------------------------------------------
# Slugs a tenant may never claim: our own subdomains/routes, plus the usual
# impersonation bait. DATA-MODEL §2 (`organizations.slug` is immutable once set).
RESERVED_SLUGS: tuple[str, ...] = (
    # our surfaces
    "admin",
    "api",
    "app",
    "www",
    "hooks",
    "accounts",
    "auth",
    "login",
    "logout",
    "signup",
    "register",
    "onboarding",
    "dashboard",
    "settings",
    "billing",
    "support",
    "help",
    "docs",
    "status",
    "static",
    "assets",
    "cdn",
    "media",
    # brand / trust-sensitive
    "calevate",
    "bb3",
    "builtbythree",
    "security",
    "abuse",
    "legal",
    "privacy",
    "terms",
    "dpa",
    "compliance",
    "trai",
    "dlt",
    # generic traps
    "test",
    "demo",
    "example",
    "root",
    "system",
    "internal",
    "null",
    "undefined",
)


async def seed_reserved_slugs() -> int:
    """Insert reserved slugs. Returns the number newly inserted."""
    async with untenanted_session() as session:
        before = (await session.execute(text("SELECT count(*) FROM reserved_slugs"))).scalar_one()
        await session.execute(
            # The ::text[] cast is required — without it Postgres cannot resolve which
            # unnest() overload to use and errors with "could not choose a best candidate".
            text(
                "INSERT INTO reserved_slugs (slug) "
                "SELECT unnest(CAST(:slugs AS text[])) ON CONFLICT DO NOTHING"
            ),
            {"slugs": list(RESERVED_SLUGS)},
        )
        after = (await session.execute(text("SELECT count(*) FROM reserved_slugs"))).scalar_one()
        await session.commit()
        return int(after) - int(before)


async def main() -> None:
    inserted = await seed_reserved_slugs()
    print(f"seed: reserved_slugs +{inserted} (total defined: {len(RESERVED_SLUGS)})")
    print(
        f"seed: {len(verticals.all_keys())} business types and "
        f"{len(DEFAULT_RETENTION_POLICIES)} retention defaults are tenant-scoped — "
        "applied by the onboarding flow, not inserted globally."
    )


if __name__ == "__main__":
    # Windows defaults to ProactorEventLoop, which psycopg's async mode cannot use.
    # tests/conftest.py selects the same loop through pytest_asyncio_loop_factories —
    # any standalone async entrypoint needs it too.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
