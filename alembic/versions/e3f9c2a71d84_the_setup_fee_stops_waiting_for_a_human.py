"""the setup fee stops waiting for somebody to open a screen

Revision ID: e3f9c2a71d84
Revises: b3d61f0a97c4
Create Date: 2026-08-14 09:40:00.000000

D-63 billed the onboarding setup fee from `billing/charges.py`, on the render of the
invoice that carries it. `one_time_charge_lines` named the cost of that in its own
docstring: `GET /v1/admin/tenants/{id}/invoice` was the only caller, so a tenant whose
first invoice nobody opened was never charged. The fee was a scheduled obligation
served by a human's browser.

`issue_one_time_charges` (apps/workers/billing.py) is the scheduled half. It has to
answer ONE cross-tenant question before it can do any per-tenant work — *which tenants
are owed a setup fee that has not been recorded?* — and this migration is that question,
asked the way D-57 taught this repo to ask cross-tenant questions.

`unbilled_setup_fees(charge_kind, charge_ref)` — SECURITY INVOKER, no exemption
-------------------------------------------------------------------------------
Same shape and same reasoning as `dispatch_scan` (a8d4f21c9b06): loop the tenants, and
for each one `set_config('app.tenant_id', ...)` and ask that tenant's question under
that tenant's own policies. It is **SECURITY INVOKER** (the default, written out
because the default is the load-bearing part): it runs as the calling role with every
policy applied and holds no grant the caller lacks. The rejected alternative is the one
every "cross-tenant aggregate" answer reaches for — `SECURITY DEFINER` owned by a
`BYPASSRLS` role — which is a hard-rule-1 violation wearing a function's clothes, and
here it would be a role that cannot see RLS reading every client's commercial terms.

**WHERE THE TENANT LIST COMES FROM, AND WHY IT IS NOT A BRIDGE TABLE.** `dispatch_scan`
and the retention sweep enumerate `engine_agent_routes`, the global routing bridge,
precisely so no widening is needed; both are careful to say the bridge is a proven
SUPERSET of the population they act on. For a setup fee it is a **subset**: the fee is
owed the moment an operator puts a plan on a tenant, and a client can sit in onboarding
for weeks before an agent is ever published. c7e4b19d3f52's rule — "a superset here and
a subset never" — therefore forbids reusing it, and a third entry in
`RLS_EXEMPT_TENANT_COLUMNS` (a globally readable `plans`, i.e. every client's
commercial terms outside RLS) is a far larger price than the one this takes.

So the loop reads `organizations` under the caller's own GUCs, which means the CALLER
must hold `app.admin` — `admin_session()`, the same "one sanctioned enumeration
surface" `scripts/reconcile_credit_ledger._all_tenant_ids` uses for the same
platform-money reason. `app.admin` widens `USING` on `organizations` and NOTHING else
(b57e2f9c4a13), so inside the loop `plans` and `one_time_charges` — the two tables this
function actually reads — are fenced by `app.tenant_id` exactly as they are in a
request. It returns ids and an onboarding instant; no name, no money, no personal data.

**The probe is deliberately COARSE, and that is what keeps plan resolution in one
place.** It asks "does this tenant have ANY plan row quoting a positive `setup_fee`,
and no charge under (kind, ref) yet?" — never "which plan is in effect", which is
`billing/plans.plan_in_effect_sql`'s job and must stay there. A SQL copy of that
resolution would be a second source of truth for what a client is charged, drifting
silently. Coarse is safe in this direction only: the result is a superset of the
tenants owed a fee, and `billing/charges.issue_setup_fee` — the same function the
invoice-issuing path calls — makes the real decision and may decline. A tenant that
should NOT be charged costs one extra session; a tenant this missed would never be
charged at all.

`kind` and `ref` are PARAMETERS, not literals, for the reason `dispatch_scan` takes
`active_statuses`: `SETUP_FEE_KIND` / `SETUP_FEE_REF` keep exactly one definition, in
`billing/charges.py`, beside the argument for why `ref` is constant.

Soft-deleted organizations are skipped. Unlike the credit-ledger reconciliation (which
includes them because their wrong balances are still wrong), issuing a NEW charge
against a client who has left is a bill nobody will send; if one is genuinely owed it
is an operator's compensating INSERT, not a nightly job's initiative.

The GUC is restored on the way out, as in `dispatch_scan`. It is transaction-local
either way, so an abort resets it regardless; restoring is for the caller that keeps
using its session afterwards.

NO NEW TABLE, SO NO NEW RLS POLICY, and no new index: the probe's two questions are
served by `ix_plans_tenant_id` and by `ux_one_time_charges_tenant_kind_ref`, which
leads with exactly `(tenant_id, kind, ref)`.

Reversible: `downgrade()` drops the function. The job that calls it then fails loudly
rather than quietly charging nobody — which is correct, and is the same choice
a8d4f21c9b06 records for the dispatch tick.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3f9c2a71d84"
down_revision: str | Sequence[str] | None = "b3d61f0a97c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "unbilled_setup_fees"

_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(charge_kind text, charge_ref text)
RETURNS TABLE (owed_tenant_id uuid, onboarded_at timestamptz)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    org record;
BEGIN
    FOR org IN
        SELECT o.id, o.created_at FROM organizations o WHERE o.deleted_at IS NULL ORDER BY o.id
    LOOP
        PERFORM set_config('app.tenant_id', org.id::text, true);
        IF EXISTS (SELECT 1 FROM plans p WHERE p.setup_fee > 0)
           AND NOT EXISTS (
               SELECT 1 FROM one_time_charges c
                WHERE c.kind = charge_kind AND c.ref = charge_ref
           )
        THEN
            owed_tenant_id := org.id;
            onboarded_at := org.created_at;
            RETURN NEXT;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(_FUNCTION_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text, text)")
