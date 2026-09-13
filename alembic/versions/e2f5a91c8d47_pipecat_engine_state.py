"""pipecat: the engine's own agent record, its KB objects, and a loadable config version

Revision ID: e2f5a91c8d47
Revises: d4e1c7a09b35
Create Date: 2026-09-13 16:40:00.000000

WHAT THIS IS FOR
----------------
`docs/PIPECAT-MIGRATION.md` §6 step 3: `apps/api/engine/pipecat.py`, the adapter for an
engine we RUN rather than rent. Under `agent_hosting="owned_runtime"` there is no vendor
holding an agent object, so the thing a vendor would hold has to be somewhere — and
"somewhere" is here, in two tables the adapter owns and nothing else writes.

It also finishes `d4e1c7a09b35` in one respect that migration's own design left open, and
that is the first change below.

1. `agent_config_versions` BECOMES LOADABLE
-------------------------------------------
`d4e1c7a09b35` made a version row two digests. `docs/PIPECAT-MIGRATION.md` §2 says the
worker *"loads a config VERSION"* — and a row that holds only hashes of content it does
not store is a row nothing can load: the worker would have had to go and find the content
somewhere else, recompose it, and hope it hashed the same, which is the false-mismatch
failure `d4e1c7a09b35` spends a whole section avoiding.

So the version now carries THE CONTENT THE TWO DIGESTS ARE TAKEN OVER, and nothing else:

* `composed_prompt` — exactly the bytes `prompt_sha256` digests, i.e.
  `compose_engine_prompt(cfg)`.
* `opening_line`    — the greeting, which the composer prepends and which
  `AgentSnapshot.greeting` is read from. It is INSIDE `composed_prompt` already, so it
  adds no fact; it is stored separately because the snapshot has a separate field for it
  and recovering it by string surgery on the prompt is the `speech_for_voice_id` mistake.
* `model_config`    — exactly the object `model_config_sha256` digests, as the same
  canonical JSON.

**THE COLUMNS ARE A FUNCTION OF THE DIGESTED INPUTS, WHICH IS WHAT MAKES THEM SAFE ON AN
APPEND-ONLY, CONTENT-ADDRESSED TABLE.** `mint_config_version` writes
`ON CONFLICT (agent_id, prompt_sha256, model_config_sha256) DO NOTHING`, so a second
publish of identical content keeps the FIRST row. That is only correct while every stored
column is determined by the conflict key — otherwise the kept row would quietly describe
the earlier publish. Storing the whole `AgentConfig` here would break exactly that: two
publishes can share both digests and differ in `handoff` (resolved from the roster AND a
clock, which is why `d4e1c7a09b35` excluded it from the digest in the first place), and
the read-back would then report a destination nobody published.

No PII, no subject-linked column, no FK to `calls` or `leads` — `d4e1c7a09b35`'s erasure
argument is unchanged. What is added is the client's own SCRIPT, which the mutable
`agents.system_prompt` already holds; this is the immutable copy that makes "which words
was this worker running" answerable at all, and it is the same class of data.

2. `pipecat_agents` — WHAT A VENDOR WOULD HOLD
-----------------------------------------------
One row per agent this engine holds: the handle, the agent it names, its display name, the
config version last published to it and the resolved `AgentConfig` it was published from. `create_agent`/`update_agent` upsert it,
`delete_agent` deletes it, `get_agent` refuses on a ref with no row (the Protocol's
"an unknown ref must RAISE", which is unimplementable without somewhere for the ref to
be absent FROM).

NOT append-only, deliberately: `update_agent` is a full replacement by contract and this
row is engine STATE, not a ledger entry. The ledger is `agent_config_versions`, which is
append-only and is where the history lives.

3. `pipecat_kb_objects` — THE ACCOUNT'S KNOWLEDGE OBJECTS
----------------------------------------------------------
`VoiceEngine.list_account_kb` asks *"what is on this engine account that nobody claims?"*
— the question `list_kb` structurally cannot answer, because it reads the AGENT. Under a
rented engine the answer comes from the vendor's account listing. Here the account is
ours, so the objects need a table of their own that OUTLIVES the agent that referenced
them: the conformance clause deletes an agent holding a document and then requires the
account listing to still answer.

**IT CARRIES THE GLOBAL-READ EXEMPTION, ON `engine_kb_routes`' EXACT PATTERN AND FOR ITS
EXACT REASON** (migration `f1c9e0a73b46`, D-519): "which objects on this account does no
tenant of ours claim" cannot be asked from a tenant session at all, and an account listing
that answered EMPTY under RLS would be a positive claim that the account is clean — the
one answer `list_account_kb` may never give by accident. The read is
`pipecat_kb_objects_global_read` (FOR SELECT USING (true)); every WRITE verb stays under
a FORCEd `tenant_isolation` policy, so one client's session can neither delete nor
re-tenant another's object. The row holds four opaque ids, a state word and a timestamp:
no source name, no chunk, no prompt, no PII. That is what lets `kb_sources` and
`kb_documents`, which hold the client's actual content, stay FORCE-RLS'd with no
exemption of their own.

4. `ck_agents_engine_enum` ADMITS `pipecat`
--------------------------------------------
`agents.engine`'s CHECK is rendered from `apps/api/agents/models.py::ENGINES`, which is
`sorted(SELECTABLE_ENGINES)`. `pipecat` joins `config.EngineName` in the same change, and
without this widening the first thing a client does on such a deployment — EXIST — fails
with an IntegrityError naming a constraint whose text disagrees with `ENGINE=`. That is
not hypothetical: it is exactly what `d7b1c48a2e93` had to repair for `cartesia`, and the
predicate is spelled out here rather than interpolated from the constant for that
migration's reason — a migration is a historical record of what the schema BECAME.

LOCKING
-------
Three `ALTER TABLE ... ADD COLUMN` with a non-volatile default (Postgres 11+ rewrites
nothing), two `CREATE TABLE`s on tables nothing references yet, and one CHECK drop/add on
`agents` whose new predicate is strictly WEAKER, so it validates nothing beyond the read
Postgres performs anyway. `lock_timeout` is set so a migration that cannot get its lock
fails fast instead of queueing in front of every writer. The FKs point OUT at
`organizations`, `agents` and `agent_config_versions`; the two at existing hot tables are
added NOT VALID and VALIDATEd separately, as `d4e1c7a09b35` and `c7a4f9e15b03` do.

DOWNGRADE
---------
Drops the two tables, the three columns and re-narrows the CHECK — and the CHECK half
REFUSES rather than stranding rows, `d7b1c48a2e93`'s pattern: narrowing back while an
`agents` row carries `engine = 'pipecat'` would require deleting client agents, which is
destruction rather than reversal (hard rule 8). Losing the three columns loses the ability
to load a version, which is a deployment decision and not a rollback detail: nothing else
reads them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from apps.api.db.migration_offline import probe_skipped_offline
from sqlalchemy.dialects import postgresql

revision: str = "e2f5a91c8d47"
down_revision: str | None = "d4e1c7a09b35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("pipecat_agents", "pipecat_kb_objects")

# DATA-MODEL §1 verbatim, as `d4e1c7a09b35` spells it. NULLIF: a pooled connection that
# once had the GUC returns '' when unset, and ''::uuid ERRORs instead of failing closed to
# zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON {table} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

_ENGINE_CONSTRAINT = "ck_agents_engine_enum"
_WIDENED = "engine IN ('bolna', 'cartesia', 'fake', 'pipecat')"
_ORIGINAL = "engine IN ('bolna', 'cartesia', 'fake')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    # --- 1. a config version the worker can actually load --------------------
    #
    # The defaults exist for the ADD's sake on a table that may already hold rows, and are
    # DROPPED immediately after: a column with a standing default is a column a writer can
    # forget and nothing reports, and every one of these three is content a version is
    # worthless without.
    op.add_column(
        "agent_config_versions",
        sa.Column("composed_prompt", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_config_versions",
        sa.Column("opening_line", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_config_versions",
        sa.Column(
            "model_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    for column in ("composed_prompt", "opening_line", "model_config"):
        op.alter_column("agent_config_versions", column, server_default=None)
    # A version whose prompt is empty is a version that cannot carry the truthful-answer
    # floor, and `mint_config_version` refuses to write one — checked in the database as
    # well because this column is the WORKER's input, and the one defect that cannot be
    # repaired afterwards is an immutable row saying the agent runs nothing.
    #
    # **NOT VALID, AND IT IS THE OPPOSITE OF THE USUAL REASON.** The normal use is to skip
    # a long validation scan on a hot table; here it is because rows minted between
    # `d4e1c7a09b35` and this migration carry the empty default and CANNOT BE BACKFILLED —
    # the content they digest was never stored, and the table is append-only (hard rule 4)
    # so an UPDATE that invented one would fire `calevate_forbid_mutation` and would be a
    # guess written into the evidence. NOT VALID still enforces the constraint on every
    # INSERT and UPDATE from here on, which is the whole population that matters: an
    # attestation quoting one of those legacy rows resolves to no content, which
    # `PipecatEngine.get_agent` reports as "could not look" rather than as agreement.
    op.execute(
        "ALTER TABLE agent_config_versions ADD CONSTRAINT "
        "ck_agent_config_versions_composed_prompt_present "
        "CHECK (length(composed_prompt) > 0) NOT VALID"
    )

    # --- 2. the engine's own agent record ------------------------------------
    op.create_table(
        "pipecat_agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        # The handle the adapter minted and `agents.engine_agent_ref` stores. UNIQUE
        # because it is the join key every read comes in on.
        sa.Column("engine_agent_ref", sa.Text(), nullable=False),
        # What the console calls this agent. Read back as `AgentSnapshot.name`, which has
        # no `_readable` tri-state because it carries no compliance claim.
        sa.Column("name", sa.Text(), nullable=False),
        # What was last PUBLISHED to this agent. The worker attests a version of its own
        # choosing and the two can disagree — that disagreement is the whole point of
        # `d4e1c7a09b35` — so this is the control plane's intent, never the read-back.
        sa.Column("agent_config_version_id", sa.UUID(), nullable=False),
        # THE WHOLE `AgentConfig` AS PUBLISHED, which is what a vendor's agent object is.
        # It is here and NOT on `agent_config_versions` for one reason: that table is
        # content-addressed on two digests and writes `ON CONFLICT DO NOTHING`, so a column
        # not determined by those digests would make the kept row describe the earlier
        # publish (see §1 above). `handoff` is exactly such a column — resolved from the
        # roster AND a clock. This row has no conflict key to be wrong about: it is
        # replaced whole on every publish, which is what `update_agent` means.
        #
        # It is never the read-back. `get_agent` answers from the worker's attestation;
        # this is what `override_call_script` rewrites two fields OF, and what a future
        # reader needs to know what the engine was told.
        sa.Column(
            "resolved_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipecat_agents")),
        sa.UniqueConstraint("engine_agent_ref", name=op.f("uq_pipecat_agents_engine_agent_ref")),
        # One engine record per agent: `create_agent` twice on one agent must return one
        # ref, which is the conformance suite's stability clause stated as a constraint.
        sa.UniqueConstraint("agent_id", name=op.f("uq_pipecat_agents_agent_id")),
        sa.ForeignKeyConstraint(
            ["agent_config_version_id"],
            ["agent_config_versions.id"],
            name=op.f("fk_pipecat_agents_agent_config_version_id_agent_config_versions"),
        ),
    )
    op.create_index(
        op.f("ix_pipecat_agents_tenant_id"), "pipecat_agents", ["tenant_id"], unique=False
    )

    # --- 3. the account's knowledge objects ----------------------------------
    op.create_table(
        "pipecat_kb_objects",
        # The ENGINE's handle for one attached source — `EngineKBRef`. Primary key for
        # `engine_kb_routes`' reason: two objects sharing a handle is two rows claiming one
        # deletable thing.
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # WHICH AGENT REFERENCES IT, or NULL once nothing does. `list_kb` reads this;
        # `list_account_kb` deliberately does not, which is the difference between the two
        # methods and the reason this table exists at all.
        sa.Column("engine_agent_ref", sa.Text(), nullable=True),
        # `KBSourceRef.kb_id` as handed to `attach_kb`. TEXT rather than a FK to
        # `kb_sources`: it is the CLAIM the object carries about itself
        # (`AccountKBObject.claimed_source_id` is documented as a claim, not a fact), and a
        # FK would make an object un-recordable precisely when its source row is the thing
        # that went missing — the state the orphan report exists to find.
        sa.Column("kb_id", sa.Text(), nullable=False),
        # `AccountKBState`. Written `ready` by this adapter because the store is ours and
        # an attach either committed or did not; the column exists so a future ingest that
        # is genuinely asynchronous has somewhere to say so.
        sa.Column("state", sa.Text(), nullable=False, server_default="ready"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('ready', 'pending', 'failed', 'unknown')",
            name=op.f("ck_pipecat_kb_objects_state_enum"),
        ),
        sa.PrimaryKeyConstraint("handle", name=op.f("pk_pipecat_kb_objects")),
    )
    op.create_index(
        op.f("ix_pipecat_kb_objects_tenant_id"), "pipecat_kb_objects", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_pipecat_kb_objects_engine_agent_ref"),
        "pipecat_kb_objects",
        ["engine_agent_ref"],
        unique=False,
    )

    # --- RLS on both (hard rule 1) -------------------------------------------
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_POLICY.format(table=table))
    # THE ONE EXEMPTION, AND IT IS FOR READS ONLY. See the module docstring §3: the account
    # listing's question is inherently cross-tenant, and the policy above covers every
    # write verb, so a tenant session still cannot insert, re-tenant or delete another
    # client's object.
    op.execute("CREATE POLICY pipecat_kb_objects_global_read ON pipecat_kb_objects FOR SELECT USING (true)")

    # --- the outward foreign keys, NOT VALID then validated -------------------
    for table, column, target in (
        ("pipecat_agents", "tenant_id", "organizations"),
        ("pipecat_agents", "agent_id", "agents"),
        ("pipecat_kb_objects", "tenant_id", "organizations"),
    ):
        name = f"fk_{table}_{column}_{target}"
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({column}) REFERENCES {target} (id) NOT VALID"
        )
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")

    # --- 4. the engine enum ---------------------------------------------------
    op.drop_constraint(op.f(_ENGINE_CONSTRAINT), "agents", type_="check")
    op.create_check_constraint(op.f(_ENGINE_CONSTRAINT), "agents", _WIDENED)


def downgrade() -> None:
    _refuse_stranded_engines()
    op.drop_constraint(op.f(_ENGINE_CONSTRAINT), "agents", type_="check")
    op.create_check_constraint(op.f(_ENGINE_CONSTRAINT), "agents", _ORIGINAL)

    op.execute("DROP POLICY IF EXISTS pipecat_kb_objects_global_read ON pipecat_kb_objects")
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index(op.f("ix_pipecat_kb_objects_engine_agent_ref"), table_name="pipecat_kb_objects")
    op.drop_index(op.f("ix_pipecat_kb_objects_tenant_id"), table_name="pipecat_kb_objects")
    op.drop_table("pipecat_kb_objects")
    op.drop_index(op.f("ix_pipecat_agents_tenant_id"), table_name="pipecat_agents")
    op.drop_table("pipecat_agents")

    op.drop_constraint(
        op.f("ck_agent_config_versions_composed_prompt_present"),
        "agent_config_versions",
        type_="check",
    )
    for column in ("model_config", "opening_line", "composed_prompt"):
        op.drop_column("agent_config_versions", column)


def _refuse_stranded_engines() -> None:
    """Count first, so a refused downgrade leaves the constraint intact (d7b1c48a2e93).

    OFFLINE (`--sql`): skipped, not refused. The count decides nothing about WHICH SQL is
    emitted — it exists to fail with a sentence instead of a constraint violation. The
    emitted script still cannot strand anything: it runs inside one transaction, the
    narrower CHECK re-validates every row on the way in, and a stranded engine aborts the
    script with the table exactly as it was.
    """
    if probe_skipped_offline(
        "offline `--sql`: the pre-flight that refuses to narrow ck_agents_engine_enum while\n"
        "agents carry engine='pipecat' was NOT run — there is no connection to count them.\n"
        "The ADD CONSTRAINT below re-validates the rows, so the transaction aborts rather\n"
        "than leaving the table unconstrained. Count them first with: SELECT count(*) FROM\n"
        "agents WHERE engine = 'pipecat';"
    ):
        return
    stranded = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM agents WHERE engine = 'pipecat'"))
        .scalar_one()
    )
    if stranded:
        raise RuntimeError(
            f"{stranded} agent row(s) carry engine='pipecat', which the pre-{revision} "
            "CHECK forbids. Downgrading would either reject or require deleting client "
            "agents. Repoint those agents at a permitted engine first."
        )
