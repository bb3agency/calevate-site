"""FastAPI dependencies that hand a route its database session.

There is exactly ONE way for a tenant-facing route to reach the database: a session
whose transaction has `app.tenant_id` set, so RLS is doing the isolation rather than
a WHERE clause someone might forget (hard rule 1). Services receive the session by
`Depends()` — no globals, no singletons, one `AsyncSession` per request
(BACKEND-PATTERNS §1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import tenant_of
from apps.api.db.session import tenant_session, untenanted_session


async def db(tenant_id: UUID = Depends(tenant_of)) -> AsyncIterator[AsyncSession]:
    """Tenant-scoped session. Commits on clean exit, rolls back on any exception."""
    async with tenant_session(tenant_id) as session:
        yield session


async def global_db() -> AsyncIterator[AsyncSession]:
    """No GUC: tenant tables yield ZERO rows. Only for genuinely global tables
    (users, admin_users, reserved_slugs, outbox/inbox/idempotency, platform_state).
    Never use this to 'see all tenants' — that is what the audited admin surface is
    for, and it goes through its own explicit queries."""
    async with untenanted_session() as session:
        yield session


__all__ = ["db", "global_db"]
