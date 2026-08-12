"""the intake answers get a home (organizations.intake)

Revision ID: c1f3a7d92b46
Revises: f4a8e1c07b62
Create Date: 2026-08-11 06:30:00.000000

FLOWS §1 says the onboarding wizard keeps "draft state saved at every step (resume
anytime)". Step 3 — the intake — had nowhere to save one. Its answers survived only as
DERIVATIVES: the compiled `[T0 FACTS]` block on `prompt_versions`, a `kb_sources` text
body, and three typed columns on `agents` (`business_hours`, `escalation_config`,
`languages_extra`). Reopening the step could therefore repopulate the structured half
of the form and not the half an operator spent an afternoon typing, because
"Service: Root canal — ₹8000 (30 minutes)" is a sentence, not the three fields that
produced it. `admin/intake.py` recorded the gap in its own module docstring and left
the schema decision explicitly unmade. This is that decision.

**A column on `organizations`, not a `client_intake` table.** Both were live options;
the column wins on four counts, in descending order of how much they matter.

1. **Ownership.** DATA-MODEL §2 makes `organizations` the row that IS the client
   business — name, slug, vertical template, plan tier, billing email. The intake
   answers are that business describing itself: its hours, its branches, its price
   list, its staff. They are not a new entity with its own lifecycle, identity or
   history; they are one more set of attributes of the row that already exists. §3
   keeps AGENT configuration on `agents`, and the per-agent halves of the intake
   (hours, escalation config, extra languages) already live there and keep living
   there — this column is deliberately not a second copy of them, it is the answer
   sheet those columns were derived FROM.
2. **Cardinality.** A table would have to answer "one intake per what?". Per tenant it
   is `organizations` with extra ceremony and an artificial UNIQUE. Per agent it says
   two agents in one business can disagree about that business's opening hours, which
   is not a feature anyone asked for and is a bug the moment a client gets an outbound
   agent beside their receptionist. DATA-MODEL §2/§3 name no such table, and inventing
   an entity to store an attribute is how a schema grows a join nobody needs.
3. **Hard rule 1 costs nothing here and costs something there.** `organizations` is
   the tenant root and is already FORCE-RLS'd with `tenant_isolation USING (id =
   current_setting('app.tenant_id')::uuid)` — migration 05bba2f3c19c, the policy that
   matches on `id` rather than `tenant_id` because this table IS the tenant. A column
   inherits that policy exactly, for reads and writes, with nothing new to get wrong;
   `tests/intake_test.py` proves the inheritance rather than assuming it, with a
   cross-tenant zero-rows case. A new table would need its own policy, its own FORCE,
   its own entry in `db/registry.TENANT_TABLES`, and its own place in the retention
   sweep's mental model — four more surfaces on which hard rule 1 can be got wrong,
   bought for no capability.
4. **JSONB is the right shape for THIS content.** DATA-MODEL §10 already sanctions the
   pattern — "CHECK constraints mirror Pydantic enums; JSONB validated at API
   boundary" — and `apps/api/admin/intake.py`'s `IntakeFacts` is that boundary
   validator, the same arrangement `agents.business_hours` and `extraction_schemas.
   fields` use. The eight answer groups are nested, repeated and partial by design (a
   half-filled step is the normal state of a wizard, not an error), which is precisely
   the case where columns-per-field would mean eight nullable arrays and a migration
   every time FLOWS §1 gains a question.

The honest cost of the choice, recorded so the next person can weigh a reversal: the
answers are not queryable as columns. Nothing today queries them — the wizard reads one
sheet by tenant id — and if a cross-client report ever wants "every client whose price
list mentions X", `jsonb_path_ops` on this column answers it without a table.

**PII (hard rule 6).** The sheet contains staff names and escalation phone numbers. It
introduces no new CLASS of data — `agents.escalation_config` already stores exactly
those contacts, and `users.phone` stores E.164 — and no new place for it to leak:
tenant-isolated at rest by the policy above, never logged (`intake.py` logs ids and
counts only, asserted by a test), and the read path keeps phone numbers out of the
response model's declared prose field. What it does add is a DPDP obligation to carry
this column in an org-level erasure, which is why it lives on `organizations` where an
offboarding already looks, rather than in a table an offboarding would have to learn.

**Locking.** One nullable `ADD COLUMN` with no default: catalog-only since PG11, no
rewrite and no scan, on a table every request touches. The CHECK is added `NOT VALID`
(brief ACCESS EXCLUSIVE for the catalog row, no scan) and validated in a second
statement under SHARE UPDATE EXCLUSIVE, which blocks neither readers nor writers. Every
existing row is NULL and satisfies it trivially; the scan exists so the constraint is
not left marked NOT VALID and therefore skipped by the planner and by later ADDs.
`lock_timeout` is set so queueing behind a long transaction fails fast and gets
retried, instead of parking an ACCESS EXCLUSIVE request in front of every other
session — which on THIS table is every session there is.

**The CHECK earns its place.** It pins the envelope, not the answers: an object,
carrying a `version` and an `answers` object. The answers themselves are Pydantic's
job (§10), but the envelope is what a reader dereferences without looking, and a
migration is the only place to say that `intake` is never a bare array or a string.

**Downgrade** drops the constraint and the column, which loses saved drafts — no
downgrade can avoid that, since the column is the only place they live — and returns
the schema to its previous shape, which is what hard rule 8 asks: pre-migration code
runs against the result unchanged. Submitted intakes are NOT lost by a downgrade: the
compiled block, the KB source and the agent columns are all still written, so a revert
costs the resume affordance, not the client's business facts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1f3a7d92b46"
down_revision: str | None = "f4a8e1c07b62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENVELOPE = "ck_organizations_intake_envelope"
# Mirrors the envelope `apps/api/admin/intake.py` writes. Spelled out rather than
# imported: a migration is a snapshot of the schema on the day it ran.
_ENVELOPE_SQL = (
    "intake IS NULL OR ("
    "jsonb_typeof(intake) = 'object' AND intake ? 'version' "
    "AND jsonb_typeof(intake -> 'answers') = 'object')"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column("intake", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {ENVELOPE} CHECK ({_ENVELOPE_SQL}) NOT VALID"
    )
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {ENVELOPE}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {ENVELOPE}")
    op.drop_column("organizations", "intake")
