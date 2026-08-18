"""five indexes the hot paths were asking for

Revision ID: c9e2a7b41d63
Revises: e7b45c19a308
Create Date: 2026-08-18 09:10:00.000000

D-205. D-192 counted 33 foreign-key child columns with no index leading with them and did not
add any, on one argument: *the parent is never hard-deleted, so the referential-integrity
scan is unreachable*. That argument is correct and it is the wrong test. A child column
earns an index when SOMETHING scans it, and the referential check is only one of the
things that can — four of the five indexes below are bought by ordinary application
queries, and one of them runs once per completed call.

Confirmed against the catalog rather than inherited: `pg_constraint` joined to
`pg_index.indkey[0]` reports **34** such columns at this revision (the extra one is
`kyc_records.verified_by_admin_id`, whose table postdates that pass), and one of the 34 —
`leads.assigned_to` — is a false positive, because `ix_leads_assigned_to` is PARTIAL on
`assigned_to IS NOT NULL` and `assigned_to = $1` under a strict operator proves that
predicate, so the partial index serves both the query and the RI probe. The honest
deficit is 33, and this migration takes 5 of them. The other 28 are enumerated with
their reasons in `docs/evidence/deepdive-dbscale.md`; the short version is that they are
insert-only references (`consent_ledger.call_id`, `kb_retrieval_logs.call_id`,
`qa_call_samples.call_id`, `recording_erasure_holds.call_id`), one-row-per-parent
pointers (`agents.system_prompt_id`, `campaigns.number_id`), or references to
`admin_users`, a table with a handful of rows that nothing deletes and nothing filters by.

MEASURED, not assumed. Private database at this revision, PostgreSQL 16.15, seeded with
8 tenants / 86,013 leads / 72,000 calls / 360,000 usage_events / 51,920 campaign_contacts
spread over 2.5 years, `VACUUM ANALYZE`d, every statement run as `calevate_app` with
`app.tenant_id` set — so RLS is in every plan. Times and buffers are
`EXPLAIN (ANALYZE, BUFFERS)`. The measured tenant holds 50,001 leads / 45,000 calls /
225,000 usage_events.

  ── ix_usage_events_call_id ────────────────────────────────────────────────────────
  usage_events (call_id) WHERE call_id IS NOT NULL

  FOUR call sites, one of them per completed call and one of them per poller tick:

    workers/pipeline.py:1777  SELECT 1 FROM usage_events WHERE call_id = :cid
                              AND tenant_id = :tid LIMIT 1      -- the metering guard
    workers/pipeline.py:2314  EXISTS (SELECT 1 FROM usage_events u WHERE u.call_id = c.id)
                              -- `_pipeline_settled`, per completed execution per tick
    api/admin/health.py:349   NOT EXISTS (…) -- "completed calls that metered nothing"
    api/billing/service.py:1552 the tier-correction idempotency probe

  Without it the only usable path is `ix_usage_events_tenant_id`, so each of those is a
  scan of the tenant's ENTIRE metering history to find at most five rows:

    metering guard          before  25.794 ms   3617 buffers  (224,995 rows discarded)
                            after    0.024 ms      4 buffers
    _pipeline_settled       before  27.812 ms   3621 buffers
                            after    0.080 ms     12 buffers
    unmetered-calls panel   before  51.876 ms   5658 buffers  (hash of 225,000 rows)
                            after   10.974 ms   2472 buffers

  The cost is one index insert per `usage_events` row (~5 per call) on a table that is
  append-only, so nothing ever repays it with an UPDATE — the same ledger arithmetic
  `e7c3d10a9f52` used to DROP an index is what justifies adding this one, because there
  the read had a composite to fall back on and here the read is O(tenant lifetime).
  PARTIAL on `call_id IS NOT NULL` because `number_rental` and the two `ai_assist_*`
  units carry no call: those rows are dead weight in this index and every probe binds a
  real id. A partial index still serves the RI check — `call_id = $1` under a strict
  operator implies `call_id IS NOT NULL`, which is how `ix_leads_assigned_to` already
  works in this schema.

  ── ix_usage_events_tenant_occurred ────────────────────────────────────────────────
  usage_events (tenant_id, occurred_at)

  Every money rollup is "this tenant, this month". Offered only `tenant_id`, a month is
  1.8% of the rows read:

    month rollup (range form)  before  33.788 ms  3822 buffers  (220,875 discarded)
                               after    2.058 ms    74 buffers

  This index is also what makes the `_IST_MONTH` rewrite in `billing/service.py` land:
  `to_char(occurred_at AT TIME ZONE 'Asia/Kolkata','YYYY-MM') = :month` is STABLE, so it
  can be neither an index condition nor an index expression, and the same aggregate took
  84.0 ms / 3829 buffers until the predicate became a half-open range on `occurred_at`.

  ── ix_leads_tenant_recent ─────────────────────────────────────────────────────────
  leads (tenant_id, updated_at DESC, id DESC) WHERE deleted_at IS NULL

  `crm.service.list_leads_page` orders by exactly this key. The ORDER BY was already
  argued at length in that docstring ("`id DESC` is not decoration") and nothing in the
  schema knew about it, so every page read the tenant's whole lead table and top-N
  sorted it:

    page 1 of the leads table  before  28.454 ms  1668 buffers  top-N heapsort of 50,001
                               after    0.064 ms     6 buffers  no sort node at all
    CSV export (LIMIT 20001)   before  44.889 ms  1665 buffers
                                       + external merge, Disk: 8224 kB
                               after    7.843 ms   797 buffers  no sort node at all

  The export number is the one that mattered most: `MAX_EXPORT_ROWS` bounds the file, it
  does not bound the SORT, and a spill to disk is the failure mode that arrives with the
  first client who has a real lead table.

  PARTIAL on `deleted_at IS NULL` because every reader of this ordering carries that
  predicate (`_lead_scope`'s first clause, unconditionally). It also keeps the index off
  soft-deleted rows, which is the population that only ever grows.

  Cost: `leads.updated_at` moves on every status change, note and assignment, so this
  index takes an insert per lead UPDATE. That is the price of the screen the client
  looks at all day, and it is paid on a table whose write rate is human-scale.

  DELIBERATELY NOT COVERING. `INCLUDE (status, data, …)` would make page 1 index-only,
  and `data` is a JSONB blob per lead — the index would become a second copy of the
  table on the one table clients keep the most rows in. Six buffers is not a number
  worth spending that to improve.

  ── ix_calls_tenant_started ────────────────────────────────────────────────────────
  calls (tenant_id, started_at DESC NULLS LAST, id DESC)

  `NULLS LAST` is written out because the DESC default is NULLS FIRST and the query is
  `ORDER BY c.started_at DESC NULLS LAST, c.id DESC` — an index declared without it does
  not serve that ordering.

    calls list page 1        before  38.953 ms  1770 buffers  top-N heapsort of 45,000
                             after    0.096 ms    15 buffers
    dashboard sentiment tile before  12.700 ms  1769 buffers
                             after    0.180 ms    26 buffers

  The dashboard polls (D-24), so the 7-day tiles are the highest-frequency reads in the
  product. `started_at` is written once and never moves, and `tenant_id` never moves, so
  this index does not cost the frequent `calls` UPDATEs their HOT path — only the insert.

  ── ix_campaign_contacts_last_call_id ──────────────────────────────────────────────
  campaign_contacts (last_call_id) WHERE last_call_id IS NOT NULL

  `workers/campaign_dispatch._settle_contact` runs once per completed campaign call and
  its own docstring says "it costs one indexed lookup and stops". It did not: with no
  index on `last_call_id` the planner reached the row through the tenant's whole contact
  list.

    settle by last_call_id   before   4.700 ms   650 buffers  (29,520 rows discarded)
                             after    0.020 ms     2 buffers

  Measured with 178 campaigns and 51,920 contacts, which is a year of a mid-sized
  account, not a stress figure. PARTIAL because a contact that has never been dialled
  has no last call and is not what this probe is looking for.

WHAT THIS DELIBERATELY DOES NOT INDEX, with the number attached:

  `calls (from_e164)` / `calls (to_e164)` for the DPDP subject-access export
  (`compliance/export.py:218`). Measured 7.8 ms / 1769 buffers on 45,000 tenant calls,
  linear in the tenant's call history. TWO indexes on the hottest-insert table in the
  schema, bought for a path that runs when a data principal files a request and has a
  statutory deadline measured in days. Revisit if erasure ever runs per call rather than
  per request.

  `call_variant_assignments (experiment_id)`. The experiment results screen filters by
  it, but `variant_id` — the column the results actually group by — is already indexed,
  and the table holds one row per experimented call, a small fraction of `calls`.

RLS (hard rule 1): this revision creates no table, so it ships no policy — the five
tables it touches already carry `ENABLE`d + `FORCE`d row security and their
`tenant_isolation` policies are unchanged. Two of the five decisions are ABOUT that
policy, though, and are stated rather than left implicit:

  * Three of the indexes LEAD with `tenant_id`, which is what makes the isolation
    predicate an index CONDITION rather than a post-scan filter. That is the property
    that keeps a tenant's query linear in its own rows instead of in the platform's, and
    it is the reason the composites are `(tenant_id, …)` and not `(…, tenant_id)`.
  * `ix_usage_events_call_id` and `ix_campaign_contacts_last_call_id` deliberately do
    NOT. Both probe a near-unique child key, so the index returns single-digit rows and
    `tenant_id = current_setting(...)` applies as a filter on top — visible as `Filter:`
    in the measured plans. Isolation is unchanged (the policy still refuses every row it
    refused before); what changes is only how few rows it has to refuse. Prefixing them
    with `tenant_id` would have made the index wider for no access path, and would have
    made it useless to the referential-integrity check, which probes the child column
    alone.

LOCKING: `CREATE INDEX CONCURRENTLY` inside `autocommit_block()`, the pattern
`d4a1e93b70c6` established here and for its reason: a plain build holds SHARE, which
blocks WRITES for its duration, and three of these five are on tables the voice pipeline
writes to continuously. The cost is that a failed build leaves an INVALID index; every
statement is `IF NOT EXISTS` / `IF EXISTS` so the retry is idempotent.

DOWNGRADE drops all five. A downgraded database is correct and slow, in exactly the five
places measured above.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9e2a7b41d63"
down_revision: str | None = "e7b45c19a308"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: name -> the CREATE body. Kept as data so upgrade and downgrade cannot disagree about
#: which indexes this revision owns.
INDEXES: dict[str, str] = {
    "ix_usage_events_call_id": "ON usage_events (call_id) WHERE call_id IS NOT NULL",
    "ix_usage_events_tenant_occurred": "ON usage_events (tenant_id, occurred_at)",
    "ix_leads_tenant_recent": (
        "ON leads (tenant_id, updated_at DESC, id DESC) WHERE deleted_at IS NULL"
    ),
    "ix_calls_tenant_started": "ON calls (tenant_id, started_at DESC NULLS LAST, id DESC)",
    "ix_campaign_contacts_last_call_id": (
        "ON campaign_contacts (last_call_id) WHERE last_call_id IS NOT NULL"
    ),
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, body in INDEXES.items():
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} {body}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in reversed(list(INDEXES)):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
