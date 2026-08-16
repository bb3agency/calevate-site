"""Spend caps: whose cap is whose, and which one actually binds.

`plans.hard_cap_min` / `plans.hard_cap_spend` are ADMIN-owned. They are the ceiling we
agreed with the client and the client cannot move them — that is the whole point of a
ceiling. But SURFACES §2b:89 lists "spend against cap" on the client's own plan panel
and D-34's R-11 lists per-account spend caps among the non-negotiable mitigations that
ship with the self-serve motion, and until this module existed there was no client
surface at all. Both halves of that are wrong in opposite directions:

- **a control the spender can raise at will is not a control.** If the client could
  edit `hard_cap_*` there would be no ceiling, only a suggestion, and R-11's mitigation
  would be decorative.
- **a limit on their own money they cannot lower is not their account.** A self-serve
  owner watching a campaign burn is exactly the person who needs a stop button, and
  "email your account manager" is not one.

So there are TWO caps per plan and the effective one is the STRICTER:

    effective_cap_min   = LEAST(hard_cap_min,   client_cap_min)
    effective_cap_spend = LEAST(hard_cap_spend, client_cap_spend)

NULL on either side means "no constraint from this side", which is exactly Postgres's
`LEAST` semantics — it ignores NULLs and returns NULL only when every input is NULL.
That is why the SQL below is `LEAST` and not a hand-rolled `CASE`: the identity we
want and the function's behaviour are the same thing, so they cannot drift.

WHY THE CLIENT SIDE IS A SEPARATE PAIR OF COLUMNS
--------------------------------------------------
Storing one merged number would destroy the fact that makes the surface safe: which
number the admin agreed to. A client who lowers to ₹2,000 and then clears their own cap
must land back on the admin's ceiling, not on ₹2,000-forever and not on unlimited. Two
columns keep both answers; the effective cap is derived, never stored, for the same
reason `agents.live_prompt_id` exists rather than a `has_pending` flag.

SETTING A CAP BELOW WHAT HAS ALREADY BEEN SPENT THIS MONTH
-----------------------------------------------------------
This is the decision this module has to defend, because both answers are real product
positions and the code has to pick one.

**We accept it, and it takes effect immediately: the tenant is capped for the rest of
the billing month and outbound calling stops at once.** `apply_client_caps` recomputes
`spend_state.capped` from the counters already in the row, in the same transaction as
the write, so the gate refuses the very next dial rather than the dial after the next
call happens to meter.

The alternative — refuse the value, or accept it and let it bind only from next month —
was rejected on the following grounds:

1. **The person setting a cap below their spend is the person having the emergency.**
   A runaway campaign, a misconfigured retry ladder, a number dialling a wrong list: in
   every case the client's intent is "stop now". A cap that answers "that is below what
   you have already spent, please pick a bigger number" refuses the one instruction the
   feature exists to obey.
2. **The blast radius is bounded and reversible in the same breath.** The compliance
   gate is OUTBOUND-ONLY (`compliance/service.py`), so inbound keeps answering — a
   client cannot take their own receptionist off the air with this control. And the
   client can raise their cap back up to the admin's ceiling from the same screen, with
   the same immediacy, so a mistaken stop costs one more click, not a support ticket.
3. **A cap that binds "from next month" is a cap that does nothing when it matters.**
   Spend caps are a mitigation for a self-serve motion where anyone can sign up and
   dial (R-11). A mitigation with a month of latency is not a mitigation.
4. **It is the client's own money.** The admin's ceiling protects us from an
   unrecoverable bill; the client's protects them from theirs. We do not get to hold
   their outbound calling open against their written instruction because we would
   rather bill it.

The cost we accept, stated plainly: a client can stop their own outbound calling
mid-campaign by typing a number, and a campaign already dispatching will be refused
call by call. `PUT /v1/billing/caps` says so in its response (`capped`, from `capped_now`) rather
than leaving the client to discover it from an empty call list.

THREE WRITERS OF `spend_state.capped`, AND WHY THAT IS SAFE
-----------------------------------------------------------
The post-call meter (`workers/pipeline.py`) is the writer that ARMS the flag. The other
two are in this module and both go through `recompute_capped` below: the client's own
`PUT /v1/billing/caps` (via `apply_client_caps`) and the ops-realm
`POST /v1/ops/tenants/{tenant_id}/spend-cap/recompute`. Neither writes anything but the
flag, neither writes it for any month but the current one, and neither touches a
counter. The three cannot disagree about what "over cap" means because they share one
expression — `over_cap_sql` below — rather than each carrying a copy. `spend_state` is
a counter table, not a ledger: the append-only set is `db.registry.APPEND_ONLY_TABLES`
(named, not re-listed here — this comment used to enumerate four of it and the set has
grown twice since), `spend_state` is not in it, and nothing in it is written here.

**A SHARED EXPRESSION WAS NOT ENOUGH, AND THIS PARAGRAPH IS THE CORRECTION.** The three
writers agreeing about the DEFINITION of "over cap" says nothing about their agreeing on
the INPUTS, and they did not: the client's stop button and the post-call meter read the
ceiling out of `plans` and write the flag into `spend_state`, two tables, so blocking on
the `spend_state` row serialized half the decision. The meter would unblock, pair the
new counters with the ceiling from before the client lowered it, and un-cap them. All
three now take `lock_tenant_spend_state` before the statement that reads the ceiling —
which is the guarantee the shared expression was being asked to provide and could not.

THE OPS WRITER EXISTS BECAUSE THE OTHER TWO CANNOT REACH THE CASE
------------------------------------------------------------------
A capped tenant meters nothing, so the meter can never clear what it armed; and the
client's route needs `org:manage`, which is in `MUTATING_PERMISSIONS`, so an
impersonating admin (D-22) cannot press that button for them. Raising
`plans.hard_cap_*` on the audited admin path therefore left a capped OUTBOUND-ONLY
tenant blocked until the client acted or the IST month rolled over —
`runbooks/calls-stopped.md` §2 documents the incident that found it. The ops route is
the third writer and it is the SAME recompute, not a new one: an ops console that could
set the flag directly would be the writer that finally makes the meter and the gate
disagree.

A stale month is left ALONE rather than recomputed. `compliance.spend_capped` already
treats a flag belonging to a closed month as no cap at all, so rewriting it would move
a number nobody reads while pretending last month's counters mean something today.

Money is NUMERIC INR throughout (hard rule 7): no float appears in this module and the
route that calls it refuses a JSON float at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import NOW_SQL, plan_in_effect_sql, warn_no_plan_in_effect
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

# The effective cap, as SQL. `LEAST` ignores NULL inputs, which IS the semantics we
# want ("NULL = no constraint from this side"), so there is no CASE to get wrong.
EFFECTIVE_CAP_MIN_SQL = "LEAST(hard_cap_min, client_cap_min)"
EFFECTIVE_CAP_SPEND_SQL = "LEAST(hard_cap_spend, client_cap_spend)"

# The body of the `caps` CTE every cap reader opens with. `plans` is effective-dated,
# so a tenant that ever changed plan has SEVERAL rows and a join on tenant_id alone
# multiplies them — the row that binds is the one whose VALID-TIME WINDOW contains the
# instant being judged (`billing/plans.py`), which for a ceiling is always NOW: a cap
# decides whether this dial may happen, and this dial is happening now. It is emphatically
# not "the newest row", which is what this expression said until effective dating was
# wired and is how a ceiling agreed for next month could stop today's calling.
#
# `now()` is transaction-start time, so the meter's upsert judges its counters and its
# ceiling at one consistent instant rather than two. Exported so the meter and this
# module cannot end up capping against different rows.
CAPS_CTE = plan_in_effect_sql(
    f"{EFFECTIVE_CAP_MIN_SQL} AS cap_min, {EFFECTIVE_CAP_SPEND_SQL} AS cap_spend", at=NOW_SQL
)


async def lock_tenant_spend_state(session: AsyncSession, tenant_id: UUID) -> None:
    """Serialize every writer of `spend_state.capped` for this tenant, for the rest of
    the transaction. **Take it BEFORE the statement that reads `plans`.**

    THE DEFECT THIS CLOSES, and it is not a theoretical one — it reproduces on demand.
    A client presses their own stop button (`apply_client_caps` writes
    `plans.client_cap_spend` and re-derives the flag in one transaction) while the
    post-call meter's `spend_state` upsert is already in flight. The meter's statement
    blocks on the `spend_state` ROW, which looks like serialization and is not:

        READ COMMITTED ... "it is possible for an updating command to see an
        inconsistent snapshot: it can see the effects of concurrent updating commands on
        the same rows it is trying to update, but it does not see effects of those
        commands on other rows in the database."
        — postgresql.org/docs/16/transaction-iso.html §13.2.1

    `spend_state` is the row it is updating; `plans` is another row. So the meter
    unblocks, reads the NEW counters and the OLD ceiling, computes `capped = false` and
    overwrites the flag the client just armed. Their outbound calling resumes until the
    next completed call happens to re-derive it — which, for the runaway campaign this
    button exists to stop, is immediately and repeatedly.

    A row lock is therefore the wrong tool and no amount of ordering fixes it: the
    ceiling and the counters live in two tables and the guarantee has to span both. An
    advisory lock taken before the reading statement does span it — the waiter's next
    statement takes a fresh snapshot after the holder commits, so it reads the ceiling
    that was just written. Same idiom, same reasoning and same failure mode as
    `service.lock_tenant_credits`, which is why it is spelled the same way.

    Its own key, not `credit:`: these serialize different things, and one key would put
    every completed call behind every wallet write. Deadlock-free because the two are
    never taken in opposite orders — the meter takes `credit:` (inside `charge_for_call`)
    and then this one, and nothing takes this one before `credit:`.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"spend_state:{tenant_id}"},
    )


def over_cap_sql(minutes_expr: str, spend_expr: str) -> str:
    """SQL for "these totals have reached one of the EFFECTIVE ceilings".

    Reads the `caps` CTE above, so every caller must open with it.

    EITHER ceiling closes the gate: a tenant well inside its minute allowance can still
    be burning money, and a tenant on a cheap voice can run the clock out without ever
    approaching the rupee ceiling. `>=` because a ceiling that is exactly reached is
    spent — the same arithmetic the usage panel's "minutes left" does when it reports 0.

    A ceiling that is NULL — an unlimited plan, a tenant with no `plans` row at all
    (the scalar subquery yields NULL), or a pair where BOTH the admin and the client
    left it unset — must never cap: `COALESCE(x >= NULL, false)` is false, so an absent
    ceiling is an absent constraint. A missing plan row means the default and never a
    refusal; the alternative reads a new client's empty billing setup as a ceiling of
    zero and takes their phones down on day one.
    """
    return (
        f"(COALESCE(({minutes_expr}) >= (SELECT cap_min FROM caps), false) "
        f"OR COALESCE(({spend_expr}) >= (SELECT cap_spend FROM caps), false))"
    )


def effective_cap(admin: Decimal | int | None, client: Decimal | int | None) -> Decimal | None:
    """The stricter of the two, in Python, matching `LEAST` exactly.

    Returned as `Decimal | None` for both cap kinds so one function answers for minutes
    and for rupees; the minute caller casts back to `int`. NUMERIC in, NUMERIC out —
    nothing here becomes a float (hard rule 7).
    """
    values = [Decimal(str(value)) for value in (admin, client) if value is not None]
    return min(values) if values else None


@dataclass(frozen=True, slots=True)
class CapView:
    """Both sides of both caps, plus what actually binds. The client screen needs all
    three: "your limit", "your plan's limit", and "the one in force" are different
    facts and a panel that shows only the last of them cannot explain itself."""

    admin_cap_min: int | None
    admin_cap_spend: Decimal | None
    client_cap_min: int | None
    client_cap_spend: Decimal | None

    @property
    def effective_cap_min(self) -> int | None:
        value = effective_cap(self.admin_cap_min, self.client_cap_min)
        return int(value) if value is not None else None

    @property
    def effective_cap_spend(self) -> Decimal | None:
        return effective_cap(self.admin_cap_spend, self.client_cap_spend)


_PLAN_CAPS_SELECT = plan_in_effect_sql(
    "id, hard_cap_min, hard_cap_spend, client_cap_min, client_cap_spend", at=NOW_SQL
)


async def read_caps(session: AsyncSession, *, tenant_id: UUID) -> CapView:
    """The caps on the plan IN EFFECT NOW, or an all-NULL view when none is.

    No plan row is a real state — nothing in the codebase creates one, so an
    admin-onboarded tenant has one only if an operator wrote it by hand. It reads as
    "no constraint from either side", which is what the meter already concludes.

    A tenant whose plan WINDOW has closed with no successor reads the same way, and
    that is the one case worth a log line rather than a silent shrug: it is a
    misconfiguration (an `effective_to` written without an `effective_from` to follow
    it) and its symptom is a ceiling quietly ceasing to bind. `warn_no_plan_in_effect`
    costs one indexed count and only on the path where there is already no plan.
    """
    row = (await session.execute(text(_PLAN_CAPS_SELECT), {"tid": tenant_id})).first()
    if row is None:
        await warn_no_plan_in_effect(session, tenant_id=tenant_id)
        return CapView(None, None, None, None)
    return CapView(
        admin_cap_min=int(row[1]) if row[1] is not None else None,
        admin_cap_spend=Decimal(str(row[2])) if row[2] is not None else None,
        client_cap_min=int(row[3]) if row[3] is not None else None,
        client_cap_spend=Decimal(str(row[4])) if row[4] is not None else None,
    )


def _refuse_looser(*, kind: str, admin: Decimal | int | None, client: Decimal | int | None) -> None:
    """A client cap above the admin's is refused, not clamped.

    Silently clamping would store a number the client did not type and show it back to
    them as their own choice — the shape that makes a cap untrustworthy (the same
    argument `a4e7b2c95d18` makes for CHECKing `max_call_duration_s` rather than
    clamping it). An admin ceiling that is NULL constrains nothing, so any client value
    is stricter than it and is accepted.
    """
    if admin is None or client is None:
        return
    if Decimal(str(client)) > Decimal(str(admin)):
        raise ProblemError.business_rule(
            "client_cap_exceeds_plan_cap",
            "Your limit cannot be higher than the limit on your plan.",
            remediation=(
                f"Your plan's {kind} limit is {admin}. Choose that or less, or contact "
                "us to have the plan limit raised."
            ),
        )


# The recompute. `minutes_used` / `spend_used` are the counters ALREADY in the row —
# this statement reads them and writes only the flag, so it can never move a total.
_RECOMPUTE_CAPPED = f"""
WITH caps AS ({CAPS_CTE})
UPDATE spend_state
SET capped = {over_cap_sql("minutes_used", "spend_used")}, updated_at = now()
WHERE tenant_id = :tid AND month = :month
RETURNING capped
"""

_SPEND_STATE_SELECT = (
    "SELECT minutes_used, spend_used, capped, month FROM spend_state WHERE tenant_id = :tid"
)


@dataclass(frozen=True, slots=True)
class SpendCounters:
    """This month's metered totals and the flag the gate reads.

    A row stamped with a CLOSED month reads as zeros and not-capped, which is not a
    convenience: `compliance.spend_capped` compares `spend_state.month` against the
    current IST billing month, so last month's flag is already not a cap and last
    month's totals are already not this month's spend. Reporting them as though they
    were would show a client a spend they have not made and a ceiling nothing is
    enforcing.
    """

    minutes_used: Decimal
    spend_used: Decimal
    capped: bool


NO_SPEND_THIS_MONTH = SpendCounters(Decimal("0"), Decimal("0"), False)


async def read_spend_counters(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> SpendCounters:
    """The CURRENT billing month's counters, or zeros when the row is absent or stale.

    `month` lets a caller that has ALREADY decided which month is "now" hand that
    decision in rather than have this function take its own reading of the clock. It is
    not a filter — passing a closed month does not fetch that month's counters, because
    `spend_state` keeps no history — it is the instant the staleness test is made
    against. `usage_summary` passes it because it asks this question and then asks
    `_spend_used` the same question again: at 00:00:00 IST on the 1st those two readings
    can straddle the roll, and the panel then reports a closed month's spend as ₹0.00
    while reading its minutes correctly from the ledger. One reading, one answer.
    """
    from apps.api.billing.service import current_billing_month

    row = (await session.execute(text(_SPEND_STATE_SELECT), {"tid": tenant_id})).first()
    if row is None or str(row[3]) != (month or current_billing_month()):
        return NO_SPEND_THIS_MONTH
    return SpendCounters(Decimal(str(row[0])), Decimal(str(row[1])), bool(row[2]))


async def recompute_capped(session: AsyncSession, *, tenant_id: UUID) -> bool | None:
    """Re-derive `spend_state.capped` from the counters already in the row.

    THE one place the flag is written outside the meter. Both non-meter writers — the
    client's cap change and the ops recompute — call this rather than each issuing an
    UPDATE, so "over cap" has one definition across three writers (see the module
    docstring).

    Returns the flag as it now stands, or `None` when there is no row for the CURRENT
    billing month — a tenant that has metered nothing this month, or whose row still
    belongs to a closed one. That is a real and distinct answer, not an error: nothing
    is capped, nothing needed writing, and a stale row is deliberately left alone
    because `spend_capped` already reads its month.
    """
    # Imported HERE, not at module scope: `billing.service.usage_summary` reads the
    # effective-cap expression from this module, so a top-level import in either
    # direction closes a cycle. One function-local import beats a second definition of
    # the IST billing month, which is the only other way out.
    from apps.api.billing.service import current_billing_month

    # Before the statement, because the statement READS `plans` (through `CAPS_CTE`) and
    # WRITES `spend_state`. Re-entrant, so `apply_client_caps` holding it already costs
    # nothing; the ops recompute reaches this function with nothing held and needs it.
    await lock_tenant_spend_state(session, tenant_id)
    result = await session.execute(
        text(_RECOMPUTE_CAPPED), {"tid": tenant_id, "month": current_billing_month()}
    )
    value = result.scalar()
    return bool(value) if value is not None else None


# A plan row that exists only to carry the client's own caps. Every other column is
# left NULL — which is what `usage_summary`, the dispatcher and the meter already read
# when there is no plan row at all, so minting one changes no price and no ceiling.
# `concurrency_ceiling` takes the column's own server default (10), the same number
# `campaign_dispatch` falls back to for a tenant with no plan row.
_INSERT_CLIENT_CAP_PLAN = """
INSERT INTO plans (id, tenant_id, client_cap_min, client_cap_spend, created_at, updated_at)
VALUES (:id, :tid, :cap_min, :cap_spend, now(), now())
"""

_UPDATE_CLIENT_CAPS = """
UPDATE plans SET client_cap_min = :cap_min, client_cap_spend = :cap_spend, updated_at = now()
WHERE id = :plan_id
"""


@dataclass(frozen=True, slots=True)
class CapWriteResult:
    caps: CapView
    # True when the tenant is capped RIGHT NOW as a result of this write — the client
    # has stopped their own outbound calling for the rest of the month. Reported rather
    # than left to be discovered from an empty call list.
    capped_now: bool


async def apply_client_caps(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    cap_min: int | None,
    cap_spend: Decimal | None,
) -> CapWriteResult:
    """Write the client's own caps and re-arm the gate in ONE transaction.

    Both values are written together, and `None` CLEARS that side — a PUT states the
    whole client-side pair, so "clear my minute cap but keep my rupee cap" is
    expressible without a second verb. Clearing is not raising past the admin: it
    returns the client to the admin's ceiling, which is where they started.

    The write updates the plan row IN EFFECT NOW, or mints one when none is. A later
    plan row inserted by an operator does NOT inherit the client's cap, and that is
    deliberate: `plans` is effective-dated, so a new row is a new agreement — carrying
    a client's old self-imposed limit into it would apply a number to terms they never
    saw. What the client set is still on the row it was set against, which is where an
    operator can read it.

    The minted row is deliberately WINDOWLESS (`effective_from`/`effective_to` NULL =
    "since forever, until further notice"), which is what an open-ended arrangement is
    and what every plan row in the database already looks like. One consequence to know:
    a tenant whose only plan row has EXPIRED gets a fresh windowless row here carrying
    nothing but their own caps — the client keeps their stop button, and the expired
    commercial terms stay expired rather than being resurrected by a cap change.

    The flag recompute is the reason this is not two statements in the route: a cap
    accepted whose gate is not armed is a cap that does nothing until the next call
    meters, and for an outbound-only tenant the next call is exactly what the cap was
    supposed to stop.
    """
    # FIRST, before the `plans` read this write depends on. A ceiling read outside the
    # lock is the same check-then-write hole a balance read outside `lock_tenant_credits`
    # is, and the concurrent writer here is the post-call meter — see
    # `lock_tenant_spend_state` for the Postgres semantics that make a row lock
    # insufficient.
    await lock_tenant_spend_state(session, tenant_id)
    caps = await read_caps(session, tenant_id=tenant_id)
    _refuse_looser(kind="minute", admin=caps.admin_cap_min, client=cap_min)
    _refuse_looser(kind="spend", admin=caps.admin_cap_spend, client=cap_spend)

    row = (await session.execute(text(_PLAN_CAPS_SELECT), {"tid": tenant_id})).first()
    if row is None:
        await session.execute(
            text(_INSERT_CLIENT_CAP_PLAN),
            {"id": uuid7(), "tid": tenant_id, "cap_min": cap_min, "cap_spend": cap_spend},
        )
    else:
        await session.execute(
            text(_UPDATE_CLIENT_CAPS),
            {"plan_id": row[0], "cap_min": cap_min, "cap_spend": cap_spend},
        )

    capped = await recompute_capped(session, tenant_id=tenant_id)

    log.info(
        "client_caps_set",
        extra={
            "tenant_id": str(tenant_id),
            # Ids and the client's own ceilings only — a cap is not PII and there is no
            # phone number, transcript or extraction anywhere on this path (rule 6).
            "cap_min": cap_min,
            "capped_now": bool(capped),
        },
    )
    return CapWriteResult(
        caps=await read_caps(session, tenant_id=tenant_id), capped_now=bool(capped)
    )


__all__ = [
    "CAPS_CTE",
    "EFFECTIVE_CAP_MIN_SQL",
    "EFFECTIVE_CAP_SPEND_SQL",
    "NO_SPEND_THIS_MONTH",
    "CapView",
    "CapWriteResult",
    "SpendCounters",
    "apply_client_caps",
    "effective_cap",
    "lock_tenant_spend_state",
    "over_cap_sql",
    "read_caps",
    "read_spend_counters",
    "recompute_capped",
]
