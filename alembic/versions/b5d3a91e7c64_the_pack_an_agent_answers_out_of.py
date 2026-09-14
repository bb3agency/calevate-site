"""the pack an agent answers out of: agents.knowledge_pack_sha256

Revision ID: b5d3a91e7c64
Revises: e2f5a91c8d47
Create Date: 2026-09-14 09:10:00.000000

WHAT THIS IS FOR
----------------
`docs/PIPECAT-MIGRATION.md` §6 step 12: `kb/pack.py::publish_pack` gets a caller on the
publish path, and the id it returns has to land somewhere the call path can read. This is
that somewhere — one nullable column on `agents` holding the `content_sha256` of the pack
this agent's LIVE published knowledge was last frozen into. With `tenant_id` and
`agent_id`, which the session already knows, it is the whole object key
(`calevate_shared.knowledge_pack.pack_object_key`), which is why no URL is stored.

WHY NOT ON `agent_config_versions`, WHICH IS WHERE A DIGEST WOULD OBVIOUSLY GO
------------------------------------------------------------------------------
That table is content-addressed on `(agent_id, prompt_sha256, model_config_sha256)` and
`mint_config_version` writes `ON CONFLICT DO NOTHING`, so — in `e2f5a91c8d47`'s own words
— it is only correct while **every stored column is a function of the conflict key**. The
pack digest is emphatically not: it is a function of `kb_chunks`, and a client can change
their knowledge base without moving either digest (publishing a T1-T4 source recompiles
no T0 block, so the composed prompt is byte-identical). The second publish would then be
refused by the conflict and the KEPT row would name the OLD pack — the exact defect that
kept `handoff` off that table.

WHY NOT ON `pipecat_agents` EITHER, which is where `handoff` went. That row belongs to one
adapter and is written only by `SqlControlPlane.publish`, in its own session; the pack is
written by the KB publish path, in the client's transaction, and exists whether or not the
agent has ever been published to any engine. A pointer stored per-engine would be absent
on exactly the agent a client has finished configuring and not yet put on the phone.

So it sits beside `live_tts_voice` and `live_prompt_id` on `agents`: the small family of
columns recording what the CALL PATH will be handed, as opposed to what an operator
configured. NULL means "this agent has published no knowledge pack", which is the ordinary
day-one state and is what `SessionConfig.knowledge_pack_sha256 = None` reports.

TENANCY (hard rule 1)
---------------------
`agents` is already FORCE-RLS'd under the `tenant_isolation` policy (DATA-MODEL §1), and a
policy is a rule about ROWS, not about columns — so this column inherits it with nothing to
add. Hard rule 1's "ships WITH its policy in the same migration" binds a new tenant TABLE;
there is none here, and writing a second policy for one column would be a second answer to
a question `agents` has already answered. `tests/knowledge_pack_pointer_rls_test.py` is the
cross-tenant zero-rows proof that the inheritance is real rather than assumed.

THE CHECK
---------
`^[0-9a-f]{64}$` or NULL, `agent_config_versions.prompt_sha256`'s constraint for its exact
reason: this value is COMPARED — a worker's fetch is `key == prefix + value + '.json'` —
and a digest stored uppercase or truncated is an agent that retrieves nothing, reported by
nobody. NULL is admitted explicitly rather than by the accident that a NULL-returning CHECK
passes, because it is a real state with a meaning ("nothing published yet") and not a gap.

LOCKING
-------
One `ALTER TABLE ... ADD COLUMN` with no default (no rewrite on any supported Postgres) and
one CHECK added NOT VALID: every existing row is NULL, so the scan would prove a fact the
column's own newness already guarantees, and skipping it keeps the lock brief on a hot
table. It binds every INSERT and UPDATE from here on, which is the whole population.

DOWNGRADE
---------
Drops the constraint and the column. Nothing is stranded: the pointer is derivable again by
republishing (the pack objects themselves are immutable and stay where they are), so this
is a reversal rather than a destruction — hard rule 8 satisfied without a refusal branch.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5d3a91e7c64"
down_revision: str | None = "e2f5a91c8d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_agents_knowledge_pack_sha256_hex"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("agents", sa.Column("knowledge_pack_sha256", sa.Text(), nullable=True))
    op.execute(
        f"ALTER TABLE agents ADD CONSTRAINT {_CONSTRAINT} CHECK ("
        "knowledge_pack_sha256 IS NULL OR knowledge_pack_sha256 ~ '^[0-9a-f]{64}$'"
        ") NOT VALID"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.drop_column("agents", "knowledge_pack_sha256")
