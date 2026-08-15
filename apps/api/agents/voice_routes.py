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

WHERE THE CURRENT VOICE IS READ
-------------------------------
Not here. `GET /v1/agents/{agent_id}/pending` (`agents/publishing_routes.py`) carries
`voice.configured` and `voice.live` — the voice on the row and the voice the engine was
last sent — because that endpoint is already the one answering configured-vs-live for
the script and the call cap, and a voice is the third instance of that question rather
than a new one. The argument, including why `AgentOut` was the wrong home and why the
answer is client-readable at all, is in that module's docstring. This file stays the
WRITE, which is admin-only per D-21.

WHAT THIS ENDPOINT DOES *NOT* DO
--------------------------------
It does not touch the engine. Checked, not assumed: `agents/service.py::publish_agent`
re-reads `a.tts_voice`/`a.tts_provider` from the row inside `_load_agent`, folds them
into `ModelConfig` in `_to_config`, and only then calls `engine.update_agent(...)`. So
a live agent keeps speaking in its OLD voice until someone publishes again — at which
point the new voice is picked up with no extra step. The response says so in a field
(`republish_required`) rather than in prose nobody reads.

`publish_agent` now also RECORDS what it sent, in `agents.live_tts_voice` (migration
c8b3f14e7a29). That is what makes `republish_required` a measurement rather than an
assumption: it used to be `== published`, which reported a needed republish even when
the operator re-selected the voice the engine was already running, because nothing in
the schema could tell those apart.

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

from apps.api.agents.voices import (
    Voice,
    VoiceSelectionCapability,
    get_voice,
    voice_ids,
    voice_selection_capability,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import engine_lacks

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
    # What the engine was last SENT (`agents.live_tts_voice`, written by
    # `publish_agent`), or null when nothing is recorded — an agent that was never
    # published, or one published before migration c8b3f14e7a29. Returned so the write
    # answers the same two questions the read does: a response that named only the voice
    # it just stored would be the "one number called the voice" this column exists to
    # stop.
    live_voice_id: str | None
    # Published AND the stored voice differs from the one the engine holds. It used to
    # be `== published`, which assumed every write moved the voice — so re-selecting the
    # voice already running reported a republish nobody needed, and there was no way to
    # tell the two apart. A null `live_voice_id` counts as different: a sync we cannot
    # prove is not a sync.
    republish_required: bool
    next_step: str


class VoiceCatalogueOut(Strict):
    """The catalog AND whether it may be chosen from (D-93).

    IT USED TO BE A BARE `list[Voice]`, and that shape cannot express the one answer this
    endpoint now has to be able to give. On an engine that supplies its own voices the
    honest response is "no selection here, and that is normal" — and a bare list has
    exactly one way to say it, `[]`, which the console reads as "this agent has no voices
    available" and renders as a claim about the product. (The console's own comment in
    `VoicePanel` says exactly that, which is how the shape was found to be wrong.) An
    empty list and a closed choice are different facts, and the envelope keeps them
    different.

    The same argument `ExecutionListing` makes: the caller needs the rows AND the verdict
    about them, and inferring the verdict from the length of the rows is the bug.

    NO FIELD HERE HAS A DEFAULT. A Pydantic field with a default is OPTIONAL in the
    generated TypeScript, and every one of these is a field the console must trust: a
    `selectable` that can arrive undefined would be read as falsy and hide the picker on
    a perfectly capable engine.
    """

    #: Who chooses the TTS leg on this deployment's engine — `ours` or `engine`.
    control: str
    #: True when a voice may be set on an agent here. When False, `voices` is empty
    #: because there is nothing to offer, NOT because the catalog failed to load.
    selectable: bool
    voices: list[Voice]
    #: One sentence a UI prints verbatim. Always present, so a surface never has to
    #: compose the explanation out of the two fields above and get the tone wrong — the
    #: closed case is a product fact, not an error, and it should not read like one.
    note: str


def _catalogue_note(capability: VoiceSelectionCapability) -> str:
    if capability.available:
        return (
            "Pick the voice this agent speaks in. Entries marked unverified have not yet "
            "been confirmed on the voice platform."
        )
    return (
        "The voice platform in use supplies its own voices, so a voice cannot be chosen "
        "here. Nothing is wrong with this agent."
    )


@router.get(
    "/v1/agents/voices",
    response_model=VoiceCatalogueOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The voices an agent may speak in (client-readable; D-36's premium/value ladder)",
)
async def list_voices(_: CatalogReader) -> VoiceCatalogueOut:
    """Static data plus one capability read: no DB, no network, no tenant scoping.

    Client-realm readable on purpose — a client is legally the Principal Entity and
    should be able to see what their own agent sounds like, exactly as they can read
    its disclosure line (`AgentOut.disclosure_line`). `requires()` defaults to
    `realm="any"`, so an admin (including one impersonating, since this is a read) gets
    the same answer — one catalog, no realm-specific truth.

    Entries carry `verified: false` until the Bolna pilot confirms each string is
    selectable (OPERATIONS §2 gate 3); render that, do not hide it.

    The capability read is the SAME selector `set_agent_voice` uses, and that is the whole
    point: this endpoint is what the picker is built from, so if the two could disagree
    the console would offer precisely the choice the write refuses.
    """
    capability = voice_selection_capability()
    return VoiceCatalogueOut(
        control=capability.control,
        selectable=capability.available,
        voices=list(capability.voices),
        note=_catalogue_note(capability),
    )


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

    THE CAPABILITY CHECK COMES FIRST, before even the catalog lookup (D-93). On an engine
    that supplies its own voices there is no id that would be correct, so refusing with
    `unknown_voice` would send an operator hunting for the right string forever. It is
    also a check the picker already made — `GET /v1/agents/voices` answers
    `selectable: false` — and this is the backstop that makes the picker's answer
    trustworthy rather than decorative: a screen built from a stale schema, a script, or
    a curl still cannot write a voice the engine will silently ignore.
    """
    capability = voice_selection_capability()
    if not capability.available:
        raise engine_lacks("tts", engine=get_settings().engine)

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
                    # `live_tts_voice` is NOT written here — that is the whole point.
                    # It records what `publish_agent` handed the engine, and this
                    # endpoint does not reach the engine. Returned so the response can
                    # say what callers are hearing rather than assume it moved.
                    "RETURNING status, engine_agent_ref, live_tts_voice"
                ),
                {"voice": voice.id, "provider": voice.provider, "aid": agent_id},
            )
        ).first()
        if row is None:
            raise ProblemError.not_found("Agent")
        status, engine_ref, live_voice_id = str(row[0]), row[1], row[2]

    published = bool(engine_ref)
    # Exact, not assumed. `live_voice_id` is null for an agent published before the
    # mirror existed, and null != voice.id, so that case still asks for a republish —
    # the safe direction.
    republish_required = published and live_voice_id != voice.id
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
            "republish_required": republish_required,
        },
    )
    return SetVoiceOut(
        agent_id=agent_id,
        voice=voice,
        agent_status=status,
        published=published,
        engine_synced=False,
        live_voice_id=live_voice_id,
        republish_required=republish_required,
        next_step=_next_step(published=published, republish_required=republish_required),
    )


def _next_step(*, published: bool, republish_required: bool) -> str:
    """What the operator does now, in one sentence a UI prints verbatim.

    Three answers rather than two: an agent already speaking the voice that was just
    selected needs NOTHING, and telling that operator to publish would send them to
    re-push a configuration the engine already holds — a pointless engine call, and a
    screen that cries wolf about a divergence stops being read when there is one.
    """
    if not published:
        return "The agent is not on the engine yet; publishing it will use this voice."
    if not republish_required:
        return (
            "Callers already hear this voice — the engine is holding it, so there is "
            "nothing to publish."
        )
    return (
        "Publish the agent to send this voice to the engine — until then callers "
        "hear the previous voice."
    )


__all__ = ["SetVoiceIn", "SetVoiceOut", "router"]
