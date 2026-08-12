"""Two structural gaps closed by migrations e2c47b90d5a1 and f4a8e1c07b62, and one
deliberately left open — written as the PROPERTIES the schema now guarantees, not as
assertions about DDL. `pg_indexes` says an index exists; it does not say a second open
erasure request is impossible, which is the thing anyone actually depends on.

- **One open erasure request per subject.** Guaranteed until now by
  `pg_advisory_xact_lock` inside `request_erasure`. The tests below therefore write
  WITHOUT that function, because a test that goes through the lock cannot tell whether
  the lock or the database refused — and the whole point of the migration is what
  happens to a caller who does not take it.
- **The erasure record stops being the last copy of the number.** After
  `execute_deletion_request` the row that proves we erased someone must not still hold
  them. What replaces it, `subject_ref`, has to keep answering "have we already erased
  this person?" — otherwise the fix trades one compliance failure for another.

The third item this file used to carry — a tripwire asserting the credit ledger's unique
index was still ABSENT — is gone: migration f9c2b41a8e57 added it, and the property is
now stated positively in `tests/credit_ledger_unique_index_test.py`.

House rules, inherited from `tests/schema_hardening_test.py` because it is the same
shared database: every row carries `RUN`, every assertion counts only rows this module
wrote, and every tenant is created by the test.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from apps.api.compliance.deletion import get_request, request_erasure
from apps.api.compliance.export import subject_ref
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.retention import execute_deletion_request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

RUN = uuid.uuid4().hex[:10]


def _phone(suffix: str) -> str:
    """A run-unique E.164 number. Digits only after +91, and stable in length so it
    cannot collide with another suite's fixtures or with a real Indian number."""
    tail = f"{abs(hash(RUN + suffix)) % 10**8:08d}"
    return f"+9199{tail[:8]}"


async def _make_org() -> uuid.UUID:
    """Org creation runs under the NEW org's own GUC — FORCE RLS derives WITH CHECK from
    USING, so inserting a tenant root requires app.tenant_id = the new org id."""
    org_id = uuid7()
    async with tenant_session(org_id) as s:
        await s.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Hardening2', :slug, 'active', now(), now())"
            ),
            {"id": org_id, "slug": f"sh2-{org_id.hex[:12]}"},
        )
    return org_id


_INSERT = (
    "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, scope, "
    "requested_at, created_at, completed_at) "
    "VALUES (:id, :tid, :phone, :ref, 'all', now(), now(), {completed})"
)


async def _raw_request(
    tenant_id: uuid.UUID, phone: str, *, completed: bool = False, session: Any = None
) -> uuid.UUID:
    """File a request WITHOUT `request_erasure` — no advisory lock, no dedupe read.

    This is the caller the migration exists for: an ops script, a future producer, a
    fixture. If the database is the guarantee, this path is refused; if the lock was the
    guarantee, this path sails straight through and writes the second open request.
    """
    request_id = uuid7()
    statement = text(_INSERT.format(completed="now()" if completed else "NULL"))
    params = {"id": request_id, "tid": tenant_id, "phone": phone, "ref": subject_ref(phone)}
    if session is not None:
        await session.execute(statement, params)
        return request_id
    async with tenant_session(tenant_id) as s:
        await s.execute(statement, params)
    return request_id


# ===================================== 1. one open erasure request per subject


async def test_a_second_open_request_for_one_subject_is_refused_by_the_database() -> None:
    """THE property of e2c47b90d5a1, tested where it lives.

    Nothing here touches `request_erasure`, so the advisory lock is not in the picture at
    all: two plain INSERTs, in two separate committed transactions, for one tenant and
    one number. Before the migration both succeed and the subject has two queued
    erasures, two workers racing over their rows and two certificates. After it, the
    second one cannot exist.
    """
    tenant_id = await _make_org()
    phone = _phone("double-open")

    await _raw_request(tenant_id, phone)

    with pytest.raises(IntegrityError):
        await _raw_request(tenant_id, phone)

    async with tenant_session(tenant_id) as s:
        open_rows = (
            await s.execute(
                text(
                    "SELECT count(*) FROM deletion_requests "
                    "WHERE phone_e164 = :p AND completed_at IS NULL"
                ),
                {"p": phone},
            )
        ).scalar()
    assert open_rows == 1, "an open erasure request is a singleton per subject"


async def test_two_concurrent_requesters_produce_one_open_request_between_them() -> None:
    """The RACE, not the replay: two transactions that both begin before either commits.

    This is the shape the advisory lock was covering for — both readers see "none open"
    under READ COMMITTED — and it is the shape a unique index resolves without anybody
    having agreed to take a lock. Exactly one transaction may commit; the loser blocks on
    the index until the winner commits and is then refused.
    """
    tenant_id = await _make_org()
    phone = _phone("race")

    async def _attempt() -> str:
        try:
            async with tenant_session(tenant_id) as s:
                await _raw_request(tenant_id, phone, session=s)
                # Hold the transaction open so the two genuinely overlap; without this the
                # second INSERT would merely be a replay of a committed row.
                await asyncio.sleep(0.25)
            return "committed"
        except IntegrityError:
            return "refused"

    outcomes = await asyncio.gather(_attempt(), _attempt())

    assert sorted(outcomes) == ["committed", "refused"], (
        f"exactly one of two concurrent open requests may survive, got {outcomes}"
    )
    async with tenant_session(tenant_id) as s:
        open_rows = (
            await s.execute(
                text(
                    "SELECT count(*) FROM deletion_requests "
                    "WHERE phone_e164 = :p AND completed_at IS NULL"
                ),
                {"p": phone},
            )
        ).scalar()
    assert open_rows == 1


async def test_a_completed_request_does_not_block_the_next_one() -> None:
    """The predicate, which is the reason this is a PARTIAL index.

    Erasure is not terminal for a phone number: the same person can call the same client
    next month, generate fresh personal data and exercise DPDP §12 again over it. An
    index over the whole table would make that second genuine request impossible — a
    compliance bug wearing a safety feature's clothes.
    """
    tenant_id = await _make_org()
    phone = _phone("again")

    await _raw_request(tenant_id, phone, completed=True)
    await _raw_request(tenant_id, phone, completed=True)  # two historical erasures: fine
    await _raw_request(tenant_id, phone)  # and a fresh open one on top: also fine

    async with tenant_session(tenant_id) as s:
        total = (
            await s.execute(
                text("SELECT count(*) FROM deletion_requests WHERE subject_ref = :r"),
                {"r": subject_ref(phone)},
            )
        ).scalar()
    assert total == 3


async def test_two_tenants_may_each_hold_an_open_request_for_one_person() -> None:
    """Why the key leads with `tenant_id`. Two clients may each hold data about the same
    caller and each owes them an erasure separately; a global key would let one client's
    request block another's, which is both wrong and a cross-tenant information leak —
    under FORCEd RLS a unique violation is one of the few channels through which a row
    your policy hides can announce that it exists."""
    mine, theirs = await _make_org(), await _make_org()
    phone = _phone("shared-subject")

    await _raw_request(mine, phone)
    await _raw_request(theirs, phone)  # must not collide with the other tenant's

    async with tenant_session(mine) as s:
        visible = (
            await s.execute(
                text("SELECT count(*) FROM deletion_requests WHERE phone_e164 = :p"),
                {"p": phone},
            )
        ).scalar()
    assert visible == 1, "RLS still shows each tenant only its own request"


async def test_the_producer_still_returns_the_open_request_rather_than_an_error() -> None:
    """The lock did not become useless — it became belt-and-braces, and this is the
    difference that matters to a caller. `request_erasure` serialises the two requesters
    so the loser receives the WINNER'S request (`already_open=True`); the index is what
    catches everyone who never learned about the lock."""
    tenant_id = await _make_org()
    phone = _phone("producer")

    async with tenant_session(tenant_id) as s:
        first = await request_erasure(s, tenant_id=tenant_id, phone_e164=phone)
    async with tenant_session(tenant_id) as s:
        second = await request_erasure(s, tenant_id=tenant_id, phone_e164=phone)

    assert second.id == first.id
    assert second.already_open is True
    assert second.subject_ref == subject_ref(phone)


# ============ 2. the erasure record stops being the last copy of the number


async def test_a_completed_erasure_no_longer_holds_the_number() -> None:
    """THE property of f4a8e1c07b62.

    Run the real worker over a real request and then look at the row that proves the
    erasure happened. Before this migration it still carried the subject's number in
    cleartext, on a table `apply_retention` does not sweep and `retention_policies`
    cannot describe — so the record of the erasure outlived everything it erased.
    """
    tenant_id = await _make_org()
    phone = _phone("erased")

    async with tenant_session(tenant_id) as s:
        record = await request_erasure(s, tenant_id=tenant_id, phone_e164=phone)

    result = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(record.id)}
    )
    assert result.startswith("erased")

    async with tenant_session(tenant_id) as s:
        row = (
            await s.execute(
                text(
                    "SELECT phone_e164, subject_ref, completed_at, proof->>'subject_hash' "
                    "FROM deletion_requests WHERE id = :rid"
                ),
                {"rid": record.id},
            )
        ).first()
    assert row is not None
    assert row[0] is None, "the erasure record must not be the last copy of the number"
    assert row[2] is not None, "and it is cleared by the same write that completes it"
    assert row[1] == subject_ref(phone), "the hash survives — it is what remains to ask with"
    assert row[3] == row[1], "proof and column agree, so an auditor can line them up"


async def test_have_we_erased_this_person_is_still_answerable() -> None:
    """The cost of clearing, paid. The number is gone, so the question support actually
    gets asked has to be answerable from the hash alone — otherwise the fix trades a data
    leak for an inability to honour DPDP §12's own bookkeeping."""
    tenant_id = await _make_org()
    phone = _phone("askable")

    async with tenant_session(tenant_id) as s:
        record = await request_erasure(s, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    # Exactly the query the index (tenant_id, subject_ref) exists for, from the number a
    # caller already holds. A reader who does NOT hold the number learns nothing: the hash
    # is one-way and this is the only handle left.
    async with tenant_session(tenant_id) as s:
        found = (
            await s.execute(
                text(
                    "SELECT id, completed_at IS NOT NULL FROM deletion_requests "
                    "WHERE subject_ref = :r"
                ),
                {"r": subject_ref(phone)},
            )
        ).all()
    assert [(r[0], r[1]) for r in found] == [(record.id, True)]

    # And the status read still carries a subject reference after the number is gone.
    async with tenant_session(tenant_id) as s:
        status = await get_request(s, request_id=record.id)
    assert status.subject_ref == subject_ref(phone)
    assert status.status == "completed"
    assert status.proof is not None


async def test_an_open_request_may_not_lose_its_number() -> None:
    """The CHECK that keeps the two migrations from cancelling each other.

    NULLs never conflict in a unique index, so a request that could be cleared while
    still OPEN would silently opt out of the one-open-request guarantee — and the worker
    would have nothing to resolve the subject from. The number is cleared on completion
    and at no other moment.
    """
    tenant_id = await _make_org()
    phone = _phone("premature")
    request_id = await _raw_request(tenant_id, phone)

    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as s:
            await s.execute(
                text("UPDATE deletion_requests SET phone_e164 = NULL WHERE id = :rid"),
                {"rid": request_id},
            )

    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as s:
            await s.execute(
                text(
                    "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, "
                    "scope, requested_at, created_at) "
                    "VALUES (:id, :tid, NULL, :ref, 'all', now(), now())"
                ),
                {"id": uuid7(), "tid": tenant_id, "ref": subject_ref(phone)},
            )


async def test_a_writer_that_never_heard_of_subject_ref_still_produces_a_usable_row() -> None:
    """The floor under the NOT NULL. `subject_ref` is not optional — it is the only handle
    a completed request has left — but a NOT NULL column with no default would turn every
    INSERT written before this migration into a failure in the same release, in fixtures
    and ops scripts nobody is editing today. The BEFORE INSERT trigger derives it from the
    number, identically to `compliance.export.subject_ref`, so the two definitions cannot
    drift and the old statement keeps working.
    """
    tenant_id = await _make_org()
    phone = _phone("legacy-writer")
    request_id = uuid7()

    async with tenant_session(tenant_id) as s:
        await s.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, requested_at, "
                "created_at) VALUES (:id, :tid, :p, now(), now())"
            ),
            {"id": request_id, "tid": tenant_id, "p": phone},
        )
        derived = (
            await s.execute(
                text("SELECT subject_ref FROM deletion_requests WHERE id = :rid"),
                {"rid": request_id},
            )
        ).scalar()
    assert derived == subject_ref(phone), "one definition of the reference, in two places"


async def test_a_supplied_subject_ref_is_not_overwritten() -> None:
    """The trigger fills and never overwrites, so the application remains the author of
    the reference — a table-level rewrite would make the column say something the caller
    did not write, which is the wrong place for that authority to live."""
    tenant_id = await _make_org()
    phone = _phone("authored")
    request_id = uuid7()

    async with tenant_session(tenant_id) as s:
        await s.execute(
            text(_INSERT.format(completed="NULL")),
            {"id": request_id, "tid": tenant_id, "phone": phone, "ref": "supplied-by-the-caller"},
        )
        stored = (
            await s.execute(
                text("SELECT subject_ref FROM deletion_requests WHERE id = :rid"),
                {"rid": request_id},
            )
        ).scalar()
    assert stored == "supplied-by-the-caller"


async def test_the_worker_is_still_idempotent_without_the_number() -> None:
    """A re-run of a completed erasure used to read the number and compare timestamps; it
    now has to notice completion BEFORE reading a column that is NULL. An erasure re-run
    must not produce a second, weaker proof."""
    tenant_id = await _make_org()
    phone = _phone("rerun")

    async with tenant_session(tenant_id) as s:
        record = await request_erasure(s, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    async with tenant_session(tenant_id) as s:
        proof_before = (
            await s.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :rid"), {"rid": record.id}
            )
        ).scalar()

    again = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(record.id)}
    )
    assert again == "already_completed"

    async with tenant_session(tenant_id) as s:
        proof_after = (
            await s.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :rid"), {"rid": record.id}
            )
        ).scalar()
    assert proof_after == proof_before


async def test_a_fresh_request_after_an_erasure_gets_its_own_row() -> None:
    """The full loop, which is the one a client will actually walk: erase, the number
    disappears from the record, the same person calls again next month and files again.
    The second request is a NEW open row — not a dedupe against the completed one, and
    not a collision with it."""
    tenant_id = await _make_org()
    phone = _phone("loop")

    async with tenant_session(tenant_id) as s:
        first = await request_erasure(s, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(first.id)})

    async with tenant_session(tenant_id) as s:
        second = await request_erasure(s, tenant_id=tenant_id, phone_e164=phone)

    assert second.id != first.id
    assert second.already_open is False
    assert second.status == "pending"
    assert second.subject_ref == first.subject_ref


# =================================== 3. the credit ledger index — landed, moved out
#
# This file used to end with a TRIPWIRE asserting `credit_ledger` had no unique index on
# its reference, minting a duplicate `topup` pair on every run to prove it. Its own
# docstring said to delete it in the commit that adds the index. Migration f9c2b41a8e57
# is that commit: the key turned out to be `(tenant_id, reason, ref)` rather than
# `(tenant_id, ref)`, and the positive property — the index exists and refuses a genuine
# duplicate — is asserted in `tests/credit_ledger_unique_index_test.py`.
