"""OUR normalized usage, metered off the pipeline we run (`docs/PIPECAT-MIGRATION.md` §1.3).

Under a rented engine one vendor invoice priced the minute and `workers/pipeline.py::_meter`
converted it. There is no such invoice here: we run the loop, so `unit_cost_paid` becomes the
SUM OF FIVE INDEPENDENTLY METERED LEGS, and the honest consequence — five refusals where
there was one — is the whole subject of this module.

**NOTHING HERE DEFAULTS A LEG TO ZERO.** A silent ₹0 leg is a margin we think we have and do
not: it produces `usage_events` rows that reconcile against nothing and is discovered when
somebody compares a vendor invoice to a month of ledger. Every leg this module cannot price
raises a named refusal an operator can act on, exactly as `billing/rates.py::llm_inr_per_ktok`
already does for the model it does not know.

WHAT EACH LEG IS METERED FROM, and where the runtime signal was read (pipecat-ai 1.10.0 at
`f67c18af`, the tree `docs/evidence/pipecat-api-surface-2026-09-13.md` cites; paths relative
to `/home/user/pipecat-ai/pipecat/`):

- **carrier** — connected seconds. **No runtime signal: this is not ours to witness.**
  Supplied as a `CarrierCdr` (§1.2).
- **runtime** — Pipecat active minutes. **No runtime signal, and UNKNOWN what one bills.**
  Supplied as a `RuntimeUsage` (§7).
- **stt** — audio seconds, from `STTUsage.audio_seconds`
  (`src/pipecat/metrics/metrics.py:161-178`), accumulated at
  `src/pipecat/services/stt_service.py:251` and flushed to a metrics frame at `:253-267`.
- **tts** — characters synthesised, from `TTSUsageMetricsData.value`, an `int`
  (`src/pipecat/metrics/metrics.py:191-198`), counted as `len(text)` at
  `src/pipecat/processors/metrics/frame_processor_metrics.py:358-370`.
- **llm** — `LLMTokenUsage.total_tokens`, from `LLMUsageMetricsData`
  (`src/pipecat/metrics/metrics.py:109-158`), built at
  `src/pipecat/services/openai/base_llm.py:498-505` and reported at `:566`.

All five arrive as `ServiceUsageRecord` from Pipecat's `ServiceMetricsObserver`
(`src/pipecat/observers/service_metrics_observer.py:78-118`, `:229-264`) — for the three we
CAN witness. The other two are named above as absences and are inputs, not observations.

**THE TWO THAT ARE NOT OURS TO WITNESS, AND WHY THAT IS THE POINT.**

*Carrier* (§1.2): the party that billed the minute owns the facts — connected, duration,
disposition, which number rang. Metering the billable quantity against our own clock is
precisely what §1.2 rejects, and it would be trivial to do here (the pipeline knows when it
started). So this module has no clock reading at all: no `CarrierCdr`, no carrier row, a
refusal instead.

*Runtime* (§7, and §3.5 P-1 of `docs/evidence/pre-build-blockers-2026-09-13.md`): **what a
Pipecat Cloud "active minute" covers is UNKNOWN** — connected time, or container start and
teardown as well; and how many minutes a 3-minute call bills is the open question. It is not
priced here with a plausible number. It is supplied by a human who read the invoice, or the
leg raises.

**HARD RULE 2.** `ServiceUsageRecord` is a Pipecat shape and it stops at this module's door:
what leaves is `UsageRow`, ours, and nothing downstream of it learns Pipecat exists.

**HARD RULE 7.** `Decimal` throughout, INR throughout, and no rate is invented here — see
`RateCard` below for the one door a rupee comes through and for the boundary that keeps this
module from importing `apps.api.billing.rates` directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pipecat.observers.service_metrics_observer import (
    ServiceMetricsObserver,
    ServiceUsageKind,
    ServiceUsageRecord,
)

__all__ = [
    "UNIT_LLM_KTOK_IN",
    "UNIT_LLM_KTOK_OUT",
    "UNIT_PLATFORM_MIN",
    "UNIT_STT_S",
    "UNIT_TELEPHONY_S",
    "UNIT_TTS_KCHARS",
    "CallMeter",
    "CarrierCdr",
    "CarrierFactsMissingError",
    "LegNotMeterableError",
    "LlmModelAmbiguousError",
    "LlmModelUnnamedError",
    "LlmTotalTokensMissingError",
    "MeteredLeg",
    "RateCard",
    "RateCardMissingError",
    "RateRefusedError",
    "RuntimePriceUnknownError",
    "RuntimeUsage",
    "TokenUsageNotComparableError",
    "UsageRow",
]


# --- the five legs, in OUR vocabulary -------------------------------------------------


class MeteredLeg(StrEnum):
    """The five legs §1.3 sums. Named here rather than in prose so a refusal can say which.

    This is not `ServiceUsageKind` with two extra members: that enum has exactly the three
    kinds Pipecat can report, which is the distinction this module exists to make.
    """

    CARRIER = "carrier"
    RUNTIME = "runtime"
    STT = "stt"
    TTS = "tts"
    LLM = "llm"


# --- the ledger's unit tokens ---------------------------------------------------------
#
# NAMED, not spelled at each construction site, because `usage_events` is append-only under
# hard rule 4: a row's `unit_type` can never be corrected by an UPDATE, so a typo at one of
# five call sites is permanent and re-files a leg into `other` forever.
#
# FOUR OF THESE ARE ALREADY IN `apps/api/billing/models.CLIENT_BILLED_UNIT_TYPES` AND TWO
# ARE NOT. `llm_ktok_in` / `llm_ktok_out` are REQUESTED, not assumed — the enum is rendered
# verbatim into `ck_usage_events_unit_type_enum`, so until that migration lands an insert of
# these rows is refused by the database rather than accepted wrongly. That is the correct
# failure and it is why they are spelled here rather than folded onto the existing
# `llm_tok_in` / `llm_tok_out`.
#
# **PER THOUSAND TOKENS, AND THAT IS A MONEY DECISION.** `unit_cost_paid` is `NUMERIC(12,4)`
# and every reader multiplies it by `qty`. `gpt-4o-mini` input lists at $0.15/Mtok, i.e.
# about ₹0.0000144 per token, which stores as `0.0000` — the LLM leg would meter as exactly
# free. The identical argument is already written for `ai_assist_ktok_*` and `tts_kchars`
# (`apps/api/billing/models.py:88-112`, `:135-156`); this is the third leg to meet it and it
# takes the same answer rather than a fourth one.
UNIT_TELEPHONY_S = "telephony_s"
UNIT_PLATFORM_MIN = "platform_min"
UNIT_STT_S = "stt_s"
UNIT_TTS_KCHARS = "tts_kchars"
UNIT_LLM_KTOK_IN = "llm_ktok_in"
UNIT_LLM_KTOK_OUT = "llm_ktok_out"

_PER_THOUSAND = Decimal(1000)


# --- refusals -------------------------------------------------------------------------
#
# The shape is `calevate_shared.document_ingest.DocumentRefusedError`'s — a stable machine
# `code`, then prose in the three parts an operator acts on. That family is the repo's
# existing answer for "a refusal raised by a library module that has no HTTP response to
# render", which is exactly this module's position: `apps/api/core/errors.ProblemError` is
# the right base for anything that becomes a problem+json body, and this worker never
# produces one. `BACKEND-PATTERNS` §3's ladder still names the `kind`, and every refusal here
# is `business_rule` — nothing is retryable, because a rate nobody attested does not appear
# by waiting.
#
# The audience is an OPERATOR and not a client: a client never sees these and can do nothing
# about them, so the remediation names the ops console, the invoice and the vendor question.


class LegNotMeterableError(Exception):
    """A leg of the call that cannot be honestly priced. NEVER caught to substitute a zero.

    Catching this to write ₹0 would reintroduce exactly what §1.3 forbids, so it is a single
    base class on purpose: `except LegNotMeterableError` is easy to find in review.
    """

    kind = "business_rule"
    retryable = False

    def __init__(self, *, leg: MeteredLeg, code: str, detail: str, remediation: str) -> None:
        self.leg = leg
        self.code = code
        self.detail = detail
        self.remediation = remediation
        super().__init__(f"{code}: {detail} {remediation}")


class RateCardMissingError(LegNotMeterableError):
    """Nothing was installed to price with. See `RateCard` for why this is not a default."""

    def __init__(self, leg: MeteredLeg) -> None:
        super().__init__(
            leg=leg,
            code="meter_rate_card_missing",
            detail=(
                f"the {leg.value} leg has a measured quantity and no rate card was installed "
                "on this worker, so nothing can turn it into rupees."
            ),
            remediation=(
                "Construct CallMeter with the rate card the deployment configures. A worker "
                "running without one meters quantities only and can never settle a call."
            ),
        )


class RateRefusedError(LegNotMeterableError):
    """The rate card itself refused — no attested price, no vendor reading. Hard rule 7.

    SEPARATE FROM `RateCardMissingError` because they are different events with the same
    symptom: nothing installed is a deployment fault, and a refusal is the rate card working
    correctly on a model nobody priced. An operator triages them differently.
    """

    def __init__(self, *, leg: MeteredLeg, subject: str, refusal: str) -> None:
        super().__init__(
            leg=leg,
            code="meter_rate_refused",
            detail=f"the rate card refused to price {subject!r} on the {leg.value} leg: {refusal}",
            remediation=(
                "Enter the price from the vendor invoice in the ops console. Until it is "
                "attested this leg is unmetered, which is not the same as free."
            ),
        )


class CarrierFactsMissingError(LegNotMeterableError):
    """No CDR, so the billable quantity has no independent witness (§1.2).

    The tempting fix — time the call with our own clock — is the one §1.2 rejects by name,
    so it is not offered here and the remediation says why.
    """

    def __init__(self) -> None:
        super().__init__(
            leg=MeteredLeg.CARRIER,
            code="meter_carrier_cdr_missing",
            detail=(
                "no carrier CDR was supplied, so the connected duration and the charge for "
                "this call have no independent witness."
            ),
            remediation=(
                "Retrieve the CDR from the carrier and meter again. Do NOT substitute the "
                "worker's own session duration: the carrier billed the minute and is the "
                "authority for it (PIPECAT-MIGRATION.md §1.2), and our clock agrees with us "
                "by construction."
            ),
        )


class RuntimePriceUnknownError(LegNotMeterableError):
    """Pipecat Cloud's active minute. UNKNOWN, and deliberately not priced (§7, P-1).

    This is the one leg that no amount of code closes. It is an unanswered VENDOR question,
    and inventing a per-minute figure for it would put an unfalsifiable number in the margin
    model — the failure `billing/rates.py` refuses for the Azure regional uplift for the same
    reason.
    """

    def __init__(self) -> None:
        super().__init__(
            leg=MeteredLeg.RUNTIME,
            code="meter_runtime_active_minute_unknown",
            detail=(
                "what a Pipecat Cloud active minute covers is UNKNOWN — whether it is "
                "connected time only, or container start and teardown too, and how many "
                "minutes a three-minute call bills. Nobody has read an answer, so this "
                "worker has neither a quantity nor a rate for the runtime leg."
            ),
            remediation=(
                "Answer P-1 of docs/evidence/pre-build-blockers-2026-09-13.md against a real "
                "Pipecat Cloud invoice, then supply RuntimeUsage with the attested minutes "
                "and rate. Do not estimate it."
            ),
        )


class TokenUsageNotComparableError(LegNotMeterableError):
    """`prompt_tokens + completion_tokens` did not reconcile to `total_tokens`.

    THIS IS THE §1.3 TRAP, CAUGHT RATHER THAN DESCRIBED. `LLMTokenUsage` reports
    `prompt_tokens` NET of the prompt cache on Anthropic and Bedrock and GROSS on
    OpenAI-compatible services, and `total_tokens` is gross either way — so it "is therefore
    not always `prompt_tokens + completion_tokens`"
    (`src/pipecat/metrics/metrics.py:109-127`, read at `f67c18af`).

    Our three declared legs (`azure_openai`, `openai`, `google`) are all OpenAI-compatible, so
    the split IS billable as reported and the two rates the rate card returns apply to it. A
    report where the parts do not reconcile to the whole means this call did not run on the
    leg we think it did, and billing the parts would silently under-bill the cached prompt.
    So it refuses, and it never repairs the figure by subtraction — `total_tokens` is the
    figure of record and is never reconstructed.
    """

    def __init__(self, *, model: str, prompt: int, completion: int, total: int) -> None:
        super().__init__(
            leg=MeteredLeg.LLM,
            code="meter_llm_tokens_not_comparable",
            detail=(
                f"{model!r} reported {prompt} prompt + {completion} completion tokens against "
                f"a total of {total}. On an OpenAI-compatible leg those reconcile; a gap means "
                "the prompt count is net of the prompt cache (Anthropic/Bedrock shape) and "
                "the two per-thousand rates do not apply to it as reported."
            ),
            remediation=(
                "Check which provider this agent's in-call LLM leg actually ran on. Bill "
                "nothing from this session until it is explained: total_tokens is the figure "
                "of record and must never be reconstructed from the parts."
            ),
        )


class LlmTotalTokensMissingError(LegNotMeterableError):
    """Token usage arrived without `total_tokens`, the one figure §1.3 makes authoritative.

    Dropping such a report would under-meter the leg silently, which is the shape of the
    defect this whole module exists to prevent — so it is remembered and refused rather than
    ignored, and it is NOT repaired by adding the prompt and completion counts. That sum is
    exactly what §1.3 forbids reconstructing, and on a net-reporting service it would be low
    by the whole prompt cache.
    """

    def __init__(self, *, processor: str, reports: int) -> None:
        super().__init__(
            leg=MeteredLeg.LLM,
            code="meter_llm_total_tokens_missing",
            detail=(
                f"{processor!r} reported LLM usage {reports} time(s) with no total_tokens, so "
                "part of this session's language leg has no comparable quantity."
            ),
            remediation=(
                "Find out why the provider omitted the total. Do not add the prompt and "
                "completion counts to stand in for it: total_tokens is gross and those are "
                "not always its parts (pipecat metrics.py:109-127)."
            ),
        )


class LlmModelUnnamedError(LegNotMeterableError):
    """Token usage arrived with no model, and a price is per model (D-410)."""

    def __init__(self, *, processor: str) -> None:
        super().__init__(
            leg=MeteredLeg.LLM,
            code="meter_llm_model_unnamed",
            detail=(
                f"{processor!r} reported token usage without naming a model, and every LLM "
                "price in this repository is per model."
            ),
            remediation=(
                "Configure the service so it reports its model name. A price picked for an "
                "unnamed model would be a guess, and the selectable models differ by 2.7x."
            ),
        )


class LlmModelAmbiguousError(LegNotMeterableError):
    """More than one model served one call, and one ledger row cannot carry two prices.

    Not a theoretical arm: `base_llm.py:507-508` re-reads the model off each chunk and calls
    `set_full_model_name` when it differs from the configured one, so a provider-side alias
    or failover surfaces here as a second name. Refusing is the only honest answer —
    `usage_events` carries one `unit_type` per call under `ux_usage_events_tenant_call_unit`,
    so picking either model would price some of the tokens at the other one's rate.
    """

    def __init__(self, *, models: tuple[str, ...]) -> None:
        super().__init__(
            leg=MeteredLeg.LLM,
            code="meter_llm_model_ambiguous",
            detail=(
                f"token usage arrived under more than one model in one session: "
                f"{', '.join(models)}."
            ),
            remediation=(
                "Find out why the provider served a second model (an alias, a failover, or a "
                "mid-call settings change) and meter that session by hand. The ledger holds "
                "one LLM price per call."
            ),
        )


# --- the rate surface, and the boundary it sits behind --------------------------------


class RateCard(Protocol):
    """The one door a rupee comes through. **NO DEFAULT IMPLEMENTATION SHIPS IN THIS FILE.**

    `apps/api/billing/rates.py` is the rate surface this repository already has, and it is
    the one to use: `llm_inr_per_ktok` refuses an unattested price rather than returning
    zero, which is the behaviour §1.3 says the other four legs must now copy. Re-deriving any
    of it here would be a second answer to a solved question.

    **BUT THIS WORKER MUST NOT IMPORT `apps.api`** — it is a separate deployable (D-592) that
    has no business pulling in a monolith carrying tenancy, billing and the console. So the
    rate surface arrives as a port, in the shape `BACKEND-PATTERNS` §1 already prescribes
    ("ports for external systems are Protocols"), and the process that builds the pipeline
    supplies the adapter.

    The methods mirror `billing/rates.py` exactly — same names, same units, same contract
    that the returned rate is EXACT and UNQUANTIZED and the caller multiplies once. They are
    a subset: the two legs this protocol does not mention are the two nobody can price from a
    rate card (`CarrierCdr`, `RuntimeUsage`).

    ⚠ **THE ADAPTER DOES NOT EXIST YET AND THIS MODULE DOES NOT INVENT ONE.** The change
    wanted, named here so the next reader inherits it rather than re-deriving it: lift the
    pure arithmetic of `billing/rates.py` — `llm_inr_per_ktok`, `tts_rate_inr_per_char`,
    `stt_rate_inr_per_second` and the attestation reader they consult — into
    `calevate_shared` so `apps/api` and this worker share ONE door instead of two. Until that
    lands a worker constructed with `rates=None` meters quantities and refuses to price,
    which is a refusal and not a zero.
    """

    def llm_inr_per_ktok(self, model: str) -> Mapping[str, Decimal]:
        """`{"in": ₹, "out": ₹}` per 1,000 tokens AS BILLED. Raises where nobody priced it."""
        ...

    def tts_rate_inr_per_char(self) -> Decimal:
        """₹ per character synthesised. Exact, unquantized."""
        ...

    def stt_rate_inr_per_second(self) -> Decimal:
        """₹ per second of audio transcribed. Exact, unquantized."""
        ...


# --- the two legs that are supplied, not observed --------------------------------------


@dataclass(frozen=True, slots=True)
class CarrierCdr:
    """The carrier's own record of the call. THE AUTHORITY FOR THE BILLABLE MINUTE (§1.2).

    Both the quantity and the charge come from here, because the carrier is the party that
    billed them; neither is derived from anything the worker observed. `cdr_id` travels onto
    the row so a disputed minute can be taken back to Plivo's record of it.

    NO PHONE NUMBER (hard rule 6). The CDR names which number rang and this dataclass does
    not carry it — the ledger row would be the wrong place for it and the reconciliation
    joins on `cdr_id`.
    """

    connected_seconds: Decimal
    charge_inr: Decimal
    carrier: str
    cdr_id: str


@dataclass(frozen=True, slots=True)
class RuntimeUsage:
    """Pipecat Cloud's billed active minutes and the rate, BOTH ATTESTED BY A HUMAN.

    There is no constructor that derives this from the session: see `RuntimePriceUnknownError`
    for why, and §3.5 P-1 for the question that closes it. `attested_by` and `source` are the
    same two fields `billing/rates.LlmPriceAttestation` carries, for the same reason — a
    figure with no named reader and no named source is a REPORTED number wearing a fact's
    clothes (hard rule 11).
    """

    active_minutes: Decimal
    inr_per_active_minute: Decimal
    attested_by: str
    source: str


# --- what leaves this module -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsageRow:
    """One `usage_events` row's worth of OUR normalized usage. No vendor shape survives here.

    `unit_cost_inr` is A PRICE PER UNIT OF `qty`, which is what `unit_cost_paid` means to
    every reader of that column (`billing.margin_for_tenant` sums `qty * unit_cost_paid`).

    **EXACT AND UNQUANTIZED, DELIBERATELY.** `billing/rates.py` promises its callers an exact
    rate and asks them to "multiply by a count and quantize once"; quantizing here and again
    at the column would be the second rounding that contract exists to avoid. The writer
    quantizes to the column's own quantum with `ROUND_HALF_UP`, which is where that fact
    already lives (`billing/rates.MONEY_Q`, `ROUNDING`) and where it stays — duplicating the
    quantum into this deployable would be a second home for it.

    `total_inr` is carried alongside because on the carrier leg it is the PRIMARY figure (the
    CDR states a charge, and the per-second price is derived from it) while on the other legs
    it is the product. Keeping both means a `qty` of zero cannot lose the money silently, the
    gap `workers/pipeline.py::_unit_price` documents at length.
    """

    leg: MeteredLeg
    unit_type: str
    qty: Decimal
    unit_cost_inr: Decimal
    total_inr: Decimal
    meta: Mapping[str, str]


def _unit_cost(*, total_inr: Decimal, qty: Decimal) -> Decimal:
    """A leg total expressed per unit of `qty`, with `workers/pipeline.py::_unit_price`'s rule
    for a zero quantity: keep the leg cost whole on the row rather than divide by zero.

    One way per problem — the same choice the Bolna path made, so the two ledgers' rows mean
    the same thing and the reader that mishandles a zero-qty row is one bug in one place.
    """
    if qty == 0:
        return total_inr
    return total_inr / qty


# --- the meter -------------------------------------------------------------------------


@dataclass
class _LlmTally:
    """What one model reported, summed. `total_tokens` is summed, never reconstructed."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reports: int = 0
    processors: set[str] = field(default_factory=set)


class CallMeter:
    """Observes one session and emits the five legs §1.3 sums, or refuses a leg by name.

    **OBSERVING NEVER RAISES; PRICING DOES.** A live call must not die because the ops console
    has no attestation for a model — the caller is mid-sentence and the refusal helps nobody
    until the call is over. So `observe` only accumulates (and remembers what it could not
    use), and every refusal lands in `metered_rows`, which runs after the call, on the path
    that writes the ledger. That division is the reason `observe` has no failure mode and no
    `try` around it at the call site.

    Not thread-safe and not meant to be: one meter per session, accumulated from the
    pipeline's own event loop, exactly as `ServiceMetricsObserver` delivers.
    """

    def __init__(self, *, rates: RateCard | None = None) -> None:
        self._rates = rates
        self._stt_audio_seconds = Decimal(0)
        self._stt_reports = 0
        self._stt_processors: set[str] = set()
        self._tts_characters = 0
        self._tts_reports = 0
        self._tts_processors: set[str] = set()
        self._llm: dict[str, _LlmTally] = {}
        self._llm_unnamed: list[str] = []
        self._llm_no_total: list[str] = []

    # -- intake --------------------------------------------------------------------

    def attach(self, observer: ServiceMetricsObserver) -> None:
        """Subscribe to the observer the pipeline already runs.

        `ServiceMetricsObserver` is the structured reporter and the right base for a ledger
        writer (`service_metrics_observer.py:121-158`); the alternative, filtering
        `MetricsFrame` out of a raw `BaseObserver`, would mean re-deriving the three usage
        shapes this one already normalizes.

        ⚠ The records only exist when the pipeline asked for them:
        `PipelineParams.enable_metrics` and `enable_usage_metrics` both default to **False**
        (`src/pipecat/pipeline/worker.py:198-199`), and `frame_processor.py:591-613` drops
        every usage metric when they are off. A meter attached to a pipeline that did not
        enable them observes nothing and then refuses every leg, which is the right failure
        but a confusing one — `pipeline.py` sets both True.

        ⚠ **THE HANDLER RUNS AS ITS OWN TASK**, not inline: the observer creates one per
        handler per event (`src/pipecat/utils/base_object.py:256-261`). So a report pushed in
        the last instants of a session is accumulated only if the loop gets one more turn,
        which is the caller's business — meter after the pipeline has drained
        (`PipelineWorker.stop_when_done` / `end`), never from inside the teardown that
        cancels it.
        """
        observer.add_event_handler("on_service_usage", self._on_service_usage)

    async def _on_service_usage(
        self, observer: ServiceMetricsObserver, record: ServiceUsageRecord
    ) -> None:
        """Pipecat's event signature (observer, record). The vendor shape stops here."""
        self.observe(record)

    def observe(self, record: ServiceUsageRecord) -> None:
        """Accumulate one usage report. Total, never raising — see the class docstring.

        Records are INCREMENTAL DELTAS and consumers sum them: `STTUsage` says so
        (`src/pipecat/metrics/metrics.py:161-170`) and the TTS counter is per synthesis
        request, aggregated to one report per flush when the service streams tokens
        (`src/pipecat/services/tts_service.py:437-448`). So summing is the contract, not an
        assumption — and it is why a session that ends abruptly still meters everything that
        happened before it did.
        """
        if record.kind is ServiceUsageKind.STT:
            if record.audio_seconds is None:
                return
            # `str()` and not `Decimal(float)`: the vendor measures audio seconds as a float
            # (`stt_service.py:251`, bytes / (sample_rate * 2)), and the binary expansion of
            # that float is not the number anyone means. This is a QUANTITY and not money,
            # but it multiplies a rate, so it enters the money path and enters it exactly.
            self._stt_audio_seconds += Decimal(str(record.audio_seconds))
            self._stt_reports += 1
            self._stt_processors.add(record.processor)
        elif record.kind is ServiceUsageKind.TTS:
            if record.characters is None:
                return
            # Already an int — `len(text)` at `frame_processor_metrics.py:365`.
            self._tts_characters += record.characters
            self._tts_reports += 1
            self._tts_processors.add(record.processor)
        elif record.kind is ServiceUsageKind.LLM:
            if record.total_tokens is None:
                self._llm_no_total.append(record.processor)
                return
            if record.model is None:
                self._llm_unnamed.append(record.processor)
                return
            tally = self._llm.setdefault(record.model, _LlmTally())
            tally.prompt_tokens += record.prompt_tokens or 0
            tally.completion_tokens += record.completion_tokens or 0
            tally.total_tokens += record.total_tokens
            tally.reports += 1
            tally.processors.add(record.processor)

    # -- what we measured, before anything is priced --------------------------------

    @property
    def stt_audio_seconds(self) -> Decimal:
        """Audio seconds submitted to the transcriber, summed across every report."""
        return self._stt_audio_seconds

    @property
    def tts_characters(self) -> int:
        """Characters handed to the synthesizer, summed across every report."""
        return self._tts_characters

    @property
    def llm_total_tokens(self) -> int:
        """`total_tokens`, summed. THE cross-provider comparable figure (§1.3), never rebuilt."""
        return sum(tally.total_tokens for tally in self._llm.values())

    # -- pricing -------------------------------------------------------------------

    def metered_rows(
        self, *, carrier: CarrierCdr | None, runtime: RuntimeUsage | None
    ) -> tuple[UsageRow, ...]:
        """All five legs, or the first refusal. **THERE IS NO PARTIAL SETTLEMENT.**

        Both arguments are required and nullable rather than optional, so a caller cannot
        reach a four-leg total by forgetting an argument: omitting the CDR has to be spelled
        `carrier=None`, and it raises.

        The legs are priced in the order they are listed in §1.3 so the refusal an operator
        sees first is the one furthest from our control — a missing CDR and an unanswered
        vendor question are somebody's to go and get, while an unattested rate is a form in
        the ops console.
        """
        rows = [self._carrier_row(carrier), self._runtime_row(runtime)]
        rows.extend(self._stt_rows())
        rows.extend(self._tts_rows())
        rows.extend(self._llm_rows())
        return tuple(rows)

    def _carrier_row(self, carrier: CarrierCdr | None) -> UsageRow:
        if carrier is None:
            raise CarrierFactsMissingError
        return UsageRow(
            leg=MeteredLeg.CARRIER,
            unit_type=UNIT_TELEPHONY_S,
            qty=carrier.connected_seconds,
            unit_cost_inr=_unit_cost(total_inr=carrier.charge_inr, qty=carrier.connected_seconds),
            total_inr=carrier.charge_inr,
            meta={
                "source": "carrier_cdr",
                "carrier": carrier.carrier,
                "cdr_id": carrier.cdr_id,
            },
        )

    def _runtime_row(self, runtime: RuntimeUsage | None) -> UsageRow:
        if runtime is None:
            raise RuntimePriceUnknownError
        total = runtime.active_minutes * runtime.inr_per_active_minute
        return UsageRow(
            leg=MeteredLeg.RUNTIME,
            unit_type=UNIT_PLATFORM_MIN,
            qty=runtime.active_minutes,
            unit_cost_inr=runtime.inr_per_active_minute,
            total_inr=total,
            meta={
                "source": "operator_attestation",
                "attested_by": runtime.attested_by,
                "attestation_source": runtime.source,
            },
        )

    def _rate_card(self, leg: MeteredLeg) -> RateCard:
        if self._rates is None:
            raise RateCardMissingError(leg)
        return self._rates

    def _stt_rows(self) -> list[UsageRow]:
        if self._stt_reports == 0:
            # A CALL THAT TRANSCRIBED NOTHING IS NOT AN UNPRICEABLE CALL. It is a call the
            # transcriber never reported on — an answer that hung up in silence — and there
            # is no leg to price. Distinct from a leg we cannot price: nothing is missing.
            return []
        rates = self._rate_card(MeteredLeg.STT)
        try:
            rate = rates.stt_rate_inr_per_second()
        except (ValueError, LookupError) as exc:
            raise RateRefusedError(
                leg=MeteredLeg.STT, subject="stt audio seconds", refusal=str(exc)
            ) from exc
        qty = self._stt_audio_seconds
        return [
            UsageRow(
                leg=MeteredLeg.STT,
                unit_type=UNIT_STT_S,
                qty=qty,
                unit_cost_inr=rate,
                total_inr=rate * qty,
                meta={
                    "source": "pipecat:STTUsage.audio_seconds",
                    "processors": ",".join(sorted(self._stt_processors)),
                    "reports": str(self._stt_reports),
                },
            )
        ]

    def _tts_rows(self) -> list[UsageRow]:
        if self._tts_reports == 0:
            return []
        rates = self._rate_card(MeteredLeg.TTS)
        try:
            per_char = rates.tts_rate_inr_per_char()
        except (ValueError, LookupError) as exc:
            raise RateRefusedError(
                leg=MeteredLeg.TTS, subject="tts characters", refusal=str(exc)
            ) from exc
        qty = Decimal(self._tts_characters) / _PER_THOUSAND
        per_kchar = per_char * _PER_THOUSAND
        return [
            UsageRow(
                leg=MeteredLeg.TTS,
                unit_type=UNIT_TTS_KCHARS,
                qty=qty,
                unit_cost_inr=per_kchar,
                total_inr=per_kchar * qty,
                meta={
                    "source": "pipecat:TTSUsageMetricsData.value",
                    "processors": ",".join(sorted(self._tts_processors)),
                    "reports": str(self._tts_reports),
                    "characters": str(self._tts_characters),
                },
            )
        ]

    def _llm_rows(self) -> list[UsageRow]:
        if self._llm_no_total:
            raise LlmTotalTokensMissingError(
                processor=sorted(self._llm_no_total)[0], reports=len(self._llm_no_total)
            )
        if self._llm_unnamed:
            raise LlmModelUnnamedError(processor=sorted(self._llm_unnamed)[0])
        if not self._llm:
            return []
        if len(self._llm) > 1:
            raise LlmModelAmbiguousError(models=tuple(sorted(self._llm)))
        model, tally = next(iter(self._llm.items()))
        # THE §1.3 TRAP, CHECKED RATHER THAN TRUSTED. `total_tokens` is the figure of record
        # and is summed straight from the reports; this asserts that the split we are about
        # to bill at two different rates reconciles to it, which is only true on the
        # OpenAI-compatible legs we declare. It is not a repair: nothing here recomputes a
        # count from the other two.
        if tally.prompt_tokens + tally.completion_tokens != tally.total_tokens:
            raise TokenUsageNotComparableError(
                model=model,
                prompt=tally.prompt_tokens,
                completion=tally.completion_tokens,
                total=tally.total_tokens,
            )
        rates = self._rate_card(MeteredLeg.LLM)
        try:
            price = rates.llm_inr_per_ktok(model)
        except (ValueError, LookupError) as exc:
            raise RateRefusedError(leg=MeteredLeg.LLM, subject=model, refusal=str(exc)) from exc
        meta = {
            "source": "pipecat:LLMTokenUsage",
            "model": model,
            "processors": ",".join(sorted(tally.processors)),
            "reports": str(tally.reports),
            # STAMPED ON THE ROW because `usage_events` is append-only and this is the figure
            # §1.3 makes authoritative: the two rows below carry the split, and this is what
            # they were checked against. A later reader can re-run the reconciliation without
            # the session that produced it.
            "total_tokens": str(tally.total_tokens),
        }
        rows = []
        for unit_type, key, tokens in (
            (UNIT_LLM_KTOK_IN, "in", tally.prompt_tokens),
            (UNIT_LLM_KTOK_OUT, "out", tally.completion_tokens),
        ):
            try:
                rate = price[key]
            except KeyError as exc:
                raise RateRefusedError(
                    leg=MeteredLeg.LLM,
                    subject=model,
                    refusal=f"the rate card returned no {key!r} rate",
                ) from exc
            qty = Decimal(tokens) / _PER_THOUSAND
            rows.append(
                UsageRow(
                    leg=MeteredLeg.LLM,
                    unit_type=unit_type,
                    qty=qty,
                    unit_cost_inr=rate,
                    total_inr=rate * qty,
                    meta=meta,
                )
            )
        return rows
