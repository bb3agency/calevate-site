"""What the copilot remembers between conversations, and how a turn gets it back.

`copilot/__init__.py` said "NOTHING IN THIS PACKAGE PERSISTS ANYTHING", and cited
`crm/assist.py:10-31`: a table of model-written prose about a person's screen re-opens
DPDP erasure and retention on a surface that had neither. **This module is that table's
writer and reader, so it is also where the two obligations that sentence was protecting
are discharged**, and the migration (`d4a9c17e6b02`) carries the rest.

THE THREE THINGS THAT ARE DIFFERENT FROM A NAIVE MEMORY STORE, in the order they matter.

1. **REDACTION ON THE WAY IN, not only in logs.** Hard rule 6 governs log lines; this is
   stricter because it PERSISTS. `redacted_content` runs `workers.redaction.redact` — the
   same primitive `pipeline.py`, `run_assist` and `copilot/sanitize.assert_redacted` use —
   over every string before it reaches a column. That is belt AND braces: the route already
   refuses a request `redact()` still changes, so nothing personal should arrive here at
   all; what this catches is the half the route CANNOT check, which is the model's own
   output. A model that invents a phone-shaped number in an answer would otherwise put it
   in a durable row.

   ⚠ **AND THE LIMIT OF THAT IS WORTH STATING RATHER THAN LEAVING FOR SOMEONE TO FIND.**
   `redact()` recognises IDENTIFIERS — phone numbers, email addresses, Aadhaar, PAN, card
   numbers, OTPs, UPI handles. It does not recognise a PROPER NOUN, so a staff member who
   types "what did Lakshmi's enquiry say" leaves a first name in a memory row. That is why
   the tenant-erasure arm below is unconditional (it DELETEs every row, it does not blank
   a matched one) and why the retention clock is 180 days rather than the transcript's
   365: neither mechanism can key on a name, so the only defences are that the row expires
   and that offboarding destroys it. Recorded, not hidden.

2. **RECALL IS HYBRID — RECENCY *AND* RELEVANCE — AND RECENCY CANNOT BE STARVED.** Two
   retrievers with their own budgets, unioned, not one ranked list. The recent channel
   returns this person's last `RECENT_LIMIT` memories whatever they say; the relevant
   channel returns the best `RELEVANT_LIMIT` lexical matches at any age. A single blended
   ORDER BY was the tempting shape and is the one that fails in production: a strong old
   match outranks the thing that happened ninety seconds ago, and the assistant answers
   about state the person has already changed. With two budgets the freshest rows are
   present unconditionally — recency does not merely *outrank* similarity, it is
   structurally guaranteed a seat. The blended score below only ORDERS what both channels
   already found.

3. **THE RELEVANCE CHANNEL IS LEXICAL, NOT SEMANTIC, AND THAT IS A FINDING.** There is no
   embedding path in this repository to reuse. D-28 made retrieval a managed API service
   that owns its own embeddings; `kb/models.KbDocument` says "No embedding column, by
   decision (D-28)"; `kb/__init__.py:11` records `kb_chunks` + pgvector as CONTINGENCY;
   `calevate_shared/config.py:766-774` records `COHERE_API_KEY` being REMOVED because
   "NOTHING in this repository ever read it". Grepped this session, not recalled: no
   `CREATE EXTENSION vector`, no `vector(` in any migration, no embedding call in `apps/`.
   So the honest options were a lexical channel that works today or a vector column nobody
   populates, and a column nobody populates is the defect CLAUDE.md names by hand.

   `_RECALL_SQL` is written so a similarity channel is a THIRD CTE and one more row in the
   union — no caller changes, no signature changes — on the day a retrieval provider is
   configured. Do not add one before then.

WHAT THIS MODULE DOES NOT DO: distil. That is `apps/workers/copilot_memory.py`, on a cron,
because reading a conversation back to a model costs money and latency a person is sitting
in front of. `remember_exchange` writes one row and returns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.models import MAX_CONTENT_CHARS, SEARCH_CONFIG
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.workers.redaction import redact

log = get_logger(__name__)

#: How many of this person's most recent memories are returned WHATEVER they say. Three,
#: because that is one exchange plus the two before it — enough to answer "and change the
#: other one too" — and because every item here is paid input tokens on the next turn.
RECENT_LIMIT: Final = 3

#: How many best-matching memories are returned at ANY age. Same size as the recent
#: channel: neither retriever may crowd the other out, which is the whole point of giving
#: them separate budgets.
RELEVANT_LIMIT: Final = 3

#: The ceiling on what recall hands the prompt builder, in characters, across all items.
#: A hard bound rather than a hope: this text is on every copilot turn, so an unbounded
#: recall is unbounded spend on a surface that is already metered per answer. ~1,200
#: characters is roughly 300-400 tokens of English and rather more of Telugu, which is
#: small beside the screen description the prompt already carries.
RECALL_CHAR_BUDGET: Final = 1_200

#: One item's share, so a single long memory cannot consume the whole budget and leave the
#: other five silently dropped.
RECALL_ITEM_CHARS: Final = 300

#: How fast the recency term decays: a memory `RECENCY_HALF_LIFE_DAYS` old scores half what
#: one written now scores. Seven days is the span over which a console conversation stops
#: being about the thing the person is still doing.
RECENCY_HALF_LIFE_DAYS: Final = 7.0

#: The blend used to ORDER the union (never to select it — see the module docstring). Both
#: terms are in [0, 1): recency is `0.5 ** (age_days / half_life)`, and `ts_rank_cd`'s
#: normalisation flag 32 divides the rank by itself plus one. Weighted toward recency
#: because when the two disagree about which of two memories describes the CURRENT state of
#: the business, the newer one is right by construction.
RECENCY_WEIGHT: Final = 0.6
RELEVANCE_WEIGHT: Final = 0.4

#: `ts_rank_cd`'s normalisation bitmask. 32 = "divide the rank by itself + 1", which is the
#: only flag that yields a BOUNDED score (postgresql.org/docs/16/textsearch-controls.html
#: §12.3.3, read 31 Aug 2026). Bounded matters here and nowhere else in this repo: an
#: unbounded rank added to a [0,1) recency term is not a blend, it is relevance with a
#: rounding error attached.
_RANK_NORMALIZATION: Final = 32

KIND_EPISODIC: Final = "episodic"
KIND_SEMANTIC: Final = "semantic"


@dataclass(frozen=True, slots=True)
class RecalledMemory:
    """One thing worth telling the model, and which retriever found it.

    `from_recent` is carried rather than derived because it is the only thing that
    distinguishes "this happened just now" from "this matched your words" — and a prompt
    that presents the two identically invites the model to treat a year-old business fact
    as something the person just said.
    """

    id: UUID
    kind: str
    content: str
    screen_route: str | None
    from_recent: bool
    from_relevant: bool


def redacted_content(*parts: str) -> str:
    """The parts, joined, redacted and capped — the ONE way text becomes a memory row.

    Returns `""` when there is nothing left worth storing, so a caller's `if not content`
    is the whole of its error handling. It never raises and never refuses: the request has
    already been answered and metered by the time this runs, and losing the memory is
    strictly better than turning a delivered answer into a 500.

    Cap BEFORE the DB sees it, so a violation surfaces as a short memory rather than as
    `ck_copilot_memories_content_cap` in a stack trace. The truncation marker is visible
    on purpose: a model reading a memory should be able to tell it is reading a fragment.
    """
    joined = "\n".join(part.strip() for part in parts if part and part.strip())
    if not joined.strip():
        return ""
    result = redact(joined)
    if result.changed:
        # KINDS, never the text and never the value (hard rule 6). This line is how an
        # operator learns the input guard is being reached from the model side, which is
        # the one direction `sanitize.assert_redacted` cannot see.
        log.warning("copilot_memory_redacted_on_write", extra={"kinds": len(result.kinds)})
    cleaned = result.text.strip()
    if len(cleaned) > MAX_CONTENT_CHARS:
        cleaned = cleaned[: MAX_CONTENT_CHARS - 1].rstrip() + "…"
    return cleaned


async def remember_exchange(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    screen_route: str,
    question: str,
    answer: str,
    meta: dict[str, Any] | None = None,
) -> UUID | None:
    """Record one question-and-answer as an episodic memory. Returns its id, or None.

    IN THE CALLER'S TRANSACTION, and it must be — `copilot/routes.py` calls this inside the
    session that already writes the meter and the audit, so a memory row and the record of
    the answer it came from share a fate. A memory of an answer whose `usage_events` row
    rolled back is a memory of something that, as far as the ledger is concerned, never
    happened.

    `None` on empty content is not a failure to report: it means the exchange redacted down
    to nothing, which is a person asking a one-word question and getting a one-word answer.
    """
    # THE LABELS ARE ADDED ONLY TO PARTS THAT HAVE SOMETHING IN THEM, and this is the one
    # subtlety in the function. Building `f"Asked: {question}"` unconditionally makes the
    # string non-blank even when the question is whitespace, so `redacted_content`'s
    # emptiness test — which is the whole of this function's error handling — could never
    # fire and an exchange with no content would be stored as the literal "Asked:".
    # Found by `tests/copilot_memory_test.test_an_empty_exchange_writes_nothing`.
    content = redacted_content(
        f"Asked: {question}" if question.strip() else "",
        f"Answered: {answer}" if answer.strip() else "",
    )
    if not content:
        return None
    memory_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO copilot_memories "
            "(id, tenant_id, user_id, kind, content, screen_route, meta, created_at, updated_at) "
            "VALUES (:id, :tid, :uid, :kind, :content, :route, CAST(:meta AS jsonb), now(), now())"
        ),
        {
            "id": memory_id,
            "tid": tenant_id,
            "uid": user_id,
            "kind": KIND_EPISODIC,
            "content": content,
            "route": screen_route[:200],
            "meta": None if meta is None else json.dumps(meta),
        },
    )
    return memory_id


# TWO RETRIEVERS, THEIR OWN LIMITS, THEN A UNION — see the module docstring for why this is
# not one ranked query.
#
# `tenant_id` is NOT in any predicate here, and its absence is the tenancy argument rather
# than an oversight: every caller runs inside `db.session.tenant_session`, the table carries
# a FORCEd `tenant_isolation` policy, and a hand-written `tenant_id =` beside it would be a
# second, weaker copy of a guarantee the database already makes unconditionally. `user_id`
# IS a predicate, because RLS answers "which tenant" and never "which person"
# (`crm/models.LeadSavedView` states the same split).
#
# `websearch_to_tsquery` rather than `plainto_tsquery`: it is the parser that never raises
# on user text (`to_tsquery` does, on a stray `&` or `!`), and this input is a sentence a
# person typed. An empty or stopword-only question yields an empty tsquery, which matches
# nothing — so the relevant channel returns zero rows and the recent channel still answers.
_RECALL_SQL = f"""
WITH q AS (SELECT websearch_to_tsquery('{SEARCH_CONFIG}', :question) AS query),
recent AS (
  SELECT m.id FROM copilot_memories m
  WHERE m.user_id = :uid
  ORDER BY m.created_at DESC
  LIMIT :recent_limit
),
relevant AS (
  SELECT m.id FROM copilot_memories m, q
  WHERE m.user_id = :uid AND m.search @@ q.query
  ORDER BY ts_rank_cd(m.search, q.query, {_RANK_NORMALIZATION}) DESC, m.created_at DESC
  LIMIT :relevant_limit
)
SELECT m.id, m.kind, m.content, m.screen_route,
       (m.id IN (SELECT id FROM recent))   AS from_recent,
       (m.id IN (SELECT id FROM relevant)) AS from_relevant
FROM copilot_memories m, q
WHERE m.id IN (SELECT id FROM recent) OR m.id IN (SELECT id FROM relevant)
ORDER BY
  :recency_weight
    * power(
        0.5,
        EXTRACT(EPOCH FROM (now() - m.created_at)) / (86400 * :half_life_days)
      )
  + :relevance_weight
    * COALESCE(ts_rank_cd(m.search, q.query, {_RANK_NORMALIZATION}), 0)
  DESC,
  m.created_at DESC
"""


async def recall(
    session: AsyncSession, *, user_id: UUID, question: str
) -> tuple[RecalledMemory, ...]:
    """This person's memories worth putting in front of the model for THIS question.

    At most `RECENT_LIMIT + RELEVANT_LIMIT` items (fewer when a row satisfies both
    channels), each truncated to `RECALL_ITEM_CHARS` and the whole list to
    `RECALL_CHAR_BUDGET`. Ordered by the recency/relevance blend, so the caller can render
    them in order and stop when its own budget runs out without re-ranking anything.

    NEVER RAISES INTO A COPILOT TURN. Recall is an enhancement, not a precondition: a
    person whose memory query failed should get an answer without memory, not an error
    instead of an answer. The failure is logged with its type — an operator can act on
    that; the person cannot act on anything.
    """
    try:
        rows = (
            await session.execute(
                text(_RECALL_SQL),
                {
                    "uid": user_id,
                    "question": question,
                    "recent_limit": RECENT_LIMIT,
                    "relevant_limit": RELEVANT_LIMIT,
                    "recency_weight": RECENCY_WEIGHT,
                    "relevance_weight": RELEVANCE_WEIGHT,
                    "half_life_days": RECENCY_HALF_LIFE_DAYS,
                },
            )
        ).all()
    except Exception as failure:
        log.warning("copilot_recall_failed", extra={"error": type(failure).__name__})
        return ()

    recalled: list[RecalledMemory] = []
    spent = 0
    for row in rows:
        content = str(row[2]).strip()
        if len(content) > RECALL_ITEM_CHARS:
            content = content[: RECALL_ITEM_CHARS - 1].rstrip() + "…"
        if spent + len(content) > RECALL_CHAR_BUDGET:
            # The budget is a STOP, not a skip: the rows are already in blended-score
            # order, so everything after this point scores lower than what was dropped.
            break
        spent += len(content)
        recalled.append(
            RecalledMemory(
                id=UUID(str(row[0])),
                kind=str(row[1]),
                content=content,
                screen_route=None if row[3] is None else str(row[3]),
                from_recent=bool(row[4]),
                from_relevant=bool(row[5]),
            )
        )
    return tuple(recalled)


def render_for_prompt(memories: tuple[RecalledMemory, ...]) -> str:
    """The recalled memories as one XML block, or `""` when there is nothing to say.

    XML-fenced for `prompt.py`'s reason (the screen state is fenced the same way): a block
    with a name is a block the model can be told to treat as reference rather than as
    instruction, and untagged prose pasted into a system prompt is indistinguishable from
    the prompt.

    `recent` vs `remembered` is the distinction the model needs and the one a single list
    destroys — see `RecalledMemory.from_recent`.
    """
    if not memories:
        return ""
    lines = ["<memory>"]
    for item in memories:
        origin = "recent" if item.from_recent else "remembered"
        where = f' screen="{item.screen_route}"' if item.screen_route else ""
        lines.append(f'  <item origin="{origin}" kind="{item.kind}"{where}>{item.content}</item>')
    lines.append("</memory>")
    return "\n".join(lines)


__all__ = [
    "KIND_EPISODIC",
    "KIND_SEMANTIC",
    "RECALL_CHAR_BUDGET",
    "RECALL_ITEM_CHARS",
    "RECENCY_HALF_LIFE_DAYS",
    "RECENCY_WEIGHT",
    "RECENT_LIMIT",
    "RELEVANCE_WEIGHT",
    "RELEVANT_LIMIT",
    "RecalledMemory",
    "recall",
    "redacted_content",
    "remember_exchange",
    "render_for_prompt",
]
