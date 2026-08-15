"""the national half of the DNC promise gets a writer, an artefact and a timestamp

Revision ID: a1c8e40f27b9
Revises: d7b1c48a2e93
Create Date: 2026-08-15

SECURITY-COMPLIANCE §3 certifies a campaign's contact list as "DNC-scrubbed (national
DND + tenant `dnc_list`) with scrub timestamp". Three parts, and only one of them
existed. The tenant list works. The national half was a claim about an empty set:
`dnc_list.scope='global'` was fully built on the READ side — the gate ranks it above a
tenant entry, `is_removable` refuses it, `remove_entry` has a dedicated refusal for it,
the launch scrub includes it — and had **no writer anywhere** in `apps/`, `scripts/`,
`alembic/` or the seed, because both INSERT sites hardcode `'tenant'` and the RLS
`WITH CHECK` forbids the rest. The scrub timestamp was never recorded at all.

This migration lands all three, and the shape it gives the national half is decided by
what the register actually is.

1. THE NATIONAL REGISTER CANNOT BE DOWNLOADED, SO THERE IS NO LIST TO LOAD
---------------------------------------------------------------------------
`17a91a69dee9` said "national DND sync is M2 with campaigns", which assumed a feed of
NDNC numbers we could sync into this table. There is none. Under TCCCPR 2018 the
register is the National Customer Preference Register (NCPR, formerly NDNC), it lives on
the access providers' DLT platform, and every operator's own documentation says the same
sentence: *"the preference and consent database will not be accessible to telemarketers
due to secure controls and use of blockchain technology on the DLT platform"*. A
registered telemarketer submits a list to the operator's scrub facility and gets back a
scrubbed list, a reference number, and a report **carrying only the count, not the
mobile numbers**; the scrubbed file is valid **until 23:59:59** of the day it was
produced. (Operator DLT FAQs — ucc-bsnl.co.in/faq, dltconnect.airtel.in/faq,
vilpower.in/faq, ucc-mtnl.in/faq. TCCCPR 2018:
trai.gov.in/sites/default/files/2024-09/RegulationUcc19072018.pdf. Second Amendment,
12 Feb 2025: trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf. Checked
2026-08.)

So the loader that was implied here would be a producer for a feed that does not exist,
and the question of how to hold tens of millions of rows does not arise. Two further
reasons `dnc_list` would be the wrong home even with the data in hand:

* **A preference is not an absolute block.** NCPR preferences are category-scoped: a
  fully-blocked subscriber still receives TRANSACTIONAL communication, and the
  block-promotional option blocks promotional only. `check_dispatch` reads a
  `scope='global'` row as an absolute refusal for every tenant and every
  classification, so preference data in this table would refuse lawful traffic.
* **The decision is per list and per day.** What the provider returns is a verdict on
  the list you submitted, expiring the same evening — a run, not a row per number.

Hence `preference_scrub_runs` below, and hence `scope='global'` keeps a narrower and
now stated meaning: an ABSOLUTE platform-wide suppression (a regulator or TSP
instruction naming a number, or our own permanent refusal), written by ops.

2. THE `WITH CHECK` GAINS EXACTLY ONE BRANCH
---------------------------------------------
`17a91a69dee9` wrote USING and WITH CHECK separately so no tenant could suppress a
number for every other client, and that property is untouched here. What is added is a
second WITH CHECK branch: a session with NO `app.tenant_id` may write a row that is
`tenant_id IS NULL AND scope='global'`. The third conjunct is load-bearing — without it
a TENANT session would satisfy the branch too, which is precisely the escalation the
original policy exists to prevent.

The alternative was the owner DB role, which hard rule 1 forbids in app code paths, and
which would have put the one write that blocks every tenant's dialling outside RLS
entirely. The residual risk of the widened branch runs in the safe direction: an
untenanted session that wrote a global row by mistake over-blocks dialling and can never
under-block it, and every write goes through a step-up-confirmed, audited ops route.

3. THE UNIQUE CONSTRAINT NEVER APPLIED TO GLOBAL ROWS
------------------------------------------------------
`UNIQUE (tenant_id, phone_e164)` looks like it covers both scopes and does not: Postgres
treats NULLs as distinct in a unique index, so two `tenant_id IS NULL` rows for the same
number never conflict. Nothing noticed because nothing could write one. The moment a
writer exists, `ON CONFLICT (tenant_id, phone_e164)` on a global insert matches nothing
and every retry adds another identical row, so this adds the partial unique index that
actually constrains them. `NULLS NOT DISTINCT` on the existing constraint was the other
option and was rejected: it would change the meaning of the tenant key as a side effect
of fixing the global one, and it cannot be added to a constraint in place.

4. TWO TIMESTAMPS, BECAUSE §3 NAMES TWO SCRUBS
------------------------------------------------
`campaigns.dnc_scrubbed_at` records when OUR tenant-list scrub ran — `launch_campaign`
has always performed it and never recorded when. `preference_scrub_runs.scrubbed_at`
records when the ACCESS PROVIDER ran the national one. Both are surfaced on
`GET /v1/campaigns/{id}` so an operator and a client can tell "scrubbed against both
lists" from "scrubbed against one", which was previously indistinguishable from either
side.

REVERSIBILITY. `downgrade` restores `17a91a69dee9`'s policy verbatim, drops the partial
index, the column and the table. Nothing is destroyed that was not created here except
`campaigns.dnc_scrubbed_at`, which is written by this release and read by nothing that
predates it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c8e40f27b9"
down_revision: str | None = "d7b1c48a2e93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The policy as `17a91a69dee9` wrote it — restored verbatim by `downgrade`.
_OLD_DNC_POLICY = """
CREATE POLICY tenant_isolation ON dnc_list
    USING (
        tenant_id IS NULL
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        AND scope = 'tenant'
    )
"""

# The same policy plus the ops branch. READ is untouched. The `IS NULL` on the GUC is
# what keeps a tenant session out of the second branch.
_NEW_DNC_POLICY = """
CREATE POLICY tenant_isolation ON dnc_list
    USING (
        tenant_id IS NULL
        OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
    )
    WITH CHECK (
        (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND scope = 'tenant'
        )
        OR (
            tenant_id IS NULL
            AND scope = 'global'
            AND NULLIF(current_setting('app.tenant_id', true), '') IS NULL
        )
    )
"""

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_SCRUB_POLICY = (
    "CREATE POLICY tenant_isolation ON preference_scrub_runs USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    # --- 1. dnc_list: a writer for the global scope, and a key that constrains it ----
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_index(
        "uq_dnc_list_global_phone",
        "dnc_list",
        ["phone_e164"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dnc_list")
    op.execute(_NEW_DNC_POLICY)

    # --- 2. the scrub timestamp SEC-COMP §3 promises for OUR list -------------------
    # Nullable with no backfill: a campaign launched before this column existed has no
    # honest answer, and inventing `launched_at` would be a fabricated compliance
    # artefact — the same reasoning `consent_source` was left NULL under b8e4c1d70f92.
    op.add_column("campaigns", sa.Column("dnc_scrubbed_at", sa.DateTime(timezone=True)))

    # --- 3. the national scrub artefact ----------------------------------------------
    op.create_table(
        "preference_scrub_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("scrub_ref", sa.Text(), nullable=False),
        sa.Column("scrubbed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_count", sa.Integer(), nullable=False),
        sa.Column("suppressed_count", sa.Integer(), nullable=False),
        sa.Column("recorded_by_admin_id", sa.UUID(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(provider)) >= 2",
            name=op.f("ck_preference_scrub_runs_run_names_its_provider"),
        ),
        sa.CheckConstraint(
            "length(btrim(scrub_ref)) >= 3",
            name=op.f("ck_preference_scrub_runs_run_names_its_reference"),
        ),
        sa.CheckConstraint(
            "submitted_count >= 0",
            name=op.f("ck_preference_scrub_runs_submitted_count_is_a_count"),
        ),
        sa.CheckConstraint(
            "suppressed_count >= 0 AND suppressed_count <= submitted_count",
            name=op.f("ck_preference_scrub_runs_suppressed_within_submitted"),
        ),
        sa.CheckConstraint(
            "expires_at > scrubbed_at",
            name=op.f("ck_preference_scrub_runs_run_expires_after_it_ran"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preference_scrub_runs")),
        sa.UniqueConstraint(
            "campaign_id",
            "provider",
            "scrub_ref",
            name=op.f("uq_preference_scrub_runs_one_run_per_reference"),
        ),
    )
    op.create_index(
        op.f("ix_preference_scrub_runs_tenant_id"),
        "preference_scrub_runs",
        ["tenant_id"],
        unique=False,
    )
    # The gate's read: newest run for one campaign, by the PROVIDER's clock. Declared
    # with a DESC ordering, so autogenerate cannot faithfully diff it and this migration
    # is the source of truth for its existence (DATA-MODEL §10).
    op.create_index(
        "ix_preference_scrub_runs_campaign",
        "preference_scrub_runs",
        ["campaign_id", sa.text("scrubbed_at DESC")],
        unique=False,
    )

    # NOT VALID first, VALIDATE second: the table is empty, but the pattern keeps the
    # ACCESS EXCLUSIVE lock on the referenced tables to the shortest possible window,
    # which is what `c4d9e18a72b6` established for exactly these three parents.
    op.execute(
        "ALTER TABLE preference_scrub_runs ADD CONSTRAINT "
        "fk_preference_scrub_runs_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute(
        # SET NULL, matching `first_campaign_reviews.reviewed_campaign_id`: the pointer
        # is EVIDENCE of which list was scrubbed, and losing it must neither destroy the
        # record (CASCADE) nor make a scrubbed campaign undeletable forever (RESTRICT).
        "ALTER TABLE preference_scrub_runs ADD CONSTRAINT "
        "fk_preference_scrub_runs_campaign_id_campaigns FOREIGN KEY (campaign_id) "
        "REFERENCES campaigns (id) ON DELETE SET NULL NOT VALID"
    )
    op.execute(
        "ALTER TABLE preference_scrub_runs ADD CONSTRAINT "
        "fk_preference_scrub_runs_recorded_by_admin_id_admin_users "
        "FOREIGN KEY (recorded_by_admin_id) REFERENCES admin_users (id) "
        "ON DELETE RESTRICT NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE preference_scrub_runs VALIDATE CONSTRAINT "
        "fk_preference_scrub_runs_tenant_id_organizations"
    )
    op.execute(
        "ALTER TABLE preference_scrub_runs VALIDATE CONSTRAINT "
        "fk_preference_scrub_runs_campaign_id_campaigns"
    )
    op.execute(
        "ALTER TABLE preference_scrub_runs VALIDATE CONSTRAINT "
        "fk_preference_scrub_runs_recorded_by_admin_id_admin_users"
    )

    # Hard rule 1, in the same migration as the table it protects.
    op.execute("ALTER TABLE preference_scrub_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE preference_scrub_runs FORCE ROW LEVEL SECURITY")
    op.execute(_SCRUB_POLICY)

    # Hard rule 4, with ONE bounded exception, which is the shape migration b8e3f2a71c04
    # established for `platform_secrets`.
    #
    # A scrub is evidence that a list was clean at an instant: an UPDATE that moved
    # `scrubbed_at` forward would launder a stale scrub into a fresh one, and a DELETE
    # would erase the basis for calls already placed. Both are refused.
    #
    # The exception exists because `ON DELETE SET NULL` is executed by Postgres as an
    # ordinary UPDATE of the referencing row, so the blanket `calevate_forbid_mutation`
    # would fire on it and make a scrubbed campaign undeletable forever — deciding a
    # product question as a side effect of storing evidence. So the function permits
    # EXACTLY the referential action: `campaign_id` going non-NULL → NULL with every
    # other column byte-for-byte unchanged. Nothing else, and no DELETE.
    op.execute(
        """
        CREATE FUNCTION calevate_preference_scrub_append_only() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.campaign_id IS NOT NULL
               AND NEW.campaign_id IS NULL
               AND (NEW.id, NEW.tenant_id, NEW.provider, NEW.scrub_ref, NEW.scrubbed_at,
                    NEW.expires_at, NEW.submitted_count, NEW.suppressed_count,
                    NEW.recorded_by_admin_id, NEW.recorded_at, NEW.created_at)
                   IS NOT DISTINCT FROM
                   (OLD.id, OLD.tenant_id, OLD.provider, OLD.scrub_ref, OLD.scrubbed_at,
                    OLD.expires_at, OLD.submitted_count, OLD.suppressed_count,
                    OLD.recorded_by_admin_id, OLD.recorded_at, OLD.created_at)
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION '% is append-only (hard rule 4)', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER preference_scrub_runs_append_only "
        "BEFORE UPDATE OR DELETE ON preference_scrub_runs "
        "FOR EACH ROW EXECUTE FUNCTION calevate_preference_scrub_append_only()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP TRIGGER IF EXISTS preference_scrub_runs_append_only ON preference_scrub_runs")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON preference_scrub_runs")
    op.drop_index("ix_preference_scrub_runs_campaign", table_name="preference_scrub_runs")
    op.drop_index(op.f("ix_preference_scrub_runs_tenant_id"), table_name="preference_scrub_runs")
    op.drop_table("preference_scrub_runs")
    # The FUNCTION as well as the trigger. Dropping only the trigger left the function
    # behind, and the next `upgrade` then failed on `DuplicateFunction` — a downgrade
    # that cannot be followed by an upgrade is not reversible, whatever it drops.
    op.execute("DROP FUNCTION IF EXISTS calevate_preference_scrub_append_only()")

    op.drop_column("campaigns", "dnc_scrubbed_at")

    # Back to `17a91a69dee9`'s policy exactly. Any global row this release created stays
    # readable and stops being writable, which is the state the old policy describes.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dnc_list")
    op.execute(_OLD_DNC_POLICY)
    op.drop_index("uq_dnc_list_global_phone", table_name="dnc_list")
