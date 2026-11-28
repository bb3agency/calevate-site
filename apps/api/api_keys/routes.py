"""The console's side of API keys: make, list, renew, revoke, and read the activity log
(D-1047, W2.1 and W2.8).

Making a key is the owner's own act on the CLIENT realm with a code typed for it (D-730's
`ClientActionCode`): a key is a credential that can ring phones, so a console left open must
not be enough to mint one, and a view-as operator cannot. The secret is in the creation
response and nowhere else, ever.

Revoking needs no code: stopping a key is the safe direction, and a person reacting to a
leak must not be slowed down.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.api_keys import service
from apps.api.api_keys.models import MAX_AGENTS, MAX_CIDRS, NAME_MAX, RATE_MAX, RATE_MIN
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.core.schemas import Strict
from apps.api.core.stepup import ClientActionCode, client_confirmation
from apps.api.public_api import activity
from apps.api.public_api.version import CURRENT_VERSION, SUPPORTED_VERSIONS

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])

Session = Annotated[AsyncSession, Depends(db)]
Owner = Annotated[Principal, Depends(requires("org:manage", realm="client"))]
Reader = Annotated[Principal, Depends(requires("org:manage"))]
ConfirmAction = Annotated[str | None, Header(alias="X-Confirm-Action")]
#: The action string the code is typed for (`client_confirmation`).
CREATE_ACTION = "create_api_key"


class CreateApiKeyIn(Strict):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    scopes: list[str] = Field(min_length=1, max_length=len(service.GRANTABLE_SCOPES))
    agent_ids: list[UUID] | None = Field(default=None, max_length=MAX_AGENTS)
    ip_cidrs: list[str] | None = Field(default=None, max_length=MAX_CIDRS)
    rate_per_minute: int | None = Field(default=None, ge=RATE_MIN, le=RATE_MAX)
    #: Left out: the version current now. A key keeps the version it was made with.
    api_version: Literal["2026-12-01"] | None = None


class ApiKeyHealthOut(Strict):
    requests_24h: int
    failed_24h: int
    last_rate_limited_at: datetime | None


class ApiKeyOut(Strict):
    id: UUID
    name: str
    #: The key's first characters, to tell keys apart. Never the key.
    display_prefix: str
    scopes: list[str] = Field(max_length=len(service.GRANTABLE_SCOPES))
    agent_ids: list[UUID] | None = Field(max_length=MAX_AGENTS)
    ip_cidrs: list[str] | None = Field(max_length=MAX_CIDRS)
    rate_per_minute: int | None
    api_version: str
    state: Literal["active", "expiring", "expired", "revoked"]
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    health: ApiKeyHealthOut


class CreatedApiKeyOut(Strict):
    key: ApiKeyOut
    #: The key itself. Shown once: it is not kept and cannot be shown again.
    secret: str


class ApiKeysOut(Strict):
    keys: list[ApiKeyOut] = Field(max_length=service.LIST_LIMIT)
    grantable_scopes: list[str] = Field(max_length=len(service.GRANTABLE_SCOPES))
    api_versions: list[str] = Field(max_length=20)


class ApiActivityOut(Strict):
    id: UUID
    api_key_id: UUID
    method: str
    route: str
    status: int
    problem_code: str | None
    #: Our own sentence for what to do about a refusal.
    remediation: str | None
    trace_id: str | None
    latency_ms: int
    replayed: bool
    created_at: datetime


class ApiActivityListOut(Strict):
    requests: list[ApiActivityOut] = Field(max_length=activity.ACTIVITY_LIMIT)


def _state(
    row: service.KeyRow, now: datetime
) -> Literal["active", "expiring", "expired", "revoked"]:
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= now:
        return "expired"
    return "expiring" if row.expires_at - now <= service.RENEW_FROM else "active"


def _out(row: service.KeyRow, health: activity.KeyHealth | None, now: datetime) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id,
        name=row.name,
        display_prefix=row.display_prefix,
        scopes=row.scopes,
        agent_ids=row.agent_ids,
        ip_cidrs=row.ip_cidrs,
        rate_per_minute=row.rate_per_minute,
        api_version=row.api_version,
        state=_state(row, now),
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        health=ApiKeyHealthOut(
            requests_24h=health.requests if health else 0,
            failed_24h=health.failed if health else 0,
            last_rate_limited_at=health.last_rate_limited_at if health else None,
        ),
    )


@router.get(
    "",
    response_model=ApiKeysOut,
    openapi_extra=permission_meta("org:manage"),
    summary="This account's API keys, newest first, with each one's last 24 hours",
)
async def list_keys(session: Session, _: Reader) -> ApiKeysOut:
    now = datetime.now(UTC)
    health = await activity.key_health(session, now=now)
    return ApiKeysOut(
        keys=[_out(r, health.get(r.id), now) for r in await service.list_keys(session)],
        grantable_scopes=sorted(service.GRANTABLE_SCOPES),
        api_versions=list(SUPPORTED_VERSIONS),
    )


@router.post(
    "",
    response_model=CreatedApiKeyOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Make an API key. The key is in this answer once and never again",
)
async def create_key(
    payload: CreateApiKeyIn,
    session: Session,
    request: Request,
    principal: Owner,
    code: ClientActionCode,
    x_confirm_action: ConfirmAction = None,
) -> CreatedApiKeyOut:
    await code.require(x_confirm_action, client_confirmation(request, CREATE_ACTION))
    assert principal.tenant_id is not None and principal.user_id is not None
    assert principal.role is not None
    row, secret = await service.create_key(
        session,
        tenant_id=principal.tenant_id,
        created_by=principal.user_id,
        creator_role=principal.role,
        name=payload.name,
        scopes=payload.scopes,
        agent_ids=payload.agent_ids,
        ip_cidrs=payload.ip_cidrs,
        rate_per_minute=payload.rate_per_minute,
        api_version=payload.api_version or CURRENT_VERSION,
    )
    await write_audit(
        session,
        action="api_key.created",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="api_key",
        object_id=str(row.id),
        ip=client_request_ip(request),
        summary={
            "scopes": row.scopes,
            "agents_bound": row.agent_ids is not None,
            "addresses_bound": row.ip_cidrs is not None,
        },
    )
    return CreatedApiKeyOut(key=_out(row, None, datetime.now(UTC)), secret=secret)


@router.post(
    "/{key_id}/revoke",
    response_model=ApiKeyOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Stop a key now. Its next request is refused",
)
async def revoke_key(
    key_id: UUID, session: Session, request: Request, principal: Owner
) -> ApiKeyOut:
    assert principal.tenant_id is not None
    before = await service.get_key(session, key_id)
    row = await service.revoke_key(session, key_id=key_id, revoked_by=principal.client_user_id)
    if before is not None and before.revoked_at is None:
        await write_audit(
            session,
            action="api_key.revoked",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="api_key",
            object_id=str(key_id),
            ip=client_request_ip(request),
        )
    return _out(row, None, datetime.now(UTC))


@router.post(
    "/{key_id}/renew",
    response_model=ApiKeyOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Keep a working key for another 90 days",
)
async def renew_key(
    key_id: UUID, session: Session, request: Request, principal: Owner
) -> ApiKeyOut:
    assert principal.tenant_id is not None
    row = await service.renew_key(session, key_id=key_id)
    await write_audit(
        session,
        action="api_key.renewed",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="api_key",
        object_id=str(key_id),
        ip=client_request_ip(request),
        summary={"expires_at": row.expires_at.isoformat()},
    )
    return _out(row, None, datetime.now(UTC))


@router.get(
    "/activity",
    response_model=ApiActivityListOut,
    openapi_extra=permission_meta("org:manage"),
    summary="The last 100 API requests: route, status and what to do about a refusal",
)
async def list_activity(
    session: Session,
    _: Reader,
    key_id: UUID | None = Query(None, description="Only this key's requests"),
    failed: bool = Query(False, description="Only requests that were refused or failed"),
    limit: int = Query(activity.ACTIVITY_LIMIT, ge=1, le=activity.ACTIVITY_LIMIT),
) -> ApiActivityListOut:
    rows = await activity.list_activity(session, api_key_id=key_id, failed_only=failed, limit=limit)
    return ApiActivityListOut(
        requests=[
            ApiActivityOut(
                id=r.id,
                api_key_id=r.api_key_id,
                method=r.method,
                route=r.route,
                status=r.status,
                problem_code=r.problem_code,
                remediation=r.remediation,
                trace_id=r.trace_id,
                latency_ms=r.latency_ms,
                replayed=r.replayed,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


__all__ = ["CREATE_ACTION", "router"]
