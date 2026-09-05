"""The PLATFORM's own AI ledger: metering the admin copilot, whose payer is us (D-499).

`apps/api/copilot/routes.py` refused the admin realm with one line and named this module
as the fix in the same docstring: *"an admin-realm copilot would either spend the founder's
Azure credential with no ledger row — which hard rule 7 forbids in as many words — or
charge whichever client's page happened to be open for an operator's typing … what closes
it is a platform-payer AI ledger in `billing/`."* This is it.

## WHY A SECOND METER AND NOT A PARAMETER ON THE FIRST

`record_ai_assist_usage` writes `usage_events`, which is tenant-scoped with FORCEd RLS: its
INSERT needs a `tenant_id` and runs inside `tenant_session(tenant_id)`. An operator asking
the admin copilot has no tenant, so there is no value to pass — the parameter does not exist
in the shape "make `tenant_id` optional" would need. Widening `usage_events` to accept a
NULL tenant was rejected before it was written: it makes the RLS policy on this platform's
busiest ledger conditional, and a conditional tenancy predicate on a money table is the
single change most likely to become a cross-tenant read.

So: a second table (`platform_ai_usage`, migration `f2c81a4d05e7`) and a second writer. What
is deliberately NOT duplicated is everything that decides the MONEY — the price comes from
`rates.llm_inr_per_ktok(model)`, the quantity from `ai_quota.ktok`, the key from
`ai_quota.new_assist_ref`, the month from the row's own `occurred_at`, and the platform
counter is the SAME `platform_ai_spend` row the tenant meter bumps. Two ledgers, one price
list, one brake.

## THE BRAKE COVERS ADMIN SPEND, AND THAT IS THE POINT RATHER THAN AN OVERSIGHT

`PLATFORM_AI_BRAKE_INR` is described on its own constant as "the brake on OUR key, across
every tenant … a hundred tenants each inside their own ceiling is still a hundred ceilings
of our money". An operator's copilot turn is spend on exactly that key, so it counts against
exactly that brake, and `require_platform_ai` refuses when it has tripped. The alternative —
an admin surface outside the only ceiling this platform has — is a runaway with no bound at
all, and the runaway this brake exists for (a retry loop, a prompt that grew a zero) is more
likely on an internal tool than on a client's screen, not less.

There is deliberately NO per-operator monthly allowance. A tenant ceiling exists because a
tenant is buying a bounded product; an operator is staff, the money is ours either way, and
inventing a rupee figure to divide it by would be a price nobody set. The brake is the
bound, and `read_platform_ai_spend` already reports how much of it is gone.

## ATTRIBUTION: TENANT, USER, FEATURE — AND HERE, OPERATOR

Current practice on multi-tenant LLM cost attribution is that every call carries at minimum
a tenant, a user, a feature and an environment, "including internal tools and cron jobs"
(SoftwareSeni, "Token Attribution and Cost Governance for Multi-Tenant LLM Products in
Production", https://www.softwareseni.com/token-attribution-and-cost-governance-for-multi-tenant-llm-products-in-production/,
read 1 Sep 2026 — EVIDENCE CLASS: SECONDARY, a vendor-neutral practice article and not a
primary specification; it is cited for the SHAPE of the record, never for a number). This
ledger has no tenant to carry, so the dimension it substitutes is the ACTOR — and the cited
reading is explicit that the attribution covers "internal tools and CRON JOBS", which is the
half this module originally could not represent. Exactly one of `admin_user_id` and
`system_actor` is always present (`ck_platform_ai_usage_one_actor`, migration
`c6b1f0d47e83`), so every row of our own spend is answerable by somebody or by some named
job; `viewing_tenant_id` carries which account was on screen so "what did supporting this
client cost us" stays a query. The same reading notes that the
internal-support/impersonation case is not covered by the published practice at all, which
is why the decision behind `viewing_tenant_id` being context and never a payer is D-499's
and is argued there rather than borrowed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import (
    ASSIST_META_KIND,
    bump_platform_ai_spend,
    is_assist_ref,
    ktok,
    read_platform_ai_spend,
)
from apps.api.billing.rates import llm_inr_per_ktok
from apps.api.billing.service import _IST_MONTH
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

#: `platform_ai_usage.meta.kind`, so a reader who finds a row knows what produced it
#: without joining anything — the same discipline `ASSIST_META_KIND` keeps on the tenant
#: ledger, and deliberately the SAME VALUE: it is the same kind of spend on the same key,
#: and the table it is in is what says who paid.
PLATFORM_ASSIST_META_KIND: Final = ASSIST_META_KIND

# TWO ROWS PER ATTEMPT, one per direction, exactly as `_INSERT_USAGE` writes them — so a
# person reading both ledgers side by side is reading one vocabulary. `RETURNING` carries
# the row's OWN IST billing month for `record_ai_assist_usage`'s two-clock reason: the app
# process's clock and the database's disagree by whatever NTP skew exists between them, and
# the brake must be bumped for the month the ROW landed in or the two never reconcile.
#
# `DO NOTHING` and not `DO UPDATE`: `platform_ai_usage` is in `APPEND_ONLY_TABLES` and
# `DO UPDATE` fires `calevate_forbid_mutation`. A conflict here means the same
# server-minted attempt was written twice — a retried transaction — which must be a no-op.
_INSERT_PLATFORM_USAGE = f"""
INSERT INTO platform_ai_usage (id, admin_user_id, system_actor, viewing_tenant_id, unit_type,
                               qty, unit_cost_paid, ref, occurred_at, meta, created_at)
VALUES (:id, :admin_id, :actor, :viewing, :unit, :qty, :cost, :ref, now(),
        CAST(:meta AS jsonb), now())
ON CONFLICT (unit_type, ref) DO NOTHING
RETURNING id, {_IST_MONTH}
"""


@dataclass(frozen=True, slots=True)
class PlatformAssistMetered:
    """What `record_platform_ai_usage` did. `recorded` False is a REPLAY of one attempt —
    with a server-minted key it can never be a second question — so `cost_inr` is zero and
    the platform counter cannot be charged twice for one answer."""

    recorded: bool
    cost_inr: Decimal


async def record_platform_ai_usage(
    session: AsyncSession,
    *,
    admin_user_id: UUID | None = None,
    system_actor: str | None = None,
    viewing_tenant_id: UUID | None = None,
    ref: str,
    tokens_in: int,
    tokens_out: int,
    model: str,
    feature: str,
) -> PlatformAssistMetered:
    """Meter one admin-copilot answer: two `platform_ai_usage` rows and the platform counter.

    THE ONLY WRITER of `platform_ai_usage`. It is `record_ai_assist_usage` with the tenant
    replaced by an operator, and every property that function argues for is kept rather than
    re-decided:

    * **Idempotent in the DATABASE** (`ux_platform_ai_usage_unit_ref`), not in an `if`. The
      failure to survive is one attempt arriving twice, and a check-then-write lets both
      copies read "not metered yet".
    * **The `ref` is validated, not trusted.** Idempotency is a switch that turns metering
      OFF, so a key a caller could supply is a way to spend our credential for free. Same
      `_ASSIST_REF_RE`, same `new_assist_ref()` minting — and the database repeats the rule
      as `ck_platform_ai_usage_ref_shape` so a future writer that forgets this guard is
      still refused.
    * **The price is DERIVED from `model`**, never passed beside it. `llm_inr_per_ktok`
      raises for an identifier this repository publishes no price for, BEFORE any statement
      runs — a wrong `unit_cost_paid` on an append-only row cannot be corrected in place,
      so refusing to guess is the only safe direction (hard rule 7, D-410).
    * **The month comes from the ROW**, read back through `_IST_MONTH`, never from this
      process's clock.

    **AN OPERATOR OR A NAMED JOB — EXACTLY ONE, AND THIS FUNCTION USED TO ADMIT ONLY THE
    FIRST.** D-502 recorded the consequence in as many words: the founder asked for the KB
    ingestion sweep to bill this ledger, `admin_user_id` was `UUID` and NOT NULL, a cron has
    no operator, and inventing one would put a fabricated identity on an APPEND-ONLY row
    that could never afterwards be corrected (hard rule 4) — so the spend went to the
    TENANT's ledger and the gap was reported rather than papered over.

    What the original signature was defending is on the column's own migration comment: "a
    row of our own spend nobody can be asked about is the one shape this ledger must not be
    able to hold". That is a property about ACCOUNTABILITY and not about a human, and a
    NAMED JOB satisfies it exactly as a named operator does — `caller_embed` is answerable,
    an anonymous NULL is not. So `system_actor` joins it, `ck_platform_ai_usage_one_actor`
    makes the database refuse both and neither, and this function refuses the same two
    before it writes: the widening is one more representable row, not one fewer rule.

    NEVER RAISES for an ordinary outcome. It runs after the provider has been paid, in the
    caller's transaction, and a metered answer undone by a failure to talk about it is the
    money hole the whole path exists to close. It DOES raise `ValueError` for a malformed
    `ref` or an unpriced model, both of which are programming errors in a caller rather than
    anything a person did.
    """
    if (admin_user_id is None) == (system_actor is None):
        # A `ValueError` and not a `ProblemError`, for the `ref` guard's reason below: this
        # is a programming error in a caller rather than anything a person did. Refused
        # BEFORE the price lookup so the message names the actual mistake.
        raise ValueError(
            "platform AI spend is attributed to exactly one of admin_user_id (a person "
            "asked) or system_actor (a named job ran); never both and never neither"
        )
    if not is_assist_ref(ref):
        raise ValueError(
            "a platform assist metering key must come from new_assist_ref() "
            "(assist:<uuid>), never from a request"
        )
    inr_per_ktok = llm_inr_per_ktok(model)

    # Ids, a model name and a feature name (hard rule 6). `admin_user_id` is in `meta` as
    # well as in its own column so a row exported to a spend board carries its attribution
    # without a join, which is the same reason `ref` is duplicated into `meta` next door.
    meta = json.dumps(
        {
            "kind": PLATFORM_ASSIST_META_KIND,
            "model": model,
            "feature": feature,
            "ref": ref,
            "admin_user_id": None if admin_user_id is None else str(admin_user_id),
            "system_actor": system_actor,
            "viewing_tenant_id": None if viewing_tenant_id is None else str(viewing_tenant_id),
        }
    )
    rows = (
        ("ai_assist_ktok_in", ktok(tokens_in), inr_per_ktok["in"]),
        ("ai_assist_ktok_out", ktok(tokens_out), inr_per_ktok["out"]),
    )
    landed = Decimal("0")
    landed_month: str | None = None
    for unit, qty, price in rows:
        inserted = (
            await session.execute(
                text(_INSERT_PLATFORM_USAGE),
                {
                    "id": uuid7(),
                    "admin_id": admin_user_id,
                    "actor": system_actor,
                    "viewing": viewing_tenant_id,
                    "unit": unit,
                    "qty": qty,
                    "cost": price,
                    "ref": ref,
                    "meta": meta,
                },
            )
        ).first()
        if inserted is not None:
            # The FIRST row's month wins if the two straddle a boundary: they are
            # microseconds apart and both honest, and what must not happen is the two
            # halves of one answer paying into two different months' brakes.
            landed_month = landed_month or str(inserted[1])
            landed += qty * price

    if landed_month is None:
        log.warning(
            "platform_ai_assist_replayed",
            extra={
                "actor": str(admin_user_id or system_actor),
                "ref": ref,
                "model": model,
                "feature": feature,
            },
        )
        return PlatformAssistMetered(recorded=False, cost_inr=Decimal("0"))

    # THE SAME COUNTER THE TENANT METER BUMPS, and the same one `require_ai_assist` reads.
    # One key, one bill, one brake — an admin surface counting against a separate ceiling
    # would be spend on our credential that the only ceiling we have cannot see.
    await bump_platform_ai_spend(session, month=landed_month, amount=landed)
    log.info(
        "platform_ai_assist_metered",
        extra={
            "actor": str(admin_user_id or system_actor),
            "viewing_tenant_id": None if viewing_tenant_id is None else str(viewing_tenant_id),
            "ref": ref,
            "model": model,
            "feature": feature,
            "month": landed_month,
            "cost_inr": str(landed),
        },
    )
    return PlatformAssistMetered(recorded=True, cost_inr=landed)


async def require_platform_ai(session: AsyncSession) -> None:
    """May an OPERATOR spend our AI credential right now? Returns, or REFUSES.

    THE ADMIN REALM'S WHOLE GATE, and it is one condition rather than three because two of
    the tenant gate's three do not exist here: there is no included allowance to exhaust
    (the payer is us) and no wallet to top up (there is nothing to sell an operator). What
    remains is the platform brake, which binds this surface for the reason the module
    docstring gives — it is the same key.

    `kind="transient"` so `core/errors.install_error_handlers` renders a 503 and alerts,
    exactly as `require_ai_assist`'s `ai_paused_platform_wide` arm does. The code is
    DIFFERENT (`admin_ai_paused_platform_wide`) and deliberately so: the client-facing code
    is what opens the client's wallet dialog, and an operator has no wallet — a shared code
    would put a "buy more AI" modal in front of somebody who cannot buy any.
    """
    spend = await read_platform_ai_spend(session)
    if spend.tripped:
        raise ProblemError(
            kind="transient",
            code="admin_ai_paused_platform_wide",
            title="The assistant is paused platform-wide",
            detail=(
                "This month's platform-wide AI spend has reached its ceiling, so the "
                "assistant is paused for everyone including the admin console. Nothing has "
                "been charged."
            ),
            remediation=(
                "It clears when the IST billing month rolls over. Releasing it sooner is a "
                "code change to PLATFORM_AI_BRAKE_INR with a review — see "
                "runbooks/alarm-index.md."
            ),
        )


__all__ = [
    "PLATFORM_ASSIST_META_KIND",
    "PlatformAssistMetered",
    "record_platform_ai_usage",
    "require_platform_ai",
]
