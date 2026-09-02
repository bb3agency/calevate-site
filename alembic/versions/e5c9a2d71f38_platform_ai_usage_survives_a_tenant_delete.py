"""platform_ai_usage: let ON DELETE SET NULL through, and nothing else

Revision ID: e5c9a2d71f38
Revises: b7e35c2f81da
Create Date: 2026-09-02

`platform_ai_usage.viewing_tenant_id` was declared `ON DELETE SET NULL` with the reason
written on the column in migration `f2c81a4d05e7`: *"an offboarded tenant must be
deletable, and platform accounting outlives the account it was about."* The same migration
then put the BLANKET `calevate_forbid_mutation` on the table for every UPDATE and DELETE,
`ENABLE ALWAYS`. Postgres executes a `SET NULL` referential action as an ordinary UPDATE of
the referencing row, so the trigger fires on it and the delete fails:

    RAISE: platform_ai_usage is append-only (hard rule 4): use a compensating entry
    CONTEXT: SQL statement "UPDATE ONLY "public"."platform_ai_usage"
             SET "viewing_tenant_id" = NULL WHERE $1 = "viewing_tenant_id""
    [SQL: DELETE FROM organizations WHERE id = ...]

(Measured on this repository's own database, 2 Sep 2026, against `head` = b7e35c2f81da.)

So the stated intent was defeated on the same table by the next twenty lines: once ANY
admin-copilot turn had that client on screen, the organization row became permanently
undeletable — not by a product decision but as a side effect of storing evidence, and with
an error message that names hard rule 4 rather than what actually happened. `SET NULL`
also silently degrades to "no referential action this database can perform", which is the
worse half: the FK reads as satisfiable and is not.

**THIS IS `a1c8e40f27b9`'s PATTERN, NOT A NEW ONE.** That migration hit exactly this on
`preference_scrub_runs.campaign_id` and wrote the answer down: replace the blanket function
with one that permits EXACTLY the referential action — the nullable context column going
non-NULL → NULL with every other column byte-for-byte unchanged — and refuses everything
else, including any other UPDATE and every DELETE. Nothing else in this repository may
mutate the row: the permitted transition is one Postgres performs itself, cannot be
composed with any other change, and is not reachable from `apps/` (no code path writes this
table except `billing/platform_ai.record_platform_ai_usage`, which only INSERTs).

WHAT IS AND IS NOT WEAKENED. The MONEY on the row — `qty`, `unit_cost_paid`, `unit_type`,
`ref`, `occurred_at` — is unchanged by the permitted transition and still cannot be edited
or removed, so hard rule 4's protection of the platform's own spend ledger is intact. What
is lost is the ability to say WHICH deleted account a historical row was about, which is
the trade `SET NULL` already declared and which `meta.viewing_tenant_id` (stamped by the
writer on every row) preserves as a plain string that no referential action rewrites.

`scripts/check_ledger_immutability.py` reads triggers by SHAPE and not by name — enabled,
row-level, RAISEing, ENABLE ALWAYS, covering UPDATE and DELETE — so this swap keeps that
gate green for the right reason rather than by exemption, exactly as the scrub trigger does.

RLS: no table, column, index or policy changes. `platform_ai_usage` carries no `tenant_id`
and no policy (it is the platform's ledger, not a client's — `f2c81a4d05e7` argues why).

LOCKING: one `CREATE FUNCTION`, one `DROP TRIGGER`, one `CREATE TRIGGER`. The trigger
swap takes a brief ACCESS EXCLUSIVE lock on `platform_ai_usage`, bounded by `lock_timeout`
(hard rule 8). Nothing rewrites the table and no row is read.

DOWNGRADE restores the blanket trigger and drops the function — the pre-migration state
exactly, including its inability to delete an organization the copilot ever viewed. The
FUNCTION is dropped as well as the trigger, for `a1c8e40f27b9`'s reason: leaving it behind
makes the next `upgrade` fail on `DuplicateFunction`, and a downgrade that cannot be
followed by an upgrade is not reversible.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5c9a2d71f38"
down_revision: str | None = "b7e35c2f81da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER = "platform_ai_usage_append_only"
FUNCTION = "calevate_platform_ai_usage_append_only"

# Every column of `platform_ai_usage` except the one the referential action clears. Spelled
# out rather than compared as a row (`NEW IS NOT DISTINCT FROM OLD`) because that comparison
# would include `viewing_tenant_id` and could never be true for the transition we are
# admitting — the same enumeration `calevate_preference_scrub_append_only` writes out.
_UNCHANGED = (
    "id",
    "admin_user_id",
    "system_actor",
    "unit_type",
    "qty",
    "unit_cost_paid",
    "ref",
    "occurred_at",
    "meta",
    "created_at",
)

_CREATE_FUNCTION = f"""
CREATE FUNCTION {FUNCTION}() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.viewing_tenant_id IS NOT NULL
       AND NEW.viewing_tenant_id IS NULL
       AND ({", ".join(f"NEW.{column}" for column in _UNCHANGED)})
           IS NOT DISTINCT FROM
           ({", ".join(f"OLD.{column}" for column in _UNCHANGED)})
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% is append-only (hard rule 4): use a compensating entry',
        TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql
"""


def _swap_trigger(function: str) -> None:
    """Point `platform_ai_usage_append_only` at `function`, keeping ENABLE ALWAYS.

    The name is kept across the swap on purpose: `f2c81a4d05e7` created it and the ops
    documentation names it, and a renamed trigger would read as a second guard rather than
    the same one taught one exception."""
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER {TRIGGER} ON platform_ai_usage")
    op.execute(
        f"CREATE TRIGGER {TRIGGER} BEFORE UPDATE OR DELETE ON platform_ai_usage "
        f"FOR EACH ROW EXECUTE FUNCTION {function}()"
    )
    # ENABLE ALWAYS, restated because `CREATE TRIGGER` defaults to ORIGIN — and an ORIGIN
    # trigger stops firing under `SET session_replication_role = replica`, which is what
    # `pg_restore --disable-triggers` emits (a2e9f31c605d).
    op.execute(f"ALTER TABLE platform_ai_usage ENABLE ALWAYS TRIGGER {TRIGGER}")


def upgrade() -> None:
    op.execute(_CREATE_FUNCTION)
    _swap_trigger(FUNCTION)


def downgrade() -> None:
    _swap_trigger("calevate_forbid_mutation")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")
