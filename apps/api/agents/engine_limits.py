"""Refuse a publish whose text will not fit the engine's own fields — before the vendor write.

On an engine that holds our agent in its records (ThinnestAI today), the composed prompt,
the first words (notices, then opening line) and an outbound call's first utterance each
land in a vendor field with a ceiling (`engine/hosted_platform.HostedAgentLimits`). Two
other responses were rejected:

* **Truncating to fit.** `compose_engine_prompt` puts the confidentiality rule and hard
  rule 5's truthful-answer block LAST, so the characters a cut removes are exactly the ones
  no client may lose. A shortened opening line drops a disclosure mid-sentence.
* **Letting the vendor refuse.** Its 400 arrives after `create_agent` may already have
  happened for a sibling field, reads as a dependency failure an operator retries, and
  names a vendor field the client has never seen.

So the check runs on the config `publish_agent` is about to send, and the refusal says how
many characters to cut from the part the client wrote. An engine with no limits answers at
once, which keeps every other engine's publish path exactly as it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from calevate_shared.call_script import opening_line_of
from calevate_shared.engine import (
    AgentConfig,
    DisclosurePosture,
    VoiceEngine,
    compose_opening_line,
    join_first_words,
)
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompt_size import PromptSize, measure
from apps.api.billing.engine_minutes import (
    ATTESTED_MINUTE_ENGINES,
    BASE_RATE_KEY,
    engine_minute_is_billable,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine.capabilities import engine_capabilities
from apps.api.engine.hosted_platform import engine_greeting, hosted_agent_limits

log = get_logger(__name__)

#: Machine codes (the last segment of the problem `type`).
PROMPT_TOO_LONG = "engine_prompt_too_long"
OPENING_TOO_LONG = "engine_greeting_too_long"
OPENING_REQUIRED = "engine_opening_required"
#: A notice switch refused because the notice would not fit after the opening line (D-846).
NOTICE_NEEDS_ROOM = "opening_line_too_long_for_notice"
MINUTE_UNPRICED = "engine_minute_unpriced"
#: The alarm that tells the operator a client was refused for want of a minute rate.
PUBLISH_REFUSED_UNPRICED_ALARM = "engine_publish_refused_unpriced"


def greeting_limit(engine: VoiceEngine, direction: str) -> int | None:
    """The most characters `engine` speaks first for an agent of `direction`, or None.

    The greeting ceiling on every direction, and on one that dials also the per-call
    opening's, which carries the same text."""
    limits = hosted_agent_limits(engine)
    caps = [limits.greeting_chars]
    if direction != "inbound":
        caps.append(limits.call_opening_chars)
    known = [cap for cap in caps if cap is not None]
    return min(known) if known else None


def greeting_chars(engine: VoiceEngine, *, notices: str, opening: str) -> int:
    """The length of what `engine` holds as the greeting for these notices and opening line.

    `join_first_words` is `compose_first_utterance` taken apart, so a screen measuring an
    agent's stored lines and the publish measuring its config count the same text."""
    return len(
        engine_greeting(engine, notices=notices, first_words=join_first_words(notices, opening))
    )


def opening_room(engine: VoiceEngine, *, notices: str, direction: str) -> int | None:
    """How many characters the opening line may have after `notices` and still be spoken.

    None where nothing limits it: no ceiling, or an engine whose greeting holds the notices
    alone. Negative when the notices by themselves are over."""
    limit = greeting_limit(engine, direction)
    if limit is None or not hosted_agent_limits(engine).greeting_is_first_words:
        return None
    # Measured with a one-character line, so the separator between notices and line counts.
    return limit - (greeting_chars(engine, notices=notices, opening="x") - 1)


@dataclass(frozen=True, slots=True)
class GreetingBudget:
    """How the agent's first words sit against the engine's ceiling (D-846): the opening
    line's length now, and the room it has with the notices on now and with each notice
    switch turned on, so a screen can count down before anything is refused."""

    limit: int
    opening_chars: int
    opening_room: int
    opening_room_with_ai_disclosure: int
    opening_room_with_recording_notice: int
    opening_room_with_caller_memory: int


def greeting_budget(
    engine: VoiceEngine, *, posture: DisclosurePosture, opening: str, direction: str
) -> GreetingBudget | None:
    """The budget for an agent with this posture and opening line, or None where the engine
    sets no ceiling on what the opening line may be."""
    recorded = engine_capabilities(engine).records_audio

    def room(switch: str | None = None) -> int | None:
        turned = posture if switch is None else posture.model_copy(update={switch: True})
        notices = compose_opening_line(turned, call_is_recorded=recorded)
        return opening_room(engine, notices=notices, direction=direction)

    limit = greeting_limit(engine, direction)
    now = room()
    # Every room is None together: each is None exactly when the engine sets no ceiling.
    if limit is None or now is None:
        return None
    return GreetingBudget(
        limit=limit,
        opening_chars=len(opening.strip()),
        opening_room=now,
        opening_room_with_ai_disclosure=room("ai_disclosure_enabled") or 0,
        opening_room_with_recording_notice=room("recording_notice_enabled") or 0,
        opening_room_with_caller_memory=room("caller_memory_enabled") or 0,
    )


def refuse_notice_without_room(
    engine: VoiceEngine,
    *,
    agent_id: str,
    direction: str,
    notices: str,
    opening: str,
    cause: str,
) -> None:
    """Refuse a switch that adds a notice the greeting has no room for, before it is saved.

    Without this the switch is saved and the refusal arrives from the publish as
    `engine_greeting_too_long`, which names neither the switch nor the way back. The publish
    check stays the final guard; this only says the same thing earlier, about its cause.
    `cause` is the sentence naming what the switch adds."""
    limit = greeting_limit(engine, direction)
    if limit is None:
        return
    length = greeting_chars(engine, notices=notices, opening=opening)
    if length <= limit:
        return
    log.info(
        "agent_notice_refused_no_room",
        extra={"agent_id": agent_id, "engine": engine.name, "over_chars": length - limit},
    )
    raise ProblemError(
        kind="business_rule",
        code=NOTICE_NEEDS_ROOM,
        title="Shorten the opening line to switch this on",
        detail=(
            f"{cause} With it, what the agent says first would be {length:,} characters, and "
            f"at most {limit:,} can be spoken there. Nothing was changed."
        ),
        remediation=(
            f"Shorten the agent's opening line by at least {length - limit:,} characters, "
            "then switch this on again."
        ),
    )


def refuse_opening_over_limit(
    engine: VoiceEngine, *, agent_id: str, direction: str, notices: str, opening: str
) -> None:
    """Refuse a new opening line that would not fit after `notices`, before it is saved."""
    limit = greeting_limit(engine, direction)
    if limit is None:
        return
    length = greeting_chars(engine, notices=notices, opening=opening)
    if length <= limit:
        return
    log.info(
        "agent_opening_refused_no_room",
        extra={"agent_id": agent_id, "engine": engine.name, "over_chars": length - limit},
    )
    raise ProblemError(
        kind="business_rule",
        code=OPENING_TOO_LONG,
        title="This opening line is too long",
        detail=(
            f"With the notices said after it, what the agent says first would be "
            f"{length:,} characters, and at most {limit:,} can be spoken there. Nothing was "
            "saved."
        ),
        remediation=f"Shorten it by at least {length - limit:,} characters.",
    )


def refuse_over_engine_limits(engine: VoiceEngine, cfg: AgentConfig) -> None:
    """Raise a plain-language `ProblemError` if `cfg` cannot be held by `engine` as is."""
    limits = hosted_agent_limits(engine)
    if limits.prompt_chars is not None:
        _check_prompt(engine, cfg, limits.prompt_chars)
    # The text the engine holds as the greeting on every direction: on ThinnestAI the
    # opening line and then the notices switched on (D-861), so the ceiling and the
    # outbound requirement apply to both together.
    length = greeting_chars(
        engine, notices=cfg.opening_line, opening=opening_line_of(cfg.system_prompt)
    )
    limit = greeting_limit(engine, cfg.direction)
    if limit is not None and length > limit:
        raise _opening_too_long(engine, cfg, length=length, cap=limit)
    if cfg.direction == "inbound":
        return
    if limits.call_opening_required and not length:
        log.warning(
            "agent_publish_refused_engine_limit",
            extra={"agent_id": cfg.agent_id, "engine": engine.name, "reason": OPENING_REQUIRED},
        )
        raise ProblemError(
            kind="business_rule",
            code=OPENING_REQUIRED,
            title="This agent needs an opening line to make calls",
            detail=(
                "Every outgoing call starts with the agent's opening line, and this agent's "
                "script has none written."
            ),
            remediation=(
                "Write an opening line in the agent's script, or set the agent to answer "
                "incoming calls only, then publish again."
            ),
        )


class PromptTooLongError(ProblemError):
    """`engine_prompt_too_long`, carrying the measurement so a live-apply failure and a
    screen can say how far over and which parts are longest (counts only)."""

    def __init__(self, size: PromptSize) -> None:
        self.size = size
        longest = ", ".join(f"{p.label.lower()} {p.chars:,}" for p in size.longest_script_parts())
        super().__init__(
            kind="business_rule",
            code=PROMPT_TOO_LONG,
            title="This script is too long for the calling system",
            detail=too_long_sentence(size),
            remediation=(
                "Shorten the longest parts of your script"
                + (f" ({longest} characters)" if longest else "")
                + ", or move product and price details into Knowledge, which the agent "
                "searches. The rules Calevate adds cannot be shortened: they make the agent "
                "answer truthfully about being an AI and about recording."
            ),
        )


def too_long_sentence(size: PromptSize) -> str:
    """The one sentence every surface shows for a script over the box."""
    return too_long_message(size.over)


def too_long_message(over: int) -> str:
    return (
        f"Your script is {over:,} characters too long for the calling system; "
        "shorten it to put it live."
    )


def _check_prompt(engine: VoiceEngine, cfg: AgentConfig, cap: int) -> None:
    size = measure(cfg, cap)
    if size.fits:
        return
    log.warning(
        "agent_publish_refused_engine_limit",
        extra={
            "agent_id": cfg.agent_id,
            "engine": engine.name,
            "reason": PROMPT_TOO_LONG,
            "composed_chars": size.total,
            "cap_chars": cap,
        },
    )
    raise PromptTooLongError(size)


def _opening_too_long(
    engine: VoiceEngine, cfg: AgentConfig, *, length: int, cap: int
) -> ProblemError:
    log.warning(
        "agent_publish_refused_engine_limit",
        extra={"agent_id": cfg.agent_id, "engine": engine.name, "reason": OPENING_TOO_LONG},
    )
    return ProblemError(
        kind="business_rule",
        code=OPENING_TOO_LONG,
        title="This agent's opening line is too long to publish",
        detail=(
            f"What the agent says first (any notices switched on, then its opening line) is "
            f"{length:,} characters, and at most {cap:,} can be spoken there. Nothing was "
            "shortened and nothing was published."
        ),
        remediation=(
            f"Shorten the opening line in the agent's script by at least {length - cap:,} "
            "characters, then publish again."
        ),
    )


__all__ = [
    "MINUTE_UNPRICED",
    "NOTICE_NEEDS_ROOM",
    "OPENING_REQUIRED",
    "OPENING_TOO_LONG",
    "PROMPT_TOO_LONG",
    "GreetingBudget",
    "PromptTooLongError",
    "greeting_budget",
    "greeting_chars",
    "greeting_limit",
    "opening_room",
    "refuse_notice_without_room",
    "refuse_opening_over_limit",
    "refuse_over_engine_limits",
    "refuse_unpriced_engine",
    "too_long_message",
    "too_long_sentence",
]


async def refuse_unpriced_engine(session: AsyncSession, engine: VoiceEngine) -> None:
    """Refuse to publish on an engine metered by the minute when its base minute is unpriced.

    Hard rule 7: an engine that reports no call cost (`billing/engine_minutes.py`) can only
    meter a minute at an attested rate, and a live agent on it would place calls nobody can
    price. `engine_minute_is_billable` is the one door; an engine not metered this way
    answers at once without a query.
    """
    if engine.name not in ATTESTED_MINUTE_ENGINES:
        return
    if await engine_minute_is_billable(
        session, engine=engine.name, rate_key=BASE_RATE_KEY, at=datetime.now(UTC)
    ):
        return
    log.warning(
        "agent_publish_refused_engine_limit",
        extra={"engine": engine.name, "reason": MINUTE_UNPRICED},
    )
    # The operator's remedy travels on the alert. The refusal itself is read by a CLIENT
    # publishing their own agent, who cannot open the ops console.
    alert(
        "CORE_LOGIC",
        PUBLISH_REFUSED_UNPRICED_ALARM,
        detail=(
            "A publish was refused because the voice platform's base per-minute rate is not "
            "recorded. Record it in the ops console (Platform configuration, Voice engine, "
            "Per-minute rates), then ask the client to publish again."
        ),
        engine=engine.name,
    )
    raise ProblemError(
        kind="business_rule",
        code=MINUTE_UNPRICED,
        title="Calling isn't priced on our side yet",
        detail="Calling isn't priced on our side yet. We've been told. Nothing was published.",
        remediation="Publish again once we let you know it is fixed.",
    )
