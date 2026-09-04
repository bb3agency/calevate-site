"""Asking Calevate for a phone number from the client console — still no, for a new reason.

**MODEL A IS ADOPTED ON THE INBOUND LEG (D-535) AND THIS ROUTE STILL REFUSES.** Calevate
now buys Indian DIDs through the voice engine and a client forwards their own published
number to one — but that supply is **operator-led**, arranged during onboarding, and the
playbook names the self-serve shape specifically as the unsafe one: *"A future 'we
provision the number for self-serve' tier is Model A and is unsafe for a proprietor"*
(`docs/legal/LEGAL-OPS-PLAYBOOK.md:621`). So the refusal survives the decision.

**WHAT CHANGED IS THAT THE OLD COPY WAS NO LONGER TRUE.** It told the client "Calevate
does not sell, rent or provision telephone numbers" and sent them to a carrier. Half of
that is now false, and a false refusal is worse than a bare 404: a client repeats it to
their own operator and to their accountant. The new answer names both real routes — their
own connection, or ours arranged with their account manager — and promises no price and no
timeline, because neither is a fact this repository holds.

The KYC gate in front of it is unchanged and matters MORE under Model A, not less: the
connection is taken in our name, so the subscriber of record is us.

**POST rather than GET, and the request body carries the series and the city**, because
those are the two facts that decide what a client must go and buy if they take the
self-supply route — the series decides what the connection may lawfully dial, and
Exotel-class operators require the KYC address proof to match the city the number is
issued in. `org:manage` is the permission because this is the shape of a request that
spends money, which also makes D-22 refuse it to an impersonating admin.

**It writes nothing on either refusal.** No allocation, no intent row, no reservation.
There is no half-provisioned state to reconcile because there is no state. The route that
DOES spend money is admin-realm (`apps/api/admin/number_routes.py`) and takes the written
authorisation gate.
"""

from __future__ import annotations

from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.provisioning import (
    assert_kyc_verified_for_provisioning,
    self_serve_purchase_refused,
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
    summary="Ask us for a phone number — always refused here; numbers are arranged by an operator",
    description=(
        "Asks Calevate for a phone number, and is always refused from the client "
        "console: a number is arranged with the account manager as part of setting an "
        "agent up, never bought self-serve. Refused with `kyc_not_verified` until "
        "Calevate has verified the business's identity — Indian telecom rules require "
        "the subscriber of a connection to be identified, an operator will ask for the "
        "same documents, and it applies to every account on every plan. A verified "
        "account is then refused with `number_purchase_is_operator_led`, whose "
        "remediation names both routes forward: talk to us, or bring a connection taken "
        "in the client's own name with an Indian operator. Neither refusal writes "
        "anything."
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

    **THE SECOND REFUSAL DOES NOT READ THE DEPLOYMENT'S CAPABILITY, AND THAT IS
    DELIBERATE (D-535).** Whether this deployment has recorded a written reseller
    authorisation is OUR legal state, and answering a client differently depending on it
    would publish our paperwork through the shape of an error. The client-facing fact is
    the same either way: a number is not bought from this screen.
    """
    assert principal.tenant_id is not None
    await assert_kyc_verified_for_provisioning(session, tenant_id=principal.tenant_id)
    raise self_serve_purchase_refused()


__all__ = ["router"]
