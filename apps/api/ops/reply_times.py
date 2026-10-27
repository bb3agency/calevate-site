"""How long callers waited for replies, across every client — `GET /v1/ops/reply-times` (D-770).

The figures are the voice platform's own, written once per call when it ends
(`calls.engine_quality`, a `calevate_shared.events.CallQuality`): `reply_ms_*` is the wait
from the caller falling silent to the agent's first audio, and `first_token_ms_*` runs from
the turn reaching the voice platform to the first speakable word, not from the caller's
speech end, each as that call's median, p90 and max over its turns
(VERIFIED-VENDOR-DOCS: `thinnest-findings/mirror/snapshots/2026-10-13/pages/api-reference/
calls/get-call.md:327-335,984-1080`; both start points VENDOR-STATED in
`docs/vendor/thinnest-replies-2026-10-12.md` §25.0). Beside them, the platform's live
`slow_reply` problem (a reply that took more than 5 s to start, :300-307) from
`call_engine_signals`.

FIRST SOUND, NOT THE ANSWER (D-901). A filler line (`voice.thinkingLines`, said once a reply
is slower than the filler delay) or an Ear acknowledgement that plays first ENDS the reply
measurement, and the time to the first word of the answer itself is not reported
(VENDOR-STATED, ThinnestAI's email of 27 Oct 2026, `docs/vendor/thinnest-replies-2026-10-12.md`
§37). So every reply figure here is the time to the agent's first sound, and on a call whose
slow replies were covered by fillers it sits near the filler delay however long the answer
took. Nothing here claims a time to the answer. What the transcript does let us see, the agent
turns that opened with a filler (`CallQuality.filler_turns`, `ops/filler_turns.py`), gives
`calls_with_filler` and a typical figure over the calls with none found
(`reply_typical_no_filler_ms`), which the filler timer cannot flatter. Whether fillers are
written into the transcript at all is UNKNOWN, so "none found" is not "none played".

AGGREGATION. The unit is the CALL, not the turn: the platform publishes per-call summaries,
not turns, and a percentile of percentiles is not a percentile of the underlying turns. So
"typical" is the median of the calls' own medians, and "slow" is the 90th percentile of
the calls' own p90s — "nine calls in ten had their slowest tenth of replies faster than
this". Every call weighs the same however many turns it had. Below `P90_MIN_CALLS` measured
calls the slow figure is withheld, because the p90 of fewer than ten values is the maximum
under another name.

THE TARGETS are two console settings (D-896, founder 27 Oct 2026): `reply_time_typical_target_ms`
(1,600) for the typical figure and `reply_time_slow_target_ms` (2,200) for the slow one; a
call is over target when its own p90 reply exceeds the slow target. They replaced one 500 ms
goal the model's first word alone (~1 s) cannot meet
(`docs/evidence/latency-research-2026-10-27.md`).

BY SETTING. Each call carries the call-handling settings its agent was published with when
the call began (`calls.voice_settings`, `agents/voice_stamp.py`), so every figure is also split
by turn detection, the known facts (on/off and size), the filler delay, early answers and the
end-of-turn pause, with `not_recorded` for calls from before the stamp. Whether a turn searched
knowledge is not split: the voice platform reports no per-turn lookup (asked, T3 in
`docs/vendor/thinnest-replies-2026-10-12.md`).

CROSS-CLIENT READ. `call_reply_scan` (migration d3f8b2c6a417) enters each live tenant with
its own `app.tenant_id` inside one statement, so no session ever holds a cross-tenant view
of a tenant table and the walk costs no pooled session per client. It must be called from an
`admin_session()`, the only session that can enumerate tenants. The rows come into this
process because percentiles do not merge across groups; `MAX_CALLS` bounds that and a run
that hits it says so (`complete=False`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.billing.rates import PREMIUM_VOICE_TIER, VALUE_VOICE_TIER
from apps.api.core.settings import get_settings

DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 90

#: Below this many measured calls a group reports no slow (p90) figure.
P90_MIN_CALLS = 10

#: Calls read per report. Above it the report covers the most recent `MAX_CALLS` and says so.
MAX_CALLS = 100_000

#: The per-agent table and the worst-calls list are cut to these, worst first. Clients,
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
    "(s.quality ->> 'reply_ms_median')::float8 AS reply_median, "
    "(s.quality ->> 'reply_ms_p90')::float8 AS reply_p90, "
    "(s.quality ->> 'reply_ms_max')::float8 AS reply_max, "
    "(s.quality ->> 'first_token_ms_median')::float8 AS first_median, "
    "(s.quality ->> 'first_token_ms_p90')::float8 AS first_p90, "
    "(s.quality ->> 'long_silences')::float8 AS long_silences, "
    "(s.quality ->> 'interruptions')::float8 AS interruptions, "
    "(s.quality ->> 'model_errors')::float8 AS model_errors, "
    "(s.quality ->> 'backup_answers')::float8 AS rescues, "
    "(s.quality ->> 'filler_turns')::float8 AS filler_turns, s.voice_settings "
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
    #: Agent turns the transcript shows opening with a filler line; None when not counted.
    filler_turns: int | None = None

    @property
    def measured(self) -> bool:
        return self.reply_median is not None

    @property
    def filler_found(self) -> bool:
        return bool(self.filler_turns)


class ReplyTimeFigures(BaseModel):
    """One group's figures. A withheld or unreported figure is null, never zero."""

    #: Completed calls in the group, measured or not.
    calls: int
    #: Calls the voice platform sent reply times for.
    calls_measured: int
    #: Median of the measured calls' own median reply time: to the agent's first SOUND, which
    #: a filler line can be (module docstring).
    reply_typical_ms: float | None = None
    #: Measured calls whose transcript shows at least one agent turn opening with a filler.
    calls_with_filler: int
    #: The typical figure over measured calls with no filler found, whose replies the filler
    #: timer did not cut short; null when every measured call had one.
    reply_typical_no_filler_ms: float | None = None
    #: 90th percentile of the measured calls' own p90 reply time; null below `P90_MIN_CALLS`.
    reply_slow_ms: float | None = None
    #: The single slowest reply on any call in the group.
    reply_worst_ms: float | None = None
    #: Median of the calls' median time from the turn reaching the voice platform to the
    #: first speakable word.
    first_token_typical_ms: float | None = None
    #: 90th percentile of the calls' p90 of that time.
    first_token_slow_ms: float | None = None
    #: Measured calls whose p90 reply exceeded the target.
    calls_over_target: int
    #: Calls on which the platform reported a reply that took more than 5 s to start.
    slow_reply_problems: int
    #: Sums over the calls that reported each figure.
    turns: int
    model_errors: int
    rescues: int
    interruptions: int
    long_silences: int


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


class SlowCall(BaseModel):
    """One of the window's slowest calls, by its p90 reply time."""

    call_id: UUID
    tenant_id: UUID
    client_name: str
    client_slug: str
    agent_id: UUID | None
    agent_name: str | None
    started_at: datetime
    voice_tier: VoiceTierKey
    turns: int | None
    reply_median_ms: float | None
    reply_p90_ms: float | None
    reply_max_ms: float | None
    first_token_p90_ms: float | None
    slow_reply: bool
    model_errors: int | None
    #: Agent turns the transcript shows opening with a filler line; null when not counted.
    filler_turns: int | None = None


class ReplyTimeReport(BaseModel):
    window_days: int
    #: The console targets, as read for this report: the typical figure is judged against
    #: the first, each call's p90 against the second.
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
    worst_calls: list[SlowCall]


def _percentile(ordered: list[float], fraction: float) -> float:
    """Linear interpolation between order statistics, as Postgres's `percentile_cont`."""
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _values(calls: Iterable[_Call], pick: Callable[[_Call], float | None]) -> list[float]:
    return sorted(value for call in calls if (value := pick(call)) is not None)


def _total(calls: Iterable[_Call], pick: Callable[[_Call], int | None]) -> int:
    return sum(value for call in calls if (value := pick(call)) is not None)


def _median(values: list[float]) -> float | None:
    return _percentile(values, 0.5) if values else None


def _p90(values: list[float]) -> float | None:
    return _percentile(values, 0.9) if len(values) >= P90_MIN_CALLS else None


def figures(calls: list[_Call], *, target_ms: int) -> ReplyTimeFigures:
    """The group's figures under the module's aggregation rules."""
    measured = [call for call in calls if call.measured]
    worst = _values(measured, lambda c: c.reply_max)
    return ReplyTimeFigures(
        calls=len(calls),
        calls_measured=len(measured),
        reply_typical_ms=_median(_values(measured, lambda c: c.reply_median)),
        calls_with_filler=sum(1 for c in measured if c.filler_found),
        reply_typical_no_filler_ms=_median(
            _values((c for c in measured if not c.filler_found), lambda c: c.reply_median)
        ),
        reply_slow_ms=_p90(_values(measured, lambda c: c.reply_p90)),
        reply_worst_ms=worst[-1] if worst else None,
        first_token_typical_ms=_median(_values(measured, lambda c: c.first_median)),
        first_token_slow_ms=_p90(_values(measured, lambda c: c.first_p90)),
        calls_over_target=sum(
            1 for c in measured if c.reply_p90 is not None and c.reply_p90 > target_ms
        ),
        slow_reply_problems=sum(1 for c in calls if c.slow_reply),
        turns=_total(measured, lambda c: c.turns),
        model_errors=_total(measured, lambda c: c.model_errors),
        rescues=_total(measured, lambda c: c.rescues),
        interruptions=_total(measured, lambda c: c.interruptions),
        long_silences=_total(measured, lambda c: c.long_silences),
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
        reply_median=_ms(m["reply_median"]),
        reply_p90=_ms(m["reply_p90"]),
        reply_max=_ms(m["reply_max"]),
        first_median=_ms(m["first_median"]),
        first_p90=_ms(m["first_p90"]),
        long_silences=_whole(m["long_silences"]),
        interruptions=_whole(m["interruptions"]),
        model_errors=_whole(m["model_errors"]),
        rescues=_whole(m["rescues"]),
        filler_turns=_whole(m["filler_turns"]),
        voice_settings=m["voice_settings"] if isinstance(m["voice_settings"], dict) else None,
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


def _worst_first(f: ReplyTimeFigures) -> tuple[float, float, int]:
    return (-f.calls_over_target, -(f.reply_slow_ms or f.reply_typical_ms or 0.0), -f.calls)


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
        reply_median_ms=call.reply_median,
        reply_p90_ms=call.reply_p90,
        reply_max_ms=call.reply_max,
        first_token_p90_ms=call.first_p90,
        slow_reply=call.slow_reply,
        model_errors=call.model_errors,
        filler_turns=call.filler_turns,
    )


def build_report(
    calls: list[_Call],
    *,
    days: int,
    typical_target_ms: int,
    slow_target_ms: int,
    complete: bool,
) -> ReplyTimeReport:
    """Every breakdown of one window's calls. Pure, so the rules are testable without a database."""
    # A call is over target when its own p90 passes the slow target.
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
            _grouped(calls, _value_of(key)).items(),
            key=lambda item: (item[0] == NOT_RECORDED, item[0]),
        )
    ]

    slowest = sorted(
        (c for c in calls if c.reply_p90 is not None),
        key=lambda c: (-(c.reply_p90 or 0.0), -(c.reply_max or 0.0)),
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
    "ClientReplyTimes",
    "DayReplyTimes",
    "ReplyTimeFigures",
    "ReplyTimeReport",
    "SettingKey",
    "SettingReplyTimes",
    "SlowCall",
    "TierReplyTimes",
    "build_report",
    "figures",
    "reply_time_report",
    "setting_value",
]
