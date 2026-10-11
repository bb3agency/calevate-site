"""`GET /v1/ops/live-apply`: how far each saved setting has reached the live agents (D-720).

The ops console's "Applied to N of M live agents" line reads this, from the run that
`agents/live_apply.queue_live_apply` recorded when the setting was saved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.live_apply import LiveApplyRunView, recent_runs
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/ops/live-apply", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
ConfigReader = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]


class LiveApplyFailureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    agent_id: UUID
    #: The agent's display name when it could be read.
    agent_name: str | None
    #: Our refusal code, e.g. `engine_prompt_too_long`.
    code: str


class LiveApplyRunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    scope: Literal["platform", "tenant", "agent"]
    tenant_id: UUID | None
    agent_id: UUID | None
    #: What changed: setting keys, or a source such as `lead_calling`.
    reasons: list[str]
    #: `pending` (queued), `running`, `done`, or `superseded` (a later save replaced it).
    status: Literal["pending", "running", "done", "superseded"]
    #: Live agents in scope when the walk began; null until it begins.
    total: int | None
    applied: int
    failed: int
    #: Agents waiting on a retry.
    retrying: int
    #: Up to 50 failed agents; `failed` is the exact count.
    failures: list[LiveApplyFailureOut]
    created_at: datetime
    finished_at: datetime | None
    #: The later run that replaced this one, when `status` is `superseded`.
    superseded_by: UUID | None


class LiveApplyRunsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[LiveApplyRunOut]


def _out(run: LiveApplyRunView) -> LiveApplyRunOut:
    return LiveApplyRunOut(
        id=run.id,
        scope=run.scope,
        tenant_id=run.tenant_id,
        agent_id=run.agent_id,
        reasons=run.reasons,
        status=run.status,  # type: ignore[arg-type]
        total=run.total,
        applied=run.applied,
        failed=run.failed,
        retrying=run.retrying,
        failures=[
            LiveApplyFailureOut(
                tenant_id=f["tenant_id"],
                agent_id=f["agent_id"],
                agent_name=f.get("agent_name"),
                code=str(f.get("code", "")),
            )
            for f in run.failures
        ],
        created_at=run.created_at,
        finished_at=run.finished_at,
        superseded_by=run.superseded_by,
    )


@router.get(
    "",
    response_model=LiveApplyRunsOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Recent passes that put a saved setting on the live agents",
    description=(
        "Newest first. Each pass was queued with the write that made it necessary and "
        "republishes every live agent in its scope, reading each back. A call already in "
        "progress finishes on its previous settings. `scope=platform` narrows to ops "
        "console settings."
    ),
)
async def list_live_apply_runs(
    session: GlobalSession,
    principal: ConfigReader,
    scope: Literal["platform", "tenant", "agent"] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> LiveApplyRunsOut:
    del principal
    return LiveApplyRunsOut(
        runs=[_out(run) for run in await recent_runs(session, scope=scope, limit=limit)]
    )


__all__ = ["router"]
