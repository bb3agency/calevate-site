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

from calevate_shared.engine import (
    AgentConfig,
    DisclosurePosture,
    VoiceEngine,
    compose_opening_line,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import CALL_CAP_DEFAULT_S, CALL_CAP_MAX_S, CALL_CAP_MIN_S
from apps.api.agents.service import effective_call_cap, publish_agent
from apps.api.agents.verification import EngineDrift, verify_publish
from apps.api.agents.voices import Voice, get_voice
from apps.api.billing.plans import NOW_SQL, plan_in_effect_sql
from apps.api.billing.service import to_paise
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.api.engine import engine_capabilities, get_engine

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
    # D-163. CONDUCT, not content — the same lane and the same precedence as the call cap,
    # and for the same reason: neither can change one word of the script. What they change
    # is what the agent does around it, and a compliance posture that only landed in our
    # table after somebody remembered to press Apply would be a screen making a claim
    # about a phone line that is not true yet. `set_disclosure_posture` republishes a live
    # agent in the same transaction, which is what puts them honestly on this side.
    LaneEntry(
        field="ai_disclosure_enabled",
        lane="live",
        precedence=2,
        why=(
            "Whether the agent announces it is an AI before anything else. It applies to "
            "the next call. It never changes the answer a caller gets when they ask "
            "outright — that answer is always the truth and cannot be switched off."
        ),
    ),
    LaneEntry(
        field="recording_notice_enabled",
        lane="live",
        precedence=2,
        why=(
            "Whether the agent says the call is being recorded before anything else. It "
            "applies to the next call. It does not stop the call being recorded, and it "
            "never changes the answer a caller gets when they ask whether it is."
        ),
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
class VerificationState:
    """WHAT WAS CONFIRMED, as opposed to what was sent (migration c1f6a94d2b07).

    `VoiceState` above splits CONFIGURED from SENT. This splits SENT from CONFIRMED, and
    it is the third field on this screen answering one shape of question, for the third
    time, for the same reason: a screen that renders one of two facts as "the" answer is
    wrong on exactly the agents where the difference matters.

    `state` is the stored verdict, so it is a fact about the LAST PUBLISH rather than
    about this instant. `agents/publishing.py::engine_drift_for` is the read that asks the
    engine right now — deliberately a separate, explicit call, because it costs a vendor
    round trip and a banner must not.
    """

    state: str
    verified_at: datetime | None
    #: True only for `applied`. Never true by default — an unread property is not a
    #: passed one, which is the entire `AgentSnapshot.*_readable` doctrine.
    confirmed: bool
    headline: str
    #: **CAN THIS DEPLOYMENT PUBLISH TO ITS VOICE PLATFORM AT ALL?** (D-281)
    #:
    #: Not a fact about this agent — a fact about the engine, read from
    #: `EngineCapabilities.hosts_agents()`. False means the selected platform's agents are
    #: programs deployed to it elsewhere, so there is no create endpoint and no prompt
    #: read-back, and `publish_agent` refuses every attempt by name.
    #:
    #: IT IS ON THIS OBJECT AND NOT A NEW ONE because a screen asking "what is the state
    #: of publishing for this agent" must get one answer, and "unverified, and also
    #: impossible" from two endpoints is how a console comes to offer a button a route
    #: refuses — the divergence D-93 exists to remove. Every other field here describes a
    #: publish that HAPPENED; this one says whether the next one can.
    publishable: bool


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
    #: What a read-back CONFIRMED at the last publish. Not a member of `pending` for the
    #: same reason `voice` is not: neither Apply nor Undo acts on it, and an unconfirmed
    #: publish is cleared by publishing again, not by moving a pointer.
    engine_verification: VerificationState
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


#: The two toggles, keyed by the column they write. The API's request model, the audit
#: action names and the lane table are all derived from this mapping rather than each
#: spelling the pair out — a third toggle would otherwise be three edits and a fourth
#: place to forget one. `lane_of` reads the same field names.
DISCLOSURE_TOGGLES: dict[str, str] = {
    "ai_disclosure_enabled": "agent.ai_disclosure",
    "recording_notice_enabled": "agent.recording_notice",
}


def audit_action_for(field: str, *, enabled: bool) -> str:
    """The `audit_log.action` for one toggle flip — WHICH toggle and WHICH way, in the row.

    NOT a single `agent.disclosure_changed` with the detail in `summary`, and that is the
    whole point rather than a style choice: `write_audit` deliberately does NOT persist
    `summary` (there is no such column — it goes to the JSONL log stream, keyed by entry
    id). So anything that must survive in the hash-chained LEDGER has to be in a column,
    and `action` is the only column with room for it. A regulator asking "when did this
    client stop announcing their agent as an AI, and who decided" is answered by one
    indexed read of `audit_log`, not by joining a ledger to a log shipper.
    """
    return f"{DISCLOSURE_TOGGLES[field]}_{'enabled' if enabled else 'disabled'}"


@dataclass(frozen=True, slots=True)
class DisclosureResult:
    """What an agent now volunteers, after one toggle flip."""

    agent_id: UUID
    ai_disclosure_enabled: bool
    recording_notice_enabled: bool
    #: What callers actually hear first, composed server-side. Empty string = the agent
    #: volunteers nothing and opens on its script.
    opening_line: str
    #: Did the change reach the voice platform? False for an agent that is not live —
    #: there is nothing to push to, and the next publish carries it.
    engine_synced: bool
    #: The fields this call actually changed, so a caller (and the audit writer above it)
    #: can tell a real flip from a re-assertion of the state that was already there.
    changed: tuple[str, ...]


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
    verify_state: str
    verified_at: datetime | None

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
    "a.live_tts_provider, a.live_verify_state, a.live_verified_at FROM agents a "
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
        verify_state=str(row[10]),
        verified_at=row[11],
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


# One sentence per stored verdict, composed here for the reason `_voice_headline` is:
# a screen that paraphrases "we could not read it back" as "not live" is how an operator
# is sent to re-publish a working agent, and paraphrasing it as "live" is how a client is
# told their disclosure line is being spoken when nobody checked.
_VERIFY_HEADLINE: dict[str, str] = {
    "applied": "The voice platform was read back and is running this script and voice.",
    "unreadable": (
        "The voice platform accepted this publish; it did not report back enough for us "
        "to confirm it is running it. Publish again to re-check."
    ),
    "unreachable": (
        "The voice platform accepted this publish and did not answer when we read it "
        "back, so we cannot confirm it is running it. Publish again to re-check."
    ),
    "unverified": (
        "This agent was published before we started reading the voice platform back, so "
        "what it is running has never been confirmed. Publish again to confirm it."
    ),
}


def _verification_state(row: _AgentRow) -> VerificationState:
    # THE ENGINE'S OWN ANSWER, ASKED FIRST (D-281). `engine_capabilities()` is synchronous
    # and makes no network call — `VoiceEngine.capabilities` is an attribute precisely so a
    # screen deciding whether to render a control can read it — so this costs a dict lookup
    # and buys the console the one thing it could not previously know: that Publish will
    # refuse whatever this agent's own columns say.
    publishable = engine_capabilities().hosts_agents()
    if not publishable:
        return VerificationState(
            state=row.verify_state,
            verified_at=None,
            confirmed=False,
            # It OUTRANKS the two sentences below, and that is the point rather than an
            # ordering accident: "not on the platform yet" invites an operator to press
            # Publish, and on this engine pressing it can only ever fail. Told before the
            # attempt, in our own vocabulary and without naming the vendor (hard rule 2).
            headline=(
                "The voice platform for this account does not host agents built here, so "
                "this agent cannot be published to it."
            ),
            publishable=False,
        )
    if not row.published:
        return VerificationState(
            state=row.verify_state,
            verified_at=None,
            confirmed=False,
            headline="This agent is not on the voice platform yet; there is nothing to confirm.",
            publishable=True,
        )
    return VerificationState(
        state=row.verify_state,
        # Only ever set alongside `applied` (`publish_agent` passes NULL otherwise), and
        # re-derived here rather than trusted, so a hand-edited row cannot make an
        # unconfirmed agent render a confirmation time.
        verified_at=row.verified_at if row.verify_state == "applied" else None,
        confirmed=row.verify_state == "applied",
        headline=_VERIFY_HEADLINE.get(
            row.verify_state,
            "We hold no readable verdict about what the voice platform is running.",
        ),
        publishable=True,
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
        engine_verification=_verification_state(row),
    )


async def pending_state_for(*, tenant_id: UUID, agent_id: UUID) -> PendingState:
    """What is staged, what it will cost, and what applies immediately.

    A pure READ — it is the view a client opens to find out why their edit has not
    taken effect, so per D-22 it must be reachable by someone who may only look.
    """
    async with tenant_session(tenant_id) as session:
        return await _state(session, tenant_id, agent_id)


#: One RUNNING arm of this agent's script test, found by the engine ref its route names.
#: Same joins and the same four columns as `service._VARIANT_CONFIG_SQL`, narrowed to one
#: arm — the arms' configuration has exactly one definition and this is a lookup into it,
#: not a second copy of it.
_ARM_BY_ENGINE_REF_SQL = (
    "SELECT v.id, v.label, v.disclosure_line, pv.body "
    "FROM prompt_experiment_variants v "
    "JOIN prompt_experiments e ON e.id = v.experiment_id "
    "JOIN prompt_versions pv ON pv.id = v.prompt_version_id "
    "WHERE e.agent_id = :aid AND e.status = 'running' AND v.engine_agent_ref = :ref"
)


async def engine_drift_for(
    *, tenant_id: UUID, agent_id: UUID, engine_agent_ref: str | None = None
) -> EngineDrift:
    """Ask the ENGINE, right now, what it is running — and compare it with our row.

    WHICH VENDOR OBJECT (D-380). An agent owns one row in `engine_agent_routes` for
    itself and one more for each arm of a RUNNING script test
    (`service.publish_variant`). The scheduled sweep claims ROUTES and passed only the
    agent id, so it read the agent's own object back once per route and stamped that
    verdict onto the ARM's row — a verdict about a different vendor object. The arms are
    the traffic actually under test: each has its own script and its own AI-disclosure
    sentence, each answers real callers, and neither was ever read back after the publish
    that created it. Somebody editing an arm in the vendor's console — or a vendor
    prompt-length ceiling truncating `TRUTHFUL_ANSWER_DIRECTIVE` off the end of it — was
    invisible to every instrument this repository has, indefinitely. Hard rule 5 requires
    that directive verified "on every publish and every drift sweep"; for arms only the
    first half was true.

    So `engine_agent_ref` names the object to compare, and when it belongs to a running
    arm the comparison is against THAT ARM's config, built by `service._variant_config` —
    the same builder the publish uses, for the reason that function already gives. Omitted
    (the on-demand endpoint, which is about the agent) or naming the agent's own ref, the
    behaviour is exactly what it was.

    A ref matching neither is compared against the agent, unchanged: the only writers of
    `engine_agent_routes` are `publish_agent` and `publish_variant`, and
    `experiments.conclude` deactivates an arm's route when it retires, so an ACTIVE route
    is one or the other. Inventing a verdict for a state nothing can produce would be a
    branch no test can reach.

    THE CASE `live_verify_state` STRUCTURALLY CANNOT COVER. That column records what a
    read-back found AT THE LAST PUBLISH. Two divergences appear afterwards and neither
    involves any code of ours running:

    * somebody edits the agent in the VENDOR'S OWN DASHBOARD. Our row is untouched, so
      every table we own agrees with itself and is wrong.
    * a publish failed on OUR side after the vendor committed — a connection reset on the
      response, a soft-delete landing between the write and the UPDATE. Our transaction
      rolled back to the previous script; the engine kept the new one. The divergence
      points the OTHER WAY, and re-reading our own tables can never find it.

    So this is a read of THEIRS, and it is a separate explicit endpoint rather than part
    of the pending banner because it costs a vendor round trip: a banner that silently
    dialled the vendor on every page load would be a rate-limit incident wearing a
    reassurance.

    A READ, not a repair. It reports; it writes nothing and it does not re-publish. What
    to do about a drift is a decision with a blast radius (re-publishing overwrites
    whatever the vendor's dashboard was used to change, which may have been the correct
    emergency edit), and this function exists so a human can make it with evidence.

    Reuses `service._to_config` so the comparison is against the EXACT config a publish
    would send. Rebuilding a config here would compare the engine against a second
    rendering of our intent, and the two would drift on the field nobody looks at — which
    is the defect `_variant_config` is built on `_to_config` to avoid.
    """
    from apps.api.agents.service import _load_agent, _to_config, _variant_config

    engine = get_engine()
    # Both branches resolve INSIDE the session and the vendor round trip happens outside
    # it — returning `await _drift_of(...)` from in here would pin a pooled connection for
    # the length of a third party's response, which is the cost this function has always
    # declined to pay.
    async with tenant_session(tenant_id) as session:
        row = await _load_agent(session, tenant_id, agent_id)
        ref = row["engine_agent_ref"]
        arm = None
        if engine_agent_ref is not None and engine_agent_ref != ref:
            arm = (
                await session.execute(
                    text(_ARM_BY_ENGINE_REF_SQL), {"aid": agent_id, "ref": engine_agent_ref}
                )
            ).first()
        if arm is not None and engine_agent_ref is not None:
            # The arm IS a published vendor object in its own right, so `not_published`
            # cannot apply to it and the agent's own ref is irrelevant to this comparison.
            target, config = (
                engine_agent_ref,
                _variant_config(
                    tenant_id,
                    row,
                    UUID(str(arm[0])),
                    str(arm[1]),
                    str(arm[3]),
                    str(arm[2]),
                    engine=engine,
                ),
            )
        else:
            # `not_published` COVERS THE EXTERNALLY-DEPLOYED ENGINE TOO, and it does so
            # truthfully rather than by luck (D-281): `publish_agent` refuses on such an
            # engine, so no agent can hold an `engine_agent_ref` on it, so this branch is
            # the one every agent takes. It needs no new state and no migration — "this
            # agent is not on the voice platform" is exactly what is true — and the
            # sentence below is already the right one to show. What it must NOT do is fall
            # through to `verify_publish`, which would ask an engine that has no prompt to
            # read back; that guard is in `verify_publish` itself, so a future caller
            # cannot lose it.
            if not isinstance(ref, str) or not ref:
                return EngineDrift(
                    agent_id=str(agent_id),
                    engine=engine.name,
                    engine_agent_ref=None,
                    checked=False,
                    state="not_published",
                    prompt_applied=None,
                    disclosure_applied=None,
                    prompt_disclosure_applied=None,
                    truthful_answer_applied=None,
                    voice_applied=None,
                    detail=(
                        "This agent is not on the voice platform, so there is nothing to compare."
                    ),
                )
            target, config = ref, _to_config(tenant_id, row, engine=engine)

    return await _drift_of(engine, agent_id, target, config)


async def _drift_of(
    engine: VoiceEngine, agent_id: UUID, ref: str, config: AgentConfig
) -> EngineDrift:
    """Read ONE vendor object back and render the comparison.

    Split out of `engine_drift_for` when the arm case arrived (D-380) rather than copied
    into it: the two differ only in which config is compared against which ref, and a
    second rendering would be a second place for the `not_applied` sentence and the
    hard-rule-6 log line to be got wrong.
    """
    verdict = await verify_publish(engine, ref, config)
    log.info(
        "agent_engine_drift_checked",
        extra={
            "agent_id": str(agent_id),
            "engine": engine.name,
            # A vendor-issued opaque id, which is what `_reclaim_orphan` already logs for
            # the same reason: it names WHICH object was scored without naming a tenant's
            # script (hard rule 6).
            "engine_agent_ref": ref,
            "verify_state": verdict.state,
        },
    )
    return EngineDrift(
        agent_id=str(agent_id),
        engine=engine.name,
        engine_agent_ref=ref,
        checked=True,
        state=verdict.state,
        prompt_applied=verdict.prompt_applied,
        disclosure_applied=verdict.disclosure_applied,
        prompt_disclosure_applied=verdict.prompt_disclosure_applied,
        truthful_answer_applied=verdict.truthful_answer_applied,
        voice_applied=verdict.voice_applied,
        detail=(
            # `verify_publish`'s wording assumes a write just happened. Here nothing did,
            # so the one verdict whose sentence would be actively misleading is respelled.
            "The voice platform is running a different script, opening line, "
            "truthful-answer rule or voice from the one this agent last published."
            if verdict.state == "not_applied"
            else verdict.detail
        ),
    )


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


async def set_disclosure_posture(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    ai_disclosure_enabled: bool | None,
    recording_notice_enabled: bool | None,
) -> DisclosureResult:
    """Switch either opening notice on or off for one agent (D-163).

    THE FOUNDER'S DECISION, IMPLEMENTED RATHER THAN SOFTENED. SEC-COMP §2's two
    call-level invariants — "this is an AI" and "this call is recorded" — are two
    obligations under two regimes (TRAI/UCC and DPDP notice-and-consent) that shared one
    column, so a client could have both or neither. Each is now its own toggle, on
    inbound and outbound agents alike, and a toggle switched off means the agent does not
    VOLUNTEER that fact at the top of the call.

    WHAT NO ARGUMENT HERE CAN REACH. Asked outright — "am I talking to a person?", "is
    this being recorded?" — the agent answers truthfully, on every agent, always. That
    behaviour is `calevate_shared.engine.TRUTHFUL_ANSWER_DIRECTIVE`: a `Final` in the
    portability contract with no writer anywhere in this repository, appended by every
    adapter to every prompt, and verified on read-back by `agents/verification.judge`,
    which REFUSES a publish whose engine copy has lost it. A client-authored script
    cannot withdraw it because the script is a different string and the directive is
    appended after it, saying so in words.

    FAST LANE, and the republish is inside the transaction. A posture that lands only in
    our table is a screen making a claim about a phone line that is not true yet, and the
    direction of that lie is unbounded in both directions — an agent still announcing a
    notice its owner withdrew, or (worse) our records saying it announces one when the
    engine was never told. The ordering is `set_call_cap`'s: column write, then the engine
    push, so a vendor failure rolls the column back with it.

    `None` on either argument means "leave this one alone", so the two toggles can be
    flipped independently by one endpoint without a partial write ever meaning "set the
    other one to false".

    IDEMPOTENT. Re-asserting the state an agent is already in changes nothing, publishes
    nothing and reports `changed=()` — which is what stops a double-clicked switch writing
    two ledger entries for one decision.
    """
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT ai_disclosure_enabled, recording_notice_enabled, "
                    "ai_disclosure_line, recording_notice_line, status, engine_agent_ref "
                    "FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
                ),
                {"aid": agent_id},
            )
        ).first()
        if row is None:
            raise ProblemError.not_found("Agent")
        wanted = {
            "ai_disclosure_enabled": (
                bool(row[0]) if ai_disclosure_enabled is None else ai_disclosure_enabled
            ),
            "recording_notice_enabled": (
                bool(row[1]) if recording_notice_enabled is None else recording_notice_enabled
            ),
        }
        current = {
            "ai_disclosure_enabled": bool(row[0]),
            "recording_notice_enabled": bool(row[1]),
        }
        changed = tuple(field for field in DISCLOSURE_TOGGLES if wanted[field] != current[field])
        posture = DisclosurePosture(
            ai_disclosure_line=str(row[2]),
            ai_disclosure_enabled=wanted["ai_disclosure_enabled"],
            recording_notice_line=str(row[3]),
            recording_notice_enabled=wanted["recording_notice_enabled"],
        )
        is_live = str(row[4]) == "live" and bool(row[5])
        if changed:
            await session.execute(
                text(
                    "UPDATE agents SET ai_disclosure_enabled = :ai, "
                    "recording_notice_enabled = :rec, updated_at = now() "
                    "WHERE id = :aid AND deleted_at IS NULL"
                ),
                {
                    "ai": wanted["ai_disclosure_enabled"],
                    "rec": wanted["recording_notice_enabled"],
                    "aid": agent_id,
                },
            )
            if is_live:
                await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    # Ids, booleans and field NAMES. The sentences themselves are a client's own business
    # copy and stay out of the log (hard rule 6's neighbourhood — they are not PII, but
    # nothing is served by putting them in a log line either).
    log.info(
        "agent_disclosure_posture_set",
        extra={
            "agent_id": str(agent_id),
            "ai_disclosure_enabled": posture.ai_disclosure_enabled,
            "recording_notice_enabled": posture.recording_notice_enabled,
            "changed": list(changed),
            "engine_synced": bool(changed) and is_live,
        },
    )
    return DisclosureResult(
        agent_id=agent_id,
        ai_disclosure_enabled=posture.ai_disclosure_enabled,
        recording_notice_enabled=posture.recording_notice_enabled,
        opening_line=compose_opening_line(posture),
        engine_synced=bool(changed) and is_live,
        changed=changed,
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
    "DISCLOSURE_TOGGLES",
    "LANES",
    "PRECEDENCE_RULE",
    "AgentVoice",
    "ApplyResult",
    "CallCapResult",
    "DisclosureResult",
    "EngineDrift",
    "Lane",
    "LaneEntry",
    "PendingChange",
    "PendingState",
    "UndoResult",
    "VerificationState",
    "VoiceState",
    "apply_to_live",
    "audit_action_for",
    "engine_drift_for",
    "lane_of",
    "pending_state_for",
    "set_call_cap",
    "set_disclosure_posture",
    "undo_staged",
    "worst_case_cost",
]
