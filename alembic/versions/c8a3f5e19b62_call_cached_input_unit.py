"""a call's prompt-cache hits on our own model are priced at the attested cached rung

Revision ID: c8a3f5e19b62
Revises: b4d2e9c71a58
Create Date: 2026-10-18 18:00:00.000000

D-817 (founder, 18 Oct 2026). `usage_events.unit_type` gains `llm_10ktok_cached_in`: the
share of a ThinnestAI call's input that Google served from its prompt cache on our own key,
per ten thousand tokens (`billing/rates.CACHED_TOKENS_PER_UNIT` argues the quantum), priced
at the rung D-816 added (`platform_model_prices.cached_input_usd_per_mtok`). No column
changes.

**Locking.** The CHECK on `usage_events` is dropped and re-created, which takes an ACCESS
EXCLUSIVE lock and scans the table; the new list is a strict superset, so no row can fail it.
`lock_timeout` makes the statement fail fast rather than queue behind a long read.

**Downgrade** restores the list. It fails loudly while any cached call row exists, which is
correct: deleting metered cost to make a schema fit is how a month stops adding up.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8a3f5e19b62"
down_revision: str | None = "b4d2e9c71a58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from `billing/models.UNIT_TYPES`: a migration states what
# the schema was and became at THIS revision (b4d2e9c71a58 last changed the list).
_UNITS_BEFORE = (
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
    "ai_stt_min",
    "forwarding_test_min",
    "whatsapp_msg",
    "ai_assist_10ktok_cached_in",
)
_UNITS_AFTER = (*_UNITS_BEFORE, "llm_10ktok_cached_in")


def _units(units: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE usage_events DROP CONSTRAINT ck_usage_events_unit_type_enum")
    op.execute(
        "ALTER TABLE usage_events ADD CONSTRAINT ck_usage_events_unit_type_enum "
        f"CHECK (unit_type IN ({', '.join(repr(u) for u in units)}))"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _units(_UNITS_AFTER)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM usage_events "
        "WHERE unit_type = 'llm_10ktok_cached_in') THEN RAISE EXCEPTION "
        "'a call''s cached-input cost is on the ledger; it would be lost'; END IF; END $$"
    )
    _units(_UNITS_BEFORE)
