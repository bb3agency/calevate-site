"""PLACING the handover: the one path from "the agent wants a person" to a ringing phone.

`agents/handoff.py` answers WHO — the ordered roster, who is on duty at this instant, and
the five reasons nobody is. This module answers WHETHER IT CAN HAPPEN AT ALL and, when it
can, makes it happen through `agents/transfer_providers/`. They are separate files because
they fail for separate reasons: one is a client's configuration, the other is a platform
capability, and a client told to "record your opening hours" when the platform cannot
transfer anybody has been given a remediation that fixes nothing.

WHAT THE CALLER IS PROMISED, WHICH IS THE WHOLE POINT
------------------------------------------------------
Hard rule 5 in this corner reads: an agent must never tell a caller something it cannot
do. There are exactly two honest answers to "put me through to a person":

* **placed** — a second leg is ringing, the person will hear who is calling and why before
  they can speak to anybody, and only then are the two joined. The caller hears
  `handoff.spoken_line_for`, which promises that somebody is being rung and nothing more.
* **degraded** — no leg was placed, and the agent says so plainly and offers the call-back
  that already exists (`callbacks/service.book`). `HANDOFF_DEGRADED_SAY` is that sentence.

There is no third answer, and in particular there is no silent drop: every refusal below
carries a machine reason an operator can read and ends in the same truthful sentence to
the caller.

WHEN a handover should happen is NOT decided here. That is the client's own call script
and their trigger wording; this module is reached because the agent already decided.

WHAT THIS MODULE DOES NOT METER, AND WHERE IT WOULD HAVE TO BE
---------------------------------------------------------------
**A bridged second leg is carrier time somebody pays for, for its whole duration.** Its
quantity is `TransferStarted.bridged_seconds` and it is stored on `handoff_attempts.
leg_duration_s` by the settle below. It is NOT metered, and the two places it would have
to be are named rather than left to be discovered:

* `apps/api/worker/service.py::_INSERT_USAGE_SQL`, on the `carrier` leg of
  `calevate_shared.worker_api.MeteredLegName` — the one writer of `usage_events` for a
  call, which multiplies a reported quantity by an ATTESTED rate (hard rule 7);
* its twin `_INSERT_REFUSAL_SQL` (`call_metering_refusals`) when no attested carrier rate
  exists, so "why did this call meter nothing" keeps an answer that is not a shrug.

Neither is written here because neither can be honest yet: no deployment can place a leg
(see `transfer_providers/registry.py`), and **UNKNOWN — what a carrier charges for a
second leg cannot be read from this container** (`api.plivo.com` is egress-blocked; fact 5
of `transfer_providers/plivo.py`'s prompt is what would supply the duration it is charged
on). OPERATIONS §2 gate 46c asks the same question of the RENTED engine and is not this
one. Metering at an invented rate would put a number in an append-only ledger that nothing
could later correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.engine import E164, VoiceEngine
from calevate_shared.languages import get_language
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.handoff import on_duty, spoken_line_for
from apps.api.agents.service import resolve_caller_id
from apps.api.agents.transfer_providers import (
    HANDOFF_OUTCOME_OF,
    PLATFORM_CANNOT_TRANSFER,
    TransferContractUnverifiedError,
    TransferOutcome,
    TransferRefusedError,
    TransferRequest,
    available_transfer,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger(__name__)

#: WHAT THE AGENT MUST TELL A CALLER WHEN NO LEG WAS PLACED. One producer for the same
#: reason `HANDOFF_SPOKEN_TEMPLATES` has one: this sentence is the difference between an
#: honest refusal and a caller left on hold, and a second copy of it is a second chance to
#: soften it into a promise.
#:
#: It forbids the two things a model reaches for unprompted — "transferring you now" and
#: "please hold" — because both are true only of the path that did not happen.
HANDOFF_DEGRADED_SAY: Final = (
    "You CANNOT put this caller through to a person on this line, and you must not say you "
    "are transferring them or ask them to hold. Tell them plainly that you are not able to "
    "connect them right now, apologise, and offer either to have somebody call them back — "
    "then use the call-back tool if they agree — or to take a message."
)

#: WHAT THE AGENT SAYS WHILE A PLACED HANDOVER RINGS, in the caller's language, is
#: `handoff.spoken_line_for` — the same sentence the client's screen shows them.

#: THE KEYPRESS THAT ACCEPTS. A key rather than speech because a voicemail greeting, an
#: answering machine and a ringback tone all produce sound and none of them presses a
#: button: the accept step's entire job is to tell a person from a recording.
ACCEPT_KEY: Final = "1"

#: How long the destination may ring, and how long after the whisper the person has to
#: accept. Both are time the CALLER spends holding, which is why they are bounded here
#: rather than left to a carrier default nobody has read.
#:
#: **UNKNOWN — at what point an Indian mobile network diverts an unanswered call to
#: voicemail.** The pattern is built so that the answer does not matter: a voicemail
#: greeting cannot press the accept key, so a diversion ends as `unanswered` rather than as
#: a caller bridged to a recording.
RING_TIMEOUT_S: Final = 25
WHISPER_TIMEOUT_S: Final = 10

#: WHAT THE PERSON TAKING THE CALL HEARS BEFORE THEY ACCEPT, per language.
#:
#: Composed by us and not by a client, for `HANDOFF_SPOKEN_TEMPLATES`' reason: it is spoken
#: on every escalated call and it has to say four things in one breath — that this is their
#: own business's line, who is calling, what about, and what to press. A client-authored
#: version would be one edit away from omitting the last of them.
#:
#: `{caller}` is a phone number spoken to the one person entitled to hear it, and it is
#: never logged (hard rule 6). `{about}` is the model's own prose, bounded before it
#: arrives.
WHISPER_TEMPLATES: Final[dict[str, str]] = {
    "te-IN": (
        "{label} gaaru, mee business ki oka call vachindi. Call chesina number {caller}. "
        "{about} Call teesukovadaniki {key} nokkandi."
    ),
    "hi-IN": (
        "{label} ji, aapke business ke liye ek call hai. Call karne wala number {caller} "
        "hai. {about} Call lene ke liye {key} dabaiye."
    ),
    "en-IN": (
        "{label}, there is a call for your business. The caller is on {caller}. {about} "
        "Press {key} to take the call."
    ),
}

#: The language a whisper falls back to, for `handoff._FALLBACK_LANGUAGE`'s reason: a
#: template rendered in a language the business does not speak is worse than the lingua
#: franca. Taken from the language declaration rather than hand-typed, so the two tables
#: cannot come to fall back to different languages.
_FALLBACK_LANGUAGE: Final = get_language("english_india").bcp47

#: What the person hears where the model gave no reason. Not an empty string: a whisper
#: that names no subject leaves the person deciding whether to accept on nothing at all.
_ABOUT_UNKNOWN: Final[dict[str, str]] = {
    "te-IN": "Vaallu oka manishi tho maatladaalani adugutunnaru.",
    "hi-IN": "Woh kisi vyakti se baat karna chahte hain.",
    "en-IN": "They have asked to speak to a person.",
}

#: The longest run of model prose a whisper will carry. The reason `workers/handoff.
#: MAX_BRIEF_CHARS` gives, one notch tighter: this is SPOKEN to somebody holding a ringing
#: phone while a caller waits, so an unbounded model output is an unbounded delay before
#: the accept key can be pressed.
MAX_WHISPER_ABOUT: Final = 200

#: WHY NO LEG WAS PLACED, in machine words. Operator-facing and metric labels — the CALLER
#: hears `HANDOFF_DEGRADED_SAY` for every one of them, because the difference between them
#: is never the caller's to fix.
#:
#: The five roster reasons are NOT respelled here: `handoff._UNAVAILABLE_REASONS` owns
#: them, and `OnDuty.reason` is passed through unchanged so a client's screen and this
#: path cannot come to disagree about why nobody is available.
OUTCOME_UNREPORTABLE: Final = "outcome_unreportable"
NO_PRESENTABLE_CLI: Final = "no_presentable_cli"
CARRIER_REFUSED: Final = "carrier_refused"
AGENT_UNKNOWN: Final = "agent_unknown"
#: A second handover on one conversation. Not an error and not a retry to be distinguished
#: from one: the row is claimed by the execution id, so whichever of the two arrives second
#: places no leg. One handover per conversation is also what `handoff_attempts`' unique
#: index already assumes, and what the rented engine enforces for itself
#: (`workers/handoff._record` and `agents/handoff.py` carry that engine's citation).
ALREADY_HANDED_OVER: Final = "already_handed_over"
#: The carrier would take the request and report the ending later, on a path that has to
#: answer the caller's agent now. See `CallTransferProvider.settles_synchronously`.
OUTCOME_ARRIVES_LATE: Final = "outcome_arrives_late"


@dataclass(frozen=True, slots=True)
class HandoffPlacement:
    """What happened, and what the agent must now say.

    A VERDICT RATHER THAN A BOOLEAN, for `OnDuty`'s reason: "not placed" has nine distinct
    causes, four of which a client can fix in a minute, and collapsing them would leave an
    operator with a feature that does not work and no sentence explaining it.
    """

    #: None when no leg was placed.
    provider_ref: str | None
    #: None when no leg was placed, and None after a placed leg whose ending the carrier
    #: reports later over its own callback.
    outcome: TransferOutcome | None
    #: A member of the reasons above or of `handoff._UNAVAILABLE_REASONS`; None on success.
    reason: str | None
    #: The sentence the agent must say to the caller. Never empty, in either direction.
    say: str
    #: The row this handover is recorded on, when one was written.
    attempt_id: UUID | None = None

    @property
    def placed(self) -> bool:
        return self.provider_ref is not None


#: What the person hears in place of a number the carrier never gave us. Named rather than
#: left blank: somebody deciding whether to accept is entitled to know which of the two it
#: is.
_WITHHELD: Final[dict[str, str]] = {
    "te-IN": "teliyadu",
    "hi-IN": "chhupaya gaya hai",
    "en-IN": "withheld",
}


def compose_whisper(
    *, language: str, label: str, caller_e164: str | None, about: str | None
) -> str:
    """The private message the person hears before they accept.

    ONE PRODUCER so that what a client is shown and what their staff hear cannot differ,
    and so no carrier adapter is ever in the position of writing product copy.
    """
    template = WHISPER_TEMPLATES.get(language, WHISPER_TEMPLATES[_FALLBACK_LANGUAGE])
    unknown = _ABOUT_UNKNOWN.get(language, _ABOUT_UNKNOWN[_FALLBACK_LANGUAGE])
    subject = (about or "").strip()[:MAX_WHISPER_ABOUT] or unknown
    return template.format(
        label=label,
        caller=caller_e164 or _WITHHELD.get(language, _WITHHELD[_FALLBACK_LANGUAGE]),
        about=subject if subject.endswith((".", "?", "!")) else f"{subject}.",
        key=ACCEPT_KEY,
    )


_AGENT_SQL: Final = (
    "SELECT handoff_enabled, business_hours, language_primary FROM agents "
    "WHERE id = :aid AND deleted_at IS NULL"
)

#: `ON CONFLICT DO NOTHING` on the execution rather than SELECT-then-INSERT, and the
#: columns are `workers/handoff._record`'s: one conversation has at most one handover, and
#: the unique index is what makes a retried tool call idempotent rather than a second leg.
_INSERT_ATTEMPT_SQL: Final = """
INSERT INTO handoff_attempts (id, tenant_id, agent_id, source_execution_id, source_call_id,
                              member_id, destination_e164, started_at, reason, summary)
SELECT :id, :tid, :aid, :ex, (SELECT c.id FROM calls c WHERE c.engine_call_id = :ex),
       :mid, :dest, :now, :reason, :summary
ON CONFLICT (tenant_id, source_execution_id) DO NOTHING
RETURNING id
"""

_SETTLE_ATTEMPT_SQL: Final = """
UPDATE handoff_attempts
   SET outcome = :outcome, raw_status = :raw, leg_duration_s = :dur,
       settled_at = now(), updated_at = now()
 WHERE id = :id AND outcome = 'started'
"""


async def place_handoff(
    session: AsyncSession,
    *,
    engine: VoiceEngine,
    tenant_id: UUID,
    agent_id: UUID,
    engine_call_id: str,
    caller_e164: str | None,
    about: str | None,
    summary: str | None,
    outcome_reaches_agent: bool,
) -> HandoffPlacement:
    """Put this caller through to whoever is on duty, or say why not. THE one entry point.

    **THE LADDER IS ORDERED SO THAT THE CHEAPEST AND LEAST PRIVATE QUESTION IS ASKED
    FIRST.** A deployment that cannot transfer anybody never reads the roster, so a
    caller's escalation on such a platform touches no staff member's mobile number at all
    (hard rule 6), and the operator reason names the platform rather than the client's
    configuration.

    `outcome_reaches_agent` is a promise the CALLER makes to this function: that whatever
    this returns will reach the agent talking to the caller. It is a parameter rather than
    an assumption because the founder's own condition on this feature is that a declined,
    busy or unanswered handover comes BACK to the agent so the caller can be told the
    truth — and a leg placed by a caller who cannot carry that outcome is a caller bridged
    to a person while their agent apologises for failing, or held while it says nothing.
    Refusing to place is the only safe reading of "the outcome returns to the agent".
    """
    capability = available_transfer(engine)
    if capability.provider is None:
        # ASKED OF THE SEAM AND NOT OF THE PLATFORM, and the difference is which mechanism
        # is being refused. `transfer_blocked_reason` answers "can this caller reach a
        # person by ANY route", which is the publish path's and the client screen's
        # question; here the only route is ours, so an engine that runs its own in-call
        # handover is `not_our_carrier_leg` rather than unable.
        return _degraded(capability.reason or PLATFORM_CANNOT_TRANSFER)
    if not outcome_reaches_agent:
        return _degraded(OUTCOME_UNREPORTABLE)
    if not capability.provider.settles_synchronously:
        # The caller's agent is holding a turn open. A leg whose ending arrives after the
        # agent has had to say something is a leg that cannot be announced truthfully.
        return _degraded(OUTCOME_ARRIVES_LATE)
    row = (await session.execute(text(_AGENT_SQL), {"aid": agent_id})).first()
    if row is None:
        return _degraded(AGENT_UNKNOWN)
    enabled, business_hours, language = bool(row[0]), row[1], str(row[2])
    duty = await on_duty(session, agent_id=agent_id, enabled=enabled, agent_hours=business_hours)
    if duty.member is None:
        return _degraded(duty.reason or "outside_hours")

    # THE HEADER THE SECOND LEG PRESENTS. Never the caller's own number: presenting a
    # number we are not the subscriber of is CLI spoofing, and this product's regulatory
    # position is built on who the subscriber of a presented number is. `resolve_caller_id`
    # is the one resolver of that question and it already refuses an agent with two
    # registered headers rather than picking one.
    try:
        present_as = await resolve_caller_id(session, agent_id=agent_id)
    except ProblemError:
        present_as = None
    if not present_as:
        return _degraded(NO_PRESENTABLE_CLI)

    request = TransferRequest(
        call_ref=engine_call_id,
        to_e164=duty.member.phone_e164,
        present_as=present_as,
        whisper=compose_whisper(
            language=language,
            label=duty.member.label,
            caller_e164=caller_e164,
            about=about,
        ),
        accept_key=ACCEPT_KEY,
        ring_timeout_s=RING_TIMEOUT_S,
        whisper_timeout_s=WHISPER_TIMEOUT_S,
    )
    # THE ROW IS CLAIMED BEFORE THE LEG IS PLACED, AND THAT ORDER IS THE IDEMPOTENCY.
    # `handoff_attempts` is unique on (tenant, execution), so the insert is what decides
    # whether this conversation has already handed over. Placing first and recording
    # afterwards would let a retried tool call — the ordinary consequence of a timeout on
    # a network the caller is waiting on — ring a second person.
    attempt_id = await _claim(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        engine_call_id=engine_call_id,
        member_id=duty.member.id,
        destination=duty.member.phone_e164,
        reason=about,
        summary=summary,
    )
    if attempt_id is None:
        return _degraded(ALREADY_HANDED_OVER)

    try:
        started = await capability.provider.start_transfer(request)
    except (TransferContractUnverifiedError, TransferRefusedError) as exc:
        # Ids and our own reason word — never the destination, never the carrier's prose
        # (hard rule 6). The caller hears the same sentence as for every other refusal.
        log.error(
            "handoff_carrier_refused",
            extra={
                "tenant_id": str(tenant_id),
                "agent_id": str(agent_id),
                "provider": capability.provider.name,
                "error": type(exc).__name__,
            },
        )
        # The claimed row is SETTLED rather than left at `started`, which would have it
        # reporting a handover in progress for ever. `unknown` and not `unreached`: we
        # could not place the leg, which is not evidence that nobody would have answered.
        await _settle(session, attempt_id, outcome="unknown", raw=None, duration_s=None)
        return _degraded(CARRIER_REFUSED)

    if started.outcome is not None:
        await _settle(
            session,
            attempt_id,
            outcome=HANDOFF_OUTCOME_OF[started.outcome],
            raw=started.raw_status,
            duration_s=started.bridged_seconds,
        )
    log.info(
        "handoff_placed",
        extra={
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "provider": capability.provider.name,
            "outcome": started.outcome or "pending",
        },
    )
    return HandoffPlacement(
        provider_ref=started.provider_ref,
        outcome=started.outcome,
        reason=None,
        # A LEG WAS PLACED IS NOT A PERSON TOOK IT. Only `bridged` — somebody heard who was
        # calling and accepted — licenses the sentence that promises a person; a leg that
        # was declined, was busy or rang out gets the same truthful degradation as a
        # handover that never happened, because that is what the caller is in.
        say=spoken_line_for(language) if started.outcome == "bridged" else HANDOFF_DEGRADED_SAY,
        attempt_id=attempt_id,
    )


def _degraded(reason: str) -> HandoffPlacement:
    """No leg. The caller is told the truth and offered the call-back that already exists."""
    return HandoffPlacement(
        provider_ref=None, outcome=None, reason=reason, say=HANDOFF_DEGRADED_SAY
    )


async def _claim(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    engine_call_id: str,
    member_id: UUID,
    destination: E164,
    reason: str | None,
    summary: str | None,
) -> UUID | None:
    """Record that this conversation is handing over, or None if it already did.

    **A ROW EXISTS BECAUSE A LEG WAS PLACED, NOT BECAUSE ONE SUCCEEDED.** The client's
    screen, the retention sweep and a DPDP answer all read this table, and a handover that
    rang somebody's mobile and was declined is exactly the row a client needs to see.

    The columns and the conflict clause are `workers/handoff._record`'s, because it is one
    table with one meaning and the rented engine's job writes the same row.
    """
    attempt_id = uuid7()
    params: dict[str, Any] = {
        "id": attempt_id,
        "tid": tenant_id,
        "aid": agent_id,
        "ex": engine_call_id,
        "mid": member_id,
        "dest": destination,
        "now": datetime.now(UTC),
        "reason": reason,
        "summary": summary,
    }
    inserted = (await session.execute(text(_INSERT_ATTEMPT_SQL), params)).first()
    return attempt_id if inserted is not None else None


async def _settle(
    session: AsyncSession,
    attempt_id: UUID,
    *,
    outcome: str,
    raw: str | None,
    duration_s: int | None,
) -> None:
    """Close the row out. Only a row still at `started` is settled, so a retry cannot
    reopen an ending — `workers/handoff.settle_handoff` is idempotent by the same
    predicate, and it is what closes a row whose carrier reports the ending later."""
    await session.execute(
        text(_SETTLE_ATTEMPT_SQL),
        {"id": attempt_id, "outcome": outcome, "raw": raw, "dur": duration_s},
    )


__all__ = [
    "ACCEPT_KEY",
    "AGENT_UNKNOWN",
    "ALREADY_HANDED_OVER",
    "CARRIER_REFUSED",
    "HANDOFF_DEGRADED_SAY",
    "MAX_WHISPER_ABOUT",
    "NO_PRESENTABLE_CLI",
    "OUTCOME_ARRIVES_LATE",
    "OUTCOME_UNREPORTABLE",
    "RING_TIMEOUT_S",
    "WHISPER_TEMPLATES",
    "WHISPER_TIMEOUT_S",
    "HandoffPlacement",
    "compose_whisper",
    "place_handoff",
]
