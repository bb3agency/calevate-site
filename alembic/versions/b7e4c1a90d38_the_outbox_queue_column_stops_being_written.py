"""`outbox_messages.queue` stops being written by the application — step 1 of its removal

Revision ID: b7e4c1a90d38
Revises: d1b8f30c94a7
Create Date: 2026-08-18 14:10:00.000000

D-217 (closes D-162's open fork, in the direction D-162 named).

WHAT THE COLUMN IS. `outbox_messages.queue` reads as routing and routes nothing, and it
never has. `dispatch_outbox` publishes without it, `WorkerSettings` sets no `queue_name`,
and arq routes by `enqueue_job(_queue_name=...)` — so every message this platform has
ever enqueued landed on arq's single default queue whatever this column said. D-162
removed the CALLER'S choice (six call sites passed `"notifications"` or `"default"` as a
pure function of `job`) and left the column, correctly, because hard rule 8 forbids
dropping a column in the release that stops writing it.

D-162 named exactly two ways it could close: the column is dropped, or a second worker
fleet arrives and filters on it. **This takes the first**, and the second is not a near
miss — honouring the column means a second deployable (container, deploy step, CI job)
for a platform with no clients yet, which ROADMAP §6 requires a decision for and
CLAUDE.md's "monolith module before new service" argues against. Nothing about that
changed; what changed is that leaving a column nobody reads is not a third option.

WHAT THIS REVISION DOES, AND WHY IT IS NOT THE DROP. The application stops naming the
column in both `INSERT`s and stops selecting it in `claim_outbox_batch` in the SAME
change as this migration. The column is NOT NULL with no default, so an INSERT that omits
it would fail — hence the default, which moves the writer from the application to the
database and nowhere else.

That is what makes the ORDER safe. `docs/DEPLOYMENT.md` §4b describes the swap as
low-downtime, not zero-downtime: `alembic upgrade head` runs against the service database
BEFORE the containers are recreated, so for a few seconds the OLD image is still serving
against the NEW schema. Old code names the column explicitly and keeps working; new code
omits it and the default fills it. Either image is correct against this schema, which is
the property a `DROP COLUMN` here would not have — the old image's INSERT would 500 for
the length of the swap, on the table that carries password-reset emails and CRM
deliveries.

STEP 2 IS `ALTER TABLE outbox_messages DROP COLUMN queue`, in the next release, with no
code change beside it. Nothing outside this repo blocks it: it waits on one deploy of
this revision, which is the whole content of hard rule 8's second step.

NO RLS. `outbox_messages` is an infra table with no `tenant_id` and no policy, by design
(`db/registry.py` records the exemption and `retention.py` explains what it costs). This
revision creates no table and changes no policy.

LOCKING. `ALTER TABLE ... ALTER COLUMN ... SET DEFAULT` takes `AccessExclusiveLock` but
rewrites nothing and does not scan the table — it edits the catalog only (PostgreSQL 16,
`ALTER TABLE` notes: only the forms that change the row type require a rewrite). The wait
for the lock is the risk, not the work, so `SET LOCAL lock_timeout` bounds it to 5s in
both directions, the same shape `d1b8f30c94a7` uses and for the same reason.

DOWNGRADE removes the default, restoring a column an INSERT must name. That is only
correct together with the code revert, which is exactly what a downgrade of this revision
means.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7e4c1a90d38"
down_revision: str | None = "d1b8f30c94a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The one value the column has ever held, spelled here rather than imported: a migration
# is a historical fact and must not change meaning because a constant later did.
# `reliability.service.OUTBOX_FLEET` is the same string, and `tests/
# outbox_queue_deprecation_test.py` pins that the two agree for as long as both exist.
FLEET = "default"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"ALTER TABLE outbox_messages ALTER COLUMN queue SET DEFAULT '{FLEET}'")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE outbox_messages ALTER COLUMN queue DROP DEFAULT")
