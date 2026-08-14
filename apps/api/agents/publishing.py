"""Two-speed publishing and the cost-runaway guard (SURFACES §2b) — the API half.

    "**Two-speed publishing** — script/flow/actions/webhook edits require an explicit
     **'Apply to live calls'**; voice, extraction fields and training apply
     immediately. Split by blast radius, with an unsaved-changes banner offering Apply
     or Undo. Nothing goes live silently."  (docs/SURFACES.md §2b:101)

    "**Cost-runaway guard** — a per-agent max call length (their default 10 min,
     adjustable). We have no equivalent today and should."  (§2b:107)

WHAT WAS ACTUALLY MISSING
-------------------------
Prompt versioning with an explicit publish already existed (FLOWS §7), so the split
looked half-present. It was worse than half-present: it was INVERTED, and both halves
were inverted in the same direction — towards publishing the thing you meant to hold
and holding the thing you meant to publish.

    field           §2b lane      behaviour before this module
    -----------     ----------    -------------------------------------------------
    script          staged        `write_prompt_version` re-published a LIVE agent in
                                  the same transaction. Every version was born live.
    voice           immediate     `set_agent_voice` deliberately never touched the
                                  engine; the response says `republish_required`.
    training (T0)   immediate     `recompile_t0` re-published a LIVE agent. Correct.
    extraction      immediate     admin-only edit, no engine hop. Correct.
    call length     (absent)      no column; every agent published the SDK default.

So FLOWS §7's "explicit publish" was about prompt VERSIONING, not prompt PUBLISHING:
creation and activation were one step, as `insert_prompt_version` said in as many
words. The missing thing was never a button. It was a second pointer — somewhere to
record that the script the client is editing and the script the engine is running are
allowed to differ. `agents.live_prompt_id` (migration a4e7b2c95d18) is that pointer,
and `system_prompt_id IS DISTINCT FROM live_prompt_id` IS the pending state, derived
rather than stored so it cannot drift the way a `has_unsaved_changes` flag would.

WHY THE FAST LANE NEEDED THE SLOW LANE FIRST
--------------------------------------------
`publish_agent` sends ONE `AgentConfig` carrying script, voice, models and cap
together. Before the applied pointer there was no way to push a voice without also
pushing whatever sat in `system_prompt_id` — which is exactly why `voice_routes.py`
refuses to publish and hands the client a `republish_required` flag instead. A fast
lane was not unbuilt, it was unbuildable. Reading the applied pointer at publish time
is what makes "apply the cap now, leave the draft script alone" expressible at all.

WHICH SIDE EACH FIELD FALLS ON
------------------------------
`LANES` below is the answer as DATA, with the precedence rule §2b asks the UI to state
attached to it. The test is not "how risky does this feel" but §2b's own sentence —
*script decides content, rules decide conduct, voice only changes delivery*:

- **script** is content. It is the only field that changes what the agent SAYS, it is
  the field a client is legally answerable for as the Principal Entity, and it is the
  one whose bad version is discovered by a customer on the phone. Staged.
- **max call length** is conduct. It cannot alter one word; it can only reduce
  exposure. Immediate.
- **voice** is delivery. Immediate per §2b — with the caveat recorded under
  `set_agent_voice`, which this module does not overrule. See the next section: the
  lane says what the design INTENDS, and `PendingState.voice` says what this agent's
  callers are actually hearing right now.
- **extraction fields** shape CRM columns, not the call. Immediate.
- **training (T0)** is immediate, with one documented exception in `agents/t0.py`: a
  recompile splices into the DRAFT body, so while a script edit is staged the
  recompile stages with it rather than dragging an unapproved script live.

⚠ AN OPEN CONFLICT BETWEEN THE DOCS AND THE CODE, REPORTED RATHER THAN RESOLVED
--------------------------------------------------------------------------------
§2b puts voice on the IMMEDIATE side and `LANES` above says so, but `set_agent_voice`
does not reach the engine, so a voice change on a live agent is in practice STAGED
until someone publishes. The lane table is therefore a description of the intended
design that no agent currently obeys, and the client screen renders it under "Applies
straight away".

Not fixed here, and deliberately not fixed here: reconciling it means either
auto-republishing on a voice change (which re-voices a running client's phone line on
an ear test we have not run — `voice_routes.py` argues that at length, pilot gate 3) or
moving `voice` to the `staged` lane (which contradicts an authoritative doc). Both are
decision-log entries (ROADMAP §6), not a quiet edit.

What IS fixed here is the part that needed no decision: the state was previously
unobservable, so nobody could even see which side of the split a given agent was on.
`PendingState.voice` reports the CONFIGURED voice and the voice the engine was last
SENT as two fields, per agent, from the row — so a screen can tell a client the truth
about their own agent whichever way the general rule is eventually settled.

NOT MOUNTED HERE. `publishing_routes.py` carries the endpoints and, like
`agents/prompt_routes.py` and `agents/voice_routes.py`, is wired into `main.py` by the
integrator rather than by this wave.

Sessions: every function here opens its own `tenant_session`, so an agent belonging to
another tenant is invisible and "not found" and "belongs to someone else" are the same
answer (hard rule 1). Nothing in this module logs a prompt body or a summary derived
from one (hard rule 6) — version NUMBERS only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import CALL_CAP_DEFAULT_S, CALL_CAP_MAX_S, CALL_CAP_MIN_S
from apps.api.agents.service import effective_call_cap, publish_agent
from apps.api.agents.voices import Voice, get_voice
from apps.api.billing.plans import NOW_SQL, plan_in_effect_sql
from apps.api.billing.service import to_paise
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session

log = get_logger(__name__)

Lane = Literal["staged", "live"]

# §2b, verbatim enough to be quotable in the UI and short enough to fit in a banner.
PRECEDENCE_RULE = "Script decides content, rules decide conduct, voice only changes delivery."


@dataclass(frozen=True, slots=True)
class LaneEntry:
    """One configurable field and the speed at which it reaches a live agent.

    Shipped as data rather than as prose in a handler so the client app renders the
    same split the server enforces — a UI that paraphrases this table is how "voice
    applies immediately" becomes a support ticket.
    """

    field: str
    lane: Lane
    # 1 content, 2 conduct, 3 delivery — the precedence rule as a sort key. Lower wins
    # when two changes disagree about what the agent should do.
    precedence: int
    why: str


LANES: tuple[LaneEntry, ...] = (
    LaneEntry(
        field="script",
        lane="staged",
        precedence=1,
        why=(
            "The script decides what the agent says, and a bad version is discovered "
            "by a customer on the phone. It waits for Apply."
        ),
    ),
    LaneEntry(
        field="max_call_duration_s",
        lane="live",
        precedence=2,
        why=(
            "A call-length cap decides conduct, not content: it cannot change one "
            "word the agent says, only how long it may keep saying it."
        ),
    ),
    LaneEntry(
        field="extraction_fields",
        lane="live",
        precedence=2,
        why="Extraction shapes the CRM columns a call produces, never the call itself.",
    ),
    LaneEntry(
        field="training",
        lane="live",
        precedence=2,
        why=(
            "Approved knowledge is recompiled into T0 and applies immediately — "
            "unless a script edit is already staged, in which case it waits with it, "
            "because both live in the same prompt body."
        ),
    ),
    LaneEntry(
        field="voice",
        lane="live",
        precedence=3,
        why="A voice only changes delivery. It cannot change what is said or decided.",
    ),
)

_LANE_BY_FIELD: dict[str, LaneEntry] = {entry.field: entry for entry in LANES}

# The table is the contract; a duplicate would silently shadow a lane.
assert len(_LANE_BY_FIELD) == len(LANES), "duplicate field in LANES"


def lane_of(field_name: str) -> LaneEntry:
    """The lane a configurable field is on, or a KeyError — an unknown field is a
    programming mistake, not a client input."""
    return _LANE_BY_FIELD[field_name]


@dataclass(frozen=True, slots=True)
class AgentVoice:
    """One voice at one moment: the id stored on the row, plus the catalog entry when
    we recognise it.

    `catalog` is None for a string outside `agents/voices.CATALOG` — a row set before
    the catalog existed, or an entry retired since. The id is still returned, because
    "we do not recognise this voice" and "there is no voice" are different answers and
    only one of them is worth an operator's attention.
    """

    voice_id: str
    provider: str | None
    catalog: Voice | None


@dataclass(frozen=True, slots=True)
class VoiceState:
    """What the agent is CONFIGURED to speak in, and what the engine was last SENT.

    THE WHOLE POINT IS THAT THESE ARE TWO FIELDS. `set_agent_voice` writes the row and
    deliberately does not touch the engine (`voice_routes.py`: re-voicing a running
    client's phone line on an ear test we have not done is not a safe default), so
    between a voice change and the next publish the configured voice and the spoken
    voice are different facts. Answering with one of them and calling it "the voice" is
    the same defect `live_prompt_id` was added to fix for the script and that
    `set_call_cap`'s in-transaction republish avoids for the cap — twice already, under
    two other names.

    `live` is None when nothing has been recorded as sent. Two situations produce that
    and they are NOT distinguishable from the row, which is why the caller is given
    `PendingState.published` to read alongside:

        published = False   nothing is on the engine; there is nothing to know
        published = True    published before migration c8b3f14e7a29, or published with
                            no voice set — either way we cannot PROVE the engine holds
                            the configured voice

    Both resolve the same way: `republish_required` is true whenever the two are
    distinct, so an unknown live voice errs towards "publish again", never towards a
    claim of sync we cannot support.
    """

    configured: AgentVoice | None
    live: AgentVoice | None
    # `live IS DISTINCT FROM configured`, and the agent is actually on the engine. An
    # unpublished agent has no callers to mislead, so it is never "republish required".
    republish_required: bool
    headline: str


@dataclass(frozen=True, slots=True)
class PendingChange:
    """One staged, unapplied change. Version NUMBERS and a lane, never a body."""

    field: str
    lane: Lane
    staged_version: int
    live_version: int | None
    staged_at: datetime
    headline: str
    why: str


@dataclass(frozen=True, slots=True)
class PendingState:
    """What the unsaved-changes banner needs, in one read.

    `worst_case_call_cost_inr` is the answer to the question a cap is really asking —
    what does one runaway call cost me — computed from the tenant's own plan rate.
    """

    agent_id: UUID
    agent_status: str
    published: bool
    has_pending: bool
    pending: list[PendingChange]
    effective_call_cap_s: int
    call_cap_is_platform_default: bool
    worst_case_call_cost_inr: Decimal | None
    # NOT a member of `pending`, and that is a statement about what Apply does rather
    # than an oversight. `pending` is the list Apply and Undo act on: every entry is a
    # `prompt_versions` number, Apply moves `live_prompt_id` and Undo moves it back. A
    # voice divergence has no version to name and neither button clears it on its own —
    # `undo_staged` does not touch the voice columns at all, so listing one here would
    # put an Undo next to a change it cannot undo. It is cleared by a PUBLISH, which is
    # what `set_agent_voice`'s `next_step` has always said. (Apply does clear it as a
    # side effect when a script is ALSO staged, because `apply_to_live` publishes; the
    # mirror is written by `publish_agent` wherever it is called from, so the answer
    # stays correct either way.)
    voice: VoiceState
    precedence_rule: str = PRECEDENCE_RULE
    lanes: tuple[LaneEntry, ...] = field(default=LANES)


@dataclass(frozen=True, slots=True)
class ApplyResult:
    agent_id: UUID
    applied: bool
    live_version: int
    engine_synced: bool


@dataclass(frozen=True, slots=True)
class UndoResult:
    agent_id: UUID
    undone: bool
    discarded_version: int | None
    live_version: int | None


@dataclass(frozen=True, slots=True)
class CallCapResult:
    agent_id: UUID
    max_call_duration_s: int | None
    effective_call_cap_s: int
    is_platform_default: bool
    engine_synced: bool
    worst_case_call_cost_inr: Decimal | None


@dataclass(frozen=True, slots=True)
class _AgentRow:
    status: str
    engine_agent_ref: str | None
    draft_version: int | None
    draft_at: datetime | None
    live_version: int | None
    max_call_duration_s: int | None
    tts_voice: str | None
    tts_provider: str | None
    live_tts_voice: str | None
    live_tts_provider: str | None

    @property
    def is_live(self) -> bool:
        return self.status == "live" and bool(self.engine_agent_ref)

    @property
    def has_pending(self) -> bool:
        return self.draft_version is not None and self.draft_version != self.live_version

    @property
    def published(self) -> bool:
        return bool(self.engine_agent_ref)

    @property
    def voice_diverged(self) -> bool:
        """SQL's `IS DISTINCT FROM`, in Python. NULL on either side is a value here, not
        an unknown: "no voice configured" and "nothing recorded as sent" are answers."""
        return self.live_tts_voice != self.tts_voice


_AGENT_SQL = (
    "SELECT a.status, a.engine_agent_ref, d.version, d.created_at, l.version, "
    "a.max_call_duration_s, a.tts_voice, a.tts_provider, a.live_tts_voice, "
    "a.live_tts_provider FROM agents a "
    "LEFT JOIN prompt_versions d ON d.id = a.system_prompt_id "
    "LEFT JOIN prompt_versions l ON l.id = a.live_prompt_id "
    "WHERE a.id = :aid AND a.deleted_at IS NULL"
)


async def _load(session: AsyncSession, agent_id: UUID) -> _AgentRow:
    row = (await session.execute(text(_AGENT_SQL), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _AgentRow(
        status=str(row[0]),
        engine_agent_ref=row[1],
        draft_version=int(row[2]) if row[2] is not None else None,
        draft_at=row[3],
        live_version=int(row[4]) if row[4] is not None else None,
        max_call_duration_s=int(row[5]) if row[5] is not None else None,
        tts_voice=row[6],
        tts_provider=row[7],
        live_tts_voice=row[8],
        live_tts_provider=row[9],
    )


async def _overage_rate(session: AsyncSession, tenant_id: UUID) -> Decimal | None:
    """The DEAREST per-minute rate this plan can charge, or None when it states none.

    None is not zero. A missing rate means "we cannot tell you what this costs", and
    quoting ₹0.00 for a ten-minute call is the one answer that is actively wrong.

    **The dearest, because this feeds a worst case.** A plan may now quote two rates —
    `overage_rate` and `overage_rate_value`, the premium and value TTS rungs (D-36) —
    and which one a call bills at is decided by the voice that actually ran, which is
    not knowable in advance. A ceiling computed from the cheaper rung would promise a
    number the very next call can exceed, and a cost ceiling has exactly one direction
    of error it must not have.

    Taken as GREATEST rather than "the premium column", for the same reason
    `billing.service.split_overage` spends the included allowance on the dearer rung by
    PRICE rather than by label: the two columns are named for the rungs they price
    today, and a plan that ever quoted them the other way round would silently invert
    every guarantee that read the label instead of the number.
    """
    row = (
        await session.execute(
            text(
                # GREATEST ignores NULLs, so a plan quoting only one rate answers with
                # it — the same reason `billing/caps.py` uses LEAST for the cap pair.
                #
                # Resolved through `plan_in_effect_sql` rather than "newest row wins":
                # a quote is a promise about the NEXT call, so it must price on the plan
                # in force now, not on one an operator has staged for next month.
                plan_in_effect_sql("GREATEST(overage_rate, overage_rate_value)", at=NOW_SQL)
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or row[0] is None:
        return None
    return Decimal(str(row[0]))


def worst_case_cost(cap_s: int, rate_inr: Decimal | None) -> Decimal | None:
    """What one call that runs the whole cap costs, in NUMERIC INR (hard rule 7).

    Billed minutes are WHOLE minutes — `plans.overage_rate` is per minute and
    `billing/invoice.py` multiplies a minute quantity by it — so a 330s cap is six
    billable minutes, not five and a half. Rounding the duration DOWN here would
    understate the guarantee the cap exists to give, which is the only direction of
    error a cost ceiling must not have.
    """
    if rate_inr is None:
        return None
    minutes = Decimal((cap_s + 59) // 60)
    return to_paise(minutes * rate_inr)


def _pending_changes(row: _AgentRow) -> list[PendingChange]:
    if not row.has_pending or row.draft_version is None:
        return []
    entry = lane_of("script")
    return [
        PendingChange(
            field=entry.field,
            lane=entry.lane,
            staged_version=row.draft_version,
            live_version=row.live_version,
            staged_at=row.draft_at or datetime.min,
            # Version numbers only. A prompt body carries a client's prices and staff
            # names, and this string is destined for a banner and a log (rule 6).
            headline=(
                f"Script v{row.draft_version} is waiting to go live"
                + (f" (callers currently hear v{row.live_version})." if row.live_version else ".")
            ),
            why=entry.why,
        )
    ]


def _agent_voice(voice_id: str | None, provider: str | None) -> AgentVoice | None:
    """One stored voice as the API answers it, or None when the column is empty.

    The catalog lookup is best-effort ON PURPOSE. `agents.tts_voice` is free text
    (`voices.py` explains why the allowlist lives at the API rather than the schema), so
    a value we no longer offer must still read back as itself. Returning None for an
    unrecognised id would make an agent speaking a retired voice indistinguishable from
    one speaking none — and "none" is the reading that would send an operator to set a
    voice that is already set.
    """
    if not voice_id:
        return None
    return AgentVoice(voice_id=voice_id, provider=provider, catalog=get_voice(voice_id))


def _voice_headline(row: _AgentRow, configured: AgentVoice | None, live: AgentVoice | None) -> str:
    """The one sentence a banner can carry, composed where the facts are.

    Written here rather than in the UI for the reason the lane table is: a screen that
    paraphrases the configured/live relationship is how "voice applies immediately"
    becomes a support ticket. Names voices by their catalog LABEL where we have one and
    by their raw id otherwise — never a guess, and never silence.
    """
    if configured is None:
        return "No voice has been set on this agent."
    chosen = _reading(configured)
    if not row.published:
        return f"This agent is not on the voice platform yet; publishing it will use {chosen}."
    if not row.voice_diverged:
        return f"Callers hear {chosen} — the voice platform is holding the configured voice."
    if live is None:
        return (
            f"Callers hear whatever voice was last published; we have no record of which. "
            f"{chosen} reaches them at the next publish."
        )
    return f"Callers still hear {_reading(live)}; {chosen} reaches them at the next publish."


def _reading(voice: AgentVoice) -> str:
    """A voice in the words an operator picks on, degrading to the raw id."""
    return voice.catalog.label if voice.catalog else voice.voice_id


def _voice_state(row: _AgentRow) -> VoiceState:
    configured = _agent_voice(row.tts_voice, row.tts_provider)
    live = _agent_voice(row.live_tts_voice, row.live_tts_provider)
    return VoiceState(
        configured=configured,
        live=live,
        # `published`, not `is_live`: a PAUSED agent still has an engine object holding
        # a voice, and a republish still changes it. Using `is_live` here would tell an
        # operator that un-pausing is enough, which it is not.
        republish_required=row.published and row.voice_diverged,
        headline=_voice_headline(row, configured, live),
    )


async def _state(session: AsyncSession, tenant_id: UUID, agent_id: UUID) -> PendingState:
    row = await _load(session, agent_id)
    cap = effective_call_cap(row.max_call_duration_s)
    return PendingState(
        agent_id=agent_id,
        agent_status=row.status,
        published=row.published,
        has_pending=row.has_pending,
        pending=_pending_changes(row),
        effective_call_cap_s=cap,
        call_cap_is_platform_default=row.max_call_duration_s is None,
        worst_case_call_cost_inr=worst_case_cost(cap, await _overage_rate(session, tenant_id)),
        voice=_voice_state(row),
    )


async def pending_state_for(*, tenant_id: UUID, agent_id: UUID) -> PendingState:
    """What is staged, what it will cost, and what applies immediately.

    A pure READ — it is the view a client opens to find out why their edit has not
    taken effect, so per D-22 it must be reachable by someone who may only look.
    """
    async with tenant_session(tenant_id) as session:
        return await _state(session, tenant_id, agent_id)


async def apply_to_live(
    *, tenant_id: UUID, agent_id: UUID, expected_version: int | None = None
) -> ApplyResult:
    """ "Apply to live calls": move the applied pointer to the draft and publish.

    Three properties, each of which is a test:

    - **CAS, not last-write-wins** (BACKEND-PATTERNS §5). `expected_version` is the
      draft version the operator actually looked at. Applying "whatever is staged now"
      is how a colleague's half-finished script goes live under someone else's click.
      Passing None opts out deliberately — for a caller with no screen to be stale.
    - **Idempotent.** Nothing pending is `applied=False`, not an error: a
      double-clicked button, a retried request and a second operator on the same
      screen are all the same intent, already satisfied.
    - **The engine push is inside the transaction**, after the pointer write, so a
      vendor failure rolls the pointer back with it and our row never claims a script
      the engine does not hold (the `kb.publish_source` ordering argument).
    """
    async with tenant_session(tenant_id) as session:
        row = await _load(session, agent_id)
        if expected_version is not None and row.draft_version != expected_version:
            raise ProblemError.conflict(
                "stale_pending_change",
                "The staged script changed after this page was loaded.",
                remediation="Reload the agent and review the current draft before applying.",
            )
        if not row.has_pending:
            return ApplyResult(
                agent_id=agent_id,
                applied=False,
                # Not `or 0`: a pending-free agent whose draft pointer is NULL has no
                # script at all, and 0 is the honest "no version" for this field.
                live_version=row.live_version or 0,
                engine_synced=False,
            )

        result = await session.execute(
            text(
                "UPDATE agents SET live_prompt_id = system_prompt_id, updated_at = now() "
                "WHERE id = :aid AND deleted_at IS NULL "
                "AND system_prompt_id IS DISTINCT FROM live_prompt_id"
            ),
            {"aid": agent_id},
        )
        if rowcount_of(result) == 0:
            # Someone applied or undid between the read and the write.
            raise ProblemError.conflict(
                "stale_pending_change",
                "The staged script changed while this request was in flight.",
                remediation="Reload the agent and review the current draft before applying.",
            )
        if row.is_live:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    assert row.draft_version is not None  # has_pending implies it
    log.info(
        "agent_changes_applied",
        extra={
            "agent_id": str(agent_id),
            "version": row.draft_version,
            "from_version": row.live_version,
            "engine_synced": row.is_live,
        },
    )
    return ApplyResult(
        agent_id=agent_id,
        applied=True,
        live_version=row.draft_version,
        engine_synced=row.is_live,
    )


async def undo_staged(*, tenant_id: UUID, agent_id: UUID) -> UndoResult:
    """Discard the staged edits: the draft pointer returns to the applied version.

    A POINTER moves; no row is written and no row is deleted. `prompt_versions` stays
    the immutable history `agents/prompts.py` promises — the discarded version remains
    readable in the version list, and the next write is still max+1, so a number is
    never reused.

    This is not the "no pointer-rewind" rule being bent. That rule protects what the
    agent is RUNNING: `live_prompt_id` only ever moves forward, and Undo does not
    touch it. The draft pointer is mutable by definition — being able to move it back
    is what the word Undo means.

    Never reaches the engine: by construction the engine is already running the
    applied version, which is what Undo returns the draft to.
    """
    async with tenant_session(tenant_id) as session:
        row = await _load(session, agent_id)
        if not row.has_pending:
            return UndoResult(
                agent_id=agent_id,
                undone=False,
                discarded_version=None,
                live_version=row.live_version,
            )
        await session.execute(
            text(
                "UPDATE agents SET system_prompt_id = live_prompt_id, updated_at = now() "
                "WHERE id = :aid AND deleted_at IS NULL "
                "AND system_prompt_id IS DISTINCT FROM live_prompt_id"
            ),
            {"aid": agent_id},
        )
    log.info(
        "agent_changes_undone",
        extra={
            "agent_id": str(agent_id),
            "discarded_version": row.draft_version,
            "version": row.live_version,
        },
    )
    return UndoResult(
        agent_id=agent_id,
        undone=True,
        discarded_version=row.draft_version,
        live_version=row.live_version,
    )


async def set_call_cap(
    *, tenant_id: UUID, agent_id: UUID, max_call_duration_s: int | None
) -> CallCapResult:
    """Set (or clear) the per-agent max call length — the cost-runaway guard.

    FAST lane: a live agent is re-published in the SAME transaction, because a cap
    that only lands in our table protects nobody. That is safe here and was not safe
    before `live_prompt_id`: the republish sends the APPLIED script, so raising a
    guard cannot smuggle an unapproved script onto a live phone line.

    The transaction ordering is the guarantee that our row never over-promises. If the
    engine push fails, the column write rolls back with it, so there is no state in
    which we display a cap the engine is not enforcing.

    `None` clears the override and returns the agent to the platform default. It does
    NOT mean unlimited — see `effective_call_cap`. Values outside
    [CALL_CAP_MIN_S, CALL_CAP_MAX_S] are refused here with a usable problem+json
    rather than left to surface as an IntegrityError 500 from the CHECK, which is the
    floor under every other writer.
    """
    if max_call_duration_s is not None and not (
        CALL_CAP_MIN_S <= max_call_duration_s <= CALL_CAP_MAX_S
    ):
        raise ProblemError(
            kind="business_rule",
            code="call_cap_out_of_range",
            title="Call length cap out of range",
            detail=(
                f"A maximum call length must be between {CALL_CAP_MIN_S} and "
                f"{CALL_CAP_MAX_S} seconds."
            ),
            remediation=(
                "Send a value in that range, or null to use the platform default of "
                f"{CALL_CAP_DEFAULT_S} seconds. Null is the default, never 'unlimited'."
            ),
            fields=[
                {
                    "field": "max_call_duration_s",
                    "rule": "out_of_range",
                    "message": (
                        f"Must be {CALL_CAP_MIN_S}-{CALL_CAP_MAX_S} seconds, or null for "
                        "the platform default."
                    ),
                }
            ],
        )

    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text(
                "UPDATE agents SET max_call_duration_s = :cap, updated_at = now() "
                "WHERE id = :aid AND deleted_at IS NULL RETURNING status, engine_agent_ref"
            ),
            {"cap": max_call_duration_s, "aid": agent_id},
        )
        agent = result.first()
        if agent is None:
            raise ProblemError.not_found("Agent")
        is_live = str(agent[0]) == "live" and bool(agent[1])
        if is_live:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        rate = await _overage_rate(session, tenant_id)

    cap = effective_call_cap(max_call_duration_s)
    # Seconds and a boolean; nothing here identifies a caller (hard rule 6).
    log.info(
        "agent_call_cap_set",
        extra={"agent_id": str(agent_id), "cap_s": cap, "engine_synced": is_live},
    )
    return CallCapResult(
        agent_id=agent_id,
        max_call_duration_s=max_call_duration_s,
        effective_call_cap_s=cap,
        is_platform_default=max_call_duration_s is None,
        engine_synced=is_live,
        worst_case_call_cost_inr=worst_case_cost(cap, rate),
    )


__all__ = [
    "LANES",
    "PRECEDENCE_RULE",
    "AgentVoice",
    "ApplyResult",
    "CallCapResult",
    "Lane",
    "LaneEntry",
    "PendingChange",
    "PendingState",
    "UndoResult",
    "VoiceState",
    "apply_to_live",
    "lane_of",
    "pending_state_for",
    "set_call_cap",
    "undo_staged",
    "worst_case_cost",
]
