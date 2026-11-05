"""the KYC review queue stops opening a session per client (A7-21)

Revision ID: c7e1a4d9b2f6
Revises: a9d3f6c2e8b1
Create Date: 2026-11-05 22:30:00.000000

`compliance/kyc_review.waiting_reviews` opened one `tenant_session` per organization to ask
whether its record waits for a reviewer: 26 s at 7.7k organizations (audit of 5 Nov 2026,
A7-21), on a page the admin bell loads everywhere and on a half-hourly alarm. Most of that is
session machinery, as `a8d4f21c9b06` measured for the dispatch tick, so the loop moves into
Postgres the same way: `kyc_waiting_scan()` re-scopes `app.tenant_id` to one organization at
a time with `set_config` and reads that organization's record under its own policy.

SECURITY INVOKER, for `a8d4f21c9b06`'s reason: a SECURITY DEFINER function owned by a role
that bypasses RLS would answer faster and put a policy-blind role behind an admin page. Every
statement inside runs with `app.tenant_id` bound to exactly one organization.

The organizations are read into an array BEFORE the loop changes the GUC: `organizations` is
itself under RLS (the caller's `app.admin` lets it list them), and a `FOR ... IN SELECT`
cursor fetches lazily, so a loop over it would read later rows under the tenant GUC the loop
set. `app.tenant_id` is restored on the way out.

No new table, so no new RLS policy. Reversible: `downgrade()` drops the function.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7e1a4d9b2f6"
down_revision: str | Sequence[str] | None = "a9d3f6c2e8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "kyc_waiting_scan"

_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}()
RETURNS TABLE (
    scanned_tenant_id uuid,
    status text,
    kyc_path text,
    owner_id_type text,
    digilocker_required boolean,
    submitted_at timestamptz
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    ids uuid[];
    t uuid;
BEGIN
    SELECT coalesce(array_agg(o.id), '{{}}') INTO ids
      FROM organizations o WHERE o.deleted_at IS NULL;
    FOREACH t IN ARRAY ids LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT k.tenant_id, k.status::text, k.kyc_path::text, k.owner_id_type::text,
                   k.digilocker_required, k.submitted_at
              FROM kyc_records k
             WHERE k.tenant_id = t AND k.status IN ('submitted', 'in_review');
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute(_FUNCTION_SQL)


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")
