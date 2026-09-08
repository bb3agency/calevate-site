"""credit_lots: the credits one purchase made, at the rates that purchase was sold at

Revision ID: c9f3a71e58d2
Revises: f2b91c47e0a3
Create Date: 2026-09-07

D-547, PLAN-CREDIT-LOTS-AND-VOICE-TIERS §3.1 and §3.4. Phase B1: the table, the FIFO
index, the freeze trigger, and the one-shot migration of every live balance into an
opening lot. The callers (pipeline, payments, credit_routes, ai_quota) are Phase B2 and
land separately; nothing in this revision changes how a call is priced today.

--------------------------------------------------------------------------------
WHY A SECOND TABLE AND NOT TWO COLUMNS ON `credit_ledger`
--------------------------------------------------------------------------------
The pack discount stops being bonus credits and becomes a CHEAPER MINUTE, frozen on the
purchase that bought it. So "what does a minute cost this client?" no longer has one
answer per tenant — it has one per purchase, and a debit has to walk them oldest-first.
The ledger cannot carry that: it is append-only (hard rule 4) and drawing a lot down is
an UPDATE. Money therefore stays on the ledger — one signed balance, untouched by this
revision — and the TERMS live here on a row that is allowed to shrink.

--------------------------------------------------------------------------------
THE FREEZE TRIGGER, AND WHY ITS ALLOWLIST IS THE MUTABLE SET
--------------------------------------------------------------------------------
`credit_lots_terms_frozen` refuses any UPDATE that changes a column outside
`_MUTABLE_COLUMNS`. It compares `to_jsonb(NEW)` minus that set against the same slice of
OLD rather than naming the frozen columns one by one, and the direction is the point: a
column added to this table next year is FROZEN by default and someone has to argue it
into the allowlist. Enumerating the frozen side instead would make every future column
silently mutable — the failure that leaves no trace.

`credits_total` IS in the allowlist, and that is ADDENDUM 2 §2.2 rather than a softening
of invariant §2.3.3. A downward restatement of a mis-recorded payment must move
`credits_total` (the amount sold), and it must floor `credits_remaining` at zero with the
shortfall becoming wallet overdraft — a lot of 5,000 with 1,000 left, restated down by
2,000, would otherwise need `credits_remaining = -1,000` and the CHECK would refuse the
write, stopping the one path an operator has to correct a bank mismatch. What §2.3.3
freezes is the TERMS — the two rates, the source, the pack, the tenant, the ledger link
and `opened_at` — and those are exactly what stays outside the allowlist. The trigger's
name says `terms_frozen` for that reason and not `append_only`: this table is not a
ledger, and `APPEND_ONLY_TABLES` deliberately does not name it.

--------------------------------------------------------------------------------
THE DATA MIGRATION (§3.4, plan §0 Q2)
--------------------------------------------------------------------------------
Every tenant whose newest ledger row carries `balance_after > 0` gets ONE opening lot at
Sarvam ₹5.00 / Cartesia ₹7.00 — the ₹5,000-pack rates, which is exactly what every
balance in existence was sold at (nobody has ever been sold a Cartesia minute, so no
promise is broken, and inventing a better rate would be a gift while a worse one would be
a breach). A zero or negative balance opens NO lot: that wallet is at or past empty, and
overdraft is a balance-level fact (invariant §2.3.1, plan §0 Q5).

Each lot is linked to a NEW **zero-delta** `adjustment` ledger row carrying
`meta.kind = 'lot_migration'`, so the ledger itself records where lots began and
`ledger_entry_id` (UNIQUE) has something real to point at. Zero delta means the balance
does not move — this migration is a re-expression of what a wallet already holds, not a
credit.

The bracket. `credit_ledger` and `organizations` are FORCE-RLS and migrations run as the
table OWNER, who is therefore subject to `tenant_isolation` — which is fail-closed on an
unset `app.tenant_id`. Unbracketed, the INSERT would match zero rows and report success
(`tests/migration_rls_bracket_test.py`, and the two production incidents it names). The
writes into `credit_lots` itself need no bracket and get none: they run BEFORE this
migration enables RLS on the table, which is the ordering `dc1aaeeeff02` established.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------
Drops the table and DELETES the marker rows. Deleting from an append-only ledger is the
one thing hard rule 4 forbids, so it is done deliberately, with the trigger disabled and
restored `ENABLE ALWAYS` in a `finally`, and for a reason that is not tidiness: the
marker's `(tenant_id, 'adjustment', 'lot_migration')` is covered by
`ux_credit_ledger_tenant_reason_ref`, so leaving the rows behind would make the NEXT
upgrade collide on the unique index and fail. A downgrade that cannot be re-upgraded is
not reversible (hard rule 8). The rows carry no money — zero delta, `balance_after`
unchanged — so nothing about any wallet moves in either direction.

What is lost on the way down is the frozen rates of any lot opened between upgrade and
rollback; the previous release prices new calls at `self_serve_inr_per_min`, which still
resolves. `runbooks/deploy-failed.md` §4 is where that sentence belongs for an operator
(plan §10) — a Phase B2 handoff, not this revision's file.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from apps.api.db.migration_offline import emit_note, execute_data_statement, is_offline

revision: str = "c9f3a71e58d2"
down_revision: str | None = "f2b91c47e0a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "credit_lots"
POLICY = "tenant_isolation"
FIFO_INDEX = "ix_credit_lots_fifo"
FREEZE_TRIGGER = "credit_lots_terms_frozen"
FREEZE_FUNCTION = "calevate_credit_lot_terms_frozen"

#: Spelled out rather than imported, as every migration here spells its constants: a
#: migration is a snapshot of the schema on the day it ran. The STRICT repo-wide form —
#: NOT the `OR <guc> IS NULL` variant, which `f2b91c47e0a3` had to correct on `kb_uploads`
#: after it bought a cross-tenant write. There is no ops-read arm here and there must not
#: be: no untenanted worker reads this table.
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"

#: `billing/models.CreditLot.LOT_SOURCES` on the day this ran.
_SOURCES = ("topup", "grant", "bonus_legacy", "migration", "override")

#: The columns a lot is allowed to change after it is opened — see the docstring. Every
#: other column, INCLUDING ONE ADDED LATER, is frozen by the trigger below.
_MUTABLE_COLUMNS = ("credits_remaining", "credits_total", "closed_at", "updated_at")

#: Plan §0 Q2. Frozen digits in a migration, never a constant imported from the rate card:
#: the card moves, and what these balances were sold at does not.
_MIGRATION_SARVAM_INR_PER_MIN = "5.0000"
_MIGRATION_CARTESIA_INR_PER_MIN = "7.0000"

#: The ledger row that records where lots began. `ref` is fixed rather than random so the
#: rows are findable by a human and so a second attempt collides on
#: `ux_credit_ledger_tenant_reason_ref` instead of double-writing.
_MARKER_REASON = "adjustment"
_MARKER_REF = "lot_migration"
_MARKER_KIND = "lot_migration"

#: One zero-delta marker per tenant whose newest entry leaves them in credit. `DISTINCT ON`
#: with this ORDER BY is `billing/service._newest_balance`'s definition of "newest",
#: verbatim, so the two can never disagree about which row is the balance.
_INSERT_MARKERS = f"""
INSERT INTO credit_ledger
    (id, tenant_id, delta, reason, ref, balance_after, occurred_at, meta, created_at)
SELECT gen_random_uuid(), newest.tenant_id, 0, '{_MARKER_REASON}', '{_MARKER_REF}',
       newest.balance_after, clock_timestamp(),
       jsonb_build_object('kind', '{_MARKER_KIND}'), clock_timestamp()
FROM (
    SELECT DISTINCT ON (tenant_id) tenant_id, balance_after
    FROM credit_ledger
    ORDER BY tenant_id, occurred_at DESC, id DESC
) AS newest
WHERE newest.balance_after > 0
"""

#: One opening lot per marker. Reading the balance back off the MARKER rather than
#: recomputing it means the lot and the ledger row it names cannot describe two different
#: amounts, whatever ran between the two statements.
_INSERT_LOTS = f"""
INSERT INTO {TABLE}
    (id, tenant_id, source, pack_id, override_of_pack_id, credits_total,
     credits_remaining, sarvam_inr_per_min, cartesia_inr_per_min, ledger_entry_id,
     opened_at, closed_at, created_at, updated_at)
SELECT gen_random_uuid(), marker.tenant_id, 'migration', NULL, NULL,
       marker.balance_after, marker.balance_after,
       {_MIGRATION_SARVAM_INR_PER_MIN}, {_MIGRATION_CARTESIA_INR_PER_MIN},
       marker.id, marker.occurred_at, NULL, clock_timestamp(), clock_timestamp()
FROM credit_ledger AS marker
WHERE marker.reason = '{_MARKER_REASON}'
  AND marker.ref = '{_MARKER_REF}'
  AND marker.meta ->> 'kind' = '{_MARKER_KIND}'
"""

_DELETE_MARKERS = f"""
DELETE FROM credit_ledger
WHERE reason = '{_MARKER_REASON}'
  AND ref = '{_MARKER_REF}'
  AND meta ->> 'kind' = '{_MARKER_KIND}'
  AND delta = 0
"""


def _jsonb_terms(row: str) -> str:
    """The frozen slice of a row, as jsonb: everything except `_MUTABLE_COLUMNS`."""
    keys = ", ".join(f"'{column}'" for column in _MUTABLE_COLUMNS)
    return f"(to_jsonb({row}) - ARRAY[{keys}]::text[])"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("pack_id", sa.Text(), nullable=True),
        sa.Column("override_of_pack_id", sa.Text(), nullable=True),
        sa.Column("credits_total", sa.Numeric(12, 4), nullable=False),
        sa.Column("credits_remaining", sa.Numeric(12, 4), nullable=False),
        sa.Column("sarvam_inr_per_min", sa.Numeric(12, 4), nullable=False),
        sa.Column("cartesia_inr_per_min", sa.Numeric(12, 4), nullable=False),
        sa.Column("ledger_entry_id", sa.UUID(), nullable=False),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_lots")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_credit_lots_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        # RESTRICT, like every other money FK here: the ledger is append-only, so this
        # can only ever fire against a hand-run DELETE, and refusing one that would
        # orphan a lot is the right answer.
        sa.ForeignKeyConstraint(
            ["ledger_entry_id"],
            ["credit_ledger.id"],
            name=op.f("fk_credit_lots_ledger_entry_id_credit_ledger"),
            ondelete="RESTRICT",
        ),
        # ONE lot per credit-adding entry. A replayed payment that somehow reached the
        # opener twice cannot open a second lot for money that arrived once.
        sa.UniqueConstraint("ledger_entry_id", name=op.f("uq_credit_lots_ledger_entry_id")),
        sa.CheckConstraint(f"source IN {_SOURCES!r}", name=op.f("ck_credit_lots_source_enum")),
        sa.CheckConstraint("credits_total > 0", name=op.f("ck_credit_lots_total_positive")),
        sa.CheckConstraint(
            "credits_remaining >= 0 AND credits_remaining <= credits_total",
            name=op.f("ck_credit_lots_remaining_within_total"),
        ),
        sa.CheckConstraint(
            "sarvam_inr_per_min > 0", name=op.f("ck_credit_lots_sarvam_rate_positive")
        ),
        sa.CheckConstraint(
            "cartesia_inr_per_min >= sarvam_inr_per_min",
            name=op.f("ck_credit_lots_cartesia_not_below_sarvam"),
        ),
    )
    # THE FIFO SCAN (invariant §2.3.2): `WHERE tenant_id = :t AND closed_at IS NULL
    # ORDER BY opened_at, id`. Partial, because a spent lot is the steady state and is
    # never walked again — the index stays the size of the open positions, not of the
    # history.
    op.create_index(
        FIFO_INDEX,
        TABLE,
        ["tenant_id", "opened_at", "id"],
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.execute(
        f"""
        CREATE FUNCTION {FREEZE_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            IF {_jsonb_terms("NEW")} IS DISTINCT FROM {_jsonb_terms("OLD")} THEN
                RAISE EXCEPTION
                    'credit_lots: a lot''s terms are frozen (invariant 2.3.3) — only '
                    '{", ".join(_MUTABLE_COLUMNS)} may change after it is opened'
                    USING ERRCODE = 'raise_exception';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"CREATE TRIGGER {FREEZE_TRIGGER} BEFORE UPDATE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {FREEZE_FUNCTION}()"
    )
    # ENABLE ALWAYS for the reason the append-only triggers carry it: otherwise
    # `SET session_replication_role = replica` switches the freeze off with no DDL and
    # no schema diff.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {FREEZE_TRIGGER}")

    # ── the data migration (§3.4). Before RLS goes on this table, bracketed for the two
    # FORCE-RLS tables it reads and writes.
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE credit_ledger NO FORCE ROW LEVEL SECURITY")
    try:
        # BOTH STATEMENTS ARE EMITTED OFFLINE, AND THIS IS A MONEY MIGRATION, so the choice
        # is stated rather than assumed: `--sql` renders a script a human reviews and
        # applies, and a script that created `credit_lots` while silently omitting the two
        # INSERTs would leave every funded wallet with a balance and NO OPEN LOT — the
        # exact state `billing/service` reads as "nothing to consume from". Both statements
        # are fixed text with no bound values, so what is emitted is byte-for-byte what the
        # online run executes, in the same order, inside the same RLS bracket. Only the two
        # row counts are impossible, and neither decides anything: they are the numbers in
        # the operator sentence below.
        markers = execute_data_statement(
            sa.text(_INSERT_MARKERS),
            note=(
                "offline `--sql`: the zero-delta marker entries are emitted in full "
                "below.\nTheir row count cannot be taken while rendering."
            ),
        )
        lots = execute_data_statement(
            sa.text(_INSERT_LOTS),
            note=(
                "offline `--sql`: the opening lot per marker is emitted in full "
                "below.\nIts row count cannot be taken while rendering."
            ),
        )
    finally:
        # Restored in a `finally` for `b7e35c2f81da`'s reason: DDL is transactional, so a
        # failure would roll the bracket back anyway — but a bracket that leans on the
        # transaction reads as if it need not be closed, and half a bracket is a tenancy
        # hole no RLS coverage check can see.
        op.execute("ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    # FORCE so the guarantee binds the table owner too — without it the owner is exempt
    # and the policy is a suggestion (hard rule 1).
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )

    # stdout, for `a8d3f61c04e7`'s reason: this is the sentence the person running the
    # deploy reads and `logging` reaches nothing here. OFFLINE stdout IS THE SCRIPT, so the
    # same sentence goes into it as a SQL comment instead — without the two counts, and
    # with the query that recovers them after the script is applied.
    if is_offline():
        emit_note(
            "D-547: this script opens one migration lot per wallet holding a positive "
            f"balance,\nat ₹{_MIGRATION_SARVAM_INR_PER_MIN} Sarvam / "
            f"₹{_MIGRATION_CARTESIA_INR_PER_MIN} Cartesia per minute. Wallets with a zero "
            "or negative\nbalance open none. NO BALANCE MOVES: every marker entry carries "
            "a zero delta. How\nmany lots were opened cannot be counted while rendering; "
            "after applying, run:\nSELECT count(*) FROM credit_lots WHERE source = "
            "'migration';"
        )
        return
    print(  # noqa: T201 - the deploy log is this statement's only reader
        f"D-547: opened {lots} migration lot(s) from {markers} marker entry(ies) at "
        f"₹{_MIGRATION_SARVAM_INR_PER_MIN} Sarvam / ₹{_MIGRATION_CARTESIA_INR_PER_MIN} "
        "Cartesia per minute. Wallets with a zero or negative balance opened none. No "
        "balance moved: every marker entry carries a zero delta."
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {FREEZE_TRIGGER} ON {TABLE}")
    op.drop_index(FIFO_INDEX, table_name=TABLE)
    op.drop_table(TABLE)
    op.execute(f"DROP FUNCTION IF EXISTS {FREEZE_FUNCTION}()")

    # The marker rows, and the deliberate suspension of hard rule 4 that removing them
    # needs — see the module docstring. `ENABLE ALWAYS` on the way back, never a plain
    # `ENABLE`, which would silently downgrade the trigger to origin-only and leave
    # `scripts/check_ledger_immutability` staring at a ledger that a replica-mode session
    # could edit.
    op.execute("ALTER TABLE credit_ledger DISABLE TRIGGER credit_ledger_append_only")
    op.execute("ALTER TABLE credit_ledger NO FORCE ROW LEVEL SECURITY")
    try:
        # EMITTED OFFLINE for the upgrade's reason inverted: the marker rows are what the
        # upgrade wrote, and a downgrade script that dropped `credit_lots` without removing
        # them would leave orphan zero-delta entries in an append-only ledger that nothing
        # afterwards knows how to explain. Fixed text, no count read.
        execute_data_statement(
            sa.text(_DELETE_MARKERS),
            note=(
                "offline `--sql`: the marker rows this revision wrote are deleted below — "
                "the\ndeliberate suspension of hard rule 4 described in this migration's "
                "docstring,\nemitted with the trigger disable/enable bracket around it."
            ),
        )
    finally:
        op.execute("ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE credit_ledger ENABLE ALWAYS TRIGGER credit_ledger_append_only")
