"""`/v1/auth/{admin,client}/**` — the first-party authentication surface (D-170).

═══ TWO ROUTERS, BUILT BY ONE FACTORY, AND WHY THAT IS NOT THE THING §3 WARNS ABOUT ═══

AUTH-MIGRATION §3 is emphatic that a shared realm-parameterised module is dangerous, and
`apps/web`'s two realm files stay duplicated for exactly that reason. The danger it names
is precise: *"a `realm` parameter on one shared module is one bad conditional away from
presenting an admin credential on a client surface"* — a RUNTIME branch that could pick the
wrong realm for a given request.

`_realm_router(realm)` has no such branch. The realm is a closure constant fixed when the
router is constructed at import, it appears in the URL as a literal (`/v1/auth/admin/...`,
never `/v1/auth/{realm}/...`), and there is no request-time input that can change which
realm a handler operates in. What comes out is two independent `APIRouter` objects with two
independent route trees — the same end state as writing the file twice, minus the copy that
would drift.

The realm is still checked FOUR ways underneath, per §3: it is inside the session token's
hash domain, it is in the `WHERE` clause beside it, it selects the cookie name, and
`enforce_same_origin` bounds where a request may come from at all.

═══ WHY EVERY ROUTE IS MOUNTED EVEN WHEN THE FLAG IS OFF ═══

`Settings.first_party_auth_enabled` defaults to **True** — this is the only authentication
this product has (D-170), so the flag is a kill switch rather than a cutover gate, and a
deployment that came up with it off would have no way for anybody to sign in.

When it IS off the routes stay mounted and refuse with `first_party_auth_disabled`, rather
than being conditionally mounted. A router that appears only under some configuration is
invisible to `scripts/check_wiring.py`, absent from the committed OpenAPI contract, and
answers 404 — which an operator cannot tell from a typo at exactly the moment they are
trying to work out why nobody can sign in.

═══ STATUS CODES, AS A CONTRACT ═══

| condition | status | code |
|---|---|---|
| flag off | 403 | `first_party_auth_disabled` |
| bad email/password, unknown account, dead account | 401 | `invalid_credentials` |
| wrong emailed sign-in code | 401 | `invalid_second_factor` |
| wrong emailed OTP | 401 | `invalid_code` |
| no/expired/replayed session cookie | 401 | `unauthorized` |
| admin session that has not done MFA | 401 | `second_factor_required` |
| cross-site request | 403 | `cross_site_request` |
| spent reset/invite token | 422 | `invalid_reset_token` / `invitation_invalid` |
| password too short/long | 422 | `password_length` |
| failure budget spent | 429 | `too_many_attempts` |
| request budget spent | 429 | `rate_limited` (middleware) |

Every one of them is RFC-9457 problem+json — `ProblemError` is the only thing raised here,
and `core/errors.install_error_handlers` renders it.

═══ NO ROUTE HERE HONOURS `Idempotency-Key`, AND THAT IS THE DECISION (D-178) ═══

`reliability.claim_idempotency` exists, CORS allows the header through, and both
password-reset forms send one. None of these routes takes the dependency, and none will.

THE REASON IS THE SCOPE. An idempotency record is keyed on `(scope_key, route, method,
idempotency_key)`, and everything about whether serving a cached response is safe collapses
into "can two different callers compute the same scope?" (`scripts/check_idempotency_scope.py`,
D-175). `scope_key` therefore takes `tenant_id: UUID | None` and `user_id: UUID | None` and
nothing else — the annotations are the guard, because mypy strict refuses a `str` at every
call site. **The routes that a double submit could plausibly hurt are the unauthenticated
ones**, and an unauthenticated caller has no principal: the only candidate scopes are the
submitted email address and the client address, which are respectively a value any stranger
can type and the value D-175 exists because a reference platform used. Two strangers sharing
a scope is caller A being served caller B's stored response. There is no version of this
where the header buys more than it costs, so it is not taken.

WHAT PROTECTS EACH ROUTE INSTEAD, since "no idempotency key" is only an answer if something
else is:

  * `password/reset/confirm`, `bootstrap/confirm`, `invitations/accept` — the token is
    burned by ONE `UPDATE … WHERE used_at IS NULL … RETURNING` (`tokens.redeem_token`,
    `invitations`' CAS). Two concurrent submissions produce exactly one winner at the
    database, which is a stronger statement than a replay cache makes. The loser is told the
    link is spent, and that is CORRECT rather than a wart: nothing here can distinguish the
    person who double-clicked from somebody replaying a leaked link, and the safe answer to
    both is the same.
  * `password/reset/request`, `login/otp/resend`, `otp/request`, `step-up` — issuing retires
    the previous secret (`tokens.invalidate_outstanding`, `otp.issue_challenge`), so a double
    submit leaves ONE live secret rather than two, which is the property idempotency would
    have been asked to provide. The residue is a second email, bounded by the `auth` rate
    profile and by `throttle`'s per-subject budget.
  * `login`, `login/otp`, `step-up/verify` — a second submission spends a throttle budget and
    either succeeds identically or is refused; the session rotation is a CAS on
    `superseded_at IS NULL`, so two concurrent rotations cannot both mint a live token.

`tests/authn_idempotency_test.py` asserts the absence as a property — no handler in this
module reads the header — and drives the double submit on both reset routes so the sentences
above are measured rather than believed.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from apps.api.authn import bootstrap, invitations, service, stepup
from apps.api.authn.cookies import (
    clear_session_cookie,
    enforce_same_origin,
    read_token,
    set_session_cookie,
)
from apps.api.authn.hashing import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS
from apps.api.authn.models import AUTHN_REALMS
from apps.api.authn.sessions import IssuedSession, VerifiedSession, verify_session
from apps.api.core.auth import client_request_ip
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)


# ───────────────────────────── wire models ──────────────────────────────────


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    # Bounded HERE as well as in `hashing._refuse_unusable`, and the two bounds are the
    # same constants rather than two numbers that could drift. Pydantic refuses an
    # over-long body before it reaches the HMAC, which is the point: an unbounded password
    # on an unauthenticated route is a free CPU sink.
    password: str = Field(min_length=MIN_PASSWORD_CHARS, max_length=MAX_PASSWORD_CHARS)


class LoginOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: `authenticated` means the cookie is usable now. `otp_required` means a code has just
    #: been emailed and the session opens exactly one door — `POST .../login/otp` — until it
    #: is answered. There is no third value: this product's second factor is the emailed
    #: code and nothing else (D-170), so there is no "enrol an authenticator" branch for a
    #: console to handle.
    status: Literal["authenticated", "otp_required"]


class SecondFactorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The emailed six-digit code. Bounded tightly because there is exactly one shape it
    #: can take — a longer bound would only widen what reaches the verifier.
    code: str = Field(min_length=1, max_length=16)


class SessionOut(BaseModel):
    """Who this session is, as ids and state.

    **NO EMAIL ADDRESS, deliberately.** An earlier draft returned one, and
    `scripts/check_redaction_exposure.py` reported it — correctly. The substance is
    defensible (it is the caller's OWN address, on a route only their own session reaches),
    but the guardrail's contract for an allowlist entry is "role-checked AND writes
    audit_log", and writing an audit row on every bootstrap poll would be absurd volume for
    a fact the caller already knows because they typed it to sign in.

    So the field is gone rather than exempted. Nothing consumed it — `apps/web` is a
    separate slice and unbuilt — and a field nobody reads is the same defect as a column
    nobody reads, in wire form. A console that later wants to render "signed in as …" gets
    a profile endpoint whose disclosure is considered on its own terms.
    """

    model_config = ConfigDict(extra="forbid")

    realm: str
    subject_id: UUID
    #: Whether this session completed the second factor. On the admin realm a session with
    #: this False can reach exactly one route.
    mfa_complete: bool
    email_verified: bool


class ResetRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_CHARS, max_length=MAX_PASSWORD_CHARS)


class OtpRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["email_verify"] = "email_verify"


class OtpConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["email_verify"] = "email_verify"
    code: str = Field(min_length=1, max_length=16)


class BootstrapConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_CHARS, max_length=MAX_PASSWORD_CHARS)


class InviteAcceptWithPasswordIn(BaseModel):
    # THE NAME IS NOW FREE — `tenancy/routes.py`'s `AcceptInviteIn`/`AcceptInviteOut` went
    # with the Clerk-era endpoint in D-177 — and the name STAYS, because renaming it would
    # rename the schema in the committed OpenAPI contract and regenerate every consumer of
    # `apps/web/src/lib/api/schema.d.ts` for no gain. It also still says the true thing:
    # this model carries a password, which the vendor-era one could not.
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=MIN_PASSWORD_CHARS, max_length=MAX_PASSWORD_CHARS)
    #: Optional, because the invitation carries the address and the address is the identity.
    #: A name is a nicety and refusing an invite for want of one would be absurd.
    name: str | None = Field(default=None, max_length=200)


class InviteAcceptWithPasswordOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    slug: str
    role: str


class RevokedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revoked: int


# ─────────────────────────────── guards ──────────────────────────────────────


def _require_enabled() -> None:
    """The cutover flag, read per request so flipping it needs no deploy.

    403 rather than 404: the route genuinely exists, and an operator mid-cutover has to be
    able to tell "this deployment has not switched over yet" from "I typed the path wrong".
    """
    if not get_settings().first_party_auth_enabled:
        raise ProblemError(
            kind="permission",
            code="first_party_auth_disabled",
            title="First-party sign-in is not enabled",
            detail="This deployment is not using first-party authentication.",
            remediation="Sign in through the configured identity provider.",
        )


def _second_factor_required() -> ProblemError:
    return ProblemError(
        kind="auth",
        code="second_factor_required",
        title="Two-factor authentication required",
        detail="This session has not completed two-factor authentication.",
        remediation="Enter the code from your authenticator app to finish signing in.",
    )


async def _live_session(request: Request, realm: str) -> VerifiedSession:
    """The session this request presents, or the one refusal every failure produces."""
    token = read_token(request, realm)
    if not token:
        raise ProblemError.unauthorized("Your session is not valid. Sign in again.")
    outcome = await verify_session(token=token, realm=realm)
    return outcome.require_live()


async def _authenticated(request: Request, realm: str) -> VerifiedSession:
    """A session that has cleared every gate this realm imposes.

    The MFA gate is applied HERE rather than only in `core/auth.py`, and it is the same
    rule: `service.MFA_REQUIRED_REALMS` is asserted equal to `core.auth.MFA_REQUIRED_REALMS`
    by `tests/authn_mfa_test.py`, so an operator session that skipped a second factor is
    refused identically by this router and by the rest of the API. A gate that existed in
    only one of the two would be a gate with a way around it.
    """
    verified = await _live_session(request, realm)
    if verified.realm in service.MFA_REQUIRED_REALMS and verified.mfa_verified_at is None:
        raise _second_factor_required()
    return verified


def _set_cookie(response: Response, request: Request, realm: str, issued: IssuedSession) -> None:
    set_session_cookie(response, realm=realm, token=issued.token, request=request)


# ─────────────────────────── the router factory ──────────────────────────────


def _realm_router(realm: str) -> APIRouter:
    """One realm's complete authentication surface. See the module docstring."""
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm")

    router = APIRouter(prefix=f"/v1/auth/{realm}", tags=[f"auth-{realm}"])

    async def live(request: Request) -> VerifiedSession:
        return await _live_session(request, realm)

    async def authed(request: Request) -> VerifiedSession:
        return await _authenticated(request, realm)

    # THE DEPENDENCIES ARE SPELLED AS DEFAULT ARGUMENTS, NOT AS `Annotated` ALIASES, and
    # that is forced rather than preferred. This module has `from __future__ import
    # annotations`, so every annotation is a STRING that FastAPI resolves against the
    # MODULE namespace — and a `Live = Annotated[...]` alias defined inside this factory is
    # local to it, so the resolution fails with a bare `ForwardRef('Live')` and
    # `app.openapi()` raises `PydanticUserError`. It fails at schema generation rather than
    # at import, which is why it is worth a comment: the app boots, and the first thing to
    # break is the contract snapshot.

    @router.post(
        "/login",
        response_model=LoginOut,
        summary=f"Sign in to the {realm} realm with an email address and password",
    )
    async def login(payload: LoginIn, request: Request, response: Response) -> LoginOut:
        """Always answers identically for an unknown address and a wrong password —
        same status, same body, and the same wall-clock cost (`service.sign_in`)."""
        _require_enabled()
        enforce_same_origin(request)
        outcome = await service.sign_in(
            realm=realm,
            email=str(payload.email),
            password=payload.password,
            ip=client_request_ip(request),
        )
        _set_cookie(response, request, realm, outcome.session)
        return LoginOut(status=outcome.status)

    @router.post(
        "/login/otp",
        response_model=SessionOut,
        summary="Complete a sign-in by entering the emailed one-time code",
    )
    async def login_otp(
        payload: SecondFactorIn,
        request: Request,
        response: Response,
        verified: VerifiedSession = Depends(live),
    ) -> SessionOut:
        """Takes a session that has proved a password but not the second factor.

        THIS IS THE ONLY SECOND-FACTOR ENDPOINT (D-170): the emailed code is the whole
        mechanism, so there is no sibling route for an authenticator app and no route for a
        recovery code. Rotates the session on success, which is OWASP's session-fixation
        defence applied at the privilege change.
        """
        _require_enabled()
        enforce_same_origin(request)
        rotated = await service.complete_second_factor(
            verified=verified, code=payload.code, ip=client_request_ip(request)
        )
        _set_cookie(response, request, realm, rotated)
        return await _session_out(realm, verified.subject_id, mfa_complete=True)

    @router.post(
        "/login/otp/resend",
        status_code=202,
        response_model=None,
        # An EMPTY 202: the handler returns a bare `Response`, so there is no body and
        # no media type. Without `response_class` FastAPI documents these as
        # `application/json` with a `{}` schema — a shape the route can never produce,
        # which the generated TypeScript client turns into a value nobody receives and
        # which the response-model sweep in `tests/response_shape_test.py` cannot tell
        # apart from a genuinely undeclared body (D-303).
        response_class=Response,
        summary="Email a fresh one-time code for a sign-in that is waiting on one",
    )
    async def login_otp_resend(
        request: Request, verified: VerifiedSession = Depends(live)
    ) -> Response:
        """A new code RETIRES the previous one, so resending cannot be used to accumulate
        parallel codes and multiply the five-guess budget."""
        _require_enabled()
        enforce_same_origin(request)
        await service.resend_second_factor(verified=verified)
        return Response(status_code=202)

    @router.get(
        "/session",
        response_model=SessionOut,
        summary="Who this session belongs to — the console's bootstrap call",
    )
    async def read_session(verified: VerifiedSession = Depends(authed)) -> SessionOut:
        """Re-reads the subject rather than trusting the session row, so a deactivation
        takes effect on the next request (BACKEND-PATTERNS §7)."""
        _require_enabled()
        return await _session_out(
            realm, verified.subject_id, mfa_complete=verified.mfa_verified_at is not None
        )

    @router.post(
        "/session/refresh",
        response_model=SessionOut,
        summary="Exchange a live session for a fresh token, keeping its lifetime",
    )
    async def refresh_session(
        request: Request, response: Response, verified: VerifiedSession = Depends(authed)
    ) -> SessionOut:
        _require_enabled()
        enforce_same_origin(request)
        rotated = await service.refresh(verified=verified)
        _set_cookie(response, request, realm, rotated)
        return await _session_out(
            realm, verified.subject_id, mfa_complete=verified.mfa_verified_at is not None
        )

    @router.post("/logout", response_model=RevokedOut, summary="End this session")
    async def logout(
        request: Request, response: Response, verified: VerifiedSession = Depends(live)
    ) -> RevokedOut:
        """Deliberately depends on `Live` and not `Authed`: a half-authenticated session
        must be able to sign itself out, or an operator who abandons an MFA prompt is stuck
        with a live partial session and no way to drop it."""
        _require_enabled()
        enforce_same_origin(request)
        await service.sign_out(verified=verified, ip=client_request_ip(request))
        clear_session_cookie(response, realm=realm, request=request)
        return RevokedOut(revoked=1)

    @router.post(
        "/logout/all",
        response_model=RevokedOut,
        summary="End every session this person holds in this realm",
    )
    async def logout_all(
        request: Request, response: Response, verified: VerifiedSession = Depends(authed)
    ) -> RevokedOut:
        _require_enabled()
        enforce_same_origin(request)
        count = await service.sign_out_everywhere(verified=verified, ip=client_request_ip(request))
        clear_session_cookie(response, realm=realm, request=request)
        return RevokedOut(revoked=count)

    @router.post(
        "/password/reset/request",
        status_code=202,
        response_model=None,
        # An EMPTY 202: the handler returns a bare `Response`, so there is no body and
        # no media type. Without `response_class` FastAPI documents these as
        # `application/json` with a `{}` schema — a shape the route can never produce,
        # which the generated TypeScript client turns into a value nobody receives and
        # which the response-model sweep in `tests/response_shape_test.py` cannot tell
        # apart from a genuinely undeclared body (D-303).
        response_class=Response,
        summary="Ask for a password reset link (answers identically for unknown addresses)",
    )
    async def reset_request(payload: ResetRequestIn, request: Request) -> Response:
        """202 with an EMPTY body, always. There is no version of this response that
        differs for a known and an unknown address — that is the point of it."""
        _require_enabled()
        enforce_same_origin(request)
        await service.request_password_reset(
            realm=realm, email=str(payload.email), ip=client_request_ip(request)
        )
        return Response(status_code=202)

    @router.post(
        "/password/reset/confirm",
        status_code=204,
        response_model=None,
        summary="Set a new password from a reset link, ending every existing session",
    )
    async def reset_confirm(payload: ResetConfirmIn, request: Request) -> Response:
        _require_enabled()
        enforce_same_origin(request)
        await service.confirm_password_reset(
            realm=realm,
            token=payload.token,
            password=payload.password,
            ip=client_request_ip(request),
        )
        return Response(status_code=204)

    @router.post(
        "/otp/request",
        status_code=202,
        response_model=None,
        # An EMPTY 202: the handler returns a bare `Response`, so there is no body and
        # no media type. Without `response_class` FastAPI documents these as
        # `application/json` with a `{}` schema — a shape the route can never produce,
        # which the generated TypeScript client turns into a value nobody receives and
        # which the response-model sweep in `tests/response_shape_test.py` cannot tell
        # apart from a genuinely undeclared body (D-303).
        response_class=Response,
        summary="Email a one-time code to this session's own address",
    )
    async def otp_request(
        payload: OtpRequestIn, request: Request, verified: VerifiedSession = Depends(authed)
    ) -> Response:
        """Scoped to the CALLER'S OWN subject — there is no parameter naming whose mailbox
        to mail, which is what stops this being a way to send mail to arbitrary addresses."""
        _require_enabled()
        enforce_same_origin(request)
        await service.request_otp(
            realm=realm, subject_id=verified.subject_id, purpose=payload.purpose
        )
        return Response(status_code=202)

    @router.post(
        "/otp/verify",
        status_code=204,
        response_model=None,
        summary="Spend one guess against the live one-time code",
    )
    async def otp_verify(
        payload: OtpConfirmIn, request: Request, verified: VerifiedSession = Depends(authed)
    ) -> Response:
        _require_enabled()
        enforce_same_origin(request)
        await service.confirm_otp(
            realm=realm,
            subject_id=verified.subject_id,
            purpose=payload.purpose,
            code=payload.code,
            ip=client_request_ip(request),
        )
        return Response(status_code=204)

    if realm == stepup.STEP_UP_REALM:

        @router.post(
            "/step-up",
            status_code=202,
            response_model=None,
            # An empty 202 — see the sibling routes above for why `response_class`
            # matters here (D-303).
            response_class=Response,
            summary="Email a code to re-prove this operator's second factor before a "
            "dangerous action",
        )
        async def step_up_request(
            request: Request, verified: VerifiedSession = Depends(authed)
        ) -> Response:
            """The first half of C-09 (D-178).

            ADMIN REALM ONLY, declared rather than refused — same structural choice as
            `/bootstrap/confirm`. The client realm requires no second factor
            (`service.MFA_REQUIRED_REALMS`), so a client-realm step-up would be a route
            with nothing to re-prove and nobody to call it.

            Depends on `authed`, not `live`: step-up RE-proves a factor, so a session that
            has never proved one is at the ordinary sign-in gate, not this one.
            """
            _require_enabled()
            enforce_same_origin(request)
            await service.request_step_up(verified=verified)
            return Response(status_code=202)

        @router.post(
            "/step-up/verify",
            response_model=SessionOut,
            summary="Answer the step-up code, restamping this session's second factor",
        )
        async def step_up_verify(
            payload: SecondFactorIn,
            request: Request,
            response: Response,
            verified: VerifiedSession = Depends(authed),
        ) -> SessionOut:
            """Rotates the session — see `service.complete_step_up` on why re-proving a
            factor is a privilege change and why it cannot extend the absolute bound."""
            _require_enabled()
            enforce_same_origin(request)
            rotated = await service.complete_step_up(
                verified=verified, code=payload.code, ip=client_request_ip(request)
            )
            _set_cookie(response, request, realm, rotated)
            return await _session_out(realm, verified.subject_id, mfa_complete=True)

    if realm == bootstrap.ADMIN_REALM:

        @router.post(
            "/bootstrap/confirm",
            status_code=204,
            response_model=None,
            summary="Set the first administrator's password from a bootstrap setup link",
        )
        async def bootstrap_confirm(payload: BootstrapConfirmIn, request: Request) -> Response:
            """The redemption half of `scripts/bootstrap_admin.py` (D-171).

            UNAUTHENTICATED, necessarily — it is how a deployment acquires its first
            operator, and there is nobody to authenticate as until it succeeds. What stands
            in its place is the token: 256 bits, mailed to an address a deploying operator
            named, single-use, one hour, and refused outright once the named account has a
            password. A leaked link from a finished deploy opens nothing.

            ADMIN REALM ONLY, and enforced structurally — this route is not declared on the
            client realm's router at all, rather than being declared and then refusing.
            A client-realm `/bootstrap/confirm` would be a 404, which is the correct answer
            for a route that should not exist there.
            """
            _require_enabled()
            enforce_same_origin(request)
            await bootstrap.confirm_bootstrap(
                token=payload.token,
                password=payload.password,
                ip=client_request_ip(request),
            )
            return Response(status_code=204)

    return router


async def _session_out(realm: str, subject_id: UUID, *, mfa_complete: bool) -> SessionOut:
    """The bootstrap payload, built from a FRESH read of the subject."""
    subject = await service.find_subject_for_session(realm, subject_id)
    if subject is None:
        # The account went away between the session check and here. Same refusal as a dead
        # session, because to the caller it is one.
        raise ProblemError.unauthorized("Your session is not valid. Sign in again.")
    return SessionOut(
        realm=realm,
        subject_id=subject.subject_id,
        mfa_complete=mfa_complete,
        email_verified=subject.email_verified_at is not None,
    )


admin_auth_router = _realm_router("admin")
client_auth_router = _realm_router("client")


# ──────────────────────── the invitation redemption ──────────────────────────
#
# Its own router rather than a route on the client realm's, because it is the one endpoint
# here that is NOT an operation on an existing identity — it creates one. Same prefix
# family, so `core/ratelimit.RULES`'s `/v1/auth/**` → `auth` profile still covers it and
# nothing new has to be declared.

invite_router = APIRouter(prefix="/v1/auth/client", tags=["auth-client"])


@invite_router.post(
    "/invitations/accept",
    response_model=InviteAcceptWithPasswordOut,
    summary="Redeem an invitation: create the account, set a password, join the workspace",
)
async def accept_invitation_with_password(
    payload: InviteAcceptWithPasswordIn, request: Request, response: Response
) -> InviteAcceptWithPasswordOut:
    """THE invitation-redemption endpoint. There is no other (D-177).

    It needs no prior account, because there is no vendor to have made one: it takes the
    password in the same call, and takes the address from the invitation rather than
    comparing two. The Clerk-era `POST /v1/invitations/accept` is deleted, and
    `/invite?token=` answers `410 Gone` naming the page that replaced it.
    """
    _require_enabled()
    enforce_same_origin(request)
    accepted = await invitations.accept_with_password(
        token=payload.token,
        password=payload.password,
        name=payload.name,
        ip=client_request_ip(request),
    )
    set_session_cookie(
        response,
        realm=invitations.INVITE_REALM,
        token=accepted.session.token,
        request=request,
    )
    return InviteAcceptWithPasswordOut(
        tenant_id=accepted.tenant_id, slug=accepted.slug, role=accepted.role
    )


__all__ = ["admin_auth_router", "client_auth_router", "invite_router"]
