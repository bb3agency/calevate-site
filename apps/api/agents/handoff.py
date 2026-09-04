"""THE HUNT LIST: who takes a call the agent hands over, and who is on duty right now.

D-533. The founder's question was "if the call is to be forwarded to a real human then how
is it handled, and to which number?" — with four decisions: one ordered hunt list rather
than departments, a spoken whisper to the human before bridging, try the next number then
fall back to a call-back, and never transfer outside business hours.

**TWO OF THOSE FOUR ARE NOT AVAILABLE ON THIS ENGINE, AND THIS MODULE IS SHAPED BY WHICH
TWO.** The evidence is in `calevate_shared.engine.HandoffSpec` and
`docs/evidence/handoff-warm-transfer.md`; the summary a reader of THIS file needs:

* **The whisper is not achievable.** Playing a message to the called party before bridging
  needs control of the caller's telephony leg — Plivo's `<Dial confirmSound=…>` is the
  shape (VERIFIED-VENDOR-SDK: `plivo/plivo-python@master`, `plivo/xml/DialElement.py`,
  `confirm_sound`/`confirm_key`/`confirm_timeout`; the live-call redirect is
  `plivo/resources/calls.py:299-338`, `POST /Call/{uuid}` with `legs` + `aleg_url`, read
  4 Sep 2026). We hold NO telephony credential: no Plivo or Exotel client, no auth id, no
  auth token, and `campaigns/provisioning.PROVISIONING_IMPLEMENTED` is False. The engine
  places the leg on the account connected to IT. So what reaches the person is a message on
  their phone as it rings, not a voice in their ear — the founder's own stated second
  choice — and this module never pretends otherwise.
* **In-call failover down the list is not achievable.** The engine latches after the first
  handover and answers every later attempt with "Call transfer already in progress"
  (VERIFIED-OSS: `bolna-ai/bolna@cd2e192`, `bolna/agent_manager/task_manager.py:3116-3126`,
  read 4 Sep 2026), so publishing one tool per member would produce an agent that silently
  tries exactly one of them.

**SO THE HUNT LIST IS RESOLVED BEFORE THE CALL RATHER THAN DURING IT**, and that is the
one honest reading of "tried in turn" this platform supports: `on_duty` walks the roster in
order and returns the FIRST member who is active and within their hours, that number is
published as the agent's single handoff destination, and a handover that reaches nobody
becomes a call-back in the queue that already exists (`callbacks/service.py`). The order is
still the product — position 0 is who normally answers — it is just honoured by choosing
rather than by ringing.

**DECISION 4 IS ENFORCED BY ABSENCE, WHICH IS THE ONLY PLACE IT CAN BE ENFORCED.** The
destination is fixed when the agent is published and no instruction reaches a running call,
so "do not transfer after 9pm" written into a prompt is a request to a model. Outside every
member's hours `on_duty` returns a verdict with no member, `publish_agent` sends
`handoff=None`, the adapter emits no transfer tool at all, and the model has nothing to
fire. Nobody's personal mobile can ring at 11pm because the agent does not know the number.

**UNKNOWN HOURS MEAN NOBODY IS ON DUTY, and that is deliberate.** `is_after_hours` is
tri-valued and its third answer is "we do not know" — an agent with no `business_hours`
recorded, or a day nobody filled in. FLOWS §3's default for the AGENT is 24/7, and this
takes the opposite default for the same reason it takes any default at all: the thing at
stake is not whether an AI answers the phone at 3am, it is whether a named person's private
mobile rings. The client is told exactly this, with the fix ("record your opening hours"),
rather than being left with a feature that is quietly off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.engine import E164, HandoffSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.business_hours import is_after_hours
from apps.api.core.settings import get_settings

#: How many people one agent may hand a call to. A BOUNDED LIST for the reason every
#: bounded list in this repo exists: the roster is rewritten wholesale on every edit, it is
#: read on every publish, and a client pasting a contact export must be refused at the
#: boundary rather than turning one publish into a thousand-row scan. Ten is the intake
#: wizard's own limit for the same list (`admin/intake.IntakeFacts.escalation_contacts`),
#: kept identical so the two screens cannot disagree about what a roster is.
MAX_HANDOFF_MEMBERS: Final = 10

#: WHEN the agent should hand over, when the client has written nothing of their own.
#:
#: The LLM reads this to decide, so it names the caller's own words rather than a category
#: — the vendor's guidance is that a vague description is an unreliable trigger
#: (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/tool-calling/transfer-calls.md`,
#: "Be Specific"). It deliberately does NOT say "transfer if you cannot answer": that turns
#: every gap in the knowledge base into somebody's phone ringing.
HANDOFF_TRIGGER_DEFAULT: Final = (
    "Hand the call to a person when the caller asks to speak to a human, a manager or the "
    "owner, when they are upset or say they have already tried to resolve this, or when "
    "they raise something about money, a complaint or safety that you have not been given "
    "an answer for. Do not hand over merely because you do not know something."
)

#: The language every template table here falls back to, and it is `compliance/disclosure.
#: DEFAULT_LANGUAGE`'s value SPELLED AGAIN rather than imported — for the reason
#: `business_hours.py` re-spells `DAYS`, verified rather than assumed: importing that
#: module from here closes an import cycle (`agents/service` → this → `compliance/
#: disclosure` → `compliance/optout` → `compliance/service` → `agents/service`), which is
#: the exact loop `agents/assist_leg.py` documents and which `import apps.api.main` refuses
#: outright. English rather than Telugu for that module's stated reason: a template
#: rendered in a language the business does not speak is worse than one in the lingua
#: franca.
_FALLBACK_LANGUAGE: Final = "en-IN"

#: WHAT THE CALLER HEARS while the handover is placed, per language.
#:
#: Composed here rather than typed by a client, for `compliance/disclosure.py`'s reason:
#: this sentence is spoken on every escalated call and the wording is a product decision,
#: not a per-agent field. It promises only what this platform can keep — that somebody is
#: being rung — and never "they know why you are calling", which would be a claim about a
#: whisper that does not exist.
HANDOFF_SPOKEN_TEMPLATES: Final[dict[str, str]] = {
    "te-IN": "Sare, nenu ippudu maa team lo okarini kaluputunnanu. Konchem wait cheyandi.",
    "hi-IN": "Theek hai, main aapko hamari team se jod raha hoon. Kripya thoda intezaar karein.",
    "en-IN": "Alright, I am putting you through to someone from our team now. Please hold.",
}

#: Why nobody is on duty. Each value is a sentence a CLIENT is shown and an operator
#: metric label, so the set is closed and each member has an authored remediation below.
_UNAVAILABLE_REASONS: Final[dict[str, str]] = {
    "disabled": (
        "Handing calls to a person is switched off for this agent. Turn it on to start "
        "sending callers to your team."
    ),
    "no_members": (
        "Nobody is on this agent's handover list, so there is no one to put a caller "
        "through to. Add the people who can take a call."
    ),
    "none_active": (
        "Everyone on the handover list is switched off. Switch at least one person back "
        "on, or callers asking for a person will be offered a call-back instead."
    ),
    "hours_unknown": (
        "We do not know when your business is open, so we will not ring anyone's mobile. "
        "Record your opening hours — or give each person on the list their own hours — "
        "and handovers will start working."
    ),
    "outside_hours": (
        "Nobody on the handover list is available right now, so callers asking for a "
        "person are offered a call-back instead."
    ),
}


@dataclass(frozen=True)
class RosterMember:
    """One row of the roster, as every reader here uses it."""

    id: UUID
    position: int
    label: str
    #: PII (hard rule 6). Nothing in this module logs it.
    phone_e164: E164
    hours: dict[str, Any] | None
    active: bool
    note: str | None


@dataclass(frozen=True)
class OnDuty:
    """WHO would take a call handed over at this instant, and if nobody, why not.

    A VERDICT RATHER THAN AN `Optional[RosterMember]`, and the reason is the screen. "No
    handover destination" has five distinct causes and four of them are things the client
    can fix in under a minute; returning None would collapse them into one silence and
    leave a client with a feature that does not work and no sentence explaining it. It is
    the shape `DispatchDecision` already uses for the same problem on the dial path.
    """

    member: RosterMember | None
    #: `None` when a member was found; otherwise a key of `_UNAVAILABLE_REASONS`.
    reason: str | None

    @property
    def remediation(self) -> str | None:
        """What the client should do about it, in one sentence they can act on."""
        return None if self.reason is None else _UNAVAILABLE_REASONS[self.reason]


_ROSTER_SQL = (
    "SELECT id, position, label, phone_e164, hours, active, note "
    "FROM agent_handoff_members WHERE agent_id = :aid ORDER BY position"
)


async def roster(session: AsyncSession, *, agent_id: UUID) -> list[RosterMember]:
    """This agent's roster, in order. RLS scopes it — a wrong id is zero rows.

    No `WHERE tenant_id` and that is not an omission: the policy matches on `tenant_id`
    and a second, weaker expression of the same isolation is what `agents/assist_leg.py`
    argues against at length.
    """
    rows = (await session.execute(text(_ROSTER_SQL), {"aid": agent_id})).all()
    return [
        RosterMember(
            id=row[0],
            position=row[1],
            label=row[2],
            phone_e164=row[3],
            hours=row[4],
            active=row[5],
            note=row[6],
        )
        for row in rows
    ]


def resolve_on_duty(
    members: list[RosterMember],
    *,
    enabled: bool,
    agent_hours: dict[str, Any] | None,
    at: datetime,
) -> OnDuty:
    """The first member who can be rung at `at`, or the reason nobody can.

    PURE, and taking the roster as a value rather than a session, so the rule is testable
    against a clock instead of against a database and so the publish path and the client's
    screen cannot reach two different answers from the same rows.

    A member with their OWN `hours` is judged on those; one with none inherits the agent's.
    Inheriting is what a three-person shop wants — the roster is "who is around when we are
    open" — and per-member hours are what a rota needs.

    ORDERED, ALWAYS, AND THE ORDER IS THE ONLY FAILOVER THIS ENGINE ALLOWS. Position 0 is
    who normally answers; a later position is reached because the earlier ones are off
    duty or switched off, never because an earlier one did not pick up (see the module
    docstring).
    """
    if not enabled:
        return OnDuty(member=None, reason="disabled")
    if not members:
        return OnDuty(member=None, reason="no_members")
    active = [m for m in members if m.active]
    if not active:
        return OnDuty(member=None, reason="none_active")
    # `unknown` is tracked separately from `outside` so the client is told which of the two
    # they are in: one is fixed by recording opening hours, the other by waiting until
    # morning, and a single "nobody is available" sentence would send half of them looking
    # in the wrong place.
    saw_unknown = False
    for member in active:
        verdict = is_after_hours(member.hours if member.hours else agent_hours, at)
        if verdict is False:
            return OnDuty(member=member, reason=None)
        if verdict is None:
            saw_unknown = True
    return OnDuty(member=None, reason="hours_unknown" if saw_unknown else "outside_hours")


async def on_duty(
    session: AsyncSession,
    *,
    agent_id: UUID,
    enabled: bool,
    agent_hours: dict[str, Any] | None,
    at: datetime | None = None,
) -> OnDuty:
    """`resolve_on_duty` over this agent's stored roster. THE one entry point for a publish.

    `at` defaults to now in UTC — aware, because `is_after_hours` refuses a naive instant
    rather than guessing between two timezones 5h30m apart.
    """
    members = await roster(session, agent_id=agent_id)
    return resolve_on_duty(
        members, enabled=enabled, agent_hours=agent_hours, at=at or datetime.now(UTC)
    )


async def spec_for(
    session: AsyncSession, agent: dict[str, Any], *, at: datetime | None = None
) -> tuple[HandoffSpec | None, OnDuty]:
    """THE one resolver every publish path uses: `(what to publish, why)`.

    Returns the verdict alongside the spec deliberately. Three callers need this — the
    publish, the experiment-arm publish, and the drift comparison — and each of them
    would otherwise re-derive "so who is on duty" from the spec, which cannot answer it:
    `None` means five different things and only the verdict tells them apart.

    **THE DRIFT PATH IS WHY THIS IS SHARED RATHER THAN INLINED IN `publish_agent`.** The
    half-hourly sweep compares what the engine holds against what a publish RIGHT NOW
    would send; if it built the destination any other way, a sweep run at 9pm would score
    an agent published at 3pm as drifted for the entirely correct reason that the roster
    has gone off duty. It is the same rule at both ends or it is a false alarm generator.

    `agent` is an `agents/service.AgentRow`, spelled loosely here for the reason
    `business_hours.py` duplicates `DAYS`: this module is on the read side of the publish
    and importing `agents/service` would close an import cycle through the opt-out chain
    (`assist_leg.py` documents the same loop).
    """
    duty = await on_duty(
        session,
        agent_id=agent["id"],
        enabled=bool(agent["handoff_enabled"]),
        agent_hours=agent["business_hours"],
        at=at,
    )
    spec = handoff_spec(
        duty,
        trigger=agent["handoff_trigger"],
        language=str(agent["language_primary"]),
        brief_url=brief_url(),
    )
    return spec, duty


def brief_url() -> str:
    """OUR endpoint, notified the moment a handover fires.

    **voice-runtime, NOT apps/api, and the reasoning is `action_tool_url`'s in reverse.**
    That function points at `apps/api` because executing an action makes a synchronous
    external call and a credential decrypt, which hard rule 3 keeps off the receiver. This
    does the opposite: it accepts a notification, acks and defers, which is exactly what
    the receiver is for and exactly what `apps/api` is the wrong place for. It is also on
    the caller's audio path in the sense that matters — the engine fires it mid-call, a
    step before it places the leg — so the 500ms discipline applies.

    `webhook_base_url` is that origin: the same one `_to_config` builds the post-call
    `webhook_url` from, because both are served by the same deployable.
    """
    settings = get_settings()
    base = settings.webhook_base_url.rstrip("/")
    return f"{base}/tools/v1/{settings.engine}/handoff"


def handoff_spec(
    duty: OnDuty, *, trigger: str | None, language: str, brief_url: str | None
) -> HandoffSpec | None:
    """The publish-time value, or None when nobody is on duty.

    None is the whole of decision 4's enforcement: the adapter emits no transfer tool for
    it, so the model has no tool to fire (see the module docstring). Every caller passes
    this straight into `AgentConfig.handoff`; nothing else constructs a `HandoffSpec`.
    """
    if duty.member is None:
        return None
    return HandoffSpec(
        destination_e164=duty.member.phone_e164,
        trigger=(trigger or "").strip() or HANDOFF_TRIGGER_DEFAULT,
        spoken_line=HANDOFF_SPOKEN_TEMPLATES.get(
            language, HANDOFF_SPOKEN_TEMPLATES[_FALLBACK_LANGUAGE]
        ),
        brief_url=brief_url,
    )


__all__ = [
    "HANDOFF_SPOKEN_TEMPLATES",
    "HANDOFF_TRIGGER_DEFAULT",
    "MAX_HANDOFF_MEMBERS",
    "OnDuty",
    "RosterMember",
    "brief_url",
    "handoff_spec",
    "on_duty",
    "resolve_on_duty",
    "roster",
    "spec_for",
]
