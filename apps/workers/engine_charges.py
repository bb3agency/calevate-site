"""Compare what the engine CHARGED for each call with what we metered for it (D-678).

A ThinnestAI minute is metered at call end from the operator-attested rate (`billing/
engine_minutes.py`): that is the only figure available then, and hard rule 7 keeps it the
only path to `unit_cost_paid`. ThinnestAI's billing view later says what each call actually
cost the workspace (`costMicro`, snapshots/2026-10-07/pages/api-reference/usage/
list-call-log.md:533-540). This sweep reads that view and alarms when the two disagree by
more than the tolerance, which is how an attested rate that no longer matches the invoice
(a plan change, a voice band repriced, a top-up fee) is seen within the hour.

WHAT IT CORRECTS, AND HOW. Until 11 Oct 2026 the meter costed a minute at the attested rate
alone and left out the wallet top-up fee, so every ThinnestAI minute row written before then
understates our cost by the fee. `usage_events` is append-only (hard
rule 4), so `restate_minutes_without_fee` appends ONE compensating row per such call, the
shape `billing/cost_unit.py` set for a cost-only correction: `unit_type = 'other'`,
`qty = 1`, `unit_cost_paid` = the missing fee, `meta.kind` = `FEE_RESTATEMENT_META_KIND`,
stamped at the original row's `occurred_at`, under `lock_tenant_credits`. It moves our cost
only: the client is billed off minutes at its own rate and no reader of client money reads
`unit_cost_paid`. The population is closed by construction (a minute row the meter writes now
carries `meta.topup_fee`, so only rows from before the fix lack it), which is why it runs at
the top of this sweep rather than as a script someone has to remember: the comparison below
needs it done first, and once the backlog is restated each run finds nothing. A call's cost
is its minute row plus its compensating rows (`minute_cost_rows`), in both comparisons.

THE FEE WAS OVERSTATED UNTIL 12 OCT 2026. The fee was read as 10% on pay-as-you-go and 9% on
Pro (D-723); ThinnestAI then stated 2.36% on every plan (`billing/rates.THINNEST_TOPUP_FEE`).
Minute rows metered with a higher `meta.topup_fee`, and restatements written at a higher
`meta.fee`, overstate our cost by the difference. `correct_overstated_fees` appends one more
compensating row per such call, the same shape with a NEGATIVE `unit_cost_paid` (the excess)
and `meta.kind` = `FEE_CORRECTION_META_KIND`, after the restatement in the same sweep. A
minute row that was never restated is restated at 2.36% directly and needs no correction.

ONE ALARM PER CALL. A mismatch the sweep has already alarmed on is not alarmed again while it
persists (`_newly_mismatched` keeps the alarmed call ids in Redis for longer than the lookback
window); a clean, complete sweep closes the episode with `resolve_alert` and forgets them.
Without this the hourly cadence outran the alert path's hour-long quiet period and the same
calls mailed every hour.

WHICH ID. The call log's `id` is the id Place Call answered with (`out_…`, or `sch_…` for a
scheduled call), which is the id our call row holds (ThinnestAI email of 11 Oct 2026,
VENDOR-STATED; list-call-log.md:456-459 says it is the one `GET /calls/{id}` answers to).
Rows that match nothing are still counted, and a sweep where nothing matches says so in its
alarm.

PER CALL, TOO (D-690). The same figure rides `call.analysed` and `GET /calls/{id}` when the
call has settled (snapshots/2026-10-08/pages/api-reference/calls/get-call.md:498-514). The
post-call pipeline records it on `calls.engine_charged_inr` once and reconciles that call
(`reconcile_call_charge`); a call that was not settled by then gets its figure from this
sweep's log, recorded the same way.

WHAT IS COMPARED. `costMicro` is what the call cost the workspace and the wallet's top-up fee
is paid on top of it, when the wallet is filled. So the cost of a call is the charge times one
plus the fee, and that is what the meter reproduces: the operator attests the posted rate, the
meter adds the fee (`billing/engine_minutes.topup_fee`, the one helper both sides use), so a
variance means the posted rate itself is wrong. The fee is the payment gateway's, the same on
every plan (`thinnest_topup_fee`). On a Studio call the charge is ThinnestAI's own minute
only; Cartesia bills our key separately, and that cost is the call's `tts_kchars` row, which
must exist.

WHAT THE CALL WAS BILLED AS (D-796). Get Call and `call.analysed` carry the call's `billing`
(`CallBilling`): whose keys it ran on after any fallback, the voice plan it was priced on, the
per-minute rate and the seconds charged (`snapshots/2026-10-15/pages/api-reference/calls/
get-call.md:1228-1294`; `api-reference/webhooks/create-webhook.md:330-340`). An agent whose
key is gone when a call starts runs on the workspace's scope (get-call.md:200-203), so the
rate key the route was sold on is not always what ran. `reconcile_call_charge` checks a
settled call three ways (`billing_findings`) and names what it finds in
`engine_call_cost_variance`:

- the scope and voice plan against the ones the route's rate key was sold on
  (`expected_billing`), so the alarm says which stack really ran;
- the engine's billed seconds against our billed minutes, on the engine's rule: 30-second
  steps at half the per-minute rate each (get-call.md:1266-1275), the pulse the meter bills;
  a call that ended before the agent spoke is rounded to the carrier's block instead
  (:1276-1285), and a difference there is named as such;
- the engine's per-minute rate against the attested one, before the top-up fee.

It reconciles and never prices: the engine's rate is evidence, and `unit_cost_paid` stays the
operator-attested rate (hard rule 7). A call that is not settled (`billed_seconds` None) is
not checked on `billing`. Nor is a forwarded call: the docs say nothing of `billing` on a call
no agent answered, and ThinnestAI's email of 15 Oct 2026 says to trust `costMicro` for those
(VENDOR-STATED, `docs/evidence/thinnest-reply-2026-10-15.md` §A), so only the total is
compared. The hourly sweep reads the call log, which carries no `billing`
(`api-reference/calls/list-calls.md`), so it compares totals, and reads Get Call for the
calls it settles itself to check their billing (`check_late_billing`, bounded per run).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, cast
from uuid import UUID

from calevate_shared.engine import ExecutionSnapshot, VoiceEngine
from calevate_shared.events import CallBilling, CallKeys
from sqlalchemy import text

from apps.api.billing.engine_minutes import (
    BYOK_LLM_VOICE_RATE_KEY,
    BYOK_VOICE_RATE_KEY,
    OWN_VOICE_RATE_KEYS,
    PULSE_SECONDS,
    TOPUP_FEE_META_KEY,
    billed_minutes,
    cost_with_fee,
    thinnest_topup_fee,
    topup_fee,
)
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.billing.service import _ROW_COST_SQL, LEDGER_RUNG_KEY, lock_tenant_credits
from apps.api.core.alerting import alert, resolve_alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.charges import EngineCharge, ReportsCharges
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.engine.vendor_http import EngineRejectedError
from apps.workers.workspace_walk import WalkReport, walk_workspaces

log = get_logger(__name__)

CHARGE_SWEEP_MINUTES: Final = frozenset({47})

#: Days back the log is read. The vendor's `from` is a date in the workspace's own time
#: zone, so yesterday is included to cover the hours either side of midnight.
CHARGE_LOOKBACK_DAYS: Final = 1

#: The difference per call that is noise rather than a wrong rate: the larger of a paisa
#: amount and a share of the charge. A wrong attested rate moves every call by its own
#: share, so it clears this on any call of a minute or more.
CHARGE_TOLERANCE_INR: Final = Decimal("0.10")
CHARGE_TOLERANCE_SHARE: Final = Decimal("0.02")

#: How many call ids an alarm names before it stops listing them.
_ALERT_ID_LIMIT: Final = 5

#: `meta.kind` of the compensating row that adds the top-up fee to a minute metered without it.
FEE_RESTATEMENT_META_KIND: Final = "engine_topup_fee_restatement"
#: `meta.kind` of the compensating row that takes back a fee costed above the stated one.
FEE_CORRECTION_META_KIND: Final = "engine_topup_fee_correction"

#: How many minute rows one tenant's restatement takes per sweep; the rest wait an hour.
_RESTATE_BATCH: Final = 500

#: The call ids already alarmed as mismatched, kept past the lookback window so a call cannot
#: fall out of the memory while the sweep still reads it.
_ALARMED_KEY: Final = "engine_charges:mismatch_alarmed:{engine}"
_ALARMED_TTL_S: Final = (CHARGE_LOOKBACK_DAYS + 2) * 86_400

_ROUTE_SQL = text(
    "SELECT tenant_id FROM engine_agent_routes WHERE engine = :engine "
    "AND engine_agent_ref = :ref ORDER BY active DESC, updated_at DESC LIMIT 1"
)


def minute_cost_rows(prefix: str = "") -> str:
    """The rows a call's engine-minute cost is: its metered minute, any fee restatement and
    any fee correction."""
    return (
        f"({prefix}unit_type = 'platform_min' OR ({prefix}unit_type = 'other' "
        f"AND {prefix}meta->>'kind' IN ('{FEE_RESTATEMENT_META_KIND}', "
        f"'{FEE_CORRECTION_META_KIND}')))"
    )


_METERED_SQL = text(
    "SELECT c.id, sum(u.qty * u.unit_cost_paid), bool_or(u.unit_cost_paid IS NULL) "
    "FROM calls c JOIN usage_events u ON u.call_id = c.id AND u.tenant_id = c.tenant_id "
    f"AND {minute_cost_rows('u.')} WHERE c.engine_call_id = :ecid GROUP BY c.id"
)


@dataclass
class _Tally:
    compared: int = 0
    matched: int = 0
    unmatched: int = 0
    unpriced: int = 0
    unreached: int = 0
    mismatched: list[tuple[str, Decimal, Decimal]] = field(default_factory=list)


def within_tolerance(metered: Decimal, charged: Decimal) -> bool:
    """Is our metered cost close enough to the vendor's charge to be the same figure?"""
    allowed = max(CHARGE_TOLERANCE_INR, abs(charged) * CHARGE_TOLERANCE_SHARE)
    return abs(metered - charged) <= allowed


def variance_sentence(metered: Decimal, expected: Decimal) -> str:
    """`metered ₹x vs charged-with-fee ₹y: +₹z (+p%)` — the figure an operator acts on."""
    diff = metered - expected
    share = (
        (diff / expected * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUNDING)
        if expected
        else None
    )
    sign = "+" if diff >= 0 else "-"
    pct = f" ({sign}{abs(share)}%)" if share is not None else ""
    return (
        f"metered INR {metered} vs charged-with-fee INR {expected}: "
        f"{sign}INR {abs(diff).quantize(MONEY_Q, rounding=ROUNDING)}{pct}"
    )


_SET_CHARGE_SQL = text(
    "UPDATE calls SET engine_charged_inr = :charged, updated_at = now() "
    "WHERE id = :cid AND engine_charged_inr IS NULL RETURNING id"
)
_CALL_COSTS_SQL = text(
    "SELECT "
    f"sum(qty * unit_cost_paid) FILTER (WHERE {minute_cost_rows()}), "
    f"bool_or(unit_cost_paid IS NULL) FILTER (WHERE {minute_cost_rows()}), "
    "count(*) FILTER (WHERE unit_type = 'platform_min'), "
    "max(meta->>'engine_rate_key') FILTER (WHERE unit_type = 'platform_min'), "
    "count(*) FILTER (WHERE unit_type = 'tts_kchars'), "
    "sum(qty * unit_cost_paid) FILTER (WHERE unit_type = 'tts_kchars'), "
    "max(meta->>'billed_minutes') FILTER (WHERE unit_type = 'platform_min'), "
    "max(meta->>'inr_per_min') FILTER (WHERE unit_type = 'platform_min'), "
    "bool_or(meta->>'own_model' IS NOT NULL) FILTER (WHERE unit_type = 'platform_min') "
    "FROM usage_events WHERE call_id = :cid AND tenant_id = :tid"
)

#: The rate keys that are one of the engine's voice bands, named as its `voicePlan` names them.
_BAND_RATE_KEYS: Final[frozenset[str]] = frozenset({"standard", "premium", "studio"})


def expected_billing(
    rate_key: str | None, *, own_model: bool
) -> tuple[CallKeys, str | None] | None:
    """The keys and voice plan a call metered at `rate_key` was sold to run on; None for a
    key with no single answer (the engine's base `platform` minute).

    A band minute runs on the engine's keys, or on our model alone when the route answers on
    our model (`llm` is priced at the band, get-call.md:1253-1265); an own-voice minute is a
    flat own-key price with no voice plan."""
    if rate_key == BYOK_VOICE_RATE_KEY:
        return "voice", None
    if rate_key == BYOK_LLM_VOICE_RATE_KEY:
        return "llm_voice", None
    if rate_key in _BAND_RATE_KEYS:
        return ("llm" if own_model else "off"), rate_key
    return None


def billing_findings(
    billing: CallBilling,
    *,
    billed_seconds: int,
    engine: str,
    rate_key: str | None,
    own_model: bool,
    our_minutes: Decimal | None,
    attested_inr_per_min: Decimal | None,
) -> list[str]:
    """Where a settled call's `billing` disagrees with the minute we metered, one sentence
    each; empty when it agrees. Three separate questions, so the alarm names which one:

    - **scope**: the keys and voice plan against the ones the rate key was sold on;
    - **seconds**: the engine's billed seconds, on its own step rule (30-second steps at
      half the minute rate, get-call.md:1266-1275, which is `billed_minutes` at the pulse),
      against our billed minutes;
    - **rate**: the engine's per-minute rate against the attested one, priced on our
      minutes before the top-up fee, so a rate gap is not read as a seconds gap.

    A call that ended before the agent spoke (`carrier_only`) is charged the carrier's fee
    only and rounded to the carrier's block (get-call.md:1276-1285), so the rate is not
    compared, and differing seconds are named as the carrier's block against our pulse:
    the block's length is UNKNOWN (no page states it), so it cannot be allowed for. The
    rate is not compared when either side is unknown: an unpriced minute (already alarmed)
    or a rate the engine stated in another currency."""
    found: list[str] = []
    expected = expected_billing(rate_key, own_model=own_model)
    if expected is not None and (billing.keys, billing.voice_plan) != expected:
        keys, plan = expected
        found.append(
            f"The call ran on keys={billing.keys} voice_plan={billing.voice_plan or 'none'}, "
            f"not the keys={keys} voice_plan={plan or 'none'} the {rate_key} route was sold "
            "on: a key of ours was gone when it started, or the route's rate key is stale."
        )
    if our_minutes is None:
        return found
    their_minutes = billed_minutes(Decimal(billed_seconds), pulse_s=PULSE_SECONDS[engine])
    if their_minutes != our_minutes:
        found.append(
            (
                f"Seconds, not rate: the call ended before the agent spoke and the voice "
                f"platform billed the phone carrier's block of {billed_seconds}s for the "
                f"carrier's fee only, against our {PULSE_SECONDS[engine]}-second pulse of "
                f"{our_minutes} min."
            )
            if billing.carrier_only
            else (
                f"Seconds, not rate: the voice platform billed {billed_seconds}s "
                f"({their_minutes} min in {PULSE_SECONDS[engine]}-second steps) against our "
                f"{our_minutes} min."
            )
        )
    if billing.carrier_only or billing.rate_inr_per_min is None or attested_inr_per_min is None:
        return found
    theirs = (our_minutes * billing.rate_inr_per_min).quantize(MONEY_Q, rounding=ROUNDING)
    ours = (our_minutes * attested_inr_per_min).quantize(MONEY_Q, rounding=ROUNDING)
    if not within_tolerance(ours, theirs):
        found.append(
            f"Rate: the voice platform charged INR {billing.rate_inr_per_min}/min against the "
            f"attested INR {attested_inr_per_min}/min, INR {theirs} against INR {ours} on our "
            f"{our_minutes} min before the top-up fee."
        )
    return found


def checked_billing(
    billing: CallBilling | None,
    *,
    forwarded: bool,
    engine: str,
    rate_key: str | None,
    own_model: bool,
    our_minutes: object,
    attested_inr_per_min: object,
) -> list[str] | None:
    """`billing_findings` for a call that can be checked; None for one that cannot: no
    billing, not settled (`billed_seconds` None), or forwarded (module docstring). The meta
    figures are passed as read from the minute row."""
    if billing is None or billing.billed_seconds is None or forwarded:
        return None
    return billing_findings(
        billing,
        billed_seconds=billing.billed_seconds,
        engine=engine,
        rate_key=rate_key,
        own_model=own_model,
        our_minutes=_decimal_or_none(our_minutes),
        attested_inr_per_min=_decimal_or_none(attested_inr_per_min),
    )


async def record_engine_charge(tenant_id: UUID, call_id: UUID, charged_inr: Decimal) -> bool:
    """Write the vendor's charge on the call once. True when this write set it; a charge
    already recorded is never overwritten, so a replay or a later read changes nothing."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(_SET_CHARGE_SQL, {"charged": charged_inr, "cid": call_id})
        ).first()
    return row is not None


async def reconcile_call_charge(
    tenant_id: UUID,
    call_id: UUID,
    charged_inr: Decimal,
    *,
    engine: str,
    billing: CallBilling | None = None,
    forwarded: bool = False,
) -> str:
    """Record one settled call's charge and compare it with what we metered for it.

    Alarms, never corrects (hard rule 4): `engine_call_cost_variance` when the attested
    minute differs from the charge with its top-up fee by more than the tolerance, or when
    the call's `billing` disagrees with the route it was metered on (`billing_findings`),
    naming each; `engine_studio_synthesis_cost_missing` when a Studio call has no Cartesia
    synthesis row beside its minute. Returns what happened, for the pipeline's span.
    """
    if not await record_engine_charge(tenant_id, call_id, charged_inr):
        return "already_recorded"
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(_CALL_COSTS_SQL, {"cid": call_id, "tid": tenant_id})).one()
    (
        metered,
        unpriced,
        minute_rows,
        rate_key,
        tts_rows,
        tts_cost,
        our_minutes,
        attested,
        own_model,
    ) = row
    if not minute_rows:
        return "not_metered"
    outcome = "matched"
    if rate_key in OWN_VOICE_RATE_KEYS and not tts_rows:
        outcome = "synthesis_cost_missing"
        alert(
            "WORKER_TERMINAL",
            "engine_studio_synthesis_cost_missing",
            detail=(
                "a Studio call has the voice platform's minute on the ledger and no Cartesia "
                "synthesis cost beside it, so the call's cost is understated by what our "
                "Cartesia key was billed for it"
            ),
            call_id=str(call_id),
            tenant_id=str(tenant_id),
        )
    checked = checked_billing(
        billing,
        forwarded=forwarded,
        engine=engine,
        rate_key=rate_key,
        own_model=bool(own_model),
        our_minutes=our_minutes,
        attested_inr_per_min=attested,
    )
    found = checked or []
    if unpriced or metered is None:
        # Metered with no attested rate: `engine_minute_rate_unattested` already alarmed, so
        # only a disagreement on what ran is news.
        if not found:
            return "unpriced"
        variance = ""
    else:
        fee = topup_fee(engine)
        expected = cost_with_fee(charged_inr, fee=fee)
        metered_inr = Decimal(str(metered)).quantize(MONEY_Q, rounding=ROUNDING)
        total_matches = within_tolerance(metered_inr, expected)
        if total_matches and not found:
            return outcome
        variance = (
            ""
            if total_matches
            else (
                f"{variance_sentence(metered_inr, expected)} (the voice platform charged INR "
                f"{charged_inr}, plus the {fee * 100}% top-up fee). The attested per-minute "
                "rate does not reproduce what this call cost."
            )
        )
    synthesis = (
        f"Cartesia synthesis is metered separately at INR "
        f"{Decimal(str(tts_cost)).quantize(MONEY_Q, rounding=ROUNDING)}."
        if tts_cost is not None
        else ""
    )
    # Only a guess while the call's own keys are unknown; `billing` names them when it is read.
    fallback = (
        "On our own model and voice a different charge can also mean the call ran on the "
        "workspace's default keys because one of ours was gone when it started: check the "
        "workspace's own keys in ops Voices."
        if rate_key == BYOK_LLM_VOICE_RATE_KEY and checked is None
        else ""
    )
    alert(
        "WORKER_TERMINAL",
        "engine_call_cost_variance",
        detail=f"rate_key={rate_key}: "
        + " ".join(part for part in (variance, *found, synthesis, fallback) if part),
        call_id=str(call_id),
        tenant_id=str(tenant_id),
    )
    return "variance"


# --- the fee restatement -------------------------------------------------------------------

_ENGINE_TENANTS_SQL = text(
    "SELECT DISTINCT tenant_id FROM engine_agent_routes WHERE engine = :engine ORDER BY tenant_id"
)


async def engine_tenants(engine: str) -> list[UUID]:
    """Every tenant with an agent route on `engine`, through the route bridge `db/registry`
    exempts for exactly this resolution."""
    async with untenanted_session() as session:
        return [
            UUID(str(row))
            for row in (await session.execute(_ENGINE_TENANTS_SQL, {"engine": engine})).scalars()
        ]


#: Priced minute rows of an attested-minute engine metered without the fee and not yet
#: restated. Unqualified columns are the outer row's, which `_ROW_COST_SQL` relies on.
#: A row whose fee rounds to nothing (a zero-length call's ₹0 minute) is left out here
#: rather than skipped after reading: nothing is ever written for it, so it would head every
#: batch and hold back the calls after it. `:half_quantum` is where `fee_delta`'s
#: ROUND_HALF_UP first reaches one `MONEY_Q`.
_WITHOUT_FEE_SQL = text(
    f"SELECT call_id, {_ROW_COST_SQL}, occurred_at, meta->>'engine_rate_key', "
    f"meta->>'{LEDGER_RUNG_KEY}', meta->>'voice_tier' FROM usage_events u "
    "WHERE unit_type = 'platform_min' AND call_id IS NOT NULL AND unit_cost_paid IS NOT NULL "
    "AND meta->>'engine_rate_key' IS NOT NULL "
    f"AND meta->>'{TOPUP_FEE_META_KEY}' IS NULL "
    f"AND ({_ROW_COST_SQL}) * :fee >= :half_quantum "
    "AND NOT EXISTS (SELECT 1 FROM usage_events r WHERE r.tenant_id = u.tenant_id "
    "AND r.call_id = u.call_id AND r.unit_type = 'other' AND r.meta->>'kind' = :kind) "
    "ORDER BY call_id LIMIT :cap"
)
_RESTATED_SQL = text(
    "SELECT 1 FROM usage_events WHERE tenant_id = :tid AND call_id = :cid "
    "AND unit_type = 'other' AND meta->>'kind' = :kind LIMIT 1"
)
_INSERT_RESTATEMENT_SQL = text(
    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid, "
    "occurred_at, meta, created_at) VALUES (:id, :tid, :cid, 'other', 1, :cost, :at, "
    "CAST(:meta AS jsonb), now())"
)


def fee_delta(metered_inr: Decimal, *, fee: Decimal) -> Decimal:
    """The top-up fee a minute metered at `metered_inr` without it is missing."""
    return (metered_inr * fee).quantize(MONEY_Q, rounding=ROUNDING)


async def restate_tenant_minutes(tenant_id: UUID, *, fee: Decimal) -> list[tuple[UUID, Decimal]]:
    """Append the missing fee for each of this tenant's minute rows metered without it.

    Returns `(call_id, delta)` for each row written. Idempotent: the dedupe read runs with
    `lock_tenant_credits` held, as `billing/cost_unit.record_cost_unit_correction` takes it,
    so two sweeps write one row between them, and a restated call is never selected again.
    """
    written: list[tuple[UUID, Decimal]] = []
    async with tenant_session(tenant_id) as session:
        await lock_tenant_credits(session, tenant_id)
        rows = (
            await session.execute(
                _WITHOUT_FEE_SQL,
                {
                    "kind": FEE_RESTATEMENT_META_KIND,
                    "cap": _RESTATE_BATCH,
                    "fee": fee,
                    "half_quantum": MONEY_Q / 2,
                },
            )
        ).all()
        for call_id, metered, occurred_at, rate_key, rung, voice in rows:
            metered_inr = Decimal(str(metered))
            delta = fee_delta(metered_inr, fee=fee)
            already = (
                await session.execute(
                    _RESTATED_SQL,
                    {"tid": tenant_id, "cid": call_id, "kind": FEE_RESTATEMENT_META_KIND},
                )
            ).first()
            if already:
                continue
            meta = {
                "kind": FEE_RESTATEMENT_META_KIND,
                "correction_ref": f"topupfee:{call_id}",
                "fee": str(fee),
                "metered_inr": str(metered_inr),
                # Not `engine_rate_key`: that key selects the rows this restates.
                "corrected_engine_rate_key": rate_key,
                # The rung and voice of the minute it corrects, so the cost lands beside them.
                LEDGER_RUNG_KEY: rung,
                "voice_tier": voice,
                "issued_at": datetime.now(UTC).isoformat(),
            }
            await session.execute(
                _INSERT_RESTATEMENT_SQL,
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "cost": delta,
                    "at": occurred_at,
                    "meta": json.dumps(meta),
                },
            )
            written.append((UUID(str(call_id)), delta))
    return written


async def restate_minutes_without_fee(engine: str) -> int:
    """Restate every tenant's minutes on `engine` metered without the top-up fee. Returns
    how many calls were restated. One tenant's failure is logged and does not stop the rest."""
    fee = topup_fee(engine)
    if fee == 0:
        return 0
    tenants = await engine_tenants(engine)
    restated = 0
    for tenant_id in tenants:
        try:
            written = await restate_tenant_minutes(tenant_id, fee=fee)
        except Exception as exc:
            log.warning(
                "engine_fee_restatement_failed",
                extra={"tenant_id": str(tenant_id), "reason": type(exc).__name__},
            )
            continue
        if written:
            log.info(
                "engine_fee_restated",
                extra={"tenant_id": str(tenant_id), "calls": len(written), "fee": str(fee)},
            )
        restated += len(written)
    return restated


# --- the fee correction (12 Oct 2026) -----------------------------------------------------

#: The rows that carry a fee above the stated one and are not yet corrected: a minute row
#: metered with `meta.topup_fee` above it, or a restatement written at `meta.fee` above it.
#: A call has at most one of them (one `platform_min` row per call by
#: `ux_usage_events_tenant_call_unit`, and a restatement only for a minute row without
#: `topup_fee`), so the row LIMIT never splits a call across two batches. A ₹0 row has no
#: excess and is left out for the reason `_WITHOUT_FEE_SQL` gives.
_OVERSTATED_SQL = text(
    f"SELECT call_id, unit_type, {_ROW_COST_SQL}, occurred_at, meta FROM usage_events u "
    f"WHERE call_id IS NOT NULL AND unit_cost_paid IS NOT NULL AND ({_ROW_COST_SQL}) > 0 AND ("
    "(unit_type = 'platform_min' AND meta->>'engine_rate_key' IS NOT NULL "
    f"AND meta->>'{TOPUP_FEE_META_KEY}' IS NOT NULL "
    f"AND CAST(meta->>'{TOPUP_FEE_META_KEY}' AS numeric) > :fee) "
    "OR (unit_type = 'other' AND meta->>'kind' = :restated "
    "AND CAST(meta->>'fee' AS numeric) > :fee)) "
    "AND NOT EXISTS (SELECT 1 FROM usage_events r WHERE r.tenant_id = u.tenant_id "
    "AND r.call_id = u.call_id AND r.unit_type = 'other' AND r.meta->>'kind' = :kind) "
    "ORDER BY call_id LIMIT :cap"
)


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        return None if value is None else Decimal(str(value))
    except ArithmeticError:
        return None


def fee_excess(unit_type: str, cost_inr: Decimal, meta: dict[str, Any], *, fee: Decimal) -> Decimal:
    """What one row costed above `fee`, in rupees at `MONEY_Q`; zero when nothing is over.

    A minute row's cost is its posted minutes with its own fee, so the correct cost is the same
    minutes with `fee`; with its `billed_minutes` and `inr_per_min` recorded the minutes are
    re-priced exactly, otherwise the fee is taken out of the cost. A restatement's cost is the
    fee on the minute it restated (`metered_inr`), so the correct one is `fee` on that."""
    if unit_type == "platform_min":
        was = _decimal_or_none(meta.get(TOPUP_FEE_META_KEY))
        if was is None or was <= fee:
            return Decimal(0)
        minutes = _decimal_or_none(meta.get("billed_minutes"))
        rate = _decimal_or_none(meta.get("inr_per_min"))
        if minutes is not None and rate is not None:
            correct = cost_with_fee(minutes * rate, fee=fee)
        else:
            correct = (cost_inr * (Decimal(1) + fee) / (Decimal(1) + was)).quantize(
                MONEY_Q, rounding=ROUNDING
            )
    else:
        was = _decimal_or_none(meta.get("fee"))
        base = _decimal_or_none(meta.get("metered_inr"))
        if was is None or was <= fee or base is None:
            return Decimal(0)
        correct = fee_delta(base, fee=fee)
    return max(Decimal(0), (cost_inr - correct).quantize(MONEY_Q, rounding=ROUNDING))


async def correct_tenant_fees(tenant_id: UUID, *, fee: Decimal) -> list[tuple[UUID, Decimal]]:
    """Append a negative compensating row for each of this tenant's calls costed at a top-up
    fee above `fee`. Returns `(call_id, excess)` for each row written. Idempotent the way
    `restate_tenant_minutes` is: the dedupe read runs under `lock_tenant_credits`, and a
    corrected call is never selected again."""
    written: list[tuple[UUID, Decimal]] = []
    async with tenant_session(tenant_id) as session:
        await lock_tenant_credits(session, tenant_id)
        rows = (
            await session.execute(
                _OVERSTATED_SQL,
                {
                    "fee": fee,
                    "restated": FEE_RESTATEMENT_META_KIND,
                    "kind": FEE_CORRECTION_META_KIND,
                    "cap": _RESTATE_BATCH,
                },
            )
        ).all()
        for call_id, unit_type, cost, occurred_at, raw_meta in rows:
            source: dict[str, Any] = dict(raw_meta or {})
            excess = fee_excess(str(unit_type), Decimal(str(cost)), source, fee=fee)
            if excess == 0:
                continue
            already = (
                await session.execute(
                    _RESTATED_SQL,
                    {"tid": tenant_id, "cid": call_id, "kind": FEE_CORRECTION_META_KIND},
                )
            ).first()
            if already:
                continue
            restated = unit_type != "platform_min"
            meta = {
                "kind": FEE_CORRECTION_META_KIND,
                "correction_ref": f"topupfeefix:{call_id}",
                "fee": str(fee),
                "fee_was": str(source.get("fee") if restated else source.get(TOPUP_FEE_META_KEY)),
                "excess_inr": str(excess),
                "corrected_row": FEE_RESTATEMENT_META_KIND if restated else "platform_min",
                # Not `engine_rate_key`: that key selects the rows the restatement reads.
                "corrected_engine_rate_key": source.get("corrected_engine_rate_key")
                if restated
                else source.get("engine_rate_key"),
                LEDGER_RUNG_KEY: source.get(LEDGER_RUNG_KEY),
                "voice_tier": source.get("voice_tier"),
                "issued_at": datetime.now(UTC).isoformat(),
            }
            await session.execute(
                _INSERT_RESTATEMENT_SQL,
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "cost": -excess,
                    "at": occurred_at,
                    "meta": json.dumps(meta),
                },
            )
            written.append((UUID(str(call_id)), excess))
    return written


async def correct_overstated_fees(engine: str) -> int:
    """Correct every tenant's calls on `engine` costed at a top-up fee above today's. Returns
    how many calls were corrected. One tenant's failure is logged and does not stop the rest."""
    fee = topup_fee(engine)
    if fee == 0:
        return 0
    tenants = await engine_tenants(engine)
    corrected = 0
    for tenant_id in tenants:
        try:
            written = await correct_tenant_fees(tenant_id, fee=fee)
        except Exception as exc:
            log.warning(
                "engine_fee_correction_failed",
                extra={"tenant_id": str(tenant_id), "reason": type(exc).__name__},
            )
            continue
        if written:
            log.info(
                "engine_fee_corrected",
                extra={"tenant_id": str(tenant_id), "calls": len(written), "fee": str(fee)},
            )
        corrected += len(written)
    return corrected


async def _newly_mismatched(engine: str, call_ids: list[str]) -> list[str]:
    """The mismatched calls not alarmed before, remembered from now on. Fails open: if Redis
    cannot say, every call is new, so a mismatch is never silenced by an outage."""
    key = _ALARMED_KEY.format(engine=engine)
    try:
        redis = get_redis()
        fresh = [
            call_id
            for call_id in call_ids
            if await cast("Awaitable[int]", redis.sadd(key, call_id))
        ]
        await redis.expire(key, _ALARMED_TTL_S)
    except Exception as exc:
        log.warning("engine_charge_memory_unavailable", extra={"reason": type(exc).__name__})
        return list(call_ids)
    return fresh


async def _forget_mismatches(engine: str) -> None:
    try:
        await get_redis().delete(_ALARMED_KEY.format(engine=engine))
    except Exception as exc:
        log.warning("engine_charge_memory_unavailable", extra={"reason": type(exc).__name__})


# --- billing of calls this sweep settles -----------------------------------------------------
#
# A call the pipeline metered before the engine settled it is settled here from the call log,
# which carries no `billing`, so its scope and seconds are read from Get Call. The calls wait
# in a Redis hash keyed by our call id: written only by the one `record_engine_charge` that
# set the charge (a conditional UPDATE, so once per call), removed once checked, so a call is
# checked at most once. Redis and not a column: `calls` has no free-form field and
# `usage_events` is an append-only cost ledger, and the alarm memory above already lives here.
# A Redis loss drops pending checks, never money: the totals were compared already.

_BILLING_PENDING_KEY: Final = "engine_charges:billing_pending:{engine}"
#: Get Call reads per sweep; the rest wait an hour, so a backlog cannot crowd the vendor.
BILLING_CHECKS_PER_RUN: Final = 20
#: A call Get Call keeps refusing (not a throttle or an outage) is given up after this many.
BILLING_CHECK_ATTEMPTS: Final = 3


async def queue_billing_check(
    engine: str, tenant_id: UUID, call_id: UUID, engine_call_id: str
) -> None:
    """Remember a call this sweep settled, for `check_late_billing`. Idempotent (`HSETNX`)."""
    entry = {"tenant_id": str(tenant_id), "engine_call_id": engine_call_id, "attempts": 0}
    try:
        await cast(
            "Awaitable[int]",
            get_redis().hsetnx(
                _BILLING_PENDING_KEY.format(engine=engine), str(call_id), json.dumps(entry)
            ),
        )
    except Exception as exc:
        log.warning(
            "engine_billing_check_unqueued",
            extra={"call_id": str(call_id), "reason": type(exc).__name__},
        )


def _vendor_busy(exc: ProblemError) -> bool:
    """A refusal that says nothing about the call: throttled (after the adapter's own 429
    ladder), unreachable, or a 5xx. The next run asks again with no attempt spent."""
    if isinstance(exc, EngineRejectedError):
        return exc.vendor_status >= 500
    return exc.kind == "transient" or exc.code == "engine_unreachable"


_CALL_ROUTE_SQL = text(
    "SELECT max(meta->>'engine_rate_key'), max(meta->>'billed_minutes'), "
    "max(meta->>'inr_per_min'), bool_or(meta->>'own_model' IS NOT NULL) "
    "FROM usage_events WHERE call_id = :cid AND tenant_id = :tid AND unit_type = 'platform_min'"
)


async def check_settled_billing(
    tenant_id: UUID, call_id: UUID, snapshot: ExecutionSnapshot, *, engine: str
) -> str:
    """Check one late-settled call's `billing` against its metered minute; the total was
    compared by the sweep, so only `billing_findings` can alarm here."""
    async with tenant_session(tenant_id) as session:
        rate_key, minutes, attested, own_model = (
            await session.execute(_CALL_ROUTE_SQL, {"cid": call_id, "tid": tenant_id})
        ).one()
    found = checked_billing(
        snapshot.billing,
        forwarded=snapshot.forwarded,
        engine=engine,
        rate_key=rate_key,
        own_model=bool(own_model),
        our_minutes=minutes,
        attested_inr_per_min=attested,
    )
    if found is None:
        return "not_checked"
    if not found:
        return "matched"
    alert(
        "WORKER_TERMINAL",
        "engine_call_cost_variance",
        detail=f"rate_key={rate_key}: " + " ".join(found),
        call_id=str(call_id),
        tenant_id=str(tenant_id),
    )
    return "variance"


async def check_late_billing(engine: VoiceEngine) -> int:
    """Read Get Call for up to `BILLING_CHECKS_PER_RUN` queued calls and check each one's
    billing. Returns how many were checked. No database session is open across a vendor
    read. A busy vendor stops the run with the rest left queued."""
    key = _BILLING_PENDING_KEY.format(engine=engine.name)
    try:
        redis = get_redis()
        pending = await cast("Awaitable[dict[str, str]]", redis.hgetall(key))
    except Exception as exc:
        log.warning("engine_charge_memory_unavailable", extra={"reason": type(exc).__name__})
        return 0
    checked = 0
    for call_id in sorted(pending)[:BILLING_CHECKS_PER_RUN]:
        entry = json.loads(pending[call_id])
        try:
            snapshot = await engine.get_execution(entry["engine_call_id"])
        except ProblemError as exc:
            if _vendor_busy(exc):
                log.warning(
                    "engine_billing_check_deferred",
                    extra={"call_id": call_id, "code": exc.code, "left": len(pending) - checked},
                )
                break
            attempts = int(entry["attempts"]) + 1
            if attempts >= BILLING_CHECK_ATTEMPTS:
                log.warning(
                    "engine_billing_check_abandoned", extra={"call_id": call_id, "code": exc.code}
                )
                await cast("Awaitable[int]", redis.hdel(key, call_id))
            else:
                await cast(
                    "Awaitable[int]",
                    redis.hset(key, call_id, json.dumps(entry | {"attempts": attempts})),
                )
            continue
        await check_settled_billing(
            UUID(entry["tenant_id"]), UUID(call_id), snapshot, engine=engine.name
        )
        await cast("Awaitable[int]", redis.hdel(key, call_id))
        checked += 1
    return checked


async def _tenant_of(engine: str, agent_ref: str | None) -> UUID | None:
    """The tenant an agent's route belongs to; the route bridge is the one untenanted read
    `db/registry` exempts for exactly this resolution."""
    if agent_ref is None:
        return None
    async with untenanted_session() as session:
        tenant = (await session.execute(_ROUTE_SQL, {"engine": engine, "ref": agent_ref})).scalar()
    return UUID(str(tenant)) if tenant is not None else None


async def _compare(engine: str, charge: EngineCharge, tally: _Tally) -> None:
    if charge.charged_inr is None:
        return
    tally.compared += 1
    tenant_id = await _tenant_of(engine, charge.engine_agent_ref)
    if tenant_id is None:
        tally.unmatched += 1
        return
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(_METERED_SQL, {"ecid": charge.engine_call_id})).first()
    if row is None:
        # Not metered yet (the pipeline runs after `call.analysed`), or the id is not ours.
        tally.unmatched += 1
        return
    tally.matched += 1
    # A call the pipeline saw before the vendor settled it gets its figure here, once, and
    # its `billing`, which the call log does not carry, is read from Get Call later.
    if await record_engine_charge(tenant_id, UUID(str(row[0])), charge.charged_inr):
        await queue_billing_check(engine, tenant_id, UUID(str(row[0])), charge.engine_call_id)
    if row[2] or row[1] is None:
        # Metered with no attested rate: `engine_minute_rate_unattested` already alarmed.
        tally.unpriced += 1
        return
    metered = Decimal(str(row[1])).quantize(MONEY_Q, rounding=ROUNDING)
    expected = cost_with_fee(charge.charged_inr, fee=topup_fee(engine))
    if not within_tolerance(metered, expected):
        tally.mismatched.append((str(row[0]), metered, expected))


async def reconcile_engine_charges(ctx: dict[str, Any], *, now: datetime | None = None) -> str:
    engine = get_engine()
    if not isinstance(engine, ReportsCharges) or not engine.holds_credentials():
        return "engine_without_charges"
    since = ((now or datetime.now(UTC)) - timedelta(days=CHARGE_LOOKBACK_DAYS)).date()
    # PER WORKSPACE (D-693): each client's calls are charged in its own customer workspace,
    # and the developer workspace holds the calls of agents made before D-693. The balance
    # charged is always ours; `costMicro` is read where each call ran.
    charges: list[EngineCharge] = []
    complete = True
    other_currency = 0
    walk = WalkReport()
    async for visit in walk_workspaces("engine_charges", report=walk):
        with in_workspace(visit.workspace):
            listing = await engine.list_call_charges(since=since)
        charges.extend(listing.charges)
        complete = complete and listing.complete
        other_currency += listing.other_currency
    complete = complete and walk.deferred == 0
    restated = await restate_minutes_without_fee(engine.name)
    # After the restatement, so a restatement written earlier at a higher fee is corrected.
    corrected = await correct_overstated_fees(engine.name)
    tally = _Tally()
    for charge in charges:
        try:
            await _compare(engine.name, charge, tally)
        except Exception as exc:
            # Ids and a class name only (hard rule 6): one row's failure is not the sweep's.
            log.warning(
                "engine_charge_check_failed",
                extra={"engine_call_id": charge.engine_call_id, "reason": type(exc).__name__},
            )
            tally.unreached += 1
    # After the comparison, which queued this run's late-settled calls.
    billing_checked = await check_late_billing(engine)
    fresh = (
        await _newly_mismatched(engine.name, [call_id for call_id, _m, _e in tally.mismatched])
        if tally.mismatched
        else []
    )
    if fresh:
        named = "; ".join(
            f"{call_id}: {variance_sentence(metered, expected)}"
            for call_id, metered, expected in tally.mismatched[:_ALERT_ID_LIMIT]
        )
        alert(
            "WORKER_TERMINAL",
            "engine_charge_mismatch",
            detail=(
                f"engine={engine.name}: {len(tally.mismatched)} call(s) metered at a cost "
                f"that differs from what the voice platform charged, with the "
                f"{topup_fee(engine.name) * 100}% top-up fee added, by more than the "
                f"tolerance, so the attested per-minute rate no longer matches the invoice "
                f"({len(fresh)} not reported before). {named}"
            ),
            episode=engine.name,
        )
    elif tally.mismatched:
        # Already alarmed: the open episode stands for it, and a mail an hour helps nobody.
        log.warning(
            "engine_charge_mismatch_persisting",
            extra={"engine": engine.name, "calls": len(tally.mismatched)},
        )
    elif complete and not tally.unreached:
        await _forget_mismatches(engine.name)
        resolve_alert("WORKER_TERMINAL", "engine_charge_mismatch", episode=engine.name)
    if tally.compared and not tally.matched:
        alert(
            "WORKER_TERMINAL",
            "engine_charge_unmatched",
            detail=(
                f"engine={engine.name}: none of {tally.compared} charged call(s) in the "
                "voice platform's call log matched a metered call of ours; either nothing "
                "has been metered yet or the log's call ids are not the ones we store."
            ),
        )
    if not complete or tally.unreached:
        log.warning(
            "engine_charge_sweep_incomplete",
            extra={
                "engine": engine.name,
                "listing_complete": complete,
                "other_currency": other_currency,
                "workspaces_deferred": walk.deferred,
                "unreached": tally.unreached,
            },
        )
    return (
        f"compared={tally.compared} matched={tally.matched} unmatched={tally.unmatched} "
        f"unpriced={tally.unpriced} mismatched={len(tally.mismatched)} "
        f"unreached={tally.unreached} complete={complete} workspaces={walk.visited} "
        f"restated={restated} corrected={corrected} billing_checked={billing_checked}"
    )


__all__ = [
    "BILLING_CHECKS_PER_RUN",
    "BILLING_CHECK_ATTEMPTS",
    "CHARGE_LOOKBACK_DAYS",
    "CHARGE_SWEEP_MINUTES",
    "CHARGE_TOLERANCE_INR",
    "CHARGE_TOLERANCE_SHARE",
    "FEE_CORRECTION_META_KIND",
    "FEE_RESTATEMENT_META_KIND",
    "billing_findings",
    "check_late_billing",
    "check_settled_billing",
    "checked_billing",
    "correct_overstated_fees",
    "correct_tenant_fees",
    "cost_with_fee",
    "expected_billing",
    "fee_delta",
    "fee_excess",
    "queue_billing_check",
    "reconcile_call_charge",
    "reconcile_engine_charges",
    "record_engine_charge",
    "restate_minutes_without_fee",
    "restate_tenant_minutes",
    "thinnest_topup_fee",
    "topup_fee",
    "variance_sentence",
    "within_tolerance",
]
