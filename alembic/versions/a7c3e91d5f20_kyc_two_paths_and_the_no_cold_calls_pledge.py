"""KYC on two paths, the business document, and the no-cold-calls pledge (D-692)

Revision ID: a7c3e91d5f20
Revises: f3b8d1e5a7c2
Create Date: 2026-10-08 23:30:00.000000

D-692 replaces the DLT entity chain and the bound DLT-registered number as the outbound
precondition with two facts about the client: a verified KYC record and an accepted,
current "no cold calls" pledge. This migration gives both somewhere to live.

`kyc_records` gains:
  * the path the client chose (`manual` document review or `digilocker`);
  * the business facts a numbering application needs on either path — legal name, GST
    registered or not, and the GSTIN when it is;
  * the admin override "require DigiLocker" (who, when, why) and the instant a DigiLocker
    run last completed, so the gate can tell a requirement satisfied BEFORE it was imposed
    from one satisfied after;
  * `name_match`: whether the name DigiLocker attested matches the owner the client named;
  * which owner ID was used (`aadhaar` or `pan`, on either path) and that ID MASKED.

The masked identifier is a founder decision of 8 Oct 2026 (D-692) and narrows what
b6e41d9c3a72 refused: a full Aadhaar number is still never stored, and a CHECK pins the
masked shapes exactly (`XXXX-XXXX-1234`, `XXXXX1234X`), so neither a full Aadhaar nor a
full PAN fits. A full PAN is not Aadhaar-restricted, but nothing downstream needs it, so it
is not kept.

`kyc_documents` holds the uploaded files' METADATA; the bytes are in object storage under
`kyc-documents/{tenant}/`. One current document per slot (`business`, `owner_id`); a
replacement supersedes the old row rather than editing it, so "what did we review" stays
answerable. The business kinds are the numbering application's own vocabulary
(`gst`/`incorporation`/`udyam`, thinnest-findings/mirror/snapshots/2026-10-08/pages/
api-reference/phone-numbers/send-business-details.md:513-522), and its limits — PDF/JPEG/PNG,
5 MB, a 99-character filename (:526-528) — are CHECKs here as well as at the route.
The owner ID on the manual path is an Aadhaar (the masked copy UIDAI issues) or a PAN card.

`outbound_pledge_acceptances` is a consent record: who accepted which version of the pledge,
when, from which address, over which exact text (its SHA-256). Append-only, because a
re-acceptance is a new row and an edited acceptance is not evidence of anything.

All three tables carry `tenant_id` with the standard FORCEd `tenant_isolation` policy
(hard rule 1); the cross-tenant proofs are in `tests/kyc_two_paths_test.py`.

LOCKING: the `kyc_records` columns are catalogue-only (nullable, or a constant default on
PG11+); its CHECKs are added NOT VALID and validated separately.

DOWNGRADE drops the two tables and the new columns. It loses the pledge acceptances, the
document metadata (the objects stay in the bucket under their prefix) and any DigiLocker
requirement an admin set — a compliance decision, since dropping the requirement re-opens
outbound for that client.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e91d5f20"
down_revision: str | None = "f3b8d1e5a7c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY = (
    "CREATE POLICY tenant_isolation ON {table} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

_UNTENANTED = "NULLIF(current_setting('app.tenant_id', true), '') IS NULL"

_GSTIN = "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"

_KYC_CHECKS = {
    "ck_kyc_records_kyc_path_enum": "kyc_path IS NULL OR kyc_path IN ('manual', 'digilocker')",
    "ck_kyc_records_gstin_format": f"gstin IS NULL OR gstin ~ '{_GSTIN}'",
    "ck_kyc_records_gstin_needs_gst_registered": "gstin IS NULL OR gst_registered IS TRUE",
    "ck_kyc_records_legal_name_bounded": (
        "legal_business_name IS NULL OR (char_length(btrim(legal_business_name)) BETWEEN 2 "
        "AND 200 AND legal_business_name !~ '^[0-9]{12}$')"
    ),
    "ck_kyc_records_owner_id_type_enum": (
        "owner_id_type IS NULL OR owner_id_type IN ('aadhaar', 'pan')"
    ),
    # MASKED ONLY. An Aadhaar shows its last four digits, a PAN its four digits; the shapes
    # are exact so a full number cannot be stored here even by mistake.
    "ck_kyc_records_owner_id_masked_shape": (
        "owner_id_masked IS NULL OR (owner_id_type = 'aadhaar' "
        "AND owner_id_masked ~ '^XXXX-XXXX-[0-9]{4}$') OR (owner_id_type = 'pan' "
        "AND owner_id_masked ~ '^XXXXX[0-9]{4}X$')"
    ),
    "ck_kyc_records_digilocker_requirement_names_why": (
        "NOT digilocker_required OR (digilocker_required_reason IS NOT NULL "
        "AND btrim(digilocker_required_reason) <> '' AND digilocker_required_at IS NOT NULL "
        "AND digilocker_required_by_admin_id IS NOT NULL)"
    ),
}


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.add_column("kyc_records", sa.Column("kyc_path", sa.Text(), nullable=True))
    op.add_column("kyc_records", sa.Column("legal_business_name", sa.Text(), nullable=True))
    op.add_column("kyc_records", sa.Column("gst_registered", sa.Boolean(), nullable=True))
    op.add_column("kyc_records", sa.Column("gstin", sa.Text(), nullable=True))
    op.add_column(
        "kyc_records",
        sa.Column(
            "digilocker_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "kyc_records", sa.Column("digilocker_required_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "kyc_records",
        sa.Column("digilocker_required_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "kyc_records",
        sa.Column("digilocker_required_by_admin_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "kyc_records",
        sa.Column("digilocker_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("kyc_records", sa.Column("name_match", sa.Boolean(), nullable=True))
    op.add_column("kyc_records", sa.Column("owner_id_type", sa.Text(), nullable=True))
    op.add_column("kyc_records", sa.Column("owner_id_masked", sa.Text(), nullable=True))
    # Which DigiLocker record a run asked for. NULL on runs opened before D-692, which
    # were Aadhaar runs.
    op.add_column("kyc_verification_requests", sa.Column("id_document", sa.Text(), nullable=True))
    op.execute(
        "ALTER TABLE kyc_verification_requests ADD CONSTRAINT "
        "ck_kyc_verification_requests_id_document_enum CHECK (id_document IS NULL OR "
        "id_document IN ('aadhaar', 'pan')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE kyc_verification_requests VALIDATE CONSTRAINT "
        "ck_kyc_verification_requests_id_document_enum"
    )
    op.create_foreign_key(
        op.f("fk_kyc_records_digilocker_required_by_admin_id_admin_users"),
        "kyc_records",
        "admin_users",
        ["digilocker_required_by_admin_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    for name, predicate in _KYC_CHECKS.items():
        op.execute(f"ALTER TABLE kyc_records ADD CONSTRAINT {name} CHECK ({predicate}) NOT VALID")
    for name in _KYC_CHECKS:
        op.execute(f"ALTER TABLE kyc_records VALIDATE CONSTRAINT {name}")

    op.create_table(
        "kyc_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=False),
        # The object's bytes are AES-256-GCM ciphertext under a per-document DEK wrapped by
        # the platform KEK (`core/envelope.seal_bytes`), with the tenant and document id as
        # AAD; these four columns are the rest of that envelope.
        sa.Column("payload_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("dek_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("dek_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("kek_version", sa.Integer(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "(slot = 'business' AND kind IN ('gst', 'incorporation', 'udyam')) OR "
            "(slot = 'owner_id' AND kind IN ('aadhaar', 'pan_card'))",
            name=op.f("ck_kyc_documents_slot_and_kind"),
        ),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png')",
            name=op.f("ck_kyc_documents_content_type_enum"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 5242880", name=op.f("ck_kyc_documents_size_bounded")
        ),
        sa.CheckConstraint(
            "char_length(filename) BETWEEN 1 AND 99", name=op.f("ck_kyc_documents_filename_bounded")
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_kyc_documents_sha256_hex")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_kyc_documents_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name=op.f("fk_kyc_documents_uploaded_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kyc_documents")),
    )
    op.create_index(op.f("ix_kyc_documents_tenant_id"), "kyc_documents", ["tenant_id"])
    op.execute(
        "CREATE UNIQUE INDEX ux_kyc_documents_current_per_slot ON kyc_documents "
        "(tenant_id, slot) WHERE superseded_at IS NULL"
    )
    op.execute("ALTER TABLE kyc_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kyc_documents FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY.format(table="kyc_documents"))
    # One narrow untenanted READ arm, `c3f7b21a94e8`'s shape (`<guc> IS NULL`, never
    # `true`, so a session scoped to tenant A still sees nothing of B), for the nightly
    # purge to find owner-ID files still held across tenants. Writes stay strict.
    op.execute(
        f"CREATE POLICY kyc_documents_owner_id_purge_read ON kyc_documents FOR SELECT "
        f"USING ({_UNTENANTED} AND slot = 'owner_id' AND purged_at IS NULL)"
    )

    op.create_table(
        "outbound_pledge_acceptances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("pledge_version", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("accepted_by_user_id", sa.UUID(), nullable=False),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "pledge_version > 0", name=op.f("ck_outbound_pledge_acceptances_version_positive")
        ),
        sa.CheckConstraint(
            "text_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_outbound_pledge_acceptances_text_sha256_hex"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_outbound_pledge_acceptances_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            name=op.f("fk_outbound_pledge_acceptances_accepted_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbound_pledge_acceptances")),
    )
    op.execute(
        "CREATE INDEX ix_outbound_pledge_acceptances_latest ON outbound_pledge_acceptances "
        "(tenant_id, accepted_at DESC, created_at DESC) INCLUDE (pledge_version)"
    )
    op.execute("ALTER TABLE outbound_pledge_acceptances ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE outbound_pledge_acceptances FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY.format(table="outbound_pledge_acceptances"))
    op.execute(
        "CREATE TRIGGER outbound_pledge_acceptances_append_only BEFORE UPDATE OR DELETE "
        "ON outbound_pledge_acceptances FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER outbound_pledge_acceptances_forbid_truncate BEFORE TRUNCATE ON "
        "outbound_pledge_acceptances FOR EACH STATEMENT "
        "EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    # ALWAYS, as every other ledger: a restore runs as `session_replication_role = replica`.
    op.execute(
        "ALTER TABLE outbound_pledge_acceptances ENABLE ALWAYS TRIGGER "
        "outbound_pledge_acceptances_append_only"
    )
    op.execute(
        "ALTER TABLE outbound_pledge_acceptances ENABLE ALWAYS TRIGGER "
        "outbound_pledge_acceptances_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table("outbound_pledge_acceptances")
    op.drop_table("kyc_documents")
    for name in _KYC_CHECKS:
        op.execute(f"ALTER TABLE kyc_records DROP CONSTRAINT {name}")
    op.drop_constraint(
        op.f("fk_kyc_records_digilocker_required_by_admin_id_admin_users"),
        "kyc_records",
        type_="foreignkey",
    )
    op.execute(
        "ALTER TABLE kyc_verification_requests DROP CONSTRAINT "
        "ck_kyc_verification_requests_id_document_enum"
    )
    op.drop_column("kyc_verification_requests", "id_document")
    for column in (
        "owner_id_masked",
        "owner_id_type",
        "name_match",
        "digilocker_verified_at",
        "digilocker_required_by_admin_id",
        "digilocker_required_at",
        "digilocker_required_reason",
        "digilocker_required",
        "gstin",
        "gst_registered",
        "legal_business_name",
        "kyc_path",
    ):
        op.drop_column("kyc_records", column)
