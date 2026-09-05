"""Requested callbacks — every read and write of `scheduled_callbacks`, in one module.

A caller says "ring me back Tuesday at four". The agent books it mid-call through the
in-call tool (`apps/voice-runtime/tool_routes.py`), a worker writes the row
(`apps/workers/callbacks.py`), the campaign dispatch tick dials it at its time through
`agents.service.dispatch_call` — the ONE outbound entry point — and the client watches all
of it on `GET /v1/callbacks`.

WHAT MAKES THIS DIFFERENT FROM A CAMPAIGN CONTACT, AND WHY THE DIFFERENCE IS THE DESIGN
--------------------------------------------------------------------------------------
**A promise was made to a human being.** A campaign contact that is refused goes back on a
thirty-minute ladder and nobody is waiting; a callback that is refused has somebody sitting
by a phone. That single fact decides three things this module does that the dispatcher
does not:

1. **NOTHING RETRIES FOR EVER, AND THE BOUND IS THE CLOCK RATHER THAN A COUNT.**
   `tests/dispatch_refusal_settlement_test.py` records three livelocks that shipped on the
   campaign side, all the same shape: a refusal classified as transient about a fact that
   could never change, re-claimed every thirty minutes for the life of the campaign, and
   nothing errored. The classification here is the SAME one — `PERSON_LEVEL_REFUSALS`,
   imported from the gate that owns it, never a second opinion — but it is not what stops
   the livelock. `GRACE` is: past `requested_at + GRACE` a callback is `missed`, whatever
   the refusal was and whether or not anybody classified it. A rule nobody thought about
   costs a client two hours of retries and then settles with a visible reason, instead of
   running until the heat death of the campaign.
2. **EVERY ENDING SAYS WHY, IN THE GATE'S OWN CLIENT-FACING WORDS.** `last_refusal_reason`
   is `DispatchDecision.reason` — the sentence the gate already writes for a person
   ("This number is on the do-not-call list.") — so a client reading their callbacks list
   sees the same explanation the dial button would have shown them.
3. **THE PROMISED TIME IS NOT A SUGGESTION.** A callback is claimed only from its own
   instant onward, and a transient refusal defers it by `RETRY_AFTER` rather than by the
   dispatcher's thirty minutes: half an hour of a two-hour grace is four attempts, and
   somebody who was told "four o'clock" should not first hear from us at half past five
   because the first tick found an empty wallet.

CANCELLATION AND DNC REACH A BOOKED CALLBACK BY TWO SEPARATE DOORS, BOTH REAL
--------------------------------------------------------------------------------------
* `cancel_for_phones` is the FAST door: the in-call "actually, don't call me" tool and the
  client's own cancel button both land here, and the row stops being claimable at once.
* `check_dispatch` at fire time is the door that CANNOT be forgotten. Every callback dial
  passes it (hard rule 5), its DNC read is uncached and per-number, and `dnc` is a
  person-level refusal — so a number added to the list at any point between booking and
  ringing settles the callback `refused` on the very next tick, exactly as CLAUDE.md
  requires DNC additions to propagate before the next dispatch tick. The fast door is a
  courtesy that makes the screen truthful sooner; the gate is the enforcement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from calevate_shared.calling_window import IST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import CALL_CAP_MAX_S
from apps.api.callbacks.models import STATUSES
from apps.api.db.result import rowcount_of

#: How long past the promised time we keep trying before giving up and SAYING SO.
#:
#: Two hours is chosen against what a caller remembers rather than against what a queue
#: can afford. A callback that arrives ninety minutes late is still recognisably the call
#: they asked for; one that arrives the next morning is a cold call from a company they
#: spoke to yesterday, and the person who answers it did not agree to that. It is also
#: long enough to outlast every transient blocker that realistically clears by itself — a
#: topped-up wallet, a lifted platform halt, a worker restart — and short enough that a
#: callback promised at 20:00 does not survive into the next day's calling window, which
#: is the case that would otherwise ring somebody at 09:00 with no idea why.
GRACE: Final[timedelta] = timedelta(hours=2)

#: How long a transient refusal defers a callback. The campaign dispatcher waits thirty
#: minutes because its contacts are interchangeable and its list is long; a callback has
#: an appointment, so it re-tries at the granularity of the promise instead. Five minutes
#: inside a two-hour grace is twenty-four attempts, each one a single indexed read plus a
#: gate the tick was going to run anyway.
RETRY_AFTER: Final[timedelta] = timedelta(minutes=5)

#: A `dialing` callback whose call never reached a terminal status. The SAME derivation
#: `campaign_dispatch.STUCK_DIALING_AFTER` uses, from the same constant, because it
#: answers the same question — "could this call still legitimately be in progress?" — and
#: two numbers for it would mean one of the two reapers was wrong.
STUCK_DIALING_AFTER: Final[timedelta] = timedelta(seconds=CALL_CAP_MAX_S) + timedelta(minutes=10)

#: How much of the caller's stated reason we keep. It is model-written text about what a
#: person said, arriving on an unsigned endpoint, and it is spoken back into the callback
#: as context — so it is bounded where it enters, on the same argument (and at the same
#: size) as `campaigns.routes.MAX_CONTACT_CUSTOM_VALUE_LEN`.
MAX_NOTE: Final[int] = 200

#: The two states a promise is still ALIVE in: waiting for its time, or being dialled.
#: Named rather than derived because these are the ones with behaviour attached —
#: `claim_due` claims from the first and `settle_dialled` ends the second.
LIVE_STATUSES: Final[frozenset[str]] = frozenset({"scheduled", "dialing"})

#: Every other ending a call-back can reach. The screen renders a SENTENCE for each and
#: never the word (`callbacks/routes._ENDINGS`): "refused" is our vocabulary and "we were
#: not allowed to make this call" is theirs, and `refused`/`missed` usually carry the
#: compliance gate's own more specific words on the row.
#:
#: **DERIVED FROM `models.STATUSES`, NOT RETYPED**, and the model's docstring said it was
#: before it was — which is the defect class this repo keeps a decision log about. A
#: literal here is a second copy of the vocabulary the CHECK constraint enforces, and the
#: way it would fail is silent: a status added to the schema and not to this set makes
#: `settle()` refuse a legal ending at 3am in a worker, with a message naming a mistake
#: nobody made.
#:
#: THE SUBTRACTION RUNS THE SAFE WAY ROUND. A status added without thought lands here, in
#: the endings, so `settle()` accepts it; landing in `LIVE_STATUSES` instead would make the
#: tick try to CLAIM and DIAL it. Between "an ending nobody wrote a screen sentence for"
#: and "an unplanned state the dispatcher rings people from", the first is the survivable
#: one.
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(STATUSES) - LIVE_STATUSES

#: What a client is told when we ran out of time without the gate ever saying anything —
#: the worker was down, or the whole window passed inside one outage. Rare, and it must
#: still be a sentence rather than a blank cell.
UNATTEMPTED_REASON: Final[str] = (
    "We were not able to place this call in time. Nothing blocked it — it simply did not "
    "go out while it still made sense to."
)


@dataclass(frozen=True, slots=True)
class DueCallback:
    """One claimed promise, with everything the dial needs and nothing more."""

    id: UUID
    agent_id: UUID
    lead_id: UUID | None
    phone_e164: str
    requested_at: datetime
    note: str | None


def context_note(requested_at: datetime, note: str | None) -> str:
    """What the agent is told this call is FOR, as one sentence in the prompt.

    It rides `CallContext.context_note`, which is the field the D-21 "call this lead"
    button and `crm.service.plan_callback` already use — deliberately not a new channel
    into the prompt, for the reason `CallContext` states about the summary field it
    deleted: a second door into what the agent says is a second door that can forget a
    redaction. Nothing transcript-derived goes in here; the note is the agent's own
    one-line summary of the request, bounded at `MAX_NOTE` where it entered.

    IST, because it is read out to a person in India.
    """
    when = (requested_at.astimezone(UTC) + IST).strftime("%d %b at %H:%M")
    opening = f"This is the call-back they asked for on {when}."
    return f"{opening} They said: {note}" if note else opening


_UPSERT = text(
    # ON CONFLICT on the execution: one live promise per conversation (migration
    # d8f31a7c2409 argues the key). The guard is `booked_at`, not `DO NOTHING`, because
    # the caller changing their mind — "make it five, not four" — is an ordinary sentence
    # and must move the time; and because two jobs racing must land on the caller's LATER
    # word whichever of them reaches the row first.
    #
    # A row that has already been claimed, cancelled or settled is NOT re-opened: a
    # `status = 'scheduled'` predicate keeps a late duplicate from resurrecting a callback
    # the client cancelled or the gate refused.
    "INSERT INTO scheduled_callbacks ("
    "  id, tenant_id, agent_id, source_call_id, source_execution_id, lead_id, phone_e164, "
    "  requested_at, booked_at, status, note, language, created_at, updated_at) "
    "VALUES (:id, :tid, :aid, :call_id, :execution_id, :lead_id, :phone, :requested_at, "
    "  :booked_at, 'scheduled', :note, :language, now(), now()) "
    "ON CONFLICT (tenant_id, source_execution_id) DO UPDATE SET "
    "  requested_at = EXCLUDED.requested_at, booked_at = EXCLUDED.booked_at, "
    "  note = EXCLUDED.note, language = EXCLUDED.language, agent_id = EXCLUDED.agent_id, "
    "  source_call_id = coalesce(EXCLUDED.source_call_id, scheduled_callbacks.source_call_id), "
    "  lead_id = coalesce(EXCLUDED.lead_id, scheduled_callbacks.lead_id), "
    "  updated_at = now() "
    "WHERE scheduled_callbacks.status = 'scheduled' "
    "  AND scheduled_callbacks.booked_at < EXCLUDED.booked_at "
    "RETURNING id, requested_at"
)


async def book(
    session: AsyncSession,
    *,
    callback_id: UUID,
    tenant_id: UUID,
    agent_id: UUID,
    source_call_id: UUID | None,
    source_execution_id: str,
    lead_id: UUID | None,
    phone_e164: str,
    requested_at: datetime,
    booked_at: datetime,
    note: str | None,
    language: str | None,
) -> tuple[UUID, datetime] | None:
    """Write (or move) the promise. None when an older duplicate lost to what is on file.

    Returns the row's id and the time it is now booked for — which is NOT necessarily
    `requested_at`: a job that arrives after a later booking has already landed changes
    nothing and is told so, rather than being allowed to drag the promise backwards.
    """
    row = (
        await session.execute(
            _UPSERT,
            {
                "id": callback_id,
                "tid": tenant_id,
                "aid": agent_id,
                "call_id": source_call_id,
                "execution_id": source_execution_id,
                "lead_id": lead_id,
                "phone": phone_e164,
                "requested_at": requested_at,
                "booked_at": booked_at,
                "note": (note or None) and note[:MAX_NOTE],
                "language": (language or None) and language[:8],
            },
        )
    ).first()
    return (UUID(str(row[0])), row[1]) if row is not None else None


async def expire_stale(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Settle every promise that has gone past saving. Returns how many.

    **THE ANTI-LIVELOCK, AND IT RUNS BEFORE THE CLAIM.** It does not consult the refusal
    classification at all, which is the point: the three livelocks
    `tests/dispatch_refusal_settlement_test.py` records were all rules nobody had thought
    about, and a bound that only catches the rules somebody remembered would have caught
    none of them. Two hours after the promised time a callback ends, and the client is
    told the last thing the gate said — or, if nothing ever refused it, that it simply did
    not go out.

    A `dialing` row is deliberately NOT expired here: it is either ringing or already rang,
    and `settle_dialled` is what ends it.
    """
    result = await session.execute(
        text(
            "UPDATE scheduled_callbacks SET status = 'missed', settled_at = now(), "
            "  last_refusal_reason = coalesce(last_refusal_reason, :fallback), "
            "  updated_at = now() "
            "WHERE status = 'scheduled' AND requested_at < :cutoff"
        ),
        {"cutoff": (now or datetime.now(UTC)) - GRACE, "fallback": UNATTEMPTED_REASON},
    )
    return rowcount_of(result)


async def settle_dialled(session: AsyncSession, *, now: datetime | None = None) -> int:
    """End the callbacks whose dial has finished. Returns how many.

    Read off OUR `calls` row rather than hooked into the post-call pipeline, and that is a
    deliberate choice between two shapes. A hook would settle the callback a few seconds
    sooner and would put a second owner inside `pipeline.py`'s call-resolution path — the
    place a campaign contact is already resolved from — for a promise whose whole state
    machine lives in this module. Reading the call row is one indexed join in a tick that
    is already open, it cannot be forgotten by a pipeline branch that returns early, and
    it settles a callback whose call the RECONCILIATION POLLER discovered rather than the
    webhook, which a hook on the webhook path would never see (D-31).

    **RANGING IS THE PROMISE, NOT ANSWERING.** `no_answer`, `busy` and `voicemail` settle
    `completed`: we called them at the time they asked. Only `failed` — the dial the
    vendor never placed — is a `failed` callback, and the call row is on the client's
    screen either way with its own outcome on it.

    The last arm is the backstop `campaign_dispatch._reap_stuck_dialing` has: a `dialing`
    callback whose call never reached a terminal status at all, past the longest a call may
    legally last. It ends `failed` rather than going back on the ladder, for that reaper's
    reason — a dial we cannot prove did not ring must never be retried.
    """
    moment = now or datetime.now(UTC)
    settled = await session.execute(
        text(
            "UPDATE scheduled_callbacks s SET "
            "  status = CASE WHEN c.status = 'failed' THEN 'failed' ELSE 'completed' END, "
            "  settled_at = now(), updated_at = now() "
            "FROM calls c "
            "WHERE c.id = s.last_call_id AND s.status = 'dialing' "
            "  AND c.status IN ('completed', 'failed', 'no_answer', 'busy', 'voicemail')"
        )
    )
    stuck = await session.execute(
        text(
            "UPDATE scheduled_callbacks SET status = 'failed', settled_at = now(), "
            "  updated_at = now() "
            "WHERE status = 'dialing' AND updated_at < :cutoff"
        ),
        {"cutoff": moment - STUCK_DIALING_AFTER},
    )
    return rowcount_of(settled) + rowcount_of(stuck)


async def claim_due(
    session: AsyncSession, *, now: datetime | None = None, limit: int
) -> list[DueCallback]:
    """CAS `scheduled → dialing` for up to `limit` promises whose time has come.

    `FOR UPDATE SKIP LOCKED` inside a `MATERIALIZED` CTE, `ORDER BY requested_at, id`, for
    the three reasons `campaign_dispatch`'s claim spells out at length: the materialization
    stops the planner rescanning the LIMIT subquery and handing out more rows than asked
    for, the total order makes the claim deterministic, and SKIP LOCKED is what lets two
    ticks run without double-dialling. The tiebreak matters more here than there — the
    oldest promise is the one somebody has been waiting longest for.

    THE CLAIM IS THE ONLY THING THAT MAKES A DOUBLE DIAL IMPOSSIBLE. An arq job that fires
    twice, two workers, a tick that overlaps its predecessor: all of them contend on this
    one conditional UPDATE, and the loser gets an empty list rather than a second phone
    ringing in somebody's kitchen.
    """
    rows = (
        await session.execute(
            text(
                "WITH picked AS MATERIALIZED ("
                "  SELECT id FROM scheduled_callbacks "
                "  WHERE status = 'scheduled' AND requested_at <= :now "
                "  AND (next_attempt_at IS NULL OR next_attempt_at <= :now) "
                "  ORDER BY requested_at, id LIMIT :n FOR UPDATE SKIP LOCKED"
                ") "
                "UPDATE scheduled_callbacks s SET status = 'dialing', "
                "  attempts = s.attempts + 1, updated_at = now() "
                "FROM picked WHERE s.id = picked.id "
                "RETURNING s.id, s.agent_id, s.lead_id, s.phone_e164, s.requested_at, s.note"
            ),
            {"now": now or datetime.now(UTC), "n": limit},
        )
    ).all()
    return [
        DueCallback(
            id=UUID(str(row[0])),
            agent_id=UUID(str(row[1])),
            lead_id=UUID(str(row[2])) if row[2] else None,
            phone_e164=str(row[3]),
            requested_at=row[4],
            note=row[5],
        )
        for row in rows
    ]


async def defer(session: AsyncSession, callback_id: UUID, *, rule: str, reason: str | None) -> None:
    """A refusal that waiting can lift: back to `scheduled`, attempt refunded, reason kept.

    The refund is `_refuse_contact`'s argument, unchanged: a blocked dial never rang a
    phone, so charging it an attempt would make the count mean "we were not allowed to try"
    rather than "we tried and could not reach them".

    The reason is kept even though the row is going back on the ladder, because it is what
    `expire_stale` will show the client if the block never clears — and because a client
    watching a callback sit at "waiting" deserves to see "this account has no calling
    credit left" now rather than in two hours.
    """
    await session.execute(
        text(
            "UPDATE scheduled_callbacks SET status = 'scheduled', "
            "  attempts = attempts - 1, next_attempt_at = :next_try, "
            "  last_refusal_rule = :rule, last_refusal_reason = :reason, updated_at = now() "
            "WHERE id = :id AND status = 'dialing'"
        ),
        {
            "id": callback_id,
            "rule": rule,
            "reason": reason,
            # `next_attempt_at`, NEVER `requested_at`. Moving the promise forward on each
            # refusal was the first draft, and it made `expire_stale`'s two-hour cutoff
            # recede by five minutes every five minutes: the exact livelock this module's
            # docstring is about, written into the fix for it.
            "next_try": datetime.now(UTC) + RETRY_AFTER,
        },
    )


async def settle(
    session: AsyncSession,
    callback_id: UUID,
    *,
    status: str,
    rule: str | None = None,
    reason: str | None = None,
    call_id: UUID | None = None,
) -> None:
    """End a callback, terminally, with the words a client will read.

    `status` is checked against `TERMINAL_STATUSES` here as well as by the database's own
    CHECK, because the DB's refusal names a constraint and this one names the mistake.
    """
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"{status} is not an ending a callback can have")
    await session.execute(
        text(
            "UPDATE scheduled_callbacks SET status = :status, settled_at = now(), "
            "  last_refusal_rule = coalesce(:rule, last_refusal_rule), "
            "  last_refusal_reason = coalesce(:reason, last_refusal_reason), "
            "  last_call_id = coalesce(:call_id, last_call_id), updated_at = now() "
            "WHERE id = :id AND settled_at IS NULL"
        ),
        {"id": callback_id, "status": status, "rule": rule, "reason": reason, "call_id": call_id},
    )


def link_callback_to_call(
    callback_id: UUID,
) -> Callable[[AsyncSession, UUID], Awaitable[None]]:
    """`dispatch_call`'s `on_reserved` hook: point the promise at the call it became.

    Runs INSIDE the transaction that inserts the `calls` row and commits with it — the FK
    needs the row to exist, and the whole value of the pointer is that it is durable before
    the vendor can seize a line. Without it, a response lost on the way back from the engine
    would leave a `dialing` callback with nothing to settle against, and `settle_dialled`'s
    stuck arm would end it `failed` when the phone may well have rung.
    """

    async def link(session: AsyncSession, call_id: UUID) -> None:
        await session.execute(
            text(
                "UPDATE scheduled_callbacks SET last_call_id = :call, updated_at = now() "
                "WHERE id = :id"
            ),
            {"call": call_id, "id": callback_id},
        )

    return link


async def cancel_for_phones(session: AsyncSession, *, phones: Sequence[str], reason: str) -> int:
    """Call off every live promise to any of these numbers. Returns how many.

    Both fast doors land here — the in-call "actually, do not call me" tool and a
    suppression the client just added — so there is ONE statement that stops a callback
    early, rather than one per caller with its own idea of which statuses are still
    stoppable.

    **A LIST AND NOT A NUMBER**, because the second caller arrived with one: a DNC bulk
    import suppresses thousands at once (`compliance/dnc.add_numbers`), and a per-number
    round trip there would be thousands of single-row UPDATEs inside the transaction that
    writes the suppression. The in-call caller passes a list of one, which costs it
    nothing. `= ANY(:phones)` reads the partial index on
    `(tenant_id, phone_e164) WHERE status IN ('scheduled', 'dialing')`.

    `dialing` rows are deliberately NOT cancelled: that dial is in flight or has already
    rung, and rewriting its state would tell the client a call was called off when their
    lead's phone was ringing as we wrote it. The compliance gate is what covers that row —
    it runs on the dial itself, so a suppression added while a call-back was being placed
    is enforced there rather than here.
    """
    if not phones:
        return 0
    result = await session.execute(
        text(
            "UPDATE scheduled_callbacks SET status = 'cancelled', settled_at = now(), "
            "  last_refusal_reason = :reason, updated_at = now() "
            "WHERE phone_e164 = ANY(:phones) AND status = 'scheduled'"
        ),
        {"phones": list(phones), "reason": reason},
    )
    return rowcount_of(result)


async def cancel_one(session: AsyncSession, callback_id: UUID, *, reason: str) -> bool:
    """The client's own cancel button. False when there was nothing left to stop."""
    result = await session.execute(
        text(
            "UPDATE scheduled_callbacks SET status = 'cancelled', settled_at = now(), "
            "  last_refusal_reason = :reason, updated_at = now() "
            "WHERE id = :id AND status = 'scheduled'"
        ),
        {"id": callback_id, "reason": reason},
    )
    return rowcount_of(result) > 0


async def list_callbacks(
    session: AsyncSession, *, limit: int, open_only: bool = False
) -> list[dict[str, Any]]:
    """The client's list: soonest promise first, then the recently settled ones.

    Ordered by `requested_at` DESC so the most recent activity is at the top of the
    screen and the callbacks still to come sit above the ones that have been. Bounded by
    `limit` at the route, which is what keeps it off the BOUNDED_LISTS registry.
    """
    where = " WHERE status = 'scheduled'" if open_only else ""
    rows = (
        await session.execute(
            text(
                "SELECT id, agent_id, phone_e164, requested_at, status, attempts, "
                "  last_refusal_rule, last_refusal_reason, last_call_id, lead_id, note, "
                "  settled_at "
                f"FROM scheduled_callbacks{where} ORDER BY requested_at DESC, id LIMIT :n"
            ),
            {"n": limit},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def get_callback(session: AsyncSession, callback_id: UUID) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT id, agent_id, phone_e164, requested_at, status, attempts, "
                "  last_refusal_rule, last_refusal_reason, last_call_id, lead_id, note, "
                "  settled_at FROM scheduled_callbacks WHERE id = :id"
            ),
            {"id": callback_id},
        )
    ).mappings()
    found = row.first()
    return dict(found) if found is not None else None


__all__ = [
    "GRACE",
    "LIVE_STATUSES",
    "MAX_NOTE",
    "RETRY_AFTER",
    "STUCK_DIALING_AFTER",
    "TERMINAL_STATUSES",
    "UNATTEMPTED_REASON",
    "DueCallback",
    "book",
    "cancel_for_phones",
    "cancel_one",
    "claim_due",
    "context_note",
    "defer",
    "expire_stale",
    "get_callback",
    "link_callback_to_call",
    "list_callbacks",
    "settle",
    "settle_dialled",
]
