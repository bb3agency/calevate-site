"""The handover to a person: the mid-call notice, the brief, and the ending (D-533).

Two entry points, and they divide the way this path actually divides:

* `record_handoff_started` — an arq job, queued by the pre-call webhook receiver in
  `apps/voice-runtime/tool_routes.py`. It runs while the caller is still on the line and
  the destination's phone is still ringing, which is the only window in which the person
  about to answer can be told anything at all.
* `settle_handoff` — NOT an arq job. It is called by `pipeline._post_call_stages` with the
  execution snapshot that stage already holds, because the ending of the handover is a
  property of that snapshot and a second fetch would be a second vendor round trip for
  data already in hand — the reasoning `dispatch_due_callbacks` uses for riding the
  campaign tick rather than owning a schedule.

**WHAT THIS DOES INSTEAD OF A WHISPER, SAID PLAINLY.** The founder asked for the agent to
brief the human before bridging. That is a telephony feature (Plivo's `<Dial
confirmSound=…>`) and it needs control of the caller's leg, which this deployment does not
have: the engine places the transfer on the account connected to IT and we hold no carrier
credential. So the person's phone rings and a MESSAGE lands on it — the founder's own
stated second choice — carrying why the call is coming and what has happened so far. It is
not a whisper and nothing here calls it one. `docs/evidence/handoff-warm-transfer.md`
records what would have to change.

**THE TOOL PAYLOAD IS A HINT; THE FETCH IS THE TRUTH** (D-31), exactly as for the callback
and opt-out jobs beside it. The endpoint is unsigned and IP-allowlisted, so nothing that
decides WHO is affected may come from the body: the tenant, the agent and the call all come
back from the authenticated Get Execution and from our own routing table. The two things
that DO cross the queue are the model's `reason` and `summary`, and they cross because they
exist nowhere else — the execution record's own summary is not populated until the call
ends, and by then the phone has stopped ringing.

**AND THE NUMBER THAT ACTUALLY RANG IS READ BACK OFF THE ENGINE, NOT RE-DERIVED.** Our
roster resolves who is on duty at an instant, and the agent was published with that answer
at a DIFFERENT instant — an hours boundary crossed between the two turns an ordinary
attempt into a wrong record. So `_destination` asks the engine what the agent is holding,
which is the number being dialled, from the system dialling it, and falls back to the
roster only when that read fails. Recording a plausible number rather than the real one
would be the worst possible outcome for a row somebody may have to answer for later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import Retry
from calevate_shared.calling_window import IST, ist_wall_clock, next_window_opening
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.handoff import RosterMember, resolve_on_duty, roster
from apps.api.callbacks import service as callbacks
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.workers.redaction import redact

log = get_logger(__name__)

#: Must equal `apps/voice-runtime/tool_routes.HANDOFF_JOB`, asserted equal in
#: `tests/handoff_tool_test.py` — that service may not import this package (hard rule 3),
#: so the name is spelled twice and pinned rather than shared.
HANDOFF_JOB = "record_handoff_started"

#: The longest a `reason` or a `summary` may be after redaction. A BOUND at the boundary,
#: for `callbacks.MAX_NOTE`'s reason: both strings are written by a language model with no
#: length contract, they land in a column a client reads and a message somebody's phone
#: receives, and an unbounded model output is an unbounded row.
MAX_BRIEF_CHARS = 600


async def record_handoff_started(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Record that the agent is handing this caller over, and tell the person taking it.

    Returns a short outcome string (arq keeps it), which is what makes "the handover fired
    and nothing happened" answerable without a transcript.
    """
    # IMPORTED INSIDE THE FUNCTION, and it is the direction of the dependency that decides
    # it. `pipeline` calls `settle_handoff` below, so a module-level import back into it
    # would be a cycle; `callbacks.py` avoids the same one only because nothing in the
    # pipeline calls IT. The three helpers are the ingest ladder every engine-fetching job
    # in this package shares, and re-implementing them here would be a fourth opinion about
    # what a transient vendor failure is.
    from apps.workers.pipeline import _resolve_agent

    engine_name = str(payload.get("engine") or "fake")
    execution_id = str(payload["execution_id"])
    attempt = int(ctx.get("job_try", 1))

    snapshot = await _snapshot(engine_name, execution_id, attempt)
    async with untenanted_session() as session:
        resolved = await _resolve_agent(session, engine_name, snapshot.engine_agent_ref)
    if resolved is None:
        # The same terminal alert `record_in_call_optout` raises for the same condition: an
        # execution whose agent we cannot map is one we can attribute to no tenant, and
        # writing it anywhere would be writing it into somebody's account at random.
        alert(
            "WORKER_TERMINAL",
            "handoff_agent_unmapped",
            detail=f"engine={engine_name}",
            execution_id=execution_id,
        )
        return "unattributable"
    tenant_id, agent_id = resolved

    async with tenant_session(tenant_id) as session:
        members = await roster(session, agent_id=agent_id)
        member, destination = await _destination(
            session, agent_id=agent_id, members=members, engine_ref=snapshot.engine_agent_ref
        )
        if destination is None:
            # THE AGENT HANDED OVER AND WE CANNOT SAY TO WHOM. That is a real state and it
            # is alarming rather than fatal: the engine is dialling somebody, and the row
            # that would let a client see it cannot be written without a number. It happens
            # when the engine holds a transfer tool nobody here configured — which is
            # exactly what the publish read-back exists to catch — so the alert names that.
            alert(
                "CORE_LOGIC",
                "handoff_destination_unknown",
                detail=(
                    "this agent handed a caller to a person and neither the engine nor its "
                    "handover list could say to which number. If the engine holds a "
                    "transfer tool nobody configured here, the publish read-back "
                    "(`handoff_applied`) is where it shows."
                ),
                execution_id=execution_id,
            )
            return "destination_unknown"
        reason = _bounded(payload.get("reason"))
        summary = _bounded(payload.get("summary"))
        attempt_id = await _record(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            execution_id=execution_id,
            engine_call_id=snapshot.engine_call_id,
            member=member,
            destination=destination,
            reason=reason,
            summary=summary,
        )
    if attempt_id is None:
        # The engine allows one handover per conversation, so a second job for the same
        # execution is a retry, not a second handover. Correct and invisible.
        return "already_recorded"
    # Ids only — never the destination, never the model's prose (hard rule 6).
    log.info(
        "handoff_recorded",
        extra={"tenant_id": str(tenant_id), "handoff_id": str(attempt_id)},
    )
    await _send_brief(
        tenant_id=tenant_id,
        agent_id=agent_id,
        destination=destination,
        reason=reason,
        summary=summary,
    )
    return "recorded"


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


async def _record(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    execution_id: str,
    engine_call_id: str,
    member: RosterMember | None,
    destination: str,
    reason: str | None,
    summary: str | None,
) -> UUID | None:
    """Insert the attempt, or None when this conversation already has one.

    `ON CONFLICT DO NOTHING` on the execution rather than a SELECT-then-INSERT: the job is
    keyed on the execution and arq retries it, so two attempts of the same job can be in
    flight, and a read-then-write between them is the race BACKEND-PATTERNS §5 names.
    """
    attempt_id = uuid7()
    result = await session.execute(
        text(
            "INSERT INTO handoff_attempts (id, tenant_id, agent_id, source_execution_id, "
            "  source_call_id, member_id, destination_e164, started_at, reason, summary) "
            "SELECT :id, :tid, :aid, :ex, "
            "  (SELECT c.id FROM calls c WHERE c.engine_call_id = :ecid), "
            "  :mid, :dest, :now, :reason, :summary "
            "ON CONFLICT (tenant_id, source_execution_id) DO NOTHING "
            "RETURNING id"
        ),
        {
            "id": attempt_id,
            "tid": tenant_id,
            "aid": agent_id,
            "ex": execution_id,
            "ecid": engine_call_id,
            "mid": member.id if member is not None else None,
            "dest": destination,
            "now": datetime.now(UTC),
            "reason": reason,
            "summary": summary,
        },
    )
    return attempt_id if result.first() is not None else None


async def _destination(
    session: AsyncSession,
    *,
    agent_id: UUID,
    members: list[RosterMember],
    engine_ref: str | None,
) -> tuple[RosterMember | None, str | None]:
    """`(roster member, number)` for the leg the engine is placing right now.

    THE ENGINE IS ASKED FIRST, and the module docstring argues why: it is holding the
    number it is dialling, and our own roster answers a question about the clock that was
    asked at publish time rather than now. A vendor round trip is affordable here — this
    is a worker, it is one call per handover, and a handover is rare.

    The member is matched BY NUMBER, so the row records which of the client's people took
    it even though the engine knows nothing about our roster. An unmatched number is
    returned with `member=None` rather than refused: a number on the engine that is not on
    our list is exactly the case worth recording, and dropping it would hide it.
    """
    if engine_ref:
        try:
            snapshot = await get_engine().get_agent(engine_ref)
        except Exception as exc:
            # NOT A RETRY AND NOT A FAILURE. The fallback below is a good answer, and a
            # handover notice that retried for two minutes over a read-back would deliver
            # the brief after the phone had stopped ringing. `exc` is our own normalized
            # error (the adapter converts), so this carries no vendor text.
            log.info("handoff_engine_readback_failed", extra={"reason": type(exc).__name__})
        else:
            if len(snapshot.handoff_destinations) == 1:
                number = snapshot.handoff_destinations[0]
                return _member_for(members, number), number
    duty = resolve_on_duty(
        members,
        enabled=True,
        agent_hours=await _agent_hours(session, agent_id),
        at=datetime.now(UTC),
    )
    if duty.member is None:
        return None, None
    return duty.member, duty.member.phone_e164


def _member_for(members: list[RosterMember], number: str) -> RosterMember | None:
    return next((m for m in members if m.phone_e164 == number), None)


async def _agent_hours(session: AsyncSession, agent_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT business_hours FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).first()
    hours: dict[str, Any] | None = row[0] if row is not None else None
    return hours


def _bounded(raw: object) -> str | None:
    """The model's own words, REDACTED and bounded, or None.

    **REDACTED BEFORE ANYTHING ELSE TOUCHES THEM.** These two strings are a summary of a
    live conversation written by a language model, so they can carry anything the caller
    said — a card number read out loud, an Aadhaar, a second phone number. They go into a
    column a client reads and into a message delivered to somebody's handset, and both are
    places SEC-COMP §4's `text_redacted` rule applies with full force. `redact` is the same
    pass every transcript in this system goes through; there is no second one.
    """
    if not isinstance(raw, str):
        return None
    cleaned = redact(raw.strip()).text.strip()
    return cleaned[:MAX_BRIEF_CHARS] or None


async def _send_brief(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    destination: str,
    reason: str | None,
    summary: str | None,
) -> None:
    """Tell the person whose phone is ringing what the call is about.

    ⚠ **NOT WIRED TO A CHANNEL, AND THIS IS A NAMED EXTERNAL BLOCKER RATHER THAN AN
    OVERSIGHT.** Reaching a staff mobile in the ~15 seconds a phone rings needs SMS or
    WhatsApp, and this deployment has neither: there is no WABA, no phone number id and no
    access token (`apps/workers/whatsapp_cloud.py` says so at length), and SMS to an Indian
    handset needs a DLT-registered template through a registered sender, which is a
    registration nobody here can perform. Email exists and is the channel of record for
    hot-lead alerts — and is useless in fifteen seconds, so it is deliberately not used as
    a substitute that would look like the feature working.

    So this logs the fact and the alarm names what closes it. **Writing a WhatsApp send
    against an unconfigured transport would have been the worse choice**: it would look
    finished, pass every test with the dev sink, and fail silently on the first real
    handover — which is the exact defect class `whatsapp.py`'s own docstring exists to
    refuse. The row is written either way, so the client's screen tells them who was rung
    and why the moment the call ends; what is missing is the message that arrives sooner.

    WHAT CLOSES IT: a WhatsApp Business Account and an approved template (OPERATIONS §2
    gate 46d). At that point this function calls the transport that already exists, with
    `reason` and `summary` already redacted and bounded above.
    """
    log.info(
        # Ids and the two booleans only. Not the number, not the prose (hard rule 6).
        "handoff_brief_undelivered",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "has_reason": reason is not None,
            "has_summary": summary is not None,
        },
    )
    alert(
        "CORE_LOGIC",
        "handoff_brief_channel_absent",
        detail=(
            "a caller was handed to a person and that person's phone rang with no context: "
            "no WhatsApp Business Account is configured and SMS needs a DLT-registered "
            "template. OPERATIONS §2 gate 46d"
        ),
        tenant_id=str(tenant_id),
    )


async def _snapshot(engine_name: str, execution_id: str, attempt: int) -> ExecutionSnapshot:
    """The authenticated fetch, with `callbacks._snapshot`'s ladder and its terminal alert.

    Spelled here rather than imported from that module for one reason: importing it would
    make this module depend on the callback booking package for a helper about executions,
    and the dependency this module actually has on `callbacks` is the opposite one (the
    settlement books a callback). Two small ladders beat a cycle.
    """
    from apps.workers.pipeline import _is_transient, _retry_after

    try:
        return await get_engine().get_execution(execution_id)
    except Exception as exc:
        if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from exc
        alert(
            "WORKER_TERMINAL",
            "handoff_unresolved",
            detail=f"{type(exc).__name__} after {attempt} attempt(s)",
            execution_id=execution_id,
        )
        raise


__all__ = [
    "HANDOFF_CALLBACK_NOTE",
    "HANDOFF_JOB",
    "MAX_BRIEF_CHARS",
    "record_handoff_started",
    "settle_handoff",
]
