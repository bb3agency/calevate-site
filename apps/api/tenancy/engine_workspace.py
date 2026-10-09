"""Which ThinnestAI workspace holds a client's data: the one resolver (D-691, D-693).

Every client has its own ThinnestAI customer workspace (`POST /customers`; every request
about it carries `Thinnest-Workspace: <org_ id>`, `thinnest-findings/mirror/snapshots/
2026-10-08/pages/api-reference/customers.md:18-91`). Its agents, calls, numbers, contacts and
do-not-call list live there, and its numbers are rented in its own business name.

`resolve_workspace` is THE resolver: the one read of `tenant_engine_workspaces`. It answers
the tenant's `org_` id while the workspace is `active`, and None — "not provisioned" — in
every other state. NOTHING falls back to our developer workspace for a client resource:
a caller that gets None refuses (`engine/thinnest_workspace.workspace_not_provisioned`) or
records that nothing was sent. `workspace_for_tenant` is the same read in a session of its
own, for callers that hold none.

Provisioning goes through the outbox (`queue_workspace_provisioning`, job
`provision_engine_workspace` in `apps/workers/engine_workspaces.py`), in the transaction
that made the tenant, so a tenant cannot exist without its provisioning being owed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from calevate_shared.engine_scope import WORKSPACE_PREFIX, is_customer_workspace
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import joined_tenant_session, untenanted_session
from apps.api.engine.thinnest_workspace import is_developer_workspace
from apps.api.reliability.service import enqueue_outbox

#: Engines that run each client in a customer workspace of its own.
WORKSPACE_ENGINES: Final = frozenset({"thinnest"})

PROVISION_JOB: Final = "provision_engine_workspace"
OFFBOARD_JOB: Final = "offboard_engine_workspace"

WorkspaceStatus = Literal[
    "not_provisioned", "pending", "active", "plan_limit", "failed", "offboarding", "deleted"
]

#: States provisioning is still owed in; the retry sweep picks these up.
OWED_STATES: Final = frozenset({"pending", "failed", "plan_limit"})


def engine_has_workspaces(engine: str | None = None) -> bool:
    """Does `engine` (this deployment's by default) run each client in its own workspace?"""
    return (engine or get_settings().engine) in WORKSPACE_ENGINES


def external_ref_for(tenant_id: UUID) -> str:
    """Our reference for a tenant's workspace, sent as the customer's `externalId` (1-128 of
    letters, digits, `.`, `_`, `:`, `-`; customers.md:55). Derived, so provisioning can find
    a workspace it already made from the tenant id alone."""
    return f"calevate-{tenant_id}"


def is_own_workspace(workspace: str | None) -> bool:
    """True only for a client's customer workspace id. Our developer workspace's id is
    also `org_…` (`api-reference/workspace/get-workspace.md:347`), so the prefix is not
    enough: its id, once known (`engine/thinnest_workspace.is_developer_workspace`), is
    refused too. Provisioning never records it as a client's."""
    return is_customer_workspace(workspace) and not is_developer_workspace(workspace)


@dataclass(frozen=True, slots=True)
class WorkspaceState:
    status: WorkspaceStatus
    workspace_id: str | None = None
    last_error_code: str | None = None
    attempts: int = 0
    provisioned_at: datetime | None = None
    business_status: str | None = None
    business_can_rent: bool = False
    business_review_note: str | None = None
    business_submitted_at: datetime | None = None
    business_checked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status == "active" and is_own_workspace(self.workspace_id)


NOT_PROVISIONED: Final = WorkspaceState(status="not_provisioned")

_STATE_SQL: Final = (
    "SELECT status, workspace_id, last_error_code, attempts, provisioned_at, business_status, "
    "business_can_rent, business_review_note, business_submitted_at, business_checked_at "
    "FROM tenant_engine_workspaces WHERE tenant_id = :tid"
)


async def read_workspace_state(session: AsyncSession, tenant_id: UUID) -> WorkspaceState:
    """The tenant's workspace and business-details state, in the caller's tenant session."""
    row = (await session.execute(text(_STATE_SQL), {"tid": tenant_id})).first()
    if row is None:
        return NOT_PROVISIONED
    return WorkspaceState(
        status=row[0],
        workspace_id=row[1],
        last_error_code=row[2],
        attempts=int(row[3] or 0),
        provisioned_at=row[4],
        business_status=row[5],
        business_can_rent=bool(row[6]),
        business_review_note=row[7],
        business_submitted_at=row[8],
        business_checked_at=row[9],
    )


async def resolve_workspace(session: AsyncSession, tenant_id: UUID) -> str | None:
    """THE RESOLVER: the tenant's own workspace id while it is active, else None."""
    state = await read_workspace_state(session, tenant_id)
    return state.workspace_id if state.active else None


async def workspace_for_tenant(tenant_id: UUID) -> str | None:
    """`resolve_workspace` for a caller holding no session (or joining this tenant's)."""
    async with joined_tenant_session(tenant_id) as session:
        return await resolve_workspace(session, tenant_id)


async def own_workspace(tenant_id: UUID) -> str | None:
    """The tenant's own workspace when it is provisioned, else None — the question both
    person-level writes ask before anything leaves this system."""
    workspace = await workspace_for_tenant(tenant_id)
    return workspace if is_own_workspace(workspace) else None


async def queue_workspace_provisioning(
    session: AsyncSession, *, tenant_id: UUID, reopen: bool = False
) -> bool:
    """Owe this tenant a workspace, in the caller's transaction: the row in `pending` and the
    provisioning job through the outbox. False, and nothing written, on an engine without
    workspaces or for a tenant whose workspace is already active. Idempotent.

    A workspace being or already deleted (a closed account) is provisioned again only with
    `reopen`, which the account restore passes: the job then finds the deleted customer by
    our reference and restores it while the vendor still holds it."""
    if not engine_has_workspaces():
        return False
    state = await read_workspace_state(session, tenant_id)
    if state.active:
        return False
    if state.status in ("offboarding", "deleted"):
        if not reopen:
            return False
        await session.execute(
            text(
                "UPDATE tenant_engine_workspaces SET status = 'pending', last_error_code = NULL, "
                "updated_at = now() WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    await session.execute(
        text(
            "INSERT INTO tenant_engine_workspaces (id, tenant_id, engine, external_ref, status, "
            "created_at, updated_at) VALUES (:id, :tid, :engine, :ref, "
            "'pending', now(), now()) ON CONFLICT (tenant_id) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "engine": get_settings().engine,
            "ref": external_ref_for(tenant_id),
        },
    )
    await enqueue_outbox(session, job=PROVISION_JOB, payload={"tenant_id": str(tenant_id)})
    return True


async def queue_workspace_offboarding(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Owe this tenant's workspace its offboarding, in the caller's (closing) transaction:
    numbers released, agents deleted, the customer deleted. From this instant the resolver
    answers "not provisioned", so nothing new is sent there. False when there is nothing to
    offboard."""
    if not engine_has_workspaces():
        return False
    state = await read_workspace_state(session, tenant_id)
    if state.status in ("not_provisioned", "deleted"):
        return False
    await session.execute(
        text(
            "UPDATE tenant_engine_workspaces SET status = 'offboarding', updated_at = now() "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    await enqueue_outbox(session, job=OFFBOARD_JOB, payload={"tenant_id": str(tenant_id)})
    return True


@dataclass(frozen=True, slots=True)
class WorkspaceRow:
    tenant_id: UUID
    status: str
    workspace_id: str | None


async def workspace_directory(
    *, statuses: frozenset[str] | None = None, limit: int = 1000
) -> list[WorkspaceRow]:
    """Every tenant's workspace row, ordered by tenant, from the untenanted directory read
    the table's `directory_read` policy allows. Bounded by `limit`."""
    wanted = sorted(statuses) if statuses is not None else None
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id, status, workspace_id FROM tenant_engine_workspaces "
                    "WHERE CAST(:statuses AS text[]) IS NULL OR status = ANY(:statuses) "
                    "ORDER BY tenant_id LIMIT :limit"
                ),
                {"statuses": wanted, "limit": limit},
            )
        ).all()
    return [
        WorkspaceRow(tenant_id=UUID(str(r[0])), status=str(r[1]), workspace_id=r[2]) for r in rows
    ]


async def active_workspaces(*, limit: int = 1000) -> list[WorkspaceRow]:
    """The tenants whose own workspace is active, ordered by tenant."""
    return [
        row
        for row in await workspace_directory(statuses=frozenset({"active"}), limit=limit)
        if is_own_workspace(row.workspace_id)
    ]


__all__ = [
    "NOT_PROVISIONED",
    "OFFBOARD_JOB",
    "OWED_STATES",
    "PROVISION_JOB",
    "WORKSPACE_ENGINES",
    "WORKSPACE_PREFIX",
    "WorkspaceRow",
    "WorkspaceState",
    "WorkspaceStatus",
    "active_workspaces",
    "engine_has_workspaces",
    "external_ref_for",
    "is_own_workspace",
    "own_workspace",
    "queue_workspace_offboarding",
    "queue_workspace_provisioning",
    "read_workspace_state",
    "resolve_workspace",
    "workspace_directory",
    "workspace_for_tenant",
]
