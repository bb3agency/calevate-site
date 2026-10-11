"""usage_events: the `ai_stt_min` unit, speech-to-text we absorb for the console

Revision ID: b8e2d4f6a1c3
Revises: a5d1c7e93f28
Create Date: 2026-10-11 15:00:00.000000

The teach box's voice note is transcribed by our speech-to-text provider and was metered
nowhere. The founder decided on 11 Oct 2026 that Calevate absorbs it: never charged to the
client and never against its AI allowance, but recorded at our cost per use (hard rule 7).
It is its own unit, `billing/models.AI_STT_UNIT_TYPE`, in `PLATFORM_ABSORBED_UNIT_TYPES`:
`stt_min` is a call's speech leg and client-billed, and the AI-assist units are priced per
thousand tokens of a language model.

The downgrade refuses while any `ai_stt_min` row exists: `usage_events` is append-only, so
those rows cannot be removed, and the old CHECK would not hold them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8e2d4f6a1c3"
down_revision: str | None = "a5d1c7e93f28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out, as every unit migration does: a revision states the schema at that revision.
_BEFORE = (
    "telephony_s",
    "stt_s",
    "stt_min",
    "tts_chars",
    "tts_kchars",
    "llm_tok_in",
    "llm_tok_out",
    "llm_ktok_in",
    "llm_ktok_out",
    "platform_min",
    "number_rental",
    "other",
    "ai_assist_ktok_in",
    "ai_assist_ktok_out",
)
_AFTER = (*_BEFORE, "ai_stt_min")


def _recheck(units: tuple[str, ...]) -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE usage_events DROP CONSTRAINT ck_usage_events_unit_type_enum")
    op.execute(
        "ALTER TABLE usage_events ADD CONSTRAINT ck_usage_events_unit_type_enum "
        f"CHECK (unit_type IN {units!r})"
    )


def upgrade() -> None:
    _recheck(_AFTER)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM usage_events WHERE unit_type = 'ai_stt_min') "
        "THEN RAISE EXCEPTION 'usage_events holds ai_stt_min rows, which are append-only: "
        "this revision cannot be downgraded'; END IF; END $$"
    )
    _recheck(_BEFORE)
