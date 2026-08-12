"""four of the eleven prefix indexes, and why the other seven stay

Revision ID: b9e5d2c74a18
Revises: a3f6b1e02d95
Create Date: 2026-08-12 09:20:00.000000

`e7c3d10a9f52` dropped `ix_credit_ledger_tenant_id` — a strict PREFIX of a composite,
so by the leading-column rule it offered no access path the composite did not. Its
commit message recorded that twelve other tables carry the same pattern and deferred
them, because "most are covered by UNIQUE indexes, which is a different call".

This is that call, made per table on a loaded database rather than from the shape of
the catalog. **Four are dropped. Seven stay.**

THE CATALOG UNIVERSE
--------------------
Eleven single-column btree indexes on ten tables are a strict prefix of another btree on
the same table with the same opclasses and the same (absent) predicate. Two near-misses
are NOT in the set and must not be added to it: `ix_consent_ledger_tenant_id` and
`ix_deletion_requests_tenant_id` are each a prefix of a PARTIAL index
(`... WHERE purpose = 'messaging'`, `... WHERE completed_at IS NULL`), which covers a
subset of rows and therefore covers nothing.

WHY UNIQUENESS TURNED OUT NOT TO BE THE DISCRIMINATOR
-----------------------------------------------------
Three things were checked before treating a `uq_*` index as a cover, and none of them
separates unique covers from plain ones:

1. **Planner use for the prefix lookup** is identical. PG16 §11.3 states the rule
   without reference to uniqueness: "equality constraints on leading columns ... will be
   used to limit the portion of the index that is scanned". Confirmed in every plan
   below — the cover is offered for the prefix predicate in exactly the shape the prefix
   index was.

2. **Selectivity estimation** is identical for a prefix predicate. `btcostestimate`
   (src/backend/utils/adt/selfuncs.c, REL_16_STABLE) takes its uniqueness shortcut only
   when an equality qual was found for EVERY key column:

       if (index->unique && indexcol == index->nkeycolumns - 1 && eqQualHere && ...)
           numIndexTuples = 1.0;

   A prefix-only qual leaves `indexcol` short of `nkeycolumns - 1`, so the shortcut does
   not fire and the estimate comes from `clauselist_selectivity` over `pg_statistic` —
   the same computation a non-unique cover gets. Uniqueness is only an estimation
   advantage when the whole key is pinned, which is a case the single-column index could
   never have served anyway.

3. **Nothing depends on a redundant index specifically.** `ON CONFLICT` infers arbiters
   only from UNIQUE indexes (PG16 INSERT: "All table_name unique indexes that ... contain
   exactly the conflict_target-specified columns/expressions are inferred"), so a
   non-unique `ix_*` can never be an arbiter — the five upsert paths here
   (`leads`, `call_extractions`, `memberships`, `campaign_contacts`, `transcript_turns`)
   all name the `uq_*` cover, which stays. Foreign keys require an index only on the
   REFERENCED side (PG16 §5.5), never the referencing one. No table in this schema has
   `REPLICA IDENTITY USING INDEX` (`pg_class.relreplident` is 'd' everywhere), and none
   of the eleven backs a constraint (`pg_constraint.conindid` is null for all of them).

What DOES separate them is btree **deduplication**. A non-unique index on a repeating
column collapses duplicates into one posting-list tuple per distinct value — PG16 §67.4.3:
"The column key value(s) only appear once in this representation ... This significantly
reduces the storage size of indexes where each value ... appears several times on
average. The latency of queries can be reduced significantly." A cover whose trailing
columns make every entry logically distinct gets none of that; in a unique index
deduplication only ever absorbs "version churn duplicates". Measured on the loaded
database (25 tenants, 200k leads, 560k transcript turns, one tenant holding ~40%):

    ix_leads_tenant_id           1288 kB   uq_leads_tenant_id_phone_e164_agent_id  23 MB
    ix_call_extractions_tenant_id 976 kB   uq_call_extractions_tenant_id_call_id   13 MB
    ix_dnc_list_tenant_id        1024 kB   uq_dnc_list_tenant_id_phone_e164        11 MB
    ix_campaign_contacts_campaign_id 2432 kB  ix_campaign_contacts_due             24 MB

So the cover is 4x-18x the size for the same rows, and offering it alone for
`tenant_id = ...` does not move the query onto it — it moves the query off indexes
altogether.

THE SEVEN THAT STAY, with the plan that collapsed
--------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS) as `calevate_app` with FORCEd RLS in effect, before and after
`DROP INDEX` in a rolled-back transaction. Only regressions are listed.

| index                            | what broke without it                              |
|----------------------------------|----------------------------------------------------|
| ix_leads_tenant_id               | 8 plans fell to Seq Scan, incl. the CRM list page's |
|                                  | status counts 20ms -> 44ms, dashboard 18 -> 42ms,   |
|                                  | CSV export 29 -> 56ms, and the FK check             |
| ix_call_extractions_tenant_id    | 3 to Seq Scan: retention batch 24 -> 38ms,          |
|                                  | retention has_work 1.4 -> 4.1ms, FK check           |
| ix_dnc_list_tenant_id            | 2 to Seq Scan: DNC list panel 17 -> 42ms.           |
|                                  | The asymmetric RLS `tenant_id IS NULL OR = ...`     |
|                                  | needs a BitmapOr and loses an arm                   |
| ix_deletion_requests_tenant_id   | FK check to Seq Scan. Note its cover is NOT unique  |
|                                  | (`ix_deletion_requests_tenant_subject`) — the       |
|                                  | keeper that disproves the uniqueness hypothesis     |
| ix_campaign_contacts_campaign_id | at 61k contacts/campaign `campaign_progress` falls  |
|                                  | back to the tenant index: 2144 -> 6282 buffers      |
| ix_kb_documents_source_id        | at 4000 chunks/source, 179 -> 211 buffers (+18%) on |
|                                  | the source preview and the engine push payload      |
| ix_kb_sources_agent_id           | at 840 sources/agent the planner abandons the agent |
|                                  | path entirely and scans the tenant partition        |

Two of those (`kb_documents`, `kb_sources`) looked droppable at first load and only
degraded once rows-per-key was raised to the ceiling the table can actually reach. That
is the reason the verdicts were re-taken at scale rather than at seed size.

THE FOUR DROPPED, and what it costs
------------------------------------
Same method, and the bar is the one `e7c3d10a9f52` set: no node type changed, nothing
fell back to a sequential scan, and the stated cost is the extra buffers.

| index                         | plans           | buffers          | measured at        |
|-------------------------------|-----------------|------------------|--------------------|
| ix_transcript_turns_call_id   | 5 move to cover | +2 (24->26, 165->167) | 14 and 400 turns/call |
| ix_prompt_versions_agent_id   | 0 change        | identical        | 12 and 800 vers/agent |
| ix_extraction_schemas_agent_id| FK check only   | 1624 -> 1625, 2x faster | 6 and 800 vers/agent |
| ix_memberships_tenant_id      | FK check only   | 5657 -> 5690 (+0.6%) | 198 and 4000 members  |

`prompt_versions` is the clearest of the four: at the scale that table reaches, no query
in the repository names the index even before it is dropped.

WHAT IT BUYS, measured not assumed. 200k single-statement inserts, arms alternated,
median of five rounds, WAL taken from `pg_current_wal_insert_lsn()`:

    transcript_turns    3.568s -> 3.407s (-4.5%)   WAL 117.6 -> 87.0 MB (-26%)
    extraction_schemas  3.305s -> 3.011s (-8.9%)   WAL 106.4 -> 84.8 MB (-20%)
    prompt_versions     3.312s -> 3.128s (-5.6%)   WAL 116.5 -> 81.5 MB (-30%)
    memberships         (3860 rows) -6.3%          WAL   3.3 ->  2.0 MB (-39%)

`transcript_turns` is where that matters: the post-call pipeline writes a row per turn,
so this is ~14 index insertions per call that now do not happen, and 26% less WAL to
ship. The other three are small tables and the percentage is a percentage of very
little — they are dropped because they are unused, not because they were expensive.

UPDATE paths are unaffected either way. HOT eligibility depends on whether any INDEXED
column changes, and `call_id` / `agent_id` / `tenant_id` remain indexed by the cover, so
removing the second index on the same column cannot make an update non-HOT.

RLS (hard rule 1). Every one of these tables has a `tenant_isolation` policy whose qual
is a predicate on `tenant_id`, so an index on `tenant_id` is an index on the RLS
predicate itself. That is precisely why the four `ix_*_tenant_id` indexes on the big
tables STAY. The one dropped here that an RLS predicate could depend on is
`ix_memberships_tenant_id`, and it is called out rather than glossed: `memberships` has
the asymmetric policy `tenant_id = ... OR user_id = ...`, and both arms of the BitmapOr
remain indexed afterwards — the tenant arm by `uq_memberships_tenant_id_user_id`, the
user arm by the untouched `ix_memberships_user_id`. Measured on the FK-enforcement shape
above at 4000 members in one tenant: the BitmapOr survives, at +33 buffers.

LOCKING. Plain `DROP INDEX`, not CONCURRENTLY, for the reason `e7c3d10a9f52` gave: an
index drop is a catalog update and a file unlink, so ACCESS EXCLUSIVE is held for
milliseconds no matter how large the table — the exposure is the WAIT for the lock, not
the work under it. `lock_timeout` bounds that wait so a queued ACCESS EXCLUSIVE request
cannot park in front of the post-call pipeline; a migration that cannot get the lock in
3s should fail and be retried, not block writes. CONCURRENTLY cannot run inside a
transaction block, so it would trade this revision's atomicity — four drops that must
land together or not at all — for a millisecond of queueing.

DOWNGRADE recreates all four. None is a constraint, so a downgraded database is slower
on writes and identical on reads.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b9e5d2c74a18"
down_revision: str | None = "a3f6b1e02d95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# index -> (table, column) — the column stays indexed by the cover named in the
# docstring; it stops being indexed TWICE.
DROPPED: tuple[tuple[str, str, str], ...] = (
    ("ix_transcript_turns_call_id", "transcript_turns", "call_id"),
    ("ix_prompt_versions_agent_id", "prompt_versions", "agent_id"),
    ("ix_extraction_schemas_agent_id", "extraction_schemas", "agent_id"),
    ("ix_memberships_tenant_id", "memberships", "tenant_id"),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for index, table, _ in DROPPED:
        op.drop_index(index, table_name=table)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    for index, table, column in DROPPED:
        op.create_index(index, table, [column])
