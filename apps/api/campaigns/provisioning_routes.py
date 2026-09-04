"""Asking Calevate for a phone number — and the answer, which is always no.

**We do not supply, sell, rent or provision telephone numbers** (Model B —
`docs/legal/LEGAL-OPS-PLAYBOOK.md` §9, published Terms clause 3, Acceptable Use §2.1).
The client takes the connection on their own operator account, passes that operator's
KYC, stays the subscriber of record, and hands us credentials they can withdraw. So this
route refuses every request, and it exists anyway for two reasons: clients ask this
question — it is the most common Model A request there is (`:266`) — and an API that
answers it with a 404 teaches them nothing, while this one names the three carriers and
says what to send back. The second reason is the KYC gate in front of it, which is a
compliance control that must be live and exercised whichever way the number is bought.

**POST rather than GET, and the request body carries the series and the city**, because
those are the two facts that decide what the client must go and buy — the series decides
what the connection may lawfully dial, and Exotel-class operators require the KYC address
proof to match the city the number is issued in. `org:manage` is the permission because
this is the shape of a request that spends money, which also makes D-22 refuse it to an
impersonating admin.

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
    later because a number's series is fixed when the operator issues it and a mismatch
    with the campaign's classification is a DLT violation the launch gate then has to
    refuse (`number_series_mismatch`).

    `city` is required because Exotel's own onboarding requires the KYC address proof to
    reflect the city the number is issued in — a number taken against an address in
    another city is one the operator will not issue, whoever asks for it.
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
    # to mypy, which is what makes it enforceable: nobody can add a success body here
    # without declaring what it is — and there is no self-serve success body to add.
    response_model=None,
    openapi_extra=permission_meta("org:manage"),
    summary="Ask us for a phone number — always refused; Calevate does not supply numbers",
    description=(
        "Asks Calevate for a phone number, and is always refused, because Calevate "
        "neither supplies nor resells telephone numbers: the client takes the connection "
        "in their own name on their own account with an Indian operator (Exotel, Plivo "
        "or Vobiz), remains the subscriber of record, and issues Calevate revocable API "
        "credentials for it. Refused with `kyc_not_verified` until Calevate has verified "
        "the business's identity — Indian telecom rules require the subscriber of a "
        "connection to be identified, the operator will ask for the same documents, and "
        "it applies to every account on every plan. A verified account is then refused "
        "with `number_provisioning_not_configured`, whose remediation names the carriers "
        "and what to send back. Neither refusal writes anything."
    ),
)
async def purchase_number(
    payload: NumberPurchaseIn,
    session: Session,
    principal: NumberBuyer,
) -> NoReturn:
    """Both gates, then the answer, which is no.

    The client-side gate first (`kyc_not_verified` — actionable, and true of them at
    their own operator too), then the refusal that names our model and their next step.
    There is no success path below them and that is not an oversight: supplying a number
    from the CLIENT CONSOLE is the self-serve shape the playbook names as unsafe, and it
    stays refused whatever the operator-led path does (module docstring).

    `series` and `city` are validated and then not used. They stay in the contract
    because they are the two facts a client needs settled before they walk into an
    operator, and asking for them is what lets the refusal be specific; the response was
    never a real shape, which is why it is `NoReturn` (see the decorator).
    """
    assert principal.tenant_id is not None
    await assert_kyc_verified_for_provisioning(session, tenant_id=principal.tenant_id)
    raise provisioning_not_configured(number_provisioning_capability().reason)


__all__ = ["router"]
