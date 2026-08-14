"""the voice the engine is holding

Revision ID: c8b3f14e7a29
Revises: d5b8a2c60e17
Create Date: 2026-08-14 10:40:00.000000

Two columns on `agents`, and they are the same shape of fix as `live_prompt_id`
(a4e7b2c95d18) for the same reason: one column cannot hold two answers that are
allowed to differ.

--------------------------------------------------------------------------------
WHAT WAS UNANSWERABLE
--------------------------------------------------------------------------------

`agents.tts_voice` holds the voice an operator CONFIGURED. Nothing held the voice the
engine is actually speaking in, and the two are allowed to diverge by design:
`agents/voice_routes.py::set_agent_voice` deliberately does not touch the engine
("re-voicing a running client's phone line on an ear test we have not done is not a
safe default"), so between a voice change and the next publish the row says one thing
and the caller's handset says another. That is not a bug — it is the documented
behaviour, and `SetVoiceOut.republish_required` announces it.

What WAS a bug is that the gap could only be guessed at. `republish_required` was
computed as `published`, i.e. "this agent is on the engine, so assume the voice moved" —
which is right the first time and wrong every time after, including when an operator
re-selects the voice the engine already holds. And no read exposed either value, so the
picker that sets a voice could not show one.

After this migration:

    tts_voice       = the CONFIGURED voice   (what an operator chose)
    live_tts_voice  = the SENT voice         (what `publish_agent` last handed the engine)

and "does a republish change what callers hear?" is
`live_tts_voice IS DISTINCT FROM tts_voice`, derived rather than stored, so it cannot
drift the way a `voice_dirty` flag would. `agents/publishing.py` renders both, and
`GET /v1/agents/{agent_id}/pending` — the read that already answers configured-vs-live
for the script and the call cap — carries them.

`live_tts_provider` travels with it because the pair is only meaningful together:
`engine/bolna.py:557` sends `synthesizer.provider` and `synthesizer.provider_config.voice`
as ONE object, and a mirror that records half of what was sent can lie about the other
half. `set_agent_voice` already writes the configured pair together for exactly this
reason.

--------------------------------------------------------------------------------
NO BACKFILL, AND THAT IS THE CAREFUL CHOICE
--------------------------------------------------------------------------------

a4e7b2c95d18 backfilled `live_prompt_id := system_prompt_id` because that was a
HISTORICAL TRUTH: until that revision every prompt version reached the engine at the
moment it was written, so the two pointers genuinely agreed on every existing row.

No equivalent truth exists here, and assuming one would invert the meaning of the
feature. Voice writes have NEVER reached the engine, so for a published agent whose
voice was set and not republished the row and the engine legitimately disagree today.
Backfilling `live_tts_voice := tts_voice` would tell that client their callers already
hear the new voice — the exact false claim the column exists to prevent, made about the
one row where it is most likely to be wrong.

So both columns start NULL, and NULL is read as "nothing has been recorded as sent":

    published = false, live_tts_voice IS NULL   nothing is live; there is nothing to know
    published = true,  live_tts_voice IS NULL   published before this column existed, or
                                                published with no voice set — either way
                                                we cannot prove the engine holds the
                                                configured voice

`IS DISTINCT FROM` gives the right answer in every one of those cases, and it errs in
the only safe direction: an agent whose voice really was already published reports
`republish_required` until someone publishes again, which costs one harmless republish.
The opposite error — reporting "in sync" for an agent that is not — is a claim about a
live phone line, and this whole slice exists because that claim was unfalsifiable.

The state self-heals: `agents/service.py::publish_agent` writes both columns in the same
UPDATE that records `engine_agent_ref`, from the config it just handed the engine, so
the first publish after this migration makes the answer exact and it stays exact.

--------------------------------------------------------------------------------
NO CHECK CONSTRAINT
--------------------------------------------------------------------------------

Deliberate, and it mirrors `tts_voice` itself: the catalog (`agents/voices.py`) is the
allowlist and it lives at the API boundary, because the set of voices we OFFER changes
with a decision-log entry while the set of voices already STORED on rows must not become
unreadable when it does. A CHECK naming today's two ids would turn tomorrow's catalog
edit into a migration on every agent row, and would make a retired voice unreadable
rather than merely unofferable. `live_tts_voice` records what we SENT, which is a fact
about the past — constraining a historical record to today's allowlist is how history
gets rewritten to fit the present.

--------------------------------------------------------------------------------
LOCKING AND RLS
--------------------------------------------------------------------------------

Both `ADD COLUMN`s are nullable with no default: catalog-only since PG11, no table
rewrite and no scan, so this is an ACCESS EXCLUSIVE held for the length of a catalog
update. `lock_timeout` bounds the wait so a queued ACCESS EXCLUSIVE request cannot park
in front of every other session (hard rule 8). There is no backfill, so the
`NO FORCE`/`FORCE` bracket a4e7b2c95d18 needed is not needed here — nothing in this
migration reads or writes a row.

**RLS.** No new table, so no new policy: `agents` already carries its FORCEd
`tenant_isolation` policy and both columns inherit the table's protection — a column is
not a separate security object. Asserted rather than assumed, in
`tests/agent_voice_test.py::test_a_second_tenant_cannot_read_or_write_the_live_voice_columns`,
which reads AND writes both columns from a second tenant's scope and requires zero rows.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Drops both columns. What is lost is only what they hold: the reader falls back to the
pre-migration behaviour of treating any published agent as needing a republish after a
voice change, which is what the code before this revision already did. The code that ran
before this revision runs correctly against the post-downgrade schema — the sense hard
rule 8 means by reversible. Nothing is two-step-deprecated because nothing is removed:
both columns are new.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8b3f14e7a29"
down_revision: str | None = "d5b8a2c60e17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agents"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("live_tts_voice", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("live_tts_provider", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column(TABLE, "live_tts_provider")
    op.drop_column(TABLE, "live_tts_voice")
