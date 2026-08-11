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

Engine-side copies are the open edge, honestly marked: Bolna's deletion API is
undocumented (pilot gate), so `engine_deletion` is recorded as `unconfirmed` in the
proof rather than asserted. A proof that overclaims is worse than one that says what it
does not know.

THE SWEEP'S COST SHAPE (see `_due_tenants` and `sweep_tenant`): the tick costs one
probe per tenant that CAN hold call data, not one session per organization on the
platform, and each tenant may consume at most `TENANT_ROW_BUDGET` rows per category
before the rest is deferred to the next tick.
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

log = get_logger(__name__)

# TRAI floor (SEC-COMP §1). Duplicated from the DB CHECK on purpose: a policy row that
# somehow claims less must not cause this job to delete a recording early.
RECORDING_FLOOR_DAYS = 90
ANONYMIZED_PHONE = "+910000000000"
REDACTED_MARK = "[erased]"

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
DERIVED_COPIES: Mapping[str, tuple[str, ...]] = {
    "transcript": ("calls.summary",),
    "lead": ("call_extractions.data",),
}

# Counter keys, so a caller (and the log line) always sees the same shape.
_EMPTY_TOTALS: Mapping[str, int] = {
    "recordings": 0,
    "transcripts": 0,
    "summaries": 0,
    "leads": 0,
    "extractions": 0,
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

    KNOWN EDGE, reported rather than papered over: a lead ingested from a website/Meta
    webhook lands even if its agent was never published (`ingest/service.py` writes the
    lead before the dial), so a tenant that has *only* such leads is not in this set and
    its `lead` TTL never runs. Closing it needs a global presence row written by the
    ingest path — a migration, and a change to a module this job does not own.
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
_PROBE_SQL = """
SELECT r.data_category, r.ttl_days, r.action,
  CASE r.data_category
    WHEN 'recording' THEN EXISTS (
      SELECT 1 FROM calls c
      WHERE c.recording_url IS NOT NULL
        AND c.ended_at < now() - make_interval(days => GREATEST(r.ttl_days, :floor)))
    WHEN 'transcript' THEN EXISTS (
      SELECT 1 FROM transcript_turns t JOIN calls c ON c.id = t.call_id
      WHERE c.ended_at < now() - make_interval(days => r.ttl_days)
        AND (r.action = 'delete' OR t.text <> :mark))
      OR EXISTS (
      SELECT 1 FROM calls c
      WHERE c.summary IS NOT NULL
        AND c.ended_at < now() - make_interval(days => r.ttl_days))
    WHEN 'lead' THEN EXISTS (
      SELECT 1 FROM leads l
      WHERE l.updated_at < now() - make_interval(days => r.ttl_days)
        AND left(l.phone_e164, length(:anon)) <> :anon)
      OR EXISTS (
      SELECT 1 FROM call_extractions e
      WHERE e.updated_at < now() - make_interval(days => r.ttl_days)
        AND e.data <> '{}'::jsonb)
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


_RECORDING_SQL = """
UPDATE calls SET recording_url = NULL, updated_at = now() WHERE id IN (
  SELECT id FROM calls WHERE recording_url IS NOT NULL AND ended_at < :cutoff
  ORDER BY ended_at LIMIT :batch)
"""

_TRANSCRIPT_DELETE_SQL = """
DELETE FROM transcript_turns WHERE id IN (
  SELECT t.id FROM transcript_turns t JOIN calls c ON c.id = t.call_id
  WHERE c.ended_at < :cutoff ORDER BY c.ended_at LIMIT :batch)
"""

# Anonymize keeps the SHAPE of the conversation (turn count, speakers, timings) for
# analytics while removing every word that was said.
_TRANSCRIPT_ANONYMIZE_SQL = """
UPDATE transcript_turns SET text = :mark, text_redacted = :mark, updated_at = now()
WHERE id IN (
  SELECT t.id FROM transcript_turns t JOIN calls c ON c.id = t.call_id
  WHERE c.ended_at < :cutoff AND t.text <> :mark ORDER BY c.ended_at LIMIT :batch)
"""

# DERIVED COPY of the transcript, on the transcript's clock. Cleared, never marked:
# `summary` is free prose with no shape worth keeping, and the DPDP erasure path
# already treats it as personal data.
_SUMMARY_SQL = """
UPDATE calls SET summary = NULL, updated_at = now() WHERE id IN (
  SELECT id FROM calls WHERE summary IS NOT NULL AND ended_at < :cutoff
  ORDER BY ended_at LIMIT :batch)
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
        return counts

    return counts


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
        phone, completed_at = str(row[0]), row[1]
        if completed_at is not None:
            # Idempotent: an erasure re-run must not produce a second, weaker proof.
            return "already_completed"

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

        turns_erased = 0
        extractions_erased = 0
        if calls:
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
            },
            "actions": {
                "calls": "phone numbers, recording pointer and summary cleared",
                "transcript_turns": "text and text_redacted replaced",
                "call_extractions": "extracted field payload cleared",
                "leads": "phone anonymized, name and extracted fields cleared",
                "usage_events": "retained — append-only ledger, carries no personal data",
                "consent_ledger": "retained — append-only proof that consent existed",
            },
            # Stated, not asserted: Bolna's deletion API is undocumented (pilot gate),
            # so the certificate must not claim an engine-side deletion we cannot show.
            "engine_deletion": "unconfirmed_pending_vendor_api",
        }
        await session.execute(
            text(
                "UPDATE deletion_requests SET completed_at = now(), proof = CAST(:proof AS jsonb) "
                "WHERE id = :rid"
            ),
            {"rid": request_id, "proof": json.dumps(proof)},
        )

    log.info(
        "deletion_executed",
        extra={"request_id": str(request_id), "calls": len(calls), "leads": len(leads)},
    )
    return f"erased calls={len(calls)} leads={len(leads)} turns={turns_erased}"


__all__ = [
    "ANONYMIZED_PHONE",
    "DERIVED_COPIES",
    "RECORDING_FLOOR_DAYS",
    "REDACTED_MARK",
    "SWEEP_BATCH_ROWS",
    "TENANT_ROW_BUDGET",
    "apply_retention",
    "execute_deletion_request",
    "sweep_tenant",
    "sweep_tenants",
]
