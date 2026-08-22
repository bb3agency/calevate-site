"""call_engine_latency — the per-turn timings the adapter used to throw away

Revision ID: b7d3e91c4a05
Revises: f2a6d81b39c4
Create Date: 2026-08-22 11:20:00.000000

**READ `f1a7c39d5be2` FIRST. This is not that column coming back.** That migration dropped
`calls.latency`, which promised `{stt_ms, llm_ttft_ms, tts_ttfa_ms, turn_p50, turn_p95}`
and was written by nothing, because the two summary numbers were VOICE-TO-VOICE — the
interval between the caller finishing a word and the caller hearing audio — and both ends
of that interval live on the PSTN leg that our stack is not in (D-25/D-33). Nothing could
write it honestly then and nothing can now. `tests/call_latency_column_test.py` keeps that
drop true in four places and this migration does not touch any of them.

What lands here is a DIFFERENT quantity with a real source: the engine's own view of its
own pipeline, per turn, which it publishes on every execution
(`bolna-findings/mirror/pages/concepts/call-latencies.md:22-45,57-155` — VERIFIED-VENDOR-DOCS)
and which `apps/api/engine/bolna.py` read and discarded until today.

**WHY IT IS WORTH A TABLE, AND WHY NOW.** D-410 put the language model in an Azure
deployment pinned to South India. The engine's orchestrator is US-hosted
(`mirror/pages/concepts/security.md:29`). So every conversational turn's LLM call is a
US->India->US round trip on the caller's audio path, inside a 350ms TTFT budget (TRD §4) —
and TRD §4a records that every latency figure in this repo is a target with zero
measurements behind it. `llm_ttft_ms` per turn, grouped by `region`, is the measurement.
OPERATIONS §2 gate 4 becomes two pilot calls (one deployment in South India, one in the US)
and a `GROUP BY`, instead of an argument between two plausible estimates.

**SEPARATE TABLE, not columns on `calls`.** The name of this thing is "what the engine
reported", and on the call row the next reader would read it as the call's latency — which
is the exact misreading that produced the dropped column. A join is cheap; a misread column
is permanent.

**NO STORED AGGREGATES.** No p50, no p95, no breach count, no turn count. Each is
`jsonb_array_elements(turns)` away, and a statistic stored beside the samples it summarizes
is a number that can disagree with its own evidence. `apps/api/ops/engine_latency.py` holds
the arithmetic, once. (This is `quality.QaReport`'s argument for not storing rendered
Markdown beside the computation it came from.)

**HARD RULE 6 IS ENFORCED BY THE SCHEMA, not by a convention.** The vendor's payload nests
recognised CALLER SPEECH beside these timings (`call-latencies.md:73`). Three things stop
it landing here: `CallLatency` has no field text can be parsed into, the adapter reads
numbers and drops the rest, and the CHECK below refuses any element of `turns` that is not
an object whose values are numbers. A future writer that "just passes the payload through"
fails at the database.

**ISOLATION** (hard rule 1), in this migration and not the next one: `tenant_id`, the
DATA-MODEL §1 `tenant_isolation` policy, ENABLE plus FORCE. The cross-tenant zero-rows
proof is `tests/engine_latency_test.py::test_tenant_b_cannot_see_tenant_as_latency_row`.

**ERASURE.** Nothing here is personal data — milliseconds, a turn index and a region code —
but the row is still reachable by the ordinary path: `call_id` is `ON DELETE CASCADE`, so
it cannot outlive the call it describes. RESTRICT on `tenant_id` matches every other table:
an organization with rows is not deletable.

**UNIQUE(call_id)** — one measurement per call. The post-call pipeline re-runs on every
re-drive and the poller can drive it again, so the write is an upsert onto this constraint.
Without it a re-drive would append a second copy of every turn and silently double-weight
that call in the distribution, which is the failure mode a measurement table can least
afford.

**Locking.** A new table: nothing to lock out, no scan, no rewrite. `lock_timeout` is set
anyway so that queueing behind another session's long transaction fails fast. The FKs are
added NOT VALID and validated separately (SHARE UPDATE EXCLUSIVE — blocks no reader or
writer on `organizations`/`calls`), which is this repo's pattern.

**Downgrade** drops the policy, the index and the table. It loses measurements, which no
downgrade can avoid since the table is the only place they live — and it loses nothing
else: the engine's raw document is still archived under the call's prefix (D-126), so a
re-drive of the pipeline can produce them again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d3e91c4a05"
down_revision: str | None = "f2a6d81b39c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once carried the GUC returns
# '' when it is unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON call_engine_latency USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

# The shape rule that makes hard rule 6 a database property. Every element of `turns` must
# be an OBJECT whose values are numbers or null — so a `text` key carrying a caller's words
# cannot be stored even by a writer that ignores every comment in this tree.
#
# A FUNCTION AND NOT AN INLINE CHECK, because Postgres refuses a subquery in a CHECK
# constraint outright ("cannot use subquery in check constraint") and the rule is
# per-element, i.e. inherently a subquery over `jsonb_array_elements`. IMMUTABLE and
# PARALLEL SAFE: it reads nothing but its argument. The alternative was a BEFORE trigger;
# a CHECK is preferred because it shows up in `\d` beside the columns it constrains, where
# the next person adding a column will actually read it.
#
# Written as NOT EXISTS over the offending elements rather than as a positive assertion,
# because an EMPTY ARRAY must pass: "the engine returned a latency object we could read no
# turns out of" is a real answer, and `parse_warnings` is where it explains itself.
_TURNS_FUNCTION = """
CREATE OR REPLACE FUNCTION call_latency_turns_are_numeric(turns jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT jsonb_typeof(turns) = 'array' AND NOT EXISTS (
    SELECT 1
    FROM jsonb_array_elements(turns) AS element
    WHERE jsonb_typeof(element) <> 'object'
       OR EXISTS (
         SELECT 1 FROM jsonb_each(element) AS entry(key, value)
         WHERE jsonb_typeof(entry.value) NOT IN ('number', 'null')
       )
  )
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_TURNS_FUNCTION)
    op.create_table(
        "call_engine_latency",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("region", sa.String(), nullable=True),
        sa.Column("time_to_first_audio_ms", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("turns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parse_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.CheckConstraint(
            "call_latency_turns_are_numeric(turns)",
            name=op.f("ck_call_engine_latency_turns_are_numbers"),
        ),
        # A region CODE, never a message. Same reason: the column is grouped by, and the
        # one thing that must not happen to a free-form vendor string is that it is stored
        # and later rendered. The adapter refuses a non-code before this ever fires; the
        # constraint is what makes that a property of the data rather than of one caller.
        sa.CheckConstraint(
            "region IS NULL OR region ~ '^[a-z0-9][a-z0-9-]{0,15}$'",
            name=op.f("ck_call_engine_latency_region_is_a_code"),
        ),
        sa.CheckConstraint(
            "parse_warnings IS NULL OR jsonb_typeof(parse_warnings) = 'array'",
            name=op.f("ck_call_engine_latency_parse_warnings_is_an_array"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_engine_latency")),
        sa.UniqueConstraint("call_id", name=op.f("uq_call_engine_latency_call_id")),
    )
    op.create_index(
        op.f("ix_call_engine_latency_tenant_id"), "call_engine_latency", ["tenant_id"], unique=False
    )

    op.execute(
        "ALTER TABLE call_engine_latency ADD CONSTRAINT "
        "fk_call_engine_latency_tenant_id_organizations FOREIGN KEY (tenant_id) "
        "REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute(
        "ALTER TABLE call_engine_latency ADD CONSTRAINT "
        "fk_call_engine_latency_call_id_calls FOREIGN KEY (call_id) "
        "REFERENCES calls (id) ON DELETE CASCADE NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE call_engine_latency VALIDATE CONSTRAINT "
        "fk_call_engine_latency_tenant_id_organizations"
    )
    op.execute(
        "ALTER TABLE call_engine_latency VALIDATE CONSTRAINT fk_call_engine_latency_call_id_calls"
    )

    # Hard rule 1, in the same migration as the table it protects.
    op.execute("ALTER TABLE call_engine_latency ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_engine_latency FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON call_engine_latency")
    op.drop_index(op.f("ix_call_engine_latency_tenant_id"), table_name="call_engine_latency")
    op.drop_table("call_engine_latency")
    op.execute("DROP FUNCTION IF EXISTS call_latency_turns_are_numeric(jsonb)")
