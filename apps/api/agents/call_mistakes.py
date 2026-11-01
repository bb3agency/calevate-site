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
missed one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol
from uuid import UUID

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


#: The kinds counted on real calls, each with the words an owner reads. Client-facing text,
#: so no provider is named (D-679).
LESSONS: Final[dict[str, Lesson]] = {
    "said_again": Lesson(
        "Said the same line again",
        "With no clear reply, ask once in other words, then offer the next step.",
    ),
    "asked_again": Lesson(
        "Asked the same question again, word for word",
        "Ask an unanswered question once more, in new words.",
    ),
    "reasked_name": Lesson(
        "Asked for a name the caller already gave",
        "Use the name the caller said.",
    ),
    "opened_again": Lesson(
        "Greeted the caller again in the middle of the call",
        "Greet once, at the start.",
    ),
    "caller_line": Lesson(
        "Answered for the caller",
        "Ask, then wait for the caller's own answer.",
    ),
    "goodbye_while_asking": Lesson(
        "Said goodbye while the caller was still asking",
        "Answer the caller's question before closing.",
    ),
    "false_recall": Lesson(
        "Said it had already told the caller something it never said",
        "Say the detail now.",
    ),
    "wrong_language": Lesson(
        "Answered in a different language from the caller",
        "Reply in the caller's language.",
    ),
    "third_person": Lesson(
        "Talked about the caller as “the caller”",
        "Speak to the caller directly.",
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


def _replies(turns: Sequence[SpokenTurn], unheard: frozenset[int]) -> tuple[str, list[_Reply]]:
    """The call's opening and each agent reply with the caller line it answered.

    Consecutive turns of one speaker are one line. The agent's first line is the opening,
    judged as `conversation_problems`' `opening`, not as a reply, whoever spoke first: on a
    call the agent places, the person's "Hello" comes before the greeting, and judging the
    greeting as a reply to it would read it as greeting twice. A turn the caller spoke over
    (`unheard`) is left out: saying again what was not heard is right."""
    opening: list[str] = []
    replies: list[_Reply] = []
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
                continue
            if first_idx is None:
                first_idx = turn.idx
            reply.append(words)
    close()
    return " ".join(opening), replies


def mistakes_in(
    turns: Sequence[SpokenTurn], *, language: str, unheard: Iterable[int] = ()
) -> dict[str, int]:
    """Each lesson kind this call shows, with the agent turn it first appears on.

    A reply's own problems are read reply by reply; what only the conversation shows is
    read on each growing prefix, so the first reply that makes it true is the one named."""
    opening, replies = _replies(turns, frozenset(unheard))
    found: dict[str, int] = {}
    for n, item in enumerate(replies, 1):
        own = turn_checks.turn_problems(
            item.exchange.reply, caller_said=item.exchange.said, language=language
        )
        whole = turn_checks.conversation_problems(
            [r.exchange for r in replies[:n]], opening=opening
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
    state: State


async def platform_mistakes(
    session: AsyncSession, *, now: datetime | None = None
) -> list[PlatformMistake]:
    """Every lesson kind across every client, for the operator. Called from an
    `admin_session()`: `call_mistake_scan` enters each client under its own tenant id, and
    only an admin session can list the clients (migration e7b3c9d1a4f2)."""
    now = now or datetime.now(UTC)
    rows = (
        await session.execute(
            text("SELECT scanned_tenant_id, kind, call_started_at FROM call_mistake_scan(:since)"),
            {"since": now - timedelta(days=WINDOW_DAYS)},
        )
    ).all()
    fixes = {
        str(kind): (at, note)
        for kind, at, note in (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (kind) kind, fixed_at, note FROM platform_mistake_fixes "
                    "ORDER BY kind, fixed_at DESC"
                )
            )
        ).all()
    }
    week = now - timedelta(days=7)
    out = []
    for kind, lesson in LESSONS.items():
        mine = [(t, at) for t, k, at in rows if k == kind]
        fixed_at, note = fixes.get(kind, (None, None))
        last_seen = max((at for _t, at in mine), default=None)
        out.append(
            PlatformMistake(
                kind=kind,
                label=lesson.label,
                calls_7d=sum(1 for _t, at in mine if at >= week),
                calls_30d=len(mine),
                accounts_30d=len({t for t, _at in mine}),
                calls_since_fix=sum(1 for _t, at in mine if fixed_at and at > fixed_at),
                last_seen_at=last_seen,
                fixed_at=fixed_at,
                fix_note=note,
                state=_state(fixed_at, last_seen),
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
