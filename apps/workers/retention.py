"""Retention enforcement and DPDP erasure-with-proof (SEC-COMP §4, FLOWS §9).

Two jobs that are legal obligations rather than features:

**Retention sweep** — `retention_policies` sets a TTL and an action per data category.
Without a job that reads them the table is a promise we make in the DPA and do not
keep. TRAI's 90-day recording floor is enforced twice: a DB CHECK stops anyone
configuring less, and this job refuses to act on a policy that somehow claims less.

**Erasure with proof** — a DPDP request locates a phone number across calls, turns,
leads and recordings, applies the erasure, and writes a proof JSON recording *what,
where, when and hashes*. The proof is the deliverable: "we deleted it" is a claim, a
per-row hash list is evidence.

Anonymize vs delete, and why anonymize is usually right: deleting a call row would take
its `usage_events` with it (FK RESTRICT) and silently rewrite a billing period. So the
default action neutralizes the personal data and keeps the countable shell — the
minutes still happened.

DELIVERED WEBHOOK BODIES (D-23) and RECORDINGS are the personal data this module expires
OUTSIDE Postgres, and both go through `_sweep_objects_in_batches`: select the keys, delete
the objects, and only then clear the references, so a crash leaves a reference to a
deleted object (harmless) rather than an object nothing can name (unreachable forever).

THE RECORDING BYTES USED TO SURVIVE EVERYTHING. This module cleared `calls.recording_url`
and said in a comment that the object-store lifecycle rule removed the audio. It does not
— SEC-COMP §4 records what `infra/object-lifecycle/` actually is, a bucket-wide 2555-day
growth CEILING that "CANNOT follow the retention policy" — so a tenant's 90-day recording
policy expired the POINTER and left the audio for seven years, and an erasure request made
it worse: clearing the pointer destroyed the only handle anything had on the key, so the
sweep (`WHERE recording_url IS NOT NULL`) could never reach it again. Filing a DPDP
erasure made the recording permanently undeletable. Both halves are closed: the sweep
destroys the bytes at `max(ttl, floor)`, and the erasure destroys the ones past the floor
and SCHEDULES the rest in `recording_erasure_holds` (`_erase_recordings`).

ARCHIVED RAW ENGINE PAYLOADS (D-126) are the third store outside Postgres. The archive
carries the caller's number and the transcript, so `_erase_engine_payloads` deletes it by
`{tenant}/{call}` prefix on both erasure paths. Until D-179 that erasure arm was the ONLY
thing that ever removed one: no `retention_policies.data_category` covered the archive, so
the copy belonging to everyone who never filed a §12 request was kept for ever behind a
bucket lifecycle rule nothing has ever applied (infra/README §5). It now expires on the
tenant's own `engine_payload` policy, through the same `_erase_engine_payloads` the
erasure uses — one definition of "destroy a call's archived payloads", two callers.

SUPERSEDED KNOWLEDGE-BASE VERSIONS are the fourth store, and the one that is not about
callers at all: a client's uploaded FAQs and price lists name their staff, their doctors
and their contact numbers. Publishing a new version ARCHIVES the old one
(`kb/service.publish_source`), and nothing had ever deleted a `kb_documents` row — so
every version ever published survived, including the ones no screen shows. The `kb`
category (D-179) expires those, and only those: the LIVE version is what the agent
answers from and a retention clock that deleted it would be an outage we caused.

Engine-side copies are the open edge, honestly marked: Bolna's deletion API is
undocumented (pilot gate), so `engine_deletion` is recorded as `unconfirmed` in the
proof rather than asserted. A proof that overclaims is worse than one that says what it
does not know.

THE SWEEP'S COST SHAPE (see `_due_tenants` and `sweep_tenant`): the tick costs one
probe per tenant that CAN hold call data, not one session per organization on the
platform, and each tenant may consume at most `TENANT_ROW_BUDGET` rows per category
before the rest is deferred to the next tick.

THE CLOCK (see `_call_clock`): every arm dates a call's data from when the call ended,
and `calls.ended_at` is a nullable VENDOR-supplied field. A call the engine never dated
used to match no predicate at all and kept its recording pointer, transcript and summary
forever. The clock now falls back to our own `created_at` plus the metered duration.

THE ONE THING THIS MODULE REFUSES TO DECIDE: whether to destroy a recording younger than
the retention floor EARLY, on request. SEC-COMP §4 says erasure covers recordings, §1 says
the floor is a minimum, and the doc reserves the choice for the founder while forbidding
anyone to "make the pointer-clear conditional on age". Both constraints are honoured: the
pointer is cleared at every age, and no under-floor recording is ever destroyed early.

What the deferral is NOT is a refusal. DPDP §12(3) obliges erasure "unless retention of
the same is necessary … for compliance with any law", and DPDP §8(7) makes keeping the
data past the end of that necessity a breach in itself — so a retention obligation moves
an erasure's date, it does not cancel it. `recording_erasure_holds` is that date made
durable, and the collision keeps its rate in the log stream (`_FLOOR_COLLISION_LOG`) and
its numbers in the proof (`recordings_within_trai_floor`, `recordings_destroyed`,
`recording_hold_until`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import storage

log = get_logger(__name__)

# TRAI floor (SEC-COMP §1). Duplicated from the DB CHECK on purpose: a policy row that
# somehow claims less must not cause this job to delete a recording early.
RECORDING_FLOOR_DAYS = 90
ANONYMIZED_PHONE = "+910000000000"
REDACTED_MARK = "[erased]"

# THE ERASURE / FLOOR COLLISION — WHAT THIS MODULE MAY AND MAY NOT DO ABOUT IT.
#
# SEC-COMP §4 describes erasure as covering recordings; SEC-COMP §1 records the TRAI
# 90-day retention floor. For a recording younger than 90 days those point opposite
# ways. The doc says in terms that the decision is the founder's, that it needs the
# Bolna erasure commitment (pilot gate 12(f)) in hand, and that until then nobody may
# "make the pointer-clear conditional on age". So this module does NOT resolve it and
# does not gate on age: the pointer is cleared at any age, exactly as before, and
# `compliance.deletion.ERASURE_LIMITATIONS` is what tells the data principal.
#
# What it does do is stop the collision being SILENT. Counting the recordings this
# erasure reached inside the floor turns "the two sections disagree" into a number a
# human can act on — how often it actually happens, on which requests — which is the
# first thing whoever resolves this will ask for.
_FLOOR_COLLISION_LOG = "erasure_within_recording_floor"

# ...and WHERE the count is written. It used to ride only the job's return string and a
# WARNING, which put it in the log stream and nowhere durable: the certificate a client
# detaches and hands to a data principal had to say "this certificate does not state how
# many", because after the pointer clear the question is unanswerable — `recording_url`
# is NULL on every row the request touched and no later reader can reconstruct which of
# them were young. So the count goes in the PROOF, where it outlives the process that
# computed it.
#
# The receiving half was built first and waited for this: `ErasureScopeOut` already
# models the field as `int | None` (strict, so an unmodelled key would 500 the status
# read), and `deletion_proof._floor_sentence` already switches its wording on it. Absent
# still means "not recorded" — proofs written before this change keep certifying that
# they do not state the number, and hard rule 4 forbids back-filling them.
#
# DUPLICATED from `apps.api.compliance.deletion.FLOOR_COUNT_KEY` rather than imported,
# for the same reason `RECORDING_FLOOR_DAYS` is duplicated in both directions: a worker
# has no business importing the API's compliance package — with its outbox producer and
# its session dependencies — in order to name a JSON key. `tests/erasure_floor_count_test`
# pins the two spellings together so they cannot drift.
FLOOR_COUNT_KEY = "recordings_within_trai_floor"

# The other two facts the proof now records about the audio, spelled the same in both
# packages for the same reason (`tests/recording_erasure_test` pins them together).
#
# `recordings_destroyed` is the count this erasure actually put beyond recovery, and
# `recording_hold_until` is the ISO instant the last DEFERRED one is destroyed on. Both
# are absent from every proof written before the bytes were reachable at all, and absent
# still means "not recorded" rather than zero — the certificate says so in words.
DESTROYED_COUNT_KEY = "recordings_destroyed"
HOLD_UNTIL_KEY = "recording_hold_until"

# How many knowledge-base documents mention the subject's number (D-179). Spelled the
# same in `apps.api.compliance.deletion.KB_MATCH_KEY` and duplicated rather than imported,
# for the reason the three keys above are: a worker has no business importing the API's
# compliance package to name a JSON key. `tests/kb_retention_test.py` pins the spellings.
#
# ABSENT IS NOT ZERO here as well, and it matters more than on the counts above: every
# proof written before this search existed carries no key, and a rendered `0` would tell a
# data principal "we looked and found nothing" about an erasure that never looked. The
# certificate says the three states in three different sentences.
KB_MATCH_KEY = "knowledge_base_documents_matched"

# Rows touched by ONE statement. Small enough that the sweep never holds a lock long
# enough to matter to a live call writing to the same tables.
SWEEP_BATCH_ROWS = 1_000
# Rows one tenant may consume PER CATEGORY per tick. The bound is what stops a single
# enormous tenant (a churned client with two years of calls, whose countdown starts at
# offboarding — FLOWS §9) from owning the whole tick while everyone else's TTLs slide.
# What is left over is not lost: it is `deferred`, and the next tick starts with the
# oldest rows again because every batch is ordered oldest-first.
TENANT_ROW_BUDGET = 20_000

# WHICH DERIVED COPY BELONGS TO WHICH CATEGORY — the policy, expressed in the same
# vocabulary the DPA uses (`data_category` + a `retention_policies` row), never as a
# hardcoded "and also delete X" bolted onto a sweep.
#
# The problem this answers: `calls.summary` and `call_extractions.data` are both
# written FROM the transcript. Ageing the transcript out and leaving them behind makes
# "transcripts are retained for N days" true of a table and false of a person — the
# summary is model-written prose about what the caller said, and the extraction payload
# is their name, their callback number and every field the schema captured.
#
# The split below classifies each derived copy by WHAT IT IS, and then lets the tenant's
# own policy row decide when it goes:
#
#   transcript → calls.summary          a retelling of the conversation. Same personal
#                                       data as the turns it paraphrases, so it lives
#                                       and dies on the transcript clock.
#   lead       → call_extractions.data  structured CRM fields — the same class of thing
#                                       as `leads.data`, which is what the client bought
#                                       and keeps using after the raw transcript is
#                                       gone. So it expires on the LEAD clock (default
#                                       1095d), not the transcript clock (365d), and
#                                       not never.
#
# Conservative on both sides: nothing personal outlives its category, and no CRM field
# is deleted earlier than the CRM category the client already agreed to. See the
# module tests for the same statement in a compliance reviewer's words.
#   lead       → webhook_deliveries  the CRM payload we POSTed to the client's own
#                .payload_ref         endpoint (D-23) — the same fields as
#                                     `call_extractions.data`, kept as an object so
#                                     support can answer "what did you send us?". Same
#                                     class of data, so the same clock; expiring it on
#                                     any other would mean "leads are kept for N days"
#                                     is true of a table and false of a bucket.
DERIVED_COPIES: Mapping[str, tuple[str, ...]] = {
    "transcript": ("calls.summary",),
    "lead": ("call_extractions.data", "webhook_deliveries.payload_ref"),
}


# THE CALL'S RETENTION CLOCK — and why it is not simply `ended_at`.
#
# Every arm of this sweep dates a call's data from when the call ENDED. `calls.ended_at`
# is nullable and VENDOR-SUPPLIED: the Bolna adapter reads it out of the execution
# payload (`ended_at` or `updated_at`, else None — apps/api/engine/bolna.py), and the
# pipeline's upsert keeps NULL when the vendor never sends one
# (`ended_at = COALESCE(EXCLUDED.ended_at, calls.ended_at)`). Transcript turns, the
# recording pointer and the summary are all written regardless.
#
# `ended_at < :cutoff` is NULL for such a row, so it matches nothing — not the probe,
# not one of the four statements below. A call the engine never dated therefore kept its
# recording pointer, its transcript and its summary FOREVER, with no counter, no alert
# and no way for the tenant's own policy to reach it. That is a legal obligation a
# vendor's missing field could switch off.
#
# The fallback is our own `created_at` (NOT NULL, written by us) plus the metered
# duration: when we do not know when the call ended, we assume the LATEST moment it
# plausibly could have. That direction is deliberate — the TRAI floor is a minimum, so a
# guess that lands late retains slightly too long (safe) while a guess that lands early
# deletes a recording before its 90 days are up (the violation that cannot be undone).
#
# Rows that DO carry `ended_at` are unaffected: COALESCE returns it, and every predicate
# below behaves exactly as it did before.
def _call_clock(alias: str) -> str:
    return (
        f"COALESCE({alias}.ended_at, "
        f"{alias}.created_at + make_interval(secs => COALESCE({alias}.duration_s, 0)))"
    )


_CLOCK = _call_clock("c")

# Counter keys, so a caller (and the log line) always sees the same shape.
_EMPTY_TOTALS: Mapping[str, int] = {
    "recordings": 0,
    "transcripts": 0,
    "summaries": 0,
    "leads": 0,
    "extractions": 0,
    # Delivered webhook bodies (D-23): one object deleted and its `payload_ref` cleared.
    "delivery_bodies": 0,
    # Archived raw vendor documents (D-126) destroyed on the tenant's own
    # `engine_payload` policy (D-179). Counted in OBJECTS, not calls, because one call
    # can hold several — the engine fires a document per status transition.
    "engine_payloads": 0,
    # Superseded knowledge-base versions deleted on the tenant's `kb` policy (D-179).
    # Counted in SOURCES (versions), not chunks: "three old versions of your price list
    # were forgotten" is the sentence a client understands.
    "kb_versions": 0,
    # Recording objects destroyed for an erasure that could not lawfully destroy them
    # when it ran (migration 9c1d3e7a05f4). Counted apart from `recordings` on purpose:
    # one is a retention period ending, the other is a DPDP obligation finally being
    # discharged, and a single number would hide whether erasures are actually completing.
    "recording_holds": 0,
    "deferred": 0,
}


def _hash(value: str) -> str:
    """Hashes go in the proof so a later audit can verify WHICH rows were erased
    without the proof itself carrying the personal data (that would defeat the point)."""
    return hashlib.sha256(value.encode()).hexdigest()[:32]


async def _due_tenants() -> list[UUID]:
    """Every tenant that CAN hold call data — resolved from the global bridge table.

    The sweep used to enumerate `organizations` and open a tenant session for every one
    of them, so the nightly tick cost grew with the client list rather than with the
    data: on the development database that is ~16k organizations and ~3 minutes of
    round-trips, almost all of it spent asking tenants with no calls whether they had
    any expired calls.

    `engine_agent_routes` is the SAME non-tenant-scoped bridge `ingest_engine_event`
    and the stall alarm use, and it exists precisely so a cross-tenant resolution needs
    no RLS exemption and no admin role (hard rule 1, `db/registry.py`). A call row is
    only ever created for an agent the engine knows — `publish_agent` writes the route
    in the transaction that mints the ref — so every tenant with calls, transcript
    turns, extractions or call-sourced leads is in this set.

    Deliberately unfiltered on `active` AND on `organizations.deleted_at`: offboarding
    is where the countdown STARTS (FLOWS §9), so a churned tenant is exactly the one
    whose rows must keep ageing out. Deactivating an agent must not freeze its calls in
    time either.

    THE LEADS HOLE, AND WHY IT IS CLOSED AT THE OTHER END. This set is a superset for
    anything involving a CALL by construction — a call row only exists for a published
    agent. Leads were the exception: `ingest/service.py` writes the lead BEFORE the
    dial, so a tenant whose agent was never published could keep a lead (on the consent
    or compliance-gate exits, which return before the dial and therefore commit) and
    appear in no worklist, and its `lead` TTL would never run.

    Three fixes were weighed and the sweep is deliberately NOT where any of them went:

    - *Sweep churned/suspended/soft-deleted organizations too.* Rejected on the merits
      before cost: it does not fix this. The tenant in the hole is typically ACTIVE — a
      live client mid-onboarding, not a churned one — so an org-status arm misses the
      population it is aimed at, while re-introducing `admin_session` into a worker that
      the previous round deliberately took it out of. Wrong answer, high price.
    - *A global presence row written by the ingest path.* The correct shape in the
      abstract, and expensive in the concrete: any cross-tenant worklist table must be
      exempt from tenant RLS (this one and `audit_log` are the only two that are, and
      `db/registry.RLS_EXEMPT_TENANT_COLUMNS` is pinned in a test precisely so a third
      costs a visible argument). It buys a second bridge to keep in step with the first,
      to cover a state the platform should not be in.
    - *Accept the invariant — and stop assuming it, enforce it.* Taken. `ingest_lead`
      now makes the refusal `dispatch_call` was already making one step earlier, in
      front of the INSERT rather than behind it, so a lead is never written for an agent
      with no `engine_agent_ref`. `publish_agent` writes that column and this table in
      one transaction, so "the tenant holds a lead" now implies "the tenant is in this
      set", for every lead source: webhook leads by that refusal, call-sourced leads by
      construction.

    Said the way a compliance reviewer would: no personal data reaching this platform
    THROUGH A CALL OR A LEAD enters it without the retention sweep being able to expire
    it later. `tests/schema_hardening_3_test.py` is that sentence as executable tests.

    **AND THAT SENTENCE USED TO BE WRITTEN WITHOUT ITS FIRST CLAUSE, WHICH MADE IT
    FALSE (D-363).** It was true of every category that existed when it was written;
    D-179 then added `kb`, and a knowledge source is the one expirable artefact a
    tenant can hold WITHOUT ever publishing an agent. `kb/service.reject_source` moves
    a source `pending_approval → rejected` with no engine involvement at all, so a
    tenant that uploads a document, has it refused, and never publishes has:

        * six `retention_policies` rows, `kb` among them at 365 days, written by
          `admin/service._create_tenant_root` in the transaction that mints the org;
        * a `kb_sources` row that `_KB_EXPIRABLE` matches exactly; and
        * NO `engine_agent_routes` row, so it is not in this list and its nightly
          sweep never runs.

    Measured, not reasoned: `sweep_tenant()` called directly on such a tenant returns
    `{'kb_versions': 1}` and removes both the source and its chunks, so the sweep ARM is
    correct and only the WORKLIST cannot reach it. The population is bounded to
    `rejected` — `archived` is only ever produced by `_detach_superseded`, i.e. by a
    publish, which mints the route — but "bounded" is not "empty", and a `kb_documents`
    row holds whatever the client uploaded.

    NOT CLOSED HERE, and the reason is that every way of closing it is a tenancy
    decision rather than a sweep change. Reading `kb_sources.tenant_id` across tenants
    needs a THIRD entry in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` — on a table that
    holds client content, where the two existing entries hold routing keys and a hash
    chain — and walking `organizations` under `admin_session` (the shape
    `qa_sampling.draw_qa_samples` uses) reinstates exactly the per-tenant fan-out D-57
    and P6.2 removed from this job. D-363 records both with their costs. Until one is
    taken, this docstring says which data the sentence covers instead of implying all
    of it.

    What enforcement cannot do is reach BACKWARD. Rows written under the old ordering
    are still outside this set, and this worker cannot even count them: it holds no
    admin role, and an `untenanted_session` reading `leads` is fail-closed and returns
    zero rows — so "how much residue is there?" is not a question the sweep can answer
    about itself, and a self-check here would be a comforting no-op. It is one query in
    the admin realm, where a cross-tenant read is audited and belongs:

        SELECT count(*) FROM leads l WHERE NOT EXISTS (
          SELECT 1 FROM engine_agent_routes r WHERE r.tenant_id = l.tenant_id);

    and the alert that catches a recurrence is that count trending UP — flat is residue,
    rising means something started writing leads outside a published agent again.
    """
    async with untenanted_session() as session:
        rows = (
            (
                await session.execute(
                    # ORDER BY, and it is not cosmetic (P6.2). Without it the order is
                    # planner-dependent, so WHICH tenants a sweep reaches before it hits
                    # its row budget — or, before the isolation below existed, before an
                    # error aborted the rest — varied night to night for reasons nobody
                    # could reproduce. A stable order makes "tenant X was not swept" a
                    # question with an answer.
                    text("SELECT DISTINCT tenant_id FROM engine_agent_routes ORDER BY tenant_id")
                )
            )
            .scalars()
            .all()
        )
    return [UUID(str(row)) for row in rows]


# WHICH KNOWLEDGE-BASE VERSION MAY BE FORGOTTEN — written once, read by the probe and by
# the sweep statement, because a probe that answers a different question from the
# statement it gates is a tick that reports work and then does none (or the reverse).
#
# Three conditions, and each one is refusing a different way of getting this wrong:
#
#   `is_active = false`   — never the LIVE version. That is the content the agent
#                           answers from; expiring it is an outage we caused, and the
#                           period a client keeps their own working knowledge for is the
#                           length of the engagement, not a TTL. The tenant-erasure path
#                           is what ends it.
#   `status IN (...)`     — only ARCHIVED (superseded by a later publish) and REJECTED
#                           (an operator refused it). A draft still moving through the
#                           approval gate — `uploaded`, `parsed`, `pending_approval` — is
#                           work in progress, and deleting somebody's unsubmitted upload
#                           on an age rule would be a surprise rather than a retention
#                           policy.
#   no `engine_kb_ref`    — the engine must have given the copy back first. A superseded
#                           version has its handle CLEARED on detach
#                           (`kb/service._detach_superseded`), so a handle still recorded
#                           means a detach that never completed — the exact residue
#                           `_reattach_after_failed_publish` documents. Deleting our rows
#                           then would destroy the only record that can address the
#                           engine's copy, which is the D-126 failure shape on a
#                           different table. Those rows are the reconciliation sweep's
#                           (D-158) to resolve, and this arm leaves them alone.
_KB_EXPIRABLE = (
    "s.is_active = false AND s.status IN ('archived', 'rejected') "
    "AND NOT EXISTS (SELECT 1 FROM kb_documents d "
    "WHERE d.source_id = s.id AND d.meta ->> 'engine_kb_ref' IS NOT NULL)"
)


# The probe. ONE statement that reads the tenant's policies AND answers "is there
# anything expired under this policy?" for each of them, so a tenant with nothing to do
# costs a single round trip instead of four blind UPDATEs that match zero rows.
#
# Each arm covers the category's OWN table and its derived copies (see DERIVED_COPIES),
# because a tick that skipped the category would skip those too.
_PROBE_SQL = f"""
SELECT r.data_category, r.ttl_days, r.action,
  CASE r.data_category
    WHEN 'recording' THEN EXISTS (
      SELECT 1 FROM calls c
      WHERE c.recording_url IS NOT NULL
        AND {_CLOCK} < now() - make_interval(days => GREATEST(r.ttl_days, :floor)))
    WHEN 'transcript' THEN EXISTS (
      SELECT 1 FROM transcript_turns t JOIN calls c ON c.id = t.call_id
      WHERE {_CLOCK} < now() - make_interval(days => r.ttl_days)
        AND (r.action = 'delete' OR t.text <> :mark))
      OR EXISTS (
      SELECT 1 FROM calls c
      WHERE c.summary IS NOT NULL
        AND {_CLOCK} < now() - make_interval(days => r.ttl_days))
    WHEN 'lead' THEN EXISTS (
      SELECT 1 FROM leads l
      WHERE l.updated_at < now() - make_interval(days => r.ttl_days)
        AND left(l.phone_e164, length(:anon)) <> :anon)
      OR EXISTS (
      SELECT 1 FROM call_extractions e
      WHERE e.updated_at < now() - make_interval(days => r.ttl_days)
        AND e.data <> '{{}}'::jsonb)
      OR EXISTS (
      -- Scoped THROUGH `outbound_webhooks`, never by RLS: `webhook_deliveries` has no
      -- policy of its own (engine webhooks arrive before a tenant is resolved), so this
      -- subquery is the whole of the tenant scoping here, exactly as on the client's own
      -- delivery screen.
      SELECT 1 FROM webhook_deliveries d
      WHERE d.payload_ref IS NOT NULL AND d.direction = 'out'
        AND d.endpoint_id IN (SELECT id FROM outbound_webhooks)
        AND d.created_at < now() - make_interval(days => r.ttl_days))
    WHEN 'engine_payload' THEN EXISTS (
      SELECT 1 FROM calls c
      WHERE c.engine_payload_ref IS NOT NULL
        AND {_CLOCK} < now() - make_interval(days => r.ttl_days))
    WHEN 'kb' THEN EXISTS (
      SELECT 1 FROM kb_sources s
      WHERE {_KB_EXPIRABLE}
        AND s.updated_at < now() - make_interval(days => r.ttl_days))
    ELSE false
  END AS has_work
FROM retention_policies r
"""


async def apply_retention(ctx: dict[str, Any]) -> str:
    """Nightly. Sweeps the tenants that can hold data, under each one's own policies.

    **THIS IS A LEGAL OBLIGATION ON A 24-HOUR CADENCE, and it used to fail in silence**
    (P6.2). Three things compounded: `max_tries` defaulted to 1, one tenant's error
    aborted every tenant after it, and the failure raised something that is not
    `arq.Retry` — so arq finished the job after one attempt with a `logger.exception` and
    nothing alerted. A deploy at 03:40 UTC or one bad row and the night's sweep was gone
    until tomorrow, with the only trace a stack trace in a log stream.

    All three are closed here and in `settings.CRON_JOBS`. What this function now
    guarantees is that a tenant that fails is ONE tenant that failed: the sweep continues,
    the count comes back, and a non-zero count alerts.
    """
    tenants = await _due_tenants()
    totals = await sweep_tenants(tenants)
    log.info("retention_sweep", extra={**totals, "tenants_scanned": len(tenants)})
    failed = totals.get("tenants_failed", 0)
    if failed:
        # AFTER the sweep, not instead of it. The tick did what it could for everybody
        # else, and this says how much of tonight's obligation went undischarged — which
        # is the number an operator needs and the one a `logger.exception` per tenant
        # cannot give them. Counts and no ids: the failing tenant's id is already in the
        # per-tenant log line, and an alert body is forwarded further than a log is.
        alert(
            "WORKER_TERMINAL",
            "retention_sweep_incomplete",
            detail=(
                f"{failed} of {len(tenants)} tenant(s) did not complete tonight's "
                "retention sweep. Their expired recordings, transcripts, leads and "
                "extractions are still held; the sweep runs again in 24 hours and will "
                "retry them, so this is a deadline slipping rather than data lost."
            ),
        )
    return json.dumps(totals)


async def sweep_tenants(tenant_ids: Iterable[UUID]) -> dict[str, int]:
    """One tick over an explicit tenant list. Split out from `apply_retention` so the
    resolution step and the sweeping step can be exercised — and costed — separately.

    **A FAILED TENANT DOES NOT FAIL THE TICK** (P6.2). This loop had no `try`, so a single
    tenant's database error — a lock timeout, a storage refusal, one malformed policy row
    — ended the sweep for every tenant that had not been reached yet. With no `ORDER BY`
    on the tenant list, which ones those were changed from night to night.

    The shape is `qa_sampling.draw_for_tenants`', which was split out of its own job to
    match this function and got the isolation this one did not: same try, same counter,
    same rule that the id goes in the log and the exception's payload does not — a psycopg
    error string can quote the row that broke it, and these rows name calls (hard rule 6).
    """
    totals = dict(_EMPTY_TOTALS)
    swept = 0
    failed = 0
    scanned = 0
    for tenant_id in tenant_ids:
        scanned += 1
        try:
            counts = await sweep_tenant(tenant_id)
        except Exception:  # one tenant's failure is not the tick's — see the docstring
            log.exception("retention_sweep_tenant_failed", extra={"tenant_id": str(tenant_id)})
            failed += 1
            continue
        if any(counts.values()):
            swept += 1
        for key, value in counts.items():
            totals[key] += value
    totals["tenants_swept"] = swept
    totals["tenants_failed"] = failed
    totals["tenants_scanned"] = scanned
    return totals


async def sweep_tenant(tenant_id: UUID) -> dict[str, int]:
    """Apply every expired policy for ONE tenant, inside that tenant's RLS context.

    One session, one probe, and a statement only where the probe found work. Counts
    only — no phone number, transcript text or extraction payload is read here or
    logged anywhere (hard rule 6).
    """
    totals = dict(_EMPTY_TOTALS)
    async with tenant_session(tenant_id) as session:
        # FIRST, and outside the policy loop. A scheduled erasure is an obligation this
        # tenant already incurred; it must not be skipped because their `recording` policy
        # row was deleted, nor deferred behind a large expiry batch on a busy tenant.
        totals["recording_holds"], hold_deferred = await _sweep_recording_holds(session)
        totals["deferred"] += int(hold_deferred)

        policies = (
            await session.execute(
                text(_PROBE_SQL),
                {
                    "floor": RECORDING_FLOOR_DAYS,
                    "mark": REDACTED_MARK,
                    "anon": ANONYMIZED_PHONE[:9],
                },
            )
        ).all()
        for category, ttl_days, action, has_work in policies:
            if str(category) == "recording" and int(ttl_days) < RECORDING_FLOOR_DAYS:
                alert("WORKER_TERMINAL", "retention_below_trai_floor", detail=f"{ttl_days}d")
            if not has_work:
                continue
            counts = await _apply_one(
                session,
                tenant_id=tenant_id,
                category=str(category),
                ttl_days=int(ttl_days),
                action=str(action),
            )
            for key, value in counts.items():
                totals[key] += value
    return totals


async def _sweep_in_batches(
    session: AsyncSession, statement: str, params: dict[str, Any]
) -> tuple[int, bool]:
    """Run one sweep statement until it stops matching rows or the budget runs out.

    Returns (rows, deferred). Every statement below narrows through a LIMITed,
    oldest-first subselect and leaves its rows no longer matching its own predicate, so
    the loop makes progress and terminates.
    """
    done = 0
    while done < TENANT_ROW_BUDGET:
        batch = min(SWEEP_BATCH_ROWS, TENANT_ROW_BUDGET - done)
        result = await session.execute(text(statement), {**params, "batch": batch})
        affected = rowcount_of(result)
        done += affected
        if affected < batch:
            return done, False
    return done, True


# RECORDINGS — the one sweep arm whose data is BYTES IN A BUCKET, and therefore the one
# that cannot be a single UPDATE either.
#
# WHAT WAS WRONG WITH THE SINGLE UPDATE. This arm used to be `UPDATE calls SET
# recording_url = NULL`, with a comment saying the object-store lifecycle rule removed
# the bytes. It does not, and SEC-COMP §4 says so in terms: `infra/object-lifecycle/` is
# a bucket-wide, prefix-scoped growth CEILING (`recordings/` at 2555 days), static while
# `retention_policies` is per tenant and editable, so it "CANNOT follow the retention
# policy". The consequence was that a tenant's 90-day recording policy expired the
# POINTER at 90 days and left the audio in the bucket for seven years — and once the
# pointer was gone nothing could name the key to delete it sooner. "Recordings are kept
# for 90 days" was true of a column and false of a person.
#
# So the same three-statement shape as the delivery bodies, in the same order and for the
# same reason: SELECT the keys, DELETE the objects, and only then clear the references.
# Clearing first would be one crash away from an object nothing can ever name again.
#
# NO FLOOR CHECK HERE, because the caller already applied one: `_apply_one` computes the
# cutoff from `max(ttl_days, RECORDING_FLOOR_DAYS)`, so every row this selects is past
# the floor by construction. Destroying the bytes at that moment is not the open decision
# SEC-COMP §4 reserves — that one is about audio YOUNGER than the floor, which this
# statement cannot select.
_RECORDING_SELECT_SQL = f"""
SELECT c.id, c.recording_url FROM calls c
WHERE c.recording_url IS NOT NULL AND {_CLOCK} < :cutoff
ORDER BY {_CLOCK} LIMIT :batch
"""

_RECORDING_CLEAR_SQL = """
UPDATE calls SET recording_url = NULL, updated_at = now() WHERE id = ANY(:ids)
"""

# SCHEDULED DESTRUCTIONS — the erasures that were owed and could not yet be performed.
#
# `execute_deletion_request` clears the pointer at any age, so for a recording inside the
# floor it writes a `recording_erasure_holds` row carrying the key and the earliest
# lawful instant instead of losing the handle. This is where that promise is kept.
#
# Swept OUTSIDE the policy loop and unconditionally, not as a fourth arm of the
# `recording` category: a DPDP obligation must not become conditional on the tenant still
# having a retention policy row of the right category. One indexed read per tenant per
# tick, against the partial index the migration created.
_HOLD_SELECT_SQL = """
SELECT id, object_key FROM recording_erasure_holds
WHERE erased_at IS NULL AND erase_after <= now()
ORDER BY erase_after LIMIT :batch
"""

_HOLD_MARK_SQL = """
UPDATE recording_erasure_holds SET erased_at = now() WHERE id = ANY(:ids)
"""

_TRANSCRIPT_DELETE_SQL = f"""
DELETE FROM transcript_turns WHERE id IN (
  SELECT t.id FROM transcript_turns t JOIN calls c ON c.id = t.call_id
  WHERE {_CLOCK} < :cutoff ORDER BY {_CLOCK} LIMIT :batch)
"""

# Anonymize keeps the SHAPE of the conversation (turn count, speakers, timings) for
# analytics while removing every word that was said.
_TRANSCRIPT_ANONYMIZE_SQL = f"""
UPDATE transcript_turns SET text = :mark, text_redacted = :mark, updated_at = now()
WHERE id IN (
  SELECT t.id FROM transcript_turns t JOIN calls c ON c.id = t.call_id
  WHERE {_CLOCK} < :cutoff AND t.text <> :mark ORDER BY {_CLOCK} LIMIT :batch)
"""

# DERIVED COPY of the transcript, on the transcript's clock. Cleared, never marked:
# `summary` is free prose with no shape worth keeping, and the DPDP erasure path
# already treats it as personal data.
_SUMMARY_SQL = f"""
UPDATE calls SET summary = NULL, updated_at = now() WHERE id IN (
  SELECT c.id FROM calls c WHERE c.summary IS NOT NULL AND {_CLOCK} < :cutoff
  ORDER BY {_CLOCK} LIMIT :batch)
"""

# Never a DELETE: leads carry FKs from lead_events and are referenced by calls.
# Anonymizing keeps the funnel countable and removes the person.
#
# The "already anonymized?" guard is the ANONYMIZED PHONE PREFIX, not the name. Keying
# it on `name IS NOT NULL` skipped every lead whose caller never gave a name — those
# rows still carry the phone number and the whole extraction payload, and they are
# exactly the rows the TTL exists for.
_LEAD_SQL = """
UPDATE leads SET phone_e164 = :anon || substr(id::text, 1, 8), name = NULL,
  data = '{}'::jsonb, deleted_at = COALESCE(deleted_at, now()), updated_at = now()
WHERE id IN (
  SELECT id FROM leads WHERE updated_at < :cutoff
    AND left(phone_e164, length(:anon)) <> :anon ORDER BY updated_at LIMIT :batch)
"""

# DERIVED COPY of the transcript that is ALSO the client's CRM — the caller's name,
# their callback number and every extracted field. On the lead clock, so the client
# keeps what they bought for as long as their lead policy says, and no longer.
# `moments` is cleared with `data` and by the same predicate. A key-moment label is
# DERIVED from the transcript and names what the caller said and when — "Caller asked not
# to be called again", and, for a model-authored one, a sentence quoting them. Leaving it
# behind after the extraction is emptied would be a second copy of the erased thing,
# surviving under a column nobody thought of: the D-126 shape, on a column added later.
# The predicate still keys on `data` alone so the sweep's batching is unchanged and a row
# whose data is already empty is not re-visited forever.
_EXTRACTION_SQL = """
UPDATE call_extractions
   SET data = '{}'::jsonb, moments = NULL, errors = NULL, updated_at = now()
WHERE id IN (
  SELECT id FROM call_extractions WHERE updated_at < :cutoff AND data <> '{}'::jsonb
  ORDER BY updated_at LIMIT :batch)
"""


# DELIVERED WEBHOOK BODIES (D-23) — the one arm of this sweep whose data lives outside
# Postgres, and therefore the one that cannot be a single UPDATE.
#
# Two statements with a storage call between them, in an order chosen so the failure mode
# is a survivable one: SELECT the keys, DELETE the objects, and only then clear the
# references. Clearing first would be one crash away from an ORPHAN — an object holding a
# lead's name and number that no query, no erasure and no later sweep can ever name
# again. The reverse residue (a reference to an object already deleted) is harmless: the
# read path reports it as gone, and the next tick clears it.
#
# `created_at` is the clock, not `last_at`: the body is what we sent, and a retry three
# days later does not make the payload younger.
_DELIVERY_BODY_SELECT_SQL = """
SELECT d.id, d.payload_ref FROM webhook_deliveries d
WHERE d.payload_ref IS NOT NULL AND d.direction = 'out'
  AND d.endpoint_id IN (SELECT id FROM outbound_webhooks)
  AND d.created_at < :cutoff
ORDER BY d.created_at LIMIT :batch
"""

_DELIVERY_BODY_CLEAR_SQL = """
UPDATE webhook_deliveries SET payload_ref = NULL
WHERE id = ANY(:ids) AND endpoint_id IN (SELECT id FROM outbound_webhooks)
"""

# ARCHIVED RAW ENGINE PAYLOADS (D-126) on the tenant's own clock (D-179). One page of
# calls at a time, oldest first; the destruction itself is `_erase_engine_payloads`,
# unchanged and shared with both erasure paths — this arm supplies the call ids and
# nothing else.
#
# Sharing that function rather than writing a fourth `_sweep_objects_in_batches` call is
# the point: the archive is the one store where the key column names ONE object and the
# prefix can hold several (a document per status transition), so a key-driven sweep would
# leave siblings behind that no later pass could name. There is one definition of "destroy
# a call's archived payloads" and this is a second caller of it.
_PAYLOAD_PAGE_SQL = f"""
SELECT c.id FROM calls c
WHERE c.engine_payload_ref IS NOT NULL AND {_CLOCK} < :cutoff
ORDER BY {_CLOCK} LIMIT :batch
"""

# SUPERSEDED KNOWLEDGE-BASE VERSIONS (D-179). A DELETE, not an anonymize: a chunk of a
# client's price list has no shape worth keeping once its text is gone — the same
# argument `_SUMMARY_SQL` makes for clearing a summary rather than marking it — and a row
# whose `content` was blanked would still be a version the rollback screen offers.
#
# `kb_documents` goes with it by FK CASCADE, which is where the personal data actually
# lives; the source row is deleted too because its `name` is client-authored prose ("Dr
# Rao's Monday clinic") and a tombstone that keeps the title of the thing it forgot is
# not a forgetting.
#
# `updated_at` is the clock, and on an archived row it IS the supersession instant:
# `publish_source` stamps it in the UPDATE that flips `is_active` to false.
_KB_EXPIRE_SQL = f"""
DELETE FROM kb_sources WHERE id IN (
  SELECT s.id FROM kb_sources s
  WHERE {_KB_EXPIRABLE} AND s.updated_at < :cutoff
  ORDER BY s.updated_at LIMIT :batch)
"""


async def _sweep_objects_in_batches(
    session: AsyncSession,
    *,
    select_sql: str,
    finish_sql: str,
    params: dict[str, Any],
    deferred_event: str,
) -> tuple[int, bool]:
    """`_sweep_in_batches` for the arms whose data is BYTES: select, delete, then finish.

    ONE implementation for the three of them — delivered CRM bodies, expiring recordings,
    and the scheduled destructions an erasure deferred. They were not going to be three
    hand-written loops: each one has the same two ways to be wrong (clear the reference
    before the object and you orphan the bytes; treat an outage as "nothing there" and you
    lose them silently), and the second and third copies are where the drift starts.

    `select_sql` returns `(id, object_key)` oldest-first under `:batch`. `finish_sql`
    takes `:ids` and must leave those rows no longer matching `select_sql`, so the loop
    terminates. Returns (rows, deferred).

    A store that will not answer STOPS this arm rather than failing the tick: every other
    category still expires, the references stay pointing at objects that still exist, and
    the next tick starts from the same oldest rows. Reported as a warning with a reason —
    an alert per tick during an object-store outage would be an alarm nobody reads, and
    nothing here is overdue by an amount that matters within one night. Keys are never
    logged: a delivery-body key contains the subject's row id (hard rule 6).
    """
    done = 0
    while done < TENANT_ROW_BUDGET:
        batch = min(SWEEP_BATCH_ROWS, TENANT_ROW_BUDGET - done)
        rows = (await session.execute(text(select_sql), {**params, "batch": batch})).all()
        if not rows:
            return done, False
        try:
            await storage.delete_objects([str(row[1]) for row in rows])
        except storage.StorageUnavailableError as exc:
            log.warning(deferred_event, extra={"reason": str(exc), "pending": len(rows)})
            return done, True
        await session.execute(text(finish_sql), {"ids": [row[0] for row in rows]})
        done += len(rows)
        if len(rows) < batch:
            return done, False
    return done, True


async def _sweep_recording_holds(session: AsyncSession) -> tuple[int, bool]:
    """Destroy the audio of every erasure whose lawful moment has arrived.

    The other half of `execute_deletion_request`'s deferral. Nothing here consults a
    retention policy: `erase_after` was fixed when the hold was written, against the
    call's own clock, and re-deriving it now against a policy the tenant may since have
    lengthened would let a client postpone somebody's erasure by editing a setting.
    """
    return await _sweep_objects_in_batches(
        session,
        select_sql=_HOLD_SELECT_SQL,
        finish_sql=_HOLD_MARK_SQL,
        params={},
        deferred_event="recording_hold_erasure_deferred",
    )


async def _sweep_engine_payloads(
    session: AsyncSession, *, tenant_id: UUID, cutoff: datetime
) -> tuple[int, bool]:
    """Destroy the archived vendor documents of every call past this tenant's TTL.

    Returns (objects, deferred). Pages calls oldest-first and hands each page to
    `_erase_engine_payloads`, which lists the `{tenant}/{call}` prefix, deletes what it
    finds and clears the references in the same transaction — so a page stops matching
    this statement and the loop terminates.

    A store that will not answer STOPS this arm rather than failing the tick, exactly as
    `_sweep_objects_in_batches` does and for the same reason: every other category still
    expires, no reference is cleared over a surviving object, and the next tick starts
    from the same oldest calls. The erasure path makes the opposite choice — there a
    refusal RAISES, because a certificate must not claim a destruction that did not
    happen — and the asymmetry is deliberate: a sweep that is one night late owes nobody
    a document.

    TWO COUNTERS, because they count different things and conflating them would make the
    budget meaningless: `objects` is what this arm reports (one call can hold several
    archived documents), and `calls` is what the per-tenant row budget bounds. A single
    counter would let a tenant whose references all name absent objects walk their whole
    call table in one tick while reporting zero, which is the opposite of what the budget
    is for.
    """
    objects = 0
    calls = 0
    while calls < TENANT_ROW_BUDGET:
        batch = min(SWEEP_BATCH_ROWS, TENANT_ROW_BUDGET - calls)
        page = (
            (await session.execute(text(_PAYLOAD_PAGE_SQL), {"cutoff": cutoff, "batch": batch}))
            .scalars()
            .all()
        )
        if not page:
            return objects, False
        call_ids = [UUID(str(row)) for row in page]
        try:
            objects += await _erase_engine_payloads(session, tenant_id=tenant_id, call_ids=call_ids)
        except storage.StorageUnavailableError as exc:
            log.warning(
                "engine_payload_expiry_deferred",
                extra={"reason": str(exc), "pending": len(call_ids)},
            )
            return objects, True
        # AFTER the objects are gone, and this is what makes the loop terminate rather
        # than being tidiness. `_erase_engine_payloads` returns early — clearing nothing —
        # when the prefix holds no objects, and that state is REACHABLE: `archive_payload`
        # commits the reference BEFORE the PUT, so a worker that died in between left a
        # reference naming an object that never existed. Those rows would match this
        # page's SELECT for ever. The statement is idempotent with the one inside the
        # erasure helper, and it can only ever clear a reference whose object has already
        # been deleted or was never written.
        await session.execute(
            text(
                "UPDATE calls SET engine_payload_ref = NULL, updated_at = now() "
                "WHERE id = ANY(:ids) AND engine_payload_ref IS NOT NULL"
            ),
            {"ids": call_ids},
        )
        calls += len(call_ids)
        if len(call_ids) < batch:
            return objects, False
    return objects, True


async def _apply_one(
    session: AsyncSession, *, tenant_id: UUID, category: str, ttl_days: int, action: str
) -> dict[str, int]:
    counts = dict(_EMPTY_TOTALS)
    if category == "consent_log":
        # Append-only ledger (hard rule 4). The category exists in the table so the
        # policy is explicit rather than forgotten, but nothing expires it on a timer.
        return counts

    if category == "recording":
        effective = max(ttl_days, RECORDING_FLOOR_DAYS)
        cutoff = datetime.now(UTC) - timedelta(days=effective)
        # The AUDIO goes, then the pointer. Keeping the call row keeps its metering
        # intact; keeping the bytes would make "recordings are kept for N days" a
        # statement about a column (see `_RECORDING_SELECT_SQL`).
        counts["recordings"], deferred = await _sweep_objects_in_batches(
            session,
            select_sql=_RECORDING_SELECT_SQL,
            finish_sql=_RECORDING_CLEAR_SQL,
            params={"cutoff": cutoff},
            deferred_event="recording_expiry_deferred",
        )
        counts["deferred"] += int(deferred)
        return counts

    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)

    if category == "engine_payload":
        # `action` is not read, and the reason is worth stating rather than leaving as a
        # silent omission: the archive is an opaque vendor document in an object store.
        # There is no anonymized form of it — we do not parse it, and a partially
        # rewritten copy of the engine's own record would be worth less than either
        # keeping it or destroying it. A policy row saying `anonymize` therefore destroys,
        # and SEC-COMP §4 says so in the words a client reads.
        counts["engine_payloads"], deferred = await _sweep_engine_payloads(
            session, tenant_id=tenant_id, cutoff=cutoff
        )
        counts["deferred"] += int(deferred)
        return counts

    if category == "kb":
        # `action` is not read here either, for `_SUMMARY_SQL`'s reason: a knowledge chunk
        # is free prose, so there is no shape to keep once the words are gone, and a
        # blanked row would still be a version the rollback screen offers.
        counts["kb_versions"], deferred = await _sweep_in_batches(
            session, _KB_EXPIRE_SQL, {"cutoff": cutoff}
        )
        counts["deferred"] += int(deferred)
        return counts

    if category == "transcript":
        if action == "delete":
            counts["transcripts"], deferred = await _sweep_in_batches(
                session, _TRANSCRIPT_DELETE_SQL, {"cutoff": cutoff}
            )
        else:
            counts["transcripts"], deferred = await _sweep_in_batches(
                session, _TRANSCRIPT_ANONYMIZE_SQL, {"cutoff": cutoff, "mark": REDACTED_MARK}
            )
        counts["deferred"] += int(deferred)
        counts["summaries"], deferred = await _sweep_in_batches(
            session, _SUMMARY_SQL, {"cutoff": cutoff}
        )
        counts["deferred"] += int(deferred)
        return counts

    if category == "lead":
        counts["leads"], deferred = await _sweep_in_batches(
            session, _LEAD_SQL, {"cutoff": cutoff, "anon": ANONYMIZED_PHONE[:9]}
        )
        counts["deferred"] += int(deferred)
        counts["extractions"], deferred = await _sweep_in_batches(
            session, _EXTRACTION_SQL, {"cutoff": cutoff}
        )
        counts["deferred"] += int(deferred)
        counts["delivery_bodies"], deferred = await _sweep_objects_in_batches(
            session,
            select_sql=_DELIVERY_BODY_SELECT_SQL,
            finish_sql=_DELIVERY_BODY_CLEAR_SQL,
            params={"cutoff": cutoff},
            deferred_event="delivery_body_expiry_deferred",
        )
        counts["deferred"] += int(deferred)
        return counts

    return counts


async def _erase_delivery_bodies(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    subjects: Iterable[tuple[str, str]],
) -> int:
    """Destroy every retained webhook body belonging to these subjects. Returns the count.

    THE OBJECT STORE IS THE AUTHORITY HERE, not `webhook_deliveries.payload_ref`, and the
    difference matters exactly once: the delivery worker writes the object BEFORE it
    records the reference, so a worker that died in between left an object with no row
    pointing at it. A DB-driven erasure would walk straight past that object — and an
    object holding a data principal's name and number that no erasure can reach is the
    breach this whole design exists to avoid. Listing by the key's subject prefix finds
    it, because the subject is IN the key (`storage.delivery_body_key`).

    RAISES `StorageUnavailableError` (an `arq.Retry`) when the store will not answer.
    That aborts the erasure and rolls the transaction back, so `completed_at` stays NULL
    and the idempotency guard lets the retry redo the whole thing. The alternative —
    proceed and note it — writes a certificate that says "erased" over a copy we did not
    look for, and a proof that overclaims is worse than one that has not been issued yet.
    """
    # A tenant with no outbound endpoint has never had a delivered body, so there is
    # nothing to enumerate. Asked FIRST, and not as an optimisation: without it every
    # erasure on the platform — including the overwhelming majority, for clients who have
    # configured no CRM sync at all — would depend on the object store being up, and a
    # storage outage would stop DPDP erasures that have nothing to do with storage.
    #
    # Sound in both directions. A body is only ever written by the delivery worker, which
    # loads an endpoint row first; and endpoints are DEACTIVATED, never deleted
    # (`integrations/routes.deactivate_endpoint` keeps the row precisely so the delivery
    # history stays readable), so "had a delivery once" implies "has a row now".
    has_endpoint = (await session.execute(text("SELECT 1 FROM outbound_webhooks LIMIT 1"))).first()
    if has_endpoint is None:
        return 0

    keys: list[str] = []
    for subject_type, subject_id in subjects:
        keys += await storage.keys_under(
            storage.delivery_body_subject_prefix(
                tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id
            )
        )
    if not keys:
        return 0
    await storage.delete_objects(keys)
    # The reference goes in the same transaction as the rest of the erasure. Scoped
    # through `outbound_webhooks` because this table has no RLS policy — the same reason
    # every other query against it in this codebase carries that subquery.
    await session.execute(
        text(
            "UPDATE webhook_deliveries SET payload_ref = NULL WHERE payload_ref = ANY(:keys) "
            "AND endpoint_id IN (SELECT id FROM outbound_webhooks)"
        ),
        {"keys": keys},
    )
    return len(keys)


async def _erase_engine_payloads(
    session: AsyncSession, *, tenant_id: UUID, call_ids: Sequence[UUID]
) -> int:
    """Destroy every archived RAW vendor payload for these calls. Returns the count.

    The archive (`storage.archive_payload`) keeps the engine's own webhook/poll document
    for a call, and that document carries the caller's number and the transcript — so it
    is personal data with an erasure duty, not an inert debug artifact, and D-126 gave its
    key a `{tenant}/{call}` prefix precisely so this arm could exist. It is written the
    same shape as `_erase_delivery_bodies` and for the same three reasons:

    * **The DELETE is driven by the object store, not by the column.** One call can hold
      several archived documents — the engine fires a payload per status transition — and
      `engine_payload_ref` holds one key. Listing the call's prefix destroys all of them,
      including any sibling no column ever named.
    * **A refusal to answer RAISES** (`StorageUnavailableError` is an `arq.Retry`), which
      rolls the erasure back and leaves `completed_at` NULL for the retry. A certificate
      that claims a destruction we did not attempt is the one failure worse than a late
      certificate.
    * **The reference is cleared in the same transaction as the delete**, so no cleared
      pointer ever outlives a surviving object and no surviving pointer names a deleted
      one.

    WHY THE COLUMN GATES THE LISTING, when `_erase_delivery_bodies`' equivalent gate is a
    table probe. Without a gate every DPDP erasure on the platform would depend on the
    object store being up — a storage outage would stop erasures that have nothing to do
    with storage — which is the argument that path already makes and this one does not get
    to ignore. The gate is a PK lookup over the calls being erased, and it is sound in both
    directions because `archive_payload` states the write order it requires: the reference
    is committed BEFORE the object is PUT. A reference naming an object that does not exist
    is harmless (deleting an absent key is a no-op); an object no reference names would be
    unreachable, which is the defect this whole change exists to remove. Once any of these
    calls carries a reference the listing runs over ALL of them, so a sibling that lost its
    own reference is still destroyed.

    THE PRODUCER NOW EXISTS, and this arm is no longer guarding an empty store: D-126 built
    it BEFORE the producer because after the producer the unreachable objects already do,
    and `pipeline._archive_engine_document` is that producer. It commits
    `engine_payload_ref` before the PUT, which is exactly what keeps the gate above sound.
    """
    if not call_ids:
        return 0
    # The gate. `id = ANY(...)` is the primary key, so this is an index probe over the
    # calls in hand rather than a scan of a column with one writer.
    archived = (
        await session.execute(
            text(
                "SELECT 1 FROM calls WHERE id = ANY(:ids) AND engine_payload_ref IS NOT NULL "
                "LIMIT 1"
            ),
            {"ids": list(call_ids)},
        )
    ).first()
    if archived is None:
        return 0

    keys: list[str] = []
    for call_id in call_ids:
        keys += await storage.keys_under(
            storage.payload_call_prefix(tenant_id=tenant_id, call_id=call_id)
        )
    if not keys:
        return 0
    await storage.delete_objects(keys)
    # RLS scopes this to the tenant; `calls` is not an append-only table (hard rule 4's
    # registry names neither it nor any object-ref column), so clearing the ref is a
    # plain UPDATE rather than a compensating entry.
    await session.execute(
        text(
            "UPDATE calls SET engine_payload_ref = NULL, updated_at = now() "
            "WHERE id = ANY(:ids) AND engine_payload_ref IS NOT NULL"
        ),
        {"ids": list(call_ids)},
    )
    return len(keys)


# The recordings this erasure reached, split by whether destroying them is lawful TODAY.
# Read BEFORE the pointer clear — afterwards the question is unanswerable, which is how
# the whole collision stayed invisible.
_ERASURE_RECORDINGS_SQL = f"""
SELECT c.id, c.recording_url,
       {_CLOCK} + make_interval(days => :floor) AS lawful_at
FROM calls c
WHERE c.id = ANY(:ids) AND c.recording_url IS NOT NULL
"""

# `ON CONFLICT DO NOTHING` on the (tenant_id, object_key) unique: a retried erasure — the
# storage outage below rolls the whole transaction back and arq runs it again — must
# re-record the same hold without failing on its own previous attempt. Nothing about a
# hold changes between attempts, so DO NOTHING is the correct resolution rather than an
# upsert that would move `erase_after` on every retry.
# EXACTLY ONE OWNER, and the database says so (`ck_recording_hold_one_owner`, migration
# f3a71c9e26b4). A hold is an obligation one erasure incurred, and there are two kinds of
# erasure now — one data principal's §12 request (`deletion_requests`) and the end of an
# engagement (`tenant_erasure_requests`). Both must be able to schedule a destruction,
# and a destruction must name the certificate that promised it, so the arc is exclusive
# rather than one nullable column reused for two meanings.
_HOLD_INSERT_SQL = """
INSERT INTO recording_erasure_holds
  (id, tenant_id, call_id, request_id, tenant_erasure_id, object_key, erase_after,
   created_at)
VALUES (:id, :tid, :cid, :rid, :teid, :key, :erase_after, now())
ON CONFLICT (tenant_id, object_key) DO NOTHING
"""


async def _erase_recordings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_ids: list[UUID],
    hold_deletion_request_id: UUID | None = None,
    hold_tenant_erasure_id: UUID | None = None,
) -> tuple[int, int, datetime | None]:
    """Destroy the audio this erasure may destroy; SCHEDULE the audio it may not yet.

    Returns `(within_floor, destroyed, latest_scheduled_destruction)`.

    THE TENSION, AND WHAT THIS FUNCTION DOES AND DOES NOT DECIDE. SEC-COMP §4 records an
    open decision: for a recording younger than the retention floor, §4's erasure duty and
    §1's floor point opposite ways, and the founder reserves the choice. This function
    does not take it. It never destroys a recording inside the floor, and it does not make
    the POINTER clear conditional on age — the caller still nulls `recording_url` for
    every matched call, exactly as before, which is what §4 forbids changing without the
    decision.

    What it settles is the part that was never a question: a recording PAST the floor.
    There is no rule requiring its retention, DPDP §12(3) obliges erasure "unless
    retention of the same is necessary for the specified purpose or for compliance with
    any law for the time being in force", and no such law reaches it — so the bytes go
    now. And for a recording inside the floor, the lawful basis for keeping it is
    TIME-LIMITED; DPDP §8(7)'s storage limitation makes holding it past that point a
    breach on its own. A deferral is therefore a SCHEDULE, and the hold row is the handle
    the sweep needs to keep it. Before this function existed the pointer clear destroyed
    that handle, so an erasure request made the audio permanently undeletable — which is
    not either side of the open decision, it is the failure to have one.

    Storage refusing to answer RAISES (`StorageUnavailableError` is an `arq.Retry`), which
    rolls the transaction back and leaves `completed_at` NULL for the retry. Same contract
    as `_erase_delivery_bodies` and for the same reason: a certificate claiming a
    destruction we did not perform is worse than one not yet issued.
    """
    # Mirrors `ck_recording_hold_one_owner`. The database is the authority; this is here
    # so a caller that gets it wrong is told which call site is wrong, rather than
    # discovering it as a CheckViolation from an INSERT several frames down.
    if (hold_deletion_request_id is None) == (hold_tenant_erasure_id is None):
        raise ValueError("a recording hold needs exactly one owning erasure request")

    rows = (
        await session.execute(
            text(_ERASURE_RECORDINGS_SQL),
            {"ids": call_ids, "floor": RECORDING_FLOOR_DAYS},
        )
    ).all()
    if not rows:
        return 0, 0, None

    now = datetime.now(UTC)
    destroy_now: list[str] = []
    defer: list[tuple[UUID, str, datetime]] = []
    for call_id, key, lawful_at in rows:
        if lawful_at <= now:
            destroy_now.append(str(key))
        else:
            defer.append((UUID(str(call_id)), str(key), lawful_at))

    if destroy_now:
        await storage.delete_objects(destroy_now)
    for call_id, key, lawful_at in defer:
        await session.execute(
            text(_HOLD_INSERT_SQL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "cid": call_id,
                "rid": hold_deletion_request_id,
                "teid": hold_tenant_erasure_id,
                "key": key,
                "erase_after": lawful_at,
            },
        )
    latest = max((lawful_at for _, _, lawful_at in defer), default=None)
    return len(defer), len(destroy_now), latest


#: The campaign contact row, erased in place. Never a DELETE, for `_LEAD_SQL`'s reason
#: turned around: `campaign_contacts` is referenced by nothing, but a running campaign
#: counts its own rows to decide when it is finished, and removing them mid-flight would
#: make a campaign that has dialled 400 of 500 people report a total of 100.
#:
#: **`status = 'dnc_blocked'` IS THE LOAD-BEARING PART.** Anonymizing the number alone
#: would leave the row `pending` with a live campaign behind it, and the dispatcher reads
#: `status`, not the number — so the erasure would have been followed by a dial. That is
#: the second consequence P3.1 names and the one that is not merely a records gap: **we
#: would ring a person whose certificate says they were removed.** `dnc_blocked` is
#: already the status the compliance gate's own refusal writes, so a settled campaign
#: reports this row exactly as it reports one the DNC list stopped, and no reader needs a
#: new state.
#:
#: **`dedupe_hash` IS CLEARED TOO, and it is not in the finding.** It holds
#: `sha256(phone)[:16]` — unsalted, and Indian mobile E.164 is a ~10^9 space anyone can
#: enumerate in seconds, so leaving it is leaving the number in a form that reverses. It
#: is only a dedupe key within one upload, so nothing reads it after the import.
#:
#: `custom` is the whole of what the client pasted from their CSV beside the phone and
#: the name — every other column, whatever it was — so it is emptied rather than
#: inspected. We do not know what is in it, which is precisely why it cannot stay.
_CAMPAIGN_CONTACT_ERASE_SQL = """
UPDATE campaign_contacts
SET phone_e164 = :anon || substr(id::text, 1, 8),
    name = NULL,
    custom = NULL,
    dedupe_hash = NULL,
    status = 'dnc_blocked',
    next_attempt_at = NULL,
    updated_at = now()
WHERE {predicate}
  AND left(phone_e164, length(:anon)) <> :anon
"""


async def _erase_campaign_contacts(session: AsyncSession, *, phone: str | None = None) -> int:
    """Erase this subject's uploaded contact rows — or every one in the tenant.

    ONE STATEMENT, TWO CALLERS, because the alternative is two statements that drift and
    a certificate that is right about one erasure and wrong about the other. `phone=None`
    is the tenant-wide arm; a number is the per-subject arm.

    THE GAP THIS CLOSES (P3.1). The string `campaign_contacts` appeared in NEITHER erasure
    path, and the table carries `phone_e164 NOT NULL`, `name`, and a `custom` JSONB
    holding every other column the client pasted from their CSV. So a data principal who
    exercised DPDP §12 got a certificate saying their record was removed while their
    number, their name and their pasted details sat in a campaign list — and the row was
    still `pending`, so the next dispatch tick would have called them.

    THE ANONYMIZED PREFIX IS THE ALREADY-DONE GUARD, exactly as in `_LEAD_SQL`, and for
    the same reason: keying on `name IS NOT NULL` would skip every row whose upload
    carried no name, which are the rows that consist of nothing but a phone number.

    The per-row `substr(id::text, 1, 8)` keeps `uq_campaign_contacts_campaign_id_phone_e164`
    satisfiable — two erased contacts in one campaign would otherwise collide on a
    constant and abort the whole erasure.
    """
    predicate = "TRUE" if phone is None else "phone_e164 = :phone"
    params: dict[str, Any] = {"anon": ANONYMIZED_PHONE[:9]}
    if phone is not None:
        params["phone"] = phone
    result = await session.execute(
        text(_CAMPAIGN_CONTACT_ERASE_SQL.format(predicate=predicate)), params
    )
    return int(rowcount_of(result) or 0)


# THE KNOWLEDGE-BASE SEARCH — what an erasure can honestly do about a client's own
# uploaded content, and what it must not do (D-179, LEGAL-SURFACE F-3).
#
# The register used to tell a data principal the knowledge base was "not searched". That
# was true and it was the wrong true thing: a client's FAQ can contain a caller's callback
# number — the AUP now forbids putting personal data there, which is a term, not a
# mechanism — and "we did not look" is not an answer a Fiduciary can give when looking is
# one query.
#
# So the erasure LOOKS and REPORTS, and does not delete. Three reasons it stops there:
#
#   * The content is the CLIENT'S OWN, written by them for their agent to quote. Deleting
#     a paragraph out of a live price list because a phone number appears in it would
#     silently change what the agent says on the next call, and we cannot tell a callback
#     number from the shop's own landline.
#   * The engine holds a copy of the live version. Editing ours without theirs would make
#     the two disagree, which is the divergence the reconciliation sweep (D-158) exists to
#     catch — the erasure would be manufacturing the incident.
#   * A count is what makes the manual step ACTIONABLE. "Two of your knowledge documents
#     mention this number" is a task; "the knowledge base was not searched" is a shrug.
#
# `strpos` rather than `LIKE '%'||…||'%'`: the number is a substring, not a pattern, so
# there is nothing for a wildcard to add — and a literal `%` inside a `text()` statement
# is a paramstyle hazard this file has no other example of and does not need a first one.
#
# THE MATCH IS ON DIGITS, not on the E.164 string. A client pastes "call 98765 43210" or
# "+91-98765-43210" — never the form the CRM holds — so a `LIKE '%+919876543210%'` would
# report zero on exactly the documents this exists to find. Both sides are stripped to
# digits and the subscriber number (the last ten) is what is compared: enough to be
# specific in the Indian mobile space, and forgiving of every separator. It over-matches
# rather than under-matches by design — a false positive costs a human one look at a
# document, a false negative costs a person their erasure.
_KB_SUBJECT_MATCH_SQL = """
SELECT count(*) FROM kb_documents
WHERE strpos(regexp_replace(content, '[^0-9]', '', 'g'), :digits) > 0
"""


async def _search_knowledge_base(session: AsyncSession, *, phone: str) -> int:
    """How many knowledge documents mention this number. Reads; never writes.

    RLS scopes it to the tenant (hard rule 1). The count is all that leaves this function
    — no document id, no title, no content — because it travels into a proof that is
    filed and forwarded, and "which document" is a question the client answers on their
    own screen with their own access.
    """
    digits = "".join(character for character in phone if character.isdigit())[-10:]
    if not digits:
        return 0
    matched = (await session.execute(text(_KB_SUBJECT_MATCH_SQL), {"digits": digits})).scalar()
    return int(matched or 0)


async def execute_deletion_request(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """DPDP erasure for one phone number, with a proof certificate (SEC-COMP §4).

    Locate → erase → prove. The proof records counts and row hashes, never the number
    itself, so the certificate can be handed to the requester and kept indefinitely
    without becoming another copy of the data it attests was removed.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    request_id = UUID(str(payload["request_id"]))

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT phone_e164, completed_at FROM deletion_requests WHERE id = :rid"),
                {"rid": request_id},
            )
        ).first()
        if row is None:
            return "not_found"
        completed_at = row[1]
        if completed_at is not None:
            # Idempotent: an erasure re-run must not produce a second, weaker proof.
            # Checked BEFORE the number is read, because a completed request no longer
            # has one — it is cleared by the write below (migration f4a8e1c07b62).
            return "already_completed"
        phone = str(row[0])

        # `erased_subject_ref` is in the predicate because the two phone columns are
        # CLEARED by the UPDATE below, so a call this subject's earlier erasure already
        # covered would otherwise be unreachable to this one — and records DO arrive for
        # it afterwards (a call still in flight when that erasure ran; D-310,
        # `compliance/deletion.refile_erasure_for_late_records`). Finding it again is the
        # difference between a standing instruction and one certificate.
        subject_handle = _hash(phone)
        calls = (
            (
                await session.execute(
                    text(
                        "SELECT id FROM calls WHERE from_e164 = :phone OR to_e164 = :phone "
                        "OR erased_subject_ref = :ref"
                    ),
                    {"phone": phone, "ref": subject_handle},
                )
            )
            .scalars()
            .all()
        )
        leads = (
            (
                await session.execute(
                    text("SELECT id FROM leads WHERE phone_e164 = :phone"), {"phone": phone}
                )
            )
            .scalars()
            .all()
        )

        # Every subject a retained delivery body could be filed under, for THIS request.
        # The calls' own `lead_id` is unioned in as well as the phone-matched leads: a
        # `lead.*` body is keyed by the lead, and a lead whose own number was already
        # anonymized by an earlier sweep would not be in `leads` above even though its
        # body is plainly this person's. Belt and braces on the erasure side costs one
        # extra prefix listing; missing a copy costs a DPDP breach.
        linked_leads = (
            (
                (
                    await session.execute(
                        text(
                            "SELECT DISTINCT lead_id FROM calls "
                            "WHERE id = ANY(:ids) AND lead_id IS NOT NULL"
                        ),
                        {"ids": list(calls)},
                    )
                )
                .scalars()
                .all()
            )
            if calls
            else []
        )
        bodies_erased = await _erase_delivery_bodies(
            session,
            tenant_id=tenant_id,
            subjects=[("call", str(c)) for c in calls]
            + [("lead", str(lead)) for lead in {*leads, *linked_leads}],
        )

        turns_erased = 0
        extractions_erased = 0
        recordings_in_floor = 0
        recordings_destroyed = 0
        payloads_erased = 0
        held_until: datetime | None = None
        if calls:
            payloads_erased = await _erase_engine_payloads(
                session, tenant_id=tenant_id, call_ids=list(calls)
            )
            recordings_in_floor, recordings_destroyed, held_until = await _erase_recordings(
                session,
                tenant_id=tenant_id,
                call_ids=list(calls),
                hold_deletion_request_id=request_id,
            )
            result = await session.execute(
                text(
                    "UPDATE transcript_turns SET text = :mark, text_redacted = :mark, "
                    "updated_at = now() WHERE call_id = ANY(:ids)"
                ),
                {"mark": REDACTED_MARK, "ids": list(calls)},
            )
            turns_erased = int(rowcount_of(result) or 0)
            await session.execute(
                text(
                    "UPDATE calls SET from_e164 = NULL, to_e164 = NULL, recording_url = NULL, "
                    "summary = NULL, erased_subject_ref = :ref, updated_at = now() "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": list(calls), "ref": subject_handle},
            )
            # The DERIVED copy. `call_extractions.data` is the caller's name, their
            # callback number and every schema field the model captured — erasing the
            # transcript and leaving this behind means the person is still on file, and
            # the proof certificate would have said otherwise.
            result = await session.execute(
                text(
                    "UPDATE call_extractions SET data = '{}'::jsonb, moments = NULL, "
                    "errors = NULL, updated_at = now() "
                    "WHERE call_id = ANY(:ids) AND data <> '{}'::jsonb"
                ),
                {"ids": list(calls)},
            )
            extractions_erased = int(rowcount_of(result) or 0)
        if leads:
            await session.execute(
                text(
                    "UPDATE leads SET phone_e164 = :anon || substr(id::text, 1, 8), name = NULL, "
                    "data = '{}'::jsonb, deleted_at = now(), updated_at = now() "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": list(leads), "anon": ANONYMIZED_PHONE[:9]},
            )

        # KEYED ON THE NUMBER, not on `calls` or `leads`, and that is the point. A
        # campaign contact this person is on may have been uploaded and never dialled, so
        # there is no call to find them by and no lead either — which is exactly the row
        # that would have been dialled AFTER the certificate was issued.
        contacts_erased = await _erase_campaign_contacts(session, phone=phone)

        # LOOKED AT, never changed — see `_search_knowledge_base` for why the erasure
        # stops at a count. Run last, so a store this request could not reach has already
        # raised and the number is never reported on an erasure that then rolled back.
        kb_matches = await _search_knowledge_base(session, phone=phone)

        proof = {
            "subject_hash": _hash(phone),
            "executed_at": datetime.now(UTC).isoformat(),
            "scope": {
                "calls": [_hash(str(c)) for c in calls],
                "leads": [_hash(str(lead)) for lead in leads],
                "transcript_turns_erased": turns_erased,
                "call_extractions_erased": extractions_erased,
                # How many of those calls still held a recording pointer INSIDE the
                # 90-day floor when this erasure ran — i.e. how many audio files the
                # request could not lawfully destroy. Always written, including 0: on
                # this field "absent" means "an older worker did not record it" and
                # only a recorded 0 supports the certificate saying "none".
                FLOOR_COUNT_KEY: recordings_in_floor,
                # How many audio files this request actually DESTROYED — the ones past
                # the floor, where nothing required their retention. Nullable in the
                # certificate model for the same reason as the field above: a proof
                # written before this arm existed recorded no such number, and hard rule
                # 4 forbids back-filling one.
                DESTROYED_COUNT_KEY: recordings_destroyed,
                # When the LAST of the deferred ones is destroyed, so the certificate can
                # give the data principal a date instead of "treat the audio as still
                # existing indefinitely". Null when nothing was deferred.
                HOLD_UNTIL_KEY: held_until.isoformat() if held_until is not None else None,
                # In `scope` rather than only in `actions`, unlike the three counts
                # below it: the certificate's knowledge-base ENTRY reports this number
                # to the data principal, and an entry that carries a count needs the
                # count in the part of the proof the renderer reads by name.
                KB_MATCH_KEY: kb_matches,
            },
            "actions": {
                "calls": "phone numbers, recording pointer and summary cleared",
                "recordings": (
                    f"{recordings_destroyed} audio file(s) destroyed in object storage; "
                    f"{recordings_in_floor} scheduled for destruction on expiry of the "
                    f"{RECORDING_FLOOR_DAYS}-day retention floor"
                ),
                "transcript_turns": "text and text_redacted replaced",
                "call_extractions": "extracted field payload cleared",
                "leads": "phone anonymized, name and extracted fields cleared",
                # Counted in the sentence rather than in `scope`, because the
                # certificate renderer builds `scope` from a fixed field list
                # (`compliance/deletion_proof.certificate`) and `actions` is the part
                # that passes through verbatim. A number a client can read beats a
                # number only this file knows.
                "webhook_deliveries": (
                    f"{bodies_erased} delivered CRM payload(s) deleted from object "
                    "storage and their references cleared"
                ),
                # Counted in the sentence rather than in `scope`, for the reason the line
                # above is: `scope` is a whitelist the certificate renderer and the
                # response model both enumerate, so a number added there is a wire-shape
                # change, and `actions` is the part that passes through verbatim.
                "engine_payloads": (
                    f"{payloads_erased} archived raw engine payload(s) deleted from "
                    "object storage and their references cleared"
                ),
                # The count is in the sentence for the same reason the two above are:
                # `scope` is a whitelist both the certificate renderer and the response
                # model enumerate, so a number added there is a wire-shape change.
                "campaign_contacts": (
                    f"{contacts_erased} uploaded campaign contact row(s): phone "
                    "anonymized, name, pasted columns and dedupe hash cleared, and the "
                    "row set to dnc_blocked so no campaign can dial it"
                ),
                "kb_sources": (
                    f"searched: {kb_matches} uploaded knowledge document(s) mention this "
                    "number. Client-authored content — read, not changed by this request"
                ),
                "usage_events": "retained — append-only ledger, carries no personal data",
                "consent_ledger": "retained — append-only proof that consent existed",
            },
            # Stated, not asserted: Bolna's deletion API is undocumented (pilot gate),
            # so the certificate must not claim an engine-side deletion we cannot show.
            "engine_deletion": "unconfirmed_pending_vendor_api",
        }
        # The number goes in the SAME write that records the proof. Until this statement
        # the row is the worker's only handle on the subject; after it, the row would
        # otherwise be the last surviving copy of a number we just certified as erased,
        # on a table no retention policy sweeps (migration f4a8e1c07b62). `subject_ref`
        # stays, so "have we already erased this person?" is still answerable to anyone
        # who holds the number — and to nobody who does not.
        await session.execute(
            text(
                "UPDATE deletion_requests SET completed_at = now(), proof = CAST(:proof AS jsonb),"
                " phone_e164 = NULL WHERE id = :rid"
            ),
            {"rid": request_id, "proof": json.dumps(proof)},
        )

    if recordings_in_floor:
        # A WARNING, not an `alert()`: this is an expected, disclosed state under the
        # position the docs record, not a job that died, and an alarm that fires on
        # normal operation is an alarm nobody reads. It is here so the open decision has
        # a rate in the log stream — "how often does this actually collide?" is the
        # first question whoever resolves it will ask. Ids and counts only.
        log.warning(
            _FLOOR_COLLISION_LOG,
            extra={"request_id": str(request_id), "recordings": recordings_in_floor},
        )
    log.info(
        "deletion_executed",
        extra={"request_id": str(request_id), "calls": len(calls), "leads": len(leads)},
    )
    return (
        f"erased calls={len(calls)} leads={len(leads)} turns={turns_erased} "
        f"bodies={bodies_erased} payloads={payloads_erased} "
        f"recordings={recordings_destroyed} floor_recordings={recordings_in_floor} "
        f"campaign_contacts={contacts_erased} kb_matches={kb_matches}"
    )


# --- TENANT-LEVEL ERASURE (FLOWS §9) -------------------------------------------------
#
# The per-subject erasure above answers one data principal's DPDP §12 request. This one
# answers the END OF AN ENGAGEMENT: the client organisation's instruction, executed by
# us, over every subject in the account at once. `apps/api/compliance/tenant_erasure.py`
# argues why the two are separate requests with separate tables and separate certificates
# — and why the MECHANISM is nevertheless this one module, reusing these statements,
# these object-store helpers and `recording_erasure_holds`.
#
# WHY IT IS ONE TRANSACTION AND HAS NO ROW BUDGET, unlike the nightly sweep.
# `sweep_tenant` may defer: a category it does not finish tonight it finishes tomorrow,
# and nothing downstream reads a "the sweep is complete" flag. A tenant erasure ends by
# writing `organizations.deleted_at` and a certificate that SAYS the data is gone, so a
# partial run that stamped either would be a document asserting something false. It
# therefore runs to completion or rolls back entirely, and it is batched only so the
# statements stay bounded rather than so the job can stop early. The clients this is for
# are Indian SMBs with thousands of calls, not millions; if that stops being true the fix
# is a resumable cursor ON THE REQUEST ROW, not a budget that silently half-erases.

#: Keyset page size for walking a tenant's calls and leads. Same order of magnitude as
#: `SWEEP_BATCH_ROWS` and for the same reason: keep each statement's row count bounded so
#: one enormous UPDATE cannot hold locks for the length of the whole erasure.
TENANT_ERASURE_BATCH = 500

# Keyset rather than OFFSET: the erasure UPDATEs the very rows it is paging over, and an
# OFFSET walk over a table being rewritten skips rows. `(created_at, id)` is unique and
# stable — `id` is uuid_v7 — so the cursor cannot repeat or miss a row.
_TENANT_CALL_PAGE_SQL = """
SELECT id, created_at FROM calls
WHERE (created_at, id) > (:after_at, :after_id)
ORDER BY created_at, id LIMIT :batch
"""

# The leads arm has no cursor because the UPDATE makes its own rows stop matching — the
# anonymized-phone prefix is the guard, exactly as `_LEAD_SQL` uses it, and keying on
# `name IS NOT NULL` would skip every lead whose caller never gave one.
_TENANT_LEAD_PAGE_SQL = """
SELECT id FROM leads
WHERE left(phone_e164, length(:anon)) <> :anon
ORDER BY created_at, id LIMIT :batch
"""

# `AND status = 'churned' AND deleted_at IS NULL` is not defensive decoration. The first
# is the invariant every reader of this column depends on (an erased tenant is always
# churned — `compliance/tenant_erasure.py` argues it, and migration f3a71c9e26b4 enforces
# it with a CHECK); the second makes the write single-shot, so a concurrent second
# erasure cannot restamp the instant on a certificate that has already been issued. A
# zero rowcount here is an invariant violation, not a no-op, and the caller raises.
_MARK_ERASED_SQL = """
UPDATE organizations SET deleted_at = now(), updated_at = now()
WHERE id = :tid AND deleted_at IS NULL AND status = 'churned'
"""

# THE ERASED ACCOUNT MUST STOP COLLECTING (D-189).
#
# Every arm above erases what the tenant HAD. None of them stopped it acquiring more.
# `engine_agent_routes` is the one bridge from the voice platform's id space into ours
# (`workers/pipeline._resolve_agent`), the vendor's agent objects are still configured
# and the client's DID is still pointed at them, so the FIRST inbound call after the
# certificate was issued re-created a `calls` row, its transcript, its extraction, its
# lead and an archived engine payload — full caller records, under a `tenant_id` whose
# certificate says the account is erased and whose own people are locked out of every
# screen that could show them (`core/auth.py` refuses a churned org). Storage with no
# purpose and no reader is DPDP §8(7) on its own; a certificate that is false within
# minutes of being signed is worse. Measured against the live schema before the fix:
# the route resolved and the row inserted.
#
# Withdrawing the routing is the half that is OURS and it is a single statement in the
# erasure's own transaction, so it commits with `deleted_at` and the certificate or not
# at all. What it does NOT do is stop the vendor answering the phone — only removing the
# agent at the voice platform and releasing the number with the telephony provider does
# that, and both are outside this repository. The certificate says so rather than
# implying otherwise, and the operator's signal is automatic: the next call to that
# number arrives with a ref nothing maps, and `_ingest_stages` already raises
# `engine_agent_unmapped` for exactly that.
#
# REJECTED: calling `VoiceEngine.delete_agent` from here. It exists and is idempotent by
# contract, but it is a third-party round trip inside the one transaction that must not
# half-commit, and its failure mode would be an erasure that rolls back because a vendor
# was slow. The vendor-side deletion stays `unconfirmed_pending_vendor_api`, which is
# what the certificate has always claimed and all it has ever been able to.
#
# `active` is filtered in the WHERE so the count reports routes this erasure actually
# withdrew rather than every row the tenant ever had; a variant retired earlier
# (`agents/experiments.py`) is already inactive and was already collecting nothing.
#
# WHAT IT DOES NOT BREAK, checked rather than assumed. The retention sweep and the
# outbox dispatcher enumerate tenants with `SELECT DISTINCT tenant_id FROM
# engine_agent_routes` and are deliberately UNFILTERED on `active` (see `_tenants` above:
# offboarding is where the countdown STARTS), so an erased tenant's remaining rows keep
# ageing out on their own policy exactly as FLOWS §9 promises. What DOES stop is the
# agent and KB drift sweeps, which read `WHERE active` — and that is the right answer,
# not a gap: those sweeps exist to keep an agent we still operate faithful to what we
# published, and this account's agents are being abandoned to the vendor, which is the
# fact the certificate now states in words instead of leaving to a reader.
_WITHDRAW_ROUTES_SQL = """
UPDATE engine_agent_routes SET active = false, updated_at = now()
WHERE tenant_id = :tid AND active
"""


async def _erase_tenant_calls(
    session: AsyncSession, *, tenant_id: UUID, request_id: UUID
) -> tuple[dict[str, int], datetime | None]:
    """Erase the caller data on every call this tenant has. Returns the counts.

    Each page runs the SAME statements `execute_deletion_request` runs for one subject's
    calls — the recording split, the transcript mark, the personal-field clear, the
    derived extraction payload, the archived engine payloads, the delivered webhook
    bodies — so there is one definition
    of "what erasing a call means" and this path cannot drift from the per-subject one.
    """
    counts: dict[str, int] = {
        "calls_erased": 0,
        "transcript_turns_erased": 0,
        "call_extractions_erased": 0,
        "recordings_destroyed": 0,
        "recordings_within_trai_floor": 0,
        "webhook_bodies_erased": 0,
        # Recorded in the proof, reported in `actions`, and deliberately NOT in
        # `tenant_erasure._SCOPE_COUNTS`: that tuple is the API's whitelist, and widening
        # it is a wire-shape change rather than a fact about this erasure. The stored
        # proof is a record of facts; the renderer takes what it understands.
        "engine_payloads_erased": 0,
    }
    held_until: datetime | None = None
    # The cursor's floor. `created_at` is NOT NULL on every row, so an epoch start is
    # strictly below every real value and needs no first-page special case.
    after_at = datetime(1970, 1, 1, tzinfo=UTC)
    after_id = UUID(int=0)

    while True:
        page = (
            await session.execute(
                text(_TENANT_CALL_PAGE_SQL),
                {"after_at": after_at, "after_id": after_id, "batch": TENANT_ERASURE_BATCH},
            )
        ).all()
        if not page:
            break
        call_ids = [UUID(str(row[0])) for row in page]
        after_id, after_at = UUID(str(page[-1][0])), page[-1][1]

        counts["engine_payloads_erased"] += await _erase_engine_payloads(
            session, tenant_id=tenant_id, call_ids=call_ids
        )
        in_floor, destroyed, page_held = await _erase_recordings(
            session,
            tenant_id=tenant_id,
            call_ids=call_ids,
            hold_deletion_request_id=None,
            hold_tenant_erasure_id=request_id,
        )
        counts["recordings_within_trai_floor"] += in_floor
        counts["recordings_destroyed"] += destroyed
        if page_held is not None and (held_until is None or page_held > held_until):
            held_until = page_held

        result = await session.execute(
            text(
                "UPDATE transcript_turns SET text = :mark, text_redacted = :mark, "
                "updated_at = now() WHERE call_id = ANY(:ids) AND text <> :mark"
            ),
            {"mark": REDACTED_MARK, "ids": call_ids},
        )
        counts["transcript_turns_erased"] += int(rowcount_of(result) or 0)

        await session.execute(
            text(
                "UPDATE calls SET from_e164 = NULL, to_e164 = NULL, recording_url = NULL, "
                "summary = NULL, updated_at = now() WHERE id = ANY(:ids)"
            ),
            {"ids": call_ids},
        )
        counts["calls_erased"] += len(call_ids)

        result = await session.execute(
            text(
                "UPDATE call_extractions SET data = '{}'::jsonb, moments = NULL, "
                "errors = NULL, updated_at = now() "
                "WHERE call_id = ANY(:ids) AND data <> '{}'::jsonb"
            ),
            {"ids": call_ids},
        )
        counts["call_extractions_erased"] += int(rowcount_of(result) or 0)

        counts["webhook_bodies_erased"] += await _erase_delivery_bodies(
            session,
            tenant_id=tenant_id,
            subjects=[("call", str(cid)) for cid in call_ids],
        )
    return counts, held_until


async def _erase_tenant_leads(session: AsyncSession, *, tenant_id: UUID) -> tuple[int, int]:
    """Anonymize every lead this tenant holds. Returns (leads, delivery bodies).

    Never a DELETE, for the reason `_LEAD_SQL` gives: leads carry FKs from `lead_events`
    and are referenced by `calls`, and anonymizing keeps the funnel countable while
    removing the person.
    """
    leads_erased = 0
    bodies = 0
    anon = ANONYMIZED_PHONE[:9]
    while True:
        page = (
            (
                await session.execute(
                    text(_TENANT_LEAD_PAGE_SQL),
                    {"anon": anon, "batch": TENANT_ERASURE_BATCH},
                )
            )
            .scalars()
            .all()
        )
        if not page:
            return leads_erased, bodies
        lead_ids = [UUID(str(lid)) for lid in page]
        # BEFORE the UPDATE: the body key is built from the lead id, which survives, but
        # keeping the two adjacent means a crash between them leaves the object findable
        # by the same prefix on the retry rather than only by a re-listing.
        bodies += await _erase_delivery_bodies(
            session, tenant_id=tenant_id, subjects=[("lead", str(lid)) for lid in lead_ids]
        )
        await session.execute(
            text(
                "UPDATE leads SET phone_e164 = :anon || substr(id::text, 1, 8), name = NULL, "
                "data = '{}'::jsonb, deleted_at = COALESCE(deleted_at, now()), "
                "updated_at = now() WHERE id = ANY(:ids)"
            ),
            {"ids": lead_ids, "anon": anon},
        )
        leads_erased += len(lead_ids)


async def execute_tenant_erasure(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Erase every caller record this tenant holds, then mark the organisation deleted.

    THE ORDER IS THE WHOLE DESIGN. `organizations.deleted_at` is written LAST, in the same
    transaction as the proof, so the column can only ever mean "the erasure below
    completed". Written first it would mean "an erasure was started", which is a
    different claim and the one that nine readers — every membership resolution, the dial
    gate, the invitation gate, the directory — would have believed.

    Idempotent on `completed_at`, like `execute_deletion_request`: a re-run must not
    produce a second, weaker proof, and arq WILL re-run this if the object store raises
    (`StorageUnavailableError` is an `arq.Retry`; the transaction rolls back, `deleted_at`
    stays NULL and the retry redoes the whole thing).

    Hard rule 4 is a constraint this had to solve rather than bend. Nothing in
    `db/registry.APPEND_ONLY_TABLES` is touched: `usage_events`, `consent_ledger`,
    `credit_ledger`, `one_time_charges`, `whatsapp_alert_optin_ledger`,
    `preference_scrub_runs` and `audit_log` are all left exactly as they are, and the
    certificate says so in the words a client can read
    (`tenant_erasure.TENANT_ERASURE_LIMITATIONS`). `consent_ledger` and `audit_log` do
    carry caller numbers; the register states that rather than hiding it, because the
    alternative — a compensating "erased" entry that did not actually remove the number —
    would be a ledger entry whose only function is to make a certificate look complete.

    Hard rule 6: ids and counts in every log line. No number, no transcript text, no
    extraction payload, and no object key (a delivery-body key contains the subject's
    row id).
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    request_id = UUID(str(payload["request_id"]))

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT completed_at FROM tenant_erasure_requests WHERE id = :rid"),
                {"rid": request_id},
            )
        ).first()
        if row is None:
            return "not_found"
        if row[0] is not None:
            return "already_completed"

        counts, held_until = await _erase_tenant_calls(
            session, tenant_id=tenant_id, request_id=request_id
        )
        leads_erased, lead_bodies = await _erase_tenant_leads(session, tenant_id=tenant_id)
        counts["leads_erased"] = leads_erased
        counts["webhook_bodies_erased"] += lead_bodies
        # UNPAGED, unlike the two above, and deliberately: this is ONE statement over one
        # tenant's contact rows with no object-store round trip in it, so the row budget
        # the paging exists to bound does not apply. `_erase_tenant_calls` pages because
        # each page issues object deletions; `_erase_tenant_leads` pages because each page
        # lists a prefix per lead. This touches neither.
        counts["campaign_contacts_erased"] = await _erase_campaign_contacts(session)
        # BEFORE the mark, in the same transaction: see `_WITHDRAW_ROUTES_SQL`. An
        # erased account must stop acquiring caller records, and this is the half of
        # that which is ours to perform.
        withdrawn = await session.execute(text(_WITHDRAW_ROUTES_SQL), {"tid": tenant_id})
        counts["engine_routes_withdrawn"] = int(rowcount_of(withdrawn) or 0)

        marked = await session.execute(text(_MARK_ERASED_SQL), {"tid": tenant_id})
        if int(rowcount_of(marked) or 0) != 1:
            # The precondition the API checked has changed underneath us, or the
            # invariant is broken. Either way the certificate must not be written: a
            # proof that says "this organisation is erased" over a row that is not is
            # the one lie a compliance document cannot contain. Raising rolls the whole
            # transaction back, so nothing was erased either.
            alert(
                "WORKER_TERMINAL",
                "tenant_erasure_mark_failed",
                detail="organizations.deleted_at was not set; nothing was erased",
                tenant_id=str(tenant_id),
                request_id=str(request_id),
            )
            raise RuntimeError(
                f"tenant erasure could not set organizations.deleted_at (request_id={request_id})"
            )

        proof: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "executed_at": datetime.now(UTC).isoformat(),
            "scope": {
                **counts,
                HOLD_UNTIL_KEY: held_until.isoformat() if held_until is not None else None,
            },
            "actions": {
                "organizations": "marked deleted; no membership resolves and no dial is permitted",
                "engine_agent_routes": (
                    f"{counts['engine_routes_withdrawn']} voice-platform routing entr(ies) "
                    "withdrawn, so no further call reaching this account's agents is "
                    "recorded here; removing the agents at the voice platform and "
                    "releasing the telephone numbers are manual steps with those vendors"
                ),
                "calls": "phone numbers, recording pointer and summary cleared",
                "recordings": (
                    f"{counts['recordings_destroyed']} audio file(s) destroyed in object "
                    f"storage; {counts['recordings_within_trai_floor']} scheduled for "
                    f"destruction on expiry of the {RECORDING_FLOOR_DAYS}-day retention floor"
                ),
                "transcript_turns": "text and text_redacted replaced",
                "call_extractions": "extracted field payload cleared",
                "leads": "phone anonymized, name and extracted fields cleared",
                "campaign_contacts": (
                    f"{counts['campaign_contacts_erased']} uploaded campaign contact "
                    "row(s): phone anonymized, name, pasted columns and dedupe hash "
                    "cleared, and the row set to dnc_blocked so no campaign can dial it"
                ),
                "webhook_deliveries": (
                    f"{counts['webhook_bodies_erased']} delivered CRM payload(s) deleted "
                    "from object storage and their references cleared"
                ),
                "engine_payloads": (
                    f"{counts['engine_payloads_erased']} archived raw engine payload(s) "
                    "deleted from object storage and their references cleared"
                ),
                "usage_events": "retained — append-only ledger, carries no personal data",
                "consent_ledger": "retained — append-only proof that consent existed",
                "audit_log": "retained — append-only, and the record of this erasure",
                "dnc_list": "retained — removing a suppression would make people callable again",
                # NOT searched, unlike the per-subject path, and the difference is the
                # subject rather than an inconsistency: a §12 erasure has a phone number
                # to look for, and a tenant erasure has no subject to search this content
                # FOR. What reaches it here is the tenant's own `kb` retention policy,
                # which expires superseded versions on its own clock (D-179).
                "kb_sources": (
                    "not searched and not changed; superseded versions expire under this "
                    "account's kb retention policy"
                ),
                "memberships": "retained — client account data, and access ends with this erasure",
            },
            "engine_deletion": "unconfirmed_pending_vendor_api",
        }
        await session.execute(
            text(
                "UPDATE tenant_erasure_requests SET completed_at = now(), "
                "proof = CAST(:proof AS jsonb) WHERE id = :rid"
            ),
            {"rid": request_id, "proof": json.dumps(proof)},
        )

    log.info(
        "tenant_erased",
        extra={
            "tenant_id": str(tenant_id),
            "request_id": str(request_id),
            "calls": counts["calls_erased"],
            "leads": counts["leads_erased"],
        },
    )
    return (
        f"tenant erased calls={counts['calls_erased']} leads={counts['leads_erased']} "
        f"turns={counts['transcript_turns_erased']} "
        f"bodies={counts['webhook_bodies_erased']} "
        f"payloads={counts['engine_payloads_erased']} "
        f"recordings={counts['recordings_destroyed']} "
        f"floor_recordings={counts['recordings_within_trai_floor']} "
        f"campaign_contacts={counts['campaign_contacts_erased']}"
    )


# --- the two infra tables the tenant sweep structurally cannot reach ----------
#
# `outbox_messages` and `webhook_inbox_events` have no `tenant_id` — deliberately, they
# are infra tables (`ops/routes.py` states that contract) — so every arm above is blind
# to them, and until this job nothing anywhere deleted a row from either (P6.7).
#
# THAT IS TWO PROBLEMS, AND THE QUIETER ONE IS THE COMPLIANCE ONE. The performance half
# is what the finding named: four "have we already promised this?" probes scanning a
# permanently-growing table. Those probes are gone (`enqueue_outbox_once`,
# `calls.crm_notified_at`), which fixes the scan and not the growth. The half nothing
# else addresses is that `outbox_messages.payload` carries a lead's name, phone number
# and call summary — `reliability/service.py` says so where it explains why the DLQ
# endpoint publishes counts only — so an unbounded outbox is an unbounded copy of tenant
# personal data sitting OUTSIDE every retention policy a tenant can set, and outside the
# DPDP erasure path, which walks tenant-scoped tables.
#
# WHAT IS NEVER PRUNED, and both exclusions matter more than the floor:
#
#   * `status <> 'published'` outbox rows. A `failed` row IS the DLQ an operator replays
#     from (`ops/routes.py`'s replay endpoint), and a `pending` one is work not yet done.
#     Deleting either would be losing the side effect rather than forgetting a completed
#     one.
#   * `status <> 'processed'` inbox rows. A `failed` row is what the client's own ingest
#     activity screen offers a re-drive from, and a `processing` one may still be in
#     flight. Only a processed event — whose whole remaining value is deduping a
#     re-delivery — is prunable.
#
# THE FLOOR IS 90 DAYS, and the number is chosen against the longest thing that still
# reads these rows, not picked for roundness:
#
#   * the poller's re-drive window is 30 MINUTES (`reconcile_executions`), four orders of
#     magnitude below it — and after this release the poller no longer reads the outbox
#     at all, because `calls.crm_notified_at` replaced its containment probe;
#   * the inbox row's job is to answer "have I seen this event id before"; no engine
#     re-delivers on a 90-day horizon;
#   * an invoice is issued monthly and disputed within the month, so 90 days spans the
#     longest window in which someone asks "was this delivery actually made";
#   * and it matches `RECORDING_FLOOR_DAYS`, so the two never-tenant-scoped floors in
#     this file are one number rather than two somebody has to reconcile.
RELIABILITY_PRUNE_AFTER = timedelta(days=RECORDING_FLOOR_DAYS)

_PRUNE_OUTBOX_SQL = """
DELETE FROM outbox_messages WHERE id IN (
    SELECT id FROM outbox_messages
    WHERE status = 'published' AND created_at < :cutoff
    ORDER BY created_at LIMIT :batch
)
"""

_PRUNE_INBOX_SQL = """
DELETE FROM webhook_inbox_events WHERE id IN (
    SELECT id FROM webhook_inbox_events
    WHERE status = 'processed' AND created_at < :cutoff
    ORDER BY created_at LIMIT :batch
)
"""


async def prune_reliability_tables(ctx: dict[str, Any]) -> str:
    """Nightly. Forget the completed infra rows nobody can reach any more (P6.7).

    Runs in an `untenanted_session` and not a tenant one: neither table has a
    `tenant_id`, so there is no tenant to be inside, and the RLS-exempt read this needs
    is a whole-table one by construction. It writes no tenant-scoped table.

    Batched through `_sweep_in_batches` — the same loop, the same budget and the same
    "deferred" answer as every arm above, so a night that hits the ceiling says so and
    the next night continues rather than one statement locking a large table for minutes.

    Counts only in the log line (hard rule 6): these rows quote leads.
    """
    cutoff = datetime.now(UTC) - RELIABILITY_PRUNE_AFTER
    async with untenanted_session() as session:
        outbox, outbox_deferred = await _sweep_in_batches(
            session, _PRUNE_OUTBOX_SQL, {"cutoff": cutoff}
        )
        inbox, inbox_deferred = await _sweep_in_batches(
            session, _PRUNE_INBOX_SQL, {"cutoff": cutoff}
        )
    totals = {
        "outbox_pruned": outbox,
        "inbox_pruned": inbox,
        "deferred": int(outbox_deferred or inbox_deferred),
    }
    log.info("reliability_prune", extra=totals)
    return json.dumps(totals)


__all__ = [
    "ANONYMIZED_PHONE",
    "DERIVED_COPIES",
    "DESTROYED_COUNT_KEY",
    "FLOOR_COUNT_KEY",
    "HOLD_UNTIL_KEY",
    "KB_MATCH_KEY",
    "RECORDING_FLOOR_DAYS",
    "REDACTED_MARK",
    "RELIABILITY_PRUNE_AFTER",
    "SWEEP_BATCH_ROWS",
    "TENANT_ERASURE_BATCH",
    "TENANT_ROW_BUDGET",
    "apply_retention",
    "execute_deletion_request",
    "execute_tenant_erasure",
    "prune_reliability_tables",
    "sweep_tenant",
    "sweep_tenants",
]
