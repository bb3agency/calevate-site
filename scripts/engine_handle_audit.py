"""Report the stored engine handles that do not live in their client's own workspace (D-693).

Each client has its own ThinnestAI customer workspace, and a handle issued there is held as
`<id>@<org_…>` (`calevate_shared.engine_scope`). For every column that stores one, per
tenant, this counts:

* `platform_account` — unscoped handles: objects in our developer workspace, made before
  D-693. Not a fault: an agent is recreated in its client's workspace on its next publish,
  and a number held there is the platform's own, recorded for testing.
* `foreign` — handles scoped to a workspace that is NOT the tenant's own active one. Every
  request about such an object would act in another workspace: a fault.

    uv run python -m scripts.engine_handle_audit

Exit 0 when nothing is `foreign`, 1 otherwise. Tenant-scoped tables are read tenant by
tenant under their own policy (the directory is the only admin-role read), the shape
`workers/number_rental` argues. It changes nothing.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Final
from uuid import UUID

from apps.api.db.session import admin_session, tenant_session
from apps.api.tenancy.engine_workspace import resolve_workspace
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text

#: Tenant tables and the column each holds a workspace-scoped handle in, read under each
#: tenant's own policy. `engine_agent_routes` carries `tenant_id` and its writes are policed,
#: so it is read the same way.
_COLUMNS: Final = (
    ("engine_agent_routes", "engine_agent_ref", "active"),
    ("agents", "engine_agent_ref", "deleted_at IS NULL"),
    ("calls", "engine_call_id", "true"),
    ("phone_numbers", "engine_number_ref", "released_at IS NULL"),
)
_DIRECTORY: Final = "SELECT id FROM organizations ORDER BY id"


async def handle_report(tenants: list[UUID] | None = None) -> dict[str, dict[str, int]]:
    """`table.column` -> `{"platform_account": n, "foreign": n}` over `tenants` (all by
    default)."""
    if tenants is None:
        async with admin_session() as directory:
            tenants = [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]
    report = {
        f"{table}.{column}": {"platform_account": 0, "foreign": 0}
        for table, column, _where in _COLUMNS
    }
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            own = await resolve_workspace(scoped, tenant_id)
            for table, column, where in _COLUMNS:
                handles = (
                    await scoped.execute(
                        text(
                            f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL "
                            f"AND tenant_id = :tid AND {where}"
                        ),
                        {"tid": tenant_id},
                    )
                ).scalars()
                for handle in handles:
                    scope = scope_of(str(handle))
                    key = f"{table}.{column}"
                    if scope is None:
                        report[key]["platform_account"] += 1
                    elif scope != own:
                        report[key]["foreign"] += 1
    return report


async def main() -> int:
    report = await handle_report()
    for name, counts in report.items():
        flag = "FOUND" if counts["foreign"] else "ok   "
        print(
            f"{flag} {name}: foreign={counts['foreign']} "
            f"platform_account={counts['platform_account']}"
        )
    return 1 if any(counts["foreign"] for counts in report.values()) else 0


if __name__ == "__main__":
    # Windows defaults to ProactorEventLoop, which psycopg's async mode cannot use.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
