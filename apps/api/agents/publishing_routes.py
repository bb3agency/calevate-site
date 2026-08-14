"""Two-speed publishing + the cost-runaway guard, as endpoints (SURFACES §2b).

Three questions and two buttons:

    GET   /v1/agents/lanes                                        what applies when
    GET   /v1/agents/{agent_id}/pending                           what is pending, what it costs,
                                                                  which voice is configured vs live
    POST  /v1/admin/tenants/{tid}/agents/{aid}/apply              "Apply to live calls"
    POST  /v1/admin/tenants/{tid}/agents/{aid}/undo               "Undo"
    PATCH /v1/admin/tenants/{tid}/agents/{aid}/call-cap           the max call length

WHY THE AGENT'S VOICE IS READ HERE AND NOT ON `AgentOut`
--------------------------------------------------------
`PATCH /v1/agents/{id}/voice` shipped without any read, so the admin picker could set a
voice and never show one. The obvious fix — put `tts_voice` on `AgentOut` — was
rejected, and the reason is the feature itself rather than tidiness:

- **`AgentOut` has nowhere to put the second answer.** A voice is two facts, configured
  and live, because `set_agent_voice` writes our row without touching the engine. A
  single `tts_voice` field on the roster row would render as "the voice" and be wrong on
  exactly the agents where it matters — the published ones with an unpublished change.
  Adding BOTH to `AgentOut` would move two-speed publishing onto a read that knows
  nothing else about it, giving the concept two homes. This endpoint is already the one
  that answers "what is configured, what is live, what does it take to close the gap"
  for the script and the call cap; the voice is the third instance of one question, not
  a new one.
- **`AgentOut` is the ROSTER, and it is on hot paths.** It backs the client agents
  screen and the agent pickers on Leads, Campaigns, Knowledge and Lead sources, and
  `get_agent` is implemented as "list them all and filter", so every field added there
  is paid per agent by five screens that want a name and an id. This read is per agent
  and already fetched by the one screen that sets a voice.
- **A dedicated ADMIN read was rejected too**, for a reason that outranks both: the
  voice is not admin-only information. `list_voices` is client-realm readable on the
  stated grounds that a client "is legally the Principal Entity and should be able to
  see what their own agent sounds like", and D-36's ladder is a PRICE ladder — premium
  and value bill at different rates (`plans.overage_rate` vs `overage_rate_value`,
  §2b's "honest degraded-tier billing"), and `usage_events.meta.tts_tier` already
  records which rung a call ran on. A client billed by rung must be able to read the
  rung. What stays admin-only is the WRITE, which is D-21 and unchanged.

WHY THE READS ARE CLIENT-REALM AND THE WRITES ARE NOT
-----------------------------------------------------
The two reads ask for `agents:read`, deliberately and not by accident of copying: they
are the views a client opens when an edit has not taken effect and a support person
opens while looking at that client's screen. D-22 makes impersonation READ-ONLY by
refusing every `MUTATING_PERMISSIONS` entry, so a GET gated on `agents:write` is
invisible in exactly the moment support is needed —
`tests/impersonation_reads_test.py` exists because that mistake has now been made
three times in three modules. It is not repeated here.

The mutations stay admin-realm with the tenant named in the path, matching
`prompt_routes.py` and `voice_routes.py`, for a reason narrower than "D-21 says so":
**you cannot apply what you cannot write.** The script edit an Apply publishes is
minted by `POST /v1/admin/tenants/{tid}/agents/{aid}/prompt`, which is admin-realm; an
Apply button in the client realm would let a client publish a draft they had no way to
author. When self-serve (D-34) puts script editing in the client's hands, this router
moves with it — that is a decision-log entry (ROADMAP §6), not a quiet permission
swap. The tenant rides in the path for the reason `prompt_routes.py` states at length:
an admin principal has no tenant of its own, and the one way it could get one is
read-only.

⚠ **MOUNT THIS ROUTER BEFORE `agents.routes.router`.** FastAPI matches in declaration
order and `/v1/agents/{agent_id}` happily matches the literal segment `lanes`, so the
wrong order turns `GET /v1/agents/lanes` into a 422 about `agent_id` not being a UUID.
Same hazard, same fix, as `voice_routes.py`'s `/v1/agents/voices`;
`tests/two_speed_publishing_routes_test.py` mounts both in the correct order so a
regression fails a test rather than a demo.

NOT mounted in `main.py` — the integrator wires this router in, exactly as with
`agents/prompt_routes.py`, `agents/voice_routes.py` and `compliance/export_routes.py`.
The OpenAPI snapshot and the generated TS client are therefore unchanged by this wave
and stay fresh; they go stale on the commit that mounts it.

MONEY AND PII
-------------
`worst_case_call_cost_inr` is `Decimal`, NUMERIC INR, never a float (hard rule 7), and
it is `null` rather than `0` when the tenant's plan quotes no rate — "we cannot tell
you" is not "it is free". No response here carries a prompt body or any string derived
from one: pending changes are described by version NUMBERS (hard rule 6), which is
also all that reaches the audit log.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import publishing
from apps.api.agents.models import CALL_CAP_DEFAULT_S, CALL_CAP_MAX_S, CALL_CAP_MIN_S
from apps.api.agents.voices import Voice
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.rbac import permission_meta

# No prefix — the reads live in the client realm's `/v1/agents` space and the
# mutations under `/v1/admin/tenants/{tenant_id}/...`, so a shared prefix could only
# describe one of them. Same resolution, and the same reason, as `voice_routes.py`.
router = APIRouter(tags=["agents"])

# `Annotated` aliases rather than `Depends()` defaults: this file is not `routes.py`,
# so it sits outside the B008 per-file ignore in pyproject.
PublishingReader = Annotated[Principal, Depends(requires("agents:read"))]
PublishingWriter = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
# Reads the tenant DIRECTORY cross-tenant so the audit row can be written on it; it
# unlocks no agent rows. Every mutation below does its work inside the tenant's own
# RLS scope, opened by the `agents.publishing` function it calls.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LaneOut(Strict):
    field: str
    lane: str
    precedence: int
    why: str


class LanesOut(Strict):
    """The split, as data. A UI that paraphrases this is how "voice applies
    immediately" becomes a support ticket."""

    precedence_rule: str
    lanes: list[LaneOut]
    call_cap_default_s: int
    call_cap_min_s: int
    call_cap_max_s: int


class PendingChangeOut(Strict):
    field: str
    lane: str
    staged_version: int
    live_version: int | None
    staged_at: datetime
    headline: str
    why: str


class AgentVoiceOut(Strict):
    """One voice at one moment: the stored id, and the catalogue entry when we know it.

    `catalog` is null for an id outside `GET /v1/agents/voices` — a row set before the
    catalogue existed, or an entry retired since. `voice_id` is still populated, so a UI
    can name what it cannot describe rather than rendering an agent with a retired voice
    as one with no voice at all.
    """

    voice_id: str
    provider: str | None
    catalog: Voice | None


class VoiceStateOut(Strict):
    """The voice CONFIGURED on the agent and the voice the engine was last SENT.

    Two fields because they are two facts. `PATCH /v1/agents/{id}/voice` writes our row
    and stops there, so a live agent keeps its old voice until the next publish — one
    value labelled "the voice" would be a claim about a client's phone line that nobody
    checked.

    `live` is null when nothing is recorded as sent, which reads two ways and is
    disambiguated by `PendingOut.published`: an unpublished agent has nothing live, and
    a published one was published before the mirror existed (or with no voice set). Both
    resolve to `republish_required` when a voice is configured, because a sync we cannot
    prove is not a sync.
    """

    configured: AgentVoiceOut | None
    live: AgentVoiceOut | None
    republish_required: bool
    headline: str


class PendingOut(Strict):
    agent_id: UUID
    agent_status: str
    published: bool
    has_pending: bool
    pending: list[PendingChangeOut]
    effective_call_cap_s: int
    call_cap_is_platform_default: bool
    # NUMERIC INR. Null when the plan quotes no rate — not zero.
    worst_case_call_cost_inr: Decimal | None
    # Deliberately NOT an entry in `pending`: that list is what Apply and Undo act on,
    # every member of it names a `prompt_versions` number, and neither button clears a
    # voice divergence on its own — a publish does. See `publishing.PendingState.voice`.
    voice: VoiceStateOut
    precedence_rule: str


class ApplyIn(Strict):
    """`expected_version` is the CAS token (BACKEND-PATTERNS §5): the staged version
    the operator actually looked at. Optional, because a caller with no screen has
    nothing to be stale about — but a UI that omits it is choosing last-write-wins."""

    expected_version: int | None = Field(default=None, ge=1)


class ApplyOut(Strict):
    agent_id: UUID
    # False = there was nothing to apply. Still 200: a double-clicked button is the
    # same intent, already satisfied, and a 409 would teach operators to fear the
    # button. `live_version` tells the caller what is running either way.
    applied: bool
    live_version: int
    engine_synced: bool


class UndoOut(Strict):
    agent_id: UUID
    undone: bool
    discarded_version: int | None
    live_version: int | None


class SetCallCapIn(Strict):
    """`null` clears the override and restores the platform default. It is NOT
    unlimited — there is no way to express an uncapped agent, by design."""

    max_call_duration_s: int | None = Field(default=None, ge=CALL_CAP_MIN_S, le=CALL_CAP_MAX_S)


class CallCapOut(Strict):
    agent_id: UUID
    max_call_duration_s: int | None
    effective_call_cap_s: int
    is_platform_default: bool
    engine_synced: bool
    worst_case_call_cost_inr: Decimal | None


@router.get(
    "/v1/agents/lanes",
    response_model=LanesOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Which agent settings apply immediately and which wait for Apply (§2b)",
)
async def list_lanes(_: PublishingReader) -> LanesOut:
    """Static data: no DB, no engine, no tenant scoping — the split is the same for
    every client, which is the point of publishing it rather than describing it."""
    return LanesOut(
        precedence_rule=publishing.PRECEDENCE_RULE,
        lanes=[
            LaneOut(field=e.field, lane=e.lane, precedence=e.precedence, why=e.why)
            for e in publishing.LANES
        ],
        call_cap_default_s=CALL_CAP_DEFAULT_S,
        call_cap_min_s=CALL_CAP_MIN_S,
        call_cap_max_s=CALL_CAP_MAX_S,
    )


@router.get(
    "/v1/agents/{agent_id}/pending",
    response_model=PendingOut,
    openapi_extra=permission_meta("agents:read"),
    summary="What is staged but not live, what one capped call costs, and which voice is live",
    description=(
        "Backs the unsaved-changes banner and the voice picker. `agents:read`, not "
        "`agents:write`: this is the view that explains why an edit has not taken "
        "effect, so it must be readable by someone who may only look (D-22).\n\n"
        "`voice.configured` is what `PATCH /v1/agents/{agent_id}/voice` wrote; "
        "`voice.live` is what the engine was last sent. They differ until a publish, "
        "which is what `voice.republish_required` reports. A null `voice.live` on a "
        "published agent means we have no record of what it is holding — read it with "
        "`published`, and never as 'in sync'."
    ),
)
async def pending(agent_id: UUID, principal: PublishingReader) -> PendingOut:
    assert principal.tenant_id is not None  # `requires()` resolves a tenant for reads
    state = await publishing.pending_state_for(tenant_id=principal.tenant_id, agent_id=agent_id)
    return _render(state)


def _render_voice(voice: publishing.AgentVoice | None) -> AgentVoiceOut | None:
    if voice is None:
        return None
    return AgentVoiceOut(voice_id=voice.voice_id, provider=voice.provider, catalog=voice.catalog)


def _render(state: publishing.PendingState) -> PendingOut:
    return PendingOut(
        agent_id=state.agent_id,
        agent_status=state.agent_status,
        published=state.published,
        has_pending=state.has_pending,
        pending=[
            PendingChangeOut(
                field=c.field,
                lane=c.lane,
                staged_version=c.staged_version,
                live_version=c.live_version,
                staged_at=c.staged_at,
                headline=c.headline,
                why=c.why,
            )
            for c in state.pending
        ],
        effective_call_cap_s=state.effective_call_cap_s,
        call_cap_is_platform_default=state.call_cap_is_platform_default,
        worst_case_call_cost_inr=state.worst_case_call_cost_inr,
        voice=VoiceStateOut(
            configured=_render_voice(state.voice.configured),
            live=_render_voice(state.voice.live),
            republish_required=state.voice.republish_required,
            headline=state.voice.headline,
        ),
        precedence_rule=state.precedence_rule,
    )


@router.post(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/apply",
    response_model=ApplyOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Apply the staged script to live calls (admin realm, D-21/D-22)",
    tags=["admin"],
)
async def apply(
    tenant_id: UUID,
    agent_id: UUID,
    payload: ApplyIn,
    session: AdminSession,
    request: Request,
    principal: PublishingWriter,
) -> ApplyOut:
    """The explicit publish §2b asks for. Audited with version NUMBERS only.

    `apply_to_live` opens the tenant's own RLS scope and reaches the engine, so it
    stays OUTSIDE the audit session's transaction: a slow vendor call must not hold
    the audit row's transaction open, and the audit entry should describe what
    actually happened.
    """
    result = await publishing.apply_to_live(
        tenant_id=tenant_id, agent_id=agent_id, expected_version=payload.expected_version
    )
    if result.applied:
        await write_audit(
            session,
            action="agent.changes_applied",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=request.client.host if request.client else None,
            # Numbers and a boolean. A prompt body embeds client business detail
            # (hard rule 6) and never enters the audit log.
            summary={"version": result.live_version, "engine_synced": result.engine_synced},
        )
    return ApplyOut(
        agent_id=result.agent_id,
        applied=result.applied,
        live_version=result.live_version,
        engine_synced=result.engine_synced,
    )


@router.post(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/undo",
    response_model=UndoOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Discard the staged script; the draft returns to what callers hear",
    description=(
        "Moves a POINTER. No `prompt_versions` row is written or deleted, so the "
        "discarded version stays readable in the history and its number is never "
        "reused."
    ),
    tags=["admin"],
)
async def undo(
    tenant_id: UUID,
    agent_id: UUID,
    session: AdminSession,
    request: Request,
    principal: PublishingWriter,
) -> UndoOut:
    result = await publishing.undo_staged(tenant_id=tenant_id, agent_id=agent_id)
    if result.undone:
        await write_audit(
            session,
            action="agent.changes_undone",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=request.client.host if request.client else None,
            summary={
                "discarded_version": result.discarded_version,
                "version": result.live_version,
            },
        )
    return UndoOut(
        agent_id=result.agent_id,
        undone=result.undone,
        discarded_version=result.discarded_version,
        live_version=result.live_version,
    )


@router.patch(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-cap",
    response_model=CallCapOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Set the per-agent max call length — the cost-runaway guard (§2b:107)",
    description=(
        "Applies immediately: a live agent is re-published in the same transaction, "
        "so a cap that only lands in our table cannot be displayed as if it were "
        "enforced. `null` restores the platform default; it never means unlimited. "
        "Out-of-range values are refused with `call_cap_out_of_range`."
    ),
    tags=["admin"],
)
async def set_call_cap(
    tenant_id: UUID,
    agent_id: UUID,
    payload: SetCallCapIn,
    session: AdminSession,
    request: Request,
    principal: PublishingWriter,
) -> CallCapOut:
    result = await publishing.set_call_cap(
        tenant_id=tenant_id,
        agent_id=agent_id,
        max_call_duration_s=payload.max_call_duration_s,
    )
    await write_audit(
        session,
        action="agent.call_cap_set",
        actor=principal,
        tenant_id=tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=request.client.host if request.client else None,
        summary={
            "cap_s": result.effective_call_cap_s,
            "is_platform_default": result.is_platform_default,
            "engine_synced": result.engine_synced,
        },
    )
    return CallCapOut(
        agent_id=result.agent_id,
        max_call_duration_s=result.max_call_duration_s,
        effective_call_cap_s=result.effective_call_cap_s,
        is_platform_default=result.is_platform_default,
        engine_synced=result.engine_synced,
        worst_case_call_cost_inr=result.worst_case_call_cost_inr,
    )


__all__ = [
    "AgentVoiceOut",
    "ApplyIn",
    "CallCapOut",
    "PendingOut",
    "SetCallCapIn",
    "VoiceStateOut",
    "router",
]
