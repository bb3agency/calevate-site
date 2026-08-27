"""agreements a client actually accepted

Revision ID: a9d4e70c31b8
Revises: e1f7a3c920b4
Create Date: 2026-08-26

Eight legal documents have been published at `/legal/<slug>` since the legal sweep, and
nothing in this product has ever asked a client to accept any of them. The DPA is the
loudest gap — LEGAL-OPS-PLAYBOOK.md:475 lists it as *"client signs or clickwrap"* — but
the Terms, the Privacy Policy and the Acceptable Use Policy are in the same position: a
client can dial today without ever having agreed to the rules the campaign gate enforces
against them, which makes the indemnity in `/legal/terms` a document nobody is party to.
This migration is where the acceptance lives.

--------------------------------------------------------------------------------
WHY A LEDGER RATHER THAN COLUMNS ON `organizations`
--------------------------------------------------------------------------------

The obvious shape is `organizations.terms_accepted_at` and friends. It is wrong for the
same reason the WhatsApp opt-in did not become three columns on `organizations`
(migration e6b2d94f31a7):

1. **A new version has to re-ask, and a column cannot hold the history.** The whole point
   of `document_version` is that an acceptance is of a SPECIFIC text. Overwriting the
   timestamp when a client re-accepts destroys the record of the version they were
   operating under before — which is precisely the period a dispute is about.
2. **It names a PERSON, and an organisation column cannot.** Only the owner may accept
   (`legal/routes.py`), and an owner handover must not silently inherit the previous
   owner's signature.
3. **Four documents, not one.** A column per document is a schema change per document.

--------------------------------------------------------------------------------
WHAT THE ROW CARRIES AS EVIDENCE, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------------------------------------

Five facts: which document, which version, which acceptance wording was on the screen,
who clicked, and when. `apps/api/legal/models.py` argues each one.

**There is no `ip` and no `user_agent` column.** They are the conventional clickwrap
evidence and they are already recorded: `compliance/audit.write_audit` stamps the caller's
IP into the hash-chained `audit_log` (`scripts/check_audit_ip.py` exists to keep it doing
so), the acceptance row and its audit row commit in the SAME transaction, and the audit
row names the acceptance by id. A copy here would be the same value written by the same
statement into a table with WEAKER guarantees — append-only, but not hash-chained — while
adding a second store of personal data with its own retention obligation, inside a table
the client's own console reads. A user-agent string adds a device fingerprint on top of
that and settles nothing anybody has ever disputed. Recorded once, in the strongest place,
and cited from here.

--------------------------------------------------------------------------------
THE TABLE
--------------------------------------------------------------------------------

Tenant-scoped, so it ships WITH its FORCEd `tenant_isolation` policy in this same
migration (hard rule 1) and with the cross-tenant zero-rows test in
`tests/legal_agreements_test.py`. Append-only, so it carries the `calevate_forbid_mutation`
trigger migration 05bba2f3c19c created (hard rule 4) and is listed in
`APPEND_ONLY_TABLES`. It also carries the statement-level `calevate_forbid_truncate`
trigger migration a2e9f31c605d created, because a `FOR EACH ROW` trigger never fires on
TRUNCATE and a ledger emptiable by one word is not append-only; both are `ENABLE ALWAYS`
so a `session_replication_role = replica` session cannot step around them. An acceptance
is contract formation, not consent, so unlike
`consent_ledger` and `whatsapp_alert_optin_ledger` there is no withdrawal row and no
status column: a client who ends the engagement does not un-accept the terms they operated
under last month, and a table that let them would destroy the evidence for that period.

The CHECKs are three non-blank assertions and nothing else. Which slugs are ACCEPTABLE is
a product decision (`legal/catalogue.ACCEPTABLE_SLUGS`) that must be able to change when a
ninth document is published, and the service refuses an unknown slug before the INSERT; a
CHECK enumerating today's four would make publishing a new agreement a schema migration.
What the database guarantees is that no stored row is meaningless.

The index is exactly the read the gate runs — the latest row for one (tenant, document) —
with `document_version` INCLUDEd so the lookup is index-only. `(accepted_at DESC,
created_at DESC)` for the reason `ix_whatsapp_alert_optin_current` uses both: one is when
the person clicked and the other is when we wrote it down, and two rows in the same instant
must still resolve deterministically rather than by planner whim.

NOT `CONCURRENTLY`: a concurrent build cannot run inside alembic's transaction, and the
table is new and empty, so the build is instantaneous. (`f9c2b41a8e57`'s CONCURRENTLY
index is the cautionary tale — a failed concurrent build leaves an INVALID index.)

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Reversible in hard rule 8's sense and honestly so: the table is NEW, nothing backfills it,
and no pre-existing column changes meaning. `downgrade` drops it whole.

The consequence to state rather than discover: reverting removes the agreements gate
entirely, so every organisation goes back to being able to dial and publish without having
accepted anything — the behaviour of the release before this one, which is why the revert
is safe, and a compliance decision rather than a rollback, which is why it is written
down. And an acceptance destroyed by a downgrade is one the client has to be asked for
again, so a revert that has been live long enough to collect rows should dump the table
first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4e70c31b8"
down_revision: str | None = "e1f7a3c920b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "legal_acceptances"
IX_CURRENT = "ix_legal_acceptances_current"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # The `/legal/<slug>` segment. Stable — these pages are linked from contracts.
        sa.Column("document_slug", sa.Text(), nullable=False),
        # The version in force when the person clicked, review state included
        # (`legal/catalogue.version_of`): `1+pre-review` today, `1` once the documents
        # have been through legal review. That suffix is what makes the review flip
        # re-demand every acceptance without a special case anywhere.
        sa.Column("document_version", sa.Text(), nullable=False),
        # WHICH WORDING they ticked, pinned by version rather than copied — the rule
        # `whatsapp_alert_optin_ledger.notice_version` states: a version string is
        # evidence only while the text it names can still be produced.
        sa.Column("statement_version", sa.Text(), nullable=False),
        sa.Column("accepted_by_user_id", sa.UUID(), nullable=False),
        # When they ACCEPTED, which is not always when we wrote it down.
        sa.Column(
            "accepted_at",
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
        sa.CheckConstraint("btrim(document_slug) <> ''", name=op.f(f"ck_{TABLE}_slug_present")),
        sa.CheckConstraint(
            "btrim(document_version) <> ''", name=op.f(f"ck_{TABLE}_version_present")
        ),
        sa.CheckConstraint(
            "btrim(statement_version) <> ''", name=op.f(f"ck_{TABLE}_statement_present")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            name=op.f(f"fk_{TABLE}_accepted_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )

    # Exactly the read every gate runs: latest row for one (tenant, document).
    op.execute(
        f"CREATE INDEX {IX_CURRENT} ON {TABLE} "
        "(tenant_id, document_slug, accepted_at DESC, created_at DESC) "
        "INCLUDE (document_version)"
    )

    # Tenant isolation (DATA-MODEL §1) + FORCE so the owner role is subject to it. No
    # WITH CHECK clause: for a FOR ALL policy Postgres reuses the USING expression as the
    # write check, so a session cannot insert an acceptance for a tenant it cannot read.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )

    # Append-only (hard rule 4), reusing the function migration 05bba2f3c19c created.
    # Re-accepting a new version is a NEW row; the acceptance it supersedes survives,
    # because the question "which terms were they operating under in March?" is asked in
    # April.
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    # AND THE VERB A ROW TRIGGER CANNOT SEE. TRUNCATE removes rows without producing any,
    # so `FOR EACH ROW` never fires on it; migration a2e9f31c605d created
    # `calevate_forbid_truncate` and gave every ledger of its day the statement-level
    # twin, and a ledger added afterwards needs both or it is emptiable by one word.
    # `check_ledger_immutability` and `check_rls_coverage` both fail on a ledger with only
    # one of them, which is how this was caught rather than shipped.
    op.execute(
        f"CREATE TRIGGER {TABLE}_forbid_truncate BEFORE TRUNCATE ON {TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    # ALWAYS rather than the default ORIGIN, on BOTH triggers: a session in
    # `session_replication_role = replica` skips ORIGIN triggers entirely, and a ledger
    # protected only from an ordinary session is protected from the wrong attacker
    # (a2e9f31c605d §2 argues it).
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TABLE}_append_only")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TABLE}_forbid_truncate")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_forbid_truncate ON {TABLE}")
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_append_only ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.execute(f"DROP INDEX IF EXISTS {IX_CURRENT}")
    op.drop_table(TABLE)
