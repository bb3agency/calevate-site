"""Voice catalog endpoints: clients READ the catalog, admins SET the voice.

That split is D-21's, restated at the top of `agents/routes.py` — "clients CAN see
their agents, but editing [engine-facing config] is admin-only, because [it] needs a
regression run — that routes through us, which is the managed-service moat". A voice
change is squarely that: which voice speaks Telugu well is an EAR TEST, not a spec
fact (BRD §6 R-10, TRD §10.1, OPERATIONS §2 gate 3), so a client picking a voice
unsupervised is exactly the failure D-21 exists to prevent. They can hear what their
agent sounds like; we change it.

NOT mounted in `main.py` — the integrator wires this router in, same as
`agents/prompt_routes.py` and `compliance/export_routes.py`.

⚠ **MOUNT THIS ROUTER BEFORE `agents.routes.router`.** FastAPI matches in declaration
order and `/v1/agents/{agent_id}` happily matches the literal segment `voices`, so the
wrong order turns `GET /v1/agents/voices` into a 422 about `agent_id` not being a UUID.
Verified against the live app, and the same hazard is called out in
`campaigns/routes.py` for `/numbers` and `/templates`. `tests/agent_voice_test.py`
mounts both routers in the correct order so a regression here fails a test, not a demo.

WHY THE TENANT IS NAMED IN THE REQUEST BODY
-------------------------------------------
It looks redundant next to `{agent_id}`, and it is not. D-22 makes admin impersonation
READ-ONLY, and `requires()` enforces that by refusing every `MUTATING_PERMISSIONS`
entry — `agents:write` included — whenever `X-Impersonate-Org` is present. So the two
ways an admin principal could carry a tenant are mutually exclusive with mutating:

- WITHOUT the impersonation header, `Principal.tenant_id` is None (`_load_admin_principal`).
- WITH it, the tenant resolves but every write is 403.

`admin/routes.py` already draws the conclusion for the mutating KB routes (its comment
above `approve_kb`): "an admin reaching a tenant does so by impersonation, and
impersonation is read-only. The tenant is therefore named in the path rather than
inferred from a session, which also makes every approval self-documenting in the audit
log." This endpoint follows that doctrine; the tenant rides in the body only because
the path was specified as `/v1/agents/{agent_id}/voice`. If the integrator prefers the
house style exactly, moving this route under
`/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice` is a prefix change and a
deleted body field — the handler below is otherwise identical.

FINDING, reported rather than copied: `POST /v1/agents/{agent_id}/publish`
(`agents/routes.py`) infers the tenant from `Principal.tenant_id` and is therefore
**un-callable today**. Exercised against the live app: without the impersonation header
it 401s (its `Depends(db)` resolves through `current_any`, which falls through to the
CLIENT verifier and rejects an admin token), and with the header it 403s on
"Impersonation is read-only". Its `assert principal.tenant_id is not None` is
unreachable. Not fixed here — that file is out of scope — but this router does not
reproduce the pattern.

WHAT THIS ENDPOINT DOES *NOT* DO
--------------------------------
It does not touch the engine. Checked, not assumed: `agents/service.py::publish_agent`
re-reads `a.tts_voice`/`a.tts_provider` from the row inside `_load_agent`, folds them
into `ModelConfig` in `_to_config`, and only then calls `engine.update_agent(...)`. So
a live agent keeps speaking in its OLD voice until someone publishes again — at which
point the new voice is picked up with no extra step. The response says so in a field
(`republish_required`) rather than in prose nobody reads.

That is a deliberate divergence from `agents/prompts.py`, which republishes a LIVE
agent inside the same transaction on the grounds that "a prompt change that only lands
in our DB is a lie on the admin screen". The same argument applies to a voice, but the
consequence does not: republishing a prompt changes what the agent SAYS, which the
operator just read and approved, whereas republishing a voice changes what a live
client's phone line SOUNDS LIKE, and the docs make that an ear test we have not run
(pilot gate 3). Silently re-voicing a running agent is not a safe default. If the
integrator wants auto-republish for parity with prompts, that is a decision-log entry
(ROADMAP §6) and two lines here, not a quiet change.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.voices import CATALOG, Voice, get_voice, voice_ids
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

# No prefix: the two paths differ below `/v1/agents` (a collection of voices vs one
# agent's voice), and a shared prefix would only hide that.
router = APIRouter(tags=["agents"])

# `Annotated` aliases rather than `Depends()` defaults: this file is `voice_routes.py`,
# not `routes.py`, so it sits outside the B008 per-file ignore in pyproject — the same
# situation, and the same resolution, as `prompt_routes.py` and `export_routes.py`.
CatalogReader = Annotated[Principal, Depends(requires("agents:read"))]
VoiceSetter = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
# Reads the tenant DIRECTORY cross-tenant; the audit row is written on it. The actual
# agent write happens under `tenant_session`, in that tenant's own RLS scope.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetVoiceIn(Strict):
    """`extra="forbid"` so a caller cannot smuggle a second config string (an llm_model,
    a tts_provider) into a request whose whole point is one curated choice."""

    # See the module docstring: an admin principal has no tenant of its own, and the
    # one way it could get one (impersonation) is refused for mutations by D-22.
    tenant_id: UUID
    # Bounded before it is looked up, so a megabyte of junk is a validation error
    # rather than a dictionary probe. Membership in the catalog is the real check.
    voice_id: str = Field(min_length=1, max_length=64)


class SetVoiceOut(Strict):
    agent_id: UUID
    voice: Voice
    agent_status: str
    # True when the agent already exists on the engine (`engine_agent_ref` is set).
    published: bool
    # Always False: this endpoint writes our row and nothing else. Stated as a field so
    # a UI cannot accidentally imply otherwise.
    engine_synced: bool
    # == published. The client's callers hear the OLD voice until a republish.
    republish_required: bool
    next_step: str


@router.get(
    "/v1/agents/voices",
    response_model=list[Voice],
    openapi_extra=permission_meta("agents:read"),
    summary="The voices an agent may speak in (client-readable; D-36's premium/value ladder)",
)
async def list_voices(_: CatalogReader) -> list[Voice]:
    """Static data, deliberately: no DB, no engine call, no tenant scoping.

    Client-realm readable on purpose — a client is legally the Principal Entity and
    should be able to see what their own agent sounds like, exactly as they can read
    its disclosure line (`AgentOut.disclosure_line`). `requires()` defaults to
    `realm="any"`, so an admin (including one impersonating, since this is a read) gets
    the same list — one catalog, no realm-specific truth.

    Entries carry `verified: false` until the Bolna pilot confirms each string is
    selectable (OPERATIONS §2 gate 3); render that, do not hide it.
    """
    return list(CATALOG)


@router.patch(
    "/v1/agents/{agent_id}/voice",
    response_model=SetVoiceOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Set an agent's voice from the catalog (admin realm, D-21)",
    description=(
        "Writes `agents.tts_voice` (and the matching `tts_provider`) and audits it. "
        "It does NOT reach the voice engine: `publish_agent` re-reads both columns, so "
        "a live agent keeps its old voice until the next publish — see "
        "`republish_required` in the response. An id outside the catalog is refused "
        "with `unknown_voice`."
    ),
)
async def set_agent_voice(
    agent_id: UUID,
    payload: SetVoiceIn,
    session: AdminSession,
    request: Request,
    principal: VoiceSetter,
) -> SetVoiceOut:
    """Catalog check first, then the row, then the audit entry.

    Order matters: an unknown id must never reach the UPDATE. The whole reason this
    module exists is that `agents.tts_voice` is free text whose next reader is a vendor
    API — a typo that gets stored looks saved, publishes cleanly, and surfaces as a
    broken call on a client's line. Refusing it here costs a dictionary lookup.

    `tts_provider` is written alongside the voice because the catalog knows it and the
    pair is only meaningful together: the adapter sends `synthesizer.provider` and
    `synthesizer.provider_config.voice` as one object, and the onboarding wizard leaves
    both NULL, so setting the voice alone would produce a half-configured synthesizer.
    """
    voice = get_voice(payload.voice_id)
    if voice is None:
        raise ProblemError(
            kind="business_rule",
            code="unknown_voice",
            title="Unknown voice",
            detail="That voice is not in the catalog, so it cannot be set on an agent.",
            remediation=("Pick one of: " + ", ".join(voice_ids()) + " (GET /v1/agents/voices)."),
            fields=[
                {
                    "field": "voice_id",
                    "rule": "not_in_catalog",
                    "message": "Not a supported voice.",
                }
            ],
        )

    # The tenant's own RLS scope. An agent belonging to a different tenant is invisible
    # here, so the UPDATE matches zero rows and the answer is 404 — under RLS "not
    # found" and "belongs to someone else" are deliberately the same answer.
    async with tenant_session(payload.tenant_id) as scoped:
        row = (
            await scoped.execute(
                text(
                    "UPDATE agents SET tts_voice = :voice, tts_provider = :provider, "
                    "updated_at = now() WHERE id = :aid AND deleted_at IS NULL "
                    "RETURNING status, engine_agent_ref"
                ),
                {"voice": voice.id, "provider": voice.provider, "aid": agent_id},
            )
        ).first()
        if row is None:
            raise ProblemError.not_found("Agent")
        status, engine_ref = str(row[0]), row[1]

    published = bool(engine_ref)
    await write_audit(
        session,
        action="agent.voice_set",
        actor=principal,
        tenant_id=payload.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=request.client.host if request.client else None,
        # Catalog ids and a boolean. No prompt text, no client detail (hard rule 6).
        summary={
            "voice_id": voice.id,
            "tier": voice.tier,
            "tts_model": voice.tts_model,
            "republish_required": published,
        },
    )
    return SetVoiceOut(
        agent_id=agent_id,
        voice=voice,
        agent_status=status,
        published=published,
        engine_synced=False,
        republish_required=published,
        next_step=(
            "Publish the agent to send this voice to the engine — until then callers "
            "hear the previous voice."
            if published
            else "The agent is not on the engine yet; publishing it will use this voice."
        ),
    )


__all__ = ["SetVoiceIn", "SetVoiceOut", "router"]
