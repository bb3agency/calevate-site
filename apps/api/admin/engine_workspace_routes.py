"""The operator's view of each client's own voice-platform workspace (D-693).

Per client (`/tenants/{tenant_id}`): the workspace and where its provisioning stands, its
business-details application, the purchase gates, and the numbers it holds — its own and any
held in the platform account for testing. Actions: provision again, send the business details
(again), refresh their status, offboard again, and buy or release a number in the client's
name through the same purchase path the client uses (`campaigns/engine_number_purchase.py`),
and record how many engine agents ThinnestAI lets this workspace hold once they raise it
(`agents/workspace_slots.workspace_agent_allowance`).

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
from decimal import Decimal
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from calevate_shared.engine_scope import scope_of
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service
from apps.api.agents.workspace_slots import (
    slot_holders,
    workspace_agent_allowance,
    workspace_agent_override,
)
from apps.api.billing.number_rental import RentalOutcome
from apps.api.billing.service import refuse_json_float
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
from apps.api.core.stepup import StepUpGate
from apps.api.db.session import admin_session, tenant_session
from apps.api.engine.thinnest_customers import PLAN_CUSTOMER_CAPS
from apps.api.engine.thinnest_numbers import BusinessDetails
from apps.api.tenancy.engine_workspace import (
    engine_has_workspaces,
    queue_workspace_offboarding,
    queue_workspace_provisioning,
    read_developer_retention,
    read_retention_record,
    read_workspace_state,
    workspace_directory,
)
from apps.api.tenancy.models import AGENT_ALLOWANCE_MAX, AGENT_ALLOWANCE_MIN

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin/engine-workspaces", tags=["admin"])

AdminSession = Annotated[AsyncSession, Depends(admin_db)]
WorkspaceOperator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
ConfirmAction = Annotated[str | None, Header(alias="X-Confirm-Action")]
#: A read; D-22 forbids gating a GET on `admin:tenants`, which read-only impersonation
#: refuses. Both admin roles hold `org:read`.
AllowanceReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]


#: The step-up strings for this router's writes (D-731), each bound to the tenant and, for
#: a release, to the number. Buying and releasing move money and a client's phone line;
#: provisioning and offboarding create or dismantle the client's whole voice workspace.
def workspace_provision_confirmation(tenant_id: UUID) -> str:
    return f"provision_workspace:{tenant_id}"


def workspace_offboard_confirmation(tenant_id: UUID) -> str:
    return f"offboard_workspace:{tenant_id}"


def buy_number_confirmation(tenant_id: UUID) -> str:
    return f"buy_number:{tenant_id}"


def release_number_confirmation(tenant_id: UUID, number_id: UUID) -> str:
    return f"release_number:{tenant_id}:{number_id}"


def forget_number_confirmation(tenant_id: UUID, number_id: UUID) -> str:
    """Forgetting stops the client's monthly charge as releasing does, so it is gated alike."""
    return f"forget_number:{tenant_id}:{number_id}"


def move_number_confirmation(tenant_id: UUID, number_id: UUID) -> str:
    return f"move_number:{tenant_id}:{number_id}"


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


class CallRetentionOut(BaseModel):
    """The call retention last confirmed on a workspace: a client's (D-798) or our developer
    workspace (D-809, which has no `error_code`)."""

    model_config = ConfigDict(extra="forbid")

    #: `callRetentionDays` set there; None until the first push.
    days: int | None
    #: The plan's `planRetentionDays` read with it.
    plan_days: int | None
    checked_at: datetime | None
    #: Our code for the last failure to set or read it.
    error_code: str | None


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
    #: How long the voice platform keeps this client's calls; None without workspaces.
    call_retention: CallRetentionOut | None = None


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
    retention = await read_retention_record(session, tenant_id)
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
        call_retention=CallRetentionOut(
            days=retention.days,
            plan_days=retention.plan_days,
            checked_at=retention.checked_at,
            error_code=retention.error_code,
        ),
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
    tenant_id: UUID,
    request: Request,
    principal: WorkspaceOperator,
    step_up: StepUpGate,
    x_confirm_action: ConfirmAction = None,
) -> TenantWorkspaceOut:
    step_up.require(x_confirm_action, workspace_provision_confirmation(tenant_id))
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
        "agents and deletes the customer. Refused unless the account is closed. While a "
        "rented number there is still held (D-860) nothing is done; the hold's release "
        "queues the offboarding again."
    ),
)
async def offboard_again(
    tenant_id: UUID,
    request: Request,
    principal: WorkspaceOperator,
    step_up: StepUpGate,
    x_confirm_action: ConfirmAction = None,
) -> TenantWorkspaceOut:
    step_up.require(x_confirm_action, workspace_offboard_confirmation(tenant_id))
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
    # Before the attempt: the failure row below names this client, and `audit_log.tenant_id`
    # must reference a real one, so an unknown id would turn the refusal into a 500.
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)

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


class AgentAllowanceOut(BaseModel):
    """How many engine agents ("calling setups") this client's own workspace may hold."""

    model_config = ConfigDict(extra="forbid")

    #: The cap in force: `agent_allowance` when set, else `default`.
    limit: int
    #: The cap ThinnestAI raised for this workspace, as an operator recorded it; null is the
    #: console default.
    agent_allowance: int | None
    #: The console's `thinnest_agents_per_workspace`.
    default: int
    #: Setups held in the workspace now, counting any whose deletion has not run; null
    #: without an active workspace.
    in_use: int | None
    #: A cap can be recorded only once the workspace exists at ThinnestAI.
    settable: bool
    min_allowance: int
    max_allowance: int


class AgentAllowanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `null` goes back to the console default.
    agent_allowance: int | None = Field(ge=AGENT_ALLOWANCE_MIN, le=AGENT_ALLOWANCE_MAX)


def agent_allowance_confirmation(tenant_id: UUID) -> str:
    """The step-up string for changing one client's cap: past what ThinnestAI really allows,
    every new setup there is refused by the platform, so it is confirmed like call lines."""
    return f"set_agent_allowance:{tenant_id}"


_ALLOWANCE_ROW = "SELECT workspace_id, status FROM tenant_engine_workspaces WHERE tenant_id = :tid"


async def _allowance_out(scoped: AsyncSession, tenant_id: UUID) -> AgentAllowanceOut:
    row = (await scoped.execute(text(_ALLOWANCE_ROW), {"tid": tenant_id})).first()
    workspace_id = row[0] if row is not None else None
    active = row is not None and row[1] == "active" and workspace_id is not None
    return AgentAllowanceOut(
        limit=await workspace_agent_allowance(scoped, tenant_id),
        agent_allowance=await workspace_agent_override(scoped, tenant_id),
        default=get_settings().thinnest_agents_per_workspace,
        in_use=(
            len(
                await slot_holders(
                    scoped,
                    tenant_id=tenant_id,
                    engine=get_settings().engine,
                    workspace=str(workspace_id),
                )
            )
            if active
            else None
        ),
        settable=workspace_id is not None,
        min_allowance=AGENT_ALLOWANCE_MIN,
        max_allowance=AGENT_ALLOWANCE_MAX,
    )


_ALLOWANCE_DESCRIPTION = (
    "How many engine agents (agents, inbound lines, campaigns, script trials and test calls) "
    "this client's own ThinnestAI workspace may hold. ThinnestAI allows 2 per workspace on "
    "pay-as-you-go and raises it per workspace on request; record a raise here once they "
    "confirm it. `null` is the console's `thinnest_agents_per_workspace`. Refused "
    "`engine_workspace_not_provisioned` until the workspace exists."
)


@router.get(
    "/tenants/{tenant_id}/agent-allowance",
    response_model=AgentAllowanceOut,
    openapi_extra=permission_meta("org:read"),
    summary="How many calling setups this client's workspace may hold",
    description=_ALLOWANCE_DESCRIPTION,
)
async def admin_agent_allowance(
    tenant_id: UUID, request: Request, principal: AllowanceReader
) -> AgentAllowanceOut:
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        out = await _allowance_out(scoped, tenant_id)
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    return out


@router.put(
    "/tenants/{tenant_id}/agent-allowance",
    response_model=AgentAllowanceOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record the calling setups ThinnestAI allows this client's workspace",
    description=_ALLOWANCE_DESCRIPTION,
)
async def admin_set_agent_allowance(
    tenant_id: UUID,
    payload: AgentAllowanceIn,
    request: Request,
    principal: WorkspaceOperator,
    step_up: StepUpGate,
    x_confirm_action: ConfirmAction = None,
) -> AgentAllowanceOut:
    step_up.require(x_confirm_action, agent_allowance_confirmation(tenant_id))
    if not engine_has_workspaces():
        raise _off()
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        before = (
            await scoped.execute(
                text(
                    "SELECT agent_allowance FROM tenant_engine_workspaces "
                    "WHERE tenant_id = :tid AND workspace_id IS NOT NULL FOR UPDATE"
                ),
                {"tid": tenant_id},
            )
        ).first()
        if before is None:
            raise ProblemError.business_rule(
                "engine_workspace_not_provisioned",
                "This client has no voice workspace yet, so there is no cap to raise.",
                remediation="Create the workspace first, then ask ThinnestAI to raise its cap.",
            )
        await scoped.execute(
            text(
                "UPDATE tenant_engine_workspaces SET agent_allowance = :n, updated_at = now() "
                "WHERE tenant_id = :tid"
            ),
            {"n": payload.agent_allowance, "tid": tenant_id},
        )
        out = await _allowance_out(scoped, tenant_id)
        await write_audit(
            scoped,
            action="engine_workspace.agent_allowance_set",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={
                "agent_allowance": payload.agent_allowance,
                "was": before[0],
                "limit": out.limit,
            },
        )
    log.info(
        "engine_workspace_agent_allowance_set",
        extra={"tenant_id": str(tenant_id), "limit": out.limit},
    )
    return out


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
    pattern: Annotated[str | None, Query(pattern=r"^[0-9]{1,10}$")] = None,
    cursor: Annotated[str | None, Query(pattern=r"^[0-9]{1,9}$")] = None,
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

    number: str = Field(min_length=8, max_length=20, pattern=r"^\+?[0-9]{8,15}$")
    agent_id: UUID | None = None
    direction: NumberDirection = "both"
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    #: The client's monthly price the confirmation showed (the list's `client_inr_per_month`).
    #: Refused as `number_price_changed` when it is no longer the attested price, as on the
    #: client's own purchase, so a client is never charged a rate the operator did not see.
    inr_per_month: Decimal | None = Field(default=None, max_digits=12, decimal_places=2, gt=0)

    @field_validator("inr_per_month", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        return refuse_json_float(value)


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
    tenant_id: UUID,
    payload: AdminPurchaseIn,
    request: Request,
    principal: WorkspaceOperator,
    step_up: StepUpGate,
    x_confirm_action: ConfirmAction = None,
) -> AdminPurchasedOut:
    step_up.require(x_confirm_action, buy_number_confirmation(tenant_id))
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
        quoted_inr_per_month=payload.inr_per_month,
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
                    "error": type(exc).__name__,
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
    step_up: StepUpGate,
    x_confirm_action: ConfirmAction = None,
) -> AdminReleasedOut:
    step_up.require(x_confirm_action, release_number_confirmation(tenant_id, number_id))
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
    summary="Take a number back from a client: our record ends and the number stays ours",
    description=(
        "Stops our record and the client's monthly charge without releasing anything at the "
        "voice platform: for a number the platform no longer holds (the "
        "`engine_number_missing_at_vendor` alarm), a number held in the platform account "
        "that was recorded for this client (detached from the client's agents, stays ours), "
        "or a number the client's own workspace holds, which is moved back into ours first "
        "with the same digits. Requires `confirm: true`."
    ),
)
async def admin_forget(
    tenant_id: UUID,
    number_id: UUID,
    payload: AdminReleaseIn,
    request: Request,
    principal: WorkspaceOperator,
    step_up: StepUpGate,
    x_confirm_action: ConfirmAction = None,
) -> AdminReleasedOut:
    step_up.require(x_confirm_action, forget_number_confirmation(tenant_id, number_id))
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


class AdminMovedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number_id: UUID
    #: `moved` now, or `queued`: the number is on a call (or the move is under way) and is
    #: tried again every two minutes until it can be.
    status: Literal["moved", "queued"]


@router.post(
    "/tenants/{tenant_id}/numbers/{number_id}/move",
    response_model=AdminMovedOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Move a number into the client's own voice workspace, keeping its digits",
    description=(
        "For a number held in the platform account, or in a workspace the client no longer "
        "uses: it moves into the client's own workspace with the same digits, instead of "
        "releasing it and buying new ones, and is pointed at the client's agent again. A "
        "rented number is charged to the client from its next renewal. Refused until the "
        "client's business details are approved (an Indian number is held in the name of "
        "the business using it). A number on a call is moved once the call ends."
    ),
)
async def admin_move(
    tenant_id: UUID,
    number_id: UUID,
    request: Request,
    principal: WorkspaceOperator,
    step_up: StepUpGate,
    x_confirm_action: ConfirmAction = None,
) -> AdminMovedOut:
    step_up.require(x_confirm_action, move_number_confirmation(tenant_id, number_id))
    if not engine_has_workspaces():
        raise _off()
    status: Literal["moved", "queued"] = "moved"
    async with tenant_session(tenant_id) as scoped:
        await _require_tenant(scoped, tenant_id)
        try:
            await engine_numbers.move_into_client_workspace(
                scoped, tenant_id=tenant_id, number_id=number_id
            )
        except ProblemError as exc:
            if exc.code != "engine_number_move_later":
                raise
            await engine_numbers.queue_number_move(tenant_id, number_id, attempt=1)
            status = "queued"
        await write_audit(
            scoped,
            action="number.moved_to_client_workspace",
            actor=principal,
            tenant_id=tenant_id,
            object_type="phone_number",
            object_id=str(number_id),
            ip=client_request_ip(request),
            summary={"status": status},
        )
    return AdminMovedOut(number_id=number_id, status=status)


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
    #: What our developer workspace (trial calls, calls from before D-693) last confirmed
    #: (D-809); the missing-recording alarm dates its calls' deletion from `days`. None on an
    #: engine without workspaces.
    developer_call_retention: CallRetentionOut | None


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
            developer_call_retention=None,
        )
    async with admin_session() as directory:
        tenants = {
            UUID(str(r[0])): str(r[1]) for r in (await directory.execute(text(_LIVE_TENANTS))).all()
        }
        developer = await read_developer_retention(directory)
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
        developer_call_retention=CallRetentionOut(
            days=developer.days,
            plan_days=developer.plan_days,
            checked_at=developer.checked_at,
            error_code=None,
        ),
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
