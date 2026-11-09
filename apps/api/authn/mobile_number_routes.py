"""`POST /v1/auth/client/mobile-number` — a signed-in person sets their own mobile (D-976).

On the client realm's auth prefix beside `/password/change`, for that route's reason: it
changes the caller's own login and nothing else, so it names no account and needs no role.
That is also what keeps an operator out. A view-as session is an ADMIN session carrying
impersonation headers; this router reads only the client cookie, so an operator gets the
same 401 as anyone with no client session, and cannot change the owner's number.

The number is not echoed back: a contact field belongs on a route that declares a
permission (`scripts/check_redaction_exposure.py` rule 2), so the account page reads it
from `GET /v1/me`.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.authn import mobile_number
from apps.api.authn.cookies import enforce_same_origin
from apps.api.authn.routes import _authenticated, _require_enabled
from apps.api.core.auth import client_request_ip

_REALM = "client"

router = APIRouter(prefix=f"/v1/auth/{_REALM}", tags=[f"auth-{_REALM}"])


class MobileNumberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: As typed. Null or blank removes the number.
    phone: str | None = Field(default=None, max_length=32)


class MobileNumberOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change: Literal["added", "changed", "removed", "unchanged"]


@router.post(
    "/mobile-number",
    response_model=MobileNumberOut,
    summary="Add, change or remove the mobile number on your own login",
    description=(
        "Stored as typed, normalised to E.164 (a 10-digit Indian mobile gains +91). No code "
        "is sent to it yet (D-976). Null or blank removes it. Refused with "
        "`mobile_number_invalid` when it cannot be read as a phone number. Every change "
        "is audited without the number."
    ),
)
async def set_mobile_number(payload: MobileNumberIn, request: Request) -> MobileNumberOut:
    """No current password and no `X-Confirm-Action`, unlike `/password/change`: the number
    is not a credential, nothing signs in with it, and `enforce_same_origin` with the
    `SameSite` cookie is what stops another site sending this."""
    _require_enabled()
    enforce_same_origin(request)
    verified = await _authenticated(request, _REALM)
    changed = await mobile_number.set_own(
        user_id=verified.subject_id, raw=payload.phone, ip=client_request_ip(request)
    )
    return MobileNumberOut(change=changed.change)


__all__ = ["MobileNumberIn", "MobileNumberOut", "router"]
