"""the audit chain has no index on its own order

Revision ID: d4a1e93b70c6
Revises: b3c8f27d41ae
Create Date: 2026-08-13 19:45:00.000000

`audit_log` carries a hash chain whose links are computed in `(at, id)` order, and
nothing in the schema knew that. Both chain operations sort by it and neither had an
index to sort with (`apps/api/compliance/audit.py`):

    _current_head   SELECT entry_hash FROM audit_log ORDER BY at DESC, id DESC LIMIT 1
    verify_chain    SELECT ... WHERE (at, id) > (:after_at, :after_id)
                    ORDER BY at ASC, id ASC LIMIT 1000        (keyset, repeated)

The head read is the one that hurts, and not only as latency. It runs on EVERY audit
write, INSIDE the advisory lock, so its duration is the width of the window during
which every other audit writer in the fleet is queued behind this one. Worse than the
milliseconds: unindexed it plans as a PARALLEL sequential scan, so each audit write
also claims two parallel workers for the duration — while holding the chain lock.

MEASURED, not assumed. Dev database grown to 400,182 entries (400k synthetic rows in a
rolled-back transaction), `EXPLAIN (ANALYZE, BUFFERS)` after `ANALYZE`, PG16:

    ORDER BY at DESC, id DESC LIMIT 1               buffers    time
      before   Limit -> Gather Merge (2 workers)
                 -> top-N heapsort -> Parallel Seq Scan   22,957   62.562 ms
      after    Limit -> Index Scan Backward using
                 ix_audit_log_chain                            4    0.060 ms

    one keyset page (WHERE (at, id) > (...) LIMIT 1000)
      before   Limit -> Gather Merge -> top-N heapsort
                 -> Parallel Seq Scan, row comparison
                 appearing as `Filter`                    11,468   59.816 ms
      after    Limit -> Index Only Scan, row comparison
                 appearing as `Index Cond`                    37    0.332 ms

    the whole-log walk `verify_chain` actually performs, 401 keyset pages
      before                                                       77.6 s
      after                                                        16.1 s

That last pair was run through a plpgsql harness that touches every row, so per-row
interpreter overhead is charged to BOTH arms and the query-side gap is wider than 4.8x
— the number to trust is the per-page pair above it. Either way it is the reason
`verify_chain`'s default stopped being `limit=1000` in the same change that adds this
index: making the walk cover the whole log is only defensible if walking the whole log
is seconds. Without the index the honest default would have had to stay a bound.

WHY ASC, when the hot path scans DESC — and the answer is NOT the one this migration
was first drafted with. The draft claimed a `(at DESC, id DESC)` declaration would
demote `(at, id) > (...)` from an index qual to a filter, so the keyset walk needed ASC.
That was reasoning from the shape of the problem, and it is wrong: measured, the DESC
declaration serves the row comparison as an `Index Cond` too, via `Index Only Scan
Backward`, at identical buffers and identical time. A btree is symmetric here and
neither query cares. ASC is therefore chosen for being the DEFAULT — the declaration a
reader can predict from the column list, and the one `op.create_index` writes without
an argument. There is no performance claim attached to it.

WHY NOT `(at, id)` UNIQUE. It very nearly is — `id` is uuid_v7, unique by itself — but a
unique index here would turn a clock stepping backwards into a failed INSERT on the one
table that must never refuse a write. Uniqueness buys nothing the primary key does not.

WHY NOT ALSO INDEX `entry_hash`. Nothing looks an entry up by its hash; the chain is
always walked, never probed. An index nobody queries is write amplification on the
hottest INSERT path in the compliance module.

LOCKING: `CREATE INDEX CONCURRENTLY`, the opposite call from `b9e5d2c74a18` /
`e7c3d10a9f52`, for the opposite reason. Those DROPPED indexes, and a drop is a catalog
update plus an unlink — ACCESS EXCLUSIVE for milliseconds regardless of table size, so
the exposure was the WAIT and `lock_timeout` bounded it. A BUILD is work proportional to
the table, and it holds SHARE, which blocks WRITES for its whole duration. Measured:
0.57s for the plain build on the 400k-row copy. That is small, and it is quoted here
rather than hidden because it is the honest size of what CONCURRENTLY is buying — the
argument is not this number but its trajectory. `audit_log` is append-only and never
pruned (hard rule 4), so it is the one table in the schema that only ever grows, and a
blocked audit write is a blocked audited ACTION: the lock in `write_audit` means the
stall fans out to every writer, not just the one whose statement collided. Paying a
slower build on a table that must never refuse a write is the trade this repo should
make every time. CONCURRENTLY cannot run in a transaction block, hence
`autocommit_block`; the cost is that a failed build leaves an INVALID index that must be
dropped before retrying, and `IF NOT EXISTS` keeps the retry idempotent.

DOWNGRADE drops it. A downgraded database is correct and slow: every audit write goes
back to a parallel sequential scan of the whole log, under the chain lock.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4a1e93b70c6"
down_revision: str | None = "b3c8f27d41ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_audit_log_chain"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON audit_log (at, id)")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
