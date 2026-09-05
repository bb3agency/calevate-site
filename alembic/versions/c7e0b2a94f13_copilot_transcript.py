"""copilot transcript — the conversation itself, durable, and the sign-in run that ends it

Revision ID: c7e0b2a94f13
Revises: b8d1f04c73a9
Create Date: 2026-09-05 00:00:00.000000

D-540. The copilot conversation was React state (`useCopilotConversation.ts`), so a
refresh, a route change that unmounted the dock, or a closed browser lost it. This
revision is the store that survives that, and it is deliberately NOT a widening of
`copilot_memories`: those rows are DISTILLED FACTS the assistant learned (one redacted
episode, or a semantic fact a worker distilled out of a run of them), read back into a
prompt through `copilot/memory.recall`'s two budgeted channels. A transcript is the
verbatim thing a person can scroll. One table serving both would be a recall query
returning chat history and a chat panel rendering distillate.

WHAT ONE ROW IS: one turn — one thing said, by a person or by the assistant, on one
screen. The conversation is the set of a user's rows; there is no header row and no
conversation id, because there is exactly ONE live conversation per user per tenant
(the founder's decision 2: the same person sees the same thread on their phone and their
desktop) and a header table would exist only to give that fact an id.

THE SCREEN IS PER TURN, NOT PER THREAD (founder's decision 3). The assistant can move a
person between screens mid-answer (D-524), so a thread keyed on screen would change
underneath them while it was answering.

`run_started_at` IS THE LIFETIME, AND IT IS WHY THIS TABLE NEEDS NO SEPARATE "SESSION"
NOTION. The founder's decision 1 is that the conversation dies when the session ends, and
decision 2 is that it is shared across devices; the resolution is that it belongs to the
USER and is cleared when their LAST session ends. So each turn carries the instant the
user's current UNBROKEN RUN of sessions began (`copilot/session_run.py` computes it from
`auth_sessions` by islands-and-gaps). A row whose `run_started_at` is older than the
current run belongs to a run that has ended, and is deleted before it is ever read.
Signing out on a phone while a desktop session is live does not move the run start, so it
does not wipe the desktop's thread — which is exactly the half the two decisions pull
against.

Expiry is a timestamp passing rather than an event, so it is OBSERVED in two real places
and assumed in neither: lazily, by the comparison above, on the next request the person
makes; and by `apps/workers/copilot_transcript.py`'s cron, which is what notices a user
who signed out and never came back.

CONTENT IS THE REDACTED FORM, ALWAYS. `copilot/redaction.ts` replaces field values that
look like identifiers with placeholders before a question leaves the browser and restores
them for DISPLAY only; what is persisted here is the wire form, through
`copilot/memory.redacted_content`'s same `redact()` pass, for that module's reasons. A
turn re-read after a reload therefore shows the placeholder where the live one showed the
digits — the digits were never ours to keep, and storing them would put a caller's number
in a durable row that the phone-keyed §12 erasure would then have to find.

RETENTION IS THE `transcript` CATEGORY — the founder's decision 4, "the same clock as call
transcripts" — so this revision widens NO enum, seeds NO policy row and creates NO second
mechanism. `apps/workers/retention.py` gains an arm under a category that already exists
on every tenant. What it does need is the same worklist bridge `copilot_memories` needed
(D-368's answer, reused rather than re-invented): `retention._due_tenants` derives its
worklist from published agent routes, and a tenant can hold copilot turns with no
published agent. `register_retention_worklist()` already takes its reason as `TG_ARGV[0]`,
so this is one new reason and one new trigger, and no function change.

THE ADMIN TWIN IS A SECOND TABLE FOR `admin_copilot_memories`' REASON, VERBATIM:
`Principal.user_id` is a `users.id` on the client realm and an `admin_users.id` on the
admin realm, and the two id spaces sharing one column is a cross-realm read waiting to
happen. It carries no `tenant_id` and no RLS policy (these are the platform's own rows;
`viewing_tenant_id` is CONTEXT, SET NULL on tenant delete) and no retention category,
because there is no tenant whose policy could name it — its clock is the admin realm's
8-hour absolute session bound, which is shorter than any retention period we publish.

REVERSIBILITY. `downgrade()` drops both tables, both triggers, the worklist rows and the
widened reason CHECK, in that order — the rows before the CHECK narrows, and with the
FORCE-RLS bracket `d3b71c9a5e08` established, because `retention_worklist` is FORCE'd and
an unbracketed DELETE there matches zero rows and reports success. Nothing here is a
record of something that happened (hard rule 4): every turn is derived from an exchange
already metered in `usage_events` and audited in `audit_log`, both of which survive.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e0b2a94f13"
down_revision: str | None = "b8d1f04c73a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "copilot_conversation_turns"
ADMIN_TABLE = "admin_copilot_conversation_turns"

# DATA-MODEL §1 verbatim, with `d5b8a2c60e17`'s NULLIF: a pooled connection that once had
# the GUC returns '' when unset, and ''::uuid ERRORs instead of failing closed.
_POLICY = (
    f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

# Literals, never imports — a migration is a snapshot of the schema on the day it ran
# (`c2f7a91b4e63`'s rule), so a constant edited later must not change what this file did.
_WORKLIST_REASON = "copilot_transcript"
_REASONS_BEFORE = ("kb_source", "copilot_memory")
_REASONS_AFTER = (*_REASONS_BEFORE, _WORKLIST_REASON)

#: Same ceiling as `copilot/schemas._MAX_TEXT` and `copilot_memories.content` — the bound
#: the wire already puts on one field value and one history turn. Repeated as a literal
#: for the reason above.
_MAX_CONTENT = 2_000

_WORKLIST_FN = "register_retention_worklist"
_TRIGGER = "copilot_transcript_registers_retention_worklist"


def _in_list(values: Sequence[str]) -> str:
    """`('a', 'b')` as SQL. NOT `repr(tuple)`, which emits a trailing comma for a
    one-element tuple and is then a syntax error in an `IN` list (`d4a9c17e6b02`)."""
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _turn_columns() -> list[sa.Column[object]]:
    """The columns both realms share. The two tables differ only in whose row it is."""
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        # WHICH SIGN-IN RUN this turn belongs to. See the module docstring: this is the
        # whole of the conversation's lifetime, and it is a plain instant rather than a
        # foreign key to `auth_sessions` on purpose — a session ROW dies on every
        # rotation (`authn/sessions.rotate_session`), and a turn pointing at a superseded
        # row would be orphaned by a second factor being proved.
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        # Redacted on the way in — see the module docstring and
        # `copilot/memory.redacted_content`, which is the shared pass.
        sa.Column("content", sa.Text(), nullable=False),
        # The route template the browser reported: a screen NAME, never a record id
        # (`copilot/routes.py` audits the same value). NOT NULL here where it is nullable
        # on `copilot_memories`, because every turn happens on a screen — there is no
        # distilled row here for which the question would be meaningless.
        sa.Column("screen_route", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _turn_constraints(table: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f(f"ck_{table}_role_enum")),
        # A blank turn is a bubble that says nothing and still costs a row and a render.
        sa.CheckConstraint(
            "length(btrim(content)) > 0", name=op.f(f"ck_{table}_content_not_blank")
        ),
        # THE SPEND AND STORAGE BOUND, in the schema rather than in the writer.
        sa.CheckConstraint(
            f"length(content) <= {_MAX_CONTENT}", name=op.f(f"ck_{table}_content_cap")
        ),
    ]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    # --- the client realm -------------------------------------------------------------
    op.create_table(
        TABLE,
        *_turn_columns(),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # WHOSE conversation. RLS answers "which tenant" and never "which person"
        # (`copilot_memories` and `lead_saved_views` say the same), so every read in
        # `copilot/transcript.py` carries an explicit `user_id =` predicate: one
        # colleague's console conversation is not another's to read.
        sa.Column("user_id", sa.UUID(), nullable=False),
        *_turn_constraints(TABLE),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    # THE ONE READ, THE TRIM AND THE SWEEP, all served by one index. `created_at` ASCENDING
    # because the transcript is rendered oldest-first and the trim deletes from the front;
    # the tail page is the same index scanned backwards. `id` is uuid7 and therefore
    # time-ordered, so it is the tiebreak that makes the order total inside one clock tick
    # — two turns of one exchange can share a `created_at` at statement granularity, and a
    # transcript that renders the answer above the question is worse than no transcript.
    op.create_index(
        op.f(f"ix_{TABLE}_tenant_user_seq"), TABLE, ["tenant_id", "user_id", "created_at", "id"]
    )
    # NOT VALID then VALIDATE — `d5b8a2c60e17`'s locking shape. `organizations` RESTRICT
    # (offboarding is an explicit workflow, never a cascade); `users` CASCADE, because a
    # deleted user's conversation has no subject left and RESTRICT would make it block the
    # deletion of the person it is about.
    for statement in (
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_{TABLE}_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_{TABLE}_user_id_users "
        "FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE NOT VALID",
    ):
        op.execute(statement)
    op.execute("SET LOCAL lock_timeout = '3s'")
    for constraint in (f"fk_{TABLE}_tenant_id_organizations", f"fk_{TABLE}_user_id_users"):
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {constraint}")

    # Hard rule 1, in the same migration as the table it protects.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    # --- the admin realm --------------------------------------------------------------
    # No `tenant_id`, no policy: see the module docstring. `db/registry.py` carries the
    # standing justification, which is what `scripts/check_rls_coverage.py` reads.
    op.create_table(
        ADMIN_TABLE,
        *_turn_columns(),
        sa.Column("admin_user_id", sa.UUID(), nullable=False),
        # WHICH ACCOUNT WAS ON SCREEN, so an operator's conversation about one client is
        # not re-read as a conversation about the platform. Context, not ownership —
        # nullable, and SET NULL on tenant delete, exactly as on `admin_copilot_memories`.
        sa.Column("viewing_tenant_id", sa.UUID(), nullable=True),
        *_turn_constraints(ADMIN_TABLE),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ADMIN_TABLE}")),
    )
    op.create_index(
        op.f(f"ix_{ADMIN_TABLE}_user_seq"), ADMIN_TABLE, ["admin_user_id", "created_at", "id"]
    )
    for statement in (
        f"ALTER TABLE {ADMIN_TABLE} ADD CONSTRAINT fk_{ADMIN_TABLE}_admin_user_id_admin_users "
        "FOREIGN KEY (admin_user_id) REFERENCES admin_users (id) ON DELETE CASCADE NOT VALID",
        f"ALTER TABLE {ADMIN_TABLE} ADD CONSTRAINT fk_{ADMIN_TABLE}_viewing_tenant_id_organizations "
        "FOREIGN KEY (viewing_tenant_id) REFERENCES organizations (id) ON DELETE SET NULL NOT VALID",
    ):
        op.execute(statement)
    op.execute("SET LOCAL lock_timeout = '3s'")
    for constraint in (
        f"fk_{ADMIN_TABLE}_admin_user_id_admin_users",
        f"fk_{ADMIN_TABLE}_viewing_tenant_id_organizations",
    ):
        op.execute(f"ALTER TABLE {ADMIN_TABLE} VALIDATE CONSTRAINT {constraint}")

    # --- the worklist bridge ----------------------------------------------------------
    # D-368's answer, reused. `register_retention_worklist()` already takes the reason as
    # TG_ARGV[0] (`d4a9c17e6b02`), so there is one registration function and this adds one
    # reason and one trigger — no function is redefined here.
    op.execute("ALTER TABLE retention_worklist DROP CONSTRAINT ck_retention_worklist_reason_enum")
    op.execute(
        "ALTER TABLE retention_worklist ADD CONSTRAINT ck_retention_worklist_reason_enum "
        f"CHECK (reason IN {_in_list(_REASONS_AFTER)})"
    )
    op.execute(
        f"CREATE TRIGGER {_TRIGGER} AFTER INSERT ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {_WORKLIST_FN}('{_WORKLIST_REASON}')"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {TABLE}")
    # BEFORE the CHECK narrows, or the constraint is created over rows that violate it.
    # The bracket (`d3b71c9a5e08`): `retention_worklist` is FORCE ROW LEVEL SECURITY, which
    # subjects the OWNER to a policy that is fail-closed on an unset `app.tenant_id`, so an
    # unbracketed DELETE here matches ZERO rows and reports success.
    op.execute("ALTER TABLE retention_worklist NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM retention_worklist WHERE reason = '{_WORKLIST_REASON}'")
    op.execute("ALTER TABLE retention_worklist FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE retention_worklist DROP CONSTRAINT ck_retention_worklist_reason_enum")
    op.execute(
        "ALTER TABLE retention_worklist ADD CONSTRAINT ck_retention_worklist_reason_enum "
        f"CHECK (reason IN {_in_list(_REASONS_BEFORE)})"
    )

    op.drop_index(op.f(f"ix_{ADMIN_TABLE}_user_seq"), table_name=ADMIN_TABLE)
    op.drop_table(ADMIN_TABLE)

    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index(op.f(f"ix_{TABLE}_tenant_user_seq"), table_name=TABLE)
    op.drop_table(TABLE)
