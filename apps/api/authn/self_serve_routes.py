"""Self-serve account creation and Google sign-in, client realm only (D-703).

Routes, all under `/v1/auth/client` beside the password sign-in, all `enforce_same_origin`:

* `GET  /sign-in-options` — which doors this deployment has open, so the pages render only
  buttons that work.
* `POST /signup/start`, `POST /signup/complete` — `authn/registration.py`.
* `POST /google/start`, `POST /google/complete` — `authn/google.py`. `start` sets the
  browser-binding cookie; `complete` checks it, clears it and sets the session cookie.

A Google sign-in that arrives with an invitation token also redeems the invitation, when
the invitation was sent to the address Google verified.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from apps.api.authn import google, invitations, registration
from apps.api.authn.cookies import _is_secure, enforce_same_origin
from apps.api.authn.routes import _require_enabled, _set_cookie
from apps.api.authn.service import _audit
from apps.api.authn.subjects import load_subject
from apps.api.core.auth import client_request_ip
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.tenancy.signup import assert_signup_open

log = get_logger(__name__)

router = APIRouter(prefix="/v1/auth/client", tags=["auth-client"])

_REALM = "client"


def _binding_cookie_name(request: Request) -> str:
    # `__Host-` needs Secure, which a plain-http local run cannot set; the session cookie
    # drops the prefix on the same condition (`cookies.cookie_name`).
    name = google.BINDING_COOKIE
    return name if _is_secure(request) else name.removeprefix("__Host-")


class SignInOptionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    google: bool
    self_serve_signup: bool


class SignupStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class SignupCompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    password: str = Field(min_length=1, max_length=256)
    name: str | None = Field(default=None, max_length=120)


class SignupCompleteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str


class GoogleStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next: str | None = Field(default=None, max_length=512)


class GoogleStartOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorize_url: str


class GoogleCompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=4096)
    invitation_token: str | None = Field(default=None, min_length=16, max_length=256)


class GoogleCompleteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next: str | None
    account_created: bool
    #: The workspace an invitation just joined, when one came with the sign-in.
    joined_slug: str | None
    #: True when an invitation came with the sign-in but was addressed to another email.
    invitation_mismatch: bool


async def _signup_is_open() -> bool:
    try:
        await assert_signup_open()
    except ProblemError:
        return False
    return True


@router.get(
    "/sign-in-options",
    response_model=SignInOptionsOut,
    summary="Which ways to sign in and sign up this deployment offers",
)
async def sign_in_options() -> SignInOptionsOut:
    _require_enabled()
    return SignInOptionsOut(
        google=google.configured() and bool(get_settings().google_signin_redirect_uri),
        self_serve_signup=await _signup_is_open(),
    )


@router.post(
    "/signup/start",
    status_code=202,
    response_model=None,
    response_class=Response,
    summary="Email a code to create an account (answers the same for any address)",
)
async def signup_start(payload: SignupStartIn, request: Request) -> Response:
    _require_enabled()
    enforce_same_origin(request)
    await assert_signup_open()
    await registration.start_signup(email=str(payload.email), ip=client_request_ip(request))
    return Response(status_code=202)


@router.post(
    "/signup/complete",
    response_model=SignupCompleteOut,
    status_code=201,
    summary="Enter the emailed code and choose a password to create the account",
)
async def signup_complete(
    payload: SignupCompleteIn, request: Request, response: Response
) -> SignupCompleteOut:
    _require_enabled()
    enforce_same_origin(request)
    await assert_signup_open()
    created = await registration.complete_signup(
        email=str(payload.email),
        code=payload.code,
        password=payload.password,
        name=(payload.name or "").strip() or None,
        ip=client_request_ip(request),
    )
    _set_cookie(response, request, _REALM, created.session)
    return SignupCompleteOut(subject_id=str(created.subject_id))


@router.post(
    "/google/start",
    response_model=GoogleStartOut,
    summary="Begin signing in with Google",
)
async def google_start(
    payload: GoogleStartIn, request: Request, response: Response
) -> GoogleStartOut:
    _require_enabled()
    enforce_same_origin(request)
    begun = google.begin(next_path=payload.next)
    response.set_cookie(
        _binding_cookie_name(request),
        begun.browser_nonce,
        max_age=int(google.STATE_TTL.total_seconds()),
        path="/",
        secure=_is_secure(request),
        httponly=True,
        samesite="strict",
    )
    return GoogleStartOut(authorize_url=begun.authorize_url)


@router.post(
    "/google/complete",
    response_model=GoogleCompleteOut,
    summary="Finish signing in with Google and start a session",
)
async def google_complete(
    payload: GoogleCompleteIn, request: Request, response: Response
) -> GoogleCompleteOut:
    _require_enabled()
    enforce_same_origin(request)
    cookie = _binding_cookie_name(request)
    ip = client_request_ip(request)
    signed_in = await google.finish(
        code=payload.code,
        state=payload.state,
        browser_nonce=request.cookies.get(cookie),
        signup_open=await _signup_is_open(),
    )
    response.delete_cookie(cookie, path="/", secure=_is_secure(request), httponly=True)

    joined: invitations.JoinedWorkspace | None = None
    mismatch = False
    if payload.invitation_token:
        subject = await load_subject(_REALM, signed_in.subject_id)
        if subject is not None:
            joined = await invitations.accept_for_verified_address(
                token=payload.invitation_token,
                user_id=signed_in.subject_id,
                verified_email=subject.email,
                ip=ip,
            )
            mismatch = joined is None

    _set_cookie(response, request, _REALM, signed_in.session)
    await _audit(
        action="auth.google_sign_in",
        realm=_REALM,
        subject_id=signed_in.subject_id,
        ip=ip,
        object_id=str(signed_in.session.session_id),
        summary={
            "account_created": signed_in.created,
            "linked": signed_in.linked,
            "invitation": joined is not None,
        },
    )
    return GoogleCompleteOut(
        next=signed_in.next_path,
        account_created=signed_in.created,
        joined_slug=joined.slug if joined else None,
        invitation_mismatch=mismatch,
    )


__all__ = ["router"]
