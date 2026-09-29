"""The handover to a person: the ending of the handover (D-533).

`settle_handoff` is NOT an arq job. It is called by `pipeline._post_call_stages` with the
execution snapshot that stage already holds, because the ending of the handover is a
property of that snapshot and a second fetch would be a second vendor round trip for data
already in hand.

**WHAT THIS DOES INSTEAD OF A WHISPER, SAID PLAINLY.** The founder asked for the agent to
brief the human before bridging. That is a telephony feature (Plivo's `<Dial
confirmSound=…>`) and it needs control of the caller's leg, which this deployment does not
have. `docs/evidence/handoff-warm-transfer.md` records what would have to change. On the
owned runtime the voice worker's handoff tool reaches `apps/api/worker/tools.request_handoff`,
which answers truthfully that this engine cannot transfer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from calevate_shared.calling_window import IST, ist_wall_clock, next_window_opening
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.callbacks import service as callbacks
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)


async def settle_handoff(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, snapshot: ExecutionSnapshot
) -> str:
    """Close out the handover this call had, from the execution's own account of it.

    **CALLED FOR EVERY COMPLETED CALL, INCLUDING THE ONES THAT NEVER HANDED OVER**, and the
    two `no_row` / `abandoned` outcomes are why. A call with no handover has no row and
    this is a single indexed lookup that finds nothing. A call that HAS a row and whose
    execution carries no transfer leg is the interesting case: the agent told the caller it
    was putting them through and the engine never reported placing a leg, which must not sit
    at `started` for ever pretending to be in progress.

    IT IS IDEMPOTENT BY PREDICATE, not by flag: only a row still at `started` is settled,
    so a re-run of the pipeline (which is ordinary — the poller and the webhook both drive
    it) cannot re-open an ending or book a second callback.
    """
    row = (
        await session.execute(
            text(
                "SELECT id, destination_e164 FROM handoff_attempts "
                "WHERE source_execution_id = :ex AND outcome = 'started'"
            ),
            {"ex": snapshot.engine_call_id},
        )
    ).first()
    if row is None:
        return "no_row"
    attempt_id = UUID(str(row[0]))
    leg = snapshot.handoff
    if leg is None:
        await session.execute(
            text(
                "UPDATE handoff_attempts SET outcome = 'abandoned', settled_at = now(), "
                "source_call_id = COALESCE(source_call_id, :cid), updated_at = now() "
                "WHERE id = :id"
            ),
            {"id": attempt_id, "cid": call_id},
        )
        return "abandoned"
    await session.execute(
        text(
            "UPDATE handoff_attempts SET outcome = :outcome, raw_status = :raw, "
            "leg_duration_s = :dur, leg_recording_present = :rec, "
            "leg_cost_reported = :cost, settled_at = now(), "
            "source_call_id = COALESCE(source_call_id, :cid), updated_at = now() "
            "WHERE id = :id"
        ),
        {
            "id": attempt_id,
            # `in_progress` cannot be an ENDING: the execution is over, so a leg the vendor
            # still calls in-progress is a leg we have no final word on. `unknown` is the
            # honest spelling and it keeps the CHECK's meaning intact.
            "outcome": "unknown" if leg.outcome == "in_progress" else leg.outcome,
            "raw": leg.raw_status or None,
            "dur": leg.duration_s,
            "rec": leg.recording_present,
            "cost": leg.cost_reported,
            "cid": call_id,
        },
    )
    if leg.outcome == "unreached":
        booked = await _book_callback_for(
            session,
            tenant_id=tenant_id,
            call_id=call_id,
            attempt_id=attempt_id,
            snapshot=snapshot,
        )
        log.info(
            "handoff_unreached_callback",
            extra={"tenant_id": str(tenant_id), "booked": booked},
        )
    # **THE `handoff_leg_recording_unretained` ALARM USED TO BE RAISED HERE AND IS GONE**
    # (the founder's decision, 5 Sep 2026). It said that a second recording of this caller
    # existed on the vendor's side which we did not copy, retain or erase — a standing
    # obligation an operator had to be told about. It is no longer true: the transferred
    # leg is fetched by `pipeline._copy_recordings` into `calls.transfer_recording_url`,
    # expires on the same retention clock and is destroyed or scheduled by the same
    # erasure. An alarm whose condition has been fixed is worse than no alarm — it teaches
    # an operator to ignore the family. What can still go wrong is the FETCH, and that has
    # its own alarm (`recording_copy_failed`, which now names the leg) and its own retry.
    #
    # `leg.recording_present` stays on the row, because "was there a second recording" is a
    # question an erasure certificate and a retention answer still have to answer on a call
    # whose bytes we could not get.
    return leg.outcome


#: What the client reads on a call-back this system booked for them rather than one the
#: caller asked for. In their words, and it says what actually happened rather than naming
#: a state: "unreached" is our vocabulary.
HANDOFF_CALLBACK_NOTE = (
    "This caller asked to speak to someone and nobody was able to take the call, so we "
    "will ring them back."
)


async def _book_callback_for(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    attempt_id: UUID,
    snapshot: ExecutionSnapshot,
) -> bool:
    """Nobody picked up, so the caller gets a call-back. Decision 3's second half.

    **THIS IS THE ONLY FAILOVER THIS ENGINE LEAVES AVAILABLE, and it is worth being exact
    about why it is not the one that was asked for.** The brief asked to try the next
    number and then fall back to a call-back. Trying the next number would have to happen
    while the caller is still on the line, and the engine latches after one handover and
    answers every later attempt with "Call transfer already in progress" (VERIFIED-OSS:
    `bolna-ai/bolna@cd2e192`, `bolna/agent_manager/task_manager.py:3116-3126`). So the
    hunt list is honoured by CHOOSING before the call (`agents/handoff.on_duty`) and the
    miss is caught after it, here.

    **IT DEFERS TO A CALL-BACK THE CALLER ACTUALLY ASKED FOR.** `callbacks.book` upserts on
    the execution and takes the LATER `booked_at`, so booking here unconditionally would
    silently move a time a caller was told out loud ("Tuesday at four") to twenty minutes
    from now. A promise a person heard beats one this system inferred, every time, so an
    existing row for this conversation is left exactly as it is.

    THE TIME IS THE SOONEST ONE THAT IS LAWFUL, never simply "now": `next_window_opening`
    is the same walk the in-call booking tool refuses outside, so a handover that fails at
    21:30 books for 09:00 rather than ringing somebody at half past nine at night. The
    number is the OTHER party, chosen by direction exactly as the callback job chooses it —
    getting that backwards would ring our own header.
    """
    phone = snapshot.from_e164 if snapshot.direction == "inbound" else snapshot.to_e164
    if not phone:
        return False
    existing = (
        await session.execute(
            text("SELECT 1 FROM scheduled_callbacks WHERE source_execution_id = :ex"),
            {"ex": snapshot.engine_call_id},
        )
    ).first()
    if existing is not None:
        return False
    now = datetime.now(UTC)
    # `next_window_opening` works in IST wall clock carrying UTC's tzinfo (the repo
    # convention `ist_wall_clock` documents), so the result is shifted back to a real
    # instant before it is stored — the DB holds UTC (hard rule: timestamptz, UTC in DB).
    when = next_window_opening(ist_wall_clock(now)) - IST
    agent_row = (
        await session.execute(
            text("SELECT agent_id FROM handoff_attempts WHERE id = :id"), {"id": attempt_id}
        )
    ).first()
    if agent_row is None:
        return False
    booked = await callbacks.book(
        session,
        callback_id=uuid7(),
        tenant_id=tenant_id,
        agent_id=UUID(str(agent_row[0])),
        source_call_id=call_id,
        source_execution_id=snapshot.engine_call_id,
        lead_id=None,
        phone_e164=str(phone),
        requested_at=when,
        booked_at=now,
        note=HANDOFF_CALLBACK_NOTE,
        language=None,
    )
    if booked is None:
        return False
    await session.execute(
        text("UPDATE handoff_attempts SET callback_id = :cb, updated_at = now() WHERE id = :id"),
        {"cb": booked[0], "id": attempt_id},
    )
    return True


__all__ = [
    "HANDOFF_CALLBACK_NOTE",
    "settle_handoff",
]
