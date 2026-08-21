"""Gate 13 (OPERATIONS §2) — concurrency ceiling, behaviour at the limit, dispatch rate.

    from scripts.pilot.concurrency import probe_concurrency_ceiling, evaluate_gate13

Three numbers come out of this gate and **all three must be recorded** (OPERATIONS §2
gate 13, FLOWS §5): the platform's concurrent-call ceiling, the Sarvam BYOK-tier model
concurrency, and the SIP trunk channel count. The dispatcher's effective pool is the MIN
of the three. A tool that recorded only the platform number would invite someone to
configure the dispatcher against 100 and discover in production that the trunk was sold
with 10 channels — so `effective_ceiling` REFUSES to produce a number while any leg is
missing, and says which one. That refusal is the most load-bearing line in this file.

D-32 context: Pilots advertises 100 concurrent, and two customers (GoKwik, Futwork) are
reported to run 250+. Both are vendor/third-party claims. This gate confirms OURS.

**What is measured versus asked.** The platform ceiling, the behaviour at the limit and
the dispatch rate limit are MEASURED by the probes below. The model concurrency and the
trunk channels are ASKED — they come from Sarvam's plan terms and the trunk contract, and
arrive as written answers, so they enter as `CeilingLeg(source="vendor_written")` and are
never invented by this module.

**Money discipline.** Every probe dial is a real call attempt on a real account with real
prepaid credit (~₹3-5k of pilot budget, OPERATIONS §2). So: `max_dials` is a hard stop
the ramp cannot pass, an accepted dial is hung up through the `hangup` seam the moment it
is observed, and the intended target is a number that rejects at the far end so the call
occupies a concurrency slot without buying minutes. The probes take no cost arithmetic of
their own — cost lands in `usage_events` through the existing path, in NUMERIC INR, and
duplicating it here would be a second way to do one thing.

**The seam.** This module never touches an engine. The runner supplies `dial` — one
coroutine that starts one call through the configured `VoiceEngine` adapter and returns a
`ProbeOutcome` — and optionally `hangup`. That is what lets the whole file execute against
the `fake` adapter in the normal suite, which is the point: a measurement tool that has
never run is as unverified as the thing it measures, and it gets one chance on the day.

**Probe refs are opaque and validated as such.** A `probe_ref` that looks like a phone
number is rejected at the model boundary rather than trusted not to be logged (hard
rule 6). Log ids.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# --- vocabulary ---------------------------------------------------------------

#: What one dial attempt did. `queued` and `rejected` are the two answers gate 13 asks
#: for by name ("queue vs reject"), and they are NOT interchangeable: a platform that
#: queues makes our dispatcher's over-limit contacts a pacing problem, a platform that
#: rejects makes them an error-handling problem with a retry budget.
ProbeOutcomeKind = Literal["accepted", "queued", "rejected", "error", "timeout"]

Verdict = Literal["PASS", "FAIL", "INCONCLUSIVE", "NOT RUN"]

PASSING_VERDICTS: frozenset[str] = frozenset({"PASS"})

#: Where a ceiling number came from. `vendor_verbal` exists to be distinguishable from
#: `vendor_written` — gate 12's whole lesson is that a number said on a call is not a
#: number we hold, and D-31 lists "in writing" for every commercial term.
CeilingSource = Literal["measured", "vendor_written", "vendor_verbal", "absent"]

CeilingBasis = Literal["measured", "incomplete", "not_run"]

ProbeBasis = Literal["measured", "ceiling_above_probed_max", "aborted_spend_guard", "not_run"]


def is_phone_shaped(value: str) -> bool:
    """True when the string carries something personal — a phone number above all.

    Delegates to `scripts.pilot.redact.scrub_text`, which is the harness's exit guard:
    ONE way per problem, and its rule is the right one here. A hand-rolled "any run of
    7+ digits" was written first and was WRONG in a way this suite caught — it fires on
    the digits inside an engine handle (`fakecall_ee4edcaa460007891e333f44`), so every
    accepted probe would have been rejected as a phone number and the ceiling probe would
    have reported a limit that was our own validator. `redact.py` documents the same
    false positive and solves it with lookarounds.
    """
    from scripts.pilot.redact import scrub_text

    return scrub_text(value)[1] > 0


# --- the seam -----------------------------------------------------------------


class ProbeOutcome(BaseModel):
    """One dial attempt, classified by the caller who owns the adapter.

    Classification belongs to the runner, not here: deciding whether a given engine's
    429 means "queued behind your ceiling" or "rejected, do not retry" requires seeing
    the vendor's response, and hard rule 2 keeps vendor shapes inside `apps/api/engine/`.
    This module consumes the verdict and never the payload.
    """

    probe_ref: str
    kind: ProbeOutcomeKind
    elapsed_ms: int = Field(ge=0)
    #: Stable machine identifier, our side (`engine_rejected`, `rate_limited`) — this is
    #: the "error shape" gate 13 asks to be recorded.
    error_code: str | None = None
    http_status: int | None = None
    #: User-safe title only. Never a response body: a vendor error body is a vendor
    #: payload shape, and it is exactly where a phone number would be echoed back.
    error_title: str | None = None

    @field_validator("probe_ref")
    @classmethod
    def _opaque(cls, value: str) -> str:
        if is_phone_shaped(value):
            raise ValueError(
                "probe_ref looks like a phone number; pass an opaque probe id (hard rule 6)"
            )
        return value


#: Start ONE call and report what happened. Never raises for an engine-side refusal —
#: that is an outcome, not an exception — but an unexpected exception is caught and
#: recorded rather than allowed to abort a ramp that has already spent money.
DialProbe = Callable[[str], Awaitable[ProbeOutcome]]

#: End a call we just started, so a probe dial costs a ring and not a conversation.
Hangup = Callable[[str], Awaitable[None]]

Sleeper = Callable[[float], Awaitable[None]]


# --- results ------------------------------------------------------------------


class ErrorShape(BaseModel):
    error_code: str | None
    http_status: int | None
    error_title: str | None
    count: int


class WidthObservation(BaseModel):
    width: int
    accepted: int
    queued: int
    rejected: int
    errors: int
    timeouts: int

    @property
    def limited(self) -> bool:
        return self.accepted < self.width


class CeilingProbeResult(BaseModel):
    """OUR ceiling as observed, and what happened at it."""

    basis: ProbeBasis
    #: The widest concurrent fan-out at which EVERY dial was accepted.
    highest_clean_width: int | None = None
    #: The first width at which anything was not accepted.
    first_limited_width: int | None = None
    behaviour_at_limit: Literal["queue", "reject", "error", "timeout", "unknown"] = "unknown"
    error_shapes: list[ErrorShape] = Field(default_factory=list)
    observations: list[WidthObservation] = Field(default_factory=list)
    dials_used: int = 0
    note: str = ""

    @property
    def ceiling(self) -> int | None:
        """The ceiling, or None when the probe never reached one.

        `highest_clean_width` is NOT the ceiling when nothing was ever refused — it is a
        lower bound on it, and returning it as "the ceiling" is how a dispatcher ends up
        configured at whatever number the probe happened to stop at.
        """
        return self.highest_clean_width if self.basis == "measured" else None


class RateLimitResult(BaseModel):
    """The outbound call-creation rate limit — unpublished, so measured (FLOWS §5 (5))."""

    basis: ProbeBasis
    highest_clean_rps: float | None = None
    first_limited_rps: float | None = None
    error_shapes: list[ErrorShape] = Field(default_factory=list)
    dials_used: int = 0
    note: str = ""

    @property
    def dispatcher_config_rps(self) -> float | None:
        """What FLOWS §5 (5) may be configured from, or None.

        Only a MEASURED limit yields a config value. When the probe never provoked a
        refusal the honest statement is "at least X", and a dispatcher paced at a lower
        bound it mistook for the limit is the one that trips the real one in production.
        """
        return self.highest_clean_rps if self.basis == "measured" else None


class CeilingLeg(BaseModel):
    name: str
    value: int | None = None
    source: CeilingSource = "absent"
    note: str = ""

    def model_post_init(self, _context: object) -> None:
        # A value with no source is a number nobody can trace, and a source with no value
        # is a leg that reads as recorded while holding nothing. Both are the failure
        # this gate exists to prevent, so both are rejected at construction.
        if self.value is not None and self.source == "absent":
            raise ValueError(f"leg {self.name!r} has a value but no source")
        if self.value is None and self.source != "absent":
            raise ValueError(f"leg {self.name!r} has a source but no value")


class EffectiveCeiling(BaseModel):
    value: int | None
    binding_leg: str | None
    basis: CeilingBasis
    missing: list[str] = Field(default_factory=list)
    legs: list[CeilingLeg] = Field(default_factory=list)
    note: str = ""


class Gate13Result(BaseModel):
    verdict: Verdict
    effective: EffectiveCeiling
    platform_probe: CeilingProbeResult
    rate_limit: RateLimitResult
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict in PASSING_VERDICTS


# --- probes -------------------------------------------------------------------


def _shapes(outcomes: Sequence[ProbeOutcome]) -> list[ErrorShape]:
    buckets: dict[tuple[str | None, int | None, str | None], int] = {}
    for outcome in outcomes:
        if outcome.kind == "accepted":
            continue
        key = (outcome.error_code, outcome.http_status, outcome.error_title)
        buckets[key] = buckets.get(key, 0) + 1
    return [
        ErrorShape(error_code=code, http_status=status, error_title=title, count=count)
        for (code, status, title), count in sorted(buckets.items(), key=lambda kv: str(kv[0]))
    ]


def _observation(width: int, outcomes: Sequence[ProbeOutcome]) -> WidthObservation:
    def count(kind: ProbeOutcomeKind) -> int:
        return sum(1 for o in outcomes if o.kind == kind)

    return WidthObservation(
        width=width,
        accepted=count("accepted"),
        queued=count("queued"),
        rejected=count("rejected"),
        errors=count("error"),
        timeouts=count("timeout"),
    )


def _behaviour(outcomes: Sequence[ProbeOutcome]) -> Literal["queue", "reject", "error", "timeout"]:
    """What the platform did at the limit, by the most severe answer present.

    Ordering rather than modal count: one hard rejection inside a mostly-queued width is
    the fact the dispatcher has to survive, and a majority vote would hide it.
    """
    kinds = {o.kind for o in outcomes}
    if "rejected" in kinds:
        return "reject"
    if "error" in kinds:
        return "error"
    if "timeout" in kinds:
        return "timeout"
    return "queue"


async def _dial_one(dial: DialProbe, hangup: Hangup | None, probe_ref: str) -> ProbeOutcome:
    started = time.monotonic()
    try:
        outcome = await dial(probe_ref)
    except Exception as exc:
        # Never abort a ramp that has already spent credit; record the shape and carry
        # on. The type NAME only: an exception's message can carry the number that was
        # dialled, and this string ends up in a committed scorecard (hard rule 6).
        return ProbeOutcome(
            probe_ref=probe_ref,
            kind="error",
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error_code=type(exc).__name__,
        )
    if outcome.kind == "accepted" and hangup is not None:
        try:
            await hangup(probe_ref)
        except Exception:
            # A failed hangup costs minutes, it does not invalidate the measurement —
            # but it must be visible, so it becomes a note on the outcome rather than
            # a silent swallow.
            return outcome.model_copy(update={"error_title": "hangup failed; check spend"})
    return outcome


async def probe_concurrency_ceiling(
    dial: DialProbe,
    *,
    widths: Sequence[int],
    hangup: Hangup | None = None,
    max_dials: int,
    stop_at_first_limit: bool = True,
) -> CeilingProbeResult:
    """Ramp concurrent dials until the platform stops accepting them.

    Returns `basis="ceiling_above_probed_max"` — not a ceiling — when every probed width
    was accepted in full, and `basis="aborted_spend_guard"` when `max_dials` stopped the
    ramp before it reached an answer. Both are results; neither is a number to configure
    a dispatcher from, which is why `ceiling` returns None for both.
    """
    observations: list[WidthObservation] = []
    all_outcomes: list[ProbeOutcome] = []
    dials_used = 0
    highest_clean: int | None = None
    first_limited: int | None = None
    limit_outcomes: list[ProbeOutcome] = []

    for width in sorted(widths):
        if dials_used + width > max_dials:
            note = (
                f"ABORTED by the spend guard after {dials_used} dials: width {width} "
                f"would exceed max_dials={max_dials}. No ceiling was established."
            )
            return CeilingProbeResult(
                basis="aborted_spend_guard",
                highest_clean_width=highest_clean,
                first_limited_width=first_limited,
                error_shapes=_shapes(all_outcomes),
                observations=observations,
                dials_used=dials_used,
                note=note,
            )
        refs = [f"probe-w{width}-{i}" for i in range(width)]
        outcomes = list(await asyncio.gather(*(_dial_one(dial, hangup, ref) for ref in refs)))
        dials_used += width
        all_outcomes.extend(outcomes)
        observation = _observation(width, outcomes)
        observations.append(observation)
        if observation.limited:
            first_limited = width
            limit_outcomes = outcomes
            if stop_at_first_limit:
                break
        else:
            highest_clean = width

    if first_limited is None:
        probed_max = max(widths) if widths else 0
        return CeilingProbeResult(
            basis="ceiling_above_probed_max" if observations else "not_run",
            highest_clean_width=highest_clean,
            observations=observations,
            error_shapes=_shapes(all_outcomes),
            dials_used=dials_used,
            note=(
                f"Every dial was accepted up to width {probed_max}. OUR ceiling is "
                f"therefore ABOVE {probed_max} and was not found — this is a lower "
                f"bound, not a ceiling, and must not be configured as one."
                if observations
                else "NOT RUN — no widths were probed."
            ),
        )

    return CeilingProbeResult(
        basis="measured",
        highest_clean_width=highest_clean,
        first_limited_width=first_limited,
        behaviour_at_limit=_behaviour(limit_outcomes),
        error_shapes=_shapes(all_outcomes),
        observations=observations,
        dials_used=dials_used,
        note=(
            f"Every dial accepted at width {highest_clean}; width {first_limited} was "
            f"limited. Behaviour at the limit: {_behaviour(limit_outcomes)}."
            if highest_clean is not None
            else f"The narrowest probed width ({first_limited}) was already limited — "
            f"the ceiling is below it and was not bracketed. Probe lower."
        ),
    )


async def probe_dispatch_rate_limit(
    dial: DialProbe,
    *,
    rates_per_s: Sequence[float],
    dials_per_rate: int,
    hangup: Hangup | None = None,
    max_dials: int,
    sleep: Sleeper = asyncio.sleep,
) -> RateLimitResult:
    """Find the outbound call-CREATION rate the platform tolerates.

    A different quantity from the concurrency ceiling and frequently a tighter one: a
    platform that holds 100 concurrent calls may still refuse 20 creations in a second.
    FLOWS §5 (5) paces the dispatch loop across ALL tenants against this number, so it
    has to be measured rather than inferred from the ceiling.

    Dials are SPACED at 1/rate and awaited together, so a slow response does not silently
    reduce the rate actually offered — the alternative (await each dial before the next)
    measures the platform's response time, not its rate limit. `sleep` is injectable so
    the suite exercises the pacing without spending wall-clock seconds.
    """
    dials_used = 0
    all_outcomes: list[ProbeOutcome] = []
    highest_clean: float | None = None

    for rate in sorted(rates_per_s):
        if rate <= 0:
            raise ValueError("rates_per_s must be positive")
        if dials_used + dials_per_rate > max_dials:
            return RateLimitResult(
                basis="aborted_spend_guard",
                highest_clean_rps=highest_clean,
                error_shapes=_shapes(all_outcomes),
                dials_used=dials_used,
                note=(
                    f"ABORTED by the spend guard after {dials_used} dials before probing "
                    f"{rate}/s. No rate limit was established."
                ),
            )
        interval = 1.0 / rate
        tasks: list[asyncio.Task[ProbeOutcome]] = []
        for i in range(dials_per_rate):
            if i:
                await sleep(interval)
            ref = f"probe-r{rate}-{i}"
            tasks.append(asyncio.create_task(_dial_one(dial, hangup, ref)))
        outcomes = list(await asyncio.gather(*tasks))
        dials_used += dials_per_rate
        all_outcomes.extend(outcomes)
        if all(o.kind == "accepted" for o in outcomes):
            highest_clean = rate
            continue
        return RateLimitResult(
            basis="measured",
            highest_clean_rps=highest_clean,
            first_limited_rps=rate,
            error_shapes=_shapes(all_outcomes),
            dials_used=dials_used,
            note=(
                f"Sustained {highest_clean}/s cleanly; {rate}/s was limited."
                if highest_clean is not None
                else f"The slowest probed rate ({rate}/s) was already limited — the "
                f"limit is below it and was not bracketed. Probe slower."
            ),
        )

    probed_max = max(rates_per_s) if rates_per_s else 0.0
    return RateLimitResult(
        basis="ceiling_above_probed_max" if all_outcomes else "not_run",
        highest_clean_rps=highest_clean,
        error_shapes=_shapes(all_outcomes),
        dials_used=dials_used,
        note=(
            f"No refusal up to {probed_max}/s. The limit is ABOVE that and was not "
            f"found — a lower bound, not the limit."
            if all_outcomes
            else "NOT RUN — no rates were probed."
        ),
    )


# --- the three ceilings -------------------------------------------------------

PLATFORM_LEG = "platform_concurrent_calls"
MODEL_LEG = "sarvam_byok_model_concurrency"
TRUNK_LEG = "sip_trunk_channels"

REQUIRED_LEGS: tuple[str, ...] = (PLATFORM_LEG, MODEL_LEG, TRUNK_LEG)


def platform_leg_from_probe(probe: CeilingProbeResult) -> CeilingLeg:
    """Turn the probe into a leg — absent unless the probe actually found a ceiling."""
    ceiling = probe.ceiling
    if ceiling is None:
        return CeilingLeg(
            name=PLATFORM_LEG,
            value=None,
            source="absent",
            note=f"probe basis={probe.basis}: {probe.note}",
        )
    return CeilingLeg(
        name=PLATFORM_LEG,
        value=ceiling,
        source="measured",
        note=f"behaviour at the limit: {probe.behaviour_at_limit}",
    )


def effective_ceiling(legs: Sequence[CeilingLeg]) -> EffectiveCeiling:
    """MIN of the three legs — or NOTHING, plus the names of the ones we do not hold.

    The rejected alternative was min() over whatever is present, defaulting the rest to
    the platform number. That produces a plausible integer from an incomplete picture,
    and a plausible integer is what gets copied into a config file. FLOWS §5 wants the
    MIN of three; two thirds of a MIN is not a smaller MIN, it is a guess.
    """
    by_name = {leg.name: leg for leg in legs}
    present = [leg for leg in legs if leg.value is not None]
    missing = [
        name for name in REQUIRED_LEGS if by_name.get(name) is None or by_name[name].value is None
    ]

    if not present:
        return EffectiveCeiling(
            value=None,
            binding_leg=None,
            basis="not_run",
            missing=missing,
            legs=list(legs),
            note="NOT RUN — none of the three ceilings was recorded.",
        )
    if missing:
        return EffectiveCeiling(
            value=None,
            binding_leg=None,
            basis="incomplete",
            missing=missing,
            legs=list(legs),
            note=(
                "INCOMPLETE — no effective ceiling. Missing: "
                + ", ".join(missing)
                + ". Do NOT configure the dispatcher from the legs that are present: the "
                "effective pool is the MIN of all three (FLOWS §5) and an unrecorded leg "
                "is the one most likely to be the smallest."
            ),
        )
    binding = min(present, key=lambda leg: leg.value or 0)
    return EffectiveCeiling(
        value=binding.value,
        binding_leg=binding.name,
        basis="measured",
        missing=[],
        legs=list(legs),
        note=(
            f"Effective pool {binding.value} concurrent calls, bound by {binding.name}. "
            "Re-run this when any vendor plan changes — the binding leg moves."
        ),
    )


def evaluate_gate13(
    *,
    platform_probe: CeilingProbeResult,
    rate_limit: RateLimitResult,
    model_leg: CeilingLeg,
    trunk_leg: CeilingLeg,
) -> Gate13Result:
    """Gate 13's verdict: it passes when all four things it asks for exist.

    Gate 13 is a SOFT gate (S) — it shapes M1 scope rather than reopening the engine
    decision — so passing means "recorded", not "big enough". Whether the number is big
    enough is a capacity decision for FLOWS §5, made against a number that exists.
    """
    effective = effective_ceiling([platform_leg_from_probe(platform_probe), model_leg, trunk_leg])
    rate_known = rate_limit.dispatcher_config_rps is not None
    behaviour_known = platform_probe.behaviour_at_limit != "unknown"

    if platform_probe.basis == "not_run" and rate_limit.basis == "not_run":
        return Gate13Result(
            verdict="NOT RUN",
            effective=effective,
            platform_probe=platform_probe,
            rate_limit=rate_limit,
            note="NOT RUN — neither probe was executed. This is not a pass.",
        )
    if effective.basis == "measured" and rate_known and behaviour_known:
        return Gate13Result(
            verdict="PASS",
            effective=effective,
            platform_probe=platform_probe,
            rate_limit=rate_limit,
            note=(
                f"All three ceilings recorded (effective {effective.value}, bound by "
                f"{effective.binding_leg}); behaviour at the limit "
                f"'{platform_probe.behaviour_at_limit}'; dispatch rate "
                f"{rate_limit.dispatcher_config_rps}/s."
            ),
        )
    gaps: list[str] = []
    if effective.basis != "measured":
        gaps.append(f"ceilings ({effective.note})")
    if not rate_known:
        gaps.append(f"dispatch rate limit ({rate_limit.note})")
    if not behaviour_known:
        gaps.append("behaviour at the limit was never observed")
    return Gate13Result(
        verdict="INCONCLUSIVE",
        effective=effective,
        platform_probe=platform_probe,
        rate_limit=rate_limit,
        note="INCONCLUSIVE — ran, but incomplete. Outstanding: " + "; ".join(gaps),
    )


def render_gate13_markdown(result: Gate13Result) -> str:
    """The scorecard block. Holds ids, counts and rates — never a number that was dialled."""
    lines = [
        "## Gate 13 — concurrency ceiling and dispatch rate (OPERATIONS §2)",
        "",
        f"**VERDICT: {result.verdict}**",
        "",
        result.note,
        "",
        "### The three ceilings (effective pool = MIN of all three, FLOWS §5)",
        "",
        "| leg | value | source |",
        "|---|---|---|",
    ]
    for leg in result.effective.legs:
        value = str(leg.value) if leg.value is not None else "**ABSENT**"
        lines.append(f"| {leg.name} | {value} | {leg.source} |")
    effective = (
        str(result.effective.value)
        if result.effective.value is not None
        else f"**NOT ESTABLISHED** ({result.effective.basis})"
    )
    lines += [
        "",
        f"- effective ceiling: {effective}"
        + (f", bound by `{result.effective.binding_leg}`" if result.effective.binding_leg else ""),
        f"- {result.effective.note}",
        "",
        "### Behaviour at the limit",
        "",
        f"- probe basis: **{result.platform_probe.basis}**",
        f"- highest width fully accepted: {result.platform_probe.highest_clean_width}",
        f"- first limited width: {result.platform_probe.first_limited_width}",
        f"- behaviour: **{result.platform_probe.behaviour_at_limit}**",
        f"- dials spent: {result.platform_probe.dials_used}",
        f"- {result.platform_probe.note}",
        "",
    ]
    if result.platform_probe.error_shapes:
        lines += ["Error shapes observed:", ""]
        lines += [
            f"- `{s.error_code}` status={s.http_status} title={s.error_title!r} x{s.count}"
            for s in result.platform_probe.error_shapes
        ]
        lines.append("")
    lines += [
        "### Outbound dispatch rate limit (unpublished — measured)",
        "",
        f"- basis: **{result.rate_limit.basis}**",
        f"- highest clean rate: {result.rate_limit.highest_clean_rps}/s",
        f"- first limited rate: {result.rate_limit.first_limited_rps}/s",
        f"- **dispatcher config value (FLOWS §5 (5)): "
        f"{result.rate_limit.dispatcher_config_rps or 'DO NOT CONFIGURE — not measured'}**",
        f"- dials spent: {result.rate_limit.dials_used}",
        f"- {result.rate_limit.note}",
        "",
    ]
    return "\n".join(lines)


# --- wiring into the harness ---------------------------------------------------
#
# `scripts/pilot/runner.py` names this module in OPTIONAL_GATE_MODULES and reads a
# `GATES: {number: runner}` mapping, with results in the shared PASS/FAIL/NOT RUN
# vocabulary of `scripts/pilot/results.py`.

#: The two ASKED ceilings and the probe plan. A file rather than CLI flags because the
#: runner's `--attest` vocabulary is closed and owned by another module: adding
#: `gate13.trunk_channels` there is the tidier long-term seam, and until it exists this
#: file is the one that does not require editing someone else's module mid-flight.
INPUTS_ENV = "CALEVATE_PILOT_GATE13_INPUTS"
DEFAULT_INPUTS_PATH = "docs/evidence/gate13-inputs.json"

#: Widths and rates the probe walks unless the inputs file overrides them. Deliberately
#: modest: D-32 puts the advertised ceiling at 100, but a ramp to 100 is 100 call
#: attempts against a pilot budget of ~₹3-5k, so the default finds the shape of the
#: limit and the operator raises it knowingly.
DEFAULT_WIDTHS: tuple[int, ...] = (1, 2, 4, 8, 12)
DEFAULT_RATES_PER_S: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0)


class Gate13Inputs(BaseModel):
    """What the operator supplies. Every field optional; absent stays absent."""

    engine_agent_ref: str | None = None
    model_concurrency: int | None = None
    model_concurrency_source: CeilingSource = "absent"
    trunk_channels: int | None = None
    trunk_channels_source: CeilingSource = "absent"
    widths: list[int] = Field(default_factory=lambda: list(DEFAULT_WIDTHS))
    rates_per_s: list[float] = Field(default_factory=lambda: list(DEFAULT_RATES_PER_S))

    def legs(self) -> tuple[CeilingLeg, CeilingLeg]:
        return (
            CeilingLeg(
                name=MODEL_LEG,
                value=self.model_concurrency,
                source=self.model_concurrency_source
                if self.model_concurrency is not None
                else "absent",
                note="Sarvam BYOK-tier concurrency; D-36 makes the plan's rpm a "
                "CONCURRENCY input, not a price input.",
            ),
            CeilingLeg(
                name=TRUNK_LEG,
                value=self.trunk_channels,
                source=self.trunk_channels_source if self.trunk_channels is not None else "absent",
                note="SIP trunk channels from Exotel/Vobiz.",
            ),
        )


def gate13_result(result: Gate13Result) -> Any:
    """Project onto the shared scorecard vocabulary.

    Gate 13 is a SOFT gate: it asks for numbers to be RECORDED, so a sub-check passes
    when the number exists and reports `not_run` (with the reason) when it does not.
    Nothing here can `fail` — "the ceiling turned out to be 40" is a capacity fact for
    FLOWS §5, not a failure of the vendor, and scoring it as one would put a red on a
    scorecard that reopens engine decisions.
    """
    from scripts.pilot.results import GateRun, not_run, passed

    probe = result.platform_probe
    rate = result.rate_limit
    checks = [
        passed(
            "platform_concurrency_ceiling",
            f"{probe.note}",
            ceiling=probe.ceiling,
        )
        if probe.ceiling is not None
        else not_run("platform_concurrency_ceiling", f"basis={probe.basis}: {probe.note}"),
        passed("behaviour_at_the_limit", f"observed: {probe.behaviour_at_limit}")
        if probe.behaviour_at_limit != "unknown"
        else not_run(
            "behaviour_at_the_limit",
            "the probe never reached a limit, so queue-vs-reject is unobserved.",
        ),
        passed(
            "outbound_dispatch_rate_limit",
            f"{rate.note} This is the FLOWS §5 (5) config value.",
            rps=rate.dispatcher_config_rps,
        )
        if rate.dispatcher_config_rps is not None
        else not_run("outbound_dispatch_rate_limit", f"basis={rate.basis}: {rate.note}"),
        passed(
            "effective_ceiling_all_three_legs",
            result.effective.note,
            effective=result.effective.value,
            binding_leg=result.effective.binding_leg or "",
        )
        if result.effective.value is not None
        else not_run(
            "effective_ceiling_all_three_legs",
            result.effective.note,
        ),
    ]
    findings = tuple(
        f"{leg.name} was never recorded ({leg.note})"
        for leg in result.effective.legs
        if leg.value is None
    )
    return GateRun(
        number=13,
        title="Concurrency ceiling and dispatch rate",
        checks=tuple(checks),
        findings=findings,
    )


def dial_through_engine(ctx: Any) -> DialProbe:
    """Build the `dial` seam from a `GateContext`.

    Classification lives here — at the edge that owns the engine — rather than in the
    probes: an engine-side refusal is an OUTCOME (`rejected`), a transport failure is an
    `error`, and only this layer can tell them apart. `ProblemError.kind`/`code` are our
    normalized error ladder, so nothing vendor-shaped crosses into the probes (hard rule
    2), and `ProblemError.detail` is user-safe by construction (`core/errors.py`) —
    everything else contributes only its type name, because an arbitrary exception's
    `str()` on this path can carry the number that was dialled (hard rule 6).
    """
    from apps.api.core.errors import ProblemError
    from calevate_shared.engine import CallContext

    async def dial(probe_ref: str) -> ProbeOutcome:
        started = time.monotonic()
        if not ctx.spend_a_call():
            # Cannot happen: `max_dials` is bounded by the same budget before the ramp
            # starts. If it ever does, it must be loud and it must not be mistaken for a
            # platform limit, which is why it carries its own code rather than 'rejected'.
            raise RuntimeError("pilot call budget exhausted mid-probe")
        try:
            handle = await ctx.engine.start_outbound_call(
                ctx.engine_agent_ref,
                ctx.to_e164,
                CallContext(),
            )
        except ProblemError as exc:
            return ProbeOutcome(
                probe_ref=probe_ref,
                kind="rejected"
                if exc.kind in ("validation", "conflict", "dependency")
                else "error",
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code=exc.code,
                http_status=exc.status,
                error_title=exc.title,
            )
        # The handle is the engine's execution id; it is what a hangup needs and it is
        # never a phone number, so it is safe to carry (redact.call_ref says the same).
        return ProbeOutcome(
            probe_ref=handle,
            kind="accepted",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    return dial


def hangup_through_engine(ctx: Any) -> Hangup:
    """End a probe call immediately: a concurrency probe buys a slot, not a conversation."""

    async def hangup(probe_ref: str) -> None:
        await ctx.engine.end_call(probe_ref)

    return hangup


def load_gate13_inputs(path_str: str | None = None) -> Gate13Inputs | None:
    import os
    from pathlib import Path

    path = Path(path_str or os.environ.get(INPUTS_ENV) or DEFAULT_INPUTS_PATH)
    if not path.exists():
        return None
    return Gate13Inputs.model_validate_json(path.read_text(encoding="utf-8"))


async def run_gate_13(ctx: Any) -> Any:
    """Gate 13 for `scripts.pilot.runner`.

    Refuses rather than guesses, in this order: no inputs file, no agent ref, no call
    budget (dry run is the default and 0 calls means 0 dials). Each refusal is a NOT RUN
    carrying what is missing — never a ceiling inferred from a probe that never ran.
    """
    from scripts.pilot.results import GateRun

    title = "Concurrency ceiling and dispatch rate"
    inputs = load_gate13_inputs()
    if inputs is None:
        return GateRun(
            number=13,
            title=title,
            blocked=(
                f"no inputs file at {DEFAULT_INPUTS_PATH} (override with ${INPUTS_ENV}); "
                "it carries the Sarvam BYOK concurrency and the trunk channel count, "
                "which are written answers rather than measurements."
            ),
        )
    model_leg, trunk_leg = inputs.legs()
    budget = int(getattr(ctx, "calls_remaining", 0) or 0)
    agent_ref = inputs.engine_agent_ref or getattr(ctx, "engine_agent_ref", None)
    if not agent_ref or budget <= 0:
        reason = (
            "no engine agent ref in the inputs file"
            if not agent_ref
            else "no call budget: this gate places real calls, and dry run is the default"
        )
        return gate13_result(
            evaluate_gate13(
                platform_probe=CeilingProbeResult(basis="not_run", note=reason),
                rate_limit=RateLimitResult(basis="not_run", note=reason),
                model_leg=model_leg,
                trunk_leg=trunk_leg,
            )
        )
    ctx.engine_agent_ref = agent_ref
    dial, hangup = dial_through_engine(ctx), hangup_through_engine(ctx)
    # The ramp and the rate probe SHARE one budget, and the ramp goes first: a ceiling
    # nobody found is the more expensive gap of the two.
    probe = await probe_concurrency_ceiling(
        dial, widths=inputs.widths, hangup=hangup, max_dials=budget
    )
    remaining = max(0, budget - probe.dials_used)
    rate = (
        await probe_dispatch_rate_limit(
            dial,
            rates_per_s=inputs.rates_per_s,
            dials_per_rate=3,
            hangup=hangup,
            max_dials=remaining,
        )
        if remaining
        else RateLimitResult(
            basis="not_run",
            note="the ceiling ramp used the whole call budget; the rate limit was not probed.",
        )
    )
    return gate13_result(
        evaluate_gate13(
            platform_probe=probe, rate_limit=rate, model_leg=model_leg, trunk_leg=trunk_leg
        )
    )


GATES = {13: run_gate_13}


__all__ = [
    "DEFAULT_INPUTS_PATH",
    "DEFAULT_RATES_PER_S",
    "DEFAULT_WIDTHS",
    "GATES",
    "INPUTS_ENV",
    "MODEL_LEG",
    "PASSING_VERDICTS",
    "PLATFORM_LEG",
    "REQUIRED_LEGS",
    "TRUNK_LEG",
    "CeilingLeg",
    "CeilingProbeResult",
    "DialProbe",
    "EffectiveCeiling",
    "ErrorShape",
    "Gate13Inputs",
    "Gate13Result",
    "Hangup",
    "ProbeOutcome",
    "ProbeOutcomeKind",
    "RateLimitResult",
    "Verdict",
    "WidthObservation",
    "dial_through_engine",
    "effective_ceiling",
    "evaluate_gate13",
    "gate13_result",
    "hangup_through_engine",
    "is_phone_shaped",
    "load_gate13_inputs",
    "platform_leg_from_probe",
    "probe_concurrency_ceiling",
    "probe_dispatch_rate_limit",
    "render_gate13_markdown",
    "run_gate_13",
]
