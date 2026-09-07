"""usage_events gains `tts_kchars` — the BYOK synthesizer leg's own count

Revision ID: f4b90c1d7e26
Revises: e1d75c2b8a43
Create Date: 2026-09-07 00:00:00.000000

D-547 / plan §3.5. A Cartesia call's synthesizer leg costs ₹0 from the engine (BYOK —
Bolna's own pricing page, plan ADDENDUM 3 §3.5), so `tts_chars`, which carries the
ENGINE's reported leg charge at `qty = 1`, has nothing to report for it. What that leg
costs is the operator-attested plan rate (`platform_tts_prices`, migration e1d75c2b8a43)
times the characters our own transcript says the agent spoke — a real count, which
belongs in `qty` rather than being folded into a single-unit price.

**PER THOUSAND CHARACTERS, and the `k` is a money decision.** `unit_cost_paid` is
NUMERIC(12,4), so the smallest non-zero price expressible per unit of `qty` is ₹0.0001.
The attested Startup-plan rate is ₹3.4496 per 1,000 characters = ₹0.0034496 each, which
stores as 0.0034 and meters our own cost 1.4% LIGHT on every Cartesia call — margin
overstated, on an append-only ledger, silently. Per thousand the same figure stores as
3.4496 exactly. `billing/models.AI_ASSIST_UNIT_TYPES` carries the same argument at the
same column for the LLM legs; this is that decision applied where it recurs.

Both unit types stay: they are different measurements (a vendor's leg charge and our own
character count), and a `qty` whose unit depended on which voice spoke would be a column
no reader could sum.

**Locking.** One CHECK constraint dropped and re-created on `usage_events`. That takes an
ACCESS EXCLUSIVE lock and VALIDATES the new constraint against every existing row — the
new list is a strict SUPERSET of the old one, so no row can fail it, but the scan is real
and this is why `lock_timeout` is set: on a large table the statement must fail fast and
be re-run in a quiet window rather than queue behind a long read and block the meter.

**Downgrade** restores the previous list. It fails loudly if any `tts_kchars` row exists
by then, which is correct: silently deleting metered cost rows to make a constraint fit is
how a month stops adding up.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b90c1d7e26"
down_revision: str | None = "e1d75c2b8a43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from `billing/models.UNIT_TYPES`: a migration states
# what the schema was and became at THIS revision, and importing today's constant would
# make an old revision re-render itself against a list that has moved since.
_BEFORE = (
    "telephony_s",
    "stt_s",
    "tts_chars",
    "llm_tok_in",
    "llm_tok_out",
    "platform_min",
    "number_rental",
    "other",
    "ai_assist_ktok_in",
    "ai_assist_ktok_out",
)
_AFTER = (
    "telephony_s",
    "stt_s",
    "tts_chars",
    "tts_kchars",
    "llm_tok_in",
    "llm_tok_out",
    "platform_min",
    "number_rental",
    "other",
    "ai_assist_ktok_in",
    "ai_assist_ktok_out",
)


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
    _recheck(_BEFORE)
