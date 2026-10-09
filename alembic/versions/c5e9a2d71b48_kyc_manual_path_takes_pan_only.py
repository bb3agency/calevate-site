"""The manual KYC path takes the owner's PAN card only, and the PAN check is recorded (D-696)

Revision ID: c5e9a2d71b48
Revises: f4c8b2e6a1d9
Create Date: 2026-10-09 18:00:00.000000

Aadhaar (Authentication and Offline Verification) Regulations 2021, reg. 16C(1): an offline
verification seeking entity shall not accept an Aadhaar "in physical or electronic form
(without authentication), as a proof of identity" without first verifying UIDAI's digital
signature on the Secure QR code or the offline e-KYC XML
(docs/evidence/aadhaar-offline-and-pan-verification-2026-10-09.md). The manual path did
exactly that with a reviewer looking at an uploaded Aadhaar image, and we verify no UIDAI
signature, so from D-696 the manual path takes the PAN card only. DigiLocker keeps Aadhaar:
the licensed provider carries the UIDAI obligations there.

1. `kyc_records.owner_pan_checked` (+ `_at`, `_by_admin_id`): the reviewer matched the PAN,
   full name and date of birth at the Income Tax "Verify Your PAN" service before approving.
   A CHECK makes the three travel together. The date of birth is not stored anywhere.
2. Every manual Aadhaar submission still WAITING for a reviewer is returned to the client
   as `rejected`, with a reason asking for the PAN card. A decided record is left exactly
   as it is: an approval made before D-696 stays valid.
3. Every held Aadhaar file has its deletion requested; `workers/kyc_owner_id_purge` deletes
   the object on its next tick, the same path a reviewer's decision takes.
4. Two CHECKs keep it so: no manual Aadhaar submission awaits review, and no Aadhaar file is
   held without its deletion requested. `owner_id_type` keeps `aadhaar` (DigiLocker) and
   `kyc_documents.kind` keeps `aadhaar` (history rows), so neither enum narrows.

Steps 2 and 3 run with RLS un-FORCEd for the owner, the bracket `a4f7d20c81be` set. They
write no audit row: `audit_log` is append-only and written by the application, and the
decision log (D-696) is the record of this one-time return.

DOWNGRADE drops the two CHECKs and the three columns. It does not undo steps 2 and 3: a
returned submission stays returned (the client resubmits) and a requested deletion stays
requested, because the file may already be gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e9a2d71b48"
down_revision: str | None = "f4c8b2e6a1d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: What the client is shown on a returned submission. Plain words, their point of view.
RETURNED_REASON = (
    "We can no longer accept a copy of an Aadhaar card when we check your documents "
    "ourselves. Please upload the owner's PAN card and send it again."
)

_CHECKS = {
    "kyc_records": {
        "ck_kyc_records_owner_pan_check_names_who_and_when": (
            "owner_pan_checked = (owner_pan_checked_at IS NOT NULL) "
            "AND owner_pan_checked = (owner_pan_checked_by_admin_id IS NOT NULL)"
        ),
        "ck_kyc_records_no_manual_aadhaar_awaits_review": (
            "NOT (kyc_path = 'manual' AND owner_id_type = 'aadhaar' "
            "AND status IN ('submitted', 'in_review'))"
        ),
    },
    "kyc_documents": {
        "ck_kyc_documents_aadhaar_copy_never_held": (
            "kind <> 'aadhaar' OR delete_requested_at IS NOT NULL"
        ),
    },
}


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "kyc_records",
        sa.Column("owner_pan_checked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "kyc_records",
        sa.Column("owner_pan_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "kyc_records", sa.Column("owner_pan_checked_by_admin_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_kyc_records_owner_pan_checked_by_admin_id_admin_users"),
        "kyc_records",
        "admin_users",
        ["owner_pan_checked_by_admin_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    for table in ("kyc_records", "kyc_documents"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            sa.text(
                "UPDATE kyc_records SET status = 'rejected', rejection_reason = :reason, "
                "  updated_at = now() "
                "WHERE kyc_path = 'manual' AND owner_id_type = 'aadhaar' "
                "  AND status IN ('submitted', 'in_review')"
            ).bindparams(reason=RETURNED_REASON)
        )
        op.execute(
            "UPDATE kyc_documents SET delete_requested_at = now(), updated_at = now() "
            "WHERE kind = 'aadhaar' AND delete_requested_at IS NULL"
        )
    finally:
        for table in ("kyc_records", "kyc_documents"):
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for table, checks in _CHECKS.items():
        for name, predicate in checks.items():
            op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({predicate}) NOT VALID")
            op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table, checks in _CHECKS.items():
        for name in checks:
            op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    op.drop_constraint(
        op.f("fk_kyc_records_owner_pan_checked_by_admin_id_admin_users"),
        "kyc_records",
        type_="foreignkey",
    )
    op.drop_column("kyc_records", "owner_pan_checked_by_admin_id")
    op.drop_column("kyc_records", "owner_pan_checked_at")
    op.drop_column("kyc_records", "owner_pan_checked")
