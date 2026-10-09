"""Self-serve accounts and Google sign-in (D-703).

Drives `authn/registration.py`, `authn/google.py` and the self-serve trial against the real
database and Redis. Google itself is never called: the token exchange is replaced by a
function that hands back an ID token built here, so every claim check runs for real.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
import pytest_asyncio
from apps.api.authn import google, registration
from apps.api.authn.subjects import load_subject, resolve_by_email
from apps.api.billing.trials import read_trial
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import credential_session, tenant_session, untenanted_session
from apps.api.tenancy import signup as signup_service
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

CLIENT_ID = "test-client.apps.googleusercontent.com"
GOOD_PASSWORD = "four unrelated words here"


def _address(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@calevate-test.example"


@pytest.fixture(autouse=True)
def _google_app(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-client-secret")
    monkeypatch.setattr(
        settings, "google_signin_redirect_uri", "https://app.example.test/auth/google/callback"
    )


@pytest_asyncio.fixture
async def planted() -> AsyncIterator[list[str]]:
    """Addresses a test caused to exist; their users and Google links are removed after."""
    addresses: list[str] = []
    yield addresses
    async with untenanted_session() as session:
        ids = [
            row[0]
            for row in (
                await session.execute(
                    text("SELECT id FROM users WHERE lower(email) = ANY(:e)"),
                    {"e": [a.casefold() for a in addresses]},
                )
            ).all()
        ]
    if not ids:
        return
    async with credential_session() as session:
        for table in ("auth_identities", "auth_credentials", "auth_sessions"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE subject_id = ANY(:ids)"), {"ids": ids}
            )
    # One at a time: `memberships` is RLS'd, so an untenanted session cannot see which users
    # own a workspace; a user the trial test made an owner stays, like the tenant it owns.
    for user_id in ids:
        try:
            async with untenanted_session() as session:
                await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        except IntegrityError:
            continue


# --- email signup ---------------------------------------------------------------------


class Mailbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def __call__(self, session: Any, *, kind: str, realm: str, to: str, secret: str) -> None:
        self.sent.append({"kind": kind, "to": to, "secret": secret})


async def _start(monkeypatch: pytest.MonkeyPatch, email: str) -> Mailbox:
    box = Mailbox()
    monkeypatch.setattr(registration, "_enqueue_auth_email", box)
    await registration.start_signup(email=email, ip="203.0.113.7")
    return box


async def test_a_new_address_gets_a_code_and_a_verified_account(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    email = _address("signup")
    planted.append(email)
    box = await _start(monkeypatch, email)
    assert [m["kind"] for m in box.sent] == ["otp_signup"]
    assert await resolve_by_email("client", email) is None, "no account before the code"

    created = await registration.complete_signup(
        email=email, code=box.sent[0]["secret"], password=GOOD_PASSWORD, name="Asha", ip=None
    )
    subject = await load_subject("client", created.subject_id)
    assert subject is not None and subject.email_verified_at is not None
    assert created.session.token


async def test_an_existing_account_is_mailed_a_way_in_and_no_code(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    email = _address("exists")
    planted.append(email)
    first = await _start(monkeypatch, email)
    await registration.complete_signup(
        email=email, code=first.sent[0]["secret"], password=GOOD_PASSWORD, name=None, ip=None
    )
    again = await _start(monkeypatch, email)
    assert [m["kind"] for m in again.sent] == ["signup_existing_account"]


async def test_a_wrong_code_creates_nothing(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    email = _address("wrong")
    planted.append(email)
    box = await _start(monkeypatch, email)
    wrong = "000000" if box.sent[0]["secret"] != "000000" else "111111"
    with pytest.raises(ProblemError) as refused:
        await registration.complete_signup(
            email=email, code=wrong, password=GOOD_PASSWORD, name=None, ip=None
        )
    assert refused.value.code == "invalid_code"
    assert await resolve_by_email("client", email) is None


async def test_a_weak_password_is_refused_before_the_code_is_spent(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    email = _address("weak")
    planted.append(email)
    box = await _start(monkeypatch, email)
    with pytest.raises(ProblemError):
        await registration.complete_signup(
            email=email, code=box.sent[0]["secret"], password="short", name=None, ip=None
        )
    created = await registration.complete_signup(
        email=email, code=box.sent[0]["secret"], password=GOOD_PASSWORD, name=None, ip=None
    )
    assert created.subject_id is not None, "the same code still works after a retype"


# --- Google sign-in -------------------------------------------------------------------


def _id_token(expected_nonce: str, **over: Any) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": f"g-{uuid.uuid4().hex}",
        "email": _address("google"),
        "email_verified": True,
        "name": "Ravi Kumar",
        "nonce": expected_nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    claims.update(over)
    return jwt.encode(claims, "not-checked", algorithm="HS256")


def _state_and_nonce(url: str) -> tuple[str, str]:
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(urlsplit(url).query)
    return query["state"][0], query["nonce"][0]


async def _sign_in(
    monkeypatch: pytest.MonkeyPatch,
    *,
    signup_open: bool = True,
    browser_nonce: str | None = None,
    **claims: Any,
) -> tuple[google.SignedIn, dict[str, Any]]:
    begun = google.begin(next_path="/c/somewhere")
    state, nonce = _state_and_nonce(begun.authorize_url)
    token = _id_token(nonce, **claims)
    seen = jwt.decode(token, options={"verify_signature": False})

    async def exchange(code: str, nonce_in: str, client: Any) -> str:
        assert code == "the-code"
        return token

    monkeypatch.setattr(google, "_exchange", exchange)
    signed_in = await google.finish(
        code="the-code",
        state=state,
        browser_nonce=browser_nonce if browser_nonce is not None else begun.browser_nonce,
        signup_open=signup_open,
    )
    return signed_in, seen


async def test_a_new_google_account_creates_a_verified_account(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    signed_in, claims = await _sign_in(monkeypatch)
    planted.append(claims["email"])
    assert signed_in.created is True
    assert signed_in.next_path == "/c/somewhere"
    subject = await load_subject("client", signed_in.subject_id)
    assert subject is not None and subject.email_verified_at is not None


async def test_the_same_google_account_signs_in_to_the_same_person(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    first, claims = await _sign_in(monkeypatch)
    planted.append(claims["email"])
    # Google says the address changed; the `sub` is what decides who this is.
    again, _ = await _sign_in(monkeypatch, sub=claims["sub"], email=_address("moved"))
    assert again.subject_id == first.subject_id
    assert again.created is False


async def test_a_verified_google_email_links_to_the_existing_account(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    email = _address("linked")
    planted.append(email)
    box = await _start(monkeypatch, email)
    created = await registration.complete_signup(
        email=email, code=box.sent[0]["secret"], password=GOOD_PASSWORD, name=None, ip=None
    )
    signed_in, _ = await _sign_in(monkeypatch, email=email.upper())
    assert signed_in.subject_id == created.subject_id
    assert signed_in.linked is True


async def test_an_unverified_google_email_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    with pytest.raises(ProblemError) as refused:
        await _sign_in(monkeypatch, email_verified=False)
    assert refused.value.code == "google_email_unverified"


async def test_no_account_and_signup_closed_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProblemError) as refused:
        await _sign_in(monkeypatch, signup_open=False)
    assert refused.value.code == "no_account_for_google"


async def test_a_sign_in_started_in_another_browser_cannot_finish_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ProblemError) as refused:
        await _sign_in(monkeypatch, browser_nonce="a-different-browser")
    assert refused.value.code == "google_sign_in_expired"


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://evil.example"},
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"exp": int((datetime.now(UTC) - timedelta(hours=2)).timestamp())},
        {"nonce": "replayed"},
    ],
)
def test_the_id_token_checks_refuse_a_bad_claim(claims: dict[str, Any]) -> None:
    begun = google.begin(next_path=None)
    _, nonce = _state_and_nonce(begun.authorize_url)
    token = _id_token(nonce, **claims)
    with pytest.raises(ProblemError) as refused:
        google.verify_id_token(token, browser_nonce=begun.browser_nonce)
    assert refused.value.code == "google_sign_in_failed"


def test_the_authorization_request_asks_for_identity_only_with_pkce() -> None:
    from urllib.parse import parse_qs, urlsplit

    begun = google.begin(next_path="//evil.example/x")
    query = parse_qs(urlsplit(begun.authorize_url).query)
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["prompt"] == ["select_account"]
    state = jwt.decode(query["state"][0], options={"verify_signature": False})
    assert state["nxt"] is None, "an off-site return path is dropped"


def test_a_safe_next_path_is_relative_only() -> None:
    assert google.safe_next("/c/acme") == "/c/acme"
    for bad in ("//evil.example", "/\\evil", "https://evil.example", "c/acme", "/c\r\n"):
        assert google.safe_next(bad) is None


# --- the self-serve trial -------------------------------------------------------------


async def test_a_self_serve_business_starts_its_trial_at_once(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "self_serve_trial_days", 9)
    monkeypatch.setattr(settings, "self_serve_trial_free_minutes", 12)
    email = _address("owner")
    planted.append(email)
    box = await _start(monkeypatch, email)
    account = await registration.complete_signup(
        email=email, code=box.sent[0]["secret"], password=GOOD_PASSWORD, name=None, ip=None
    )
    created = await signup_service.create_self_serve_tenant(
        user_id=account.subject_id,
        name="Corner Bakery",
        slug=f"bakery-{uuid.uuid4().hex[:8]}",
        vertical_template="custom",
        language="te-IN",
        billing_email=None,
        plan_tier="self_serve",
    )
    async with tenant_session(created["id"]) as session:
        trial = await read_trial(session, tenant_id=created["id"])
    assert trial is not None and trial.status == "active"
    assert trial.days == 9
    assert trial.free_minutes == 12
