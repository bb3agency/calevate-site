"""The big red switch can reach a dial the vendor is already holding

Revision ID: d5c81f30ab47
Revises: b2e6f10c94d7
Create Date: 2026-08-21 00:00:00.000000

D-432, closing the halt half of D-428.

WHAT WAS MISSING. `BolnaEngine.end_call` (`POST /call/{execution_id}/stop`, "Stop a
queued or scheduled call") was implemented, conformance-tested and called by nothing in
the tree. So `outbound_halted` stopped this platform PLACING dials and recalled none the
vendor had already accepted — and the vendor accepts more than it runs: `POST /call`
answers `status: queued` for every dial
(`bolna-findings/mirror/pages/api-reference/calls/make.md:25`) and surplus over the
account's concurrency ceiling is QUEUED, not rejected
(`bolna-findings/mirror/pages/pricing/outbound-calling-concurrency.md:41`), in a queue we
cannot see, cancel or DNC-scrub. On a trial account that ceiling is 2 against an outbound
pool of 6, so two thirds of a batch sits in it.

TWO OBJECTS, AND WHY EACH IS THE SHAPE IT IS
---------------------------------------------

1. `calls.recall_requested_at` — the instant this platform ASKED the vendor to drop a
   queued dial. Nullable; NULL means "never asked", which is the correct reading for
   every row that predates this revision.

   **It exists so a re-run is not a re-stop.** The recall job cannot settle the call row
   itself: the reconciliation poller is the guarantee of record (D-31, TRD §5) and a
   worker writing `failed` over a dial the vendor may still be deciding about would be a
   second answer to a question the poller already owns. So the row stays `queued` until
   the poller closes it, and without this column a second halt — or a retry of the same
   job — would re-POST a stop for every dial it already stopped, take the vendor's
   refusal for an already-stopped execution, and raise the "could not stop N dials" alarm
   on work that succeeded. A false alarm on the big red switch is worse than none: it is
   the one alarm an operator must be able to read literally mid-incident.

   Not append-only and not a ledger: it is a single one-way NULL→instant stamp on a
   mutable operational row, and the permanent history of who threw the switch is
   `audit_log` (`ops.halt_outbound`).

2. `queued_dial_scan(max_rows integer)` — the fleet-wide scan, SECURITY INVOKER, one
   statement per tenant, exactly the construction `dispatch_scan` (a8d4f21c9b06) uses and
   for the same reasons: `calls` is FORCE-RLS'd, so an untenanted probe returns zero rows
   for every tenant and reads as an empty queue; and a `tenant_session` per tenant was
   measured at 12,070 checkouts / 22.9s, which is not a shape to reach for while dialling
   is being stopped in an emergency.

   **NO TIME HORIZON, deliberately, and this is where it differs from `dispatch_scan`.**
   That function bounds its count with `ACTIVE_CALL_HORIZON` (1 hour) because it is
   answering "who is busy right now". This one is answering "what is the vendor still
   holding", and the whole reason the queue is dangerous is that it drains at the
   concurrency ceiling — a backlog older than an hour is the case that matters MOST, not
   an anomaly to filter out.

   `engine_call_id NOT LIKE 'local:%'` excludes the pre-dial intent rows
   (`agents.service.UNCONFIRMED_ENGINE_CALL_PREFIX`): those carry an id WE minted because
   the vendor has not named the dial yet, so there is nothing to send a stop for.
   `_reap_stuck_dialing` is what settles those, and it already does.

   `max_rows` is a PARAMETER rather than a literal for `dispatch_scan`'s reason — the
   caller states its own budget and the function makes no policy. The scan returns rows
   in `(tenant_id, created_at)` order so a capped run takes the oldest dials, which are
   the ones nearest to ringing.

INDEXES. None added. `ix_calls_outbound_live` is `(tenant_id, status, updated_at) WHERE
direction = 'outbound'` and its two leading columns answer this predicate; the residual
filters (`recall_requested_at IS NULL`, the `LIKE`) apply to a set already narrowed to one
tenant's live outbound dials, which is at most the platform line pool.

Reversible: `downgrade()` drops the function and the column. Nothing else reads either.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d5c81f30ab47"
down_revision = "b2e6f10c94d7"
branch_labels = None
depends_on = None

FUNCTION = "queued_dial_scan"

_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}(max_rows integer)
RETURNS TABLE (scanned_tenant_id uuid, call_id uuid, engine_call_id text)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    emitted integer := 0;
BEGIN
    FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r ORDER BY 1 LOOP
        EXIT WHEN emitted >= max_rows;
        PERFORM set_config('app.tenant_id', t::text, true);
        FOR call_id, engine_call_id IN
            SELECT c.id, c.engine_call_id
              FROM calls c
             WHERE c.direction = 'outbound'
               AND c.status = 'queued'
               AND c.recall_requested_at IS NULL
               AND c.engine_call_id NOT LIKE 'local:%'
             ORDER BY c.created_at
             LIMIT max_rows - emitted
        LOOP
            scanned_tenant_id := t;
            emitted := emitted + 1;
            RETURN NEXT;
        END LOOP;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "calls", sa.Column("recall_requested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(_FUNCTION_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(integer)")
    op.drop_column("calls", "recall_requested_at")
