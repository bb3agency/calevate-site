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
  any of them importing this module. The post-call pipeline is the only other writer,
  and it records only what the engine has already told us — see the next section.

INBOUND: WHAT WE CAN HONESTLY SAY, AND WHAT WE REFUSE TO SAY
--------------------------------------------------------------
An A/B test needs two things: two scripts, and traffic SPLIT between them. Outbound has
both, because we choose to dial and can therefore choose an arm first. Inbound has only
the first, and the reason is not a missing lookup — it is the shape of a phone call:

* The caller dials the client's number. FLOWS §3: that number answers with the agent, so
  the script they hear was fixed by the agent's live prompt pointer before the phone
  rang. Nothing about that call is a draw of ours, and none of it is undone by noticing
  the call afterwards.
* Drawing a bucket when the call row is created would therefore name an arm the caller
  never heard, on a screen that reports it as a measured conversion rate. That is the
  one failure this feature cannot survive, and it is refused in
  `workers/pipeline.py::_record_arm_the_engine_ran` rather than merely avoided.
* The agent's live prompt version may happen to EQUAL an arm's version — usually the
  control's. Attributing inbound to that arm on those grounds is worse than useless: it
  is 100% of inbound landing in one arm by construction, so the arm that never gets any
  is being compared against a different population. Newcombe's interval assumes two
  randomised binomials and would silently describe the direction mix instead of the
  script.

What IS honest is a fact the engine reports. Every arm is published as its OWN engine
agent with its own ref (`service.publish_variant`), so `ExecutionSnapshot.
engine_agent_ref` answers "which script object ran this call?" without any inference.
The pipeline records an arm when — and only when — that ref names one. In today's
provisioning (one number set per client, attached to the agent) an inbound call names
the agent, so it carries no arm; if a client's telephony account is ever wired to answer
a DID with an arm, those calls ARE that arm's and are recorded as such.

Consequences, all of them enforced here rather than left to a reader:

* `start` still REFUSES an `inbound`-only agent: none of its calls would be split, so
  the screen would say "not enough data" forever.
* `attributed_directions` is READ FROM THE ASSIGNED CALLS, never asserted. It was the
  literal `("outbound",)` and that was a claim about code, not a measurement; the
  moment the two disagreed, the screen would have been the last thing to find out.
* A `both` agent's coverage note prints the number of completed inbound calls in the
  experiment's window that are in NEITHER arm, so the size of the excluded traffic is
  visible rather than merely admitted.

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
from apps.api.db.session import tenant_session
from apps.api.db.transition import transition_status

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

# The coverage sentences. Assembled by `_coverage_note` from what the DATA says, so the
# screen cannot promise a coverage the assignment rows do not have.
INBOUND_NOT_SPLIT_NOTE = (
    "Only outbound calls are split between the arms: an inbound caller reaches the "
    "number's own agent, so the script they hear was decided before they dialled and we "
    "never choose an arm for them."
)
INBOUND_ON_AN_ARM_NOTE = (
    "Some inbound calls were answered by an arm's own line and are counted in it. "
    "Inbound traffic is not split between the arms, so those calls all land in one of "
    "them — read the comparison with that in mind."
)


@dataclass(frozen=True, slots=True)
class VariantResult:
    """One arm's counts and its Wilson interval.

    THREE COUNTS, AND WHY THE OLD SINGLE `dialled` COULD NOT SURVIVE D-60
    ---------------------------------------------------------------------
    `dialled` was `count(*)` over the arm's assignment rows, from a time when the only
    way to get one was `dispatch_call` deciding to place a call. D-60 gave assignment a
    second writer: an inbound call the engine says an arm's OWN agent answered carries
    that arm as a fact. The count then held calls nobody dialled, under a column a client
    reads as "calls we placed for you". Renaming it to something direction-neutral would
    have made the label true and left both numbers it feeds wrong:

    * **The connect-rate diagnostic is an outbound question.** The gap between calls
      placed and calls completed is how a telephony problem is told apart from a script
      problem. An inbound call arrives already connected, so folding inbound into both
      sides of that ratio moves it towards 1 — it makes a bad connect rate look better,
      which is the exact direction a diagnostic must never fail in. So `outbound_dialled`
      is SCOPED, not renamed: it counts the calls we chose to place into this arm.
    * **`completed` — the denominator of `rate` and of Newcombe's interval — is the
      count that can actually be a MIXTURE.** Outbound calls are randomised into arms by
      `assignment.bucket_of`; inbound ones are not drawn at all, they land wherever the
      client's telephony happens to point (D-60). Two arms whose completed calls mix the
      two populations in different proportions are not two randomised binomials, and the
      interval over them describes the mix as much as the script. `inbound_completed`
      is how much of `completed` came that way, published as a NUMBER so the screen can
      qualify the rate it renders instead of relying on a reader having read the prose.
      Outbound completed calls are `completed - inbound_completed`.

    What is deliberately NOT done here: the comparison is still made over the whole
    `completed`, exactly as D-60 left it. Restricting the analysis set to randomised
    traffic is the statistically cleaner move and it is a decision about what the product
    measures, not a naming repair — it belongs with the data this field now makes
    visible, not ahead of it.
    """

    variant_id: UUID
    label: str
    prompt_version: int
    weight_bp: int
    published: bool
    # Calls we PLACED into this arm, any status. Outbound only — see the class note.
    outbound_dialled: int
    # Completed calls in this arm, either direction. The denominator of `rate`.
    # NAMED FOR THE FILTER THAT PRODUCES IT. It was `attributed`, which named the join
    # rather than the count: EVERY assignment row is attributed to an arm, ringing and
    # failed ones included, so `outbound_dialled - attributed` read as "calls we could
    # not attribute" when it is in fact "calls that did not complete" — the difference
    # between a bookkeeping bug and an unanswered phone. Attribution is still a real
    # concept here; it is what `attributed_directions` and `unattributed_inbound` on
    # `ExperimentResults` count, and those keep the word.
    completed: int
    # How many of `completed` arrived inbound, i.e. were never split into this arm.
    # Zero in today's provisioning, where inbound answers as the agent and carries no arm.
    inbound_completed: int
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
    # The directions of the calls that actually carry an arm — measured, not assumed,
    # and empty until the first call is attributed.
    attributed_directions: tuple[str, ...]
    # Completed inbound calls in this experiment's window that carry no arm. The size of
    # what the comparison leaves out, which "outbound only" states without quantifying.
    unattributed_inbound: int
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
    # False when the test had ALREADY ended this way — a success with no second
    # promotion, no second engine push and no second audit row (`LifecycleOut.changed`
    # is the same flag for the same reason). `new_version` and `applied` are then this
    # CALL's facts, which are "none" and "nothing": the first call's version is not
    # recoverable from the concluded row and inventing one would be a guess.
    changed: bool


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
    - **inbound-only agent** — none of its traffic can be split between the arms, so the
      screen would read "not enough data" for ever (module docstring).
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
                    "A script test splits traffic between two arms when a call is placed, "
                    "and this agent only receives calls."
                ),
                remediation=(
                    "An inbound caller reaches the agent's own line, so there is no point "
                    "at which we could send them to one arm rather than the other — and "
                    "deciding afterwards would credit a script they never heard. Run the "
                    "test on an outbound or two-way agent."
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
    list and call it a script difference. `outbound_dialled` is reported alongside so a
    lopsided connection rate is visible rather than buried.

    Every count is resolved BY DIRECTION here rather than by the reader, because since
    D-60 an assignment row can be an inbound call the engine attributed to an arm, and
    the two directions answer different questions (see `VariantResult`). `calls` is the
    only place the direction lives, and the join is already made for `status`.

    The predicate is interpolated, and it is safe BECAUSE it is never a caller's string:
    the only values that reach it are `CONVERSION_METRICS`' own SQL fragments, selected
    by a key that `start` validates against that same dict before it can be stored.
    """
    return (
        "SELECT v.id, v.label, pv.version, v.weight_bp, v.engine_agent_ref, "
        "count(a.call_id) FILTER (WHERE c.direction = 'outbound') AS outbound_dialled, "
        "count(a.call_id) FILTER (WHERE c.status = 'completed') AS completed, "
        "count(a.call_id) FILTER (WHERE c.status = 'completed' AND c.direction = 'inbound') "
        "AS inbound_completed, "
        f"count(a.call_id) FILTER (WHERE c.status = 'completed' AND {conversion_predicate}) "
        "AS conversions "
        "FROM prompt_experiment_variants v "
        "JOIN prompt_versions pv ON pv.id = v.prompt_version_id "
        "LEFT JOIN call_variant_assignments a ON a.variant_id = v.id "
        "LEFT JOIN calls c ON c.id = a.call_id "
        "WHERE v.experiment_id = :eid GROUP BY v.id, v.label, pv.version, v.weight_bp, "
        "v.engine_agent_ref ORDER BY v.label"
    )


# The READ's header: the running experiment if there is one, else the most recent. It is
# a reasonable answer to "what should this screen show?" and a WRONG one to "what am I
# ending?" — see `conclude`, which used to share it and now names its row instead.
_LATEST_SQL = (
    "SELECT e.id, e.name, e.status, e.conversion_metric, e.started_at, e.concluded_at, "
    "pv.label FROM prompt_experiments e "
    "LEFT JOIN prompt_experiment_variants pv ON pv.id = e.promoted_variant_id "
    "WHERE e.agent_id = :aid ORDER BY (e.status = 'running') DESC, e.started_at DESC LIMIT 1"
)

# What the numbers on the screen actually cover, asked of the rows rather than asserted
# by the module that writes them. `call_variant_assignments` carries the experiment id,
# so this needs no join to the variants.
_DIRECTIONS_SQL = (
    "SELECT DISTINCT c.direction FROM call_variant_assignments a "
    "JOIN calls c ON c.id = a.call_id WHERE a.experiment_id = :eid ORDER BY 1"
)

# The traffic the comparison leaves out: completed inbound calls to this agent, inside
# the experiment's window, that no arm claims. `started_at` is null on a row the engine
# has not reported a start for, so the window falls back to when we created it — the
# alternative, dropping those rows, would UNDERCOUNT exactly the calls that went wrong.
_UNATTRIBUTED_INBOUND_SQL = (
    "SELECT count(*) FROM calls c WHERE c.agent_id = :aid AND c.direction = 'inbound' "
    "AND c.status = 'completed' AND COALESCE(c.started_at, c.created_at) >= :started "
    "AND (CAST(:concluded AS timestamptz) IS NULL "
    "     OR COALESCE(c.started_at, c.created_at) <= CAST(:concluded AS timestamptz)) "
    "AND NOT EXISTS (SELECT 1 FROM call_variant_assignments a WHERE a.call_id = c.id)"
)


def _coverage_note(
    *, agent_direction: str, directions: tuple[str, ...], unattributed_inbound: int
) -> str:
    """The sentence under the headline. Empty for an outbound-only agent, which has no
    coverage question to answer."""
    parts: list[str] = []
    if agent_direction != "outbound":
        parts.append(INBOUND_NOT_SPLIT_NOTE)
        if unattributed_inbound:
            parts.append(
                f"{unattributed_inbound} completed inbound call"
                f"{'' if unattributed_inbound == 1 else 's'} in this window "
                f"{'is' if unattributed_inbound == 1 else 'are'} in neither arm."
            )
    if "inbound" in directions:
        parts.append(INBOUND_ON_AN_ARM_NOTE)
    return " ".join(parts)


METRIC_LABELS = {
    "call_outcome_resolved": "calls the agent resolved",
    "lead_won": "leads eventually won",
}


def _variant_result(row: tuple[Any, ...]) -> VariantResult:
    completed = int(row[6])
    conversions = int(row[8])
    interval = wilson_interval(conversions, completed) if completed else None
    return VariantResult(
        variant_id=UUID(str(row[0])),
        label=str(row[1]),
        prompt_version=int(row[2]),
        weight_bp=int(row[3]),
        published=bool(row[4]),
        outbound_dialled=int(row[5]),
        completed=completed,
        inbound_completed=int(row[7]),
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

    smallest = min(a.completed, b.completed)
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

    difference = newcombe_difference(a.conversions, a.completed, b.conversions, b.completed)
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

    Three queries and all three are counts of rows: the arms' tallies, the DIRECTIONS
    those tallied calls actually ran in, and the inbound traffic no arm claims. The
    second and third exist because the coverage of a comparison has to be measured from
    the same rows the comparison is made of — a coverage stated as a constant is right
    only until the day the writers change, and wrong silently thereafter.
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
        directions = tuple(
            str(r[0])
            for r in (await session.execute(text(_DIRECTIONS_SQL), {"eid": experiment_id})).all()
        )
        unattributed_inbound = int(
            (
                await session.execute(
                    text(_UNATTRIBUTED_INBOUND_SQL),
                    {"aid": agent_id, "started": header[4], "concluded": header[5]},
                )
            ).scalar_one()
        )

    variants = [_variant_result(tuple(r)) for r in rows]
    basis, verdict, leader, winner, headline = judge(variants)
    difference = (
        newcombe_difference(
            variants[0].conversions,
            variants[0].completed,
            variants[1].conversions,
            variants[1].completed,
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
        attributed_directions=directions,
        unattributed_inbound=unattributed_inbound,
        coverage_note=_coverage_note(
            agent_direction=agent.direction,
            directions=directions,
            unattributed_inbound=unattributed_inbound,
        ),
    )


# The arm to promote, scoped by AGENT as well as by experiment. The experiment id is the
# caller's now, so an id naming ANOTHER agent's test must not resolve an arm here and then
# be refused two statements later — the arm lookup runs first (its id has to go into the
# CAS's SET), so it is the first statement that has to be scoped.
_ARM_SQL = (
    "SELECT v.id, v.disclosure_line, pv.body, pv.version "
    "FROM prompt_experiment_variants v "
    "JOIN prompt_versions pv ON pv.id = v.prompt_version_id "
    "JOIN prompt_experiments e ON e.id = v.experiment_id "
    "WHERE v.experiment_id = :eid AND e.agent_id = :aid AND v.label = :label"
)

# The same scope, as `transition_status`'s visibility predicate. It reaches the CAS and
# the discriminating SELECT both, which is what makes "another agent's test" and "no such
# test" one answer rather than a 409 naming a status the caller may not know it has
# (db/transition.py's module docstring argues it at length; D-77 added the parameter).
_ON_THIS_AGENT = "agent_id = :aid"


async def _recorded_promotion(session: AsyncSession, experiment_id: UUID) -> str | None:
    """The arm a concluded experiment promoted, or None for "stopped, kept the control".

    Read on the LOSING path only — after the CAS has already failed, and therefore after
    `visible_where` has already established that the row is this agent's — so it cannot
    reintroduce a read-then-write and needs no scope of its own.
    """
    label = (
        await session.execute(
            text(
                "SELECT v.label FROM prompt_experiments e "
                "LEFT JOIN prompt_experiment_variants v ON v.id = e.promoted_variant_id "
                "WHERE e.id = :eid"
            ),
            {"eid": experiment_id},
        )
    ).scalar()
    return None if label is None else str(label)


def _ended_differently(recorded: str | None, requested: str | None) -> ProblemError:
    """409 for a conclude that names an ending this test did not have.

    NAMES what was found, per `db/transition.py`'s contract — "conflict" with no state
    in it leaves an operator with nothing to reload towards. The CODE stays
    `no_running_experiment`: it is the published code for this refusal, nothing switches
    on a different one, and it is still the literal reason the request cannot be honoured.
    """
    found = f"promoting variant {recorded}" if recorded else "with no promotion"
    wanted = f"promote variant {requested}" if requested else "end with no promotion"
    return ProblemError.conflict(
        "no_running_experiment",
        f"This script test has already ended {found}, so it cannot now {wanted}.",
        remediation="Reload the agent to see how it ended.",
    )


async def conclude(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    experiment_id: UUID,
    promote_label: str | None,
    created_by: UUID | None = None,
) -> ConcludeResult:
    """Stop the NAMED experiment, and optionally make one arm the agent's script.

    THE CALLER NAMES THE TEST, AND THAT IS THE WHOLE POINT OF THE PARAMETER
    -----------------------------------------------------------------------
    This used to be keyed on the AGENT: it resolved `_LATEST_SQL`, which prefers the
    RUNNING experiment. So a conclude that took the slow path — a retried request whose
    response was lost, a proxy replay, an operator's second click after a colleague ended
    the test and started the next one — arrived at an agent whose "current" experiment was
    no longer the one the request was about, and ended THAT one instead. It promoted an
    arm of a test nobody had read the results of, published a script to real phone lines,
    and wrote an audit row that looked like a deliberate decision. Nothing in the request
    was wrong; the server simply had no way to tell which test it meant.

    `experiment_id` is a REQUIRED body field, and the alternatives were:

    * **A path segment** (`.../experiments/{id}/conclude`) is the more RESTful spelling
      and was rejected on what this action actually mutates: it promotes a prompt version
      ONTO THE AGENT, moves the agent's disclosure line and republishes the agent — the
      audit row's `object_id` is the agent for that reason. The route stays agent-scoped
      because the effect is, and the experiment id rides as the precondition it is.
    * **`If-Match` on the results read** was rejected on a fact about this resource: the
      results representation changes with every completed call, so an ETag over it would
      refuse a perfectly good conclude because a phone rang while the operator was
      reading. A precondition that fails for reasons unrelated to the hazard trains people
      to retry blindly, which is the behaviour that caused this defect.
    * **Optional, defaulting to "the running one"**, was rejected outright: it is this
      bug behind a flag, and the one caller that would use the default is the stale retry.

    So the console sends the id it is displaying (it has `experiment_id` on every read),
    and a request that names a test which is not the current one is answered ABOUT THE
    TEST IT NAMED — never redirected onto the current one. Concretely, with the arms'
    labels being A/B and the tests being older/newer:

    * named test ended the way you asked -> 200, `changed=False` (the D-65 idempotency,
      RFC 9110 §9.2.2). The existence of a LATER test is not a fact about this request.
    * named test ended some OTHER way -> 409 naming the ending it found.
    * named test is not visible on this agent — another agent's, another tenant's, or an
      id that names nothing -> 404, via `visible_where`.

    ENDING IS PART OF THE FEATURE. Three things happen and they happen in this order:

    1. **CAS `running -> concluded`**, through `db/transition.py::transition_status` —
       the repo's ONE state-transition discriminator, not a second copy of it. Doing this
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

    THE THREE ANSWERS A CONCLUDE OWES ITS CALLER
    ---------------------------------------------
    This path answered ONE 409 (`no_running_experiment`) to all three, which told an
    operator "conflict" for an id that names nothing at all and confirmed a row exists
    that RLS deliberately hides:

    * **No test to end** — an experiment id that names nothing, one belonging to another
      agent, or one belonging to another tenant — is a **404**. A 409 asserts a conflict
      with a resource that is there; here there is none, and under RLS a neighbour's row
      must be indistinguishable from a typo (`ProblemError.not_found`). It comes from
      `transition_status`'s own zero-row discriminator plus `visible_where`, so the CAS
      and the SELECT that explains it agree about which rows exist.
      Deliberately NOT preceded by an `_agent` lookup: "this agent does not exist" and
      "this agent never ran that test" are one answer to the caller of THIS route, and a
      separate agent probe would also start refusing to end the running test of an agent
      somebody soft-deleted mid-experiment.
    * **Already ended the way you asked** — the retry of a lost response, the second
      operator on the same screen — is a **success that promotes nothing a second time**
      (`changed=False`, RFC 9110 §9.2.2: N identical requests have the effect of one).
      `publishing.apply_to_live`, which this function delegates the promotion to, already
      answers its own no-op that way; a 409 here would have been this feature's second
      opinion about the same shape.
    * **Already ended some OTHER way** stays a **409 that names the ending it found**.
      This is the one case that is a real conflict: promoting B over a test that
      concluded on A is not a repeat of anything, and answering 200 would tell an
      operator that B is live when A is.

    The ending is compared on the PROMOTION, not merely on the status, because that is
    what the caller asked for. `promote=None` is an ending in its own right ("stop, keep
    the control"), so a repeat of it is a success and a promotion over it is a conflict.
    """
    if promote_label is not None and promote_label not in VARIANT_LABELS:
        raise ProblemError.business_rule(
            "unknown_variant",
            f"'{promote_label}' is not an arm of this experiment.",
            remediation=f"Promote one of: {', '.join(VARIANT_LABELS)}, or none.",
        )

    new_version: int | None = None
    async with tenant_session(tenant_id) as session:
        promoted_id: UUID | None = None
        arm: Any = None
        if promote_label is not None:
            # Before the CAS because its id is part of the CAS's SET — and therefore the
            # first statement that has to be scoped to the agent in the path.
            arm = (
                await session.execute(
                    text(_ARM_SQL),
                    {"eid": experiment_id, "aid": agent_id, "label": promote_label},
                )
            ).first()
            if arm is None:
                # "Script test", not "Variant": the label is already constrained to A/B
                # above and `start` writes both arms in the same transaction as the
                # experiment, so the row that is missing here is the EXPERIMENT — or it
                # is one this caller may not see, which is the same answer (hard rule 1).
                raise ProblemError.not_found("Script test")
            promoted_id = UUID(str(arm[0]))

        changed = await transition_status(
            session,
            table="prompt_experiments",
            entity="Script test",
            row_id=experiment_id,
            to_status="concluded",
            from_statuses=("running",),
            extra_set="concluded_at = now(), promoted_variant_id = :pid",
            # The caller's id is only ever acted on for THIS agent. There is no fallback
            # to the agent's current test — that fallback WAS the defect.
            visible_where=_ON_THIS_AGENT,
            params={"pid": promoted_id, "aid": agent_id},
        )
        if not changed:
            # It was already over — either before this request, or by the operator who
            # won the race with it. Everything below (retiring the arms' routes, minting
            # the version, the caller's audit row) belongs to the call that MOVED it.
            recorded = await _recorded_promotion(session, experiment_id)
            if recorded != promote_label:
                raise _ended_differently(recorded, promote_label)
            return ConcludeResult(
                experiment_id=experiment_id,
                promoted_label=recorded,
                new_version=None,
                applied=False,
                engine_synced=False,
                changed=False,
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
        changed=True,
    )


__all__ = [
    "INBOUND_NOT_SPLIT_NOTE",
    "INBOUND_ON_AN_ARM_NOTE",
    "METRIC_LABELS",
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
