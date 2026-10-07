"""agents choose a voice and a model from the engine's own catalogue; facts as knowledge (D-678)

Revision ID: b7e2d94f1a30
Revises: f3a8c61d2e57
Create Date: 2026-10-06 18:00:00.000000

Two nullable columns on `agents`:

* `engine_voice_id` — an id from the selected engine's own voice list (ThinnestAI's
  `GET /voices`, sent as the agent's `voice.voice`;
  `thinnest-findings/mirror/pages/api-reference/voices-and-models.md:9-10`, `agents.md:156`).
* `engine_model_id` — an id from its model list (`GET /models`, sent as `model`;
  `agents.md:105-110`).

NULL is the default and means "the engine's own default", which is what every agent was
published with before this revision. They are separate from `tts_voice` / `llm_model`
because those name OUR catalogue on engines where we run the speech and the model; the two
vocabularies never share a value, and one column holding either would let a Cartesia voice
id reach ThinnestAI or the reverse.

The CHECKs are a floor (length and no whitespace), not the offer: which ids may be chosen
is a live read of the engine's catalogue and of the attested per-tier rates, decided at
publish by `agents/engine_choice.py`. RLS is untouched: `agents` already carries FORCEd
tenant isolation and new columns inherit it.

On `engine_agent_routes`, `facts_kb_ref` and `facts_digest`: the knowledge document that
holds the agent's business facts on an engine that keeps them out of the prompt
(`agents/engine_facts.py`), per VENDOR AGENT because an experiment arm is its own vendor
agent with its own copy. Both or neither; the digest is what makes a republish with the same
facts a no-op at the vendor.

Downgrade drops all four. A choice is lost and the agent falls back to the engine default on
its next publish; a facts document stays at the vendor with nothing naming it until the
agent is deleted there, so the downgrade refuses while any route still records one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "b7e2d94f1a30"
down_revision: str | None = "f3a8c61d2e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("engine_voice_id", "engine_model_id")
_FACTS = ("facts_kb_ref", "facts_digest")


def _shape(column: str) -> str:
    return f"{column} IS NULL OR {column} ~ '^[^[:space:]]{{1,128}}$'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for column in _COLUMNS:
        op.add_column("agents", sa.Column(column, sa.Text(), nullable=True))
        op.create_check_constraint(op.f(f"ck_agents_{column}_shape"), "agents", _shape(column))
    for column in _FACTS:
        op.add_column("engine_agent_routes", sa.Column(column, sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_engine_agent_routes_facts_whole"),
        "engine_agent_routes",
        "(facts_kb_ref IS NULL) = (facts_digest IS NULL)",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _refuse_recorded_facts()
    op.drop_constraint(
        op.f("ck_engine_agent_routes_facts_whole"), "engine_agent_routes", type_="check"
    )
    for column in reversed(_FACTS):
        op.drop_column("engine_agent_routes", column)
    for column in reversed(_COLUMNS):
        op.drop_constraint(op.f(f"ck_agents_{column}_shape"), "agents", type_="check")
        op.drop_column("agents", column)


def _refuse_recorded_facts() -> None:
    """Refuse BEFORE anything is dropped: the column is the only record of which vendor
    document holds a client's facts, and without it nothing can remove that document."""
    if probe_skipped_offline(
        "offline `--sql`: the pre-flight that refuses to drop recorded ThinnestAI facts\n"
        "documents was NOT run. Check first with:\n"
        "SELECT count(*) FROM engine_agent_routes WHERE facts_kb_ref IS NOT NULL;"
    ):
        return
    recorded = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM engine_agent_routes WHERE facts_kb_ref IS NOT NULL"))
        .scalar_one()
    )
    if recorded:
        raise RuntimeError(
            f"{recorded} route row(s) record a business-facts document at the voice "
            "platform. Remove those documents (republish the agents on another engine) "
            "first, then re-run this downgrade."
        )
