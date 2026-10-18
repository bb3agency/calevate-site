"""Client-realm structured call-script builder (D-21 CONFLICT — see below).

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

AI WRITING IS PIP'S (D-820). A change, a whole draft or a hand-written script turned into
steps is asked of Pip (`copilot/script_actions.py`) and written by a job; this router only
shows the pending proposal (`GET .../proposal`) and clears it once the owner has kept or
discarded it (`DELETE .../proposal/{id}`). The test routes below still gate on the allowance
(`require_ai_assist`) because they queue paid AI work of their own.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
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
    upgrade_to_v2,
)
from calevate_shared.spoken_style import example_exchange, native_reviewed, style_for
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import publishing, script_builder, script_proposals, test_conversations
from apps.api.agents.engine_limits import too_long_sentence
from apps.api.billing.ai_quota import require_ai_assist
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.reliability.engine_actions import ACTION_NAMES, CALLBACK, CALLBACK_CANCEL, OPT_OUT

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


class SizePartOut(BaseModel):
    """One part of the instructions and its length. Never its text."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    chars: int


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
    #: How far `instructions_chars` is over the limit (0 when it fits).
    over_chars: int = 0
    #: The sentence to show when it is over, null when it fits.
    too_long: str | None = None
    #: The instructions by layer (Calevate's rules and the script) and the script by
    #: section, longest first, so the owner can see what to shorten. Counts only.
    layers: list[SizePartOut] = Field(default_factory=list)
    script_parts: list[SizePartOut] = Field(default_factory=list)


def preview_out(preview: script_builder.Preview) -> PreviewOut:
    size = preview.size
    return PreviewOut(
        compiled=preview.compiled,
        instructions_chars=preview.instructions_chars,
        instructions_limit=preview.instructions_limit,
        native_steps=preview.native_steps,
        over_chars=size.over,
        too_long=None if size.fits else too_long_sentence(size),
        layers=[SizePartOut(key=p.key, label=p.label, chars=p.chars) for p in size.layers],
        script_parts=[
            SizePartOut(key=p.key, label=p.label, chars=p.chars)
            for p in sorted(size.script_parts, key=lambda p: p.chars, reverse=True)
        ],
    )


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
                # Unreviewed until the founder publishes this language as reviewed (D-744).
                "example_needs_review": not native_reviewed(context.language),
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


@router.post(
    "/preview",
    response_model=PreviewOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Compile a (possibly unsaved) script into the exact engine prompt",
)
async def preview_script(
    agent_id: UUID, payload: PreviewIn, session: Session, _: ScriptReader
) -> PreviewOut:
    return preview_out(await script_builder.compiled_preview(session, agent_id, payload.script))


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
    await script_builder.refuse_if_too_long(session, agent_id, payload.script)
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


TestVerdict = Literal["passed", "needs_fix", "failed", "unjudged"]


class TestTurnOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The caller line sent: written by the AI, the owner's saved test, or a standard line.
    said: str
    #: What the agent answered in its test chat.
    reply: str
    #: The steps it took in this turn, in our words: `knowledge` (looked something up),
    #: `do_not_call` (its step that removes a number), `call_back`, or `other`.
    actions: list[Literal["knowledge", "do_not_call", "call_back", "other"]] = Field(
        default_factory=list
    )


class TestResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    #: `business` · `edge` · `objection` · `compliance`.
    category: str
    #: `ai` · `recording` · `stop_calling` · `person` for a compliance probe, else null.
    probe: str | None
    #: `generated` · `standard` · `saved` · `retest`.
    source: str
    turns: list[TestTurnOut]
    #: What a good agent does here, in plain English.
    expect: str
    #: `passed`, `needs_fix`, `failed`, or `unjudged` when no AI could check it.
    verdict: TestVerdict
    #: One line on why, in plain English.
    reason: str
    #: `script_step` · `knowledge` · `objection` · `style` · `settings` · `platform`, or null.
    fix: str | None
    #: The step to change, when `fix` is `script_step`.
    step_id: str | None
    #: Textbook words the agent used that callers do not say.
    formal_words: list[str]
    #: This scenario's verdict in the run being re-tested, on a "Test again".
    before: TestVerdict | None
    #: What a test chat cannot show for this check, in the owner's words, or null.
    limit: str | None = None


class ProposedChangeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `step:<id>`, or a part of the script (`opening_line`, `objections`, `style`, ...).
    target: str
    #: The test it fixes.
    because: str | None
    why: str


class ProposedFactOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `add` a pinned fact, or `fix` the pinned fact `fact_id`.
    action: Literal["add", "fix"]
    fact_id: str | None
    question: str
    #: Empty when only the owner knows the answer: they type it before keeping the fact.
    answer: str
    because: str | None
    why: str


class ImprovementOut(BaseModel):
    """The "Improve my agent" proposal, reviewed change by change, never applied by itself."""

    model_config = ConfigDict(extra="forbid")

    #: The proposed script. Diff it against `base_script` to list the changes; apply the
    #: kept ones to the editor's working copy.
    script: CallScript
    #: The script the proposal was made from.
    base_script: CallScript
    #: `draft` (the autosaved working copy) or `live` (what callers hear).
    base: Literal["draft", "live"]
    changes: list[ProposedChangeOut]
    facts: list[ProposedFactOut]
    #: The tests it was made for.
    for_keys: list[str]
    #: Set when a fallback model wrote it (D-127 G-6): show it.
    disclosure: str | None
    created_at: datetime


class TestScoreOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: int
    #: Scenarios with a verdict; `unjudged` ones are not counted.
    judged: int
    total: int


class TestRunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: Literal["queued", "running", "done", "failed"]
    #: The live script version the run talked to.
    prompt_version: int | None
    #: False once the live script has changed since the run.
    is_current: bool
    #: 1 for a first run; each "Test again" after a fix adds one.
    round: int
    retest_of: UUID | None
    auto_improve: bool
    score: TestScoreOut
    #: Failures first.
    results: list[TestResultOut]
    improvement: ImprovementOut | None
    #: How the run went, in the owner's words, when there is something to say.
    note: str | None
    #: "Improve my agent" is being worked out; poll until `improvement` or `improve_note`.
    improving: bool = False
    #: Why the last "Improve my agent" could not be made, in the owner's words.
    improve_note: str | None = None
    created_at: datetime
    completed_at: datetime | None


class TestHistoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    created_at: datetime
    prompt_version: int | None
    round: int
    score: TestScoreOut


class TestConversationsOut(BaseModel):
    """Test conversations that improve the agent (D-724): advised, never required."""

    model_config = ConfigDict(extra="forbid")

    available: bool
    #: Why tests cannot run now, in the owner's words. Null exactly when `available`.
    unavailable_reason: str | None
    cost_note: str
    #: Why the agent under test is behind the instructions we give every agent, or null.
    waiting_update: str | None = None
    latest: TestRunOut | None
    #: Finished runs, newest first, for the score over time.
    history: list[TestHistoryOut]


def _score(run: test_conversations.TestRun) -> TestScoreOut:
    passed, judged = run.score
    return TestScoreOut(passed=passed, judged=judged, total=len(run.results))


TestAction = Literal["knowledge", "do_not_call", "call_back", "other"]

_ACTION_KINDS: dict[str, TestAction] = {
    ACTION_NAMES[OPT_OUT]: "do_not_call",
    ACTION_NAMES[CALLBACK]: "call_back",
    ACTION_NAMES[CALLBACK_CANCEL]: "call_back",
}


def _actions(tools: Any) -> list[TestAction]:
    """A turn's tool names in the owner's vocabulary, each kind once. The tool names are
    the engine's and ours; the screen never shows them."""
    knowledge = hosted_agent_limits(get_engine()).knowledge_tool
    out: list[TestAction] = []
    for name in tools if isinstance(tools, list) else []:
        kind: TestAction = (
            "knowledge"
            if knowledge is not None and name == knowledge
            else _ACTION_KINDS.get(str(name), "other")
        )
        if kind not in out:
            out.append(kind)
    return out


def _result_out(raw: dict[str, Any]) -> TestResultOut:
    """A stored result on today's wire. Runs before D-724 kept one `said`/`reply` pair and
    an `advice` sentence."""
    conversation = raw.get("conversation")
    turns = (
        [
            TestTurnOut(
                said=str(t.get("said", "")),
                reply=str(t.get("reply", "")),
                actions=_actions(t.get("tools")),
            )
            for t in conversation
            if isinstance(t, dict)
        ]
        if isinstance(conversation, list)
        else [TestTurnOut(said=str(raw.get("said", "")), reply=str(raw.get("reply", "")))]
    )
    before = raw.get("before")
    return TestResultOut(
        key=str(raw.get("key", "")),
        title=str(raw.get("title", "")),
        category=str(raw.get("category") or "business"),
        probe=raw.get("probe") or None,
        source=str(raw.get("source") or "standard"),
        turns=turns,
        expect=str(raw.get("expect") or ""),
        verdict=test_conversations.result_verdict(raw),
        reason=str(raw.get("reason") or raw.get("advice") or ""),
        fix=raw.get("fix") or None,
        step_id=raw.get("step_id") or None,
        formal_words=[str(w) for w in raw.get("formal_words") or []],
        before=test_conversations.result_verdict({"verdict": before}) if before else None,
        limit=str(raw["limit"]) if raw.get("limit") else None,
    )


def _improvement_out(raw: dict[str, Any] | None) -> ImprovementOut | None:
    if not raw:
        return None
    return ImprovementOut.model_validate(
        {k: raw.get(k) for k in ImprovementOut.model_fields if k in raw}
        | {"facts": raw.get("facts") or [], "changes": raw.get("changes") or []}
    )


def _run_out(run: test_conversations.TestRun, live_version: int | None) -> TestRunOut:
    return TestRunOut(
        id=run.id,
        status=run.status,  # type: ignore[arg-type]
        prompt_version=run.prompt_version,
        is_current=run.prompt_version == live_version,
        round=run.improve_round,
        retest_of=run.retest_of,
        auto_improve=run.auto_improve,
        score=_score(run),
        results=[_result_out(r) for r in run.results if isinstance(r, dict)],
        improvement=_improvement_out(run.improvement),
        note=run.note,
        improving=run.improving,
        improve_note=run.improve_note,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


async def _tests_out(
    session: AsyncSession, agent_id: UUID, tenant_id: UUID
) -> TestConversationsOut:
    ready = await test_conversations.readiness(session, agent_id)
    run = await test_conversations.latest_run(session, agent_id)
    history = await test_conversations.recent_runs(session, agent_id)
    return TestConversationsOut(
        available=ready.available,
        unavailable_reason=ready.reason,
        cost_note=test_conversations.COST_NOTE,
        waiting_update=await test_conversations.waiting_update(session, tenant_id, agent_id),
        latest=_run_out(run, ready.live_version) if run is not None else None,
        history=[
            TestHistoryOut(
                id=h.id,
                created_at=h.created_at,
                prompt_version=h.prompt_version,
                round=h.improve_round,
                score=_score(h),
            )
            for h in history
        ],
    )


@router.get(
    "/tests",
    response_model=TestConversationsOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The agent's latest test conversations and its score over time",
)
async def get_test_conversations(
    agent_id: UUID, session: Session, principal: ScriptReader
) -> TestConversationsOut:
    assert principal.tenant_id is not None
    return await _tests_out(session, agent_id, principal.tenant_id)


class RunTestsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: "Test again" after a fix: that run's failures are asked again beside a fresh set.
    retest_of: UUID | None = None
    #: Prepare the improvement proposal by itself when this run has failures.
    auto_improve: bool = False


@router.post(
    "/tests",
    response_model=TestConversationsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Run test conversations against the agent callers hear now",
)
async def run_test_conversations(
    agent_id: UUID,
    session: Session,
    request: Request,
    principal: ScriptWriter,
    payload: RunTestsIn | None = None,
) -> TestConversationsOut:
    assert principal.tenant_id is not None
    # Writing and judging the tests spend the client's dashboard AI allowance (founder,
    # 10 Oct 2026): refused at the ceiling or under view-as, before anything is queued.
    assert_view_as_may(principal, "billing.ai_assist")
    await require_ai_assist(session, tenant_id=principal.tenant_id)
    body = payload or RunTestsIn()
    run = await test_conversations.request_run(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        requested_by=principal.user_id,
        retest_of=body.retest_of,
        auto_improve=body.auto_improve,
    )
    await write_audit(
        session,
        action="agent.tests_requested",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={
            "run_id": str(run.id),
            "prompt_version": run.prompt_version,
            "retest": body.retest_of is not None,
            "auto_improve": body.auto_improve,
        },
    )
    return await _tests_out(session, agent_id, principal.tenant_id)


# --- the suggestion Pip prepared (D-820) ------------------------------------------------


class ScriptProposalOut(BaseModel):
    """A script suggestion Pip was asked for, reviewed part by part on the Script page."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    #: `change` (one change), `whole` (the whole script from the owner's answers) or
    #: `steps` (a hand-written script turned into steps).
    mode: Literal["change", "whole", "steps"]
    #: `drafting` until it is written (poll), then `ready`, or `failed` with `note`.
    status: Literal["drafting", "ready", "failed"]
    #: The change the person asked for, with `change`.
    request: str | None
    #: The script it was made from. List the changes against this, not the working copy,
    #: so an edit made since is never offered back; apply the kept ones to the working copy.
    base_script: CallScript
    #: The suggested script, when `ready`.
    script: CallScript | None
    #: Lines of the hand-written script that appear nowhere in the steps (`steps`).
    unplaced: list[str]
    #: Set when a fallback model wrote it (D-127 G-6): show it.
    disclosure: str | None
    #: Why it could not be written, in the owner's words, when `failed`.
    note: str | None
    requested_at: datetime


class PendingProposalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: ScriptProposalOut | None


@router.get(
    "/proposal",
    response_model=PendingProposalOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The script suggestion Pip prepared and the owner has not yet reviewed",
)
async def get_script_proposal(
    agent_id: UUID, session: Session, _: ScriptReader
) -> PendingProposalOut:
    found = await script_proposals.read_proposal(session, agent_id)
    if found is None:
        return PendingProposalOut(proposal=None)
    return PendingProposalOut(
        proposal=ScriptProposalOut(
            id=found.id,
            mode=found.mode,
            status=found.status,
            request=found.request,
            base_script=found.base_script,
            script=found.script,
            unplaced=found.unplaced,
            disclosure=found.disclosure,
            note=found.note,
            requested_at=found.requested_at,
        )
    )


@router.delete(
    "/proposal/{proposal_id}",
    status_code=204,
    openapi_extra=permission_meta("org:manage"),
    summary="Clear the suggestion once its kept parts are in the draft, or to discard it",
)
async def discard_script_proposal(
    agent_id: UUID, proposal_id: UUID, session: Session, _: ScriptWriter
) -> None:
    # Not audited, for the autosave's reason: what reaches the draft is the owner's own edit,
    # and nothing here reaches a call. A proposal already gone is the same outcome.
    await script_proposals.discard(session, agent_id=agent_id, proposal_id=proposal_id)


# --- the autosaved draft, "Put it live", versions, restore (D-714) ----------------------


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
        # Before the version is stored or anything reaches the calling system: a script that
        # cannot fit is refused here with its length, and the draft is kept.
        await script_builder.refuse_if_too_long(session, agent_id, script)
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
    limit: int = Query(script_builder.MAX_VERSIONS_PAGE, ge=1, le=script_builder.MAX_VERSIONS_PAGE),
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
