"""the people who take a call from the agent, and every handover attempted

Revision ID: c4a91e60d7b3
Revises: b3f7c21ea940
Create Date: 2026-09-04 00:00:00.000000

D-533. A caller asks for a person; the agent hands the call over. Two tables, and one
column that decides whether either is ever used.

**`agent_handoff_members` REPLACES `agents.escalation_config`, IT DOES NOT SIT BESIDE
IT.** That column has held `{"contacts": [{name, phone_e164, hours}]}` since the intake
wizard shipped — an ordered list of the people who take a call, collected from every
client, blocking the intake if empty (`admin/intake.py::_blockers`,
`escalation_contact_missing`) — and read by NOTHING. It is the founder's hunt list,
already gathered and never wired to anything, which is exactly the half-wired shape
CLAUDE.md calls a defect that looks like progress. So this promotes it rather than
adding a second one, for three reasons a JSONB blob cannot meet:

* **`hours` was free text** ("after 6pm", "weekends only"). Decision 4 of the brief is
  "never transfer outside business hours", enforced server-side, and a sentence cannot
  be enforced. The new column is the same `{"mon": {"opens", "closes"}}` shape
  `agents.business_hours` already uses, so ONE reader (`agents/business_hours.py`)
  answers the question for both, and NULL means "inherit the agent's own hours" —
  which is what a small shop actually wants and what every migrated row gets.
* **A phone number inside a JSONB blob is invisible.** It is PII (hard rule 6) and it
  belongs in a column an erasure, an export and a redaction pass can see.
* **The client has to be able to edit it.** Intake is the ADMIN console's onboarding
  form; the roster changes when somebody joins, leaves or goes on holiday, and that is
  a client's screen with its own RLS, its own audit and its own ordering.

NOTHING IS LOST IN THE MOVE. The data migration copies name, phone and ORDER, and puts
the free-text hours into `note` verbatim rather than guessing at a machine window — a
guessed window is a mobile ringing at a time nobody agreed to. `escalation_config`
itself is KEPT and merely stops being written (hard rule 8's two-step: the `drop` is a
later release), so a rollback lands on rows that still say what they said.

**`handoff_attempts` IS KEYED ON THE EXECUTION, for `scheduled_callbacks`' reason and
one more.** The row is created by an unauthenticated mid-call notification whose only
stable identifier is the engine's execution id; the `calls` row may not exist yet
(D-31 makes the poller the record of truth, and the status webhook may be late or
lost). The extra reason is the engine itself: it latches after the first handover and
answers every later attempt with "Call transfer already in progress" (VERIFIED-OSS:
bolna-ai/bolna@cd2e192, bolna/agent_manager/task_manager.py:3116-3126), so ONE handover
per conversation is not our policy — it is the platform's behaviour, and a unique index
is the honest way to record a fact the engine will enforce whatever we do.

**WHY THE DESTINATION IS COPIED ONTO THE ATTEMPT ROW** rather than only referenced. The
member row is editable and deletable; the attempt is a record of a number that actually
rang, which a client may have to answer for months later. The FK is `SET NULL` for the
same reason: removing somebody from the roster must not rewrite the history of the
calls they took.

`reason` and `summary` arrive from the model's own words about a live conversation and
are stored REDACTED (`workers/redaction.redact`), never raw — the same rule every
transcript in this system follows.

RLS: `tenant_id` with the FORCEd `tenant_isolation` policy, verbatim from DATA-MODEL §1,
on both tables. Cross-tenant zero-rows test: `tests/handoff_rls_test.py`.

The data migration is DML, so both tables are bracketed `NO FORCE`/`FORCE` around it —
the pattern b7e35c2f81da established and `tests/migration_rls_bracket_test.py` reads for.
Reversible: `downgrade()` restores `escalation_config` from the members it created, then
drops both tables and the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a91e60d7b3"
down_revision: str | Sequence[str] | None = "b3f7c21ea940"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
#: when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
def _policy(table: str) -> str:
    return (
        f"CREATE POLICY tenant_isolation ON {table} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


#: What a handover can be. A CHECK rather than a comment, because four of the five are
#: renderings a client sees and a typo would produce a row no screen has a sentence for.
#:
#: * `started`    — the agent fired the handover; nothing has come back yet. Every row
#:                  begins here, written by the mid-call notification.
#: * `connected`  — somebody picked up.
#: * `unreached`  — nobody did: busy, no answer, or the leg failed. ONE spelling for
#:                  three vendor words, because this product does exactly one thing about
#:                  all three (book the caller a callback).
#: * `unknown`    — the engine reported a status we have no mapping for. Never silently
#:                  read as either of the two above.
#: * `abandoned`  — the call ended and the execution carried no handover leg at all. The
#:                  handover was announced to the caller and no second leg was ever
#:                  reported, which is the state that must not read as `started` for ever.
_OUTCOMES = "'started', 'connected', 'unreached', 'unknown', 'abandoned'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    # THE MASTER SWITCH, and FALSE is the safe silence (`caller_memory_enabled` makes the
    # identical argument). A forgotten column in an INSERT, a future importer or a restore
    # from a dump written before today must all yield an agent that hands nobody's call to
    # anybody's mobile. Turning it on is a client's deliberate act.
    op.add_column(
        "agents",
        sa.Column(
            "handoff_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    # WHEN the agent should hand over, in the client's own words, or NULL for the
    # composed default. It is a TOOL DESCRIPTION and not a prompt: nothing a client
    # writes here can withdraw the truthful-answer directive, which lives in the system
    # prompt and is appended by `compose_engine_prompt` (hard rule 5).
    op.add_column("agents", sa.Column("handoff_trigger", sa.Text(), nullable=True))

    op.create_table(
        "agent_handoff_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        # THE ORDER THE ROSTER IS TRIED IN. Zero-based, dense, unique per agent — the
        # service rewrites the whole list on every edit rather than patching one row,
        # because "move Priya above Ravi" is one intention and two UPDATEs that can half
        # apply is how two people end up at position 1.
        sa.Column("position", sa.Integer(), nullable=False),
        # What the client calls this person. Shown on their own screen; never spoken to a
        # caller and never sent to the engine.
        sa.Column("label", sa.Text(), nullable=False),
        # PII (hard rule 6): a member of the client's staff, on their personal mobile.
        sa.Column("phone_e164", sa.Text(), nullable=False),
        # WHEN THIS PERSON MAY BE RUNG. Same shape as `agents.business_hours` so ONE
        # reader answers for both; NULL means "whenever the business is open", which is
        # what a three-person shop wants and what every migrated row gets.
        sa.Column("hours", sa.dialects.postgresql.JSONB(), nullable=True),
        # Off without being deleted — somebody on holiday. Skipped by the on-duty
        # resolver and kept in position, so coming back is one toggle rather than a
        # re-ordering.
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        # The free-text hours the intake wizard collected ("after 6pm"), carried across
        # verbatim rather than guessed into a window. Also where a client writes anything
        # else about this person. Never spoken and never sent anywhere.
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"],
            name=op.f("fk_agent_handoff_members_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        # CASCADE, unlike every other FK in this migration: a roster member is a property
        # OF an agent and has no meaning without one. `scheduled_callbacks` uses RESTRICT
        # because a promise to a person outlives the agent that made it; a phone number to
        # ring on behalf of an agent nobody can call does not.
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"],
            name=op.f("fk_agent_handoff_members_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_handoff_members")),
        sa.CheckConstraint("position >= 0", name=op.f("ck_agent_handoff_members_position")),
        sa.CheckConstraint(
            "length(btrim(label)) > 0", name=op.f("ck_agent_handoff_members_label_nonempty")
        ),
        # E.164, the same expression `admin/intake.EscalationContact` validates with.
        # A CHECK as well as a Pydantic pattern for the reason every other floor in this
        # schema is doubled: a restore, an import or a hand-run UPDATE during an incident
        # does not pass through a Pydantic model, and this column is dialled.
        sa.CheckConstraint(
            r"phone_e164 ~ '^\+[1-9][0-9]{7,18}$'",
            name=op.f("ck_agent_handoff_members_phone_e164"),
        ),
    )
    op.create_index(
        op.f("ix_agent_handoff_members_tenant_id"),
        "agent_handoff_members",
        ["tenant_id"],
    )
    # THE ROSTER, IN ORDER, IN ONE INDEX SCAN — and the uniqueness that keeps the order a
    # total order. Every read of this table is "this agent's members, by position".
    op.create_index(
        "uq_agent_handoff_members_position",
        "agent_handoff_members",
        ["tenant_id", "agent_id", "position"],
        unique=True,
    )

    op.create_table(
        "handoff_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        # THE IDENTITY — see the module docstring. NOT NULL, unique per tenant.
        sa.Column("source_execution_id", sa.Text(), nullable=False),
        # The call it happened on, once the pipeline has written one. A POINTER, not the
        # identity: the row exists before it and outlives its erasure.
        sa.Column("source_call_id", sa.UUID(), nullable=True),
        # WHO was rung, and the number that actually rang. Both, deliberately — see the
        # module docstring on why the destination is copied.
        sa.Column("member_id", sa.UUID(), nullable=True),
        sa.Column("destination_e164", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        # The model's own words about a live conversation, REDACTED before they get here.
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "outcome", sa.Text(), server_default=sa.text("'started'"), nullable=False
        ),
        # The vendor's own word for the leg's ending, kept for the operator who wants to
        # know which of the three `unreached` collapses this was. Never branched on.
        sa.Column("raw_status", sa.Text(), nullable=True),
        sa.Column("leg_duration_s", sa.Integer(), nullable=True),
        # A SECOND RECORDING OF THIS CALLER EXISTS ON THE VENDOR'S SIDE. Not copied, not
        # retained under our policy, not reached by a DPDP erasure — OPERATIONS §2 gate
        # 46b. The boolean is how a human finds out, and it is why it is a column rather
        # than a log line.
        sa.Column(
            "leg_recording_present", sa.Boolean(), server_default=sa.text("false"),
            nullable=False,
        ),
        # The vendor stated a cost for this leg separately from the execution's own.
        # Whether it is already inside `total_cost` is gate 46c; until that is answered a
        # boolean is what can honestly be recorded (hard rule 7 meters neither a guess nor
        # a double).
        sa.Column(
            "leg_cost_reported", sa.Boolean(), server_default=sa.text("false"),
            nullable=False,
        ),
        # The callback booked because nobody picked up. Decision 3's second half, and the
        # ONLY failover this engine leaves available (see `HandoffSpec`).
        sa.Column("callback_id", sa.UUID(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organizations.id"],
            name=op.f("fk_handoff_attempts_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"],
            name=op.f("fk_handoff_attempts_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_call_id"], ["calls.id"],
            name=op.f("fk_handoff_attempts_source_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["agent_handoff_members.id"],
            name=op.f("fk_handoff_attempts_member_id_agent_handoff_members"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["callback_id"], ["scheduled_callbacks.id"],
            name=op.f("fk_handoff_attempts_callback_id_scheduled_callbacks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_handoff_attempts")),
        sa.CheckConstraint(f"outcome IN ({_OUTCOMES})", name=op.f("ck_handoff_attempts_outcome")),
        # A settled row names its ending, and an unsettled one does not claim to have one.
        # `scheduled_callbacks` carries the identical constraint for the identical reason.
        sa.CheckConstraint(
            "(outcome = 'started') = (settled_at IS NULL)",
            name=op.f("ck_handoff_attempts_settled"),
        ),
    )
    op.create_index(
        op.f("ix_handoff_attempts_tenant_id"), "handoff_attempts", ["tenant_id"]
    )
    # THE IDENTITY. One handover per conversation, per tenant — which is the engine's own
    # behaviour, not our policy (see the module docstring).
    op.create_index(
        "uq_handoff_attempts_execution",
        "handoff_attempts",
        ["tenant_id", "source_execution_id"],
        unique=True,
    )
    # What the client's screen lists by, and what the reconciliation sweep finds the rows
    # still waiting for an outcome with.
    op.create_index(
        "ix_handoff_attempts_open",
        "handoff_attempts",
        ["tenant_id", "started_at"],
        postgresql_where=sa.text("outcome = 'started'"),
    )

    for table in ("agent_handoff_members", "handoff_attempts"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_policy(table))

    # --- the move, and it is DML, so the policy is lifted around it -------------------
    #
    # A migration runs as the OWNER, which FORCE RLS applies to as well; without the
    # bracket this INSERT would see zero source rows and write zero destination rows, and
    # every client's escalation list would silently vanish. b7e35c2f81da established the
    # pattern; `tests/migration_rls_bracket_test.py` reads for it.
    #
    # **BOTH TABLES, AND `agents` IS THE ONE THAT IS EASY TO FORGET.** The bracket is
    # usually reasoned about as protecting the WRITE; here the SELECT is just as exposed —
    # `agents` is FORCE-RLS'd too, so an unlifted read would return zero source rows and
    # the migration would report success having moved nothing at all. That failure is
    # silent in both directions, which is why it is spelled out rather than assumed.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_handoff_members NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        INSERT INTO agent_handoff_members
            (id, tenant_id, agent_id, position, label, phone_e164, hours, active, note)
        SELECT gen_random_uuid(),
               a.tenant_id,
               a.id,
               (c.ordinality - 1)::int,
               left(coalesce(nullif(btrim(c.value->>'name'), ''), 'Contact'), 120),
               c.value->>'phone_e164',
               -- NULL, ALWAYS: the source `hours` was free text and a guessed window is a
               -- mobile ringing at a time nobody agreed to. NULL means "whenever the
               -- business is open", which is the answer the intake form's own blocker
               -- ("we need somebody who can take a call") was actually asking for.
               NULL,
               true,
               nullif(btrim(coalesce(c.value->>'hours', '')), '')
          FROM agents a
          CROSS JOIN LATERAL jsonb_array_elements(a.escalation_config->'contacts')
                             WITH ORDINALITY AS c(value, ordinality)
         WHERE a.deleted_at IS NULL
           AND jsonb_typeof(a.escalation_config->'contacts') = 'array'
           -- The CHECK below would reject anything else, and a migration that aborts on
           -- one malformed legacy blob takes the whole release with it. A contact whose
           -- number was never valid is dropped and stays in `escalation_config`, which is
           -- kept precisely so nothing is lost.
           AND c.value->>'phone_e164' ~ '^\\+[1-9][0-9]{7,18}$'
        """
    )
    op.execute("ALTER TABLE agent_handoff_members FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Put the roster back where the wizard reads it from, so a rollback does not land on
    # an account whose escalation list is empty. Members added AFTER the upgrade come
    # back too — losing them would be the worse ending.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_handoff_members NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE agents a
           SET escalation_config = jsonb_build_object('contacts', m.contacts)
          FROM (SELECT agent_id,
                       jsonb_agg(jsonb_build_object(
                           'name', label, 'phone_e164', phone_e164, 'hours', note)
                           ORDER BY position) AS contacts
                  FROM agent_handoff_members
                 GROUP BY agent_id) AS m
         WHERE a.id = m.agent_id
        """
    )
    op.execute("ALTER TABLE agent_handoff_members FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON handoff_attempts")
    op.drop_index("ix_handoff_attempts_open", table_name="handoff_attempts")
    op.drop_index("uq_handoff_attempts_execution", table_name="handoff_attempts")
    op.drop_index(op.f("ix_handoff_attempts_tenant_id"), table_name="handoff_attempts")
    op.drop_table("handoff_attempts")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON agent_handoff_members")
    op.drop_index("uq_agent_handoff_members_position", table_name="agent_handoff_members")
    op.drop_index(
        op.f("ix_agent_handoff_members_tenant_id"), table_name="agent_handoff_members"
    )
    op.drop_table("agent_handoff_members")

    op.drop_column("agents", "handoff_trigger")
    op.drop_column("agents", "handoff_enabled")
