"""The voice-catalogue cache stops naming a withdrawn TTS vendor and starts naming the live one.

The founder withdrew the **Sarvam TEXT-TO-SPEECH leg** on 18 Sep 2026. Sarvam remains this
product's transcription vendor on every call (Saaras, `SARVAM_API_KEY`) and remains a
sub-processor; this migration touches neither. What it touches is one CHECK constraint on
`platform_voice_catalog.provider`, which enumerated the TTS providers as
`('sarvam', 'cartesia')` and was wrong in BOTH directions the moment the leg moved:

* it still admitted `sarvam`, a provider `calevate_shared.model_lifecycle.TtsProvider` no
  longer has and `agents/voices.Voice.provider` can no longer hold; and
* it refused `gnani`, which `TtsProvider` has carried since D-618 and which now serves the
  VALUE rung (`agents/voices.VOICE_TIER_OF_PROVIDER`). Without this, no Gnani voice can be
  synced or admitted at all — the value rung would have a provider on paper and no way to
  put a voice in front of anybody, ever.

**WHY A MIGRATION AT ALL, WHEN THE INSTRUCTION FOR THIS CHANGE WAS THAT NONE BE WRITTEN.**
That instruction was about the MONEY tables — `credit_lots`, `organizations`, `agents`,
`usage_events` — which the founder verified empty on the production host on 18 Sep 2026, so
there was no frozen rate to preserve and no sold term to restate. This is a different kind
of object: `platform_voice_catalog` is a CACHE of the voice platform's own list, holds no
money, has no RLS (`db/registry.RLS_EXEMPT_TENANT_COLUMNS` records why) and is re-derivable
by running the sync. Leaving its constraint listing a vendor we do not use and excluding the
one we do would be a schema fact that is simply false, and a half-wired value rung.

**REVERSIBLE, AND THE DESTRUCTION IN EACH DIRECTION IS NARROW AND NAMED.** Neither direction
is a pure widening, so each deletes exactly the rows the OTHER side's constraint refuses,
and nothing else:

* `upgrade` deletes `provider = 'sarvam'` rows. They are already dead to the application —
  `voice_sync.voice_from_row` skips a row whose `tts_model` this build does not offer, and
  `bulbul:v3` left `TtsModel` in this same change — so they could not reach a picker or a
  publish. A live agent still holding such a `tts_voice` is unaffected: that column is free
  text and `speech_for_voice_id` passes an unrecognised id through unchanged, by design.
* `downgrade` deletes `provider = 'gnani'` rows, which only this revision made insertable.

Re-running the sync after either direction restores whatever the platform actually lists.

Revision ID: d8b3f5127ac4
Revises: e3a7c05b91d4
"""

from __future__ import annotations

from alembic import op

revision = "d8b3f5127ac4"
down_revision = "e3a7c05b91d4"
branch_labels = None
depends_on = None

_TABLE = "platform_voice_catalog"

_OLD = "provider IN ('sarvam', 'cartesia')"
_NEW = "provider IN ('cartesia', 'gnani')"

#: THE BARE NAME, NOT THE RENDERED ONE. `alembic/env.py` sets a naming convention, so
#: `op.drop_constraint` runs whatever it is given back through
#: `ck_%(table_name)s_%(constraint_name)s`; handing it the already-rendered name drops
#: nothing. Both directions pass the bare name — `e3a7c05b91d4` is the precedent and carries
#: the worked example of the failure.
_NAME = "provider"


def upgrade() -> None:
    # No RLS bracket, unlike `e3a7c05b91d4`: this table is deliberately un-policied (it is
    # platform-scoped, not tenant-scoped), so a migration's DELETE matches the rows it names.
    op.execute(f"DELETE FROM {_TABLE} WHERE provider = 'sarvam'")
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)


def downgrade() -> None:
    op.execute(f"DELETE FROM {_TABLE} WHERE provider = 'gnani'")
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _OLD)
