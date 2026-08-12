"""`POST /v1/auth/signup` — the self-serve way in (D-34 motion 2, FLOWS §2 route 1).

Mounted under `/v1/auth` for two reasons that happen to agree: it is the sign-in
surface's sibling, and `/v1/auth/` is on `rbac.PUBLIC_PREFIXES` — which is the honest
classification, because **no permission can gate a caller who has no organization
yet**. The locks on this route are a verified Clerk identity (`current_identity`, the
same dependency the invitation-accept route uses for the same reason) and the signup
quota. Both are asserted in `tests/self_serve_test.py`.

The business logic lives in `tenancy/signup.py`; this file is the boundary: shapes in,
shapes out, and the order the checks run in.

NOT mounted here — the integrator wires this router into `main.py`.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from scripts.seed import VERTICAL_TEMPLATES

from apps.api.admin.service import DISCLOSURE_TEMPLATES
from apps.api.core.auth import current_identity
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.tenancy.signup import (
    SelfServeTier,
    assert_signup_open,
    assert_signup_quota,
    create_self_serve_tenant,
    derive_slug,
)

log = get_logger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["signup"])

Identity = Annotated[tuple[UUID, str], Depends(current_identity)]

# The languages an agent can actually disclose itself in. Not a free string: hard rule
# 5 says the disclosure line is never null, and `create_organization` derives it from
# this map — an unknown language would silently fall back to English on a Telugu-first
# product (D-36).
Language = Literal["te-IN", "hi-IN", "en-IN"]


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_name: str = Field(min_length=2, max_length=120)
    # Optional: derived from the business name when absent. Validated for shape,
    # reserved-ness and collision server-side (there is no operator here to catch it),
    # and immutable once set.
    slug: str | None = Field(default=None, min_length=3, max_length=40)
    vertical_template: str = Field(default="clinic", max_length=40)
    language: Language = "te-IN"
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
    agent_id: UUID
    extraction_schema_id: UUID
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
        "The caller is a Clerk-verified user with no organization yet. Creates the "
        "organization, its receptionist agent, its extraction schema and its retention "
        "policies, and makes the caller its owner. The wallet starts empty, so the "
        "compliance gate refuses outbound calls until it is topped up."
    ),
)
async def signup(payload: SignupIn, request: Request, identity: Identity) -> SignupOut:
    """Order matters: is signup open → is this caller within quota → is the request
    coherent → build the tenant.

    The quota is consumed before the DB work and after the cheap checks, so a malformed
    body is free and a refused slug is not (see `assert_signup_quota`).
    """
    user_id, clerk_user_id = identity
    await assert_signup_open()
    await assert_signup_quota(
        clerk_user_id=clerk_user_id, ip=request.client.host if request.client else None
    )

    if payload.vertical_template not in VERTICAL_TEMPLATES:
        # `create_organization` falls back to the clinic template for an unknown
        # vertical, which is right for an operator who typed something odd and wrong
        # for a self-serve user who picked from a list: they would get a clinic's
        # extraction schema and no indication of it.
        raise ProblemError(
            kind="validation",
            code="unknown_vertical_template",
            title="Unknown business type",
            detail="That business type is not one we have a template for.",
            fields=[
                {
                    "field": "vertical_template",
                    "rule": "enum",
                    "message": f"one of: {', '.join(sorted(VERTICAL_TEMPLATES))}",
                }
            ],
        )
    assert payload.language in DISCLOSURE_TEMPLATES  # the Literal above guarantees it

    slug = payload.slug or derive_slug(payload.business_name)
    created = await create_self_serve_tenant(
        user_id=user_id,
        name=payload.business_name,
        slug=slug,
        vertical_template=payload.vertical_template,
        language=payload.language,
        billing_email=str(payload.billing_email) if payload.billing_email else None,
        plan_tier=payload.plan_tier,
        ip=request.client.host if request.client else None,
    )

    return SignupOut(
        tenant_id=created["id"],
        slug=created["slug"],
        name=payload.business_name,
        plan_tier=created["plan_tier"],
        status=created["status"],
        role=created["role"],
        agent_id=created["agent_id"],
        extraction_schema_id=created["extraction_schema_id"],
        next_steps=[
            "Add credit to your wallet — outbound calling is blocked until you do.",
            "Complete KYC so a calling number can be provisioned.",
            "Review your agent's questions and publish it.",
        ],
    )


__all__ = ["router"]
