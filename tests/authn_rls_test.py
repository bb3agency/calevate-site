"""The cross-tenant zero-rows test for D-165's two new tables (hard rule 1).

`auth_credentials` and `auth_sessions` carry no `tenant_id` — identity crosses tenants,
so a password or a session scoped to one would be duplicated or wrong — which means the
usual "tenant A sees none of tenant B's rows" cannot be written as a `tenant_id`
comparison. The property is still the one hard rule 1 asks for, and it is stronger: the
FORCEd policy those tables carry does not consult `app.tenant_id` AT ALL, so **no value
of it opens the table**. Tenant A sees zero rows belonging to tenant B's owner because it
sees zero rows belonging to anybody, including its own.

That is also why the tenant ids below are `uuid4()` with no `organizations` row behind
them. RLS evaluates the policy expression against the GUC; whether the uuid names a real
tenant changes nothing about the expression, and creating two orgs in a shared database
to prove a predicate that ignores them would add cleanup and subtract clarity. What the
test does need — and has — is REAL ROWS in both tables, so that "zero rows" is a refusal
and not an empty table. `test_the_credential_session_can_see_what_the_others_cannot` is
the control that makes every assertion above mean something.

SHARED DATABASE DISCIPLINE: every row hangs off a `uuid4` subject this module minted, and
the fixture deletes exactly those. Nothing counts rows globally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from apps.api.authn.credentials import authenticate_subject, set_password
from apps.api.authn.hashing import (
    ARGON2_MEMORY_KIB,
    MIN_PASSWORD_CHARS,
    _peppered,
    pepper_ring,
)
from apps.api.authn.sessions import issue_session
from apps.api.db.session import (
    admin_session,
    credential_session,
    invite_session,
    tenant_session,
    untenanted_session,
    user_session,
)
from argon2 import PasswordHasher
from argon2.low_level import Type
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

PASSWORD = "kurnool-clinic-reception-desk"

_COUNT_CREDENTIALS = "SELECT count(*) FROM auth_credentials WHERE subject_id = ANY(:ids)"
_COUNT_SESSIONS = "SELECT count(*) FROM auth_sessions WHERE subject_id = ANY(:ids)"


@pytest_asyncio.fixture
async def planted() -> AsyncIterator[list[uuid.UUID]]:
    """Two subjects standing in for two different tenants' owners, with real rows.

    Yields their ids. Both a credential and a session exist for each, so a query that
    returns nothing is returning nothing about rows that are definitely there.
    """
    owners = [uuid.uuid4(), uuid.uuid4()]
    async with credential_session() as session:
        for owner in owners:
            await set_password(session, realm="client", subject_id=owner, password=PASSWORD)
            await issue_session(session, realm="client", subject_id=owner)
    yield owners
    async with credential_session() as session:
        await session.execute(
            text("DELETE FROM auth_sessions WHERE subject_id = ANY(:ids)"), {"ids": owners}
        )
        await session.execute(
            text("DELETE FROM auth_credentials WHERE subject_id = ANY(:ids)"), {"ids": owners}
        )


# ------------------------------------------------------------------ the control


async def test_the_credential_session_can_see_what_the_others_cannot(
    planted: list[uuid.UUID],
) -> None:
    """THE CONTROL. Without it every assertion below is satisfied by an empty table."""
    async with credential_session() as session:
        credentials = (
            await session.execute(text(_COUNT_CREDENTIALS), {"ids": planted})
        ).scalar_one()
        sessions = (await session.execute(text(_COUNT_SESSIONS), {"ids": planted})).scalar_one()
    assert credentials == 2
    assert sessions == 2


# ------------------------------------------------------------------ zero rows, per session


async def test_a_tenant_session_sees_zero_credentials_including_another_tenants_owner(
    planted: list[uuid.UUID],
) -> None:
    """The cross-tenant case, in the only form this table can express it.

    Two tenant contexts, one per pretend tenant, and neither sees either owner's
    credential — not the "other" tenant's, and not its own. A password store that a
    tenant-scoped code path can read is one SQL mistake away from being every password.
    """
    for _ in range(2):
        async with tenant_session(uuid.uuid4()) as session:
            assert (
                await session.execute(text(_COUNT_CREDENTIALS), {"ids": planted})
            ).scalar_one() == 0


async def test_a_tenant_session_sees_zero_sessions(planted: list[uuid.UUID]) -> None:
    """Same property for the session table, and the consequence is worse: a readable
    `token_hash` plus an offline dictionary is nothing, but a readable row tells an
    attacker which subjects are signed in and which families to target."""
    async with tenant_session(uuid.uuid4()) as session:
        assert (await session.execute(text(_COUNT_SESSIONS), {"ids": planted})).scalar_one() == 0


async def test_every_other_session_this_repo_opens_sees_zero_rows(
    planted: list[uuid.UUID],
) -> None:
    """The sweep. `db/session.py` exposes six context managers; five of them must be blind
    to these tables, and a future seventh will be blind by default because the policy
    names exactly one GUC.

    `admin_session` is the one worth naming: `app.admin` widens `organizations` and
    nothing else, and an operator console that could read the password store would make
    D-22's "view as client is READ-ONLY" a sentence about the wrong risk.
    """
    async with untenanted_session() as session:
        assert (await session.execute(text(_COUNT_CREDENTIALS), {"ids": planted})).scalar_one() == 0
    async with admin_session() as session:
        assert (await session.execute(text(_COUNT_CREDENTIALS), {"ids": planted})).scalar_one() == 0
    async with user_session(planted[0]) as session:
        assert (await session.execute(text(_COUNT_CREDENTIALS), {"ids": planted})).scalar_one() == 0
    async with invite_session("any-hash-at-all") as session:
        assert (await session.execute(text(_COUNT_SESSIONS), {"ids": planted})).scalar_one() == 0


async def test_a_tenant_session_cannot_write_a_credential_either() -> None:
    """NEGATIVE CONTROL on the WITH CHECK half.

    A policy with only a USING clause hides rows and still lets a tenant INSERT them —
    which here would mean planting a password for somebody else's account. PostgreSQL
    raises rather than silently dropping the row, and that is the answer we want: a write
    that cannot be seen afterwards is worse than a write that is refused.
    """
    subject_id = uuid.uuid4()
    with pytest.raises(ProgrammingError):
        async with tenant_session(uuid.uuid4()) as session:
            await session.execute(
                text(
                    "INSERT INTO auth_credentials (id, realm, subject_id, password_hash, "
                    "password_set_at) VALUES (:id, 'client', :sub, 'x', now())"
                ),
                {"id": uuid.uuid4(), "sub": subject_id},
            )
    # And nothing landed — the refusal is a refusal, not a row we merely cannot read.
    async with credential_session() as session:
        assert (
            await session.execute(text(_COUNT_CREDENTIALS), {"ids": [subject_id]})
        ).scalar_one() == 0


# ------------------------------------------------------------------ the store itself


async def test_a_password_can_be_set_and_proved(planted: list[uuid.UUID]) -> None:
    async with credential_session() as session:
        assert await authenticate_subject(
            session, realm="client", subject_id=planted[0], password=PASSWORD
        )


async def test_the_wrong_password_and_the_unknown_subject_both_answer_false(
    planted: list[uuid.UUID],
) -> None:
    """NEGATIVE CONTROL, both shapes. Neither raises — a sign-in route must be able to
    tell a caller "no" without the two cases looking different from outside."""
    async with credential_session() as session:
        assert not await authenticate_subject(
            session, realm="client", subject_id=planted[0], password=PASSWORD + "x"
        )
        assert not await authenticate_subject(
            session, realm="client", subject_id=uuid.uuid4(), password=PASSWORD
        )


async def test_a_credential_is_scoped_to_its_realm(planted: list[uuid.UUID]) -> None:
    """The realm boundary in the password store: the same subject id in the admin realm
    has no credential, so the client owner's password is not an operator password."""
    async with credential_session() as session:
        assert not await authenticate_subject(
            session, realm="admin", subject_id=planted[0], password=PASSWORD
        )


async def test_setting_a_password_twice_replaces_it_and_leaves_one_row(
    planted: list[uuid.UUID],
) -> None:
    """The UPSERT, and the reason it is one: a reset must not be able to leave two rows
    where a later read picks whichever the planner returns first."""
    replacement = "hyderabad-clinic-evening-shift"
    async with credential_session() as session:
        await set_password(session, realm="client", subject_id=planted[0], password=replacement)
        rows = (
            await session.execute(
                text("SELECT count(*) FROM auth_credentials WHERE subject_id = :s"),
                {"s": planted[0]},
            )
        ).scalar_one()
        assert rows == 1
        assert not await authenticate_subject(
            session, realm="client", subject_id=planted[0], password=PASSWORD
        )
        assert await authenticate_subject(
            session, realm="client", subject_id=planted[0], password=replacement
        )


async def test_a_rule_that_arrived_after_a_password_cannot_lock_it_out(
    planted: list[uuid.UUID],
) -> None:
    """NEGATIVE CONTROL for the back door the length bounds nearly opened.

    `verify_password` deliberately does not enforce `MIN_PASSWORD_CHARS`, so raising the
    floor does not lock out everyone whose password predates the rule — but the UPGRADE
    path calls `hash_password`, which does. Without the guard in `authenticate_subject`,
    a short legacy password would verify and then be refused by its own re-hash, and the
    person would meet a 400 about length on a CORRECT sign-in.

    Simulated the only honest way: install a hash of a password shorter than the floor
    (the state a floor increase creates), then sign in with it. `needs_rehash` is forced
    by writing the row under weaker Argon2 parameters, so the upgrade path is genuinely
    entered rather than skipped.
    """
    short = "short-one"
    assert len(short) < MIN_PASSWORD_CHARS
    weak = PasswordHasher(
        time_cost=1, memory_cost=8192, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
    )
    legacy = weak.hash(_peppered(short, pepper_ring()[0]))

    subject_id = planted[0]
    async with credential_session() as session:
        await session.execute(
            text("UPDATE auth_credentials SET password_hash = :h WHERE subject_id = :s"),
            {"h": legacy, "s": subject_id},
        )
        assert await authenticate_subject(
            session, realm="client", subject_id=subject_id, password=short
        )
        # And the row was left alone rather than half-upgraded.
        assert (
            await session.execute(
                text("SELECT password_hash FROM auth_credentials WHERE subject_id = :s"),
                {"s": subject_id},
            )
        ).scalar_one() == legacy


async def test_a_stale_hash_of_an_acceptable_password_is_rewritten_in_place(
    planted: list[uuid.UUID],
) -> None:
    """The upgrade path's SUCCESS half — the twin of the test above, and the reason both
    exist: one asserts the re-hash is skipped when it cannot be done, the other that it
    actually happens when it can. Either alone would pass a version that never upgrades.

    The row is written under weaker Argon2 parameters, which is exactly what a row from
    before a cost bump looks like, and the password is long enough to pass the floor. The
    sign-in must succeed AND leave a different hash behind, still matching the password.
    """
    weak = PasswordHasher(
        time_cost=1, memory_cost=8192, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
    )
    legacy = weak.hash(_peppered(PASSWORD, pepper_ring()[0]))
    subject_id = planted[0]

    async with credential_session() as session:
        await session.execute(
            text("UPDATE auth_credentials SET password_hash = :h WHERE subject_id = :s"),
            {"h": legacy, "s": subject_id},
        )
        assert await authenticate_subject(
            session, realm="client", subject_id=subject_id, password=PASSWORD
        )
        upgraded = (
            await session.execute(
                text("SELECT password_hash FROM auth_credentials WHERE subject_id = :s"),
                {"s": subject_id},
            )
        ).scalar_one()
    assert upgraded != legacy
    assert f"m={ARGON2_MEMORY_KIB}" in upgraded

    async with credential_session() as session:
        assert await authenticate_subject(
            session, realm="client", subject_id=subject_id, password=PASSWORD
        )


async def test_an_unknown_realm_is_refused_by_the_password_store_too() -> None:
    """`realm` is chosen by a dependency, never taken from the wire, so a bad value is a
    bug — and it must not become a row the CHECK constraint rejects three statements
    later. `sessions.py` has the same guard; both are asserted so neither can be dropped
    on the assumption that the other covers it."""
    async with credential_session() as session:
        with pytest.raises(ValueError, match="not an authentication realm"):
            await set_password(session, realm="ops", subject_id=uuid.uuid4(), password=PASSWORD)
        with pytest.raises(ValueError, match="not an authentication realm"):
            await authenticate_subject(
                session, realm="ops", subject_id=uuid.uuid4(), password=PASSWORD
            )


async def test_password_set_at_records_when_the_password_last_moved(
    planted: list[uuid.UUID],
) -> None:
    """The one fact a support conversation actually needs, and the only history kept."""
    at = datetime(2026, 8, 17, 4, 30, tzinfo=UTC)
    async with credential_session() as session:
        await set_password(
            session, realm="client", subject_id=planted[0], password=PASSWORD, now=at
        )
        stored = (
            await session.execute(
                text("SELECT password_set_at FROM auth_credentials WHERE subject_id = :s"),
                {"s": planted[0]},
            )
        ).scalar_one()
    assert stored == at
