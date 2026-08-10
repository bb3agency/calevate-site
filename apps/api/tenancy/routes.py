"""Session/identity endpoints.

`/v1/me` is the first call every frontend makes. It exists so the browser never has to
infer who it is talking as: the realm, the resolved tenant, the role and the permission
set all come from the server, and the UI renders from them rather than from a decoded
JWT it might read differently than we do.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import current_any
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import ROLE_PERMISSIONS, permission_meta

router = APIRouter(prefix="/v1", tags=["tenancy"])

Session = Annotated[AsyncSession, Depends(db)]


class OrganizationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    slug: str
    status: str
    vertical_template: str | None = None


class MeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    realm: str
    user_id: UUID | None
    role: str | None
    permissions: list[str]
    # D-22: the client UI renders a persistent banner when this is true, because a
    # read-only admin session must never look like the client's own session.
    impersonating: bool
    organization: OrganizationOut | None = None


@router.get(
    "/me",
    response_model=MeOut,
    openapi_extra=permission_meta("org:read"),
    summary="Who am I, in which account, with what permissions",
)
async def me(session: Session, principal: Principal = Depends(current_any)) -> MeOut:
    org = None
    row = (
        await session.execute(
            text("SELECT id, name, slug, status, vertical_template FROM organizations LIMIT 1")
        )
    ).first()
    if row is not None:
        org = OrganizationOut(
            id=row[0], name=row[1], slug=row[2], status=row[3], vertical_template=row[4]
        )
    return MeOut(
        realm=principal.realm,
        user_id=principal.user_id,
        role=principal.role,
        permissions=sorted(ROLE_PERMISSIONS.get(principal.role or "", frozenset())),
        impersonating=principal.impersonating,
        organization=org,
    )


__all__ = ["router"]
