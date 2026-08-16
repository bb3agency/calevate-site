"""Gate 4 (OPERATIONS §2) — real-call latency: the ledger, the arithmetic, the verdict.

    from scripts.pilot.latency import evaluate_gate4, render_gate4_markdown

**What this is, and what it deliberately is not.** TRD §4 carries a full latency budget
and this repo holds zero measurements of it; `calls.latency` was DROPPED
(`f1a7c39d5be2`) rather than filled with pipeline timings that are not the caller's
experience. This module is what turns ten PSTN calls into evidence. It is a LEDGER,
a STATISTICS pass and a COMPARATOR — **it is not a robot that measures latency**, and
the distinction is the whole design:

**Voice-to-voice latency cannot be measured from our side at all.** It is the interval
between the caller finishing a word and the caller hearing audio. Both ends of that
interval exist on the PSTN leg, in the caller's ear; our stack is not in the audio path
at all (D-25: in v1 the engine hosts the entire live call). No API we can call, and no
timestamp we can take, observes either end. So:

| Quantity                        | How it is obtained          | Automatic? |
|---------------------------------|-----------------------------|------------|
| voice-to-voice turn latency     | human with a stopwatch, or  | **NO**     |
|                                 | offset analysis of a        | NO (needs  |
|                                 | dual-channel recording      | the audio) |
| first-greeting delay after pickup| same two routes            | **NO**     |
| `latency_data` per component    | one Get Execution call      | **YES**    |
| the arithmetic, the statistics, | this module                 | YES        |
| the agreement test, the verdict |                             |            |

A tool that pretended otherwise would be worse than a notebook, because its output
would be believed. So the human numbers are TYPED IN, every sample carries the method
that produced it, and the rendered report prints the method counts before it prints a
single millisecond.

**First-greeting delay is a separate ledger** (`GreetingSample`), never folded into the
turn samples: OPERATIONS §2 gate 4 is explicit that cold start hides there, and mixing a
one-per-call cold-start number into a many-per-call warm-turn distribution would move
the p50 by an amount nobody could later separate out.

**The vendor comparison is the gate's most interesting output.** Bolna documents
`latency_data` on Get Execution — `time_to_first_audio` plus per-component
transcriber/llm/synthesizer blocks (bolna.ai/docs/concepts/call-latencies, read Aug 2026;
first-party domains are egress-blocked from this environment, so the field names below
come from that page as surfaced in search and are UNVERIFIED against a live account).
Those numbers are a DIFFERENT quantity from voice-to-voice turn latency: turning them
into one requires OUR arithmetic aligning three components on the same turn. Whether the
result agrees with a stopwatch is a first-class finding either way — an agreement makes
the vendor field usable for continuous monitoring after the pilot; a disagreement kills
that idea and is worth more than the ten calls cost.

**`transcriber.turns[].turn_latency[].text` carries recognised CALLER SPEECH.** Hard
rules 5 and 6 apply to wherever it lands, and a pilot artefact committed to
`docs/evidence/` that quotes a caller is a permanent leak in a public-ish repo. So this
module NEVER retains text: `parse_latency_data` reads timings and drops text without
storing it, `redact_latency_data` produces the fixture-safe payload (shape preserved,
text replaced by its length), and `unredacted_text_paths` is the refusal — the runner is
expected to call it and refuse to write a fixture that still trips it. The rejected
alternative was "redact on write": that leaves the raw text alive in memory and in any
traceback along the way, and one `--debug` flag later it is in a log.

**Statistics, honestly (§ `summarize_samples`).** Ten samples support a median and do
not support a p95. That is not a stylistic preference, it is arithmetic — see the
docstrings of `median_confidence_interval` and `evaluate_tail`. The repo already has a
position on unearned numbers (`after_hours_basis` in `apps/api/crm/service.py`,
`CallVolume.basis` in `apps/api/admin/health.py`): a number that is a guess must say so
in a field, not in a comment. Every summary here therefore carries a `basis`, nothing
prints a percentile the sample cannot support, and no statistic is printed finer than
`REPORT_PRECISION_MS`.

**Absent is absent.** A component the payload did not carry is `None`, never `0`, and a
turn missing any component yields no vendor sum at all rather than a partial one. The
entire value of this slice is that its output can be trusted as evidence.

**FINDING — the storage shape `latency_data` would justify** is recorded in
`STORAGE_SHAPE_FINDING` at the bottom of this file. It is a finding, not a migration.

**FINDING — engine isolation (hard rule 2).** This module reads a VENDOR payload shape,
which in product code would belong only in `apps/api/engine/`. It lives here because the
shape is exactly what gate 4 exists to learn: `ExecutionSnapshot` has no `latency_data`
field and no raw-payload ref, so the payload cannot reach us through the adapter contract
at all today. The reader below is therefore deliberately shape-TOLERANT (it walks for
known keys and tolerates their absence) rather than a typed mapping that would encode an
unverified claim as truth, and it is pilot-scoped: the durable home for a verified reader
is `apps/api/engine/bolna.py`, and moving it there is part of what gate 4's result buys.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- vocabulary ---------------------------------------------------------------

#: How a millisecond figure came to exist. Printed beside every distribution, because
#: "measured" means three very different things here and the reader must not have to
#: guess which one.
MeasurementMethod = Literal["stopwatch_human", "recording_analysis", "vendor_reported"]

#: PASS/FAIL/NOT RUN, plus the one the gate actually lands on at n=10.
#:
#: **Why a fourth value exists.** D-31 makes gate 4 a HARD gate: a red reopens the engine
#: decision. Folding "we do not have enough samples to confirm the p95" into FAIL would
#: reopen the engine decision on a sample-size artefact rather than on evidence; folding
#: it into NOT RUN would erase ten real calls. INCONCLUSIVE is neither, and nothing in
#: this module or its rendering ever lets it read as green — `PASSING_VERDICTS` is the
#: single place that decides what counts as passed.
Verdict = Literal["PASS", "FAIL", "INCONCLUSIVE", "NOT RUN"]

PASSING_VERDICTS: frozenset[str] = frozenset({"PASS"})

#: Why a `basis` at all: `after_hours_basis` (crm/service.py) and `CallVolume.basis`
#: (admin/health.py) set the precedent — a number that is not entitled to be read as a
#: measurement says so in a field, not in a comment a dashboard author will not read.
SummaryBasis = Literal["measured", "insufficient_samples", "not_run"]

AgreementVerdict = Literal["agrees", "disagrees", "not_comparable"]

# TRD §4 / OPERATIONS §2 gate 4. Targets, not measurements — they are the thresholds a
# measurement is judged against and are never copied into a result.
TARGET_P50_MS = 1_100
TARGET_TAIL_MS = 1_800
TARGET_TAIL_FRACTION = 0.05  # "p95 ≤ 1.8s" == "at most 5% of turns exceed 1.8s"

#: One-sided confidence for every bound in this module.
ALPHA = 0.05

#: Nothing prints finer than this. Ten stopwatch samples do not resolve a millisecond,
#: and a report that says "1,143ms" invites a comparison at a precision the instrument
#: never had.
REPORT_PRECISION_MS = 10

#: The comparator's tolerance is the INSTRUMENT's floor, not a taste. Simple auditory
#: reaction time in adults is ~160-230ms and a hand-operated stopwatch adds the
#: experimenter's own reaction at both ends, so a tolerance tighter than that would
#: manufacture disagreements out of the measurer's nervous system. Recording analysis
#: has no human in the loop; its floor is the frame size of whatever VAD produced the
#: offsets, taken here as 100ms.
TOLERANCE_MS_BY_METHOD: dict[MeasurementMethod, int] = {
    "stopwatch_human": 250,
    "recording_analysis": 100,
    "vendor_reported": 0,
}


# --- samples (the ledger) ------------------------------------------------------


class TurnLatencySample(BaseModel):
    """One voice-to-voice observation: caller stopped speaking → caller heard audio.

    `call_ref` is OUR opaque pilot label (`pilot-03`) or an engine execution id — never
    a phone number, and nothing here holds one (hard rule 6).
    """

    call_ref: str
    turn_index: int
    voice_to_voice_ms: int = Field(gt=0)
    method: MeasurementMethod
    note: str | None = None


class GreetingSample(BaseModel):
    """First-greeting delay after pickup, kept in its own ledger (see module docstring)."""

    call_ref: str
    greeting_delay_ms: int = Field(gt=0)
    method: MeasurementMethod
    note: str | None = None


# --- the vendor payload --------------------------------------------------------

#: Keys whose VALUE is free text recognised from the caller. Anything landing here is
#: hard-rule-5/6 material. Kept as a set rather than a single key because the payload is
#: unverified: if a live account returns `transcript` or `utterance` instead of `text`,
#: the redactor must still catch it rather than pass it through because it did not match
#: the one name the docs happened to show.
FREE_TEXT_KEYS: frozenset[str] = frozenset(
    {"text", "transcript", "utterance", "words", "content", "message"}
)

_REDACTED_MARKER = "<redacted"


def _scrub_string(value: str) -> str:
    """Scrub a payload string of anything personal, keeping ids and region names.

    Delegates to `scripts.pilot.redact.scrub_text` — ONE way per problem. It is the
    harness's exit guard and already carries the pipeline's validated
    phone/Aadhaar/PAN/UPI logic plus a free-standing 7+-digit sweep, with the lookarounds
    that stop an engine id like `fakecall_ee4edcaa460007891` being masked as a phone
    number. A second regex here would be a second answer, and the weaker one.
    """
    from scripts.pilot.redact import scrub_text

    return scrub_text(value)[0]


def redact_latency_data(raw: Any) -> Any:
    """Return the payload with every free-text value replaced by its LENGTH.

    Shape is preserved exactly — the point of the fixture is the shape — but no caller
    utterance survives. `{"text": "hello who is there"}` becomes
    `{"text": "<redacted len=18>"}`.

    The rejected alternative was dropping the key. That loses the evidence that the
    field exists and is populated, which is precisely what the next reader needs in
    order to decide it must never be mapped into a typed column.
    """
    if isinstance(raw, Mapping):
        out: dict[str, Any] = {}
        for key, value in raw.items():
            if str(key).lower() in FREE_TEXT_KEYS and isinstance(value, str):
                out[str(key)] = f"{_REDACTED_MARKER} len={len(value)}>"
            else:
                out[str(key)] = redact_latency_data(value)
        return out
    if isinstance(raw, list | tuple):
        return [redact_latency_data(item) for item in raw]
    if isinstance(raw, str):
        return _scrub_string(raw)
    return raw


def unredacted_text_paths(raw: Any, *, _path: str = "$") -> list[str]:
    """JSON paths still holding free text or a phone-shaped digit run.

    The runner calls this before writing anything to `docs/evidence/` and REFUSES on a
    non-empty result. A leak in a committed artefact is permanent; a refused write is a
    minute of someone's day.
    """
    found: list[str] = []
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            child = f"{_path}.{key}"
            if str(key).lower() in FREE_TEXT_KEYS and isinstance(value, str):
                if not value.startswith(_REDACTED_MARKER):
                    found.append(child)
                continue
            found.extend(unredacted_text_paths(value, _path=child))
    elif isinstance(raw, list | tuple):
        for i, item in enumerate(raw):
            found.extend(unredacted_text_paths(item, _path=f"{_path}[{i}]"))
    elif isinstance(raw, str) and _scrub_string(raw) != raw:
        found.append(_path)
    return found


class VendorTurnLatency(BaseModel):
    """Per-turn components as the vendor reports them. Every field may be absent.

    Units: the documented examples are integers that read as MILLISECONDS
    (`time_to_first_token: 599`), except `audio_to_text_latency: 20.12`, whose
    magnitude does not read as a millisecond transcription latency at all. The unit is
    therefore UNVERIFIED per field — `units_note` carries that forward into the report
    rather than letting an arithmetic sum quietly mix seconds with milliseconds.
    """

    turn: int
    transcriber_ms: float | None = None
    llm_ttft_ms: float | None = None
    tts_ttft_ms: float | None = None

    @property
    def component_sum_ms(self) -> float | None:
        """STT + LLM TTFT + TTS TTFA, or NOTHING.

        A partial sum is not a smaller latency, it is a different quantity wearing the
        same name — so a turn missing any leg contributes to no comparison at all.
        """
        parts = (self.transcriber_ms, self.llm_ttft_ms, self.tts_ttft_ms)
        if any(p is None for p in parts):
            return None
        return math.fsum(p for p in parts if p is not None)


class VendorCallLatency(BaseModel):
    """`latency_data` for one execution, timings only — never text."""

    call_ref: str
    time_to_first_audio_ms: float | None = None
    region: str | None = None
    turns: list[VendorTurnLatency] = Field(default_factory=list)
    #: Everything the reader could not make sense of. An unparsed payload must announce
    #: itself; silently returning an empty object would read as "the vendor reported
    #: nothing", which is a different and much more interesting result.
    warnings: list[str] = Field(default_factory=list)
    units_note: str = (
        "Units UNVERIFIED. Documented examples read as ms for llm/synthesizer "
        "time_to_first_token and for time_to_connect; transcriber.audio_to_text_latency "
        "is shown as 20.12, which does not read as ms. Confirm on the live account "
        "before any sum below is believed."
    )

    @property
    def turns_by_index(self) -> dict[int, VendorTurnLatency]:
        return {t.turn: t for t in self.turns}


def _as_float(value: Any) -> float | None:
    """Absent, non-numeric and boolean all mean ABSENT — never 0."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _first_turn_value(entry: Any, keys: Sequence[str]) -> float | None:
    """Read the first present key from a turn entry, tolerating the nested list form.

    The transcriber block nests a `turn_latency` LIST per turn (one entry per
    incremental refinement of the same utterance). The LAST sequence is the one the
    orchestrator acted on, so that is the one taken — the earlier ones are guesses the
    recogniser itself revised.
    """
    if not isinstance(entry, Mapping):
        return None
    for key in keys:
        direct = _as_float(entry.get(key))
        if direct is not None:
            return direct
    nested = entry.get("turn_latency")
    if isinstance(nested, list) and nested:
        last = nested[-1]
        if isinstance(last, Mapping):
            for key in keys:
                value = _as_float(last.get(key))
                if value is not None:
                    return value
    return None


def _turn_number(entry: Any, fallback: int) -> int:
    if isinstance(entry, Mapping):
        raw = entry.get("turn")
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
    return fallback


def parse_latency_data(raw: Mapping[str, Any], *, call_ref: str) -> VendorCallLatency:
    """Read timings out of `latency_data`. Text is dropped, never stored.

    Shape-tolerant by design (see the engine-isolation finding in the module docstring):
    every block is optional, an unrecognised block becomes a warning rather than an
    exception, and a missing number stays `None`. On the day, a payload that fails to
    parse must still leave the ten calls' stopwatch evidence intact.
    """
    warnings: list[str] = []
    ttfa = _as_float(raw.get("time_to_first_audio"))
    if ttfa is None and "time_to_first_audio" in raw:
        warnings.append("time_to_first_audio present but not numeric")

    region_raw = raw.get("region")
    region = _scrub_string(region_raw) if isinstance(region_raw, str) else None

    per_turn: dict[int, dict[str, float | None]] = {}
    blocks: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("transcriber", "transcriber_ms", ("audio_to_text_latency",)),
        ("llm", "llm_ttft_ms", ("time_to_first_token",)),
        ("synthesizer", "tts_ttft_ms", ("time_to_first_token",)),
    )
    for block_name, field, keys in blocks:
        block = raw.get(block_name)
        if block is None:
            warnings.append(f"{block_name} block absent")
            continue
        if not isinstance(block, Mapping):
            warnings.append(f"{block_name} block is not an object")
            continue
        turns = block.get("turns")
        if not isinstance(turns, list):
            warnings.append(f"{block_name}.turns absent or not a list")
            continue
        for i, entry in enumerate(turns, start=1):
            number = _turn_number(entry, i)
            per_turn.setdefault(number, {})[field] = _first_turn_value(entry, keys)

    parsed = [
        VendorTurnLatency(
            turn=number,
            transcriber_ms=fields.get("transcriber_ms"),
            llm_ttft_ms=fields.get("llm_ttft_ms"),
            tts_ttft_ms=fields.get("tts_ttft_ms"),
        )
        for number, fields in sorted(per_turn.items())
    ]
    return VendorCallLatency(
        call_ref=call_ref,
        time_to_first_audio_ms=ttfa,
        region=region,
        turns=parsed,
        warnings=warnings,
    )


# --- statistics ----------------------------------------------------------------


def _binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X ≤ k) for X ~ Bin(n, p). Exact — n is ten, not ten million."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return math.fsum(math.comb(n, i) * p**i * (1.0 - p) ** (n - i) for i in range(k + 1))


def _bisect(fn: Any, target: float, *, increasing: bool) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        value = fn(mid)
        if (value < target) == increasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def clopper_pearson_upper(k: int, n: int, alpha: float = ALPHA) -> float:
    """One-sided upper bound on the true exceedance probability (exact, Clopper-Pearson).

    Exact binomial rather than a normal approximation: at n=10 with k=0 the normal
    interval is [0, 0] — it would report certainty from ten calls, which is the exact
    failure mode this slice exists to avoid.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    if k >= n:
        return 1.0
    return _bisect(lambda p: _binomial_cdf(k, n, p), alpha, increasing=False)


def clopper_pearson_lower(k: int, n: int, alpha: float = ALPHA) -> float:
    """One-sided lower bound on the true exceedance probability (exact)."""
    if n <= 0:
        raise ValueError("n must be positive")
    if k <= 0:
        return 0.0
    return _bisect(lambda p: 1.0 - _binomial_cdf(k - 1, n, p), alpha, increasing=True)


class MedianInterval(BaseModel):
    low_ms: int
    high_ms: int
    #: The ACTUAL coverage of the order-statistic interval, not the requested one.
    #: Order statistics are discrete, so a "95%" interval is really 97.85% at n=10 —
    #: printing the requested figure would be a rounder lie than printing the true one.
    coverage: float
    low_order_stat: int
    high_order_stat: int


#: Two-sided coverage the median interval must reach. 0.95, not `1 - 2*ALPHA`: the
#: interval is two-sided and both tails are already in the construction below, so
#: doubling alpha a second time would quietly report a 90% interval as a 95% one.
MEDIAN_MIN_COVERAGE = 0.95


def median_confidence_interval(
    sorted_ms: Sequence[int], *, min_coverage: float = MEDIAN_MIN_COVERAGE
) -> MedianInterval | None:
    """Distribution-free CI for the MEDIAN from order statistics.

    The count of samples below the true median is Bin(n, 0.5) whatever the underlying
    distribution, so [x(k), x(n+1-k)] covers the median with probability
    1 - 2*P(Bin(n,0.5) ≤ k-1) — no normality, no bootstrap, no minimum n beyond the one
    the arithmetic itself imposes. At n=10 the tightest interval reaching 95% is
    [x(2), x(9)] at 97.85%. Returns None when no interval reaches `min_coverage`
    (n ≤ 5), which is a refusal, not a zero.

    Method per the standard order-statistic construction (AFIT STAT COE, "Confidence
    Intervals for the Median and Other Percentiles"); the bootstrap alternative was
    rejected because the literature puts its usable floor at n ≳ 60 and it would import
    a resampling dependency to produce a shakier interval than exact binomial gives.
    """
    n = len(sorted_ms)
    best: MedianInterval | None = None
    for k in range(1, n // 2 + 1):
        coverage = 1.0 - 2.0 * _binomial_cdf(k - 1, n, 0.5)
        if coverage >= min_coverage:
            best = MedianInterval(
                low_ms=_round_ms(sorted_ms[k - 1]),
                high_ms=_round_ms(sorted_ms[n - k]),
                coverage=coverage,
                low_order_stat=k,
                high_order_stat=n - k + 1,
            )
        else:
            break
    return best


def _round_ms(value: float) -> int:
    return int(round(value / REPORT_PRECISION_MS) * REPORT_PRECISION_MS)


class SampleSummary(BaseModel):
    """A distribution, with a `basis` saying what it is entitled to claim."""

    n: int
    basis: SummaryBasis
    median_ms: int | None = None
    median_ci: MedianInterval | None = None
    min_ms: int | None = None
    max_ms: int | None = None
    method_counts: dict[str, int] = Field(default_factory=dict)
    #: Written out so a reader cannot take the median for a mean or the max for a p95.
    note: str = ""


#: Fewer than this and even the median has no distribution-free interval (n ≤ 5 cannot
#: reach 95% coverage on any order-statistic pair).
MIN_SAMPLES_FOR_MEDIAN_CI = 6


def summarize_samples(values_ms: Sequence[int], methods: Sequence[str] = ()) -> SampleSummary:
    """Median + its exact interval + extremes. No mean, and no percentile.

    **No mean**: one 6-second call in ten moves a mean by 500ms and moves a median not
    at all, and the failure this gate is hunting (a cold start, a retry, one bad turn)
    is exactly that shape.

    **No percentile beyond the median** — see `evaluate_tail` for the arithmetic.
    """
    counts: dict[str, int] = {}
    for method in methods:
        counts[method] = counts.get(method, 0) + 1
    n = len(values_ms)
    if n == 0:
        return SampleSummary(
            n=0,
            basis="not_run",
            method_counts=counts,
            note="NOT RUN — no samples were recorded.",
        )
    ordered = sorted(values_ms)
    ci = median_confidence_interval(ordered) if n >= MIN_SAMPLES_FOR_MEDIAN_CI else None
    mid = (
        ordered[n // 2] if n % 2 else int(round((ordered[n // 2 - 1] + ordered[n // 2]) / 2))  # noqa: RUF046
    )
    basis: SummaryBasis = "measured" if ci is not None else "insufficient_samples"
    note = (
        f"Median over {n} samples, distribution-free interval at "
        f"{ci.coverage * 100:.1f}% from order statistics x({ci.low_order_stat}), "
        f"x({ci.high_order_stat})."
        if ci is not None
        else f"{n} samples: too few for a distribution-free interval on the median "
        f"(needs ≥ {MIN_SAMPLES_FOR_MEDIAN_CI}). The median below is a point with no "
        f"stated precision."
    )
    return SampleSummary(
        n=n,
        basis=basis,
        median_ms=_round_ms(mid),
        median_ci=ci,
        min_ms=_round_ms(ordered[0]),
        max_ms=_round_ms(ordered[-1]),
        method_counts=counts,
        note=note,
    )


class TailFinding(BaseModel):
    """What ten samples can say about "p95 ≤ 1.8s" — which is less than it sounds.

    "p95 ≤ T" is exactly "P(latency > T) ≤ 5%". That is a claim about a proportion, so
    the honest instrument is an exact binomial bound on the exceedance count, not an
    interpolated 95th order statistic (at n=10 the "p95" of any interpolation formula is
    a function of the top one or two samples, i.e. of the worst call and nothing else).

    The asymmetry is the finding: with zero exceedances in ten, the 95% upper bound on
    the true exceedance rate is 25.9% — five times the criterion — so **ten calls cannot
    CONFIRM the p95 leg of gate 4**. They can REFUTE it: enough exceedances push the 95%
    LOWER bound above 5% and the target is beaten on its own terms. Confirming at 95%
    confidence with zero exceedances needs 0.95^n ≤ 0.05, i.e. **n ≥ 59** — which is the
    number to take to whoever wrote "10 PSTN calls" if a confirmed p95 is wanted.
    """

    threshold_ms: int
    target_fraction: float
    n: int
    exceedances: int
    exceedance_upper_95: float | None = None
    exceedance_lower_95: float | None = None
    verdict: Verdict
    samples_needed_to_confirm: int | None = None
    note: str = ""


def samples_needed_to_confirm(fraction: float = TARGET_TAIL_FRACTION, alpha: float = ALPHA) -> int:
    """Smallest n whose ZERO-exceedance run confirms `P(exceed) ≤ fraction`.

    (1 - fraction)^n ≤ alpha. At 5% and 95% confidence this is 59 — the classic
    "rule of three" neighbourhood, and the reason gate 4's own sample size cannot
    confirm gate 4's own p95 criterion.
    """
    return math.ceil(math.log(alpha) / math.log(1.0 - fraction))


def evaluate_tail(
    values_ms: Sequence[int],
    *,
    threshold_ms: int = TARGET_TAIL_MS,
    fraction: float = TARGET_TAIL_FRACTION,
) -> TailFinding:
    n = len(values_ms)
    needed = samples_needed_to_confirm(fraction)
    if n == 0:
        return TailFinding(
            threshold_ms=threshold_ms,
            target_fraction=fraction,
            n=0,
            exceedances=0,
            verdict="NOT RUN",
            samples_needed_to_confirm=needed,
            note="NOT RUN — no samples were recorded. This is not a pass.",
        )
    k = sum(1 for v in values_ms if v > threshold_ms)
    upper = clopper_pearson_upper(k, n)
    lower = clopper_pearson_lower(k, n)
    if lower > fraction:
        verdict: Verdict = "FAIL"
        note = (
            f"REFUTED: {k}/{n} turns exceeded {threshold_ms}ms, so the true exceedance "
            f"rate is at least {lower * 100:.1f}% at 95% confidence — above the "
            f"{fraction * 100:.0f}% the target allows."
        )
    elif upper <= fraction:
        verdict = "PASS"
        note = (
            f"CONFIRMED: {k}/{n} exceeded; the true exceedance rate is at most "
            f"{upper * 100:.1f}% at 95% confidence."
        )
    else:
        verdict = "INCONCLUSIVE"
        note = (
            f"{k}/{n} turns exceeded {threshold_ms}ms. Not a pass and not a failure: "
            f"the true exceedance rate is bounded only at {upper * 100:.1f}% (95% "
            f"confidence), against a {fraction * 100:.0f}% criterion. Confirming it "
            f"needs ≥ {needed} clean samples."
        )
    return TailFinding(
        threshold_ms=threshold_ms,
        target_fraction=fraction,
        n=n,
        exceedances=k,
        exceedance_upper_95=upper,
        exceedance_lower_95=lower,
        verdict=verdict,
        samples_needed_to_confirm=needed,
        note=note,
    )


def evaluate_median_against(summary: SampleSummary, *, threshold_ms: int) -> Verdict:
    """PASS only when the whole interval sits under the target.

    Comparing the point median to the threshold would call 1,090ms a pass on an interval
    running to 1,600ms. The mirror rule makes FAIL equally hard to reach: the whole
    interval must sit above.
    """
    if summary.n == 0:
        return "NOT RUN"
    if summary.median_ci is None:
        return "INCONCLUSIVE"
    if summary.median_ci.high_ms <= threshold_ms:
        return "PASS"
    if summary.median_ci.low_ms > threshold_ms:
        return "FAIL"
    return "INCONCLUSIVE"


# --- the vendor/stopwatch comparison -------------------------------------------


class TurnComparison(BaseModel):
    call_ref: str
    turn_index: int
    measured_ms: int
    vendor_ms: float
    delta_ms: float  # vendor - measured; negative = vendor claims to be faster
    tolerance_ms: int
    agrees: bool


class AgreementFinding(BaseModel):
    """Does the vendor's self-reported latency match a stopwatch? Either answer is a result."""

    what: str
    verdict: AgreementVerdict
    comparisons: list[TurnComparison] = Field(default_factory=list)
    median_delta_ms: int | None = None
    note: str = ""


def _agreement(what: str, comparisons: list[TurnComparison], why_empty: str) -> AgreementFinding:
    if not comparisons:
        return AgreementFinding(what=what, verdict="not_comparable", note=why_empty)
    deltas = sorted(c.delta_ms for c in comparisons)
    n = len(deltas)
    median_delta = deltas[n // 2] if n % 2 else (deltas[n // 2 - 1] + deltas[n // 2]) / 2.0
    disagreeing = [c for c in comparisons if not c.agrees]
    if disagreeing:
        return AgreementFinding(
            what=what,
            verdict="disagrees",
            comparisons=comparisons,
            median_delta_ms=_round_ms(median_delta),
            note=(
                f"DISAGREES on {len(disagreeing)}/{n} comparable pairs. Median signed "
                f"delta {_round_ms(median_delta)}ms (vendor - measured; negative means "
                f"the vendor reports itself faster than the caller experienced). The "
                f"vendor field cannot stand in for a stopwatch."
            ),
        )
    return AgreementFinding(
        what=what,
        verdict="agrees",
        comparisons=comparisons,
        median_delta_ms=_round_ms(median_delta),
        note=(
            f"AGREES on all {n} comparable pairs within the instrument's own tolerance; "
            f"median signed delta {_round_ms(median_delta)}ms. On this evidence the "
            f"vendor field is usable for CONTINUOUS monitoring after the pilot — which "
            f"is the only way we would ever have per-call latency at scale."
        ),
    )


def compare_turn_latency(
    samples: Iterable[TurnLatencySample],
    vendor: Mapping[str, VendorCallLatency],
) -> AgreementFinding:
    """Stopwatch turn latency vs the vendor's three components summed.

    Only pairs where BOTH exist are compared, and a turn missing any vendor component is
    not comparable at all (`component_sum_ms` returns None) — pairing a stopwatch number
    against a two-of-three sum would manufacture a disagreement out of a missing field.
    """
    comparisons: list[TurnComparison] = []
    for sample in samples:
        call = vendor.get(sample.call_ref)
        if call is None:
            continue
        turn = call.turns_by_index.get(sample.turn_index)
        if turn is None:
            continue
        total = turn.component_sum_ms
        if total is None:
            continue
        tolerance = TOLERANCE_MS_BY_METHOD[sample.method]
        delta = total - sample.voice_to_voice_ms
        comparisons.append(
            TurnComparison(
                call_ref=sample.call_ref,
                turn_index=sample.turn_index,
                measured_ms=sample.voice_to_voice_ms,
                vendor_ms=total,
                delta_ms=delta,
                tolerance_ms=tolerance,
                agrees=abs(delta) <= tolerance,
            )
        )
    return _agreement(
        "voice-to-voice turn latency vs summed latency_data components",
        comparisons,
        why_empty=(
            "NOT COMPARABLE — no turn had both a measured sample and a complete "
            "transcriber+llm+synthesizer triple. Record this as an outcome of gate 4: "
            "an incomplete latency_data is itself the answer to whether it can replace "
            "a stopwatch."
        ),
    )


def compare_greeting_latency(
    samples: Iterable[GreetingSample],
    vendor: Mapping[str, VendorCallLatency],
) -> AgreementFinding:
    """First-greeting delay vs `time_to_first_audio`.

    ASSUMPTION, to be confirmed on the live account: `time_to_first_audio` is
    call-level — "how long the caller waits before hearing the agent speak" — which
    makes it the greeting number, not a per-turn number. If the live payload shows one
    per turn, this comparison is the one that has to change, not the turn comparison.
    """
    comparisons: list[TurnComparison] = []
    for sample in samples:
        call = vendor.get(sample.call_ref)
        if call is None or call.time_to_first_audio_ms is None:
            continue
        tolerance = TOLERANCE_MS_BY_METHOD[sample.method]
        delta = call.time_to_first_audio_ms - sample.greeting_delay_ms
        comparisons.append(
            TurnComparison(
                call_ref=sample.call_ref,
                turn_index=0,
                measured_ms=sample.greeting_delay_ms,
                vendor_ms=call.time_to_first_audio_ms,
                delta_ms=delta,
                tolerance_ms=tolerance,
                agrees=abs(delta) <= tolerance,
            )
        )
    return _agreement(
        "first-greeting delay vs latency_data.time_to_first_audio",
        comparisons,
        why_empty=(
            "NOT COMPARABLE — no call had both a measured greeting delay and a time_to_first_audio."
        ),
    )


# --- the gate ------------------------------------------------------------------


class Gate4Result(BaseModel):
    verdict: Verdict
    calls_observed: int
    turn_summary: SampleSummary
    greeting_summary: SampleSummary
    median_verdict: Verdict
    tail: TailFinding
    turn_agreement: AgreementFinding
    greeting_agreement: AgreementFinding
    vendor_warnings: dict[str, list[str]] = Field(default_factory=dict)
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict in PASSING_VERDICTS


def evaluate_gate4(
    turn_samples: Sequence[TurnLatencySample],
    greeting_samples: Sequence[GreetingSample] = (),
    vendor: Mapping[str, VendorCallLatency] | None = None,
    *,
    target_p50_ms: int = TARGET_P50_MS,
    target_tail_ms: int = TARGET_TAIL_MS,
) -> Gate4Result:
    """The whole gate. Pure — it takes evidence and returns a verdict, nothing else.

    Being pure is what makes it testable in the normal suite, which matters more here
    than anywhere else in the repo: this harness gets ONE chance, on a day when the
    founder is on a phone with a stopwatch and cannot debug it.
    """
    vendor = dict(vendor or {})
    turn_summary = summarize_samples(
        [s.voice_to_voice_ms for s in turn_samples], [s.method for s in turn_samples]
    )
    greeting_summary = summarize_samples(
        [s.greeting_delay_ms for s in greeting_samples], [s.method for s in greeting_samples]
    )
    tail = evaluate_tail([s.voice_to_voice_ms for s in turn_samples], threshold_ms=target_tail_ms)
    median_verdict = evaluate_median_against(turn_summary, threshold_ms=target_p50_ms)

    legs = (median_verdict, tail.verdict)
    if not turn_samples:
        verdict: Verdict = "NOT RUN"
        note = (
            "NOT RUN — gate 4 recorded no voice-to-voice samples. This is NOT a pass "
            "and must never be rendered as one."
        )
    elif "FAIL" in legs:
        verdict = "FAIL"
        note = "FAIL — at least one leg of the gate was refuted by the measurements."
    elif all(leg == "PASS" for leg in legs):
        verdict = "PASS"
        note = "PASS — both legs confirmed against their targets."
    else:
        verdict = "INCONCLUSIVE"
        note = (
            "INCONCLUSIVE — measured, not refuted, not confirmed. At ten calls this is "
            "the expected landing: the p50 leg is answerable and the p95 leg is not "
            "(see the tail finding). Not a pass; do not record it as one."
        )

    return Gate4Result(
        verdict=verdict,
        calls_observed=len(
            {s.call_ref for s in turn_samples} | {s.call_ref for s in greeting_samples}
        ),
        turn_summary=turn_summary,
        greeting_summary=greeting_summary,
        median_verdict=median_verdict,
        tail=tail,
        turn_agreement=compare_turn_latency(turn_samples, vendor),
        greeting_agreement=compare_greeting_latency(greeting_samples, vendor),
        vendor_warnings={ref: call.warnings for ref, call in vendor.items() if call.warnings},
        note=note,
    )


def _summary_lines(title: str, summary: SampleSummary, *, threshold_ms: int | None) -> list[str]:
    lines = [f"### {title}", ""]
    if summary.n == 0:
        lines += ["**NOT RUN** — no samples recorded.", ""]
        return lines
    methods = ", ".join(f"{k}={v}" for k, v in sorted(summary.method_counts.items())) or "unstated"
    lines += [
        f"- samples: **{summary.n}** (method: {methods})",
        f"- basis: **{summary.basis}**",
        f"- median: **{summary.median_ms} ms**"
        + (f" (target ≤ {threshold_ms} ms)" if threshold_ms is not None else ""),
    ]
    if summary.median_ci is not None:
        ci = summary.median_ci
        lines.append(
            f"- median {ci.coverage * 100:.1f}% interval: **{ci.low_ms}-{ci.high_ms} ms** "
            f"(order statistics x({ci.low_order_stat}), x({ci.high_order_stat}))"
        )
    lines += [
        f"- range: {summary.min_ms}-{summary.max_ms} ms",
        f"- {summary.note}",
        "",
    ]
    return lines


def render_gate4_markdown(result: Gate4Result) -> str:
    """The scorecard block, for `docs/evidence/bolna-pilot-scorecard.md`.

    Contains no phone number, no transcript text and no caller utterance — everything it
    can print came out of the typed models above, and those hold timings and opaque
    call refs only. That is a property of the pipeline, not of this function's care.
    """
    lines: list[str] = [
        "## Gate 4 — real-call latency (OPERATIONS §2)",
        "",
        f"**VERDICT: {result.verdict}**",
        "",
        result.note,
        "",
        "How these numbers were obtained — read this before the numbers:",
        "",
        "- voice-to-voice turn latency and first-greeting delay are **NOT measurable "
        "from our side**; both ends of the interval are on the caller's PSTN leg. They "
        "are a human with a stopwatch, or offsets read off a recording, typed in.",
        "- `latency_data` is the only automatic capture here, and it is a **different "
        "quantity** — the comparison below is what says whether it can stand in.",
        "",
    ]
    lines += _summary_lines(
        "Voice-to-voice turn latency", result.turn_summary, threshold_ms=TARGET_P50_MS
    )
    lines += [f"- median leg vs target: **{result.median_verdict}**", ""]
    lines += _summary_lines(
        "First-greeting delay after pickup (kept separate — cold start hides here)",
        result.greeting_summary,
        threshold_ms=None,
    )
    lines += [
        f'### Tail — the "p95 ≤ {result.tail.threshold_ms} ms" leg',
        "",
        f"**{result.tail.verdict}** — {result.tail.note}",
        "",
        "### Vendor-reported vs measured",
        "",
    ]
    for finding in (result.turn_agreement, result.greeting_agreement):
        lines += [f"- **{finding.what}: {finding.verdict.upper()}** — {finding.note}"]
    lines.append("")
    if result.vendor_warnings:
        lines += ["### latency_data parse warnings", ""]
        lines += [f"- `{ref}`: {'; '.join(w)}" for ref, w in sorted(result.vendor_warnings.items())]
        lines.append("")
    return "\n".join(lines)


# --- findings ------------------------------------------------------------------

#: FINDING for TRD §4 / DATA-MODEL — the storage shape the payload would justify.
#: Deliberately prose and deliberately NOT a migration: TRD §4 says the shape gets
#: chosen from the payload we actually receive, and we have not received one yet.
STORAGE_SHAPE_FINDING = """
`calls.latency` was dropped (f1a7c39d5be2) because a column that always reads NULL is
worse than none. What the gate-4 payload would justify re-opening, IF the capture
succeeds and the agreement finding is 'agrees':

1. NOT a JSONB column on `calls`. The payload is per-TURN and unbounded in length; a
   40-minute call carries hundreds of turn entries, and one of the three blocks carries
   recognised caller TEXT. A JSONB blob on the call row would put unredactable PII in a
   typed column with no `text_redacted` counterpart (hard rules 5/6) and would grow the
   hot row that every dashboard query reads.

2. The raw payload goes where every other raw vendor payload goes: object storage, by
   ref (hard rule 2). Redacted first — `redact_latency_data` above is the function, and
   `unredacted_text_paths` is the assertion that it worked.

3. What earns typed columns is the SMALL, per-call, text-free part, and only the fields
   the pilot proved are populated:
     calls.time_to_first_audio_ms  int null   -- greeting delay, vendor-reported
     calls.turn_latency_p50_ms     int null   -- our arithmetic over complete turns
     calls.turn_latency_max_ms     int null
     calls.turn_latency_n          int null   -- turns with a COMPLETE component triple
     calls.latency_source          text null  -- 'vendor_reported' | 'measured' | null
   `latency_n` is what stops the repeat of the dropped column: a p50 over 2 complete
   turns out of 300 is not a p50, and a reader with the count can see that. `null`
   remains legal and means ABSENT — but unlike `calls.latency`, absent is now the
   exception rather than every row.

4. Nothing above is worth building if the agreement finding is 'disagrees'. In that case
   the vendor numbers are pipeline timings that are not the caller's experience, which
   is the exact mistake f1a7c39d5be2 refused to institutionalise — and the correct
   outcome is a second stopwatch round, not a column.
"""


# --- wiring into the harness ---------------------------------------------------
#
# `scripts/pilot/runner.py` names this module in OPTIONAL_GATE_MODULES and picks up a
# `GATES: {number: runner}` mapping, with results in the shared PASS/FAIL/NOT RUN
# vocabulary of `scripts/pilot/results.py`. One way per problem: this slice keeps its own
# rich models because they carry the statistics, and projects them onto that vocabulary
# at the seam rather than inventing a second scorecard shape.

#: Where the human-entered observations live. The gate cannot measure them (see the
#: module docstring), so it READS them, and it reports NOT RUN with this path in the
#: reason when the file is absent — never a zero, never a pass.
OBSERVATIONS_ENV = "CALEVATE_PILOT_GATE4_OBSERVATIONS"
DEFAULT_OBSERVATIONS_PATH = "docs/evidence/gate4-observations.json"

#: FINDING, reported on every run of this gate: gate 4 asks for `latency_data` from Get
#: Execution, and our adapter contract still cannot deliver it HERE. `ExecutionSnapshot`
#: has no `latency_data` field, and the vendor's own document now reaches a worker only as
#: `raw_document` — opaque bytes for D-126's archive, whose whole design is that nothing
#: above the adapter reads a field out of it. Parsing one open in this harness to fish out
#: `latency_data` would be precisely the hard-rule-2 leak the bytes exist to prevent, and
#: `tests/engine_audit_test.py` fails the tree for it. So executing this half of the gate
#: still requires either an adapter change (a mapped field, after the shape is verified —
#: which is what the archive makes cheap: the document is now KEPT, so a real payload can
#: be read off a live call instead of guessed) or the operator pasting the raw Get
#: Execution `latency_data` into the observations file. The second is what this module
#: does, deliberately.
ADAPTER_FINDING = (
    "gate 4's latency_data capture cannot run through the VoiceEngine contract: "
    "ExecutionSnapshot carries no latency_data, and the raw document it now carries is "
    "opaque bytes for the archive that no caller above the adapter may parse — so the "
    "payload is pasted into the observations file by the operator. Mapping the field is a "
    "decision for after the shape is verified — see STORAGE_SHAPE_FINDING."
)

SMALL_N_FINDING = (
    "ten calls cannot CONFIRM the p95 leg: zero exceedances in ten bounds the true "
    "exceedance rate at 25.9% against a 5% criterion (exact binomial, 95% one-sided). "
    f"Confirming needs n >= {samples_needed_to_confirm()}. Ten calls CAN refute it, and "
    "CAN answer the p50 leg."
)

NOT_MEASURABLE_FINDING = (
    "voice-to-voice latency and first-greeting delay are not measurable from our side "
    "(both ends of the interval sit on the caller's PSTN leg; D-25 puts our stack outside "
    "the audio path). They are a stopwatch or a recording, typed in. Only latency_data is "
    "an automatic capture, and it is a different quantity."
)


class ObservationsError(ValueError):
    """The observations file exists but cannot be read as evidence.

    Raised rather than tolerated: a partially-parsed ledger would drop samples silently,
    and a gate that quietly measured six of ten calls is worse than one that refused.
    """


def load_gate4_observations(
    payload: Mapping[str, Any],
) -> tuple[list[TurnLatencySample], list[GreetingSample], dict[str, VendorCallLatency]]:
    """Parse the operator's ledger. Shape::

        {"calls": [{"call_ref": "<engine execution id>",
                    "greeting_delay_ms": 1200, "greeting_method": "stopwatch_human",
                    "turns": [{"turn_index": 1, "voice_to_voice_ms": 1100,
                               "method": "stopwatch_human"}],
                    "latency_data": { ... raw Get Execution latency_data ... }}]}

    `call_ref` is the engine execution id — never the number dialled (hard rule 6).
    `latency_data` may carry recognised caller text; it is read for timings here and
    never retained (`parse_latency_data`).
    """
    calls = payload.get("calls")
    if not isinstance(calls, list):
        raise ObservationsError("observations file has no 'calls' list")
    turns: list[TurnLatencySample] = []
    greetings: list[GreetingSample] = []
    vendor: dict[str, VendorCallLatency] = {}
    for entry in calls:
        if not isinstance(entry, Mapping):
            raise ObservationsError("every entry in 'calls' must be an object")
        ref = str(entry.get("call_ref") or "").strip()
        if not ref:
            raise ObservationsError("a call entry has no call_ref")
        for turn in entry.get("turns") or []:
            if not isinstance(turn, Mapping):
                raise ObservationsError(f"{ref}: 'turns' must hold objects")
            turns.append(
                TurnLatencySample(
                    call_ref=ref,
                    turn_index=int(turn["turn_index"]),
                    voice_to_voice_ms=int(turn["voice_to_voice_ms"]),
                    method=turn.get("method", "stopwatch_human"),
                    note=turn.get("note"),
                )
            )
        if entry.get("greeting_delay_ms") is not None:
            greetings.append(
                GreetingSample(
                    call_ref=ref,
                    greeting_delay_ms=int(entry["greeting_delay_ms"]),
                    method=entry.get("greeting_method", "stopwatch_human"),
                    note=entry.get("greeting_note"),
                )
            )
        raw = entry.get("latency_data")
        if isinstance(raw, Mapping):
            vendor[ref] = parse_latency_data(raw, call_ref=ref)
    return turns, greetings, vendor


#: How a statistical verdict lands in the shared three-state vocabulary.
#:
#: INCONCLUSIVE maps to `not_run` — with a reason — and that mapping is deliberate. The
#: shared vocabulary has three rungs on purpose ("NOT RUN is not PASS"), and of the three,
#: `not_run` is the only one that does not assert a fact we do not have: `pass` would
#: claim confirmation the sample cannot give, `fail` would reopen D-31's engine decision
#: on a sample-size artefact. The reason string carries what WAS measured, so nothing is
#: lost except a green tick nobody earned.
def _leg_check(name: str, verdict: Verdict, detail: str, **measurements: int | float) -> Any:
    from scripts.pilot.results import failed, not_run, passed

    if verdict == "PASS":
        return passed(name, detail, **measurements)
    if verdict == "FAIL":
        return failed(name, detail, **measurements)
    return not_run(name, detail, **measurements)


def gate4_result(result: Gate4Result) -> Any:
    """Project the statistics onto the shared scorecard vocabulary."""
    from scripts.pilot.results import GateRun, not_run, passed

    checks = [
        _leg_check(
            "voice_to_voice_p50",
            result.median_verdict,
            f"target <= {TARGET_P50_MS}ms. {result.turn_summary.note}",
            **{
                k: v
                for k, v in {
                    "n": result.turn_summary.n,
                    "median_ms": result.turn_summary.median_ms,
                    "ci_low_ms": result.turn_summary.median_ci.low_ms
                    if result.turn_summary.median_ci
                    else None,
                    "ci_high_ms": result.turn_summary.median_ci.high_ms
                    if result.turn_summary.median_ci
                    else None,
                }.items()
                if v is not None
            },
        ),
        _leg_check(
            "voice_to_voice_tail",
            result.tail.verdict,
            result.tail.note,
            n=result.tail.n,
            exceedances=result.tail.exceedances,
            **(
                {"exceedance_upper_95": round(result.tail.exceedance_upper_95, 4)}
                if result.tail.exceedance_upper_95 is not None
                else {}
            ),
        ),
    ]
    greeting = result.greeting_summary
    checks.append(
        passed(
            "first_greeting_delay_recorded",
            f"recorded separately from turn latency. {greeting.note}",
            n=greeting.n,
            **({"median_ms": greeting.median_ms} if greeting.median_ms is not None else {}),
        )
        if greeting.n
        else not_run(
            "first_greeting_delay_recorded",
            "no first-greeting delay was recorded; cold start hides here and gate 4 asks "
            "for it separately.",
        )
    )
    comparisons = len(result.turn_agreement.comparisons) + len(
        result.greeting_agreement.comparisons
    )
    checks.append(
        passed(
            "vendor_latency_vs_stopwatch_compared",
            f"{result.turn_agreement.note} || {result.greeting_agreement.note}",
            comparable_pairs=comparisons,
        )
        if comparisons
        else not_run(
            "vendor_latency_vs_stopwatch_compared",
            "no latency_data was captured beside a measured sample, so the vendor's "
            f"self-reported latency was never tested. {ADAPTER_FINDING}",
        )
    )
    return GateRun(
        number=4,
        title="Real-call latency",
        checks=tuple(checks),
        findings=(NOT_MEASURABLE_FINDING, SMALL_N_FINDING, ADAPTER_FINDING),
    )


def gate4_from_disk(path_str: str | None = None) -> Any:
    """Read the ledger and score it. Synchronous: this gate is a file and some arithmetic.

    Kept out of the async runner entry point because blocking file IO inside a coroutine
    is a defect the linter is right about, and because this is the form the scorecard
    author (and a test) can call directly.
    """
    import json
    import os
    from pathlib import Path

    from scripts.pilot.results import GateRun

    path = Path(path_str or os.environ.get(OBSERVATIONS_ENV) or DEFAULT_OBSERVATIONS_PATH)
    if not path.exists():
        return GateRun(
            number=4,
            title="Real-call latency",
            blocked=(
                f"no observations file at {path} (override with ${OBSERVATIONS_ENV}). "
                f"{NOT_MEASURABLE_FINDING}"
            ),
            findings=(NOT_MEASURABLE_FINDING, SMALL_N_FINDING, ADAPTER_FINDING),
        )
    try:
        payload = json.loads(path.read_text())
        turns, greetings, vendor = load_gate4_observations(payload)
    except (ObservationsError, ValueError, KeyError, TypeError) as exc:
        # The message may quote the file's own content, which may quote a caller. Type
        # and the failing path only (hard rule 6).
        return GateRun(
            number=4,
            title="Real-call latency",
            blocked=f"observations file at {path} could not be read: {type(exc).__name__}",
            findings=(ADAPTER_FINDING,),
        )
    return gate4_result(evaluate_gate4(turns, greetings, vendor))


async def run_gate_4(ctx: Any) -> Any:
    """Gate 4 for `scripts.pilot.runner`.

    It places no calls and touches no engine: everything it needs was produced by a human
    with a stopwatch and a saved Get Execution payload. `ctx` is accepted (and unused
    beyond its presence) to match `GateRunner`; taking a call budget it cannot spend
    would be the only lie in the file.
    """
    del ctx  # nothing here may dial; see the module docstring
    return gate4_from_disk()


GATES = {4: run_gate_4}


__all__ = [
    "ADAPTER_FINDING",
    "ALPHA",
    "DEFAULT_OBSERVATIONS_PATH",
    "GATES",
    "MIN_SAMPLES_FOR_MEDIAN_CI",
    "NOT_MEASURABLE_FINDING",
    "OBSERVATIONS_ENV",
    "PASSING_VERDICTS",
    "REPORT_PRECISION_MS",
    "SMALL_N_FINDING",
    "STORAGE_SHAPE_FINDING",
    "TARGET_P50_MS",
    "TARGET_TAIL_FRACTION",
    "TARGET_TAIL_MS",
    "TOLERANCE_MS_BY_METHOD",
    "AgreementFinding",
    "Gate4Result",
    "GreetingSample",
    "MeasurementMethod",
    "MedianInterval",
    "ObservationsError",
    "SampleSummary",
    "TailFinding",
    "TurnComparison",
    "TurnLatencySample",
    "VendorCallLatency",
    "VendorTurnLatency",
    "Verdict",
    "clopper_pearson_lower",
    "clopper_pearson_upper",
    "compare_greeting_latency",
    "compare_turn_latency",
    "evaluate_gate4",
    "evaluate_median_against",
    "evaluate_tail",
    "gate4_from_disk",
    "gate4_result",
    "load_gate4_observations",
    "median_confidence_interval",
    "parse_latency_data",
    "redact_latency_data",
    "render_gate4_markdown",
    "run_gate_4",
    "samples_needed_to_confirm",
    "summarize_samples",
    "unredacted_text_paths",
]
