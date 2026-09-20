"""a kyc verification run is resolvable by the webhook that reports it

Revision ID: c3f7b21a94e8
Revises: e5c1a70b93f4
Create Date: 2026-09-20 11:05:00.000000

`kyc_verification_requests` shipped with `tenant_isolation` alone:

    FOR ALL USING/WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)

On the session that resolve runs on there is no `app.tenant_id`, so the predicate is
`tenant_id = NULL` — NULL, not false — and every row is filtered. The aggregator's
webhook could therefore never find the run it was reporting on, for any tenant: the
route answered 404 to every well-formed, correctly-signed delivery, and no client could
finish verification by that path. Measured against a migrated database as the five
DB-backed tests in `tests/kyc_client_verification_test.py`, which had never been run
because the environment they were written in had no database.

The lookup is inherently cross-tenant and cannot be anything else: the payload names a
provider reference, the tenant is what we are trying to learn, and taking the tenant
from the body would let a leaked signing secret verify an arbitrary account.

So this adds the same asymmetric pair `engine_agent_routes` carries, in its CURRENT
form rather than its first one — `USING (<guc> IS NULL)` and not `USING (true)`. The
distinction is the whole of migration `d7c2f4a91b83`: permissive policies are OR'd per
command, so a `true` read arm would let a session scoped to tenant A read tenant B's
verification runs. The untenanted session is the only caller that needs this, and it is
the only one that gets it.

Measured as `calevate_app` (NOSUPERUSER NOBYPASSRLS) against a run owned by tenant B,
after this migration:

    SET LOCAL app.tenant_id = <tenant A>;  SELECT ... WHERE provider_ref = <B's>  -->  0
    (no app.tenant_id at all)              SELECT ... WHERE provider_ref = <B's>  -->  1
    SET LOCAL app.tenant_id = <tenant A>;  UPDATE ... WHERE provider_ref = <B's>  -->  UPDATE 0
    (no app.tenant_id at all)              UPDATE ... WHERE provider_ref = <B's>  -->  UPDATE 0

WRITES ARE UNTOUCHED AND STAY STRICT. `tenant_isolation` remains `FOR ALL` with the
row's own tenant on USING and WITH CHECK, so an untenanted session can read a run and
still write nothing; `kyc_routes.receive_verification_outcome` already reopens under
`tenant_session(run.tenant_id)` before `apply_outcome`, which is where every write
happens.
"""

from __future__ import annotations

from alembic import op

revision: str = "c3f7b21a94e8"
down_revision: str | None = "e5c1a70b93f4"
branch_labels: None = None
depends_on: None = None

TABLE = "kyc_verification_requests"
POLICY = f"{TABLE}_global_read"
_UNTENANTED = "NULLIF(current_setting('app.tenant_id', true), '') IS NULL"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(f"CREATE POLICY {POLICY} ON {TABLE} FOR SELECT USING ({_UNTENANTED})")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
