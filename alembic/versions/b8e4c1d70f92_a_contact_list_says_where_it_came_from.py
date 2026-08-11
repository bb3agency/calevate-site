"""a contact list says where it came from

Revision ID: b8e4c1d70f92
Revises: 7c04ab5f9e26
Create Date: 2026-08-11 09:40:00.000000

SEC-COMP §3 lists five conditions on the campaign launch gate. Four of them are
enforced in `launch_blockers`. The fifth — "Consent provenance recorded for the list
(source + date) — a purchased list with no consent artefacts is refused, in writing,
as policy" — was not merely unenforced, it was UNENFORCEABLE: there was no column
anywhere that could hold the answer, so the gate had nothing to read and the audit
found a rule that could not be broken because it could not be stated.

**Why not `consent_ledger`.** It is the obvious candidate and it is the wrong one. The
ledger records consent per (phone, call, purpose) with a transcript span as evidence —
consent captured DURING a conversation, which is to say after we have already dialled.
The question §3 asks is about the list, before the first ring: on what basis are these
five thousand strangers being called at all? A per-call ledger cannot answer it,
because every row in it postdates the act it would have had to authorise.

**Why the source is an enum and the date is a date.** Free text is a box someone types
"yes" into. An enum is CHECKABLE — the gate can refuse `purchased_list` by name, an
operator can count how many campaigns rest on `existing_customer`, and the DPDP
self-assessment (§7) can be produced from a GROUP BY rather than from reading prose.
`purchased_list` is deliberately IN the enum: §3 promises a refusal in writing, and a
refusal can only be written if the client can say the word. An enum stocked only with
acceptable answers does not stop purchased lists, it hides them behind whichever
member sounds nearest.

**Existing campaigns.** Nullable, no server default, no backfill — every campaign that
predates this migration says NULL, which is the truth: nobody asked, so nobody knows.
The two alternatives were both worse in ways that do not cancel out:

- a default naming a source (`existing_customer`, say) is the system asserting on the
  client's behalf a consent nobody gave. That is not a migration convenience, it is a
  fabricated compliance artefact, and it would be indistinguishable in the table from
  the answers real clients really give.
- backfilling from anything already in the schema — a tenant's lead sources, say —
  infers consent from adjacency. `leads.source = 'campaign'` says where a row entered
  our database, not what the person on the other end agreed to.

So the choice is deliberate: existing campaigns are BLOCKED, not silently consented.
The blast radius of that is narrower than it first sounds, and the narrowing is the
whole reason it is safe:

- `launch_blockers` runs at LAUNCH. A campaign already `running` keeps dialling — the
  per-contact dispatch gate is untouched by this migration — so nothing in flight
  stops. This is not a production outage; nobody's live campaign goes dark.
- only UNLAUNCHED drafts are affected, and they are affected by being asked a
  question they should have been asked at creation.
- `declare_consent_provenance` (apps/api/campaigns/service.py) is the answer path: a
  draft that predates the columns is fixed by answering, not by being recreated. It
  refuses on a non-draft campaign, so the declaration cannot be back-filled AFTER the
  dialling it was supposed to authorise.

**Locking, with other suites live on this database.** Both `ADD COLUMN`s are nullable
with no default, which since PG11 is a catalog-only change — no rewrite, no scan. The
CHECK constraints are added `NOT VALID` and validated in a second statement: `NOT
VALID` takes a brief ACCESS EXCLUSIVE to write the catalog row but scans nothing, and
`VALIDATE CONSTRAINT` does the scan under SHARE UPDATE EXCLUSIVE, which does not block
readers or writers. `lock_timeout` is set so that if we do queue behind a long
transaction we fail fast and get retried, rather than parking an ACCESS EXCLUSIVE
request in front of every other session's queries.

**Downgrade** drops the constraints and the columns. That loses recorded provenance,
which no downgrade can avoid — the columns are the only place it lives — and it is
correct in hard rule 8's sense: the schema returns to its previous shape and the
pre-migration code runs against it unchanged. It is worth saying plainly that reverting
this migration re-opens the gap it closes, so a revert is a compliance decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e4c1d70f92"
down_revision: str | None = "7c04ab5f9e26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ENUM = "ck_campaigns_consent_source_enum"
COMPLETE = "ck_campaigns_consent_provenance_complete"

# Mirrors `campaigns.models.CONSENT_SOURCES` (DATA-MODEL §10: CHECK constraints mirror
# the enums). Spelled out rather than imported: a migration is a snapshot of the schema
# on the day it ran, and importing today's model would silently rewrite history the
# next time somebody adds a member.
_SOURCE_ENUM_SQL = (
    "consent_source IS NULL OR consent_source IN ('existing_customer', 'inbound_enquiry', "
    "'web_form_optin', 'offline_form_optin', 'purchased_list')"
)
# Source and date travel together or not at all. A source with no date cannot be aged
# against a consent since withdrawn; a date with no source names nothing.
_COMPLETE_SQL = "(consent_source IS NULL) = (consent_collected_at IS NULL)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("campaigns", sa.Column("consent_source", sa.String(), nullable=True))
    op.add_column(
        "campaigns",
        sa.Column("consent_collected_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name, expression in ((SOURCE_ENUM, _SOURCE_ENUM_SQL), (COMPLETE, _COMPLETE_SQL)):
        op.execute(f"ALTER TABLE campaigns ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
        # Every existing row is (NULL, NULL) and satisfies both trivially; the scan is
        # for the catalog's benefit, so the constraint is not left marked NOT VALID and
        # therefore skipped by the planner and by future ADD CONSTRAINT checks.
        op.execute(f"ALTER TABLE campaigns VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name in (COMPLETE, SOURCE_ENUM):
        op.execute(f"ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS {name}")
    op.drop_column("campaigns", "consent_collected_at")
    op.drop_column("campaigns", "consent_source")
