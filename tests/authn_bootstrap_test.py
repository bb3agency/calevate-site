"""The first administrator (D-167): the one act that turns a bare deployment into a usable one.

Four properties the coordinator named, plus the ones that make them mean something:

  * a second run does not mint a second god-account;
  * an expired link is refused;
  * a consumed link cannot be replayed;
  * the created account can really authenticate afterwards — which is the test that would
    catch a bootstrap that "succeeded" and left an account nobody can sign in to.

SHARED DATABASE DISCIPLINE, and this suite is the awkward case. `bootstrap_first_admin` asks
a GLOBAL question — "does ANY operator have a password?" — so the state it reads cannot be
scoped to ids this module minted.

What the fixture does NOT do is empty `admin_users`. That was the first attempt and it is
wrong twice over: other suites seed operators, and `kyc_records.verified_by` carries a
foreign key to the table, so the delete is refused anyway. What it does instead is park the
ADMIN-REALM CREDENTIAL ROWS — which is precisely what the bootstrap keys on, and which
nothing outside this feature creates. Pre-existing `admin_users` rows stay exactly where
they are; they simply have no password, which is what an un-bootstrapped deployment looks
like.

Every count below is then scoped to the rows this module created, by taking a baseline of
existing ids in the fixture and subtracting it. Nothing counts globally.

**THIS SUITE MUST RUN SERIALLY, and on this repo's shared development database that is not
only a pytest concern** — several agent worktrees point at one Postgres. The fixture is
written to be as polite as that allows: session and token cleanup is scoped to the operators
it created, and the one genuinely global act (parking admin-realm credentials, which is what
"un-bootstrapped" MEANS) restores every row it removed. `pyproject.toml` configures no
xdist, so within a run the ordering holds.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from apps.api.authn import service, tokens
from apps.api.authn.bootstrap import bootstrap_first_admin, confirm_bootstrap
from apps.api.authn.throttle import KEY_PREFIX
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

PASSWORD = "first-operator-passphrase"
REALM = "admin"


@dataclass(frozen=True)
class BareDeployment:
    """One un-bootstrapped deployment, and the baseline needed to count only our own rows."""

    email: str
    #: `admin_users` ids that existed before this test. Every count subtracts these.
    pre_existing: frozenset[uuid.UUID]

    async def new_admin_count(self) -> int:
        async with untenanted_session() as session:
            rows = (await session.execute(text("SELECT id FROM admin_users"))).all()
        return len({uuid.UUID(str(row[0])) for row in rows} - self.pre_existing)


@pytest_asyncio.fixture
async def bare_deployment() -> AsyncIterator[BareDeployment]:
    """A deployment that looks freshly migrated: no operator holds a PASSWORD.

    See the module docstring for why this parks credentials rather than emptying
    `admin_users`. The parked rows are restored verbatim, including their hashes, so a
    suite that runs after this one sees exactly what it would have seen.
    """
    email = f"first-admin-{uuid.uuid4().hex[:10]}@calevate-test.example"
    async with untenanted_session() as session:
        existing = (await session.execute(text("SELECT id FROM admin_users"))).all()
    pre_existing = frozenset(uuid.UUID(str(row[0])) for row in existing)

    async with credential_session() as session:
        parked = (
            await session.execute(
                text(
                    "SELECT id, subject_id, password_hash, password_set_at, created_at, "
                    "updated_at FROM auth_credentials WHERE realm = 'admin'"
                )
            )
        ).all()
        await session.execute(text("DELETE FROM auth_credentials WHERE realm = 'admin'"))
    try:
        yield BareDeployment(email=email, pre_existing=pre_existing)
    finally:
        async with credential_session() as session:
            # Scoped to the operators THIS test created — `mine` is every admin_users row
            # that was not there when the fixture started. A blanket
            # `DELETE … WHERE realm = 'admin'` was the first shape and it is antisocial on
            # a SHARED database: other worktrees run this suite concurrently, and their
            # in-flight admin sessions are not ours to destroy. The credential DELETE below
            # stays global because the precondition this fixture creates is global, but it
            # RESTORES what it took.
            mine = (
                await session.execute(
                    text("SELECT id FROM admin_users WHERE id <> ALL(:keep)"),
                    {"keep": list(pre_existing) or [uuid.uuid4()]},
                )
            ).all()
            created_ids = [uuid.UUID(str(row[0])) for row in mine] or [uuid.uuid4()]
            await session.execute(
                text(
                    "DELETE FROM auth_email_tokens WHERE purpose = 'admin_bootstrap' "
                    "AND subject_id = ANY(:ids)"
                ),
                {"ids": created_ids},
            )
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = ANY(:ids)"),
                {"ids": created_ids},
            )
            await session.execute(text("DELETE FROM auth_credentials WHERE realm = 'admin'"))
            for row in parked:
                await session.execute(
                    text(
                        "INSERT INTO auth_credentials (id, realm, subject_id, password_hash, "
                        "password_set_at, created_at, updated_at) "
                        "VALUES (:id, 'admin', :sub, :hash, :set_at, :created, :updated)"
                    ),
                    {
                        "id": row[0],
                        "sub": row[1],
                        "hash": row[2],
                        "set_at": row[3],
                        "created": row[4],
                        "updated": row[5],
                    },
                )
        # Only the operators this module created — the parked ones keep their rows.
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM admin_users WHERE id <> ALL(:keep)"),
                {"keep": list(pre_existing) or [uuid.uuid4()]},
            )
        redis = get_redis()
        async for key in redis.scan_iter(f"{KEY_PREFIX}:*:{REALM}:*"):
            await redis.delete(key)


@pytest.mark.asyncio
async def test_a_bare_deployment_gets_an_operator_and_a_link(
    bare_deployment: BareDeployment,
) -> None:
    result = await bootstrap_first_admin(email=bare_deployment.email, name="First Operator")
    assert result.created is True
    assert result.email == bare_deployment.email
    assert len(result.token) >= 43, "the setup token must carry 256 bits"

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT email, role, clerk_user_id FROM admin_users WHERE id = :id"),
                {"id": result.admin_id},
            )
        ).first()
    assert row is not None
    assert row[0] == bare_deployment.email
    assert row[1] == "superadmin"
    assert row[2] is None, "a first-party operator has no Clerk id to name"


@pytest.mark.asyncio
async def test_the_bootstrap_writes_an_audit_entry_naming_the_address(
    bare_deployment: BareDeployment,
) -> None:
    """The single most privileged act in the system's life leaves a record."""
    result = await bootstrap_first_admin(email=bare_deployment.email, name=None)
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT action, actor_type, object_type FROM audit_log "
                    "WHERE object_id = :oid AND action = 'auth.admin_bootstrapped'"
                ),
                {"oid": str(result.admin_id)},
            )
        ).first()
    assert row is not None, "the bootstrap must be auditable"
    assert row[0] == "auth.admin_bootstrapped"
    assert row[2] == "admin_user"


@pytest.mark.asyncio
async def test_the_second_run_does_not_mint_a_second_god_account(
    bare_deployment: BareDeployment,
) -> None:
    """IDEMPOTENCY, and the refusal that makes this not a back door.

    Before the first password is set, re-running is a RESEND for the same row. Once an
    operator has a password the deployment is bootstrapped and the script refuses — there
    is deliberately no `--force`.
    """
    first = await bootstrap_first_admin(email=bare_deployment.email, name=None)

    # Not yet consumed: a re-run is a resend of the SAME account, not a new one.
    second = await bootstrap_first_admin(email=bare_deployment.email, name=None)
    assert second.admin_id == first.admin_id
    assert second.created is False
    assert second.token != first.token, "a resend must issue a fresh token"

    assert await bare_deployment.new_admin_count() == 1, "a re-run created a second operator row"

    # The link is consumed — the deployment now has an administrator.
    await confirm_bootstrap(token=second.token, password=PASSWORD, ip=None)

    # From here the script must refuse, for ANY address.
    with pytest.raises(ProblemError) as caught:
        await bootstrap_first_admin(email=bare_deployment.email, name=None)
    assert caught.value.code == "already_bootstrapped"
    assert caught.value.status == 409

    with pytest.raises(ProblemError):
        await bootstrap_first_admin(email="someone-else@calevate-test.example", name=None)

    assert await bare_deployment.new_admin_count() == 1, (
        "the refusal still created a row — the bootstrap is a back door"
    )


@pytest.mark.asyncio
async def test_a_resend_retires_the_previous_link(bare_deployment: BareDeployment) -> None:
    """Only the newest link works, exactly as a password reset behaves."""
    first = await bootstrap_first_admin(email=bare_deployment.email, name=None)
    second = await bootstrap_first_admin(email=bare_deployment.email, name=None)

    with pytest.raises(ProblemError) as caught:
        await confirm_bootstrap(token=first.token, password=PASSWORD, ip=None)
    assert caught.value.code == "invalid_bootstrap_token"
    # The newest one still works.
    await confirm_bootstrap(token=second.token, password=PASSWORD, ip=None)


@pytest.mark.asyncio
async def test_a_consumed_link_cannot_be_replayed(bare_deployment: BareDeployment) -> None:
    result = await bootstrap_first_admin(email=bare_deployment.email, name=None)
    await confirm_bootstrap(token=result.token, password=PASSWORD, ip=None)

    with pytest.raises(ProblemError) as caught:
        await confirm_bootstrap(token=result.token, password="a-different-passphrase", ip=None)
    assert caught.value.code == "invalid_bootstrap_token"


@pytest.mark.asyncio
async def test_an_expired_link_is_refused(bare_deployment: BareDeployment) -> None:
    """The TTL, driven by minting a token in the past rather than by waiting an hour."""
    result = await bootstrap_first_admin(email=bare_deployment.email, name=None)
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    async with credential_session() as session:
        stale = await tokens.issue_token(
            session,
            purpose="admin_bootstrap",
            realm=REALM,
            subject_id=result.admin_id,
            now=long_ago,
        )
    assert stale.expires_at < datetime.now(UTC), "the fixture must produce an expired token"

    with pytest.raises(ProblemError) as caught:
        await confirm_bootstrap(token=stale.token, password=PASSWORD, ip=None)
    assert caught.value.code == "invalid_bootstrap_token"


@pytest.mark.asyncio
async def test_the_bootstrap_ttl_is_an_hour_not_ten_minutes() -> None:
    """The reference implementation's `INVITE_TTL_MS = 10 * 60 * 1000` is too short for a
    deployment bootstrap: if it expires before the operator reaches the mailbox, there is
    no other way into the platform. Pinned so a future edit is a decision."""
    assert tokens.TOKEN_LIFETIMES["admin_bootstrap"] == timedelta(minutes=60)


@pytest.mark.asyncio
async def test_the_bootstrapped_account_can_actually_sign_in(
    bare_deployment: BareDeployment,
) -> None:
    """THE END-TO-END PROPERTY. A bootstrap that reports success and leaves an account
    nobody can sign in to is the failure mode worth testing for, because every intermediate
    assertion above would still be green."""
    result = await bootstrap_first_admin(email=bare_deployment.email, name="First Operator")
    await confirm_bootstrap(token=result.token, password=PASSWORD, ip=None)

    outcome = await service.sign_in(
        realm=REALM, email=bare_deployment.email, password=PASSWORD, ip=None
    )
    assert outcome.subject_id == result.admin_id
    # The admin realm mandates a second factor, so a correct password is NOT a finished
    # sign-in — it is a session that opens exactly one door: the emailed code (D-166).
    assert outcome.status == "otp_required"
    assert outcome.session.token


@pytest.mark.asyncio
async def test_a_bootstrap_link_cannot_reset_an_established_operator(
    bare_deployment: BareDeployment,
) -> None:
    """A leaked link from a finished deploy must open nothing, even before it expires.

    Minted while the account had no password, then presented after one was set by other
    means — the shape a stale deploy artifact takes.
    """
    result = await bootstrap_first_admin(email=bare_deployment.email, name=None)
    spare = None
    async with credential_session() as session:
        spare = await tokens.issue_token(
            session, purpose="admin_bootstrap", realm=REALM, subject_id=result.admin_id
        )
    await confirm_bootstrap(token=result.token, password=PASSWORD, ip=None)

    with pytest.raises(ProblemError) as caught:
        await confirm_bootstrap(token=spare.token, password="attacker-chosen-passphrase", ip=None)
    assert caught.value.code == "invalid_bootstrap_token"

    # And the original password still works — nothing was overwritten.
    outcome = await service.sign_in(
        realm=REALM, email=bare_deployment.email, password=PASSWORD, ip=None
    )
    assert outcome.subject_id == result.admin_id


@pytest.mark.asyncio
async def test_a_bootstrap_token_is_not_redeemable_as_a_password_reset(
    bare_deployment: BareDeployment,
) -> None:
    """The purpose is inside the hash domain, so the two cannot be traded."""
    result = await bootstrap_first_admin(email=bare_deployment.email, name=None)
    with pytest.raises(ProblemError) as caught:
        await service.confirm_password_reset(
            realm=REALM, token=result.token, password=PASSWORD, ip=None
        )
    assert caught.value.code == "invalid_reset_token"


@pytest.mark.asyncio
async def test_a_malformed_address_is_refused_before_anything_is_written(
    bare_deployment: BareDeployment,
) -> None:
    del bare_deployment
    for bad in ("", "   ", "not-an-address"):
        with pytest.raises(ValueError, match="deliverable email address"):
            await bootstrap_first_admin(email=bad, name=None)


@pytest.mark.asyncio
async def test_an_unknown_role_is_refused(bare_deployment: BareDeployment) -> None:
    with pytest.raises(ValueError, match="not an admin role"):
        await bootstrap_first_admin(email=bare_deployment.email, name=None, role="root")
