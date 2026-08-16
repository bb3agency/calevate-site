"""The client's own dashboard-AI allowance, and the one thing they can buy with it
(D-127 — G-3, G-4, G-5).

Two routes, and the second exists because of one sentence in G-5: **nothing is debited
from the wallet until the user explicitly accepts.** That makes the acceptance an ACT —
a person agreeing to spend money — which is why it is a POST with a permission, an
echoed amount and an `audit_log` row in the same transaction, and not a query parameter
on the read.

WHAT THE READ IS FOR. It is the quota panel AND the modal's contents. When the assist
endpoint refuses with `ai_quota_exceeded` the browser re-reads this route rather than
rendering figures carried in the error body, so the amount a person is asked to accept
is always the amount the server would charge — there is one computation
(`billing/ai_quota.py::read_ai_quota`) and no copy of it anywhere.

PERMISSIONS
-----------
- `GET` is `billing:read` — spend is an owner's business, not staff's (SEC-COMP §5), and
  it is the permission the usage panel and the caps panel already use so the three
  screens cannot disagree about who may see them. NOT `org:manage`: no GET may require a
  mutating permission (D-22).
- `POST` is `org:manage`, which is in `MUTATING_PERMISSIONS`, so an operator inside a
  read-only "view as client" session cannot spend a client's money from a client screen
  (D-22). There is no `billing:write` in the registry and one route did not warrant
  inventing one — the same call `cap_routes.py`, `credit_routes.py` and
  `payment_routes.py` all made.

THE ECHOED AMOUNT IS THE CONFIRMATION. `accept_amount_inr` must equal what the server
would charge, and a mismatch is refused rather than clamped. It is the client-realm form
of the admin routes' `X-Confirm-Action` double-key, and it closes the same failure: a
screen left open across a price change debiting a figure nobody was shown. A JSON float
is refused at the boundary for the reason hard rule 7 exists — `500.10` has already been
through a binary double by the time we see it.

NOT mounted here — the integrator wires this router into `main.py`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import (
    AI_OVERAGE_BLOCK_INR,
    purchase_ai_overage,
    quota_payload,
    read_ai_quota,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/billing/ai-quota", tags=["billing"])

Session = Annotated[AsyncSession, Depends(db)]
# Annotated dependencies rather than `Depends()` in a default: this file is not
# `routes.py`, so it is not covered by the B008 per-file ignore.
QuotaReader = Annotated[Principal, Depends(requires("billing:read", realm="client"))]
QuotaBuyer = Annotated[Principal, Depends(requires("org:manage", realm="client"))]


class Strict(BaseModel):
    """`extra="forbid"`: the response model IS the output whitelist, and a request with a
    misspelled field is a refusal rather than a silently ignored intention."""

    model_config = ConfigDict(extra="forbid")


class AiExtraIn(Strict):
    """What the person accepted, echoed back from the modal.

    NO DEFAULT, deliberately. A Pydantic field with a default generates an OPTIONAL
    TypeScript property in the client this repo generates from OpenAPI, and an optional
    confirmation is not a confirmation — the whole value of the echo is that the caller
    had to state the figure they were shown.
    """

    accept_amount_inr: Decimal = Field(max_digits=12, decimal_places=2)

    @field_validator("accept_amount_inr", mode="before")
    @classmethod
    def _never_a_float(cls, value: Any) -> Any:
        """Hard rule 7 at the boundary, identical to both top-up routes and the caps
        route: `500.10` as a JSON number has already lost its exactness before we see
        it, and this field's entire job is to be compared for EQUALITY."""
        if isinstance(value, float):
            raise ValueError('money crosses the wire as a string ("500.00"), never as a JSON float')
        return value


class AiQuotaOut(Strict):
    """This month's AI allowance, in the two units the screen needs it in.

    EVERY FIELD IS REQUIRED — none carries a Pydantic default — because a default here
    generates an optional property in the typed client, and a screen that can render
    `undefined` as a figure is one §52 violation away from printing a ceiling nobody has.

    Money is an exact decimal STRING throughout (hard rule 7); the counts are the
    ESTIMATE the rupee ceiling is worth at a reference price, which the screen renders
    with "about" beside it.
    """

    month: str
    plan_tier: str
    # "within" | "ceiling_reached" | "exhausted" | "platform_paused" — the SERVER's own
    # name for the state, so the browser never re-derives it from three numbers.
    state: str
    included_inr: str
    used_inr: str
    # included + anything already bought this month.
    allowance_inr: str
    remaining_inr: str
    requests_used: int
    requests_included: int
    requests_remaining: int
    # Null when nothing was bought this month: "they added ₹500" and "they added
    # nothing" are different facts and the screen says different things about them.
    extra_purchased_inr: str | None
    # What the modal quotes. Always present, so the figure on the screen is the server's
    # and never a constant compiled into the browser bundle.
    extra_block_inr: str
    # What that block is worth in assists, at the same reference price as the counts
    # above — so the modal never divides a rupee amount in the browser.
    extra_block_requests: int
    extra_available: bool
    # "not_at_ceiling" | "already_purchased" | "not_prepaid" | "platform_paused", or null
    # when the block IS on offer.
    extra_unavailable_reason: str | None


@router.get(
    "",
    response_model=AiQuotaOut,
    openapi_extra=permission_meta("billing:read"),
    summary="This account's AI help allowance for an IST billing month, and what more costs",
    description=(
        "What the dashboard's AI help has used this month, against the allowance "
        "included with the plan. The allowance is a rupee ceiling; the assist counts "
        "beside it are an estimate of what that ceiling is worth and are labelled as "
        "such. Requires `billing:read`, which account owners hold and staff do not."
    ),
)
async def get_ai_quota(
    session: Session, principal: QuotaReader, month: str | None = None
) -> AiQuotaOut:
    """The tenant comes from the PRINCIPAL, never from the caller — there is no
    `tenant_id` to tamper with, and `session` is RLS-scoped to the principal's own
    tenant, so another account's month is unaddressable rather than merely forbidden."""
    assert principal.tenant_id is not None
    quota = await read_ai_quota(session, tenant_id=principal.tenant_id, month=month)
    return AiQuotaOut.model_validate(quota_payload(quota))


@router.post(
    "/extra",
    response_model=AiQuotaOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Accept the charge for more AI help this month — the only thing that debits it",
    description=(
        "Debits the wallet ONCE for this billing month and adds the extra AI allowance. "
        "`accept_amount_inr` must equal `extra_block_inr` from the read above, as an "
        "exact decimal string. Refused before anything moves if the account still has "
        "included allowance left, if it is invoiced rather than prepaid, or if AI help "
        "is paused platform-wide; a second submission of the same month returns the "
        "block already bought and charges nothing. Requires `org:manage`."
    ),
)
async def buy_ai_extra(payload: AiExtraIn, session: Session, principal: QuotaBuyer) -> AiQuotaOut:
    """One transaction: the debit and the record of who agreed to it move together.

    The audit row is written only when money actually moved (`charged`) — the convention
    `billing/terms.py` and `kb.approve_source` established: an audit row belongs to a
    real change, not to a button press. It commits in the CALLER's transaction, so a
    debit with no record of the person who accepted it is not a reachable state; that is
    the discipline `credit_routes.py` states for the admin half of this ledger.
    """
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    result = await purchase_ai_overage(
        session, tenant_id=tenant_id, accepted_amount_inr=payload.accept_amount_inr
    )
    if result.charged:
        await write_audit(
            session,
            action="billing.ai_quota.extra_accepted",
            actor=principal,
            tenant_id=tenant_id,
            object_type="credit_ledger",
            object_id=result.quota.month,
            # Rupee amounts and a month. No phone number, transcript or extraction is
            # reachable from this path (hard rule 6), and the figures are exactly the
            # ones the person was shown before they pressed accept.
            summary={
                "month": result.quota.month,
                "accepted_amount_inr": str(result.amount_inr),
                "included_inr": str(result.quota.included_inr),
                "used_inr": str(result.quota.used_inr),
            },
        )
    return AiQuotaOut.model_validate(quota_payload(result.quota))


__all__ = ["AI_OVERAGE_BLOCK_INR", "AiExtraIn", "AiQuotaOut", "router"]
