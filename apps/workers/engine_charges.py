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
understates our cost by the fee (10% on pay-as-you-go). `usage_events` is append-only (hard
rule 4), so `restate_minutes_without_fee` appends ONE compensating row per such call, the
shape `billing/cost_unit.py` set for a cost-only correction: `unit_type = 'other'`,
`qty = 1`, `unit_cost_paid` = the missing fee, `meta.kind` = `FEE_RESTATEMENT_META_KIND`,
stamped at the original row's `occurred_at`, under `lock_tenant_credits`. It moves our cost
only: the client is billed off minutes at its own rate and no reader of client money reads
`unit_cost_paid`. The population is closed by construction (a minute row the meter writes now
carries `meta.topup_fee`, so only rows from before the fix lack it), which is why it runs at
the top of this sweep rather than as a script someone has to remember: the comparison below
needs it done first, and once the backlog is restated each run finds nothing. A call's cost
is its minute row plus its restatement (`_minute_cost_rows`), in both comparisons.

ONE ALARM PER CALL. A mismatch the sweep has already alarmed on is not alarmed again while it
persists (`_newly_mismatched` keeps the alarmed call ids in Redis for longer than the lookback
window); a clean, complete sweep closes the episode with `resolve_alert` and forgets them.
Without this the hourly cadence outran the alert path's hour-long quiet period and the same
calls mailed every hour.

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
plus the fee, and that is what the meter reproduces: the operator attests the posted rate, the
meter adds the fee (`billing/engine_minutes.topup_fee`, the one helper both sides use), so a
variance means the posted rate itself is wrong. The fee is the plan's, VENDOR-STATED in
`billing/rates.py` (9% on Pro, which the Studio band needs; 10% on pay-as-you-go) and chosen by
the band Clear is sold on (`thinnest_topup_fee`). On a Studio
call the charge is ThinnestAI's own minute only; Cartesia bills our key separately, and that
cost is the call's `tts_kchars` row, which must exist.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, cast
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.engine_minutes import (
    BYOK_VOICE_RATE_KEY,
    TOPUP_FEE_META_KEY,
    cost_with_fee,
    thinnest_topup_fee,
    topup_fee,
)
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.billing.service import _ROW_COST_SQL, LEDGER_RUNG_KEY, lock_tenant_credits
from apps.api.core.alerting import alert, resolve_alert
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.base import uuid7
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

#: `meta.kind` of the compensating row that adds the top-up fee to a minute metered without it.
FEE_RESTATEMENT_META_KIND: Final = "engine_topup_fee_restatement"

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


def _minute_cost_rows(prefix: str = "") -> str:
    """The rows a call's engine-minute cost is: its metered minute and any fee restatement."""
    return (
        f"({prefix}unit_type = 'platform_min' OR ({prefix}unit_type = 'other' "
        f"AND {prefix}meta->>'kind' = '{FEE_RESTATEMENT_META_KIND}'))"
    )


_METERED_SQL = text(
    "SELECT c.id, sum(u.qty * u.unit_cost_paid), bool_or(u.unit_cost_paid IS NULL) "
    "FROM calls c JOIN usage_events u ON u.call_id = c.id AND u.tenant_id = c.tenant_id "
    f"AND {_minute_cost_rows('u.')} WHERE c.engine_call_id = :ecid GROUP BY c.id"
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
    f"sum(qty * unit_cost_paid) FILTER (WHERE {_minute_cost_rows()}), "
    f"bool_or(unit_cost_paid IS NULL) FILTER (WHERE {_minute_cost_rows()}), "
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


async def reconcile_call_charge(
    tenant_id: UUID, call_id: UUID, charged_inr: Decimal, *, engine: str
) -> str:
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
    fee = topup_fee(engine)
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


# --- the fee restatement -------------------------------------------------------------------

_ENGINE_TENANTS_SQL = text(
    "SELECT DISTINCT tenant_id FROM engine_agent_routes WHERE engine = :engine ORDER BY tenant_id"
)

#: Priced minute rows of an attested-minute engine metered without the fee and not yet
#: restated. Unqualified columns are the outer row's, which `_ROW_COST_SQL` relies on.
_WITHOUT_FEE_SQL = text(
    f"SELECT call_id, {_ROW_COST_SQL}, occurred_at, meta->>'engine_rate_key', "
    f"meta->>'{LEDGER_RUNG_KEY}', meta->>'voice_tier' FROM usage_events u "
    "WHERE unit_type = 'platform_min' AND call_id IS NOT NULL AND unit_cost_paid IS NOT NULL "
    "AND meta->>'engine_rate_key' IS NOT NULL "
    f"AND meta->>'{TOPUP_FEE_META_KEY}' IS NULL "
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
                _WITHOUT_FEE_SQL, {"kind": FEE_RESTATEMENT_META_KIND, "cap": _RESTATE_BATCH}
            )
        ).all()
        for call_id, metered, occurred_at, rate_key, rung, voice in rows:
            metered_inr = Decimal(str(metered))
            delta = fee_delta(metered_inr, fee=fee)
            if delta == 0:
                continue
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
    async with untenanted_session() as session:
        tenants = [
            UUID(str(row))
            for row in (await session.execute(_ENGINE_TENANTS_SQL, {"engine": engine})).scalars()
        ]
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
        f"restated={restated}"
    )


__all__ = [
    "CHARGE_LOOKBACK_DAYS",
    "CHARGE_SWEEP_MINUTES",
    "CHARGE_TOLERANCE_INR",
    "CHARGE_TOLERANCE_SHARE",
    "FEE_RESTATEMENT_META_KIND",
    "cost_with_fee",
    "fee_delta",
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
