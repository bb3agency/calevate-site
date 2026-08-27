"""platform_dashboard_data_use — what an operator attested about a provider's data-use terms

Revision ID: d4a83f06c1e7
Revises: f1c9d4a72b06
Create Date: 2026-08-27 00:00:00.000000

D-477. The dashboard AI assistant now prefers the provider the CLIENT's own agents run on,
and "may the assistant run on this provider" is a question about the VENDOR'S TERMS FOR OUR
ACCOUNT — not about a model's merit, not about a credential being present, and not about
anything this repository can read. Every Google-owned host is egress-blocked from this
deployment (re-measured 27 Aug 2026), so the answer arrives the way the LLM price and the
Azure resource's region already do: an operator reads it in the vendor's console and attests
it, with provenance. This table is where that lands.

## Three facts, not one signature

A single "the terms are fine" boolean is unfalsifiable and can never be re-checked. The tier
that decides the terms is a property of the vendor's PROJECT rather than of the API key, and
nothing verifiable maps a key back to its project — so the row captures the project by id
(`vendor_account_ref`, NOT NULL), and captures separately the two settings that can each
defeat the paid tier: `paid_tier_confirmed` (the project is linked to an open billing
account) and `no_training_opt_in_confirmed` (nothing on that project opts its logs back into
the vendor's unpaid terms). An attestation that asked only the first would give a false
negative on the second path, which is precisely why it is a column.

`vendor_account_ref` is the field that makes the claim RE-CHECKABLE later: Google's Cloud
Billing API answers `billingEnabled` for a project id
(`cloudbilling.googleapis.com/$discovery/rest?version=v1`, revision `20260821`, read
27 Aug 2026 — VENDOR-PUBLISHED), and a boolean with no project attached could only ever be
re-attested. Wiring that live check needs an OAuth-scoped credential this deployment does not
hold; OPERATIONS §2 gate 41 names it as the next step and says why a quarterly signature is
the wrong instrument for a setting a human can silently unlink.

## Append-only, latest-row-wins

The primary key is `(provider, attested_at)`. A correction is a NEW row, never an edit, so
"what did we believe, on whose word, and when, at the time a client's screen content reached
this vendor" stays answerable after the fact — a question a mutable row would answer with
today's belief. Resolution is the row for the provider with the greatest `attested_at`, over
`ix_platform_dashboard_data_use_provider`.

It joins the hard-rule-4 family (`db/registry.APPEND_ONLY_TABLES`) with the SHARED blanket
trigger `calevate_forbid_mutation` — no rewrap exception, because nothing here is encrypted
and no column ever needs rewriting. TRUNCATE is covered by the shared
`calevate_forbid_truncate`, and BOTH are `ENABLE ALWAYS` so
`SET session_replication_role = replica` cannot switch them off.

## Not tenant-scoped, and not a secret

One vendor account per provider for the whole deployment — no tenant whose row this could
be, so no `tenant_id`; registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` as the RLS
sweep's rule 7a requires of any `platform_*` table. It holds no credential and no PII: a
project id is an account label, not an authenticator, and it must be VISIBLE for the same
reason a price must — an attestation nobody can read is one nobody can audit.

## No config-version sentinel bump

Nothing here is a `Settings` field. `ops/pricing_snapshot.py` polls it into the in-process
snapshot the eligibility gate reads, exactly as it already does for prices and credentials,
and the attestation route triggers a refresh so the common case is immediate.

**Locking.** One `CREATE TABLE`, one index, two triggers on the new table. Nothing existing
is touched, and both trigger functions already exist (05bba2f3c19c, a2e9f31c605d).

**Downgrade** drops the table, destroying the attestation history. Recoverable only by
re-attesting from the vendor console — the same irreversibility `platform_model_prices`
carries, and for the same reason: the evidence lives off this database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4a83f06c1e7"
down_revision: str | None = "f1c9d4a72b06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "platform_dashboard_data_use",
        # `calevate_shared.engine.LlmProvider` as text, not an enum, for
        # `platform_model_prices.model`'s reason: an attestation read back to explain a past
        # decision must resolve even for a leg the product no longer declares.
        sa.Column("provider", sa.Text(), nullable=False),
        # When the operator attested it. Part of the PK, so a re-attestation is a new row and
        # two writers at one instant collide rather than silently both existing.
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attested_by", postgresql.UUID(as_uuid=True), nullable=False),
        # The vendor project/account the platform's credential for this provider belongs to.
        # Required: without it the claim can never be verified, only re-made.
        sa.Column("vendor_account_ref", sa.Text(), nullable=False),
        sa.Column("paid_tier_confirmed", sa.Boolean(), nullable=False),
        sa.Column("no_training_opt_in_confirmed", sa.Boolean(), nullable=False),
        # The operator's stated evidence — what they looked at and when. Required, because it
        # is what makes this an attestation rather than a guess.
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attested_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_dashboard_data_use_attested_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint(
            "provider", "attested_at", name=op.f("pk_platform_dashboard_data_use")
        ),
        # A project id that is blank is not a project id. Checked at the database and not
        # only at the API for the reason the price CHECK gives: the column is reachable by
        # any writer holding the untenanted role, and an empty ref makes the whole row
        # un-re-checkable while looking exactly like a complete attestation.
        sa.CheckConstraint(
            "btrim(vendor_account_ref) <> '' AND btrim(source_note) <> ''",
            name=op.f("ck_platform_dashboard_data_use_evidence_present"),
        ),
    )
    # "The latest attestation for this provider" walks this index rather than scanning the
    # provider's history.
    op.create_index(
        "ix_platform_dashboard_data_use_provider",
        "platform_dashboard_data_use",
        ["provider", sa.text("attested_at DESC")],
    )

    op.execute(
        "CREATE TRIGGER platform_dashboard_data_use_append_only "
        "BEFORE UPDATE OR DELETE ON platform_dashboard_data_use "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER platform_dashboard_data_use_forbid_truncate "
        "BEFORE TRUNCATE ON platform_dashboard_data_use "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(
        "ALTER TABLE platform_dashboard_data_use "
        "ENABLE ALWAYS TRIGGER platform_dashboard_data_use_append_only"
    )
    op.execute(
        "ALTER TABLE platform_dashboard_data_use "
        "ENABLE ALWAYS TRIGGER platform_dashboard_data_use_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DROP TRIGGER IF EXISTS platform_dashboard_data_use_forbid_truncate "
        "ON platform_dashboard_data_use"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS platform_dashboard_data_use_append_only "
        "ON platform_dashboard_data_use"
    )
    op.drop_index(
        "ix_platform_dashboard_data_use_provider", table_name="platform_dashboard_data_use"
    )
    op.drop_table("platform_dashboard_data_use")
