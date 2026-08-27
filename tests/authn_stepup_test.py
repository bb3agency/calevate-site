"""Step-up re-authentication (C-09, D-178) — the half that was `X-Confirm-Action` only.

Two obligations, two kinds of evidence, and this file's job is to prove that a dangerous
mutation cannot be reached by satisfying one of them:

    X-Confirm-Action                       INTENT   — this screen meant to send THIS action
    a second factor proved recently        PRESENCE — the person at the keyboard is still them

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
from apps.api.authn.stepup import REAUTH_MAX_AGE, current_admin_session, is_fresh
from apps.api.authn.throttle import KEY_PREFIX
from apps.api.core import auth as auth_module
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.core.stepup import step_up_gate
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
        (await step_up_gate(request)).require(ACTION, ACTION)

    problem = caught.value
    assert problem.code == "reauthentication_required"
    assert problem.status == 403
    # An operator mid-incident must not have to read the source to get past this.
    assert "/v1/auth/admin/step-up" in (problem.remediation or "")
    assert ACTION in (problem.remediation or "")


@pytest.mark.asyncio
async def test_a_fresh_second_factor_passes(operator: uuid.UUID) -> None:
    issued = await _session_with_factor_aged(operator, timedelta(seconds=30))
    gate = await step_up_gate(_request({cookie_name("admin", secure=False): issued.token}))
    gate.require(ACTION, ACTION)


@pytest.mark.asyncio
async def test_a_session_that_never_proved_a_factor_is_refused(operator: uuid.UUID) -> None:
    """A half-authenticated admin session — password accepted, code unanswered — has a NULL
    `mfa_verified_at`, and "never" must not read as "just now"."""
    at = datetime.now(UTC)
    async with credential_session() as session:
        issued = await issue_session(session, realm="admin", subject_id=operator, now=at)
    gate = await step_up_gate(_request({cookie_name("admin", secure=False): issued.token}))
    assert gate.present and gate.verified_at is None
    with pytest.raises(ProblemError) as caught:
        gate.require(ACTION, ACTION)
    assert caught.value.code == "reauthentication_required"


@pytest.mark.asyncio
async def test_a_request_with_no_first_party_session_is_refused_off_a_dev_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The branch that used to return unconditionally, pinned from both sides.

    It returned because a caller with no first-party session had presented a Clerk token —
    a real credential with its own gates — and freshness is a property OF A CREDENTIAL.
    D-177 deleted that credential, so the only thing left that reaches an admin route
    without our cookie is the local `dev:admin:<uuid>` token. On a deployment that will not
    honour one, `present=False` is now a refusal rather than a pass, because a returning
    branch whose reason has expired is a gate with a hole in it.

    Both directions are asserted from the SAME call, so the test fails if the branch is
    made unconditional in either direction.
    """
    for keyless, refuses in ((True, False), (False, True)):
        settings = auth_module.get_settings().model_copy(
            update={
                "app_env": "local" if keyless else "prod",
                "platform_kek": None if keyless else "a-real-looking-key-0000000000000000",
            }
        )
        monkeypatch.setattr(auth_module, "get_settings", lambda s=settings: s)
        gate = await step_up_gate(_request())
        assert gate.present is False
        if refuses:
            with pytest.raises(ProblemError) as exc:
                gate.require(ACTION, ACTION)
            assert exc.value.code == "reauthentication_required"
        else:
            gate.require(ACTION, ACTION)
            (await step_up_gate(_request({"unrelated": "x"}))).require(ACTION, ACTION)


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
        (await step_up_gate(request)).require(None, ACTION)
    assert caught.value.code == "step_up_required"
    assert f"X-Confirm-Action: {ACTION}" in (caught.value.remediation or "")


@pytest.mark.asyncio
async def test_the_right_header_is_not_enough_on_a_stale_session(operator: uuid.UUID) -> None:
    """THE GAP C-09 NAMED. Before D-178 this call returned `None` and the mutation went
    ahead on the strength of a header anybody holding the cookie can send."""
    issued = await _session_with_factor_aged(operator, REAUTH_MAX_AGE + timedelta(seconds=1))
    request = _request({cookie_name("admin", secure=False): issued.token})
    with pytest.raises(ProblemError) as caught:
        (await step_up_gate(request)).require(ACTION, ACTION)
    assert caught.value.code == "reauthentication_required"


@pytest.mark.asyncio
async def test_both_halves_satisfied_passes(operator: uuid.UUID) -> None:
    issued = await _session_with_factor_aged(operator, timedelta(seconds=5))
    gate = await step_up_gate(_request({cookie_name("admin", secure=False): issued.token}))
    gate.require(ACTION, ACTION)


@pytest.mark.asyncio
async def test_the_boundary_is_checked_from_both_sides(operator: uuid.UUID) -> None:
    """One second inside the window passes and one second outside it does not — the two
    assertions a `<=` comparison can get wrong in opposite directions."""
    at = datetime.now(UTC)
    async with credential_session() as session:
        issued = await issue_session(session, realm="admin", subject_id=operator, now=at)
    assert (await verify_session(token=issued.token, realm="admin")).live
    assert is_fresh(at - REAUTH_MAX_AGE + timedelta(seconds=1), now=at)
    assert not is_fresh(at - REAUTH_MAX_AGE - timedelta(seconds=1), now=at)
    assert not is_fresh(None, now=at), "never proved is not recently proved"


def test_every_dangerous_mutation_takes_the_composed_gate_rather_than_half_of_it() -> None:
    """The census, so a new dangerous route cannot take the echo check alone.

    `StepUp.require` is the ONLY way to spell either half, and the pairing is STRUCTURAL
    rather than remembered: the method cannot be called without a `StepUp`, and the only
    source of one is `Depends(step_up_gate)` — which FastAPI resolves before the handler
    body runs, so the session read never happens inside an open transaction
    (`core/stepup.py` on `max_overflow=0`). What this walk adds is the COUNT: a route that
    quietly stopped taking the gate would shrink it.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "apps" / "api"
    sites = 0
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "require"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "step_up"
            ):
                sites += 1
                assert "StepUpGate" in source, f"{path} calls the gate without declaring it"
    # 23: the twenty-two dangerous mutations, plus D-210's door —
    # `admin/routes.py::mint_impersonation_grant`, which is a step-up on ENTERING a
    # client account rather than on changing something. Counted the same way because the
    # census is about the pairing, not about the verb.
    #
    # The sixteenth mutation is `admin/routes.py::set_tenant_status`, gated on the
    # TERMINAL transition only. It was the one irreversible action on the operator console
    # reachable with nothing but a live session, while three reversible ones beside it
    # each demanded a code; found by walking the console rather than the code, because
    # `test_no_ops_console_write_can_ship_without_the_gate` below scopes itself to
    # `apps/api/ops/` and this route is not there.
    #
    # FOUR OF THE TWENTY ARE THE OPERATOR ALLOWLIST (`admin/operator_routes.py`): adding an
    # administrator, promoting or demoting one, revoking one, and re-issuing a setup link.
    # They are on this list for a reason none of the others has — their effect OUTLIVES the
    # session that performed it, so a stolen console session that adds an administrator
    # keeps a way in after the session it was stolen from has been revoked.
    #
    # THE TWENTY-FIRST MUTATION is `ops/model_price_routes.py::attest_price` (D-459):
    # a super-admin writes the per-model price that billing reads for
    # `unit_cost_paid`. Its effect OUTLIVES the session for the operator-allowlist
    # reason — a wrong or malicious price keeps charging every client on that model
    # long after the session that set it is gone — so it takes the composed gate too.
    #
    # THE TWENTY-SECOND is `ops/dashboard_data_use_routes.py::attest_provider_data_use`
    # (D-477): a super-admin attests that a vendor's terms for OUR account permit the
    # dashboard assistant to send a client's screen content to that vendor. Same
    # outlives-the-session ground and a worse blast radius than a price — a false
    # attestation keeps routing other businesses' data to a provider on terms nobody
    # checked, and unlike a wrong price nothing downstream would ever notice.
    assert sites == 23, f"found {sites} step-up call sites, expected 23; the census went stale"


#: Mutating handlers under `apps/api/ops/` that deliberately take NO step-up, and why.
#:
#: One entry, and its asymmetry is the argument the route's own docstring makes: every
#: other write on that router changes what the platform authenticates with, and this one
#: STORES NOTHING — it is a read against a vendor with a value the caller already holds.
#: Demanding a typed confirmation to run a check is how operators learn to skip the check.
_OPS_WRITES_WITHOUT_STEP_UP = {
    ("apps/api/ops/secret_routes.py", "test_secret"): (
        "probes a candidate credential against the vendor and stores nothing"
    ),
}


def test_no_ops_console_write_can_ship_without_the_gate() -> None:
    """THE OTHER DIRECTION, which the census above cannot see.

    The census above catches a route that STOPS taking the gate — the count shrinks. It
    cannot catch a route that never took it: a new `POST /v1/ops/...` with no `step_up`
    parameter adds no call site, so the count is unchanged and the census stays green while
    an unconfirmed lever ships on the incident surface. That is the half of scope this
    file's title promises and did not cover.

    Scoped to `apps/api/ops/` rather than to the whole app on purpose. Step-up is not the
    right control for every mutation — a client adding a number to their OWN DNC list is
    a tenant-scoped write in the safe direction, and gating it would be theatre. What
    makes `ops/` different is that everything on it is platform-wide and operator-only:
    the big red switch, load-shed, config, secrets, the KEK re-wrap, outbox replay. An
    exemption there has to be argued in `_OPS_WRITES_WITHOUT_STEP_UP` rather than
    remembered, and adding one is a visible diff on this file.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    mutating = {"post", "put", "patch", "delete"}
    ungated: list[str] = []
    seen = 0
    for path in sorted((root / "apps" / "api" / "ops").rglob("*.py")):
        # `.as_posix()`: `_OPS_WRITES_WITHOUT_STEP_UP` is keyed on forward slashes, so a
        # `str()` here made every exemption unmatchable on Windows and the census
        # reported argued-for handlers as ungated. It failed SAFE -- over-reporting,
        # not under -- but a guard that cries wolf on a clean tree stops being read.
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            decorators = [
                dec.func if isinstance(dec, ast.Call) else dec for dec in node.decorator_list
            ]
            if not any(
                isinstance(dec, ast.Attribute) and dec.attr in mutating for dec in decorators
            ):
                continue
            seen += 1
            if "StepUpGate" in ast.unparse(node.args):
                continue
            if (rel, node.name) in _OPS_WRITES_WITHOUT_STEP_UP:
                continue
            ungated.append(f"{rel}::{node.name}")
    # Refuses on an empty scan for `check_wiring`'s reason: a walk that stopped matching
    # would otherwise report a clean sweep of nothing, which is how a guard dies quietly.
    assert seen, "found no mutating handlers under apps/api/ops — this walk sees nothing"
    assert not ungated, (
        "these operator-console writes take no step-up gate, so an admin session alone "
        f"can throw them: {ungated}. Add the gate, or argue the exemption in "
        "_OPS_WRITES_WITHOUT_STEP_UP with the reason."
    )


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
    gate = await step_up_gate(_request({cookie_name("admin", secure=False): rotated.token}))
    gate.require(ACTION, ACTION)


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


def test_the_window_is_never_the_loosest_clock_in_the_request() -> None:
    """Step-up may equal the idle bound (D-473) but must never exceed either session bound.

    THIS TEST USED TO ASSERT A STRICT `>`, on the reasoning that a window "at or above the
    idle bound would be satisfied by every session that is live at all — a control that
    never fires". That reasoning is wrong and D-473 records why: `mfa_verified_at` is
    stamped when a factor is PROVED and is never refreshed by activity, so a session in
    its fourth hour carries a four-hour-old stamp and is challenged by any window shorter
    than four hours. Equality with the idle bound costs the first half hour after each
    proof, not the control's ability to fire.

    What genuinely must hold is the weaker statement the old one was reaching for: a
    step-up window LONGER than a session bound would be a gate the session outlives, i.e.
    a per-action control that no living session could ever fail. `<=` on idle, and
    strictly `<` on absolute, is exactly that line — and it is what would fail if somebody
    widened this constant again without weighing it against the session it guards.
    """
    from apps.api.authn.sessions import REALM_TIMEOUTS

    assert REALM_TIMEOUTS["admin"].idle >= REAUTH_MAX_AGE
    assert REALM_TIMEOUTS["admin"].absolute > REAUTH_MAX_AGE
    assert COOKIE_NAMES["admin"].startswith("__Host-")
