"""In-call actions: the agent's action secret on its engine route (phase 2 of D-678)

Revision ID: e8a4c2f17b39
Revises: d681a7c3e5f2
Create Date: 2026-10-07 18:00:00.000000

ThinnestAI reaches our in-call tools (opt-out, call-back, call-back cancel, handoff) as
custom actions: HTTPS calls to our API that carry a header we chose, stored sealed on their
side and never shown again (`thinnest-findings/mirror/snapshots/2026-10-07/pages/
api-reference/actions/create-action.md:7, :457`). That header is the only thing that tells
our endpoint which agent is calling, so we must hold the value too, to verify it and to send
it again when an action has to be re-created.

It lives on `engine_agent_routes` for `webhook_secret_*`'s reason (f3a8c61d2e57): the
endpoint receives no tenant, and this row is the one the request can be resolved against
without one. Sealed under `PLATFORM_KEK` (`core/envelope.py`) — unlike the webhook secret it
is read by `apps/api` only, so voice-runtime's narrower key is not needed for it. The five
envelope columns are all set or all NULL.

The downgrade drops the columns without a refusal: the vendor keeps the header, and the next
publish after a re-upgrade finds no secret held, mints a new one and replaces the header on
every action (`reliability/engine_actions.ensure_agent_actions`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8a4c2f17b39"
down_revision: str | None = "d681a7c3e5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "engine_agent_routes"
_SEALED = (
    "action_secret_ciphertext",
    "action_secret_nonce",
    "action_secret_dek_wrapped",
    "action_secret_dek_nonce",
    "action_secret_kek_version",
)
_WHOLE = "ck_engine_agent_routes_action_secret_sealed_whole"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column in _SEALED[:-1]:
        op.add_column(_TABLE, sa.Column(column, sa.LargeBinary(), nullable=True))
    op.add_column(_TABLE, sa.Column("action_secret_kek_version", sa.Integer(), nullable=True))
    all_null = " AND ".join(f"{c} IS NULL" for c in _SEALED)
    none_null = " AND ".join(f"{c} IS NOT NULL" for c in _SEALED)
    op.create_check_constraint(op.f(_WHOLE), _TABLE, f"({all_null}) OR ({none_null})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(_WHOLE), _TABLE, type_="check")
    for column in reversed(_SEALED):
        op.drop_column(_TABLE, column)
