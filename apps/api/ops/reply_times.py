"""How long callers waited for replies, across every client — `GET /v1/ops/reply-times` (D-770).

The figures are the voice platform's own, written once per call when it ends
(`calls.engine_quality`, a `calevate_shared.events.CallQuality`), each as that call's median,
p90 and max over its turns:

* `answer_ms_*`, THE reply time (D-902): the caller falling silent to the first word of the
  actual answer heard. A filler line or an acknowledgement that plays first does not end it.
  Null on calls from before 27 Oct 2026, which count as not measured, never as zero.
* `reply_ms_*`, the first SOUND of any kind, a filler included (shown as "first sound"). The
  gap between the two is how long fillers held the line. It replaced the transcript count of
  filler-led turns D-901 used, which could only guess where the platform now measures.
* `first_token_ms_*`, from the turn reaching the voice platform to the first speakable word.

(VERIFIED-VENDOR-DOCS: `CallQuality` in https://app.thinnest.ai/openapi.json, read 27 Oct
2026.) Beside them, the platform's live `slow_reply` problem (a reply that took more than 5 s
to start) from `call_engine_signals`.

AGGREGATION. For the per-call figures the unit is the CALL: a percentile of percentiles is
not a percentile of the turns. So "typical" is the median of the calls' own medians and "slow"
the 90th percentile of the calls' own p90s; every call weighs the same however many turns it
had. Below `P90_MIN_CALLS` calls the slow figure is withheld, because the p90 of fewer than
ten values is the maximum under another name.

THE SPLIT. Each call's per-turn timeline (`calls.engine_timeline`, `workers/call_timeline`)
gives every turn's steps: the wait before the turn was decided, the recogniser, the Ear check,
the model's first sentence, the voice, and when the model was asked. Those are real turns, so
their medians are taken over TURNS, grouped by the turn detection each call ran on (its
`voice_settings`), overall and per agent, so Ear and Timer can be compared on one agent.

THE TARGETS are two console settings (D-896): `reply_time_typical_target_ms` for the typical
answer time and `reply_time_slow_target_ms` for the slow one; a call is over target when its
own p90 answer time exceeds the slow target.

BY SETTING. Each call carries the call-handling settings its agent was published with when the
call began (`calls.voice_settings`, `agents/voice_stamp.py`), so every figure is also split by
them, with `not_recorded` for calls from before the stamp.

CROSS-CLIENT READ. `call_reply_scan` (migration d3f8b2c6a417) enters each live tenant with
its own `app.tenant_id` inside one statement, so no session ever holds a cross-tenant view
of a tenant table. It must be called from an `admin_session()`, the only session that can
enumerate tenants. The rows come into this process because percentiles do not merge across
groups; `MAX_CALLS` bounds that and a run that hits it says so (`complete=False`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, get_args
from uuid import UUID

from calevate_shared.events import CallTimeline, TurnTiming
from pydantic import BaseModel, ValidationError
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.billing.rates import PREMIUM_VOICE_TIER, VALUE_VOICE_TIER
from apps.api.core.settings import get_settings

DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 90

#: Below this many measured calls (or timed turns) a group reports no slow (p90) figure.
P90_MIN_CALLS = 10

#: Calls read per report. Above it the report covers the most recent `MAX_CALLS` and says so.
MAX_CALLS = 100_000

#: The per-agent tables and the worst-calls list are cut to these, worst first. Clients,
#: tiers and days are bounded by the client list, the two rungs and the window.
MAX_AGENT_ROWS = 50
MAX_WORST_CALLS = 20

#: Why a window has no reply-time figures. `no_calls`: no call connected and finished in it.
#: `not_reported`: calls finished, and the voice platform sent no reply times for any of them.
EmptyReason = Literal["no_calls", "not_reported"]

VoiceTierKey = Literal["clear", "studio", "not_metered"]

_SCAN_SQL = text(
    "SELECT s.scanned_tenant_id, o.name AS client_name, o.slug AS client_slug, s.call_id, "
    "s.agent_id, s.agent_name, s.started_at, s.slow_reply, s.voice_tier, "
    "(s.quality ->> 'turns')::float8 AS turns, "
    "(s.quality ->> 'answer_ms_median')::float8 AS answer_median, "
    "(s.quality ->> 'answer_ms_p90')::float8 AS answer_p90, "
    "(s.quality ->> 'answer_ms_max')::float8 AS answer_max, "
    "(s.quality ->> 'reply_ms_median')::float8 AS reply_median, "
    "(s.quality ->> 'reply_ms_p90')::float8 AS reply_p90, "
    "(s.quality ->> 'reply_ms_max')::float8 AS reply_max, "
    "(s.quality ->> 'first_token_ms_median')::float8 AS first_median, "
    "(s.quality ->> 'first_token_ms_p90')::float8 AS first_p90, "
    "(s.quality ->> 'long_silences')::float8 AS long_silences, "
    "(s.quality ->> 'interruptions')::float8 AS interruptions, "
    "(s.quality ->> 'model_errors')::float8 AS model_errors, "
    "(s.quality ->> 'backup_answers')::float8 AS rescues, "
    "(s.quality ->> 'knowledge_turns')::float8 AS knowledge_turns, "
    "s.voice_settings, s.timeline "
    "FROM call_reply_scan(:since) AS s "
    "JOIN organizations o ON o.id = s.scanned_tenant_id "
    "ORDER BY s.started_at DESC LIMIT :cap"
)


@dataclass(frozen=True, slots=True)
class _Call:
    tenant_id: UUID
    client_name: str
    client_slug: str
    call_id: UUID
    agent_id: UUID | None
    agent_name: str | None
    started_at: datetime
    slow_reply: bool
    voice_tier: VoiceTierKey
    turns: int | None
    reply_median: float | None
    reply_p90: float | None
    reply_max: float | None
    first_median: float | None
    first_p90: float | None
    long_silences: int | None
    interruptions: int | None
    model_errors: int | None
    rescues: int | None
    #: `agents/voice_stamp.stamp_of`'s record, or None for a call from before it.
    voice_settings: dict[str, Any] | None = None
    answer_median: float | None = None
    answer_p90: float | None = None
    answer_max: float | None = None
    knowledge_turns: int | None = None
    #: The call's timed turns; empty when none were fetched.
    timeline: tuple[TurnTiming, ...] = ()

    @property
    def measured(self) -> bool:
        """The platform sent any reply time for the call."""
        return self.reply_median is not None or self.answer_median is not None

    @property
    def answer_measured(self) -> bool:
        return self.answer_median is not None

    @property
    def slowness(self) -> float:
        """The call's p90 for ranking: the answer when measured, else the first sound, which
        is never later than the answer and so understates rather than inflates."""
        return self.answer_p90 if self.answer_p90 is not None else (self.reply_p90 or 0.0)


class ReplyTimeFigures(BaseModel):
    """One group's figures. A withheld or unreported figure is null, never zero."""

    #: Completed calls in the group, measured or not.
    calls: int
    #: Calls the voice platform sent any reply time for.
    calls_measured: int
    #: Calls it sent an answer time for (none before 27 Oct 2026).
    calls_answer_measured: int
    #: Median of the calls' own median wait for the first word of the actual answer.
    answer_typical_ms: float | None = None
    #: 90th percentile of the calls' own p90 answer time; null below `P90_MIN_CALLS`.
    answer_slow_ms: float | None = None
    #: The single slowest answer on any call in the group.
    answer_worst_ms: float | None = None
    #: The same three for the first sound of any kind, a filler line included.
    first_sound_typical_ms: float | None = None
    first_sound_slow_ms: float | None = None
    first_sound_worst_ms: float | None = None
    #: Median of the calls' median time from the turn reaching the voice platform to the
    #: first speakable word, and the 90th percentile of their p90s.
    first_token_typical_ms: float | None = None
    first_token_slow_ms: float | None = None
    #: Calls whose p90 answer time exceeded the slow target.
    calls_over_target: int
    #: Calls on which the platform reported a reply that took more than 5 s to start.
    slow_reply_problems: int
    #: Sums over the calls that reported each figure.
    turns: int
    model_errors: int
    rescues: int
    interruptions: int
    long_silences: int
    knowledge_turns: int


class ClientReplyTimes(ReplyTimeFigures):
    tenant_id: UUID
    client_name: str
    client_slug: str


class AgentReplyTimes(ReplyTimeFigures):
    tenant_id: UUID
    client_name: str
    client_slug: str
    agent_id: UUID | None
    agent_name: str | None


class TierReplyTimes(ReplyTimeFigures):
    #: The rung the call's minutes were metered on; `not_metered` before metering ran.
    tier: VoiceTierKey


class DayReplyTimes(ReplyTimeFigures):
    #: The IST calendar day the calls started on (D-709).
    day: date


#: The settings the report splits by, in the order the screen shows them.
SettingKey = Literal[
    "turn_detection",
    "known_facts",
    "known_facts_size",
    "filler_delay_ms",
    "early_answers",
    "turn_silence_ms",
]
SETTING_KEYS: tuple[SettingKey, ...] = get_args(SettingKey)

#: A call whose settings were not recorded (before D-896, or an agent not yet republished).
NOT_RECORDED = "not_recorded"

#: Known-facts size bands, in characters of the section: small enough to compare.
_SIZE_BANDS: tuple[tuple[int, str], ...] = ((2000, "under_2000"), (4000, "2000_to_4000"))


class SettingReplyTimes(ReplyTimeFigures):
    #: Which setting (`SETTING_KEYS`).
    setting: SettingKey
    #: Its value on these calls, as a closed-set string (`on`/`off`, `ear`, `2000`, ...),
    #: or `not_recorded`.
    value: str


class TurnSplit(BaseModel):
    """Medians over the timed turns of a group: where the wait for an answer went. A step
    no turn recorded is null."""

    #: The turn detection the calls ran on (`timer`, `ear`, `smart`) or `not_recorded`.
    turn_detection: str
    calls_timed: int
    turns_timed: int
    #: Caller stopped -> the first word of the actual answer heard; and its 90th percentile
    #: over turns, null below `P90_MIN_CALLS` turns.
    answer_ms: float | None = None
    answer_slow_ms: float | None = None
    #: Caller stopped -> the first sound of any kind.
    first_sound_ms: float | None = None
    wait_before_decision_ms: float | None = None
    recogniser_ms: float | None = None
    ear_check_ms: float | None = None
    model_first_sentence_ms: float | None = None
    voice_ms: float | None = None
    #: When the model was asked; negative when early answers asked it before the turn ended.
    model_asked_ms: float | None = None
    #: Turns whose first sound was a filler, and turns whose answer start was estimated
    #: because a filler spoke first.
    turns_filler_first: int
    turns_estimated: int


class AgentTurnSplit(TurnSplit):
    tenant_id: UUID
    client_name: str
    client_slug: str
    agent_id: UUID | None
    agent_name: str | None


class SlowCall(BaseModel):
    """One of the window's slowest calls, by its p90 answer time (its first sound's when the
    answer was not measured)."""

    call_id: UUID
    tenant_id: UUID
    client_name: str
    client_slug: str
    agent_id: UUID | None
    agent_name: str | None
    started_at: datetime
    voice_tier: VoiceTierKey
    turns: int | None
    answer_median_ms: float | None
    answer_p90_ms: float | None
    answer_max_ms: float | None
    first_sound_median_ms: float | None
    first_sound_p90_ms: float | None
    first_token_p90_ms: float | None
    slow_reply: bool
    model_errors: int | None
    knowledge_turns: int | None


class ReplyTimeReport(BaseModel):
    window_days: int
    #: The console targets, as read for this report: the typical answer time is judged
    #: against the first, each call's p90 answer time against the second.
    typical_target_ms: int
    slow_target_ms: int
    #: False when the window held more than `MAX_CALLS` calls and only the newest were read.
    complete: bool
    #: Set when there are no figures to show, saying why.
    empty_reason: EmptyReason | None
    overall: ReplyTimeFigures
    by_client: list[ClientReplyTimes]
    by_agent: list[AgentReplyTimes]
    #: How many agents had calls; `by_agent` holds at most `MAX_AGENT_ROWS` of them.
    agents_total: int
    by_tier: list[TierReplyTimes]
    by_day: list[DayReplyTimes]
    #: Every figure again per value of each call-handling setting (`SETTING_KEYS` order).
    by_setting: list[SettingReplyTimes]
    #: Step medians over timed turns, per turn detection, then per agent and turn detection
    #: (at most `MAX_AGENT_ROWS` rows). Only groups with a timed turn appear.
    split_by_turn_detection: list[TurnSplit]
    split_by_agent: list[AgentTurnSplit]
    worst_calls: list[SlowCall]


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """Linear interpolation between order statistics, as Postgres's `percentile_cont`."""
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _values[T](items: Iterable[T], pick: Callable[[T], float | int | None]) -> list[float]:
    return sorted(float(value) for item in items if (value := pick(item)) is not None)


def _total(calls: Iterable[_Call], pick: Callable[[_Call], int | None]) -> int:
    return sum(value for call in calls if (value := pick(call)) is not None)


def _median(values: list[float]) -> float | None:
    return _percentile(values, 0.5) if values else None


def _p90(values: list[float]) -> float | None:
    return _percentile(values, 0.9) if len(values) >= P90_MIN_CALLS else None


def figures(calls: list[_Call], *, target_ms: int) -> ReplyTimeFigures:
    """The group's figures under the module's aggregation rules."""
    measured = [call for call in calls if call.measured]
    answered = [call for call in calls if call.answer_measured]
    answer_worst = _values(answered, lambda c: c.answer_max)
    sound_worst = _values(measured, lambda c: c.reply_max)
    return ReplyTimeFigures(
        calls=len(calls),
        calls_measured=len(measured),
        calls_answer_measured=len(answered),
        answer_typical_ms=_median(_values(answered, lambda c: c.answer_median)),
        answer_slow_ms=_p90(_values(answered, lambda c: c.answer_p90)),
        answer_worst_ms=answer_worst[-1] if answer_worst else None,
        first_sound_typical_ms=_median(_values(measured, lambda c: c.reply_median)),
        first_sound_slow_ms=_p90(_values(measured, lambda c: c.reply_p90)),
        first_sound_worst_ms=sound_worst[-1] if sound_worst else None,
        first_token_typical_ms=_median(_values(measured, lambda c: c.first_median)),
        first_token_slow_ms=_p90(_values(measured, lambda c: c.first_p90)),
        calls_over_target=sum(
            1 for c in answered if c.answer_p90 is not None and c.answer_p90 > target_ms
        ),
        slow_reply_problems=sum(1 for c in calls if c.slow_reply),
        turns=_total(measured, lambda c: c.turns),
        model_errors=_total(measured, lambda c: c.model_errors),
        rescues=_total(measured, lambda c: c.rescues),
        interruptions=_total(measured, lambda c: c.interruptions),
        long_silences=_total(measured, lambda c: c.long_silences),
        knowledge_turns=_total(measured, lambda c: c.knowledge_turns),
    )


def turn_split(calls: list[_Call], *, turn_detection: str) -> TurnSplit:
    """Step medians over every timed turn of the group's calls."""
    turns = [turn for call in calls for turn in call.timeline]
    answers = _values(turns, lambda t: t.answer_ms)
    return TurnSplit(
        turn_detection=turn_detection,
        calls_timed=sum(1 for call in calls if call.timeline),
        turns_timed=len(turns),
        answer_ms=_median(answers),
        answer_slow_ms=_p90(answers),
        first_sound_ms=_median(_values(turns, lambda t: t.first_sound_ms)),
        wait_before_decision_ms=_median(_values(turns, lambda t: t.wait_before_decision_ms)),
        recogniser_ms=_median(_values(turns, lambda t: t.recogniser_ms)),
        ear_check_ms=_median(_values(turns, lambda t: t.ear_check_ms)),
        model_first_sentence_ms=_median(_values(turns, lambda t: t.model_first_sentence_ms)),
        voice_ms=_median(_values(turns, lambda t: t.voice_ms)),
        model_asked_ms=_median(_values(turns, lambda t: t.model_asked_ms)),
        turns_filler_first=sum(1 for t in turns if t.first_sound_kind == "filler"),
        turns_estimated=sum(1 for t in turns if t.answer_estimated),
    )


def _whole(value: object) -> int | None:
    return None if value is None else int(float(str(value)))


def _ms(value: object) -> float | None:
    return None if value is None else float(str(value))


def _tier(value: object) -> VoiceTierKey:
    """The metered rung (`billing.rates.VoiceTier`), or `not_metered` before metering ran."""
    if value == VALUE_VOICE_TIER:
        return VALUE_VOICE_TIER
    if value == PREMIUM_VOICE_TIER:
        return PREMIUM_VOICE_TIER
    return "not_metered"


def timeline_turns(value: object) -> tuple[TurnTiming, ...]:
    """A stored `calls.engine_timeline` as turns; a record this code cannot read is no
    turns rather than a failed report."""
    if not isinstance(value, dict):
        return ()
    try:
        return tuple(CallTimeline.model_validate(value).turns)
    except ValidationError:
        return ()


def _call(row: Row[Any]) -> _Call:
    m = row._mapping
    return _Call(
        tenant_id=UUID(str(m["scanned_tenant_id"])),
        client_name=str(m["client_name"]),
        client_slug=str(m["client_slug"]),
        call_id=UUID(str(m["call_id"])),
        agent_id=UUID(str(m["agent_id"])) if m["agent_id"] is not None else None,
        agent_name=str(m["agent_name"]) if m["agent_name"] is not None else None,
        started_at=m["started_at"],
        slow_reply=bool(m["slow_reply"]),
        voice_tier=_tier(m["voice_tier"]),
        turns=_whole(m["turns"]),
        answer_median=_ms(m["answer_median"]),
        answer_p90=_ms(m["answer_p90"]),
        answer_max=_ms(m["answer_max"]),
        reply_median=_ms(m["reply_median"]),
        reply_p90=_ms(m["reply_p90"]),
        reply_max=_ms(m["reply_max"]),
        first_median=_ms(m["first_median"]),
        first_p90=_ms(m["first_p90"]),
        long_silences=_whole(m["long_silences"]),
        interruptions=_whole(m["interruptions"]),
        model_errors=_whole(m["model_errors"]),
        rescues=_whole(m["rescues"]),
        knowledge_turns=_whole(m["knowledge_turns"]),
        voice_settings=m["voice_settings"] if isinstance(m["voice_settings"], dict) else None,
        timeline=timeline_turns(m["timeline"]),
    )


def setting_value(call: _Call, key: SettingKey) -> str:
    """The call's value for one setting as a closed-set string, or `NOT_RECORDED`."""
    stamp = call.voice_settings
    if stamp is None:
        return NOT_RECORDED
    if key == "known_facts_size":
        chars = stamp.get("known_facts_chars")
        if not isinstance(chars, int):
            return NOT_RECORDED
        if chars == 0:
            return "none"
        return next((band for ceiling, band in _SIZE_BANDS if chars < ceiling), "4000_plus")
    value = stamp.get(key)
    if value is None:
        return NOT_RECORDED
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def _value_of(key: SettingKey) -> Callable[[_Call], str]:
    return lambda call: setting_value(call, key)


def _grouped[K](calls: list[_Call], key: Callable[[_Call], K]) -> dict[K, list[_Call]]:
    groups: dict[K, list[_Call]] = {}
    for call in calls:
        groups.setdefault(key(call), []).append(call)
    return groups


def _setting_order(value: str) -> tuple[bool, str]:
    return (value == NOT_RECORDED, value)


def _worst_first(f: ReplyTimeFigures) -> tuple[float, float, int]:
    slowest = (
        f.answer_slow_ms
        or f.answer_typical_ms
        or f.first_sound_slow_ms
        or f.first_sound_typical_ms
        or 0.0
    )
    return (-f.calls_over_target, -slowest, -f.calls)


def _slow_call(call: _Call) -> SlowCall:
    return SlowCall(
        call_id=call.call_id,
        tenant_id=call.tenant_id,
        client_name=call.client_name,
        client_slug=call.client_slug,
        agent_id=call.agent_id,
        agent_name=call.agent_name,
        started_at=call.started_at,
        voice_tier=call.voice_tier,
        turns=call.turns,
        answer_median_ms=call.answer_median,
        answer_p90_ms=call.answer_p90,
        answer_max_ms=call.answer_max,
        first_sound_median_ms=call.reply_median,
        first_sound_p90_ms=call.reply_p90,
        first_token_p90_ms=call.first_p90,
        slow_reply=call.slow_reply,
        model_errors=call.model_errors,
        knowledge_turns=call.knowledge_turns,
    )


def _splits(calls: list[_Call]) -> tuple[list[TurnSplit], list[AgentTurnSplit]]:
    timed = [call for call in calls if call.timeline]
    mode = _value_of("turn_detection")
    by_mode = [
        turn_split(group, turn_detection=value)
        for value, group in sorted(
            _grouped(timed, mode).items(), key=lambda i: _setting_order(i[0])
        )
    ]
    by_agent = [
        AgentTurnSplit(
            tenant_id=tenant_id,
            client_name=group[0].client_name,
            client_slug=group[0].client_slug,
            agent_id=agent_id,
            agent_name=group[0].agent_name,
            **turn_split(group, turn_detection=value).model_dump(),
        )
        for (tenant_id, agent_id, value), group in _grouped(
            timed, lambda c: (c.tenant_id, c.agent_id, mode(c))
        ).items()
    ]
    by_agent.sort(
        key=lambda r: (
            r.client_name,
            r.agent_name or "",
            str(r.agent_id),
            *_setting_order(r.turn_detection),
        )
    )
    return by_mode, by_agent[:MAX_AGENT_ROWS]


def build_report(
    calls: list[_Call],
    *,
    days: int,
    typical_target_ms: int,
    slow_target_ms: int,
    complete: bool,
) -> ReplyTimeReport:
    """Every breakdown of one window's calls. Pure, so the rules are testable without a database."""
    # A call is over target when its own p90 answer time passes the slow target.
    target_ms = slow_target_ms
    overall = figures(calls, target_ms=target_ms)
    empty: EmptyReason | None = None
    if overall.calls == 0:
        empty = "no_calls"
    elif overall.calls_measured == 0:
        empty = "not_reported"

    by_client = [
        ClientReplyTimes(
            tenant_id=tenant_id,
            client_name=group[0].client_name,
            client_slug=group[0].client_slug,
            **figures(group, target_ms=target_ms).model_dump(),
        )
        for tenant_id, group in _grouped(calls, lambda c: c.tenant_id).items()
    ]
    by_client.sort(key=lambda row: (*_worst_first(row), row.client_name))

    agents = [
        AgentReplyTimes(
            tenant_id=tenant_id,
            client_name=group[0].client_name,
            client_slug=group[0].client_slug,
            agent_id=agent_id,
            agent_name=group[0].agent_name,
            **figures(group, target_ms=target_ms).model_dump(),
        )
        for (tenant_id, agent_id), group in _grouped(
            calls, lambda c: (c.tenant_id, c.agent_id)
        ).items()
    ]
    agents.sort(key=lambda row: (*_worst_first(row), row.client_name, row.agent_name or ""))

    tiers = _grouped(calls, lambda c: c.voice_tier)
    by_tier = [
        TierReplyTimes(tier=tier, **figures(tiers[tier], target_ms=target_ms).model_dump())
        for tier in ("clear", "studio", "not_metered")
        if tier in tiers
    ]

    days_of = _grouped(calls, lambda c: c.started_at.astimezone(IST).date())
    by_day = [
        DayReplyTimes(day=day, **figures(days_of[day], target_ms=target_ms).model_dump())
        for day in sorted(days_of)
    ]

    by_setting = [
        SettingReplyTimes(
            setting=key, value=value, **figures(group, target_ms=target_ms).model_dump()
        )
        for key in SETTING_KEYS
        for value, group in sorted(
            _grouped(calls, _value_of(key)).items(), key=lambda item: _setting_order(item[0])
        )
    ]

    split_by_mode, split_by_agent = _splits(calls)

    slowest = sorted(
        (c for c in calls if c.answer_p90 is not None or c.reply_p90 is not None),
        key=lambda c: (-c.slowness, -(c.answer_max or c.reply_max or 0.0)),
    )[:MAX_WORST_CALLS]

    return ReplyTimeReport(
        window_days=days,
        typical_target_ms=typical_target_ms,
        slow_target_ms=slow_target_ms,
        complete=complete,
        empty_reason=empty,
        overall=overall,
        by_client=by_client,
        by_agent=agents[:MAX_AGENT_ROWS],
        agents_total=len(agents),
        by_tier=by_tier,
        by_day=by_day,
        by_setting=by_setting,
        split_by_turn_detection=split_by_mode,
        split_by_agent=split_by_agent,
        worst_calls=[_slow_call(c) for c in slowest],
    )


async def reply_time_report(
    directory: AsyncSession, *, days: int = DEFAULT_WINDOW_DAYS
) -> ReplyTimeReport:
    """The window's report. `directory` must be an `admin_session()` (module docstring)."""
    window = max(1, min(days, MAX_WINDOW_DAYS))
    since = datetime.now(UTC) - timedelta(days=window)
    rows = (await directory.execute(_SCAN_SQL, {"since": since, "cap": MAX_CALLS + 1})).all()
    calls = [_call(row) for row in rows[:MAX_CALLS]]
    return build_report(
        calls,
        days=window,
        typical_target_ms=get_settings().reply_time_typical_target_ms,
        slow_target_ms=get_settings().reply_time_slow_target_ms,
        complete=len(rows) <= MAX_CALLS,
    )


__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "MAX_AGENT_ROWS",
    "MAX_CALLS",
    "MAX_WINDOW_DAYS",
    "MAX_WORST_CALLS",
    "NOT_RECORDED",
    "P90_MIN_CALLS",
    "SETTING_KEYS",
    "AgentReplyTimes",
    "AgentTurnSplit",
    "ClientReplyTimes",
    "DayReplyTimes",
    "ReplyTimeFigures",
    "ReplyTimeReport",
    "SettingKey",
    "SettingReplyTimes",
    "SlowCall",
    "TierReplyTimes",
    "TurnSplit",
    "build_report",
    "figures",
    "reply_time_report",
    "setting_value",
    "timeline_turns",
    "turn_split",
]
