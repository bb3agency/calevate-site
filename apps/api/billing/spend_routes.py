"""Where every rupee went, in BOTH realms — three routes over ONE computation.

`billing/attribution.py` attributes a tenant-month to its calls and its agents, both
directions of the money, once. This file renders it, and the ONLY thing it decides is
WHO SEES WHICH HALF:

    GET /v1/billing/spend                     client  — what THEY were charged, itemised
    GET /v1/admin/tenants/{tenant_id}/spend   admin   — the same, plus what WE paid
    GET /v1/admin/spend                       admin   — one row per live client

**THE SPLIT IS TWO SEPARATE MODELS, NOT ONE MODEL AND A FLAG.** `unit_cost_paid` is our
supplier pricing (`admin/routes.py::tenant_margin` and `crm/schemas.UsagePanelOut` both
say so already), and a client who can see it is a client negotiating against it. The
client models below declare no cost-shaped field at all and are `extra="forbid"`, so the
exclusion is a property of the type rather than of a branch somebody could invert — and
`tests/spend_attribution_test.py` reads the model's own field list to prove it, so a
later widening fails a test rather than reaching a browser.

Deliberately NOT achieved by subclassing the client model: a shared base is a place to
add a field, and the one field that must never be added is the whole point of the file.

Money is a STRING on every one of these, like every other billing response: the values
are `Decimal` (hard rule 7) and `Number()` on INR is how ₹10,159.00 becomes
₹10,158.999999999998.

These routers are NOT mounted here — the integrator mounts them (`main.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin import service as admin_service
from apps.api.billing import rates, tts_speaking_rate
from apps.api.billing import service as billing
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.billing.attribution import (
    AgentAttribution,
    CallAttribution,
    PeriodAttribution,
    period_attribution,
)
from apps.api.billing.plans import ist_month_window, month_pricing_instant
from apps.api.billing.service import to_paise
from apps.api.core.auth import record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session
from apps.api.ops.model_pricing import (
    PLAN_BILLED_TTS_PROVIDERS,
    TTS_PROVIDERS,
    TtsPlanFeeAttestation,
    TtsPriceAttestation,
    attested_tts_plan_fees,
    attested_tts_prices,
)

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin"])
client_router = APIRouter(prefix="/v1/billing/spend", tags=["billing"])

Session = Annotated[AsyncSession, Depends(db)]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py` and this is `spend_routes.py`, which is exactly how `cap_routes.py`,
# `credit_routes.py` and `ai_quota_routes.py` already declare theirs.
#
# The CLIENT reader is realm `any` (the default), like `GET /v1/usage` and
# `GET /v1/billing/invoice` beside it: `billing:read` is not in `MUTATING_PERMISSIONS`, so
# a support person inside a read-only view-as session (D-22) sees exactly the page the
# client is looking at — which is the property `tests/impersonation_reads_test.py` exists
# to keep.
SpendReader = Annotated[Principal, Depends(requires("billing:read"))]
AdminSpendReader = Annotated[Principal, Depends(requires("billing:read", realm="admin"))]

#: How many calls one response may itemise. The rollups above it are always the WHOLE
#: month — an allocation has to see its own denominator — so this bounds the payload and
#: never the arithmetic, and `truncated` says plainly when a month has more.
DEFAULT_CALLS = 50
MAX_CALLS = 500

#: The fleet roll-up's walk budget, and the same trade `admin/health.py::WALK_BUDGET_S`
#: makes: a money board that silently dropped the client at the bottom would be worse
#: than a slow one, so nothing here truncates — it logs and names the remedy.
FLEET_BUDGET_S = 10.0

#: Live clients only, exactly as the health board scopes its walk: an archive of churned
#: tenants must not become a per-open cost on a page an operator refreshes.
_ENDED_STATUSES = ("churned", "suspended")
_DIRECTORY = (
    "SELECT id, name, slug, plan_tier FROM organizations "
    " WHERE deleted_at IS NULL AND status <> ALL(:ended) ORDER BY name"
)

#: ONE TENANT's share of the BYOK synthesizer leg for an IST month.
#:
#: **`unit_type = 'tts_kchars'` IS THE PROVIDER DISCRIMINATOR, and there is no other.**
#: `workers/pipeline.py::_tts_cost_row` writes that unit type on the BYOK branch alone; a
#: Sarvam call's synthesizer cost is the ENGINE's own reported leg figure, on a `tts_chars`
#: row at `qty = 1` — a whole-leg charge carrying no character count at all. So this sum is
#: the plan-billed vendors' attributed cost, and `PLAN_BILLED_TTS_PROVIDERS` names them.
#: `tests/tts_plan_fee_test.py` pins that set at ONE member, because a second plan-billed
#: vendor could not be told from the first by this query — it would need a discriminator on
#: the ledger row first, which is a migration and not a `WHERE` clause.
#:
#: THREE FIGURES, and the third is the one that keeps the second honest. `unit_cost_paid` is
#: NULLable, and `SUM` skips a NULL silently: a month holding an unpriced row would report a
#: smaller attributed total and therefore a LARGER unused allotment, which flatters us. The
#: count is what lets the difference be withheld instead (`TtsPlanSpendOut.unused_inr`).
#:
#: HALF-OPEN on `occurred_at` (`billing/plans.ist_month_window`), never `to_char(... AT TIME
#: ZONE ...)`: that predicate is STABLE rather than IMMUTABLE and cannot be an index qual,
#: so it walks a tenant's whole metering history — the measurement is in that function's
#: own docstring.
_TTS_ATTRIBUTED_SQL = (
    "SELECT COALESCE(SUM(qty * unit_cost_paid), 0), COALESCE(SUM(qty), 0), "
    "count(*) FILTER (WHERE unit_cost_paid IS NULL) "
    "FROM usage_events WHERE tenant_id = :tid AND unit_type = 'tts_kchars' "
    "AND occurred_at >= :start AND occurred_at < :next"
)

#: Characters per unit of `usage_events.qty` on a `tts_kchars` row — the same quantum
#: `workers/pipeline._CHARS_PER_KCHAR` divides by, spelled here because this is the reader
#: that multiplies it back. `billing/models.CLIENT_BILLED_UNIT_TYPES` argues why the unit is
#: a thousand and not one.
_CHARS_PER_KCHAR = Decimal("1000")

#: A whole character. `qty` is `NUMERIC(14,4)` and the writer stores `characters / 1000`, so
#: multiplying back is exact for any integer count and this quantize is a FORMATTER rather
#: than a rounding decision — it turns `12345.0000` into `12345` and nothing else. It is
#: spelled rather than `.normalize()`d because `normalize` renders `10000.0000` as `1E+4`,
#: which is a true decimal and an unreadable one.
#:
#: THE ROUNDING MODE IS STATED AT THE CALL EVEN THOUGH THE ARGUMENT ABOVE SAYS IT CANNOT
#: ROUND. "Exact for any integer count" is a property of today's writer, not of this line,
#: and an unstated mode takes the process-global `decimal` context — which any library in
#: the image may change, at any import, without touching this file. A formatter that
#: silently becomes a rounding decision on somebody else's import is the failure
#: `money_rounding_mode_test` exists to make impossible, so the mode is named rather than
#: inherited.
_WHOLE_CHAR = Decimal("1")


class Strict(BaseModel):
    """`extra="forbid"` — the response model IS the output whitelist (BACKEND-PATTERNS §3)."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------- the CLIENT's half


class AgentChargeOut(Strict):
    """What one agent added to this month's bill. No cost field, and there never is one."""

    #: Null only for calls whose agent row is unreadable, which RLS makes unreachable for
    #: a usage row in the same tenant — it is typed nullable because the join is a LEFT
    #: JOIN and a schema that cannot express a missing row invites a 500 instead of a gap.
    agent_id: str | None
    agent_name: str | None
    calls: int
    minutes: str
    charged_inr: str


class CallChargeOut(Strict):
    """One call, and what it added to this month's bill."""

    call_id: str
    agent_id: str | None
    agent_name: str | None
    #: ISO-8601, or null for a call that never started.
    started_at: str | None
    direction: str | None
    minutes: str
    charged_inr: str


class SpendOut(Strict):
    """GET /v1/billing/spend — this month's bill, itemised by agent and by call."""

    month: str
    #: `wallet_debit` = the rupees this call actually took off your balance.
    #: `allocated` = this call's share of the month's calling charge, by its minutes at
    #: its own voice rung's rate. The screen must say which; they are different claims.
    charge_basis: Literal["wallet_debit", "allocated"]
    calls: int
    minutes_used: str
    #: The monthly fee, published on its own and deliberately not divided across calls: it
    #: buys the account rather than any particular minute.
    retainer_inr: str | None
    #: The month's calling charge at this account's own rate — the SAME figure
    #: `GET /v1/usage` publishes as `overage_cost_inr` on a managed plan, and the list
    #: price times the month's minutes on a prepaid one. The retainer above is not in it.
    period_charge_inr: str
    #: What the rows below add up to, exactly as published.
    itemised_charge_inr: str
    #: `period_charge_inr - itemised_charge_inr`. ₹0.00 on the `allocated` basis; on the
    #: wallet basis it is per-call display rounding plus the documented gap between the
    #: sum of wallet debits and the panel's own month figure.
    itemisation_residual_inr: str
    #: Why the residual is not zero, from a closed vocabulary. Null when it IS zero.
    residual_reason: str | None
    by_agent: list[AgentChargeOut]
    #: The costliest calls first, capped at `limit`.
    top_calls: list[CallChargeOut]
    top_calls_truncated: bool


# ------------------------------------------------------------------ the ADMIN's half


class AgentSpendOut(Strict):
    """One agent: what the client paid, what we paid, and the difference."""

    agent_id: str | None
    agent_name: str | None
    calls: int
    minutes: str
    charged_inr: str
    #: OUR supplier cost. Admin realm only.
    cost_inr: str
    #: `charged_inr - cost_inr` — the CALLING margin. The retainer is not in it (it is
    #: published once, at the top, un-allocated), so this is not the margin card's figure
    #: for a managed client and must not be labelled as if it were.
    margin_inr: str
    #: At least one of this agent's cost rows was priced in a currency the vendor's
    #: payload did not state (OPERATIONS §2 gate 7).
    cost_currency_assumed: bool


class CallSpendOut(Strict):
    """One call, both directions."""

    call_id: str
    agent_id: str | None
    agent_name: str | None
    started_at: str | None
    direction: str | None
    minutes: str
    charged_inr: str
    cost_inr: str
    margin_inr: str
    cost_currency_assumed: bool


class UnitSpendOut(Strict):
    """What one metered unit type contributed to OUR cost.

    `qty` is not money and is not rounded like it — seconds, minutes and character counts
    are published as the ledger holds them.
    """

    unit_type: str
    qty: str
    cost_inr: str


class UnattributedSpendOut(Strict):
    """Cost this month that belongs to no call.

    `number_rental` is the only unit that can land here and nothing writes one: under
    Model B a client rents their number from their own operator, not from us
    (`campaigns/provisioning.py`). Kept because a total that claims to be a partition
    must not silently stop being one if a callless unit is ever metered.
    """

    minutes: str
    cost_inr: str


class AbsorbedAiSpendOut(Strict):
    """The dashboard-AI cost Calevate ABSORBED for this client this month (D-127 G-3).

    Admin realm only, and deliberately SEPARATE from the four margin figures above it. Our
    dashboard-AI cost (the re-summarise, the script draft and the in-app copilot) is metered
    per tenant under `ai_assist_ktok_*` and is NOT billed to the client — so it is not
    revenue, it is not a call cost, and it is not in `cost_inr`/`margin_inr`. Folding it
    into the call margin would add cost with no matching revenue and break the
    `sum(by_unit.cost_inr) == cost_inr` partition the whole page rests on (the exact reason
    `attribution._CALL_ROWS_SQL` filters `_NOT_AI_UNITS`).

    But an operator reading "which client is costing us money" has to be able to see it: a
    client with zero calls and a busy copilot costs us real rupees this money board would
    otherwise report as ₹0.00. So it is published here as its own line, sourced from
    `billing/ai_quota.py::read_ai_quota` — the ONE reader of the AI ledger, not a second
    spelling of its SQL — which is the same computation the client's AI assistance screen
    and the per-tenant ceiling already use.
    """

    #: OUR absorbed cost, exact paise. `read_ai_quota.used_inr` summed from `usage_events`
    #: at the price each assist actually ran at (`record_ai_assist_usage`), so a month during
    #: which `azure_openai_model` was flipped holds both models' rows at their own prices.
    used_inr: str
    #: Distinct AI-assist actions this month — `COUNT(DISTINCT ref)`, one per user action
    #: across every assist surface (copilot, re-summarise, script draft), never per model
    #: turn. The number an operator counts, beside the rupees that actually protect us.
    requests: int


class TenantSpendOut(Strict):
    """GET /v1/admin/tenants/{tenant_id}/spend — one client's month, both directions.

    The four header figures are D-12's margin, in D-12's OWN definitions — the retainer
    plus `calling_revenue_inr` against the sum of `_ROW_COST_SQL`, with `margin_pct` the
    one shared function `margin_for_tenant` and the fleet board both call. They are folded
    out of `period_attribution`'s single scan rather than read from a second
    `margin_for_tenant` call, and that is a partition fix rather than a shortcut: a second
    call is a second statement at a second instant over an append-only table the meter
    writes to all month, so on an open month the header's `cost_inr` could exceed the
    `by_unit` lines beneath it by one completing call — the parts silently not adding up,
    on the page whose whole promise is that they do. Same rows, same expressions, so on a
    month nobody is dialling in this is `margin_for_tenant` to the paisa, which is the
    identity `tests/spend_attribution_test.py` pins.
    """

    month: str
    plan_tier: str
    charge_basis: Literal["wallet_debit", "allocated"]
    calls: int
    minutes_used: str
    retainer_inr: str | None
    #: The retainer plus this month's calling charge — `margin_for_tenant`'s own two
    #: halves, which is why `retainer_inr + period_charge_inr == revenue_inr` exactly.
    revenue_inr: str
    cost_inr: str
    margin_inr: str
    #: Null rather than "0.0" when nothing has been billed: "0% margin" and "nothing
    #: billed yet" are different facts.
    margin_pct: str | None
    #: The client's own itemisation anchor, so an operator reading this page and a client
    #: reading theirs are looking at the same rupees.
    period_charge_inr: str
    itemised_charge_inr: str
    itemisation_residual_inr: str
    residual_reason: str | None
    #: THE HONESTY ABOUT OUR COST (OPERATIONS §2 gate 7). `cost_currency_stated` is False
    #: whenever any row recorded that WE chose the currency rather than the vendor naming
    #: it — which is every row today, because the vendor's execution object declares no
    #: currency at all. Every cost figure on this page is scaled by that assumption; no
    #: client-facing figure is, because a client is priced off minutes at their own rate.
    cost_currency: str | None
    cost_currency_stated: bool
    #: Absent on every month that has no callless cost row.
    unattributed: UnattributedSpendOut | None
    #: OUR absorbed dashboard-AI cost (D-127 G-3), published on its own and NOT in the
    #: margin above. Null when this client generated no AI-assist usage this month — "they
    #: ran the copilot and it cost us ₹X" and "they never opened it" are different facts an
    #: operator acts on differently. See `AbsorbedAiSpendOut`.
    ai_assist: AbsorbedAiSpendOut | None
    by_unit: list[UnitSpendOut]
    by_agent: list[AgentSpendOut]
    top_calls: list[CallSpendOut]
    top_calls_truncated: bool


class FleetTenantOut(Strict):
    """One client on the fleet board."""

    tenant_id: str
    name: str
    slug: str
    plan_tier: str
    minutes_used: str
    calls: int
    revenue_inr: str
    cost_inr: str
    margin_inr: str
    margin_pct: str | None


class TtsPlanSpendOut(Strict):
    """ONE voice vendor's month: what the plan cost us, against what our meter attributed.

    THE TWO FIGURES ARE INDEPENDENT MEASUREMENTS AND THE CARD EXISTS TO KEEP THEM APART.
    `plan_inr` is what the VENDOR billed — a committed monthly spend for a character
    allotment, paid whether or not the allotment is spoken, read off the invoice by an
    operator (`ops/model_pricing.TtsPlanFeeAttestation`). `attributed_inr` is what OUR
    meter charged to calls: the attested per-character rate times the characters our own
    transcripts say the agents spoke. A board showing only the first could not say which
    client caused it; one showing only the second under-states what we pay.

    ⚠ **UNKNOWN: whether the vendor's own character count agrees with ours** (OPERATIONS §2
    gate 51). `chars` is counted from our transcripts and from nothing the vendor says.
    This card publishes both sides and reconciles neither.

    ⚠ **UNKNOWN: the vendor's OVERAGE rate past the allotment** (plan ADDENDUM 1, unknown
    #3). `inr_per_1k_chars` prices characters INSIDE the allotment, so a month that ran
    past it cost more per character than that figure says. `plan_inr` is unaffected — it is
    what the invoice states, overage included.

    A MONTH NOBODY HAS ATTESTED HAS NO ROW HERE AT ALL. `plan_inr` is required precisely so
    that absence cannot be spelled as ₹0, which would read as "the vendor billed us
    nothing" — the one misreading of a missing invoice that flatters us.
    """

    #: THE VENDOR'S OWN NAME. This is the admin console and the invoice has a vendor on it;
    #: every client-facing surface gets `tier_label` instead.
    provider: str
    #: What a CLIENT calls the same tier — `billing/rates.voice_tier_label`, crossing the
    #: wire rather than being typed in the browser.
    tier_label: str
    #: The IST billing month, `YYYY-MM`.
    month: str
    #: What the vendor billed for this month, rupees. Never null: the row exists because an
    #: operator attested this figure.
    plan_inr: str
    #: What this month's calls attributed to this vendor's synthesizer leg, rupees.
    attributed_inr: str
    #: `plan_inr - attributed_inr`, the allotment nobody spoke into — THE SERVER's
    #: subtraction (D-458), because a difference worked out in a browser is float
    #: arithmetic on money. MAY BE NEGATIVE: a month that attributed more than the plan
    #: charged is what an overage looks like from our side of the meter, and clamping it at
    #: zero would hide the one state that matters most.
    #:
    #: `null` when the month's attributed total is INCOMPLETE — at least one `tts_kchars`
    #: row carries no `unit_cost_paid`, so the sum omits real characters and the difference
    #: would overstate the unused allotment, in the flattering direction. `attributed_inr`
    #: still reports what WAS attributed, which stays a true statement about those rows.
    unused_inr: str | None
    #: Characters this vendor's voices spoke across the fleet this month, from OUR
    #: transcripts. An exact decimal string like every other figure here, because it is the
    #: quantity `inr_per_1k_chars` is multiplied by.
    chars: str
    #: The attested ₹/1,000 characters those characters were metered at, resolved at the
    #: month's own pricing instant (`billing/plans.month_pricing_instant`) so a closed month
    #: reports the rate it was struck at rather than today's. `null` when nothing is
    #: attested — which is a real state, distinct from a zero, and one in which
    #: `attributed_inr` is ₹0 because the pipeline writes no cost row it cannot price.
    inr_per_1k_chars: str | None


class FleetSpendOut(Strict):
    """GET /v1/admin/spend — every live client's month, worst margin first.

    The totals are sums of the rows, computed here rather than queried: `usage_events` is
    FORCE RLS'd and an untenanted session sees zero rows by design, so a cross-tenant
    `SUM` is unaskable in app code and reaching for the admin DB role to get one would
    break hard rule 1. `billing/models.PlatformAiSpend` records the same constraint and
    the same answer one ledger over. Each client's numbers are read INSIDE that client's
    own `tenant_session`, so no query here sees two tenants at once.
    """

    month: str
    clients: int
    revenue_inr: str
    cost_inr: str
    margin_inr: str
    margin_pct: str | None
    tenants: list[FleetTenantOut]
    #: WHAT THE VOICE VENDORS BILLED, beside what this board attributed (D-547 Phase D.3).
    #: One row per plan-billed vendor with an attested fee for the month, in vendor order;
    #: an empty list means nobody has attested one, which the console renders as a stated
    #: absence rather than as ₹0. Bounded by `PLAN_BILLED_TTS_PROVIDERS`, a two-element
    #: vocabulary's plan-billed subset, so it does not grow with anybody's row count.
    tts_plan: list[TtsPlanSpendOut]


class SpeakingRatePointOut(Strict):
    """A chars-per-call-minute figure and the TTS ₹/min it implies at the live rate card.

    Both are exact decimal STRINGS — a speaking rate is priced by multiplying it, so it is
    money's shadow and crosses the wire the way money does (hard rule 7).
    """

    chars_per_minute: str
    tts_inr_per_minute: str


class SpeakingRateByProviderOut(Strict):
    """What the measured speaking rate means for ONE voice vendor (D-547).

    The board's other TTS figures are struck at the SARVAM rate card, which is the only
    price this product had when they were written. With two vendors that is no longer one
    number: the same 450 chars/minute costs what each vendor charges for 450 characters,
    and only one of the two has a price this platform can bill from without an attestation.

    `pooled_inr_per_minute` is the SERVER's multiplication — chars per minute, times the
    rate, over 1,000 — because a browser multiplying two decimal strings is float
    arithmetic on money (hard rule 7), and its answer would be a third figure disagreeing
    with the meter's.
    `null` when there is no attested rate to multiply by, or no pooled measurement to
    multiply: two different absences, both reported as no number rather than as a zero.
    """

    #: The VENDOR's own name — this is the admin console and the invoice has a vendor on it.
    provider: str
    #: What a CLIENT calls the same tier, from `billing/rates.voice_tier_label`.
    tier_label: str
    #: Has an operator attested a ₹/1,000-character price for this vendor? For Sarvam the
    #: answer is normally False and nothing is wrong: the engine bills that leg and reports
    #: what it charged, so there is no invoice of ours to divide (`tts_price_is_billable`).
    price_attested: bool
    inr_per_1k_chars: str | None
    pooled_inr_per_minute: str | None


class TtsSpeakingRateOut(Strict):
    """GET /v1/admin/spend/tts-speaking-rate — pilot gate 12's number, or the refusal.

    `measured` is the field to read first. When it is False the three rate fields are
    null, `reason` says how many calls there are and how many are needed, and the assumed
    band is the figure still in force. A screen that printed the band as if it were the
    measurement — or printed a placeholder rate — would be the hard-rule-11 failure the
    threshold exists to prevent; there is no number here to print in that state.
    """

    measured: bool
    calls: int
    clients: int
    minimum_calls: int
    reason: str | None
    p50: SpeakingRatePointOut | None
    p95: SpeakingRatePointOut | None
    pooled: SpeakingRatePointOut | None
    assumed_low: SpeakingRatePointOut
    assumed_high: SpeakingRatePointOut
    tts_inr_per_10k_chars: str
    #: THE SAME MEASUREMENT, PRICED PER VENDOR (D-547). One row per voice provider, always
    #: both, because the tier nobody has priced is the row an operator opened this card for.
    #: The fields above are the Sarvam-rate-card view they have always been.
    by_provider: list[SpeakingRateByProviderOut]


# ------------------------------------------------------------------------ rendering
#
# `str(Decimal)` and nothing else: no formatting, no locale, no rounding. Every figure
# reaching here has already been quantized by `billing/service.to_paise` or allocated by
# `allocate_paise`, and re-rounding at the boundary is how two surfaces publish two
# spellings of one rupee (D-375).


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _agent_charge(agent: AgentAttribution) -> AgentChargeOut:
    return AgentChargeOut(
        agent_id=str(agent.agent_id) if agent.agent_id else None,
        agent_name=agent.agent_name,
        calls=agent.calls,
        minutes=str(agent.minutes),
        charged_inr=str(agent.charged_inr),
    )


def _call_charge(call: CallAttribution) -> CallChargeOut:
    return CallChargeOut(
        call_id=str(call.call_id),
        agent_id=str(call.agent_id) if call.agent_id else None,
        agent_name=call.agent_name,
        started_at=call.started_at.isoformat() if call.started_at else None,
        direction=call.direction,
        minutes=str(call.minutes),
        charged_inr=str(call.charged_inr),
    )


def _agent_spend(agent: AgentAttribution) -> AgentSpendOut:
    return AgentSpendOut(
        agent_id=str(agent.agent_id) if agent.agent_id else None,
        agent_name=agent.agent_name,
        calls=agent.calls,
        minutes=str(agent.minutes),
        charged_inr=str(agent.charged_inr),
        cost_inr=str(agent.cost_inr),
        margin_inr=str(agent.charged_inr - agent.cost_inr),
        cost_currency_assumed=agent.cost_currency_assumed,
    )


def _call_spend(call: CallAttribution) -> CallSpendOut:
    return CallSpendOut(
        call_id=str(call.call_id),
        agent_id=str(call.agent_id) if call.agent_id else None,
        agent_name=call.agent_name,
        started_at=call.started_at.isoformat() if call.started_at else None,
        direction=call.direction,
        minutes=str(call.minutes),
        charged_inr=str(call.charged_inr),
        cost_inr=str(call.cost_inr),
        margin_inr=str(call.charged_inr - call.cost_inr),
        cost_currency_assumed=call.cost_currency_assumed,
    )


def _by_charge(period: PeriodAttribution) -> list[CallAttribution]:
    """The client's ordering: what drove MY bill. Ties by cost, then by id — never by
    dict order, so two renders of one closed month list the same calls in the same
    places."""
    return sorted(period.by_call, key=lambda c: (-c.charged_inr, -c.cost_inr, str(c.call_id)))


def _by_cost(period: PeriodAttribution) -> list[CallAttribution]:
    """The operator's ordering: what cost US the most."""
    return sorted(period.by_call, key=lambda c: (-c.cost_inr, -c.charged_inr, str(c.call_id)))


# -------------------------------------------------------------------------- routes


@client_router.get(
    "",
    response_model=SpendOut,
    openapi_extra=permission_meta("billing:read"),
    summary="This month's bill, itemised by agent and by call",
    description=(
        "Every rupee on this account's calling charge, attributed to the agent and the "
        "call that produced it. `charge_basis` says what kind of number the per-call "
        "figure is: `wallet_debit` is the exact amount taken off a prepaid balance for "
        "that call, `allocated` is that call's share of a month priced as a whole. "
        "Requires `billing:read`, which account owners hold and staff do not. Calevate's "
        "own supplier cost never appears here."
    ),
)
async def my_spend(
    session: Session,
    principal: SpendReader,
    month: str | None = None,
    limit: int = Query(DEFAULT_CALLS, ge=1, le=MAX_CALLS),
) -> SpendOut:
    """The tenant comes from the PRINCIPAL — there is no id to tamper with, and `session`
    is RLS-scoped to that principal's own tenant, so another account's month is not
    merely forbidden but unaddressable (hard rule 1)."""
    assert principal.tenant_id is not None
    period = await period_attribution(session, tenant_id=principal.tenant_id, month=month)
    ranked = _by_charge(period)
    return SpendOut(
        month=period.month,
        charge_basis=period.charge_basis,
        calls=period.calls,
        minutes_used=str(period.minutes),
        retainer_inr=_money(period.retainer_inr),
        period_charge_inr=str(period.period_charge_inr),
        itemised_charge_inr=str(period.itemised_charge_inr),
        itemisation_residual_inr=str(period.itemisation_residual_inr),
        residual_reason=period.residual_reason,
        by_agent=[_agent_charge(a) for a in period.by_agent],
        top_calls=[_call_charge(c) for c in ranked[:limit]],
        top_calls_truncated=len(ranked) > limit,
    )


@router.get(
    "/tenants/{tenant_id}/spend",
    response_model=TenantSpendOut,
    openapi_extra=permission_meta("billing:read"),
    summary="One client's month, both directions — what we paid, what we charged, margin",
)
async def tenant_spend(
    tenant_id: UUID,
    session: AdminSession,
    principal: AdminSpendReader,
    request: Request,
    month: str | None = None,
    limit: int = Query(DEFAULT_CALLS, ge=1, le=MAX_CALLS),
) -> TenantSpendOut:
    """Admin realm only, for the reason `tenant_margin` is: `unit_cost_paid` is our
    supplier pricing.

    Runs the reads inside the client's own `tenant_session` because `usage_events`,
    `calls` and `agents` are RLS'd and stay that way — `app.admin` opens the client
    DIRECTORY, never their data (migration b57e2f9c4a13). The existence check comes first
    for the reason it does on the margin card: a mistyped id and a client with no usage
    both aggregate to zero, and a ₹0 page about a client that does not exist is worse
    than a 404.

    ONE ATTRIBUTION, and the margin is folded out of it — see `TenantSpendOut` for why a
    second `margin_for_tenant` read would let this page's header disagree with its own
    lines. It also removes the whole question of the two reads landing either side of a
    month boundary, which is what `month=period.month` used to have to defend against.
    """
    if not await admin_service.tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Client")
    async with tenant_session(tenant_id) as scoped:
        period = await period_attribution(scoped, tenant_id=tenant_id, month=month)
        # OUR absorbed dashboard-AI cost, read in the SAME scope and for the SAME resolved
        # month (`period.month`, already validated by the attribution above), through the
        # one reader of the AI ledger. It is `_NOT_AI_UNITS`-excluded from `period` by
        # design — see `AbsorbedAiSpendOut` — so this is where the copilot spend a client
        # generated becomes visible on the money board an operator opens.
        ai = await read_ai_quota(scoped, tenant_id=tenant_id, month=period.month)
        # D-482 L-1: a direct-admin read of one client's money board joins the audit
        # trail, coalesced per (admin, tenant) per minute.
        await record_admin_tenant_read(
            scoped, request=request, principal=principal, tenant_id=tenant_id
        )
    margin = _margin_of(period)
    ranked = _by_cost(period)
    return TenantSpendOut(
        month=period.month,
        plan_tier=period.plan_tier,
        charge_basis=period.charge_basis,
        calls=period.calls,
        minutes_used=str(period.minutes),
        retainer_inr=_money(period.retainer_inr),
        revenue_inr=str(margin.revenue_inr),
        cost_inr=str(margin.cost_inr),
        margin_inr=str(margin.margin_inr),
        margin_pct=_money(margin.margin_pct),
        period_charge_inr=str(period.period_charge_inr),
        itemised_charge_inr=str(period.itemised_charge_inr),
        itemisation_residual_inr=str(period.itemisation_residual_inr),
        residual_reason=period.residual_reason,
        cost_currency=period.cost_currency,
        cost_currency_stated=period.cost_currency_stated,
        unattributed=(
            None
            if period.unattributed is None
            else UnattributedSpendOut(
                minutes=str(period.unattributed.minutes),
                cost_inr=str(period.unattributed.cost_inr),
            )
        ),
        # Published only when there is something to show: `requests_used` is the
        # `COUNT(DISTINCT ref)` over the AI unit types, so > 0 means this client actually
        # ran an assist this month. `used_inr` goes through `to_paise` like every other
        # rupee on this response.
        ai_assist=(
            AbsorbedAiSpendOut(used_inr=str(to_paise(ai.used_inr)), requests=ai.requests_used)
            if ai.requests_used > 0
            else None
        ),
        by_unit=[
            UnitSpendOut(unit_type=u.unit_type, qty=str(u.qty), cost_inr=str(u.cost_inr))
            for u in period.by_unit
        ],
        by_agent=[_agent_spend(a) for a in period.by_agent],
        top_calls=[_call_spend(c) for c in ranked[:limit]],
        top_calls_truncated=len(ranked) > limit,
    )


@dataclass(frozen=True, slots=True)
class _Margin:
    """D-12's margin for one attributed month. Derived, never separately queried."""

    revenue_inr: Decimal
    cost_inr: Decimal
    margin_inr: Decimal
    margin_pct: Decimal | None


def _margin_of(period: PeriodAttribution) -> _Margin:
    """`margin_for_tenant`'s arithmetic over the attribution's own single scan.

    Revenue is the retainer plus the month's calling charge, which is exactly the pair
    `margin_for_tenant` adds — `period_charge_inr` IS `calling_revenue_inr` for the month
    (`billing/attribution.py`), and the retainer is `usage_summary.monthly_fee_inr`, the
    same field. Cost is the sum of `_ROW_COST_SQL` the breakdown beneath it partitions.
    `margin_pct` is the one shared function, never a second copy of the no-revenue rule.

    Both addends are already paise-exact, so `to_paise` here rounds nothing that was not
    rounded the same way one function over; it is spelled anyway because every money field
    in every billing response goes through it and a field that skipped it would be the one
    that renders four decimals.
    """
    revenue = (period.retainer_inr or Decimal("0.00")) + period.period_charge_inr
    margin = to_paise(revenue - period.cost_inr)
    return _Margin(
        revenue_inr=to_paise(revenue),
        cost_inr=period.cost_inr,
        margin_inr=margin,
        margin_pct=billing.margin_pct(margin_inr=margin, revenue_inr=revenue),
    )


@dataclass(frozen=True, slots=True)
class _TtsAttribution:
    """The fleet's BYOK synthesizer leg for one month, accumulated across the walk.

    Summed per tenant inside that tenant's own `tenant_session` and added up here, for
    `FleetSpendOut`'s stated reason: `usage_events` is FORCE RLS'd, an untenanted `SUM`
    over it returns zero rows and reports success, and reaching for the admin DB role to
    get a cross-tenant total would break hard rule 1.
    """

    inr: Decimal
    #: Characters, already multiplied back out of `qty`'s thousands.
    chars: Decimal
    #: How many rows in the window carried no `unit_cost_paid`. Non-zero means `inr` is
    #: INCOMPLETE — see `_tts_plan_rows`, which withholds the difference rather than
    #: publishing one that overstates the unused allotment.
    unpriced_rows: int

    def plus(self, inr: Decimal, chars: Decimal, unpriced_rows: int) -> _TtsAttribution:
        return _TtsAttribution(
            inr=self.inr + inr,
            chars=self.chars + chars,
            unpriced_rows=self.unpriced_rows + unpriced_rows,
        )


_NO_TTS_ATTRIBUTION = _TtsAttribution(inr=Decimal("0.00"), chars=Decimal(0), unpriced_rows=0)


def _tts_plan_rows(
    *,
    month: str,
    fees: Mapping[str, TtsPlanFeeAttestation],
    prices: Mapping[str, TtsPriceAttestation],
    attributed: _TtsAttribution,
) -> list[TtsPlanSpendOut]:
    """One row per plan-billed vendor that HAS an attested fee for `month`. No others.

    THE ABSENCE IS THE POINT. A vendor with no attestation for this month produces no row,
    so the console renders a stated absence; a row carrying ₹0 would say the vendor billed
    us nothing, which is a lie in the direction that flatters us. Sarvam produces no row
    ever, and not because it is unattested: the engine buys that synthesis and reports what
    it charged on every call, so there is no monthly invoice of ours to attest and no
    `tts_kchars` character count of ours to compare one against.
    """
    rows: list[TtsPlanSpendOut] = []
    for provider in sorted(PLAN_BILLED_TTS_PROVIDERS):
        fee = fees.get(provider)
        if fee is None:
            continue
        price = prices.get(provider)
        rows.append(
            TtsPlanSpendOut(
                provider=provider,
                tier_label=rates.voice_tier_label(cast("rates.VoiceTier", provider)),
                month=month,
                plan_inr=str(to_paise(fee.plan_inr)),
                attributed_inr=str(to_paise(attributed.inr)),
                # Withheld, not zeroed, when the sum above is known to have skipped priced
                # characters — `_TTS_ATTRIBUTED_SQL`'s third figure is exactly this test.
                unused_inr=(
                    None
                    if attributed.unpriced_rows
                    else str(to_paise(fee.unused_inr(to_paise(attributed.inr))))
                ),
                chars=str(attributed.chars.quantize(_WHOLE_CHAR, rounding=rates.ROUNDING)),
                inr_per_1k_chars=None if price is None else str(price.inr_per_1k_chars),
            )
        )
    return rows


@dataclass(frozen=True, slots=True)
class _FleetRow:
    """One walked client, before it is stringified."""

    tenant_id: UUID
    name: str
    slug: str
    plan_tier: str
    margin: dict[str, object]


@router.get(
    "/spend",
    response_model=FleetSpendOut,
    openapi_extra=permission_meta("billing:read"),
    summary="Every live client's month — revenue, our cost, margin — worst margin first",
)
async def fleet_spend(
    directory: AdminSession,
    _: AdminSpendReader,
    month: str | None = None,
) -> FleetSpendOut:
    """The board that answers "which client is costing us money", one row per client.

    ONE directory query, then ONE `tenant_session` per client, exactly as
    `admin/health.py::client_health` does — the directory comes from the `app.admin`
    session (which widens `organizations` and nothing else) and every rupee is read under
    ordinary RLS inside the client's own scope. Nothing here can see two tenants at once
    and no policy is widened to make it faster.

    Nothing truncates, for the reason the health board does not: hiding the client at the
    bottom of a money board defeats the board. The walk is watched instead.
    """
    started = perf_counter()
    rows = (await directory.execute(text(_DIRECTORY), {"ended": list(_ENDED_STATUSES)})).all()
    # ONE month for the whole walk. `margin_for_tenant` resolves `None` to "now" per call,
    # and a walk that straddles midnight IST on the 1st would otherwise put some clients
    # in August and the rest in September on one board.
    period = month or billing.current_billing_month()
    # The voice vendors' side of the month, read ONCE before the walk: both are PLATFORM
    # tables with no tenancy, and reading them inside the per-tenant loop would be a query
    # per client for an answer that does not vary by client (`fleet_tts_speaking_rate`
    # makes the same trade for the same reason).
    #
    # TWO DIFFERENT INSTANTS, deliberately. The FEE resolves at NOW, because an invoice
    # arrives after its month has closed and resolving it at the month's own last instant
    # would make every attestation about a closed month invisible. The PRICE resolves at
    # the month's own pricing instant, because that is when the characters were metered —
    # a closed month must report the rate it was struck at, not today's.
    window_start, window_next = ist_month_window(period)
    fees = await attested_tts_plan_fees(directory, month=period, at=datetime.now(UTC))
    tts_prices = await attested_tts_prices(directory, at=month_pricing_instant(period))

    walked: list[_FleetRow] = []
    attributed = _NO_TTS_ATTRIBUTION
    for org in rows:
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            margin = await billing.margin_for_tenant(scoped, tenant_id=tenant_id, month=period)
            # Inside the client's own scope, like every other rupee on this board.
            tts = (
                await scoped.execute(
                    text(_TTS_ATTRIBUTED_SQL),
                    {"tid": tenant_id, "start": window_start, "next": window_next},
                )
            ).one()
        attributed = attributed.plus(_dec(tts[0]), _dec(tts[1]) * _CHARS_PER_KCHAR, int(tts[2]))
        walked.append(
            _FleetRow(
                tenant_id=tenant_id,
                name=str(org[1]),
                slug=str(org[2]),
                plan_tier=str(org[3]),
                margin=margin,
            )
        )

    elapsed = perf_counter() - started
    if elapsed > FLEET_BUDGET_S:
        # Counts and seconds only, never a client name (the same log discipline
        # `client_health_walk_over_budget` keeps), and the remedy on the line.
        log.warning(
            "fleet_spend_walk_over_budget",
            extra={
                "clients": len(walked),
                "elapsed_s": round(elapsed, 2),
                "budget_s": FLEET_BUDGET_S,
                "remedy": "the client list has outgrown the per-tenant margin walk — "
                "materialize the monthly rollup (billing/spend_routes.py)",
            },
        )

    revenue = sum((_dec(r.margin["revenue_inr"]) for r in walked), Decimal("0.00"))
    cost = sum((_dec(r.margin["cost_inr"]) for r in walked), Decimal("0.00"))
    total_margin = revenue - cost
    return FleetSpendOut(
        month=period,
        clients=len(walked),
        revenue_inr=str(revenue),
        cost_inr=str(cost),
        margin_inr=str(total_margin),
        # Suppressed rather than zeroed when nothing has been billed across the fleet,
        # through the SAME function `margin_for_tenant` uses per client rather than a
        # second copy of the rule (`billing.service.margin_pct`).
        margin_pct=_money(billing.margin_pct(margin_inr=total_margin, revenue_inr=revenue)),
        tenants=[
            FleetTenantOut(
                tenant_id=str(r.tenant_id),
                name=r.name,
                slug=r.slug,
                plan_tier=r.plan_tier,
                minutes_used=str(r.margin["minutes_used"]),
                calls=int(str(r.margin["calls"])),
                revenue_inr=str(r.margin["revenue_inr"]),
                cost_inr=str(r.margin["cost_inr"]),
                margin_inr=str(r.margin["margin_inr"]),
                margin_pct=_money(_opt_dec(r.margin["margin_pct"])),
            )
            # Worst first: the client we are losing the most on is the one an operator
            # opened this page for. Ties by name so the order is stable between renders.
            for r in sorted(walked, key=lambda r: (_dec(r.margin["margin_inr"]), r.name))
        ],
        tts_plan=_tts_plan_rows(month=period, fees=fees, prices=tts_prices, attributed=attributed),
    )


@router.get(
    "/spend/tts-speaking-rate",
    response_model=TtsSpeakingRateOut,
    openapi_extra=permission_meta("billing:read"),
    summary="How many TTS characters a call-minute really costs — measured from transcripts",
)
async def fleet_tts_speaking_rate(
    directory: AdminSession, _: AdminSpendReader
) -> TtsSpeakingRateOut:
    """TRD §10.1's "360-540 chars per call-minute" assumption, replaced by a reading.

    The SAME walk as `fleet_spend` and for the same reason: `transcript_turns` and `calls`
    are FORCE-RLS'd, an untenanted read of either returns zero rows and reports success,
    so the directory comes from the `app.admin` session and every call is sampled inside
    its own client's `tenant_session`. The samples are pooled in memory and summarised
    once (`tts_speaking_rate.summarize`), which is the only place two tenants' figures
    meet — as integers, after every row has been read under its own policy.

    Below `TTS_SPEAKING_RATE_MIN_CALLS` the response says so and carries no rate.
    """
    started = perf_counter()
    # The attested voice prices, read ONCE before the walk: it is a platform table with no
    # tenancy, and reading it inside the per-tenant loop would be one query per client for
    # an answer that does not vary by client.
    attested = await attested_tts_prices(directory, at=datetime.now(UTC))
    rows = (await directory.execute(text(_DIRECTORY), {"ended": list(_ENDED_STATUSES)})).all()
    samples: list[tts_speaking_rate.CallSample] = []
    for org in rows:
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            samples.extend(await tts_speaking_rate.sample_tenant(scoped, tenant_id=tenant_id))

    elapsed = perf_counter() - started
    if elapsed > FLEET_BUDGET_S:
        log.warning(
            "tts_speaking_rate_walk_over_budget",
            extra={
                "clients": len(rows),
                "calls": len(samples),
                "elapsed_s": round(elapsed, 2),
                "budget_s": FLEET_BUDGET_S,
                "remedy": "the transcript archive has outgrown the per-tenant walk — "
                "sample a window of recent calls per client (billing/tts_speaking_rate.py)",
            },
        )

    return _speaking_rate_out(tts_speaking_rate.summarize(samples), attested=attested)


def _point_out(point: tts_speaking_rate.SpeakingRatePoint) -> SpeakingRatePointOut:
    return SpeakingRatePointOut(
        chars_per_minute=str(point.chars_per_minute),
        tts_inr_per_minute=str(point.tts_inr_per_minute),
    )


def _by_provider_out(
    rate: tts_speaking_rate.TtsSpeakingRate, *, attested: Mapping[str, TtsPriceAttestation]
) -> list[SpeakingRateByProviderOut]:
    """Both vendors, each priced at its OWN attested rate — or at nothing, stated.

    `inr_for_chars` is the attestation's own multiplication (`ops/model_pricing
    .TtsPriceAttestation`), so the ₹/minute here, the ₹ the pipeline meters a call at and
    the margin panel's cost all come out of one function rather than three divisions by
    1,000.
    """
    per_minute = None if rate.pooled is None else rate.pooled.chars_per_minute
    return [
        SpeakingRateByProviderOut(
            provider=provider,
            tier_label=rates.voice_tier_label(cast("rates.VoiceTier", provider)),
            price_attested=price is not None,
            inr_per_1k_chars=None if price is None else str(price.inr_per_1k_chars),
            pooled_inr_per_minute=(
                None
                if price is None or per_minute is None
                else str(price.inr_for_chars(per_minute))
            ),
        )
        for provider in TTS_PROVIDERS
        # Walrus in the comprehension so the price is fetched once per row and the three
        # branches above read the same object.
        for price in (attested.get(provider),)
    ]


def _speaking_rate_out(
    rate: tts_speaking_rate.TtsSpeakingRate, *, attested: Mapping[str, TtsPriceAttestation]
) -> TtsSpeakingRateOut:
    return TtsSpeakingRateOut(
        measured=rate.measured,
        calls=rate.calls,
        clients=rate.clients,
        minimum_calls=rate.minimum_calls,
        reason=rate.reason,
        p50=None if rate.p50 is None else _point_out(rate.p50),
        p95=None if rate.p95 is None else _point_out(rate.p95),
        pooled=None if rate.pooled is None else _point_out(rate.pooled),
        assumed_low=_point_out(rate.assumed_low),
        assumed_high=_point_out(rate.assumed_high),
        tts_inr_per_10k_chars=str(rates.TTS_INR_PER_10K_CHARS),
        by_provider=_by_provider_out(rate, attested=attested),
    )


def _dec(value: object) -> Decimal:
    """A money field off `margin_for_tenant`, which types its dict `Any`.

    `Decimal(str(...))` and never `Decimal(float)`: hard rule 7 is not only about the
    database, and a float that reaches here would round a fleet total.
    """
    return Decimal(str(value))


def _opt_dec(value: object) -> Decimal | None:
    return None if value is None else _dec(value)


__all__ = ["client_router", "router"]
