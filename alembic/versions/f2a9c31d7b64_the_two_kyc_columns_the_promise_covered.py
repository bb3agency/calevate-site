"""the two kyc columns the published promise covered and the schema did not

Revision ID: f2a9c31d7b64
Revises: c3f7b21a94e8
Create Date: 2026-09-21 09:30:00.000000

`/legal/privacy` §4 (revision 9) lists what we hold for identity verification — entity
type, document kind, the document's reference number, **the signatory's name**, **a
reference to where the verification pack is filed**, and, on the self-service route, the
provider's reference and the attested name — and then says: "The schema deliberately
refuses a twelve-digit bare number in every one of these fields, so an Aadhaar number
cannot be stored even by mistake."

Four of those fields carried the refusal (`document_ref`, `verification_reference`,
`verified_name`, and `provider_ref` on the run). `signatory_name` and `evidence_ref` did
not, and they are the two an OPERATOR types by hand — the paste the guard exists for.
`entity_type` and `document_kind` need no check: both are enum-constrained to values that
cannot be twelve digits.

So the published sentence was broader than the schema. Fixed in the direction the brief
requires: the code moves, the notice does not.

NOT VALID then VALIDATE, as `b6e41d9c3a72` did and for its reason — VALIDATE takes the
weaker SHARE UPDATE EXCLUSIVE, and "small today" is not a locking argument. A deployment
holding a row that violates either check fails the VALIDATE loudly, which is the correct
outcome: it would mean an identity number is already stored and somebody has to remove it
before the promise is true again.
"""

from alembic import op

revision: str = "f2a9c31d7b64"
down_revision: str | None = "c3f7b21a94e8"
branch_labels: None = None
depends_on: None = None

_AADHAAR = "^[0-9]{12}$"
_CONSTRAINTS = (
    ("ck_kyc_records_signatory_name_is_not_an_aadhaar", "signatory_name"),
    ("ck_kyc_records_evidence_ref_is_not_an_aadhaar", "evidence_ref"),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name, column in _CONSTRAINTS:
        op.execute(
            f"ALTER TABLE kyc_records ADD CONSTRAINT {name} "
            f"CHECK ({column} IS NULL OR {column} !~ '{_AADHAAR}') NOT VALID"
        )
    for name, _ in _CONSTRAINTS:
        op.execute(f"ALTER TABLE kyc_records VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name, _ in _CONSTRAINTS:
        op.execute(f"ALTER TABLE kyc_records DROP CONSTRAINT IF EXISTS {name}")
