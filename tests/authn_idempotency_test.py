"""`/v1/auth/**` takes no `Idempotency-Key`, and what protects it instead (D-178).

AUTH-MIGRATION §11 reported the header as inert: both password-reset forms send one,
`core/middleware.py` lets it through CORS, `reliability/service.py` implements the store, and
no auth route takes the dependency. The decision is that no auth route ever will, so this
file makes the ABSENCE a property rather than an oversight, and measures the mechanisms the
decision leans on.

THE ARGUMENT, in one paragraph, because a test file that only asserts an absence is not
evidence of anything. An idempotency record is keyed on `(scope_key, route, method,
idempotency_key)`, and its safety collapses into "can two different callers compute the same
scope?" (`scripts/check_idempotency_scope.py`, D-175 — a reference platform fell back to the
client address for anonymous callers, which behind a CDN is one scope for everybody). Our
`scope_key` takes two `UUID | None` parameters and has no fallback branch; mypy strict is the
guard, because a header is a `str`. The auth routes a double submit could plausibly hurt are
the UNAUTHENTICATED ones — the two reset forms, bootstrap, invitation redemption — and an
unauthenticated caller has no principal. The only candidate scopes are the submitted address
and the socket peer: one is a value any stranger can type, the other is the D-175 defect
verbatim. So the key is not taken, and the double submit is answered where it happens
instead: by a single-use CAS on the row.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints, the fixture deletes
exactly those, and nothing counts globally.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from apps.api.authn import service
from apps.api.authn.throttle import KEY_PREFIX
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

AUTHN_ROUTES = Path(__file__).resolve().parent.parent / "apps" / "api" / "authn" / "routes.py"


@pytest_asyncio.fixture
async def account() -> AsyncIterator[tuple[uuid.UUID, str]]:
    """One client-realm user with a live address and no password."""
    user_id = uuid.uuid4()
    email = f"idem-{user_id.hex[:10]}@calevate-test.example"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, name, email_verified_at, "
                "created_at, updated_at) "
                "VALUES (:id, NULL, :email, 'Idem Probe', now(), now(), now())"
            ),
            {"id": user_id, "email": email},
        )
    try:
        yield user_id, email
    finally:
        async with credential_session() as session:
            for table in ("auth_email_tokens", "auth_sessions", "auth_credentials"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = :s"), {"s": user_id}
                )
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM outbox_messages WHERE payload->>'to' = :to"), {"to": email}
            )
            await session.execute(text("DELETE FROM users WHERE id = :s"), {"s": user_id})
        redis = get_redis()
        for budget in ("password", "otp"):
            await redis.delete(f"{KEY_PREFIX}:{budget}:client:{user_id}")


async def _live_reset_tokens(user_id: uuid.UUID) -> int:
    async with credential_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM auth_email_tokens WHERE subject_id = :s "
                        "AND purpose = 'password_reset' AND used_at IS NULL"
                    ),
                    {"s": user_id},
                )
            ).scalar()
            or 0
        )


async def _issue_reset_token(user_id: uuid.UUID, email: str) -> str:
    """The token as the mailbox would receive it — read out of the outbox payload, which
    is the only place the plaintext exists."""
    await service.request_password_reset(realm="client", email=email, ip=None)
    async with untenanted_session() as session:
        secret = (
            await session.execute(
                text(
                    "SELECT payload->>'secret' FROM outbox_messages "
                    "WHERE payload->>'to' = :to AND payload->>'kind' = 'password_reset' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"to": email},
            )
        ).scalar()
    assert secret is not None, "a reset request must queue exactly one mail"
    return str(secret)


# ═══════════════ the absence, as a property ═══════════════


def test_no_handler_in_the_auth_router_reads_the_idempotency_key_header() -> None:
    """The decision, made checkable. A handler that started reading the header would be
    claiming a protection it cannot scope, and the scope is the whole safety argument."""
    source = AUTHN_ROUTES.read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.lower() == "idempotency-key"
    ]
    assert not offenders, (
        f"authn/routes.py reads Idempotency-Key at line(s) {offenders}. An unauthenticated "
        "caller has no principal to scope a replay cache on (D-175)."
    )


def test_no_module_in_the_auth_package_claims_an_idempotency_record() -> None:
    package = AUTHN_ROUTES.parent
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else None
                name = name or (node.func.id if isinstance(node.func, ast.Name) else None)
                assert name != "claim_idempotency", f"{path}:{node.lineno}"


def test_the_scope_producer_still_refuses_a_string_at_the_type_level() -> None:
    """The guard the decision rests on: `scope_key` is keyword-only and both parameters are
    `UUID | None`, so mypy strict refuses an address or a header at EVERY call site. If this
    ever widens, the argument for not taking the header changes with it."""
    import inspect

    from apps.api.reliability.service import scope_key

    signature = inspect.signature(scope_key)
    assert [p.kind for p in signature.parameters.values()] == [
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.KEYWORD_ONLY,
    ]
    assert set(signature.parameters) == {"tenant_id", "user_id"}
    for parameter in signature.parameters.values():
        assert parameter.annotation in ("UUID | None", "uuid.UUID | None")


# ═══════════════ what protects each route instead ═══════════════


@pytest.mark.asyncio
async def test_a_double_submitted_reset_request_leaves_one_live_link_not_two(
    account: tuple[uuid.UUID, str],
) -> None:
    """`tokens.invalidate_outstanding` is the mechanism, and it is a stronger statement than
    a replay cache: the property is not "the second request did nothing", it is "there is
    exactly one live key in that mailbox", which is what the reset flow actually needs."""
    user_id, email = account
    await service.request_password_reset(realm="client", email=email, ip=None)
    await service.request_password_reset(realm="client", email=email, ip=None)

    assert await _live_reset_tokens(user_id) == 1


@pytest.mark.asyncio
async def test_the_newest_link_is_the_one_that_works_after_a_double_submit(
    account: tuple[uuid.UUID, str],
) -> None:
    user_id, email = account
    first = await _issue_reset_token(user_id, email)
    second = await _issue_reset_token(user_id, email)
    assert first != second

    with pytest.raises(ProblemError) as caught:
        await service.confirm_password_reset(
            realm="client", token=first, password="a-brand-new-passphrase", ip=None
        )
    assert caught.value.code == "invalid_reset_token"

    await service.confirm_password_reset(
        realm="client", token=second, password="a-brand-new-passphrase", ip=None
    )


@pytest.mark.asyncio
async def test_the_second_submission_of_one_reset_link_is_refused_and_that_is_correct(
    account: tuple[uuid.UUID, str],
) -> None:
    """What an idempotency record would have changed, and why not changing it is right.

    A replay cache would serve the first response to the second click. But nothing here can
    tell the person who double-clicked from somebody replaying a link they should not have,
    and the safe answer to both is the same one: the link is spent. The password DID change
    on the first submission — asserted below, because "the second call failed" would
    otherwise be indistinguishable from "neither worked".
    """
    user_id, email = account
    token = await _issue_reset_token(user_id, email)
    await service.confirm_password_reset(
        realm="client", token=token, password="a-brand-new-passphrase", ip=None
    )

    async with credential_session() as session:
        set_at = (
            await session.execute(
                text("SELECT password_set_at FROM auth_credentials WHERE subject_id = :s"),
                {"s": user_id},
            )
        ).scalar()
    assert set_at is not None and (datetime.now(UTC) - set_at).total_seconds() < 60

    with pytest.raises(ProblemError) as caught:
        await service.confirm_password_reset(
            realm="client", token=token, password="another-passphrase-entirely", ip=None
        )
    assert caught.value.code == "invalid_reset_token"


@pytest.mark.asyncio
async def test_the_token_burn_admits_exactly_one_winner_under_concurrency(
    account: tuple[uuid.UUID, str],
) -> None:
    """The claim the decision rests on, driven rather than asserted from the SQL. Two
    confirmations of one token, launched together: one succeeds, one is refused."""
    import asyncio

    user_id, email = account
    token = await _issue_reset_token(user_id, email)

    results = await asyncio.gather(
        service.confirm_password_reset(
            realm="client", token=token, password="a-brand-new-passphrase", ip=None
        ),
        service.confirm_password_reset(
            realm="client", token=token, password="a-brand-new-passphrase", ip=None
        ),
        return_exceptions=True,
    )
    refusals = [r for r in results if isinstance(r, ProblemError)]
    assert len(refusals) == 1, results
    assert refusals[0].code == "invalid_reset_token"
