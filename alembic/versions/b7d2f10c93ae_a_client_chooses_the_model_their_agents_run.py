"""a client chooses the model their agents run — and the column that held it stops being decorative

Revision ID: b7d2f10c93ae
Revises: c9f4a2e17b83
Create Date: 2026-08-22 09:40:00.000000

`agents.llm_model` has existed since the first schema and NOTHING has ever written it.
`agents/service.py::in_call_llm` reads it, so it is not unwired — it is a column with a
reader, no writer and no constraint, which is the shape a typo becomes a model identifier
in: a value outside the allow-list reaching that reader is a 404 from a third party in
the middle of a live phone call (`calevate_shared.engine.AzureOpenAIModel` records the
same failure class for `SARVAM_RETIRED_LLMS`).

WHAT THIS REVISION ADDS
-----------------------
1. `organizations.default_llm_model` TEXT NULL — the ACCOUNT's choice, the middle rung of
   `agent -> organization -> platform`. NULL means "inherit the platform's model", which
   is the state every existing row is created in, so the column needs no backfill and
   changes nothing about any account until somebody chooses.
2. A CHECK on BOTH columns admitting only NULL or a member of the allow-list.

WHY A CHECK AND NOT ONLY THE API VALIDATOR
------------------------------------------
Same instrument and same argument as `ck_agents_direction_enum`, `ck_agents_status_enum`
and `ck_agents_engine_enum`, which render their CHECKs from the Literals they mirror
(`agents/models.py`, D-104). The API refuses an unknown identifier at the write path, and
the write path is not the only way a row is written: a restore that lands without
constraints, a hand-run UPDATE by an operator during an incident, or a future importer
all reach these columns without passing a Pydantic model. The constraint is what makes
"the model on a live phone line is one we priced" a property of the database rather than
of every writer remembering.

THE ALLOW-LIST IS COPIED, FROZEN, HERE — and that is the alembic discipline rather than
an oversight. Importing `calevate_shared.engine.AZURE_OPENAI_MODELS` would make THIS
revision replay differently after a future model is added, so the values are written out
as they read today and `tests/llm_model_selection_test.py` asserts the frozen copy still
equals the live allow-list. The drift is therefore caught while it is still free: adding
a model to the Literal fails that test until a new revision widens the constraint, which
is exactly the "not a one-line change" the Literal's own comment already warns about.

`agents.llm_model` IS SAFE TO CONSTRAIN because it has never had a writer: every row in
every environment holds NULL. The `ADD CONSTRAINT` validates existing rows, so a database
that somehow holds a value we do not ship refuses this migration by name rather than
letting the value through — the loud direction, and the recoverable one.

NO RLS CHANGE, VERIFIED RATHER THAN ASSUMED
-------------------------------------------
`organizations` carries its FORCEd policy (matching on `id`, not `tenant_id` — it is the
tenant root) and `agents` carries its own; a column added to a table under RLS inherits
the policy, because Postgres has no per-column RLS. "Inherits" is the kind of sentence
that stays true until a neighbouring `ALTER TABLE` turns FORCE off, so `_assert_rls_
still_forced` re-reads `pg_class` after the DDL rather than trusting it, and
`tests/llm_model_selection_test.py` proves the cross-tenant read returns zero rows
through the new column specifically (hard rule 1).

REVERSIBLE. The downgrade drops the two constraints and the one column. Nothing else
depends on them: `agents.llm_model` predates this revision and is left exactly as it was,
so a rollback leaves a working agent rather than one with no model at all.
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d2f10c93ae"
down_revision = "c9f4a2e17b83"
branch_labels = None
depends_on = None

CK_ORG_MODEL = "ck_organizations_default_llm_model_allowed"
CK_AGENT_MODEL = "ck_agents_llm_model_allowed"

# FROZEN COPY of `calevate_shared.engine.AZURE_OPENAI_MODELS` as it read the day this
# revision was written. See the docstring for why it is a copy and what keeps it honest.
ALLOWED_LLM_MODELS = ("gpt-4.1-mini", "gpt-4o-mini")

# Rendered from the tuple above so the two cannot disagree, and sorted at the source so
# the constraint text is byte-stable across interpreter runs — an unordered set here
# would make `alembic revision --autogenerate` offer a spurious diff on every invocation.
_IN_LIST = ", ".join(f"'{model}'" for model in sorted(ALLOWED_LLM_MODELS))


def upgrade() -> None:
    op.add_column("organizations", sa.Column("default_llm_model", sa.Text(), nullable=True))
    # Spelled with `op.execute` rather than `op.create_check_constraint`, which applies
    # this project's naming convention to a name that already carries it and produces
    # `ck_organizations_ck_organizations_…` (measured on a real database — see
    # `c4f18a6b90e2`).
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {CK_ORG_MODEL} "
        f"CHECK (default_llm_model IS NULL OR default_llm_model IN ({_IN_LIST}))"
    )
    op.execute(
        f"ALTER TABLE agents ADD CONSTRAINT {CK_AGENT_MODEL} "
        f"CHECK (llm_model IS NULL OR llm_model IN ({_IN_LIST}))"
    )
    _assert_rls_still_forced()


def _assert_rls_still_forced() -> None:
    """Hard rule 1, re-read from the catalog instead of asserted in the docstring.

    `check_rls_coverage` asks this of the whole schema on every `make guardrails`; asking
    it HERE is what stops a release shipping a client's model choice onto a table whose
    protection somebody turned off in a neighbouring revision.
    """
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


def downgrade() -> None:
    op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {CK_AGENT_MODEL}")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {CK_ORG_MODEL}")
    op.drop_column("organizations", "default_llm_model")
