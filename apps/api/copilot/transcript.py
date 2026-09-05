"""The durable copilot conversation: load it, append to it, end it.

D-540, migration `c7e0b2a94f13`. Before this the conversation was
`useState<CopilotTurn[]>([])` and nothing else, so a refresh, a route change that
unmounted the dock, or a closed browser lost it.

═══ WHAT THIS IS NOT ═══

**It is not `copilot_memories`.** That table holds DISTILLED facts — one redacted episode,
or a semantic fact a worker distilled out of a run of them — read back into a prompt
through `memory.recall`'s two budgeted channels. This holds the verbatim conversation a
person scrolls. Overloading one on the other would mean a recall query returning chat
history and a chat panel rendering distillate; the two are written in the same
transaction and read by nothing in common.

**AND THE DISTILLATION DID NOT BECOME REDUNDANT.** It is the natural conclusion to reach
and it is wrong twice over. (a) The two have different lifetimes on purpose: the
transcript dies when the person's last session ends (hours), the memory lives on the
tenant's `copilot_memory` retention clock (180 days) — so a fact learned yesterday is
still known tomorrow, which is the whole feature. (b) They are read at different sizes:
recall spends `RECALL_CHAR_BUDGET` on six rows chosen by recency AND lexical relevance,
and no truncation rule over a raw transcript can substitute for that. What IS now
double-stored is one exchange, briefly, in two shapes — and that is the intended shape,
not the defect: it is the standard "sliding window for recent turns, structured memory
for the facts that matter" split (see `MAX_STORED_TURNS` for the citation).

═══ WHAT IS STORED ═══

The REDACTED form of every turn, always. `apps/web/src/lib/copilot/redaction.ts` replaces
screen field values that look like identifiers with placeholders before a question leaves
the browser and restores them for DISPLAY only; what lands here is the wire form, put
through `memory.redacted_content`'s same `redact()` pass. The consequence is visible and
is the right trade: a turn re-read after a reload shows `«PHONE_1»` where the live one
showed the digits. The digits were never ours to keep — storing them would put a caller's
number in a durable row, which is exactly the thing the phone-keyed §12 erasure then has
to be able to find, on a table whose whole safety argument is that it holds no identifier.

⚠ **THE LIMIT OF THAT, STATED RATHER THAN LEFT TO BE DISCOVERED** — `copilot/memory.py`
records the same one and it applies here identically. `redact()` recognises IDENTIFIERS,
not PROPER NOUNS, so a staff member who types "what did Lakshmi's enquiry say" leaves a
first name in a row. Three things reach it and none of them is a name match: the run
clearing below (usually within hours), the `transcript` retention clock, and tenant
offboarding, which DELETEs every row unconditionally.

═══ THE LIFETIME ═══

`session_run.py` holds the whole argument. Every turn carries the instant its subject's
current unbroken run of sign-ins began; a turn from an earlier run is deleted before it
is ever returned, and the cron sweeps the subjects who never came back. This module's job
is to apply that comparison on EVERY path — load, append and count — so there is no read
that can return a turn from a run that has ended.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.memory import redacted_content
from apps.api.copilot.schemas import CopilotConversationOut, CopilotStoredTurnOut
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

#: The hard ceiling on one conversation, in turns, enforced on every append by deleting
#: the oldest surplus. A conversation is a LIST and an unbounded one is an unbounded read,
#: an unbounded row count per person and an unbounded page for the panel to render.
#:
#: 200 is ~100 exchanges, which is far more than one sign-in run has ever produced and
#: well inside what one paged read can serve. What it is NOT is a context-window rule:
#: the model is still sent `schemas.MAX_HISTORY` whole exchanges and not one turn more —
#: see `truncation` below.
MAX_STORED_TURNS: Final = 200

#: THE TRUNCATION RULE, AND IT DID NOT CHANGE WHEN THE TRANSCRIPT BECAME DURABLE.
#:
#: What goes to the model stays a SLIDING WINDOW OVER WHOLE EXCHANGES — the last
#: `schemas.MAX_HISTORY` turns, with a leading orphan assistant turn dropped
#: (`useCopilotConversation.recentTurns` is the one implementation and the server's
#: `max_length` is the enforcement). A 200-turn history is never sent.
#:
#: **Summarise-and-drop was considered and refused, and the reason is that we already run
#: its better half.** The published production guidance is to start with a sliding window
#: for recent turns, keep structured memory for the facts that matter, and reach for
#: compression only after both (mem0.ai "LLM summarization techniques for managing chat
#: history" and apxml.com "Context window management strategies", read as WEB-SEARCH
#: SUMMARIES on 5 Sep 2026 — ⚠ **EVIDENCE CLASS: REPORTED.** Both hosts, and
#: devblogs.microsoft.com and redis.io, are egress-blocked from this container: a fetch
#: 403s at the proxy, so the summaries are what was read and not the pages. Nothing about
#: our own system rests on them; they are a design precedent). `copilot_memories` IS that
#: structured memory, distilled by a cron rather than on the latency path, which is the
#: cost summarisation would add: a second model call inside a question a person is
#: sitting in front of, on a surface metered per answer (`crm/assist.meter_assist`), to
#: compress text the recall channel has already distilled.
#:
#: So the durable transcript changes what the PERSON sees and nothing about what the
#: model knows. That is deliberate and is the safest half of the change: no answer moves
#: because a conversation was persisted.
_TRUNCATION_RULE_IS_UNCHANGED: Final = True

#: The default and maximum page of a `GET`. The route declares `limit` as a bounded query
#: parameter, which is what keeps it off `scripts/check_list_bounds.BOUNDED_LISTS` — a
#: conversation history is a list, and this is its ceiling.
PAGE_DEFAULT: Final = 50
PAGE_MAX: Final = 100


@dataclass(frozen=True, slots=True)
class StoredTurn:
    """One turn as it comes back off the wire. Ids and prose; no `run_started_at`.

    The run is a property of the CONVERSATION rather than of a turn a caller can see:
    every row a read returns is from the current run by construction, so publishing it
    per turn would invite a caller to re-decide a question this module has already
    settled.
    """

    id: UUID
    role: str
    content: str
    screen_route: str
    said_at: str


@dataclass(frozen=True, slots=True)
class ConversationPage:
    """A page of a conversation, oldest first, plus whether older turns remain."""

    turns: tuple[StoredTurn, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class _Realm:
    """Which table, and whose rows. The two realms differ in nothing else.

    Two tables rather than one with a discriminator, for `models.AdminCopilotMemory`'s
    reason: `Principal.user_id` is a `users.id` on one realm and an `admin_users.id` on
    the other, and two id spaces behind one column is a cross-realm read one forgotten
    predicate away.
    """

    table: str
    owner: str
    #: The admin table records which account was on screen; the client table does not need
    #: to, because its `tenant_id` already says so and RLS enforces it.
    context_column: str | None


CLIENT: Final = _Realm(table="copilot_conversation_turns", owner="user_id", context_column=None)
ADMIN: Final = _Realm(
    table="admin_copilot_conversation_turns",
    owner="admin_user_id",
    context_column="viewing_tenant_id",
)


def _load_sql(realm: _Realm) -> str:
    """The tail of the current run, oldest first, one page at a time.

    `LIMIT :limit + 1` is how `has_more` is answered without a second COUNT: one extra row
    fetched and dropped says "there is at least one older turn" for the cost of a row.

    The ORDER is `created_at, id` in BOTH directions — DESC to take the newest page,
    then reversed in Python. `id` is uuid7 and time-ordered, so it is the tiebreak that
    makes the order total inside one clock tick: the two turns of one exchange are
    written in one statement and can share a `created_at`, and a transcript that renders
    the answer above the question is worse than no transcript.

    `tenant_id` is in NO predicate on the client table, and its absence is the tenancy
    argument rather than an oversight: every caller runs inside `db.session.tenant_session`
    and the table carries a FORCEd `tenant_isolation` policy, so a hand-written
    `tenant_id =` would be a second, weaker copy of what the database already guarantees.
    The owner column IS a predicate, because RLS answers "which tenant" and never "which
    person".
    """
    return f"""
    SELECT id, role, content, screen_route, created_at
    FROM {realm.table}
    WHERE {realm.owner} = :owner
      AND run_started_at = :run
      AND (CAST(:before AS uuid) IS NULL OR (created_at, id) < (
            SELECT b.created_at, b.id FROM {realm.table} b
            WHERE b.id = CAST(:before AS uuid) AND b.{realm.owner} = :owner))
    ORDER BY created_at DESC, id DESC
    LIMIT :limit
    """


def _insert_sql(realm: _Realm) -> str:
    columns = ["id", realm.owner, "run_started_at", "role", "content", "screen_route"]
    values = [":id", ":owner", ":run", ":role", ":content", ":route"]
    if realm is CLIENT:
        columns.insert(1, "tenant_id")
        values.insert(1, ":tenant_id")
    if realm.context_column is not None:
        columns.append(realm.context_column)
        values.append(":context")
    return (
        f"INSERT INTO {realm.table} ({', '.join(columns)}, created_at, updated_at) "
        f"VALUES ({', '.join(values)}, now(), now())"
    )


def _trim_sql(realm: _Realm) -> str:
    """Two deletions in one statement's worth of intent, and they are different things.

    The first arm is the END OF A RUN: every turn of this owner that belongs to an older
    run. It is not a cleanup — it is the founder's decision 1 being applied, and it runs
    before the read as well as before the write so no path can return a turn from a
    conversation that has ended.

    The second is the CEILING: the oldest turns beyond `MAX_STORED_TURNS`. Deleting from
    the front rather than refusing at the back, because a person whose conversation has
    reached the cap wants to keep talking, and a chat that stops accepting messages is a
    worse answer than one that forgets its beginning.
    """
    return f"""
    DELETE FROM {realm.table}
    WHERE {realm.owner} = :owner
      AND (run_started_at <> :run
           OR id IN (
             SELECT id FROM {realm.table}
             WHERE {realm.owner} = :owner AND run_started_at = :run
             ORDER BY created_at DESC, id DESC
             OFFSET :keep))
    """


async def _drop_stale(
    session: AsyncSession, realm: _Realm, *, owner: UUID, run: datetime, keep: int
) -> None:
    await session.execute(text(_trim_sql(realm)), {"owner": owner, "run": run, "keep": keep})


async def load(
    session: AsyncSession,
    *,
    realm: _Realm,
    owner_id: UUID,
    run_started_at: datetime,
    limit: int = PAGE_DEFAULT,
    before: UUID | None = None,
) -> ConversationPage:
    """The most recent page of this person's live conversation, oldest first.

    THE STALE RUN IS DROPPED FIRST, in this same transaction. A read that merely FILTERED
    on the current run would leave the dead conversation on disk until a cron noticed —
    and the person's next question would then be answered while an unreadable copy of
    their last one was still stored. Clearing on read is what makes "the conversation dies
    when their last session ends" true at the moment they come back, rather than at the
    moment a job runs.
    """
    await _drop_stale(session, realm, owner=owner_id, run=run_started_at, keep=MAX_STORED_TURNS)
    rows = (
        await session.execute(
            text(_load_sql(realm)),
            {
                "owner": owner_id,
                "run": run_started_at,
                "before": before,
                # One more than asked for, to answer `has_more` without a COUNT.
                "limit": min(limit, PAGE_MAX) + 1,
            },
        )
    ).all()
    has_more = len(rows) > min(limit, PAGE_MAX)
    kept = rows[: min(limit, PAGE_MAX)]
    turns = tuple(
        StoredTurn(
            id=UUID(str(row[0])),
            role=str(row[1]),
            content=str(row[2]),
            screen_route=str(row[3]),
            said_at=str(row[4].isoformat()),
        )
        # Reversed, because the page was taken from the NEWEST end and is rendered from
        # the oldest.
        for row in reversed(kept)
    )
    return ConversationPage(turns=turns, has_more=has_more)


async def append_exchange(
    session: AsyncSession,
    *,
    realm: _Realm,
    owner_id: UUID,
    tenant_id: UUID | None,
    run_started_at: datetime,
    screen_route: str,
    question: str,
    answer: str,
) -> int:
    """Store one question and its answer. Returns how many rows were written (0, 1 or 2).

    IN THE CALLER'S TRANSACTION, and it must be, for `memory.remember_exchange`'s reason:
    `copilot/routes.py` calls this inside the session that already writes the meter and
    the audit, so a stored turn and the record of the answer it came from share a fate.

    TWO ROWS, NOT ONE. The memory table stores an exchange as one "Asked: … Answered: …"
    blob because a prompt reads it as one fact; a transcript is rendered as bubbles, and a
    panel that had to split a blob back into two would be parsing prose we wrote.

    Each half is redacted INDEPENDENTLY, so one empty half does not take the other with
    it: an answer that redacted down to nothing must still leave the question the person
    asked on screen, or the panel shows a reply to a message that is not there.

    It never raises and never refuses. The request has been answered and metered by the
    time this runs, and losing a turn is strictly better than turning a delivered answer
    into a 500 — `redacted_content` is written to the same contract.
    """
    written = 0
    for role, spoken in (("user", question), ("assistant", answer)):
        content = redacted_content(spoken)
        if not content:
            continue
        await session.execute(
            text(_insert_sql(realm)),
            {
                "id": uuid7(),
                "tenant_id": tenant_id,
                "owner": owner_id,
                "run": run_started_at,
                "role": role,
                "content": content,
                "route": screen_route[:200],
                "context": tenant_id,
            },
        )
        written += 1
    if written:
        # AFTER the insert, not before: trimming first would evict a turn to make room and
        # then leave the conversation one short of its own ceiling.
        await _drop_stale(session, realm, owner=owner_id, run=run_started_at, keep=MAX_STORED_TURNS)
    return written


async def clear(session: AsyncSession, *, realm: _Realm, owner_id: UUID) -> int:
    """Forget this person's whole conversation, whatever run it belongs to.

    The panel's own "start again", and the only path that removes a LIVE conversation.
    Returns the row count so the route can say what it did.
    """
    result = await session.execute(
        text(f"DELETE FROM {realm.table} WHERE {realm.owner} = :owner"), {"owner": owner_id}
    )
    return int(rowcount_of(result) or 0)


def turn_cursor(before: str | None) -> UUID | None:
    """The `before` cursor as a uuid, or None.

    A MALFORMED CURSOR IS `None`, NOT A 422. It is an opaque token this API issued, so a
    client sending a broken one is a client with a stale page — and answering the newest
    page is a recovery, where a validation error is a chat panel that refuses to open and
    cannot be talked out of it. The value is a predicate on the caller's OWN rows
    (`transcript._load_sql` scopes the sub-select on the owner too), so an invented one
    reaches nothing.
    """
    if before is None:
        return None
    try:
        return UUID(before)
    except ValueError:
        return None


def conversation_out(page: ConversationPage) -> CopilotConversationOut:
    return CopilotConversationOut(
        turns=[
            CopilotStoredTurnOut(
                id=str(turn.id),
                # `role` is a CHECK-constrained column, so the cast is a type assertion
                # rather than a trust decision — the database admits no third value.
                role="user" if turn.role == "user" else "assistant",
                content=turn.content,
                screen_route=turn.screen_route,
                said_at=turn.said_at,
            )
            for turn in page.turns
        ],
        has_more=page.has_more,
    )


__all__ = [
    "ADMIN",
    "CLIENT",
    "MAX_STORED_TURNS",
    "PAGE_DEFAULT",
    "PAGE_MAX",
    "ConversationPage",
    "StoredTurn",
    "append_exchange",
    "clear",
    "conversation_out",
    "load",
    "turn_cursor",
]
