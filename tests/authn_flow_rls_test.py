"""Deny-by-default RLS on the two tables migration `b3d9f6a2c815` adds (hard rule 1).

`tests/authn_rls_test.py` does this for `auth_credentials` and `auth_sessions`; this is its
twin for the two that hold the material which RESETS those two — reset tokens that mint
passwords, and the one-time codes that ARE this product's second factor (D-166).

The property is the one hard rule 1 asks for, reached from the other side. None of these
carry a `tenant_id` — identity crosses tenants — so "tenant A sees none of tenant B's rows"
cannot be a `tenant_id` comparison. Instead the FORCEd policy does not consult
`app.tenant_id` AT ALL, so no value of it opens the table: tenant A sees zero rows belonging
to tenant B's owner because it sees zero rows belonging to anybody.

SHARED DATABASE DISCIPLINE: every row hangs off a `uuid4` subject this module minted, the
fixture deletes exactly those, and nothing counts rows globally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from apps.api.authn import otp, tokens
from apps.api.db.session import (
    admin_session,
    credential_session,
    invite_session,
    tenant_session,
    untenanted_session,
    user_session,
)
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

#: The two tables and the column each hangs off, so one loop drives both of them.
FLOW_TABLES = ("auth_email_tokens", "auth_otp_challenges")


@pytest_asyncio.fixture
async def planted() -> AsyncIterator[list[uuid.UUID]]:
    """Two subjects standing in for two different tenants' operators, with REAL rows in
    both tables — so "zero rows" below is a refusal and not an empty table."""
    subjects = [uuid.uuid4(), uuid.uuid4()]
    async with credential_session() as session:
        for subject_id in subjects:
            await tokens.issue_token(
                session, purpose="password_reset", realm="client", subject_id=subject_id
            )
            await otp.issue_challenge(
                session, purpose="email_verify", realm="client", subject_id=subject_id
            )
    try:
        yield subjects
    finally:
        async with credential_session() as session:
            for table in FLOW_TABLES:
                await session.execute(
                    text(f"DELETE FROM {table} WHERE subject_id = ANY(:ids)"), {"ids": subjects}
                )


async def _count(session: object, table: str, ids: list[uuid.UUID]) -> int:
    result = await session.execute(  # type: ignore[attr-defined]
        text(f"SELECT count(*) FROM {table} WHERE subject_id = ANY(:ids)"), {"ids": ids}
    )
    return int(result.scalar() or 0)


@pytest.mark.asyncio
async def test_the_credential_session_can_see_what_the_others_cannot(
    planted: list[uuid.UUID],
) -> None:
    """THE CONTROL. Without it every assertion below is satisfied by an empty table."""
    async with credential_session() as session:
        assert await _count(session, "auth_email_tokens", planted) == 2
        assert await _count(session, "auth_otp_challenges", planted) == 2


@pytest.mark.parametrize("table", FLOW_TABLES)
@pytest.mark.asyncio
async def test_a_tenant_session_sees_zero_rows(table: str, planted: list[uuid.UUID]) -> None:
    """The cross-tenant property hard rule 1 asks for. Tenant A's session cannot see the
    second factor, the recovery codes, the reset token or the live challenge of tenant B's
    owner — because it cannot see anybody's."""
    async with tenant_session(uuid.uuid4()) as session:
        assert await _count(session, table, planted) == 0


@pytest.mark.parametrize("table", FLOW_TABLES)
@pytest.mark.asyncio
async def test_every_other_session_kind_sees_zero_rows(
    table: str, planted: list[uuid.UUID]
) -> None:
    """`app.auth` is the ONLY GUC that opens these. Each of the other openers in
    `db/session.py` is driven against rows that are definitely there."""
    async with untenanted_session() as session:
        assert await _count(session, table, planted) == 0
    async with admin_session() as session:
        assert await _count(session, table, planted) == 0
    async with user_session(uuid.uuid4()) as session:
        assert await _count(session, table, planted) == 0
    async with invite_session("deadbeef" * 8) as session:
        assert await _count(session, table, planted) == 0


#: A FULLY VALID insert per table, so the ONLY thing that can refuse it is the policy.
#:
#: This matters more than it looks. A generic `INSERT (id, realm, subject_id)` would be
#: refused by a NOT NULL long before RLS was consulted — so the test would pass against a
#: table with NO POLICY AT ALL, which is exactly the false green a `WITH CHECK` test exists
#: to avoid.
_VALID_INSERT = {
    "auth_email_tokens": (
        "INSERT INTO auth_email_tokens (id, purpose, realm, subject_id, token_hash, "
        "expires_at, created_at, updated_at) VALUES (:id, 'password_reset', 'client', "
        ":sub, :b, now() + interval '1 hour', now(), now())"
    ),
    "auth_otp_challenges": (
        "INSERT INTO auth_otp_challenges (id, purpose, realm, subject_id, code_hash, "
        "expires_at, attempts, created_at, updated_at) VALUES (:id, 'email_verify', "
        "'client', :sub, :b, now() + interval '10 minutes', 0, now(), now())"
    ),
}


@pytest.mark.parametrize("table", FLOW_TABLES)
@pytest.mark.asyncio
async def test_a_tenant_session_cannot_plant_a_row_either(table: str) -> None:
    """The `WITH CHECK` half. A policy that only filtered READS would let a tenant-scoped
    code path INSERT a recovery code for an operator — which is account takeover with extra
    steps, and it would be invisible to every read-side test above."""
    subject_id = uuid.uuid4()
    with pytest.raises(ProgrammingError) as caught:
        async with tenant_session(uuid.uuid4()) as session:
            await session.execute(
                text(_VALID_INSERT[table]),
                {"id": uuid.uuid4(), "sub": subject_id, "b": b"\x00" * 12},
            )
    # The refusal must be the POLICY, not a constraint the row happened to violate.
    assert "row-level security" in str(caught.value).lower(), str(caught.value)


@pytest.mark.parametrize("table", FLOW_TABLES)
@pytest.mark.asyncio
async def test_the_same_insert_succeeds_under_the_credential_session(table: str) -> None:
    """THE CONTROL for the test above: the statement is well-formed and would land, so the
    refusal there is about authority and not about a malformed row."""
    subject_id = uuid.uuid4()
    try:
        async with credential_session() as session:
            await session.execute(
                text(_VALID_INSERT[table]),
                {"id": uuid.uuid4(), "sub": subject_id, "b": b"\x00" * 12},
            )
        async with credential_session() as session:
            assert await _count(session, table, [subject_id]) == 1
    finally:
        async with credential_session() as session:
            await session.execute(
                text(f"DELETE FROM {table} WHERE subject_id = :sub"), {"sub": subject_id}
            )


@pytest.mark.asyncio
async def test_the_policy_is_forced_so_the_owner_is_bound_by_it_too() -> None:
    """FORCE is what stops the migration role — and any future admin-role query — from
    bypassing the policy. Read from the catalogue rather than assumed."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(:names)"
                ),
                {"names": list(FLOW_TABLES)},
            )
        ).all()
    assert len(rows) == len(FLOW_TABLES)
    for name, enabled, forced in rows:
        assert enabled, f"{name} does not have row-level security enabled"
        assert forced, f"{name} does not FORCE row-level security — the owner bypasses it"


@pytest.mark.asyncio
async def test_every_flow_table_carries_exactly_the_credential_policy() -> None:
    """One policy, one predicate, spelled identically on all four — a table that drifted to
    a laxer `USING` would pass every test above that names another table."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT tablename, policyname, qual, with_check FROM pg_policies "
                    "WHERE tablename = ANY(:names)"
                ),
                {"names": list(FLOW_TABLES)},
            )
        ).all()
    assert {row[0] for row in rows} == set(FLOW_TABLES)
    for table, policy, using, with_check in rows:
        assert policy == "credential_store_only", table
        assert "app.auth" in str(using), table
        assert "app.auth" in str(with_check), table
