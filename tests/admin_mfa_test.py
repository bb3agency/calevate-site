"""Admin-realm MFA: mandatory in the docs since day one, absent from the tree until now.

TRD §2 ("MFA mandatory on admin realm") and SEC-COMP §5 both stated it; no code enforced
it, and two live comments conceded as much — `ops/routes.py` was candid that the
`X-Confirm-Action` header "is not a strong second factor", and `apps/web`'s
`useSetPlatformState` said Clerk re-auth would replace it "when the admin realm's MFA
lands". This file is what makes the sentence in the docs true of the running system.

WHAT IS ASSERTED, AND WHY EACH IS A REGRESSION IF IT FLIPS

1. **A privileged admin call is REFUSED without a second factor**, at the highest-value
   route there is: `POST /v1/ops/platform`, the big red switch. A step-up header that is
   otherwise perfectly valid does not rescue it — MFA is checked at the door, before any
   route dependency runs, so the confirmation never gets a chance to stand in for it.
2. **The same call is ALLOWED with one.** A gate that refuses everything proves nothing;
   this is the half that fails if the predicate is inverted or the claim misread.
3. **A CLIENT-realm session is untouched.** The requirement is admin-only. Breaking
   client sign-in to add admin MFA would be a bad trade, and it is the failure most
   likely to be introduced by putting the check in the shared verifier — which is
   exactly where it is (`core/auth.py::verify_token`).
4. **The claim predicate matches Clerk's**, including that an ABSENT `fva` is a refusal
   rather than a pass. That is the case a misconfigured JWT template produces, and
   reading "unknown" as "verified" would silently disable the whole control.

THE REFUSAL IS THE SUBJECT, so almost nothing here moves state. Exactly one test flips
the global halt (it must, to prove the allowed direction is really allowed) and restores
it in `finally` — the pattern `platform_audit_test` established for the one row every
other suite shares.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.core import auth as auth_module
from apps.api.core.errors import ProblemError
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.routes import platform_confirmation
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.authz_audit_test import _make_member, _make_org

OPS_PLATFORM = "/v1/ops/platform"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _without_second_factor(token: str) -> str:
    """The same operator, signed in but never having completed a second factor.

    `dev:<realm>:<id>:nomfa` is the local stand-in for Clerk's `fva: [n, -1]` — see
    `core/auth.py::DEV_TOKEN_NO_MFA_SUFFIX`. Derived from the admin's own token rather
    than built from a second string, so the two halves of every assertion below are the
    SAME admin_users row and the only difference is the second factor.
    """
    return f"{token}:{auth_module.DEV_TOKEN_NO_MFA_SUFFIX}"


@pytest.fixture(autouse=True)
async def platform_must_still_dial() -> AsyncIterator[None]:
    """Whatever happens in this file, the shared platform row leaves it un-halted.

    Not belt-and-braces. The whole point of the tests below is that the big red switch is
    UNREACHABLE without a second factor, so the way they fail is by reaching it — a
    regression, or a deliberate sabotage rehearsal of the gate, halts every other suite's
    dialling on the one row the whole database shares. A test that stops the platform
    when it fails is a test people stop running.
    """
    yield
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE platform_state SET outbound_halted = false, halt_reason = NULL "
                "WHERE id = 1 AND outbound_halted"
            )
        )


async def _halt_state() -> tuple[bool, str | None]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT outbound_halted, halt_reason FROM platform_state WHERE id = 1")
            )
        ).first()
    assert row is not None, "the singleton is seeded by migration 769a9152cb06"
    return bool(row[0]), row[1]


# ------------------------------------------------------------------ the two directions


async def test_the_big_red_switch_is_refused_without_a_second_factor() -> None:
    """A valid superadmin, a valid step-up header, and still no halt.

    This is the test the SABOTAGE check is for: delete the gate in `verify_token` and
    this goes green, because every other control on the path — the role, the permission,
    the confirmation — is satisfied.
    """
    token = await _make_admin(role="superadmin")
    body = {"outbound_halted": True, "reason": "mfa test — must never reach the switch"}
    confirmation = platform_confirmation(outbound_halted=True, load_shed_mode=None)

    async with _client() as http:
        response = await http.post(
            OPS_PLATFORM,
            json=body,
            headers={
                "Authorization": f"Bearer {_without_second_factor(token)}",
                "X-Confirm-Action": confirmation,
            },
        )

    assert response.status_code == 403, response.text
    problem = response.json()
    assert problem["kind"] == "permission"
    assert problem["type"].endswith("/mfa_required"), problem
    # Errors are part of the interface: an operator meeting this must be told what to do,
    # not merely that they may not.
    assert "two-step" in problem["remediation"].lower(), problem

    halted, _reason = await _halt_state()
    assert halted is False, "a refused request must not have moved the platform"


async def test_a_read_on_the_admin_realm_is_refused_too() -> None:
    """MFA is authentication, so it gates the READ as well as the write.

    Stated as its own case because the obvious wrong implementation — a check bolted to
    the mutating routes, or to `MUTATING_PERMISSIONS` — passes the test above and fails
    this one, while leaving every client's data readable by a half-authenticated
    operator session.
    """
    token = await _make_admin(role="superadmin")
    async with _client() as http:
        response = await http.get(
            OPS_PLATFORM,
            headers={"Authorization": f"Bearer {_without_second_factor(token)}"},
        )
    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/mfa_required")


async def test_the_switch_moves_for_an_operator_who_completed_a_second_factor() -> None:
    """The allowed direction, on the same route, with the same admin and the same body.

    The ONLY suite-shared state this file touches. It halts, asserts, and releases in
    `finally` — a halt left behind stops every other suite's dialling.
    """
    token = await _make_admin(role="superadmin")
    reason = "mfa test — halted and released in the same test"
    halt_confirmation = platform_confirmation(outbound_halted=True, load_shed_mode=None)
    release_confirmation = platform_confirmation(outbound_halted=False, load_shed_mode=None)

    async with _client() as http:
        try:
            response = await http.post(
                OPS_PLATFORM,
                json={"outbound_halted": True, "reason": reason},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Confirm-Action": halt_confirmation,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["outbound_halted"] is True
        finally:
            released = await http.post(
                OPS_PLATFORM,
                json={"outbound_halted": False, "reason": "mfa test cleanup"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Confirm-Action": release_confirmation,
                },
            )
            assert released.status_code == 200, released.text

    halted, _reason = await _halt_state()
    assert halted is False, "the suite must leave the platform dialling"


async def test_mfa_is_checked_before_the_step_up_header() -> None:
    """Ordering matters, and it is the ordering that says which control is which.

    A session with no second factor and NO confirmation must be told about the second
    factor — not about the header. Otherwise an operator without MFA is walked through
    typing a confirmation that can never work, and the console's refusal is a lie about
    which requirement they failed.
    """
    token = await _make_admin(role="superadmin")
    async with _client() as http:
        response = await http.post(
            OPS_PLATFORM,
            json={"outbound_halted": True, "reason": "mfa test — no header at all"},
            headers={"Authorization": f"Bearer {_without_second_factor(token)}"},
        )
    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/mfa_required")


# --------------------------------------------------------- the client realm is untouched


async def test_a_client_session_needs_no_second_factor() -> None:
    """SEC-COMP §5 requires MFA on ADMIN. A client owner signs in exactly as before.

    The check lives in the shared verifier, which is the right place (there is no way to
    obtain an admin identity that skipped it) and is also the one place a mistake would
    lock every client out of their own dashboard. So the negative is pinned here.
    """
    org = await _make_org()
    _user_id, token = await _make_member(uuid.UUID(str(org["id"])))

    async with _client() as http:
        response = await http.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])},
        )
    assert response.status_code == 200, response.text


async def test_the_client_realm_has_no_mfa_gate_at_the_verifier() -> None:
    """The unit-level statement of the same fact, so the policy is readable in one line.

    `verify_token` is what an admin identity must pass through; asserting the realm set
    here means a future change that adds `"client"` to it fails a test that names the
    decision, rather than surfacing as every client screen answering 403.
    """
    assert set(auth_module.MFA_REQUIRED_REALMS) == {"admin"}

    verified = await auth_module.verify_token("dev:client:user_whoever", "client")
    assert verified.clerk_user_id == "user_whoever"
    # A client token carries no `fva` and nothing asks it to.
    assert verified.second_factor_age_min in (0, None)


# ------------------------------------------------------- the claim predicate, exactly


def test_the_second_factor_age_is_read_the_way_clerk_writes_it() -> None:
    """Clerk's `fva` is `[firstFactorAgeMinutes, secondFactorAgeMinutes]`, `-1` = never.

    Pinned against the shapes a real token takes (`[0, -1]` for a user with no second
    factor, `[9, 3]` for one who completed both) and against the shapes a MISCONFIGURED
    or hostile token takes. `[true, true]` is in the list because `bool` is an `int` in
    Python: without the explicit check, a token claiming `fva: [true, true]` would read
    as "second factor verified 1 minute ago".
    """
    read = auth_module._second_factor_age_minutes
    assert read({"fva": [0, -1]}) == -1
    assert read({"fva": [9, 3]}) == 3
    assert read({"fva": [0, 0]}) == 0

    # Every one of these means "we cannot tell", which the gate treats as a refusal.
    assert read({}) is None
    assert read({"fva": None}) is None
    assert read({"fva": [0]}) is None
    assert read({"fva": "0,-1"}) is None
    assert read({"fva": [True, True]}) is None
    assert read({"fva": [0, "3"]}) is None


def test_an_unreadable_claim_fails_closed_with_a_different_code() -> None:
    """A refusal saying "we could not check" is not one saying "you did not do it".

    A missing `fva` is an OPERATOR's problem — the admin Clerk application is issuing a
    custom session token that drops the claim — while `-1` is the signed-in person's. One
    code for both would send an operator to enrol a factor they already have.
    """
    with pytest.raises(ProblemError) as missing:
        auth_module._require_second_factor("admin", None)
    assert missing.value.code == "mfa_claim_missing"
    assert missing.value.status == 403

    with pytest.raises(ProblemError) as never:
        auth_module._require_second_factor("admin", -1)
    assert never.value.code == "mfa_required"

    # And the two that must NOT raise.
    auth_module._require_second_factor("admin", 0)
    auth_module._require_second_factor("client", -1)


async def test_an_unrecognised_dev_token_suffix_is_not_a_pass() -> None:
    """`dev:admin:<id>:mfa` must be refused, not read as "no suffix I know, so allow".

    The lenient reading is the dangerous direction on the one realm this gate protects,
    and a four-segment token is exactly what someone reaching for a bypass would try.
    """
    with pytest.raises(ProblemError) as exc:
        await auth_module.verify_token("dev:admin:admin_whoever:mfa", "admin")
    # 401: it is not a valid dev token at all, so it never reaches the MFA question.
    assert exc.value.status == 401
