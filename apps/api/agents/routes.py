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

from calevate_shared.engine import DisclosurePosture, compose_opening_line
from calevate_shared.extraction import ExtractionField
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.publishing import audit_action_for, set_disclosure_posture
from apps.api.agents.service import publish_agent
from apps.api.compliance.audit import write_audit
from apps.api.compliance.disclosure import TRUTHFUL_ANSWER_PROMISE
from apps.api.core.auth import client_request_ip, requires
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
    # THE LEGACY BUNDLE, kept on the wire for step 1 of D-163's two-step deprecation:
    # both sentences joined whatever the toggles say. Read it as "the notices this agent
    # HAS", never as "what it says" — `opening_line` below is what it says.
    disclosure_line: str
    # THE SPLIT (D-163). Shown to the client verbatim: they are legally the Principal
    # Entity, so they need to be able to read what their agent announces — and, now that
    # each half is theirs to switch off, to see the two halves separately.
    ai_disclosure_line: str
    ai_disclosure_enabled: bool
    recording_notice_line: str
    recording_notice_enabled: bool
    #: What a caller actually hears first, composed by the server from the two toggles.
    #: Empty string = this agent volunteers neither notice and opens on its script.
    #: Composed here rather than left to the screen because a UI that re-joined the two
    #: sentences itself would be a second implementation of a compliance rule.
    opening_line: str
    #: The one sentence no toggle reaches, in words a client can read. Server-composed for
    #: the same reason the lane table's `why` strings are: a screen that paraphrases this
    #: is a screen that can accidentally promise the opposite.
    truthful_answer_rule: str = TRUTHFUL_ANSWER_PROMISE
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
                "a.disclosure_line, a.engine, a.engine_agent_ref, es.fields, "
                "a.ai_disclosure_line, a.ai_disclosure_enabled, "
                "a.recording_notice_line, a.recording_notice_enabled "
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
            ai_disclosure_line=r[9],
            ai_disclosure_enabled=bool(r[10]),
            recording_notice_line=r[11],
            recording_notice_enabled=bool(r[12]),
            # Through the ONE composer, so the roster, the publish path and the engine
            # cannot disagree about what this agent opens with (D-163).
            opening_line=compose_opening_line(
                DisclosurePosture(
                    ai_disclosure_line=str(r[9]),
                    ai_disclosure_enabled=bool(r[10]),
                    recording_notice_line=str(r[11]),
                    recording_notice_enabled=bool(r[12]),
                )
            ),
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
        ip=client_request_ip(request),
    )
    return PublishOut(agent_id=agent_id, engine_agent_ref=ref, status="live")


class DisclosureIn(BaseModel):
    """Which notices this agent volunteers. `null` on a field leaves it alone.

    Two nullable booleans rather than two endpoints: the pair is one posture, a screen
    with two switches sends whichever one moved, and a PATCH that could only send both
    would make flipping one switch a read-modify-write race against the other.
    """

    model_config = ConfigDict(extra="forbid")

    ai_disclosure_enabled: bool | None = None
    recording_notice_enabled: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> DisclosureIn:
        if self.ai_disclosure_enabled is None and self.recording_notice_enabled is None:
            # A body that names nothing is a client bug, and answering 200 for it would
            # write an audit row describing a decision nobody took.
            raise ValueError("name at least one of ai_disclosure_enabled, recording_notice_enabled")
        return self


class DisclosureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    ai_disclosure_enabled: bool
    recording_notice_enabled: bool
    #: What callers now hear first. Empty = the agent volunteers neither notice.
    opening_line: str
    #: Did the voice platform get the change? False on an agent that is not live yet —
    #: there is nothing on the platform to update, and the first publish carries it.
    engine_synced: bool
    #: The one behaviour these switches do not reach, in the words the API owns.
    truthful_answer_rule: str = TRUTHFUL_ANSWER_PROMISE


@router.patch(
    "/v1/agents/{agent_id}/disclosure",
    response_model=DisclosureOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Switch the AI disclosure and the recording notice on or off (D-163)",
    description=(
        "Each opening notice is separately controllable, per agent, on inbound and "
        "outbound agents alike. A notice switched off means the agent does not VOLUNTEER "
        "that fact at the start of the call.\n\n"
        "It does not change what the agent says when a caller ASKS. Asked whether they "
        "are speaking to a human, the agent says it is an AI assistant; asked whether "
        "the call is recorded, it says yes. That is composed server-side, appended to "
        "every agent's instructions after the script, and verified against the voice "
        "platform on every publish — no script can withdraw it.\n\n"
        "Switching the recording notice off does not stop the call being recorded, and "
        "does not discharge the client's own notice obligation under the DPDP Act; it "
        "moves where that notice is given. Every flip is written to the audit log.\n\n"
        "Applies immediately: a live agent is re-published to the voice platform in the "
        "same transaction, so the screen never claims a posture the platform is not "
        "running."
    ),
)
async def set_disclosure(
    agent_id: UUID,
    payload: DisclosureIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("org:manage")),
) -> DisclosureOut:
    """`org:manage`, which is the CLIENT OWNER's permission — and that is the decision.

    The client is the Principal Entity: the calls are made under their identity and their
    DLT templates, and the disclosure posture is their legal exposure to carry (D-163
    records the regulatory position and the risk the founder accepted). So the switch
    belongs to the person who answers for it. `agents:write` would have been the
    neighbouring choice and is wrong here: it is admin-only, so we would be deciding a
    client's compliance posture for them and being unable to show them the switch.

    Two consequences of `org:manage` being in `MUTATING_PERMISSIONS`, both intended: an
    admin-realm token without `X-Impersonate-Org` is refused by the client verifier, and
    an impersonating operator is refused by D-22's read-only rule. Nobody but the client
    flips these, which is exactly the accountability this decision rests on.

    THE AUDIT ROW NAMES THE TOGGLE AND THE VALUE IN ITS `action`, not in a summary:
    `write_audit` does not persist summaries (BACKEND-PATTERNS §7 — they go to the log
    stream), and "who switched the AI disclosure off, and when" has to survive in the
    hash-chained ledger to be worth anything. One row per toggle that actually moved.

    `write_audit` runs AFTER `set_disclosure_posture`, which reaches the voice platform,
    for `publish`'s reason above: a slow vendor call must not hold the audit row's
    transaction open, and the entry should describe what actually happened.
    """
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    result = await set_disclosure_posture(
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        ai_disclosure_enabled=payload.ai_disclosure_enabled,
        recording_notice_enabled=payload.recording_notice_enabled,
    )
    for field in result.changed:
        await write_audit(
            session,
            # `field` IS the column name and IS the attribute name on the result — one
            # spelling, so a third toggle needs no edit here.
            action=audit_action_for(field, enabled=bool(getattr(result, field))),
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            # The CALLER's address, never the socket peer — behind nginx that is our own
            # edge (`core/auth.client_request_ip`, `scripts/check_audit_ip.py`).
            ip=client_request_ip(request),
            summary={"engine_synced": result.engine_synced},
        )
    return DisclosureOut(
        agent_id=result.agent_id,
        ai_disclosure_enabled=result.ai_disclosure_enabled,
        recording_notice_enabled=result.recording_notice_enabled,
        opening_line=result.opening_line,
        engine_synced=result.engine_synced,
    )


# A/B script testing (ROADMAP M3) lives in `agents/experiment_routes.py` and is mounted
# in `main._mount_routers` with every other router. It was briefly ADOPTED here with
# `router.routes.extend(...)` because the slice that built it could not edit `main.py`;
# that worked, but it made this the one router in the app mounted by a neighbour, and
# two ways to mount a router is the drift CLAUDE.md names even when both work.

__all__ = ["router"]
