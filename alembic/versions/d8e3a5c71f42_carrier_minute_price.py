"""the carrier's fee is a minute price an operator can attest (D-813)

Revision ID: d8e3a5c71f42
Revises: c5f6e1202331
Create Date: 2026-10-18 16:00:00.000000

A ThinnestAI call no agent ran on (it ended before the agent spoke, or a number forward put it
through to a phone) is charged the phone carrier's fee only, in 30-second blocks
(`thinnest-findings/mirror/snapshots/2026-10-18/pages/api-reference/calls/get-call.md:
1236-1243`). The meter costs such a call at an operator-attested `carrier` rate, so
`platform_engine_minute_prices.rate_key` accepts `carrier`. A route is never stamped with it
(no agent is published on the carrier's fee), so `engine_agent_routes.engine_rate_key` keeps
its CHECK. RLS is unchanged: the price table is global, as before.

DOWNGRADE refuses while a `carrier` price is attested (append-only, hard rule 4), then
restores the narrower CHECK.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "d8e3a5c71f42"
down_revision: str | None = "c5f6e1202331"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies, not imports: a migration records what the schema became at this revision.
_RATE_KEYS_OLD = "('platform', 'standard', 'premium', 'studio', 'byok_voice', 'byok_llm_voice')"
_RATE_KEYS_NEW = (
    "('platform', 'standard', 'premium', 'studio', 'byok_voice', 'byok_llm_voice', 'carrier')"
)
_PRICE_CK = "ck_platform_engine_minute_prices_rate_key"
_PRICES = "platform_engine_minute_prices"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(_PRICE_CK), _PRICES, type_="check")
    op.create_check_constraint(op.f(_PRICE_CK), _PRICES, f"rate_key IN {_RATE_KEYS_NEW}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _refuse_stranded_price()
    op.drop_constraint(op.f(_PRICE_CK), _PRICES, type_="check")
    op.create_check_constraint(op.f(_PRICE_CK), _PRICES, f"rate_key IN {_RATE_KEYS_OLD}")


def _refuse_stranded_price() -> None:
    """Refuse BEFORE anything changes: an attested `carrier` price cannot be deleted
    (append-only) and would fail the narrower CHECK."""
    if probe_skipped_offline(
        "offline `--sql`: the pre-flight that refuses to narrow the minute rate keys while a\n"
        "`carrier` price exists was NOT run. Check first with:\n"
        "SELECT count(*) FROM platform_engine_minute_prices WHERE rate_key = 'carrier';"
    ):
        return
    prices = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM {_PRICES} WHERE rate_key = 'carrier'"))
        .scalar_one()
    )
    if prices:
        raise RuntimeError(
            f"{prices} attested `carrier` price row(s) exist. Prices are append-only and "
            "cannot be removed; keep this revision."
        )
