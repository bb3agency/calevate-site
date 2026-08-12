"""two speeds and a ceiling on an agent

Revision ID: a4e7b2c95d18
Revises: f9c2b41a8e57
Create Date: 2026-08-12 09:20:00.000000

Two columns on `agents`, one per SURFACES §2b gap. They ship together because the
second one is only safe once the first exists — see WHY THEY TRAVEL TOGETHER below.

--------------------------------------------------------------------------------
1. `live_prompt_id` — the pointer two-speed publishing was missing
--------------------------------------------------------------------------------

SURFACES §2b:101: "script/flow/actions/webhook edits require an explicit 'Apply to
live calls'; voice, extraction fields and training apply immediately."

Half of that was already true and the other half was INVERTED, which is worth stating
precisely because it is the finding, not the feature:

- **script** — `agents/prompts.py::write_prompt_version` re-published a LIVE agent in
  the same transaction. The slow lane published fastest of all.
- **voice** — `agents/voice_routes.py::set_agent_voice` deliberately does NOT touch
  the engine and returns `republish_required: true`. The fast lane published slowest.

So "explicit publish exists" (FLOWS §7) was true of prompt VERSIONING and not of
prompt PUBLISHING: every version was born live. There was nowhere in the schema to
record the distinction, because `agents.system_prompt_id` was doing two jobs — "the
script the client is editing" and "the script the engine is running" — and one column
cannot hold two answers that are allowed to differ.

`live_prompt_id` is the second answer. After this migration:

    system_prompt_id  = the DRAFT pointer   (what the client is editing)
    live_prompt_id    = the APPLIED pointer (what `publish_agent` sends the engine)

and "is anything pending?" is `system_prompt_id IS DISTINCT FROM live_prompt_id`,
derived rather than stored, so it cannot drift the way a `has_pending` flag would.

**Why this is the enabling change for the FAST lane too, not just the slow one.**
`publish_agent` sends ONE `AgentConfig` carrying script AND voice AND cap together.
Before this column there was no way to push a voice without also pushing whatever
script happened to be in `system_prompt_id` — which is exactly why voice_routes.py
refused to publish at all. A fast lane was not merely unbuilt, it was unbuildable.
Reading the applied pointer at publish time is what makes "apply the voice now, leave
the draft script alone" expressible.

**Backfill: `live_prompt_id := system_prompt_id`, unconditionally.** That is not a
convenience default, it is the historical truth: until this revision every prompt
version reached the engine at the moment it was written, so for every existing row
the draft pointer IS the applied pointer. Any other backfill would invent a pending
change nobody made (NULL everywhere would tell every client their agent is running a
script it is not) .

**No CHECK constraint on this column**, and the absence is deliberate. The invariant
one would want — "live_prompt_id names a version of THIS agent" — is not expressible
in a row-local CHECK (it is a join), and the invariant one might reach for instead —
"live_prompt_id <= system_prompt_id" — is FALSE by design: `prompt_versions.version`
is per agent and a rollback mints a higher number than the one it restores. The FK to
`prompt_versions` with ON DELETE SET NULL is the constraint that is both true and
enforceable. `agents.system_prompt_id` carries exactly the same FK and the same
`SET NULL`, so the two pointers degrade identically.

--------------------------------------------------------------------------------
2. `max_call_duration_s` — the cost-runaway guard (§2b:107)
--------------------------------------------------------------------------------

"a per-agent max call length (their default 10 min, adjustable). We have no equivalent
today and should."

We had half an equivalent and could not reach it. `AgentConfig.max_call_duration_s`
(packages/shared) already exists, defaults to 600, and `engine/bolna.py` already maps
it to the vendor's `task_config.call_terminate`. Nothing filled it: `_to_config` never
mentioned the field, so every agent on the platform published the Pydantic default and
no client could change it. This column is the missing input — OUR normalized field,
per hard rule 2, with the vendor mapping left where it already lives.

**NULL means "the platform default" (600s), never "unlimited".** The constraint brief
is explicit that zero or negative is not unlimited; nor is the absence of a value. A
nullable column with a floor is the honest shape for "this client has not chosen":
the reader (`agents/service.py::effective_call_cap`) resolves NULL to 600 and the
agent is published with a ceiling either way. There is no value of this column, and no
absence of one, that produces an uncapped call.

**CHECK `max_call_duration_s BETWEEN 60 AND 3600` (or NULL):**

- the floor is 60s, not 1s. A cap below one minute cannot be *satisfied* by a real
  conversation — the disclosure line alone is spoken before anything useful happens —
  so a 30s cap is not a thrifty client, it is an agent that hangs up on everyone while
  still billing the connected minute. Refusing it at the schema is cheaper than
  explaining it in support.
- the ceiling is 3600s. It is the point past which the guard has stopped guarding: an
  hour of robot-to-voicemail is the runaway §2b:107 exists to prevent, whatever the
  client typed. It is a CHECK rather than a clamp because silently rewriting a client's
  number is how a cap becomes untrustworthy.
- `IS NULL OR` first, because a CHECK returning NULL passes, and writing the constraint
  so it *accidentally* admits NULL rather than *explicitly* admitting it is how the
  next reader mistakes the sentinel for an oversight.

--------------------------------------------------------------------------------
WHY THEY TRAVEL TOGETHER
--------------------------------------------------------------------------------

A cap is a FAST-lane field (it changes conduct, not content — it cannot alter one word
the agent says) so §2b puts it on the side that applies immediately, and applying
immediately means publishing immediately. Without `live_prompt_id`, publishing a cap
change would drag whatever unapplied script sat in `system_prompt_id` onto a live
client's phone line — the precise blast-radius accident §2b:101 is written to prevent.
Shipping the cap without the pointer would build the runaway guard by opening the leak.

--------------------------------------------------------------------------------
LOCKING
--------------------------------------------------------------------------------

Both `ADD COLUMN`s are nullable with no default: catalog-only since PG11, no rewrite,
no scan. The CHECK is added `NOT VALID` (brief ACCESS EXCLUSIVE for the catalog row,
no scan) and validated separately under SHARE UPDATE EXCLUSIVE, which blocks neither
readers nor writers. The FK is added NOT VALID and validated the same way — an FK
`ADD CONSTRAINT` otherwise takes ACCESS EXCLUSIVE on BOTH tables while it scans, and
`prompt_versions` is on the publish path. `lock_timeout` bounds the wait so a queued
ACCESS EXCLUSIVE request cannot park in front of every other session (hard rule 8).

The backfill UPDATE runs inside a `NO FORCE` / `FORCE` bracket: RLS on `agents` is
FORCEd and the migration role owns the table, so the owner is subject to the policy
too and — with no `app.tenant_id` GUC set — an unbracketed UPDATE would match zero
rows and report success. Same bracket, same reason, as d3b71c9a5e08 and f4a8e1c07b62.

**RLS.** No new table, so no new policy: `agents` already carries its FORCEd
`tenant_isolation` policy and both columns inherit the table's protection — a column
is not a separate security object. That is asserted rather than assumed:
`tests/two_speed_publishing_test.py::test_a_second_tenant_sees_no_agent_and_cannot_
read_or_write_the_new_columns` reads and writes both columns as another tenant and
requires zero rows.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Drops the constraints and then the columns, in the reverse order of creation. What is
lost is what only these columns hold: per-agent caps revert to the platform default
(a widening, so no call gets *longer* than 600s that was not already allowed to be),
and every staged-but-unapplied script becomes indistinguishable from an applied one —
which is precisely the pre-migration behaviour, since the pre-migration code publishes
`system_prompt_id`. The code that ran before this revision runs correctly against the
post-downgrade schema, which is the sense hard rule 8 means by reversible. Nothing is
two-step-deprecated here because nothing is being removed: both columns are new.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4e7b2c95d18"
down_revision: str | None = "f9c2b41a8e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agents"

CK_CAP = "ck_agents_max_call_duration_range"
FK_LIVE_PROMPT = "fk_agents_live_prompt_id"

# Mirrors `agents.models.CALL_CAP_MIN_S` / `CALL_CAP_MAX_S` (DATA-MODEL §10: CHECK
# constraints mirror the enums). Spelled out rather than imported — a migration is a
# snapshot of the schema on the day it ran, and importing today's constants would
# rewrite history the next time somebody widens the range.
_CAP_SQL = "max_call_duration_s IS NULL OR (max_call_duration_s >= 60 AND max_call_duration_s <= 3600)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("max_call_duration_s", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("live_prompt_id", postgresql.UUID(), nullable=True))

    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_CAP} CHECK ({_CAP_SQL}) NOT VALID")
    # NOT VALID: an FK ADD CONSTRAINT otherwise holds ACCESS EXCLUSIVE on `agents` AND
    # `prompt_versions` for the length of its scan, and `prompt_versions` is on the
    # publish path. SET NULL matches `system_prompt_id`'s FK exactly, so the two
    # pointers degrade identically when a version row is removed.
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {FK_LIVE_PROMPT} "
        "FOREIGN KEY (live_prompt_id) REFERENCES prompt_versions (id) "
        "ON DELETE SET NULL NOT VALID"
    )

    # RLS on `agents` is FORCEd and this role owns the table, so without the bracket
    # the UPDATE below matches zero rows and reports success — every agent would then
    # claim a pending script change nobody made. The two VALIDATEs sit inside the same
    # bracket so a validation scan cannot be RLS-filtered into declaring a constraint
    # proven against zero rows.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    # The backfill runs BEFORE the FK is validated, so the validation scan proves the
    # rows this migration just wrote, not only the rows it inherited.
    op.execute(
        f"UPDATE {TABLE} SET live_prompt_id = system_prompt_id WHERE system_prompt_id IS NOT NULL"
    )
    # Every pre-existing row is NULL under the CHECK and satisfies it trivially; the
    # scan is for the catalog's benefit, so the constraint is not left NOT VALID and
    # therefore skipped by the planner and by future ADD CONSTRAINT checks.
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_CAP}")
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {FK_LIVE_PROMPT}")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {FK_LIVE_PROMPT}")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_CAP}")
    op.drop_column(TABLE, "live_prompt_id")
    op.drop_column(TABLE, "max_call_duration_s")
