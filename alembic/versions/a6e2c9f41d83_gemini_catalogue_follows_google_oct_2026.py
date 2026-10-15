"""the model CHECKs follow Google's October catalogue (D-786)

Revision ID: a6e2c9f41d83
Revises: b4d7e2a9c815
Create Date: 2026-10-15 12:00:00.000000

Re-states `ck_agents_llm_model_allowed` and `ck_organizations_default_llm_model_allowed`
over today's `calevate_shared.engine.LLM_MODEL_NAMES`: `gemini-3.5-flash` leaves (Google's
models page no longer lists it and its deprecations page names `gemini-3.6-flash` as its
replacement, both read 15 Oct 2026), `gemini-3.5-flash-lite` and `gemini-3.8-flash` arrive
(stable, and the two models Google names for new projects).

No row is rewritten. Neither column can hold any of the three: none was ever selectable,
and `agents/llm_models.validate_llm_model` refuses a model that is not offerable, so the
ADD cannot meet a violating row; if one existed the ADD would refuse and say so, which is
the right outcome for a value nobody can run. Drop-and-add under the same names for
`d3a7c81f45be`'s reason (Postgres cannot alter a CHECK's expression, and a second name
would leave the old one in force).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from apps.api.db.migration_offline import probe_skipped_offline

revision = "a6e2c9f41d83"
down_revision = "b4d7e2a9c815"
branch_labels = None
depends_on = None

CK_ORG_MODEL = "ck_organizations_default_llm_model_allowed"
CK_AGENT_MODEL = "ck_agents_llm_model_allowed"

# FROZEN COPY of `LLM_MODEL_NAMES` on the day this revision was written: a revision that
# imported the live constant would replay differently once it changed.
ALLOWED_LLM_MODELS = (
    # azure_openai
    "gpt-4.1-mini",
    "gpt-4o-mini",
    # openai direct
    "gpt-5.4-mini",
    "gpt-5.6-luna",
    # google gemini
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
)

# What `d3a7c81f45be` admitted, restored by the downgrade.
PRIOR_ALLOWED_LLM_MODELS = (
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "gpt-5.4-mini",
    "gpt-5.6-luna",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
)


def _apply(models: tuple[str, ...]) -> None:
    """Re-state both CHECKs over `models` under their existing names. `op.execute` rather
    than `op.create_check_constraint`, which would double the naming-convention prefix
    (see `c4f18a6b90e2`)."""
    admitted = ", ".join(f"'{model}'" for model in sorted(models))
    for table, constraint, column in (
        ("organizations", CK_ORG_MODEL, "default_llm_model"),
        ("agents", CK_AGENT_MODEL, "llm_model"),
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"CHECK ({column} IS NULL OR {column} IN ({admitted}))"
        )
    _assert_rls_still_forced()


def _assert_rls_still_forced() -> None:
    """Hard rule 1, re-read from the catalog after the DDL."""
    if probe_skipped_offline(
        "offline `--sql`: the post-DDL re-read of pg_class that proves `organizations` and\n"
        "`agents` are still FORCE ROW LEVEL SECURITY was NOT run. The DDL above is\n"
        "unaffected; run `uv run python -m scripts.check_rls_coverage` against the database\n"
        "this script is applied to."
    ):
        return
    for table in ("organizations", "agents"):
        row = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = CAST(:qualified AS regclass)"
                ),
                {"qualified": f"public.{table}"},
            )
            .first()
        )
        if row is None or not (row[0] and row[1]):
            raise RuntimeError(
                f"{table} is not FORCE ROW LEVEL SECURITY after this migration; the "
                "language-model selection would be readable across tenants (hard rule 1)"
            )


def upgrade() -> None:
    _apply(ALLOWED_LLM_MODELS)


def downgrade() -> None:
    _apply(PRIOR_ALLOWED_LLM_MODELS)
