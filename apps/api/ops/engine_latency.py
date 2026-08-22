"""What the engine's own pipeline cost, aggregated — the read side of OPERATIONS §2 gate 4.

    GET /v1/ops/engine-latency

**THE QUESTION THIS ANSWERS.** D-410 pinned the language model to an Azure deployment in
South India. The engine's orchestrator is US-hosted
(`bolna-findings/mirror/pages/concepts/security.md:29`). So every conversational turn's LLM
call is a US->India->US round trip on the caller's audio path, inside a 350ms TTFT budget
(TRD §4) — and TRD §4a records that every latency figure in this repo is a TARGET with zero
measurements behind it. A us-east↔Mumbai round trip is conventionally quoted at 180-230ms,
which would be most of that budget spent on geography before the model thinks. That figure
is an estimate off the internet, and this module exists so nobody has to keep quoting it:
place two pilot calls, one on each deployment, and read the two rows.

**GROUPING BY `region` IS THE WHOLE DESIGN.** The engine stamps each execution with where
it ran (`in`, `us` — `mirror/pages/concepts/call-latencies.md:38`). Grouped by that code,
the difference between two rows IS the cost of the geography, measured. Ungrouped it is one
number nobody can attribute to anything.

**THE WALK, AND WHY IT IS NOT ONE QUERY.** `call_engine_latency` is tenant-scoped and
FORCE-RLS'd, and `app.admin` widens `USING` on `organizations` and NOTHING else
(b57e2f9c4a13). Widening it here was considered and rejected: a fleet-wide latency report
is not worth a second table outside RLS, and the moment one exists the next reader assumes
the widening is available for the table they want too. So this follows the pattern
`admin/health.client_health` and `scripts/reconcile_credit_ledger` already set — enumerate
tenants from the directory, then ENTER each account with its own GUC, so no cross-tenant
view of any tenant table exists at any instant. The walk has a budget and says so when it
misses it, exactly as `client_health` does.

**STATISTICS, HONESTLY.** A percentile is a claim about a distribution and a handful of
turns cannot support one. `scripts/pilot/latency.py` set this repo's position — a number
not entitled to be read as a measurement says so in a FIELD, not in a comment a dashboard
author will not read — and this module keeps it: every group carries a `basis`, a p95 is
withheld below `P95_MIN_TURNS`, and a withheld statistic is `None` rather than a smaller
sample's answer wearing a p95's name.

**WHAT IT IS NOT.** Not voice-to-voice latency. That interval runs from the caller's last
syllable to the first sound of the reply, and both ends of it are on the PSTN leg our stack
is not in (D-25/D-33) — which is why `calls.latency` was dropped (`f1a7c39d5be2`) and stays
dropped. These are the engine's numbers about the engine's own pipeline: the only per-turn
evidence that exists, and the LLM leg is the one whose geography we chose. The stopwatch
that says whether they resemble what a caller HEARS is gate 4's, and a human types it in
(`scripts/pilot/latency.py`).

**HARD RULE 6.** Nothing read here is text: the table holds turn indices, milliseconds and
a region code, and its CHECK constraint refuses anything else (migration `b7d3e91c4a05`).
"""

from __future__ import annotations

from time import perf_counter
from typing import Literal
from uuid import UUID

from calevate_shared.engine import LLM_TTFT_BUDGET_MS
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: How much history the report covers by default, and the widest it will look. A gate-4 run
#: is two calls placed minutes apart, so the default is short on purpose: a 90-day window
#: would bury the pilot under whatever the fleet did last quarter.
DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 90

#: Below this many timed turns a group reports NO p95. Twenty is the smallest sample in
#: which the 95th percentile is an order statistic between two observations rather than the
#: maximum wearing a percentile's name — at n=10, "p95" IS the largest sample, and printing
#: it invites an operator to act on a single slow turn.
P95_MIN_TURNS = 20

#: Below this many timed turns a group reports no percentile at all. Five is not a
#: statistical claim; it is the point below which the median moves by a whole turn.
P50_MIN_TURNS = 5

#: Turns read per tenant per run. A bound rather than an unbounded fetch, because the rows
#: cross into this process to be sorted here (percentiles do not merge across shards). A
#: run that hits it reports `complete=False` rather than quietly describing a subset —
#: `ExecutionListing.complete`'s rule, for the same reason.
SAMPLE_CAP_PER_TENANT = 20_000

#: The walk is per-tenant, so it grows with the client list. Same budget and same remedy as
#: `admin/health.WALK_BUDGET_S`: when it is missed, the report is still correct and the
#: log line says what to do about it.
WALK_BUDGET_S = 5.0

#: Where a number came from, in a field rather than in a footnote. Same vocabulary as
#: `scripts/pilot/latency.SummaryBasis`, and for the same reason.
SummaryBasis = Literal["measured", "insufficient_samples"]

_DIRECTORY = "SELECT id FROM organizations WHERE status <> 'deleted'"

# ONE ROW PER TIMED TURN, expanded from the stored array under the tenant's own GUC. Only
# `llm_ttft_ms` is pulled: it is the leg whose geography D-410 chose, and it is the one
# whose unit their documentation is unambiguous about (`stt_ms` comes from
# `audio_to_text_latency: 20.12`, which does not read as milliseconds — see the adapter).
_SAMPLES_SQL = """
SELECT l.engine AS engine, l.region AS region, l.call_id AS call_id,
       (element ->> 'llm_ttft_ms')::float8 AS ttft
FROM call_engine_latency AS l
CROSS JOIN LATERAL jsonb_array_elements(l.turns) AS element
WHERE l.created_at >= now() - make_interval(days => :days)
  AND jsonb_typeof(element -> 'llm_ttft_ms') = 'number'
LIMIT :cap
"""


class LatencyGroup(BaseModel):
    """One (engine, region) pair's LLM time-to-first-token distribution."""

    engine: str
    #: `None` means the engine did not say where it ran — itself a finding: an
    #: unattributable measurement cannot answer the geography question at all.
    region: str | None
    calls: int
    turns: int
    basis: SummaryBasis
    llm_ttft_p50_ms: float | None = None
    llm_ttft_p95_ms: float | None = None
    llm_ttft_max_ms: float | None = None
    #: Turns that spent more than OUR budget in the model. A COUNT, never a page: one turn
    #: over budget is a cold start (the vendor's own worked example opens at 1633.04ms —
    #: `mirror/pages/concepts/call-latencies.md:99`), and the alarm that DOES page keys on
    #: a whole call's median against the vendor's own bottleneck threshold instead
    #: (`engine_llm_ttft_degraded`).
    turns_over_budget: int
    #: THE BREACH, NAMED. True when the MEDIAN turn misses the budget — the typical turn,
    #: not the worst one. `None` when the sample cannot support a median, because "we do
    #: not know" and "we are within budget" must never render the same.
    budget_breached: bool | None = None


class EngineLatencyReport(BaseModel):
    """Every group in the window, plus the target each is judged against."""

    window_days: int
    #: TRD §4. Restated in the payload rather than left to the reader's memory: a
    #: distribution with no threshold beside it is the shape in which a target quietly
    #: becomes whatever the fleet currently does.
    llm_ttft_budget_ms: float = Field(default=LLM_TTFT_BUDGET_MS)
    #: False when some tenant hit `SAMPLE_CAP_PER_TENANT`, i.e. the distribution describes
    #: a subset. Reported rather than hidden, for `ExecutionListing.complete`'s reason.
    complete: bool = True
    groups: list[LatencyGroup]

    @property
    def regions_measured(self) -> int:
        """How many distinct regions reported a median. Gate 4 needs TWO."""
        return len({group.region for group in self.groups if group.llm_ttft_p50_ms is not None})


def _percentile(ordered: list[float], fraction: float) -> float:
    """Linear interpolation between order statistics — Postgres's `percentile_cont`.

    Written out rather than taken from `statistics.quantiles`, which cuts a fixed number of
    equal-probability intervals and cannot be asked for an arbitrary fraction without
    rounding it to the nearest cut point. The arithmetic is four lines and matching the
    database's definition matters more than saving them: a report and an ad-hoc SQL query
    over the same table must not disagree about what p95 means.
    """
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class _Bucket:
    """Accumulator for one (engine, region) group during the walk."""

    __slots__ = ("calls", "samples")

    def __init__(self) -> None:
        self.samples: list[float] = []
        self.calls: set[UUID] = set()


def _summarize(engine: str, region: str | None, bucket: _Bucket) -> LatencyGroup:
    """Apply the sample-size rules. Arithmetic is arithmetic; REFUSING is the policy."""
    ordered = sorted(bucket.samples)
    enough_for_median = len(ordered) >= P50_MIN_TURNS
    median = _percentile(ordered, 0.5) if enough_for_median else None
    return LatencyGroup(
        engine=engine,
        region=region,
        calls=len(bucket.calls),
        turns=len(ordered),
        basis="measured" if enough_for_median else "insufficient_samples",
        llm_ttft_p50_ms=median,
        llm_ttft_p95_ms=_percentile(ordered, 0.95) if len(ordered) >= P95_MIN_TURNS else None,
        # The MAXIMUM is reported at any sample size, and it is the one number that is
        # honest at n=1: an observation, not an estimate of a population.
        llm_ttft_max_ms=ordered[-1] if ordered else None,
        turns_over_budget=sum(1 for value in ordered if value > LLM_TTFT_BUDGET_MS),
        budget_breached=(median > LLM_TTFT_BUDGET_MS) if median is not None else None,
    )


async def engine_latency_report(
    directory: AsyncSession, *, days: int = DEFAULT_WINDOW_DAYS
) -> EngineLatencyReport:
    """The LLM TTFT distribution per (engine, region) over the last `days` days.

    `directory` must be an `admin_session()` — the only session that can enumerate tenants
    (b57e2f9c4a13). Each account is then entered with its own GUC, so every measurement is
    read under ordinary RLS and this function holds no cross-tenant view of a tenant table
    at any instant. Same shape, same reason, as `admin/health.client_health`.
    """
    window = max(1, min(days, MAX_WINDOW_DAYS))
    started = perf_counter()
    tenants = [UUID(str(row[0])) for row in (await directory.execute(text(_DIRECTORY))).all()]

    buckets: dict[tuple[str, str | None], _Bucket] = {}
    complete = True
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            rows = (
                await scoped.execute(
                    text(_SAMPLES_SQL), {"days": window, "cap": SAMPLE_CAP_PER_TENANT}
                )
            ).all()
        if len(rows) == SAMPLE_CAP_PER_TENANT:
            complete = False
        for row in rows:
            key = (str(row.engine), str(row.region) if row.region is not None else None)
            bucket = buckets.setdefault(key, _Bucket())
            bucket.samples.append(float(row.ttft))
            bucket.calls.add(UUID(str(row.call_id)))

    elapsed = perf_counter() - started
    if elapsed > WALK_BUDGET_S:
        # Ids and counts only, never a client name — the same log discipline
        # `client_health` keeps, and the remedy is on the line rather than in this module.
        log.warning(
            "engine_latency_walk_over_budget",
            extra={
                "accounts": len(tenants),
                "elapsed_s": round(elapsed, 2),
                "budget_s": WALK_BUDGET_S,
                "remedy": "the client list has outgrown the per-tenant walk — "
                "materialize per-tenant latency summaries (ops/engine_latency.py)",
            },
        )

    return EngineLatencyReport(
        window_days=window,
        complete=complete,
        groups=[
            _summarize(engine, region, bucket)
            for (engine, region), bucket in sorted(
                buckets.items(), key=lambda item: (item[0][0], item[0][1] or "~")
            )
        ],
    )


__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "MAX_WINDOW_DAYS",
    "P50_MIN_TURNS",
    "P95_MIN_TURNS",
    "SAMPLE_CAP_PER_TENANT",
    "WALK_BUDGET_S",
    "EngineLatencyReport",
    "LatencyGroup",
    "engine_latency_report",
]
