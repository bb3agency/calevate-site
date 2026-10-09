"""Live reads that feed the configuration screen's pickers.

A setting that names something which exists elsewhere is chosen from that thing, never
typed (D-704). Each read here lists what such a setting may name; the write still goes
through `PUT /v1/ops/config/{key}` and its validation. The shared trial number's read is
`ops/trial_number.py` and the client list is `GET /v1/admin/tenants`, so neither is here.

    GET /v1/ops/config-sources/thinnest-workspace   our own ThinnestAI workspace

An unreachable vendor is answered with its problem, never with an empty answer the console
could read as "there is nothing to choose".
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.engine.thinnest_customers import thinnest_customers

router = APIRouter(prefix="/v1/ops/config-sources", tags=["ops"])
ConfigReader = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]


class ThinnestWorkspaceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Our workspace's id (`org_…`), as ThinnestAI reports it.
    workspace_id: str
    #: Its name in ThinnestAI's console; null when the answer carried none.
    name: str | None
    #: True when `thinnest_developer_workspace_id` already holds this id.
    matches_setting: bool


@router.get(
    "/thinnest-workspace",
    response_model=ThinnestWorkspaceOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Our own ThinnestAI workspace, read live from ThinnestAI",
    description=(
        "Calls ThinnestAI's `GET /workspace` without a workspace header, which answers with "
        "the workspace the API key belongs to. Refused with the vendor's problem when no "
        "ThinnestAI key is installed or ThinnestAI cannot be reached."
    ),
)
async def read_thinnest_workspace(principal: ConfigReader) -> ThinnestWorkspaceOut:
    del principal
    workspace = await thinnest_customers().developer_workspace()
    return ThinnestWorkspaceOut(
        workspace_id=workspace.workspace_id,
        name=workspace.name,
        matches_setting=get_settings().thinnest_developer_workspace_id == workspace.workspace_id,
    )


__all__ = ["ThinnestWorkspaceOut", "read_thinnest_workspace", "router"]
