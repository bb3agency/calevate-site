"""what the engine was proved to be running

Revision ID: c1f6a94d2b07
Revises: b8d3f47c2a19
Create Date: 2026-08-15 09:20:00.000000

Two columns on `agents`, and they are the THIRD instance of the same shape of fix as
`live_prompt_id` (a4e7b2c95d18) and `live_tts_voice` (c8b3f14e7a29) — one column cannot
hold two answers that are allowed to differ. The first two split CONFIGURED from SENT.
This one splits SENT from CONFIRMED, which is the split neither of them made.

--------------------------------------------------------------------------------
WHAT WAS UNANSWERABLE
--------------------------------------------------------------------------------

`live_prompt_id` and `live_tts_voice` record what `publish_agent` HANDED the engine.
Both were written on the strength of one fact: that our HTTP call to the vendor returned
without raising. A 2xx says the vendor took the bytes; it does not say the agent is
running them, and D-64 put `VoiceEngine.get_agent` on the Protocol with that sentence in
its docstring. Nothing called it. So `status = 'live'` — the word a client reads on their
own screen — was a claim about our own intent, and no row anywhere could distinguish:

    the engine was read back and is holding the published script
    the engine accepted the write and nobody has ever looked

After this migration:

    live_prompt_id / live_tts_voice   what we SENT
    live_verify_state                 what a read-back CONFIRMED
    live_verified_at                  when it confirmed it

and `agents/verification.py` is the one place the verdict is computed.

--------------------------------------------------------------------------------
FOUR VALUES, AND WHY `unverified` IS NOT `unreachable`
--------------------------------------------------------------------------------

    unverified   no read-back has ever been attempted for this row. THE DEFAULT, and
                 what every agent published before this revision honestly is.
    applied      read back; the engine holds the script, the disclosure line and the
                 voice we sent.
    unreadable   read back; the adapter could not FIND one of those properties in the
                 answer. The `AgentSnapshot.*_readable` tri-state, persisted — "we could
                 not tell" is not "it does not match" and is not "it does".
    unreachable  the read-back itself failed. The write may well have landed.

`not_applied` — read back and PROVABLY wrong — is deliberately NOT a value here. It is a
refusal: `publish_agent` raises, the transaction rolls back, and no row is left claiming
a script the engine was observed not to be holding. A state that can only be reached by
committing a known-false claim is a state the schema should not be able to express.

The CHECK is the guard. It is spelled as a constraint rather than left to the
application because the same argument the ledger triggers make: the column's meaning is
read by a screen a client sees, and a fifth value arriving from a future writer would
render as an unexplained word next to the phrase "live".

--------------------------------------------------------------------------------
NO BACKFILL, FOR THE c8b3f14e7a29 REASON
--------------------------------------------------------------------------------

Backfilling `applied` would assert that every already-published agent has been read back,
which is precisely the false claim this column exists to make impossible. `unverified` is
the historically true answer for every existing row, and it self-heals: the next publish
of each agent writes the real verdict.

`live_verified_at` stays NULL except under `applied`. It is a timestamp of EVIDENCE, and
stamping one for a verdict that proved nothing would let a screen render "confirmed 2
minutes ago" over an `unreachable`.

--------------------------------------------------------------------------------
LOCKING AND RLS
--------------------------------------------------------------------------------

`live_verify_state` is NOT NULL with a constant DEFAULT — catalog-only since PG11, so no
table rewrite and no scan (the default is stored in `pg_attribute.atthasmissing`, and
existing rows read it without being touched). `live_verified_at` is nullable with no
default. Both are ACCESS EXCLUSIVE for the length of a catalog update, bounded by
`lock_timeout` so a queued request cannot park in front of every other session
(hard rule 8).

**RLS.** No new table, so no new policy: `agents` already carries its FORCEd
`tenant_isolation` policy and a column is not a separate security object. Asserted rather
than assumed, in `tests/publish_verification_test.py::
test_a_second_tenant_cannot_read_or_write_the_verification_columns`, which reads AND
writes both columns from a second tenant's scope and requires zero rows.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Drops both columns and the CHECK that travels with them. What is lost is only what they
hold: the reader falls back to the pre-revision behaviour of reporting `live` with no
statement about what was confirmed. Nothing is two-step-deprecated because nothing is
removed — both columns are new (hard rule 8).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1f6a94d2b07"
down_revision: str | None = "b8d3f47c2a19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agents"
# `op.f()` at both ends: the metadata naming convention would otherwise prefix
# `ck_agents_` onto a name that already carries it, producing
# `ck_agents_ck_agents_live_verify_state` — a name the downgrade then cannot find.
CHECK_NAME = "ck_agents_live_verify_state"
# The literal set, written once and rendered into the CHECK below rather than spelled a
# second time in SQL — a migration whose constant and whose constraint can disagree is a
# migration that documents a schema it did not create.
STATES = ("unverified", "applied", "unreadable", "unreachable")
CHECK_SQL = "live_verify_state IN (" + ", ".join(f"'{s}'" for s in STATES) + ")"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        TABLE,
        sa.Column(
            "live_verify_state",
            sa.Text(),
            nullable=False,
            server_default="unverified",
        ),
    )
    op.add_column(TABLE, sa.Column("live_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f(CHECK_NAME), TABLE, CHECK_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(CHECK_NAME), TABLE, type_="check")
    op.drop_column(TABLE, "live_verified_at")
    op.drop_column(TABLE, "live_verify_state")
