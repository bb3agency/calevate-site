"""Every route that SPENDS a one-time code demands a session first.

This is a small file for one property, and it exists because a paragraph in
`authn/service.confirm_password_reset` reasons from it.

A password reset burns outstanding `password_reset` TOKENS and revokes every session, but
it deliberately does NOT retire outstanding OTP CHALLENGES (`auth_otp_challenges`) — a
live `email_verify`, `login_challenge` or `step_up` code survives it. That is safe for
exactly one reason: none of those codes can be presented without a session, and the reset
just revoked every session this subject had, `mfa_verified_at IS NULL` ones included. The
surviving secret has no door.

`core/rbac.PUBLIC_PREFIXES` contains `/v1/auth/`, so the repo-wide public-route sweep in
`tests/public_routes_guard_test.py` deliberately does not assert a credential on this
router — these are the routes an anonymous stranger MUST be able to reach. So nothing else
in this suite pins the half the reset argument leans on, and an OTP purpose added later
behind an anonymous endpoint would silently invalidate that argument with no test going
red. This is that test.

It drives the real routers over ASGI with no cookie at all, because a dependency read out
of `route.dependant` would assert the wiring rather than the behaviour — and the behaviour
is the claim.
"""

from __future__ import annotations

import pytest
from apps.api.authn.routes import admin_auth_router, client_auth_router
from apps.api.core.errors import install_error_handlers
from apps.api.core.settings import get_settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

#: Path suffix → a body that passes Pydantic, so a 422 cannot be mistaken for a refusal.
#: The values are shaped, not real: nothing here should get far enough to be checked.
_OTP_REDEEMING_ROUTES: dict[str, dict[str, object]] = {
    # Prove a mailbox (client realm only) — the code that clears `email_verified_at`, and
    # therefore the one that now unlocks `POST /v1/auth/signup`.
    "/otp/verify": {"purpose": "email_verify", "code": "123456"},
    # The second factor itself (D-170) — the only thing a password-but-no-MFA session may do.
    "/login/otp": {"code": "123456"},
    # Step-up presence (D-178), admin realm only.
    "/step-up/verify": {"code": "123456"},
}


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(admin_auth_router)
    application.include_router(client_auth_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


def _mounted_otp_routes() -> list[str]:
    """The OTP-redeeming paths this build actually serves.

    ENUMERATED FROM THE APP, not typed out, so a realm that gains one of these routes is
    covered the moment it does. `/step-up/verify` is admin-only and `/otp/verify` is
    client-only today, and neither fact is asserted here — this file is about what a
    caller with no session is told, not about which realm has which route.
    """
    # Read off the OpenAPI document rather than `app.routes`: this FastAPI keeps an
    # included router as an `_IncludedRouter` with no `.path`, so walking `routes` sees
    # the wrapper and not the endpoints. The schema is also the surface the generated
    # client is built from, which makes it the right thing to enumerate anyway.
    paths = {
        path
        for path in _app().openapi()["paths"]
        if any(path.endswith(suffix) for suffix in _OTP_REDEEMING_ROUTES)
    }
    assert paths, "no OTP-redeeming routes found — the suffixes below have gone stale"
    return sorted(paths)


@pytest.mark.parametrize("path", _mounted_otp_routes())
async def test_an_otp_cannot_be_spent_without_a_session(path: str) -> None:
    """401, on every realm that has the route.

    A 200 or a 422 here would mean a surviving code is redeemable by whoever holds it,
    which is the case `confirm_password_reset` argues cannot arise.
    """
    if not get_settings().first_party_auth_enabled:
        pytest.skip("first-party auth is off in this configuration")

    suffix = next(s for s in _OTP_REDEEMING_ROUTES if path.endswith(s))
    async with _client() as client:
        response = await client.post(path, json=_OTP_REDEEMING_ROUTES[suffix])

    assert response.status_code == 401, f"{path} answered {response.status_code}: {response.text}"
    # And it is an authentication refusal rather than something that merely shares the
    # status — the distinction the RFC-9457 `type` carries.
    assert response.json()["type"].endswith("/unauthorized"), response.text
