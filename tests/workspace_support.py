"""Give a test tenant its own ThinnestAI customer workspace (D-693), as provisioning would.

Every new vendor agent of a tenant is created in that tenant's own workspace, and a tenant
with none is refused rather than falling back to the developer workspace, so a test that
publishes on the ThinnestAI engine first gives its tenant one.
"""

from __future__ import annotations

from uuid import UUID

from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.tenancy.engine_workspace import external_ref_for
from sqlalchemy import text


def workspace_of(tenant_id: UUID) -> str:
    """The test workspace id for a tenant: `org_…`, unique per tenant."""
    return f"org_test-{tenant_id}"


async def give_own_workspace(
    tenant_id: UUID,
    *,
    workspace: str | None = None,
    business_status: str | None = None,
    can_rent: bool = False,
    status: str = "active",
) -> str:
    """Record `tenant_id`'s workspace as provisioned. Returns its id."""
    ws = workspace or workspace_of(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_engine_workspaces (id, tenant_id, engine, external_ref, "
                "workspace_id, status, provisioned_at, business_status, business_can_rent, "
                "created_at, updated_at) VALUES (:id, :tid, 'thinnest', :ref, :ws, :status, "
                "now(), :bs, :rent, now(), now()) ON CONFLICT (tenant_id) DO UPDATE SET "
                "workspace_id = EXCLUDED.workspace_id, status = EXCLUDED.status, "
                "business_status = EXCLUDED.business_status, "
                "business_can_rent = EXCLUDED.business_can_rent, updated_at = now()"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "ref": external_ref_for(tenant_id),
                "ws": ws if status == "active" else None,
                "status": status,
                "bs": business_status,
                "rent": can_rent,
            },
        )
    return ws
