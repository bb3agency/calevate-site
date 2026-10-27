"""The "Give callers time" preset (D-907): call settings for a caller who is busy on their phone.

A caller following the agent's directions on their own phone (installing an app, finding a
screen, typing a number) goes quiet for long stretches and is still on the line. The standard
settings treat that silence as an empty line: re-ask at 5 s, "are you still there?" at 8 s,
hang up at 20 s. The preset is one tap that sets, on this agent alone, the values that suit the
other case, and nothing else: each stays an ordinary call setting the owner can change after.

- ask whether they are still there after 20 s, up to 3 times, in the agent's main language;
- hang up after 120 s of silence;
- never repeat an unanswered question on its own timer, which would talk over a caller who
  is still looking for the screen the question was about;
- the longest call raised to at least 15 minutes, within what the engine accepts.

Whether the voice platform's "are you still there?" restarts its hang-up count is UNKNOWN (a
question to ThinnestAI in docs/THINNEST-INTEGRATION.md; its Voice guide says only that the
count starts again when the CALLER says anything, thinnest-findings/mirror/snapshots/
2026-10-19/pages/channels/voice.md:691-699). The values assume it does not, so the 120 s
are counted from the caller's last words: that is 40 s past 20 s x (3 + 1), the floor the
platform holds the hang-up to so the last question gets an answer window (same page,
:666-669). If it does restart, the call only runs longer.

The phrase is the one setting with words. It is written for each language an agent can be
stored in and the agent's main language picks it; the owner may change it like any other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_handling
from apps.api.agents.call_handling import AgentCallHandling, ResolvedSettings
from apps.api.agents.live_apply import queue_live_apply
from apps.api.agents.models import REASK_NEVER, is_published
from apps.api.agents.service import call_cap_max_s, effective_call_cap
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

NUDGE_AFTER_S: Final = 20
NUDGE_COUNT: Final = 3
END_AFTER_SILENCE_S: Final = 120
REASK_AFTER_MS: Final = REASK_NEVER
#: Fifteen minutes: a guided install with a login and a first entry runs past the platform's
#: 10-minute default.
CALL_CAP_S: Final = 900

#: "Can you see it?" in each language an agent can be stored in (`agents/languages.
#: BUILT_LANGUAGES`; `tests/patient_caller_test.py` holds the keys to it). The Telugu line is
#: the founder's (RytuKhata brief, 27 Oct 2026); the others are spoken forms of the same short
#: question, not yet reviewed by a native speaker, and are the owner's to change.
NUDGE_PHRASES: Final[dict[str, str]] = {
    "te-IN": "కనిపించిందా అండి?",
    "hi-IN": "दिख गया जी?",
    "en-IN": "Can you see it?",
    "ta-IN": "தெரிகிறதா?",
    "kn-IN": "ಕಾಣಿಸ್ತಾ?",
    "ml-IN": "കാണുന്നുണ്ടോ?",
    "mr-IN": "दिसलं का?",
}


def nudge_phrase_for(language: str) -> str:
    """The preset's question in `language`; '' (the platform's own "are you still there?" in
    the caller's language) for a language with none."""
    return NUDGE_PHRASES.get(language, "")


def preset_changes(language: str) -> dict[str, object]:
    """The call settings the preset writes on the agent, as `set_agent_call_handling` takes
    them."""
    return {
        "nudge_after_seconds": NUDGE_AFTER_S,
        "nudge_count": NUDGE_COUNT,
        "nudge_phrase": nudge_phrase_for(language),
        "end_after_silence_seconds": END_AFTER_SILENCE_S,
        "reask_after_ms": REASK_AFTER_MS,
    }


def preset_call_cap_s() -> int:
    """The longest call the preset asks for, within the engine's ceiling."""
    return min(CALL_CAP_S, call_cap_max_s())


def is_applied(resolved: ResolvedSettings, call_cap_s: int) -> bool:
    """Do the settings in force match the preset? The question is the owner's to word, so it
    is not compared; a longer call than the preset's still matches."""
    v = resolved.values
    return (
        v.nudge_after_seconds == NUDGE_AFTER_S
        and v.nudge_count == NUDGE_COUNT
        and v.end_after_silence_seconds == END_AFTER_SILENCE_S
        and v.reask_after_ms == REASK_AFTER_MS
        and call_cap_s >= preset_call_cap_s()
    )


@dataclass(frozen=True, slots=True)
class PatientCaller:
    """The preset as it applies to one agent, and whether its values are in force."""

    applied: bool
    nudge_phrase: str
    call_cap_s: int


_AGENT: Final = (
    "SELECT language_primary, max_call_duration_s, status, engine_agent_ref FROM agents "
    "WHERE id = :aid AND deleted_at IS NULL"
)


async def read_patient_caller(session: AsyncSession, state: AgentCallHandling) -> PatientCaller:
    """The preset for the agent whose call settings are `state`. RLS scopes the read."""
    row = (await session.execute(text(_AGENT), {"aid": state.agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    cap = effective_call_cap(row[1])
    return PatientCaller(
        applied=is_applied(state.resolved, cap),
        nudge_phrase=nudge_phrase_for(str(row[0])),
        call_cap_s=preset_call_cap_s(),
    )


@dataclass(frozen=True, slots=True)
class PatientCallerApplied:
    state: AgentCallHandling
    #: The call settings that moved.
    moved: tuple[str, ...]
    #: The agent's longest call before and after, in seconds.
    call_cap_before_s: int
    call_cap_after_s: int


async def apply_patient_caller(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> PatientCallerApplied:
    """Write the preset on one agent in the caller's transaction.

    The call settings go through `set_agent_call_handling`, which locks the row and queues the
    agent's live apply. The longest call is only ever raised here, never lowered: an owner who
    chose 20 minutes keeps them. It rides the same live apply rather than
    `publishing.set_call_cap`'s publish in the request, because a longer cap that reaches the
    line a moment after the save ends calls sooner, never later, than the screen says."""
    row = (await session.execute(text(_AGENT + " FOR UPDATE"), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    language, own_cap, status, ref = str(row[0]), row[1], row[2], row[3]
    state, moved = await call_handling.set_agent_call_handling(
        session, tenant_id=tenant_id, agent_id=agent_id, changes=preset_changes(language)
    )
    before = effective_call_cap(own_cap)
    after = max(before, preset_call_cap_s())
    if after != before:
        await session.execute(
            text(
                "UPDATE agents SET max_call_duration_s = :cap, updated_at = now() WHERE id = :aid"
            ),
            {"cap": after, "aid": agent_id},
        )
        if is_published(status, ref):
            await queue_live_apply(
                session, scope="agent", tenant_id=tenant_id, agent_id=agent_id, reason="call_cap"
            )
    log.info(
        "agent_patient_caller_applied",
        extra={
            "agent_id": str(agent_id),
            "changed": list(moved),
            "cap_before_s": before,
            "cap_after_s": after,
        },
    )
    return PatientCallerApplied(
        state=state, moved=moved, call_cap_before_s=before, call_cap_after_s=after
    )


__all__ = [
    "CALL_CAP_S",
    "END_AFTER_SILENCE_S",
    "NUDGE_AFTER_S",
    "NUDGE_COUNT",
    "NUDGE_PHRASES",
    "REASK_AFTER_MS",
    "PatientCaller",
    "PatientCallerApplied",
    "apply_patient_caller",
    "is_applied",
    "nudge_phrase_for",
    "preset_call_cap_s",
    "preset_changes",
    "read_patient_caller",
]
