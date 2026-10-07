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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.charges import EngineCharge, ReportsCharges

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
    if row[2] or row[1] is None:
        # Metered with no attested rate: `engine_minute_rate_unattested` already alarmed.
        tally.unpriced += 1
        return
    metered = Decimal(str(row[1]))
    if not within_tolerance(metered, charge.charged_inr):
        tally.mismatched.append((str(row[0]), metered, charge.charged_inr))


async def reconcile_engine_charges(ctx: dict[str, Any], *, now: datetime | None = None) -> str:
    engine = get_engine()
    if not isinstance(engine, ReportsCharges) or not engine.holds_credentials():
        return "engine_without_charges"
    since = ((now or datetime.now(UTC)) - timedelta(days=CHARGE_LOOKBACK_DAYS)).date()
    listing = await engine.list_call_charges(since=since)
    tally = _Tally()
    for charge in listing.charges:
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
        named = ", ".join(
            f"{call_id}: metered {metered} vs charged {charged}"
            for call_id, metered, charged in tally.mismatched[:_ALERT_ID_LIMIT]
        )
        alert(
            "WORKER_TERMINAL",
            "engine_charge_mismatch",
            detail=(
                f"engine={engine.name}: {len(tally.mismatched)} call(s) metered at a cost "
                f"that differs from what the voice platform charged by more than the "
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
    if not listing.complete or tally.unreached:
        log.warning(
            "engine_charge_sweep_incomplete",
            extra={
                "engine": engine.name,
                "listing_complete": listing.complete,
                "other_currency": listing.other_currency,
                "unreached": tally.unreached,
            },
        )
    return (
        f"compared={tally.compared} matched={tally.matched} unmatched={tally.unmatched} "
        f"unpriced={tally.unpriced} mismatched={len(tally.mismatched)} "
        f"unreached={tally.unreached} complete={listing.complete}"
    )


__all__ = [
    "CHARGE_LOOKBACK_DAYS",
    "CHARGE_SWEEP_MINUTES",
    "CHARGE_TOLERANCE_INR",
    "CHARGE_TOLERANCE_SHARE",
    "reconcile_engine_charges",
    "within_tolerance",
]
