"""The operator's view of each client's own voice-platform workspace (D-693).

Per client (`/tenants/{tenant_id}`): the workspace and where its provisioning stands, its
business-details application, the purchase gates, and the numbers it holds — its own and any
held in the platform account for testing. Actions: provision again, send the business details
(again), refresh their status, offboard again, and buy or release a number in the client's
name through the same purchase path the client uses (`campaigns/engine_number_purchase.py`).

Across clients (`/summary`, the ops dashboard): workspaces provisioned against tenants, the
ones failing, and the plan's headroom — 3 customers on pay-as-you-go, 100 on Pro, 1,000 on
Scale, and a deleted one counts until it is erased (`thinnest-findings/mirror/snapshots/
2026-10-08/pages/api-reference/customers.md:191-200`).

Admin realm: vendor names may appear here. Tenant reads are recorded
(`record_admin_tenant_read`); every action is audited, a purchase BEFORE the vendor is
called and its outcome under a savepoint (BACKEND-PATTERNS §4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal
from uuid import UUID

from calevate_shared.engine_scope import scope_of
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service
from apps.api.billing.number_rental import RentalOutcome
from apps.api.campaigns import engine_numbers
from apps.api.campaigns.engine_business_details import (
    refresh_business_details,
    submit_business_details,
)
from apps.api.campaigns.engine_number_purchase import (
    PurchaseStep,
    forget_engine_number,
    purchase_engine_number,
    purchase_readiness,
    release_engine_number,
)
from apps.api.campaigns.number_catalog import NumberDirection
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine.thinnest_customers import PLAN_CUSTOMER_CAPS
from apps.api.engine.thinnest_numbers import BusinessDetails
from apps.api.tenancy.engine_workspace import (
    engine_has_workspaces,
    queue_workspace_offboarding,
    queue_workspace_provisioning,
    read_workspace_state,
    workspace_directory,
)

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin/engine-workspaces", tags=["admin"])

AdminSession = Annotated[AsyncSession, Depends(admin_db)]
WorkspaceOperator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
OpsViewer = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]

#: The vendor erases a deleted customer 30 days after the delete, and it counts towards the
#: plan's cap until then (customers.md:148-161, :200).
ERASE_AFTER: Final = timedelta(days=30)


class BusinessDetailsStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None
    can_rent: bool
    review_note: str | None
    submitted_at: datetime | None
    checked_at: datetime | None


class TenantNumbersCountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Live numbers rented in the client's own workspace.
    own_workspace: int
    #: Live numbers held in our developer workspace and recorded for this client for
    #: testing only.
    platform_held: int


class TenantWorkspaceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    #: `not_provisioned`, `pending`, `active`, `plan_limit`, `failed`, `offboarding`,
    #: `deleted`.
    status: str | None
    workspace_id: str | None
    last_error_code: str | None
    attempts: int
    provisioned_at: datetime | None
    business_details: BusinessDetailsStateOut | None
    purchase_step: PurchaseStep | None
    purchase_blockers: list[str]
    client_inr_per_month: str | None
    numbers: TenantNumbersCountOut | None
    #: Live agents still published in the developer workspace: recreated in the client's
    #: workspace on their next publish.
    agents_in_platform_account: int


_NUMBER_REFS = (
    "SELECT engine_number_ref FROM phone_numbers WHERE provider = :p AND released_at IS NULL "
    "AND engine_number_ref IS NOT NULL"
)
_AGENT_REFS = (
    "SELECT engine_agent_ref FROM agents WHERE deleted_at IS NULL AND status <> 'archived' "
    "AND engine = :engine AND engine_agent_ref IS NOT NULL"
)


async def _tenant_out(session: AsyncSession, tenant_id: UUID) -> TenantWorkspaceOut:
    if not engine_has_workspaces():
        return TenantWorkspaceOut(
            available=False,
            status=None,
            workspace_id=None,
            last_error_code=None,
            attempts=0,
            provisioned_at=None,
            business_details=None,
            purchase_step=None,
            purchase_blockers=[],
            client_inr_per_month=None,
            numbers=None,
            agents_in_platform_account=0,
        )
    state = await read_workspace_state(session, tenant_id)
    readiness = await purchase_readiness(session, tenant_id=tenant_id)
    provider = engine_numbers.engine_number_provider()
    refs = (
        [str(r) for r in (await session.execute(text(_NUMBER_REFS), {"p": provider})).scalars()]
        if provider
        else []
    )
    agent_refs = [
        str(r)
        for r in (
            await session.execute(text(_AGENT_REFS), {"engine": get_settings().engine})
        ).scalars()
    ]
    return TenantWorkspaceOut(
        available=True,
        status=state.status,
        workspace_id=state.workspace_id,
        last_error_code=state.last_error_code,
        attempts=state.attempts,
        provisioned_at=state.provisioned_at,
        business_details=BusinessDetailsStateOut(
            status=state.business_status,
            can_rent=state.business_can_rent,
            review_note=state.business_review_note,
            submitted_at=state.business_submitted_at,
            checked_at=state.business_checked_at,
        ),
        purchase_step=readiness.step,
        purchase_blockers=readiness.blockers,
        client_inr_per_month=(
            str(readiness.client_inr_per_month)
            if readiness.client_inr_per_month is not None
            else None
        ),
        numbers=TenantNumbersCountOut(
            own_workspace=sum(
                1 for r in refs if state.workspace_id and scope_of(r) == state.workspace_id
            ),
            platform_held=sum(1 for r in refs if scope_of(r) is None),
        ),
        agents_in_platform_account=sum(1 for r in agent_refs if scope_of(r) is None),
    )


async def _require_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    if not await service.tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Client")


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantWorkspaceOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="This client's own voice workspace, business details, purchase gates, numbers",
)
async def tenant_workspace(
    tenant_id: UUID, session: AdminSession, request: Request, principal: WorkspaceOperator
) -> TenantWorkspaceOut:
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        out = await _tenant_out(scoped, tenant_id)
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return out


async def _audited(
    tenant_id: UUID, request: Request, principal: Principal, *, action: str, summary: dict[str, str]
) -> None:
    async with tenant_session(tenant_id) as scoped:
        await write_audit(
            scoped,
            action=action,
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary=summary,
        )


def _off() -> ProblemError:
    return ProblemError.business_rule(
        "engine_workspaces_not_used",
        "This deployment's voice platform does not give each client a workspace of its own.",
        remediation="Nothing to do here on this deployment.",
    )


@router.post(
    "/tenants/{tenant_id}/provision",
    response_model=TenantWorkspaceOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Provision this client's own voice workspace again (after a plan upgrade or a fix)",
)
async def provision_again(
    tenant_id: UUID, request: Request, principal: WorkspaceOperator
) -> TenantWorkspaceOut:
    if not engine_has_workspaces():
        raise _off()
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        queued = await queue_workspace_provisioning(scoped, tenant_id=tenant_id)
        await write_audit(
            scoped,
            action="engine_workspace.provision_requested",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"queued": str(queued)},
        )
        return await _tenant_out(scoped, tenant_id)


@router.post(
    "/tenants/{tenant_id}/offboard",
    response_model=TenantWorkspaceOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Run this closed client's workspace offboarding again",
    description=(
        "Releases the workspace's numbers (permanent, no refund of the month), deletes its "
        "agents and deletes the customer. Refused unless the account is closed."
    ),
)
async def offboard_again(
    tenant_id: UUID, request: Request, principal: WorkspaceOperator
) -> TenantWorkspaceOut:
    if not engine_has_workspaces():
        raise _off()
    async with tenant_session(tenant_id) as scoped:
        status = (
            await scoped.execute(
                text("SELECT status FROM organizations WHERE id = :tid"), {"tid": tenant_id}
            )
        ).scalar()
        if status is None:
            raise ProblemError.not_found("Client")
        if status != "churned":
            raise ProblemError.business_rule(
                "engine_workspace_account_open",
                "This client's account is open, so its voice workspace is not offboarded.",
                remediation="Close the account first.",
            )
        queued = await queue_workspace_offboarding(scoped, tenant_id=tenant_id)
        await write_audit(
            scoped,
            action="engine_workspace.offboard_requested",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"queued": str(queued)},
        )
        return await _tenant_out(scoped, tenant_id)


@router.post(
    "/tenants/{tenant_id}/business-details",
    response_model=BusinessDetailsStateOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Send this client's verified business details to its workspace (again)",
)
async def send_business_details(
    tenant_id: UUID, request: Request, principal: WorkspaceOperator
) -> BusinessDetailsStateOut:
    if not engine_has_workspaces():
        raise _off()

    async def audit_sent(scoped: AsyncSession, details: BusinessDetails) -> None:
        await write_audit(
            scoped,
            action="engine_workspace.business_details_sent",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"status": details.status},
        )

    try:
        details = await submit_business_details(tenant_id, audit=audit_sent)
    except Exception as exc:
        # An operator's attempt is attributable even when it did not happen; the row says
        # it failed and why, never that the details were sent.
        reason = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
        await _audited(
            tenant_id,
            request,
            principal,
            action="engine_workspace.business_details_send_failed",
            summary={"reason": reason},
        )
        raise
    return BusinessDetailsStateOut(
        status=details.status,
        can_rent=details.can_rent,
        review_note=details.review_note,
        submitted_at=details.submitted_at,
        checked_at=None,
    )


@router.post(
    "/tenants/{tenant_id}/business-details/refresh",
    response_model=BusinessDetailsStateOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Read this client's business-details status from its workspace now",
)
async def refresh_details(
    tenant_id: UUID, session: AdminSession, request: Request, principal: WorkspaceOperator
) -> BusinessDetailsStateOut:
    if not engine_has_workspaces():
        raise _off()
    details = await refresh_business_details(tenant_id)
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return BusinessDetailsStateOut(
        status=details.status,
        can_rent=details.can_rent,
        review_note=details.review_note,
        submitted_at=details.submitted_at,
        checked_at=None,
    )


class AdminCityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    available: int


@router.get(
    "/tenants/{tenant_id}/numbers/cities",
    response_model=list[AdminCityOut],
    openapi_extra=permission_meta("admin:tenants"),
    summary="Cities numbers can be searched in, in this client's workspace",
)
async def admin_cities(
    tenant_id: UUID, session: AdminSession, request: Request, principal: WorkspaceOperator
) -> list[AdminCityOut]:
    if not engine_has_workspaces():
        raise _off()
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        cities = await engine_numbers.available_cities(scoped, tenant_id)
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return [AdminCityOut(name=c.name, available=c.available) for c in cities]


class AdminAvailableNumberOut(BaseModel):
    """A number this client could buy: what the CLIENT pays (the attested rate) and what it
    costs US (the vendor's monthly rent), the second for the operator only."""

    model_config = ConfigDict(extra="forbid")

    number: str
    e164: str
    city: str | None
    client_inr_per_month: str | None
    vendor_inr_per_month: str | None


class AdminAvailableNumbersOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numbers: list[AdminAvailableNumberOut]
    next_cursor: str | None


@router.get(
    "/tenants/{tenant_id}/numbers/available",
    response_model=AdminAvailableNumbersOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Numbers this client could buy in its own workspace, a page at a time",
)
async def admin_available(
    tenant_id: UUID,
    session: AdminSession,
    request: Request,
    principal: WorkspaceOperator,
    city: Annotated[str | None, Query(max_length=60)] = None,
    pattern: Annotated[str | None, Query(pattern=r"^\d{1,10}$")] = None,
    cursor: Annotated[str | None, Query(pattern=r"^\d{1,9}$")] = None,
) -> AdminAvailableNumbersOut:
    if not engine_has_workspaces():
        raise _off()
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        readiness = await purchase_readiness(scoped, tenant_id=tenant_id)
        page = await engine_numbers.search_available(
            scoped, tenant_id, city=city, pattern=pattern, cursor=cursor
        )
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    client_price = (
        str(readiness.client_inr_per_month) if readiness.client_inr_per_month is not None else None
    )
    return AdminAvailableNumbersOut(
        numbers=[
            AdminAvailableNumberOut(
                number=n.number,
                e164=n.e164,
                city=n.city,
                client_inr_per_month=client_price,
                vendor_inr_per_month=(
                    str(n.vendor_monthly_inr) if n.vendor_monthly_inr is not None else None
                ),
            )
            for n in page.numbers
        ],
        next_cursor=page.next_cursor,
    )


class AdminPurchaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=8, max_length=20, pattern=r"^\+?\d{8,15}$")
    agent_id: UUID | None = None
    direction: NumberDirection = "both"
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class AdminPurchasedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number_id: UUID
    e164: str
    client_inr_per_month: str | None
    attachment: str
    replayed: bool
    #: What became of the first month: `charged` (from the wallet), `invoiced`, `trial`
    #: (free), `closed`, or `replayed` when an earlier click already bought it; null for an
    #: unpriced number. The screen words its sentence from this, so it never claims a charge
    #: that did not happen.
    first_period: RentalOutcome | None


@router.post(
    "/tenants/{tenant_id}/numbers/purchase",
    response_model=AdminPurchasedOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Buy a number in this client's own workspace, in its name — charges it a month",
    description=(
        "The client's own purchase, run by an operator: same gates (verified business, "
        "approved business details, attested price, enough credit), same charge (the "
        "client's first month now). Repeating `request_key` never buys a second number."
    ),
)
async def admin_purchase(
    tenant_id: UUID, payload: AdminPurchaseIn, request: Request, principal: WorkspaceOperator
) -> AdminPurchasedOut:
    if not engine_has_workspaces():
        raise _off()
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        await write_audit(
            scoped,
            action="number.buy_requested",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"workspace": "client", "agent_id": str(payload.agent_id or "")},
        )
    bought = await purchase_engine_number(
        tenant_id=tenant_id,
        number=payload.number,
        agent_id=payload.agent_id,
        direction=payload.direction,
        idempotency_key=payload.request_key,
        requested_by="admin",
    )
    if not bought.replayed:
        try:
            async with tenant_session(tenant_id) as scoped:
                await write_audit(
                    scoped,
                    action="number.bought",
                    actor=principal,
                    tenant_id=tenant_id,
                    object_type="phone_number",
                    object_id=str(bought.number_id),
                    ip=client_request_ip(request),
                    summary={
                        "client_inr_per_month": str(bought.client_inr_per_month),
                        "attachment": bought.attachment,
                    },
                )
        except Exception as exc:
            log.error(
                "number_bought_audit_not_written",
                extra={
                    "tenant_id": str(tenant_id),
                    "number_id": str(bought.number_id),
                    "reason": type(exc).__name__,
                },
            )
    return AdminPurchasedOut(
        number_id=bought.number_id,
        e164=bought.e164,
        client_inr_per_month=(
            str(bought.client_inr_per_month) if bought.client_inr_per_month is not None else None
        ),
        attachment=bought.attachment,
        replayed=bought.replayed,
        first_period=bought.first_period,
    )


class AdminReleaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: Literal[True]


class AdminReleasedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number_id: UUID
    released: bool


@router.post(
    "/tenants/{tenant_id}/numbers/{number_id}/release",
    response_model=AdminReleasedOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Release a voice-platform number for good — no refund of the month",
    description=(
        "Permanent: the number goes back to the pool and anybody may take it next; the "
        "current month is not refunded by the platform or to the client. The client's "
        "monthly charge stops. A number held in the platform account (testing) is released "
        "only here. Requires `confirm: true`."
    ),
)
async def admin_release(
    tenant_id: UUID,
    number_id: UUID,
    payload: AdminReleaseIn,
    request: Request,
    principal: WorkspaceOperator,
) -> AdminReleasedOut:
    if not engine_has_workspaces():
        raise _off()
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        released = await release_engine_number(
            scoped, tenant_id=tenant_id, number_id=number_id, by_admin=True
        )
        await write_audit(
            scoped,
            action="number.released",
            actor=principal,
            tenant_id=tenant_id,
            object_type="phone_number",
            object_id=str(number_id),
            ip=client_request_ip(request),
            summary={"released": str(released), "refunded": "False"},
        )
    return AdminReleasedOut(number_id=number_id, released=released)


@router.post(
    "/tenants/{tenant_id}/numbers/{number_id}/forget",
    response_model=AdminReleasedOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Release our record of a number the platform no longer holds, or a test number",
    description=(
        "Stops our record and the client's monthly charge without releasing anything at the "
        "voice platform: for a number the platform no longer holds (the "
        "`engine_number_missing_at_vendor` alarm), or a number held in the platform account "
        "that was recorded for this client for testing (it is detached from the client's "
        "agents and stays ours). Refused with `engine_number_still_held` for a number the "
        "client's own workspace still holds: release that one. Requires `confirm: true`."
    ),
)
async def admin_forget(
    tenant_id: UUID,
    number_id: UUID,
    payload: AdminReleaseIn,
    request: Request,
    principal: WorkspaceOperator,
) -> AdminReleasedOut:
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        released = await forget_engine_number(scoped, tenant_id=tenant_id, number_id=number_id)
        await write_audit(
            scoped,
            action="number.record_released",
            actor=principal,
            tenant_id=tenant_id,
            object_type="phone_number",
            object_id=str(number_id),
            ip=client_request_ip(request),
            summary={"released": str(released)},
        )
    return AdminReleasedOut(number_id=number_id, released=released)


class WorkspaceFailureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    tenant_name: str
    status: str
    last_error_code: str | None


class WorkspacesSummaryOut(BaseModel):
    """Every client's workspace against the plan, for the ops dashboard."""

    model_config = ConfigDict(extra="forbid")

    available: bool
    plan: str | None
    #: How many customer workspaces the plan allows.
    plan_cap: int | None
    #: Workspaces counting against the cap: active, being offboarded, or deleted and not yet
    #: erased by the platform (30 days).
    counted: int
    headroom: int | None
    #: Live client accounts.
    tenants: int
    provisioned: int
    by_status: dict[str, int]
    #: Clients waiting on the plan, failing, or never provisioned (up to 50).
    failures: list[WorkspaceFailureOut]
    #: Live clients with no workspace row at all yet: the backfill still owed.
    not_provisioned: int


_LIVE_TENANTS = (
    "SELECT id, name FROM organizations WHERE deleted_at IS NULL AND status <> 'churned' "
    "ORDER BY id"
)


@router.get(
    "/summary",
    response_model=WorkspacesSummaryOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Client voice workspaces provisioned against clients, failures and plan headroom",
)
async def workspaces_summary(_: OpsViewer) -> WorkspacesSummaryOut:
    if not engine_has_workspaces():
        return WorkspacesSummaryOut(
            available=False,
            plan=None,
            plan_cap=None,
            counted=0,
            headroom=None,
            tenants=0,
            provisioned=0,
            by_status={},
            failures=[],
            not_provisioned=0,
        )
    async with admin_session() as directory:
        tenants = {
            UUID(str(r[0])): str(r[1]) for r in (await directory.execute(text(_LIVE_TENANTS))).all()
        }
    rows = await workspace_directory()
    errors = await _error_codes()
    plan = get_settings().thinnest_customer_plan
    cap = PLAN_CUSTOMER_CAPS[plan]
    now = datetime.now(UTC)
    deleted_recent = await _recently_deleted(now - ERASE_AFTER)
    counted = sum(1 for r in rows if r.status in ("active", "offboarding")) + deleted_recent
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    have_row = {row.tenant_id for row in rows}
    failures = [
        WorkspaceFailureOut(
            tenant_id=row.tenant_id,
            tenant_name=tenants.get(row.tenant_id, ""),
            status=row.status,
            last_error_code=errors.get(row.tenant_id),
        )
        for row in rows
        if row.status in ("plan_limit", "failed") and row.tenant_id in tenants
    ]
    failures.extend(
        WorkspaceFailureOut(
            tenant_id=tenant_id, tenant_name=name, status="not_provisioned", last_error_code=None
        )
        for tenant_id, name in tenants.items()
        if tenant_id not in have_row
    )
    return WorkspacesSummaryOut(
        available=True,
        plan=plan,
        plan_cap=cap,
        counted=counted,
        headroom=max(cap - counted, 0),
        tenants=len(tenants),
        provisioned=by_status.get("active", 0),
        by_status=by_status,
        failures=failures[:50],
        not_provisioned=sum(1 for t in tenants if t not in have_row),
    )


async def _error_codes() -> dict[UUID, str]:
    from apps.api.db.session import untenanted_session

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tenant_id, last_error_code FROM tenant_engine_workspaces "
                    "WHERE last_error_code IS NOT NULL ORDER BY tenant_id LIMIT 1000"
                )
            )
        ).all()
    return {UUID(str(r[0])): str(r[1]) for r in rows}


async def _recently_deleted(since: datetime) -> int:
    from apps.api.db.session import untenanted_session

    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM tenant_engine_workspaces WHERE status = 'deleted' "
                        "AND deleted_at >= :since"
                    ),
                    {"since": since},
                )
            ).scalar_one()
        )


__all__ = ["router"]
