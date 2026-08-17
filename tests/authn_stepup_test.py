"""Step-up re-authentication (C-09, D-178) — the half that was `X-Confirm-Action` only.

Two obligations, two kinds of evidence, and this file's job is to prove that a dangerous
mutation cannot be reached by satisfying one of them:

    X-Confirm-Action                       INTENT   — this screen meant to send THIS action
    a second factor proved in the last 5m  PRESENCE — the person at the keyboard is still them

`core/auth.py` records why freshness was NOT enforced before: Clerk models it as
"reverification", this repo had no browser flow to raise the prompt, and gating an incident
lever on a flow that does not exist is a control that gets switched off. D-170's emailed OTP
IS that flow, so the objection is spent — and `POST /v1/auth/admin/step-up` is the endpoint
the refusal below points an operator at.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints, the fixture deletes
exactly those, and nothing counts globally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from apps.api.authn import otp, service
from apps.api.authn.cookies import COOKIE_NAMES, cookie_name
from apps.api.authn.credentials import set_password
from apps.api.authn.models import OTP_PURPOSES
from apps.api.authn.sessions import IssuedSession, issue_session, verify_session
from apps.api.authn.stepup import (
    REAUTH_MAX_AGE,
    current_admin_session,
    require_fresh_second_factor,
)
from apps.api.authn.throttle import KEY_PREFIX
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.core.stepup import require_step_up
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text
from starlette.requests import Request

PASSWORD = "operator-console-passphrase"
ACTION = "halt_outbound"


@pytest_asyncio.fixture
async def operator() -> AsyncIterator[uuid.UUID]:
    """One admin-realm operator with a password. Sessions are minted per test."""
    admin_id = uuid.uuid4()
    email = f"stepup-{admin_id.hex[:10]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, email, name, role, "
                "created_at, updated_at) "
                "VALUES (:id, NULL, :email, 'Step Up Probe', 'superadmin', now(), now())"
            ),
            {"id": admin_id, "email": email},
        )
    async with credential_session() as session:
        await set_password(session, realm="admin", subject_id=admin_id, password=PASSWORD)
    try:
        yield admin_id
    finally:
        async with credential_session() as session:
            for table in ("auth_otp_challenges", "auth_sessions", "auth_credentials"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = :s"), {"s": admin_id}
                )
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE payload->>'to' = :to"), {"to": email}
            )
            await session.execute(text("DELETE FROM admin_users WHERE id = :s"), {"s": admin_id})
        redis = get_redis()
        for budget in ("password", "otp"):
            await redis.delete(f"{KEY_PREFIX}:{budget}:admin:{admin_id}")


async def _session_with_factor_aged(admin_id: uuid.UUID, age: timedelta) -> IssuedSession:
    """A live admin session whose second factor was proved `age` ago.

    The column is written directly rather than by winding a clock, because what is under
    test is the READ — whether the gate compares `mfa_verified_at` to now correctly — and
    driving it through `sign_in` plus a code would test the sign-in flow a second time.
    """
    at = datetime.now(UTC)
    async with credential_session() as session:
        issued = await issue_session(session, realm="admin", subject_id=admin_id, now=at)
        await session.execute(
            text("UPDATE auth_sessions SET mfa_verified_at = :when WHERE id = :id"),
            {"when": at - age, "id": issued.session_id},
        )
    return issued


def _request(cookies: dict[str, str] | None = None) -> Request:
    raw = [(b"host", b"api")]
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/ops/platform",
            "raw_path": b"/v1/ops/platform",
            "query_string": b"",
            "headers": raw,
            "scheme": "http",
            "server": ("api", 80),
            "client": ("203.0.113.9", 5000),
            "root_path": "",
        }
    )


# ═══════════════ the schema and the vocabulary ═══════════════


@pytest.mark.asyncio
async def test_the_step_up_purpose_is_admissible_in_the_database_not_only_in_python() -> None:
    """`OTP_PURPOSES` and the CHECK constraint migration `c7a1e93d40b8` rewrote have to
    agree; a purpose Python allows and Postgres rejects is a challenge that cannot be
    minted, discovered at the worst moment."""
    assert service.STEP_UP == "step_up"
    assert service.STEP_UP in OTP_PURPOSES
    async with credential_session() as session:
        definition = (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_auth_otp_challenges_purpose_enum'"
                )
            )
        ).scalar()
    assert definition is not None
    for purpose in OTP_PURPOSES:
        assert f"'{purpose}'" in definition, f"{purpose} is not admissible in the database"


# ═══════════════ the gate ═══════════════


@pytest.mark.asyncio
async def test_a_stale_second_factor_refuses_the_mutation_and_names_the_way_out(
    operator: uuid.UUID,
) -> None:
    issued = await _session_with_factor_aged(operator, REAUTH_MAX_AGE + timedelta(minutes=1))
    request = _request({cookie_name("admin", secure=False): issued.token})

    with pytest.raises(ProblemError) as caught:
        await require_fresh_second_factor(request, ACTION)

    problem = caught.value
    assert problem.code == "reauthentication_required"
    assert problem.status == 403
    # An operator mid-incident must not have to read the source to get past this.
    assert "/v1/auth/admin/step-up" in (problem.remediation or "")
    assert ACTION in (problem.remediation or "")


@pytest.mark.asyncio
async def test_a_fresh_second_factor_passes(operator: uuid.UUID) -> None:
    issued = await _session_with_factor_aged(operator, timedelta(seconds=30))
    await require_fresh_second_factor(
        _request({cookie_name("admin", secure=False): issued.token}), ACTION
    )


@pytest.mark.asyncio
async def test_a_session_that_never_proved_a_factor_is_refused(operator: uuid.UUID) -> None:
    """A half-authenticated admin session — password accepted, code unanswered — has a NULL
    `mfa_verified_at`, and "never" must not read as "just now"."""
    at = datetime.now(UTC)
    async with credential_session() as session:
        issued = await issue_session(session, realm="admin", subject_id=operator, now=at)
    with pytest.raises(ProblemError) as caught:
        await require_fresh_second_factor(
            _request({cookie_name("admin", secure=False): issued.token}), ACTION
        )
    assert caught.value.code == "reauthentication_required"


@pytest.mark.asyncio
async def test_a_request_with_no_first_party_session_is_not_this_gate_s_business() -> None:
    """`authn/stepup.py`'s docstring makes this claim and it is the one a reviewer will
    challenge: freshness is a property OF A CREDENTIAL, and a caller presenting no
    first-party session presented some other credential with its own gates. It is not a
    bypass that survives — deleting Clerk leaves no other credential, at which point this
    branch is unreachable rather than permissive."""
    await require_fresh_second_factor(_request(), ACTION)
    await require_fresh_second_factor(_request({"unrelated": "x"}), ACTION)


@pytest.mark.asyncio
async def test_a_dead_cookie_is_treated_as_no_session_rather_than_as_a_fresh_one() -> None:
    assert await current_admin_session(_request({cookie_name("admin"): "not-a-token"})) is None


@pytest.mark.asyncio
async def test_a_client_realm_cookie_does_not_satisfy_the_admin_gate(
    operator: uuid.UUID,
) -> None:
    """The realm is inside the token's hash domain, so a client token presented under the
    admin cookie name verifies as nothing at all."""
    at = datetime.now(UTC)
    async with credential_session() as session:
        client_side = await issue_session(session, realm="client", subject_id=operator, now=at)
        await session.execute(
            text("UPDATE auth_sessions SET mfa_verified_at = :when WHERE id = :id"),
            {"when": at, "id": client_side.session_id},
        )
    assert (
        await current_admin_session(
            _request({cookie_name("admin", secure=False): client_side.token})
        )
        is None
    )
    async with credential_session() as session:
        await session.execute(
            text("DELETE FROM auth_sessions WHERE id = :id"), {"id": client_side.session_id}
        )


# ═══════════════ both halves, together ═══════════════


@pytest.mark.asyncio
async def test_the_echo_check_still_fires_first_and_alone(operator: uuid.UUID) -> None:
    """A caller who forgot the header is told so without a round trip to the session
    store, and the refusal still prints the exact string to send."""
    issued = await _session_with_factor_aged(operator, timedelta(seconds=5))
    request = _request({cookie_name("admin", secure=False): issued.token})
    with pytest.raises(ProblemError) as caught:
        await require_step_up(None, ACTION, request=request)
    assert caught.value.code == "step_up_required"
    assert f"X-Confirm-Action: {ACTION}" in (caught.value.remediation or "")


@pytest.mark.asyncio
async def test_the_right_header_is_not_enough_on_a_stale_session(operator: uuid.UUID) -> None:
    """THE GAP C-09 NAMED. Before D-178 this call returned `None` and the mutation went
    ahead on the strength of a header anybody holding the cookie can send."""
    issued = await _session_with_factor_aged(operator, REAUTH_MAX_AGE + timedelta(seconds=1))
    request = _request({cookie_name("admin", secure=False): issued.token})
    with pytest.raises(ProblemError) as caught:
        await require_step_up(ACTION, ACTION, request=request)
    assert caught.value.code == "reauthentication_required"


@pytest.mark.asyncio
async def test_both_halves_satisfied_passes(operator: uuid.UUID) -> None:
    issued = await _session_with_factor_aged(operator, timedelta(seconds=5))
    await require_step_up(
        ACTION, ACTION, request=_request({cookie_name("admin", secure=False): issued.token})
    )


def test_every_dangerous_mutation_takes_the_composed_gate_rather_than_half_of_it() -> None:
    """The census, so a new dangerous route cannot take the echo check alone.

    `require_step_up` is now the ONLY way to spell either half — `authn.stepup.
    require_fresh_second_factor` is called from exactly one place — so this walks the repo
    and asserts that every call site passes a request, which is the argument the freshness
    half needs to run at all.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "apps" / "api"
    sites = 0
    for path in sorted(root.rglob("*.py")):
        if path.name == "stepup.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name != "require_step_up":
                continue
            sites += 1
            assert any(k.arg == "request" for k in node.keywords), (
                f"{path}:{node.lineno} takes the intent half without the presence half"
            )
    assert sites >= 12, f"found only {sites} step-up call sites; the census went stale"


# ═══════════════ the flow that clears the refusal ═══════════════


@pytest.mark.asyncio
async def test_the_step_up_flow_restamps_the_factor_without_extending_the_session(
    operator: uuid.UUID,
) -> None:
    """The whole point: an operator refused at 3am can clear it from the screen they were
    refused on. And re-proving a factor must not become a session-renewal loop, so
    `absolute_expires_at` is carried forward rather than recomputed."""
    issued = await _session_with_factor_aged(operator, REAUTH_MAX_AGE + timedelta(minutes=5))
    stale = (await verify_session(token=issued.token, realm="admin")).require_live()

    await service.request_step_up(verified=stale)
    async with credential_session() as session:
        code = (
            await otp.issue_challenge(
                session, purpose=service.STEP_UP, realm="admin", subject_id=operator
            )
        ).code

    rotated = await service.complete_step_up(verified=stale, code=code, ip=None)
    fresh = (await verify_session(token=rotated.token, realm="admin")).require_live()

    assert fresh.mfa_verified_at is not None
    assert datetime.now(UTC) - fresh.mfa_verified_at < timedelta(seconds=30)
    assert fresh.absolute_expires_at == stale.absolute_expires_at, (
        "re-proving a factor extended the session's absolute bound"
    )
    await require_fresh_second_factor(
        _request({cookie_name("admin", secure=False): rotated.token}), ACTION
    )


@pytest.mark.asyncio
async def test_a_sign_in_code_does_not_answer_a_step_up_prompt(operator: uuid.UUID) -> None:
    """Why the purpose is separate. The purpose is inside the code's HMAC domain, so a
    `login_challenge` code presented to the step-up verifier matches no row — and the
    reverse would mean a code minted to finish signing in could lift the big red switch."""
    issued = await _session_with_factor_aged(operator, REAUTH_MAX_AGE + timedelta(minutes=1))
    stale = (await verify_session(token=issued.token, realm="admin")).require_live()
    async with credential_session() as session:
        login_code = (
            await otp.issue_challenge(
                session, purpose=service.LOGIN_CHALLENGE, realm="admin", subject_id=operator
            )
        ).code
        await otp.issue_challenge(
            session, purpose=service.STEP_UP, realm="admin", subject_id=operator
        )

    with pytest.raises(ProblemError) as caught:
        await service.complete_step_up(verified=stale, code=login_code, ip=None)
    assert caught.value.code == "invalid_second_factor"


@pytest.mark.asyncio
async def test_requesting_a_step_up_code_does_not_retire_a_pending_sign_in_code(
    operator: uuid.UUID,
) -> None:
    """The other direction of the same separation, and the one that would have been a live
    bug: an operator mid-way through typing their sign-in code must not have it silently
    retired by a step-up request from another tab."""
    issued = await _session_with_factor_aged(operator, timedelta(seconds=5))
    live = (await verify_session(token=issued.token, realm="admin")).require_live()
    async with credential_session() as session:
        await otp.issue_challenge(
            session, purpose=service.LOGIN_CHALLENGE, realm="admin", subject_id=operator
        )

    await service.request_step_up(verified=live)

    async with credential_session() as session:
        still_live = (
            await session.execute(
                text(
                    "SELECT count(*) FROM auth_otp_challenges WHERE subject_id = :s "
                    "AND purpose = :p AND consumed_at IS NULL"
                ),
                {"s": operator, "p": service.LOGIN_CHALLENGE},
            )
        ).scalar()
    assert still_live == 1


def test_the_window_is_tighter_than_the_session_it_guards() -> None:
    """A step-up window at or above the admin idle bound would be satisfied by every
    session that is live at all — a control that never fires."""
    from apps.api.authn.sessions import REALM_TIMEOUTS

    assert REALM_TIMEOUTS["admin"].idle > REAUTH_MAX_AGE
    assert COOKIE_NAMES["admin"].startswith("__Host-")
