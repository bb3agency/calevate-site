"""Compare what the engine CHARGED for each call with what we metered for it (D-678).

A ThinnestAI minute is metered at call end from the operator-attested rate (`billing/
engine_minutes.py`): that is the only figure available then, and hard rule 7 keeps it the
only path to `unit_cost_paid`. ThinnestAI's billing view later says what each call actually
cost the workspace (`costMicro`, snapshots/2026-10-07/pages/api-reference/usage/
list-call-log.md:533-540). This sweep reads that view and alarms when the two disagree by
more than the tolerance, which is how an attested rate that no longer matches the invoice
(a plan change, a voice band repriced, a top-up fee) is seen within the hour.

WHAT IT DOES NOT DO: write a correction. `usage_events` is append-only (hard rule 4) and its
unique index on `(tenant_id, call_id, unit_type)` admits one `platform_min` row per call, so
a compensating entry needs a unit type or a ledger of its own: a migration this change does
not carry. Until it exists the variance is alarmed, never silently absorbed.

ONE ASSUMPTION, MARKED: that the call log's `id` is the id our call row holds. The page says
it is "the one `GET /calls/{id}` answers to" (list-call-log.md:456-459), and that endpoint
answers to both the `out_…` id we store and the call reference (calls/get-call.md:7).
UNVERIFIED which one the log carries for an API-placed call; rows that match nothing are
counted, and a sweep where nothing matches says so in its alarm.

PER CALL, TOO (D-690). The same figure rides `call.analysed` and `GET /calls/{id}` when the
call has settled (snapshots/2026-10-08/pages/api-reference/calls/get-call.md:498-514). The
post-call pipeline records it on `calls.engine_charged_inr` once and reconciles that call
(`reconcile_call_charge`); a call that was not settled by then gets its figure from this
sweep's log, recorded the same way.

WHAT IS COMPARED. `costMicro` is what the call cost the workspace and the wallet's top-up fee
is paid on top of it, when the wallet is filled. So the cost of a call is the charge times one
plus the fee, and that is what the attested per-minute rate must reproduce: an operator who
attests the band's list price without the fee is told so by the variance alarm. The fee is the
plan's, VENDOR-STATED in `billing/rates.py` (9% on Pro, which the Studio band needs; 10% on
pay-as-you-go) and chosen by the band Clear is sold on (`thinnest_topup_fee`). On a Studio
call the charge is ThinnestAI's own minute only; Cartesia bills our key separately, and that
cost is the call's `tts_kchars` row, which must exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.engine_minutes import BYOK_VOICE_RATE_KEY
from apps.api.billing.rates import (
    MONEY_Q,
    ROUNDING,
    THINNEST_PAYG_TOPUP_FEE,
    THINNEST_WALLET_TOPUP_FEE,
)
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.charges import EngineCharge, ReportsCharges
from apps.api.engine.thinnest_workspace import in_workspace
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

_ROUTE_SQL = text(
    "SELECT tenant_id FROM engine_agent_routes WHERE engine = :engine "
    "AND engine_agent_ref = :ref ORDER BY active DESC, updated_at DESC LIMIT 1"
)
_METERED_SQL = text(
    "SELECT c.id, sum(u.qty * u.unit_cost_paid), bool_or(u.unit_cost_paid IS NULL) "
    "FROM calls c JOIN usage_events u ON u.call_id = c.id AND u.tenant_id = c.tenant_id "
    "AND u.unit_type = 'platform_min' WHERE c.engine_call_id = :ecid GROUP BY c.id"
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


def thinnest_topup_fee(clear_band: str | None = None) -> Decimal:
    """The wallet top-up fee of the plan this deployment's ThinnestAI workspace is on, as a
    fraction. The Studio band is listed only on Pro and above, so a deployment selling Clear on
    it is on Pro (9%); otherwise pay-as-you-go (10%) — the same reading the cost floors make
    (`billing/rates.THINNEST_CLEAR_COST_FLOOR_BY_BAND`)."""
    band = clear_band if clear_band is not None else get_settings().thinnest_clear_voice_band
    return THINNEST_WALLET_TOPUP_FEE if band == "studio" else THINNEST_PAYG_TOPUP_FEE


def cost_with_fee(charged: Decimal, *, fee: Decimal) -> Decimal:
    """What a charge cost us once the top-up fee on the rupees that paid it is added."""
    return (charged * (Decimal(1) + fee)).quantize(MONEY_Q, rounding=ROUNDING)


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
    "sum(qty * unit_cost_paid) FILTER (WHERE unit_type = 'platform_min'), "
    "bool_or(unit_cost_paid IS NULL) FILTER (WHERE unit_type = 'platform_min'), "
    "count(*) FILTER (WHERE unit_type = 'platform_min'), "
    "max(meta->>'engine_rate_key') FILTER (WHERE unit_type = 'platform_min'), "
    "count(*) FILTER (WHERE unit_type = 'tts_kchars'), "
    "sum(qty * unit_cost_paid) FILTER (WHERE unit_type = 'tts_kchars') "
    "FROM usage_events WHERE call_id = :cid AND tenant_id = :tid"
)


async def record_engine_charge(tenant_id: UUID, call_id: UUID, charged_inr: Decimal) -> bool:
    """Write the vendor's charge on the call once. True when this write set it; a charge
    already recorded is never overwritten, so a replay or a later read changes nothing."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(_SET_CHARGE_SQL, {"charged": charged_inr, "cid": call_id})
        ).first()
    return row is not None


async def reconcile_call_charge(tenant_id: UUID, call_id: UUID, charged_inr: Decimal) -> str:
    """Record one settled call's charge and compare it with what we metered for it.

    Alarms, never corrects (hard rule 4): `engine_call_cost_variance` when the attested
    minute differs from the charge with its top-up fee by more than the tolerance, naming
    the variance; `engine_studio_synthesis_cost_missing` when a Studio call has no Cartesia
    synthesis row beside its minute. Returns what happened, for the pipeline's span.
    """
    if not await record_engine_charge(tenant_id, call_id, charged_inr):
        return "already_recorded"
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(_CALL_COSTS_SQL, {"cid": call_id, "tid": tenant_id})).one()
    metered, unpriced, minute_rows, rate_key, tts_rows, tts_cost = row
    if not minute_rows:
        return "not_metered"
    outcome = "matched"
    if rate_key == BYOK_VOICE_RATE_KEY and not tts_rows:
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
    if unpriced or metered is None:
        # Metered with no attested rate: `engine_minute_rate_unattested` already alarmed.
        return "unpriced"
    fee = thinnest_topup_fee()
    expected = cost_with_fee(charged_inr, fee=fee)
    metered_inr = Decimal(str(metered)).quantize(MONEY_Q, rounding=ROUNDING)
    if within_tolerance(metered_inr, expected):
        return outcome
    synthesis = (
        f" Cartesia synthesis is metered separately at INR "
        f"{Decimal(str(tts_cost)).quantize(MONEY_Q, rounding=ROUNDING)}."
        if tts_cost is not None
        else ""
    )
    alert(
        "WORKER_TERMINAL",
        "engine_call_cost_variance",
        detail=(
            f"rate_key={rate_key}: {variance_sentence(metered_inr, expected)} "
            f"(the voice platform charged INR {charged_inr}, plus the {fee * 100}% top-up "
            "fee). The attested per-minute rate does not reproduce what this call cost."
            f"{synthesis}"
        ),
        call_id=str(call_id),
        tenant_id=str(tenant_id),
    )
    return "variance"


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
    # A call the pipeline saw before the vendor settled it gets its figure here, once.
    await record_engine_charge(tenant_id, UUID(str(row[0])), charge.charged_inr)
    if row[2] or row[1] is None:
        # Metered with no attested rate: `engine_minute_rate_unattested` already alarmed.
        tally.unpriced += 1
        return
    metered = Decimal(str(row[1])).quantize(MONEY_Q, rounding=ROUNDING)
    expected = cost_with_fee(charge.charged_inr, fee=thinnest_topup_fee())
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
    if tally.mismatched:
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
                f"{thinnest_topup_fee() * 100}% top-up fee added, by more than the "
                f"tolerance, so the attested per-minute rate no longer matches the invoice. "
                f"{named}"
            ),
        )
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
        f"unreached={tally.unreached} complete={complete} workspaces={walk.visited}"
    )


__all__ = [
    "CHARGE_LOOKBACK_DAYS",
    "CHARGE_SWEEP_MINUTES",
    "CHARGE_TOLERANCE_INR",
    "CHARGE_TOLERANCE_SHARE",
    "cost_with_fee",
    "reconcile_call_charge",
    "reconcile_engine_charges",
    "record_engine_charge",
    "thinnest_topup_fee",
    "variance_sentence",
    "within_tolerance",
]
