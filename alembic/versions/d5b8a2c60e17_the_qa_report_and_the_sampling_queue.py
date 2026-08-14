"""qa_reports + qa_call_samples — the two trust surfaces D-15 promised

Revision ID: d5b8a2c60e17
Revises: a7e2c40d9b53
Create Date: 2026-08-14 10:00:00.000000

SURFACES §2 lists "monthly QA report (D-15) rendered in-app, not just PDF" among the
trust surfaces, and SURFACES §1 lists "QA sampling: spot-check ~5% of calls per client
per week (queue surfaced in admin)". The report existed as `make qa-report` and nothing
else; the sampling queue did not exist at all. Two tables, one slice, because they are
one control: the report is what we SHOW the client, the queue is how we EARN it.

`qa_reports` — WHY STORED AT ALL
---------------------------------
The obvious in-app report runs the harness on request. It cannot: `scripts/eval.py`
replays ~110 scenarios through the extractor, which is a model call per case, and
CLAUDE.md forbids calling a model provider from a request handler for exactly this
reason. OPERATIONS §3 already says the shape — "report stored per run" — so the CLI run
IS the write, and the screen is a read of what it wrote.

Consequences accepted, both deliberate:

* **A tenant with no run has no report**, and the screen says so rather than rendering
  zeros. A QA report with no run behind it is the one thing worse than no report.
* **One row per (tenant, month-end, vertical)**, and a regeneration REPLACES it. The
  report is a pure function of (fixtures, baseline, client, vertical, as-of), so a
  second run of the same month is the same document; keeping both would be two
  identical rows and a question about which one the client sees. The history that must
  be immutable is `audit_log` (hard rule 4), not this.

`data` is the computed report (`calevate_shared.qa_report.QaReport`) and it is the ONLY
representation stored. The Markdown is not stored beside it: it is derived from `data`
by `scripts/qa_report.render_report`, and storing both is storing a chance for them to
disagree — the exact fork this slice exists to prevent.

Hard rules 5 and 6 on this table: nothing here is transcript-derived. Scenario class
labels are ours, field labels are the client's own column names, the rest are counts.
`tests/qa_report_in_app_test.py` scans the served payload against every fixture
transcript, the same way `tests/eval_qa_report_test.py` scans the Markdown.

`qa_call_samples` — WHAT MAKES A SAMPLE DEFENSIBLE
---------------------------------------------------
A spot-check that cannot be reconstructed is not a control, it is a habit. Three
properties are designed in rather than hoped for:

1. **REPRODUCIBLE.** The order is `md5(seed || call_id)` with `seed = '<tenant>:<week>'`,
   and both the seed and the row's rank are STORED. Anyone — us, a client, an auditor —
   can re-run that one SQL expression and get the same list back. `ORDER BY random()`
   and `TABLESAMPLE SYSTEM` were both rejected for the same reason: neither can answer
   "why this call and not that one" six months later, and the answer "the RNG chose it"
   is not an answer a reviewer can stand behind. (`tablesample` additionally samples
   PAGES, not rows, so on a table clustered by insertion it correlates the sample with
   arrival time.)
2. **NO SILENT RE-SAMPLING.** `UNIQUE (tenant_id, call_id)`. The weekly job is an
   INSERT ... ON CONFLICT DO NOTHING, so a re-run — a retry, a late tick, a backfill of
   an old week — converges on the same set instead of drawing a second one.
3. **THE FRAME IS RECORDED, NOT JUST THE DRAW.** `population` (how many calls the week
   held) and `target` (how many 5% came to) are on every row. Without them a queue of
   twelve rows cannot tell you whether it is 5% of 240 calls or everything the tenant
   had, and "we sample 5%" becomes an unfalsifiable claim.

The week is an IST week (Monday 00:00 IST), because an Indian business week is what is
being sampled — the same argument `IST_DAY_SQL` makes in `crm/performance.py`.

`call_id` is `ON DELETE CASCADE`, alone among this table's references. Retention and
DPDP erasure must never be blocked by a QA work list: if the call is gone, the sample of
it is not evidence of anything, and RESTRICT here would turn a legal obligation into a
foreign-key error (SEC-COMP §4).

WHAT IS NOT ON THE TABLE (hard rule 6): no transcript text, no phone number, no free-text
reviewer note. The verdict is an enum. A note field would be an operator typing what the
caller said into a cross-tenant work list, which is precisely what `admin/holds.py`
refuses for `first_campaign_rejected_reason`.

RLS
---
Both tables are tenant-scoped, so hard rule 1 in full: `tenant_id`, ENABLE + FORCE, and
the DATA-MODEL §1 `tenant_isolation` policy created in THIS migration beside the table.
Cross-tenant zero-rows proofs: `tests/qa_report_in_app_test.py::
test_tenant_b_cannot_see_tenant_as_report` and `tests/qa_sampling_test.py::
test_tenant_b_cannot_see_tenant_as_samples`, both asserted on the raw RLS-scoped session
so an endpoint that filtered in Python would still fail.

LOCKING (hard rule 8)
---------------------
`CREATE TABLE` locks only itself. The FKs point OUT at `organizations`, `calls` and
`admin_users`; a validated FK takes SHARE ROW EXCLUSIVE on the REFERENCED table, and
`calls` is written by the post-call pipeline continuously. So every FK is added NOT VALID
and VALIDATEd separately, under a `lock_timeout` so a migration that cannot get its lock
fails fast rather than queueing in front of every writer behind it.

DOWNGRADE
---------
Drops policies, indexes, then the tables. It loses stored reports (regenerable — the
harness is deterministic) and the sampling history (NOT regenerable in its reviewed
state: the draw can be recomputed, the verdicts cannot). A revert is therefore a QA
decision, not a rollback detail.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5b8a2c60e17"
down_revision: str | None = "a7e2c40d9b53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON {table} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "qa_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # The month-end the report covers. A DATE, not a timestamp: the month is the only
        # granularity G3 cares about, and a timestamp would make two runs of one month
        # two different reports.
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("vertical", sa.String(), nullable=False),
        # The extraction model the scenarios ran against. Denormalized out of `data` so
        # a query can answer "which reports were produced on the old model" without
        # opening every JSON document.
        sa.Column("model", sa.String(), nullable=False),
        # The computed report — `calevate_shared.qa_report.QaReport`, carrying its own
        # `version` so a reader can refuse a shape it does not understand.
        sa.Column("data", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qa_reports")),
        sa.UniqueConstraint(
            "tenant_id", "as_of", "vertical", name=op.f("uq_qa_reports_tenant_month_vertical")
        ),
    )
    # The screen's only query is "this tenant's reports, newest first".
    op.create_index(
        op.f("ix_qa_reports_tenant_id_as_of"),
        "qa_reports",
        ["tenant_id", sa.text("as_of DESC")],
        unique=False,
    )

    op.create_table(
        "qa_call_samples",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        # Monday of the IST week the call started in.
        sa.Column("week_start", sa.Date(), nullable=False),
        # The frame, kept so the draw is checkable: how many calls the week held, and
        # how many 5% of them came to.
        sa.Column("population", sa.Integer(), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        # This call's position in the deterministic order, 1-based.
        sa.Column("selection_rank", sa.Integer(), nullable=False),
        # The seed the order was computed from — '<tenant_id>:<week_start>'. Stored so
        # the draw can be recomputed with one SQL expression years later, by someone who
        # no longer has this code.
        sa.Column("selection_seed", sa.String(), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        # The review. NULL = not yet reviewed, which is what puts the row on the queue.
        sa.Column("verdict", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_admin_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Three things a reviewer can conclude. No free text anywhere on this table —
        # see the module docstring, hard rule 6.
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('clean', 'concern', 'defect')",
            name=op.f("ck_qa_call_samples_verdict_enum"),
        ),
        # A verdict must name its reviewer and its instant, and a reviewer without a
        # verdict is a half-written review. The three move together or not at all.
        sa.CheckConstraint(
            "(verdict IS NULL AND reviewed_at IS NULL AND reviewed_by_admin_id IS NULL) "
            "OR (verdict IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND reviewed_by_admin_id IS NOT NULL)",
            name=op.f("ck_qa_call_samples_review_is_complete_or_absent"),
        ),
        sa.CheckConstraint(
            "selection_rank >= 1 AND selection_rank <= target AND target <= population",
            name=op.f("ck_qa_call_samples_draw_fits_its_frame"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qa_call_samples")),
        # THE no-re-sampling guarantee. A re-run of the weekly job conflicts here and
        # does nothing, rather than drawing a second sample of the same week.
        sa.UniqueConstraint("tenant_id", "call_id", name=op.f("uq_qa_call_samples_tenant_call")),
    )
    # The queue's own query: this tenant's week, unreviewed first. Partial on the
    # unreviewed rows because that is the work list — reviewed rows are history and are
    # read by week, not by emptiness.
    op.create_index(
        op.f("ix_qa_call_samples_tenant_week"),
        "qa_call_samples",
        ["tenant_id", "week_start"],
        unique=False,
    )
    op.create_index(
        op.f("ix_qa_call_samples_outstanding"),
        "qa_call_samples",
        ["tenant_id", "selected_at"],
        unique=False,
        postgresql_where=sa.text("verdict IS NULL"),
    )

    # NOT VALID first, VALIDATE second — see the LOCKING note.
    for statement in (
        "ALTER TABLE qa_reports ADD CONSTRAINT fk_qa_reports_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        "ALTER TABLE qa_call_samples ADD CONSTRAINT "
        "fk_qa_call_samples_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        # CASCADE, alone on this table: an erasure or a retention sweep must never be
        # blocked by a QA work list.
        "ALTER TABLE qa_call_samples ADD CONSTRAINT fk_qa_call_samples_call_id_calls "
        "FOREIGN KEY (call_id) REFERENCES calls (id) ON DELETE CASCADE NOT VALID",
        "ALTER TABLE qa_call_samples ADD CONSTRAINT "
        "fk_qa_call_samples_reviewed_by_admin_users FOREIGN KEY (reviewed_by_admin_id) "
        "REFERENCES admin_users (id) ON DELETE RESTRICT NOT VALID",
    ):
        op.execute(statement)

    op.execute("SET LOCAL lock_timeout = '3s'")
    for constraint, table in (
        ("fk_qa_reports_tenant_id_organizations", "qa_reports"),
        ("fk_qa_call_samples_tenant_id_organizations", "qa_call_samples"),
        ("fk_qa_call_samples_call_id_calls", "qa_call_samples"),
        ("fk_qa_call_samples_reviewed_by_admin_users", "qa_call_samples"),
    ):
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")

    # Hard rule 1, in the same migration as the tables it protects.
    for table in ("qa_reports", "qa_call_samples"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_POLICY.format(table=table))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in ("qa_reports", "qa_call_samples"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index(op.f("ix_qa_call_samples_outstanding"), table_name="qa_call_samples")
    op.drop_index(op.f("ix_qa_call_samples_tenant_week"), table_name="qa_call_samples")
    op.drop_table("qa_call_samples")
    op.drop_index(op.f("ix_qa_reports_tenant_id_as_of"), table_name="qa_reports")
    op.drop_table("qa_reports")
