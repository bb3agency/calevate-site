"""`POST /v1/auth/signup` — the self-serve way in (D-34 motion 2, FLOWS §2 route 1).

Mounted under `/v1/auth` for two reasons that happen to agree: it is the sign-in
surface's sibling, and `/v1/auth/` is on `rbac.PUBLIC_PREFIXES` — which is the honest
classification, because **no permission can gate a caller who has no organization
yet**. The locks on this route are a verified first-party session with no membership
(`current_identity`) and the signup quota. Both are asserted in
`tests/self_serve_test.py`.

The business logic lives in `tenancy/signup.py`; this file is the boundary: shapes in,
shapes out, and the order the checks run in.

`public_router` serves `GET /v1/public/business-types`, the list every business-type picker
renders (signup, the admin console's new-client form and its type screens), so the web holds
no copy of it.

NOT mounted here — the integrator wires these routers into `main.py`.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from calevate_shared import verticals
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from apps.api.core.auth import client_request_ip, current_identity
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.tenancy.signup import (
    SelfServeTier,
    assert_email_verified,
    assert_signup_open,
    assert_signup_quota,
    clean_business_name,
    create_self_serve_tenant,
    derive_slug,
)

log = get_logger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["signup"])
# `/v1/public/` is the prefix the RBAC registry skips (`core/rbac.PUBLIC_PREFIXES`): signup
# renders the list before its caller has an organization.
public_router = APIRouter(prefix="/v1/public", tags=["public"])

#: The list changes only with a deploy, and is the same for every reader.
BUSINESS_TYPES_CACHE_CONTROL: Final = "public, max-age=300"

Identity = Annotated[UUID, Depends(current_identity)]


class BusinessTypeExamplesOut(BaseModel):
    """The placeholders the admin console shows while it creates an account of this type
    (`calevate_shared.verticals.EXAMPLE_KEYS`)."""

    model_config = ConfigDict(extra="forbid")

    org_name: str | None = None
    org_slug: str | None = None
    knowledge_title: str | None = None
    knowledge_answer: str | None = None
    extraction_reason: str | None = None
    script_brief: str | None = None
    extraction_label: str | None = None
    extraction_options: str | None = None
    end_call_rules: str | None = None
    lead_search: str | None = None
    booking_job_title: str | None = None
    booking_job_line: str | None = None


class BusinessTypeOptionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    #: What choosing the type does: the details every lead of that business captures.
    hint: str
    #: Whether the type has its own starting lead details; without them a business's own
    #: are drafted by AI from its details, as `custom`'s are.
    has_standard_set: bool
    #: None for a type the file gives no examples, which shows the neutral ones.
    examples: BusinessTypeExamplesOut | None


class BusinessTypesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Every type, in picker order; `custom` is the one for a business that fits none.
    choices: list[BusinessTypeOptionOut]
    custom: str


def business_types_out() -> BusinessTypesOut:
    return BusinessTypesOut(
        choices=[
            BusinessTypeOptionOut(
                value=row.key,
                label=row.label,
                hint=row.hint,
                has_standard_set=bool(row.fields),
                examples=BusinessTypeExamplesOut(**row.examples) if row.examples else None,
            )
            for row in verticals.all_types()
        ],
        custom=verticals.CUSTOM,
    )


@public_router.get(
    "/business-types",
    response_model=BusinessTypesOut,
    summary="Every business type a picker offers",
    description=(
        "The business types in picker order, each with its label, what choosing it does and "
        "the examples the admin console shows for it. The same list `POST /v1/auth/signup` "
        "and the admin account forms accept."
    ),
)
async def list_business_types(response: Response) -> BusinessTypesOut:
    response.headers["Cache-Control"] = BUSINESS_TYPES_CACHE_CONTROL
    return business_types_out()


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_name: str = Field(min_length=2, max_length=120)
    # Optional: derived from the business name when absent. Validated for shape,
    # reserved-ness and collision server-side (there is no operator here to catch it),
    # and immutable once set.
    slug: str | None = Field(default=None, min_length=3, max_length=40)
    #: REQUIRED, with no default (D-722): the business says what it is.
    vertical_template: str = Field(max_length=40)
    billing_email: EmailStr | None = None
    # `managed` is deliberately not in this Literal: it is the invoiced motion, the one
    # with no wallet gate in front of it, and it is not self-assignable.
    plan_tier: SelfServeTier = "self_serve"


class SignupOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    slug: str
    name: str
    plan_tier: str
    status: str
    role: str
    # What the account still needs before it can dial (R-11): credit, and a
    # KYC-verified number. Stated by the API so the UI does not have to encode the
    # compliance rules a second time.
    next_steps: list[str]


@router.post(
    "/signup",
    response_model=SignupOut,
    status_code=201,
    summary="Create a self-serve tenant for the signed-in user (D-34, FLOWS §2)",
    description=(
        "The caller holds a first-party session and no organization yet. Creates the "
        "organization and its retention policies, makes the caller its owner and starts "
        "the free trial (test calls only until the first payment). No agent is made: the "
        "owner makes the first one (D-853)."
    ),
)
async def signup(payload: SignupIn, request: Request, user_id: Identity) -> SignupOut:
    """Order matters: is signup open → is this caller within quota → is the request
    coherent → build the tenant.

    The quota is consumed before the DB work and after the cheap checks, so a malformed
    body is free and a refused slug is not (see `assert_signup_quota`).
    """
    await assert_signup_open()
    # THE CALLER'S ADDRESS, not the socket peer. Behind the edge the peer is nginx,
    # so the per-IP half of the quota was one bucket for the entire internet — a
    # 30/hour cap on the PLATFORM (see `assert_signup_quota`).
    caller_ip = client_request_ip(request)
    await assert_signup_quota(user_id=user_id, ip=caller_ip)
    # BEFORE any tenant is written, and before the body is looked at: an unproved
    # mailbox is a property of the CALLER, not of what they typed, so a caller who has
    # to go and confirm their address should not first be told their slug is taken.
    await assert_email_verified(user_id)

    # `custom` is a business that fits none of the templates; it starts with the core lead
    # details only and its own are drafted once from its business details
    # (`agents/lead_fields`), as the operator wizard does.
    if not verticals.is_known(payload.vertical_template):
        # A value from outside the list is a client bug or a probe, not a business type;
        # refusing it beats silently seating the business on the neutral set.
        raise ProblemError(
            kind="validation",
            code="unknown_vertical_template",
            title="Unknown business type",
            detail="That business type is not one we have a template for.",
            fields=[
                {
                    "field": "vertical_template",
                    "rule": "enum",
                    "message": f"one of: {', '.join(sorted(verticals.all_keys()))}",
                }
            ],
        )

    # Cleaned BEFORE the slug is derived from it, so the derivation and the stored name
    # see the same string — a name whose only content is spacing or invisible characters
    # is refused here rather than becoming a workspace nobody can name.
    business_name = clean_business_name(payload.business_name)
    slug = payload.slug or derive_slug(business_name)
    created = await create_self_serve_tenant(
        user_id=user_id,
        name=business_name,
        slug=slug,
        vertical_template=payload.vertical_template,
        billing_email=str(payload.billing_email) if payload.billing_email else None,
        plan_tier=payload.plan_tier,
        ip=caller_ip,
    )

    return SignupOut(
        tenant_id=created["id"],
        slug=created["slug"],
        name=business_name,
        plan_tier=created["plan_tier"],
        status=created["status"],
        role=created["role"],
        next_steps=[
            "Your free trial has started: meet your first agent. Tell it its job in your own "
            "words, and it rings your phone so you hear it.",
            "When you are ready to go live, add credit. Then verify your business and "
            "choose your phone number.",
        ],
    )


__all__ = ["public_router", "router"]
