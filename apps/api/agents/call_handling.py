"""The call settings a client decides per agent or for the whole account (D-751, F3, F9).

- **Pause before the agent replies**: the quiet after the caller's last words that ends their
  turn. Too short and a caller reading out a phone number is answered half way through it;
  too long and every reply waits. Under real-time listening (`ear`) it is the recogniser's
  end-of-speech silence, under the timer the wait after its final words (ThinnestAI, email of
  28 Oct 2026, VENDOR-STATED, correcting its 27 Oct one; 0.2 s is the floor either way).
- **Hang up when the conversation ends**: the agent releases the line when it has finished,
  rather than leaving it open, and billed, until the caller puts the phone down.
- **If the caller goes quiet** (F3, F9, 12 Oct 2026): ask "are you still there?" after some
  seconds (or never), how many times, in the client's own words or the platform's; and hang
  up after some seconds of silence.
- **Asking an unanswered question again** (D-907): after a question the agent asked has had no
  answer, how long it waits before asking it once more, or never. A caller following along on
  their phone is busy, not deaf, and a question repeated at 5 s talks over them.
- **Lines the agent says while it looks something up** (F3): the client's own, or the
  platform's.
- **Background sound** (F3): none, or an office, at a volume.
- **How long a waiting opening waits** (D-901): for an agent whose opening waits for the
  person's hello, the silence after which it speaks anyway. Calevate's level is the console's
  `thinnest_opening_wait_ms`, not a constant: while it is unset the field is never sent (the
  vendor's 4 s applies) and no client may set a wait of its own, because the vendor accepts the
  field only from 28 Oct 2026 and a field it does not know could refuse the whole publish.

Each resolves agent -> organisation -> Calevate, the order the language model already uses
(`agents/llm_models.resolve_llm_model`): NULL on `agents` inherits the account's value, NULL
on `organizations` inherits the platform constant here. The resolution is this module's and
nobody else's, so the publish path (`service._to_config`), the screens and the copilot read
one answer.

Four settings need a value that is a CHOICE distinct from inheriting, so they spell it:
`nudge_after_seconds` and `reask_after_ms` 0 are "never ask", `nudge_phrase` '' and
`filler_lines` [] are "the platform's own", and `ambience` 'off' is no sound. NULL is always
"inherit".

Milliseconds as a bounded integer, not seconds as NUMERIC: the pause is a duration with a
vendor floor of 0.2 s and no stated step, never money and never summed, so an integer holds
every value a person can mean exactly and the CHECK states the vendor range in whole units.
The adapter divides by 1000 only at the wire. The volume is a whole percent for the same
reason; the adapter divides by 100.

A change reaches the phone line through the live apply (D-720), queued in the saving
transaction: one agent for an agent's own value, the client's agents for an account default
that a live agent inherits. A call in progress finishes as it started (ThinnestAI email of
12 Oct 2026: a connected call keeps the configuration it started with).

Clients change these on an agent's Settings only (founder, 27 Oct 2026): each change is for
"just this agent" (`set_agent_call_handling`) or "all my agents"
(`set_call_handling_for_all_agents`, the account default plus dropping every agent's own
value). The account default on its own (`set_organization_call_handling`) is the operator's
console and the API's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal
from uuid import UUID

from calevate_shared.engine import TurnDetection
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
    OPENING_WAIT_MAX_MS,
    OPENING_WAIT_MIN_MS,
    OPENING_WAIT_STEP_MS,
    REASK_AFTER_MAX_MS,
    REASK_AFTER_MIN_MS,
    REASK_AFTER_STEP_MS,
    REASK_NEVER,
    TURN_SILENCE_MAX_MS,
    TURN_SILENCE_MIN_MS,
    is_published,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

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
#: An unanswered question is asked again after 5 s rather than the platform's 2.5 s (founder,
#: 20 Oct 2026, D-835): the value every agent was sent before it became a setting (D-907).
REASK_AFTER_DEFAULT_MS: Final = 5000
#: Off, and 15% once switched on: the vendor's own default volume (0.15).
AMBIENCE_DEFAULT: Final = "off"
AMBIENCE_VOLUME_DEFAULT_PCT: Final = 15

SettingSource = Literal["agent", "organization", "platform"]

#: The agent's own settings with no account default and no inheritance: always a value,
#: written beside `SETTING_FIELDS` by the same writer. `opening_waits_for_caller` holds the
#: opening until the person who picked up speaks (D-871).
AGENT_ONLY_FIELDS: Final[tuple[str, ...]] = ("opening_waits_for_caller",)


def opening_waits_default(direction: str) -> bool:
    """A new agent's `opening_waits_for_caller` (D-871): on for an agent that only places
    calls, because the person who picks up speaks first and an opening played over their
    "Hello" is greeted twice; off for one that answers calls, because a caller ringing a
    business expects it to speak first and four seconds of silence reads as a dead line."""
    return direction == "outbound"


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
    #: Milliseconds of silence before an opening that waits for hello plays anyway. Resolved,
    #: None is "not sent" (the console has no wait).
    opening_wait_ms: int | None = None
    #: Milliseconds before an unanswered question of the agent's is asked again; 0 is never.
    reask_after_ms: int | None = None


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
    "opening_wait_ms",
    "reask_after_ms",
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
    "default_opening_wait_ms",
    "default_reask_after_ms",
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
    # The console's, filled in by `platform_settings`.
    opening_wait_ms=None,
    reask_after_ms=REASK_AFTER_DEFAULT_MS,
)


def platform_turn_silence_ms(own_turn_detection: TurnDetection | None = None) -> int:
    """Calevate's pause for one agent. An agent an operator put on the timer on its own
    (D-901) starts from the console's `thinnest_timer_turn_silence_ms`: under the timer the
    pause is counted from the recogniser's final words, after its own end-of-speech wait, and
    ThinnestAI's advice for a first Telugu trial is 0.35-0.4 s (email of 27 Oct 2026,
    VENDOR-STATED; no Telugu measurement exists). Every other agent keeps
    `TURN_SILENCE_DEFAULT_MS`: the console's mode is the founder's choice for every agent,
    and a timer default tied to it would move every agent's pause with one switch."""
    if own_turn_detection == "timer":
        return get_settings().thinnest_timer_turn_silence_ms
    return TURN_SILENCE_DEFAULT_MS


def platform_settings(own_turn_detection: TurnDetection | None = None) -> CallSettings:
    """Calevate's level as it stands now for an agent whose own turn detection is
    `own_turn_detection` (None follows the console's): the constants, the console's opening
    wait, and `platform_turn_silence_ms`."""
    return replace(
        PLATFORM_SETTINGS,
        opening_wait_ms=get_settings().thinnest_opening_wait_ms,
        turn_silence_ms=platform_turn_silence_ms(own_turn_detection),
    )


def opening_wait_available() -> bool:
    """May a wait be set and sent? Only once an operator has set the console's."""
    return get_settings().thinnest_opening_wait_ms is not None


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


def resolve_turn_silence(
    agent_ms: int | None,
    organization_ms: int | None,
    *,
    own_turn_detection: TurnDetection | None = None,
) -> TurnSilence:
    if agent_ms is not None:
        return TurnSilence(agent_ms, "agent")
    if organization_ms is not None:
        return TurnSilence(organization_ms, "organization")
    return TurnSilence(platform_turn_silence_ms(own_turn_detection), "platform")


def resolve_end_call_on_finish(agent: bool | None, organization: bool | None) -> EndCallOnFinish:
    if agent is not None:
        return EndCallOnFinish(agent, "agent")
    if organization is not None:
        return EndCallOnFinish(organization, "organization")
    return EndCallOnFinish(END_CALL_ON_FINISH_DEFAULT, "platform")


def resolve_settings(
    own: CallSettings,
    organization: CallSettings,
    *,
    own_turn_detection: TurnDetection | None = None,
) -> ResolvedSettings:
    """Each field from the first level that holds a value: the agent, the account, Calevate
    (`platform_settings` for an agent whose own turn detection is `own_turn_detection`)."""
    chosen: dict[str, object] = {}
    sources: dict[str, SettingSource] = {}
    platform = platform_settings(own_turn_detection)
    for field in SETTING_FIELDS:
        mine, theirs = getattr(own, field), getattr(organization, field)
        if mine is not None:
            chosen[field], sources[field] = mine, "agent"
        elif theirs is not None:
            chosen[field], sources[field] = theirs, "organization"
        else:
            chosen[field], sources[field] = getattr(platform, field), "platform"
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
    refuse_opening_wait(values.opening_wait_ms)
    reask = values.reask_after_ms
    if (
        reask is not None
        and reask != REASK_NEVER
        and (not _in(reask, REASK_AFTER_MIN_MS, REASK_AFTER_MAX_MS) or reask % REASK_AFTER_STEP_MS)
    ):
        low, high = REASK_AFTER_MIN_MS / 1000, REASK_AFTER_MAX_MS / 1000
        raise _refuse(
            "reask_after_ms",
            "Time before asking again is out of range",
            f"The agent can ask an unanswered question again after {low:g} to {high:g} "
            "seconds, in tenths of a second, or never.",
            f"Choose {low:g}-{high:g} seconds, or never.",
        )


def refuse_opening_wait(ms: int | None) -> None:
    """A wait is 0.5 to 10 seconds to a tenth, and only once the console offers one."""
    if ms is None:
        return
    if not opening_wait_available():
        raise ProblemError.business_rule(
            "opening_wait_unavailable",
            "How long the agent waits for a hello cannot be changed yet.",
            remediation="Leave it on the default for now.",
        )
    low, high = OPENING_WAIT_MIN_MS / 1000, OPENING_WAIT_MAX_MS / 1000
    if not _in(ms, OPENING_WAIT_MIN_MS, OPENING_WAIT_MAX_MS) or ms % OPENING_WAIT_STEP_MS:
        raise _refuse(
            "opening_wait_ms",
            "Wait for hello is out of range",
            f"The agent can wait {low:g} to {high:g} seconds, in tenths of a second.",
            f"Choose {low:g}-{high:g} seconds.",
        )


@dataclass(frozen=True, slots=True)
class AgentCallHandling:
    agent_id: UUID
    #: The agent's own values; None inherits.
    own: CallSettings
    #: The account's values; None follows Calevate's.
    organization: CallSettings
    resolved: ResolvedSettings
    #: The agent's own, never inherited (`AGENT_ONLY_FIELDS`).
    opening_waits_for_caller: bool = False
    #: An operator's turn detection for this agent (D-901); None follows the console's.
    turn_detection: TurnDetection | None = None

    @property
    def turn_detection_effective(self) -> TurnDetection:
        return self.turn_detection or get_settings().thinnest_turn_detection

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
        return resolve_turn_silence(
            self.own.turn_silence_ms,
            self.organization.turn_silence_ms,
            own_turn_detection=self.turn_detection,
        )

    @property
    def end_call(self) -> EndCallOnFinish:
        return resolve_end_call_on_finish(
            self.own.end_call_on_finish, self.organization.end_call_on_finish
        )


@dataclass(frozen=True, slots=True)
class AgentOwnSettings:
    """An agent holding a value of its own for at least one setting, which the account
    default therefore does not reach."""

    agent_id: UUID
    name: str
    own: CallSettings


#: The agents with values of their own read beside the account defaults, at most this many:
#: a ceiling against a pathological roster, not a product limit. `agents_with_own_total`
#: still counts every one, so a screen can say how many it is not listing.
AGENTS_WITH_OWN_MAX: Final = 50


@dataclass(frozen=True, slots=True)
class OrganizationCallHandling:
    own: CallSettings
    resolved: ResolvedSettings
    #: Who does not follow these defaults. Without it a screen of account defaults reads
    #: "Background sound: Off" while an agent that set its own plays an office on every call.
    agents_with_own: tuple[AgentOwnSettings, ...] = ()
    agents_with_own_total: int = 0

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
    f"SELECT {AGENT_SETTING_COLUMNS}, {ORG_SETTING_COLUMNS}, "
    + ", ".join(f"a.{f}" for f in AGENT_ONLY_FIELDS)
    + ", a.turn_detection "
    "FROM agents a LEFT JOIN organizations o ON o.id = a.tenant_id "
    "WHERE a.id = :aid AND a.deleted_at IS NULL"
)
_ORG_ROW: Final = (
    "SELECT " + ", ".join(ORG_SETTING_FIELDS) + " FROM organizations WHERE deleted_at IS NULL"
)
_ORG_ROW_FOR_UPDATE: Final = _ORG_ROW + " FOR UPDATE"
_AGENTS_WITH_OWN: Final = (
    "SELECT id, name, "
    + ", ".join(SETTING_FIELDS)
    + ", count(*) OVER () FROM agents WHERE deleted_at IS NULL AND ("
    + " OR ".join(f"{f} IS NOT NULL" for f in SETTING_FIELDS)
    + ") ORDER BY lower(name), id LIMIT :limit"
)
_AGENT_FOR_UPDATE: Final = (
    "SELECT "
    + ", ".join((*SETTING_FIELDS, *AGENT_ONLY_FIELDS))
    + ", status, engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
)
_UPDATE_AGENT: Final = (
    "UPDATE agents SET "
    + ", ".join(f"{f} = :{f}" for f in (*SETTING_FIELDS, *AGENT_ONLY_FIELDS))
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
        opening_wait_ms=_int_or_none(row[9]),
        reask_after_ms=_int_or_none(row[10]),
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
    turn_detection = turn_detection_of(row[2 * width + len(AGENT_ONLY_FIELDS)])
    return AgentCallHandling(
        agent_id=agent_id,
        own=own,
        organization=organization,
        resolved=resolve_settings(own, organization, own_turn_detection=turn_detection),
        opening_waits_for_caller=bool(row[2 * width]),
        turn_detection=turn_detection,
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
    """Write the named fields on one agent and queue its live apply when the
    engine holds it (live or ready).

    The row is locked first so "did this change?" and the write are one step, and a repeat
    of the value already held writes nothing and queues nothing. Answers the new state and the
    fields that moved."""
    unknown = set(changes) - set(SETTING_FIELDS) - set(AGENT_ONLY_FIELDS)
    if unknown:
        raise ValueError(f"not a call handling field: {sorted(unknown)}")
    own_only = {f: changes[f] for f in AGENT_ONLY_FIELDS if f in changes}
    for field, value in own_only.items():
        if not isinstance(value, bool):
            # Never inherited, so null cannot mean "follow the default" as it does above.
            raise _refuse(
                field,
                "This setting is on or off",
                "This setting belongs to the agent alone and has no default to follow.",
                "Send true or false.",
            )
    cleaned = _clean({f: v for f, v in changes.items() if f in SETTING_FIELDS})
    refuse_invalid_settings(settings_of(cleaned))
    row = (await session.execute(text(_AGENT_FOR_UPDATE), {"aid": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    width = len(SETTING_FIELDS)
    current = settings_from_row(tuple(row)[:width])
    held_own = {f: bool(row[width + i]) for i, f in enumerate(AGENT_ONLY_FIELDS)}
    moved = tuple(
        f for f in SETTING_FIELDS if f in cleaned and cleaned[f] != getattr(current, f)
    ) + tuple(f for f in AGENT_ONLY_FIELDS if f in own_only and own_only[f] != held_own[f])
    if moved:
        wanted = settings_of(
            {**as_mapping(current), **{f: cleaned[f] for f in moved if f in cleaned}}
        )
        await session.execute(
            text(_UPDATE_AGENT),
            {**_binds(wanted), **held_own, **own_only, "aid": agent_id},
        )
        extra = len(AGENT_ONLY_FIELDS)
        status, ref = row[width + extra], row[width + extra + 1]
        if is_published(status, ref):
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


async def read_organization_call_handling(session: AsyncSession) -> OrganizationCallHandling:
    """The account's defaults and the agents that override any of them; RLS scopes both
    reads to the session's tenant."""
    row = (await session.execute(text(_ORG_ROW))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    own = settings_from_row(tuple(row))
    width = len(SETTING_FIELDS)
    agents = (await session.execute(text(_AGENTS_WITH_OWN), {"limit": AGENTS_WITH_OWN_MAX})).all()
    return OrganizationCallHandling(
        own=own,
        resolved=resolve_settings(CallSettings(), own),
        agents_with_own=tuple(
            AgentOwnSettings(
                agent_id=UUID(str(r[0])),
                name=str(r[1]),
                own=settings_from_row(tuple(r)[2 : 2 + width]),
            )
            for r in agents
        ),
        agents_with_own_total=int(agents[0][2 + width]) if agents else 0,
    )


_LIVE_AGENT: Final = (
    "SELECT 1 FROM agents WHERE deleted_at IS NULL AND status IN ('live', 'paused') "
    "AND engine_agent_ref IS NOT NULL AND "
)
#: Per field: a live or ready agent (D-838) that inherits the account value, so changing it
#: moves a line.
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


_LIVE_AGENTS_FOR_UPDATE: Final = (
    "SELECT "
    + ", ".join(SETTING_FIELDS)
    + " FROM agents WHERE deleted_at IS NULL AND status IN ('live', 'paused') "
    "AND engine_agent_ref IS NOT NULL FOR UPDATE"
)
#: Per field: drop every agent's own value so the agent follows the account again.
_CLEAR_AGENT_FIELD: Final = {
    f: f"UPDATE agents SET {f} = NULL, updated_at = now() "
    f"WHERE deleted_at IS NULL AND {f} IS NOT NULL RETURNING id"
    for f in SETTING_FIELDS
}


@dataclass(frozen=True, slots=True)
class AllAgentsCallHandling:
    organization: OrganizationCallHandling
    #: The account defaults that moved.
    moved: tuple[str, ...]
    #: How many agents had a value of their own for a named setting, now dropped.
    agents_reset: int


async def set_call_handling_for_all_agents(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    changes: Mapping[str, object],
) -> AllAgentsCallHandling:
    """The "All my agents" save: the named settings become the account default (null follows
    Calevate's) and every agent's own value for them is dropped, in this one transaction.

    The alternative, writing the value onto each agent, would leave a new agent on the old
    default and every agent reading "only this agent" for a value they all share. The live
    apply is queued once for the client when any live agent's value in force moves, which is
    worked out from the rows before and after rather than "a live agent inherits": an agent
    whose own value is dropped moves even though it inherited nothing."""
    unknown = set(changes) - set(SETTING_FIELDS)
    if unknown:
        raise ValueError(f"not an account call handling field: {sorted(unknown)}")
    if not changes:
        raise ProblemError(
            kind="validation",
            code="call_setting_missing",
            title="Nothing to change",
            detail="Name at least one call setting to use on every agent.",
            remediation="Choose a setting and its value.",
        )
    cleaned = _clean(changes)
    refuse_invalid_settings(settings_of(cleaned))
    row = (await session.execute(text(_ORG_ROW_FOR_UPDATE))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    current = settings_from_row(tuple(row))
    wanted = settings_of({**as_mapping(current), **cleaned})
    live_before = [
        resolve_settings(settings_from_row(tuple(r)), current).values
        for r in (await session.execute(text(_LIVE_AGENTS_FOR_UPDATE))).all()
    ]
    after = resolve_settings(CallSettings(), wanted).values
    moved = tuple(f for f in SETTING_FIELDS if f in cleaned and cleaned[f] != getattr(current, f))
    if moved:
        await session.execute(text(_UPDATE_ORG), _binds(wanted))
    reset: set[UUID] = set()
    for field in SETTING_FIELDS:
        if field in cleaned:
            cleared = await session.execute(text(_CLEAR_AGENT_FIELD[field]))
            reset.update(UUID(str(r[0])) for r in cleared.all())
    if any(getattr(before, f) != getattr(after, f) for before in live_before for f in cleaned):
        await queue_live_apply(session, scope="tenant", tenant_id=tenant_id, reason="call_handling")
    log.info(
        "call_handling_set_for_all_agents",
        extra={"tenant_id": str(tenant_id), "changed": list(moved), "agents_reset": len(reset)},
    )
    return AllAgentsCallHandling(
        organization=await read_organization_call_handling(session),
        moved=moved,
        agents_reset=len(reset),
    )


def turn_detection_of(value: object) -> TurnDetection | None:
    """`agents.turn_detection` as the engine's word; its CHECK holds the column to these."""
    if value == "timer":
        return "timer"
    if value == "ear":
        return "ear"
    if value == "smart":
        return "smart"
    return None


_AGENT_TURN_DETECTION: Final = (
    "SELECT turn_detection, status, engine_agent_ref FROM agents "
    "WHERE id = :aid AND deleted_at IS NULL"
)


async def set_agent_turn_detection(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    mode: TurnDetection | None,
) -> tuple[AgentCallHandling, bool]:
    """Put one agent on its own turn detection, or back on the console's (None), so a mode
    can be tried on one agent without moving every client's (D-901). An operator's setting,
    never a client's: the console's mode is a platform decision. Answers the agent's call
    settings as they now resolve (the pause moves with the mode, `platform_turn_silence_ms`)
    and whether it moved; a move on a published agent queues its live apply."""
    row = (
        await session.execute(text(_AGENT_TURN_DETECTION + " FOR UPDATE"), {"aid": agent_id})
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    moved = turn_detection_of(row[0]) != mode
    if moved:
        await session.execute(
            text("UPDATE agents SET turn_detection = :mode, updated_at = now() WHERE id = :aid"),
            {"mode": mode, "aid": agent_id},
        )
        if is_published(row[1], row[2]):
            await queue_live_apply(
                session,
                scope="agent",
                tenant_id=tenant_id,
                agent_id=agent_id,
                reason="turn_detection",
            )
    log.info("agent_turn_detection_set", extra={"agent_id": str(agent_id), "moved": moved})
    return await read_agent_call_handling(session, agent_id), moved


__all__ = [
    "AGENTS_WITH_OWN_MAX",
    "AGENT_FIELDS",
    "AGENT_ONLY_FIELDS",
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
    "AgentOwnSettings",
    "AllAgentsCallHandling",
    "CallSettings",
    "EndCallOnFinish",
    "OrganizationCallHandling",
    "ResolvedSettings",
    "SettingSource",
    "TurnSilence",
    "as_mapping",
    "normalise_filler_lines",
    "opening_wait_available",
    "opening_waits_default",
    "platform_settings",
    "platform_turn_silence_ms",
    "read_agent_call_handling",
    "read_organization_call_handling",
    "refuse_invalid_settings",
    "refuse_opening_wait",
    "refuse_turn_silence_out_of_range",
    "resolve_end_call_on_finish",
    "resolve_settings",
    "resolve_turn_silence",
    "set_agent_call_handling",
    "set_agent_turn_detection",
    "set_call_handling_for_all_agents",
    "set_organization_call_handling",
    "settings_from_row",
    "settings_of",
    "turn_detection_of",
]
