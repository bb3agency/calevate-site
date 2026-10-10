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

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from calevate_shared.call_script import (
    MAX_SCRIPT_STAGES,
    MAX_STAGE_BRANCHES,
    MAX_STAGE_COLLECT,
    SCRIPT_SCHEMA_VERSION,
    SOUNDS_LIKE_MAX,
    SPECIAL_TARGETS,
    STAGE_DETAIL_MAX,
    STAGE_TITLE_MAX,
    STANDARD_VARIABLES,
    CallScript,
    ExampleLine,
    unplaced_lines,
    upgrade_to_v2,
)
from calevate_shared.spoken_style import example_exchange, style_for
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import publishing, script_builder, test_conversations
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, require_ai_assist
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.workers.script_assist import (
    CONVERT_INSTRUCTION,
    OWNER_QUESTIONS,
    ScriptBrief,
    draft_script,
)

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


class CollectFieldOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    reason: str
    required: bool


class ScriptLimitsOut(BaseModel):
    """The builder's limits on this deployment's engine (D-714)."""

    model_config = ConfigDict(extra="forbid")

    max_sections: int
    section_title_max: int
    section_detail_max: int
    sounds_like_max: int
    max_branches: int
    max_collect: int
    #: The engine's ceiling on the composed instructions, or null where there is none.
    instructions_limit: int | None
    #: Sections go to the engine's own step list (ThinnestAI) rather than the text.
    native_steps: bool
    #: Branch targets that are not a section.
    special_targets: list[str]


class DraftOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: CallScript
    saved_at: datetime


class ScriptContextOut(BaseModel):
    """What the builder shows beside the script and does not edit there."""

    model_config = ConfigDict(extra="forbid")

    #: The details the agent asks for, from its extraction schema (edited on its own screen).
    collect: list[CollectFieldOut]
    #: Can this account keep a call back right now? False on a free trial, where the agent
    #: never offers one whatever the script says (founder decision 1, 10 Oct 2026).
    call_backs_available: bool
    #: Is hand-over to a person switched on for this agent (who is on duty decides the rest)?
    hand_over_enabled: bool
    direction: str
    language: str
    #: The spoken register the agent uses for its main language, by name, when we have one.
    register_name: str | None
    #: True while that language's register wording and examples await a native speaker.
    register_needs_review: bool
    business_type: str
    limits: ScriptLimitsOut


class ScriptOut(BaseModel):
    """The draft script the builder edits, plus where it stands and the free merge fields.

    `script` is always in the current sections: a script saved in the older format is shown
    converted (`upgrade_to_v2`) and stays as it was stored until it is saved again.
    """

    model_config = ConfigDict(extra="forbid")

    script: CallScript
    #: The format the draft is STORED in (1 or 2), or null when there is no script yet.
    stored_schema_version: int | None = None
    context: ScriptContextOut | None = None
    #: The autosaved working copy, when one is unpublished; the builder edits it in place of
    #: `script`, and callers keep hearing the live version until it is put live.
    draft: DraftOut | None = None
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
    #: The draft version this edit started from (null: the agent had no script). When sent,
    #: the save is refused with `script_changed_elsewhere` if the draft has moved since, so
    #: a builder holding an older copy can never save over a newer version. Left out, the
    #: save is unconditional, as before.
    expected_version: int | None = Field(default=None, ge=1)


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
    #: non-removable platform rules appended last — what the engine actually holds — then,
    #: on an engine with its own step list, the stages as sent there.
    compiled: str
    #: Characters of the instructions text and the engine's ceiling on it (null: none), so
    #: the builder can show the budget as the owner types. Publishing over it is refused.
    instructions_chars: int = 0
    instructions_limit: int | None = None
    #: Stages sent as the engine's own step list (0 where they stay in the text).
    native_steps: int = 0


class AssistIn(BaseModel):
    """The owner's words. Either the five short answers (keys of `OWNER_QUESTIONS`), a
    free description, or both; at least ten characters in all."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(default="", max_length=4000)
    answers: dict[str, str] = Field(default_factory=dict, max_length=len(OWNER_QUESTIONS))
    #: The editor's working copy. With `change`, the answer is this script with only that
    #: change made and every section id kept; nothing is saved.
    current: CallScript | None = None
    #: The owner's request, e.g. "make the push-back answer warmer".
    change: str = Field(default="", max_length=600)

    def has_enough(self) -> bool:
        written = (
            self.description.strip()
            + self.change.strip()
            + "".join(v.strip() for k, v in self.answers.items() if k in OWNER_QUESTIONS)
        )
        return len(written) >= 10


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
    context = await _context(session, agent_id)
    script = upgrade_to_v2(loaded.script)
    if (
        (loaded.version is None or loaded.script.schema_version == 1)
        and not script.is_raw
        and not script.example_exchange
        and (seed := example_exchange(context.language, context.business_type))
    ):
        # A new or older-format script opens with the example call for its language and
        # business type, marked for review; nothing is stored until the owner saves. A
        # current-format script the owner emptied is left empty.
        script = script.model_copy(
            update={
                "schema_version": SCRIPT_SCHEMA_VERSION,
                "example_exchange": [ExampleLine(speaker=t.speaker, text=t.text) for t in seed],
                "example_needs_review": True,
            }
        )
    draft = await script_builder.read_draft(session, agent_id)
    return ScriptOut(
        script=script,
        draft=DraftOut(script=draft.script, saved_at=draft.saved_at) if draft else None,
        stored_schema_version=(
            loaded.script.schema_version if loaded.version is not None else None
        ),
        context=context,
        version=loaded.version,
        is_freeform=loaded.is_freeform,
        has_pending=loaded.has_pending,
        standard_variables=_STANDARD_VARIABLES,
    )


async def _context(session: AsyncSession, agent_id: UUID) -> ScriptContextOut:
    row = (
        await session.execute(
            text(
                "SELECT a.direction, a.language_primary, a.handoff_enabled, a.tenant_id, "
                "o.vertical_template FROM agents a LEFT JOIN organizations o "
                "ON o.id = a.tenant_id WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    style = style_for(str(row[1]))
    return ScriptContextOut(
        collect=[
            CollectFieldOut(label=f.label, reason=f.reason, required=f.required)
            for f in await script_builder.collect_fields(session, agent_id)
        ],
        call_backs_available=await script_builder.call_backs_available(session, row[3]),
        hand_over_enabled=bool(row[2]),
        direction=str(row[0]),
        language=str(row[1]),
        register_name=style.register_name if style is not None else None,
        register_needs_review=style is not None and style.review == "needs_native_review",
        business_type=str(row[4] or "custom"),
        limits=_limits(),
    )


def _limits() -> ScriptLimitsOut:
    limits = hosted_agent_limits(get_engine())
    return ScriptLimitsOut(
        max_sections=MAX_SCRIPT_STAGES,
        section_title_max=STAGE_TITLE_MAX,
        section_detail_max=STAGE_DETAIL_MAX,
        sounds_like_max=SOUNDS_LIKE_MAX,
        max_branches=MAX_STAGE_BRANCHES,
        max_collect=MAX_STAGE_COLLECT,
        instructions_limit=limits.prompt_chars,
        native_steps=limits.native_steps,
        special_targets=sorted(SPECIAL_TARGETS),
    )


async def _knowledge_titles(session: AsyncSession) -> tuple[str, ...]:
    rows = await session.execute(
        text(
            "SELECT name FROM kb_sources WHERE is_active AND published_at IS NOT NULL "
            "ORDER BY published_at DESC LIMIT 20"
        )
    )
    return tuple(str(r[0])[:120] for r in rows)


@router.post(
    "/preview",
    response_model=PreviewOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Compile a (possibly unsaved) script into the exact engine prompt",
)
async def preview_script(
    agent_id: UUID, payload: PreviewIn, session: Session, _: ScriptReader
) -> PreviewOut:
    preview = await script_builder.compiled_preview(session, agent_id, payload.script)
    return PreviewOut(
        compiled=preview.compiled,
        instructions_chars=preview.instructions_chars,
        instructions_limit=preview.instructions_limit,
        native_steps=preview.native_steps,
    )


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
        check_version="expected_version" in payload.model_fields_set,
        expected_version=payload.expected_version,
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
    # Spends the CLIENT'S AI allowance, so a view-as session is refused it for
    # `crm/routes.assist_call`'s reason and on the same named ground (D-587). Before the
    # ownership check, because a refusal that costs nothing should cost no query either.
    assert_view_as_may(principal, "billing.ai_assist")
    tenant_id = principal.tenant_id

    # OWNERSHIP — the agent must be visible to this tenant (RLS) before a rupee is spent or
    # an audit row is written against its id. Unlike the load/save/preview routes this one
    # never loads the agent's script, so without this a neighbour's agent id would bill and
    # audit under it (hard rule 1). 404 for a stranger's id, indistinguishable from missing.
    await script_builder.assert_agent_visible(session, agent_id)
    if not payload.has_enough():
        raise ProblemError(
            kind="validation",
            code="script_assist_too_little",
            title="Tell us a little more first",
            detail="Answer at least one of the questions so the draft has something to go on.",
            fields=[{"name": "answers", "reason": "at least ten characters in all"}],
        )
    context = await _context(session, agent_id)
    business = (
        await session.execute(
            text("SELECT name FROM organizations WHERE id = :t"), {"t": tenant_id}
        )
    ).scalar()
    style = style_for(context.language)
    brief = ScriptBrief(
        description=payload.description,
        business_name=str(business or ""),
        business_type=context.business_type,
        direction=context.direction,
        language=context.language,
        register=(f"{style.register_name}. {style.register}" if style is not None else ""),
        collect=tuple(f.label for f in context.collect),
        knowledge_titles=await _knowledge_titles(session),
        answers=tuple((k, v[:600]) for k, v in payload.answers.items() if k in OWNER_QUESTIONS),
    )

    # GATE — raises `ai_quota_exceeded` / `ai_paused_platform_wide` before any spend.
    quota = await require_ai_assist(session, tenant_id=tenant_id)

    # RUN — the model call, on the controlled worker path (never a raw handler call).
    ref = new_assist_ref()
    # WHOSE AI DRAFTS. The account's own model where it may serve this leg — read on the
    # session already open, for `crm/routes.assist_call`'s reason.
    tenant_leg = await account_assist_leg(session)
    draft = await draft_script(
        brief,
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling,
        edit_of=payload.current if payload.change.strip() else None,
        change=payload.change,
    )

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


class TestResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    #: The caller line that was sent.
    said: str
    reply: str
    #: `passed` (checked by machine), `attention` (something to fix), `failed` (contact us),
    #: or `read` (a person must read the reply).
    verdict: Literal["passed", "attention", "failed", "read"]
    advice: str | None


class TestRunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["queued", "running", "done", "failed"]
    #: The live script version the run talked to.
    prompt_version: int | None
    #: False once the live script has changed since the run.
    is_current: bool
    results: list[TestResultOut]
    created_at: datetime
    completed_at: datetime | None


class TestConversationsOut(BaseModel):
    """Pre-launch test conversations (founder decision 11): advised, never required."""

    model_config = ConfigDict(extra="forbid")

    available: bool
    #: Why tests cannot run now, in the owner's words. Null exactly when `available`.
    unavailable_reason: str | None
    cost_note: str
    latest: TestRunOut | None


def _tests_out(
    ready: test_conversations.TestReadiness, run: test_conversations.TestRun | None
) -> TestConversationsOut:
    latest = None
    if run is not None:
        latest = TestRunOut(
            status=run.status,  # type: ignore[arg-type]
            prompt_version=run.prompt_version,
            is_current=run.prompt_version == ready.live_version,
            results=[
                TestResultOut(
                    key=str(r.get("key", "")),
                    title=str(r.get("title", "")),
                    said=str(r.get("said", "")),
                    reply=str(r.get("reply", "")),
                    verdict=r.get("verdict", "read"),
                    advice=r.get("advice"),
                )
                for r in run.results
                if isinstance(r, dict)
            ],
            created_at=run.created_at,
            completed_at=run.completed_at,
        )
    return TestConversationsOut(
        available=ready.available,
        unavailable_reason=ready.reason,
        cost_note=test_conversations.COST_NOTE,
        latest=latest,
    )


@router.get(
    "/tests",
    response_model=TestConversationsOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The agent's latest pre-launch test conversations",
)
async def get_test_conversations(
    agent_id: UUID, session: Session, _: ScriptReader
) -> TestConversationsOut:
    ready = await test_conversations.readiness(session, agent_id)
    run = await test_conversations.latest_run(session, agent_id)
    return _tests_out(ready, run)


@router.post(
    "/tests",
    response_model=TestConversationsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Run the pre-launch test conversations against the agent",
)
async def run_test_conversations(
    agent_id: UUID, session: Session, request: Request, principal: ScriptWriter
) -> TestConversationsOut:
    assert principal.tenant_id is not None
    # The tests count against the client's dashboard AI allowance (founder, 10 Oct 2026):
    # refused at the ceiling or under view-as. No rupee amount is recorded, because the
    # voice platform does not publish its chat-reply rate (hard rule 7).
    assert_view_as_may(principal, "billing.ai_assist")
    await require_ai_assist(session, tenant_id=principal.tenant_id)
    run = await test_conversations.request_run(
        session, tenant_id=principal.tenant_id, agent_id=agent_id, requested_by=principal.user_id
    )
    await write_audit(
        session,
        action="agent.tests_requested",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={"prompt_version": run.prompt_version},
    )
    return _tests_out(await test_conversations.readiness(session, agent_id), run)


# --- the autosaved draft, "Put it live", versions, restore, convert (D-714) ------------


class SaveDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: CallScript
    #: The draft's `saved_at` the editor loaded (null: there was no draft). When sent, the
    #: save is refused with `script_changed_elsewhere` (409) if the stored draft moved since.
    base_saved_at: datetime | None = None


class DraftSavedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved_at: datetime


@router.put(
    "/draft",
    response_model=DraftSavedOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Autosave the working copy (no version, never reaches a call)",
)
async def save_script_draft(
    agent_id: UUID, payload: SaveDraftIn, session: Session, principal: ScriptWriter
) -> DraftSavedOut:
    # Not audited: an autosave per pause in typing is not a decision. Putting it live is.
    if "base_saved_at" in payload.model_fields_set:
        saved_at = await script_builder.save_draft(
            session, agent_id, payload.script, base_saved_at=payload.base_saved_at
        )
    else:
        saved_at = await script_builder.save_draft(session, agent_id, payload.script)
    return DraftSavedOut(saved_at=saved_at)


class PublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What changed, in the owner's words; becomes the version's note.
    summary: str = Field(min_length=1, max_length=200)
    #: The script to put live; left out, the autosaved draft is.
    script: CallScript | None = None
    #: The version the draft started from (null: no script yet); refused if it moved.
    expected_version: int | None = Field(default=None, ge=1)


class PublishOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    #: True when callers now hear it. False while the agent is not switched on (the version
    #: is what it will use) or the push to the calling system did not complete.
    live: bool


@router.post(
    "/publish",
    response_model=PublishOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Put it live: the draft becomes a version with a change summary and is applied",
)
async def publish_script(
    agent_id: UUID, payload: PublishIn, request: Request, principal: ScriptWriter
) -> PublishOut:
    """One action in place of Save then Apply: a version with the owner's summary, applied
    to live calls in the same request. Callers keep the old script until this succeeds."""
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    async with tenant_session(tenant_id) as session:
        script = payload.script
        if script is None:
            draft = await script_builder.read_draft(session, agent_id)
            if draft is None:
                raise ProblemError.business_rule(
                    "script_nothing_to_publish", "There are no unpublished changes to put live."
                )
            script = draft.script
        saved = await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script,
            notes=payload.summary,
            created_by=principal.user_id,
            check_version="expected_version" in payload.model_fields_set,
            expected_version=payload.expected_version,
        )
        await script_builder.clear_draft(session, agent_id)
        await write_audit(
            session,
            action="agent.script_published",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={"version": saved.version},
        )
    applied = await publishing.apply_to_live(
        tenant_id=tenant_id, agent_id=agent_id, expected_version=saved.version
    )
    return PublishOut(version=saved.version, live=applied.applied and applied.engine_synced)


class VersionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    summary: str | None
    created_at: datetime
    is_live: bool


@router.get(
    "/versions",
    response_model=list[VersionOut],
    openapi_extra=permission_meta("agents:read"),
    summary="The script's versions, newest first, and which one callers hear",
)
async def script_versions(
    agent_id: UUID,
    session: Session,
    _: ScriptReader,
    limit: int = Query(
        script_builder.MAX_VERSIONS_PAGE, ge=1, le=script_builder.MAX_VERSIONS_PAGE
    ),
) -> list[VersionOut]:
    await script_builder.assert_agent_visible(session, agent_id)
    return [
        VersionOut(version=v.version, summary=v.summary, created_at=v.created_at, is_live=v.is_live)
        for v in await script_builder.list_versions(session, agent_id, limit=limit)
    ]


@router.post(
    "/versions/{version}/restore",
    response_model=DraftOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Copy an earlier version into the draft (callers keep the live one)",
)
async def restore_script_version(
    agent_id: UUID, version: int, session: Session, principal: ScriptWriter
) -> DraftOut:
    draft = await script_builder.restore_into_draft(session, agent_id, version)
    return DraftOut(script=draft.script, saved_at=draft.saved_at)


class ConvertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The hand-written prompt; left out, the agent's own text-mode script is used.
    raw_text: str | None = Field(default=None, min_length=10, max_length=20000)


class ConvertOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The proposed sections. Never saved: the owner reviews it and saves it as a draft.
    script: CallScript
    #: Lines of the hand-written prompt that appear nowhere in the proposal.
    unplaced: list[str]
    disclosure: str | None
    metered: bool


@router.post(
    "/convert",
    response_model=ConvertOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Propose sections for a hand-written prompt (AI), with what could not be placed",
)
async def convert_script(
    agent_id: UUID,
    payload: ConvertIn,
    session: Session,
    request: Request,
    principal: ScriptWriter,
) -> ConvertOut:
    """SUBJECT → GATE → RUN → METER, as the assist above, on the client's AI allowance."""
    assert principal.tenant_id is not None
    assert_view_as_may(principal, "billing.ai_assist")
    tenant_id = principal.tenant_id
    raw = payload.raw_text
    if raw is None:
        loaded = await script_builder.load_agent_script(session, agent_id)
        raw = loaded.script.raw_override
    else:
        await script_builder.assert_agent_visible(session, agent_id)
    if not raw or len(raw.strip()) < 10:
        raise ProblemError.business_rule(
            "script_nothing_to_convert", "There is no hand-written script to convert."
        )
    quota = await require_ai_assist(session, tenant_id=tenant_id)
    ref = new_assist_ref()
    tenant_leg = await account_assist_leg(session)
    context = await _context(session, agent_id)
    brief = ScriptBrief(
        description=f"Convert this hand-written prompt:\n{raw}",
        business_type=context.business_type,
        direction=context.direction,
        language=context.language,
    )
    draft = await draft_script(
        brief,
        tenant_leg=tenant_leg,
        quota_exhausted=quota.at_ceiling,
        instruction=CONVERT_INSTRUCTION,
    )
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
            action="agent.script_convert",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary={"metered": metered.metered, "provider": draft.capability.provider},
        )
    return ConvertOut(
        script=draft.script,
        unplaced=unplaced_lines(raw, draft.script),
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
