"""Our own language model on ThinnestAI: the llm_voice minute, the route's model, and where
our Google key is on (D-764)

Revision ID: a4c8e1f6b2d9
Revises: b6d2f8a41c97
Create Date: 2026-10-13 18:00:00.000000

With the console switch `thinnest_own_model` on, Clear agents answer on our Google key with
ThinnestAI's speech-to-text and voice (BYOK scope `llm`) and Studio agents answer on our Google
key and speak on our Cartesia key (scope `llm_voice`, a flat per-minute fee)
(`thinnest-findings/mirror/snapshots/2026-10-13/pages/api-reference/bring-your-own-keys.md:13-29`).

* `byok_llm_voice` joins the minute rate keys on `platform_engine_minute_prices.rate_key` and
  `engine_agent_routes.engine_rate_key`: the operator-attested price of a scope `llm_voice`
  minute. A scope `llm` minute bills the voice band's own rate (:21-24), so it needs no key.
* `engine_agent_routes.engine_own_model`: the model of our key the vendor agent was published
  on, NULL when it answers on ThinnestAI's own model. The meter costs a call's tokens at this
  model's attested price, and the own-model sweep repairs the agent to it.
* `tenant_engine_workspaces.own_model_enabled_at / _checked_at / _error_code`: where our Google
  key is installed and confirmed in a client's own workspace, as the `studio_*` columns of
  `e9b2c7d4a1f3` record it for our Cartesia key.

Both tables keep their RLS posture: `engine_agent_routes` is global by design and
`tenant_engine_workspaces` keeps its FORCEd tenant policy; nullable columns change neither.

DOWNGRADE refuses while a `byok_llm_voice` price is attested (append-only, hard rule 4) or a
route is stamped with it, then drops the columns. The vendor state is untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "a4c8e1f6b2d9"
down_revision: str | None = "b6d2f8a41c97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies, not imports: a migration records what the schema became at this revision.
_RATE_KEYS_OLD = "('platform', 'standard', 'premium', 'studio', 'byok_voice')"
_RATE_KEYS_NEW = "('platform', 'standard', 'premium', 'studio', 'byok_voice', 'byok_llm_voice')"
_PRICE_CK = "ck_platform_engine_minute_prices_rate_key"
_ROUTE_CK = "ck_engine_agent_routes_engine_rate_key"
_MODEL_CK = "ck_engine_agent_routes_engine_own_model_shape"
_ERROR_CK = "ck_tenant_engine_workspaces_own_model_error_code_bounded"
_WORKSPACES = "tenant_engine_workspaces"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(_PRICE_CK), "platform_engine_minute_prices", type_="check")
    op.create_check_constraint(
        op.f(_PRICE_CK), "platform_engine_minute_prices", f"rate_key IN {_RATE_KEYS_NEW}"
    )
    op.drop_constraint(op.f(_ROUTE_CK), "engine_agent_routes", type_="check")
    op.create_check_constraint(
        op.f(_ROUTE_CK),
        "engine_agent_routes",
        f"engine_rate_key IS NULL OR engine_rate_key IN {_RATE_KEYS_NEW}",
    )
    op.add_column("engine_agent_routes", sa.Column("engine_own_model", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f(_MODEL_CK),
        "engine_agent_routes",
        "engine_own_model IS NULL OR engine_own_model ~ '^[^[:space:]]{1,128}$'",
    )
    op.add_column(
        _WORKSPACES, sa.Column("own_model_enabled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        _WORKSPACES, sa.Column("own_model_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(_WORKSPACES, sa.Column("own_model_error_code", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f(_ERROR_CK),
        _WORKSPACES,
        "own_model_error_code IS NULL OR char_length(own_model_error_code) <= 64",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _refuse_stranded_rates()
    op.drop_constraint(op.f(_ERROR_CK), _WORKSPACES, type_="check")
    op.drop_column(_WORKSPACES, "own_model_error_code")
    op.drop_column(_WORKSPACES, "own_model_checked_at")
    op.drop_column(_WORKSPACES, "own_model_enabled_at")
    op.drop_constraint(op.f(_MODEL_CK), "engine_agent_routes", type_="check")
    op.drop_column("engine_agent_routes", "engine_own_model")
    op.drop_constraint(op.f(_ROUTE_CK), "engine_agent_routes", type_="check")
    op.create_check_constraint(
        op.f(_ROUTE_CK),
        "engine_agent_routes",
        f"engine_rate_key IS NULL OR engine_rate_key IN {_RATE_KEYS_OLD}",
    )
    op.drop_constraint(op.f(_PRICE_CK), "platform_engine_minute_prices", type_="check")
    op.create_check_constraint(
        op.f(_PRICE_CK), "platform_engine_minute_prices", f"rate_key IN {_RATE_KEYS_OLD}"
    )


def _refuse_stranded_rates() -> None:
    """Refuse BEFORE anything changes: an attested `byok_llm_voice` price cannot be deleted
    (append-only) and a route stamped with it would fail the narrower CHECK."""
    if probe_skipped_offline(
        "offline `--sql`: the pre-flight that refuses to narrow the minute rate keys while a\n"
        "`byok_llm_voice` price or route exists was NOT run. Check first with:\n"
        "SELECT count(*) FROM platform_engine_minute_prices WHERE rate_key = 'byok_llm_voice';\n"
        "SELECT count(*) FROM engine_agent_routes WHERE engine_rate_key = 'byok_llm_voice';"
    ):
        return
    bind = op.get_bind()
    prices = bind.execute(
        sa.text(
            "SELECT count(*) FROM platform_engine_minute_prices WHERE rate_key = 'byok_llm_voice'"
        )
    ).scalar_one()
    routes = bind.execute(
        sa.text("SELECT count(*) FROM engine_agent_routes WHERE engine_rate_key = 'byok_llm_voice'")
    ).scalar_one()
    if prices or routes:
        raise RuntimeError(
            f"{prices} attested `byok_llm_voice` price row(s) and {routes} route row(s) stamped "
            "with it exist. Prices are append-only and cannot be removed; re-publish those "
            "agents with the own-model switch off and keep this revision."
        )
