"""`ux_credit_ledger_tenant_reason_ref` exists and refuses a genuine duplicate.

This file replaces two tripwires — `schema_hardening_2_test::test_the_ledger_still_
accepts_the_double_credit_its_own_fixtures_write` and `schema_hardening_3_test::
test_the_reconcilers_over_charge_fixture_still_mints_a_post_cutoff_violation` — which
asserted the index was ABSENT and minted a duplicate pair per run to prove it. Migration
f9c2b41a8e57 added it, so the coverage inverts rather than disappears: what those tests
said could not be true is now stated as the thing that is.

THREE PROPERTIES, and the middle one is the reason the file is not one test:

1. **The index exists**, on `(tenant_id, reason, ref)` — not `(tenant_id, ref)`, the
   shape four earlier attempts proposed. `credit_ledger.ref` is two namespaces in one
   column and the platform tolerates a collision between them deliberately, so the
   narrower key would 500 a valid payment. `credit_ledger_uniqueness_test.py::
   test_a_call_id_and_a_payment_reference_may_collide` owns that argument; this file
   checks the schema actually carries the conclusion.
2. **It refuses a second row with the same key**, driven by INSERT rather than through
   `record_entry`, for the same reason `schema_hardening_2_test` writes its erasure
   requests without `request_erasure`: a test that goes through `lock_tenant_credits`
   cannot tell whether the lock or the database refused, and the whole point of the
   index is what happens to the future writer who never took the lock.
3. **The cutoff is exactly where the constant says**, asserted at the second, in both
   directions: a pair one second BEFORE `LEDGER_UNIQUE_INDEX_CUTOFF` is still accepted
   (the grandfathered residue hard rule 4 forbids deleting), a pair AT it is refused
   (`>=` — the boundary is inclusive). That is stronger than parsing the index
   definition out of `pg_indexes`, and it cannot be fooled by a predicate that reads
   right and compares wrong.

NOTHING HERE COMMITS A LEDGER ROW. Every database test builds its tenant and its
entries inside ONE transaction and abandons it. This is not tidiness — it is the trap
the previous attempt fell into, and `credit_ledger_uniqueness_test._RecordingSession`
carries the same scar. `credit_ledger` is append-only (hard rule 4) and the
`credit_ledger_append_only` trigger enforces it at the database, so a row this file
wrote could never be removed. A red run of the test in §2 — the index missing, both
INSERTs succeeding — would therefore leave a permanent post-cutoff duplicate on that
database, and the index this file exists to protect could never be built there again.
A test whose failure permanently breaks the thing it tests is not a tripwire, it is a
trap. So the transaction is abandoned, and on the failing path there is nothing to
abandon it from.

WHY THE DATABASE TESTS ARE GATED. They skip on a database that has not run
f9c2b41a8e57, and the gate reads `alembic_version` — NOT the presence of the index. The
difference matters: "skip if the index is missing" would pass silently on a database
whose migration is broken, which is the failure this file is supposed to catch. Gating
on the revision means that anywhere the migration HAS run, every assertion below is
enforced, and CI migrates from `base` on a fresh database every run.

The gate is not hypothetical. The shared dev database carries two duplicate groups
stamped 2027-08-27 (`UTR-DRIFT-1` and one call uuid), written by an earlier form of
`credit_ledger_uniqueness_test::test_the_residue_seed_cannot_drift_past_the_cutoff` back
when it wrote its future-dated fixture for real. Hard rule 4 makes them permanent, so
f9c2b41a8e57 cannot build there — deliberately, since a cutoff moved past 2027 to dodge
dev residue would be a cutoff that protects nothing.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from apps.api.billing import payments
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from scripts.reconcile_credit_ledger import LEDGER_UNIQUE_INDEX_CUTOFF
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

REPO_ROOT = Path(__file__).resolve().parent.parent

MIGRATION_REVISION = "f9c2b41a8e57"
INDEX = "ux_credit_ledger_tenant_reason_ref"


class _AbandonTransactionError(Exception):
    """Raised to roll the test's transaction back.

    `tenant_session` wraps its body in `session.begin()`, which commits on a clean exit
    and rolls back on an exception. Raising this on the way out is how a test that has
    to WRITE to an append-only ledger leaves the database exactly as it found it.
    """


# --- locating the migration and the database's revision --------------------------


def _migration() -> ModuleType:
    """The migration module, loaded from `alembic/versions` by revision id.

    Found by glob on the revision rather than by filename so that renaming the file —
    which alembic permits and reviewers sometimes do — does not silently disable the
    cutoff comparison below.
    """
    matches = sorted((REPO_ROOT / "alembic" / "versions").glob(f"{MIGRATION_REVISION}_*.py"))
    assert len(matches) == 1, f"expected exactly one {MIGRATION_REVISION}_*.py, found {matches}"
    spec = importlib.util.spec_from_file_location(f"_migration_{MIGRATION_REVISION}", matches[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _database_revision() -> str | None:
    async with untenanted_session() as session:
        found = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    return None if found is None else str(found)


def _revision_is_applied(current: str) -> bool:
    """Is `MIGRATION_REVISION` an ancestor of (or equal to) the database's revision?

    Walked through alembic's own `ScriptDirectory` rather than compared as a string,
    because `alembic_version` holds only the HEAD: the day a revision lands on top of
    this one, an equality check would start skipping every test in this file.
    """
    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    try:
        walked = list(script.iterate_revisions(current, "base"))
    except Exception:  # a revision this working tree does not carry
        return False
    return any(revision.revision == MIGRATION_REVISION for revision in walked)


async def _require_the_migration() -> None:
    """Skip only when this database has never run f9c2b41a8e57 — never because the
    index is missing, which is exactly what these tests are here to notice."""
    current = await _database_revision()
    if current is not None and _revision_is_applied(current):
        return
    pytest.skip(
        f"database is at alembic revision {current!r}, which does not include "
        f"{MIGRATION_REVISION}; {INDEX} is not expected to exist here"
    )


# --- writing to the ledger without leaving anything behind -----------------------

_INSERT_ORG = (
    "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
    "VALUES (:id, 'Unique Index Clinic', :slug, 'active', now(), now())"
)

_INSERT_ENTRY = (
    "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
    "occurred_at, created_at) VALUES (:id, :tid, :delta, :reason, :ref, :balance, :at, :at)"
)


async def _entry(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    reason: str,
    ref: str,
    at: datetime,
    delta: Decimal = Decimal("500"),
) -> None:
    """One ledger row, by direct INSERT.

    Deliberately NOT `record_entry`: that takes `lock_tenant_credits` first, and a test
    that goes through the lock cannot distinguish "the database refused" from "the lock
    serialized us". The index exists for the writer who never learned about the lock, so
    that is the writer this file plays.
    """
    await session.execute(
        text(_INSERT_ENTRY),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "delta": delta,
            "reason": reason,
            "ref": ref,
            "balance": delta,
            "at": at,
        },
    )


# --- 1. the migration and the reconciler agree on the cutoff ---------------------


def test_the_migration_and_the_reconciler_name_the_same_cutoff() -> None:
    """Two copies of one instant, held equal.

    The migration carries its cutoff as a frozen literal instead of importing
    `LEDGER_UNIQUE_INDEX_CUTOFF`, and that is correct: a migration must keep meaning what
    it meant on the day it ran, whatever a constant three directories away says later.
    The cost of that correctness is a duplicate, and this is the assertion that stops the
    duplicate from becoming a disagreement — the reconciler's detector, the residue seed
    and the index would otherwise be fencing off three different dates.
    """
    migration = _migration()

    assert datetime.fromisoformat(migration.CUTOFF) == LEDGER_UNIQUE_INDEX_CUTOFF
    assert LEDGER_UNIQUE_INDEX_CUTOFF.tzinfo is not None, (
        "a naive literal is read in the server's TimeZone, which is how a cutoff moves "
        "by five and a half hours on a machine set to IST"
    )
    assert migration.INDEX == INDEX
    assert f"'{migration.CUTOFF}'::timestamptz" in migration.CREATE


def test_the_migration_builds_concurrently_and_drops_unconditionally() -> None:
    """The two operational properties the statement text is the only record of.

    CONCURRENTLY because `credit_ledger` is written continuously by the post-call
    pipeline and a plain `CREATE UNIQUE INDEX` would hold a SHARE lock — blocking every
    top-up and every per-call charge — for the length of the build. And `DROP INDEX IF
    EXISTS`, unconditional, because a CONCURRENTLY build that fails leaves an INVALID
    index behind that the migration's transaction cannot roll back: the downgrade is
    also the recovery, on a database whose `alembic_version` never advanced.
    """
    migration = _migration()

    assert "CREATE UNIQUE INDEX CONCURRENTLY" in migration.CREATE
    assert f"DROP INDEX IF EXISTS {INDEX}" == migration.DROP
    assert migration.down_revision == "c1f3a7d92b46"


def test_the_key_carries_reason_and_the_predicate_carries_all_three() -> None:
    """`reason` in the key is the finding four refusals missed, so it is pinned here.

    `usage` rows carry a call id and `topup` rows carry whatever the bank printed;
    `TopUpIn.payment_ref` accepts any 3-to-120-character string, a UUID among them. The
    platform tolerates that collision rather than preventing it, so `UNIQUE (tenant_id,
    ref)` would turn a valid payment into an IntegrityError on a money route.
    """
    create = _migration().CREATE

    assert "(tenant_id, reason, ref)" in create
    assert "ref IS NOT NULL" in create
    assert "reason IN ('topup', 'usage', 'adjustment')" in create
    assert "'refund'" not in create, (
        # THIS MESSAGE USED TO SAY "refund has no writer, every refund row carries a NULL
        # ref". BOTH HALVES ARE NOW FALSE and the test below is what stops them coming
        # back: `payments.credit_refund` is a writer, and it passes the PROVIDER'S REFUND
        # ID as `ref` under `reason='refund'`. The third clause of the old message —
        # "several partial refunds against one payment reference would be legitimate" —
        # was true and is not an argument against this key: partial refunds carry
        # different REFUND ids, so `(tenant_id, 'refund', ref)` separates them exactly as
        # it separates two top-ups.
        #
        # So refund is absent from this predicate because THIS MIGRATION PREDATES THE
        # REFUND WRITER, not because the key would be wrong.
        #
        # THAT RESIDUAL IS NOW CLOSED, and this comment used to end by naming it as open.
        # `ux_credit_ledger_refund_ref` (migration `817842cf3b97`) is the partial unique
        # index this paragraph asked for, in the exact shape `ux_credit_ledger_bonus_ref`
        # took for the sibling reason. This assertion still holds and still should: it is
        # about THIS migration's predicate, and the widening correctly went into a
        # migration of its own rather than an edit of a shipped one (hard rule 8).
        # `test_the_refund_key_is_enforced_by_the_database` below is what proves the new
        # index actually bites, rather than merely existing.
        "refund is absent from this migration's predicate because the migration predates "
        "the refund writer, NOT because the key would be wrong — it is covered by "
        "`ux_credit_ledger_refund_ref` in migration 817842cf3b97, which is where a "
        "widening belongs (hard rule 8), never an edit of this shipped one"
    )


def test_a_refund_carries_a_non_null_ref_so_the_backstop_gap_is_real() -> None:
    """The fact the guard above used to deny, pinned so it cannot be denied again.

    The assertion next door reads `"'refund'" not in create`, and its old justification
    was that refund rows carry no `ref` — i.e. that there is nothing for a unique index to
    key on. If that were true the absence would be harmless and there would be no residual
    to name. It is not true, and this test is what makes the difference visible: a single
    grep for `reason="refund"` in `billing/payments.py` finds a writer handing over the
    provider's refund id.

    Read from the WRITER'S OWN SOURCE rather than by executing a refund, deliberately.
    Driving one needs a signed provider envelope and a captured payment, and all of that is
    already covered behaviourally in `razorpay_events_test.py`; what is NOT covered
    anywhere is the schema-shaped claim this file makes about which reasons carry a key.
    That claim is about what the writer passes, so what the writer passes is what is read.

    **BY AST, AND ONLY THE `record_entry` CALL — a substring search over the function is
    not strong enough, which was measured rather than assumed.** `credit_refund` mentions
    `ref=refund.refund_id` three times: once on the INSERT and twice on `find_entry_by_ref`
    (the dedupe lookup and the read-back). A version of this test that grepped the
    function body therefore stayed GREEN when the write itself was changed to `ref=None`
    — the two lookups alone satisfied it. Only the writing call says anything about what
    lands in the column, so only the writing call is inspected.
    """
    write = next(
        (
            node
            for node in ast.walk(ast.parse(inspect.getsource(payments.credit_refund)))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "record_entry"
        ),
        None,
    )
    assert write is not None, (
        "`credit_refund` no longer appends through `record_entry` — that function is the "
        "ONE writer of this ledger (`billing/service.py`), so a refund reaching the table "
        "another way is a bigger finding than the one this test was written for"
    )
    passed = {kw.arg: kw.value for kw in write.keywords}

    reason = passed.get("reason")
    assert isinstance(reason, ast.Constant) and reason.value == "refund", (
        "`credit_refund` no longer writes under reason='refund' — if that is deliberate, "
        "the guard above can go back to saying refund has no writer; if the reason moved, "
        "point this test and that guard at the new one"
    )
    ref = passed.get("ref")
    assert isinstance(ref, ast.Attribute) and ref.attr == "refund_id", (
        "a refund ledger row must carry the provider's refund id as its `ref`: that pair "
        "IS the idempotency key `credit_refund` dedupes on, and the guard above depends "
        "on it being non-NULL to be describing a real backstop gap rather than a harmless "
        "absence"
    )


# --- 2. the index is really there ------------------------------------------------


async def test_the_index_exists_on_tenant_reason_ref() -> None:
    """Present, UNIQUE, partial, and keyed the way the migration says.

    Read from `pg_index` rather than trusted from the migration file: a revision that
    ran is not the same fact as an index that is there and valid, and the gap between
    those two is precisely what a failed CONCURRENTLY build leaves behind.
    """
    await _require_the_migration()

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT i.indisunique, i.indisvalid, i.indpred IS NOT NULL, "
                    "  pg_get_indexdef(i.indexrelid) "
                    "FROM pg_index i WHERE i.indexrelid = to_regclass(:name)"
                ),
                {"name": INDEX},
            )
        ).first()

    assert row is not None, f"{INDEX} is missing on a database that ran {MIGRATION_REVISION}"
    assert row[0] is True, "a non-unique index would enforce nothing"
    assert row[1] is True, (
        "the index is INVALID — a CONCURRENTLY build failed and left this behind; drop "
        f"it (DROP INDEX IF EXISTS {INDEX}) and re-run the migration"
    )
    assert row[2] is True, "it must be PARTIAL: a full index cannot build over the residue"
    assert "btree (tenant_id, reason, ref)" in str(row[3]), str(row[3])


# --- 3. it refuses a genuine duplicate -------------------------------------------


async def test_a_second_entry_with_the_same_tenant_reason_and_ref_is_refused() -> None:
    """THE property, driven by the writer the index exists for.

    Two `topup` rows, one tenant, one payment reference, both after the cutoff — the
    exact shape the check-then-write race produced before the dedupe SELECT moved inside
    `lock_tenant_credits`. Written by direct INSERT, so nothing here takes the advisory
    lock and the refusal can only be the database's.

    Both rows and the tenant they belong to are abandoned with the transaction. If this
    test ever goes red the second INSERT succeeded, and a committed second row would be
    an undeletable post-cutoff duplicate (hard rule 4) that makes the index unbuildable
    on this database forever.
    """
    await _require_the_migration()
    tenant_id = uuid7()
    ref = f"UTR-UNIQ-{uuid.uuid4().hex[:10]}"
    at = LEDGER_UNIQUE_INDEX_CUTOFF + timedelta(days=1)

    with pytest.raises(_AbandonTransactionError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(_INSERT_ORG), {"id": tenant_id, "slug": f"uxi-{tenant_id.hex[:12]}"}
            )
            await _entry(session, tenant_id, reason="topup", ref=ref, at=at)

            with pytest.raises(IntegrityError):
                await _entry(session, tenant_id, reason="topup", ref=ref, at=at)

            raise _AbandonTransactionError


async def test_two_tenants_may_hold_the_same_payment_reference() -> None:
    """Why the key leads with `tenant_id`.

    Two clients can be sent the same bank reference — a UTR is unique to a payment, not
    to a payer, and an operator keying a cheque number can legitimately produce the same
    string twice across two businesses. A global key would let one client's entry block
    another's, and under FORCEd RLS a unique violation is one of the few channels through
    which a row your policy hides can announce that it exists.
    """
    await _require_the_migration()
    mine, theirs = uuid7(), uuid7()
    ref = f"UTR-SHARED-{uuid.uuid4().hex[:10]}"
    at = LEDGER_UNIQUE_INDEX_CUTOFF + timedelta(days=1)

    with pytest.raises(_AbandonTransactionError):
        async with tenant_session(mine) as session:
            await session.execute(text(_INSERT_ORG), {"id": mine, "slug": f"uxi-{mine.hex[:12]}"})
            await _entry(session, mine, reason="topup", ref=ref, at=at)
            raise _AbandonTransactionError

    with pytest.raises(_AbandonTransactionError):
        async with tenant_session(theirs) as session:
            await session.execute(
                text(_INSERT_ORG), {"id": theirs, "slug": f"uxi-{theirs.hex[:12]}"}
            )
            await _entry(session, theirs, reason="topup", ref=ref, at=at)
            raise _AbandonTransactionError


async def test_one_reference_under_two_reasons_is_still_accepted() -> None:
    """The collision the platform TOLERATES, and the reason the key is not
    `(tenant_id, ref)`.

    A call id and a payment reference share the `ref` column. `find_topup` scopes its
    lookup to `reason = 'topup'` and `charge_for_call` scopes its dedupe to
    `reason = 'usage'`, so the two namespaces are already kept apart in code. The index
    has to keep them apart too, or a client whose operator keys a UUID-shaped payment
    reference gets a 500 on a valid top-up.
    """
    await _require_the_migration()
    tenant_id = uuid7()
    ref = str(uuid.uuid4())
    at = LEDGER_UNIQUE_INDEX_CUTOFF + timedelta(days=1)

    with pytest.raises(_AbandonTransactionError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(_INSERT_ORG), {"id": tenant_id, "slug": f"uxi-{tenant_id.hex[:12]}"}
            )
            await _entry(session, tenant_id, reason="usage", ref=ref, at=at, delta=Decimal("-30"))
            await _entry(session, tenant_id, reason="topup", ref=ref, at=at)
            raise _AbandonTransactionError


async def test_a_null_reference_never_collides() -> None:
    """`ref IS NOT NULL` in the predicate, stated as behaviour.

    A null ref is "no idempotency key", not a key that collides — and most of this table
    carries no ref at all. If those rows were in the index, an ordinary manual adjustment
    would start failing against another one.
    """
    await _require_the_migration()
    tenant_id = uuid7()
    at = LEDGER_UNIQUE_INDEX_CUTOFF + timedelta(days=1)

    with pytest.raises(_AbandonTransactionError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(_INSERT_ORG), {"id": tenant_id, "slug": f"uxi-{tenant_id.hex[:12]}"}
            )
            for _ in range(2):
                await session.execute(
                    text(_INSERT_ENTRY),
                    {
                        "id": uuid7(),
                        "tid": tenant_id,
                        "delta": Decimal("500"),
                        "reason": "adjustment",
                        "ref": None,
                        "balance": Decimal("500"),
                        "at": at,
                    },
                )
            raise _AbandonTransactionError


# --- 4. the cutoff, to the second, in both directions ----------------------------


async def test_a_duplicate_one_second_before_the_cutoff_is_still_accepted() -> None:
    """The grandfather line, from below.

    Hard rule 4 forbids deleting the residue the pre-fix race left behind, and
    `scripts/reconcile_credit_ledger.py` does not delete it either — it appends one
    compensating entry per group and the duplicate rows REMAIN. So the residue is
    permanent, and a partial index is the only shape that could ever build. This is that
    clause, asserted rather than described.
    """
    await _require_the_migration()
    tenant_id = uuid7()
    ref = f"UTR-GRANDFATHER-{uuid.uuid4().hex[:10]}"
    at = LEDGER_UNIQUE_INDEX_CUTOFF - timedelta(seconds=1)

    with pytest.raises(_AbandonTransactionError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(_INSERT_ORG), {"id": tenant_id, "slug": f"uxi-{tenant_id.hex[:12]}"}
            )
            await _entry(session, tenant_id, reason="topup", ref=ref, at=at)
            await _entry(session, tenant_id, reason="topup", ref=ref, at=at)
            raise _AbandonTransactionError


async def test_a_duplicate_at_the_cutoff_instant_is_refused() -> None:
    """The same line from above, and the reason it is `>=` rather than `>`.

    One second separates this test from the one before it. Together they pin the cutoff
    to the exact instant `LEDGER_UNIQUE_INDEX_CUTOFF` names, in the database, without
    parsing a predicate out of `pg_indexes` — a comparison that reads right and compares
    wrong could not survive both.
    """
    await _require_the_migration()
    tenant_id = uuid7()
    ref = f"UTR-BOUNDARY-{uuid.uuid4().hex[:10]}"

    with pytest.raises(_AbandonTransactionError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(_INSERT_ORG), {"id": tenant_id, "slug": f"uxi-{tenant_id.hex[:12]}"}
            )
            await _entry(session, tenant_id, reason="topup", ref=ref, at=LEDGER_UNIQUE_INDEX_CUTOFF)
            with pytest.raises(IntegrityError):
                await _entry(
                    session, tenant_id, reason="topup", ref=ref, at=LEDGER_UNIQUE_INDEX_CUTOFF
                )
            raise _AbandonTransactionError


async def test_the_cutoff_is_not_in_the_future_of_the_database_it_guards() -> None:
    """A cutoff at or before deploy, checked against the clock rather than asserted.

    Not "the cutoff is old" — that would rot the way a relative backdate does. The
    property is that the grandfather line has already passed on the machine the index is
    guarding, because a cutoff in the future is a window in which a duplicate is legal
    and the index says nothing about it.
    """
    async with untenanted_session() as session:
        now = (await session.execute(text("SELECT now()"))).scalar()

    assert isinstance(now, datetime)
    assert now.astimezone(UTC) >= LEDGER_UNIQUE_INDEX_CUTOFF, (
        f"the cutoff {LEDGER_UNIQUE_INDEX_CUTOFF} has not happened yet on this database "
        f"(now={now}); every duplicate written until then is outside the index"
    )
