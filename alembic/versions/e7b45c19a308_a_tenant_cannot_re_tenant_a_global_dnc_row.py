"""A tenant cannot RE-TENANT a global DNC row — e4f2a86b13d7 cleared UPDATE too early

Revision ID: e7b45c19a308
Revises: c7a1e93d40b8
Create Date: 2026-08-18 00:00:00.000000

THE HOLE, and it is the same compliance hole `e4f2a86b13d7` closed for DELETE, reached by
a different verb. That migration's docstring says, in its own words:

    "UPDATE was already safe and was checked rather than assumed: the same statement with
    `SET source = 'hijacked'` returns *new row violates row-level security policy*,
    because the NEW row fails `WITH CHECK`. Only DELETE was open."

The check was real and the conclusion was wrong, because the probe only tried an UPDATE
that LEFT THE ROW GLOBAL. `SET source = 'hijacked'` keeps `tenant_id IS NULL` and
`scope = 'global'`, which fails the permissive `WITH CHECK` for a session that carries an
`app.tenant_id` — so the refusal that was observed was real, and it says nothing about the
update that MOVES the row. `a1c8e40f27b9`'s `USING` admits `tenant_id IS NULL`, so a tenant
session may select a global row for update; the `WITH CHECK` then only asks whether the NEW
row is a legitimate row for this tenant. `SET tenant_id = <me>, scope = 'tenant'` satisfies
it exactly. Measured before writing this, as `calevate_app` against a scratch database
migrated from base to head:

    SET LOCAL app.tenant_id = '0190...000a';
    DELETE FROM dnc_list WHERE phone_e164 = '+919999000001' AND tenant_id IS NULL;
    -- DELETE 0        <- e4f2a86b13d7 doing its job
    UPDATE dnc_list SET tenant_id = '0190...000a', scope = 'tenant'
     WHERE phone_e164 = '+919999000001' AND tenant_id IS NULL;
    -- UPDATE 1        <- the row is now the attacker's
    DELETE FROM dnc_list WHERE phone_e164 = '+919999000001';
    -- DELETE 1        <- and a row you own may be deleted

Net effect: any tenant session can lift a platform-wide suppression — a regulator or TSP
instruction naming a number, or our own permanent refusal (DATA-MODEL §6) — for every
other client on the platform, in two statements. `remove_entry`'s `dnc_global_entry`
refusal is an APPLICATION check on one route; hard rule 1 is explicit that RLS is the
enforcement, which is the whole argument `e4f2a86b13d7` already made.

WHY NOTHING CAUGHT IT. `tests/rls_sweep_test.py` sweeps cross-TENANT mutation — tenant A
aiming at tenant B's rows. A global row belongs to no tenant, so `tenant_id IS NULL` is
outside every probe in that file by construction, and `dnc_list` is the only table in this
schema whose `USING` mentions `tenant_id IS NULL` (confirmed against `pg_policy`). The
behavioural pin that does exist, `dnc_test.py::
test_a_global_suppression_is_visible_to_a_tenant_and_not_removable`, asserts the ROUTE's
422 — which is the application check, not the table's.

THE FIX, and why it is shaped like its predecessor. A RESTRICTIVE policy is ANDed with the
permissive ones (PostgreSQL 16 §5.8: multiple policies "are combined using either OR (for
permissive policies ...) or using AND (for restrictive policies)"), and scoping it `FOR
UPDATE` subtracts exactly the verb that was over-permitted while leaving SELECT — the one
clause that MUST admit global rows, or a nationally suppressed number keeps getting dialled
— untouched. `WITH CHECK` is deliberately omitted: for a policy that can carry both,
PostgreSQL applies `USING` to the rows an UPDATE may select AND, "if no WITH CHECK
expression is defined, then the USING expression will be used for both purposes"
(PG16 CREATE POLICY). One expression is what makes "the rule for may-this-session-write-
this-row does not differ by verb" true by construction rather than by two texts agreeing.

The predicate is character-for-character `e4f2a86b13d7`'s, which is character-for-character
`a1c8e40f27b9`'s `WITH CHECK`. Three copies of one sentence is worse than one shared
constant, and this is the reason it stays a copy: a migration is a historical record of the
statement that ran, so importing the predicate from a module would let a later edit
retroactively change what an applied migration is documented to have done.

NOTHING IN THE APPLICATION UPDATES THIS TABLE. `grep -rn "UPDATE dnc_list" apps/` returns
nothing; `dnc.py` inserts and deletes only. So this policy refuses no path that exists, and
the ops path it must not refuse — an untenanted session, second branch — is the same one
`add_global_numbers` and `remove_global_entry` already run under.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7b45c19a308"
down_revision: str | None = "c7a1e93d40b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "dnc_list_update_scope"

# The same sentence as `dnc_list_delete_scope` and as the FOR ALL policy's WITH CHECK, on
# purpose (see the docstring): a tenant may touch only its own tenant-scoped row, and a
# global row may be touched only by a session that carries no tenant at all.
UPDATE_USING = """
    (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        AND scope = 'tenant'
    )
    OR (
        tenant_id IS NULL
        AND scope = 'global'
        AND NULLIF(current_setting('app.tenant_id', true), '') IS NULL
    )
"""


def upgrade() -> None:
    op.execute(
        f"CREATE POLICY {POLICY} ON dnc_list AS RESTRICTIVE FOR UPDATE USING ({UPDATE_USING})"
    )


def downgrade() -> None:
    # Reversible, and the reversal genuinely restores the prior behaviour — including the
    # hole — for the same reason `e4f2a86b13d7`'s downgrade does: a deployment running
    # `c7a1e93d40b8`'s schema is a deployment with this defect, and a downgrade that
    # refused would be a downgrade that lies about which schema it produced.
    op.execute(f"DROP POLICY {POLICY} ON dnc_list")
