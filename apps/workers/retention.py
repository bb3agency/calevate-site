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

DELIVERED WEBHOOK BODIES (D-23) are the first personal data this module expires OUTSIDE
Postgres. `webhook_deliveries.payload_ref` names an object holding the CRM payload we
POSTed to a client's endpoint, so both jobs gained an arm: the sweep expires them on the
tenant's own `lead` policy (see `DERIVED_COPIES`), and the erasure deletes them by
SUBJECT, enumerating the object store rather than trusting the reference column
(`_erase_delivery_bodies` says why). Unlike recordings, these do not wait on a bucket
lifecycle rule — nothing about them is under a statutory retention floor, so the tenant's
own policy is the whole answer and this module executes it.

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

THE ONE THING THIS MODULE REFUSES TO DECIDE: an erasure request for a recording younger
than the TRAI 90-day floor. SEC-COMP §4 says erasure covers recordings, SEC-COMP §1 says
90 days is a minimum, and the doc reserves the choice for the founder. The behaviour is
therefore unchanged — the pointer is cleared at any age — but the collision is COUNTED
and reported (`_FLOOR_COLLISION_LOG`, `floor_recordings=` on the job result, and
`scope.recordings_within_trai_floor` in the proof) instead of passing unremarked.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
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

    Said the way a compliance reviewer would: NO PERSONAL DATA ENTERS THE PLATFORM THAT
    THE RETENTION SWEEP CANNOT LATER EXPIRE. `tests/schema_hardening_3_test.py` is that
    sentence as executable tests.

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
            (await session.execute(text("SELECT DISTINCT tenant_id FROM engine_agent_routes")))
            .scalars()
            .all()
        )
    return [UUID(str(row)) for row in rows]


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
    ELSE false
  END AS has_work
FROM retention_policies r
"""


async def apply_retention(ctx: dict[str, Any]) -> str:
    """Nightly. Sweeps the tenants that can hold data, under each one's own policies."""
    tenants = await _due_tenants()
    totals = await sweep_tenants(tenants)
    log.info("retention_sweep", extra={**totals, "tenants_scanned": len(tenants)})
    return json.dumps(totals)


async def sweep_tenants(tenant_ids: Iterable[UUID]) -> dict[str, int]:
    """One tick over an explicit tenant list. Split out from `apply_retention` so the
    resolution step and the sweeping step can be exercised — and costed — separately."""
    totals = dict(_EMPTY_TOTALS)
    swept = 0
    for tenant_id in tenant_ids:
        counts = await sweep_tenant(tenant_id)
        if any(counts.values()):
            swept += 1
        for key, value in counts.items():
            totals[key] += value
    totals["tenants_swept"] = swept
    return totals


async def sweep_tenant(tenant_id: UUID) -> dict[str, int]:
    """Apply every expired policy for ONE tenant, inside that tenant's RLS context.

    One session, one probe, and a statement only where the probe found work. Counts
    only — no phone number, transcript text or extraction payload is read here or
    logged anywhere (hard rule 6).
    """
    totals = dict(_EMPTY_TOTALS)
    async with tenant_session(tenant_id) as session:
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
                session, category=str(category), ttl_days=int(ttl_days), action=str(action)
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


_RECORDING_SQL = f"""
UPDATE calls SET recording_url = NULL, updated_at = now() WHERE id IN (
  SELECT c.id FROM calls c WHERE c.recording_url IS NOT NULL AND {_CLOCK} < :cutoff
  ORDER BY {_CLOCK} LIMIT :batch)
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
_EXTRACTION_SQL = """
UPDATE call_extractions SET data = '{}'::jsonb, errors = NULL, updated_at = now()
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


async def _sweep_delivery_bodies(session: AsyncSession, *, cutoff: datetime) -> tuple[int, bool]:
    """Expire the retained delivery bodies past `cutoff`. Returns (rows, deferred).

    A store that will not answer STOPS this arm rather than failing the tick: every other
    category still expires, the references stay pointing at objects that still exist, and
    the next tick starts from the same oldest rows. Reported as a warning with counts —
    an alert per tick during an object-store outage would be an alarm nobody reads, and
    the objects are not yet overdue by any amount that matters within one night.
    """
    done = 0
    while done < TENANT_ROW_BUDGET:
        batch = min(SWEEP_BATCH_ROWS, TENANT_ROW_BUDGET - done)
        rows = (
            await session.execute(
                text(_DELIVERY_BODY_SELECT_SQL), {"cutoff": cutoff, "batch": batch}
            )
        ).all()
        if not rows:
            return done, False
        try:
            storage.delete_objects([str(row[1]) for row in rows])
        except storage.StorageUnavailableError as exc:
            log.warning("delivery_body_expiry_deferred", extra={"reason": str(exc)})
            return done, True
        await session.execute(text(_DELIVERY_BODY_CLEAR_SQL), {"ids": [row[0] for row in rows]})
        done += len(rows)
        if len(rows) < batch:
            return done, False
    return done, True


async def _apply_one(
    session: AsyncSession, *, category: str, ttl_days: int, action: str
) -> dict[str, int]:
    counts = dict(_EMPTY_TOTALS)
    if category == "consent_log":
        # Append-only ledger (hard rule 4). The category exists in the table so the
        # policy is explicit rather than forgotten, but nothing expires it on a timer.
        return counts

    if category == "recording":
        effective = max(ttl_days, RECORDING_FLOOR_DAYS)
        cutoff = datetime.now(UTC) - timedelta(days=effective)
        # Clearing the pointer is the local half; the object-store lifecycle rule
        # removes the bytes. Keeping the call row keeps its metering intact.
        counts["recordings"], deferred = await _sweep_in_batches(
            session, _RECORDING_SQL, {"cutoff": cutoff}
        )
        counts["deferred"] += int(deferred)
        return counts

    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)

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
        counts["delivery_bodies"], deferred = await _sweep_delivery_bodies(session, cutoff=cutoff)
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
        keys += storage.delivery_body_keys_for(
            storage.delivery_body_subject_prefix(
                tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id
            )
        )
    if not keys:
        return 0
    storage.delete_objects(keys)
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

        calls = (
            (
                await session.execute(
                    text("SELECT id FROM calls WHERE from_e164 = :phone OR to_e164 = :phone"),
                    {"phone": phone},
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
        if calls:
            # Counted BEFORE the pointer is cleared — afterwards the question is
            # unanswerable, which is how this collision stayed invisible.
            recordings_in_floor = int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM calls c WHERE c.id = ANY(:ids) "
                            "AND c.recording_url IS NOT NULL AND "
                            f"{_CLOCK} > now() - make_interval(days => :floor)"
                        ),
                        {"ids": list(calls), "floor": RECORDING_FLOOR_DAYS},
                    )
                ).scalar()
                or 0
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
                    "summary = NULL, updated_at = now() WHERE id = ANY(:ids)"
                ),
                {"ids": list(calls)},
            )
            # The DERIVED copy. `call_extractions.data` is the caller's name, their
            # callback number and every schema field the model captured — erasing the
            # transcript and leaving this behind means the person is still on file, and
            # the proof certificate would have said otherwise.
            result = await session.execute(
                text(
                    "UPDATE call_extractions SET data = '{}'::jsonb, errors = NULL, "
                    "updated_at = now() WHERE call_id = ANY(:ids) AND data <> '{}'::jsonb"
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
            },
            "actions": {
                "calls": "phone numbers, recording pointer and summary cleared",
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
        f"bodies={bodies_erased} floor_recordings={recordings_in_floor}"
    )


__all__ = [
    "ANONYMIZED_PHONE",
    "DERIVED_COPIES",
    "FLOOR_COUNT_KEY",
    "RECORDING_FLOOR_DAYS",
    "REDACTED_MARK",
    "SWEEP_BATCH_ROWS",
    "TENANT_ROW_BUDGET",
    "apply_retention",
    "execute_deletion_request",
    "sweep_tenant",
    "sweep_tenants",
]
