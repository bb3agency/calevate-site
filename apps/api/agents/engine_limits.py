"""Refuse a publish whose text will not fit the engine's own fields — before the vendor write.

On an engine that holds our agent in its records (ThinnestAI today), the composed prompt,
the opening line and an outbound call's first utterance each land in a vendor field with a
ceiling (`engine/hosted_platform.HostedAgentLimits`). Two other responses were rejected:

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

from datetime import UTC, datetime

from calevate_shared.engine import AgentConfig, VoiceEngine, compose_engine_prompt
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.engine_minutes import (
    ATTESTED_MINUTE_ENGINES,
    BASE_RATE_KEY,
    engine_minute_is_billable,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.engine.hosted_platform import hosted_agent_limits

log = get_logger(__name__)

#: Machine codes (the last segment of the problem `type`).
PROMPT_TOO_LONG = "engine_prompt_too_long"
OPENING_TOO_LONG = "engine_greeting_too_long"
OPENING_REQUIRED = "engine_opening_required"
MINUTE_UNPRICED = "engine_minute_unpriced"


def refuse_over_engine_limits(engine: VoiceEngine, cfg: AgentConfig) -> None:
    """Raise a plain-language `ProblemError` if `cfg` cannot be held by `engine` as is."""
    limits = hosted_agent_limits(engine)
    if limits.prompt_chars is not None:
        _check_prompt(engine, cfg, limits.prompt_chars)
    opening = cfg.opening_line.strip()
    # The opening line is the agent's greeting on every direction (the adapter sends it as
    # the agent-level greeting), so its ceiling applies to every agent.
    if limits.greeting_chars is not None and len(opening) > limits.greeting_chars:
        raise _opening_too_long(engine, cfg, length=len(opening), cap=limits.greeting_chars)
    if cfg.direction == "inbound":
        return
    if limits.call_opening_chars is not None and len(opening) > limits.call_opening_chars:
        raise _opening_too_long(engine, cfg, length=len(opening), cap=limits.call_opening_chars)
    if limits.call_opening_required and not opening:
        log.warning(
            "agent_publish_refused_engine_limit",
            extra={"agent_id": cfg.agent_id, "engine": engine.name, "reason": OPENING_REQUIRED},
        )
        raise ProblemError(
            kind="business_rule",
            code=OPENING_REQUIRED,
            title="This agent needs an opening line to make calls",
            detail=(
                "On the voice platform this account uses, every outgoing call starts by "
                "speaking the agent's opening line, and this agent has none because both "
                "the AI introduction and the recording notice are switched off."
            ),
            remediation=(
                "Switch on the AI introduction or the recording notice for this agent, or "
                "set it to answer incoming calls only, then publish again."
            ),
        )


def _check_prompt(engine: VoiceEngine, cfg: AgentConfig, cap: int) -> None:
    composed = len(compose_engine_prompt(cfg))
    if composed <= cap:
        return
    script = len((cfg.system_prompt or "").strip())
    over = composed - cap
    # What the platform adds (rules, opening line, languages) is fixed by the agent's own
    # settings, so the room left for the client's script is the cap minus that.
    room = max(cap - (composed - script), 0)
    log.warning(
        "agent_publish_refused_engine_limit",
        extra={
            "agent_id": cfg.agent_id,
            "engine": engine.name,
            "reason": PROMPT_TOO_LONG,
            "composed_chars": composed,
            "cap_chars": cap,
        },
    )
    raise ProblemError(
        kind="business_rule",
        code=PROMPT_TOO_LONG,
        title="This agent's instructions are too long to publish",
        detail=(
            f"With Calevate's required rules added, this agent's instructions come to "
            f"{composed:,} characters, and the voice platform this account uses holds at "
            f"most {cap:,}. Nothing was shortened and nothing was published."
        ),
        remediation=(
            f"Shorten the agent's script by at least {over:,} characters (it can be up to "
            f"{room:,} characters long), then publish again. The required rules cannot be "
            "shortened: they are what makes the agent answer truthfully about being an AI "
            "and about recording."
        ),
    )


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
            f"The agent's opening line (the AI introduction, recording notice and memory "
            f"notice it speaks first) is {length:,} characters, and the voice platform this "
            f"account uses speaks at most {cap:,}. Nothing was shortened and nothing was published."
        ),
        remediation=(
            f"Shorten the AI introduction or the recording notice by at least "
            f"{length - cap:,} characters, then publish again."
        ),
    )


__all__ = [
    "MINUTE_UNPRICED",
    "OPENING_REQUIRED",
    "OPENING_TOO_LONG",
    "PROMPT_TOO_LONG",
    "refuse_over_engine_limits",
    "refuse_unpriced_engine",
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
    raise ProblemError(
        kind="business_rule",
        code=MINUTE_UNPRICED,
        title="Calls on this voice platform have not been priced yet",
        detail=(
            "No per-minute rate has been recorded for the voice platform this account uses, "
            "so a call on it could not be metered. Nothing was published."
        ),
        remediation=(
            "Record the platform's per-minute rate in the ops console (Platform "
            "configuration, Calling, Per-minute rates), then publish again."
        ),
    )
