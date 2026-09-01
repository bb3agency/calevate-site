"""What the ADMIN copilot remembers, for one OPERATOR, and why it cannot share a table.

`copilot/memory.py` is the design document — redaction on the way in, a recency channel and
a relevance channel with their own budgets unioned rather than one ranked list, lexical and
not semantic because there is no embedding path in this repository to reuse. Every one of
those arguments holds here unchanged and is not restated. This module states the two things
that DIFFER, and both come from the same fact.

## THE FACT: `Principal.user_id` IS TWO ID SPACES

It is a `users.id` on the client realm and an `admin_users.id` on the admin realm, and
`copilot_memories.user_id` has a foreign key to `users`. So writing an operator's memory
into that table is a constraint violation when the id happens not to collide and a
CROSS-REALM LEAK when it does — recall's only predicate is `user_id`, so a client asking
their own copilot a question would get an operator's notes about their account handed back
into the answer. `copilot/routes.py` already guards the write with
`principal.realm == "client"` and its comment calls the guard "the difference between 'this
cannot happen' and 'this cannot happen because of a permission list two modules away'".
This module is what that guard was waiting for.

## WHAT DIFFERS: THE TABLE, AND ONE EXTRA PREDICATE

1. `admin_copilot_memories`, keyed on `admin_user_id`, read and written on an
   `untenanted_session()` — it carries no `tenant_id` and no RLS policy, so a tenant GUC
   neither hides it nor is needed to see it.
2. **`viewing_tenant_id` IS PART OF RECALL, NOT JUST OF THE ROW.** A memory formed while an
   operator was looking at one client ("their KYC is with the founder") is a fact about that
   client and NOT about the platform, and recalling it into a question asked on a different
   account's page is how an assistant comes to answer about the wrong client with total
   confidence. So the relevance and recency channels both match the CURRENT view: rows with
   no viewing tenant (platform-level memories) are always eligible, rows tied to a tenant are
   eligible only when that tenant is the one open. This is the one thing this module adds to
   its twin, and it is added because the admin realm has a dimension the client realm does
   not — a client's copilot is always inside exactly one account.

WHAT THIS MODULE DOES NOT DO: distil. There is no admin distillation worker and this change
does not create one, so nothing here writes a `semantic` row. The kind is still accepted by
the CHECK so a future distiller writes rows rather than DDL.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.memory import (
    KIND_EPISODIC,
    RECALL_CHAR_BUDGET,
    RECALL_ITEM_CHARS,
    RECENCY_HALF_LIFE_DAYS,
    RECENCY_WEIGHT,
    RECENT_LIMIT,
    RELEVANCE_WEIGHT,
    RELEVANT_LIMIT,
    RecalledMemory,
    redacted_content,
)
from apps.api.copilot.models import SEARCH_CONFIG
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

#: `ts_rank_cd`'s normalisation flag, the same value `memory._RANK_NORMALIZATION` uses.
#: Re-spelled rather than imported because it is private there; the two are pinned equal by
#: `tests/admin_copilot_memory_test.py` rather than left to agree by luck.
_RANK_NORMALIZATION: Final = 32


async def remember_exchange(
    session: AsyncSession,
    *,
    admin_user_id: UUID,
    viewing_tenant_id: UUID | None,
    screen_route: str,
    question: str,
    answer: str,
    meta: dict[str, Any] | None = None,
) -> UUID | None:
    """Record one operator question-and-answer. Returns its id, or None.

    IN THE CALLER'S TRANSACTION, for `memory.remember_exchange`'s reason: the admin route
    calls this inside the session that already writes the platform meter and the audit row,
    so a memory of an answer whose `platform_ai_usage` rows rolled back is unreachable.

    `None` on empty content means the exchange redacted down to nothing, which is a one-word
    question and a one-word answer — not a failure to report. The label-only-if-non-blank
    construction is copied deliberately from the client writer: building the labels
    unconditionally makes the string non-blank even for a whitespace question, so
    `redacted_content`'s emptiness test — the whole of this function's error handling —
    could never fire and the row would be stored as the literal "Asked:".
    """
    content = redacted_content(
        f"Asked: {question}" if question.strip() else "",
        f"Answered: {answer}" if answer.strip() else "",
    )
    if not content:
        return None
    memory_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO admin_copilot_memories "
            "(id, admin_user_id, viewing_tenant_id, kind, content, screen_route, meta, "
            " created_at, updated_at) "
            "VALUES (:id, :aid, :viewing, :kind, :content, :route, CAST(:meta AS jsonb), "
            "        now(), now())"
        ),
        {
            "id": memory_id,
            "aid": admin_user_id,
            "viewing": viewing_tenant_id,
            "kind": KIND_EPISODIC,
            "content": content,
            "route": screen_route[:200],
            "meta": None if meta is None else json.dumps(meta),
        },
    )
    return memory_id


# TWO RETRIEVERS, THEIR OWN LIMITS, THEN A UNION — `memory._RECALL_SQL`'s shape, with one
# predicate added to both channels. `:viewing` NULL means "no account is open", and then
# only platform-level memories are eligible: a memory tied to a client is not a fact about
# the platform and must not be recalled as one. When an account IS open, its own memories
# and the platform-level ones are both eligible, which is exactly what an operator looking
# at that client would want in front of the model.
#
# `websearch_to_tsquery` rather than `plainto_tsquery`, for the client module's reason: it
# is the parser that never raises on user text, and an empty or stopword-only question
# yields an empty tsquery so the relevance channel returns nothing and recency still
# answers.
_ADMIN_ELIGIBLE = (
    "m.admin_user_id = :aid AND "
    "(m.viewing_tenant_id IS NULL OR m.viewing_tenant_id = CAST(:viewing AS uuid))"
)
_RECALL_SQL = f"""
WITH q AS (SELECT websearch_to_tsquery('{SEARCH_CONFIG}', :question) AS query),
recent AS (
  SELECT m.id FROM admin_copilot_memories m
  WHERE {_ADMIN_ELIGIBLE}
  ORDER BY m.created_at DESC
  LIMIT :recent_limit
),
relevant AS (
  SELECT m.id FROM admin_copilot_memories m, q
  WHERE {_ADMIN_ELIGIBLE} AND m.search @@ q.query
  ORDER BY ts_rank_cd(m.search, q.query, {_RANK_NORMALIZATION}) DESC, m.created_at DESC
  LIMIT :relevant_limit
)
SELECT m.id, m.kind, m.content, m.screen_route,
       (m.id IN (SELECT id FROM recent))   AS from_recent,
       (m.id IN (SELECT id FROM relevant)) AS from_relevant
FROM admin_copilot_memories m, q
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
    session: AsyncSession,
    *,
    admin_user_id: UUID,
    viewing_tenant_id: UUID | None,
    question: str,
) -> tuple[RecalledMemory, ...]:
    """This operator's memories worth putting in front of the model for THIS question.

    NEVER RAISES INTO A COPILOT TURN, for `memory.recall`'s reason and with more force: an
    operator asking about an incident must get an answer without memory rather than an error
    instead of an answer. The failure is logged with its type, which is what an operator can
    act on; they cannot act on a spinner that stops.

    The budgets, the truncation and the blended order are the client module's constants,
    imported rather than re-chosen — two memory surfaces that recall different amounts for
    different reasons is a difference nobody could explain later.
    """
    try:
        rows = (
            await session.execute(
                text(_RECALL_SQL),
                {
                    "aid": admin_user_id,
                    "viewing": viewing_tenant_id,
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
        log.warning("admin_copilot_recall_failed", extra={"error": type(failure).__name__})
        return ()

    recalled: list[RecalledMemory] = []
    spent = 0
    for row in rows:
        content = str(row[2]).strip()
        if len(content) > RECALL_ITEM_CHARS:
            content = content[: RECALL_ITEM_CHARS - 1].rstrip() + "…"
        if spent + len(content) > RECALL_CHAR_BUDGET:
            # A STOP, not a skip: the rows are already in blended-score order, so
            # everything past this point scores lower than what was dropped.
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


__all__ = ["recall", "remember_exchange"]
