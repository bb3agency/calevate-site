"""One live account per address (D-178, migration `c7a1e93d40b8`).

AUTH-MIGRATION §2.2 named this as still open and said why `b3d9f6a2c815` could not safely
close it: `users` predates the constraint, nothing had ever enforced it, and a migration that
fails on real data at 3am is worse than an application-level refusal. So
`subjects.resolve_by_email` refused an AMBIGUOUS address loudly and the schema stayed silent.
Both halves now exist — the constraint, and the refusal that fails safe if it is ever
dropped — and this file is where the pair is measured.

WHAT THE PREDICATE BUYS. The index is `unique (lower(email)) where deactivated_at is null`,
which is the rule the application already assumed at both readers. `admin_users` has no
`deactivated_at` (an operator is removed by deleting the row), so `uq_admin_users_email_lower`
expresses the identical rule with no predicate to write. Without the predicate here, an SMB
owner whose account was deactivated could never be re-onboarded under their own address.

HARD RULE 1: this migration adds no tenant-scoped table and no tenant-scoped column, so
there is no new cross-tenant surface. `users` is platform-level by design — identity crosses
tenants, which is what `memberships` is for — and the test near the bottom asserts that
against the live catalogue rather than asserting it in prose.

SHARED DATABASE DISCIPLINE: every row hangs off ids this module mints and is deleted here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from apps.api.authn.subjects import resolve_by_email
from apps.api.db.session import untenanted_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

INDEX = "uq_users_email_lower"


@pytest_asyncio.fixture
async def planted() -> AsyncIterator[list[uuid.UUID]]:
    """Ids this test planted, deleted afterwards whatever happened."""
    ids: list[uuid.UUID] = []
    try:
        yield ids
    finally:
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [str(i) for i in ids]}
            )


async def _insert_user(ids: list[uuid.UUID], email: str, *, deactivated: bool = False) -> uuid.UUID:
    user_id = uuid.uuid4()
    ids.append(user_id)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, name, deactivated_at, "
                "created_at, updated_at) "
                "VALUES (:id, NULL, :email, 'Uniqueness Probe', "
                ":dead, now(), now())"
            ),
            {
                "id": user_id,
                "email": email,
                "dead": datetime(2026, 1, 1, tzinfo=UTC) if deactivated else None,
            },
        )
    return user_id


# ═══════════════ the constraint ═══════════════


@pytest.mark.asyncio
async def test_the_index_exists_with_the_lowered_expression_and_the_live_predicate() -> None:
    """Shape asserted against the catalogue, not against the migration source: a migration
    that ran on a database somebody had since altered would still read correctly."""
    async with untenanted_session() as session:
        definition = (
            await session.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": INDEX}
            )
        ).scalar()
    assert definition is not None, f"{INDEX} is missing — migration c7a1e93d40b8 did not run"
    assert "UNIQUE" in definition
    assert "lower(email)" in definition
    assert "deactivated_at IS NULL" in definition


@pytest.mark.asyncio
async def test_a_second_live_account_on_one_address_is_refused_by_the_database(
    planted: list[uuid.UUID],
) -> None:
    email = f"dupe-{uuid.uuid4().hex[:10]}@calevate-test.example"
    await _insert_user(planted, email)
    with pytest.raises(IntegrityError):
        await _insert_user(planted, email)


@pytest.mark.asyncio
async def test_case_alone_does_not_buy_a_second_account(planted: list[uuid.UUID]) -> None:
    """The reason the index is on the lowered value. `resolve_by_email` casefolds, so two
    rows differing only in case would be findable by the index and not by the query — one
    of them a permanent, invisible sign-in failure."""
    local = f"Mixed-{uuid.uuid4().hex[:10]}"
    await _insert_user(planted, f"{local}@calevate-test.example")
    with pytest.raises(IntegrityError):
        await _insert_user(planted, f"{local.upper()}@CALEVATE-TEST.EXAMPLE")


@pytest.mark.asyncio
async def test_a_deactivated_account_does_not_block_re_onboarding(
    planted: list[uuid.UUID],
) -> None:
    """The predicate, exercised. An owner who left and came back gets their address back."""
    email = f"returner-{uuid.uuid4().hex[:10]}@calevate-test.example"
    await _insert_user(planted, email, deactivated=True)
    live_id = await _insert_user(planted, email)

    subject = await resolve_by_email("client", email)
    assert subject is not None and subject.subject_id == live_id, (
        "the live row must be the one that resolves, with the dead one beside it"
    )


@pytest.mark.asyncio
async def test_the_application_role_cannot_drop_the_index_it_now_depends_on() -> None:
    """The constraint is not application state. `db/session.py`'s roles are not the index's
    owner, so no code path in this process — and no SQL injected into one — can remove the
    uniqueness that `_find_or_create_user`'s `ON CONFLICT` now relies on. Migrations run as
    the owner and are the only way it changes."""
    with pytest.raises(ProgrammingError) as caught:
        async with untenanted_session() as session:
            await session.execute(text(f"DROP INDEX {INDEX}"))
    assert "must be owner" in str(caught.value)


def test_the_ambiguity_refusal_survives_the_constraint_that_made_it_unreachable() -> None:
    """A guard made true by a constraint is not a guard to delete — it is the thing that
    fails safe if the constraint is ever dropped, and the ONLY thing, because a duplicate
    that reached `resolve_by_email` would otherwise be resolved by physical row order."""
    source = (
        Path(__file__).resolve().parent.parent / "apps" / "api" / "authn" / "subjects.py"
    ).read_text(encoding="utf-8")
    assert "auth_identifier_ambiguous" in source
    assert "LIMIT 2" in source, "the query must still be able to SEE a second row"


@pytest.mark.asyncio
async def test_the_invitation_path_reuses_the_live_row_rather_than_making_a_second(
    planted: list[uuid.UUID],
) -> None:
    """`_find_or_create_user`'s two outcomes, on the address that already exists.

    This is the function that gained `ON CONFLICT` — one person invited to two client
    businesses is the ordinary case (`memberships` is the many-to-many), and it must find
    the row rather than plant a rival. **Nothing exercised it before**: `accept_with_password`
    had no test at all, so the read-then-write it used to be was never driven.
    """
    from apps.api.authn.invitations import _find_or_create_user

    email = f"twice-{uuid.uuid4().hex[:10]}@calevate-test.example"
    at = datetime.now(UTC)
    first, created = await _find_or_create_user(email=email, name="Ravi", at=at)
    planted.append(first)
    assert created is True

    second, created_again = await _find_or_create_user(email=email.upper(), name=None, at=at)
    assert (second, created_again) == (first, False), (
        "a second invitation to the same address must join the existing account"
    )


@pytest.mark.asyncio
async def test_a_simultaneous_first_redemption_loses_cleanly_instead_of_duplicating(
    planted: list[uuid.UUID],
) -> None:
    """The race the constraint now decides. Two invitations to one BRAND NEW address,
    redeemed together: both read nothing, both INSERT, one conflicts, and the loser
    re-reads the winner's id. Before D-178 both inserted and the address became
    unresolvable for both people until a human merged the rows."""
    import asyncio

    email = f"race-{uuid.uuid4().hex[:10]}@calevate-test.example"
    at = datetime.now(UTC)
    results = await asyncio.gather(
        _find_or_create_user_shim(email, at), _find_or_create_user_shim(email, at)
    )
    ids = {r[0] for r in results}
    planted.extend(ids)
    assert len(ids) == 1, f"the race planted two rows: {ids}"
    assert sorted(r[1] for r in results) == [False, True], results


async def _find_or_create_user_shim(email: str, at: datetime) -> tuple[uuid.UUID, bool]:
    from apps.api.authn.invitations import _find_or_create_user

    return await _find_or_create_user(email=email, name=None, at=at)


# ═══════════════ what the constraint is NOT ═══════════════


@pytest.mark.asyncio
async def test_this_migration_added_no_tenant_scoped_object() -> None:
    """Hard rule 1, answered rather than waved at. `users` carries no `tenant_id` — identity
    crosses tenants, which is what `memberships` is for — so a unique index on it opens no
    cross-tenant surface and there is no policy for it to ship with."""
    async with untenanted_session() as session:
        columns = {
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'users'"
                    )
                )
            ).all()
        }
    assert "tenant_id" not in columns
    assert {"email", "deactivated_at"} <= columns


def test_password_migrated_at_was_not_added() -> None:
    """§11 named it; D-178 argues it is vestigial rather than pending. A column nobody
    reads is the defect `scripts/check_wiring.py` exists to catch, and the fact it would
    have carried — when this account got its first-party password — is
    `auth_credentials.password_set_at`, which is written on every path that sets one."""
    from apps.api.tenancy.models import User

    assert not hasattr(User, "password_migrated_at")
