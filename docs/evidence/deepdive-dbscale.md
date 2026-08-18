# Deep dive: what the database DOES with the schema (D-206 … D-209)

18 Aug 2026. Ground: query plans. Every previous pass over this repo audited LOGIC — what
the code says, what the constraints promise, what the policies admit. Nobody had run
`EXPLAIN` on this schema at all, so nothing had ever asked the one question a multi-tenant
SaaS lives or dies on: **does a tenant's query cost scale with the tenant's data, with the
platform's data, or with neither?**

Everything below is marked **PROVEN** (executed) or **REASONED** (read). Almost everything
here is PROVEN, because a plan is not something you can reason your way to.

---

## Method, and where the numbers come from

**Not the shared development database.** `calevate` is ~50 revisions behind head, carries
41 tables instead of 62, and is internally inconsistent (its `alembic_version` disagrees
with its schema, so `upgrade head` fails on an object that already exists). Every number in
this document was taken on databases created for this pass and migrated from EMPTY through
the whole chain:

| database | what it is |
|---|---|
| `dbscale` | the measurement target — migrated base → head, then seeded (below) |
| `dbscale_test` | a clean, seeded database for the test runs |
| `dbscale_fresh` | a pristine control, for the round-trip schema diff |
| `dbscale_dirty` | a database carrying a first-party operator, for the `db-reset` proof |

`dbscale_fresh` and `dbscale_dirty` were dropped once they had answered their question; `dbscale` and `dbscale_test` are left in place so the numbers above can be re-taken rather than re-derived. **No shared database was migrated, downgraded, reset or truncated by this pass** — the two migrations it ships have been applied nowhere but the four databases named here.

**Seed.** 8 tenants, 86,013 leads, 72,000 calls, 360,000 usage_events, 432,000
transcript_turns, 172,026 lead_events, 51,920 campaign_contacts, 178 campaigns, 36,000
credit_ledger rows — spread over 2.5 years of `started_at`, then `VACUUM ANALYZE`d. The
tenant every measurement is taken as holds 50,001 leads / 45,000 calls / 225,000
usage_events; the other seven exist so that `tenant_id = X` is a real predicate and not a
100%-selective one. **Every statement was run as `calevate_app` with `app.tenant_id` set**,
so the RLS predicate is inside every plan quoted here. PostgreSQL 16.15.

Nothing in this pass touched another agent's tenants, and the two migrations it ships were
verified up/down/up on a throwaway before going anywhere else.

---

## 1. FIXED — the unindexed foreign-key child columns, counted and then argued one at a time

### The census (PROVEN)

`pg_constraint` joined to `pg_index.indkey[0]` reports **34** foreign-key child columns
with no index leading with them — not 33. The count was re-derived rather than inherited,
and then confirmed a second time against `calevate_replay`, an independently-built
replay of the whole chain: **the two lists are identical, 34 for 34.**

Of those 34, **one is a false positive**: `leads.assigned_to` is covered by
`ix_leads_assigned_to`, which is PARTIAL on `assigned_to IS NOT NULL`. A catalog census
cannot see that, but the planner can — `assigned_to = $1` uses a strict operator, which
proves `assigned_to IS NOT NULL`, so the partial index serves both the query and the
referential-integrity probe. **The honest deficit is 33.** This pass takes 5 of them.

### Why D-192's argument for taking none of them was the wrong test

That pass declined on one ground, and it is factually correct: the referential-integrity
scan a missing child index causes is only reachable on a parent DELETE or key UPDATE, and
`calls`, `leads` and `agents` are never hard-deleted (grep-confirmed again here: the only
`DELETE FROM` statements in `apps/` target eleven small tables, none of them a parent of
these columns).

**A child column earns an index when SOMETHING scans it, and the RI check is only one of
the things that can.** Four of the five below are bought entirely by ordinary application
queries; the fifth is bought by a query the post-call pipeline runs on every completed
call. The RI benefit is a by-product.

### The five, with the plan each one bought (all PROVEN)

| index | who asks for it | before | after |
|---|---|---|---|
| `ix_usage_events_call_id`<br>`(call_id) WHERE call_id IS NOT NULL` | `pipeline` metering guard, per completed call | 25.794 ms / 3,617 buffers<br>224,995 rows discarded | **0.024 ms / 4 buffers** |
| | `_pipeline_settled` EXISTS, per poller tick | 27.812 ms / 3,621 buffers | **0.080 ms / 12 buffers** |
| | admin health "calls that metered nothing" | 51.876 ms / 5,658 buffers | **10.974 ms / 2,472 buffers** |
| `ix_usage_events_tenant_occurred`<br>`(tenant_id, occurred_at)` | every money rollup, per invoice/usage panel | 33.788 ms / 3,822 buffers<br>220,875 rows discarded | **2.058 ms / 74 buffers** |
| `ix_leads_tenant_recent`<br>`(tenant_id, updated_at DESC, id DESC) WHERE deleted_at IS NULL` | Leads table, page 1 | 28.454 ms / 1,668 buffers<br>top-N heapsort of 50,001 | **0.064 ms / 6 buffers**, no sort node |
| | Leads CSV export (`LIMIT 20001`) | 44.889 ms / 1,665 buffers<br>**external merge, Disk: 8,224 kB** | **7.843 ms / 797 buffers**, no sort node |
| `ix_calls_tenant_started`<br>`(tenant_id, started_at DESC NULLS LAST, id DESC)` | Calls list, page 1 | 38.953 ms / 1,770 buffers<br>top-N heapsort of 45,000 | **0.096 ms / 15 buffers** |
| | dashboard sentiment tile (polled) | 12.700 ms / 1,769 buffers | **0.180 ms / 26 buffers** |
| `ix_campaign_contacts_last_call_id`<br>`(last_call_id) WHERE last_call_id IS NOT NULL` | `_settle_contact`, per completed campaign call | 4.700 ms / 650 buffers<br>29,520 rows discarded | **0.020 ms / 2 buffers** |

Three details worth keeping:

* **The export's spill is the one that would have arrived first.** `MAX_EXPORT_ROWS` bounds
  the FILE; it never bounded the SORT. 8 MB to disk on one tenant's export, on a request
  that already builds the whole CSV in memory.
* **`NULLS LAST` is written out on `ix_calls_tenant_started`** because `DESC` defaults to
  `NULLS FIRST` and the query asks for `DESC NULLS LAST`. An index declared the obvious way
  is a correct index for a different ordering, and the sort comes back. Pinned by a test.
* **`_settle_contact`'s docstring promised "one indexed lookup and stops".** It reached the
  row through the tenant's entire contact list. The docstring was the finding.

### What was deliberately NOT indexed, and why (28 columns)

| group | columns | reason |
|---|---|---|
| references to `admin_users` | `first_campaign_reviews.decided_by_admin_id`, `kyc_records.verified_by_admin_id`, `preference_scrub_runs.recorded_by_admin_id`, `qa_call_samples.reviewed_by_admin_id`, `tenant_feature_flags.set_by_admin_id`, `whatsapp_alert_optin_ledger.recorded_by_admin_id`, `platform_secrets.created_by`, `platform_settings.updated_by` | the parent has a handful of rows, is never deleted, and nothing filters a child by it. These are provenance stamps read back with the row that carries them. |
| insert-only `call_id` references | `consent_ledger.call_id`, `kb_retrieval_logs.call_id`, `qa_call_samples.call_id`, `recording_erasure_holds.call_id` | grep-confirmed: written on INSERT, never a WHERE. `qa_call_samples` already carries `UNIQUE(tenant_id, call_id)` for its own dedupe, and `recording_erasure_holds` is read through `ix_recording_erasure_holds_due`. |
| one-row-per-parent pointers | `agents.system_prompt_id`, `agents.live_prompt_id`, `agents.extraction_schema_id`, `campaigns.number_id`, `campaigns.dlt_template_id`, `prompt_experiments.promoted_variant_id`, `prompt_experiment_variants.prompt_version_id`, `one_time_charges.plan_id`, `first_campaign_reviews.reviewed_campaign_id` | the traversal is always parent→child by primary key, never child→parent by this column. |
| `agent_id` on small config tables | `campaigns.agent_id`, `phone_numbers.agent_id`, `inbound_webhooks.agent_id` | one row per campaign / number / webhook. No query filters these tables by agent; agents are soft-deleted, never removed. |
| `users` references | `lead_saved_views.user_id`, `whatsapp_alert_optin_ledger.user_id`, `whatsapp_alert_optin_ledger.recorded_by_user_id` | `users` rows are deactivated, never deleted, so even the CASCADE on `lead_saved_views` is unreachable. `lead_saved_views` is bounded by views-per-user. |
| erasure bookkeeping | `recording_erasure_holds.request_id`, `recording_erasure_holds.tenant_erasure_id` | one hold set per request; the sweep reads by `(tenant_id, erase_after)`, which is indexed. |
| `calls.lead_id` | | **the interesting negative.** Nothing in `apps/` filters `calls` by `lead_id` — the join always runs `calls → leads` by primary key. A synthetic `WHERE lead_id = ?` is a parallel sequential scan (29.3 ms), which is what an index would fix, and there is no caller to fix it for. Leads are never hard-deleted (`workers/retention.py` says so in a comment), so the RI path is unreachable too. |
| `call_variant_assignments.experiment_id` | | the experiment results screen filters by it, but `variant_id` — the column the results actually group by — is already indexed, and the table holds one row per experimented call. On-demand admin/owner read, not a hot path. |

Also declined, with the number attached: **`calls (from_e164)` and `calls (to_e164)`** for
the DPDP subject-access export (`compliance/export.py:218`). Measured 7.781 ms / 1,769
buffers over 45,000 tenant calls to find 3 — linear in the tenant's call history, PROVEN.
Two indexes on the highest-insert-rate table in the schema, bought for a path that runs
when a data principal files a request and has a statutory deadline measured in days.
**What re-opens it:** erasure running per call rather than per request.

### RLS considerations (hard rule 1)

The migration creates no table, so it ships no policy; all five tables already carry
`ENABLE`d + `FORCE`d row security and their `tenant_isolation` policies are untouched. Two
of the five decisions are ABOUT the policy:

* three indexes LEAD with `tenant_id`, which is what makes the isolation predicate an index
  CONDITION rather than a post-scan filter — the property that keeps a tenant's query linear
  in its own rows rather than in the platform's;
* `ix_usage_events_call_id` and `ix_campaign_contacts_last_call_id` deliberately do not.
  Both probe a near-unique child key, so `tenant_id = current_setting(...)` applies as a
  `Filter:` over single-digit rows — visible in the measured plans. Isolation is unchanged;
  what changes is how few rows the policy has to refuse. Prefixing them with `tenant_id`
  would buy no access path and would make them useless to the RI check, which probes the
  child column alone.

**Migration `c9e2a7b41d63`**, `CREATE INDEX CONCURRENTLY` in an `autocommit_block()` (the
pattern `d4a1e93b70c6` established here, for the reason it gives). Reversible: `DROP INDEX
CONCURRENTLY IF EXISTS` for all five.

**Test:** `tests/hot_path_index_test.py` — 12 tests. Sabotage-verified: with the five
indexes dropped, **11 of 12 go red**; the twelfth is the predicate-shape assertion, which is
about `billing/service.py` and correctly stays green.

---

## 2. FIXED — a tenant session could hard-DELETE its own `organizations` row (PROVEN)

### The proof

```
BEGIN;
SELECT set_config('app.tenant_id', '01a00dfe-0000-7000-8000-00000000dead', true);
DELETE FROM organizations WHERE id = '01a00dfe-0000-7000-8000-00000000dead';
-- DELETE 1
ROLLBACK;
```

as `calevate_app`, against a database at `e7b45c19a308`, on a childless organization.

`organizations`' `tenant_isolation` policy is `FOR ALL` with a permissive `USING` admitting
the session's own id and a `WITH CHECK` saying the same — and **`WITH CHECK` is not
consulted on DELETE.** That is the third time this exact PostgreSQL fact has cost this
schema a rule: `e4f2a86b13d7` (dnc_list DELETE), `e7b45c19a308` (dnc_list UPDATE), and now
the tenancy anchor.

### Why it matters, and why it is not an incident today

Every one of the 43 tenant tables carries `tenant_id REFERENCES organizations(id) ON DELETE
RESTRICT`. That row is what makes "this data belongs to somebody" a fact the database
enforces, and it is the subject of the erasure certificate and the anchor of the retention
countdown.

It is not an incident because no route or worker issues the statement, and a real
organization carries children behind RESTRICT. **The protection today is the foreign keys,
by accident, rather than the policy, by design** — and "by accident" runs out the first time
a tenant's last child row is deletable through a route, which several already are
(`memberships`, `invitations`, `lead_saved_views`, `tenant_feature_flags`, `dnc_list`).

### The fix, and the test it had to move

**Migration `d1b8f30c94a7`** adds `organizations_delete_admin_only`, RESTRICTIVE FOR
DELETE, `USING (current_setting('app.admin', true) = 'on')`. Not `USING (false)`: removing
a mistyped prospect that never got children is a real operator task, `admin_session()` is
the one factory that sets `app.admin` and is minted only after an admin-realm principal is
verified, and the existing `USING` clause already grants that session the visibility this
policy now requires. What must be impossible is a TENANT doing it.

`tests/dispatch_scale_test.py` hard-deleted organizations **from a tenant session** as its
cleanup, and its docstring argued for that choice on the grounds that `admin_session` is
"the ADMIN-REALM widening and a fixture is not an admin-realm principal". That instinct is
right and the trade runs the other way: **the cleanup moved, not the schema.** The fixture
now removes the organization through `admin_session()` and asserts `rowcount == 1` — RLS
filters rather than raises, so a cleanup left on the tenant session would have gone on
"succeeding" while leaking every organization it minted. The docstring already promised the
cleanup fails loudly; the rowcount assertion is what makes that true. `dispatch_scale_test`
passes with the move.

**Test:** `tests/organizations_delete_rls_test.py` — 5 tests. Sabotage-verified: with the
policy dropped, **2 go red** (the named DELETE and the unqualified one) and the 3 controls
stay green, so the red is the subject and not the harness.

| probe | before | after |
|---|---|---|
| tenant deletes its own org by id | DELETE 1 | DELETE 0 |
| tenant issues `DELETE FROM organizations` unqualified | DELETE 1 | DELETE 0 |
| untenanted session deletes an org | DELETE 0 | DELETE 0 |
| admin session deletes a childless org (must still work) | DELETE 1 | DELETE 1 |
| tenant SELECTs and soft-deletes its own org (must still work) | ok | ok |

---

## 3. FIXED — the IST billing month was unindexable by construction (PROVEN)

`billing/service._IST_MONTH` filtered with
`to_char(occurred_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') = :month`. That expression is
CORRECT — D-186 fixed a real timezone defect to arrive at it — and it is **STABLE, not
IMMUTABLE**, which means PostgreSQL will use it neither as an index condition nor as an
index EXPRESSION. No index could ever have helped it. Every money rollup therefore read the
tenant's entire metering history one row at a time:

```
rung_seconds, current month, 225,000 tenant rows
  before   Parallel Index Scan using ix_usage_events_tenant_id
           Filter: to_char(...) = ...   Rows Removed: 220,821     84.021 ms / 3,829 buffers
  after    Bitmap Index Scan on ix_usage_events_tenant_occurred
           Index Cond: (tenant_id = ... AND occurred_at >= ... AND occurred_at < ...)
                                                                  2.222 ms /    76 buffers
```

**The fix keeps every sentence of D-186's argument.** `plans.ist_month_window(month)` builds
the same IST month from the same NAMED zone — in Python, so the session's `TimeZone` still
cannot reach the answer — and hands SQL two `timestamptz` bounds. Half-open, `>= start` and
`< next_start`, the same SQL:2011 application-time reading `plan_in_effect_sql` already
uses, so no instant lands in two months or in neither. `ist_month_end` is now derived from
it rather than recomputing the rollover, so there is exactly one place that knows when a
month ends.

`_IST_MONTH` survives, narrowed to what only it can do: RENDER a row's own month for
`ai_quota._INSERT_USAGE`'s `RETURNING`, which is what keeps the platform brake's counter
stamped by the database's clock rather than the API process's. The split is by what the SQL
does with the month, not by taste, and it is stated in both places.

Three call sites moved: `rung_seconds`, the usage-panel call count, and
`ai_quota._USAGE_SQL`. **481 money tests pass.** Sabotage-verified: reverting the constant
to the rendered form turns `test_the_billing_month_predicate_is_a_range_a_btree_can_use`
red.

---

## 4. FIXED — two unbounded reads (PROVEN)

### The facet rail allocated one dict entry per distinct value in the tenant's data

`crm.service.lead_facets` ran `GROUP BY 1 ORDER BY n DESC` with **no LIMIT** and built
`observed = {value: count for …}` from the whole result — up to eight times per page render.
`MAX_FACET_VALUES`' own comment says it bounds the undeclared values "which is otherwise
unbounded", and it did: it bounded what was RENDERED, one layer too late.

A facet is an enum field by DECLARATION only. The extractor writes whatever the model
produced, so a field whose declaration changed — or whose model went off-script — holds as
many distinct strings as the tenant has leads.

The query now carries `LIMIT :facet_cap`, and **the ordering is declared-first**:
`ORDER BY ((l.data ->> :facet_key) = ANY(:facet_declared)) DESC, n DESC, 1 ASC`. A bare
LIMIT would have dropped a declared value ranking below the cap, and the zero-fill would
then have reported it as 0 — a filter claiming a value nobody has, which is worse than the
unbounded query it replaced.

Two tests in `tests/lead_columns_test.py`: one drives 60 undeclared values and asserts the
statement the database was asked carries a `LIMIT` (**red without the fix**), the other
makes a declared value the rarest thing in the table behind 60 undeclared ones and asserts
it comes back with its true count — the invariant a future naive LIMIT would break.

Measured, and recorded rather than pre-optimised: one facet over 50,001 leads is 43.4 ms /
1,661 buffers. `lead_facets`' docstring claims the rail is "nowhere near" its researched
200 ms budget; at one or two enum fields (what the shipped vertical templates declare) that
is true, and at the eight the function permits it is ~350 ms of sequential round trips and
it is not. No index changes that — a facet count reads every row in scope by definition —
so the docstring now carries the measurement and the threshold.

### The after-hours tile shipped a JSONB blob once per call

`agents.business_hours.count_after_hours_calls` joined `agents` to `calls` and selected
`a.business_hours` **beside every call row** — the same few hundred bytes of opening hours
repeated across a 7-day window, on an endpoint the dashboard polls (D-24).

Now two queries: the hours once (a handful of agents), the calls separately as
`(agent_id, started_at)`. The Python arithmetic is untouched, which was the point of
evaluating it in Python in the first place. What remains is honest and has a number: one
row per call in the window, bounded by PLATFORM CAPACITY rather than tenant history —
`PLATFORM_LINES_TOTAL` is 10 concurrent lines, so the whole platform cannot produce more
than roughly 34k calls in seven days. 30 after-hours/dashboard tests pass.

### Bounded already, checked and left alone

An AST sweep over every `text(...)` literal in `apps/**` found 185 SELECTs with no LIMIT.
Read one at a time, all but the two above are single-row key lookups, aggregates returning
one row, or sets bounded by something other than tenant data (chunks per KB source, statuses
per campaign, job names in the outbox). `list_leads_page` and `list_calls` are paged;
`export_leads` is capped at `MAX_EXPORT_ROWS`; the DPDP export is unbounded by DESIGN and
must stay so — a subject access request that returns a page is not a subject access request.

---

## 5. FIXED — `make db-reset` was a rollback, not a reset (PROVEN, by causing it)

`make db-reset` ran `alembic downgrade base`. A downgrade UNDOES revisions in order, so it
can be refused by the DATA the database happens to hold — and a developer's database always
holds some. On a scratch database at head, seeded, with one first-party operator
(`admin_users.clerk_user_id IS NULL`, which is exactly what `scripts/bootstrap_admin.py`
writes):

```
sqlalchemy.exc.IntegrityError: (psycopg.errors.NotNullViolation)
  column "clerk_user_id" of relation "admin_users" contains null values
  [SQL: ALTER TABLE admin_users ALTER COLUMN clerk_user_id SET NOT NULL]
```

and it stopped MID-CHAIN: `alembic_version` at `b3d9f6a2c815` with 62 tables still present.
**That stranded shape is not hypothetical** — it is the state the shared development
database was found in, where the version table and the schema disagreed and every
subsequent `upgrade head` failed on an object that already existed.

`b3d9f6a2c815`'s refusal is CORRECT and is not touched: past that revision a downgrade is a
restore, not a rollback. What was wrong was routing a reset through it.

`scripts/db_reset.py` drops and recreates `public`, re-granting what the drop took with it.
O(1) in revisions instead of O(74), it cannot be refused by data because there is no data
left to refuse with, and it cannot half-apply. It is also what Django, Rails and Prisma all
do. **Guarded on two independent facts** — `APP_ENV=local` AND a loopback DSN host — because
either alone is one misconfiguration away from being wrong, and there is deliberately no
`--force`. PROVEN end to end: the new sequence takes the database the old one stranded back
to 62 tables at head, seeded.

**Test:** `tests/db_reset_test.py` — 4 tests: both refusals, the missing-owner-DSN refusal,
and that the Makefile recipe actually calls the script (a script nothing invokes is the
half-wired change this repo names by name). The destructive path is deliberately not
driven: a test that drops the schema out from under four concurrent suites is a worse defect
than the one it checks.

---

## 6. RLS cost — the predicates are index-usable, with one named exception (PROVEN)

44 tenant-scoped tables. **37 carry the plain `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`**,
and every plan captured in this document shows it as an `Index Cond:` rather than a
`Filter:` — `current_setting` is STABLE, so it is evaluated once per query and the equality
is an ordinary indexable qual. The isolation predicate costs nothing beyond the index probe
it rides on.

Seven policies are OR-forms, six of them documented asymmetries on small or otherwise-keyed
tables (`dnc_list`, `engine_agent_routes`, `inbound_webhooks`, `invitations`, `memberships`).
`dnc_list` — the one on the dial path — is clean: `ix_dnc_list_phone_e164` serves the scrub's
`phone_e164 = ANY(...)` directly.

**The exception is `organizations`**, whose `USING` is
`(id = GUC) OR (id IN (SELECT tenant_id FROM memberships WHERE user_id = GUC)) OR (app.admin = 'on')`.
An OR containing a subquery cannot be an index condition, so an UNKEYED read of that table
is a sequential scan of the entire platform's client list. Measured on the shared database's
34,470 organizations, from an ordinary tenant session:

```
Seq Scan on organizations   Rows Removed by Filter: 34470   596 buffers   9.677 ms
```

**This is bounded by the number of clients, not by any tenant's data**, and the reads that
matter are all keyed: `WHERE slug = ...` plans as an index scan on `uq_organizations_slug`
(0.449 ms) and `WHERE id = ...` as a primary-key scan, both with the policy applying as a
cheap filter afterwards. The one unkeyed read is the ADMIN client directory
(`admin/service.py:601`), which is admin-realm, already documented as N+1 by construction,
and already carries its own recorded deferral ("revisit with a materialized `tenant_health`
table if the client list ever gets long enough to notice"). **That deferral now has a
number**: at 34,470 rows it is one sequential scan plus 34,470 nested tenant sessions of
five queries each. Not changed here — it is an admin surface with a founder's decision
already attached, and narrowing it is an API-contract change rather than an index.

---

## CLEARED — checked by execution and correct

| claim | how | verdict |
|---|---|---|
| The whole chain replays from empty | `alembic upgrade head` on three new databases | PROVEN, 62 tables at `d1b8f30c94a7` |
| This pass's two revisions are reversible | `downgrade e7b45c19a308` then `upgrade head` on `dbscale_test` | PROVEN, both directions clean |
| Round-trip fidelity | `pg_dump -s` of the down/up database vs a pristine chain | PROVEN byte-identical |
| The FK census is not an artefact of one database | same query on `calevate_replay`, built independently | PROVEN: 34 columns, identical lists |
| The DNC scrub is indexed | `pg_indexes` + the scrub's own predicate | PROVEN: `ix_dnc_list_phone_e164` leads with the probed column |
| The campaign dispatch scan is already O(live calls), not O(history) | the `calevate_dispatch_scan` probe re-run after this pass's indexes landed | PROVEN: still `Index Only Scan using ix_calls_outbound_live`, `Heap Fetches: 0`, 0.173 ms — `a8d4f21c9b06` had measured and fixed this surface, and nothing here disturbed it |
| The due-contact claim is indexed | `campaign_contacts` claim query at 51,920 contacts | PROVEN: `ix_campaign_contacts_due` bitmap scan, 0.129 ms |
| The DPDP subject-access export is unbounded BY DESIGN and stays so | read | REASONED: a subject access request that returns a page is not a subject access request |
| The new indexes did not move an existing plan onto a worse one | `ix_leads_tenant_id`-driven queries (status counts, facets) re-measured after | PROVEN: same node types, same buffers (1,665) |
| The index doctrine's existing pins still hold | `prefix_index_audit_test`, `credit_ledger_index_prune_test`, `usage_events_unique_index_test`, `orm_schema_fidelity_test` | PROVEN green |
| Guardrails | `ruff check`, `ruff format --check`, `mypy apps packages`, `check_rls_coverage`, `check_metadata_columns` | PROVEN clean |
| Targeted suites | 97 schema/RLS/index tests + 638 crm/campaign/pipeline/retention/export tests + 481 money tests | PROVEN green |

---

## STILL OPEN, and whose it is

**Ours, named:**

* The dashboard's `avg_duration` tile has **no time window** —
  `avg(duration_s) FILTER (WHERE status = 'completed') FROM calls` over the account's whole
  history, on a polled endpoint, and `calls` rows are never deleted. No index can fix an
  aggregate over every row; the fix is a window, and a window changes a number the client
  reads. **What closes it:** a decision about what the tile means. Everything beside it in
  that query is already 7-day windowed.
* The admin client directory's N+1 (§6 above) — deferral already recorded, number now
  attached.
* The facet rail exceeds its own 200 ms budget at eight enum facets on a six-figure lead
  table (§4). No shipped template gets near eight. **What closes it:** a single round trip,
  which the function's docstring already argues against for one and two facets.

**Not ours:** nothing in this pass was blocked externally.
