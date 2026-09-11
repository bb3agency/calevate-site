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
                                  engine; the response said `republish_required`.
                                  CLOSED BY D-586 — see below.
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
- **voice** is delivery. Immediate per §2b, and since D-586 the CODE is immediate too:
  `set_agent_voice` below writes the row and re-publishes a live agent in the same
  transaction, exactly as the cap and the two notice toggles do. `PendingState.voice`
  still reports configured-vs-sent as two fields, because a PAUSED or draft agent, and
  an agent published before the mirror existed, still make them two facts.
- **extraction fields** shape CRM columns, not the call. Immediate.
- **training (T0)** is immediate, with one documented exception in `agents/t0.py`: a
  recompile splices into the DRAFT body, so while a script edit is staged the
  recompile stages with it rather than dragging an unapproved script live.

THE CONFLICT BETWEEN THE DOCS AND THE CODE, CLOSED BY D-586 (11 Sep 2026)
--------------------------------------------------------------------------------
This section used to REPORT an open conflict: §2b put voice on the IMMEDIATE side and
`LANES` said so, while `set_agent_voice` did not reach the engine — so a voice change
on a live agent was in practice STAGED until someone published, under a screen reading
"Applies straight away". The two options were named as decision-log entries rather than
a quiet edit, and the founder took the first: auto-republish.

The ear-test objection that held it (`voice_routes.py`, pilot gate 3 — "silently
re-voicing a running agent is not a safe default") is answered rather than ignored. It
was an argument about WHO was choosing: an operator re-voicing somebody else's live
phone line from a console the client cannot see. The voice is now the CLIENT's own
choice, made on their own agent from a picker that plays the voice before it is picked,
and the change they just made is the one they are asking for. Nothing is silent — the
request is the consent — and the alternative is worse in exactly the way this module
exists to stop: a screen that says the voice changed over a phone line that did not.

What did NOT change: the republish sends the APPLIED script (`live_prompt_id`), so a
voice change still cannot drag an unapproved draft onto a live line, and a PAUSED or
draft agent is not published by a voice write — `publish_agent` writes
`status = 'live'`, so republishing one would put a switched-off agent back on the
frontline as a side effect of a delivery change. For those, `PendingState.voice` still
reports the configured voice and the sent voice as two fields.

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
from typing import Final, Literal
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
from apps.api.agents.voice_offer import (
    VoiceReasonAudience,
    cartesia_tier_could_be_offered,
    count_live_cartesia_agents,
    read_curation,
    unofferable_reason,
)
from apps.api.agents.voices import (
    Voice,
    get_voice,
    voice_selection_capability,
)
from apps.api.billing.lots import voice_tier_rates
from apps.api.billing.plans import NOW_SQL, OVERAGE_RATE_SECOND_SQL, plan_in_effect_sql
from apps.api.billing.service import to_paise
from apps.api.compliance.caller_memory import spdi_refuses_memory
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.api.engine import engine_capabilities, engine_lacks, get_engine

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
        why=(
            "A voice only changes delivery. It cannot change what is said or decided, "
            "so it applies to the next call."
        ),
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

    THE WHOLE POINT IS THAT THESE ARE TWO FIELDS, AND D-586 DID NOT COLLAPSE THEM.
    `set_agent_voice` now re-publishes a LIVE agent in the same transaction, so on a live
    agent the two converge on the write. They stay two facts everywhere else, and every
    one of those states is reachable:

        draft / not published   nothing is on the engine to hold a voice
        paused                  an engine object exists and still holds the OLD voice;
                                a voice write deliberately does not republish it,
                                because `publish_agent` writes `status = 'live'` and a
                                delivery change must not put a switched-off agent back
                                on the frontline
        published pre-mirror    `live_tts_voice` is NULL; a sync we cannot prove

    Answering with one of them and calling it "the voice" is the same defect
    `live_prompt_id` was added to fix for the script and that `set_call_cap`'s
    in-transaction republish avoids for the cap — twice already, under two other names.

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
    what does one runaway call cost me — computed from the dearest minute this account can
    actually be charged (`worst_case_rate`: the plan's overage rate, or, for a prepaid
    account that has no plan row at all, its own credit lots' rate). `None` still means "we
    cannot say", and now means it only when nothing on the account can price a minute.
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
    # put an Undo next to a change it cannot undo. Since D-586 a divergence on a LIVE
    # agent cannot outlive the write that created it (`set_agent_voice` republishes), so
    # what is left here is a draft agent, a PAUSED one, and an agent published before the
    # mirror existed — none of which Apply or Undo acts on either. It is cleared by a
    # PUBLISH, which is what `_next_step` says. (Apply clears it as a side effect when a
    # script is ALSO staged, because `apply_to_live` publishes; the mirror is written by
    # `publish_agent` wherever it is called from, so the answer stays correct either way.)
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
class CallerMemoryResult:
    """What one agent's caller-continuity switch is now, after a flip (D-513)."""

    agent_id: UUID
    enabled: bool
    #: What callers actually hear first, recomposed. When memory goes ON this GAINS the
    #: `caller_memory_notice_line` sentence and when it goes off it loses it — which is the
    #: property D-507 made unconstructible to violate, surfaced here so the screen shows the
    #: client the sentence their callers will now hear rather than describing it.
    opening_line: str
    #: Did the change reach the voice platform? False for an agent that is not live — there
    #: is nothing to push to, and the next publish carries it.
    engine_synced: bool
    #: True when this call was a no-op because the switch was already where it was asked to
    #: be. Lets the route write one audit row per DECISION rather than per double-click.
    unchanged: bool
    #: When this business attested that its calls are safe to remember. `None` only on the
    #: OFF path, which needs no attestation.
    attested_at: datetime | None
    #: WHO confirmed it, by name. `None` when nobody has, and also when the person who did
    #: has since left — the attestation is the organisation's, so the row survives them
    #: (`caller_memory_attested_by` is `ON DELETE SET NULL`).
    #:
    #: IT IS HERE BECAUSE A CLIENT SWITCHING A SECOND AGENT ON IS NOT ASKED AGAIN, and a
    #: permission that silently does not apply to you is one nobody can audit from their
    #: own screen. "Confirmed by Asha on 2 September" is the sentence that makes "we did
    #: not ask you this time" explicable. The audit ledger is the durable record of the
    #: act; this is the one a client can read.
    attested_by_name: str | None


@dataclass(frozen=True, slots=True)
class VoiceWriteResult:
    """What one agent speaks in after a voice write, and whether the phone line agrees.

    The fields are the ones `SetVoiceOut` has always carried, with two of them turned from
    assumptions into measurements by D-586: `engine_synced` was a hard-coded `False` (this
    endpoint never reached the engine) and is now what actually happened, and
    `republish_required` is now false on a live agent because the republish already
    happened inside the transaction.
    """

    agent_id: UUID
    voice: Voice
    agent_status: str
    #: The agent exists on the engine (`engine_agent_ref` is set) — true for a PAUSED
    #: agent too, which is why it is not `is_live`.
    published: bool
    #: The voice reached the voice platform on THIS request.
    engine_synced: bool
    #: What the engine was last SENT (`agents.live_tts_voice`), re-read after any push.
    live_voice_id: str | None
    #: Published AND the engine is not holding the configured voice. A null
    #: `live_voice_id` counts as different: a sync we cannot prove is not a sync.
    republish_required: bool
    #: False when the row already held this voice — the second click, or the retry of a
    #: request whose response was lost. Lets the route write one audit row per decision.
    changed: bool


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
    `overage_rate` and `overage_rate_second`, the plan's two overage-rate slots (D-36) —
    and which one a call bills at is decided by the rung it is metered on, which is not
    knowable in advance. A ceiling computed from the cheaper rung would promise a
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
                plan_in_effect_sql(f"GREATEST(overage_rate, {OVERAGE_RATE_SECOND_SQL})", at=NOW_SQL)
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or row[0] is None:
        return None
    return Decimal(str(row[0]))


async def _credit_lot_rate(session: AsyncSession, tenant_id: UUID) -> Decimal | None:
    """The DEAREST per-minute rate this WALLET can charge, or None when nothing can price a
    minute — the prepaid answer to the question `_overage_rate` answers for a plan.

    **A PREPAID ACCOUNT HAS NO PLAN ROW**, which is not a defect and is said outright by the
    metering path (`workers/pipeline.py`: the prepaid tiers are the ones with no plan to
    read). So `_overage_rate` answered None for every one of them and the screen said "we
    cannot put a number on it" one cell away from the very rate it was already rendering —
    the lot rate, on the same response. Under D-547 that lot rate is the real price of a
    minute for these accounts: what a call costs is the rate frozen on the credit lot it
    draws from (`billing/lots.voice_tier_rates`, oldest lot first), so it is the figure a
    worst case must be struck from.

    DEAREST BY PRICE, NEVER BY TIER NAME, for `_overage_rate`'s reason exactly: a ceiling
    computed from the cheaper of the two rates promises a number the very next call can
    exceed, and which tier runs a given call is not knowable in advance. Taking the maximum
    of the rates themselves — rather than "the Cartesia one" — also survives a wallet whose
    two lots were sold at rates the other way round.

    None when NO tier can be priced, which is the empty or overdrawn wallet: there is no
    open lot, so there is no rate, and a card figure would be a guess about a purchase
    nobody has made (`billing/lots.TierRate`).
    """
    quoted = [
        tier.inr_per_min
        for tier in await voice_tier_rates(session, tenant_id=tenant_id)
        if tier.inr_per_min is not None
    ]
    return max(quoted) if quoted else None


async def worst_case_rate(session: AsyncSession, tenant_id: UUID) -> Decimal | None:
    """THE ONE DOOR to "what is the dearest minute this account can be charged": the plan's
    rate when it quotes one, else the wallet's.

    The order is the order the money itself resolves in — a committed plan's overage rate is
    what a bundled account is billed at, and a prepaid account is billed off its lots — so
    this is not a fallback chain looking for any number, it is each tier's own answer asked
    in turn. Both callers of a worst case go through it, so the cap screen and the cap WRITE
    cannot quote different ceilings for one account.
    """
    # `is not None`, never `or`: a plan that genuinely quotes ₹0 a minute is a real answer
    # and `Decimal("0")` is falsy, so `or` would silently price that account off its lots.
    plan_rate = await _overage_rate(session, tenant_id)
    if plan_rate is not None:
        return plan_rate
    return await _credit_lot_rate(session, tenant_id)


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
        worst_case_call_cost_inr=worst_case_cost(cap, await worst_case_rate(session, tenant_id)),
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
    from apps.api.agents.handoff import spec_for
    from apps.api.agents.service import _load_agent, _to_config, _variant_config

    engine = get_engine()
    # Both branches resolve INSIDE the session and the vendor round trip happens outside
    # it — returning `await _drift_of(...)` from in here would pin a pooled connection for
    # the length of a third party's response, which is the cost this function has always
    # declined to pay.
    async with tenant_session(tenant_id) as session:
        row = await _load_agent(session, tenant_id, agent_id)
        # WHO A PUBLISH RIGHT NOW WOULD SEND (D-533), resolved through the ONE resolver
        # the publish itself uses. Not optional and not a shortcut: the destination is a
        # function of the clock, so a sweep that rebuilt it any other way — or skipped it —
        # would score every agent published in the morning as drifted by nightfall, for the
        # entirely correct reason that the roster has gone off duty. Same rule at both ends
        # or this is a false-alarm generator, which is `_to_config`'s own argument about
        # rebuilding a config here.
        handoff, _duty = await spec_for(session, dict(row))
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
                    handoff=handoff,
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
                    handoff_applied=None,
                    detail=(
                        "This agent is not on the voice platform, so there is nothing to compare."
                    ),
                )
            target, config = ref, _to_config(tenant_id, row, engine=engine, handoff=handoff)

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
        handoff_applied=verdict.handoff_applied,
        detail=(
            # `verify_publish`'s wording assumes a write just happened. Here nothing did,
            # so the one verdict whose sentence would be actively misleading is respelled.
            #
            # IT ENUMERATES `judge`'s `checked` TUPLE AND MUST KEEP DOING SO. The
            # handover destination joined that tuple with D-533 and this sentence did
            # not, so the one drift a roster can produce read back as "a different
            # script, opening line, truthful-answer rule or voice" — four properties
            # that are all identical — and sent whoever opened the screen looking at
            # the script. A verdict that names the wrong cause is worse than a verdict
            # with no detail at all.
            "The voice platform is running a different script, opening line, "
            "truthful-answer rule, voice or handover destination from the one this "
            "agent last published."
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
                    "ai_disclosure_line, recording_notice_line, status, engine_agent_ref, "
                    # Read but NOT settable here: this route toggles the two D-163
                    # switches, and the memory sentence has none of its own (D-507). It is
                    # selected so the recomposed opening carries it — a toggle flip that
                    # dropped the memory sentence would republish an agent that still
                    # remembers callers and has stopped saying so.
                    "caller_memory_notice_line, caller_memory_enabled "
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
            caller_memory_notice_line=str(row[6]),
            caller_memory_enabled=bool(row[7]),
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


#: The sentence a client accepts to switch cross-call memory on, stored nowhere and
#: rendered by the API so the screen and the refusal cannot describe different promises.
#:
#: IT IS AN ATTESTATION AND NOT A CHECKBOX ON A FORM, which is why it is phrased as a
#: statement in the first person about facts only the client knows.
#: `compliance.caller_memory.SPDI_REFUSED_VERTICALS` says of itself that it is "a PROXY AND
#: KNOWN TO BE ONE ... the enable path — when one is built — is where a per-tenant
#: attestation belongs". This is that instrument, and the proxy stays above it as the belt:
#: a clinic is refused whatever it attests, because the vertical is a RECORD and an
#: attestation is a CLAIM.
CALLER_MEMORY_ATTESTATION = (
    "I confirm that these calls do not collect health, medical, financial, biometric or "
    "other sensitive personal data about callers, that my business is the Data Fiduciary "
    "for these callers, and that my own privacy notice tells them we keep a short note of "
    "what they ask about. I understand that my agents will say so at the start of every "
    "call, that notes are kept for 180 days, and that a caller may ask for theirs to be "
    "erased."
)


async def set_caller_memory(
    *, tenant_id: UUID, agent_id: UUID, enabled: bool, attested_by: UUID | None
) -> CallerMemoryResult:
    """Switch CALLER CONTINUITY on or off for one agent (D-513). Returns the new state.

    **ONE SWITCH, TWO ABILITIES, AND THAT IS THE FOUNDER'S DECISION RATHER THAN A
    SHORTCUT.** The client-facing copy calls cross-call memory and auto-reschedule callbacks
    "two linked abilities, always on or off together", so `agents.caller_memory_enabled` is
    the ONE column both read and `compliance.caller_memory.memory_enabled` is the ONE reader
    (D-514's callback path uses it too). A second column would let a client switch off the
    thing their callers were told about and keep the thing that reuses it.

    **THE ATTESTATION IS REQUIRED TO TURN IT ON AND IS NOT REQUIRED TO TURN IT OFF.** It is
    a permission, and a permission is asked for when the risk is taken, never when it is
    given up. It is recorded on `organizations` because the attested fact is about the
    BUSINESS, so a client with four agents answers once — and a client who has already
    attested may switch a second agent on without being asked again, which is the whole
    reason it is not an agent column.

    **THE SPDI REFUSAL SITS ABOVE THE ATTESTATION AND CANNOT BE ATTESTED PAST** (D-507(b)).
    A tenant on a refused vertical is told no here rather than being allowed to set a column
    that `remember()` would then silently ignore — the state "the switch reads true and the
    store stays empty" is an operator mystery, and it is one this route can simply not
    create.

    **FAST LANE, AND THE REPUBLISH IS INSIDE THE TRANSACTION**, exactly as
    `set_disclosure_posture` and `set_call_cap`: a live agent whose column moved is
    re-published before this returns, so the SPOKEN NOTICE and the prompt's memory section
    land on the phone line at the same moment the screen changes. That ordering is the whole
    compliance guarantee here — a column that said "remembers" while the engine still held a
    greeting that did not mention it is precisely the state D-507 made unconstructible, and
    an engine push after the commit would reintroduce it for the width of one vendor call.

    IDEMPOTENT. Re-asserting the state an agent is already in changes nothing, publishes
    nothing and reports `unchanged=True`.
    """
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT a.caller_memory_enabled, a.ai_disclosure_line, "
                    "a.ai_disclosure_enabled, a.recording_notice_line, "
                    "a.recording_notice_enabled, a.caller_memory_notice_line, a.status, "
                    "a.engine_agent_ref, o.vertical_template, o.caller_memory_attested_at, "
                    # LEFT JOIN, never inner: the attester is nullable twice over — nobody
                    # has attested yet, or the person who did has left and the FK went to
                    # NULL. An inner join would drop the whole agent row for either, which
                    # is a 404 on a switch because somebody was offboarded.
                    "u.name "
                    "FROM agents a JOIN organizations o ON o.id = a.tenant_id "
                    "LEFT JOIN users u ON u.id = o.caller_memory_attested_by "
                    "WHERE a.id = :aid AND a.deleted_at IS NULL FOR UPDATE OF a"
                ),
                {"aid": agent_id},
            )
        ).first()
        if row is None:
            raise ProblemError.not_found("Agent")
        current = bool(row[0])
        vertical = None if row[8] is None else str(row[8])
        attested_at: datetime | None = row[9]
        attested_by_name: str | None = None if row[10] is None else str(row[10])

        if enabled and spdi_refuses_memory(vertical):
            raise ProblemError.business_rule(
                "caller_memory_refused_for_vertical",
                "Agents on this kind of business cannot remember callers between calls.",
                remediation=(
                    "A note about what a caller asked is information about their health "
                    "when the business is a clinic, and Indian law requires written "
                    "consent for that — which a phone call cannot give. Nothing needs to "
                    "be changed here; the feature is not available for this account."
                ),
            )
        if enabled and attested_at is None and attested_by is None:
            raise ProblemError.business_rule(
                "caller_memory_attestation_required",
                "Confirm what these calls collect before agents can remember callers.",
                remediation=CALLER_MEMORY_ATTESTATION,
            )

        if current != enabled:
            if enabled and attested_at is None:
                # In the SAME transaction as the switch it permits. An attestation that
                # committed while the switch rolled back would be a recorded promise about
                # a capability nobody turned on, and the client would never be asked again.
                await session.execute(
                    text(
                        "UPDATE organizations SET caller_memory_attested_at = now(), "
                        "caller_memory_attested_by = :by, updated_at = now() "
                        "WHERE id = :tid AND caller_memory_attested_at IS NULL"
                    ),
                    {"by": attested_by, "tid": tenant_id},
                )
                # RE-READ RATHER THAN STAMPED FROM PYTHON: the UPDATE is guarded on
                # `IS NULL`, so a concurrent request may have won it, and the value the
                # client is shown must be the one on the row. The attester's name is read
                # back with it for the same reason — after a race it is the WINNER's name.
                attested = (
                    await session.execute(
                        text(
                            "SELECT o.caller_memory_attested_at, u.name "
                            "FROM organizations o "
                            "LEFT JOIN users u ON u.id = o.caller_memory_attested_by "
                            "WHERE o.id = :tid"
                        ),
                        {"tid": tenant_id},
                    )
                ).one()
                attested_at = attested[0]
                attested_by_name = None if attested[1] is None else str(attested[1])
            await session.execute(
                text(
                    "UPDATE agents SET caller_memory_enabled = :on, updated_at = now() "
                    "WHERE id = :aid AND deleted_at IS NULL"
                ),
                {"on": enabled, "aid": agent_id},
            )
        posture = DisclosurePosture(
            ai_disclosure_line=str(row[1]),
            ai_disclosure_enabled=bool(row[2]),
            recording_notice_line=str(row[3]),
            recording_notice_enabled=bool(row[4]),
            caller_memory_notice_line=str(row[5]),
            caller_memory_enabled=enabled,
        )
        is_live = str(row[6]) == "live" and bool(row[7])
        if current != enabled and is_live:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)

    # Ids and booleans (hard rule 6). The sentence itself is the client's own copy and
    # nothing is served by putting it in a log line.
    log.info(
        "agent_caller_memory_set",
        extra={
            "agent_id": str(agent_id),
            "enabled": enabled,
            "changed": current != enabled,
            "engine_synced": (current != enabled) and is_live,
        },
    )
    return CallerMemoryResult(
        agent_id=agent_id,
        enabled=enabled,
        opening_line=compose_opening_line(posture),
        engine_synced=(current != enabled) and is_live,
        unchanged=current == enabled,
        attested_at=attested_at,
        attested_by_name=attested_by_name,
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
        rate = await worst_case_rate(session, tenant_id)

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


def _refuse_unknown_voice(voice_id: str) -> ProblemError:
    """`agents.tts_voice` is free text whose next reader is a vendor API, so a typo that
    gets stored looks saved, publishes cleanly, and surfaces as a broken call on a
    client's line. Refusing it costs a dictionary lookup.

    ⚠ **THE REMEDIATION NO LONGER ENUMERATES THE CATALOGUE, AND BOTH REASONS ARE D-588.**
    It used to read "Pick one of the available voices: " + every id. (a) Since curation,
    `voice_ids()` is the LOOKUP layer and includes the voices an operator has switched off,
    so the list was naming ids the very next check refuses — a remediation that hands the
    reader a wrong answer is worse than none. (b) On a deployment nobody has synced the
    catalogue is empty, and the sentence degenerated to "Pick one of the available voices:
    ." So it points at the one read that answers per audience, per deployment and per
    moment, and that read carries a `note` saying what to do when it is empty.
    """
    return ProblemError(
        kind="business_rule",
        code="unknown_voice",
        title="Unknown voice",
        detail="That voice is not in the catalog, so it cannot be set on an agent.",
        remediation=(
            "Read GET /v1/agents/voices for the voices offered on this account, and pick "
            "one whose `offerable` is true."
        ),
        fields=[
            {
                "field": "voice_id",
                "rule": "not_in_catalog",
                "message": "Not a supported voice.",
            }
        ],
    )


async def _voice_refusal(
    voice: Voice, *, agent_id: UUID, audience: VoiceReasonAudience
) -> str | None:
    """Ground the catalogue's OWN verdict about this voice, in the caller's language.

    THE WRITE ASKS THE SAME QUESTION THE PICKER ASKS, which is the whole reason
    `voice_offer.py` is a module and not a branch in the route: a picker that offered a
    voice the write refuses — or a write that accepted one the picker greyed out — is the
    divergence D-93 exists to remove. `audience` decides only the WORDING (an operator
    reads the missing key or the unattested price and can act on it; a client reads the one
    action they have), never the verdict.

    `exclude_agent_id` is this agent: a live Cartesia agent moving between two Cartesia
    personas is not a FURTHER agent on the tier, and counting it against itself would
    refuse a change that adds nothing to the plan.

    The count is measured only when it could decide anything — a Sarvam voice fails no
    PRICED ground, and a deployment with no Cartesia key or no attested price already has
    its answer — so the ordinary write opens no extra session for it.

    **CURATION IS ALWAYS MEASURED (D-588)**, because ground zero applies to both providers:
    a voice no operator has enabled may not be set on anybody's agent, and "an archived
    voice cannot be newly selected" is this one read. It is one SELECT against a
    platform-scoped table of tens of rows, on a write a human just made.
    """
    curation = await read_curation()
    needs_count = voice.provider != "sarvam" and cartesia_tier_could_be_offered()
    live = await count_live_cartesia_agents(exclude_agent_id=agent_id) if needs_count else 0
    return unofferable_reason(
        voice, cartesia_live_agents=live, curation=curation, audience=audience
    )


#: Locked for the duration, then re-read: the same row the UPDATE and the republish touch.
#: `FOR UPDATE` rather than a CAS token — see `set_agent_voice` for why a voice has no
#: version for a screen to be stale about, and what the lock is actually defending.
_VOICE_ROW_SQL: Final = (
    "SELECT status, engine_agent_ref, tts_voice, tts_provider, live_tts_voice "
    "FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
)


async def set_agent_voice(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    voice_id: str,
    audience: VoiceReasonAudience = "operator",
) -> VoiceWriteResult:
    """Set the voice an agent speaks in, and put it on the phone line (D-586).

    FAST LANE, AND THE REPUBLISH IS INSIDE THE TRANSACTION — the ordering
    `set_call_cap`, `set_disclosure_posture` and `set_caller_memory` all use, for the
    reason this module's docstring gives: a voice that only lands in our table is a screen
    telling a client their agent sounds different while their callers hear the old voice.
    If the engine refuses the push — a 400 on a voice their account cannot synthesise,
    a vendor outage — the column write rolls back with it and the row goes on saying
    exactly what the engine is running. There is no state in which the two disagree
    because of this function.

    ═══ THE FOUR CHECKS, IN THIS ORDER, AND THE ORDER IS THE POINT ═══

    1. **Can a voice be chosen on this engine AT ALL** (D-93). On an engine that supplies
       its own voices there is no id that would be correct, so refusing with
       `unknown_voice` would send a caller hunting for the right string for ever.
    2. **Is it a voice we sell** — a dictionary lookup against the synced catalogue.
    3. **May it be chosen HERE, TODAY** — `voice_offer.py`'s three grounds (no Cartesia
       key, no attested price, the platform-wide cap). This check did not exist on the
       write before D-586: the picker greyed the voice out and the write took it anyway,
       so a curl, a stale schema or a client who had the page open before the cap filled
       could put an agent on a tier this deployment cannot bill for — hard rule 7, by the
       back door. The refusal carries the REASON, in the caller's own language, because a
       generic "no" on a client's own screen is a support ticket with no words in it.
    4. **Does the agent exist, in THIS tenant** — under the tenant's own RLS scope, so
       "not found" and "belongs to someone else" are deliberately the same answer.

    ═══ WHY A LOCK AND NOT A CAS TOKEN ═══

    BACKEND-PATTERNS §5 makes conditional UPDATE the pervasive primitive, and `apply_to_live`
    takes an `expected_version` because a script HAS a version the operator looked at. A
    voice does not: the client picks one entry from a catalogue, and "the voice was
    something else when you opened the page" is not a fact that should refuse them — they
    are asking for THIS voice, not for a transition from a particular one.

    What has to be defended is different and a token cannot defend it: two writes, or a
    write racing a publish, INTERLEAVING between our read and the engine push. `SELECT …
    FOR UPDATE` here and `_load_agent(for_update=True)` inside `publish_agent` take the
    same row lock, so the second writer waits for the first to COMMIT and then re-reads —
    and the engine receives the two configurations in the order the database committed
    them. Last write wins, which is the correct semantics for a choice, and it wins on the
    phone line as well as in the row rather than only in one of them.

    IDEMPOTENT. Re-selecting the voice the row already holds writes nothing and reports
    `changed=False` — so a double-clicked picker is one audit row, not two. It still
    republishes when the ENGINE is out of step (`live_tts_voice` differs), because that is
    the one case where re-asserting the same voice is the whole point.
    """
    capability = voice_selection_capability()
    if not capability.available:
        raise engine_lacks("tts", engine=get_settings().engine)

    voice = get_voice(voice_id)
    if voice is None:
        raise _refuse_unknown_voice(voice_id)

    refusal = await _voice_refusal(voice, agent_id=agent_id, audience=audience)
    if refusal is not None:
        raise ProblemError(
            kind="business_rule",
            code="voice_not_available",
            title="That voice cannot be used here",
            # The ground itself, capitalised into a sentence. `voice_offer.py` writes its
            # reasons lower-case and unpunctuated so a picker can complete "Cannot be
            # chosen — {…}"; a problem+json `detail` is a sentence on its own.
            detail=f"{refusal[:1].upper()}{refusal[1:]}.",
            remediation=(
                "Pick another voice, or ask your account manager about this one."
                if audience == "client"
                else "Clear the ground named above, then set the voice again."
            ),
            fields=[
                {"field": "voice_id", "rule": "not_offerable", "message": "Not available here."}
            ],
        )

    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text(_VOICE_ROW_SQL), {"aid": agent_id})).first()
        if row is None:
            raise ProblemError.not_found("Agent")
        status, engine_ref, current_voice, current_provider = (
            str(row[0]),
            row[1],
            row[2],
            row[3],
        )
        live_voice_id: str | None = row[4]
        changed = (current_voice, current_provider) != (voice.id, voice.provider)
        # `is_live`, never `published`: `publish_agent` writes `status = 'live'`, so
        # republishing a PAUSED agent would put a switched-off phone line back into
        # service as a side effect of a delivery change. The same guard, for the same
        # reason, as `set_call_cap` and both notice toggles.
        is_live = status == "live" and bool(engine_ref)
        if changed:
            await session.execute(
                text(
                    "UPDATE agents SET tts_voice = :voice, tts_provider = :provider, "
                    "updated_at = now() WHERE id = :aid AND deleted_at IS NULL"
                ),
                {"voice": voice.id, "provider": voice.provider, "aid": agent_id},
            )
        # The engine is pushed when it is not already holding this voice — which covers
        # the re-assertion case `changed` misses: an agent whose row was right and whose
        # engine copy was not is exactly the agent a second click is trying to fix.
        engine_synced = is_live and live_voice_id != voice.id
        if engine_synced:
            # Writes `live_tts_voice`/`live_tts_provider` itself, so the mirror below is
            # read from the row rather than assumed from what we asked for.
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
            live_voice_id = (
                await session.execute(
                    text("SELECT live_tts_voice FROM agents WHERE id = :aid"), {"aid": agent_id}
                )
            ).scalar_one()

    published = bool(engine_ref)
    # Exact, not assumed. Null `live_tts_voice` on a published agent (published before
    # migration c8b3f14e7a29, or with no voice) still asks for a republish — the safe
    # direction, and the one a PAUSED agent lands in.
    republish_required = published and live_voice_id != voice.id
    # Catalogue ids and booleans. No prompt text and nothing about a caller (hard rule 6).
    log.info(
        "agent_voice_set",
        extra={
            "agent_id": str(agent_id),
            "voice_id": voice.id,
            "provider": voice.provider,
            "changed": changed,
            "engine_synced": engine_synced,
            "republish_required": republish_required,
        },
    )
    return VoiceWriteResult(
        agent_id=agent_id,
        voice=voice,
        agent_status=status,
        published=published,
        engine_synced=engine_synced,
        live_voice_id=live_voice_id,
        republish_required=republish_required,
        changed=changed,
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
    "VoiceWriteResult",
    "apply_to_live",
    "audit_action_for",
    "engine_drift_for",
    "lane_of",
    "pending_state_for",
    "set_agent_voice",
    "set_call_cap",
    "set_disclosure_posture",
    "undo_staged",
    "worst_case_cost",
    "worst_case_rate",
]
