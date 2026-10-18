"""a prompt-cache hit is priced at its own attested rung

Revision ID: b4d2e9c71a58
Revises: e3b9d4a7c218
Create Date: 2026-10-18 14:00:00.000000

D-816 (founder, 18 Oct 2026: cut our own model spend without lowering quality).

* `platform_model_prices.cached_input_usd_per_mtok` — the operator-attested price of input
  the vendor served from its prompt cache, USD per million tokens, NULL when none was
  attested (every existing row). Gemini 3.1 Flash-Lite lists $0.025 against $0.25 input
  (ai.google.dev/gemini-api/docs/pricing, read 18 Oct 2026); the figure that bills is the
  operator's reading, never that page. `ck_platform_model_prices_cached_input_range` keeps it
  above zero and at most the input price. The table is append-only; adding a nullable column
  rewrites nothing and fires no row trigger.
* `usage_events.unit_type` gains `ai_assist_10ktok_cached_in`: the cached share of an
  assist's input, per ten thousand tokens (`billing/rates.CACHED_TOKENS_PER_UNIT` argues the
  quantum). `platform_ai_usage` has no unit CHECK and needs nothing.

**Locking.** The CHECK on `usage_events` is dropped and re-created, which takes an ACCESS
EXCLUSIVE lock and scans the table; the new list is a strict superset, so no row can fail it.
`lock_timeout` makes the statement fail fast rather than queue behind a long read.

**Downgrade** restores both. It fails loudly while any cached row or attested cached price
exists, which is correct: deleting metered cost or an operator's attestation to make a
schema fit is how a month stops adding up.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d2e9c71a58"
down_revision: str | None = "e3b9d4a7c218"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from `billing/models.UNIT_TYPES`: a migration states what
# the schema was and became at THIS revision (d6f2b8a41c73 last changed the list).
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
)
_UNITS_AFTER = (*_UNITS_BEFORE, "ai_assist_10ktok_cached_in")


def _units(units: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE usage_events DROP CONSTRAINT ck_usage_events_unit_type_enum")
    op.execute(
        "ALTER TABLE usage_events ADD CONSTRAINT ck_usage_events_unit_type_enum "
        f"CHECK (unit_type IN ({', '.join(repr(u) for u in units)}))"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "platform_model_prices",
        sa.Column("cached_input_usd_per_mtok", sa.Numeric(12, 6), nullable=True),
    )
    op.execute(
        "ALTER TABLE platform_model_prices ADD CONSTRAINT "
        "ck_platform_model_prices_cached_input_range CHECK (cached_input_usd_per_mtok IS NULL "
        "OR (cached_input_usd_per_mtok > 0 AND cached_input_usd_per_mtok <= input_usd_per_mtok))"
    )
    _units(_UNITS_AFTER)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _units(_UNITS_BEFORE)
    op.execute(
        "ALTER TABLE platform_model_prices "
        "DROP CONSTRAINT ck_platform_model_prices_cached_input_range"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM platform_model_prices "
        "WHERE cached_input_usd_per_mtok IS NOT NULL) THEN RAISE EXCEPTION "
        "'an attested cached-input price exists; it would be lost'; END IF; END $$"
    )
    op.drop_column("platform_model_prices", "cached_input_usd_per_mtok")
