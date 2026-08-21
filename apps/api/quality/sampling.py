"""The weekly QA spot-check: drawing it, listing it, recording a review (SURFACES §1).

SURFACES §1 asks for "QA sampling: spot-check ~5% of calls per client per week (queue
surfaced in admin)". Nothing implemented it. This module is the draw and the queue.

WHAT MAKES A SAMPLE DEFENSIBLE
-------------------------------
A spot-check nobody can reconstruct is a habit, not a control — and this one is
compliance-adjacent, so the question "which calls did you review last week, and why
those?" has to have an answer that does not depend on anyone's memory.

**The order is a keyed hash, not a random number.** Calls are ordered by
`md5(seed || call_id)` where `seed = '<tenant_id>:<week_start>'`, and the row stores both
the seed and the resulting rank. Anyone can re-run that expression years later and get
the same list. Two alternatives were considered and rejected:

* `ORDER BY random()` — reproducible only if you also store the seed AND the exact
  Postgres version's RNG behaviour, and unauditable in practice. "The RNG picked it" is
  not something a reviewer can stand behind in front of a regulator.
* `TABLESAMPLE SYSTEM (5)` — samples PAGES, not rows. On a table written in arrival
  order that correlates the sample with time of day, so the 5% would systematically
  over-represent whichever hours happened to fill a page. It is also not reproducible.

The seed CHANGES PER WEEK on purpose. A seed of just the tenant id would rank a given
call the same way forever, so a call that sorted late would be skipped every week it was
eligible — a stable bias in favour of never looking at the same corner of the data.

**The frame is stored with the draw.** `population` (calls that week) and `target` (what
5% came to) sit on every row, so a queue of twelve rows can say whether it is 5% of 240
calls or everything the tenant had. Without them "we sample 5%" is unfalsifiable.

**Nothing is re-sampled silently.** `UNIQUE (tenant_id, call_id)` plus
`ON CONFLICT DO NOTHING`, so a retry, a late tick or a backfill of an old week converges
on the set that was already drawn instead of drawing a second one.

WHAT THE FRAME IS
------------------
Completed calls only. A `no_answer` or `failed` row has no conversation in it, so
reviewing one reviews nothing, and including them would inflate the denominator with
rows the sample can never learn anything from — 5% of a number padded with non-calls is
not 5% of the calls.

HARD RULE 5
------------
Nothing in this module reads transcript text. The queue row carries ids, timings and
tags; the reviewer opens the call through `crm.service.get_call(raw=False)` — the SAME
function the client's own call screen uses, which returns `text_redacted`. There is
deliberately no raw path here: raw transcript text has exactly one route in this
codebase (`GET /v1/calls/{call_id}/transcript/raw`, role-checked and audit-logged), and
a second one built for reviewers would be a second answer to the question hard rule 5
asks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.crm.performance import IST_ZONE
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.quality.models import QA_SAMPLE_RATE, QA_VERDICTS, Verdict

#: The zone, from the one place that names it (`crm/performance.IST_ZONE`) — a second
#: literal 'Asia/Kolkata' is not a duplicate string, it is a second answer to "which
#: zone is IST" waiting to drift.
_IST_TZ = ZoneInfo(IST_ZONE)

#: The IST Monday a call belongs to. `date_trunc('week', ...)` is ISO — weeks start
#: Monday — and the shift into IST is what makes it an Indian business week rather than
#: a UTC one (`IST_DAY_SQL` in crm/performance.py makes the same argument for days).
_IST_WEEK_SQL = f"date_trunc('week', started_at AT TIME ZONE '{IST_ZONE}')::date"

#: The draw. `md5(seed || id)` orders the frame; `id` breaks a tie so the order is total
#: even in the (astronomically unlikely) event of a digest collision. `count(*) OVER ()`
#: gives the population in the same pass, so the frame and the draw cannot be measured a
#: microsecond apart and disagree.
_DRAW_SQL = f"""
WITH frame AS (
    SELECT id, md5(:seed || id::text) AS k
    FROM calls
    WHERE status = 'completed' AND {_IST_WEEK_SQL} = :week_start
), ranked AS (
    SELECT id, k,
           row_number() OVER (ORDER BY k, id) AS rank,
           count(*) OVER () AS population
    FROM frame
)
SELECT id, rank, population
FROM ranked
WHERE rank <= GREATEST(1, ceil(population * :rate)::int)
ORDER BY rank
"""

_INSERT_SQL = (
    "INSERT INTO qa_call_samples (id, tenant_id, call_id, week_start, population, target, "
    "  selection_rank, selection_seed, selected_at, created_at, updated_at) "
    "VALUES (:id, :tid, :call_id, :week_start, :population, :target, :rank, :seed, "
    "  :selected_at, now(), now()) "
    "ON CONFLICT (tenant_id, call_id) DO NOTHING"
)


def ist_week_start(moment: datetime) -> date:
    """The Monday (IST) of the week `moment` falls in — the Python twin of `_IST_WEEK_SQL`.

    Used to name the week the job is drawing; the DRAW itself buckets in SQL, so this
    function never decides which calls are in the frame. One expression deciding
    membership and another deciding the label is how a week's sample ends up filed under
    the wrong week.
    """
    local = moment.astimezone(_IST_TZ)
    return (local - timedelta(days=local.weekday())).date()


def seed_for(tenant_id: UUID, week_start: date) -> str:
    """The published seed. Printed on the queue so the draw can be recomputed."""
    return f"{tenant_id}:{week_start.isoformat()}"


@dataclass(frozen=True, slots=True)
class WeekDraw:
    """What one tenant-week's draw did — counts only, never a call id (hard rule 6)."""

    week_start: date
    population: int
    target: int
    inserted: int


async def draw_week_sample(session: AsyncSession, *, tenant_id: UUID, week_start: date) -> WeekDraw:
    """Draw (or re-affirm) this tenant's 5% for one IST week. IDEMPOTENT.

    `session` must already be inside the tenant's RLS context — the caller supplies it,
    exactly as `retention.sweep_tenant` does, so this function holds no cross-tenant
    view of `calls` at any point.

    Re-running is a no-op rather than a second draw: the order is a pure function of
    (seed, call ids), and the unique constraint absorbs the rows already filed. The one
    thing that CAN change a re-run's outcome is the frame itself — a call that finished
    late and only now falls in the week. That is the correct behaviour and it is
    visible: such a row lands with the population of the LATER run, so a reader can see
    the frame moved instead of finding a silently different sample.
    """
    seed = seed_for(tenant_id, week_start)
    rows = (
        await session.execute(
            text(_DRAW_SQL),
            {"seed": seed, "week_start": week_start, "rate": QA_SAMPLE_RATE},
        )
    ).all()
    if not rows:
        return WeekDraw(week_start=week_start, population=0, target=0, inserted=0)

    population = int(rows[0][2])
    target = len(rows)
    selected_at = datetime.now(UTC)
    inserted = 0
    for call_id, rank, _population in rows:
        result = await session.execute(
            text(_INSERT_SQL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "call_id": call_id,
                "week_start": week_start,
                "population": population,
                "target": target,
                "rank": int(rank),
                "seed": seed,
                "selected_at": selected_at,
            },
        )
        inserted += rowcount_of(result)
    return WeekDraw(week_start=week_start, population=population, target=target, inserted=inserted)


@dataclass(frozen=True, slots=True)
class SampledCall:
    """One line of the reviewer's queue. Ids, timings and tags — no transcript, no phone."""

    id: UUID
    call_id: UUID
    agent_name: str
    week_start: date
    population: int
    target: int
    selection_rank: int
    selection_seed: str
    selected_at: datetime
    started_at: datetime | None
    duration_s: int | None
    direction: str
    outcome_tag: str | None
    sentiment: str | None
    disclosure_played: bool | None
    #: The DB CHECK (`quality.models.QaCallSample.verdict_enum`) allows exactly these
    #: three strings or NULL, and `record_review` refuses anything else before the write,
    #: so the narrow type states an invariant the schema enforces rather than one this
    #: function checks. `str | None` here is what made `QaSampleOut(verdict=...)` — a
    #: Literal field — accept a widened CHECK without a word from either checker.
    verdict: Verdict | None
    reviewed_at: datetime | None


_QUEUE_SQL = """
SELECT s.id, s.call_id, a.name, s.week_start, s.population, s.target, s.selection_rank,
       s.selection_seed, s.selected_at, c.started_at, c.duration_s, c.direction,
       c.outcome_tag, c.sentiment, c.disclosure_played, s.verdict, s.reviewed_at
FROM qa_call_samples s
JOIN calls c ON c.id = s.call_id
JOIN agents a ON a.id = c.agent_id
{where}
ORDER BY s.week_start DESC, s.selection_rank
LIMIT :limit
"""


async def list_samples(
    session: AsyncSession, *, pending_only: bool = True, limit: int = 200
) -> list[SampledCall]:
    """This tenant's sampled calls, newest week first, in the DRAW's own order.

    Draw order, not "worst first": a reviewer who works the queue in an order the queue
    chose for them is reviewing our opinion of the calls rather than a sample. The rank
    is on screen for the same reason.
    """
    where = "WHERE s.verdict IS NULL" if pending_only else ""
    rows = (
        await session.execute(
            text(_QUEUE_SQL.format(where=where)), {"limit": max(1, min(limit, 500))}
        )
    ).all()
    return [_row(r) for r in rows]


def _row(r: Any) -> SampledCall:
    return SampledCall(
        id=UUID(str(r[0])),
        call_id=UUID(str(r[1])),
        agent_name=str(r[2]),
        week_start=r[3],
        population=int(r[4]),
        target=int(r[5]),
        selection_rank=int(r[6]),
        selection_seed=str(r[7]),
        selected_at=r[8],
        started_at=r[9],
        duration_s=r[10],
        direction=str(r[11]),
        outcome_tag=r[12],
        sentiment=r[13],
        disclosure_played=r[14],
        verdict=r[15],
        reviewed_at=r[16],
    )


async def find_sample(session: AsyncSession, sample_id: UUID) -> SampledCall | None:
    """One row of the queue, or None. RLS decides visibility — a sample belonging to
    another tenant is indistinguishable from one that does not exist, deliberately."""
    row = (
        await session.execute(
            text(_QUEUE_SQL.format(where="WHERE s.id = :sid")),
            {"limit": 1, "sid": sample_id},
        )
    ).first()
    return None if row is None else _row(row)


_REVIEW_SQL = (
    "UPDATE qa_call_samples SET verdict = :verdict, reviewed_at = now(), "
    "  reviewed_by_admin_id = :admin_id, updated_at = now() "
    "WHERE id = :sid AND verdict IS NULL"
)


async def record_review(
    session: AsyncSession, *, sample_id: UUID, verdict: str, admin_id: UUID
) -> SampledCall:
    """Record one reviewer's conclusion. First writer wins; a second is refused.

    The `AND verdict IS NULL` is CAS, not decoration (BACKEND-PATTERNS §5): two reviewers
    opening the same row is the ordinary way this queue is worked, and a read-then-write
    would let the second one overwrite the first's finding with no trace that a
    disagreement existed. The loser is told the row was already reviewed and can see what
    the winner concluded.

    A verdict is never edited afterwards by this path. The audit_log row the route writes
    is the history (hard rule 4's spirit); a correction is a decision somebody makes
    deliberately, not a second PATCH that erases the first.
    """
    if verdict not in QA_VERDICTS:
        raise ProblemError.business_rule(
            "qa_verdict_unknown",
            f"{verdict!r} is not a review verdict.",
            remediation=f"Use one of: {', '.join(QA_VERDICTS)}.",
        )
    result = await session.execute(
        text(_REVIEW_SQL), {"verdict": verdict, "admin_id": admin_id, "sid": sample_id}
    )
    if rowcount_of(result) == 0:
        existing = await find_sample(session, sample_id)
        if existing is None:
            raise ProblemError.not_found("QA sample")
        raise ProblemError.conflict(
            "qa_sample_already_reviewed",
            f"This call was already reviewed as {existing.verdict!r}.",
            remediation="Reload the queue — someone else reviewed it first.",
        )
    reviewed = await find_sample(session, sample_id)
    if reviewed is None:
        # Not reachable through this function — the UPDATE above matched this row in this
        # same transaction, so the re-read sees it. Kept as a REFUSAL rather than a
        # coverage exclusion because the two differ in what they leave behind: an
        # exclusion is a branch nobody can see fail, while this one is driven by
        # `test_a_verdict_survives_the_row_vanishing_under_the_re_read` and answers the
        # same 404 the caller above it does.
        raise ProblemError.not_found("QA sample")
    return reviewed


__all__ = [
    "QA_SAMPLE_RATE",
    "QA_VERDICTS",
    "SampledCall",
    "WeekDraw",
    "draw_week_sample",
    "find_sample",
    "ist_week_start",
    "list_samples",
    "record_review",
    "seed_for",
]
