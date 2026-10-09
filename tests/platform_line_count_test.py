"""A dial's line count is platform-wide even inside a tenant session (D-697 follow-up).

`carrier_lines_in_use()` and `dispatch_scan()` enumerate tenants from
`engine_agent_routes`, whose policy shows every row only while `app.tenant_id` is unset.
`agents.service._platform_scalar` clears the setting for the count and restores it.
"""

from __future__ import annotations

import uuid

from apps.api.agents.service import _platform_scalar
from apps.api.db.session import tenant_session
from sqlalchemy import text


async def test_the_count_sees_every_tenant_and_puts_the_tenant_back() -> None:
    tenant_id = uuid.uuid4()
    statement = text("SELECT count(*) FROM engine_agent_routes")
    async with tenant_session(tenant_id) as session:
        scoped = int((await session.execute(statement)).scalar_one())
        platform = await _platform_scalar(session, statement, {})
        after = (
            await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
        ).scalar()
    assert scoped == 0, "a tenant with no agents sees none of its own"
    assert platform >= scoped
    assert after == str(tenant_id), "the caller's tenant is restored for its next write"
