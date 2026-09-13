"""agent_config_versions + agent_config_attestations — the witness that replaces a vendor

Revision ID: d4e1c7a09b35
Revises: c7a4f9e15b03
Create Date: 2026-09-13 12:10:00.000000

WHAT THIS IS FOR
----------------
`docs/PIPECAT-MIGRATION.md` §1.1, step 2 of its §6 sequencing. `AgentHosting` gains
`owned_runtime` — we hold the agent record AND run the program — and the moment the vendor
leaves, the read-back that `get_agent` exists for loses its independent witness. Under a
rented engine we ask the vendor what it is running and it may disagree with us; with no
vendor, `get_agent` would read our own tables and hand back the configuration
`create_agent` had just written. That is *"it agrees with the caller by construction"*
(`packages/shared/src/calevate_shared/engine.py`, `get_agent`'s own docstring), which
turns OPERATIONS §2 gate 2's APPLIED-not-merely-ACCEPTED property from false into
unfalsifiable — a green gate that measured nothing, with nothing saying so.

These two tables are the replacement witness, and the whole design is that they are
written by two different things:

* `agent_config_versions` — what the CONTROL PLANE intends, minted by `create_agent` /
  `publish_agent`. Immutable and content-addressed: the row IS its two digests.
* `agent_config_attestations` — what a RUNNING WORKER actually loaded, recomputed by that
  process from its own memory at session start.

`get_agent` on an `owned_runtime` engine returns the latest attestation, never the config
version. The two can disagree — a worker on a stale deploy, a version published after the
session started, a prompt truncated on the way into the process — and that disagreement is
exactly what gate 2, the drift sweep and `agents/verification.py` exist to detect. The
property survives the vendor's departure; only the witness changes.

WHAT IS IN EACH DIGEST, AND WHAT IS DELIBERATELY OUT
----------------------------------------------------
Stated here as well as in `apps/api/agents/config_versions.py` because a hash whose inputs
are ambiguous is a hash that produces false mismatches, and a false mismatch on this table
is an incident that is not happening.

`prompt_sha256` = sha256 of `compose_engine_prompt(cfg)` as UTF-8 bytes, with
**`caller_memory` omitted**. That call is the ONE composer (hard rule 5), so the digest
covers the platform-rules preamble, the voice-style block, the composed opening line, the
client's script and `TRUTHFUL_ANSWER_DIRECTIVE` — everything the model is handed.

OUT, each because the worker CANNOT reproduce it byte-for-byte from a config version:

* **`caller_memory`** — per-call facts about one person, passed to the composer per
  session. In the digest it would make every attestation a mismatch.
* **`AgentConfig.handoff`** — resolved from the roster AND A CLOCK at publish time
  (`agents/handoff.on_duty`), so its value at 09:00 and at 21:00 differ for an unchanged
  agent. It is not in the composed prompt at all; it reaches the engine as a tool.
* **Dial-time `{{ }}` merge values** — substituted into the composed prompt per contact.

`model_config_sha256` = sha256 of the resolved `ModelConfig`, serialised as canonical JSON
(sorted keys, no whitespace, `mode="json"`). Every leg is in it: STT, LLM (model, provider,
base URL, traps) and TTS (provider, model, voice, label). It is NOT recomputed by the
worker and there is no attestation column for it — see below.

WHY THE ATTESTATION CARRIES ONLY THE PROMPT DIGEST
---------------------------------------------------
§1.1 specifies three columns and this migration adds no fourth. A model-config digest the
worker recomputed would be a claim about strings it holds in configuration, not about what
it did with them; the honest witness for the model leg is the metering (§1.3) and the
per-turn token usage, which say which model actually answered. What the prompt digest can
prove — that the words in the process are the words we published — is exactly the property
hard rule 5 needs and the one a vendor read-back used to provide.

CONTENT-ADDRESSED, SO RE-PUBLISHING IDENTICAL CONTENT REUSES THE ROW
---------------------------------------------------------------------
A UNIQUE constraint on (agent_id, prompt_sha256, model_config_sha256) — declared from the
columns and left to the naming convention, whose spelling of it exceeds PostgreSQL's
63-character identifier limit and is therefore truncated with SQLAlchemy's deterministic
hash suffix. Nothing quotes that name: `config_versions.mint_config_version` writes
`ON CONFLICT (agent_id, prompt_sha256, model_config_sha256)`, which names the columns.
A publish that changes nothing mints nothing, so an attestation quoting a version id
remains resolvable to exactly one content, and the table does not grow by one row per
press of a button. `id` is still the key an attestation references, because the worker
loads a VERSION rather than a hash pair.

APPEND-ONLY (HARD RULE 4)
-------------------------
Both tables are in `apps/api/db/registry.APPEND_ONLY_TABLES` and carry the shared
`calevate_forbid_mutation` / `calevate_forbid_truncate` triggers with NO carve-out,
`ENABLE ALWAYS` so `session_replication_role = replica` cannot switch them off. The reason
is the same one `platform_model_prices` gives, pointed at evidence rather than money: an
UPDATE here would let today's belief rewrite what a worker attested last month, which is
the one fact these rows exist to fix in place. A correction is a new attestation at a
later `observed_at`; a config change is a new version.

RLS (HARD RULE 1)
-----------------
Both are tenant-scoped — they name one client's agent and the digest of that client's
script — so both ship with `tenant_id`, ENABLE + FORCE and the DATA-MODEL §1
`tenant_isolation` policy, created HERE in the same migration as the tables. The
cross-tenant zero-rows proof is `tests/agent_config_versions_rls_test.py`.

NO SUBJECT-LINKED COLUMN, DELIBERATELY. Neither table carries a phone number, a
`subject_ref`, a FK to `calls` or `leads`, or any free text. An attestation is about an
AGENT, not about a caller, so a DPDP §12 erasure has nothing to reach here and
`scripts/check_erasure_coverage.py` has nothing to find — which is what keeps an
append-only table lawful to hold indefinitely.

LOCKING
-------
Two `CREATE TABLE`s on tables nothing references yet, their indexes, and four triggers on
the new tables. The foreign keys point OUT, at `organizations`, `agents` and (for the
attestation) the version table created in this same migration — and a new FK takes a SHARE
ROW EXCLUSIVE on the referenced table for as long as it validates, so the two pointing at
existing hot tables are added NOT VALID and VALIDATEd separately, exactly as
`c7a4f9e15b03` does. `lock_timeout` is set so a migration that cannot get its lock fails
fast instead of queueing in front of every writer. Both trigger functions already exist
(05bba2f3c19c, a2e9f31c605d).

DOWNGRADE
---------
Drops triggers, policies, indexes and both tables, and is exercised (upgrade → downgrade →
upgrade) by `tests/migration_reversibility_test.py` rather than assumed. It loses the
attestation history, which is unavoidable — this is the only place it lives — and it
removes the witness, so a revert while an `owned_runtime` engine is selected leaves
`get_agent` with nothing to answer from. That is a deployment decision, not a rollback
detail. Nothing is dropped that anything still writes: this migration only adds (hard rule
8's two-step deprecation has no work to do in this direction).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e1c7a09b35"
down_revision: str | None = "c7a4f9e15b03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("agent_config_versions", "agent_config_attestations")

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
# when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON {table} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

# A sha256 hexdigest as `hashlib.sha256(...).hexdigest()` spells it, and nothing else.
# Checked in the database rather than only in Python because these columns are COMPARED —
# an attestation is judged by `=` against a config version — and one side stored uppercase
# or truncated would read as a drift incident forever, on an agent that is fine.
_HEX64 = "{column} ~ '^[0-9a-f]{{64}}$'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "agent_config_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        # What the model is handed, digested. See the docstring for what is in it.
        sa.Column("prompt_sha256", sa.Text(), nullable=False),
        # The resolved `ModelConfig` as canonical JSON, digested. Recorded so a drift in
        # WHICH MODEL answered is visible beside a drift in WHAT IT WAS TOLD; the two fail
        # for different reasons and an operator has to be able to tell them apart.
        sa.Column("model_config_sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _HEX64.format(column="prompt_sha256"),
            name=op.f("ck_agent_config_versions_prompt_sha256_hex"),
        ),
        sa.CheckConstraint(
            _HEX64.format(column="model_config_sha256"),
            name=op.f("ck_agent_config_versions_model_config_sha256_hex"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_config_versions")),
        # CONTENT-ADDRESSED: the same content on the same agent is the same version.
        sa.UniqueConstraint(
            "agent_id",
            "prompt_sha256",
            "model_config_sha256",
            name=op.f("uq_agent_config_versions_agent_id_prompt_sha256_model_config_sha256"),
        ),
    )
    op.create_index(
        op.f("ix_agent_config_versions_tenant_id"),
        "agent_config_versions",
        ["tenant_id"],
        unique=False,
    )
    # No separate `(agent_id)` index: the unique constraint above leads with `agent_id`,
    # so every lookup by agent already has one (`prompt_versions` makes the same call and
    # migration b9e5d2c74a18 dropped the redundant one it used to carry).

    op.create_table(
        "agent_config_attestations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # Denormalised from the version row it references, and deliberately: the read this
        # table exists for is "what did the worker last attest FOR THIS AGENT", on the
        # `get_agent` path. Reaching it through the version would put a join on that read
        # and an index on the join key, to recover a column the writer already holds.
        sa.Column("agent_id", sa.UUID(), nullable=False),
        # WHAT THE PROCESS ACTUALLY LOADED — the whole point of the row.
        sa.Column("agent_config_version_id", sa.UUID(), nullable=False),
        # RECOMPUTED BY THE WORKER from what is in its memory, never copied from the
        # version row. A copy would make this table agree with the control plane by
        # construction, which is the defect the whole arrangement exists to remove.
        sa.Column("prompt_sha256", sa.Text(), nullable=False),
        # WHEN THE WORKER SAW IT, as the worker's own clock reports. Separate from
        # `created_at` for `legal_acceptances.accepted_at`'s reason: one is the act, the
        # other is when we wrote it down, and a worker that attests and then waits on a
        # busy database must not have that delay read as a late load.
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _HEX64.format(column="prompt_sha256"),
            name=op.f("ck_agent_config_attestations_prompt_sha256_hex"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_config_attestations")),
    )
    op.create_index(
        op.f("ix_agent_config_attestations_tenant_id"),
        "agent_config_attestations",
        ["tenant_id"],
        unique=False,
    )
    # EXACTLY THE READ `get_agent` RUNS — newest attestation for one agent. `observed_at
    # DESC, id DESC` for `ix_legal_acceptances_current`'s reason: two attestations in the
    # same instant (two workers, one agent) must still resolve deterministically rather
    # than by planner whim, and `id` is uuid_v7 so it breaks the tie by write order.
    op.execute(
        "CREATE INDEX ix_agent_config_attestations_latest ON agent_config_attestations "
        "(agent_id, observed_at DESC, id DESC)"
    )

    # NOT VALID first, VALIDATE second — see the LOCKING note. `organizations` and
    # `agents` are read on every request and neither may have its writes blocked by a scan
    # of a table that is empty at this instant anyway.
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_tenant_id_organizations "
            "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_agent_id_agents "
            "FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE RESTRICT NOT VALID"
        )
    # This one points at a table created moments ago in this same transaction, so it is
    # validated inline: there is nothing to block and nobody to block it.
    #
    # NAMED SHORT ON PURPOSE. The `fk_%(table_name)s_%(column_0_name)s_%(referred_table_
    # name)s` convention would spell this 74 characters, and PostgreSQL truncates an
    # identifier to 63 SILENTLY — so the constraint in the database would not be the name
    # written here, and a later `DROP CONSTRAINT` naming the convention's spelling would
    # fail on a name nobody could see was wrong.
    op.execute(
        "ALTER TABLE agent_config_attestations ADD CONSTRAINT "
        "fk_agent_config_attestations_version_id "
        "FOREIGN KEY (agent_config_version_id) REFERENCES agent_config_versions (id) "
        "ON DELETE RESTRICT"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_tenant_id_organizations")
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_agent_id_agents")

    for table in _TABLES:
        # Hard rule 1, in the same migration as the tables it protects.
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_POLICY.format(table=table))
        # Hard rule 4, likewise. `ENABLE ALWAYS` so a `SET session_replication_role =
        # replica` cannot switch the guarantee off.
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_forbid_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_append_only")
        op.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {table}_forbid_truncate")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_forbid_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute("DROP INDEX IF EXISTS ix_agent_config_attestations_latest")
    op.drop_index(
        op.f("ix_agent_config_attestations_tenant_id"),
        table_name="agent_config_attestations",
    )
    op.drop_index(
        op.f("ix_agent_config_versions_tenant_id"),
        table_name="agent_config_versions",
    )
    # The attestation table first: it holds the foreign key.
    op.drop_table("agent_config_attestations")
    op.drop_table("agent_config_versions")
