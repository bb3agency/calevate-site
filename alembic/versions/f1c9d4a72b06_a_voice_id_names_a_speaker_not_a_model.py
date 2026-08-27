"""A voice id names a SPEAKER, not a model — `bulbul:v3` becomes `bulbul:v3:ashutosh`.

Revision ID: f1c9d4a72b06
Revises: d7f2a94c61be

--------------------------------------------------------------------------------
WHAT WAS WRONG
--------------------------------------------------------------------------------

`agents.tts_voice` held `bulbul:v3` — a MODEL string — and `engine/bolna.py` pasted it
into the vendor's `synthesizer.provider_config.voice`, which is the SPEAKER slot. The
vendor's own worked example puts the two in different keys: `"provider_config": {"model":
"bulbul:v3", "voice": "Ashutosh", "voice_id": "ashutosh"}` (VERIFIED-VENDOR-REPO,
`bolna-ai/skills@28b24aa`, `create-agent/SKILL.md`). So every published agent named a
model where a speaker belongs and named no model at all, and the engine chose a speaker.

The reason it was not fixed earlier was that no speaker list was known, so moving the
string would have left `voice` unset. That premise is dead: Sarvam's own SDK enumerates
all 44 (VERIFIED-VENDOR-SDK: sarvamai==0.1.31 (PyPI wheel),
`types/text_to_speech_speaker.py`, read 27 Aug 2026), and `apps/api/agents/voices.py` now
carries them as a catalogue whose ids are `<tts_model>:<speaker>`.

--------------------------------------------------------------------------------
WHAT THIS REVISION DOES
--------------------------------------------------------------------------------

A DATA migration only. No column is added, dropped or retyped; `tts_voice`,
`live_tts_voice` and their `*_provider` siblings keep the shape they have had since
`c8b3f14e7a29`. What changes is the VALUE these two free-text columns hold, because the
catalogue that validates writes into them now spells its ids differently — and a row left
holding `bulbul:v3` would publish a body naming a speaker the vendor has never heard of.

Two UPDATEs, each `WHERE ... = 'bulbul:v3'`:

* `agents.tts_voice`      — what an operator CONFIGURED.
* `agents.live_tts_voice` — what `publish_agent` last SENT.

BOTH, and the second is not optional. `agents/publishing.py::voice_diverged` is
`live_tts_voice IS DISTINCT FROM tts_voice`; moving one column and not the other would
report every previously-published agent as needing a republish, forever, on a change that
moved no voice.

--------------------------------------------------------------------------------
THE TARGET, AND WHY IT IS A PLACEHOLDER
--------------------------------------------------------------------------------

`bulbul:v3:ashutosh` (`voices.DEFAULT_VOICE_ID`). `ashutosh` is the speaker in the
vendor's own worked example, which makes it the only speaker id in this tree with an
end-to-end request behind it — it is NOT an ear test and must not be quoted as one. Which
speaker suits Telugu is BRD R-10 / OPERATIONS §2 gate 3, and re-pointing the default after
that test is another data migration of exactly this shape.

**A BACKFILL IS REQUIRED RATHER THAN OPTIONAL** because the alternative is worse in the
direction that matters: leaving the legacy value would keep those agents publishing the
old broken body (`voice: "bulbul:v3"`, no model), silently, while every newly-picked agent
got the fixed one. Hard rule 8's two-step deprecation does not apply — nothing stops being
written and nothing is dropped.

The literal `'bulbul:v3'` is spelled out rather than imported from `voices.py`, per
`d7f2a94c61be`'s rule: a migration is a snapshot of the schema on the day it ran, and
importing today's constant would silently rewrite history the next time the default moves.

Any OTHER value is left exactly as it is. `agents.tts_voice` is free text by design, a
value the catalogue no longer offers must still read back as itself
(`publishing.py::_agent_voice`), and `voices.speech_for_voice_id` passes an unrecognised
id through to the speaker slot — byte for byte the pre-split behaviour. This revision
corrects the one value this repository actually wrote; it does not normalise strangers.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Exactly reversible, which is unusual enough here to say why: the mapping is total and
injective on the rows it touches (one source value, one target value), so the inverse
UPDATE restores the pre-migration state precisely. It is NOT a no-op and must not be
skipped — `voices.py` at the earlier revision refuses `bulbul:v3:ashutosh`, so a
downgraded database whose rows kept the new id would fail the picker's own allowlist.

RLS: no new table and no new column, so no new policy; `agents` has carried its FORCEd
`tenant_isolation` policy since the first migration. These UPDATEs run as the migration
role, which is the only role permitted to bypass it.

Append-only (hard rule 4): `agents` is not in `db.registry.APPEND_ONLY_TABLES` — it is
mutable config, not a ledger — so an UPDATE here is permitted. Nothing in this revision
touches a ledger table.

`lock_timeout` bounds the wait so a queued row lock cannot park in front of every other
session.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1c9d4a72b06"
down_revision: str | None = "d7f2a94c61be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agents"

# Frozen literals — see the module docstring on why these are not imported.
_LEGACY_VOICE_ID = "bulbul:v3"
_SPLIT_VOICE_ID = "bulbul:v3:ashutosh"

_COLUMNS = ("tts_voice", "live_tts_voice")


def _repoint(column: str, *, frm: str, to: str) -> None:
    op.execute(f"UPDATE {TABLE} SET {column} = '{to}' WHERE {column} = '{frm}'")  # noqa: S608


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column in _COLUMNS:
        _repoint(column, frm=_LEGACY_VOICE_ID, to=_SPLIT_VOICE_ID)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column in _COLUMNS:
        _repoint(column, frm=_SPLIT_VOICE_ID, to=_LEGACY_VOICE_ID)
