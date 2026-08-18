"""The client health overview: which account is about to churn or break, this week.

    GET /v1/admin/client-health

`apps/api/admin/health.py` argues the whole design — which five signals earned a place,
which candidates were rejected and why, why the call trend carries a `basis` rather than
a bare ratio, and why the cross-tenant read widens no RLS policy. This module is the
surface only.

**`org:read`, not `admin:tenants`**, for the reason `holds_routes.py` states: D-22
forbids gating a GET on a permission read-only impersonation refuses, and `admin:tenants`
is in `MUTATING_PERMISSIONS`. Reading a triage list is not acting on it — every remedy an
operator reaches FROM this board (record a KYC verification, release a first campaign,
raise a cap, approve a knowledge source) keeps its own mutating permission and its own
audit row. `tests/impersonation_reads_test.py` asserts that rule over the whole route
table; the exemption list it carries for the older `/v1/admin/tenants` GETs is a debt, not
a pattern to inherit.

**`realm="admin"` is what separates the realms**, never the permission — client roles hold
`org:read` too. The dependency resolves against `admin_users`, so a client token cannot
reach this route whatever its role, and there is no client-realm twin: a client has no
business reading a list that names other businesses.

**No audit row.** The board discloses no personal data and it is a page an operator leaves
open and refreshes; an audit chain that grows a row per poll stops being readable (the
argument `kyc_routes.py` makes for the client's own screen, and `holds_routes.py` for the
work list). Every ACTION taken from it writes its own entry.

**Money is a STRING on the wire, AND IT IS QUANTIZED TO PAISE FIRST.** `spend_used_inr`
and `spend_cap_inr` are `Decimal` through billing (hard rule 7) and are stringified here,
for the reason `UsagePanelOut` states: a JSON float cannot hold a rupee amount exactly,
and `Number()` on INR is how ₹10,159.00 becomes ₹10,158.999999999998.

The QUANTIZATION is the second half and it was missing — this screen stringified
`spend_state.billed_inr` at its NUMERIC(12,4) storage precision, and `apps/web`'s
`formatINR` truncates where `billing.service.to_paise` rounds half-up. See `_out` for the
measurement; it is the same defect D-375 fixed on the client's own wallet, on the
operator's screen, and `billing/cap_routes.py` already had it right.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.health import CallBasis, ClientHealth, HealthSignal, Severity, client_health
from apps.api.billing.service import to_paise
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/admin/client-health", tags=["admin"])

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is `health_routes.py` — same situation and the same
# resolution as `holds_routes.py`.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
BoardReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]


class HealthSignalOut(BaseModel):
    """One thing wrong with one account, in machine names only."""

    model_config = ConfigDict(extra="forbid")

    # `calls_stopped` | `outbound_blocked` | `spend_cap_near` | `deliveries_failing` |
    # `knowledge_waiting` | `calls_unmetered`. A bare `str` rather than a Literal, for the reason
    # `HeldTenantOut.holds` is: the set grows whenever a signal does, and a generated
    # client that had to be regenerated before it could DISPLAY a new signal would drop
    # the row instead. The console fails visible on a name it does not know.
    rule: str
    # `stop` = broken now; `warn` = will break. The board's whole ordering rests on this
    # distinction, so it is the server's answer and never the console's arithmetic.
    severity: Severity
    # For `outbound_blocked`: the GATES' own rule names, in the order the launch preview
    # asks them (`kyc_missing`, `first_campaign_review_pending`, `pe_registration_*`,
    # `tm_link_not_active`, `spend_cap`, `no_credits`) — the same vocabulary the client's
    # screen uses, so an operator and a client on the phone name one condition the same
    # way. Deliberately NOT the blockers' `reason` prose: a rejection reason interpolates
    # an operator's free text (hard rule 6, `admin/holds.py`).
    causes: list[str] = []
    # The number behind a countable signal, or None where the signal is a state. None and
    # 0 are different claims and the screen keeps them apart.
    count: int | None = None


class ClientHealthOut(BaseModel):
    """One line of the board. Accounts and their state — never a person, never a number
    anyone could be dialled on."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str
    slug: str
    plan_tier: str
    status: str
    # The worst severity among `signals` — computed server-side so two screens cannot
    # disagree about how bad an account is.
    severity: Severity
    signals: list[HealthSignalOut]
    calls_7d: int
    calls_prev_7d: int
    # WHICH claim the two counts above support. `measured` = the comparison is entitled
    # to be made; `too_new` = the account is younger than the comparison window;
    # `no_baseline` = it traded, below the floor a ratio needs. This is the
    # `after_hours_basis` precedent applied to an ACCUSATION rather than a tile: a
    # console that rendered a trend identically from all three would send an operator to
    # ask a four-day-old account why its calls stopped.
    calls_basis: CallBasis
    last_call_at: datetime | None
    # Money as STRING (hard rule 7 at the boundary — see the module docstring).
    #
    # `spend_cap_inr` is the RUPEE ceiling in force, and None means there is no rupee
    # ceiling — which is a real and common state (a tenant with no plan row is
    # unconstrained, not capped at zero) and is NOT the same as "nothing constrains this
    # account": `billing/caps.py` has two independent ceilings, and a MINUTE cap can be
    # about to bite while this is null. That is why `spend_cap_near` carries its own
    # percentage (the nearer of the two) instead of the screen dividing these two fields:
    # a console that computed the ratio itself would report the wrong ceiling for every
    # minute-capped client, and would do it by parsing a rupee string into a float.
    spend_used_inr: str
    spend_cap_inr: str | None


def _signal(signal: HealthSignal) -> HealthSignalOut:
    return HealthSignalOut(
        rule=signal.rule,
        severity=signal.severity,
        causes=list(signal.causes),
        count=signal.count,
    )


def _out(row: ClientHealth) -> ClientHealthOut:
    return ClientHealthOut(
        tenant_id=row.tenant_id,
        name=row.name,
        slug=row.slug,
        plan_tier=row.plan_tier,
        status=row.status,
        severity=row.severity,
        signals=[_signal(signal) for signal in row.signals],
        calls_7d=row.volume.calls_7d,
        calls_prev_7d=row.volume.calls_prev_7d,
        calls_basis=row.volume.basis,
        last_call_at=row.volume.last_call_at,
        # `to_paise`, for the same reason and with the same measurement as D-375 on the
        # client's own wallet — this is the SECOND surface that skipped the one rounding
        # function, and it is the operator's half of the same pair of screens.
        #
        # `spend_used_inr` is `spend_state.billed_inr`, NUMERIC(12,4), and four decimals
        # is what it ordinarily holds: a prepaid call is debited
        # `rates.prepaid_billed_inr`, quantized at `MONEY_Q`, so any
        # `self_serve_inr_per_min` that is not a divisor of 60 produces one on the first
        # call — 95 seconds at ₹6.50/min is ₹10.2917. `apps/web`'s `formatINR` TRUNCATES
        # a fraction to two digits (deliberately: it formats digits without ever parsing
        # them, hard rule 7's frontend shadow) where `to_paise` rounds half-up, so at a
        # `billed_inr` of ₹489.7050 THIS screen said ₹489.70 while `billing/cap_routes.py`
        # — which already went through `to_paise` — showed the client ₹489.71 for the
        # same row in the same instant. One paisa, on the "spend cap near" line an
        # operator quotes to a client while deciding whether to raise their ceiling.
        #
        # The screen's own docstring already says "this is a rupee AMOUNT, not a rate, so
        # two decimals is the right precision". It was right; the server was not sending
        # two.
        spend_used_inr=str(to_paise(row.spend_used_inr)),
        spend_cap_inr=None if row.spend_cap_inr is None else str(to_paise(row.spend_cap_inr)),
    )


@router.get(
    "",
    response_model=list[ClientHealthOut],
    openapi_extra=permission_meta("org:read"),
    summary="Client health overview — accounts about to churn or break, worst first",
    description=(
        "Every live client account with at least one live signal, ranked by how much is "
        "broken: the account with the most `stop` signals first, then the most `warn`. "
        "An account with nothing wrong is ABSENT — this is an exception report, not the "
        "client directory (`GET /v1/admin/tenants` is the roster). Signals are composed "
        "from the same predicates that refuse the client's dial, so the board cannot say "
        "an account is fine while the client is looking at a refusal. `calls_basis` says "
        "whether the call-volume comparison is entitled to be made at all; a trend must "
        "never be rendered on any value but `measured`."
    ),
)
async def read_client_health(
    session: AdminSession, principal: BoardReader
) -> list[ClientHealthOut]:
    del principal  # the dependency IS the authorization; the identity is not needed here
    return [_out(row) for row in await client_health(session)]


__all__ = ["router"]
