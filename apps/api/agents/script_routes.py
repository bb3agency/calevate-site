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
from typing import Annotated, Any, Final, Literal, get_args
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
from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import (
    publishing,
    script_builder,
    script_proposals,
    starters,
    test_conversations,
    trial_results,
)
from apps.api.agents.engine_limits import too_long_sentence
from apps.api.agents.script_edits import MAX_EDITS, ScriptEdit, apply_edits
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


class TestSettingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `handover` (the agent's call handling) or `agreements` (the account's agreements).
    area: Literal["handover", "agreements"]
    #: Why this setting decides the result, in the owner's words.
    reason: str


TestReliability = Literal["passed", "flaky", "failed", "unjudged"]
TestStanding = Literal["works", "unreliable", "broken", "setting", "check", "ours", "wrong"]
TestChange = Literal["fixed", "broken", "still", "same", "new"]
#: `turn_checks.SOUND_KINDS`, named on the wire so the screen can word each one.
SoundKind = Literal[
    "brackets",
    "symbols",
    "time",
    "money_digits",
    "formal_words",
    "spoken_number",
    "repeated_question",
    "several_questions",
    "unmarked_question",
    "too_long",
    "wrong_language",
    "third_person",
    "foreign_script",
    "repeated_turn",
]


class TestSoundOut(BaseModel):
    """One way a test's replies sounded wrong (D-828): a note, never the verdict."""

    model_config = ConfigDict(extra="forbid")

    kind: SoundKind
    #: The first time it was seen, in the owner's words.
    reason: str
    #: Tries it was seen on.
    tries: int


class TestTryOut(BaseModel):
    """One try of a test: the conversation it was and its verdict."""

    model_config = ConfigDict(extra="forbid")

    verdict: TestVerdict
    reason: str
    turns: list[TestTurnOut]


class TestResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    #: `business` · `edge` · `objection` · `compliance`.
    category: str
    #: `ai` · `recording` · `stop_calling` · `person` for a compliance probe, else null.
    probe: str | None
    #: `generated` · `standard` · `saved` · `real`, and `retest` on runs before D-828.
    source: str
    #: The try to read: the first that failed, else the first.
    turns: list[TestTurnOut]
    #: What a good agent does here, in plain English.
    expect: str
    #: `passed` (every try), `needs_fix` or `failed` (the shown try's), or `unjudged`.
    verdict: TestVerdict
    #: One line on why, in plain English.
    reason: str
    #: `script_step` · `knowledge` · `objection` · `settings` · `platform`, or null
    #: (`style` on results before D-828).
    fix: str | None
    #: The step to change, when `fix` is `script_step`.
    step_id: str | None
    #: Textbook words the agent used that callers do not say.
    formal_words: list[str]
    #: What a test chat cannot show for this check, in the owner's words, or null.
    limit: str | None = None
    #: Who can fix it (D-823): `script`, `knowledge`, `setting`, `platform` (ours, and we
    #: are told), or `test` once the owner marked it wrong. Null when it passed.
    owner: Literal["script", "knowledge", "setting", "platform", "test"] | None = None
    #: The setting that decides it, when `owner` is `setting`.
    setting: TestSettingOut | None = None
    #: The owner marked this test wrong: it is left out of the score and the fixes.
    marked_wrong: bool = False
    #: Tries that passed, and tries judged (D-828). Results before D-828 had one try.
    passes: int = 0
    judged_tries: int = 0
    #: Works every try (`passed`), some (`flaky`), none (`failed`), or nobody could judge.
    reliability: TestReliability = "unjudged"
    #: Where it sits for the owner (`trial_results.standing`).
    standing: TestStanding = "check"
    #: Counted in the owner's score: their script or knowledge decides it.
    counted: bool = False
    #: Against the same test in the run this one repeated, when it is in the score.
    change: TestChange | None = None
    #: How its replies sounded, when wrong: notes for us, never the verdict.
    sounds: list[TestSoundOut] = Field(default_factory=list)
    #: Where it was produced: `test_chat`, the engine's website-chat sandbox.
    channel: Literal["test_chat"] = "test_chat"
    #: Every try, in order.
    tries: list[TestTryOut] = Field(default_factory=list)


class ScriptEditOut(BaseModel):
    """One suggested edit, kept or left with its own tick box (D-823)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    #: `set_step` · `add_step` · `set_objection` · `set_part`.
    op: Literal["set_step", "add_step", "set_objection", "set_part"]
    #: What it changes, in the owner's words.
    label: str
    #: The words now (empty for something new) and the words suggested.
    before: str
    after: str
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
    """The "Improve my agent" proposal: small edits and facts, each kept or left on its own,
    never applied by itself. Kept edits are applied to the working copy by
    `POST .../tests/{run_id}/improvement/apply`."""

    model_config = ConfigDict(extra="forbid")

    #: `draft` (the autosaved working copy) or `live` (what callers hear).
    base: Literal["draft", "live"]
    edits: list[ScriptEditOut]
    facts: list[ProposedFactOut]
    #: Edits the AI suggested that did not fit the script and were left out.
    dropped: int = 0
    #: The tests it was made for.
    for_keys: list[str]
    #: Set when a fallback model wrote it (D-127 G-6): show it.
    disclosure: str | None
    created_at: datetime


class TestScoreOut(BaseModel):
    """The owner's score (`trial_results.owner_score`)."""

    model_config = ConfigDict(extra="forbid")

    #: Tests in the score that worked on every try.
    passed: int
    #: Tests in the score: the ones the script or the knowledge decides.
    judged: int
    total: int
    #: Of `judged`, tests that worked on some tries only.
    unreliable: int = 0
    #: Tests left out because they are ours to fix.
    ours: int = 0
    #: Tests nobody could judge, for the owner to read.
    check: int = 0
    #: Tests a setting decides.
    setting: int = 0


class TestComparisonOut(BaseModel):
    """Before against after on the same tests (D-828), for a "Test again"."""

    model_config = ConfigDict(extra="forbid")

    #: The run this one repeated, and the script version that run talked to (restore it to
    #: undo a change that broke a test).
    with_run: UUID
    with_version: int | None
    fixed: int
    broken: int
    still: int
    same: int
    new: int
    #: The live script was the same in both runs.
    same_script: bool


class TestSoundCountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SoundKind
    #: Tests whose replies sounded wrong this way on any try.
    tests: int


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
    #: Why the last improve round stopped: `completed` · `no_change` ·
    #: `nothing_fixable_by_script` · `budget` · `failed`.
    improve_stop: (
        Literal["completed", "no_change", "nothing_fixable_by_script", "budget", "failed"] | None
    ) = None
    created_at: datetime
    completed_at: datetime | None
    #: The version of the agent's test set this run asked; null before D-828.
    set_version: int | None = None
    #: Tries per test, and tries finished (progress while running).
    trials: int = 1
    trials_done: int = 0
    #: Before against after, when this run repeated an earlier one.
    comparison: TestComparisonOut | None = None
    #: How the replies sounded across the run, most frequent first: ours to fix.
    sounds: list[TestSoundCountOut] = Field(default_factory=list)
    #: A machine code when `failed`: `stalled` when its job stopped part-way.
    error_code: str | None = None


class TestHistoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    created_at: datetime
    prompt_version: int | None
    round: int
    score: TestScoreOut
    set_version: int | None = None


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
    #: Saved tests and real-call questions the latest set does not have: they join a new set,
    #: never a "Test again".
    waiting_tests: int = 0
    #: AI-written practice callers may be asked for: the agent has few real calls.
    practice_offered: bool = False
    #: Tries per test and the most test-chat replies one run may use.
    trials: int = trial_results.TRIALS
    max_replies: int = test_conversations.MAX_REPLIES_PER_RUN


def _score(run: test_conversations.TestRun) -> TestScoreOut:
    score = run.score
    return TestScoreOut(
        passed=score.passed,
        judged=score.counted,
        total=len(run.results),
        unreliable=score.unreliable,
        ours=score.ours,
        check=score.check,
        setting=score.setting,
    )


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


def _turns_out(raw: dict[str, Any]) -> list[TestTurnOut]:
    conversation = raw.get("conversation")
    if not isinstance(conversation, list):
        return [TestTurnOut(said=str(raw.get("said", "")), reply=str(raw.get("reply", "")))]
    return [
        TestTurnOut(
            said=str(t.get("said", "")),
            reply=str(t.get("reply", "")),
            actions=_actions(t.get("tools")),
        )
        for t in conversation
        if isinstance(t, dict)
    ]


_SOUND_KINDS: Final = frozenset(get_args(SoundKind))


def _sounds_out(raw: dict[str, Any]) -> list[TestSoundOut]:
    return [
        TestSoundOut(
            kind=note["kind"],
            reason=str(note.get("reason") or ""),
            tries=int(note.get("tries") or 1),
        )
        for note in raw.get("sounds") or []
        if isinstance(note, dict) and note.get("kind") in _SOUND_KINDS
    ]


def _result_out(
    raw: dict[str, Any],
    wrong_keys: frozenset[str] = frozenset(),
    change: trial_results.Change | None = None,
) -> TestResultOut:
    """A stored result on today's wire. Runs before D-724 kept one `said`/`reply` pair and
    an `advice` sentence; results before D-823 carry no owner, which is read from `fix`;
    results before D-828 had one try and no sound notes."""
    turns = _turns_out(raw)
    verdict = test_conversations.result_verdict(raw)
    wrong = str(raw.get("key", "")) in wrong_keys
    owner: test_conversations.Owner | None = (
        "test" if wrong else test_conversations.result_owner(raw)
    )
    setting = raw.get("setting")
    rel = trial_results.reliability(raw)
    stored_tries = [t for t in raw.get("tries") or [] if isinstance(t, dict)]
    tries = [
        TestTryOut(
            verdict=test_conversations.result_verdict(t),
            reason=str(t.get("reason") or ""),
            turns=_turns_out(t),
        )
        for t in stored_tries
    ] or [TestTryOut(verdict=verdict, reason=str(raw.get("reason") or ""), turns=turns)]
    return TestResultOut(
        key=str(raw.get("key", "")),
        title=str(raw.get("title", "")),
        category=str(raw.get("category") or "business"),
        probe=raw.get("probe") or None,
        source=str(raw.get("source") or "standard"),
        turns=turns,
        expect=str(raw.get("expect") or ""),
        verdict=verdict,
        reason=str(raw.get("reason") or raw.get("advice") or ""),
        fix=raw.get("fix") or None,
        step_id=raw.get("step_id") or None,
        formal_words=[str(w) for w in raw.get("formal_words") or []],
        limit=str(raw["limit"]) if raw.get("limit") else None,
        owner=None if verdict == "passed" and not wrong else owner,
        setting=(
            TestSettingOut.model_validate(setting)
            if isinstance(setting, dict) and owner == "setting"
            else None
        ),
        marked_wrong=wrong,
        passes=int(raw.get("passes") or (1 if rel == "passed" else 0)),
        judged_tries=int(raw.get("judged_tries") or (0 if rel == "unjudged" else 1)),
        reliability=rel,
        standing=trial_results.standing(raw, wrong_keys),
        counted=trial_results.in_owner_score(raw, wrong_keys),
        change=change,
        sounds=_sounds_out(raw),
        tries=tries,
    )


_EDIT_FIELDS: Final = frozenset(ScriptEditOut.model_fields)


def _improvement_out(raw: dict[str, Any] | None) -> ImprovementOut | None:
    """The stored proposal, or None. A proposal made before D-823 is a whole script with no
    edits, which nothing on today's screen can review; the owner asks for fixes again."""
    if not raw or not isinstance(raw.get("edits"), list):
        return None
    return ImprovementOut(
        base=raw.get("base") or "live",
        edits=[
            ScriptEditOut.model_validate({k: v for k, v in e.items() if k in _EDIT_FIELDS})
            for e in raw["edits"]
            if isinstance(e, dict)
        ],
        facts=[ProposedFactOut.model_validate(f) for f in raw.get("facts") or []],
        dropped=int(raw.get("dropped") or 0),
        for_keys=[str(k) for k in raw.get("for_keys") or []],
        disclosure=raw.get("disclosure"),
        created_at=raw["created_at"],
    )


def _comparison(
    run: test_conversations.TestRun, previous: test_conversations.TestRun | None
) -> tuple[TestComparisonOut | None, trial_results.Comparison]:
    if previous is None or run.status != "done":
        return None, trial_results.Comparison()
    found = trial_results.compare(
        previous.results,
        run.results,
        wrong_keys=run.wrong_keys,
        before_wrong_keys=previous.wrong_keys,
    )
    return (
        TestComparisonOut(
            with_run=previous.id,
            with_version=previous.prompt_version,
            fixed=found.count("fixed"),
            broken=found.count("broken"),
            still=found.count("still"),
            same=found.count("same"),
            new=found.count("new"),
            same_script=previous.prompt_version == run.prompt_version,
        ),
        found,
    )


def _run_out(
    run: test_conversations.TestRun,
    live_version: int | None,
    previous: test_conversations.TestRun | None = None,
) -> TestRunOut:
    comparison, changes = _comparison(run, previous)
    return TestRunOut(
        id=run.id,
        status=run.status,  # type: ignore[arg-type]
        prompt_version=run.prompt_version,
        is_current=run.prompt_version == live_version,
        round=run.improve_round,
        retest_of=run.retest_of,
        auto_improve=run.auto_improve,
        score=_score(run),
        results=[
            _result_out(r, run.wrong_keys, changes.changes.get(str(r.get("key"))))
            for r in run.results
            if isinstance(r, dict)
        ],
        improvement=_improvement_out(run.improvement),
        note=run.note,
        improving=run.improving,
        improve_note=run.improve_note,
        improve_stop=run.improve_stop,  # type: ignore[arg-type]
        created_at=run.created_at,
        completed_at=run.completed_at,
        set_version=run.set_version,
        trials=run.trials,
        trials_done=run.trials_done,
        comparison=comparison,
        sounds=[
            TestSoundCountOut(kind=kind, tests=n)  # type: ignore[arg-type]
            for kind, n in trial_results.sound_counts(run.results, run.wrong_keys).items()
            if kind in _SOUND_KINDS
        ],
        error_code=run.error_code,
    )


async def _tests_out(
    session: AsyncSession, agent_id: UUID, tenant_id: UUID
) -> TestConversationsOut:
    ready = await test_conversations.readiness(session, agent_id)
    run = await test_conversations.latest_run(session, agent_id)
    history = await test_conversations.recent_runs(session, agent_id)
    previous = (
        await test_conversations.get_run(session, agent_id, run.retest_of)
        if run is not None and run.retest_of is not None
        else None
    )
    # The set to add to is the latest one that asked anything.
    asked = next((r for r in [run, *history] if r is not None and r.scenarios), None)
    return TestConversationsOut(
        available=ready.available,
        unavailable_reason=ready.reason,
        cost_note=test_conversations.COST_NOTE,
        waiting_update=await test_conversations.waiting_update(session, tenant_id, agent_id),
        latest=_run_out(run, ready.live_version, previous) if run is not None else None,
        history=[
            TestHistoryOut(
                id=h.id,
                created_at=h.created_at,
                prompt_version=h.prompt_version,
                round=h.improve_round,
                score=_score(h),
                set_version=h.set_version,
            )
            for h in history
        ],
        waiting_tests=await test_conversations.waiting_tests(session, agent_id, asked),
        practice_offered=(
            await test_conversations.count_real_calls(session, agent_id)
            < test_conversations.ENOUGH_REAL_CALLS
        ),
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

    #: "Test again": exactly that run's tests are asked again, for before against after.
    #: Without it the run makes a new version of the agent's test set.
    retest_of: UUID | None = None
    #: Prepare the improvement proposal by itself when this run has failures.
    auto_improve: bool = False
    #: Add AI-written practice callers to the new set (never with `retest_of`).
    practice_callers: bool = False


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
        practice_callers=body.practice_callers,
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
            "practice_callers": body.practice_callers,
            "set_version": run.set_version,
        },
    )
    return await _tests_out(session, agent_id, principal.tenant_id)


@router.post(
    "/tests/{run_id}/results/{key}/wrong",
    response_model=TestConversationsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Mark a test that did not pass as wrong: out of the score and the fixes",
)
async def mark_test_wrong(
    agent_id: UUID,
    run_id: UUID,
    key: Annotated[str, Path(min_length=1, max_length=120)],
    session: Session,
    request: Request,
    principal: ScriptWriter,
) -> TestConversationsOut:
    assert principal.tenant_id is not None
    await test_conversations.mark_wrong(
        session,
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        run_id=run_id,
        key=key,
        by=principal.user_id,
    )
    await write_audit(
        session,
        action="agent.test_marked_wrong",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary={"run_id": str(run_id)},
    )
    return await _tests_out(session, agent_id, principal.tenant_id)


class ApplyEditsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The owner's working copy: the draft, or the live script when there is no draft.
    script: CallScript
    #: The edits kept, by id, in the order to apply them.
    edits: list[Annotated[str, Field(max_length=8)]] = Field(max_length=MAX_EDITS)


class ApplyEditsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `script` with the kept edits made. Nothing is saved: the caller saves it as the
    #: draft or puts it live, as it does any edit.
    script: CallScript
    #: Kept edits that no longer fit the working copy (their step was removed since, or the
    #: step limit was reached), left out.
    skipped: list[str]


@router.post(
    "/tests/{run_id}/improvement/apply",
    response_model=ApplyEditsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="The working script with the kept suggested edits made (nothing is saved)",
)
async def apply_suggested_edits(
    agent_id: UUID,
    run_id: UUID,
    payload: ApplyEditsIn,
    session: Session,
    principal: ScriptWriter,
) -> ApplyEditsOut:
    """The one place a kept edit is applied: the same `script_edits.apply_edit` that built
    the proposal, onto the copy the owner holds now, so an edit made since is never undone."""
    run = await test_conversations.get_run(session, agent_id, run_id)
    stored = (run.improvement or {}).get("edits") or []
    by_id = {str(e.get("id")): e for e in stored if isinstance(e, dict)}
    if any(i not in by_id for i in payload.edits):
        raise ProblemError.business_rule(
            "agent_tests_unknown_edit",
            "These suggestions have changed since you opened them.",
            remediation="Close the suggestions and open them again.",
        )
    script, _applied, rejected = apply_edits(
        upgrade_to_v2(payload.script), [ScriptEdit.of(by_id[i]) for i in payload.edits]
    )
    return ApplyEditsOut(script=script, skipped=[edit.id for edit, _why in rejected])


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
    try:
        applied = await publishing.apply_to_live(
            tenant_id=tenant_id, agent_id=agent_id, expected_version=saved.version
        )
    except ProblemError as exc:
        # The version above is committed and the draft cleared, so a refusal from here on
        # must not read as "nothing happened": it says what is saved and how to finish. The
        # refusal itself is re-raised, so its code, status and alarm stay the raise site's.
        exc.title = "Saved, but not live yet"
        exc.detail = (
            f"Your changes are saved as version {saved.version}, and callers still hear the "
            f"previous script. Putting it live did not finish: {exc.detail}"
        )
        exc.remediation = (
            "Press Put it live again to finish; your changes are kept. " + (exc.remediation or "")
        ).strip()
        raise
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


class OpeningRewrittenOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The opening line now in the draft, in the agent's main language.
    opening_line: str
    saved_at: datetime


@router.post(
    "/opening-line/in-language",
    response_model=OpeningRewrittenOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Put a ready-made opening line in the agent's main language into the draft",
    description=(
        "Offered after the agent's main language changes (D-838). The line is the "
        "ready-made greeting for this business type in that language, written into the "
        "autosaved draft; callers keep the live script until the draft is put live."
    ),
)
async def rewrite_opening_in_language(
    agent_id: UUID, session: Session, _: ScriptWriter
) -> OpeningRewrittenOut:
    # Not audited, for the autosave's reason: nothing here reaches a call. Putting it live is.
    done = await starters.rewrite_opening_in_language(session, agent_id)
    return OpeningRewrittenOut(opening_line=done.opening_line, saved_at=done.saved_at)


class OpeningLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The new opening line, in the agent's main language. `CallScript.opening_line`'s bound.
    opening_line: str = Field(min_length=1, max_length=1000)


class OpeningLineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_line: str
    #: The new version of the script, or null when it already had this line.
    version: int | None


@router.put(
    "/opening-line",
    response_model=OpeningLineOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Replace the opening line in the script callers hear, and put it live",
    description=(
        "For shortening the opening line where a notice switch was refused for want of room "
        "(D-846). The rest of the script is kept. Refused while other script changes are "
        "waiting to go live, and when the line would not fit after the notices switched on."
    ),
)
async def replace_opening_line(
    agent_id: UUID, payload: OpeningLineIn, request: Request, principal: ScriptWriter
) -> OpeningLineOut:
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as session:
        done = await script_builder.replace_opening_line(
            session,
            tenant_id=principal.tenant_id,
            agent_id=agent_id,
            opening_line=payload.opening_line,
            created_by=principal.user_id,
        )
        if done.version is not None:
            await write_audit(
                session,
                action="agent.opening_line_replaced",
                actor=principal,
                tenant_id=principal.tenant_id,
                object_type="agent",
                object_id=str(agent_id),
                ip=client_request_ip(request),
                summary={"version": done.version},
            )
    return OpeningLineOut(opening_line=done.opening_line, version=done.version)


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
