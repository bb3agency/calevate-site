"""The Bolna pilot scorecard: the RESULT CONTRACT, and the evidence document it renders.

    uv run python -m scripts.pilot.scorecard --out docs/evidence/bolna-pilot-scorecard.md
    uv run python -m scripts.pilot.scorecard --results run.json --check

ROADMAP gate G0 ("engine scorecard passed") is the first gate in the roadmap and has
never been attempted. OPERATIONS §2 lists the 13 gates; `docs/evidence/` is where the
answer has to live, because ENGINEERING-PRACTICES §2 makes vendor scorecards *evidence
artifacts*: committed, auditable, and usable as client-facing proof material.

What this module owns is the shape of an ANSWER. `scripts/pilot/runner.py` and the
per-gate modules beside it (gates_api, latency, concurrency, knowledge) produce
`GateResult`s; this module is the only place that decides what a result is allowed to
say, and the only place that turns results into the committed document.

FOUR PROPERTIES, EACH ONE A FAILURE MODE WE HAVE ALREADY SEEN
--------------------------------------------------------------
1. **"Not run" cannot be mistaken for "passed."** The template this replaces had two
   empty checkboxes per gate, so an unattempted gate and a green one rendered
   IDENTICALLY — a pre-launch checklist that can be ticked on nothing. Here NOT RUN is
   the default `Verdict`, it is printed in full words, and a `GateResult` that says NOT
   RUN may carry no measurements, no attestation and no artifacts at all: a gate nobody
   ran cannot look worked-on.

2. **The overall verdict is DERIVED and has no field.** `Scorecard` forbids extra keys,
   so "overall": "PASS" in a results file is a load error rather than a headline. The
   derivation is `derive_overall()`: a red HARD gate is FAIL regardless of everything
   else, and anything unrun or inconclusive among the hard gates is not a pass.

3. **A red hard gate is the loudest thing in the document.** OPERATIONS §2 and D-31: a
   failing hard gate reopens the engine decision, and *no fallback engine is
   designated*. That consequence is printed in the verdict block, not left as a
   footnote under a table.

4. **The human-only gates cannot be satisfied by a phone call.** Gates 9-12 (residency,
   agency model, support responsiveness, commercials) and the two listening gates (3, 5)
   are unautomatable, and they are the ones this company has actually been burned on:
   D-31 exists because ThinnestAI failed diligence, and gate 11 exists because
   unresponsive humans were the trap the first time. So a PASS on those gates REQUIRES
   an `Attestation` with a date, a named human and a source that is not
   `SourceKind.VERBAL`. "We asked and they said yes on a call" is recordable — as
   INCONCLUSIVE, which is what it is.

REDACTION: THIS FILE GOES INTO GIT FOREVER
--------------------------------------------
The gates handle real caller numbers, real transcripts and real recordings, and this
document is a sales-and-diligence artifact that leaves the building. Hard rules 5 and 6
apply to every line. Two mechanisms, both structural rather than procedural:

* `SafeText` — every free-text field runs the repo's own `redact()` detector and
  **rejects** rather than masks, and refuses any `scheme://` token outright (a recording
  URL cannot be pasted into a note; it has to become an `ArtifactRef`).
* `assert_no_pii()` — the whole rendered document is scanned once more before it is
  written, so a leak through a field nobody thought of (a gate title, an operator name,
  a fixture filename) still cannot reach the disk.

Why reject instead of mask here, when `record.py` masks: a vendor payload cannot be
rewritten, so masking is the only option there. Prose CAN be rewritten, and a document
full of `[redacted]` teaches operators that the notes field is a safe place to paste a
transcript. The error names the KIND that fired, never the value (hard rule 6).

DETERMINISM
-----------
Rendering the same results twice produces byte-identical output — no capture timestamp,
no dict iteration order, gates in registry order. A diligence artifact that changes on
re-render is not evidence, and `--check` (a rendered-vs-committed diff) only means
something if the renderer is a function of its inputs alone. That is also why there is
deliberately no "generated at" line, the obvious thing to put in a generated file: it
would make every re-render a diff and every history unreadable. The dates that belong
here are the ones the pilot produced (`observed_at`, `Attestation.dated`).

NEVER INVENT A MEASUREMENT
---------------------------
There is no "0" for an unmeasured field. A `Measurement` requires a value AND the method
that produced it, and a cost line with a measured amount requires the source document.
An absent number renders as "not measured" — the reader can tell the difference, which
is the entire value of the artifact to a reader doing diligence on US.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Self

from apps.workers.redaction import redact
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_OUT: Final = REPO_ROOT / "docs" / "evidence" / "bolna-pilot-scorecard.md"

# The regenerate command, printed into the document so the next reader can reproduce it.
# `check_docs_drift` verifies commands written in code spans actually resolve, which is
# why this string is built from the real module path rather than typed twice.
RENDER_COMMAND: Final = (
    "uv run python -m scripts.pilot.scorecard --out docs/evidence/bolna-pilot-scorecard.md"
)


class Verdict(StrEnum):
    """NOT_RUN is first and is the default. Ordering here is documentation, not logic —
    `derive_overall` states the precedence explicitly."""

    NOT_RUN = "NOT RUN"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAIL = "FAIL"
    PASS = "PASS"


class GateKind(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class EvidenceKind(StrEnum):
    """How a gate can be answered at all.

    The distinction is not decoration: it decides what `GateResult` demands before it
    will record a PASS. AUTOMATED gates are answered by a program against a live
    account; ATTESTED gates are answered by a human reading a written commitment;
    LISTENED gates are answered by a human with Telugu ears and a recording.
    """

    AUTOMATED = "automated"
    ATTESTED = "human attestation"
    LISTENED = "human listening"


class SourceKind(StrEnum):
    """Where an attestation's claim came from — the whole point of gate 12.

    VERBAL is deliberately representable. The failure mode is not that someone records a
    phone call; it is that a phone call gets recorded as a PASS and nobody can tell six
    months later. So VERBAL is allowed, and it caps the verdict at INCONCLUSIVE.
    """

    CONTRACT = "signed contract / order form"
    EMAIL = "email or ticket from the vendor"
    VENDOR_DOC = "vendor's own published document"
    INVOICE = "invoice or billing export"
    DASHBOARD_EXPORT = "exported from the vendor console"
    LISTENING_TEST = "recorded listening test"
    VERBAL = "verbal — call or meeting, nothing in writing"


NON_WRITTEN_SOURCES: Final = frozenset({SourceKind.VERBAL})


class EvidenceLeakError(Exception):
    """Raised when something that must never be committed reaches an evidence field.

    **Deliberately NOT a ValueError, which is the obvious choice.** pydantic converts a
    ValueError raised inside a validator into a `ValidationError` whose message embeds
    `input_value=<the offending text>` — so the tidy, idiomatic version of this class
    would take a caller's phone number out of the document and put it into the traceback,
    the terminal and the CI log, which are every bit as permanent (hard rule 6). An
    exception pydantic does not catch propagates unwrapped, and this message names the
    KIND that fired and never the value.

    It is also the right severity. A leak is not "input to fix and resubmit" alongside
    three other field errors; it is a stop.
    """


# `redact()` is this repo's authority on PII in prose and is reused rather than
# re-implemented — but it is tuned for MASKING a transcript, and a transcript is a
# different problem from a document. Its phone pattern cannot anchor on a number that
# carries its country code without a space (`+919876543210`: the `\b` it needs falls
# between two word characters), which is harmless when the goal is masking speech and is
# the single likeliest leak in a document where somebody pastes a number from a console.
# So the evidence artifact adds one stricter pattern rather than lowering its own bar to
# the one that already exists. `record.py` imports THIS regex; two spellings of "what a
# phone number looks like" is how one of them ends up wrong.
PHONE_IN_TEXT_RE: Final = re.compile(r"(?<!\d)(?:\+?0{0,2}91[ -]?)?[6-9]\d{9}(?!\d)")


def pii_kinds(text: str) -> list[str]:
    """Every kind of personal data detected in `text`. One detector, two callers (the
    field validator and the whole-document scan), so the document can never be checked
    more loosely than the fields inside it."""
    kinds = set(redact(text).kinds)
    if PHONE_IN_TEXT_RE.search(text):
        kinds.add("phone")
    return sorted(kinds)


def _no_pii(value: str) -> str:
    kinds = pii_kinds(value)
    if kinds:
        raise EvidenceLeakError(
            f"this text carries {', '.join(kinds)} and cannot be committed to "
            "an evidence artifact (hard rules 5/6). Describe what happened; do not "
            "quote the caller."
        )
    return value


def _no_url(value: str) -> str:
    # A recording URL is the single likeliest leak in this document, and it is not
    # phone-shaped, so `redact()` cannot see it. Refusing every scheme://token also
    # catches presigned links (which carry credentials in the query) and vendor console
    # deep links (which are account-scoped). Files belong in `ArtifactRef`.
    if "://" in value:
        raise EvidenceLeakError(
            "an evidence field may not contain a URL — record the file as an "
            "ArtifactRef (path + sha256) instead, so the document names it without "
            "embedding a link that may be presigned or account-scoped"
        )
    return value


def _safe_text(value: str) -> str:
    if not isinstance(value, str):
        # Reachable through the `Exact | SafeText` union on `Measurement.value`: pydantic
        # tries both branches, and a float must fail this one with a message rather than
        # an AttributeError from `.strip()`.
        raise ValueError("this field is free text")
    text = value.strip()
    if not text:
        raise ValueError("an evidence field may not be blank — omit it instead")
    return _no_pii(_no_url(text))


SafeText = Annotated[str, BeforeValidator(_safe_text)]


def _reject_float(value: Any) -> Any:
    # Hard rule 7. `Decimal(0.1)` is 0.1000000000000000055511151231257827, and a
    # measured unit price is the number that will be multiplied by every minute we ever
    # bill. pydantic would coerce a float here without complaint, so the refusal is
    # explicit and the caller has to decide what the exact value is.
    if isinstance(value, float):
        raise ValueError(
            "money and measured quantities are Decimal, never float (hard rule 7) — "
            "pass a string or a Decimal so the recorded value is exactly what was measured"
        )
    return value


Exact = Annotated[Decimal, BeforeValidator(_reject_float)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Measurement(_Frozen):
    """One number this pilot actually produced.

    `method` is required and that is the anti-invention lever: you cannot record
    `p95 = 1.8s` without saying it came from a stopwatch over 10 PSTN calls, which is
    exactly the sentence that would have stopped somebody copying the vendor's marketing
    figure into the box (OPERATIONS §2 gate 4: "vendor latency claims are marketing").

    There is no representation of an unmeasured quantity. An absent measurement is an
    absent key — never a zero.
    """

    name: SafeText
    value: Exact | SafeText
    unit: SafeText | None = None
    method: SafeText
    sample_n: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _money_is_numeric(self) -> Self:
        is_money = bool(self.unit) and str(self.unit).upper().startswith("INR")
        if is_money and not isinstance(self.value, Decimal):
            raise ValueError(f"{self.name!r} is money and must be a Decimal (hard rule 7)")
        return self


class Attestation(_Frozen):
    """A human's answer, with the receipt attached.

    Four required parts, and every one of them is a question somebody failed to ask the
    last time: WHO attested, WHEN, WHAT KIND of source, and WHERE that source is. A
    claim without a locatable source is not evidence; it is a memory.
    """

    statement: SafeText
    source_kind: SourceKind
    # Where the source lives: a repo path under docs/evidence/, an object-storage key,
    # or a ticket id. Not a URL — see `_no_url`.
    source_ref: SafeText
    dated: date
    attested_by: SafeText

    @property
    def is_written(self) -> bool:
        return self.source_kind not in NON_WRITTEN_SOURCES


class ArtifactRef(_Frozen):
    """A captured file, named by path and content hash rather than by link.

    The hash is what makes the scorecard checkable a year later: a fixture that has been
    edited since the pilot no longer matches the document that cites it.
    """

    path: SafeText
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    describes: SafeText

    @field_validator("path")
    @classmethod
    def _repo_relative(cls, value: str) -> str:
        if value.startswith("/") or ".." in value:
            raise ValueError("artifact paths are repo-relative and may not escape the tree")
        return value


class GateSpec(_Frozen):
    """One row of OPERATIONS §2, as data. Titles are ours and deliberately short; the
    authoritative criteria stay in the doc, which this document cites rather than
    duplicates (two copies of a pass criterion is one copy that goes stale)."""

    id: int
    title: str
    kind: GateKind
    evidence: EvidenceKind
    asks: str


# OPERATIONS §2, in its own order. 10 hard gates, 3 soft.
GATES: Final[dict[int, GateSpec]] = {
    spec.id: spec
    for spec in (
        GateSpec(
            id=1,
            title="Webhook trust",
            kind=GateKind.HARD,
            evidence=EvidenceKind.AUTOMATED,
            asks=(
                "deliveries arrive only from the documented egress address, the allowlist "
                "rejects everything else, execution_id dedupes, and the payload matches "
                "Get Execution"
            ),
        ),
        GateSpec(
            id=2,
            title="Full API provisioning",
            kind=GateKind.HARD,
            evidence=EvidenceKind.AUTOMATED,
            asks=(
                "agent -> prompt -> number -> call -> execution, by API only; user_data "
                "round-trips into the prompt; scheduled_at works"
            ),
        ),
        GateSpec(
            id=3,
            title="Telugu quality (BYOK)",
            kind=GateKind.HARD,
            evidence=EvidenceKind.LISTENED,
            asks=(
                "names and numbers >=90% correct on a 10-utterance Telugu script over real "
                "PSTN, code-mixed handled, and Bulbul V3 selectable"
            ),
        ),
        GateSpec(
            id=4,
            title="Real-call latency",
            kind=GateKind.HARD,
            evidence=EvidenceKind.AUTOMATED,
            asks=(
                "voice-to-voice p50 <= 1.1s and p95 <= 1.8s over 10 PSTN calls, measured by "
                "us; first-greeting delay recorded separately; the engine's own latency_data "
                "captured and compared against the stopwatch"
            ),
        ),
        GateSpec(
            id=5,
            title="Telugu turn-taking",
            kind=GateKind.HARD,
            evidence=EvidenceKind.LISTENED,
            asks=(
                "barge-in mid-sentence and end-of-utterance on slow, hesitant Telugu: does it "
                "cut callers off, or leave dead air? An orchestration property BYOK does not fix"
            ),
        ),
        GateSpec(
            id=6,
            title="Webhook loss behaviour",
            kind=GateKind.HARD,
            evidence=EvidenceKind.AUTOMATED,
            asks=(
                "kill the receiver mid-call: the call continues, no retry arrives, and the "
                "List-Executions poller recovers every missed execution"
            ),
        ),
        GateSpec(
            id=7,
            title="Post-call data fidelity",
            kind=GateKind.SOFT,
            evidence=EvidenceKind.AUTOMATED,
            asks=(
                "cost, recording and extracted data present at `completed`; currency "
                "confirmed; transcript parses into TranscriptTurn; time-to-completed against "
                "the 2-minute lead SLO"
            ),
        ),
        GateSpec(
            id=8,
            title="KB, campaigns, tools, history",
            kind=GateKind.SOFT,
            evidence=EvidenceKind.AUTOMATED,
            asks=(
                "Telugu retrieval quality and latency in the built-in KB; tool-call p95; a "
                "10-contact batch; whether the KB listing carries the agent linkage and "
                "whether deleting a KB clears the agent's reference; history truncation and "
                "context caching on BYOK"
            ),
        ),
        GateSpec(
            id=9,
            title="Compute region + data residency",
            kind=GateKind.HARD,
            evidence=EvidenceKind.ATTESTED,
            asks=(
                "where the call actually executes, and India data-residency terms and price "
                "IN WRITING (recordings on US storage is a separate fact from compute)"
            ),
        ),
        GateSpec(
            id=10,
            title="Agency model + sub-accounts tier",
            kind=GateKind.HARD,
            evidence=EvidenceKind.ATTESTED,
            asks=(
                "multiple end-clients under one account permitted, in writing; and which tier "
                "actually includes sub-accounts — the pricing page and the docs disagree, and "
                "if the lower tier includes it our tenancy model lands far earlier"
            ),
        ),
        GateSpec(
            id=11,
            title="The humans",
            kind=GateKind.HARD,
            evidence=EvidenceKind.ATTESTED,
            asks=(
                "two support threads opened during the pilot, one technical and one "
                "commercial: time to first USEFUL answer and the quality of it. This is the "
                "gate the previous vendor failed"
            ),
        ),
        GateSpec(
            id=12,
            title="Commercials in writing",
            kind=GateKind.HARD,
            evidence=EvidenceKind.ATTESTED,
            asks=(
                "the BYOK platform fee (the single number that decides our unit economics), "
                "volume tiers, INR/GST invoicing, price-change notice, export on exit, "
                "recording retention and deletion, and whether the built-in KB is billed "
                "separately or included — an inference that is currently load-bearing"
            ),
        ),
        GateSpec(
            id=13,
            title="Concurrency ceiling",
            kind=GateKind.SOFT,
            evidence=EvidenceKind.AUTOMATED,
            asks=(
                "our ceiling, the behaviour at the limit (queue or reject, and the error "
                "shape), the outbound dispatch rate limit, and the model and trunk ceilings "
                "beside it — the effective ceiling is the minimum of all three"
            ),
        ),
    )
}

HARD_GATE_IDS: Final = tuple(g.id for g in GATES.values() if g.kind is GateKind.HARD)
SOFT_GATE_IDS: Final = tuple(g.id for g in GATES.values() if g.kind is GateKind.SOFT)


class GateResult(_Frozen):
    """What one gate produced. This is the type the per-gate modules write.

    The validators below are the contract, and each closes a way of recording something
    the pilot did not establish.
    """

    gate: int
    verdict: Verdict = Verdict.NOT_RUN
    observed_at: datetime | None = None
    operator: SafeText | None = None
    summary: SafeText | None = None
    measurements: tuple[Measurement, ...] = ()
    attestation: Attestation | None = None
    artifacts: tuple[ArtifactRef, ...] = ()

    @field_validator("gate")
    @classmethod
    def _known_gate(cls, value: int) -> int:
        if value not in GATES:
            raise ValueError(f"gate {value} is not in OPERATIONS §2 (gates 1-13)")
        return value

    @field_validator("observed_at")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware (UTC in storage, IST at the edge)")
        return value

    @property
    def spec(self) -> GateSpec:
        return GATES[self.gate]

    @model_validator(mode="after")
    def _a_result_says_only_what_it_can_show(self) -> Self:
        if self.verdict is Verdict.NOT_RUN:
            # A gate nobody ran must not be able to look worked-on. Half-filled evidence
            # under a NOT RUN heading is how the reader's eye starts treating the two as
            # the same row, which is the exact defect in the template this replaces.
            carried = {
                "observed_at": self.observed_at,
                "operator": self.operator,
                "summary": self.summary,
                "measurements": self.measurements or None,
                "attestation": self.attestation,
                "artifacts": self.artifacts or None,
            }
            present = sorted(k for k, v in carried.items() if v)
            if present:
                raise ValueError(
                    f"gate {self.gate} is NOT RUN but carries {', '.join(present)} — "
                    "a gate that produced something is INCONCLUSIVE at worst, never NOT RUN"
                )
            return self

        if self.observed_at is None or self.operator is None:
            raise ValueError(
                f"gate {self.gate} records a {self.verdict} verdict without observed_at "
                "and operator — an unattributed, undated result is not evidence"
            )

        if self.spec.evidence is not EvidenceKind.AUTOMATED and self.verdict is Verdict.PASS:
            if self.attestation is None:
                raise ValueError(
                    f"gate {self.gate} ({self.spec.title}) is a {self.spec.evidence} gate: "
                    "a PASS needs an Attestation naming who, when and from what source"
                )
            if not self.attestation.is_written:
                raise ValueError(
                    f"gate {self.gate} ({self.spec.title}) cannot PASS on a "
                    f"{self.attestation.source_kind}. Record it as INCONCLUSIVE: "
                    "'we asked and they said yes on a call' is what D-31's due diligence "
                    "failure looked like from the inside"
                )
        return self


class CostLine(_Frozen):
    """One leg of the measured cost model that replaces TRD §10's estimates.

    `measured_inr_per_min` is optional and absent means NOT MEASURED. It renders as a
    dash, never as zero — a zero here would become a wrong unit price in the ledger
    forever. A measured amount requires the document it came from.
    """

    leg: SafeText
    estimate: SafeText
    measured_inr_per_min: Exact | None = None
    source: SafeText | None = None

    @model_validator(mode="after")
    def _measured_needs_a_source(self) -> Self:
        if self.measured_inr_per_min is not None and not self.source:
            raise ValueError(
                f"the measured cost of {self.leg!r} must name its source (invoice, quote, "
                "rate card) — an unsourced price cannot be defended in a billing dispute"
            )
        if self.measured_inr_per_min is not None and self.measured_inr_per_min < 0:
            raise ValueError("a measured cost cannot be negative")
        return self


def default_cost_model() -> tuple[CostLine, ...]:
    """The legs OPERATIONS §2 and TRD §10 name, with nothing measured yet.

    Estimates are quoted as text so nobody can mistake one for a measurement: the
    estimate column is prose, the measured column is a Decimal or absent.
    """
    return (
        CostLine(leg="Platform fee (BYOK)", estimate="unpublished; target <= ~INR 1.5/min"),
        CostLine(leg="Sarvam Saaras V3 STT", estimate="INR 0.50/min"),
        CostLine(leg="Sarvam Bulbul V3 TTS", estimate="INR 0.90-1.40/min (beta pricing)"),
        CostLine(leg="LLM", estimate="INR 0.00 (Sarvam 105B per D-36); Gemini fallback 0.15-0.20"),
        CostLine(leg="Telephony", estimate="INR 0.35-0.50/min"),
        CostLine(
            leg="Built-in KB",
            estimate="INR 0 - INFERRED included in the platform fee (D-33)",
        ),
        CostLine(leg="All-in", estimate="target INR 3.0-3.6/min"),
    )


class Scorecard(_Frozen):
    """A whole pilot run.

    There is no `overall` field, and `extra="forbid"` means a results file that tries to
    supply one fails to load rather than being quietly believed. The verdict is a
    function of the results; the only way to change it is to change a gate.
    """

    engine: SafeText = "Bolna"
    run_by: SafeText | None = None
    window_start: date | None = None
    window_end: date | None = None
    spend_inr: Exact | None = None
    results: tuple[GateResult, ...]
    cost_model: tuple[CostLine, ...] = Field(default_factory=default_cost_model)
    open_items: tuple[SafeText, ...] = ()

    @model_validator(mode="after")
    def _covers_every_gate_exactly_once(self) -> Self:
        seen = [r.gate for r in self.results]
        if sorted(seen) != sorted(GATES):
            missing = sorted(set(GATES) - set(seen))
            duplicated = sorted({g for g in seen if seen.count(g) > 1})
            raise ValueError(
                "a scorecard reports every gate exactly once "
                f"(missing: {missing or 'none'}; duplicated: {duplicated or 'none'}) — "
                "a gate omitted from the file is a gate omitted from the reader's attention"
            )
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("the pilot window ends before it starts")
        return self

    @property
    def by_gate(self) -> dict[int, GateResult]:
        return {r.gate: r for r in self.results}

    @property
    def overall(self) -> Verdict:
        return derive_overall(self.results)

    @classmethod
    def not_yet_run(cls, **kwargs: Any) -> Scorecard:
        """The honest state of G0 today: 13 gates, none attempted."""
        return cls(results=tuple(GateResult(gate=g) for g in sorted(GATES)), **kwargs)


def derive_overall(results: Sequence[GateResult]) -> Verdict:
    """The whole-scorecard verdict. Hard gates decide it; soft gates shape M1 scope.

    Precedence, loudest first:

    * any HARD gate FAIL  -> FAIL. It stays FAIL even if other hard gates are unrun,
      because the consequence (the engine decision reopens) has already been triggered
      and adding "...and we did not finish" would soften a conclusion that is reached.
    * any HARD gate INCONCLUSIVE -> INCONCLUSIVE.
    * any HARD gate NOT RUN -> NOT RUN.
    * otherwise -> PASS.

    Rejected alternative: scoring soft gates into the total (e.g. "PASS with
    reservations"). OPERATIONS §2 is explicit that a soft gate shapes scope rather than
    the engine choice, and a verdict that mixes the two would make the one sentence this
    document exists to say — *is Bolna adopted or not* — ambiguous.
    """
    hard = [r.verdict for r in results if GATES[r.gate].kind is GateKind.HARD]
    if not hard:
        raise ValueError("no hard gates present — this is not a pilot scorecard")
    for verdict in (Verdict.FAIL, Verdict.INCONCLUSIVE, Verdict.NOT_RUN):
        if verdict in hard:
            return verdict
    return Verdict.PASS


# --- the seam with the gate runner ---------------------------------------------


def from_runner_result(
    ran: Any,
    *,
    observed_at: datetime,
    operator: str,
    attestation: Attestation | None = None,
    artifacts: Sequence[ArtifactRef] = (),
) -> GateResult:
    """Convert a `scripts.pilot.results.GateResult` (the gate runner's shape) into ours.

    **This is a MIGRATION SHIM and should not outlive the pilot.** Two result types for
    one question is a defect even while both work, and this repo's rule is to migrate
    rather than accumulate. It exists because the runner slice and this one landed in the
    same wave: the runner's type is per-SUB-CHECK (which half of gate 2 failed — real
    information this type does not hold), and this one is per-ARTIFACT (provenance,
    attestation, the derived headline). The end state is one type carrying both halves;
    until then everything renders through here, and nothing renders around it.

    Two conversions are judgements rather than mappings, and both are deliberate:

    * **not-run vs inconclusive.** The runner has three statuses, so a gate that was
      BLOCKED and a gate that ran half its checks are both `not_run`. Here they differ:
      blocked (or nothing attempted) is NOT RUN; partially executed is INCONCLUSIVE,
      because something was produced and a reader must not see it filed beside a gate
      nobody touched. This type would refuse the alternative anyway — a NOT RUN result
      may carry no measurements.
    * **an attested pass with no written source is downgraded, not refused.** The runner
      cannot invent an attestation, and the human gates require one (see `GateResult`).
      Raising here would make the whole scorecard unrenderable because a human has not
      emailed anyone yet, so the verdict drops to INCONCLUSIVE and the summary says why.
      Silent acceptance is the one option that is not available.

    The import is function-local on purpose: this module renders results from a JSON file
    perfectly well without the runner present, and a top-level import would couple the
    committed artifact's renderer to a sibling slice's file surviving.
    """
    from scripts.pilot.results import GateRun

    if not isinstance(ran, GateRun):
        raise TypeError(f"expected a scripts.pilot.results.GateResult, got {type(ran).__name__}")

    spec = GATES[ran.number]
    executed = [c for c in ran.checks if c.status != "not_run"]
    status = ran.status

    if status == "pass":
        verdict = Verdict.PASS
    elif status == "fail":
        verdict = Verdict.FAIL
    elif ran.blocked is not None or not executed:
        verdict = Verdict.NOT_RUN
    else:
        verdict = Verdict.INCONCLUSIVE

    notes: list[str] = []
    if (
        verdict is Verdict.PASS
        and spec.evidence is not EvidenceKind.AUTOMATED
        and (attestation is None or not attestation.is_written)
    ):
        verdict = Verdict.INCONCLUSIVE
        notes.append(
            "downgraded from the runner's PASS: this gate needs a dated written "
            "source and none is on file"
        )

    if verdict is Verdict.NOT_RUN:
        # Nothing may be carried: the type enforces it, and the reason belongs in the
        # runner's own JSON, which is kept beside this document.
        return GateResult(gate=ran.number)

    notes.append(
        f"{len(executed)} of {len(ran.checks)} sub-checks executed; "
        + ", ".join(f"{c.name}={c.status}" for c in ran.checks)
    )
    notes.extend(f"finding: {f}" for f in ran.findings)

    measurements = tuple(
        Measurement(
            name=key,
            # A float is exact-converted through its repr rather than rejected: the
            # runner's latency numbers are legitimately floats, and `Exact` exists to
            # stop a float becoming a PRICE. Money already arrives as a Decimal.
            value=Decimal(str(value)) if isinstance(value, float | int | Decimal) else str(value),
            method=f"gate {ran.number} sub-check {check.name}",
        )
        for check in ran.checks
        for key, value in check.measurements.items()
    )

    return GateResult(
        gate=ran.number,
        verdict=verdict,
        observed_at=observed_at,
        operator=operator,
        summary=" · ".join(notes),
        measurements=measurements,
        attestation=attestation,
        artifacts=tuple(artifacts),
    )


# --- rendering ----------------------------------------------------------------

_VERDICT_CELL: Final[dict[Verdict, str]] = {
    Verdict.PASS: "**PASS**",
    Verdict.FAIL: "**FAIL**",
    Verdict.INCONCLUSIVE: "INCONCLUSIVE",
    Verdict.NOT_RUN: "_NOT RUN_",
}

_CONSEQUENCE: Final[dict[Verdict, str]] = {
    Verdict.PASS: (
        "G0 is CLOSED. Bolna is adopted as the primary engine under D-31; A-1/A-8 close with it."
    ),
    Verdict.FAIL: (
        "**THE ENGINE DECISION REOPENS.** A red hard gate is not a to-do item: D-31 "
        "designates NO fallback engine, so the next step is an engine selection, not a "
        "retry. Do not begin M1 client work against this engine until this is resolved."
    ),
    Verdict.INCONCLUSIVE: (
        "G0 is NOT closed. At least one hard gate produced a result nobody can act on. "
        "An inconclusive hard gate is not a soft pass — it is an unanswered question "
        "about the engine every client call will run on."
    ),
    Verdict.NOT_RUN: (
        "G0 is NOT closed and has not been attempted. Nothing below has been measured. "
        "This document is a plan, not evidence."
    ),
}


def _cell(text: str) -> str:
    """Markdown table cells: a pipe or a newline in prose silently breaks the table, and
    a broken table hides rows — which in this document means hiding a gate."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _fmt_measurement(m: Measurement) -> str:
    value = f"{m.value:f}" if isinstance(m.value, Decimal) else str(m.value)
    unit = f" {m.unit}" if m.unit else ""
    sample = f", n={m.sample_n}" if m.sample_n else ""
    return f"{m.name}: {value}{unit} ({m.method}{sample})"


def _gate_evidence(result: GateResult) -> str:
    if result.verdict is Verdict.NOT_RUN:
        return "_no evidence — this gate has not been attempted_"
    parts: list[str] = []
    if result.summary:
        parts.append(result.summary)
    parts.extend(_fmt_measurement(m) for m in result.measurements)
    if result.attestation is not None:
        a = result.attestation
        parts.append(
            f"attested by {a.attested_by} on {a.dated.isoformat()} "
            f"[{a.source_kind}: {a.source_ref}] — {a.statement}"
        )
    parts.extend(
        f"artifact `{a.path}` ({a.describes}, sha256 {a.sha256[:12]})" for a in result.artifacts
    )
    return " · ".join(parts) if parts else "_recorded with no detail_"


def _gate_table(scorecard: Scorecard, gate_ids: Sequence[int]) -> list[str]:
    lines = [
        "| # | Gate | How it can be answered | Verdict | Evidence |",
        "|---|---|---|---|---|",
    ]
    by_gate = scorecard.by_gate
    for gate_id in gate_ids:
        spec = GATES[gate_id]
        result = by_gate[gate_id]
        lines.append(
            f"| {gate_id} | **{_cell(spec.title)}** — {_cell(spec.asks)} "
            f"| {spec.evidence} | {_VERDICT_CELL[result.verdict]} "
            f"| {_cell(_gate_evidence(result))} |"
        )
    return lines


def _counts(scorecard: Scorecard, gate_ids: Sequence[int]) -> str:
    by_gate = scorecard.by_gate
    tally = {v: sum(1 for g in gate_ids if by_gate[g].verdict is v) for v in Verdict}
    return ", ".join(f"{tally[v]} {v.lower()}" for v in Verdict if tally[v])


def render(scorecard: Scorecard) -> str:
    """Render the committed evidence document. Pure: same input, same bytes."""
    overall = scorecard.overall
    spend = f"INR {scorecard.spend_inr:f}" if scorecard.spend_inr is not None else "_not recorded_"
    lines: list[str] = [
        "# Bolna Pilot Scorecard — EVIDENCE ARTIFACT",
        "",
        "<!-- GENERATED FILE — do not hand-edit. -->",
        f"<!-- Regenerate: {RENDER_COMMAND} -->",
        "",
        "Gates and pass criteria: OPERATIONS.md §2 (authoritative — this document reports "
        "results, it does not restate criteria). Decisions: D-31 (Bolna primary, no "
        "fallback engine designated), D-32 (evaluation doctrine). Committed under "
        'ENGINEERING-PRACTICES §2 ("evidence artifacts": DR drills, stress runs and '
        "vendor scorecards live in the repo).",
        "",
        "This file is generated from typed gate results by "
        f"`{RENDER_COMMAND}`. The verdict below is DERIVED from the gate rows — it is not "
        "a field anybody can set, and a hard gate that is red or unrun cannot sit under a "
        "green headline.",
        "",
        "It contains no caller numbers, no transcript text and no recording links, by "
        "construction rather than by care: every free-text field is refused at "
        "construction if it carries PII or a URL, and the whole rendered document is "
        "re-scanned before it is written (hard rules 5 and 6).",
        "",
        "---",
        "",
        f"## VERDICT: {overall} — {'G0 CLOSED' if overall is Verdict.PASS else 'G0 NOT CLOSED'}",
        "",
        _CONSEQUENCE[overall],
        "",
        f"- Hard gates ({len(HARD_GATE_IDS)}): {_counts(scorecard, HARD_GATE_IDS)}",
        f"- Soft gates ({len(SOFT_GATE_IDS)}): {_counts(scorecard, SOFT_GATE_IDS)}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Engine under test | {_cell(scorecard.engine)} |",
        f"| Run by | {_cell(scorecard.run_by) if scorecard.run_by else '_not recorded_'} |",
        f"| Window | {_window(scorecard)} |",
        f"| Spend | {spend} |",
        "",
        "## Hard gates — a red one reopens the engine decision",
        "",
    ]
    lines += _gate_table(scorecard, HARD_GATE_IDS)
    lines += [
        "",
        "## Soft gates — these shape M1 scope, not the engine choice",
        "",
    ]
    lines += _gate_table(scorecard, SOFT_GATE_IDS)
    lines += [
        "",
        "## The gates no program can answer",
        "",
        "Gates 9, 10, 11 and 12 are human-attestation gates and gates 3 and 5 need a human "
        "listening to Telugu. They are recorded here separately because they are the ones "
        "this company has been burned on: the previous vendor passed a demo and failed "
        "diligence (D-31), and gate 11 exists because unresponsive humans were that trap. "
        "A PASS on any row below is refused by the result type unless it carries a dated "
        "attestation from a written source — a verbal assurance is recordable, and it caps "
        "the gate at INCONCLUSIVE.",
        "",
        "| # | Gate | Verdict | Attested by | Dated | Source |",
        "|---|---|---|---|---|---|",
    ]
    for gate_id in sorted(GATES):
        spec = GATES[gate_id]
        if spec.evidence is EvidenceKind.AUTOMATED:
            continue
        result = scorecard.by_gate[gate_id]
        a = result.attestation
        lines.append(
            f"| {gate_id} | {_cell(spec.title)} | {_VERDICT_CELL[result.verdict]} "
            f"| {_cell(a.attested_by) if a else '—'} "
            f"| {a.dated.isoformat() if a else '—'} "
            f"| {_cell(f'{a.source_kind}: {a.source_ref}') if a else '_no source on file_'} |"
        )

    lines += [
        "",
        "## Measured cost model (replaces the estimates in TRD §10)",
        "",
        "A blank measured cell means NOT MEASURED. It is never zero: a zero here becomes a "
        "wrong unit price in every ledger row we ever write (hard rule 7).",
        "",
        "| Leg | Estimated (pre-pilot) | Measured (INR/min) | Source |",
        "|---|---|---|---|",
    ]
    for line in scorecard.cost_model:
        measured = (
            f"**{line.measured_inr_per_min:f}**"
            if line.measured_inr_per_min is not None
            else "_not measured_"
        )
        lines.append(
            f"| {_cell(line.leg)} | {_cell(line.estimate)} | {measured} "
            f"| {_cell(line.source) if line.source else '—'} |"
        )
    lines += [
        "",
        "BYOK legs (STT + TTS + LLM) are identical on every platform and are NOT a decision "
        "variable (D-32). Only the platform fee row and gate 4's latency decide.",
        "",
        "## Captured artifacts",
        "",
    ]
    artifacts = [(g, a) for g in sorted(GATES) for a in scorecard.by_gate[g].artifacts]
    if artifacts:
        lines += ["| Gate | Path | Describes | sha256 |", "|---|---|---|---|"]
        lines += [
            f"| {gate_id} | `{_cell(a.path)}` | {_cell(a.describes)} | `{a.sha256}` |"
            for gate_id, a in artifacts
        ]
    else:
        lines.append(
            "_None captured._ Gates 1, 2, 4, 7 and 8 each require a payload captured as an "
            "adapter conformance fixture; `scripts/pilot/record.py` is what writes them, and "
            "it redacts on the way in."
        )
    lines += [
        "",
        "## Parallel asks to Sarvam (not Bolna gates, and they move the cost model more)",
        "",
        # Carried forward from the template this file replaces. They are NOT gates — no
        # verdict, no bearing on G0 — but dropping them when the template went away would
        # have quietly closed three questions that are still open, and OPERATIONS §2 asks
        # them beside the pilot precisely because the same week is when they get answered.
        '- Is the Sarvam LLM\'s "free per token" permanent, promotional or rate-limited? '
        "D-35 read it live from the published rate card; what is unconfirmed is what "
        "happens ON OUR ACCOUNT and at the rate-limit ceiling.",
        "- Is Bulbul V3's beta rate committed or introductory? Beta prices move, and D-36 "
        "makes v3 the default with v2 as the value tier.",
        "- Convert the plan rate limits (rpm) into concurrent calls at our turn rate, and "
        "confirm which plan we need — this is a concurrency input to gate 13, not a price "
        "input (D-35).",
        "- Telugu ear test, v3 vs v2, same script and same voice: if v2 is acceptable, the "
        "value tier halves the TTS leg (TRD §10.1).",
        "",
        "## Open items carried forward",
        "",
    ]
    if scorecard.open_items:
        lines += [f"- {item}" for item in scorecard.open_items]
    else:
        lines.append("_None recorded._")
    lines.append("")

    document = "\n".join(lines)
    assert_no_pii(document)
    return document


def _window(scorecard: Scorecard) -> str:
    if scorecard.window_start and scorecard.window_end:
        return f"{scorecard.window_start.isoformat()} to {scorecard.window_end.isoformat()}"
    if scorecard.window_start:
        return f"from {scorecard.window_start.isoformat()}"
    return "_not recorded_"


def assert_no_pii(document: str) -> None:
    """The last gate before disk.

    Field-level validation covers the fields we thought of. This covers the document: a
    gate title, an operator's name, a fixture filename or a future section could all
    carry a number, and this file is committed forever. Cheap, and the one check whose
    absence is unrecoverable.
    """
    kinds = pii_kinds(document)
    if kinds:
        raise EvidenceLeakError(
            f"the rendered scorecard carries {', '.join(kinds)} — refusing to "
            "write it (hard rules 5/6). The offending value is deliberately not printed."
        )


def load_results(path: Path) -> Scorecard:
    """Load a results file produced by the pilot runner.

    Errors are part of the interface: a malformed file says which file and what pydantic
    objected to, because the operator reading this message is mid-pilot with a vendor
    account that costs money to re-run.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read pilot results from {path}: {exc}") from exc
    try:
        return Scorecard.model_validate(raw)
    except EvidenceLeakError as exc:
        # Not folded into the ValueError branch: a leak is a different instruction to the
        # operator ("rewrite the sentence, it names a caller") than a schema error, and
        # its message is the one that must not be decorated with the input.
        raise SystemExit(f"{path} cannot be rendered — {exc}") from exc
    except ValueError as exc:
        raise SystemExit(f"{path} is not a valid pilot result set:\n{exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--results",
        type=Path,
        help="JSON results produced by the pilot runner. Omit to render the honest "
        "not-yet-run scorecard (which is the current state of G0).",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the document")
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the committed document differs from what the "
        "results render to (drift guard)",
    )
    args = parser.parse_args(argv)

    scorecard = load_results(args.results) if args.results else Scorecard.not_yet_run()
    document = render(scorecard)

    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != document:
            print(f"{args.out} is stale — regenerate with: {RENDER_COMMAND}", file=sys.stderr)
            return 1
        print(f"{args.out} matches the results ({scorecard.overall}).")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(document, encoding="utf-8")
    print(
        f"wrote {args.out} — verdict {scorecard.overall} "
        f"(derived from {len(scorecard.results)} gates)"
    )
    return 0


__all__ = [
    "GATES",
    "HARD_GATE_IDS",
    "SOFT_GATE_IDS",
    "ArtifactRef",
    "Attestation",
    "CostLine",
    "EvidenceKind",
    "EvidenceLeakError",
    "GateKind",
    "GateResult",
    "GateSpec",
    "Measurement",
    "Scorecard",
    "SourceKind",
    "Verdict",
    "assert_no_pii",
    "derive_overall",
    "render",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
