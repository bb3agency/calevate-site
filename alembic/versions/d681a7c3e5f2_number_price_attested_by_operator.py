"""number price attestations are attested by an OPERATOR (admin_users), not a client user

Revision ID: d681a7c3e5f2
Revises: b7e2d94f1a30
Create Date: 2026-10-07 12:00:00.000000

`number_price_attestations.attested_by` pointed at `users` — the CLIENT realm's people —
while its only writer, `POST /v1/admin/number-pricing`, is admin-realm and passes the
operator's `admin_users` id. Every attestation from the ops console therefore failed on the
foreign key, so no client number price could be recorded at all (gate 26, D-681). The
constraint now names `admin_users`, as `platform_engine_minute_prices.attested_by` and
`platform_model_prices.attested_by` do.

`NOT VALID`: Postgres then enforces the new constraint for every new row without scanning
the existing ones, which can only be rows written directly against `users` ids (test
fixtures); the table is append-only (hard rule 4), so those rows cannot be rewritten to
satisfy it. The downgrade restores the old target the same way.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d681a7c3e5f2"
down_revision: str | None = "b7e2d94f1a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "number_price_attestations"
OLD = "fk_number_price_attestations_attested_by_users"
NEW = "fk_number_price_attestations_attested_by_admin_users"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {OLD}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {NEW} FOREIGN KEY (attested_by) "
        "REFERENCES admin_users (id) ON DELETE RESTRICT NOT VALID"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {NEW}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {OLD} FOREIGN KEY (attested_by) "
        "REFERENCES users (id) ON DELETE RESTRICT NOT VALID"
    )
