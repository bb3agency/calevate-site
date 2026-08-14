"""Pilot gate 7 (OPERATIONS §2) — post-call data fidelity, as probes.

    uv run python -m scripts.pilot run --gates 7

Gate 7 asks five things of a `completed` execution — not of a `call-disconnected` one,
and that distinction is the gate's premise: TRD §5 says cost, recording and extracted
data populate only at `completed`, roughly 2-3 minutes after disconnect, so anything
read earlier is legitimately empty and scoring it would produce a red that means
nothing. The five:

  1. does `completed` carry `total_cost` **and** a per-component `cost_breakdown`;
  2. is the money in the unit we assumed (USD **cents**);
  3. does it carry a `recording_url`;
  4. does it carry `extracted_data`;
  5. does the transcript parse into OUR `TranscriptTurn`;
  and the measurement: time-to-`completed` against the 2-minute lead SLO (OPERATIONS §5).

**EVERYTHING RUNS THROUGH THE `VoiceEngine` ADAPTER, NEVER RAW HTTP** (hard rule 2, and
`gates_api.py`'s reasoning applies verbatim: a curl verifies Bolna, an adapter call
verifies the thing we will ship a client on). That choice is what gives check 5 its
teeth and what takes them off check 2, and both consequences are worth stating plainly:

* **Check 5 is the whole engine-isolation bet, in one row.** `ExecutionSnapshot.
  transcript` is `list[TranscriptTurn]`, so "does their payload survive our model" is
  answered by whether `get_execution` returns at all and by what it returns. A payload
  our model rejects surfaces as a `pydantic.ValidationError` raised out of the adapter —
  which this module catches and reports as a FAIL naming the FIELDS (`loc`) and the
  error TYPES, never as a traceback and never quoting the input value (a validation
  message carries the rejected input, and here that input is a caller's words).
* **Check 2 cannot be answered by reading our own snapshot.** `BolnaEngine._cost` sets
  `source_currency="USD"` as a literal and computes `source_amount = total_cost / 100`;
  asking the snapshot what currency it is in returns our own assumption, exactly as
  gate 1 would learn nothing by asking the adapter whether it allows the IP the adapter
  allows. So the row is NOT RUN until the operator supplies the vendor's OWN figure for
  the same execution (dashboard or invoice), and what it then tests is whether our
  derived amount matches theirs — a 100x disagreement is the signature of the cents
  assumption being wrong, and every INR row in the ledger inherits that factor.

**TIME-TO-`completed` IS A MEASUREMENT, AND ABSENT IF NOT MEASURED.** There is no
"completed_at" anywhere in the contract — `ExecutionSnapshot` carries `started_at` and
`ended_at` (the CALL's instants) and nothing that says when cost/transcript landed — so
the interval cannot be reconstructed after the fact from a snapshot that is already
complete. It is measured by POLLING from an operator-supplied disconnect instant, or it
is absent. It is never defaulted, and `now - ended_at` is deliberately NOT used: that is
an upper bound on the interval that grows with how long the operator took to run the
harness, and a bound wearing a measurement's name is the one thing this harness exists
to prevent.

**HARD RULES 5 AND 6.** A real execution carries `to_e164`, transcript text and a
`recording_url` whose query string is usually a presigned CREDENTIAL (`record.py`). This
module records the PRESENCE of those things, their COUNTS and their FIELD NAMES, and
never their values: no phone number, no turn text, no URL, no extracted value. The
execution id is the only identifier that leaves here, and `redact.call_ref` is the one
place that decision is written down, so this module names calls through it rather than
re-deciding.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Protocol

from calevate_shared.engine import ExecutionSnapshot
from pydantic import BaseModel, Field, ValidationError

from scripts.pilot.redact import call_ref
from scripts.pilot.results import GateRun, SubCheck, failed, not_run, passed

GATE_NUMBER = 7
GATE_TITLE = "Post-call data fidelity"

#: Sub-check names, in report order. Every one is emitted on every run — a check whose
#: inputs were missing appears as NOT RUN rather than not appearing, which is the only
#: way a reader can tell "we did not measure this" from "this gate is short".
CHECK_NAMES: tuple[str, ...] = (
    "completed_carries_total_cost",
    "completed_carries_cost_breakdown",
    "cost_currency_is_usd_cents",
    "completed_carries_recording_url",
    "completed_carries_extracted_data",
    "transcript_parses_into_transcript_turn",
    "time_to_completed_within_lead_slo",
)

#: OPERATIONS §5: "lead visible post-hangup ≤ 2 min (99%)". The vendor claims cost and
#: transcript land ~2-3 min after disconnect, which is the ENTIRE budget before our
#: pipeline has done anything — measuring the real number is the point of the row.
LEAD_SLO_S: float = 120.0

#: The cost legs `CostBreakdown` can carry, by OUR field names. Reported by NAME so a
#: vendor that stops sending one is visible as a named absence rather than as a zero.
COST_COMPONENTS: tuple[str, ...] = (
    "platform_inr",
    "network_inr",
    "llm_inr",
    "tts_inr",
    "stt_inr",
)

#: What the adapter assumes the vendor's `total_cost` is denominated in. Written here as
#: the value gate 7 TESTS, never imported from the adapter: importing it would make the
#: check tautological (gate 1 makes the same argument about the egress IP).
ASSUMED_SOURCE_CURRENCY = "USD"
ASSUMED_MINOR_UNITS_PER_MAJOR = Decimal(100)

#: Money comparisons quantize here before they are compared. Fractions of a US cent on a
#: per-call charge are below the resolution either side reports, and comparing raw
#: Decimals would fail the gate on a rounding digit rather than on a unit error.
MONEY_QUANTUM = Decimal("0.0001")

INPUTS_ENV = "CALEVATE_PILOT_GATE7_INPUTS"
DEFAULT_INPUTS_PATH = "docs/evidence/gate7-inputs.json"

DEFAULT_POLL_INTERVAL_S = 15.0
DEFAULT_POLL_TIMEOUT_S = 300.0

# --- findings this gate reports on every run ----------------------------------

CURRENCY_FINDING = (
    "THE CURRENCY IS STILL AN ASSUMPTION UNTIL A PAYLOAD STATES IT. `CostBreakdown"
    ".currency_stated` now separates the two cases: True means the execution payload "
    "named the currency and the adapter converted on a FACT; False means it named "
    "nothing and the adapter fell back to `_ASSUMED_CURRENCY` ('USD cents', read off "
    "docs.bolna.ai, never confirmed on a live account). This gate corroborates against "
    "the vendor's own figure for the same execution either way, because that is the only "
    "independent check — but a `currency_stated=False` run is the one that leaves the "
    "assumption load-bearing, and if it is wrong every INR row in usage_events is wrong "
    "by the exchange rate (hard rule 7). A currency the adapter cannot convert is now "
    "REFUSED rather than converted at the USD rate, so a wrong cost basis cannot ship "
    "silently; the cost is simply absent and this gate reports it as missing."
)

TRANSCRIPT_PARSE_FINDING = (
    "A PARTIAL TRANSCRIPT PARSE IS NOW MEASURABLE, AND THIS GATE MEASURES IT. "
    "`bolna.parse_transcript` reads a prefix-tagged STRING, and the lines it cannot "
    "place — an unprefixed line before any turn exists, a recognised prefix with an "
    "empty body — used to vanish, so a format change costing a third of every transcript "
    "looked like quiet callers. It now returns a count alongside the turns and the "
    "snapshot carries it as `transcript_lines_unparsed`. Any non-zero value is scored "
    "below, in ADDITION to the total-failure signature (zero turns on a completed call "
    "that carried audio) and the per-turn structural defects. A count rather than the "
    "lines themselves: transcript text does not leave the engine boundary except as a "
    "`TranscriptTurn` (hard rule 6)."
)

COMPLETED_AT_FINDING = (
    "`billable_ready_at` IS AN UPPER BOUND, NOT THE TRANSITION. `ExecutionSnapshot` now "
    "carries an instant for when cost, recording and transcript landed — the vendor's "
    "own `completed_at` where the payload has one, otherwise the moment WE observed the "
    "execution already complete. The second form is bounded by the poller's tick and by "
    "how long after the call anything looked, so it can only ever over-state "
    "time-to-completed. This gate therefore still prefers a LIVE poll from an operator-"
    "supplied disconnect instant when one is given, and falls back to the recorded "
    "instant with the bound stated. `now - ended_at` remains deliberately unused: it "
    "grows with how long the operator took to run the harness."
)


class ExecutionReader(Protocol):
    """The one `VoiceEngine` method this gate needs, narrowed.

    Narrower than the full Protocol so the probes can be pointed at a stub that models
    exactly one vendor behaviour (a snapshot with no cost; a payload our model rejects;
    an execution that becomes complete on the third poll). A probe that demanded
    `verify_webhook` too could not be pointed at one, and every failure path below would
    then be untested — which is the state gate 7 was in before this module existed.
    """

    async def get_execution(self, call_id: str) -> ExecutionSnapshot: ...


# --- what one execution told us ------------------------------------------------


@dataclass(frozen=True, slots=True)
class TranscriptDefect:
    """One named way OUR model did not survive THEIR payload.

    `field` is a dotted path in our own vocabulary and `reason` is our own words. The
    rejected value is never carried: a pydantic error's `input` on this path is a
    caller's speech, and this object is serialized into an artefact committed to git.
    """

    field: str
    reason: str

    def render(self) -> str:
        return f"{self.field}: {self.reason}"


@dataclass(frozen=True, slots=True)
class FidelityObservation:
    """What ONE execution carried. Presence, counts and field names only."""

    call_ref: str
    status: str
    raw_status: str
    terminal: bool
    billable_ready: bool
    duration_s: int | None
    has_total_cost: bool
    cost_components_present: tuple[str, ...]
    cost_components_absent: tuple[str, ...]
    source_currency: str | None
    source_amount: Decimal | None
    has_recording_url: bool
    extracted_field_names: tuple[str, ...]
    transcript_turns: int
    transcript_defects: tuple[TranscriptDefect, ...]


@dataclass(frozen=True, slots=True)
class UnreadableExecution:
    """An execution whose snapshot never materialised, and why.

    `kind="model_rejected"` is the interesting one and it is NOT an error: it is gate 7's
    headline result — their payload did not survive our model, and `defects` names the
    fields. `kind="unreachable"` is a transport or engine-side failure, which says
    nothing about fidelity and must not be scored as if it did.
    """

    call_ref: str
    kind: Literal["model_rejected", "unreachable"]
    detail: str
    defects: tuple[TranscriptDefect, ...] = ()


@dataclass(frozen=True, slots=True)
class CompletionTiming:
    """A measured interval from an observed disconnect to an observed `completed`.

    `poll_interval_s` is carried because it IS the resolution: the true instant lies
    within one interval below the measured value, and a reader comparing a 118s
    measurement against a 120s SLO needs to know the number is ±15s, not ±0.
    """

    call_ref: str
    seconds_to_completed: float
    polls: int
    poll_interval_s: float


@dataclass(frozen=True, slots=True)
class VendorCostClaim:
    """The vendor's OWN figure for one execution, read off their dashboard or invoice.

    This is an operator observation, not a measurement, and it is the only way check 2
    can be answered at all (see `CURRENCY_FINDING`). `total` is a string in the inputs
    file and a Decimal here — money never touches a float (hard rule 7).
    """

    call_ref: str
    total: Decimal
    currency: str


# --- reading one execution -----------------------------------------------------


def _validation_defects(exc: ValidationError, *, prefix: str = "") -> tuple[TranscriptDefect, ...]:
    """Field paths and error TYPES out of a pydantic failure. Never the input value.

    `ValidationError.errors()` entries carry `input` — for a transcript that is the
    caller's words, and for `to_e164` it is a phone number. Only `loc` and `type` are
    read, and `msg` is deliberately left behind as well: pydantic v2 interpolates the
    value into some messages, and a rule of "usually safe" is not one this artefact can
    rest on.
    """
    defects: list[TranscriptDefect] = []
    for error in exc.errors():
        path = ".".join(str(part) for part in error.get("loc", ())) or "(root)"
        defects.append(
            TranscriptDefect(
                field=f"{prefix}{path}",
                reason=f"our model rejected it: {error.get('type', 'unknown')}",
            )
        )
    return tuple(defects)


def transcript_defects(snapshot: ExecutionSnapshot) -> tuple[TranscriptDefect, ...]:
    """Every way this snapshot's transcript falls short of OUR `TranscriptTurn` contract.

    Four questions, and the first is the one with teeth:

    * **zero turns on a completed call that carried audio.** That is the observable
      signature of a total parse failure — `parse_transcript` returns [] for any shape
      it does not recognise, which is indistinguishable from a silent call, so the
      duration is what separates them.
    * **the turns round-trip through the model.** A turn built by an adapter that
      bypassed validation (`model_construct`, or a `model_copy` that widened a field) is
      caught here and nowhere else.
    * **idx is a contiguous 0-based sequence.** Our CRM and the redaction pipeline order
      by it; a transcript whose turns all carry idx 0 parses fine and reads as one turn.
    * **call_id addresses this execution.** A turn stamped with another call's id is a
      row that will land under the wrong lead.
    """
    defects: list[TranscriptDefect] = []
    turns = snapshot.transcript

    # The PARTIAL case, which used to be invisible and is the reason the adapter counts.
    # Checked before the empty case and independently of it: a transcript can parse into
    # plenty of turns and still have lost lines, which is the shape that survives every
    # "did we get a transcript" check ever written.
    if snapshot.transcript_lines_unparsed:
        defects.append(
            TranscriptDefect(
                field="transcript",
                reason=(
                    f"{snapshot.transcript_lines_unparsed} line(s) could not be placed as "
                    "a turn — the parser recognised the shape well enough to return "
                    "something, so this loss is silent everywhere except here"
                ),
            )
        )

    if not turns:
        if snapshot.billable_ready and (snapshot.duration_s or 0) > 0:
            defects.append(
                TranscriptDefect(
                    field="transcript",
                    reason=(
                        f"zero turns on a completed execution carrying {snapshot.duration_s}s "
                        "of audio — the signature of a transcript shape our parser does "
                        "not recognise"
                    ),
                )
            )
        return tuple(defects)

    for position, turn in enumerate(turns):
        try:
            turn.__class__.model_validate(turn.model_dump())
        except ValidationError as exc:
            defects.extend(_validation_defects(exc, prefix=f"transcript.{position}."))
            continue
        if not turn.text.strip():
            defects.append(
                TranscriptDefect(
                    field=f"transcript.{position}.text",
                    reason="empty after parsing — a turn with no words is a dropped turn",
                )
            )
        if turn.call_id != snapshot.engine_call_id:
            defects.append(
                TranscriptDefect(
                    field=f"transcript.{position}.call_id",
                    reason="does not address this execution",
                )
            )

    if [t.idx for t in turns] != list(range(len(turns))):
        defects.append(
            TranscriptDefect(
                field="transcript[].idx",
                reason="not a contiguous 0-based sequence, so turn order is not recoverable",
            )
        )
    return tuple(defects)


def observe(snapshot: ExecutionSnapshot) -> FidelityObservation:
    """Project a snapshot onto the non-PII record gate 7 scores and commits."""
    cost = snapshot.cost
    present = tuple(name for name in COST_COMPONENTS if getattr(cost, name, None) is not None)
    return FidelityObservation(
        call_ref=call_ref(snapshot.engine_call_id),
        status=snapshot.status,
        raw_status=snapshot.raw_status,
        terminal=snapshot.terminal,
        billable_ready=snapshot.billable_ready,
        duration_s=snapshot.duration_s,
        has_total_cost=cost is not None,
        cost_components_present=present,
        cost_components_absent=tuple(n for n in COST_COMPONENTS if n not in present),
        source_currency=cost.source_currency if cost is not None else None,
        source_amount=cost.source_amount if cost is not None else None,
        has_recording_url=bool(snapshot.recording_url),
        # NAMES only. The values are whatever the extraction schema pulled out of a
        # caller, which is the definition of an extraction payload (hard rule 6).
        extracted_field_names=tuple(sorted(snapshot.engine_extracted)),
        transcript_turns=len(snapshot.transcript),
        transcript_defects=transcript_defects(snapshot),
    )


async def read_execution(
    engine: ExecutionReader, execution_id: str
) -> FidelityObservation | UnreadableExecution:
    """One `GET /executions/{id}` through the adapter, with the failure modes separated.

    A payload our model rejects is a RESULT (`model_rejected`), not an error: it is the
    single most valuable thing gate 7 can find, because everything above the adapter is
    written against these models. A transport failure is not a fidelity fact at all and
    is kept apart so it can never be scored as one.
    """
    try:
        snapshot = await engine.get_execution(execution_id)
    except ValidationError as exc:
        return UnreadableExecution(
            call_ref=call_ref(execution_id),
            kind="model_rejected",
            detail=f"{exc.error_count()} field(s) of the vendor payload failed our model",
            defects=_validation_defects(exc),
        )
    except Exception as exc:
        # Only the exception TYPE (and a ProblemError's code, which is user-safe by
        # construction). An arbitrary `str()` here can be an httpx object carrying the
        # request URL, and the URL carries the execution — and sometimes the number.
        code = getattr(exc, "code", None)
        return UnreadableExecution(
            call_ref=call_ref(execution_id),
            kind="unreachable",
            detail=f"get_execution failed: {code or 'unexpected ' + type(exc).__name__}",
        )
    return observe(snapshot)


# --- the one thing that must be measured live ----------------------------------


async def measure_time_to_completed(
    engine: ExecutionReader,
    execution_id: str,
    *,
    disconnected_at: datetime,
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> CompletionTiming | str:
    """Poll until the execution is `billable_ready`; return the interval or the reason.

    Returns a REASON STRING rather than raising or returning None, because every caller
    of this function has to write that reason into a NOT RUN row and a bare None would
    let one of them forget.

    The clock and the sleep are seams so the failure paths (never completes, times out,
    completes on the third poll) run in the normal suite in microseconds. `now` returns
    an aware instant and a naive `disconnected_at` is REFUSED: subtracting a naive
    operator timestamp from an aware one raises deep inside the arithmetic, and the
    operator's IST wall-clock entry is exactly the value most likely to arrive naive.
    """
    if disconnected_at.tzinfo is None:
        return (
            "disconnected_at has no timezone offset. It is an instant on a wall clock in "
            "IST; write it as ISO-8601 with its offset (…+05:30) so the interval is not "
            "5.5 hours wrong."
        )
    started = now()
    polls = 0
    while True:
        polls += 1
        observed = await read_execution(engine, execution_id)
        if isinstance(observed, FidelityObservation) and observed.billable_ready:
            elapsed = (now() - disconnected_at).total_seconds()
            return CompletionTiming(
                call_ref=call_ref(execution_id),
                seconds_to_completed=elapsed,
                polls=polls,
                poll_interval_s=interval_s,
            )
        if isinstance(observed, UnreadableExecution) and observed.kind == "unreachable":
            return f"{observed.call_ref} could not be polled — {observed.detail}"
        if (now() - started).total_seconds() + interval_s > timeout_s:
            return (
                f"{call_ref(execution_id)} was still not `completed` after {timeout_s:.0f}s of "
                f"polling ({polls} polls). That is itself a fact about the vendor: raise "
                "the timeout and re-run rather than recording a bound as a measurement."
            )
        await sleep(interval_s)


# --- scoring -------------------------------------------------------------------


def _money(value: object) -> Decimal | None:
    """A Decimal from an operator-written string. Never a float (hard rule 7)."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _cost_checks(completed: Sequence[FidelityObservation]) -> list[SubCheck]:
    without_total = [o for o in completed if not o.has_total_cost]
    if without_total:
        total_check = failed(
            "completed_carries_total_cost",
            f"{len(without_total)} of {len(completed)} `completed` executions carry NO "
            f"cost at all ({', '.join(sorted(o.call_ref for o in without_total))}). Every "
            "usage_event for those calls would be unpriced, and D-31's poller cannot "
            "repair what the vendor never sent.",
            completed_executions=len(completed),
            without_total_cost=len(without_total),
        )
    else:
        total_check = passed(
            "completed_carries_total_cost",
            "every `completed` execution carries a total cost",
            completed_executions=len(completed),
        )

    with_total = [o for o in completed if o.has_total_cost]
    missing_all = [o for o in with_total if not o.cost_components_present]
    absent_names = sorted({name for o in with_total for name in o.cost_components_absent})
    if missing_all:
        breakdown_check = failed(
            "completed_carries_cost_breakdown",
            f"{len(missing_all)} of {len(with_total)} priced executions carry a total and "
            "NO per-component breakdown. Without legs we cannot attribute spend to "
            "platform vs network vs models, which is the whole basis of the margin model.",
            priced_executions=len(with_total),
            without_any_component=len(missing_all),
        )
    elif absent_names:
        breakdown_check = passed(
            "completed_carries_cost_breakdown",
            "a per-component breakdown is present; these legs were absent on at least one "
            f"execution and are ABSENT rather than zero: {', '.join(absent_names)}",
            priced_executions=len(with_total),
            components_absent_somewhere=len(absent_names),
        )
    else:
        breakdown_check = passed(
            "completed_carries_cost_breakdown",
            "every priced execution carries all five cost components",
            priced_executions=len(with_total),
            components=len(COST_COMPONENTS),
        )
    return [total_check, breakdown_check]


def _currency_check(
    completed: Sequence[FidelityObservation], claims: Mapping[str, VendorCostClaim]
) -> SubCheck:
    """Our derived amount against the vendor's own figure. See `CURRENCY_FINDING`."""
    comparable = [(o, claims[o.call_ref]) for o in completed if o.call_ref in claims]
    comparable = [(o, c) for o, c in comparable if o.source_amount is not None]
    if not comparable:
        return not_run(
            "cost_currency_is_usd_cents",
            "no vendor-reported figure to corroborate against. Our snapshot says "
            f"{ASSUMED_SOURCE_CURRENCY} because the ADAPTER hard-codes it, so reading it "
            "back tests nothing. Put the vendor's own total for the same execution in the "
            "inputs file (`vendor_reported_total` / `vendor_reported_currency`).",
        )

    wrong_currency = [c.currency for _o, c in comparable if c.currency.upper() != "USD"]
    if wrong_currency:
        return failed(
            "cost_currency_is_usd_cents",
            "the vendor reports this execution in "
            f"{', '.join(sorted(set(wrong_currency)))}, not USD. The adapter converts "
            "assuming USD cents, so every INR figure derived from it is wrong by the FX "
            "ratio as well as by any unit error.",
            executions_compared=len(comparable),
        )

    mismatched: list[tuple[str, Decimal]] = []
    for observation, claim in comparable:
        ours = (observation.source_amount or Decimal(0)).quantize(MONEY_QUANTUM)
        theirs = claim.total.quantize(MONEY_QUANTUM)
        if ours != theirs:
            ratio = (theirs / ours).quantize(MONEY_QUANTUM) if ours else Decimal(0)
            mismatched.append((observation.call_ref, ratio))

    if not mismatched:
        return passed(
            "cost_currency_is_usd_cents",
            "our derived major-unit amount equals the vendor's own reported total on every "
            f"compared execution, so `total_cost` is {ASSUMED_SOURCE_CURRENCY} minor units "
            f"({ASSUMED_MINOR_UNITS_PER_MAJOR} per major) as the adapter assumes",
            executions_compared=len(comparable),
        )

    ratios = sorted({str(ratio) for _ref, ratio in mismatched})
    hundredfold = any(ratio == ASSUMED_MINOR_UNITS_PER_MAJOR for _ref, ratio in mismatched)
    return failed(
        "cost_currency_is_usd_cents",
        f"{len(mismatched)} of {len(comparable)} executions disagree with the vendor's own "
        f"total (theirs / ours = {', '.join(ratios)}; executions "
        f"{', '.join(sorted(ref for ref, _ratio in mismatched))}). "
        + (
            "A ratio of exactly 100 means `total_cost` is NOT in cents: the adapter's /100 "
            "is wrong and every INR row is 100x off (hard rule 7)."
            if hundredfold
            else "The cents assumption does not hold as written; re-derive the unit before "
            "any ledger row is trusted."
        ),
        executions_compared=len(comparable),
        executions_mismatched=len(mismatched),
    )


def _recording_check(completed: Sequence[FidelityObservation]) -> SubCheck:
    without = [o for o in completed if not o.has_recording_url]
    if without:
        return failed(
            "completed_carries_recording_url",
            f"{len(without)} of {len(completed)} `completed` executions carry no "
            f"recording_url ({', '.join(sorted(o.call_ref for o in without))}). QA, the "
            "eval harness and every dispute rest on the recording, "
            "and a URL that is absent at `completed` is one the poller cannot fetch later.",
            completed_executions=len(completed),
            without_recording=len(without),
        )
    return passed(
        "completed_carries_recording_url",
        "every `completed` execution carries a recording_url (presence only — the URL is "
        "presigned and its query string is a credential)",
        completed_executions=len(completed),
    )


def _extraction_check(
    completed: Sequence[FidelityObservation], expected: Mapping[str, tuple[str, ...]]
) -> SubCheck:
    """Extracted data, scored against what the operator's schema actually asked for.

    An empty `extracted_data` is not automatically a failure: an agent configured with no
    extraction schema legitimately returns nothing, and failing that would score OUR
    configuration as the vendor's defect. So the row is decided by expectations when the
    operator supplied them, is a pass when fields arrived unasked, and is NOT RUN when
    neither is true — with the reason naming what to configure.
    """
    with_fields = [o for o in completed if o.extracted_field_names]
    if expected:
        shortfalls: list[str] = []
        for observation in completed:
            wanted = expected.get(observation.call_ref)
            if not wanted:
                continue
            missing = [f for f in wanted if f not in observation.extracted_field_names]
            shortfalls.extend(missing)
        if shortfalls:
            return failed(
                "completed_carries_extracted_data",
                "the extraction schema's fields did not all come back at `completed`; "
                f"absent: {', '.join(sorted(set(shortfalls)))}. Schema-driven extraction "
                "is what fills the CRM columns, so an absent field is an empty column.",
                completed_executions=len(completed),
                fields_absent=len(set(shortfalls)),
            )
        return passed(
            "completed_carries_extracted_data",
            "every field the extraction schema asked for came back at `completed`",
            completed_executions=len(completed),
            fields_expected=len({f for fields in expected.values() for f in fields}),
        )
    if with_fields:
        names = sorted({name for o in with_fields for name in o.extracted_field_names})
        return passed(
            "completed_carries_extracted_data",
            f"`extracted_data` arrived at `completed` carrying these field NAMES: "
            f"{', '.join(names)} (values withheld — hard rule 6)",
            completed_executions=len(completed),
            executions_with_extraction=len(with_fields),
        )
    return not_run(
        "completed_carries_extracted_data",
        "no execution carried any `extracted_data`, and no expected fields were supplied. "
        "An agent with no extraction schema returns nothing legitimately, so this cannot "
        "be scored: configure the pilot agent's extraction schema and list its field names "
        "as `expects_extracted_fields` in the inputs file.",
    )


def _transcript_check(
    observations: Sequence[FidelityObservation], rejected: Sequence[UnreadableExecution]
) -> SubCheck:
    """The engine-isolation bet, in one row. A parse failure is a FAIL with the field
    named — never an exception that takes the run down and never a silent skip."""
    # Every defect is prefixed with its EXECUTION ID: an operator reading "transcript.3.
    # speaker" has to know which of ten calls to open, and the execution id is the one
    # identifier that is both useful to them and not personal data (`redact.call_ref`).
    defect_lines: list[str] = []
    for unreadable in rejected:
        defect_lines.extend(f"{unreadable.call_ref} {d.render()}" for d in unreadable.defects)
    for observation in observations:
        defect_lines.extend(
            f"{observation.call_ref} {d.render()}" for d in observation.transcript_defects
        )

    if rejected:
        return failed(
            "transcript_parses_into_transcript_turn",
            f"{len(rejected)} vendor payload(s) did not survive our models at all — "
            f"get_execution raised on: {'; '.join(sorted(set(defect_lines)))}. Everything "
            "above the adapter is written against these models, so a call whose payload "
            "our model rejects is a call that does not exist for the pipeline.",
            executions_read=len(observations) + len(rejected),
            payloads_rejected=len(rejected),
        )
    if not observations:
        return not_run(
            "transcript_parses_into_transcript_turn",
            "no execution snapshot was read, so no transcript was parsed.",
        )
    if defect_lines:
        return failed(
            "transcript_parses_into_transcript_turn",
            "the transcript reached our model but does not satisfy its contract: "
            f"{'; '.join(sorted(set(defect_lines)))}.",
            executions_read=len(observations),
            defects=len(set(defect_lines)),
        )
    turns = sum(o.transcript_turns for o in observations)
    if not turns:
        return not_run(
            "transcript_parses_into_transcript_turn",
            "no execution carried any transcript turns and none of them was a `completed` "
            "call with audio, so nothing was parsed and nothing can be concluded. Re-read "
            "the execution once it is billable_ready.",
            executions_read=len(observations),
        )
    return passed(
        "transcript_parses_into_transcript_turn",
        "every turn of every transcript parsed into our `TranscriptTurn`, with contiguous "
        "0-based idx and this execution's call_id",
        executions_read=len(observations),
        turns_parsed=turns,
    )


def _timing_check(timings: Sequence[CompletionTiming], reasons: Sequence[str]) -> SubCheck:
    if not timings:
        return not_run(
            "time_to_completed_within_lead_slo",
            "time-to-`completed` was not measured. "
            + (
                " ".join(reasons)
                if reasons
                else "It is measured by polling from an observed disconnect instant "
                f"(`disconnected_at` per execution in the inputs file), never derived — "
                f"{COMPLETED_AT_FINDING}"
            ),
        )
    slowest = max(t.seconds_to_completed for t in timings)
    fastest = min(t.seconds_to_completed for t in timings)
    resolution = max(t.poll_interval_s for t in timings)
    breaches = [t for t in timings if t.seconds_to_completed > LEAD_SLO_S]
    measurements: dict[str, int | float | str | Decimal] = {
        "executions_timed": len(timings),
        "slowest_s": round(slowest, 1),
        "fastest_s": round(fastest, 1),
        "resolution_s": resolution,
        "slo_s": LEAD_SLO_S,
    }
    if breaches:
        return failed(
            "time_to_completed_within_lead_slo",
            f"{len(breaches)} of {len(timings)} executions took longer than the "
            f"{LEAD_SLO_S:.0f}s lead SLO to reach `completed` (slowest {slowest:.0f}s, "
            f"±{resolution:.0f}s). The vendor consumes the WHOLE budget before our "
            "pipeline starts, so OPERATIONS §5's 'lead visible post-hangup ≤ 2 min' cannot "
            "be met from the `completed` event — either the SLO moves or the lead is "
            "created from an earlier transition and enriched at `completed`.",
            **measurements,
        )
    return passed(
        "time_to_completed_within_lead_slo",
        f"every execution reached `completed` inside the {LEAD_SLO_S:.0f}s lead SLO "
        f"(slowest {slowest:.0f}s, ±{resolution:.0f}s resolution) — the budget our own "
        "pipeline still has to fit inside",
        **measurements,
    )


def evaluate_gate7(
    observations: Sequence[FidelityObservation],
    *,
    unreadable: Sequence[UnreadableExecution] = (),
    timings: Sequence[CompletionTiming] = (),
    timing_reasons: Sequence[str] = (),
    vendor_claims: Mapping[str, VendorCostClaim] | None = None,
    expected_extraction: Mapping[str, tuple[str, ...]] | None = None,
) -> GateRun:
    """Score what was observed. Pure — no engine, no clock, no file.

    Kept separate from the driving so every verdict below is reachable from a test with
    a hand-built observation, including the ones a `fake` engine can never produce (a
    payload our model rejects, a 100x currency error, a 4-minute time-to-completed).
    """
    rejected = [u for u in unreadable if u.kind == "model_rejected"]
    unreachable = [u for u in unreadable if u.kind == "unreachable"]
    completed = [o for o in observations if o.billable_ready]

    checks: list[SubCheck] = []
    if not completed:
        # Every fidelity claim in this gate is a claim about `completed`, so with none in
        # hand the four field rows are unanswerable — and saying so by name is the point.
        # A terminal-but-not-billable_ready execution is the EXPECTED state before ~2-3
        # min; scoring it would produce a red about the vendor's documented behaviour.
        seen = (
            f"{len(observations)} execution(s) were read and none was `completed` "
            f"(statuses: {', '.join(sorted({o.raw_status for o in observations}))})"
            if observations
            else "no execution snapshot was read"
        )
        reason = (
            f"{seen}. Cost, recording and extracted data populate only at `completed` "
            "(~2-3 min after disconnect), so there is nothing here to judge — re-read the "
            "execution once it is billable_ready."
        )
        checks.extend(
            [
                not_run("completed_carries_total_cost", reason),
                not_run("completed_carries_cost_breakdown", reason),
                not_run("cost_currency_is_usd_cents", reason),
                not_run("completed_carries_recording_url", reason),
                not_run("completed_carries_extracted_data", reason),
            ]
        )
    else:
        checks.extend(_cost_checks(completed))
        checks.append(_currency_check(completed, vendor_claims or {}))
        checks.append(_recording_check(completed))
        checks.append(_extraction_check(completed, expected_extraction or {}))

    checks.append(_transcript_check(observations, rejected))
    checks.append(_timing_check(timings, timing_reasons))

    findings = [CURRENCY_FINDING, TRANSCRIPT_PARSE_FINDING, COMPLETED_AT_FINDING]
    if unreachable:
        findings.append(
            f"{len(unreachable)} execution(s) could not be read at all "
            f"({'; '.join(sorted({u.detail for u in unreachable}))}). Not scored as a "
            "fidelity failure — an unreachable execution says nothing about what a "
            "payload carries — but it is the reason those rows are thinner than they look."
        )

    ordered = {check.name: check for check in checks}
    return GateRun(
        number=GATE_NUMBER,
        title=GATE_TITLE,
        checks=tuple(
            ordered.get(name)
            or not_run(name, "the harness produced no row for this check — this is a bug")
            for name in CHECK_NAMES
        ),
        findings=tuple(findings),
    )


# --- wiring into the harness ---------------------------------------------------
#
# `scripts/pilot/runner.py` names this module in OPTIONAL_GATE_MODULES and reads a
# `GATES: {number: runner}` mapping, with results in the shared PASS/FAIL/NOT RUN
# vocabulary of `scripts/pilot/results.py`. The operator's inputs arrive in a JSON file
# with an env override — the same seam `latency.py` (gate 4) and `concurrency.py`
# (gate 13) use, deliberately rather than a third spelling: `--attest`'s vocabulary is
# closed and owned by another module, and the alternative (a flag per field) would put
# a vendor invoice line into a shell history.


class ExecutionInput(BaseModel):
    """One execution the operator wants gate 7 to read, and what they observed about it.

    `call_ref` is the ENGINE EXECUTION ID and never a phone number — it is what
    `GET /executions/{id}` takes, and it is the only identifier that reaches the artefact.
    """

    call_ref: str
    #: When the call actually hung up, ISO-8601 WITH its offset. The only route to a
    #: time-to-`completed` measurement; absent means that leg stays absent for this call.
    disconnected_at: datetime | None = None
    #: The vendor's own total for this execution, off their dashboard or invoice. A
    #: string in the file, a Decimal here: money never round-trips through a float.
    vendor_reported_total: Decimal | None = None
    vendor_reported_currency: str = "USD"
    #: The extraction schema's field NAMES for the agent that ran this call.
    expects_extracted_fields: list[str] = Field(default_factory=list)


class Gate7Inputs(BaseModel):
    """What the operator supplies. Every field optional; absent stays absent."""

    executions: list[ExecutionInput] = Field(default_factory=list)
    #: Poll for `completed` on executions that carry a `disconnected_at`. Off by default:
    #: polling blocks the run for minutes, and a harness that silently hangs is one an
    #: operator kills, losing the rest of the gates with it.
    #: Both bounded: a zero interval is a busy loop against a vendor's rate limiter, and
    #: a zero timeout is a measurement that can only ever report "not yet".
    poll_for_completed: bool = False
    poll_interval_s: float = Field(default=DEFAULT_POLL_INTERVAL_S, gt=0)
    poll_timeout_s: float = Field(default=DEFAULT_POLL_TIMEOUT_S, gt=0)


class Gate7InputsError(ValueError):
    """The inputs file exists but cannot be read.

    Raised rather than tolerated: a partially-parsed file would drop executions silently,
    and a gate that quietly read three of ten calls is worse than one that refused.
    """


def load_gate7_inputs(path_str: str | None = None) -> Gate7Inputs | None:
    """Read the operator's file, or None when there is none. Never invents inputs."""
    path = Path(path_str or os.environ.get(INPUTS_ENV) or DEFAULT_INPUTS_PATH)
    if not path.exists():
        return None
    try:
        return Gate7Inputs.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, json.JSONDecodeError, ValueError) as exc:
        # The message can quote the file's own content, which can quote a caller number
        # the operator pasted by accident. Type and path only (hard rule 6).
        raise Gate7InputsError(
            f"{path} could not be read as gate 7 inputs: {type(exc).__name__}"
        ) from exc


async def run_gate_7(ctx: Any) -> GateRun:
    """Gate 7 for `scripts.pilot.runner`.

    Places no calls: it READS executions that already happened, so it needs no budget and
    can never dial. Execution ids come from the operator's inputs file and from anything
    gate 2 placed earlier in the same run (`--gates 2,7`) — the second is why the ids are
    deduplicated rather than concatenated.
    """
    try:
        inputs = load_gate7_inputs()
    except Gate7InputsError as exc:
        return GateRun(number=GATE_NUMBER, title=GATE_TITLE, blocked=str(exc))

    wanted: dict[str, ExecutionInput] = {}
    for entry in inputs.executions if inputs else []:
        wanted.setdefault(entry.call_ref, entry)
    for created in getattr(ctx, "created_executions", []) or []:
        wanted.setdefault(str(created), ExecutionInput(call_ref=str(created)))

    if not wanted:
        return GateRun(
            number=GATE_NUMBER,
            title=GATE_TITLE,
            blocked=(
                f"no executions to read: there is no inputs file at {DEFAULT_INPUTS_PATH} "
                f"(override with ${INPUTS_ENV}) and no gate in this run placed a call. The "
                "file lists the execution ids of completed pilot calls, plus — per call — "
                "the observed `disconnected_at` and the vendor's own reported total, "
                "neither of which is derivable from a snapshot."
            ),
            findings=(CURRENCY_FINDING, TRANSCRIPT_PARSE_FINDING, COMPLETED_AT_FINDING),
        )

    engine: ExecutionReader = ctx.engine
    observations: list[FidelityObservation] = []
    unreadable: list[UnreadableExecution] = []
    timings: list[CompletionTiming] = []
    timing_reasons: list[str] = []

    for execution_id, entry in wanted.items():
        if inputs and inputs.poll_for_completed and entry.disconnected_at is not None:
            timed = await measure_time_to_completed(
                engine,
                execution_id,
                disconnected_at=entry.disconnected_at,
                interval_s=inputs.poll_interval_s,
                timeout_s=inputs.poll_timeout_s,
            )
            if isinstance(timed, CompletionTiming):
                timings.append(timed)
            else:
                timing_reasons.append(timed)
        elif entry.disconnected_at is not None:
            timing_reasons.append(
                f"{call_ref(execution_id)} carries a disconnect instant but "
                "`poll_for_completed` is false, so nothing was timed."
            )
        read = await read_execution(engine, execution_id)
        if isinstance(read, FidelityObservation):
            observations.append(read)
        else:
            unreadable.append(read)

    claims = {
        entry.call_ref: VendorCostClaim(
            call_ref=entry.call_ref,
            total=total,
            currency=entry.vendor_reported_currency,
        )
        for entry in wanted.values()
        if (total := _money(entry.vendor_reported_total)) is not None
    }
    expected = {
        entry.call_ref: tuple(entry.expects_extracted_fields)
        for entry in wanted.values()
        if entry.expects_extracted_fields
    }
    return evaluate_gate7(
        observations,
        unreadable=unreadable,
        timings=timings,
        timing_reasons=timing_reasons,
        vendor_claims=claims,
        expected_extraction=expected,
    )


GATES = {GATE_NUMBER: run_gate_7}


__all__ = [
    "ASSUMED_MINOR_UNITS_PER_MAJOR",
    "ASSUMED_SOURCE_CURRENCY",
    "CHECK_NAMES",
    "COMPLETED_AT_FINDING",
    "COST_COMPONENTS",
    "CURRENCY_FINDING",
    "DEFAULT_INPUTS_PATH",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_POLL_TIMEOUT_S",
    "GATES",
    "GATE_NUMBER",
    "GATE_TITLE",
    "INPUTS_ENV",
    "LEAD_SLO_S",
    "TRANSCRIPT_PARSE_FINDING",
    "CompletionTiming",
    "ExecutionInput",
    "ExecutionReader",
    "FidelityObservation",
    "Gate7Inputs",
    "Gate7InputsError",
    "TranscriptDefect",
    "UnreadableExecution",
    "VendorCostClaim",
    "evaluate_gate7",
    "load_gate7_inputs",
    "measure_time_to_completed",
    "observe",
    "read_execution",
    "run_gate_7",
    "transcript_defects",
]
