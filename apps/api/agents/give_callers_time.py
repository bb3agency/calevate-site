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

The phrase is the one setting with words. "Can you see it?" is written for each language an
agent can be stored in, the agent's main language picks it, and it is set only on an agent
whose callers follow along on a screen (D-906); any other agent keeps the platform's own
"are you still there?" in the caller's language (D-915). The platform holds one question per
agent (`voice.nudgePhrase`), so an agent that also answers in other languages asks it in its
main language whatever the caller speaks. The owner may change it like any other setting.

Switching "caller follows along on a screen" on applies the preset to every setting the
owner has left at Calevate's default (`apply_where_default`); the button applies it to all.

A campaign or inbound line (a holder) carries the preset on its own engine agent when its
script asks the caller to act on their phone (founder, 25 Nov 2026): a step-by-step list, or
a line that gives an on-screen action (`script_lint.asks_caller_to_act`). Without it a silent
caller is hung up on after about 30 s. It is laid over the settings the holder's agent and
account leave at Calevate's level, at every publish of the holder, so it never touches the
agent's own calls or a value the owner chose, and it follows the script as it changes. The
owner may switch it off or on for that holder (`campaigns.give_callers_time`,
`inbound_lines.give_callers_time`); that choice is kept and the script no longer decides.
It is per holder rather than the agent's `caller_has_screen` because one agent's campaigns
can differ (one guides an install, another only books). The holder's screen frame follows
its script the same way (`holder_has_screen`), so "Can you see it?" is asked on a holder
whose script guides the caller's phone and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from calevate_shared import spoken_lines
from calevate_shared.call_script import CallScript
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_handling
from apps.api.agents.call_handling import AgentCallHandling, CallSettings, ResolvedSettings
from apps.api.agents.live_apply import queue_live_apply
from apps.api.agents.models import REASK_NEVER, is_published
from apps.api.agents.script_lint import asks_caller_to_act
from apps.api.agents.service import call_cap_max_s, effective_call_cap
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

if TYPE_CHECKING:
    from apps.api.agents.mistake_fixes import Holder

log = get_logger(__name__)

NUDGE_AFTER_S: Final = 20
NUDGE_COUNT: Final = 3
END_AFTER_SILENCE_S: Final = 120
REASK_AFTER_MS: Final = REASK_NEVER
#: Fifteen minutes: a guided install with a login and a first entry runs past the platform's
#: 10-minute default.
CALL_CAP_S: Final = 900

#: "Can you see it?" per language: the founder's lines (`calevate_shared/spoken_lines.json`, entry
#: `still_there`, A-12). A language with no line there gets none, which leaves the
#: platform's own "are you still there?" in the caller's language (D-915).
NUDGE_PHRASES: Final[dict[str, str]] = spoken_lines.lines("still_there")


def nudge_phrase_for(language: str, *, caller_has_screen: bool) -> str:
    """The preset's question in `language` for an agent whose callers follow along on a
    screen (D-906); '' otherwise, and for a language with none, which leaves the platform's
    own "are you still there?" in the caller's language (D-915). "Can you see it?" asked of
    a caller fetching a document or thinking it over is the wrong question."""
    return NUDGE_PHRASES.get(language, "") if caller_has_screen else ""


def preset_changes(language: str, *, caller_has_screen: bool) -> dict[str, object]:
    """The call settings the preset writes on the agent, as `set_agent_call_handling` takes
    them."""
    return {
        "nudge_after_seconds": NUDGE_AFTER_S,
        "nudge_count": NUDGE_COUNT,
        "nudge_phrase": nudge_phrase_for(language, caller_has_screen=caller_has_screen),
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
class GiveCallersTime:
    """The preset as it applies to one agent, and whether its values are in force."""

    applied: bool
    nudge_phrase: str
    call_cap_s: int


_AGENT: Final = (
    "SELECT language_primary, max_call_duration_s, status, caller_has_screen "
    "FROM agents WHERE id = :aid AND deleted_at IS NULL"
)


async def read_give_callers_time(
    session: AsyncSession, state: AgentCallHandling
) -> GiveCallersTime:
    """The preset for the agent whose call settings are `state`. RLS scopes the read."""
    row = (await session.execute(text(_AGENT), {"aid": state.agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    cap = effective_call_cap(row[1])
    return GiveCallersTime(
        applied=is_applied(state.resolved, cap),
        nudge_phrase=nudge_phrase_for(str(row[0]), caller_has_screen=bool(row[3])),
        call_cap_s=preset_call_cap_s(),
    )


@dataclass(frozen=True, slots=True)
class GiveCallersTimeApplied:
    state: AgentCallHandling
    #: The call settings that moved.
    moved: tuple[str, ...]
    #: The agent's longest call before and after, in seconds.
    call_cap_before_s: int
    call_cap_after_s: int


async def apply_give_callers_time(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> GiveCallersTimeApplied:
    """Write the preset on one agent in the caller's transaction.

    The call settings go through `set_agent_call_handling`, which locks the row and queues the
    agent's live apply. The longest call is only ever raised here, never lowered: an owner who
    chose 20 minutes keeps them. It rides the same live apply rather than
    `publishing.set_call_cap`'s publish in the request, because a longer cap that reaches the
    line a moment after the save ends calls sooner, never later, than the screen says."""
    row = (await session.execute(text(_AGENT + " FOR UPDATE"), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    own_cap, status = row[1], row[2]
    state, moved = await call_handling.set_agent_call_handling(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        changes=preset_changes(str(row[0]), caller_has_screen=bool(row[3])),
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
        if is_published(status):
            await queue_live_apply(
                session, scope="agent", tenant_id=tenant_id, agent_id=agent_id, reason="call_cap"
            )
    log.info(
        "agent_give_callers_time_applied",
        extra={
            "agent_id": str(agent_id),
            "changed": list(moved),
            "cap_before_s": before,
            "cap_after_s": after,
        },
    )
    return GiveCallersTimeApplied(
        state=state, moved=moved, call_cap_before_s=before, call_cap_after_s=after
    )


#: The longest call's name among the settings `apply_where_default` answers.
CALL_CAP_FIELD: Final = "max_call_duration_s"


async def apply_where_default(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> tuple[str, ...]:
    """The preset on the call settings this agent still takes from Calevate, as the
    caller-has-screen switch is turned on, in the caller's transaction. A setting the owner
    chose, on this agent or for every agent, is kept; so is a longest call of their own.

    The standard settings hang up on a caller who is looking for a screen: on the Rytu
    Khata call of 2 Nov 2026 the farmer was asked "are you still there?" at 8 s and the call
    ended at 20 s of quiet while they looked for the app. The caller's republish puts the
    values on the line, so the longest call is written without a live apply of its own.
    Answers the settings that moved, `CALL_CAP_FIELD` among them when the cap was raised."""
    row = (await session.execute(text(_AGENT + " FOR UPDATE"), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    state = await call_handling.read_agent_call_handling(session, agent_id)
    resolved = state.resolved
    changes = {
        field: value
        for field, value in preset_changes(str(row[0]), caller_has_screen=True).items()
        if resolved.sources[field] == "platform" and getattr(resolved.values, field) != value
    }
    moved: tuple[str, ...] = ()
    if changes:
        _state, moved = await call_handling.set_agent_call_handling(
            session, tenant_id=tenant_id, agent_id=agent_id, changes=changes
        )
    if row[1] is None and preset_call_cap_s() > effective_call_cap(None):
        await session.execute(
            text(
                "UPDATE agents SET max_call_duration_s = :cap, updated_at = now() WHERE id = :aid"
            ),
            {"cap": preset_call_cap_s(), "aid": agent_id},
        )
        moved = (*moved, CALL_CAP_FIELD)
    log.info(
        "agent_give_callers_time_defaults_applied",
        extra={"agent_id": str(agent_id), "changed": list(moved)},
    )
    return moved


# --- On a campaign's or inbound line's engine agent ------------------------------------------

#: The row key `_to_config` reads (`agents/service._call_settings_fields`).
HOLDER_ROW_KEY: Final = "holder_gives_time"


def holder_gives_time(owner_choice: bool | None, script: CallScript | None) -> bool:
    """Does a holder's engine agent carry the preset? The owner's choice for that holder once
    they made one, never overridden; until then, whether its script asks the caller to act on
    their phone."""
    if owner_choice is not None:
        return owner_choice
    return script is not None and asks_caller_to_act(script)


def holder_has_screen(script: CallScript | None, *, agent_switch: bool) -> bool:
    """Does a holder's caller follow along on their phone (the screen frame, D-906)? Read from
    the holder's own script (founder, 25 Nov 2026), because one agent's campaigns and lines
    differ: one guides an install, another only books. A raw script is not read
    (`asks_caller_to_act`) and a holder with no script speaks its agent's prompt, so those two
    keep the agent's switch, the one control their owner has."""
    if script is None or script.raw_override is not None:
        return agent_switch
    return asks_caller_to_act(script)


def holder_row(
    row: dict[str, Any], *, owner_choice: bool | None, script: CallScript | None
) -> dict[str, Any]:
    """A holder's agent row as `_to_config` builds its engine agent: the screen frame its
    script calls for in place of the agent's switch, and, where the holder carries the preset
    (`holder_gives_time`), the preset marked for the call settings and the longest call raised
    where the agent has none of its own. Pure: the agent's stored values are never written."""
    held = {
        **row,
        "caller_has_screen": holder_has_screen(
            script, agent_switch=bool(row.get("caller_has_screen", False))
        ),
    }
    if not holder_gives_time(owner_choice, script):
        return held
    held[HOLDER_ROW_KEY] = True
    if held.get("max_call_duration_s") is None and preset_call_cap_s() > effective_call_cap(None):
        held["max_call_duration_s"] = preset_call_cap_s()
    return held


def over_platform_level(
    resolved: ResolvedSettings, language: str, *, caller_has_screen: bool
) -> CallSettings:
    """The settings in force with the preset laid over each one still at Calevate's level:
    a value the agent or the account chose is kept, as `apply_where_default` keeps it. "Can
    you see it?" only where the caller is on a screen; otherwise the question stays the one
    every other call asks."""
    changes = {
        field: value
        for field, value in preset_changes(language, caller_has_screen=caller_has_screen).items()
        if resolved.sources[field] == "platform"
    }
    return call_handling.settings_of({**call_handling.as_mapping(resolved.values), **changes})


@dataclass(frozen=True, slots=True)
class HolderGiveTime:
    """The preset on one holder: in force, the owner's own choice (None: the script decides),
    and whether the script asks the caller to act."""

    on: bool
    owner_choice: bool | None
    script_asks: bool


def _script_or_none(raw: object) -> CallScript | None:
    if not raw:
        return None
    try:
        return CallScript.model_validate(raw)
    except ValidationError:
        return None


async def read_holder_give_time(session: AsyncSession, holder: Holder) -> HolderGiveTime:
    """The preset on a campaign or line. RLS scopes the read; 404 for one this session cannot
    see. A campaign with no script of its own speaks its agent's (`campaign_agent_row`)."""
    if holder.kind == "campaign":
        sql = (
            "SELECT c.give_callers_time, COALESCE(c.script, pv.structured_script) "
            "FROM campaigns c JOIN agents a ON a.id = c.agent_id "
            "LEFT JOIN prompt_versions pv "
            "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) "
            "WHERE c.id = :hid AND c.archived_at IS NULL"
        )
    else:
        sql = (
            "SELECT give_callers_time, script FROM inbound_lines "
            "WHERE id = :hid AND archived_at IS NULL"
        )
    row = (await session.execute(text(sql), {"hid": holder.id})).first()
    if row is None:
        raise ProblemError.not_found("Campaign" if holder.kind == "campaign" else "Inbound line")
    choice = None if row[0] is None else bool(row[0])
    script = _script_or_none(row[1])
    asks = script is not None and asks_caller_to_act(script)
    return HolderGiveTime(
        on=holder_gives_time(choice, script), owner_choice=choice, script_asks=asks
    )


async def set_holder_give_time(session: AsyncSession, holder: Holder, *, on: bool) -> bool:
    """Record the owner's choice for this holder, in the caller's transaction; the script no
    longer decides. Answers whether the value moved. The caller republishes a live holder."""
    from apps.api.agents.mistake_fixes import holder_table

    table = holder_table(holder.kind)
    moved = (
        await session.execute(
            text(
                f"UPDATE {table} SET give_callers_time = CAST(:on AS boolean), "
                "updated_at = now() WHERE id = :hid AND archived_at IS NULL "
                "AND give_callers_time IS DISTINCT FROM CAST(:on AS boolean) RETURNING id"
            ),
            {"on": on, "hid": holder.id},
        )
    ).first()
    log.info(
        "holder_give_callers_time_set",
        extra={"holder": holder.kind, "holder_id": str(holder.id), "on": on, "moved": bool(moved)},
    )
    return moved is not None


__all__ = [
    "CALL_CAP_FIELD",
    "CALL_CAP_S",
    "END_AFTER_SILENCE_S",
    "HOLDER_ROW_KEY",
    "NUDGE_AFTER_S",
    "NUDGE_COUNT",
    "NUDGE_PHRASES",
    "REASK_AFTER_MS",
    "GiveCallersTime",
    "GiveCallersTimeApplied",
    "HolderGiveTime",
    "apply_give_callers_time",
    "apply_where_default",
    "holder_gives_time",
    "holder_has_screen",
    "holder_row",
    "is_applied",
    "nudge_phrase_for",
    "over_platform_level",
    "preset_call_cap_s",
    "preset_changes",
    "read_give_callers_time",
    "read_holder_give_time",
    "set_holder_give_time",
]
