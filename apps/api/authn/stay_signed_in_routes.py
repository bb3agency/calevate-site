"""`POST /v1/auth/admin/stay-signed-in` — an operator's own "Stay signed in" switch (D-766).

On the admin realm's auth prefix, beside `/password/change`, because it is the same kind of
act: a change to the caller's own credential, taken from the session the router holds, with
the cookie re-set in the same response. There is no client-realm spelling: the client realm
already has the long bounds and has no switch.

Not reachable from `/v1/admin/config` or any other platform-setting form, and it names no
account: the only account it can change is the one whose session sent it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from apps.api.authn import stay_signed_in, stepup
from apps.api.authn.cookies import enforce_same_origin, read_token, set_session_cookie
from apps.api.authn.routes import SessionOut, _authenticated, _require_enabled, _session_out
from apps.api.authn.sessions import STAY_SIGNED_IN_REALM, VerifiedSession, session_policy
from apps.api.core.auth import client_request_ip
from apps.api.core.errors import ProblemError

router = APIRouter(prefix=f"/v1/auth/{STAY_SIGNED_IN_REALM}", tags=[f"auth-{STAY_SIGNED_IN_REALM}"])

#: The step-up action name the refusal prints, and the one the console's prompt names.
STEP_UP_ACTION = "stay_signed_in"


class StaySignedInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stay_signed_in: bool


@dataclass(frozen=True, slots=True)
class _Caller:
    verified: VerifiedSession
    #: The cookie value this request presented, re-set by the route with a new `Max-Age`.
    token: str


async def _caller(request: Request) -> _Caller:
    """The verified admin session and its token. The token is read first so the route can
    re-set it; `_authenticated` then verifies it and applies the second-factor gate."""
    token = read_token(request, STAY_SIGNED_IN_REALM)
    if not token:
        raise ProblemError.unauthorized("Your session is not valid. Sign in again.")
    return _Caller(verified=await _authenticated(request, STAY_SIGNED_IN_REALM), token=token)


Caller = Annotated[_Caller, Depends(_caller)]


@router.post(
    "/stay-signed-in",
    response_model=SessionOut,
    summary="Switch 'Stay signed in' on or off for your own operator account",
    description=(
        "On: this operator's sessions may sit idle for 12 hours and last 14 days, and this "
        "browser keeps its cookie when it closes. Switching it on needs a second factor "
        "proved in the last 30 minutes (`reauthentication_required` otherwise). Off: every "
        "session of this operator goes back to 30 minutes idle and 8 hours from sign-in, "
        "and one already past those ends. Every change is audited."
    ),
)
async def set_stay_signed_in(
    payload: StaySignedInIn,
    request: Request,
    response: Response,
    caller: Caller,
) -> SessionOut:
    """Freshness only, no `X-Confirm-Action`, for the reason `password/change` gives: the
    act touches nothing but the caller's own account, and `enforce_same_origin` with the
    `SameSite=Strict` cookie is what stops another site sending it.

    Only switching ON asks for the fresh second factor. Switching off can only shorten
    sessions, and a person leaving a shared device should not meet a code prompt."""
    _require_enabled()
    enforce_same_origin(request)
    verified = caller.verified
    on = payload.stay_signed_in
    if on and not stepup.is_fresh(verified.mfa_verified_at):
        raise stepup.reauthentication_required(STEP_UP_ACTION)
    change = await stay_signed_in.set_own(verified=verified, on=on, ip=client_request_ip(request))
    policy = session_policy(STAY_SIGNED_IN_REALM, switch_on=on, second_factor_proved=True)
    # The same token, re-set: ON gives it a `Max-Age` to the session's new absolute bound so
    # it survives the browser closing; OFF makes it a browser-session cookie again.
    set_session_cookie(
        response,
        realm=STAY_SIGNED_IN_REALM,
        token=caller.token,
        request=request,
        absolute_expires_at=change.absolute_expires_at,
        stay_signed_in=policy.stay_signed_in,
    )
    return await _session_out(
        STAY_SIGNED_IN_REALM, verified.subject_id, mfa_complete=True, policy=policy
    )


__all__ = ["STEP_UP_ACTION", "StaySignedInIn", "router"]
