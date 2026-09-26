"""usage_events gains `stt_min` — the speech-to-text leg per minute of audio

Revision ID: c5e8a1f47b92
Revises: e95e0d780629
Create Date: 2026-09-26 00:00:00.000000

D-638. `stt_s` priced a second of audio at the Saaras card rate, ₹30/hour
(`billing/rates.STT_INR_PER_HOUR`), i.e. ₹0.008333… a second. `unit_cost_paid` is
NUMERIC(12,4), so that rate stores as 0.0083 and meters our STT cost 0.4% light on every
call, on an append-only ledger. Per minute the same rate is ₹0.5000 exactly. This is the
decision `f4b90c1d7e26` (`tts_kchars`) and `a3f1c6e82d47` (`llm_ktok_*`) made at the same
column: scale the unit until the rate fits, rather than widen a column holding frozen
history.

`stt_s` STAYS IN THE CHECK. Every row already written carries it and hard rule 4 forbids
rewriting them; nothing writes it after this revision. It can leave the constraint only on
a table holding no such row, which an append-only ledger that has metered a call never is.

A UNIQUE INDEX comes with it, partial on `stt_min`: the owned runtime's settlement insert is
`ON CONFLICT DO NOTHING` with no target and relies on a unique index to make a re-settled
leg converge on one row, and `stt_s`'s protection (`ux_usage_events_tenant_call_unit`) does
not reach the new unit. A separate index rather than a wider one for `a3c62f8b4d19`'s
reason: re-creating the older key would drop the protection on four live legs. It carries
no `created_at` floor and is built NOT concurrently, as `a3f1c6e82d47` built its `ktok`
index: no row can hold `stt_min` until the CHECK above admits it, so the build scans a
predicate that matches nothing under the lock the CHECK re-creation already holds.

LOCKING. The CHECK is dropped and re-created — ACCESS EXCLUSIVE, validating every row. The
new list is a strict superset of the old, so no row can fail, but the scan is real; hence
`lock_timeout`, so the statement fails fast rather than queueing in front of the meter.

DOWNGRADE drops the index and re-narrows the CHECK. The CHECK half fails loudly if any
`stt_min` row exists by then, which is correct: deleting metered cost rows to make a
constraint fit is how a month stops adding up.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5e8a1f47b92"
down_revision: str | None = "e95e0d780629"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from `billing/models.UNIT_TYPES`: a migration states
# what the schema was and became at THIS revision, and importing today's constant would
# make an old revision re-render itself against a list that has moved since.
_BEFORE = (
    "telephony_s",
    "stt_s",
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
_AFTER = (
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

_INDEX = "ux_usage_events_tenant_call_stt_min"
_PREDICATE = "call_id IS NOT NULL AND unit_type = 'stt_min'"


def _recheck(units: tuple[str, ...]) -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE usage_events DROP CONSTRAINT ck_usage_events_unit_type_enum")
    op.execute(
        "ALTER TABLE usage_events ADD CONSTRAINT ck_usage_events_unit_type_enum "
        f"CHECK (unit_type IN {units!r})"
    )


def upgrade() -> None:
    _recheck(_AFTER)
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX} ON usage_events "
        f"(tenant_id, call_id, unit_type) WHERE {_PREDICATE}"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    _recheck(_BEFORE)
