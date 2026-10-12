"""The call settings a client decides per agent or for the whole account (D-751, F3, F9).

- **Pause before the agent replies**: how long the caller must be quiet before their turn is
  over and the agent answers. Too short and a caller reading out a phone number is answered
  half way through it; too long and every reply waits.
- **Hang up when the conversation ends**: the agent releases the line when it has finished,
  rather than leaving it open, and billed, until the caller puts the phone down.
- **If the caller goes quiet** (F3, F9, 12 Oct 2026): ask "are you still there?" after some
  seconds (or never), how many times, in the client's own words or the platform's; and hang
  up after some seconds of silence.
- **Lines the agent says while it looks something up** (F3): the client's own, or the
  platform's.
- **Background sound** (F3): none, or an office, at a volume.

Each resolves agent -> organisation -> Calevate, the order the language model already uses
(`agents/llm_models.resolve_llm_model`): NULL on `agents` inherits the account's value, NULL
on `organizations` inherits the platform constant here. The resolution is this module's and
nobody else's, so the publish path (`service._to_config`), the screens and the copilot read
one answer.

Three settings need a value that is a CHOICE distinct from inheriting, so they spell it:
`nudge_after_seconds` 0 is "never ask", `nudge_phrase` '' and `filler_lines` [] are "the
platform's own", and `ambience` 'off' is no sound. NULL is always "inherit".

Milliseconds as a bounded integer, not seconds as NUMERIC: the pause is a duration with a
vendor floor of 0.2 s and no stated step, never money and never summed, so an integer holds
every value a person can mean exactly and the CHECK states the vendor range in whole units.
The adapter divides by 1000 only at the wire. The volume is a whole percent for the same
reason; the adapter divides by 100.

A change reaches the phone line through the live apply (D-720), queued in the saving
transaction: one agent for an agent's own value, the client's agents for an account default
that a live agent inherits. A call in progress finishes as it started (ThinnestAI email of
12 Oct 2026: a connected call keeps the configuration it started with).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.live_apply import queue_live_apply
from apps.api.agents.models import (
    AMBIENCE_VOLUME_MAX_PCT,
    AMBIENCE_VOLUME_MIN_PCT,
    AMBIENCES,
    END_AFTER_SILENCE_MAX_S,
    END_AFTER_SILENCE_MIN_S,
    FILLER_LINE_MAX_CHARS,
    FILLER_LINES_MAX,
    NUDGE_AFTER_MAX_S,
    NUDGE_AFTER_MIN_S,
    NUDGE_COUNT_MAX,
    NUDGE_COUNT_MIN,
    NUDGE_NEVER,
    NUDGE_PHRASE_MAX_CHARS,
    TURN_SILENCE_MAX_MS,
    TURN_SILENCE_MIN_MS,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: Calevate's default: the vendor's own, "0.25 s on most lines" (same pages). Kept rather
#: than raised, D-751 gives the reason: the delay is paid on every reply of every call, while
#: the dictation case it would help is already handled by asking for numbers a few digits at a
#: time (D-749), and an agent that takes numbers can be given a longer pause of its own.
TURN_SILENCE_DEFAULT_MS: Final = 250
#: On: a finished call that stays open bills every minute until the caller hangs up, and a new
#: vendor agent starts with it off (D-749).
END_CALL_ON_FINISH_DEFAULT: Final = True
#: Ask once after 8 seconds and hang up after 20 seconds of silence (founder decision F9,
#: 12 Oct 2026).
NUDGE_AFTER_DEFAULT_S: Final = 8
NUDGE_COUNT_DEFAULT: Final = 1
END_AFTER_SILENCE_DEFAULT_S: Final = 20
#: Off, and 15% once switched on: the vendor's own default volume (0.15).
AMBIENCE_DEFAULT: Final = "off"
AMBIENCE_VOLUME_DEFAULT_PCT: Final = 15

SettingSource = Literal["agent", "organization", "platform"]


@dataclass(frozen=True, slots=True)
class CallSettings:
    """One level's values. At the agent and account levels None inherits; resolved, every
    field is set (`PLATFORM_SETTINGS` fills the gaps)."""

    turn_silence_ms: int | None = None
    end_call_on_finish: bool | None = None
    #: Seconds before asking whether the caller is still there; 0 is never.
    nudge_after_seconds: int | None = None
    nudge_count: int | None = None
    #: The client's own question; '' is the platform's own, in the caller's language.
    nudge_phrase: str | None = None
    end_after_silence_seconds: int | None = None
    #: The client's own lines; () is the platform's own.
    filler_lines: tuple[str, ...] | None = None
    #: 'off', 'office' or 'office-quiet'.
    ambience: str | None = None
    ambience_volume_pct: int | None = None


#: The fields, in column order. Spelled out (not read off the dataclass) because they reach
#: SQL as identifiers, and `scripts/check_raw_sql` admits only text typed here.
SETTING_FIELDS: Final[tuple[str, ...]] = (
    "turn_silence_ms",
    "end_call_on_finish",
    "nudge_after_seconds",
    "nudge_count",
    "nudge_phrase",
    "end_after_silence_seconds",
    "filler_lines",
    "ambience",
    "ambience_volume_pct",
)
#: The same fields on `organizations`, the account defaults, in the same order. Spelled out for
#: `SETTING_FIELDS`' reason.
ORG_SETTING_FIELDS: Final[tuple[str, ...]] = (
    "default_turn_silence_ms",
    "default_end_call_on_finish",
    "default_nudge_after_seconds",
    "default_nudge_count",
    "default_nudge_phrase",
    "default_end_after_silence_seconds",
    "default_filler_lines",
    "default_ambience",
    "default_ambience_volume_pct",
)
#: The fields a PATCH may name. A field left out is untouched; null inherits.
AGENT_FIELDS: Final = SETTING_FIELDS

#: Calevate's own values, the last level of every resolution.
PLATFORM_SETTINGS: Final = CallSettings(
    turn_silence_ms=TURN_SILENCE_DEFAULT_MS,
    end_call_on_finish=END_CALL_ON_FINISH_DEFAULT,
    nudge_after_seconds=NUDGE_AFTER_DEFAULT_S,
    nudge_count=NUDGE_COUNT_DEFAULT,
    nudge_phrase="",
    end_after_silence_seconds=END_AFTER_SILENCE_DEFAULT_S,
    filler_lines=(),
    ambience=AMBIENCE_DEFAULT,
    ambience_volume_pct=AMBIENCE_VOLUME_DEFAULT_PCT,
)


@dataclass(frozen=True, slots=True)
class TurnSilence:
    ms: int
    source: SettingSource


@dataclass(frozen=True, slots=True)
class EndCallOnFinish:
    enabled: bool
    source: SettingSource


@dataclass(frozen=True, slots=True)
class ResolvedSettings:
    """Every setting in force, and the level that chose each."""

    values: CallSettings
    sources: Mapping[str, SettingSource]


def resolve_turn_silence(agent_ms: int | None, organization_ms: int | None) -> TurnSilence:
    if agent_ms is not None:
        return TurnSilence(agent_ms, "agent")
    if organization_ms is not None:
        return TurnSilence(organization_ms, "organization")
    return TurnSilence(TURN_SILENCE_DEFAULT_MS, "platform")


def resolve_end_call_on_finish(agent: bool | None, organization: bool | None) -> EndCallOnFinish:
    if agent is not None:
        return EndCallOnFinish(agent, "agent")
    if organization is not None:
        return EndCallOnFinish(organization, "organization")
    return EndCallOnFinish(END_CALL_ON_FINISH_DEFAULT, "platform")


def resolve_settings(own: CallSettings, organization: CallSettings) -> ResolvedSettings:
    """Each field from the first level that holds a value: the agent, the account, Calevate."""
    chosen: dict[str, object] = {}
    sources: dict[str, SettingSource] = {}
    for field in SETTING_FIELDS:
        mine, theirs = getattr(own, field), getattr(organization, field)
        if mine is not None:
            chosen[field], sources[field] = mine, "agent"
        elif theirs is not None:
            chosen[field], sources[field] = theirs, "organization"
        else:
            chosen[field], sources[field] = getattr(PLATFORM_SETTINGS, field), "platform"
    return ResolvedSettings(settings_of(chosen), sources)


def refuse_turn_silence_out_of_range(ms: int | None, *, field: str) -> None:
    """The range check every writer runs: the CHECK is the floor, this is the sentence."""
    if ms is None or TURN_SILENCE_MIN_MS <= ms <= TURN_SILENCE_MAX_MS:
        return
    raise ProblemError(
        kind="validation",
        code="turn_silence_out_of_range",
        title="Pause before replying is out of range",
        detail=(
            f"The pause before the agent replies must be between "
            f"{TURN_SILENCE_MIN_MS / 1000:g} and {TURN_SILENCE_MAX_MS / 1000:g} seconds."
        ),
        remediation=(
            "Choose a pause in that range, or clear it to use the default "
            f"({TURN_SILENCE_DEFAULT_MS / 1000:g} seconds)."
        ),
        fields=[
            {
                "field": field,
                "rule": "out_of_range",
                "message": (
                    f"Must be {TURN_SILENCE_MIN_MS}-{TURN_SILENCE_MAX_MS} milliseconds, or "
                    "null to inherit."
                ),
            }
        ],
    )


def _refuse(field: str, title: str, detail: str, remediation: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="call_setting_out_of_range",
        title=title,
        detail=detail,
        remediation=remediation,
        fields=[{"field": field, "rule": "out_of_range", "message": detail}],
    )


def _in(value: int, low: int, high: int) -> bool:
    return low <= value <= high


def normalise_filler_lines(lines: Sequence[str]) -> tuple[str, ...]:
    """The lines as stored: each trimmed, blank ones dropped."""
    return tuple(line.strip() for line in lines if line.strip())


def refuse_invalid_settings(values: CallSettings) -> None:
    """Every value a writer is about to store, checked in the words a client reads. None is
    always valid (it inherits)."""
    refuse_turn_silence_out_of_range(values.turn_silence_ms, field="turn_silence_ms")
    after = values.nudge_after_seconds
    if (
        after is not None
        and after != NUDGE_NEVER
        and not _in(after, NUDGE_AFTER_MIN_S, NUDGE_AFTER_MAX_S)
    ):
        raise _refuse(
            "nudge_after_seconds",
            "Time before asking is out of range",
            f"The agent can ask whether the caller is still there after {NUDGE_AFTER_MIN_S} to "
            f"{NUDGE_AFTER_MAX_S} seconds of quiet, or never.",
            f"Choose {NUDGE_AFTER_MIN_S}-{NUDGE_AFTER_MAX_S} seconds, or never.",
        )
    if values.nudge_count is not None and not _in(
        values.nudge_count, NUDGE_COUNT_MIN, NUDGE_COUNT_MAX
    ):
        raise _refuse(
            "nudge_count",
            "Number of times to ask is out of range",
            f"The agent can ask {NUDGE_COUNT_MIN} to {NUDGE_COUNT_MAX} times.",
            f"Choose {NUDGE_COUNT_MIN}-{NUDGE_COUNT_MAX}.",
        )
    if values.nudge_phrase is not None and len(values.nudge_phrase) > NUDGE_PHRASE_MAX_CHARS:
        raise _refuse(
            "nudge_phrase",
            "The question is too long",
            f"The question can be up to {NUDGE_PHRASE_MAX_CHARS} characters.",
            "Shorten it, or leave it empty to use the standard question.",
        )
    silence = values.end_after_silence_seconds
    if silence is not None and not _in(silence, END_AFTER_SILENCE_MIN_S, END_AFTER_SILENCE_MAX_S):
        raise _refuse(
            "end_after_silence_seconds",
            "Time before hanging up is out of range",
            f"The agent can hang up after {END_AFTER_SILENCE_MIN_S} to "
            f"{END_AFTER_SILENCE_MAX_S} seconds of silence.",
            f"Choose {END_AFTER_SILENCE_MIN_S}-{END_AFTER_SILENCE_MAX_S} seconds.",
        )
    lines = values.filler_lines
    if lines is not None:
        if len(lines) > FILLER_LINES_MAX:
            raise _refuse(
                "filler_lines",
                "Too many lines",
                f"The agent can have up to {FILLER_LINES_MAX} lines to say while it looks "
                "something up.",
                f"Keep {FILLER_LINES_MAX} or fewer.",
            )
        if any(len(line) > FILLER_LINE_MAX_CHARS for line in lines):
            raise _refuse(
                "filler_lines",
                "A line is too long",
                f"Each line can be up to {FILLER_LINE_MAX_CHARS} characters.",
                "Shorten the long line.",
            )
    if values.ambience is not None and values.ambience not in AMBIENCES:
        raise _refuse(
            "ambience",
            "Unknown background sound",
            "The background sound can be off, an office, or a quiet office.",
            "Choose one of those.",
        )
    volume = values.ambience_volume_pct
    if volume is not None and not _in(volume, AMBIENCE_VOLUME_MIN_PCT, AMBIENCE_VOLUME_MAX_PCT):
        raise _refuse(
            "ambience_volume_pct",
            "Background volume is out of range",
            f"The background volume can be {AMBIENCE_VOLUME_MIN_PCT}% to "
            f"{AMBIENCE_VOLUME_MAX_PCT}%.",
            f"Choose {AMBIENCE_VOLUME_MIN_PCT}-{AMBIENCE_VOLUME_MAX_PCT}%.",
        )


@dataclass(frozen=True, slots=True)
class AgentCallHandling:
    agent_id: UUID
    #: The agent's own values; None inherits.
    own: CallSettings
    #: The account's values; None follows Calevate's.
    organization: CallSettings
    resolved: ResolvedSettings

    @property
    def turn_silence_ms(self) -> int | None:
        return self.own.turn_silence_ms

    @property
    def end_call_on_finish(self) -> bool | None:
        return self.own.end_call_on_finish

    @property
    def organization_turn_silence_ms(self) -> int | None:
        return self.organization.turn_silence_ms

    @property
    def organization_end_call_on_finish(self) -> bool | None:
        return self.organization.end_call_on_finish

    @property
    def turn_silence(self) -> TurnSilence:
        return resolve_turn_silence(self.own.turn_silence_ms, self.organization.turn_silence_ms)

    @property
    def end_call(self) -> EndCallOnFinish:
        return resolve_end_call_on_finish(
            self.own.end_call_on_finish, self.organization.end_call_on_finish
        )


@dataclass(frozen=True, slots=True)
class OrganizationCallHandling:
    own: CallSettings
    resolved: ResolvedSettings

    @property
    def turn_silence_ms(self) -> int | None:
        return self.own.turn_silence_ms

    @property
    def end_call_on_finish(self) -> bool | None:
        return self.own.end_call_on_finish

    @property
    def turn_silence(self) -> TurnSilence:
        return resolve_turn_silence(None, self.own.turn_silence_ms)

    @property
    def end_call(self) -> EndCallOnFinish:
        return resolve_end_call_on_finish(None, self.own.end_call_on_finish)


AGENT_SETTING_COLUMNS: Final = ", ".join(f"a.{f}" for f in SETTING_FIELDS)
ORG_SETTING_COLUMNS: Final = ", ".join(f"o.{f}" for f in ORG_SETTING_FIELDS)
_AGENT_ROW: Final = (
    f"SELECT {AGENT_SETTING_COLUMNS}, {ORG_SETTING_COLUMNS} "
    "FROM agents a LEFT JOIN organizations o ON o.id = a.tenant_id "
    "WHERE a.id = :aid AND a.deleted_at IS NULL"
)
_ORG_ROW: Final = (
    "SELECT " + ", ".join(ORG_SETTING_FIELDS) + " FROM organizations WHERE deleted_at IS NULL"
)
_ORG_ROW_FOR_UPDATE: Final = _ORG_ROW + " FOR UPDATE"
_AGENT_FOR_UPDATE: Final = (
    "SELECT "
    + ", ".join(SETTING_FIELDS)
    + ", status, engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
)
_UPDATE_AGENT: Final = (
    "UPDATE agents SET "
    + ", ".join(f"{f} = :{f}" for f in SETTING_FIELDS)
    + ", updated_at = now() WHERE id = :aid"
)
_UPDATE_ORG: Final = (
    "UPDATE organizations SET "
    + ", ".join(
        f"{column} = :{field}"
        for column, field in zip(ORG_SETTING_FIELDS, SETTING_FIELDS, strict=True)
    )
    + ", updated_at = now() WHERE deleted_at IS NULL"
)


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(str(value))


def _bool_or_none(value: object) -> bool | None:
    return None if value is None else bool(value)


def _str_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def _lines_or_none(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        return tuple(str(line) for line in value)
    raise TypeError("filler lines are not an array")


def settings_from_row(row: Sequence[object]) -> CallSettings:
    """A `CallSettings` from the columns in `SETTING_FIELDS` order."""
    return CallSettings(
        turn_silence_ms=_int_or_none(row[0]),
        end_call_on_finish=_bool_or_none(row[1]),
        nudge_after_seconds=_int_or_none(row[2]),
        nudge_count=_int_or_none(row[3]),
        nudge_phrase=_str_or_none(row[4]),
        end_after_silence_seconds=_int_or_none(row[5]),
        filler_lines=_lines_or_none(row[6]),
        ambience=_str_or_none(row[7]),
        ambience_volume_pct=_int_or_none(row[8]),
    )


def settings_of(values: Mapping[str, object]) -> CallSettings:
    """A `CallSettings` from named values; a name left out is None."""
    return settings_from_row(tuple(values.get(f) for f in SETTING_FIELDS))


def as_mapping(values: CallSettings) -> dict[str, object]:
    return {f: getattr(values, f) for f in SETTING_FIELDS}


def _binds(values: CallSettings) -> dict[str, object]:
    out: dict[str, object] = {f: getattr(values, f) for f in SETTING_FIELDS}
    # A list, not a tuple: the driver binds a list as a Postgres array.
    out["filler_lines"] = None if values.filler_lines is None else list(values.filler_lines)
    return out


def _agent_state(agent_id: UUID, row: Sequence[object]) -> AgentCallHandling:
    width = len(SETTING_FIELDS)
    own = settings_from_row(row[:width])
    organization = settings_from_row(row[width : 2 * width])
    return AgentCallHandling(
        agent_id=agent_id,
        own=own,
        organization=organization,
        resolved=resolve_settings(own, organization),
    )


async def read_agent_call_handling(session: AsyncSession, agent_id: UUID) -> AgentCallHandling:
    """One agent's settings with where each comes from. RLS scopes the read, so another
    client's agent is a 404 exactly like a missing one."""
    row = (await session.execute(text(_AGENT_ROW), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return _agent_state(agent_id, tuple(row))


def _clean(changes: Mapping[str, object]) -> dict[str, object]:
    """The changes as stored: filler lines trimmed into a tuple, the nudge phrase trimmed. A
    blank phrase is '' (the platform's own): kept as spaces it would be sent as a phrase and
    read back trimmed, which is drift no repair can clear."""
    out = dict(changes)
    phrase = out.get("nudge_phrase")
    if isinstance(phrase, str):
        out["nudge_phrase"] = phrase.strip()
    lines = out.get("filler_lines")
    if lines is not None:
        if not isinstance(lines, list | tuple):
            raise TypeError("filler lines must be a list")
        out["filler_lines"] = normalise_filler_lines([str(line) for line in lines])
    return out


async def set_agent_call_handling(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    changes: Mapping[str, object],
) -> tuple[AgentCallHandling, tuple[str, ...]]:
    """Write the named fields on one agent and queue its live apply when it is live.

    The row is locked first so "did this change?" and the write are one step, and a repeat
    of the value already held writes nothing and queues nothing. Answers the new state and the
    fields that moved."""
    unknown = set(changes) - set(SETTING_FIELDS)
    if unknown:
        raise ValueError(f"not a call handling field: {sorted(unknown)}")
    cleaned = _clean(changes)
    refuse_invalid_settings(settings_of(cleaned))
    row = (await session.execute(text(_AGENT_FOR_UPDATE), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    width = len(SETTING_FIELDS)
    current = settings_from_row(tuple(row)[:width])
    moved = tuple(f for f in SETTING_FIELDS if f in cleaned and cleaned[f] != getattr(current, f))
    if moved:
        wanted = settings_of({**as_mapping(current), **{f: cleaned[f] for f in moved}})
        await session.execute(text(_UPDATE_AGENT), {**_binds(wanted), "aid": agent_id})
        status, ref = row[width], row[width + 1]
        if str(status) == "live" and ref:
            await queue_live_apply(
                session,
                scope="agent",
                tenant_id=tenant_id,
                agent_id=agent_id,
                reason="call_handling",
            )
    log.info(
        "agent_call_handling_set",
        extra={"agent_id": str(agent_id), "changed": list(moved)},
    )
    return await read_agent_call_handling(session, agent_id), moved


def _org_state(own: CallSettings) -> OrganizationCallHandling:
    return OrganizationCallHandling(own=own, resolved=resolve_settings(CallSettings(), own))


async def read_organization_call_handling(session: AsyncSession) -> OrganizationCallHandling:
    row = (await session.execute(text(_ORG_ROW))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    return _org_state(settings_from_row(tuple(row)))


_LIVE_AGENT: Final = (
    "SELECT 1 FROM agents WHERE deleted_at IS NULL AND status = 'live' "
    "AND engine_agent_ref IS NOT NULL AND "
)
#: Per field: a live agent that inherits the account value, so changing it moves a line.
_INHERITING_LIVE_AGENT: Final = {f: _LIVE_AGENT + f + " IS NULL LIMIT 1" for f in SETTING_FIELDS}


async def set_organization_call_handling(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    changes: Mapping[str, object],
) -> tuple[OrganizationCallHandling, tuple[str, ...]]:
    """Write the named account defaults (null follows Calevate's) and queue the client's live
    apply when a live agent inherits a value that moved. A field left out is kept."""
    unknown = set(changes) - set(SETTING_FIELDS)
    if unknown:
        raise ValueError(f"not a call handling field: {sorted(unknown)}")
    cleaned = _clean(changes)
    refuse_invalid_settings(settings_of(cleaned))
    row = (await session.execute(text(_ORG_ROW_FOR_UPDATE))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    current = settings_from_row(tuple(row))
    moved = tuple(f for f in SETTING_FIELDS if f in cleaned and cleaned[f] != getattr(current, f))
    if moved:
        wanted = settings_of({**as_mapping(current), **{f: cleaned[f] for f in moved}})
        await session.execute(text(_UPDATE_ORG), _binds(wanted))
        for field in moved:
            sql = _INHERITING_LIVE_AGENT[field]
            if (await session.execute(text(sql))).first() is not None:
                await queue_live_apply(
                    session, scope="tenant", tenant_id=tenant_id, reason="call_handling"
                )
                break
    log.info(
        "organization_call_handling_set",
        extra={"tenant_id": str(tenant_id), "changed": list(moved)},
    )
    return await read_organization_call_handling(session), moved


__all__ = [
    "AGENT_FIELDS",
    "AGENT_SETTING_COLUMNS",
    "AMBIENCE_DEFAULT",
    "AMBIENCE_VOLUME_DEFAULT_PCT",
    "END_AFTER_SILENCE_DEFAULT_S",
    "END_CALL_ON_FINISH_DEFAULT",
    "NUDGE_AFTER_DEFAULT_S",
    "NUDGE_COUNT_DEFAULT",
    "ORG_SETTING_COLUMNS",
    "ORG_SETTING_FIELDS",
    "PLATFORM_SETTINGS",
    "SETTING_FIELDS",
    "TURN_SILENCE_DEFAULT_MS",
    "TURN_SILENCE_MAX_MS",
    "TURN_SILENCE_MIN_MS",
    "AgentCallHandling",
    "CallSettings",
    "EndCallOnFinish",
    "OrganizationCallHandling",
    "ResolvedSettings",
    "SettingSource",
    "TurnSilence",
    "as_mapping",
    "normalise_filler_lines",
    "read_agent_call_handling",
    "read_organization_call_handling",
    "refuse_invalid_settings",
    "refuse_turn_silence_out_of_range",
    "resolve_end_call_on_finish",
    "resolve_settings",
    "resolve_turn_silence",
    "set_agent_call_handling",
    "set_organization_call_handling",
    "settings_from_row",
    "settings_of",
]
