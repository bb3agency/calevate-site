"""A tenant cannot DELETE a global DNC row — WITH CHECK never guarded that verb

Revision ID: e4f2a86b13d7
Revises: a1c8e40f27b9
Create Date: 2026-08-15 09:30:00.000000

THE HOLE, and it is a compliance one. `a1c8e40f27b9` gave `dnc_list` a deliberately
asymmetric `FOR ALL` policy: a permissive `USING` so a tenant can READ global rows — it
must, or a nationally suppressed number would still be dialled — and a `WITH CHECK` that
confines writes to `scope='tenant'` unless the session carries no `app.tenant_id`.

**`WITH CHECK` is not evaluated on DELETE.** Postgres consults `USING` alone to decide
which rows a DELETE may remove; `WITH CHECK` applies to INSERT and to the NEW row of an
UPDATE. The `USING` clause permits `tenant_id IS NULL`, so every tenant session could
delete every global suppression on the platform. Measured before writing this, as the app
role against the real schema:

    SET app.tenant_id = '1111...';
    DELETE FROM dnc_list WHERE phone_e164 = '+9198...';   -- DELETE 1

That is one client lifting a regulator instruction, or our own permanent refusal, for
every other client — and `remove_entry`'s named `dnc_global_entry` refusal is an
APPLICATION check, so it protects the route and not the table. Hard rule 1 is explicit
that RLS is the enforcement.

UPDATE was already safe and was checked rather than assumed: the same statement with
`SET source = 'hijacked'` returns *new row violates row-level security policy*, because
the NEW row fails `WITH CHECK`. Only DELETE was open. `dnc_list` is also the only table in
the schema whose `USING` mentions `tenant_id IS NULL`, so the blast radius is this table
and no other — confirmed against `pg_policy`.

WHY A RESTRICTIVE POLICY RATHER THAN REWRITING THE EXISTING ONE. The permissive `FOR ALL`
policy is load-bearing for SELECT and correct for INSERT/UPDATE; splitting it into four
per-command policies would rewrite three working rules to fix one, and every reader of
`dnc.py` would then have to hold four policies in their head to answer "can a tenant see a
global row". A RESTRICTIVE policy is ANDed with the permissive ones and scoped `FOR
DELETE`, so it subtracts exactly the verb that was over-permitted and touches nothing
else. Its predicate is the same sentence as the existing `WITH CHECK`, deliberately — the
rule for "may this session write this row" should not differ by verb, and stating it twice
in one migration is how the next reader sees that they match.

WHY NOT AN APPLICATION GUARD. `remove_global_entry` already has one (`rowcount != 1`
reported as not-found), and it was written believing RLS refused the delete. It did not.
An `if` in one function cannot constrain the other callers, a psql session, or the next
function somebody writes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4f2a86b13d7"
down_revision: str | None = "a1c8e40f27b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "dnc_list_delete_scope"

# The same sentence as the FOR ALL policy's WITH CHECK, on purpose: a tenant may remove
# only its own tenant-scoped row, and a global row may be removed only by a session that
# carries no tenant at all (the ops path).
DELETE_USING = """
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
        f"CREATE POLICY {POLICY} ON dnc_list AS RESTRICTIVE FOR DELETE USING ({DELETE_USING})"
    )


def downgrade() -> None:
    # Reversible, and the reversal genuinely restores the prior behaviour — including the
    # hole. Recorded rather than silently refused: a downgrade past this revision is a
    # deployment running `a1c8e40f27b9`'s schema, and that schema had this defect.
    op.execute(f"DROP POLICY {POLICY} ON dnc_list")
