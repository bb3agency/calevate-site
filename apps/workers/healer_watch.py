"""What the healer's scorer reads beyond the health score (D-987), and the healer's own
safety: one function per best-practice check the founder approved on 12 Nov 2026.

* **Silent calls** (`silent_agents`): answered calls with no turn or no voice report, which
  open the voice fallback even at one call (`workers/voice_fallback`).
* **Callers ringing back** (`repeat_callers`): the same caller ringing the agent again
  within `healer_repeat_call_minutes` of a short or silent call. Matched INSIDE Postgres on
  the call's own party column and returned as counts per agent, so no number reaches Python,
  a log or a ledger (hard rule 6). That is stronger than matching keyed hashes in Python,
  which would still hold every number in memory to hash it.
* **Failure domains** (`failing_agents`): agents whose callers heard a failure, by the
  voice the call spoke on (`healer/voice.failure_domain`: our Cartesia key for every
  Studio voice, the catalogue voice for Clear), so the scorer opens ONE incident and ONE
  page for a provider or a voice failing for many agents (`failing_domains`).
* **The call objective** (`objective_counts`, `burning`): "calls with no failure the
  caller heard", fleet-wide and per rung, judged on burn rate over a long and a short
  window each (Google SRE workbook, "Alerting on SLOs", multiwindow multi-burn-rate,
  read 12 Nov 2026): a fast burn pages, a slow burn is a ticket (an `attention` row).
* **The publish watch** (`publish_watch`): an agent's first calls after a script went live,
  scored like a window and compared with its own baseline; a clear drop proposes going back
  (`heal_proposals` `rollback_prompt`) without waiting for three bad windows.
* **The healer's own breaker** (`actions_recent`) and **post-incident summaries**
  (`summarize_resolved`): deterministic, from the ledger, no model (D-776).

Every threshold is a console setting read per call (`calevate_shared.config.Settings`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.core.settings import get_settings
from apps.api.healer import health, ledger, proposals
from apps.api.healer import voice as voices
from apps.api.healer.health import (
    HEARD_SQL,
    SHORT_CALL_S,
    SILENT_CALL_SQL,
    call_check_params,
    silent_call_sql,
)
from apps.api.healer.models import MAX_SUMMARY
from apps.api.healer.wording import incident_kind, progress

#: The groups the call objective is judged for.
OBJECTIVE_GROUPS: Final = ("fleet", "studio", "clear")

# --- silent calls ----------------------------------------------------------------------------


async def silent_agents(
    session: AsyncSession, *, start: datetime, end: datetime, now: datetime
) -> list[tuple[UUID, datetime]]:
    """Agents of this tenant with a silent answered call in the span, and the latest one."""
    rows = (
        await session.execute(
            text(
                "SELECT c.agent_id, max(coalesce(c.ended_at, c.created_at)) FROM calls c "
                "WHERE c.created_at >= :start AND c.created_at < :end AND NOT c.trial_call "
                "AND c.agent_id IS NOT NULL AND " + SILENT_CALL_SQL + " GROUP BY c.agent_id"
            ),
            {**call_check_params(now), "start": start, "end": end},
        )
    ).all()
    return [(UUID(str(r[0])), r[1]) for r in rows]


# --- callers ringing back ----------------------------------------------------------------------

#: The caller's party on a call: the number that rang in, or the number we rang.
_PARTY: Final = "CASE WHEN {a}.direction = 'inbound' THEN {a}.from_e164 ELSE {a}.to_e164 END"


@dataclass(frozen=True, slots=True)
class RingBacks:
    calls: int
    #: When the newest of them was recorded: a line check closed after it has seen them all.
    last_at: datetime


async def repeat_callers(session: AsyncSession) -> dict[UUID, RingBacks]:
    """Per agent, the calls inside `healer_repeat_call_window_minutes` that are the same
    caller ringing again within `healer_repeat_call_minutes` of a short or silent call."""
    settings = get_settings()
    first = _PARTY.format(a="a")
    rows = (
        await session.execute(
            text(
                "SELECT b.agent_id, count(DISTINCT b.id), max(b.created_at) FROM calls b "
                "JOIN calls a ON "
                "a.agent_id = b.agent_id AND a.id <> b.id AND b.direction = 'inbound' AND "
                f"b.from_e164 IS NOT NULL AND b.from_e164 = {first} AND "
                "b.started_at > coalesce(a.ended_at, a.started_at) AND b.started_at <= "
                "coalesce(a.ended_at, a.started_at) + make_interval(mins => :within) "
                "WHERE b.created_at > now() - make_interval(mins => :window) AND NOT a.trial_call "
                "AND (coalesce(a.duration_s, 0) < :short OR "
                + silent_call_sql("a")
                + " OR coalesce(a.ended_before_agent, false)) GROUP BY b.agent_id"
            ),
            {
                **call_check_params(datetime.now(IST)),
                "within": settings.healer_repeat_call_minutes,
                "window": settings.healer_repeat_call_window_minutes,
                "short": SHORT_CALL_S,
            },
        )
    ).all()
    return {UUID(str(r[0])): RingBacks(calls=int(r[1]), last_at=r[2]) for r in rows}


# --- failure domains ---------------------------------------------------------------------------


async def failing_agents(session: AsyncSession, *, minutes: int) -> dict[UUID, str]:
    """This tenant's agents whose callers heard a failure in the last `minutes`, each with
    the failure domain of the voice the failing call spoke on."""
    rows = (
        await session.execute(
            text(
                "SELECT c.agent_id, max(coalesce(c.voice_settings ->> 'engine_voice', "
                "a.engine_voice_id)) FROM calls c JOIN agents a ON a.id = c.agent_id "
                "WHERE c.created_at > now() - make_interval(mins => :m) AND " + HEARD_SQL + " "
                "GROUP BY c.agent_id"
            ),
            {**call_check_params(datetime.now(IST)), "m": minutes},
        )
    ).all()
    return {UUID(str(r[0])): voices.failure_domain(r[1]) for r in rows}


def failing_domains(agents: dict[tuple[UUID, UUID], str], *, at_least: int) -> dict[str, int]:
    """The domains with at least `at_least` failing agents (`(tenant, agent) -> domain`)."""
    counted = Counter(agents.values())
    return {domain: n for domain, n in counted.items() if n >= at_least}


# --- the call objective -----------------------------------------------------------------------


@dataclass
class ObjectiveCounts:
    """Calls and calls with a failure the caller heard, per group and window minutes."""

    calls: Counter[tuple[str, int]] = field(default_factory=Counter)
    heard: Counter[tuple[str, int]] = field(default_factory=Counter)

    def add(self, other: ObjectiveCounts) -> None:
        self.calls.update(other.calls)
        self.heard.update(other.heard)


def objective_windows() -> tuple[int, int, int, int]:
    s = get_settings()
    return (
        s.healer_slo_fast_long_minutes,
        s.healer_slo_fast_short_minutes,
        s.healer_slo_slow_long_minutes,
        s.healer_slo_slow_short_minutes,
    )


async def objective_counts(session: AsyncSession) -> ObjectiveCounts:
    """This tenant's real finished calls in each objective window, by rung."""
    windows = objective_windows()
    longest = max(windows)
    rows = (
        await session.execute(
            text(
                "SELECT coalesce(c.voice_settings ->> 'engine_voice', a.engine_voice_id), "
                "extract(epoch FROM now() - c.created_at) / 60, " + HEARD_SQL + " FROM calls c "
                "JOIN agents a ON a.id = c.agent_id WHERE c.created_at > now() - "
                "make_interval(mins => :m) AND NOT c.trial_call AND c.status IN ('completed', "
                "'failed')"
            ),
            {**call_check_params(datetime.now(IST)), "m": longest},
        )
    ).all()
    found = ObjectiveCounts()
    for voice_id, age, heard in rows:
        for minutes in windows:
            if float(age) > minutes:
                continue
            for group in ("fleet", voices.rung_of(voice_id)):
                found.calls[(group, minutes)] += 1
                found.heard[(group, minutes)] += int(bool(heard))
    return found


def burn_rate(heard: int, calls: int) -> Decimal:
    """How many times faster than the objective allows the error budget is spent."""
    budget = Decimal(1000 - get_settings().healer_slo_target_permille) / Decimal(1000)
    if calls <= 0 or budget <= 0:
        return Decimal(0)
    return (Decimal(heard) / Decimal(calls)) / budget


@dataclass(frozen=True, slots=True)
class Burn:
    group: str
    fast: bool
    rate: Decimal
    calls: int


def burning(counts: ObjectiveCounts) -> list[Burn]:
    """The groups burning their error budget: both windows of a pair over its rate."""
    s = get_settings()
    fast_long, fast_short, slow_long, slow_short = objective_windows()
    pairs = (
        (True, fast_long, fast_short, Decimal(s.healer_slo_fast_burn_tenths) / 10),
        (False, slow_long, slow_short, Decimal(s.healer_slo_slow_burn_tenths) / 10),
    )
    found: list[Burn] = []
    for group in OBJECTIVE_GROUPS:
        for fast, long_m, short_m, threshold in pairs:
            calls = counts.calls[(group, long_m)]
            if calls < s.healer_slo_min_calls:
                continue
            long_rate = burn_rate(counts.heard[(group, long_m)], calls)
            short_rate = burn_rate(counts.heard[(group, short_m)], counts.calls[(group, short_m)])
            if long_rate >= threshold and short_rate >= threshold:
                found.append(Burn(group=group, fast=fast, rate=long_rate, calls=calls))
                break
    return found


# --- the publish watch -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublishDrop:
    agent_id: UUID
    score: Decimal
    baseline: Decimal
    calls: int
    proposed: bool


async def publish_watch(
    session: AsyncSession, *, tenant_id: UUID, now: datetime
) -> list[PublishDrop]:
    """Agents whose live script went live inside `healer_publish_watch_hours`, with at least
    `healer_publish_watch_calls` real calls since, scoring `healer_publish_watch_drop_points`
    or more below their own baseline. Each is proposed going back once per publish."""
    s = get_settings()
    rows = (
        await session.execute(
            text(
                "SELECT a.id, pv.created_at FROM agents a JOIN prompt_versions pv ON pv.id = "
                "COALESCE(a.live_prompt_id, a.system_prompt_id) WHERE a.deleted_at IS NULL "
                "AND pv.created_at > now() - make_interval(hours => :h) AND NOT EXISTS "
                "(SELECT 1 FROM heal_proposals p WHERE p.agent_id = a.id AND p.kind = "
                "'rollback_prompt' AND p.created_at >= pv.created_at)"
            ),
            {"h": s.healer_publish_watch_hours},
        )
    ).all()
    drops: list[PublishDrop] = []
    for agent_id, published_at in rows:
        counted = await health.count_between(
            session, start=published_at, end=now, agent_id=agent_id
        )
        if not counted or counted[0].calls < s.healer_publish_watch_calls:
            continue
        value = health.score(counted[0])
        baseline = await health.baseline_for(session, agent_id=agent_id, start=published_at)
        if baseline is None or baseline - value < s.healer_publish_watch_drop_points:
            continue
        made = await proposals.propose_for(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            incident_id=None,
            worst_signal=None,
            since=now,
        )
        drops.append(
            PublishDrop(
                agent_id=agent_id,
                score=value,
                baseline=baseline,
                calls=counted[0].calls,
                proposed="rollback_prompt" in made,
            )
        )
    return drops


# --- the healer's own safety -------------------------------------------------------------------


async def actions_recent(session: AsyncSession) -> int:
    """Automatic acting steps (act, protect, restore) the healer took inside
    `healer_action_breaker_minutes`, every playbook together."""
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM heal_actions WHERE actor_type = 'healer' AND outcome = "
                    "'ok' AND step IN ('act', 'protect', 'restore') AND at > now() - "
                    "make_interval(mins => :m)"
                ),
                {"m": get_settings().healer_action_breaker_minutes},
            )
        ).scalar_one()
    )


# --- post-incident summaries -------------------------------------------------------------------

#: The newest ledger rows a summary reads per incident.
SUMMARY_STEPS: Final = 40


def _ist(at: datetime) -> str:
    return at.astimezone(IST).strftime("%d %b %H:%M IST")


def _lasted(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def summary_of(
    *,
    trigger_code: str,
    playbook: str,
    automatic: bool,
    attempts: int,
    last_outcome: str | None,
    escalated: bool,
    opened_at: datetime,
    resolved_at: datetime,
    steps: list[ledger.ActionRow],
) -> str:
    """A draft post-incident summary from the ledger alone: what it was, when, what the
    healer did step by step, and how it ended. Deterministic; the founder edits nothing."""
    kind = incident_kind(trigger_code)
    tally = Counter(f"{s.step} {s.outcome}" for s in steps)
    lines = [
        f"{kind.title}.",
        f"Opened {_ist(opened_at)}, closed {_ist(resolved_at)} "
        f"({_lasted(resolved_at - opened_at)}). Playbook {playbook}.",
        "Ended: "
        + progress(
            playbook=playbook,
            automatic=automatic,
            state="resolved",
            attempts=attempts,
            last_outcome=last_outcome,
            escalated=escalated,
        )
        + ".",
        "Steps: " + ", ".join(f"{n} {k}" for k, n in sorted(tally.items())) + "."
        if tally
        else "Steps: none recorded.",
        "Timeline:",
    ]
    for step in sorted(steps, key=lambda s: s.at):
        who = "" if step.actor_type == "healer" else f" by {step.actor_type}"
        detail = f": {step.detail}" if step.detail else ""
        lines.append(f"- {_ist(step.at)} {step.step} {step.outcome}{who}{detail}")
    lines.append(f"Next step if it recurs: {kind.next_step}")
    text_out = "\n".join(lines)
    return text_out if len(text_out) <= MAX_SUMMARY else text_out[: MAX_SUMMARY - 1] + "…"


__all__ = [
    "OBJECTIVE_GROUPS",
    "SUMMARY_STEPS",
    "Burn",
    "ObjectiveCounts",
    "PublishDrop",
    "RingBacks",
    "actions_recent",
    "burn_rate",
    "burning",
    "failing_agents",
    "failing_domains",
    "objective_counts",
    "publish_watch",
    "repeat_callers",
    "silent_agents",
    "summary_of",
]
