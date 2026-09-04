"""closing a client is a deadline, not a delete — and an invite link can be re-cut

Revision ID: e6c1a49d2f70
Revises: d1e58c7a94f2
Create Date: 2026-09-04 00:00:00.000000

D-536. The founder asked for a delete button on a client business in the admin console.
The decision taken is *close now, erase after a grace period, undo during it* — so what
the database needs is not a delete but a DEADLINE, and one that a human can call off.

═══ FOUR COLUMNS ON `organizations`, AND WHY NOT A TABLE ═══

`organizations` already carries the two facts a closure sits between — `status` (the
commercial relationship) and `deleted_at` (the data has been erased, written once by
`compliance/tenant_erasure.py`'s worker and never cleared). The scheduled erasure is the
BRIDGE between them: it exists only after the first and only until the second. Putting it
anywhere else would mean a reader holding "is this account closed, and when does its data
go?" had to join two tables to answer half a question each.

The decisive argument is the sweep. A cron has to find every account whose deadline has
passed, ACROSS tenants, and `admin_session()` widens `USING` on exactly one table —
`organizations` (migration b57e2f9c4a13). A new tenant-RLS'd `tenant_closures` table
would have been invisible to it, and the alternatives are all worse than four columns: a
second bridge table outside RLS (a new un-isolated surface holding client state), one
tenant session per organization on the platform (`retention._due_tenants` exists because
that cost is real), or the admin DB role in a worker (hard rule 1, never).

* **`closed_at`** — when access stopped. Not derivable from `status='churned'`, because
  `status` records no instant and an operator needs to say how long the grace has left.
* **`erase_after`** — when the tenant erasure becomes DUE. The sweep's only predicate.
  Nullable and independent of `closed_at` so a closure with no scheduled erasure is
  expressible: that is what an UNDO leaves behind, and it is also what a closure looks
  like the moment the erasure has been filed.
* **`closure_reason`** — why, in the operator's own words, in the row the console reads.
  `audit_log` holds it too and is the record of authority; this is the copy the screen
  renders without walking a hash chain, and the client's own closure notice quotes it.
* **`closed_by`** — which operator. `admin_users`, `ON DELETE SET NULL`: an operator row
  removed later must not take a client's closure record with it, and the audit chain is
  where the unforgeable attribution lives regardless.

═══ THE THREE CHECKS, AND THE ONE THEY DELIBERATELY DO NOT ADD ═══

1. `ck_organizations_erase_after_implies_closed` — `erase_after IS NOT NULL` requires
   `closed_at IS NOT NULL`. A deadline to erase an account nobody closed is the state
   that would let a live client's data be destroyed on a timer.
2. `ck_organizations_closed_implies_churned` — `closed_at IS NOT NULL` requires
   `status = 'churned'`. This is the same class of invariant as
   `ck_organizations_deleted_implies_churned` (migration f3a71c9e26b4) and it is here for
   the same reason: nine readers filter on `status`, `deleted_at` or both, and they only
   agree if the three facts are nested. `deleted_at` refines `closed_at` refines
   `churned`.
3. `ck_organizations_deleted_implies_no_deadline` — an erased account has no pending
   deadline. Once `deleted_at` is set the erasure HAPPENED; leaving `erase_after` in the
   future would make the sweep file a second erasure against an account whose subject is
   already gone, which `assert_erasable` refuses anyway — as a 409 raised from a cron,
   nightly, for ever.

**NOT added: `churned` implies `closed_at`.** `churned` predates this change and existing
rows carry it with no closure record, so such a CHECK would be a backfill of an instant
nobody observed — inventing a closure date is worse than not having one. It also has to
stay legal: closing an account WITHOUT scheduling an erasure is the right motion for a
client who is leaving but has asked us to keep their records, and `status` alone is how
that is said.

═══ `undo` IS WHY `churned` IS NO LONGER TERMINAL, AND THIS MIGRATION DOES NOT ENFORCE
    THAT IT IS ═══

`admin/routes.py::_LIFECYCLE_FROM` had no exit from `churned` and its docstring said
re-opening is a new tenant. D-536 reverses that for the GRACE WINDOW only, and the
reversal is safe precisely because of check 3 above: irreversibility now attaches to
`deleted_at` — the erasure that actually destroyed something — rather than to a status
flip that destroyed nothing. There is no schema change for it; the transition table is
code, and stating the rule twice is how the two copies drift.

═══ TWO COLUMNS ON `invitations`: RE-SENDING WITHOUT MINTING A SECOND KEY ═══

A client who mistyped their address at signup receives nothing, and today the only way to
help them is revoke-then-create — two rows, two audit trails, and a window in which the
account has zero live invitations if the second call fails. The resend path rotates the
token IN PLACE instead, so a second live key for one account cannot exist by
construction rather than by a refusal (`create_invitation`'s `invitation_already_pending`
check stays exactly as it is; it now guards a door nobody needs to walk through).

* **`last_sent_at`** — NOT NULL, defaulted to `now()`; every existing row was sent when
  it was created, so the default is a true statement about them rather than a backfill of
  an unknown. It is the rate limiter's clock AND the "last sent 4 minutes ago" line on
  the screen, and those must be one fact: a screen that reads a different value from the
  limiter tells an operator to wait when they need not, or the reverse.
* **`send_count`** — NOT NULL DEFAULT 1, same reasoning. On screen it is the number that
  makes "we have sent this five times and they still have not signed up" visible, which
  is the moment to stop clicking and telephone the client.

REVERSIBLE (hard rule 8). The downgrade drops the three CHECKs and the six columns and
touches no data outside them. Nothing is being retired, so the two-step deprecation rule
does not bite. The upgrade adds only nullable columns and columns with server defaults,
so it needs no UPDATE and therefore no `NO FORCE ROW LEVEL SECURITY` dance — the trap
migrations a4f7d20c81be and b7e35c2f81da both document.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e6c1a49d2f70"
down_revision = "d1e58c7a94f2"
branch_labels = None
depends_on = None

ERASE_AFTER_IMPLIES_CLOSED = "ck_organizations_erase_after_implies_closed"
CLOSED_IMPLIES_CHURNED = "ck_organizations_closed_implies_churned"
DELETED_IMPLIES_NO_DEADLINE = "ck_organizations_deleted_implies_no_deadline"


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("erase_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("organizations", sa.Column("closure_reason", sa.Text(), nullable=True))
    op.add_column(
        "organizations",
        sa.Column(
            "closed_by",
            sa.UUID(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_check_constraint(
        ERASE_AFTER_IMPLIES_CLOSED,
        "organizations",
        "erase_after IS NULL OR closed_at IS NOT NULL",
    )
    op.create_check_constraint(
        CLOSED_IMPLIES_CHURNED,
        "organizations",
        "closed_at IS NULL OR status = 'churned'",
    )
    op.create_check_constraint(
        DELETED_IMPLIES_NO_DEADLINE,
        "organizations",
        "deleted_at IS NULL OR erase_after IS NULL",
    )

    # The sweep's index. Partial on the predicate the cron actually asks — "a deadline
    # that has not yet been discharged" — because the overwhelming majority of rows are
    # live clients this index must not carry, and because a scan of `organizations` every
    # ten minutes is the cost `retention._due_tenants` was rewritten to avoid.
    op.create_index(
        "ix_organizations_erase_due",
        "organizations",
        ["erase_after"],
        unique=False,
        postgresql_where=sa.text("erase_after IS NOT NULL AND deleted_at IS NULL"),
    )

    op.add_column(
        "invitations",
        sa.Column(
            "last_sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "invitations",
        sa.Column("send_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("invitations", "send_count")
    op.drop_column("invitations", "last_sent_at")
    op.drop_index("ix_organizations_erase_due", table_name="organizations")
    op.drop_constraint(DELETED_IMPLIES_NO_DEADLINE, "organizations", type_="check")
    op.drop_constraint(CLOSED_IMPLIES_CHURNED, "organizations", type_="check")
    op.drop_constraint(ERASE_AFTER_IMPLIES_CLOSED, "organizations", type_="check")
    op.drop_column("organizations", "closed_by")
    op.drop_column("organizations", "closure_reason")
    op.drop_column("organizations", "erase_after")
    op.drop_column("organizations", "closed_at")
