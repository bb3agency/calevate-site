"""Agent endpoints. Reads are client-realm; publish is admin-only.

D-21 draws the control boundary and it is enforced here: clients CAN see their agents,
but editing an extraction schema is admin-only, because a schema change regenerates
prompt hints and needs a regression run — that routes through us, which is the
managed-service moat, not an oversight.

WHY THIS ROUTER HAS NO PREFIX
-----------------------------
It carries paths in two spaces — the client realm's `/v1/agents` reads and ONE admin
mutation under `/v1/admin/tenants/{tenant_id}/...` — so a shared prefix could only
describe one of them. Same resolution as `voice_routes.py`, which says so for the same
reason. Mount order is unchanged (`main.py` still includes `voice_router` first so
`/v1/agents/voices` is matched before `/v1/agents/{agent_id}`), and the new admin path
does not collide with anything on `admin/routes.py`: its `/tenants/{tenant_id}/...`
routes all take a different literal third segment (`kb`, `numbers`, `margin`, ...).

WHY PUBLISH NAMES ITS TENANT IN THE PATH
----------------------------------------
It used to be `POST /v1/agents/{agent_id}/publish`, inferring the tenant from
`Principal.tenant_id`, and in that shape it was **un-callable** — verified against the
live app, not reasoned about:

- WITHOUT `X-Impersonate-Org`: 401. Its `Depends(db)` resolves through `tenant_of` ->
  `current_any`, which without the impersonation header falls through to the CLIENT
  verifier and rejects an admin token ("not valid for this realm").
- WITH the header: 403. The principal resolves, but D-22 makes impersonation READ-ONLY
  and `requires()` refuses every `MUTATING_PERMISSIONS` entry — `agents:write`
  included — whenever that header is present.

So its `assert principal.tenant_id is not None` was unreachable code guarding a door
nobody could reach. The two ways an admin principal can carry a tenant are mutually
exclusive with mutating, which is why the fix is NOT to loosen D-22 but to stop
inferring the tenant: name it in the path and enter its RLS scope explicitly, exactly
as `admin/routes.py` does above `approve_kb` ("an admin reaching a tenant does so by
impersonation, and impersonation is read-only. The tenant is therefore named in the
path rather than inferred from a session, which also makes every approval
self-documenting in the audit log") and as `agents/prompt_routes.py` already does at
`/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt`. Publish now sits beside it.

⚠ The path changed, so the OpenAPI snapshot and the generated TS client are stale
until someone regenerates them (`pnpm gen:api`) — deliberately not done here.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.service import publish_agent
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

# No prefix — see the module docstring: the reads and the admin mutation live in
# different path spaces.
router = APIRouter(tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]
# Reads the tenant DIRECTORY cross-tenant so the audit row can be written on it; it
# unlocks no agent rows. The publish itself runs under `tenant_session`, in that
# tenant's own RLS scope.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]


class AgentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    direction: str
    status: str
    language_primary: str
    # Shown to the client verbatim: they are legally the Principal Entity, so they
    # need to be able to read what their agent announces (SEC-COMP §1).
    disclosure_line: str
    engine: str
    published: bool
    extraction_fields: list[ExtractionField] = []


class PublishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    engine_agent_ref: str
    status: str


@router.get(
    "/v1/agents", response_model=list[AgentOut], openapi_extra=permission_meta("agents:read")
)
async def list_agents(
    session: Session, _: Principal = Depends(requires("agents:read"))
) -> list[AgentOut]:
    rows = (
        await session.execute(
            text(
                "SELECT a.id, a.name, a.direction, a.status, a.language_primary, "
                "a.disclosure_line, a.engine, a.engine_agent_ref, es.fields "
                "FROM agents a LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                "WHERE a.deleted_at IS NULL ORDER BY a.created_at"
            )
        )
    ).all()
    return [
        AgentOut(
            id=r[0],
            name=r[1],
            direction=r[2],
            status=r[3],
            language_primary=r[4],
            disclosure_line=r[5],
            engine=r[6],
            published=bool(r[7]),
            extraction_fields=[ExtractionField.model_validate(f) for f in (r[8] or [])],
        )
        for r in rows
    ]


@router.get(
    "/v1/agents/{agent_id}",
    response_model=AgentOut,
    openapi_extra=permission_meta("agents:read"),
)
async def get_agent(
    agent_id: UUID, session: Session, _: Principal = Depends(requires("agents:read"))
) -> AgentOut:
    agents = await list_agents(session)  # RLS-scoped; small list per tenant in v1
    found = next((a for a in agents if a.id == agent_id), None)
    if found is None:
        raise ProblemError.not_found("Agent")
    return found


@router.post(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish",
    response_model=PublishOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Create/update the agent on the engine and record its routing (admin realm, D-21)",
    description=(
        "The tenant is named in the path because an admin principal has no tenant of "
        "its own and the one way it could get one — impersonation — is read-only by "
        "D-22. Sending `X-Impersonate-Org` to this endpoint is still refused; publish "
        "from the admin console instead."
    ),
    tags=["admin"],
)
async def publish(
    tenant_id: UUID,
    agent_id: UUID,
    session: AdminSession,
    request: Request,
    principal: Principal = Depends(requires("agents:write", realm="admin")),
) -> PublishOut:
    """Publish inside the tenant's own RLS scope, audit on the admin session.

    `admin_db` opens the tenant DIRECTORY only (`app.admin` widens `USING` on
    `organizations` alone, migration b57e2f9c4a13) — it does not unlock `agents`, so
    the engine call and the `engine_agent_ref` write must happen under
    `tenant_session`. An agent belonging to a different tenant is simply invisible
    there, which makes "not found" and "belongs to someone else" the same answer.

    `publish_agent` reaches the voice engine, so it stays OUTSIDE the audit session's
    transaction: a slow vendor call must not hold the audit row's transaction open,
    and the audit entry should describe what actually happened.
    """
    async with tenant_session(tenant_id) as scoped:
        ref = await publish_agent(scoped, tenant_id=tenant_id, agent_id=agent_id)
    await write_audit(
        session,
        action="agent.published",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=request.client.host if request.client else None,
    )
    return PublishOut(agent_id=agent_id, engine_agent_ref=ref, status="live")


__all__ = ["router"]
