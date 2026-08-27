"""What the engine's own pipeline cost, aggregated — the read side of OPERATIONS §2 gate 4.

    GET /v1/ops/engine-latency

**FOUR LEGS, NOT ONE, AND THAT IS THIS MODULE'S SECOND VERSION.** It reported the LLM
time-to-first-token alone, against the one budget this repository had ever written down —
so a turn that spent 900ms in the transcriber and 120ms in the model was reported as
comfortably within target, and the operator screen printed 350ms as though it were the
whole constraint. TRD §4 declares four sub-budgets adding to 1050ms inside a 1.1s
voice-to-voice p50; `calevate_shared.engine.LATENCY_BUDGET` is now the single declaration
of all of them, the composed turn budget is DERIVED from its parts, and every leg here is
judged against its own. A target is never computed from the observations it judges — TRD
§4a records that every one of these figures is unmeasured, and the slots where a measured
number may one day replace them.

**THE QUESTION THIS ANSWERS, AND WHY IT SURVIVED THE ANSWER.** D-410 pinned the language
model to an Azure deployment in South India while the engine's orchestrator is US-hosted
(`bolna-findings/mirror/pages/concepts/security.md:29`), which made every conversational
turn's LLM call a US->India->US round trip on the caller's audio path, inside a 350ms TTFT
budget (TRD §4). A us-east↔Mumbai round trip is conventionally quoted at 180-230ms — most
of that budget spent on geography before the model thinks — but that is an estimate off the
internet, and TRD §4a records that every latency figure in this repo is a TARGET with zero
measurements behind it.

**D-449 REMOVED THE ROUND TRIP BY DECIDING, NOT BY MEASURING**, moving the deployment to
`eastus2` beside the orchestrator and withdrawing the India residency claim to do it. That
makes this endpoint MORE useful rather than redundant: it is the only thing that can say
what the withdrawal actually bought, and a trade justified by an internet estimate is one
this repository can be talked into making twice. Place two pilot calls, one on each
deployment, and read the two rows.

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

from calevate_shared.engine import LATENCY_BUDGET, LatencyBudget
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

# LIVE tenants only, by `deleted_at IS NULL` — the same predicate `_load_admin_principal`
# resolves the directory with and `admin/health.client_health` walks by. This read
# `status <> 'deleted'`, which excluded NOTHING: `'deleted'` is not one of `ORG_STATUSES`
# and the `status_enum` CHECK refuses it, so the clause was always true and a soft-deleted
# (being-erased) tenant's turns landed in the distribution. Soft-delete is `deleted_at`, not
# a status — `ck_organizations_deleted_implies_churned` binds the two — so a CHURNED account
# that has not yet been erased stays in: its recent calls are real engine measurements.
_DIRECTORY = "SELECT id FROM organizations WHERE deleted_at IS NULL"

# ONE ROW PER TIMED TURN, expanded from the stored array under the tenant's own GUC. ALL
# THREE LEGS are pulled, and that is the change: this read `llm_ttft_ms` alone, so a turn
# that blew the whole voice-to-voice budget inside the transcriber or the synthesizer
# produced a report that said nothing at all. TRD §4 budgets four legs; a report that
# judged one of them was not measuring the constraint it was named after.
#
# A NON-NUMERIC VALUE IS ABSENT, NOT AN ERROR. The `CASE` is not decoration: `->>` on a
# JSON string returns that string and `::float8` on it raises, so one malformed turn in one
# tenant's array would fail the whole fleet walk. The column's CHECK constraint
# (`b7d3e91c4a05`) makes that unlikely rather than impossible, and a latency report is not
# worth an outage. A turn reaches this result if ANY leg reported a number; the legs it did
# not report contribute to no distribution, per `TurnLatency`'s absent-is-absent rule.
_SAMPLES_SQL = """
SELECT l.engine AS engine, l.region AS region, l.call_id AS call_id,
       CASE WHEN jsonb_typeof(element -> 'stt_ms') = 'number'
            THEN (element ->> 'stt_ms')::float8 END AS stt,
       CASE WHEN jsonb_typeof(element -> 'llm_ttft_ms') = 'number'
            THEN (element ->> 'llm_ttft_ms')::float8 END AS llm,
       CASE WHEN jsonb_typeof(element -> 'tts_ttfa_ms') = 'number'
            THEN (element ->> 'tts_ttfa_ms')::float8 END AS tts
FROM call_engine_latency AS l
CROSS JOIN LATERAL jsonb_array_elements(l.turns) AS element
WHERE l.created_at >= now() - make_interval(days => :days)
  AND (jsonb_typeof(element -> 'stt_ms') = 'number'
       OR jsonb_typeof(element -> 'llm_ttft_ms') = 'number'
       OR jsonb_typeof(element -> 'tts_ttfa_ms') = 'number')
LIMIT :cap
"""


#: Which leg of the turn a summary is about. `turn` is the COMPOSED one — STT + LLM TTFT +
#: TTS TTFA for the same turn — and it is a member of this union rather than a field beside
#: it so that every leg is summarised by one function under one set of sample-size rules.
#:
#: `retrieval` IS DELIBERATELY ABSENT. TRD §4 budgets it at 100ms (§6) and `LatencyBudget`
#: carries that target, but the engine's `latency_data` has no retrieval block and
#: `call_engine_latency` therefore holds no sample: the in-call RAG tool endpoint is OURS
#: and is not instrumented here. A member with no distribution behind it would be a column
#: of em dashes inviting the reader to conclude retrieval is fast.
LatencyLeg = Literal["stt", "llm_ttft", "tts_ttfa", "turn"]

#: The legs in the order a turn spends them, composed leg last. Rendering order is a
#: property of the pipeline, not of whichever dict the walk happened to build.
_LEG_ORDER: tuple[LatencyLeg, ...] = ("stt", "llm_ttft", "tts_ttfa", "turn")


class LegSummary(BaseModel):
    """One leg's distribution for one (engine, region) group, and its own verdict.

    **EVERY LEG CARRIES ITS OWN BUDGET, ITS OWN SAMPLE SIZE AND ITS OWN BASIS**, because it
    has all three. A turn whose payload carried an LLM timing and no transcriber block is a
    sample for one leg and for neither the other nor the composed sum, so a single `turns`
    count on the group would be wrong for at least one column of any real report.
    """

    leg: LatencyLeg
    #: The target from TRD §4, restated per leg so a row can be read on its own. It is a
    #: COPY of the corresponding `LatencyBudget` field and never an independent number —
    #: `_summarize_leg` is handed the budget it judges against, so the two cannot diverge.
    budget_ms: float
    #: Turns that reported this leg. For `turn`, turns that reported ALL THREE — a partial
    #: sum is a different quantity wearing the same name (`TurnLatency.component_sum_ms`).
    turns: int
    basis: SummaryBasis
    p50_ms: float | None = None
    p95_ms: float | None = None
    #: The MAXIMUM is reported at any sample size: an observation, not an estimate.
    max_ms: float | None = None
    #: Turns that spent more than OUR budget on this leg. A COUNT, never a page: one turn
    #: over budget is a cold start (the vendor's own worked example opens at 1633.04ms —
    #: `mirror/pages/concepts/call-latencies.md:99`), and the alarm that DOES page keys on
    #: a whole call's median against the vendor's own bottleneck threshold instead
    #: (`engine_llm_ttft_degraded`).
    turns_over_budget: int
    #: THE BREACH, NAMED. True when the MEDIAN turn misses the budget — the typical turn,
    #: not the worst one. `None` when the sample cannot support a median, because "we do
    #: not know" and "we are within budget" must never render the same.
    budget_breached: bool | None = None
    #: Whether the UNIT of the underlying observation has been confirmed. False on `stt`
    #: and therefore on `turn`: the vendor's field table calls `audio_to_text_latency`
    #: milliseconds (`bolna-findings/mirror/pages/concepts/call-latencies.md:82`) while
    #: their own example carries `20.12` (:62), which is not a plausible millisecond
    #: transcription latency. A verdict computed from a number in an unconfirmed unit is
    #: not a verdict, and the screen that prints it has to say so — so the doubt travels
    #: as a FIELD rather than as a comment in a module no operator reads. It is settled by
    #: OPERATIONS §2 gate 4, not by this report.
    unit_verified: bool


class LatencyGroup(BaseModel):
    """One (engine, region) pair, every leg of it."""

    engine: str
    #: `None` means the engine did not say where it ran — itself a finding: an
    #: unattributable measurement cannot answer the geography question at all.
    region: str | None
    calls: int
    #: Turns that reported at least one leg. Never the denominator for a leg's own count —
    #: that is `LegSummary.turns`, which differs per leg.
    turns: int
    legs: list[LegSummary]

    @property
    def llm_ttft(self) -> LegSummary:
        """The language leg, which is the one whose geography D-410/D-449 chose."""
        return next(leg for leg in self.legs if leg.leg == "llm_ttft")


class EngineLatencyReport(BaseModel):
    """Every group in the window, and the WHOLE budget each is judged against.

    **THE BUDGET IS AN OBJECT AND NOT A FIELD**, and that is this model's second version.
    It carried `llm_ttft_budget_ms` alone, so the console it feeds printed "target for the
    first reply: 350 ms" as though it were the budget — one quarter of a 1.1s voice-to-voice
    p50, presented as the whole constraint. Publishing `LatencyBudget` puts every target on
    the wire, including the two nothing here can measure and the retrieval leg nothing here
    samples, so a reader can see what the four numbers add up to instead of inferring it.
    """

    window_days: int
    #: TRD §4, whole. Restated in the payload rather than left to the reader's memory: a
    #: distribution with no threshold beside it is the shape in which a target quietly
    #: becomes whatever the fleet currently does. The composed totals on it are DERIVED
    #: (`LatencyBudget.turn_ms`), so no consumer — least of all a browser — ever adds the
    #: legs up itself.
    budget: LatencyBudget = Field(default=LATENCY_BUDGET)
    #: False when some tenant hit `SAMPLE_CAP_PER_TENANT`, i.e. the distribution describes
    #: a subset. Reported rather than hidden, for `ExecutionListing.complete`'s reason.
    complete: bool = True
    groups: list[LatencyGroup]

    @property
    def regions_measured(self) -> int:
        """How many distinct regions reported an LLM median. Gate 4 needs TWO."""
        return len({group.region for group in self.groups if group.llm_ttft.p50_ms is not None})


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
    """Accumulator for one (engine, region) group during the walk.

    One sample list PER LEG, because a turn is a sample for the legs it reported and for no
    others — and the composed leg only for a turn that reported all three.
    """

    __slots__ = ("calls", "samples", "turns")

    def __init__(self) -> None:
        self.samples: dict[LatencyLeg, list[float]] = {leg: [] for leg in _LEG_ORDER}
        self.calls: set[UUID] = set()
        self.turns = 0

    def add(self, *, stt: float | None, llm: float | None, tts: float | None) -> None:
        """One turn. Absent is absent — never 0, which would read as instant."""
        self.turns += 1
        pairs: tuple[tuple[LatencyLeg, float | None], ...] = (
            ("stt", stt),
            ("llm_ttft", llm),
            ("tts_ttfa", tts),
        )
        for leg, value in pairs:
            if value is not None:
                self.samples[leg].append(value)
        if stt is not None and llm is not None and tts is not None:
            # `TurnLatency.component_sum_ms`'s rule, applied to the aggregate: a turn
            # missing a leg contributes to no comparison at all, because a partial sum is a
            # smaller number that is not a smaller latency.
            self.samples["turn"].append(stt + llm + tts)


#: Which legs carry an observation whose UNIT we have confirmed against the vendor's docs.
#: `stt` does not (`call-latencies.md:82` vs :62), and the composed `turn` inherits the
#: doubt because it contains it. Derived per leg rather than written per summary so the
#: composed leg cannot be marked verified while one of its addends is not.
_UNIT_VERIFIED: dict[LatencyLeg, bool] = {
    "stt": False,
    "llm_ttft": True,
    "tts_ttfa": True,
    "turn": False,
}


def _summarize_leg(leg: LatencyLeg, samples: list[float], budget_ms: float) -> LegSummary:
    """Apply the sample-size rules to ONE leg. Arithmetic is arithmetic; REFUSING is the
    policy, and it is the same policy for every leg."""
    ordered = sorted(samples)
    enough_for_median = len(ordered) >= P50_MIN_TURNS
    median = _percentile(ordered, 0.5) if enough_for_median else None
    return LegSummary(
        leg=leg,
        budget_ms=budget_ms,
        turns=len(ordered),
        basis="measured" if enough_for_median else "insufficient_samples",
        p50_ms=median,
        p95_ms=_percentile(ordered, 0.95) if len(ordered) >= P95_MIN_TURNS else None,
        max_ms=ordered[-1] if ordered else None,
        turns_over_budget=sum(1 for value in ordered if value > budget_ms),
        budget_breached=(median > budget_ms) if median is not None else None,
        unit_verified=_UNIT_VERIFIED[leg],
    )


def _summarize(engine: str, region: str | None, bucket: _Bucket) -> LatencyGroup:
    """One group: every leg, each against its OWN target, plus the composed turn.

    The budgets are read off `LATENCY_BUDGET` at the point of comparison — no leg budget is
    named twice in this module, and the composed one is `turn_ms`, which is the sum of the
    other three by construction rather than by a literal somebody has to keep in step.
    """
    budgets: dict[LatencyLeg, float] = {
        "stt": LATENCY_BUDGET.stt_ms,
        "llm_ttft": LATENCY_BUDGET.llm_ttft_ms,
        "tts_ttfa": LATENCY_BUDGET.tts_ttfa_ms,
        "turn": LATENCY_BUDGET.turn_ms,
    }
    return LatencyGroup(
        engine=engine,
        region=region,
        calls=len(bucket.calls),
        turns=bucket.turns,
        legs=[_summarize_leg(leg, bucket.samples[leg], budgets[leg]) for leg in _LEG_ORDER],
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
            bucket.add(
                stt=None if row.stt is None else float(row.stt),
                llm=None if row.llm is None else float(row.llm),
                tts=None if row.tts is None else float(row.tts),
            )
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
    "LatencyLeg",
    "LegSummary",
    "engine_latency_report",
]
