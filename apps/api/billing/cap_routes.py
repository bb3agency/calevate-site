"""The client's own spend cap — the surface D-34's R-11 says has to exist.

SURFACES §2b:89 puts "spend against cap" on the client's plan panel and R-11 lists
per-account spend caps among the non-negotiable mitigations that ship WITH the
self-serve motion. Until now the caps were `plans.hard_cap_min` / `hard_cap_spend`,
admin-owned, editable only by hand in SQL, and a client could neither see the ceiling
that would stop their calls nor set one of their own. This is both halves of that.

WHAT A CLIENT MAY AND MAY NOT DO
---------------------------------
They may set `client_cap_min` and `client_cap_spend` as low as they like, including
zero. They may clear them, which returns them to the admin's ceiling. They may NOT set
one looser than the admin's — that is refused, not clamped, so the number they see is
always the number they typed. The effective cap is the stricter of the two, and the
whole argument for that shape, plus the defence of what happens when a client sets a
cap BELOW what they have already spent this month, lives in `billing/caps.py`.

PERMISSIONS
-----------
- `GET` is `billing:read` — an owner's business, not staff's (SEC-COMP §5), and the
  same permission the usage panel already uses so the two screens cannot disagree about
  who may see them.
- `PUT` is `org:manage`. Changing what a client is allowed to spend is not a read, and
  `org:manage` is in `MUTATING_PERMISSIONS`, so an impersonating admin (D-22) cannot
  set a client's cap from a client screen. There is no `billing:write` in the registry
  and inventing one for one route was not worth it — the same call `credit_routes.py`
  and `payment_routes.py` both made.

D-22 also fixes what CANNOT be here: no GET may require `org:manage`. The read below is
therefore a genuinely separate permission rather than the write's permission reused.

PUT, not PATCH, and it states the whole client-side pair: `null` on either field CLEARS
that side. A partial verb would need a way to say "leave this one alone", which is a
third state (`absent` vs `null`) that JSON makes easy to send by accident and hard to
read on the screen.

NOT mounted here — the integrator wires this router into `main.py`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.caps import CapView, apply_client_caps, read_caps, read_spend_counters
from apps.api.billing.service import current_billing_month, to_paise
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta

log = get_logger(__name__)

router = APIRouter(prefix="/v1/billing/caps", tags=["billing"])

Session = Annotated[AsyncSession, Depends(db)]
# Annotated dependencies rather than `Depends()` in a default: this file is not
# `routes.py`, so it is not covered by the B008 per-file ignore.
# THE READ IS `realm="any"` AND THE WRITE IS NOT, and the asymmetry is the point.
#
# `realm="client"` on the READ made the operator console's own Spend cap panel
# unreachable: `admin/tenants/[tenantId]/page.tsx::SpendCapPanel` reads this route
# through a D-22 view-as session, and `current_principal` refuses ANY request carrying
# the impersonation header — so the panel rendered "The cap state could not be read, so
# nothing is offered here" for every tenant, and the recompute control underneath it was
# permanently withheld. That was reported from the live console.
#
# It was never a considered restriction. `current_principal`'s docstring enumerates the
# three routes that are deliberately in that position — `PUT /v1/billing/caps`, the
# top-up intent and the WhatsApp alert opt-in — because each is part of the client's own
# sign-in. The GET is not one of them, and both realm-boundary sweeps drive the PUT, not
# this. An operator already sees this account's spend on the Money board and on Client
# health (`admin/health.py` reads `spend_cap_inr` and raises `spend_cap_near`), so
# nothing here is newly visible; what changes is that the panel built to show it can.
#
# The WRITE stays `realm="client"` deliberately, and not merely because D-22 refuses a
# mutation through impersonation. `client_cap_spend` is the CLIENT'S OWN INSTRUCTION —
# "stop us at this figure" — and it sits beside `plan_cap_spend`, which is OURS. An
# operator who wants to move what stops this account edits the plan's ceiling through
# the admin-realm commercial-terms route, where the write is theirs and the audit row
# names them. Letting the operator console write the client's half would erase the
# distinction between "we capped them" and "they capped themselves", which is the one
# thing this pair of columns exists to keep separate.
CapsRead = Annotated[Principal, Depends(requires("billing:read", realm="any"))]
CapsWrite = Annotated[Principal, Depends(requires("org:manage", realm="client"))]

# A rupee cap wider than this is not a cap. NUMERIC(12,4) holds eight digits before the
# point, so the column's own ceiling is ₹99,999,999.9999 — refusing at ten lakh instead
# gives a typo ("200000" for "20000") somewhere to fail that is not the database.
MAX_CLIENT_CAP_SPEND_INR = Decimal("1000000.00")
# Minutes are whole. 100,000 minutes is ~70 days of continuous calling.
MAX_CLIENT_CAP_MIN = 100_000


class Strict(BaseModel):
    """`extra="forbid"`: the response model IS the output whitelist, and a request with
    a misspelled field is a refusal rather than a silently ignored intention."""

    model_config = ConfigDict(extra="forbid")


class CapsIn(Strict):
    """The whole client-side pair. `null` clears that side (see the module docstring)."""

    cap_minutes: int | None = Field(default=None, ge=0, le=MAX_CLIENT_CAP_MIN)
    cap_spend_inr: Decimal | None = Field(
        default=None, ge=0, le=MAX_CLIENT_CAP_SPEND_INR, max_digits=12, decimal_places=2
    )

    @field_validator("cap_spend_inr", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        """Hard rule 7 at the boundary, identical to both top-up routes: `2500.10` as a
        JSON number has already been through a binary float by the time we see it."""
        if isinstance(value, float):
            raise ValueError(
                'money crosses the wire as a string ("2500.00"), never as a JSON float'
            )
        return value


class CapsOut(Strict):
    """Three answers, because a screen that shows only the last of them cannot explain
    itself: what the plan allows, what the client chose, and what is in force.

    Money is a string throughout for the reason hard rule 7 exists — these are exact
    NUMERIC rupee amounts and a JSON float cannot hold them.
    """

    month: str
    # The admin's ceiling. Read-only to the client; null means the plan sets none.
    plan_cap_minutes: int | None
    plan_cap_spend_inr: str | None
    # The client's own. Null means they have set none and the plan's applies.
    client_cap_minutes: int | None
    client_cap_spend_inr: str | None
    # The stricter of the pair — the one the compliance gate actually enforces.
    effective_cap_minutes: int | None
    effective_cap_spend_inr: str | None
    # This month's counters, so the client can see how close they are without a second
    # request to the usage panel. Same source (`spend_state`) the gate reads.
    minutes_used: str
    spend_used_inr: str
    # Is outbound calling stopped RIGHT NOW? On a PUT this is the answer AFTER the
    # write, which is what makes "I just capped myself below my spend" visible at the
    # moment it happens rather than discovered from an empty call list.
    capped: bool


def _render(caps: CapView, *, minutes: Decimal, spend: Decimal, capped: bool) -> CapsOut:
    def money(value: Decimal | None) -> str | None:
        return str(to_paise(value)) if value is not None else None

    return CapsOut(
        month=current_billing_month(),
        plan_cap_minutes=caps.admin_cap_min,
        plan_cap_spend_inr=money(caps.admin_cap_spend),
        client_cap_minutes=caps.client_cap_min,
        client_cap_spend_inr=money(caps.client_cap_spend),
        effective_cap_minutes=caps.effective_cap_min,
        effective_cap_spend_inr=money(caps.effective_cap_spend),
        minutes_used=str(to_paise(minutes)),
        spend_used_inr=str(to_paise(spend)),
        capped=capped,
    )


@router.get(
    "",
    response_model=CapsOut,
    openapi_extra=permission_meta("billing:read"),
    summary="The spending limits on this account — the plan's, the client's, and the one in force",
)
async def get_caps(session: Session, principal: CapsRead) -> CapsOut:
    """`billing:read`, not `org:manage`: no GET may require a mutating permission
    (D-22), and spend is an owner's business rather than staff's (SEC-COMP §5)."""
    assert principal.tenant_id is not None
    caps = await read_caps(session, tenant_id=principal.tenant_id)
    # The shared reader in `caps.py`: this screen and the ops recompute must agree about
    # what "this month" means and about a stale row reading as zeros, and one function
    # is how that stops being a coincidence.
    counters = await read_spend_counters(session, tenant_id=principal.tenant_id)
    return _render(
        caps,
        minutes=counters.minutes_used,
        # `billed_inr` — the CLIENT'S spend at their own rate, which is the number
        # `caps.over_cap_sql` compares their ceiling against. It used to be
        # `spend_used` — the engine's charge to US — so a client who set ₹5,000 was
        # shown our supplier cost as their progress towards it and was stopped at
        # roughly a quarter of what they thought they had bought (P1.3). Our pricing is
        # commercially ours; `billing/service.py` states that rule and this route was
        # publishing the monthly aggregate of it.
        spend=counters.billed_inr,
        capped=counters.capped,
    )


@router.put(
    "",
    response_model=CapsOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Set this account's own spending limits — never looser than the plan's",
    description=(
        "A client may lower their own limit as far as they like, including to zero, and "
        "may clear it to fall back on the plan's. A value looser than the plan's limit "
        "is refused with `client_cap_exceeds_plan_cap`. A limit BELOW what has already "
        "been spent this month is accepted and takes effect immediately: outbound "
        "calling stops for the rest of the month and the response says so in `capped`. "
        "Incoming calls are never affected."
    ),
)
async def set_caps(payload: CapsIn, session: Session, principal: CapsWrite) -> CapsOut:
    """One transaction: the cap and the gate's flag move together.

    `apply_client_caps` recomputes `spend_state.capped` from the counters already in the
    row, so a client who has just stopped themselves is stopped on the NEXT dial rather
    than on the dial after the next call happens to meter — which for an outbound-only
    tenant is precisely the call the cap was meant to prevent.

    The audit row commits with the change (the discipline `credit_routes.py` states):
    either both land or neither does, so a spending limit that moved without a record of
    who moved it is not a reachable state. `audit_log` is INSERT-only (hard rule 4) and
    `write_audit` is the only writer.
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    result = await apply_client_caps(
        session,
        tenant_id=tenant_id,
        cap_min=payload.cap_minutes,
        cap_spend=payload.cap_spend_inr,
    )
    await write_audit(
        session,
        action="billing.caps.set",
        actor=principal,
        tenant_id=tenant_id,
        object_type="plans",
        object_id=str(tenant_id),
        # Ceilings and a boolean, nothing else. No phone number, transcript or
        # extraction appears anywhere on this path (hard rule 6). `write_audit`'s
        # parameter is called `summary` and that is fine — the RAW_PII_FIELDS pattern of
        # the same name is about RESPONSE MODELS, and `CapsOut` declares no such field.
        summary={
            "cap_minutes": payload.cap_minutes,
            "cap_spend_inr": (
                str(to_paise(payload.cap_spend_inr)) if payload.cap_spend_inr is not None else None
            ),
            "capped_now": result.capped_now,
        },
    )
    counters = await read_spend_counters(session, tenant_id=tenant_id)
    return _render(
        result.caps,
        minutes=counters.minutes_used,
        # Same column as the GET above, for the same reason: the two describe one
        # screen, and a PUT that answered in a different currency from the GET that
        # loaded it would move the number under the client as they pressed save.
        spend=counters.billed_inr,
        # The flag AFTER this write, from the recompute itself rather than from a second
        # read: same transaction either way, but this is the value the client is being
        # told they caused.
        capped=result.capped_now,
    )


__all__ = ["MAX_CLIENT_CAP_MIN", "MAX_CLIENT_CAP_SPEND_INR", "CapsIn", "CapsOut", "router"]
