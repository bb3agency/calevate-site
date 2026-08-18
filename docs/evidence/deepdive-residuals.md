# The residuals: the three things the db-scale pass could not close, and two nobody owned

18 Aug 2026. Follows `deepdive-dbscale.md`, which fixed the hot paths and ended with a
"STILL OPEN, and whose it is" section. This closes that section, plus D-162's open fork
and R-9 from `audit-reliability.md`. Decisions **D-215 … D-219**.

Everything below is marked **PROVEN** (executed) or **REASONED** (read). Two of the five
items are decisions rather than optimisations, and both are argued rather than measured —
they are marked as such.

---

## Method, and where the numbers come from

**Not the shared development database, and not `calevate_replay` either.** Measurements
were taken on `calevate_resid`, created for this pass as `CREATE DATABASE calevate_resid
TEMPLATE calevate_replay` (head, `d1b8f30c94a7`) and then seeded with tenants of this
pass's own — ids in the `01b0dead-…` range so nothing collides with another agent's
fixtures. `calevate_resid_mig`, a second template copy, was used for the up/down/up
verification of the one migration this pass ships and nothing else.

**Seed.** 8 tenants, 85,001 leads, 72,000 calls spread over 2.5 years of `started_at`,
then `VACUUM ANALYZE`d. The tenant every measurement is taken as holds **50,001 leads and
45,000 calls**; the other seven carry the rest so `tenant_id = X` is a real predicate.
Each lead's `data` jsonb carries eight enum-shaped keys plus a free-text note, which is
what makes the eight-facet ceiling measurable rather than hypothetical. **Every statement
was run as `calevate_app` with `app.tenant_id` set**, so the RLS predicate is inside every
plan quoted here. PostgreSQL 16.15.

**No shared database was migrated, downgraded, reset or truncated.** The one migration
this pass ships was applied to `calevate_resid_mig` (up/down/up) and to `calevate_replay`,
the database this session was told to use. Redis was not flushed.

---

## 1. FIXED — the dashboard's `avg_duration` tile had no window, and neither did the statement around it (PROVEN)

### What it was

```sql
SELECT count(*) FILTER (WHERE started_at::date = :today) AS calls_today,
       count(*) FILTER (WHERE started_at >= :since)      AS calls_7d,
       avg(duration_s) FILTER (WHERE status = 'completed') AS avg_duration,
       count(*) FILTER (WHERE started_at >= :since AND (…IST hour…)) AS after_hours
FROM calls
```

Three of the four columns carried a seven-day bound as a `FILTER`; the average carried
none. So the tile was the mean of every completed call the account had ever made, on an
endpoint the dashboard polls (D-24), against a table nothing ever deletes from — and
because the unbounded column was in the same statement, **the FROM clause could not be
bounded either**, so all four numbers were computed from a full scan of the tenant's call
history.

### The decision, which is the part that was actually open

The previous pass stopped here correctly: no index fixes an aggregate that must visit
every row, and a window changes a number the client reads.

**Seven days, not thirty**, against the obvious default:

* every other bounded figure on this screen is seven days, and `DashboardOut` already
  spells the window into the NAME of each one — `calls_7d`, `leads_new_7d`,
  `after_hours_captured_7d`, `daily_7d`. The average was the only bounded figure whose
  name said nothing, because until now it had nothing to say;
* the screen already carries three windows (today, 7 days, this month). A 30-day average
  would be a fourth, and close enough to "this month" to be read as it;
* **the thirty-day reading already exists and is already bounded.** `crm/performance.py`
  takes `days` (default 30) and returns `avg_duration_s` with the window as a field on the
  same response. Two labelled answers on two screens is one answer per question; a second
  unlabelled average would have been two answers to one.

Said out loud in three places rather than slipped in: the field is `avg_duration_s_7d`,
the tile's hint reads "Completed calls, last 7 days" instead of "Completed calls only",
and the call site carries the argument above.

### The plan (PROVEN), 45,000 tenant calls

```
before  Aggregate  (actual time=27.102..27.104)
          ->  Index Scan using ix_calls_tenant_id on calls   rows=45000
        Buffers: shared hit=1017                             Execution Time: 27.165 ms

after   Aggregate  (actual time=0.767..0.768)
          ->  Bitmap Heap Scan on calls                      rows=349
                ->  Bitmap Index Scan on ix_calls_tenant_started
                      Index Cond: (tenant_id = … AND started_at >= now() - '7 days')
        Buffers: shared hit=61                               Execution Time: 0.842 ms
```

Re-run three times after the change: 0.842 / 0.904 / 0.957 ms, 61 buffers each. The index
is `ix_calls_tenant_started`, which **D-206 added a week ago and which this query could
not use** while one of its four columns reached outside the window.

`calls_today` is unchanged by the move — today is a subset of the last seven days — and
`calls_7d` stops needing a `FILTER` at all, because the statement is now the filter.

**Test:** `tests/dashboard_avg_duration_window_test.py`, 5 tests. Sabotage-verified: with
the window reverted, **3 go red** (the two behavioural ones and the SQL-shape assertion);
the two that stay green are the "other tiles did not change meaning" control and the field
name, which is about `schemas.py`. The red is the subject.

---

## 2. FIXED — the facet rail is bounded by its own budget, and D-209's LIMIT stops spilling 13 MB per facet (PROVEN)

Two things, and the second was not on anybody's list.

### 2a. The ceiling is derived now, because a ceiling nothing enforces is a promise

`MAX_FACET_FIELDS` was 8, on the researched ground that 5-7 filter groups per results page
is where a rail stops being scannable. That is a good argument about scannability and it
was the only argument the number had. `lead_facets` runs one query per facet, so eight
facets is eight sequential passes over the tenant's whole lead table, against a docstring
promising the rail was "nowhere near" its researched 200 ms budget.

**"Make it fit" was written and measured first.** Two single-round-trip rewrites, both
against the same 50,001-lead tenant:

| shape | result |
|---|---|
| `CROSS JOIN unnest(keys)` + per-facet `row_number()` window | **209-221 ms**, `external merge  Disk: 4224kB` × 3 workers |
| `GROUP BY GROUPING SETS ((1),(2),…,(8))` | **223 ms**, eight sorts |
| eight sequential queries, as shipped before this pass | ~610 ms |
| eight sequential queries, after 2b below | ~400 ms |

Both rewrites are ~2.8× better than the sequential loop and **both are still over the 200
ms budget.** The reason is structural: PostgreSQL has no `n_distinct` for
`data ->> 'key'` where the key is bound at runtime — a jsonb key cannot carry statistics,
and `CREATE STATISTICS` on an expression needs the key at DDL time, which is per tenant
and client-authored. So it estimates every row as its own group and picks a sort.
`SET enable_sort = off` shows the floor is **111.2 ms** — real, and unreachable by any
query that can be shipped.

So the rewrite buys a 2.8× speedup, does not buy the budget, and costs the readability
its first rejection was argued on. **The count is bounded instead:**

```python
FACET_RAIL_BUDGET_MS = 200        # researched, the promise
FACET_QUERY_COST_MS  = 50         # measured at the six-figure ceiling, rounded up
MAX_FACET_FIELDS = FACET_RAIL_BUDGET_MS // FACET_QUERY_COST_MS      # 4
```

Arithmetic rather than a literal, so making a facet cheaper or widening the budget raises
the cap by itself and re-typing the cap does not.

**The refusal a client can act on already existed and is unchanged**: the first
`MAX_FACET_FIELDS` facetable fields IN SCHEMA ORDER, plus `FacetSet.omitted_field_count`,
which the rail renders as *"N more capture fields are filterable but not shown here — ask
us to reorder your capture list if you need one of them."* Reordering the extraction
schema is an action an operator can take today. No shipped vertical template declares more
than two enum fields, so four is twice what anything on the platform uses.

### 2b. D-209's LIMIT made every facet 1.5× slower and spilled 13 MB to disk

Found while measuring 2a, and it is a regression the previous pass introduced while fixing
a real unboundedness.

```
D-209's shape:  GROUP BY 1 ORDER BY (declared) DESC, n DESC, 1 ASC LIMIT :cap

  Sort (order key)  ->  GroupAggregate  ->  Sort (group key, width=285)
                                              Sort Method: external merge  Disk: 13296kB
  Buffers: shared hit=2682, temp read=1662 written=1665     70.5 – 74.9 ms
```

The planner estimates ~249 groups, decides a sorted `GroupAggregate` is as cheap as a
hash, and the sort it then chooses runs over **full-width lead rows** — 13 MB written and
read back, per facet, per page render, on a query that never needed a sort at all.

Fencing the aggregate off from the ordering fixes the plan without changing the answer:

```sql
WITH counted AS MATERIALIZED (
  SELECT l.data ->> :facet_key AS value, count(*) AS n
  FROM leads l WHERE … GROUP BY 1
)
SELECT value, n FROM counted
ORDER BY (value = ANY(:facet_declared)) DESC, n DESC, value ASC
LIMIT :facet_cap
```

```
after   Sort Method: quicksort  Memory: 2611kB   (and 25kB for the ordering)
        Buffers: shared hit=2682, temp 0          47.4 / 49.6 / 50.6 ms
```

Same rows, same order, same LIMIT, **1.5× faster with zero temp I/O**. `AS MATERIALIZED`
is the documented way to say "evaluate this once, on its own terms" and is already this
repo's spelling for the same intent in `claim_outbox_batch` and the campaign dispatcher.

`ORDER BY (value = …)` referring to the SELECT alias was tried and is not legal SQL —
PostgreSQL allows a bare output-column name in `ORDER BY`, not an expression over one — so
the CTE is what makes the projection narrow.

**Tests:** three in `tests/lead_columns_test.py` (the derived ceiling as arithmetic, the
`omitted_field_count` refusal over a 7-enum schema, and the statement shape).
Sabotage-verified: with `MAX_FACET_FIELDS = 8` and the `MATERIALIZED` removed, **2 go
red**, one per fix, and the 26 existing tests in that file stay green.

---

## 3. PARTLY FIXED — the admin directory's N+1, with the part that is not closeable named (PROVEN)

`admin.service.tenant_overview` is N+1 by construction and says so: the directory comes
from an `app.admin` session, the counters from a per-tenant RLS session, because
`app.admin` does not unlock `calls` or `leads`. That trade is recorded and is not what
changed.

### The number the deferral did not have

312 accounts, warm: **1,027 ms**, 3.3 ms per account. Broken down per account:

| term | cost |
|---|---|
| connection checkout + `pool_pre_ping` + `set_config` | 0.90 ms |
| the four counts (agents / calls 7d / leads / last call) | 0.55 ms |
| **`read_tenant_holds`** | **0.95 ms** |
| `spend_capped` | 0.45 ms |

`holds` being the largest term is the finding, and what it was spending it on is the
defect: `kyc_blocker` and `first_campaign_hold_blocker` both open with
`plan_tier_of(...) not in SELF_SERVE_TIERS -> None`, so **for a `managed` account
`read_tenant_holds` is two `SELECT plan_tier FROM organizations` round trips and nothing
else** — re-reading, once per account, a column the directory row is already holding, to
reach an answer that could not have differed.

`admin/holds.py::held_tenants` — the ops WORK QUEUE built from the same predicate — has
always pre-filtered its candidate set on exactly this tier line, and argues at length why
a filter on the CANDIDATE SET is not a second copy of the RULE. The directory did not, so
two admin surfaces disagreed about which accounts can even be held. That is the older
defect underneath the slow one.

```
before   994.3 ms / 312 accounts   (3.19 ms each)
after    701.7 ms / 312 accounts   (2.25 ms each)      -29%
```

(all-managed directory, which is what every real client is today; on a directory that is
20% self-serve the saving is proportionally smaller — 1,027 → 844 ms — because a
self-serve account is still asked, and there the reads decide something.)

### What is NOT closed, and why it is not closeable here

The SHAPE. Closing it needs one of two things:

* **widening `calls` / `leads` / `kyc_records` for `app.admin`** — hard rule 1, and
  `admin/holds.py` already rejects it at length: a policy is table-scoped, not
  column-scoped, so widening a table in order to COUNT its rows hands every future query
  on an admin session the rows themselves. A `SECURITY DEFINER` aggregate function is the
  textbook alternative and is the same rule violation with a nicer name;
* **paging the response**, which is an admin-console contract change — the screen renders
  every row and prints `rows.length` as "N accounts" — and not a query change. Outside
  this pass's fence.

The materialized `tenant_health` table stays the named escape. It now has a number to be
judged against, which is what the recorded deferral was missing.

**Test:** `tests/admin_directory_holds_prefilter_test.py`, 3 tests. Sabotage-verified:
with the pre-filter removed, **1 goes red** — and getting that red took a correction worth
recording. The first version of the test counted `kyc_records` / `first_campaign_reviews`
statements and **stayed green under sabotage**, because a managed account never reaches
those tables: it is the `plan_tier` read that is saved. A probe aimed one layer past the
work is a probe that proves nothing, and it is why the sabotage step is not optional.

---

## 4. FIXED — `outbox_messages.queue` stops being written (PROVEN)

D-162 recorded that the column reads as routing and routes nothing: `dispatch_outbox`
publishes without it, `WorkerSettings` sets no `queue_name`, and arq routes by
`enqueue_job(_queue_name=...)`, so every message this platform has ever enqueued landed on
arq's single default queue whatever the column said. D-162 removed the CALLER'S choice and
left the value, correctly — hard rule 8 forbids dropping a column in the release that
stops writing it.

**D-162 named exactly two ways it could close. This takes the first (drop), not the second
(a second worker fleet).** The second is not a near miss: one arq worker consumes exactly
one queue, so honouring the column means a second deployable for a platform with no
clients — ROADMAP §6 requires a decision for that and CLAUDE.md's "monolith module before
new service" argues against it — and passing `_queue_name` with no worker consuming that
queue would silently stop every notification. Nothing about that changed. What changed is
that leaving a column nobody reads is not a third option.

### Why this release is the DEFAULT and not the DROP

`docs/DEPLOYMENT.md` §4b: the swap is low-downtime, not zero-downtime, and
`alembic upgrade head` runs against the service database **before** the containers are
recreated. So for the length of the swap the OLD image is serving against the NEW schema.

* With migration `b7e4c1a90d38`'s `SET DEFAULT 'default'`: old code names the column
  explicitly and works; new code omits it and the database fills it. **Both images are
  correct against this schema**, which is the whole content of the two-step.
* With `DROP COLUMN` in the same release: the old image's `INSERT` 500s for those seconds,
  on the table that carries password-reset tokens, invite links and CRM deliveries.

**Step 2 is `ALTER TABLE outbox_messages DROP COLUMN queue`, with no code change beside
it.** Nothing outside this repo blocks it — it waits on one deploy of this revision.

What moved in code, in the same change: both `INSERT`s stop naming the column,
`claim_outbox_batch` stops selecting it, `OutboxMessageRow.queue` is deleted, and the
declaration in `models.py` now says which step has shipped and which has not.
`OUTBOX_FLEET` survives because it is the value the migration defaults to, and a test
pins the two equal — a default in a migration quietly disagreeing with the constant a
reader finds in the service is how a retired column comes back to life wearing a new
value.

**Migration verified up / down / up on `calevate_resid_mig`** (PROVEN): `d1b8f30c94a7 →
b7e4c1a90d38` (default present, column still `NOT NULL`), `downgrade -1` (default gone),
`upgrade head` again. `ALTER COLUMN … SET DEFAULT` edits the catalog and rewrites nothing,
so the risk is the `AccessExclusiveLock` wait rather than the work; `SET LOCAL
lock_timeout = '5s'` bounds it in both directions, the shape `d1b8f30c94a7` established.

**It is NOT added to `check_wiring.UNWIRED_BASELINE`, and that is deliberate.** That
registry is the right home for a column nothing touches, and it cannot hold this one:
the guard detects an unwired column by NAME, and `queue` is a common word — `core/queue.py`,
arq's own vocabulary and a hundred unrelated mentions make the scan see it as wired, so
`stale_baseline()` would refuse the entry as "wired now" (checked, not assumed:
`unwired_columns(baseline={})` returns nothing for `OutboxMessage.queue`). The guard's own
docstring names that blindness — "some unrelated variable will mention it … this check
misses rather than accuses" — and `tests/outbox_queue_deprecation_test.py` is the
purpose-built pin that covers it instead.

**Test:** `tests/outbox_queue_deprecation_test.py`, rewritten, 6 tests. Sabotage-verified:
restoring `queue` to the `enqueue_outbox` INSERT turns
`test_no_statement_in_the_service_writes_the_column` red and leaves the other five green.
56 existing outbox/dispatcher/replay/scrub/prune tests pass unchanged.

---

## 5. NOT CLOSED, RE-ARGUED — the inbound webhook forensic gap (REASONED, and the premise is PROVEN false)

R-9 (`audit-reliability.md`): `webhook_deliveries` records only the inbound deliveries we
CLAIMED. The receiver writes its row inside `if claimed:`, so a delivery refused at the
source-IP check, refused over the size cap, refused as unkeyable, or abandoned at the
claim deadline leaves nothing behind — and that is exactly the population an intrusion
investigation would be pointed at.

### The reason it gave had stopped being true

`integrations/service.py` deferred the fix on: *"closing the gap properly needs a bounded,
aggregated counter rather than a row per refusal, which needs the metrics pipeline
`DEPLOYMENT.md` §8 defers."*

**D-204 falsified the second half while that sentence stood.** `platform_engine_health`
(migration `c4f70b1e28da`) IS a bounded, aggregated minute-bucket counter, it lives in
Postgres, and it shipped with no metrics pipeline — its decision entry even argues "WHY
POSTGRES AND NOT REDIS" at length. A deferral resting on a premise the repo has since
disproved is D-201's own failure mode: *a security argument resting on a premise the code
does not implement is worse than no argument, because it stops the next reader looking.*

### The two reasons it survives on now

1. **Hard rule 3.** All four refusals are on the receiver's ack path, and three of them
   happen before the request has become an event at all — the source check reads no body
   by design, because "on a public, unsigned endpoint that ordering is the difference
   between a rejection and a memory-exhaustion primitive". A durable counter written there
   is a DB write beyond the minimal event row. That is the rule, not a preference.
2. **The write rate belongs to the caller.** `platform_engine_health` is written from OUR
   outbound failures, at a rate we control, which is what makes an upsert-per-event
   affordable there. On an unauthenticated public endpoint the same pattern hands a prober
   one database write per POST. A minute bucket is a smaller ROW than a row per refusal;
   it is the same NUMBER of writes, so it does not answer the objection that rejected the
   row per refusal — it makes the amplifier tidier. What would answer it is in-process
   aggregation flushed on a timer, i.e. a stateful receiver whose state dies with every
   container the deploy recreates (§4b).

**What re-opens it:** a signed engine. Bolna signs nothing today (D-31), so the source
check is an IP allowlist and a refusal is unattributable; with HMAC the refusal becomes
evidence about a named sender and is worth a durable row.

### Two corrections of record

* **`duplicate` is not one of the gaps.** R-9 listed it and OPERATIONS §7 called it "not
  evidence of anything". `claim_inbox_event` bumps `webhook_inbox_events.duplicate_count`
  on the transition's own row, so a replay burst is durable, queryable evidence — it is
  the one inbound outcome recorded without an alert, not the one recorded nowhere.
* **`webhook_claim_timeout` was missing from both documents' refusal lists.** Which is why
  the list is now derived from code: `integrations.service.INBOUND_REFUSAL_ALERTS` is the
  single home, OPERATIONS §7 and SEC-COMP §4 cite it rather than re-typing it, and a test
  checks the list against the receiver **in both directions** — every named code is
  raised, and every raised code is named. `scripts/check_alarm_wiring.py` exists for
  exactly the defect of a prose list of alarm codes drifting from the code that raises
  them.

The warning also moved to where an investigator meets the table: `WebhookDelivery`'s
declaration now says which of its two directions is complete, the same discipline
`outbox_messages.queue` is held to.

**Test:** `tests/webhook_inbound_forensics_test.py`, 7 tests, no database — every claim is
about source text and one constant, deliberately, because these are claims about what we
have WRITTEN DOWN and a runtime probe cannot fail when a document goes stale.
Sabotage-verified twice: removing `webhook_claim_timeout` from the constant turns the
receiver-coverage test red, and restoring the metrics-pipeline sentence turns the
falsified-premise test red.

---

## Guardrails and suites (PROVEN)

| gate | result |
|---|---|
| `uv run ruff check .` | clean |
| `uv run ruff format --check .` | 710 files already formatted |
| `uv run mypy apps packages` | no issues, 233 source files |
| `scripts.check_rls_coverage` | OK — 44 tenant-column tables, 48 policied |
| `scripts.check_metadata_columns` | OK — 62 tables agree in both directions |
| `scripts.check_docs_drift` | OK — 213 decisions, no dangling reference |
| `scripts.check_openapi_fresh --write` + `pnpm -C apps/web gen:api` | snapshot and types regenerated |
| `pnpm -C apps/web typecheck` | clean |
| `pnpm -C apps/web test` | 89 files, 1,148 tests green |
| targeted python suites | see each section |

---

## Databases created by this pass

| database | what it is | left in place? |
|---|---|---|
| `calevate_resid` | the measurement target — template copy of `calevate_replay`, seeded 85,001 leads / 72,000 calls | **yes**, so the numbers above can be re-taken rather than re-derived |
| `calevate_resid_mig` | the up/down/up target for `b7e4c1a90d38` | **yes** |
| `calevate_replay` | the session's working database; `b7e4c1a90d38` applied | pre-existing |

Nothing else was touched. `calevate` was not opened, no shared database was reset or
downgraded, and Redis was not flushed.

---

## STILL OPEN, and whose it is

**Ours, named:**

* **`ALTER TABLE outbox_messages DROP COLUMN queue`** — step 2 of D-217, next release, no
  code change beside it. It waits on one deploy of `b7e4c1a90d38` and on nothing outside
  this repo.
* **The admin client directory is still O(clients)** — §3. Its constant is 29% smaller and
  its number is recorded; its SHAPE needs either an RLS widening hard rule 1 forbids or a
  paged admin-console contract, and the materialized `tenant_health` table stays the named
  escape.
* **The inbound webhook forensic gap** — §5, deliberately open, re-argued, and with what
  re-opens it named (a signed engine).

**Not ours:** nothing in this pass was blocked externally.
