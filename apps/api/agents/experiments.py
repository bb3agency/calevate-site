"""A/B greeting/script testing with conversion attribution (ROADMAP M3).

WHAT THIS ADDS TO A REPO THAT ALREADY HAS PROMPT VERSIONS
----------------------------------------------------------
`prompt_versions` gives an agent a history and a rollback (FLOWS §7), and two-speed
publishing (`agents/publishing.py`) gives it a draft and a live pointer. What neither
gives is the ability to run TWO scripts against comparable traffic and find out which one
books more appointments. That is this module.

It is deliberately a THIN layer over what exists:

* **A variant is an existing `prompt_versions` row**, named by id. No new prompt-writing
  path, no copied body, no second place a script can live. An operator writes the
  challenger through the screen they already use (which STAGES it, per §2b), then points
  an arm at it.
* **Promotion is `insert_prompt_version` + `publishing.apply_to_live`** — the mechanism
  that already changes what an agent says. There is no second way to change a live
  script, which is the point: an experiment that could publish on its own would be a
  parallel publishing path with none of §2b's guarantees.
* **Assignment rides the one outbound entry point** (`service.dispatch_call`), so the
  campaign dispatcher, the leads button and the callback path are all covered without
  any of them importing this module.

WHAT IT CANNOT DO, SAID PLAINLY RATHER THAN HIDDEN
---------------------------------------------------
**Inbound calls are not attributed.** An inbound call row is created by
`apps/workers/pipeline.py` from the engine's webhook, and nothing in that path consults
an experiment. Two consequences, both enforced here rather than left to a reader:

* `start` REFUSES an agent whose `direction` is `inbound` — an experiment that could
  never attribute a single call is not a feature, it is a screen that says "not enough
  data" forever.
* For a `both` agent the results carry `attributed_directions = ("outbound",)` and the
  UI prints it. The inbound calls are not in the denominator, are not silently in the
  numerator, and the reader is told which half they are looking at.

Closing that gap needs an assignment lookup at inbound call creation, in a file this
wave does not own. It is a seam, and it is named here rather than half-wired.

COMPLIANCE (hard rule 5) — WHAT AN EXPERIMENT MUST NOT WEAKEN
--------------------------------------------------------------
Every arm carries its own `disclosure_line`, NOT NULL with a non-empty CHECK, defaulted
from the agent's. `service.publish_variant` puts it on the `AgentConfig` the adapter
renders, exactly as `publish_agent` does — so there is no arm, and no way of writing an
arm, that reaches a phone line without a disclosure. Nothing here touches the dispatch
gate: `dispatch_call` is downstream of `check_dispatch` on every path, and this module
only changes which of two already-published scripts the engine speaks.

PII (hard rule 6): ids, labels, version numbers and counts. No prompt body, no
disclosure text and no phone number is logged by anything in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import prompts, publishing
from apps.api.agents.models import (
    CONVERSION_METRICS,
    SPLIT_MIN_BP,
    SPLIT_TOTAL_BP,
    VARIANT_LABELS,
)
from apps.api.agents.proportions import (
    MIN_CALLS_PER_VARIANT,
    newcombe_difference,
    wilson_interval,
)
from apps.api.agents.service import publish_variant
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session

log = get_logger(__name__)

Basis = Literal["measured", "insufficient_data"]
Verdict = Literal["not_enough_data", "inconclusive", "winner"]

# Printed on the results surface, verbatim, every time. It is the honest caveat on a
# fixed-sample 95% interval read repeatedly — see `proportions.py`'s closing note.
PEEKING_CAVEAT = (
    "The 95% confidence is per reading. Checking this screen daily and stopping the "
    "moment it clears zero makes mistakes more often than 1 in 20 — decide the arm on "
    "the interval, not on the first day it looks good."
)

ONLY_OUTBOUND_NOTE = (
    "Only outbound calls are assigned to an arm. Inbound calls to this agent are "
    "counted in neither variant, so this comparison describes the outbound motion only."
)


@dataclass(frozen=True, slots=True)
class VariantResult:
    """One arm's counts and its Wilson interval.

    `dialled` and `attributed` are both here because they answer different questions: a
    large gap between them means the arm's calls are not connecting, which is a
    telephony problem masquerading as a script problem.
    """

    variant_id: UUID
    label: str
    prompt_version: int
    weight_bp: int
    published: bool
    dialled: int
    attributed: int
    conversions: int
    # None until there is a single completed call — a rate over zero calls is not 0%.
    rate: float | None
    rate_low: float | None
    rate_high: float | None


@dataclass(frozen=True, slots=True)
class ExperimentResults:
    experiment_id: UUID
    agent_id: UUID
    name: str
    status: str
    conversion_metric: str
    conversion_metric_label: str
    started_at: datetime
    concluded_at: datetime | None
    promoted_label: str | None
    variants: list[VariantResult]
    minimum_calls_per_variant: int
    basis: Basis
    verdict: Verdict
    # The arm that is AHEAD on today's counts. An ordering, never a claim — populated on
    # every basis, including one that cannot support a comparison.
    leader_label: str | None
    # The arm we are willing to say is BETTER. Populated only on verdict == "winner".
    winner_label: str | None
    difference_point: float | None
    difference_low: float | None
    difference_high: float | None
    headline: str
    caveat: str
    attributed_directions: tuple[str, ...]
    coverage_note: str


@dataclass(frozen=True, slots=True)
class StartResult:
    experiment_id: UUID
    variant_ids: tuple[UUID, ...]
    engine_synced: bool


@dataclass(frozen=True, slots=True)
class ConcludeResult:
    experiment_id: UUID
    promoted_label: str | None
    new_version: int | None
    applied: bool
    engine_synced: bool


_AGENT_SQL = (
    "SELECT a.status, a.engine_agent_ref, a.direction, a.disclosure_line, l.id, l.version "
    "FROM agents a LEFT JOIN prompt_versions l ON l.id = COALESCE(a.live_prompt_id, "
    "a.system_prompt_id) WHERE a.id = :aid AND a.deleted_at IS NULL"
)


@dataclass(frozen=True, slots=True)
class _AgentFacts:
    status: str
    engine_agent_ref: str | None
    direction: str
    disclosure_line: str
    live_version_id: UUID | None
    live_version: int | None


async def _agent(session: AsyncSession, agent_id: UUID) -> _AgentFacts:
    row = (await session.execute(text(_AGENT_SQL), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _AgentFacts(
        status=str(row[0]),
        engine_agent_ref=row[1],
        direction=str(row[2]),
        disclosure_line=str(row[3]),
        live_version_id=UUID(str(row[4])) if row[4] is not None else None,
        live_version=int(row[5]) if row[5] is not None else None,
    )


async def _version_id(session: AsyncSession, agent_id: UUID, version: int) -> UUID:
    row = (
        await session.execute(
            text("SELECT id FROM prompt_versions WHERE agent_id = :aid AND version = :v"),
            {"aid": agent_id, "v": version},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Prompt version")
    return UUID(str(row[0]))


async def start(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str,
    control_version: int,
    challenger_version: int,
    split_bp: int,
    conversion_metric: str,
    control_disclosure: str | None = None,
    challenger_disclosure: str | None = None,
) -> StartResult:
    """Begin an experiment: two published arms, a split, and a metric.

    Every refusal below exists because the alternative is a control that looks like it
    is working:

    - **not live / not published** — an arm is an engine agent; there is nothing to
      publish it beside.
    - **inbound-only agent** — nothing would ever be assigned (module docstring).
    - **the same version twice** — an A/A test measures the noise floor, which is a
      genuinely useful thing to run, but not through a surface that will report "no
      difference" as if it were a finding about two scripts.
    - **an experiment already running** — caught by the partial unique index rather than
      by a read-then-write, so two operators pressing Start at once produce one
      experiment and one conflict (BACKEND-PATTERNS §5).

    The engine push happens INSIDE the transaction, after the rows, so a vendor failure
    rolls the whole experiment back rather than leaving arms our table claims are live.
    """
    if conversion_metric not in CONVERSION_METRICS:
        raise ProblemError.business_rule(
            "unknown_conversion_metric",
            f"'{conversion_metric}' is not a conversion metric this platform measures.",
            remediation=f"Use one of: {', '.join(sorted(CONVERSION_METRICS))}.",
        )
    if not SPLIT_MIN_BP <= split_bp <= SPLIT_TOTAL_BP - SPLIT_MIN_BP:
        raise ProblemError.business_rule(
            "split_out_of_range",
            "A traffic split must leave at least 5% of calls to each arm.",
            remediation=(
                f"Send a control share between {SPLIT_MIN_BP} and "
                f"{SPLIT_TOTAL_BP - SPLIT_MIN_BP} basis points."
            ),
        )
    if control_version == challenger_version:
        raise ProblemError.business_rule(
            "identical_variants",
            "Both arms name the same prompt version, so the test cannot measure anything.",
            remediation="Write a challenger version first, then start the experiment.",
        )

    async with tenant_session(tenant_id) as session:
        agent = await _agent(session, agent_id)
        if agent.status != "live" or not agent.engine_agent_ref:
            raise ProblemError.business_rule(
                "agent_not_published",
                "This agent is not on the voice platform, so an experiment has nothing to run.",
                remediation="Publish the agent first, then start the experiment.",
            )
        if agent.direction == "inbound":
            raise ProblemError.business_rule(
                "experiment_needs_outbound",
                (
                    "Script tests are assigned when a call is placed, and this agent only "
                    "receives calls."
                ),
                remediation=(
                    "Inbound attribution is not built yet. Run the test on an outbound or "
                    "two-way agent."
                ),
            )

        version_ids = {
            "A": await _version_id(session, agent_id, control_version),
            "B": await _version_id(session, agent_id, challenger_version),
        }
        disclosures = {
            "A": (control_disclosure or agent.disclosure_line).strip(),
            "B": (challenger_disclosure or agent.disclosure_line).strip(),
        }
        for label, disclosure in disclosures.items():
            if not disclosure:
                # Belt to the CHECK's braces: an empty override is a client typing a
                # space, and it deserves a message rather than an IntegrityError 500.
                raise ProblemError.business_rule(
                    "variant_disclosure_required",
                    f"Variant {label} has no disclosure line.",
                    remediation=(
                        "Every variant must state who is calling. Leave the field empty "
                        "to inherit the agent's disclosure."
                    ),
                )
        weights = {"A": split_bp, "B": SPLIT_TOTAL_BP - split_bp}

        experiment_id = uuid7()
        try:
            await session.execute(
                text(
                    "INSERT INTO prompt_experiments (id, tenant_id, agent_id, name, status, "
                    "conversion_metric, started_at, created_at, updated_at) VALUES (:id, :tid, "
                    ":aid, :name, 'running', :metric, now(), now(), now())"
                ),
                {
                    "id": experiment_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "name": name,
                    "metric": conversion_metric,
                },
            )
        except IntegrityError as exc:
            raise ProblemError.conflict(
                "experiment_already_running",
                "This agent already has a script test running.",
                remediation="Conclude the running test before starting another.",
            ) from exc

        variant_ids: list[UUID] = []
        for label in VARIANT_LABELS:
            variant_id = uuid7()
            variant_ids.append(variant_id)
            await session.execute(
                text(
                    "INSERT INTO prompt_experiment_variants (id, tenant_id, experiment_id, "
                    "label, prompt_version_id, disclosure_line, weight_bp, created_at, "
                    "updated_at) VALUES (:id, :tid, :eid, :label, :pv, :disc, :w, now(), now())"
                ),
                {
                    "id": variant_id,
                    "tid": tenant_id,
                    "eid": experiment_id,
                    "label": label,
                    "pv": version_ids[label],
                    "disc": disclosures[label],
                    "w": weights[label],
                },
            )
            body = (
                await session.execute(
                    text("SELECT body FROM prompt_versions WHERE id = :id"),
                    {"id": version_ids[label]},
                )
            ).scalar_one()
            await publish_variant(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                variant_id=variant_id,
                label=label,
                body=str(body),
                disclosure_line=disclosures[label],
                existing_ref=None,
            )

    log.info(
        "prompt_experiment_started",
        extra={
            "agent_id": str(agent_id),
            "experiment_id": str(experiment_id),
            "control_version": control_version,
            "challenger_version": challenger_version,
            "split_bp": split_bp,
            "metric": conversion_metric,
        },
    )
    return StartResult(
        experiment_id=experiment_id, variant_ids=tuple(variant_ids), engine_synced=True
    )


def _counts_sql(conversion_predicate: str) -> str:
    """The per-arm tally.

    DENOMINATOR = COMPLETED calls, not dialled ones. A script cannot influence whether a
    phone is answered; putting no-answers in the denominator would measure the contact
    list and call it a script difference. `dialled` is reported alongside so a lopsided
    connection rate is visible rather than buried.

    The predicate is interpolated, and it is safe BECAUSE it is never a caller's string:
    the only values that reach it are `CONVERSION_METRICS`' own SQL fragments, selected
    by a key that `start` validates against that same dict before it can be stored.
    """
    return (
        "SELECT v.id, v.label, pv.version, v.weight_bp, v.engine_agent_ref, "
        "count(a.call_id) AS dialled, "
        "count(a.call_id) FILTER (WHERE c.status = 'completed') AS attributed, "
        f"count(a.call_id) FILTER (WHERE c.status = 'completed' AND {conversion_predicate}) "
        "AS conversions "
        "FROM prompt_experiment_variants v "
        "JOIN prompt_versions pv ON pv.id = v.prompt_version_id "
        "LEFT JOIN call_variant_assignments a ON a.variant_id = v.id "
        "LEFT JOIN calls c ON c.id = a.call_id "
        "WHERE v.experiment_id = :eid GROUP BY v.id, v.label, pv.version, v.weight_bp, "
        "v.engine_agent_ref ORDER BY v.label"
    )


_LATEST_SQL = (
    "SELECT e.id, e.name, e.status, e.conversion_metric, e.started_at, e.concluded_at, "
    "pv.label FROM prompt_experiments e "
    "LEFT JOIN prompt_experiment_variants pv ON pv.id = e.promoted_variant_id "
    "WHERE e.agent_id = :aid ORDER BY (e.status = 'running') DESC, e.started_at DESC LIMIT 1"
)

METRIC_LABELS = {
    "call_outcome_resolved": "calls the agent resolved",
    "lead_won": "leads eventually won",
}


def _variant_result(row: tuple[Any, ...]) -> VariantResult:
    attributed = int(row[6])
    conversions = int(row[7])
    interval = wilson_interval(conversions, attributed) if attributed else None
    return VariantResult(
        variant_id=UUID(str(row[0])),
        label=str(row[1]),
        prompt_version=int(row[2]),
        weight_bp=int(row[3]),
        published=bool(row[4]),
        dialled=int(row[5]),
        attributed=attributed,
        conversions=conversions,
        rate=interval.point if interval else None,
        rate_low=interval.low if interval else None,
        rate_high=interval.high if interval else None,
    )


def judge(variants: list[VariantResult]) -> tuple[Basis, Verdict, str | None, str | None, str]:
    """(basis, verdict, leader, winner, headline) — the whole statistical position.

    Pure, and separated from the query for exactly that reason: this is the function
    whose wrongness would be repeated to a client, so it is the one that gets unit tests
    over hand-written counts rather than over a database.

    THE THREE ANSWERS, and why there are three rather than two:

    - `not_enough_data` — either arm is below `MIN_CALLS_PER_VARIANT` (40, from
      Fagerland/Lydersen/Laake 2011's coverage study of exactly this interval). We
      publish NO comparison, not a wide one. A leader is still named, because "B is
      ahead so far" is a true statement about the counts and operators will read it off
      the two rates anyway; what is withheld is any claim that it means something.
    - `inconclusive` — enough data, and the 95% Newcombe interval for the difference
      CONTAINS ZERO. The two scripts are not distinguishable on this evidence. This is
      the commonest correct answer and the surface must not be embarrassed by it.
    - `winner` — the interval excludes zero. Only here is one arm called better.
    """
    if len(variants) != 2:
        # The schema admits exactly two arms; a third would need a multiplicity
        # correction `proportions.py` does not implement, so refuse rather than compare.
        return (
            "insufficient_data",
            "not_enough_data",
            None,
            None,
            "This experiment does not have two arms to compare.",
        )

    a, b = variants[0], variants[1]
    rated = [v for v in (a, b) if v.rate is not None]
    leader = max(rated, key=lambda v: v.rate or 0.0).label if rated else None
    if a.rate is not None and b.rate is not None and a.rate == b.rate:
        leader = None

    smallest = min(a.attributed, b.attributed)
    if smallest < MIN_CALLS_PER_VARIANT:
        return (
            "insufficient_data",
            "not_enough_data",
            leader,
            None,
            (
                f"Not enough calls to compare yet — {smallest} completed on the smaller "
                f"arm, and {MIN_CALLS_PER_VARIANT} per arm is the minimum this comparison "
                "is valid at."
            ),
        )

    difference = newcombe_difference(a.conversions, a.attributed, b.conversions, b.attributed)
    if not difference.excludes_zero:
        return (
            "measured",
            "inconclusive",
            leader,
            None,
            (
                "No difference we can stand behind. The plausible range for the gap "
                f"({_pct(difference.low)} to {_pct(difference.high)}) still includes zero, "
                "so these two scripts are not distinguishable on this many calls."
            ),
        )

    winner = a.label if difference.point > 0 else b.label
    return (
        "measured",
        "winner",
        leader,
        winner,
        (
            f"Variant {winner} converts better. The gap is at least "
            f"{_pct(min(abs(difference.low), abs(difference.high)))} and at most "
            f"{_pct(max(abs(difference.low), abs(difference.high)))}, with 95% confidence."
        ),
    )


def _pct(value: float) -> str:
    return f"{value * 100:.1f} points"


async def results_for(*, tenant_id: UUID, agent_id: UUID) -> ExperimentResults | None:
    """The running experiment if there is one, else the most recent, else None.

    A pure READ, gated on `agents:read` by its route (D-22): it is the screen somebody
    opens to find out whether a test can be stopped, and a support person looking at the
    client's console must be able to see the same thing.
    """
    async with tenant_session(tenant_id) as session:
        agent = await _agent(session, agent_id)
        header = (await session.execute(text(_LATEST_SQL), {"aid": agent_id})).first()
        if header is None:
            return None
        experiment_id = UUID(str(header[0]))
        metric = str(header[3])
        rows = (
            await session.execute(
                text(_counts_sql(CONVERSION_METRICS[metric])), {"eid": experiment_id}
            )
        ).all()

    variants = [_variant_result(tuple(r)) for r in rows]
    basis, verdict, leader, winner, headline = judge(variants)
    difference = (
        newcombe_difference(
            variants[0].conversions,
            variants[0].attributed,
            variants[1].conversions,
            variants[1].attributed,
        )
        if basis == "measured"
        else None
    )
    return ExperimentResults(
        experiment_id=experiment_id,
        agent_id=agent_id,
        name=str(header[1]),
        status=str(header[2]),
        conversion_metric=metric,
        conversion_metric_label=METRIC_LABELS[metric],
        started_at=header[4],
        concluded_at=header[5],
        promoted_label=header[6],
        variants=variants,
        minimum_calls_per_variant=MIN_CALLS_PER_VARIANT,
        basis=basis,
        verdict=verdict,
        leader_label=leader,
        winner_label=winner,
        difference_point=difference.point if difference else None,
        difference_low=difference.low if difference else None,
        difference_high=difference.high if difference else None,
        headline=headline,
        caveat=PEEKING_CAVEAT,
        attributed_directions=("outbound",),
        coverage_note=ONLY_OUTBOUND_NOTE if agent.direction != "outbound" else "",
    )


async def conclude(
    *, tenant_id: UUID, agent_id: UUID, promote_label: str | None, created_by: UUID | None = None
) -> ConcludeResult:
    """Stop the experiment, and optionally make one arm the agent's script.

    ENDING IS PART OF THE FEATURE. Three things happen and they happen in this order:

    1. **CAS `running -> concluded`.** A conditional UPDATE, so a second operator's
       Conclude is a 409 rather than a second promotion (BACKEND-PATTERNS §5). Doing this
       FIRST also stops `dispatch_call` assigning any further calls to the arms, and
       stops `publish_agent` republishing them.
    2. **The arms' engine agents are taken out of the routing table.** They are not
       deleted — the portability contract has no `delete_agent` and inventing one for
       this would widen `VoiceEngine` for one adapter — but an inbound event naming a
       retired arm must no longer resolve as a live route.
    3. **Promotion goes through the publishing mechanism that already exists.** The
       winner's body is minted as a NEW prompt version by `prompts.insert_prompt_version`
       (copy-forward, never pointer-rewind — the FLOWS §7 doctrine), and then
       `publishing.apply_to_live` moves the applied pointer and re-publishes. There is
       no engine call in this module for the promotion, and no second way to change what
       an agent says.

    The Apply runs in its OWN transaction, after this one commits, because that is the
    shape `apply_to_live` is written in (it opens its own tenant session and reaches the
    vendor). If it fails, the new version is STAGED and the operator sees the ordinary
    "Apply to live calls" banner on the same screen — a failure that leaves a button to
    press, rather than one that leaves the experiment un-endable.
    """
    if promote_label is not None and promote_label not in VARIANT_LABELS:
        raise ProblemError.business_rule(
            "unknown_variant",
            f"'{promote_label}' is not an arm of this experiment.",
            remediation=f"Promote one of: {', '.join(VARIANT_LABELS)}, or none.",
        )

    new_version: int | None = None
    async with tenant_session(tenant_id) as session:
        header = (await session.execute(text(_LATEST_SQL), {"aid": agent_id})).first()
        if header is None or str(header[2]) != "running":
            raise ProblemError.conflict(
                "no_running_experiment",
                "This agent has no script test running.",
                remediation="Reload the agent — someone may have concluded it already.",
            )
        experiment_id = UUID(str(header[0]))

        promoted_id: UUID | None = None
        arm: Any = None
        if promote_label is not None:
            arm = (
                await session.execute(
                    text(
                        "SELECT v.id, v.disclosure_line, pv.body, pv.version "
                        "FROM prompt_experiment_variants v "
                        "JOIN prompt_versions pv ON pv.id = v.prompt_version_id "
                        "WHERE v.experiment_id = :eid AND v.label = :label"
                    ),
                    {"eid": experiment_id, "label": promote_label},
                )
            ).first()
            if arm is None:
                raise ProblemError.not_found("Variant")
            promoted_id = UUID(str(arm[0]))

        result = await session.execute(
            text(
                "UPDATE prompt_experiments SET status = 'concluded', concluded_at = now(), "
                "promoted_variant_id = :pid, updated_at = now() "
                "WHERE id = :eid AND status = 'running'"
            ),
            {"eid": experiment_id, "pid": promoted_id},
        )
        if rowcount_of(result) == 0:
            raise ProblemError.conflict(
                "no_running_experiment",
                "This script test was concluded while the request was in flight.",
                remediation="Reload the agent to see how it ended.",
            )

        await session.execute(
            text(
                "UPDATE engine_agent_routes SET active = false, updated_at = now() "
                "WHERE tenant_id = :tid AND engine_agent_ref IN ("
                "  SELECT engine_agent_ref FROM prompt_experiment_variants "
                "  WHERE experiment_id = :eid AND engine_agent_ref IS NOT NULL)"
            ),
            {"tid": tenant_id, "eid": experiment_id},
        )

        if promote_label is not None and arm is not None:
            # The arm's disclosure becomes the agent's: the promoted script and the
            # sentence spoken before it are one artefact, and promoting half of it would
            # publish a script whose disclosure nobody chose.
            await session.execute(
                text(
                    "UPDATE agents SET disclosure_line = :disc, updated_at = now() "
                    "WHERE id = :aid AND deleted_at IS NULL"
                ),
                {"disc": str(arm[1]), "aid": agent_id},
            )
            new_version = await prompts.insert_prompt_version(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                body=str(arm[2]),
                notes=f"promoted variant {promote_label} (v{int(arm[3])}) from experiment",
                created_by=created_by,
                # STAGED, then applied below through the one publishing path. Setting
                # this True would publish from here and make this a second way to change
                # a live script.
                apply_live=False,
            )

    applied = False
    engine_synced = False
    if new_version is not None:
        outcome = await publishing.apply_to_live(
            tenant_id=tenant_id, agent_id=agent_id, expected_version=new_version
        )
        applied = outcome.applied
        engine_synced = outcome.engine_synced

    log.info(
        "prompt_experiment_concluded",
        extra={
            "agent_id": str(agent_id),
            "experiment_id": str(experiment_id),
            "promoted": promote_label,
            "version": new_version,
            "applied": applied,
        },
    )
    return ConcludeResult(
        experiment_id=experiment_id,
        promoted_label=promote_label,
        new_version=new_version,
        applied=applied,
        engine_synced=engine_synced,
    )


__all__ = [
    "METRIC_LABELS",
    "ONLY_OUTBOUND_NOTE",
    "PEEKING_CAVEAT",
    "ConcludeResult",
    "ExperimentResults",
    "StartResult",
    "VariantResult",
    "conclude",
    "judge",
    "results_for",
    "start",
]
