"""an account whose outbound is service/transactional refuses a dial with no consent

Revision ID: b4e17c920fd3
Revises: a3f70c19d84b
Create Date: 2026-09-18 00:00:00.000000

One boolean on `organizations`, defaulting FALSE, and the whole of it is D-624.

WHAT IT REPLACES, WHICH IS THE ONLY REASON IT EXISTS
----------------------------------------------------------------------------------
`compliance/service.check_dispatch` is deliberately permissive about consent:

    ABSENCE IS NOT A REFUSAL, and that asymmetry is the whole design. Most dialable
    leads have no `consent_ledger` row: a number typed in by staff, a CSV import, a
    caller who rang US. Treating silence as `declined` would refuse every one of them
    and be met as an outage rather than a rule.

That reasoning is intact and this migration does not touch it. It was correct while a
client's DLT Principal-Entity registration stood behind the dial — the REGISTRATION, not
the ledger, was what separated a relationship call from a cold list.

An account sold on a SERVICE/TRANSACTIONAL footing has no such registration behind it.
Its position is that it calls the client's own existing, consenting customers about those
customers' own bookings and orders, which is the classification TRAI's
promotional-versus-transactional distinction turns on. Under the permissive default that
position is an INTENTION rather than a property: nothing stops a client with a quiet month
uploading a prospect list, and the first anyone learns of it is a complaint — under
TCCCPR Reg 25(6), which disconnects "all telecom resources of the sender" and blacklists
that sender for up to two years. DoT/TRAI's own 2025 figures put that at 1,84,482
disconnections in the year, so it is not a theoretical tail.

WHY A COLUMN AND NOT A CHANGED DEFAULT
----------------------------------------------------------------------------------
Flipping the global behaviour would change the answer for every existing account in one
deploy, which is precisely the "outage rather than a rule" the permissive comment warns
about. And the accounts that need this are the ones SOLD on that footing — a commercial
fact about an account, not a property of the software.

WHY NOT A FEATURE FLAG
----------------------------------------------------------------------------------
`flags/models.TenantFeatureFlag` exists and would have been less typing. It is the wrong
home: a flag is for rolling a capability out and taking it back, and this is a standing
compliance posture that a client was sold and that an auditor may ask about. It belongs on
the account row beside `staff_may_curate_knowledge`, which is the same shape — a permission
property of the organization, greppable by column name, visible in one SELECT.

REVERSIBILITY
----------------------------------------------------------------------------------
Dropping the column restores the permissive behaviour for every account, which is a
LOOSENING and must never happen by accident. It is written here because hard rule 8
requires a reversible migration, not because it is a safe thing to run: any account that
had it TRUE is one whose refusals silently become permissions. The two-step deprecation of
hard rule 8 applies if it is ever really removed — stop reading it, ship, then drop.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b4e17c920fd3"
down_revision = "a3f70c19d84b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "outbound_requires_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "outbound_requires_consent")
