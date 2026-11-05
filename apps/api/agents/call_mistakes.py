"""Mistakes on real calls (D-949): the practice-test checks, run on every finished call.

A human telecaller gets better because a supervisor listens to their calls, names what went
wrong, and checks the next calls for it. This module is that loop for an agent, with one
deliberate limit: the agent never rewrites its own instructions. A model that edits its own
prompt from its own reading of its calls repeats its own wrong lessons ("Memory Reward
Inflation in Self-Improving LLM Agents", arXiv 2608.00017; "Governing Evolving Memory in
LLM Agents", arXiv 2603.11768), and what these checks find is not the owner's to fix
either: every kind below is decided by the platform prompt (`turn_checks.SOUND_KINDS`,
`JOB_KINDS`). So:

1. `mistakes_in` runs `turn_checks` over a real call's turns: the same code that judges a
   practice conversation, so a practice test and a real call can never disagree.
2. `record_call_mistakes` stores one row per (call, kind), a kind and a turn index only.
3. The owner sees each kind with its count and whether we have fixed it (`agent_mistakes`).
4. An operator marks a kind fixed once the platform rule is changed (`mark_fixed`); a call
   that STARTED after that and shows it again is the mistake coming back, which raises
   `call_mistake_back` so the fix is known not to have held.

Only kinds the checks read without the agent's script, facts or tools are counted on a real
call. The rest need context a real call does not hand us here (`invented_source` needs the
facts, `unconfirmed_action` the actions) or read digits that a real transcript's spelled-out
numbers make unreliable, and a false mistake shown to an owner costs more trust than a
missed one. `false_history` is the one kind read with the call's own data: whether the
business had the person on file before the call, which the pipeline reads and hands in.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol
from uuid import UUID

from calevate_shared.cut_off import likely_cut_off_rows
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import turn_checks
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Lesson:
    #: What went wrong, in the owner's words.
    label: str
    #: What a good telecaller does instead.
    instead: str
    #: Where in the platform prompt (`calevate_shared.engine`) the fix goes. Operator-only;
    #: empty where no rule is known to govern the kind yet.
    rule: str = ""


#: The kinds counted on real calls, each with the words an owner reads. Client-facing text,
#: so no provider is named (D-679).
LESSONS: Final[dict[str, Lesson]] = {
    "said_again": Lesson(
        "Said the same line again",
        "With no clear reply, ask once in other words, then offer the next step.",
        'HOW TO SPEAK: "Never re-ask what they said or repeat a sentence"; CANNOT HELP: two '
        "tries to one question",
    ),
    "asked_again": Lesson(
        "Asked the same question again, word for word",
        "Ask an unanswered question once more, in new words.",
        'HOW TO SPEAK: "Unclear ... Ask one thing again, reworded"',
    ),
    "reasked_name": Lesson(
        "Asked for a name the caller already gave",
        "Use the name the caller said.",
        "NAME_RULE",
    ),
    "opened_again": Lesson(
        "Greeted the caller again in the middle of the call",
        "Greet once, at the start.",
        "START OF THE CALL (OPENING_CONTINUES_RULE)",
    ),
    "caller_line": Lesson(
        "Answered for the caller",
        "Ask, then wait for the caller's own answer.",
        'HOW TO SPEAK: "Say only your own part, never the caller\'s"',
    ),
    "goodbye_while_asking": Lesson(
        "Said goodbye while the caller was still asking",
        "Answer the caller's question before closing.",
        'HOW TO SPEAK: "Close ... End only then or when asked, never while they talk"',
    ),
    "false_recall": Lesson(
        "Said it had already told the caller something it never said",
        "Say the detail now.",
        "ACTION_CLAIM_RULE (its D-849 line)",
    ),
    "wrong_language": Lesson(
        "Answered in a different language from the caller",
        "Reply in the caller's language.",
        "LANGUAGES, and HOW TO SPEAK's register bullet",
    ),
    "third_person": Lesson(
        "Talked about the caller as “the caller”",
        "Speak to the caller directly.",
    ),
    "offered_more_too_soon": Lesson(
        "Kept asking “anything else?” before the caller was done",
        "Ask once a topic is finished; while helping step by step, give the next step.",
        'HOW TO SPEAK: "Mid-task ... \\"Anything else?\\" only once a topic is done"',
    ),
    "false_history": Lesson(
        "Said the caller had enquired or spoken to you before, when they had not",
        "Say why you are calling without claiming an earlier enquiry or call.",
        "CALL_REASON_RULE",
    ),
}
assert set(LESSONS) <= set(turn_checks.SOUND_KINDS | turn_checks.JOB_KINDS)

#: How far back the owner's list and the admin roll-up look.
WINDOW_DAYS: Final = 30
#: The longest a fix note may be: one line saying what changed.
NOTE_MAX_CHARS: Final = 300

State = Literal["fixing", "fixed", "back"]


@dataclass(frozen=True, slots=True)
class _Exchange:
    said: str
    reply: str
    tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Reply:
    exchange: _Exchange
    turn_idx: int


class SpokenTurn(Protocol):
    """What `mistakes_in` reads of a transcript turn (`calevate_shared.events.TranscriptTurn`
    has it)."""

    @property
    def idx(self) -> int: ...

    @property
    def speaker(self) -> str: ...

    @property
    def text(self) -> str: ...


def _replies(
    turns: Sequence[SpokenTurn], unheard: frozenset[int]
) -> tuple[str, list[_Reply], _Reply | None, str]:
    """The call's opening, each agent reply with the caller line it answered, the first
    reply after the opening when the caller spoke over it, and what the caller said after
    the agent's last reply.

    Consecutive turns of one speaker are one line. The agent's first line is the opening,
    judged as `conversation_problems`' `opening`, not as a reply, whoever spoke first: on a
    call the agent places, the person's "Hello" comes before the greeting, and judging the
    greeting as a reply to it would read it as greeting twice. A turn the caller spoke over
    (`unheard`) is left out: saying again what was not heard is right. The first such reply
    is still returned, because a turn is cut at its end, never its start, so a greeting that
    opens it was heard ("హలో అండి. రైతు ఖాతా", cut off, on the call of 2 Nov 2026)."""
    opening: list[str] = []
    replies: list[_Reply] = []
    cut_first: _Reply | None = None
    said: list[str] = []
    reply: list[str] = []
    first_idx: int | None = None
    # "before": nothing from the agent yet; "opening": its first line; "talk": the rest.
    phase = "before"

    def close() -> None:
        nonlocal reply, said, first_idx
        if reply and first_idx is not None:
            replies.append(_Reply(_Exchange(" ".join(said), " ".join(reply)), first_idx))
            said = []
        reply, first_idx = [], None

    for turn in sorted(turns, key=lambda t: t.idx):
        words = turn.text.strip()
        if not words:
            continue
        if turn.speaker == "caller":
            close()
            if phase == "opening":
                phase = "talk"
            if phase == "talk":
                said.append(words)
        elif turn.speaker == "agent":
            if phase != "talk":
                phase = "opening"
                opening.append(words)
                continue
            if turn.idx in unheard:
                if not replies and not reply and cut_first is None:
                    cut_first = _Reply(_Exchange(" ".join(said), words), turn.idx)
                continue
            if first_idx is None:
                first_idx = turn.idx
            reply.append(words)
    close()
    return " ".join(opening), replies, cut_first, " ".join(said)


def mistakes_in(
    turns: Sequence[SpokenTurn],
    *,
    language: str,
    unheard: Iterable[int] = (),
    prior_contact: bool | None = None,
) -> dict[str, int]:
    """Each lesson kind this call shows, with the agent turn it first appears on.

    A reply's own problems are read reply by reply; what only the conversation shows is
    read on each growing prefix, so the first reply that makes it true is the one named.
    `prior_contact` is whether the business had this person on file before the call
    (`workers/pipeline._prior_contact`); None leaves `false_history` unjudged."""
    opening, replies, cut_first, trailing = _replies(turns, frozenset(unheard))
    found: dict[str, int] = {}
    if cut_first is not None and turn_checks.opened_again(cut_first.exchange.reply):
        found["opened_again"] = cut_first.turn_idx
    for n, item in enumerate(replies, 1):
        own = turn_checks.turn_problems(
            item.exchange.reply, caller_said=item.exchange.said, language=language
        )
        # The caller's next line goes with each prefix, unanswered, so a goodbye the caller
        # talked on after is named on the goodbye rather than on the reply after it.
        following = replies[n].exchange.said if n < len(replies) else trailing
        whole = turn_checks.conversation_problems(
            [r.exchange for r in replies[:n]] + [_Exchange(following, "")],
            opening=opening,
            prior_contact=prior_contact,
        )
        for problem in (*own, *whole):
            if problem.kind in LESSONS:
                found.setdefault(problem.kind, item.turn_idx)
    return found


async def record_call_mistakes(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    call_started_at: datetime,
    found: dict[str, int],
) -> list[str]:
    """Replace this call's mistake rows with `found`. Returns the kinds that came BACK: seen
    on a call that started after the latest fix of that kind, each raised as
    `call_mistake_back`. Idempotent per call, so a re-driven call never double-counts."""
    async with tenant_session(tenant_id) as session:
        await session.execute(text("DELETE FROM call_mistakes WHERE call_id = :c"), {"c": call_id})
        for kind, turn_idx in found.items():
            await session.execute(
                text(
                    "INSERT INTO call_mistakes (id, tenant_id, agent_id, call_id, kind, turn_idx, "
                    "call_started_at) VALUES (:id, :t, :a, :c, :k, :i, :s)"
                ),
                {
                    "id": uuid7(),
                    "t": tenant_id,
                    "a": agent_id,
                    "c": call_id,
                    "k": kind,
                    "i": turn_idx,
                    "s": call_started_at,
                },
            )
        fixes = await _latest_fixes(session, found)
        # Raised once per account and kind in the window, so "our team has been told" on
        # the client's screen is true without an alarm for every call.
        seen_before = {
            str(k)
            for (k,) in (
                await session.execute(
                    text(
                        "SELECT DISTINCT kind FROM call_mistakes WHERE kind = ANY(:k) "
                        "AND call_id <> :c AND call_started_at >= :since"
                    ),
                    {
                        "k": sorted(found),
                        "c": call_id,
                        "since": datetime.now(UTC) - timedelta(days=WINDOW_DAYS),
                    },
                )
            ).all()
        }
    for kind in sorted(set(found) - set(fixes) - seen_before):
        alert(
            "WORKER_STALL",
            "call_mistake_new",
            detail=(
                f"A mistake no fix was recorded for showed on this account ({kind}). Read "
                "the call on Ops > Mistakes on real calls and change the rule it names."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            call_id=str(call_id),
            reason=kind,
        )
    back = sorted(kind for kind, at in fixes.items() if call_started_at > at)
    for kind in back:
        alert(
            "WORKER_STALL",
            "call_mistake_back",
            detail=(
                f"A mistake marked fixed came back on a real call ({kind}). The platform "
                "rule that was changed did not hold; read the call and fix it again."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            call_id=str(call_id),
            reason=kind,
        )
    return back


#: Kinds whose checks were narrowed by D-970 (a number read again on request; a goodbye after
#: the caller signed off), so rows found before it are read again.
RECHECKED_KINDS: Final = ("said_again", "goodbye_while_asking")


@dataclass(frozen=True, slots=True)
class _StoredTurn:
    idx: int
    speaker: str
    text: str


async def recheck_call_mistakes(tenant_id: UUID) -> int:
    """Read again the calls in the window holding a `RECHECKED_KINDS` row, and delete each such
    row the checks no longer find. Never adds a row. The checks read the agent's primary
    language as the pipeline passes it (STEP 3c'); the prior contact is not re-read, and it
    decides none of these kinds. Returns rows deleted."""
    since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
    async with tenant_session(tenant_id) as session:
        flagged = (
            await session.execute(
                text(
                    "SELECT m.call_id, array_agg(m.kind), min(a.language_primary) "
                    "FROM call_mistakes m LEFT JOIN agents a ON a.id = m.agent_id "
                    "WHERE m.kind = ANY(:k) AND m.call_started_at >= :since GROUP BY m.call_id"
                ),
                {"k": list(RECHECKED_KINDS), "since": since},
            )
        ).all()
        dropped = 0
        for call_id, kinds, language in flagged:
            rows = (
                await session.execute(
                    text(
                        "SELECT idx, speaker, text, start_ms FROM transcript_turns "
                        "WHERE call_id = :c ORDER BY idx"
                    ),
                    {"c": call_id},
                )
            ).all()
            turns = [_StoredTurn(int(r[0]), str(r[1]), str(r[2] or "")) for r in rows]
            unheard = likely_cut_off_rows(
                (int(r[0]), str(r[1]), len(r[2] or ""), r[3]) for r in rows
            )
            still = mistakes_in(turns, language=str(language or ""), unheard=unheard)
            gone = [k for k in kinds if k not in still]
            if gone:
                await session.execute(
                    text("DELETE FROM call_mistakes WHERE call_id = :c AND kind = ANY(:k)"),
                    {"c": call_id, "k": gone},
                )
                dropped += len(gone)
    return dropped


async def _latest_fixes(session: AsyncSession, kinds: Iterable[str]) -> dict[str, datetime]:
    wanted = sorted(set(kinds))
    if not wanted:
        return {}
    rows = await session.execute(
        text(
            "SELECT kind, max(fixed_at) FROM platform_mistake_fixes WHERE kind = ANY(:k) "
            "GROUP BY kind"
        ),
        {"k": wanted},
    )
    return {str(kind): at for kind, at in rows}


def _state(fixed_at: datetime | None, last_seen: datetime | None) -> State:
    if fixed_at is None:
        return "fixing"
    if last_seen is not None and last_seen > fixed_at:
        return "back"
    return "fixed"


@dataclass(frozen=True, slots=True)
class AgentMistake:
    kind: str
    label: str
    instead: str
    #: Calls in the window that showed it.
    calls: int
    #: Of those, calls that started after the latest fix.
    calls_since_fix: int
    last_seen_at: datetime
    last_call_id: UUID
    fixed_at: datetime | None
    state: State


async def agent_mistakes(
    session: AsyncSession, agent_id: UUID, *, now: datetime | None = None
) -> list[AgentMistake]:
    """This agent's mistakes on real calls in the window, the ones still happening first."""
    since = (now or datetime.now(UTC)) - timedelta(days=WINDOW_DAYS)
    rows = (
        await session.execute(
            text(
                "SELECT m.kind, m.call_id, m.call_started_at FROM call_mistakes m "
                "WHERE m.agent_id = :a AND m.call_started_at >= :since "
                "ORDER BY m.call_started_at DESC"
            ),
            {"a": agent_id, "since": since},
        )
    ).all()
    seen: dict[str, list[tuple[UUID, datetime]]] = {}
    for kind, call_id, started in rows:
        if kind in LESSONS:
            seen.setdefault(str(kind), []).append((call_id, started))
    fixes = await _latest_fixes(session, seen)
    out = []
    for kind, calls in seen.items():
        fixed_at = fixes.get(kind)
        last_call, last_seen = calls[0]
        out.append(
            AgentMistake(
                kind=kind,
                label=LESSONS[kind].label,
                instead=LESSONS[kind].instead,
                calls=len(calls),
                calls_since_fix=sum(1 for _c, at in calls if fixed_at and at > fixed_at),
                last_seen_at=last_seen,
                last_call_id=last_call,
                fixed_at=fixed_at,
                state=_state(fixed_at, last_seen),
            )
        )
    order = {"back": 0, "fixing": 1, "fixed": 2}
    return sorted(out, key=lambda m: (order[m.state], -m.calls, m.kind))


@dataclass(frozen=True, slots=True)
class CallMistakeLine:
    kind: str
    label: str
    instead: str
    turn_idx: int


async def call_mistakes(session: AsyncSession, call_id: UUID) -> list[CallMistakeLine]:
    """What went wrong on one call, in the order the call reached it."""
    rows = await session.execute(
        text("SELECT kind, turn_idx FROM call_mistakes WHERE call_id = :c ORDER BY turn_idx, kind"),
        {"c": call_id},
    )
    return [
        CallMistakeLine(kind=str(k), label=LESSONS[k].label, instead=LESSONS[k].instead, turn_idx=i)
        for k, i in rows
        if k in LESSONS
    ]


@dataclass(frozen=True, slots=True)
class PlatformMistake:
    kind: str
    label: str
    calls_7d: int
    calls_30d: int
    accounts_30d: int
    calls_since_fix: int
    last_seen_at: datetime | None
    fixed_at: datetime | None
    fix_note: str | None
    #: The operator's display name; None when no fix is recorded or the operator has no name.
    fixed_by: str | None
    state: State
    #: Where in the platform prompt the fix goes (`Lesson.rule`).
    rule: str
    #: The latest call showing it, so the operator reads the call before changing the rule.
    last_call_id: UUID | None
    last_client_slug: str | None


async def platform_mistakes(
    session: AsyncSession, *, now: datetime | None = None
) -> list[PlatformMistake]:
    """Every lesson kind across every client, for the operator. Called from an
    `admin_session()`: `call_mistake_scan` enters each client under its own tenant id, and
    only an admin session can list the clients (migration e7b3c9d1a4f2)."""
    now = now or datetime.now(UTC)
    # Counted in SQL rather than in Python: the scan returns one row per call per kind
    # across every client for the whole window, and only nine numbers per kind leave it.
    # A call holds a kind at most once (unique on tenant, call, kind), so rows are calls.
    fixes = {
        str(kind): (at, note, by)
        for kind, at, note, by in (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (f.kind) f.kind, f.fixed_at, f.note, a.name "
                    "FROM platform_mistake_fixes f JOIN admin_users a ON a.id = f.fixed_by "
                    "ORDER BY f.kind, f.fixed_at DESC"
                )
            )
        ).all()
    }
    counts = {
        str(row.kind): row
        for row in (
            await session.execute(
                text(
                    "WITH fx AS (SELECT DISTINCT ON (kind) kind, fixed_at "
                    "FROM platform_mistake_fixes ORDER BY kind, fixed_at DESC) "
                    "SELECT s.kind, "
                    "count(*) FILTER (WHERE s.call_started_at >= :week) AS calls_7d, "
                    "count(*) AS calls_30d, "
                    "count(DISTINCT s.scanned_tenant_id) AS accounts_30d, "
                    "count(*) FILTER (WHERE s.call_started_at > fx.fixed_at) AS since_fix, "
                    "max(s.call_started_at) AS last_seen, "
                    "(array_agg(s.call_id ORDER BY s.call_started_at DESC))[1] AS last_call, "
                    "(array_agg(o.slug ORDER BY s.call_started_at DESC))[1] AS last_slug "
                    "FROM call_mistake_scan(:since) s LEFT JOIN fx ON fx.kind = s.kind "
                    "JOIN organizations o ON o.id = s.scanned_tenant_id "
                    "GROUP BY s.kind"
                ),
                {"since": now - timedelta(days=WINDOW_DAYS), "week": now - timedelta(days=7)},
            )
        ).all()
    }
    out = []
    for kind, lesson in LESSONS.items():
        fixed_at, note, fixed_by = fixes.get(kind, (None, None, None))
        row = counts.get(kind)
        last_seen = row.last_seen if row else None
        last_call = row.last_call if row else None
        last_slug = row.last_slug if row else None
        out.append(
            PlatformMistake(
                kind=kind,
                label=lesson.label,
                calls_7d=row.calls_7d if row else 0,
                calls_30d=row.calls_30d if row else 0,
                accounts_30d=row.accounts_30d if row else 0,
                calls_since_fix=row.since_fix if row else 0,
                last_seen_at=last_seen,
                fixed_at=fixed_at,
                fix_note=note,
                fixed_by=fixed_by,
                state=_state(fixed_at, last_seen),
                rule=lesson.rule,
                last_call_id=last_call,
                last_client_slug=last_slug,
            )
        )
    order = {"back": 0, "fixing": 1, "fixed": 2}
    return sorted(out, key=lambda m: (order[m.state], -m.calls_7d, -m.calls_30d, m.kind))


async def mark_fixed(session: AsyncSession, *, kind: str, note: str, admin_id: UUID) -> datetime:
    """Record that `kind` is fixed in the platform, from now. Calls that start after this and
    show it again count as the mistake coming back."""
    if kind not in LESSONS:
        raise ProblemError.not_found("Mistake")
    cleaned = " ".join(note.split())
    if not cleaned:
        raise ProblemError.business_rule(
            "mistake_fix_note_missing",
            "Say what was changed.",
            remediation="One line, such as the rule you edited.",
        )
    fixed_at: datetime = (
        await session.execute(
            text(
                "INSERT INTO platform_mistake_fixes (id, kind, note, fixed_by) "
                "VALUES (:id, :k, :n, :by) RETURNING fixed_at"
            ),
            {"id": uuid7(), "k": kind, "n": cleaned[:NOTE_MAX_CHARS], "by": admin_id},
        )
    ).scalar_one()
    return fixed_at
