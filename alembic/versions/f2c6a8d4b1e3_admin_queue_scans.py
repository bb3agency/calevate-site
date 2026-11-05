"""the held-accounts queue and the call-lines queue stop opening a session per client (A7-21)

Revision ID: f2c6a8d4b1e3
Revises: d3a9f5c1e7b4
Create Date: 2026-11-06 10:00:00.000000

`admin/holds.held_tenants` and `tenancy/call_lines_routes.list_open_call_line_requests` each
opened one `tenant_session` per organization, the shape that took the KYC review queue 26 s
at 7.7k organizations (audit of 5 Nov 2026). Both move into Postgres the way `c7e1a4d9b2f6`
moved that queue: a SECURITY INVOKER function that re-scopes `app.tenant_id` to one
organization at a time with `set_config` and reads that organization's rows under its own
policy. No policy is widened (hard rule 1), and the caller's own `organizations` policy
decides which organizations are scanned, so a tenant session that calls either function sees
its own rows and nothing else.

* `kyc_hold_scan(candidates uuid[])` returns, for each candidate the caller may see, whether
  a KYC record exists and the four columns `compliance.service.kyc_rule` reads. The rule
  itself stays in Python: one spelling of the gate that refuses the dial.
* `open_call_line_request_scan()` returns each organization's open request for more lines.

The organization ids are read into an array BEFORE the loop changes the GUC, for
`c7e1a4d9b2f6`'s reason (a lazily fetched cursor would read later rows under the GUC the loop
set), and `app.tenant_id` is restored on the way out. No new table, so no new RLS policy.
Reversible: `downgrade()` drops both functions.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2c6a8d4b1e3"
down_revision: str | Sequence[str] | None = "d3a9f5c1e7b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KYC_HOLD_SCAN = """
CREATE OR REPLACE FUNCTION kyc_hold_scan(candidates uuid[])
RETURNS TABLE (
    scanned_tenant_id uuid,
    recorded boolean,
    status text,
    digilocker_required boolean,
    digilocker_required_at timestamptz,
    digilocker_verified_at timestamptz
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
    SELECT coalesce(array_agg(o.id), '{}') INTO ids
      FROM organizations o WHERE o.id = ANY(candidates) AND o.deleted_at IS NULL;
    FOREACH t IN ARRAY ids LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT t, k.tenant_id IS NOT NULL, k.status::text, coalesce(k.digilocker_required, false),
                   k.digilocker_required_at, k.digilocker_verified_at
              FROM (SELECT 1) AS one
              LEFT JOIN kyc_records k ON k.tenant_id = t;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""

_OPEN_REQUEST_SCAN = """
CREATE OR REPLACE FUNCTION open_call_line_request_scan()
RETURNS TABLE (
    scanned_tenant_id uuid,
    lines_at_request integer,
    wanted_lines integer,
    created_at timestamptz
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
    SELECT coalesce(array_agg(o.id), '{}') INTO ids
      FROM organizations o WHERE o.deleted_at IS NULL;
    FOREACH t IN ARRAY ids LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT r.tenant_id, r.lines_at_request, r.wanted_lines, r.created_at
              FROM call_line_requests r
             WHERE r.tenant_id = t AND r.status = 'open';
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute(_KYC_HOLD_SCAN)
    op.execute(_OPEN_REQUEST_SCAN)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS open_call_line_request_scan()")
    op.execute("DROP FUNCTION IF EXISTS kyc_hold_scan(uuid[])")
