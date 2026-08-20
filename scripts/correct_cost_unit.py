"""Restate `usage_events` metered under a superseded vendor cost-UNIT assumption.

Run (READ ONLY, the default — it prints what it WOULD write and touches nothing):

    uv run python -m scripts.correct_cost_unit --currency INR --from 100 --to 1
    uv run python -m scripts.correct_cost_unit --currency INR --from 100 --to 1 --tenant <uuid>

Write the corrections:

    uv run python -m scripts.correct_cost_unit --currency INR --from 100 --to 1 --apply

WHEN YOU RUN THIS. `engine/bolna.py::_MINOR_UNITS_PER_MAJOR` says how many of the vendor's
cost units make one unit of the currency they quoted. It is a marked assumption — the
vendor's OAS says "in cents" and the vendor's own prose says "account currency", and gate 7
(OPERATIONS §2) is the observation that settles it against one real invoice line. The day
that observation lands and the constant changes, every row metered before it is wrong by
the ratio of the two divisors, and `engine_cost_implausible` may well have paged about it
first (`runbooks/alarm-index.md`).

    --from   the divisor those rows WERE priced with
    --to     the divisor the adapter now uses for that currency

WHY THIS SCRIPT DELETES AND EDITS NOTHING. Hard rule 4: `usage_events` is INSERT-only and a
database trigger enforces it. That is not an obstacle to route around — the rows are the
evidence of what we believed when we metered them, and a ledger somebody can tidy is not
evidence of anything. So the repair is ONE compensating row per affected call, appended
through `billing.cost_unit.record_cost_unit_correction`, which owns the delta arithmetic,
the advisory lock and the idempotency key. A hand-rolled INSERT here would be a second,
divergent definition of what a correction is — the rule
`scripts/reconcile_credit_ledger.py` states for the credit ledger, applied to this one.

WHAT IT MOVES: our cost, and only our cost. `unit_cost_paid` is what the ENGINE charged us;
the client's invoice is priced off MINUTES at their plan's rate and does not move. See
`billing/cost_unit.py`.

WHICH TENANTS IT WALKS, AND WHY IT NEEDS NO ADMIN ROLE. `usage_events` rows with a
`call_id` exist only for tenants that have published an agent — `publish_agent` writes
`engine_agent_routes` in the transaction that mints the engine reference, and a call row is
only ever created for an agent the engine knows. So the globally-readable bridge
`engine_agent_routes` is a superset of the tenants that can hold one of these rows, exactly
as it is for `retention._due_tenants`. Every read and every write below then happens inside
`tenant_session`, under that tenant's own RLS policy: this script widens nothing (hard
rule 1).

IDEMPOTENT. Re-running with the same `--currency/--from/--to` writes nothing: the
correction's reference is derived from those three values, and correction rows carry no
`meta.source_currency`, so they are not re-read as more mis-metered cost.
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
from uuid import UUID

from apps.api.billing.cost_unit import (
    MisMeteredCall,
    mis_metered_calls,
    record_cost_unit_correction,
    restatement_delta,
)
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text


async def _tenants() -> list[UUID]:
    """Every tenant that can hold a call-scoped usage row. See the module docstring for
    why this bridge is a superset and why reading it needs no exemption."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT DISTINCT tenant_id FROM engine_agent_routes ORDER BY tenant_id")
            )
        ).scalars()
        return [UUID(str(row)) for row in rows]


def _describe(tenant_id: UUID, call: MisMeteredCall, delta: Decimal) -> str:
    return (
        f"  tenant {tenant_id} call {call.call_id}: "
        f"metered INR {call.metered_inr} -> {call.metered_inr + delta} (delta {delta})"
    )


async def run(
    *,
    currency: str,
    from_divisor: Decimal,
    to_divisor: Decimal,
    apply: bool,
    only_tenant: UUID | None,
) -> int:
    """Returns the number of calls corrected (or, on a dry run, that WOULD be)."""
    tenants = [only_tenant] if only_tenant else await _tenants()
    corrected = 0
    total_delta = Decimal(0)

    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            candidates = await mis_metered_calls(session, source_currency=currency)
            for call in candidates:
                if apply:
                    delta = await record_cost_unit_correction(
                        session,
                        tenant_id=tenant_id,
                        call=call,
                        source_currency=currency,
                        from_divisor=from_divisor,
                        to_divisor=to_divisor,
                    )
                    if delta is None:
                        # Already restated by an earlier run, or below a paisa. Neither is
                        # an error and neither is a correction.
                        continue
                else:
                    delta = restatement_delta(
                        call.metered_inr, from_divisor=from_divisor, to_divisor=to_divisor
                    )
                    if delta == 0:
                        continue
                corrected += 1
                total_delta += delta
                print(_describe(tenant_id, call, delta))

    verb = "corrected" if apply else "would correct"
    print(
        f"cost-unit restatement ({currency}, {from_divisor} -> {to_divisor}): "
        f"{verb} {corrected} call(s), total delta INR {total_delta}"
    )
    if not apply and corrected:
        print("READ ONLY. Re-run with --apply to append the compensating rows.")
    return corrected


def _divisor(raw: str) -> Decimal:
    """A divisor off the command line, as a Decimal and never a float (hard rule 7)."""
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not a number: {raw!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("a minor-units-per-major divisor must be positive")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--currency",
        required=True,
        help="the `meta.source_currency` the affected rows carry, e.g. INR",
    )
    parser.add_argument(
        "--from",
        dest="from_divisor",
        required=True,
        type=_divisor,
        help="the minor-units-per-major divisor those rows were priced with",
    )
    parser.add_argument(
        "--to",
        dest="to_divisor",
        required=True,
        type=_divisor,
        help="the divisor the adapter uses for that currency now",
    )
    parser.add_argument("--tenant", type=UUID, default=None, help="restrict to one tenant")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="append the compensating rows (default: print them and write nothing)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    currency = str(args.currency).strip().upper()
    if args.from_divisor == args.to_divisor:
        # Refused rather than run as a no-op: an operator who typed the same number twice
        # asked for something they did not mean, and a clean "0 calls corrected" would
        # read as "there was nothing wrong".
        print("--from and --to are the same divisor; there is nothing to restate.")
        return 2
    asyncio.run(
        run(
            currency=currency,
            from_divisor=args.from_divisor,
            to_divisor=args.to_divisor,
            apply=bool(args.apply),
            only_tenant=args.tenant,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
