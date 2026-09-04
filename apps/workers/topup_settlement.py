"""The alarm for a payment webhook that never arrives at all.

WHAT THIS EXISTS FOR — the one payment failure nothing else in this repository can see
---------------------------------------------------------------------------------------
Every other alarm on the top-up path fires from INSIDE
`billing/payment_routes.razorpay_webhook`, so every one of them needs a delivery to
reach that handler first: `razorpay_webhook_unconfigured` (no secret),
`razorpay_webhook_bad_signature` (wrong secret), `razorpay_unknown_tenant` and
`razorpay_money_unapplied` (verified, unappliable). A webhook that is posted to the
WRONG ADDRESS trips none of them, because nothing of ours is ever asked.

That is not hypothetical. `runbooks/topup-payments.md` §0.4 names the trap it is most
afraid of — a webhook registered against `hooks.calevate.tech` instead of
`api.calevate.tech`. Both hostnames exist and both are ours;
`infra/nginx/calevate.conf.template:579` sends `hooks.` to `calevate_hooks` (:8100,
voice-runtime) and `:516` sends `api.` to `calevate_api` (:8000). Only the API mounts
`POST /hooks/v1/razorpay` (`billing/payment_routes.py:119`), so a delivery to the other
one is answered by voice-runtime's catch-all problem handler — a 404, MEASURED against
the real app object rather than assumed, and pinned by
`tests/edge_route_policy_test.py::test_the_razorpay_webhook_is_served_by_the_api_and_not_by_voice_runtime`.
A 404 is the safe shape (nothing is acked, nothing is swallowed) and it is completely
invisible from here: it is a line in an nginx access log on a host, on a service whose
own logs are about calls.

So before this job the sequence was: the client is debited, the wallet does not move,
the attempt sits at `created`, and the FIRST notice anybody gets is the client saying
so. The evidence was all present — `topup_attempts` has held it since D-98 — and the
only reader was the client's own credits screen, which shows one tenant their own rows
and pages nobody.

WHAT IT ASSERTS, AND WHAT IT REFUSES TO ASSERT
----------------------------------------------
It asserts one thing: **an order exists at the provider, it is older than
`SETTLEMENT_GRACE`, and the webhook leg has shown no sign of life since it was
created.** Both halves are needed, and the second is what makes this quiet in normal
operation — an abandoned Checkout window produces exactly the same stuck row as a
misdirected webhook, and the only thing that tells them apart is whether ANY delivery
has been processed since. `payment.captured` and `payment.failed` both count as a sign
of life: a declined card proves the leg is alive just as well as a successful one, and
counting only successes would page every time a client's first card bounced.

It refuses to assert that money was taken. Nothing here talks to Razorpay — their host
is egress-blocked from this environment (403 on CONNECT, re-measured 25 Aug 2026) and no
endpoint for reading an order's payments has been read from their documentation by
anybody in this repository. Inventing one to "reconcile automatically" would mean
inventing a wire format and then crediting a wallet from it, which is the one thing hard
rule 11 exists to stop. **The alarm's job is to put a person in front of the Razorpay
dashboard**; the credit, if one is owed, is written by hand through the admin credits
route keyed on the payment id, which is the same `credit_ledger.ref` the webhook would
have used — so a late redelivery dedupes rather than double-credits
(`billing/payments.credit_captured_payment`). Nothing in this module writes to any
ledger, and nothing in it can move a rupee.

TWO CLOCKS, ON PURPOSE — this is not the client screen's `PENDING_GRACE_HOURS`
------------------------------------------------------------------------------
`wallet.PENDING_GRACE_HOURS` (24h) is how long a payment stays the word "settling" on
the PAYER's screen. That is a promise made to somebody who has just handed over money,
and it is deliberately generous: telling a client their payment is "unfinished" while a
slow settlement is still plausible is worse than making them wait.

This is the OPERATOR's clock and it is a different question — not "should the payer
worry yet" but "has the webhook leg said anything at all". Thirty minutes of complete
silence after an order was created is already abnormal for a leg whose normal latency is
seconds (`runbooks/topup-payments.md` §0.6 step 5: "the balance moves within a second or
two"). Sharing the 24-hour figure would mean a misdirected webhook installed at 09:00
goes unreported through a full day of client payments.

FLEET WALK (D-369). `topup_attempts` is FORCE-RLS'd, so this is one `tenant_session` per
organization under a `WalkBudget`, and a truncated pass ALERTS rather than reporting a
smaller number — the shape `qa_sampling` and `retention` already use.

Hard rule 6: order ids and tenant ids, never an amount against a name, never an address.
A provider order id is the identifier an operator types into the vendor dashboard, which
is the entire point of naming it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import admin_session, tenant_session
from apps.workers.fleet_walk import WalkBudget

log = get_logger(__name__)

#: How long an order may sit unsettled before it is the operator's business. See the
#: module docstring for why this is NOT `wallet.PENDING_GRACE_HOURS`.
SETTLEMENT_GRACE = timedelta(minutes=30)

#: How far back a stuck attempt stays news. Without it, one Checkout window abandoned in
#: March would page forever on a deployment where nobody has paid since — the alarm would
#: become permanent, and a permanent alarm is a silenced one. A payment taken today
#: re-enters the window on its own, so nothing is lost by forgetting the old ones: the
#: client's own credits screen still shows them as `unfinished`, which is where a row
#: this old belongs.
LOOKBACK = timedelta(days=7)

#: The minutes past the hour this sweep runs at, exported so the registration in
#: `settings.py` and the runbook's "within about an hour" promise cannot drift apart.
#: Twice hourly, and OFF the busy slots: the fan-out is one session per organization, and
#: :13/:43 leave the :00/:05/:30/:35 block to the reconciliation poller, the outbox and
#: the stall report. Worst-case notice is therefore about 60 minutes after an order stops
#: settling, on top of `SETTLEMENT_GRACE`.
SETTLEMENT_MINUTES: tuple[int, ...] = (13, 43)

#: At most this many order ids in one alert body. An operator needs a handful to start
#: looking, not a list.
_ALERT_ID_LIMIT = 5

#: `ORDER BY id` for `qa_sampling._DIRECTORY`'s reason: a truncated walk must starve the
#: same stable tail rather than a different arbitrary slice each tick.
_DIRECTORY = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"

#: One tenant's attempts inside the window. The whole window rather than only the stuck
#: ones, because the SIGN OF LIFE is computed from the settled rows in the same read —
#: two queries would be two round trips per tenant on the fan-out this walk is budgeted
#: against, and they would answer as of two different instants.
_ATTEMPTS = (
    "SELECT provider_order_id, status, created_at, updated_at FROM topup_attempts "
    "WHERE created_at >= :since"
)


@dataclass(frozen=True, slots=True)
class StuckOrder:
    """One order created at the provider that no webhook has ever settled."""

    tenant_id: UUID
    order_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SettlementScan:
    """What one pass over the fleet saw. Counts and ids — never an amount."""

    tenants: int
    tenants_probed: int
    tenants_failed: int
    stuck: tuple[StuckOrder, ...]
    #: The newest instant at which ANY attempt anywhere was settled — captured or failed —
    #: inside the window, or None if nothing was. This is the webhook leg's pulse.
    last_settlement: datetime | None
    truncated: bool

    @property
    def tenants_unreached(self) -> int:
        return self.tenants - self.tenants_probed

    @property
    def silent(self) -> bool:
        """Is there an unsettled order the webhook leg cannot account for?

        True when something is stuck AND nothing has been settled since the OLDEST stuck
        order was created. A settlement after that instant proves deliveries are reaching
        us, which makes every stuck order an abandoned window rather than a lost webhook —
        the distinction this whole job exists to draw.
        """
        if not self.stuck:
            return False
        oldest = min(order.created_at for order in self.stuck)
        return self.last_settlement is None or self.last_settlement < oldest

    def totals(self) -> dict[str, Any]:
        return {
            "tenants": self.tenants,
            "tenants_probed": self.tenants_probed,
            "tenants_failed": self.tenants_failed,
            "tenants_unreached": self.tenants_unreached,
            "stuck_orders": len(self.stuck),
            "stuck_tenants": len({order.tenant_id for order in self.stuck}),
            "webhook_leg_silent": self.silent,
            "truncated": self.truncated,
        }


async def scan_tenants(
    tenant_ids: list[UUID], *, now: datetime, budget: WalkBudget | None = None
) -> SettlementScan:
    """One pass over an EXPLICIT tenant list.

    Split out of the job for `qa_sampling.draw_for_tenants`' reason: the directory read
    and the scan are separately exercisable, and a test of the verdict does not have to
    enumerate every organization in the database to reach it.

    A failing tenant does NOT stop the others — one client's database error must not cost
    the whole fleet its payment watch — but it IS counted, because a scan that could not
    read half the fleet has seen less than it appears to have seen.
    """
    walk = budget or WalkBudget()
    cutoff = now - SETTLEMENT_GRACE
    since = now - LOOKBACK
    stuck: list[StuckOrder] = []
    last_settlement: datetime | None = None
    probed = 0
    failed = 0
    for tenant_id in tenant_ids:
        if walk.spent():
            break
        probed += 1
        try:
            async with tenant_session(tenant_id) as session:
                rows = (await session.execute(text(_ATTEMPTS), {"since": since})).all()
        except Exception:
            # The id, never the exception's payload: psycopg quotes the offending row
            # back, and these rows carry a client's payment references.
            log.exception("topup_settlement_scan_failed", extra={"tenant_id": str(tenant_id)})
            failed += 1
            continue
        for order_id, status, created_at, updated_at in rows:
            if status == "created":
                # NULL `provider_order_id` means no order was ever created at the
                # provider (`payment_capability().creates_orders` was false, or the
                # order call failed), so no money can have been taken and there is
                # nothing for a webhook to have missed.
                if order_id is not None and created_at <= cutoff:
                    stuck.append(
                        StuckOrder(
                            tenant_id=tenant_id, order_id=str(order_id), created_at=created_at
                        )
                    )
                continue
            if last_settlement is None or updated_at > last_settlement:
                last_settlement = updated_at
    return SettlementScan(
        tenants=len(tenant_ids),
        tenants_probed=probed,
        tenants_failed=failed,
        stuck=tuple(stuck),
        last_settlement=last_settlement,
        truncated=walk.exhausted,
    )


def _describe(scan: SettlementScan, *, now: datetime) -> str:
    """The alert body. Our own words about our own counts — never a provider payload."""
    oldest = min(order.created_at for order in scan.stuck)
    age_minutes = int((now - oldest).total_seconds() // 60)
    named = ", ".join(sorted(order.order_id for order in scan.stuck)[:_ALERT_ID_LIMIT])
    return (
        f"{len(scan.stuck)} payment order(s) across "
        f"{len({order.tenant_id for order in scan.stuck})} tenant(s) were created at the "
        f"payment provider and no webhook has settled any of them; the oldest is "
        f"{age_minutes} minute(s) old and NOTHING has been settled since it was created. "
        "The likeliest cause is that the provider's webhook is not reaching us at all — "
        "check the webhook URL first, it must be https://api.<domain>/hooks/v1/razorpay "
        "and NOT the hooks. hostname. Abandoned checkout windows look identical from "
        "here, so confirm in the provider dashboard whether these orders were actually "
        f"paid before crediting anything. Orders: {named}"
    )


async def sweep_topup_settlement(ctx: dict[str, Any]) -> str:
    """Twice hourly. Is the payment webhook leg alive, or is money going unclaimed?

    Returns a small JSON summary (arq stores it), so "the sweep ran and found nothing"
    is answerable without reading a day of logs.
    """
    attempt = int(ctx.get("job_try", 1) or 1)
    now = datetime.now(UTC)
    async with admin_session() as directory:
        rows = (await directory.execute(text(_DIRECTORY))).all()
    tenant_ids = [UUID(str(row[0])) for row in rows]

    scan = await scan_tenants(tenant_ids, now=now)
    totals = scan.totals()
    log.info("topup_settlement_scan", extra=totals)

    if scan.silent:
        # WORKER_STALL for `engine_violation_open`'s reason: this is a scheduled probe
        # reporting a bad state of the world it went and measured, not a worker dying.
        # Nothing is retried by reporting it — only a person can clear it.
        alert("WORKER_STALL", "topup_settlement_silent", detail=_describe(scan, now=now))

    if scan.tenants_unreached:
        # A SEPARATE alarm from the verdict, because it says the thing the verdict
        # cannot: the tail of the fleet was never asked, so `stuck_orders` is a floor and
        # a clean verdict is not a clean fleet.
        alert(
            "WORKER_DELIVERY",
            "topup_settlement_scan_incomplete",
            detail=(
                f"the payment-settlement sweep reached {scan.tenants_probed} of "
                f"{scan.tenants} tenant(s) inside its time budget and stopped there. The "
                f"remaining {scan.tenants_unreached} were not asked, so a quiet verdict "
                "here does not cover them"
            ),
        )

    # Everybody failed: that is a database or a deploy, not a tenant. Ask for the ladder —
    # `WorkerSettings.retry_jobs` only honours `Retry`, so a plain raise would be one
    # silent attempt — and alert on the last one, because there is no arq DLQ that anything
    # reads (`apps/workers/settings.py`).
    if scan.tenants_probed and scan.tenants_failed == scan.tenants_probed:
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=300)
        alert(
            "WORKER_TERMINAL",
            "topup_settlement_sweep_abandoned",
            detail=(
                f"the payment-settlement sweep failed for all {scan.tenants_probed} "
                f"tenant(s) it reached after {attempt} attempt(s). Until it succeeds, a "
                "payment webhook that stops arriving is unwatched"
            ),
        )
        raise RuntimeError("the payment-settlement sweep reached no tenant successfully")
    return json.dumps(totals)


__all__ = [
    "LOOKBACK",
    "SETTLEMENT_GRACE",
    "SETTLEMENT_MINUTES",
    "SettlementScan",
    "StuckOrder",
    "scan_tenants",
    "sweep_topup_settlement",
]
