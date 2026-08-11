"""Integration endpoints — the client's own webhook config (D-23, SURFACES §2b).

`org:manage` throughout: pointing our events at a URL is an account-level decision, not
a lead-handling one, and staff explicitly do not get org settings (SEC-COMP §5).

The signing secret is returned EXACTLY ONCE, at creation. After that the API answers
with a fingerprint and never the value — a config screen that re-displays a shared
secret turns every screenshot and every support session into a key disclosure.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.integrations.service import EVENT_TYPES

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])

Session = Annotated[AsyncSession, Depends(db)]

EventName = Literal["lead.created", "lead.updated", "call.completed", "campaign.completed"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateEndpointIn(Strict):
    # HttpUrl rejects a bare hostname and anything that is not http(s) — we sign and
    # POST to whatever lands here, so "looks like a URL" is not good enough.
    url: HttpUrl
    events: list[EventName] = Field(min_length=1)


class CreateEndpointOut(Strict):
    id: UUID
    url: str
    events: list[str]
    # Shown once, never again.
    secret: str


class EndpointOut(Strict):
    id: UUID
    url: str | None
    events: list[str]
    active: bool
    secret_fingerprint: str | None
    created_at: datetime


class DeliveryOut(Strict):
    id: UUID
    event_type: str | None
    status: str | None
    attempts: int
    first_at: datetime
    last_at: datetime


def _fingerprint(secret: str) -> str:
    """First 8 hex of the digest — enough to tell two secrets apart in a support call,
    useless for forging one."""
    return hashlib.sha256(secret.encode()).hexdigest()[:8]


@router.get(
    "/events",
    openapi_extra=permission_meta("org:read"),
    summary="The events an endpoint may subscribe to",
)
async def list_event_types(_: Principal = Depends(requires("org:read"))) -> dict[str, list[str]]:
    return {"events": list(EVENT_TYPES)}


@router.get(
    "/endpoints",
    response_model=list[EndpointOut],
    openapi_extra=permission_meta("org:manage"),
)
async def list_endpoints(
    session: Session,
    _: Principal = Depends(requires("org:manage")),
) -> list[EndpointOut]:
    rows = (
        await session.execute(
            text(
                "SELECT id, url, events, active, secret_ref, created_at FROM outbound_webhooks "
                "WHERE kind = 'webhook' ORDER BY created_at DESC"
            )
        )
    ).all()
    return [
        EndpointOut(
            id=r[0],
            url=r[1],
            events=list(r[2] or []),
            active=bool(r[3]),
            secret_fingerprint=_fingerprint(r[4]) if r[4] else None,
            created_at=r[5],
        )
        for r in rows
    ]


@router.post(
    "/endpoints",
    response_model=CreateEndpointOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Register a webhook endpoint — the signing secret is shown once",
)
async def create_endpoint(
    payload: CreateEndpointIn,
    session: Session,
    principal: Principal = Depends(requires("org:manage")),
) -> CreateEndpointOut:
    assert principal.tenant_id is not None
    endpoint_id = uuid7()
    secret = secrets.token_urlsafe(32)
    await session.execute(
        text(
            "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
            "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, :secret, "
            ":events, true, now(), now())"
        ),
        {
            "id": endpoint_id,
            "tid": principal.tenant_id,
            "url": str(payload.url),
            "secret": secret,
            "events": list(payload.events),
        },
    )
    return CreateEndpointOut(
        id=endpoint_id, url=str(payload.url), events=list(payload.events), secret=secret
    )


@router.delete(
    "/endpoints/{endpoint_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Deactivate — kept, not deleted, so the delivery history stays readable",
)
async def deactivate_endpoint(
    endpoint_id: UUID,
    session: Session,
    _: Principal = Depends(requires("org:manage")),
) -> None:
    result = await session.execute(
        text(
            "UPDATE outbound_webhooks SET active = false, updated_at = now() "
            "WHERE id = :id AND active = true"
        ),
        {"id": endpoint_id},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Endpoint")


@router.get(
    "/deliveries",
    response_model=list[DeliveryOut],
    openapi_extra=permission_meta("org:manage"),
    summary="Recent delivery attempts — 'did it reach my CRM?' answered without support",
)
async def list_deliveries(
    session: Session,
    limit: int = 50,
    _: Principal = Depends(requires("org:manage")),
) -> list[DeliveryOut]:
    # `webhook_deliveries` is not tenant-RLS'd (engine webhooks arrive before tenant
    # resolution — see its model docstring), so this query is scoped by the tenant's
    # OWN endpoint ids rather than by RLS. That is the whole reason it is a subquery
    # against `outbound_webhooks`, which IS tenant-scoped, instead of a plain select.
    rows = (
        await session.execute(
            text(
                "SELECT d.id, d.event_type, d.status, d.attempts, d.first_at, d.last_at "
                "FROM webhook_deliveries d WHERE d.direction = 'out' "
                "AND d.endpoint_id IN (SELECT id FROM outbound_webhooks) "
                "ORDER BY d.last_at DESC LIMIT :limit"
            ),
            {"limit": min(limit, 200)},
        )
    ).all()
    return [
        DeliveryOut(
            id=r[0],
            event_type=r[1],
            status=r[2],
            attempts=int(r[3] or 0),
            first_at=r[4],
            last_at=r[5],
        )
        for r in rows
    ]


__all__ = ["router"]
