"""Dashboard pins on the wire (D-934): the client home's cards and the admin home's.

Reads take the home's own door (`org:read` on the client realm, `copilot:admin` on the admin
one) so everyone who sees the home sees its cards — including an operator in a view-as
session. Changing the cards takes the assistant's door (`copilot:use`), which a view-as
session does not hold: the cards are the account's, not the operator's.

A card's figures come from `GET .../pins/{id}/card`, which re-runs the chart under the
viewer's session and role and answers `refused` instead of a spec when the viewer may not
see it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.copilot import charts, pins
from apps.api.copilot.chart_spec import ChartArgs, ChartSpec
from apps.api.copilot.pin_models import MAX_PIN_CHART, MAX_PIN_TITLE
from apps.api.copilot.tools import ToolContext
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1", tags=["copilot"])

ClientReader = Annotated[Principal, Depends(requires("org:read"))]
ClientWriter = Annotated[Principal, Depends(requires("copilot:use"))]
AdminUser = Annotated[Principal, Depends(requires("copilot:admin", realm="admin"))]
TenantSession = Annotated[AsyncSession, Depends(db)]
DirectorySession = Annotated[AsyncSession, Depends(admin_db)]


class PinOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    chart: str
    args: ChartArgs
    title: str
    position: int


class PinPageOut(BaseModel):
    """The home's cards, in order, and how many it may hold."""

    model_config = ConfigDict(extra="forbid")

    pins: list[PinOut]
    max_pins: int


class PinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart: str = Field(min_length=1, max_length=MAX_PIN_CHART)
    args: ChartArgs = ChartArgs()
    title: str = Field(min_length=1, max_length=MAX_PIN_TITLE)


class PinRenameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_PIN_TITLE)


class PinOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(max_length=pins.MAX_PINS)


class PinCardOut(BaseModel):
    """One card, re-run for the viewer: `spec`, or `refused` with the reason."""

    model_config = ConfigDict(extra="forbid")

    pin: PinOut
    spec: ChartSpec | None
    refused: str | None


def _out(row: pins.PinRow) -> PinOut:
    return PinOut(
        id=str(row.id), chart=row.chart, args=row.args, title=row.title, position=row.position
    )


def _page(rows: list[pins.PinRow]) -> PinPageOut:
    return PinPageOut(pins=[_out(r) for r in rows], max_pins=pins.MAX_PINS)


async def _card(
    session: AsyncSession, principal: Principal, row: pins.PinRow, realm: pins.PinRealm
) -> PinCardOut:
    context = ToolContext(tenant_id=principal.tenant_id, role=principal.role)
    try:
        spec = await charts.build_in(session, context, row.chart, row.args.model_dump(), realm)
    except charts.ChartRefusedError as refused:
        return PinCardOut(pin=_out(row), spec=None, refused=refused.reason)
    return PinCardOut(pin=_out(row), spec=spec, refused=None)


async def _audit(
    session: AsyncSession,
    principal: Principal,
    request: Request,
    *,
    action: str,
    row: pins.PinRow,
) -> None:
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=principal.tenant_id if principal.realm == "client" else None,
        object_type="dashboard_pin",
        object_id=str(row.id),
        ip=client_request_ip(request),
        summary={"chart": row.chart, "days": row.args.days},
    )


# --- the client home -----------------------------------------------------------------


@router.get(
    "/copilot/pins",
    response_model=PinPageOut,
    openapi_extra=permission_meta("org:read"),
    summary="The charts pinned to this account's home, in order",
)
async def list_client_pins(session: TenantSession, principal: ClientReader) -> PinPageOut:
    del principal
    return _page(await pins.list_pins(session, "client"))


@router.post(
    "/copilot/pins",
    response_model=PinOut,
    status_code=201,
    openapi_extra=permission_meta("copilot:use"),
    summary="Pin a chart to this account's home",
    description="Stores the chart's name and arguments, never its figures.",
)
async def add_client_pin(
    body: PinIn, session: TenantSession, principal: ClientWriter, request: Request
) -> PinOut:
    row = await pins.add_pin(
        session,
        "client",
        tenant_id=principal.tenant_id,
        created_by=principal.client_user_id,
        chart=body.chart,
        args=body.args.model_dump(),
        title=body.title,
    )
    await _audit(session, principal, request, action="copilot.pin_added", row=row)
    return _out(row)


@router.patch(
    "/copilot/pins/{pin_id}",
    response_model=PinOut,
    openapi_extra=permission_meta("copilot:use"),
    summary="Rename a pinned card",
)
async def rename_client_pin(
    pin_id: UUID, body: PinRenameIn, session: TenantSession, principal: ClientWriter
) -> PinOut:
    del principal
    return _out(await pins.rename_pin(session, "client", pin_id, body.title))


@router.put(
    "/copilot/pins/order",
    response_model=PinPageOut,
    openapi_extra=permission_meta("copilot:use"),
    summary="Put the pinned cards in a new order",
)
async def reorder_client_pins(
    body: PinOrderIn, session: TenantSession, principal: ClientWriter
) -> PinPageOut:
    del principal
    return _page(await pins.reorder_pins(session, "client", body.ids))


@router.delete(
    "/copilot/pins/{pin_id}",
    response_model=PinOut,
    openapi_extra=permission_meta("copilot:use"),
    summary="Take a card off the home (Undo: POST .../restore)",
)
async def remove_client_pin(
    pin_id: UUID, session: TenantSession, principal: ClientWriter, request: Request
) -> PinOut:
    row = await pins.remove_pin(session, "client", pin_id)
    await _audit(session, principal, request, action="copilot.pin_removed", row=row)
    return _out(row)


@router.post(
    "/copilot/pins/{pin_id}/restore",
    response_model=PinOut,
    openapi_extra=permission_meta("copilot:use"),
    summary="Put a removed card back where it was",
)
async def restore_client_pin(
    pin_id: UUID, session: TenantSession, principal: ClientWriter, request: Request
) -> PinOut:
    row = await pins.restore_pin(session, "client", pin_id)
    await _audit(session, principal, request, action="copilot.pin_added", row=row)
    return _out(row)


@router.get(
    "/copilot/pins/{pin_id}/card",
    response_model=PinCardOut,
    openapi_extra=permission_meta("org:read"),
    summary="One pinned card's chart, re-run for the person looking",
)
async def client_pin_card(
    pin_id: UUID, session: TenantSession, principal: ClientReader
) -> PinCardOut:
    row = await pins.get_pin(session, "client", pin_id)
    return await _card(session, principal, row, "client")


# --- the admin home ------------------------------------------------------------------


@router.get(
    "/admin/copilot/pins",
    response_model=PinPageOut,
    openapi_extra=permission_meta("copilot:admin"),
    summary="The charts pinned to the admin home, in order",
)
async def list_admin_pins(session: DirectorySession, principal: AdminUser) -> PinPageOut:
    del principal
    return _page(await pins.list_pins(session, "admin"))


@router.post(
    "/admin/copilot/pins",
    response_model=PinOut,
    status_code=201,
    openapi_extra=permission_meta("copilot:admin"),
    summary="Pin a chart to the admin home",
)
async def add_admin_pin(
    body: PinIn, session: DirectorySession, principal: AdminUser, request: Request
) -> PinOut:
    row = await pins.add_pin(
        session,
        "admin",
        tenant_id=None,
        created_by=principal.user_id,
        chart=body.chart,
        args=body.args.model_dump(),
        title=body.title,
    )
    await _audit(session, principal, request, action="copilot.pin_added", row=row)
    return _out(row)


@router.patch(
    "/admin/copilot/pins/{pin_id}",
    response_model=PinOut,
    openapi_extra=permission_meta("copilot:admin"),
    summary="Rename a card on the admin home",
)
async def rename_admin_pin(
    pin_id: UUID, body: PinRenameIn, session: DirectorySession, principal: AdminUser
) -> PinOut:
    del principal
    return _out(await pins.rename_pin(session, "admin", pin_id, body.title))


@router.put(
    "/admin/copilot/pins/order",
    response_model=PinPageOut,
    openapi_extra=permission_meta("copilot:admin"),
    summary="Put the admin home's cards in a new order",
)
async def reorder_admin_pins(
    body: PinOrderIn, session: DirectorySession, principal: AdminUser
) -> PinPageOut:
    del principal
    return _page(await pins.reorder_pins(session, "admin", body.ids))


@router.delete(
    "/admin/copilot/pins/{pin_id}",
    response_model=PinOut,
    openapi_extra=permission_meta("copilot:admin"),
    summary="Take a card off the admin home (Undo: POST .../restore)",
)
async def remove_admin_pin(
    pin_id: UUID, session: DirectorySession, principal: AdminUser, request: Request
) -> PinOut:
    row = await pins.remove_pin(session, "admin", pin_id)
    await _audit(session, principal, request, action="copilot.pin_removed", row=row)
    return _out(row)


@router.post(
    "/admin/copilot/pins/{pin_id}/restore",
    response_model=PinOut,
    openapi_extra=permission_meta("copilot:admin"),
    summary="Put a removed card back on the admin home",
)
async def restore_admin_pin(
    pin_id: UUID, session: DirectorySession, principal: AdminUser, request: Request
) -> PinOut:
    row = await pins.restore_pin(session, "admin", pin_id)
    await _audit(session, principal, request, action="copilot.pin_added", row=row)
    return _out(row)


@router.get(
    "/admin/copilot/pins/{pin_id}/card",
    response_model=PinCardOut,
    openapi_extra=permission_meta("copilot:admin"),
    summary="One admin card's chart, re-run for the operator looking",
)
async def admin_pin_card(
    pin_id: UUID, session: DirectorySession, principal: AdminUser
) -> PinCardOut:
    row = await pins.get_pin(session, "admin", pin_id)
    return await _card(session, principal, row, "admin")


__all__ = ["router"]
