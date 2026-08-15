"""Buying a phone number — the gated surface (SURFACES §2b: "Number purchase + KYC").

Today this route always refuses, and it exists anyway. The alternative — no route until
a vendor adapter lands — is what left "gated behind KYC" as a sentence in a document
with no code under it for a whole milestone, and it is how the gate ends up being
written by whoever wires the vendor, under deadline, at the moment they most want it not
to be there. The refusals are the feature; the provisioning is the part still missing,
and `campaigns.provisioning.PROVISIONING_IMPLEMENTED` says so in a greppable constant
rather than in prose.

**POST, and the request body carries the location.** Not because a city is personal data
— it is not — but because this is a mutating request that will, the day it works, spend
money and create a telecom connection. `org:manage` is the permission for exactly that
reason (spending a client's money is not a read), which also makes D-22 refuse it to an
impersonating admin: a support person viewing an account read-only must not be able to
buy them a phone line.

**It writes nothing on either refusal.** No allocation, no intent row, no reservation.
There is no half-provisioned state to reconcile because there is no state.
"""

from __future__ import annotations

from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.provisioning import (
    assert_kyc_verified_for_provisioning,
    number_provisioning_capability,
    provisioning_not_configured,
)
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/numbers", tags=["campaigns"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` alias rather than a `Depends(...)` default: B008 is waived only for
# `**/routes.py` and this module is `provisioning_routes.py`.
NumberBuyer = Annotated[Principal, Depends(requires("org:manage"))]


class NumberPurchaseIn(BaseModel):
    """What a purchase needs from the client, and nothing it does not.

    `series` is DLT's number-class distinction (DATA-MODEL §6): 140 dials promotions,
    160/standard dials service and transactional. It is asked here rather than assigned
    later because a number's series is fixed at purchase and a mismatch with the
    campaign's classification is a DLT violation the launch gate then has to refuse
    (`number_series_mismatch`).

    `city` is required because Exotel's own onboarding requires the KYC address proof to
    reflect the city the number is bought in — a number bought against an address in
    another city is one the operator will not issue, whatever we record here.
    """

    model_config = ConfigDict(extra="forbid")

    series: Literal["140", "160", "standard"]
    city: str = Field(min_length=2, max_length=64)


@router.post(
    "/purchase",
    status_code=202,
    # No response model, because there is no success response to model. The route ends
    # in a `raise` on every path (see below), so `dict[str, str]` was not a contract a
    # client could code against — it was the SHAPE of a contract, published for a body
    # that cannot be produced, and the generated client turned it into a
    # `Record<string, string>` nobody will ever receive. `NoReturn` states the same fact
    # to mypy, which is what makes it enforceable: the day a provisioning adapter lands,
    # the author cannot return a value without declaring what it is.
    response_model=None,
    openapi_extra=permission_meta("org:manage"),
    summary="Buy a phone number — gated on verified KYC, and not implemented yet",
    description=(
        "Requests a phone number for this account. Refused with `kyc_not_verified` "
        "until Calevate has verified the business's identity — Indian telecom rules "
        "require the subscriber of a connection to be identified, and that applies to "
        "every account on every plan. A verified account is then refused with "
        "`number_provisioning_not_configured`, because this deployment holds no "
        "telephony-provider credentials and no provisioning adapter exists: numbers are "
        "provisioned by Calevate operations today. Neither refusal writes anything."
    ),
)
async def purchase_number(
    payload: NumberPurchaseIn,
    session: Session,
    principal: NumberBuyer,
) -> NoReturn:
    """Both gates, then the part that does not exist.

    The client-side gate first (`kyc_not_verified` — actionable), then the deployment
    capability. There is no success path below them and that is not an oversight: see
    the module docstring. When an adapter lands it goes here, behind a gate that has
    been live and exercised the whole time rather than written on the same afternoon.

    `series` and `city` are validated and then not used, because the thing that would
    use them does not exist. They are in the contract now rather than later so the shape
    a client codes against does not change on the day provisioning starts working — the
    same reason `create_topup_intent` publishes `provider_order_id: null` instead of
    omitting the field. That argument holds for the REQUEST, which is a real shape a
    client can send today; it never held for the response, which is why the declared
    `dict[str, str]` is now `NoReturn` (see the decorator).
    """
    assert principal.tenant_id is not None
    await assert_kyc_verified_for_provisioning(session, tenant_id=principal.tenant_id)
    raise provisioning_not_configured(number_provisioning_capability().reason)


__all__ = ["router"]
