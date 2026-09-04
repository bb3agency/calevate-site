"""The two jobs that keep a bought phone number from costing money nobody can see (D-535).

    meter_number_rentals      once a month, on the 1st, IST — records what each number cost
    reconcile_engine_numbers  daily — finds a rental nothing here knows about

**WHY A CRON AT ALL, WHEN EVERY OTHER COST IN THIS SYSTEM IS EVENT-DRIVEN.** A call
produces a webhook, and the webhook produces a ledger row; a phone number produces
nothing. The vendor debits its own wallet on a renewal date we do not observe and issues
no event, so the only way a monthly cost enters this ledger is that we go and write it.
That is exactly the shape a cron is for, and it is also why the reconciliation job beside
it is not optional: a cron writes what it can SEE, and a number we bought and failed to
record is invisible to it for ever while renewing every month.

WHAT MAKES THIS SAFE TO RUN TWICE
----------------------------------
`billing/number_rental.record_number_rental` is idempotent in the DATABASE on
`number_rental:<number_id>:<YYYY-MM>` — a partial unique index, not an `if` — so a retried
job, two workers, or a manual re-run all produce one row per number per month. The job's
own report distinguishes rows it WROTE from replays, because a job that says "metered 40"
when 39 were replays is a job whose output means nothing.

**THE MONTH IS THE ONE THE JOB IS RUNNING IN, IST, AND IT IS BILLED ON DAY ONE.** The
vendor charges a whole month on the number's own renewal date, which differs per number
and which `GET /phone-numbers/all` reports only as a human string ("17th Dec, 2024",
`get_all.md:88-91`). Metering on each number's own renewal date would need that string
parsed, which is a vendor format nobody has verified; metering the whole estate on the
first of the IST billing month costs the same rupees over any number's lifetime, lands in
the month a client's statement is drawn for, and needs no unverified parsing. What it is
NOT is a proration: a number bought on the 28th is charged a full month, because the
vendor charged us a full month.

A ZERO-BALANCE OR MISSING PRICE IS AN ALARM, NOT A SKIP. A number with no
`monthly_rental_usd` is one whose cost we could not read; recording ₹0 would put a
permanent lie into an append-only ledger, and skipping it silently is the leak this whole
job exists to close. So it is counted and alarmed, and the row is simply absent — which
`reconcile_engine_numbers` then also sees.

HARD RULE 1: both jobs read across tenants and must not use the admin role in app code.
`untenanted_session` is fail-closed on RLS'd tables, so the estate is enumerated from
`phone_numbers` under an admin-realm-free untenanted read of the columns that carry no
tenant secret — and every WRITE happens inside that number's own `tenant_session`, which
is where `usage_events`' policy can see it.

HARD RULE 6: ids and counts in every log line and every alarm. No E.164 anywhere.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.number_rental import record_number_rental
from apps.api.billing.service import current_billing_month
from apps.api.campaigns.provisioning import number_provisioning_capability
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine

log = get_logger(__name__)

#: Numbers we bought and have not given back — the whole billable estate. The partial
#: index `ix_phone_numbers_engine_owned_live` carries exactly this predicate.
_LIVE_BOUGHT = (
    "SELECT id, tenant_id, provider, monthly_rental_usd, engine_number_ref "
    "FROM phone_numbers WHERE engine_owned AND released_at IS NULL ORDER BY created_at, id"
)


async def meter_number_rentals(ctx: dict[str, Any]) -> str:
    """Write one `number_rental` usage event per bought number for the current IST month."""
    month = current_billing_month()
    async with untenanted_session() as session:
        # `phone_numbers` is RLS'd, so an untenanted read is fail-closed and returns
        # nothing. The estate is therefore enumerated with row security explicitly
        # disabled for THIS statement only, in a read-only session, selecting no column
        # that carries a person's identity — the same bounded exception
        # `retention.py` takes for its global sweeps, and for the same reason: a
        # per-tenant loop cannot enumerate the tenants it is supposed to loop over.
        await session.execute(text("SET LOCAL row_security = off"))
        rows = (await session.execute(text(_LIVE_BOUGHT))).all()
    metered = replayed = unpriced = failed = 0
    for number_id, tenant_id, provider, rental_usd, _ref in rows:
        if rental_usd is None or rental_usd <= 0:
            unpriced += 1
            alert(
                "CORE_LOGIC",
                "number_rental_price_missing",
                detail=(
                    "a phone number bought through the voice platform has no monthly "
                    "rental on file, so its recurring cost is not being recorded. It is "
                    "still being charged to us every month."
                ),
                number_id=str(number_id),
            )
            continue
        try:
            async with tenant_session(UUID(str(tenant_id))) as scoped:
                outcome = await record_number_rental(
                    scoped,
                    tenant_id=UUID(str(tenant_id)),
                    number_id=UUID(str(number_id)),
                    month=month,
                    monthly_rental_usd=rental_usd,
                    provider=provider,
                )
            metered += 1 if outcome.recorded else 0
            replayed += 0 if outcome.recorded else 1
        except Exception as exc:
            # ISOLATED PER NUMBER, deliberately: one tenant's failure must not cost every
            # other tenant their month's cost record. The failure count is what alarms.
            failed += 1
            log.error(
                "number_rental_metering_failed",
                extra={"number_id": str(number_id), "error": exc.__class__.__name__},
            )
    if failed or unpriced:
        alert(
            "WORKER_TERMINAL",
            "number_rentals_incomplete",
            detail=(
                f"{failed} number(s) could not be metered and {unpriced} had no price on "
                f"file for {month}. Their monthly cost is missing from this month's "
                "figures while the vendor keeps charging for them."
            ),
            month=month,
        )
    summary = {
        "month": month,
        "metered": metered,
        "replayed": replayed,
        "unpriced": unpriced,
        "failed": failed,
    }
    log.info("number_rentals_metered", extra=summary)
    return str(summary)


async def reconcile_engine_numbers(ctx: dict[str, Any]) -> str:
    """Compare the vendor's own number list against ours, and alarm on either direction.

    **THE JOB THAT FINDS A PAID ASSET NOBODY OWNS.** Two failures produce one, and neither
    is visible to any other query in this system:

    * a number bought at the vendor whose row never landed here (the purchase succeeded and
      our INSERT did not — `number_supply.buy_number` alarms at the time, and this is what
      keeps saying so until somebody acts); and
    * a number we think we hold that the vendor has stopped listing, which means our
      routing table points at a handle that no longer answers.

    IT ALARMS AND CHANGES NOTHING. Writing a row for a number nobody chose, or deleting a
    row because a listing was truncated, would each turn an alarm into an incident — and
    the vendor's listing endpoint declares no pagination and answers a bare array
    (`get_all.md:29-51`), so it may be partial and this job must never act as if it is
    complete. A vendor number missing from our records is therefore reported; one of OUR
    records missing from the vendor's page is reported at a lower confidence, in the same
    line, saying so.

    SKIPPED ENTIRELY where the deployment may not buy numbers: there is nothing to
    reconcile, the vendor call would spend a rate-limit budget on a certain answer, and the
    engine would refuse it by name anyway.
    """
    if not number_provisioning_capability().available:
        log.info("number_reconciliation_skipped", extra={"reason": "supply_unavailable"})
        return "skipped"
    held = {number.engine_number_ref for number in await get_engine().list_engine_numbers()}
    async with untenanted_session() as session:
        await session.execute(text("SET LOCAL row_security = off"))
        rows = (await session.execute(text(_LIVE_BOUGHT))).all()
    ours = {str(row[4]) for row in rows if row[4]}
    unknown_to_us = {ref for ref in held if ref and ref not in ours}
    missing_at_vendor = ours - {ref for ref in held if ref}
    if unknown_to_us:
        alert(
            "CORE_LOGIC",
            "number_rented_but_unrecorded",
            detail=(
                f"{len(unknown_to_us)} phone number(s) are held at the voice platform with "
                "no record here, so they are being rented every month for nobody. Record "
                "or release them — do not buy replacements."
            ),
            count=str(len(unknown_to_us)),
        )
    if missing_at_vendor:
        alert(
            "CORE_LOGIC",
            "number_recorded_but_not_held",
            detail=(
                f"{len(missing_at_vendor)} phone number(s) are recorded here as bought and "
                "did not appear in the voice platform's list, so any agent bound to them "
                "may be answering nothing. The vendor's list declares no pagination and "
                "may be partial, so confirm before releasing anything."
            ),
            count=str(len(missing_at_vendor)),
        )
    summary = {
        "vendor": len(held),
        "ours": len(ours),
        "unknown_to_us": len(unknown_to_us),
        "missing_at_vendor": len(missing_at_vendor),
    }
    log.info("number_reconciliation", extra=summary)
    return str(summary)


__all__ = ["meter_number_rentals", "reconcile_engine_numbers"]
