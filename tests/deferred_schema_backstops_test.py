"""The three deferred schema changes, proved at the DATABASE rather than in the migration.

Each was specified by an audit and held back until the alembic chain settled. A migration
that creates an index is not evidence the index BITES — these drive the property.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.anyio


async def _credit_row(tenant_id: uuid.UUID, *, reason: str, ref: str | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, reason, ref, delta, "
                "balance_after, occurred_at, created_at) VALUES (:id, :t, :r, :ref, "
                "1.0000, 1.0000, now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "r": reason, "ref": ref},
        )


async def test_the_refund_key_is_enforced_by_the_database() -> None:
    """Two refunds under one provider refund id are refused by the INDEX, not by a lock.

    The refund path's idempotency rested ENTIRELY on `lock_tenant_credits` +
    `find_entry_by_ref`. That is correct today because `credit_refund` is the sole writer
    and does take the lock — so this index is not for today, it is for the future writer
    who forgets it, which is the one failure `CreditLedgerEntry`'s docstring says these
    indexes exist for. `topup`/`usage`/`adjustment` and `bonus` each had one; `refund`,
    which carries the provider's refund id as `ref`, had neither.
    """
    tenant_id, _ = await _tenant_with_published_agent()
    ref = f"rfnd_{uuid.uuid4().hex[:12]}"
    await _credit_row(tenant_id, reason="refund", ref=ref)
    with pytest.raises(IntegrityError):
        await _credit_row(tenant_id, reason="refund", ref=ref)


async def test_a_refund_with_no_ref_is_still_allowed_twice() -> None:
    """The index is PARTIAL, and this is the arm that proves it did not over-reach.

    `ref IS NOT NULL` is in the predicate, so refunds carrying no provider reference are
    outside the key entirely. A unique index that swallowed those would refuse a second
    legitimate manual refund and turn a backstop into an outage.
    """
    tenant_id, _ = await _tenant_with_published_agent()
    await _credit_row(tenant_id, reason="refund", ref=None)
    await _credit_row(tenant_id, reason="refund", ref=None)


async def test_two_tenants_may_hold_the_same_refund_reference() -> None:
    """`tenant_id` LEADS the key. Two accounts' refund references are independent, and a
    key that collided across them would be a cross-tenant failure dressed as a constraint
    (hard rule 1)."""
    first, _ = await _tenant_with_published_agent()
    second, _ = await _tenant_with_published_agent()
    ref = f"rfnd_{uuid.uuid4().hex[:12]}"
    await _credit_row(first, reason="refund", ref=ref)
    await _credit_row(second, reason="refund", ref=ref)


async def test_the_erasure_phone_lookup_has_an_index_on_every_arm() -> None:
    """The DPDP erasure's subject lookup, and why a missing arm cost a sequential scan.

    `execute_deletion_request` selects
    `WHERE from_e164 = :phone OR to_e164 = :phone OR erased_subject_ref = :ref`.
    Postgres builds a BitmapOr only when EVERY arm is indexed; with one unindexed it
    scans `calls` whole — on the one query in this repository with a statutory clock on
    it. Asserted on the catalogue rather than on a plan, because a plan on an empty test
    table is a seq scan whatever the indexes say, and would pass against the defect.
    """
    async with untenanted_session() as session:
        names = {
            str(row[0])
            for row in (
                await session.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'calls'")
                )
            ).all()
        }
    assert {"ix_calls_from_e164", "ix_calls_to_e164", "ix_calls_erased_subject_ref"} <= names, (
        "an arm of the erasure's OR lost its index — the lookup degrades to a full scan "
        "of every call the platform holds"
    )


async def test_the_phone_indexes_exclude_rows_an_erasure_already_cleared() -> None:
    """PARTIAL on the erasure's own postcondition. Erasure sets both columns to NULL, so
    `IS NOT NULL` excludes exactly the rows no later erasure can match — the index holds
    live callers only and SHRINKS as erasures are discharged."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname IN "
                    "('ix_calls_from_e164', 'ix_calls_to_e164')"
                )
            )
        ).all()
    assert len(rows) == 2
    for (definition,) in rows:
        assert "IS NOT NULL" in str(definition), (
            "the index covers erased rows too — it grows with every erasure instead of "
            "shrinking, which is backwards"
        )


async def test_deleting_an_endpoint_with_delivery_history_is_refused() -> None:
    """`RESTRICT`, not `SET NULL`, and the difference is a tenant's visibility.

    **`webhook_deliveries` HAS NO `tenant_id` COLUMN AT ALL** (verified against the live
    table, not the model). It carries no RLS policy of its own precisely because
    `endpoint_id` is its only link to a tenant — the delivery screen scopes THROUGH
    `outbound_webhooks`, the tenant-RLS'd parent.

    That makes `SET NULL` worse than "history gets detached from its endpoint": NULLing
    that column orphaned the row from EVERY tenant-scoped query in the system, since
    there is no second path back to an owner. A delivery attempt carrying a client's CRM
    payload reference would sit in the table belonging to nobody — retrievable only by an
    untenanted session, which is to say by nothing a client or an operator screen runs.
    `RESTRICT` makes the parent undeletable while that history exists, which is the
    guarantee the schema's shape already assumed it had.
    """
    tenant_id, _ = await _tenant_with_published_agent()
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, "
                "events, active, created_at, updated_at) VALUES (:id, :t, 'webhook', "
                "'https://example.invalid/hook', 'ref', ARRAY['call.completed'], true, "
                "now(), now())"
            ),
            {"id": endpoint_id, "t": tenant_id},
        )
    # `webhook_deliveries` carries NO `tenant_id` — see the docstring above — so it is
    # written through an untenanted session, exactly as the delivery recorder does.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO webhook_deliveries (id, endpoint_id, direction, status, "
                "attempts, first_at, last_at, created_at) VALUES (:id, :e, 'out', "
                "'delivered', 1, now(), now(), now())"
            ),
            {"id": uuid7(), "e": endpoint_id},
        )

    async with tenant_session(tenant_id) as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text("DELETE FROM outbound_webhooks WHERE id = :id"), {"id": endpoint_id}
            )
