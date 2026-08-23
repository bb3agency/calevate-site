"""Commercial terms: what we agreed to charge a client, and WHEN it was agreed.

`plans` has carried the whole commercial relationship since the first migration —
`setup_fee`, `monthly_fee`, `included_min`, `overage_rate`, the admin ceilings and the
valid-time window that dates them — and until this module existed **nothing in this
product wrote one**. The only writer was `billing/caps.py::apply_client_caps`, which
mints a row carrying nothing but the CLIENT's own stop button. So the invoice, the
margin panel, the dispatch ceiling, the D-64 setup-fee cron and the whole of
`billing/plans.py`'s effective-dating machinery all resolved a row that an operator had
to INSERT BY HAND against production. This module is the writer that closes that, and
`admin/routes.py` is the surface over it.

INSERT-ONLY, AND WHY THAT IS NOT MERELY A PREFERENCE
-----------------------------------------------------
A plan change is a NEW DATED ROW. It is never an UPDATE of the row that priced a month
the client has already been billed for, because an invoice in this product is a DERIVED
statement (`billing/invoice.py` persists nothing) — re-rendering July reads `plans`
again. Editing the row that priced July therefore does not "change the price going
forward", it silently re-writes a statement the client has already paid, and
`tests/plan_effective_dating_test.py` exists because that has been a real defect here
once already.

`plans` is not one of hard rule 4's append-only ledgers and no trigger stops an UPDATE,
so this is a discipline the WRITER has to keep. `record_terms` has no UPDATE in it. The
one column pair this module never writes at all is `client_cap_min` / `client_cap_spend`
— those belong to the client (`billing/caps.py`), and a new agreement deliberately does
not inherit the limit they set against terms they had not yet seen.

THE WINDOW GESTURE, TAKEN FROM `billing/plans.py` RATHER THAN INVENTED HERE
----------------------------------------------------------------------------
Resolution is a total order, not an exclusion constraint (that module argues why at
length: every existing row is windowless, and any two windowless rows overlap). Among
the rows whose half-open `[effective_from, effective_to)` contains the instant, the
LATEST `effective_from` wins. Two consequences this module depends on:

- inserting the new terms with an `effective_from` is sufficient. The predecessor is
  left ALONE — not closed, not edited — and stops applying the moment the successor
  comes into effect. That is one statement, it is atomic, and it cannot lose history;
- so this module never writes `effective_to` on an existing row. An operator who wants
  terms to END rather than to be REPLACED says so on the new row they are writing, and
  the surface warns them what an end with no successor costs (`billing/plans.py`:
  the tenant's ceiling and rate silently stop binding, and `warn_no_plan_in_effect`
  starts logging).

Money is NUMERIC INR throughout (hard rule 7). No float is constructed anywhere in this
module and the route stringifies at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.caps import lock_tenant_spend_state, recompute_capped
from apps.api.billing.plans import NOW_SQL, plan_in_effect_sql
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

# WHAT AN OPERATOR AGREES, split into the two kinds it has always been two kinds of.
#
# `PRICING_COLUMNS` state what the client PAYS; `CEILING_COLUMNS` state what we refuse to
# exceed. `TERM_COLUMNS` is their concatenation and is what the SELECT, the INSERT and
# the equality test read, so those three cannot list different ones.
#
# THE SPLIT IS NAMED RATHER THAN RETYPED, and that is a fix. `PlanRecord.states_pricing`
# used to carry its own hand-written list of the price columns; `overage_rate_value` was
# added to `TERM_COLUMNS` when D-36's second rung landed and never to that list, so a
# plan quoting ONLY the value-tier rate — the exact row a founder writes the day that
# price is decided — billed the client and reported to the operator as "No price agreed
# … they are still invoiced nothing". One list, one classification, and
# `tests/plan_term_columns_test.py` fails if a column ever belongs to neither.
#
# `client_cap_*` is in neither and is deliberately absent from `TERM_COLUMNS` entirely:
# see the module docstring.
PRICING_COLUMNS: tuple[str, ...] = (
    "setup_fee",
    "monthly_fee",
    "included_min",
    "overage_rate",
    "overage_rate_value",
    "llm_model_surcharge",
)

CEILING_COLUMNS: tuple[str, ...] = (
    "hard_cap_min",
    "hard_cap_spend",
    "concurrency_ceiling",
)

TERM_COLUMNS: tuple[str, ...] = PRICING_COLUMNS + CEILING_COLUMNS

_ROW_COLUMNS = (
    "id, "
    + ", ".join(TERM_COLUMNS)
    + ", client_cap_min, client_cap_spend, effective_from, effective_to, created_at"
)

# "Which row prices this instant", asked with the SAME resolver every money reader uses.
# A second ordering here is how an operator's screen and the client's invoice would end
# up naming different rows as the current agreement.
_IN_EFFECT_AT = plan_in_effect_sql(_ROW_COLUMNS, at=":at")
_IN_EFFECT_NOW = plan_in_effect_sql(_ROW_COLUMNS, at=NOW_SQL)

# History, in the resolver's own order. Newest agreement first by VALID time — not by
# `created_at` — so the row at the top of an operator's screen is the row the resolver
# would pick, and a correction written after the row it corrects does not appear to win.
_HISTORY = f"""
    SELECT {_ROW_COLUMNS}
    FROM plans
    WHERE tenant_id = :tid
    ORDER BY COALESCE(effective_from, '-infinity'::timestamptz) DESC,
             created_at DESC,
             id DESC
"""

_INSERT = f"""
INSERT INTO plans (id, tenant_id, {", ".join(TERM_COLUMNS)},
                   effective_from, effective_to, created_at, updated_at)
VALUES (:id, :tid, {", ".join(f":{name}" for name in TERM_COLUMNS)},
        :effective_from, :effective_to, clock_timestamp(), clock_timestamp())
"""


@dataclass(frozen=True, slots=True)
class CommercialTerms:
    """The terms themselves — what an operator types, with no identity and no history.

    Every money field is `Decimal | None` and `None` means UNSET, never zero. The
    distinction is load-bearing in both directions: an `overage_rate` of 0 is free
    minutes and an unset one is a plan that quotes no overage at all, and
    `plans.overage_rate_value` documents the same rule for the value tier.
    """

    setup_fee: Decimal | None = None
    monthly_fee: Decimal | None = None
    included_min: int | None = None
    overage_rate: Decimal | None = None
    # The retail value-tier rate. Left settable and UNSET on purpose: TRD §10.1's cost
    # bands are unmeasured pilot gates, so any default here would be invention wearing a
    # citation. What goes in it is a founder decision, and until it is made the column
    # stays NULL and billing quotes one rate (`billing/models.py::Plan`).
    overage_rate_value: Decimal | None = None
    # What a minute costs EXTRA when the client chose a dearer language model (D-455,
    # `billing/models.py::Plan.llm_model_surcharge`). Settable and UNSET for
    # `overage_rate_value`'s reason: the number is a founder decision, and until it is
    # made the column stays NULL and a model choice moves the bill by nothing.
    llm_model_surcharge: Decimal | None = None
    hard_cap_min: int | None = None
    hard_cap_spend: Decimal | None = None
    concurrency_ceiling: int = 10
    effective_from: datetime | None = None
    effective_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class PlanRecord:
    """One row of `plans` as an operator reads it: the terms, plus who set what."""

    id: UUID
    terms: CommercialTerms
    # The client's own ceilings, read-only here. Shown beside the admin's because the
    # EFFECTIVE cap is the stricter of the two and a screen that omitted the client's
    # half could not explain why a client is capped below the plan.
    client_cap_min: int | None
    client_cap_spend: Decimal | None
    created_at: datetime

    @property
    def states_pricing(self) -> bool:
        """Does this row actually say what the client pays?

        `apply_client_caps` mints rows carrying nothing but the client's own caps, and
        such a row is "in effect" for every reader while agreeing no price at all. An
        operator screen that counted it as commercial terms would report a tenant as
        priced when nobody had priced them.

        DERIVED FROM `PRICING_COLUMNS`, never from a list retyped here. The retyped list
        is what made this property lie: it predated `overage_rate_value`, so a plan
        quoting only the value-tier rate answered False while `usage_summary` charged the
        client at it, and the console said "No price agreed … they are still invoiced
        nothing" over a real bill. A ceiling is deliberately still not a price — a plan
        that caps spend and quotes nothing agrees no terms.
        """
        return any(getattr(self.terms, column) is not None for column in PRICING_COLUMNS)


# What an operator has to resolve, named rather than left to be inferred from a null.
#
# `none`     — this tenant has no `plans` row at all. The state every tenant is born in
#              (see `admin/routes.py::read_commercial_terms` for why onboarding does NOT
#              seed one), and the state `caps.read_caps` reads as "no ceiling".
# `unpriced` — a row is in effect but states no price: the cap-only row minted by the
#              client's own stop button. Reads identically to `none` for every money
#              reader; distinguished because the REMEDY is the same but the screen must
#              not claim the account has terms.
# `lapsed`   — rows exist and none is in effect. A misconfiguration
#              (`billing/plans.py::warn_no_plan_in_effect` logs it): an `effective_to`
#              was written with no successor, and the tenant's ceiling and rate stopped
#              binding on the stroke of that instant.
# `set`      — a priced row is in effect.
TermsState = Literal["none", "unpriced", "lapsed", "set"]


@dataclass(frozen=True, slots=True)
class TermsView:
    state: TermsState
    in_effect: PlanRecord | None
    history: tuple[PlanRecord, ...]


def _record(values: Row[Any]) -> PlanRecord:
    """One `plans` row, read BY NAME rather than by position.

    Positional reads (`values[5]`) were the previous shape and they are a trap next to a
    list that is meant to grow: `_ROW_COLUMNS` interpolates `TERM_COLUMNS`, so inserting
    a ninth agreed column shifts `client_cap_min` down one and this function silently
    reads a rupee ceiling into a minute count — no error, no test, a wrong number on a
    commercials screen. `_mapping` is keyed by the SELECT's own column names, which are
    exactly the names `_ROW_COLUMNS` was built from, so the two cannot drift apart.
    """
    row = values._mapping
    return PlanRecord(
        id=row["id"],
        terms=CommercialTerms(
            setup_fee=_money(row["setup_fee"]),
            monthly_fee=_money(row["monthly_fee"]),
            included_min=_count(row["included_min"]),
            overage_rate=_money(row["overage_rate"]),
            overage_rate_value=_money(row["overage_rate_value"]),
            llm_model_surcharge=_money(row["llm_model_surcharge"]),
            hard_cap_min=_count(row["hard_cap_min"]),
            hard_cap_spend=_money(row["hard_cap_spend"]),
            concurrency_ceiling=int(row["concurrency_ceiling"]),
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
        ),
        client_cap_min=_count(row["client_cap_min"]),
        client_cap_spend=_money(row["client_cap_spend"]),
        created_at=row["created_at"],
    )


def _money(value: object) -> Decimal | None:
    """NUMERIC in, `Decimal` out — via `str`, never `float` (hard rule 7)."""
    return None if value is None else Decimal(str(value))


def _count(value: object) -> int | None:
    return None if value is None else int(str(value))


async def plan_in_effect(
    session: AsyncSession, *, tenant_id: UUID, at: datetime | None = None
) -> PlanRecord | None:
    """The one row in effect at `at` (default: now), by the shared resolver."""
    statement, params = (
        (_IN_EFFECT_NOW, {"tid": tenant_id})
        if at is None
        else (_IN_EFFECT_AT, {"tid": tenant_id, "at": at})
    )
    row = (await session.execute(text(statement), params)).first()
    return None if row is None else _record(row)


async def read_terms(session: AsyncSession, *, tenant_id: UUID) -> TermsView:
    """Everything the Commercials screen needs in one read: the row in force, the
    whole dated history behind it, and the NAME of the state an operator is looking at.

    The state is computed here rather than on the screen for the reason every other
    server-side predicate in this codebase is: two answers to "does this client have
    terms" is how a console ends up reporting an account as priced while the invoice
    prices it at nothing.
    """
    rows = (await session.execute(text(_HISTORY), {"tid": tenant_id})).all()
    history = tuple(_record(row) for row in rows)
    current = await plan_in_effect(session, tenant_id=tenant_id)
    if not history:
        state: TermsState = "none"
    elif current is None:
        state = "lapsed"
    elif not current.states_pricing:
        state = "unpriced"
    else:
        state = "set"
    return TermsView(state=state, in_effect=current, history=history)


def loosened_ceilings(current: PlanRecord | None, terms: CommercialTerms) -> tuple[str, ...]:
    """Which ADMIN ceilings this write would raise or remove, by field name.

    The rule the role table in `core/rbac.py` states — cap raises are a superadmin
    action with a step-up confirmation — needs a definition of "raise", and the honest
    one is a comparison against the ceiling this row supersedes rather than against
    nothing. Removing a ceiling (`None`) is the LOOSEST possible value and counts;
    tightening one, or setting the first ceiling a tenant has ever had, does not, so an
    operator can still complete an onboarding without a superadmin in the room.

    A tenant with no plan in effect has no ceiling to loosen, so their first terms are
    never a raise however generous — which is correct: unlimited is what they have right
    now (`caps.over_cap_sql`: an absent ceiling is an absent constraint).
    """
    if current is None:
        return ()
    raised: list[str] = []
    for field, old, new in (
        ("hard_cap_min", current.terms.hard_cap_min, terms.hard_cap_min),
        ("hard_cap_spend", current.terms.hard_cap_spend, terms.hard_cap_spend),
    ):
        if old is None:
            continue  # already unlimited; nothing to loosen
        if new is None or Decimal(str(new)) > Decimal(str(old)):
            raised.append(field)
    return tuple(raised)


def _same_terms(record: PlanRecord, terms: CommercialTerms) -> bool:
    """Do these terms say exactly what the row in effect already says?

    The dataclass's own equality, which compares every agreed field INCLUDING the
    window — a row re-dated to start next month is a change even when every amount on
    it is identical. Decimal comparison is by VALUE (`Decimal("8.00") ==
    Decimal("8.0000")`), which is what an operator means by "unchanged": the column is
    NUMERIC(12,4) and re-typing ₹8 must not mint a row because the stored copy carries
    four decimal places.
    """
    return record.terms == terms


@dataclass(frozen=True, slots=True)
class TermsWriteResult:
    plan_id: UUID
    # False when the submitted terms were ALREADY the terms in effect and nothing was
    # written. The caller audits on `True` only — the convention `kb.approve_source` and
    # `integrations.deactivate_endpoint` established: an audit row belongs to a real
    # change, not to a button press.
    changed: bool
    # What this write superseded, for the audit summary and for the response. `None`
    # when the tenant had no terms in effect at the new row's start instant.
    superseded: PlanRecord | None
    # True when this write leaves the tenant OVER their ceiling right now — i.e. the
    # operator has just stopped this client's outbound calling for the rest of the
    # month. The same fact `caps.CapWriteResult.capped_now` carries for the client's own
    # stop button, and its consumers are the two places an operator looks after changing
    # a ceiling: the `plan.terms_recorded` audit row (a ceiling change that stopped a
    # client's calling is exactly what that log is for) and the structured log line.
    # `False` when nothing is in effect for the current billing month, which is also
    # "not capped".
    capped_now: bool = False


async def record_terms(
    session: AsyncSession, *, tenant_id: UUID, terms: CommercialTerms
) -> TermsWriteResult:
    """Write a new dated `plans` row — the ONLY way this product changes a price.

    Idempotent in the one way that matters: if the terms in effect at this row's start
    instant already say exactly this, including the same window, nothing is written and
    `changed` is False. That is not a nicety — the wizard and the console both save on a
    button an operator can press twice, and a duplicate row would leave two identical
    agreements resolved by a tie-break, which is history nobody agreed to.

    No UPDATE, anywhere, including on the predecessor: the total-order resolver makes
    the insert sufficient (module docstring). The row's own `created_at` is
    `clock_timestamp()` rather than `now()`, so two rows written in one transaction have
    distinct stamps and "newest" stays a total order — the same reason
    `tests/plan_effective_dating_test.py` gives for its fixture.

    **IT RE-ARMS THE GATE, AND THAT USED TO BE THE HALF NOBODY DID.** `hard_cap_min` /
    `hard_cap_spend` are written HERE and nowhere else, `over_cap_sql` compares them
    through `LEAST(hard, client)`, and the only thing that can stop a dial is
    `spend_state.capped` (`compliance.check_dispatch` reads that boolean and nothing
    else). This function wrote the ceiling and left the flag alone, so a TIGHTENING did
    nothing until the next completed call happened to meter — and for an outbound-only
    tenant the next completed call is precisely what the ceiling was supposed to stop.
    Measured on this tree before the fix (`tests/admin_cap_arms_the_gate_test.py` is the
    reproduction): ₹480 already billed for the month, operator writes
    `hard_cap_spend = ₹100`, `spend_state.capped` stays `false` and `check_dispatch`
    still returns `allowed=True`.

    `billing/caps.py::apply_client_caps` had this right for the CLIENT's own stop button
    and states the argument in as many words — "a cap accepted whose gate is not armed
    is a cap that does nothing until the next call meters". The two surfaces write the
    two halves of ONE ceiling, so they now do the same thing, through the same
    `recompute_capped` rather than a second UPDATE: there is one definition of "over
    cap" across all three writers of the flag.

    **The lock is taken FIRST, before the read this write depends on.** A ceiling read
    outside `lock_tenant_spend_state` is the same check-then-write hole a balance read
    outside `lock_tenant_credits` is, and the concurrent writer is the post-call meter —
    which reads `plans` and writes `spend_state` in one statement, so a row lock cannot
    span it (that function carries the Postgres semantics). Re-entrant, so the
    `recompute_capped` below re-taking it costs nothing.
    """
    await lock_tenant_spend_state(session, tenant_id)
    # The row this one supersedes, resolved AT THE NEW ROW'S START — not at now. A
    # change dated for next month supersedes whatever will be in force then, and
    # comparing it against today's row would call an unchanged future write a change.
    superseded = await plan_in_effect(session, tenant_id=tenant_id, at=terms.effective_from)
    if superseded is not None and _same_terms(superseded, terms):
        # Nothing was written, so nothing can have moved the ceiling. Deliberately NOT
        # recomputed here: the flag is derived from terms this call did not change, and
        # re-deriving it would make an idempotent no-op into a write.
        return TermsWriteResult(plan_id=superseded.id, changed=False, superseded=None)

    plan_id = uuid7()
    await session.execute(
        text(_INSERT),
        {
            "id": plan_id,
            "tid": tenant_id,
            "setup_fee": terms.setup_fee,
            "monthly_fee": terms.monthly_fee,
            "included_min": terms.included_min,
            "overage_rate": terms.overage_rate,
            "overage_rate_value": terms.overage_rate_value,
            "llm_model_surcharge": terms.llm_model_surcharge,
            "hard_cap_min": terms.hard_cap_min,
            "hard_cap_spend": terms.hard_cap_spend,
            "concurrency_ceiling": terms.concurrency_ceiling,
            "effective_from": terms.effective_from,
            "effective_to": terms.effective_to,
        },
    )
    # AFTER the insert and inside the same transaction, so a ceiling that is accepted and
    # a gate that is armed are one atomic fact. `None` = no `spend_state` row for the
    # current billing month, i.e. nothing metered yet, which is not capped.
    capped = await recompute_capped(session, tenant_id=tenant_id)
    log.info(
        "commercial_terms_recorded",
        extra={
            # Ids and the SHAPE of the change. Never the amounts: a client's commercial
            # terms are not ours to scatter through log aggregation, which is the same
            # discipline `warn_no_plan_in_effect` keeps (hard rule 6 is about PII; this
            # is the adjacent rule the plans module already states).
            "tenant_id": str(tenant_id),
            "plan_id": str(plan_id),
            "supersedes": str(superseded.id) if superseded else None,
            "dated": terms.effective_from is not None,
            "ends": terms.effective_to is not None,
            # Whether this write stopped the client's outbound calling. Not an amount —
            # a client's commercial terms stay off the log line (see above).
            "capped_now": bool(capped),
        },
    )
    return TermsWriteResult(
        plan_id=plan_id, changed=True, superseded=superseded, capped_now=bool(capped)
    )


__all__ = [
    "CEILING_COLUMNS",
    "PRICING_COLUMNS",
    "TERM_COLUMNS",
    "CommercialTerms",
    "PlanRecord",
    "TermsState",
    "TermsView",
    "TermsWriteResult",
    "loosened_ceilings",
    "plan_in_effect",
    "read_terms",
    "record_terms",
]
