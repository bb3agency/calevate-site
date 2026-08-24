"""Client-realm structured call-script builder + AI writing assist (D-21 CONFLICT — see below).

⚠ **CONFLICT FLAGGED, NOT SILENTLY RESOLVED (CLAUDE.md: "flag the conflict, don't silently
pick").** D-21 as reflected in `apps/web/.../agents/[agentId]/page.tsx::ScriptNote` and in
`agents/routes.py`'s header draws the control boundary so that the SCRIPT is authored
admin-realm ("with your account manager"), because a script change regenerates prompt hints
and needs a regression run. This router puts a STRUCTURED script builder on the CLIENT realm
under `org:manage`, on the founder's APPROVED DECISION that the structured builder is the
primary authoring model. It is reconciled with D-21's actual concern rather than overriding
it: every client edit here STAGES (the slow lane, `write_prompt_version`), so nothing a
client authors reaches a live call until an explicit **Apply** — the same two-speed gate
D-21's regression concern is really about. The admin-realm prompt/apply endpoints
(`prompt_routes.py`, `publishing_routes.py`) remain for the account-manager path; this is a
second surface onto the SAME storage and the SAME staging gate, not a second system.

WHY IT IS ONE ROUTER WITH NO SHARED PREFIX. Every path here is client-realm `/v1/agents/...`
and tenant-scoped through `Depends(db)` + `requires(...)` (the principal's own tenant), so a
single prefix fits — unlike `agents/routes.py`, which straddles two realms. Mounted by
`main.py`.

THE AI ASSIST FOLLOWS SUBJECT → GATE → RUN → METER (crm/routes.assist_call's order), because
it spends the founder's Azure rupees and must obey the per-tenant ceiling and the platform
brake exactly as re-summarise does. It reuses `billing/ai_quota` (gate + meter) and
`crm/assist.meter_assist` (the one metering path), so there is one money path, not two.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from calevate_shared.call_script import STANDARD_VARIABLES, CallScript
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import publishing, script_builder
from apps.api.billing.ai_quota import new_assist_ref, require_ai_assist
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers.script_assist import draft_script

log = get_logger(__name__)

router = APIRouter(prefix="/v1/agents/{agent_id}/script", tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]
ScriptReader = Annotated[Principal, Depends(requires("agents:read"))]
# `org:manage` is the client-realm write scope the disclosure and model settings already use
# (`agents/routes.py::set_disclosure`); a script edit is the same class of client-owned
# change under the approved decision, so it shares the permission rather than minting one.
ScriptWriter = Annotated[Principal, Depends(requires("org:manage"))]


class VariableSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str


class ScriptOut(BaseModel):
    """The draft script the builder edits, plus where it stands and the free merge fields."""

    model_config = ConfigDict(extra="forbid")

    script: CallScript
    #: None when the agent has no script yet — the builder opens an empty structured editor.
    version: int | None
    #: True when the loaded version was authored as freeform text; the UI opens raw mode.
    is_freeform: bool
    #: True when a staged draft is waiting to be applied to live calls.
    has_pending: bool
    #: The standard `{{ }}` merge fields every agent gets, for the insert-variable menu.
    standard_variables: list[VariableSuggestion]


class SaveScriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: CallScript
    notes: str | None = Field(default=None, max_length=200)


class SaveScriptOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    #: True = live agent, edit is waiting for Apply. False = draft/paused, applied as written.
    staged: bool


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: CallScript


class PreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The exact engine prompt: the disclosure opening, the compiled script, and the
    #: non-removable platform rules appended last — what the engine actually holds.
    compiled: str


class AssistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=10, max_length=4000)


class AssistOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A drafted script the builder pre-fills — never saved, always the author's to edit.
    script: CallScript
    #: The Sarvam-fallback disclosure (G-6), or None when the preferred model answered.
    disclosure: str | None
    #: Whether this draft was billed (an Azure answer Azure counted). Sarvam is free (D-36).
    metered: bool


_STANDARD_VARIABLES = [
    VariableSuggestion(key=key, label=label) for key, label in STANDARD_VARIABLES
]


@router.get(
    "",
    response_model=ScriptOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Load the agent's draft script for the structured builder",
)
async def get_script(agent_id: UUID, session: Session, _: ScriptReader) -> ScriptOut:
    loaded = await script_builder.load_agent_script(session, agent_id)
    return ScriptOut(
        script=loaded.script,
        version=loaded.version,
        is_freeform=loaded.is_freeform,
        has_pending=loaded.has_pending,
        standard_variables=_STANDARD_VARIABLES,
    )


@router.post(
    "/preview",
    response_model=PreviewOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Compile a (possibly unsaved) script into the exact engine prompt",
)
async def preview_script(
    agent_id: UUID, payload: PreviewIn, session: Session, _: ScriptReader
) -> PreviewOut:
    compiled = await script_builder.compiled_preview(session, agent_id, payload.script)
    return PreviewOut(compiled=compiled)


@router.put(
    "",
    response_model=SaveScriptOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Save the structured script as a new version (staged on a live agent)",
)
async def save_script(
    agent_id: UUID,
    payload: SaveScriptIn,
    session: Session,
    request: Request,
    principal: ScriptWriter,
) -> SaveScriptOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    saved = await script_builder.save_agent_script(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        script=payload.script,
        notes=payload.notes,
        created_by=principal.user_id,
    )
    await write_audit(
        session,
        action="agent.script_saved",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        # Version and a boolean only — a script body embeds client business detail (rule 6).
        summary={"version": saved.version, "staged": saved.staged},
    )
    return SaveScriptOut(version=saved.version, staged=saved.staged)


@router.post(
    "/assist",
    response_model=AssistOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Draft a script from a plain-language business description (AI writing assist)",
)
async def assist_script(
    agent_id: UUID,
    payload: AssistIn,
    session: Session,
    request: Request,
    principal: ScriptWriter,
) -> AssistOut:
    """AI writing assist. SUBJECT → GATE → RUN → METER, the crm/routes.assist_call order.

    The SUBJECT is the client's own business description (tenant-authored config, not
    transcript PII), so there is no transcript to load or redact — the subject is the
    request body, present before the gate. The GATE (`require_ai_assist`) RAISES at the
    ceiling before a token is spent; the RUN drafts through the controlled worker path; the
    METER records the Azure cost (or nothing, for the free Sarvam fallback) in its own
    transaction. Nothing is persisted to the agent — a draft is returned for the author to
    edit and then save through `PUT` above.
    """
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    tenant_id = principal.tenant_id

    # GATE — raises `ai_quota_exceeded` / `ai_paused_platform_wide` before any spend.
    quota = await require_ai_assist(session, tenant_id=tenant_id)

    # RUN — the model call, on the controlled worker path (never a raw handler call).
    ref = new_assist_ref()
    draft = await draft_script(payload.description, quota_exhausted=quota.at_ceiling)

    # METER — a completed run is money spent; record it in its own transaction so a later
    # failure cannot roll back the record of a payment already made (crm/assist §4).
    async with tenant_session(tenant_id) as record_session:
        metered = await crm_assist.meter_assist(
            record_session,
            tenant_id=tenant_id,
            ref=ref,
            result=draft,
            feature=crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT,
        )
        await write_audit(
            record_session,
            action="agent.script_assist",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={"metered": metered.metered, "provider": draft.capability.provider},
        )
    return AssistOut(
        script=draft.script,
        disclosure=draft.capability.disclosure,
        metered=metered.metered,
    )


class ApplyScriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The draft version the author looked at — CAS, so a colleague's later edit is not
    #: applied under this click (publishing.apply_to_live's `expected_version`).
    expected_version: int | None = Field(default=None, ge=1)


class ApplyScriptOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: bool
    live_version: int
    engine_synced: bool


class UndoScriptOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    undone: bool
    discarded_version: int | None
    live_version: int | None


@router.post(
    "/apply",
    response_model=ApplyScriptOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Apply the staged script to live calls",
)
async def apply_script(
    agent_id: UUID,
    payload: ApplyScriptIn,
    session: Session,
    request: Request,
    principal: ScriptWriter,
) -> ApplyScriptOut:
    assert principal.tenant_id is not None
    result = await publishing.apply_to_live(
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        expected_version=payload.expected_version,
    )
    if result.applied:
        await write_audit(
            session,
            action="agent.changes_applied",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={"version": result.live_version, "engine_synced": result.engine_synced},
        )
    return ApplyScriptOut(
        applied=result.applied,
        live_version=result.live_version,
        engine_synced=result.engine_synced,
    )


@router.post(
    "/undo",
    response_model=UndoScriptOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Discard the staged script; the draft returns to what callers hear",
)
async def undo_script(
    agent_id: UUID,
    session: Session,
    request: Request,
    principal: ScriptWriter,
) -> UndoScriptOut:
    assert principal.tenant_id is not None
    result = await publishing.undo_staged(tenant_id=principal.tenant_id, agent_id=agent_id)
    if result.undone:
        await write_audit(
            session,
            action="agent.changes_undone",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={
                "discarded_version": result.discarded_version,
                "version": result.live_version,
            },
        )
    return UndoScriptOut(
        undone=result.undone,
        discarded_version=result.discarded_version,
        live_version=result.live_version,
    )


__all__ = ["router"]
