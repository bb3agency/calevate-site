"""The read behind the aggregate: rows in, tokens out, transcripts never touched.

`patterns.py` is pure and knows nothing about a database; this module is the one place
that turns a tenant's rows into `CallOutcome`s. Keeping them apart is what makes the
guard testable — the wall can be driven with a hostile batch that no SQL could produce.

WHAT THIS QUERY IS ALLOWED TO SELECT, AND WHY THE LIST IS SHORT
---------------------------------------------------------------
Three columns of `calls` (`id`, `outcome_tag`, `sentiment`) and one JSONB of
`call_extractions` (`data`), for calls that ENDED inside the window. Not
`transcript_turns`, not `calls.summary`, not `from_e164`/`to_e164`, not
`call_extractions.moments`. Every one of those is caller-derived text, and the shortest
description of this module's job is that it never reads one.

`summary` is the near miss worth naming: it is a per-call AI summary, it is right there
in the same row, and it is exactly what somebody adding "top questions" would reach for.
It is transcript-derived — hard rule 6 — and `tests/kb_aggregate_guard_test.py` asserts
by SOURCE INVENTORY that this module does not name it. The precedent is
`tests/kb_tiers_test.py`'s token scan over `apps/voice-runtime`: a cheap net that catches
the change nobody would think to describe as a leak.

`data` DOES arrive here in full, because there is no way to ask Postgres for "only the
enum-valued keys this agent's schema declares" without building the key list into the
statement — and `CallOutcome.admit` is the door that drops the rest, in memory, before
anything is counted. The JSONB is never logged, never returned and never rendered; it
exists inside one comprehension.

WINDOW
------
Calls that ENDED in the window, not calls that started in it: a call that starts at
23:58 belongs to the day its outcome was decided, and `ended_at` is also the column that
is NULL for everything still in flight — so the filter that makes the window honest is
the same one that keeps unfinished calls out of a denominator.

AN ERASED CALLER IS NOT IN THE WINDOW AT ALL
---------------------------------------------
k-anonymity is a property of what is PUBLISHED, so a floor cleared at write time proves
nothing about a read taken after the underlying set changed — and the change that matters
here is a DPDP erasure, which is not a shrinking of the set but a REWRITE of it. The
erasure (`workers/retention.py`) leaves the `calls` row in place: it NULLs the numbers and
the summary, stamps `erased_subject_ref`, and empties `call_extractions.data`. It does not
touch `outcome_tag` or `sentiment`.

Counting such a row does three separate wrongs, and they were all measured on this
module before the predicate below existed:

1. the erased person's outcome and sentiment keep feeding a published statistic, so the
   certificate that said their data was destroyed is false about the one place it went;
2. their emptied extraction reads as "the agent captured nothing", so the digest gains a
   knowledge-gap line — "Preferred slot — missing on 5 of 25 calls" — that is FALSE about
   a working agent and is a statement about precisely the people who were erased;
3. the same window rendered before and after differences to exactly the erased subject's
   answers (25/25 becomes 20/25: the delta IS their data), which is the textbook
   differencing attack that a floor on the numerator cannot see.

A RETENTION SCRUB IS NOT AN ERASURE, AND GETS A DIFFERENT ANSWER
-----------------------------------------------------------------
The lead-clock retention sweep also empties `call_extractions.data`, and the emptied row
is byte-identical to one where the agent captured nothing — so on a tenant whose lead TTL
is shorter than this window, a required field the agent DID capture was published as a
gap: "Preferred slot — missing on 5 of 25 calls", about an agent that missed none.
`call_extractions.scrubbed_at` (migration f2a6d81b39c4) is the recorded fact that replaces
that inference; every sweep that empties the row stamps it in the same UPDATE.

The response is deliberately NOT the erasure's. An erasure removes a PERSON, so their
call leaves every family. A scrub removes only the EXTRACTION: `outcome_tag` and
`sentiment` are columns on `calls`, no sweep touches them, and they are still true — so a
scrubbed call stays in the outcome and sentiment counts at full weight and leaves only
`asked_about` and `not_captured`, numerator and denominator together (`patterns.
EXTRACTION_KINDS`). Dropping it from the outcome families too would have been the easy
symmetry and the wrong one: it silently shrinks a real statistic to fix a different one,
and a client with aggressive retention would see their outcome mix quietly stop matching
their call log.

So the predicate is `erased_subject_ref IS NULL` and it removes the call from the
NUMERATOR AND THE DENOMINATOR together. Shrinking the denominator can drop the window
below `MIN_CALLS_PER_WINDOW` and publish nothing at all, which is the safe direction and
the intended one. `erased_subject_ref` is on `tests/kb_aggregate_guard_test.py`'s
forbidden-source list because it names a SUBJECT; the test carves out this one spelling —
an `IS NULL` in a WHERE clause — and still fails if the column is ever SELECTed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from calevate_shared.extraction import ExtractionSchemaSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.kb.patterns import (
    CallOutcome,
    CallPattern,
    Vocabulary,
    assert_text_carries_no_call_content,
    distil,
)

log = get_logger(__name__)

#: The digest window. A week rather than a day for the reason the k-anonymity floor
#: exists: an SMB agent takes a handful of calls a day, and a daily window would spend
#: most of its life below `MIN_CALLS_PER_WINDOW` and publish nothing — which reads as a
#: broken feature rather than as a floor doing its job.
WINDOW_DAYS = 7

_SCHEMA_SQL = (
    "SELECT es.version, es.fields FROM agents a "
    "JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
    "WHERE a.id = :aid"
)

# `ended_at` bounds, `agent_id` scopes, RLS does the tenant. The LEFT JOIN is what makes
# a call with no extraction count in the denominator: an agent that captured nothing on
# forty calls has a knowledge gap, and an INNER JOIN would hide precisely those calls
# from the arithmetic meant to find them.
#
# NO `LIMIT`, and that is deliberate against D-302's bounding doctrine rather than an
# omission of it. The bound here is the WINDOW: one agent, one week of finished calls, so
# the row count is bounded by how many calls one phone line can take in seven days — a few
# thousand at the absolute ceiling, of four small columns. A `LIMIT` would be worse than
# unbounded: it would silently shrink the DENOMINATOR every count in the digest is a
# fraction of, so a busy agent's "missing on 41 of 200 calls" would describe a week that
# had 900. A truncated aggregate is not a smaller true statement, it is a false one.
#
# `c.erased_subject_ref IS NULL` is the erasure predicate — see the module docstring for
# the three things counting an erased row does. It is a WHERE clause and never a SELECT:
# the value is a subject handle and nothing here may read it.
#
# `e.scrubbed_at IS NOT NULL` is projected to a BOOLEAN in the statement rather than
# selected as a timestamp, and that is the same discipline the rest of this SELECT keeps:
# the only question this module may ask of the column is "can we still read this row",
# and an instant is a fact about one call that nothing here has any use for. The LEFT JOIN
# makes it FALSE for a call with no extraction at all, which is the right answer — nothing
# was destroyed, the agent simply produced none.
_OUTCOMES_SQL = (
    "SELECT c.id, c.outcome_tag, c.sentiment, e.data, "
    "(e.scrubbed_at IS NOT NULL) AS extraction_scrubbed FROM calls c "
    "LEFT JOIN call_extractions e ON e.call_id = c.id "
    "WHERE c.agent_id = :aid AND c.ended_at >= :since AND c.ended_at < :until "
    "AND c.erased_subject_ref IS NULL "
    "ORDER BY c.ended_at"
)


@dataclass(frozen=True, slots=True)
class AgentInsights:
    """One agent's window, distilled. `patterns` is empty when a floor was not cleared,
    and `calls` says which floor — a caller can tell "quiet week" from "nothing stood
    out" without asking a second question.

    TWO POPULATIONS, NAMED, because there genuinely are two and a single number would have
    to lie about one of them. `calls` is every completed call in the window: it is what
    `outcome` and `sentiment` counts are out of, and it is the honest answer to "how busy
    was the week". `calls_with_details` is the subset whose extraction we can still read,
    which is what `asked_about` and `not_captured` are out of — a retention scrub destroys
    the extraction and leaves the call, so the second number can be smaller than the first
    and every count in the digest still be exactly true. `render_digest` says out loud
    which one a line was counted over whenever they differ, rather than printing two
    denominators and letting a reader guess.
    """

    agent_id: UUID
    calls: int
    calls_with_details: int
    patterns: list[CallPattern]
    vocabulary: Vocabulary


async def vocabulary_for_agent(session: AsyncSession, agent_id: UUID) -> Vocabulary | None:
    """The agent's published extraction schema as a vocabulary, or None if it has none.

    None is a real answer and not an error: an agent with no extraction schema has no
    client-authored vocabulary, so the only tokens available would be our own two enums —
    outcome and sentiment counts with nothing to attach them to. A digest of that is
    noise, and returning None lets the caller skip the agent rather than render one.
    """
    row = (await session.execute(text(_SCHEMA_SQL), {"aid": agent_id})).first()
    if row is None:
        return None
    version, fields = row
    spec = ExtractionSchemaSpec.model_validate({"version": version, "fields": fields})
    return Vocabulary.for_schema(spec)


async def insights_for_agent(
    session: AsyncSession,
    *,
    agent_id: UUID,
    since: datetime,
    until: datetime,
) -> AgentInsights | None:
    """Distil one agent's window. None means "this agent has no vocabulary to speak in".

    The session must already be tenant-scoped (`tenant_session`): nothing here filters on
    `tenant_id` and nothing here should, because a WHERE clause a caller can forget is
    exactly the isolation hard rule 1 refuses to rely on. RLS is the boundary; this
    statement scopes to the AGENT inside it.
    """
    vocabulary = await vocabulary_for_agent(session, agent_id)
    if vocabulary is None:
        return None

    rows = (
        await session.execute(
            text(_OUTCOMES_SQL), {"aid": agent_id, "since": since, "until": until}
        )
    ).all()

    outcomes = [
        CallOutcome.admit(
            call_id=UUID(str(row[0])),
            vocabulary=vocabulary,
            outcome_tag=row[1],
            sentiment=row[2],
            extraction=_mapping_or_none(row[3]),
            extraction_scrubbed=bool(row[4]),
        )
        for row in rows
    ]
    patterns = distil(outcomes, vocabulary=vocabulary)
    # DISTINCT CALLS, not rows, in both numbers — the row count and the call count are
    # equal only because `call_extractions` is UNIQUE on `(tenant_id, call_id)`, which is
    # a fact about a table this module does not name. `calls` is what `distil` divides the
    # outcome and sentiment families by and `calls_with_details` is what it divides the
    # extraction families by, so counting either of them a second way here is how a screen
    # comes to say "41 of 30" (`CallPattern`'s own docstring, on carrying the denominator).
    return AgentInsights(
        agent_id=agent_id,
        calls=len({outcome.call_id for outcome in outcomes}),
        calls_with_details=len(
            {outcome.call_id for outcome in outcomes if outcome.extraction_readable}
        ),
        patterns=patterns,
        vocabulary=vocabulary,
    )


def _mapping_or_none(value: Any) -> dict[str, object] | None:
    """`call_extractions.data` is JSONB and NOT NULL, so psycopg hands back a dict — but
    the LEFT JOIN above produces NULL for a call with no extraction at all, and a
    hand-written row in a fixture can produce a list. Anything that is not a mapping is
    "nothing was captured", which is the same fact the required-field arm needs."""
    return value if isinstance(value, dict) else None


def render_digest(insights: AgentInsights, *, agent_name: str, limit: int = 5) -> str | None:
    """The owner-facing digest, or None when there is nothing to say.

    ASSEMBLED FROM A TEMPLATE, OUR COUNTS AND THE CLIENT'S OWN LABELS — no value from any
    call reaches it, and `assert_text_carries_no_call_content` re-checks the finished
    string before it is handed back. See `patterns.assert_text_carries_no_call_content`
    for what that check can and cannot see.

    It is ADVICE, and the wording keeps it advice. It is deliberately not a draft of
    anything an agent could say: the system can prove that callers keep reaching a field
    the agent does not capture, and it cannot know what the right answer is — only the
    business owner does. A digest that proposed the ANSWER would be putting a sentence
    nobody in the business wrote into a queue whose approve button is one click, on the
    strength of a statistic.

    WHEN THE TWO POPULATIONS DIFFER IT SAYS SO, IN THE CLIENT'S OWN TERMS. The header
    counts every completed call; the reason-for-calling and missed-detail lines count only
    the calls whose captured details are still on file, because the client's own retention
    policy destroyed the rest (`AgentInsights`). Printing "20 of 18 calls" under "Across
    25 completed calls" with no explanation is how a correct digest gets reported as a
    bug, so the difference is stated as the client's own setting rather than left as
    arithmetic that does not add up.
    """
    if not insights.patterns:
        return None

    gaps = [p for p in insights.patterns if p.kind == "not_captured"][:limit]
    asked = [p for p in insights.patterns if p.kind == "asked_about"][:limit]
    follow_up = next((p for p in insights.patterns if p.token == "outcome:needs_follow_up"), None)

    lines = [
        f"What your callers asked {agent_name} this week",
        "",
        f"Across {insights.calls} completed calls:",
    ]
    if (asked or gaps) and insights.calls_with_details < insights.calls:
        lines += [
            "",
            f"The details below are counted over {insights.calls_with_details} of those "
            f"{insights.calls} calls. Your data-retention setting has already cleared the "
            "captured details of the rest, so they are left out of these counts rather "
            "than counted as calls where nothing was captured.",
        ]
    if asked:
        lines += ["", "Most common reasons for calling:"]
        lines += [
            f"  - {insights.vocabulary.label_for(p.token)} — {p.calls} of {p.of_calls} calls"
            for p in asked
        ]
    if gaps:
        lines += [
            "",
            "Details the agent was asked to capture and often did not:",
        ]
        lines += [
            f"  - {insights.vocabulary.label_for(p.token)} — missing on {p.calls} of "
            f"{p.of_calls} calls"
            for p in gaps
        ]
        lines += [
            "",
            "Adding a line of knowledge about these usually fixes them. Open Knowledge in "
            "your Calevate dashboard and write what the agent should say — it goes live "
            "after review, like any other knowledge you add.",
        ]
    if follow_up is not None:
        lines += [
            "",
            f"{follow_up.calls} of {follow_up.of_calls} calls ended needing a follow-up.",
        ]
    # "counts only" rather than "this summary is counts only": `calls.summary` is the
    # column this whole module must not read, and `tests/kb_aggregate_guard_test.py`
    # forbids the token in executable source deliberately bluntly — a scan that tried to
    # tell the English word from the column name would be the kind of clever check that
    # eventually waves the column through.
    lines += ["", "These are counts only. Nothing any caller said appears above."]

    body = "\n".join(lines)
    # The client's own labels are the only text here they wrote, so they are what the
    # guard elides before looking for a phone-shaped digit run — see
    # `patterns.assert_text_carries_no_call_content` for why eliding them matters.
    assert_text_carries_no_call_content(body, declared=insights.vocabulary.labels.values())
    return body


__all__ = [
    "WINDOW_DAYS",
    "AgentInsights",
    "insights_for_agent",
    "render_digest",
    "vocabulary_for_agent",
]
