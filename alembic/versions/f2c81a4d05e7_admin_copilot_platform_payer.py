"""the admin copilot's payer and its memory — a platform-scoped AI ledger, and admin memories

Revision ID: f2c81a4d05e7
Revises: d3b81f5c02ae
Create Date: 2026-09-01 00:00:00.000000

D-499. `apps/api/copilot/routes.py` refused the admin realm outright — one
`assert principal.tenant_id is not None` — and its docstring named the reason and the fix
in the same breath: *"an admin-realm copilot would either spend the founder's Azure
credential with no ledger row — which hard rule 7 forbids in as many words — or charge
whichever client's page happened to be open for an operator's typing … what closes it is a
platform-payer AI ledger in `billing/`, which is a money surface with its own migration and
its own append-only rules."* This is that migration.

## `platform_ai_usage` — the second AI ledger, because the first one has a tenant in its PK

`usage_events` is tenant-scoped with FORCEd RLS, and an operator asking the admin copilot a
question has no tenant at all. There are exactly three ways to record that spend and two of
them are wrong:

* put it on `usage_events` with some tenant — that is the objection the route raised,
  and the founder answered it: *"You never charge a client for your own support work."*;
* put it nowhere — hard rule 7, in as many words;
* put it on a platform-scoped ledger of its own. This.

The COLUMN SET is `usage_events`' AI subset and nothing else: `unit_type`, `qty`,
`unit_cost_paid`, `ref`, `occurred_at`, `meta`. Same names, same NUMERIC(12,4) scale, same
`ai_assist_ktok_in` / `ai_assist_ktok_out` unit vocabulary — so the two ledgers answer
"what did a thousand tokens cost" with the same units and an operator reading both does not
have to translate. What it does NOT copy is `call_id` (an operator's question is attached to
no call) and `tenant_id` (there is none — that is the whole point).

What it ADDS is `admin_user_id`: WHO spent it. `usage_events` has no equivalent because a
tenant's assist is the tenant's whatever member clicked; here the payer is the platform and
the only attribution that means anything is the operator. NOT NULL and FK to `admin_users`,
so a row of platform spend nobody can be asked about is unrepresentable.

`viewing_tenant_id` is NULLABLE and is NOT a payer. It records the tenant an operator was
looking at when they asked — the admin console's tenant page, or a D-22 view-as session —
so "what did we spend supporting this client" is a query. It is deliberately not a foreign
key with RESTRICT: a tenant that offboards must be deletable, and a support-spend row is
platform accounting that outlives the account it was about. It is `ON DELETE SET NULL`
instead, which keeps the money and drops the pointer.

## Append-only, blanket trigger, ENABLE ALWAYS — the same family as `platform_model_prices`

Hard rule 4. A ledger somebody can edit is not evidence of anything, and this one is the
sole record of spend on our own credential. `calevate_forbid_mutation` (05bba2f3c19c) for
every UPDATE and DELETE, `calevate_forbid_truncate` (a2e9f31c605d) for the statement-level
case a row trigger never sees, and `ENABLE ALWAYS` on both so
`SET session_replication_role = replica` cannot switch the immutability off with no DDL.
Registered in `db/registry.APPEND_ONLY_TABLES`, which is what `check_ledger_immutability`
walks.

## Idempotency is a UNIQUE INDEX, not a reader's `if`

`ux_platform_ai_usage_unit_ref` over `(unit_type, ref)`. `billing/platform_ai.py` inserts
`ON CONFLICT … DO NOTHING`, exactly as `record_ai_assist_usage` does against
`ux_usage_events_tenant_unit_ref`, and for the same reason: the failure to survive is one
attempt arriving twice, and a check-then-write lets both copies read "not metered yet". The
index is NOT partial — `usage_events`' predicate exists because that table also holds
per-call rows with a NULL `ref`, and this table holds nothing but assist rows, so every row
here has a `ref` and the plain unique index is the honest shape.

`ck_platform_ai_usage_ref_shape` refuses anything that is not `assist:<uuid>` at the
DATABASE, because `ref` IS the meter's off switch (`ai_quota.ASSIST_REF_PREFIX` argues it):
a key a caller could choose is a way to spend our credential for free, and the Python guard
is one `raise` away from being bypassed by a future writer.

## `admin_copilot_memories` — the operator's memory, which cannot live in the client's table

`copilot_memories.user_id` is a foreign key to `users`, and an operator is a row in
`admin_users`. `Principal.user_id` is a `users.id` on one realm and an `admin_users.id` on
the other, so writing an admin memory into that table is a foreign-key violation in the best
case and a cross-realm leak into a client's recall in the worst — a client asking their
copilot a question would get an operator's notes about their account back.

The alternative considered and REJECTED was widening `copilot_memories`: make `tenant_id`
nullable, drop the FK, add a realm discriminator. That breaks hard rule 1's shape (a
tenant-scoped table with a nullable `tenant_id` is a table whose RLS policy cannot be
written), and it puts two populations behind one `WHERE user_id =` where a bug in the
predicate is a cross-realm read. Two tables, two populations, no predicate to get wrong.

Everything else about the shape is `copilot_memories`, deliberately: same two `kind`s, same
2000-character cap, same `simple` tsvector generated column and GIN index (the console is
Telugu-first; English stemming helps none of it), same recency+relevance recall in
`copilot/admin_memory.py`. NO EMBEDDING COLUMN, for `d4a9c17e6b02`'s reason restated: there
is no embedding path in this repository to reuse, D-28 has not been decided, and a column
nobody populates is the defect CLAUDE.md names by hand.

WHAT IT DOES NOT CARRY that its client twin does: `distilled_at` and the pending-distillation
index. There is no admin distillation worker and this migration does not create one, so a
column nothing writes would be exactly that defect. `kind` still admits `semantic` because
the CHECK is the same closed set and a future distiller writes rows, not DDL.

RETENTION AND ERASURE, WHICH IS WHY THIS PARAGRAPH EXISTS RATHER THAN A SILENCE. The client
table carries a DPDP erasure arm and a 180-day clock because its rows are about a client's
data subjects. These rows are about the PLATFORM's own operators asking about the platform's
own state, and the operator is an employee, not a data principal of a client's. They are
still not kept forever: `content` goes through the same `redacted_content` pass on the way
in, the same 2000-character cap bounds one row, and `ON DELETE CASCADE` from `admin_users`
destroys an operator's memories when their account is removed. A time-based sweep is NOT
shipped here and that is stated rather than implied — it needs a retention-policy row and a
worker, neither of which this migration is entitled to invent.

**Locking.** Two `CREATE TABLE`s, four indexes, two triggers on one of the new tables.
Nothing existing is touched.

**Downgrade** drops both tables. Reversible in the schema sense; the ledger history it
destroys is not recoverable, which is the standing property of every append-only table in
this tree.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2c81a4d05e7"
down_revision: str | None = "d3b81f5c02ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The `ref` shape, spelled here as a CHECK and in `ai_quota.ASSIST_REF_PREFIX` as a regex.
#: Two spellings of one rule is normally the drift this repo calls a defect; here the
#: database's copy is the one that holds when a future writer forgets the Python guard, and
#: `tests/admin_copilot_billing_test.py` asserts the two agree rather than trusting them to.
_REF_SHAPE = (
    r"^assist:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "platform_ai_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # WHO spent it. The payer is the platform, so the operator is the only attribution
        # that means anything — and a row of our own spend nobody can be asked about is the
        # one shape this ledger must not be able to hold.
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # WHAT they were looking at, or NULL. Context, never a payer: this column has no
        # path to anybody's bill (`billing/platform_ai.py` writes it and nothing prices it).
        sa.Column("viewing_tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        # `usage_events`' vocabulary, unchanged: `ai_assist_ktok_in` / `ai_assist_ktok_out`.
        sa.Column("unit_type", sa.Text(), nullable=False),
        # Thousands of tokens, exactly (`ai_quota.ktok`). NUMERIC, never a float.
        sa.Column("qty", sa.Numeric(12, 4), nullable=False),
        # INR per unit, at `billing/rates.MONEY_Q`'s scale — the same scale
        # `usage_events.unit_cost_paid` stores, so a figure moved between the two ledgers
        # rounds in one place (hard rule 7).
        sa.Column("unit_cost_paid", sa.Numeric(12, 4), nullable=False),
        # The server-minted metering key, one per attempt (`ai_quota.new_assist_ref`).
        sa.Column("ref", sa.Text(), nullable=False),
        # The DATABASE's clock, for `record_ai_assist_usage`'s two-clock reason: the month
        # a row is counted in is read back from the row, never taken from the app process.
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        # Ids, a model name and a feature name. No prompt, no answer, no PII (hard rule 6).
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admin_users.id"],
            name=op.f("fk_platform_ai_usage_admin_user_id_admin_users"),
        ),
        # SET NULL, not RESTRICT: an offboarded tenant must be deletable, and platform
        # accounting about supporting them outlives the account. The money stays; the
        # pointer goes.
        sa.ForeignKeyConstraint(
            ["viewing_tenant_id"],
            ["organizations.id"],
            name=op.f("fk_platform_ai_usage_viewing_tenant_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_ai_usage")),
        sa.CheckConstraint("qty >= 0", name=op.f("ck_platform_ai_usage_qty_not_negative")),
        sa.CheckConstraint(
            "unit_cost_paid >= 0", name=op.f("ck_platform_ai_usage_cost_not_negative")
        ),
        sa.CheckConstraint(
            f"ref ~ '{_REF_SHAPE}'", name=op.f("ck_platform_ai_usage_ref_shape")
        ),
    )
    # THE IDEMPOTENCY. Not partial: every row here is an assist row and every one has a
    # `ref`, so `usage_events`' predicate has nothing to exclude.
    op.create_index(
        "ux_platform_ai_usage_unit_ref", "platform_ai_usage", ["unit_type", "ref"], unique=True
    )
    # "What did the admin copilot cost this month, and who spent it" — the spend board's
    # query, and the one an operator runs when the platform brake is climbing.
    op.create_index(
        "ix_platform_ai_usage_occurred",
        "platform_ai_usage",
        [sa.text("occurred_at DESC"), "admin_user_id"],
    )

    op.execute(
        "CREATE TRIGGER platform_ai_usage_append_only "
        "BEFORE UPDATE OR DELETE ON platform_ai_usage "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER platform_ai_usage_forbid_truncate "
        "BEFORE TRUNCATE ON platform_ai_usage "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(
        "ALTER TABLE platform_ai_usage ENABLE ALWAYS TRIGGER platform_ai_usage_append_only"
    )
    op.execute(
        "ALTER TABLE platform_ai_usage ENABLE ALWAYS TRIGGER platform_ai_usage_forbid_truncate"
    )

    # --- the operator's own memory ------------------------------------------------------
    op.create_table(
        "admin_copilot_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # CASCADE for `copilot_memories.user_id`'s reason: a removed operator's console
        # memories have no subject left, and RESTRICT would make this row block the
        # deletion of the person it is about.
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        # Already through `workers.redaction.redact` — `copilot/memory.redacted_content` is
        # the only sanctioned writer for both tables.
        sa.Column("content", sa.Text(), nullable=False),
        # The admin route template the browser reported: a screen NAME, never a record.
        sa.Column("screen_route", sa.String(200), nullable=True),
        # WHICH tenant the operator was looking at, so a memory formed on one client's page
        # is not recalled as a fact about the platform. Nullable — most admin screens are
        # about no tenant — and SET NULL on delete for the ledger's reason above.
        sa.Column("viewing_tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        # GENERATED ALWAYS ... STORED, `simple` and not `english`: this console is
        # Telugu-first and English stemming helps none of it (d4a9c17e6b02's reason).
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, content)", persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admin_users.id"],
            name=op.f("fk_admin_copilot_memories_admin_user_id_admin_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["viewing_tenant_id"],
            ["organizations.id"],
            name=op.f("fk_admin_copilot_memories_viewing_tenant_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_copilot_memories")),
        sa.CheckConstraint(
            "kind IN ('episodic', 'semantic')", name=op.f("ck_admin_copilot_memories_kind_enum")
        ),
        sa.CheckConstraint(
            "length(btrim(content)) > 0", name=op.f("ck_admin_copilot_memories_content_not_blank")
        ),
        sa.CheckConstraint(
            "length(content) <= 2000", name=op.f("ck_admin_copilot_memories_content_cap")
        ),
        sa.CheckConstraint(
            "kind <> 'semantic' OR screen_route IS NULL",
            name=op.f("ck_admin_copilot_memories_semantic_has_no_screen"),
        ),
    )
    # The recency channel walks this; the relevance channel walks the GIN index.
    op.create_index(
        "ix_admin_copilot_memories_user_recent",
        "admin_copilot_memories",
        ["admin_user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_admin_copilot_memories_search",
        "admin_copilot_memories",
        ["search"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index("ix_admin_copilot_memories_search", table_name="admin_copilot_memories")
    op.drop_index("ix_admin_copilot_memories_user_recent", table_name="admin_copilot_memories")
    op.drop_table("admin_copilot_memories")
    op.execute(
        "DROP TRIGGER IF EXISTS platform_ai_usage_forbid_truncate ON platform_ai_usage"
    )
    op.execute("DROP TRIGGER IF EXISTS platform_ai_usage_append_only ON platform_ai_usage")
    op.drop_index("ix_platform_ai_usage_occurred", table_name="platform_ai_usage")
    op.drop_index("ux_platform_ai_usage_unit_ref", table_name="platform_ai_usage")
    op.drop_table("platform_ai_usage")
