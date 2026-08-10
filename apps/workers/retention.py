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
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.session import admin_session, tenant_session

log = get_logger(__name__)

# TRAI floor (SEC-COMP §1). Duplicated from the DB CHECK on purpose: a policy row that
# somehow claims less must not cause this job to delete a recording early.
RECORDING_FLOOR_DAYS = 90
ANONYMIZED_PHONE = "+910000000000"
REDACTED_MARK = "[erased]"


def _hash(value: str) -> str:
    """Hashes go in the proof so a later audit can verify WHICH rows were erased
    without the proof itself carrying the personal data (that would defeat the point)."""
    return hashlib.sha256(value.encode()).hexdigest()[:32]


async def _tenant_ids() -> list[UUID]:
    async with admin_session() as session:
        rows = (
            (await session.execute(text("SELECT id FROM organizations WHERE deleted_at IS NULL")))
            .scalars()
            .all()
        )
    return [UUID(str(r)) for r in rows]


async def apply_retention(ctx: dict[str, Any]) -> str:
    """Nightly. Walks each tenant's policies and applies the expired ones."""
    total = {"recordings": 0, "transcripts": 0, "leads": 0}
    for tenant_id in await _tenant_ids():
        async with tenant_session(tenant_id) as session:
            policies = (
                await session.execute(
                    text("SELECT data_category, ttl_days, action FROM retention_policies")
                )
            ).all()
            for category, ttl_days, action in policies:
                applied = await _apply_one(
                    session, category=str(category), ttl_days=int(ttl_days), action=str(action)
                )
                key = {"recording": "recordings", "transcript": "transcripts", "lead": "leads"}
                if category in key:
                    total[key[str(category)]] += applied
    log.info("retention_sweep", extra=total)
    return json.dumps(total)


async def _apply_one(session: AsyncSession, *, category: str, ttl_days: int, action: str) -> int:
    if category == "consent_log":
        # Append-only ledger (hard rule 4). The category exists in the table so the
        # policy is explicit rather than forgotten, but nothing expires it on a timer.
        return 0

    if category == "recording":
        effective = max(ttl_days, RECORDING_FLOOR_DAYS)
        if effective != ttl_days:
            alert("WORKER_TERMINAL", "retention_below_trai_floor", detail=f"{ttl_days}d")
        cutoff = datetime.now(UTC) - timedelta(days=effective)
        # Clearing the pointer is the local half; the object-store lifecycle rule
        # removes the bytes. Keeping the call row keeps its metering intact.
        result = await session.execute(
            text(
                "UPDATE calls SET recording_url = NULL, updated_at = now() "
                "WHERE recording_url IS NOT NULL AND ended_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        return int(result.rowcount or 0)

    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)

    if category == "transcript":
        if action == "delete":
            result = await session.execute(
                text(
                    "DELETE FROM transcript_turns WHERE call_id IN "
                    "(SELECT id FROM calls WHERE ended_at < :cutoff)"
                ),
                {"cutoff": cutoff},
            )
        else:
            # Anonymize keeps the SHAPE of the conversation (turn count, speakers,
            # timings) for analytics while removing every word that was said.
            result = await session.execute(
                text(
                    "UPDATE transcript_turns SET text = :mark, text_redacted = :mark, "
                    "updated_at = now() WHERE text <> :mark AND call_id IN "
                    "(SELECT id FROM calls WHERE ended_at < :cutoff)"
                ),
                {"cutoff": cutoff, "mark": REDACTED_MARK},
            )
        return int(result.rowcount or 0)

    if category == "lead":
        # Never a DELETE: leads carry FKs from lead_events and are referenced by calls.
        # Anonymizing keeps the funnel countable and removes the person.
        result = await session.execute(
            text(
                "UPDATE leads SET phone_e164 = :anon || substr(id::text, 1, 8), name = NULL, "
                "data = '{}'::jsonb, deleted_at = COALESCE(deleted_at, now()), updated_at = now() "
                "WHERE updated_at < :cutoff AND name IS NOT NULL"
            ),
            {"cutoff": cutoff, "anon": ANONYMIZED_PHONE[:9]},
        )
        return int(result.rowcount or 0)

    return 0


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
        if calls:
            result = await session.execute(
                text(
                    "UPDATE transcript_turns SET text = :mark, text_redacted = :mark, "
                    "updated_at = now() WHERE call_id = ANY(:ids)"
                ),
                {"mark": REDACTED_MARK, "ids": list(calls)},
            )
            turns_erased = int(result.rowcount or 0)
            await session.execute(
                text(
                    "UPDATE calls SET from_e164 = NULL, to_e164 = NULL, recording_url = NULL, "
                    "summary = NULL, updated_at = now() WHERE id = ANY(:ids)"
                ),
                {"ids": list(calls)},
            )
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
            },
            "actions": {
                "calls": "phone numbers, recording pointer and summary cleared",
                "transcript_turns": "text and text_redacted replaced",
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
    "RECORDING_FLOOR_DAYS",
    "REDACTED_MARK",
    "apply_retention",
    "execute_deletion_request",
]
