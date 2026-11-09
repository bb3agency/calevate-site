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
from apps.api.authn.service import has_password
from apps.api.authn.sessions import verify_session
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
        "hd": "calevate-test.example",
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
    invited_email: str | None = None,
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
        invited_email=invited_email,
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
    # A PROVED account keeps its password and its sessions: only an unproved one is reclaimed.
    assert signed_in.reclaimed is False
    assert await has_password("client", created.subject_id)
    assert (await verify_session(token=created.session.token, realm="client")).session


async def test_linking_google_reclaims_an_unproved_account(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    """D-955, the "classic-federated merge" pre-hijack: somebody set a password on this
    address without ever proving it; Google now proves the mailbox. The merge must not keep
    that password or any session it opened."""
    from apps.api.authn.credentials import authenticate_subject, set_password
    from apps.api.authn.invitations import _find_or_create_user
    from apps.api.authn.sessions import issue_session

    email = _address("prehijack")
    planted.append(email)
    at = datetime.now(UTC)
    user_id, created = await _find_or_create_user(email=email, name=None, at=at)
    assert created
    async with credential_session() as session:
        await set_password(
            session, realm="client", subject_id=user_id, password=GOOD_PASSWORD, email=email
        )
        squatter = await issue_session(session, realm="client", subject_id=user_id)

    signed_in, _ = await _sign_in(monkeypatch, email=email)

    assert signed_in.subject_id == user_id
    assert signed_in.linked is True and signed_in.reclaimed is True
    assert not await has_password("client", user_id)
    async with credential_session() as session:
        assert not await authenticate_subject(
            session, realm="client", subject_id=user_id, password=GOOD_PASSWORD
        )
    assert (await verify_session(token=squatter.token, realm="client")).session is None
    assert (await verify_session(token=signed_in.session.token, realm="client")).session
    subject = await load_subject("client", user_id)
    assert subject is not None and subject.email_verified_at is not None


async def test_an_unproved_account_created_in_the_race_window_is_reclaimed_too(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    """The unproved account appears between `finish`'s read and its insert, so the insert
    loses to it and the raced arm links. That arm must reclaim exactly as the read arm does,
    or the squatter's password and session survive the merge."""
    from apps.api.authn.credentials import set_password
    from apps.api.authn.invitations import _find_or_create_user
    from apps.api.authn.sessions import issue_session

    email = _address("raced")
    planted.append(email)
    user_id, _ = await _find_or_create_user(email=email, name=None, at=datetime.now(UTC))
    async with credential_session() as session:
        await set_password(
            session, realm="client", subject_id=user_id, password=GOOD_PASSWORD, email=email
        )
        squatter = await issue_session(session, realm="client", subject_id=user_id)

    real_resolve = google.resolve_by_email
    calls = 0

    async def resolve_after_the_race(realm: str, address: str) -> Any:
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real_resolve(realm, address)

    monkeypatch.setattr(google, "resolve_by_email", resolve_after_the_race)
    signed_in, _ = await _sign_in(monkeypatch, email=email)

    assert signed_in.subject_id == user_id
    assert signed_in.linked is True and signed_in.reclaimed is True
    assert not await has_password("client", user_id)
    assert (await verify_session(token=squatter.token, realm="client")).session is None


async def test_an_address_google_does_not_host_neither_links_nor_creates(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    """A consumer Google account on a non-Gmail address carries `email_verified` from when
    it was created; the mailbox may belong to somebody else now (Google's own guide)."""
    email = _address("reassigned")
    planted.append(email)
    box = await _start(monkeypatch, email)
    await registration.complete_signup(
        email=email, code=box.sent[0]["secret"], password=GOOD_PASSWORD, name=None, ip=None
    )
    with pytest.raises(ProblemError) as link:
        await _sign_in(monkeypatch, email=email, hd=None)
    assert link.value.code == "google_email_not_authoritative"
    with pytest.raises(ProblemError) as create:
        await _sign_in(monkeypatch, email=_address("fresh"), hd=None)
    assert create.value.code == "google_email_not_authoritative"


async def test_a_gmail_address_needs_no_hosted_domain(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    email = f"ravi.{uuid.uuid4().hex[:10]}@gmail.com"
    planted.append(email)
    signed_in, _ = await _sign_in(monkeypatch, email=email, hd=None)
    assert signed_in.created is True


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
        {"azp": "someone-else.apps.googleusercontent.com"},
        {"aud": [CLIENT_ID, "someone-else.apps.googleusercontent.com"]},
    ],
)
def test_the_id_token_checks_refuse_a_bad_claim(claims: dict[str, Any]) -> None:
    begun = google.begin(next_path=None)
    _, nonce = _state_and_nonce(begun.authorize_url)
    token = _id_token(nonce, **claims)
    with pytest.raises(ProblemError) as refused:
        google.verify_id_token(token, browser_nonce=begun.browser_nonce)
    assert refused.value.code == "google_sign_in_failed"


def test_a_token_for_several_audiences_passes_when_it_was_issued_to_us() -> None:
    begun = google.begin(next_path=None)
    _, nonce = _state_and_nonce(begun.authorize_url)
    token = _id_token(nonce, aud=[CLIENT_ID, "another.apps.googleusercontent.com"], azp=CLIENT_ID)
    assert google.verify_id_token(token, browser_nonce=begun.browser_nonce)["azp"] == CLIENT_ID


async def test_a_state_answers_one_callback_only(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    """RFC 9700 §4.7.1: the same callback replayed in the same browser inside the ten
    minutes is refused before any code reaches Google."""
    begun = google.begin(next_path=None)
    state, nonce = _state_and_nonce(begun.authorize_url)
    token = _id_token(nonce)
    planted.append(jwt.decode(token, options={"verify_signature": False})["email"])
    exchanges: list[str] = []

    async def exchange(code: str, nonce_in: str, client: Any) -> str:
        exchanges.append(code)
        return token

    monkeypatch.setattr(google, "_exchange", exchange)
    await google.finish(
        code="the-code", state=state, browser_nonce=begun.browser_nonce, signup_open=True
    )
    with pytest.raises(ProblemError) as replayed:
        await google.finish(
            code="the-code", state=state, browser_nonce=begun.browser_nonce, signup_open=True
        )
    assert replayed.value.code == "google_sign_in_expired"
    assert exchanges == ["the-code"], "the replay must be refused before the code exchange"


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
        billing_email=None,
        plan_tier="self_serve",
    )
    async with tenant_session(created["id"]) as session:
        trial = await read_trial(session, tenant_id=created["id"])
    assert trial is not None and trial.status == "active"
    assert trial.days == 9
    assert trial.free_minutes == 12


async def test_an_invitee_accepts_with_google_while_self_serve_signup_is_closed(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    """The invitation page offers "Accept with Google" on every deployment, and
    `self_serve_signup_enabled` defaults off. A new invitee pressing it was refused
    `no_account_for_google` ("use the invitation your workspace owner sent") while holding
    that invitation. The invitation to the address Google vouches for opens the account."""
    import httpx
    from apps.api.authn import self_serve_routes
    from apps.api.main import app
    from tests.api_security_test import _make_tenant
    from tests.member_invitations_test import mailed_invitation_token
    from tests.members_test import _headers

    async def closed() -> bool:
        return False

    monkeypatch.setattr(self_serve_routes, "_signup_is_open", closed)
    tenant_id, slug, owner = await _make_tenant("owner")
    invitee = _address("invitee")
    planted.append(invitee)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as http:
        invited = await http.post(
            "/v1/invitations",
            json={"email": invitee, "role": "staff"},
            headers=_headers(slug, owner),
        )
        assert invited.status_code == 201, invited.text
        raw = await mailed_invitation_token(invitee)

        started = await http.post("/v1/auth/client/google/start", json={"next": "/c"})
        assert started.status_code == 200, started.text
        state, nonce = _state_and_nonce(started.json()["authorize_url"])
        token = _id_token(nonce, email=invitee)

        async def exchange(code: str, nonce_in: str, client: Any) -> str:
            return token

        monkeypatch.setattr(google, "_exchange", exchange)
        done = await http.post(
            "/v1/auth/client/google/complete",
            json={"code": "the-code", "state": state, "invitation_token": raw},
        )

    assert done.status_code == 200, done.text
    assert done.json()["joined_slug"] == slug
    assert done.json()["account_created"] is True
    async with tenant_session(tenant_id) as session:
        role = (
            await session.execute(
                text(
                    "SELECT m.role FROM memberships m JOIN users u ON u.id = m.user_id "
                    "WHERE lower(u.email) = :e"
                ),
                {"e": invitee.casefold()},
            )
        ).scalar()
    assert role == "staff"


async def test_an_invitation_to_another_address_opens_nothing_while_signup_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The invitation is leave for ITS address only: a Google account with a different
    address is refused exactly as before."""
    with pytest.raises(ProblemError) as refused:
        await _sign_in(monkeypatch, signup_open=False, invited_email=_address("someone-else"))
    assert refused.value.code == "no_account_for_google"


async def test_a_stale_invitation_is_refused_before_google_opens_an_account(
    monkeypatch: pytest.MonkeyPatch, planted: list[str]
) -> None:
    """Deep audit D2. The request ends in `invitation_invalid` whatever happens, so it ends
    there BEFORE `google.finish`: finishing first minted a session nobody received and, with
    signup open, created an account for a link that no longer works."""
    import httpx
    from apps.api.authn import self_serve_routes
    from apps.api.main import app

    async def open_signup() -> bool:
        return True

    monkeypatch.setattr(self_serve_routes, "_signup_is_open", open_signup)
    stranger = _address("stale")
    planted.append(stranger)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as http:
        started = await http.post("/v1/auth/client/google/start", json={"next": "/c"})
        assert started.status_code == 200, started.text
        state, nonce = _state_and_nonce(started.json()["authorize_url"])
        token = _id_token(nonce, email=stranger)

        async def exchange(code: str, nonce_in: str, client: Any) -> str:
            return token

        monkeypatch.setattr(google, "_exchange", exchange)
        done = await http.post(
            "/v1/auth/client/google/complete",
            json={"code": "the-code", "state": state, "invitation_token": uuid.uuid4().hex},
        )

    assert done.status_code == 422, done.text
    assert done.json()["type"].endswith("/invitation_invalid")
    assert await resolve_by_email("client", stranger) is None
