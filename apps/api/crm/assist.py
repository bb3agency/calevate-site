"""The user-triggered call assist: read the REDACTED call, run it, meter what it cost.

This module is the JOIN between two halves that were built one call apart and never met
— `apps/workers/extraction.run_assist` (which decides who answers and what that answer
cost) and `apps/api/billing/ai_quota` (which decides whether it may run at all and turns
a token count into rupees). Until something called both in order, the ledger, the quota,
the wallet modal, the platform brake, the capability ladder and the assistant client were
all reachable by nobody.

WHAT A "RE-SUMMARISE" IS, AND WHAT IT DELIBERATELY IS NOT
--------------------------------------------------------
It is a second reading of one call, on demand, by the assistant model, over the REDACTED
transcript — the founder's "when users want to do something about that extracted
summarized thing and re-summarize it". It answers into the response and it writes
NOTHING to `calls` or `call_extractions`.

That is a decision and not an omission. The stored `calls.summary` and the
`call_extractions` row are the output of the FIRST pass, which read `turn.text` — the
raw transcript, with the digits in it — because a CRM callback-number field needs them
(D-127 G-7, `workers/pipeline.py:750`). This pass reads `text_redacted`, so its fields
are structurally *less* complete about exactly the values the CRM was built to capture.
Overwriting the raw-pass record with a redacted-pass one would silently degrade the
lead, the Leads-table columns and the CSV export, and — because `call_extractions` rows
are what the schema version pins history to (TRD §7) — would rewrite history a client
may already have exported. So the assist is a VIEW, held for as long as the person is
looking at it.

Not persisting also means this feature creates no new store of transcript-derived
personal data: nothing to enumerate on a DPDP erasure, nothing to age out under
retention, no `text_redacted` twin to keep in step. D-126 is the standing example of
what the other choice costs.

WHY THE MODEL IS CALLED FROM A REQUEST HANDLER (a departure, argued)
--------------------------------------------------------------------
CLAUDE.md says model providers are called from workers or the engine, never a request
handler. This calls one, and the exception is argued rather than assumed — the same way
`ops/secret_probes.py` argues its own.

The rule's purpose is to keep vendor latency off the latency-critical path and off a
blocking worker. Neither applies: the voice path is `apps/voice-runtime` and is not
this, and every hop here is `await`ed on an asyncio loop, so a slow Azure occupies no
thread. What it DOES occupy is one pooled Postgres connection for the length of the
round trip, because `Depends(db)`'s transaction is open across it and `app.tenant_id` is
transaction-local (`db/session.tenant_session`) so the transaction cannot be committed
and resumed.

That cost is real and this paragraph USED TO STATE ITS BOUND WRONG, which is how the
collision below survived review: it said "bounded by `EXTRACTION_TIMEOUT_S` (30s)", and
`run_assist` runs TWO provider legs in series — Azure, then the disclosed Sarvam fallback
— so 30s per leg was ~60s of provider wait, plus this route's own idempotency claim,
quota gate, transcript load, metering and audit write, behind an `api.` vhost whose
`proxy_read_timeout` is 60s. The connection was held for the longer of the two numbers
and the client got a 504 instead of the fallback's answer.

The real bound is `2 * ASSIST_TIMEOUT_S` (15s a leg), which `run_assist` passes into both
extractors, plus `ASSIST_ROUTE_RESERVE_S` for everything in this file —
`tests/assist_deadline_test.py` reads nginx's number out of the config and asserts the sum
fits under it. The `costly` rate-limit profile — whose own comment names "an LLM call" —
is the other half of the bound, and the whole thing is the price of the alternative being
worse in three ways:

- a 202-and-poll shape needs somewhere to PUT the answer, which is a new table of
  transcript-derived prose: the personal-data store the section above declines to build;
- the acceptance dialog G-5 requires ("the feature blocks and asks, naming what it will
  cost") is a synchronous answer to a synchronous click, and `require_ai_assist` raises
  a `ProblemError` — an HTTP refusal — rather than returning a job state;
- `run_assist` already returns `AssistResult` and raises `ProblemError`; wrapping it in a
  job would mean re-encoding both into a row and decoding them on the other side, i.e. a
  second spelling of the two things D-127 built exactly one of.

ORDER OF OPERATIONS, WHICH IS THE WHOLE CORRECTNESS ARGUMENT
-------------------------------------------------------------
SUBJECT → GATE → RUN → METER, and each arrow is load-bearing:

1. **subject before gate.** A call with no redacted transcript cannot be summarised by
   anyone, at any price. Gating first would answer a client at their ceiling with "add
   ₹500" for a call the money would not have helped with.
2. **gate before run.** `require_ai_assist` RAISES, so a refusal happens before a token
   is spent: a refused request costs nothing, which is the only reading of G-4 under
   which a ceiling is a ceiling.
3. **run before meter.** The quantity metered is Azure's own count, which does not
   exist until the call returns. `AssistResult.usage is None` is handled by
   `meter_assist` below and never by inventing a number.
4. **meter is unconditional on a run that returned.** A completed assist is money spent
   whether or not the answer was any good, so nothing between the run and the meter may
   raise — the two share the caller's transaction and a rollback here would lose the
   record of a payment we had already made.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol
from uuid import UUID

from calevate_shared.extraction import ExtractionSchemaSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import record_ai_assist_usage
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.workers.chat import TokenUsage
from apps.workers.extraction import (
    AZURE_PROVIDER,
    SARVAM_PROVIDER,
    AssistCapability,
)

log = get_logger(__name__)

#: `usage_events.meta.feature` for this surface. One constant, because "which screen
#: spent this" is a query an operator runs against the ledger and a typo would answer it
#: with silence rather than with an error.
ASSIST_FEATURE_RESUMMARISE: Final = "call_resummarise"

#: `usage_events.meta.feature` for the AI script-writing assist (`agents/script_builder`).
#: A separate feature name so the ledger can tell a re-summarise from a script draft.
ASSIST_FEATURE_SCRIPT_DRAFT: Final = "script_draft"

#: `usage_events.meta.feature` for the IN-APP COPILOT (`apps/api/copilot/`), the floating
#: assistant that answers about a screen and fills its form fields.
#:
#: A THIRD name rather than a reuse of `call_resummarise`, for the reason the second one
#: exists: "which screen spent this" is a query an operator runs against the ledger, and
#: a copilot turn and a re-summarise cost differently, are triggered differently and would
#: be investigated differently. One surface, one feature name — and the copilot is the
#: first surface here that can spend on SEVERAL model turns for one user action, which is
#: precisely the row an operator will want to be able to isolate.
ASSIST_FEATURE_COPILOT: Final = "copilot"


class MeterableAssist(Protocol):
    """The two things `meter_assist` needs from a completed assist, whatever the surface.

    `AssistResult` (re-summarise, `workers/extraction`) and `ScriptDraft` (the AI script
    writer, `workers/script_assist`) both satisfy this structurally, so ONE metering path
    prices both — the alternative is a second copy of the Azure/Sarvam/unknown-provider
    money branches below, which is exactly the kind of subtle duplication a ledger cannot
    afford to have drift. Neither surface's own richer result (an `ExtractionOutput`, a
    `CallScript`) is metering's business; the tokens and who produced them are.
    """

    @property
    def usage(self) -> TokenUsage | None: ...

    @property
    def capability(self) -> AssistCapability: ...


@dataclass(frozen=True, slots=True)
class AssistSource:
    """Everything the model is allowed to see about one call, and nothing else.

    `transcript` is built from `transcript_turns.text_redacted` — never `text`. That is
    G-2, and it is why this dataclass exists at all rather than the route passing a raw
    row around: a named, single-field carrier is a thing a reader can check, and the
    query that fills it is four lines below the promise.
    """

    call_id: UUID
    agent_id: UUID
    spec: ExtractionSchemaSpec
    transcript: str


# THE COLUMN IS `text_redacted` AND THE RAW ONE IS NOT NAMED IN THIS FILE.
#
# `crm.service.get_call` picks its column with an f-string on a `raw` flag, which is
# right there — it serves both views — and would be wrong here, because there is no
# second view to serve. The raw column is not a parameter of this query, so no argument
# and no future refactor can select it.
#
# `speaker` comes back so the transcript reads as a conversation: an extractor handed an
# undifferentiated wall of text cannot tell who asked for the callback.
_TURNS_SQL = "SELECT speaker, text_redacted FROM transcript_turns WHERE call_id = :cid ORDER BY idx"

_CALL_SQL = (
    "SELECT c.agent_id, es.version, es.fields FROM calls c "
    "JOIN agents a ON a.id = c.agent_id "
    "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
    "WHERE c.id = :cid"
)


def transcript_for_model(turns: list[tuple[str, str]]) -> str:
    """`speaker: line` per turn, newline separated.

    THE SAME SHAPE `workers/pipeline._persist_transcript` BUILDS, and it has to be: the
    prompt the model receives is `build_extraction_prompt(spec, transcript)`, one
    function, and a second transcript dialect would mean the assist scored against a
    format the golden-transcript fixtures never exercise. It is rebuilt here rather than
    imported because that function builds it from the RAW column by design — importing
    it would put `turn.text` one refactor away from this path. `tests/call_assist_test.py`
    pins the shape.
    """
    return "\n".join(f"{speaker}: {line}" for speaker, line in turns)


async def load_assist_source(session: AsyncSession, call_id: UUID) -> AssistSource:
    """The redacted transcript and the agent's extraction schema, or a refusal.

    Three refusals, all of them things a person can act on, and all of them BEFORE the
    quota gate so that none of them can be mistaken for a money problem:

    - the call does not exist in this tenant (RLS makes those one answer, deliberately);
    - it has no transcript yet — the ordinary state for a call that ended a minute ago;
    - it has a transcript with a turn that has no redacted copy. That one is fail-closed
      rather than best-effort: `text_redacted` is nullable, and skipping such turns would
      hand the model a transcript with holes in it and hand the client a summary of part
      of a call presented as a summary of the call. Sending the raw turn instead is the
      one thing G-2 forbids outright.
    """
    row = (await session.execute(text(_CALL_SQL), {"cid": call_id})).first()
    if row is None:
        raise ProblemError.not_found("Call")
    agent_id, version, fields = row[0], row[1], row[2]

    turns = (await session.execute(text(_TURNS_SQL), {"cid": call_id})).all()
    if not turns:
        raise ProblemError.business_rule(
            "assist_no_transcript",
            "This call has no transcript yet, so there is nothing to summarise.",
            remediation=(
                "Transcripts arrive a couple of minutes after a call ends. Reload the "
                "page and try again."
            ),
        )
    if any(turn[1] is None for turn in turns):
        # Never logged with the call's content, and never repaired by falling back to
        # `text`: an assist that reads the raw column is the residency inversion D-127
        # exists to make impossible.
        log.error("assist_turn_missing_redaction", extra={"call_id": str(call_id)})
        raise ProblemError.business_rule(
            "assist_transcript_not_redacted",
            "Part of this call's transcript has no redacted copy, so the assistant cannot read it.",
            remediation="Tell us about this call — we need to re-run its redaction pass.",
        )

    spec = ExtractionSchemaSpec.model_validate({"version": version or 1, "fields": fields or []})
    return AssistSource(
        call_id=call_id,
        agent_id=agent_id,
        spec=spec,
        transcript=transcript_for_model([(str(t[0]), str(t[1])) for t in turns]),
    )


@dataclass(frozen=True, slots=True)
class AssistMetering:
    """What reached the ledger. `metered` False is a real outcome, not a failure —
    `meter_assist` says which of the two kinds it was."""

    metered: bool
    cost_inr: Decimal


async def meter_assist(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    ref: str,
    result: MeterableAssist,
    feature: str = ASSIST_FEATURE_RESUMMARISE,
) -> AssistMetering:
    """Turn one `AssistResult` into `usage_events` rows, or say why it did not.

    `AssistResult.usage is None` IS THE INTERESTING CASE and it has two causes that must
    not be handled the same way — `AssistResult`'s own docstring says so, and this is the
    caller that has to mean it:

    * **A Sarvam fallback.** D-36 prices that leg at zero, so there is nothing to charge
      and no `ai_assist_ktok_*` quantity to state. Nothing is written. Writing `qty = 0`
      rows instead was rejected on D-140's ground: an assist that certainly consumed
      thousands of Sarvam tokens recorded as zero thousand is a FABRICATED quantity, and
      a fabricated quantity in an append-only ledger looks exactly like a real one. It
      would also move `read_ai_quota`'s `requests_used` — `COUNT(DISTINCT ref)` over the
      paid unit types — so the screen would count a paid assist that never happened, and
      the rupee ceiling (the number that actually blocks) and the request count (the
      number a person plans around) would start disagreeing about the same month.
    * **An Azure answer Azure did not count.** We paid Microsoft and cannot say how much.
      Also unwritten, for the same reason and with the opposite severity: this is a
      METERING OUTAGE — every assist in this state is spend the per-tenant ceiling and
      the platform brake are both blind to — so it fires `alert()` rather than an info
      log. Estimating from the transcript length was available and is exactly what D-140
      refused; the brake going quiet is a thing an operator can act on, and a plausible
      invented number is not.

      WHAT "NO USAGE" MEANS HERE IS THE ADAPTER'S ANSWER, NOT A CLAIM ABOUT AZURE
      (D-410). `workers/extraction.py::_azure_usage` returns None when the response
      carried no `usage` block, and this branch reports exactly that. Why a 200 would
      arrive without one is a vendor behaviour nobody in this repository has observed, so
      nothing is asserted about it and nothing is inferred from it — the alert says what
      was seen and asks an operator to look, which is the only honest shape for a metering
      outage whose cause is on somebody else's side.

    Never raises. It runs after the provider has been paid, in the same transaction as
    everything else the request writes (§4's rule that the record and the act commit
    together), and a metered assist undone by a failure to talk about it would be the
    money hole this whole path exists to close.
    """
    # THE MODEL THE LEDGER NAMES, and it is the model rather than the deployment on
    # purpose (D-410). Azure serves a model under a deployment ID the operator chose; the
    # deployment is a routing label that says nothing about price or quality, so a ledger
    # row naming it could not be priced later and would silently re-baseline on a console
    # rename. `azure_extractor()` builds the client with this same setting, which is why
    # this is a read of the setting rather than a constant: `azure_openai_model` is
    # D-410's LIVE switch (`gpt-4.1-mini` costs 2.7x the default on both legs), so a
    # constant here would name a model nothing ran on within one poll of an operator
    # flipping it. Read AFTER the run, so an operator who flips it mid-request has the
    # ledger name the model the answer probably came from rather than the one it
    # certainly did not — the residual race is one request wide and the alternative is
    # widening `AssistResult` to carry the model, which is a Protocol change for a
    # one-request window.
    model = get_settings().azure_openai_model
    usage = result.usage
    if usage is None:
        if result.capability.provider == AZURE_PROVIDER:
            alert(
                "CORE_LOGIC",
                "ai_assist_unmeterable",
                detail=(
                    "A dashboard assist ran on Azure OpenAI and the response carried no "
                    "usage block, so it could not be metered: this spend is invisible "
                    "to the tenant's AI ceiling and to the platform brake. Nothing was "
                    "estimated. Check whether Azure has stopped sending the block "
                    "before the month's real spend outruns PLATFORM_AI_BRAKE_INR."
                ),
                # Ids, a model name and a feature name. No tenant name, no transcript,
                # no output — and never the key, which is the one thing on this path
                # whose leak is worse than PII.
                tenant_id=str(tenant_id),
                ref=ref,
                model=model,
                feature=feature,
            )
        elif result.capability.provider == SARVAM_PROVIDER:
            # The ordinary, correct, free case. Logged so that "why did the counter not
            # move" has an answer that is not a shrug.
            log.info(
                "ai_assist_unmetered_fallback",
                extra={
                    "tenant_id": str(tenant_id),
                    "ref": ref,
                    "provider": result.capability.provider,
                    "fallback_reason": result.capability.fallback_reason,
                    "feature": feature,
                },
            )
        else:
            # THE CLOSED SET IS NOW CLOSED, and this arm is why. The free branch above
            # used to be a bare `else`: it SAID "not Azure" and MEANT "Sarvam", a fact
            # owned by `assist_capability`'s ladder in `apps/workers/extraction.py` and
            # depended on here with nothing comparing the two. The default for an
            # unrecognised provider was therefore "free" — on an APPEND-ONLY ledger, where
            # a row that should have existed cannot be back-filled by an UPDATE.
            #
            # NOT A LIVE MONEY HOLE TODAY, and saying so is part of the record: the ladder
            # returns exactly two providers, `SarvamExtractor` has no `last_usage` so the
            # Sarvam path always arrives with `usage is None` (this branch, never the
            # metered one), D-36 prices that leg at zero, and `record_ai_assist_usage`
            # refuses an identifier `rates.llm_inr_per_ktok` does not publish rather than
            # defaulting to a price. It is a hole that OPENS the day a third, paid provider
            # is added — the change that adds it touches `extraction.py` and has no reason
            # to look at this file, which is precisely when a silent default costs money.
            #
            # An alert rather than a log line, and a REFUSAL was rejected: the run already
            # happened and §4's rule is that nothing between the run and the meter may
            # raise. So it is recorded as unmetered, loudly, with the provider named.
            alert(
                "CORE_LOGIC",
                "ai_assist_unknown_provider",
                detail=(
                    "A dashboard assist was answered by a provider this meter does not "
                    "know how to price, so it was recorded as free. If that provider is "
                    "paid, this is spend invisible to the tenant's AI ceiling and to the "
                    "platform brake. Teach crm/assist.py::meter_assist about it, or "
                    "confirm it belongs in the free bucket."
                ),
                tenant_id=str(tenant_id),
                ref=ref,
                model=model,
                feature=feature,
                provider=str(result.capability.provider),
            )
        return AssistMetering(metered=False, cost_inr=Decimal("0"))

    metered = await record_ai_assist_usage(
        session,
        tenant_id=tenant_id,
        ref=ref,
        tokens_in=usage.prompt_tokens,
        tokens_out=usage.output_tokens,
        # THE MODEL, AND THE PRICE IS DERIVED FROM IT rather than passed beside it
        # (D-410). This call used to hand over two rupee figures and a model name as
        # three independent arguments, which is a ledger row whose `unit_cost_paid` can
        # disagree with its own `meta.model` — on an APPEND-ONLY table, invisibly, once
        # `azure_openai_model` became a live switch between two models 2.7x apart.
        # `record_ai_assist_usage` reads `rates.llm_inr_per_ktok(model)` and refuses an
        # unpriced identifier, so that row is now unrepresentable.
        model=model,
        feature=feature,
    )
    return AssistMetering(metered=metered.recorded, cost_inr=metered.cost_inr)


__all__ = [
    "ASSIST_FEATURE_COPILOT",
    "ASSIST_FEATURE_RESUMMARISE",
    "ASSIST_FEATURE_SCRIPT_DRAFT",
    "AssistMetering",
    "AssistSource",
    "MeterableAssist",
    "load_assist_source",
    "meter_assist",
    "transcript_for_model",
]
