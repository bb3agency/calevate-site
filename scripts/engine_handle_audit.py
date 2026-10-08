"""Find any stored engine handle that still carries a ThinnestAI workspace scope (D-688).

D-687 stored an agent, knowledge document or call that lived in a ThinnestAI customer
workspace as `<id>@<workspace>`. D-688 removed customer workspaces and every reader of that
form, so a handle still spelled that way names an object no code path can reach: the adapter
would send `ag_…@org_…` as a path segment and the vendor would answer 404. This reports how
many such handles each column holds; it changes nothing.

    uv run python -m scripts.engine_handle_audit

Exit 0 when none are found, 1 otherwise. Tenant-scoped tables are read tenant by tenant
under their own policy (the directory is the only admin-role read), the shape
`workers/number_rental` argues.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Final
from uuid import UUID

from apps.api.db.session import admin_session, tenant_session, untenanted_session
from sqlalchemy import text

#: The separator D-687 used (`<id>@<workspace>`). No vendor id ThinnestAI documents carries
#: one: agents are `ag_…`, calls `out_…`/`sch_…` or the call reference, knowledge `kn_…`.
SCOPE_SEPARATOR: Final = "@"

#: Route tables, readable untenanted by design (`db/registry.RLS_EXEMPT_TENANT_COLUMNS`).
_ROUTE_COLUMNS: Final = (
    ("engine_agent_routes", "engine_agent_ref"),
    ("engine_kb_routes", "engine_kb_ref"),
)
#: Tenant tables, read under each tenant's own policy.
_TENANT_COLUMNS: Final = (
    ("agents", "engine_agent_ref"),
    ("calls", "engine_call_id"),
)
_DIRECTORY: Final = "SELECT id FROM organizations ORDER BY id"


async def scoped_handle_counts(tenants: list[UUID] | None = None) -> dict[str, int]:
    """`table.column` -> how many stored handles carry the workspace separator. `tenants`
    narrows the tenant-scoped half; by default every organization is read."""
    pattern = f"%{SCOPE_SEPARATOR}%"
    counts: dict[str, int] = {}
    async with untenanted_session() as session:
        for table, column in _ROUTE_COLUMNS:
            counts[f"{table}.{column}"] = int(
                (
                    await session.execute(
                        text(f"SELECT count(*) FROM {table} WHERE {column} LIKE :p"),
                        {"p": pattern},
                    )
                ).scalar_one()
            )
    if tenants is None:
        async with admin_session() as directory:
            tenants = [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]
    for table, column in _TENANT_COLUMNS:
        counts[f"{table}.{column}"] = 0
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            for table, column in _TENANT_COLUMNS:
                counts[f"{table}.{column}"] += int(
                    (
                        await scoped.execute(
                            text(f"SELECT count(*) FROM {table} WHERE {column} LIKE :p"),
                            {"p": pattern},
                        )
                    ).scalar_one()
                )
    return counts


async def main() -> int:
    counts = await scoped_handle_counts()
    for name, count in counts.items():
        print(f"{'FOUND' if count else 'ok   '} {name}: {count}")
    return 1 if any(counts.values()) else 0


if __name__ == "__main__":
    # Windows defaults to ProactorEventLoop, which psycopg's async mode cannot use.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
