"""Pip speaks up on its own (D-936): what the hourly detectors notice, and the notes they leave.

A note is one line and one button at the top of Pip's panel. It is in-app only: nothing here
mails, messages or rings anybody, so no quiet-hours rule applies to it, and the detector run
is scheduled inside the IST working day anyway (`apps/workers/settings.py`).

WHAT PIP SAYS, AND WHAT IT LEAVES TO THE SCREENS THAT ALREADY SAY IT. Before this module the
account was already told things in six places: the bell (the needs-attention queue, the
announcements and finished Pip plans, `notifications/service.py`), the dashboard's "What
needs you today" and "This week" blocks, the setup checklist's evidence nudges
(`tenancy/setup_nudges.py`), the healer's line notices and emails (`healer/notices.py`), the
low-credit emails (`workers/wallet_alerts.py`), the hot-lead email and team alerts
(`workers/notifications.py`, `team_alerts/`), and the weekly knowledge digest
(`workers/kb_aggregation.py`). A Pip note either says something none of those says, or it IS
one of their items, shown in Pip's voice with a link and no stored copy:

* STORED (a detector, a row in `copilot_notes`): a hot lead nobody has called back for N
  hours (the bell says a lead is hot, nothing says it has been left); credit forecast to run
  out within N days while still above the low-credit line (`credit_low` and the emails fire
  at the line, the forecast is only on the billing screen); one unanswered question asked on
  N calls in a week whose topic no unfinished setup step covers (the setup nudge says the
  others); a good week (the dashboard shows the figures, nothing says "this went well").
* LINKED (read live, never stored): stopped answering, a stalled campaign, failing
  deliveries, a broken in-call action and low credit are the needs-attention queue's own
  counts; a line problem is the healer's open incident. Missed-call spikes against an
  agent's own baseline and degraded knowledge ARE the healer's `broken` and `knowledge`
  signals, so they arrive here as its incident rather than as a second detector.

DEDUPE AND RATE. One open note per (kind, subject) — the partial unique index
`uq_copilot_notes_open_subject` — so a condition that lasts three days is one note whose
counts move, resolved when the condition clears. `episode_key` (subject and the IST day it
opened) is unique for ever, so a condition that clears and returns the same day is not
noted twice that day. At most `pip_notes_daily_cap` NEW notes per account per IST day,
spent in the order of `DETECTORS` (most urgent first).

Every payload holds ids and counts only (hard rule 6); a line is composed when it is read,
from the rows those ids point at, under the reader's RLS.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import get_balance, low_balance_line, plan_tier_of
from apps.api.billing.trials import read_trial
from apps.api.billing.wallet import read_runway
from apps.api.copilot.navigation import _may_open, find_screen
from apps.api.core.settings import get_settings
from apps.api.crm import attention
from apps.api.crm.service import dashboard
from apps.api.db.base import uuid7
from apps.api.tenancy import business_profile as bp
from apps.api.tenancy.models import PROFILE_STEPS
from apps.api.tenancy.setup_nudges import GAP_TOPIC_STEP

NoteKind = Literal["hot_lead_waiting", "balance_runway", "knowledge_gap_repeat", "good_week"]

#: How long a resolved or dismissed note is kept before the detector run prunes it.
KEEP_DAYS: Final = 30
#: How many open notes the panel shows at most.
MAX_SHOWN: Final = 20
#: How far back a hot lead or a knowledge-gap occurrence counts.
LEAD_WINDOW: Final = timedelta(days=attention.WINDOW_DAYS)
GAP_WINDOW: Final = timedelta(days=7)
#: How many gaps one run may note, and how many lead ids a hot-lead note carries.
MAX_GAPS: Final = 3
MAX_LEAD_IDS: Final = 20
#: A good week needs at least this many calls: two calls after one is not news.
GOOD_WEEK_MIN_CALLS: Final = 10
#: The fallback step `setup_nudges` gives a gap topic it does not map.
_FALLBACK_STEP: Final = "faqs"


@dataclass(frozen=True, slots=True)
class Detection:
    kind: NoteKind
    subject: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Thresholds:
    hot_lead_hours: int
    runway_days: int
    gap_repeat_calls: int
    good_week_percent: int
    daily_cap: int

    @classmethod
    def from_settings(cls) -> Thresholds:
        s = get_settings()
        return cls(
            hot_lead_hours=s.pip_notes_hot_lead_hours,
            runway_days=s.pip_notes_runway_days,
            gap_repeat_calls=s.pip_notes_gap_repeat_calls,
            good_week_percent=s.pip_notes_good_week_percent,
            daily_cap=s.pip_notes_daily_cap,
        )


def ist_day(now: datetime) -> str:
    return now.astimezone(IST).date().isoformat()


def ist_week(now: datetime) -> str:
    year, week, _ = now.astimezone(IST).isocalendar()
    return f"week:{year}-W{week:02d}"


def _ist_midnight(now: datetime) -> datetime:
    local = now.astimezone(IST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


# --- detectors ------------------------------------------------------------------------

_HOT_WAITING_SQL: Final = (
    "SELECT l.id, count(*) OVER () FROM leads l "
    "WHERE l.status = 'hot' AND l.deleted_at IS NULL "
    "  AND COALESCE(l.status_set_at, l.updated_at) < :cutoff "
    "  AND COALESCE(l.status_set_at, l.updated_at) > :since "
    "  AND NOT EXISTS (SELECT 1 FROM calls c WHERE c.lead_id = l.id "
    "                  AND c.created_at > COALESCE(l.status_set_at, l.updated_at)) "
    # A call-back the agent promised is the Call-backs screen's, and is not "left".
    "  AND NOT EXISTS (SELECT 1 FROM scheduled_callbacks s WHERE s.lead_id = l.id "
    "                  AND s.status IN ('scheduled', 'dialing')) "
    "ORDER BY COALESCE(l.status_set_at, l.updated_at), l.id LIMIT :lim"
)


async def detect_hot_leads(
    session: AsyncSession, *, now: datetime, thresholds: Thresholds
) -> list[Detection]:
    rows = (
        await session.execute(
            text(_HOT_WAITING_SQL),
            {
                "cutoff": now - timedelta(hours=thresholds.hot_lead_hours),
                "since": now - LEAD_WINDOW,
                "lim": MAX_LEAD_IDS,
            },
        )
    ).all()
    if not rows:
        return []
    return [
        Detection(
            kind="hot_lead_waiting",
            subject="account",
            payload={
                "count": int(rows[0][1]),
                "hours": thresholds.hot_lead_hours,
                "lead_ids": [str(r[0]) for r in rows],
            },
        )
    ]


async def detect_runway(
    session: AsyncSession, *, tenant_id: UUID, now: datetime, thresholds: Thresholds
) -> list[Detection]:
    """The wallet's own projection (`wallet.read_runway`), never a second one. Silent for an
    invoiced client, during a trial (the wallet limits nothing then, D-536), and below the
    low-credit line, where the needs-attention queue and the emails already speak."""
    if await plan_tier_of(session, tenant_id) not in PREPAID_TIERS:
        return []
    trial = await read_trial(session, tenant_id=tenant_id)
    if trial is not None and trial.is_active(at=now):
        return []
    balance = await get_balance(session, tenant_id=tenant_id)
    if balance.amount_inr < await low_balance_line(session, tenant_id=tenant_id):
        return []
    runway, _ = await read_runway(session, tenant_id=tenant_id, balance=balance, now=now)
    if runway.basis != "projected" or runway.days is None or runway.days > thresholds.runway_days:
        return []
    return [Detection(kind="balance_runway", subject="account", payload={"days": runway.days})]


_GAP_REPEAT_SQL: Final = (
    "SELECT g.id, g.topic_key, count(DISTINCT o.call_id) AS calls "
    "FROM knowledge_gap_occurrences o "
    "JOIN knowledge_gaps g ON g.tenant_id = o.tenant_id AND g.agent_id = o.agent_id "
    "  AND g.topic_key = o.topic_key "
    "WHERE g.status = 'open' AND o.created_at > :since "
    "GROUP BY g.id, g.topic_key HAVING count(DISTINCT o.call_id) >= :n "
    "ORDER BY calls DESC, g.id LIMIT :lim"
)


async def detect_gaps(
    session: AsyncSession, *, tenant_id: UUID, now: datetime, thresholds: Thresholds
) -> list[Detection]:
    """While the setup checklist is unfinished it nudges for a gap whose step is not done
    (`setup_nudges`), so such a gap is its line, not a note. A finished checklist is off the
    dashboard (`on_dashboard`), and then every repeated gap is Pip's to say."""
    rows = (
        await session.execute(
            text(_GAP_REPEAT_SQL),
            {"since": now - GAP_WINDOW, "n": thresholds.gap_repeat_calls, "lim": MAX_GAPS * 3},
        )
    ).all()
    if not rows:
        return []
    profile = await bp.load_profile(session, tenant_id=tenant_id)
    unfinished = (
        set()
        if bp.setup_complete(profile)
        else {step for step in PROFILE_STEPS if bp.step_state(profile, step) != "done"}
    )
    found = [
        Detection(
            kind="knowledge_gap_repeat",
            subject=str(gap_id),
            payload={"gap_id": str(gap_id), "calls": int(calls)},
        )
        for gap_id, topic, calls in rows
        if GAP_TOPIC_STEP.get(str(topic), _FALLBACK_STEP) not in unfinished
    ]
    return found[:MAX_GAPS]


async def detect_good_week(
    session: AsyncSession, *, now: datetime, thresholds: Thresholds
) -> list[Detection]:
    """The dashboard's own week figures (`crm.service.dashboard`), so this and "This week"
    cannot disagree about what the week was."""
    del now
    figures = await dashboard(session)
    factor = Decimal(100 + thresholds.good_week_percent) / Decimal(100)
    calls_up = figures.calls_7d >= GOOD_WEEK_MIN_CALLS and Decimal(
        figures.calls_7d
    ) >= factor * Decimal(max(figures.calls_prev_7d, 1))
    leads_up = figures.leads_new_7d > 0 and Decimal(figures.leads_new_7d) >= factor * Decimal(
        max(figures.leads_new_prev_7d, 1)
    )
    if not (calls_up and leads_up):
        return []
    return [
        Detection(
            kind="good_week",
            subject="",  # filled with the ISO week by the run
            payload={
                "calls": figures.calls_7d,
                "calls_prev": figures.calls_prev_7d,
                "leads": figures.leads_new_7d,
                "leads_prev": figures.leads_new_prev_7d,
            },
        )
    ]


# --- the run ----------------------------------------------------------------------------


async def _open_subjects(session: AsyncSession, kind: NoteKind) -> dict[str, str]:
    rows = await session.execute(
        text(
            "SELECT subject, payload::text FROM copilot_notes "
            "WHERE kind = :k AND resolved_at IS NULL"
        ),
        {"k": kind},
    )
    return {str(r[0]): str(r[1]) for r in rows.all()}


async def _resolve(
    session: AsyncSession, kind: NoteKind, subjects: Sequence[str], now: datetime
) -> int:
    if not subjects:
        return 0
    result = await session.execute(
        text(
            "UPDATE copilot_notes SET resolved_at = :now, updated_at = :now "
            "WHERE kind = :k AND resolved_at IS NULL AND subject = ANY(:subjects)"
        ),
        {"now": now, "k": kind, "subjects": list(subjects)},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def created_today(session: AsyncSession, *, now: datetime) -> int:
    return int(
        (
            await session.execute(
                text("SELECT count(*) FROM copilot_notes WHERE created_at >= :midnight"),
                {"midnight": _ist_midnight(now)},
            )
        ).scalar_one()
    )


async def _insert(
    session: AsyncSession, *, tenant_id: UUID, found: Detection, now: datetime
) -> bool:
    result = await session.execute(
        text(
            "INSERT INTO copilot_notes (id, tenant_id, kind, subject, episode_key, payload, "
            "created_at, updated_at) VALUES (:id, :tid, :kind, :subject, :episode, "
            "CAST(:payload AS jsonb), :now, :now) ON CONFLICT DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "kind": found.kind,
            "subject": found.subject,
            "episode": f"{found.subject}@{ist_day(now)}",
            "payload": json.dumps(found.payload, sort_keys=True),
            "now": now,
        },
    )
    return bool(getattr(result, "rowcount", 0))


Detector = Callable[[AsyncSession, UUID, datetime, Thresholds], Awaitable[list[Detection]]]


async def _hot(s: AsyncSession, t: UUID, n: datetime, th: Thresholds) -> list[Detection]:
    return await detect_hot_leads(s, now=n, thresholds=th)


async def _runway(s: AsyncSession, t: UUID, n: datetime, th: Thresholds) -> list[Detection]:
    return await detect_runway(s, tenant_id=t, now=n, thresholds=th)


async def _gaps(s: AsyncSession, t: UUID, n: datetime, th: Thresholds) -> list[Detection]:
    return await detect_gaps(s, tenant_id=t, now=n, thresholds=th)


async def _week(s: AsyncSession, t: UUID, n: datetime, th: Thresholds) -> list[Detection]:
    week = ist_week(n)
    if week in await _open_subjects(s, "good_week"):
        return [Detection(kind="good_week", subject=week, payload={})]  # already said
    found = await detect_good_week(s, now=n, thresholds=th)
    return [Detection(kind=d.kind, subject=week, payload=d.payload) for d in found]


#: Most urgent first: the daily cap is spent in this order.
DETECTORS: Final[tuple[tuple[NoteKind, Detector], ...]] = (
    ("hot_lead_waiting", _hot),
    ("balance_runway", _runway),
    ("knowledge_gap_repeat", _gaps),
    ("good_week", _week),
)


async def run_detectors(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    now: datetime | None = None,
    thresholds: Thresholds | None = None,
) -> dict[str, int]:
    """One account's pass: open, refresh and resolve notes. Idempotent within an hour: the
    same rows open nothing new and rewrite nothing that did not change."""
    at = now or datetime.now(UTC)
    limits = thresholds or Thresholds.from_settings()
    counts = {"opened": 0, "refreshed": 0, "resolved": 0, "capped": 0, "pruned": 0}
    budget = max(limits.daily_cap - await created_today(session, now=at), 0)
    for kind, detector in DETECTORS:
        found = await detector(session, tenant_id, at, limits)
        open_now = await _open_subjects(session, kind)
        wanted = {d.subject: d for d in found}
        counts["resolved"] += await _resolve(
            session, kind, [s for s in open_now if s not in wanted], at
        )
        for subject, detection in wanted.items():
            if subject in open_now:
                if detection.payload and json.loads(open_now[subject]) != detection.payload:
                    await session.execute(
                        text(
                            "UPDATE copilot_notes SET payload = CAST(:p AS jsonb), "
                            "updated_at = :now WHERE kind = :k AND subject = :s "
                            "AND resolved_at IS NULL"
                        ),
                        {
                            "p": json.dumps(detection.payload, sort_keys=True),
                            "now": at,
                            "k": kind,
                            "s": subject,
                        },
                    )
                    counts["refreshed"] += 1
                continue
            if budget <= 0:
                counts["capped"] += 1
                continue
            if await _insert(session, tenant_id=tenant_id, found=detection, now=at):
                counts["opened"] += 1
                budget -= 1
    pruned = await session.execute(
        text(
            "DELETE FROM copilot_notes WHERE created_at < :before "
            "AND (resolved_at IS NOT NULL OR dismissed_at IS NOT NULL)"
        ),
        {"before": at - timedelta(days=KEEP_DAYS)},
    )
    counts["pruned"] = int(getattr(pruned, "rowcount", 0) or 0)
    return counts


# --- what the panel reads ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Button:
    kind: Literal["open", "ask"]
    label: str
    #: For `open`: the screen's NAME and its route TEMPLATE, both from `screens.CLIENT_SCREENS`.
    screen: str | None = None
    route: str | None = None
    #: For `ask`: what goes into Pip's ask box. Prefilled, never sent (`lib/copilot/launcher`).
    prompt: str | None = None


@dataclass(frozen=True, slots=True)
class NoteView:
    id: str
    kind: str
    source: Literal["pip", "linked"]
    tone: Literal["info", "success", "warning", "critical"]
    line: str
    button: Button
    created_at: datetime
    unread: bool
    dismissible: bool


def _as_dict(value: object) -> dict[str, Any]:
    """A jsonb column as a dict, whichever way the driver hands it back."""
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, Mapping) else {}


def _open(screen_name: str, label: str, role: str | None) -> Button | None:
    screen = find_screen(screen_name)
    if screen is None or not _may_open(screen, role):
        return None
    return Button(kind="open", label=label, screen=screen.name, route=screen.route)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _compose(
    kind: str, payload: Mapping[str, Any], *, role: str | None, gap_labels: Mapping[str, str]
) -> tuple[str, Button, Literal["info", "success", "warning", "critical"]] | None:
    if kind == "hot_lead_waiting":
        n, hours = int(payload.get("count", 0)), int(payload.get("hours", 0))
        button = _open("Leads", "Open leads", role)
        line = (
            f"{_plural(n, 'hot lead has', 'hot leads have')} waited over "
            f"{_plural(hours, 'hour', 'hours')} for a call back."
        )
        return (line, button, "warning") if button else None
    if kind == "balance_runway":
        days = int(payload.get("days", 0))
        button = _open("Credits & billing", "Top up", role)
        when = "today" if days == 0 else f"in {_plural(days, 'day', 'days')}"
        line = f"At your current spending, your credit runs out {when}."
        return (line, button, "warning") if button else None
    if kind == "knowledge_gap_repeat":
        label = gap_labels.get(str(payload.get("gap_id")))
        if label is None:
            return None
        button = _open("What your agents know", "Teach the answer", role)
        calls = int(payload.get("calls", 0))
        line = f"Callers asked about {label} on {calls} calls this week. Your agents had no answer."
        return (line, button, "info") if button else None
    if kind == "good_week":
        calls, leads = int(payload.get("calls", 0)), int(payload.get("leads", 0))
        line = (
            f"Good week: {_plural(calls, 'call', 'calls')} and "
            f"{_plural(leads, 'new lead', 'new leads')}, both up on the week before."
        )
        ask = Button(
            kind="ask", label="See the week", prompt="How did this week go compared with last week?"
        )
        return line, ask, "success"
    return None


#: The needs-attention kinds Pip repeats in its own voice, with the line it says for a count
#: and the screen its button opens. The queue's own item is the record; this is a link to it.
_LINKED_ATTENTION: Final[dict[str, tuple[Callable[[int], str], str, str]]] = {
    "inbound_stopped": (
        lambda n: "Your agents have stopped answering calls.",
        "Needs attention",
        "See why",
    ),
    "campaign_stalled": (
        lambda n: f"{_plural(n, 'campaign has', 'campaigns have')} stopped calling.",
        "Needs attention",
        "See why",
    ),
    "delivery_failed": (
        lambda n: f"{_plural(n, 'lead did', 'leads did')} not reach where you send them.",
        "Needs attention",
        "See which",
    ),
    "action_broken": (
        lambda n: f"{_plural(n, 'task your agents do', 'tasks your agents do')} cannot run.",
        "Needs attention",
        "Fix it",
    ),
    "credit_low": (lambda n: "Your credit is running low.", "Credits & billing", "Top up"),
}


async def _linked(session: AsyncSession, *, role: str | None, now: datetime) -> list[NoteView]:
    sources = [
        await attention.inbound_stopped(session, limit=1),
        await attention.stalled_campaigns(session, limit=1),
        await attention.failed_deliveries(session, limit=1),
        await attention.broken_actions(session, limit=1),
        await attention.low_credit(session),
    ]
    out: list[NoteView] = []
    for source in sources:
        if not source.total or source.kind not in _LINKED_ATTENTION:
            continue
        say, screen, label = _LINKED_ATTENTION[source.kind]
        button = _open(screen, label, role)
        if button is None:
            continue
        at = source.items[0].occurred_at if source.items else now
        out.append(
            NoteView(
                id=f"linked:{source.kind}",
                kind=source.kind,
                source="linked",
                tone="critical" if source.kind in {"inbound_stopped", "credit_low"} else "warning",
                line=say(source.total),
                button=button,
                created_at=at,
                unread=False,
                dismissible=False,
            )
        )
    incident = (
        await session.execute(
            text(
                "SELECT opened_at FROM heal_client_incidents WHERE state = 'open' "
                "ORDER BY opened_at DESC LIMIT 1"
            )
        )
    ).first()
    line_button = _open("Line protection", "See what we did", role)
    if incident is not None and line_button is not None:
        out.append(
            NoteView(
                id="linked:line_problem",
                kind="line_problem",
                source="linked",
                tone="warning",
                line="One of your lines had a problem. We are on it.",
                button=line_button,
                created_at=incident[0],
                unread=False,
                dismissible=False,
            )
        )
    return out


async def read_notes(
    session: AsyncSession, *, role: str | None, now: datetime | None = None
) -> list[NoteView]:
    """Open notes this reader's role can act on, newest first, then the linked items."""
    at = now or datetime.now(UTC)
    rows = (
        await session.execute(
            text(
                "SELECT id, kind, payload, created_at, seen_at FROM copilot_notes "
                "WHERE resolved_at IS NULL AND dismissed_at IS NULL "
                "ORDER BY created_at DESC, id DESC LIMIT :lim"
            ),
            {"lim": MAX_SHOWN},
        )
    ).all()
    payloads = {str(r[0]): _as_dict(r[2]) for r in rows}
    gap_ids = [
        str(payloads[str(r[0])].get("gap_id"))
        for r in rows
        if r[1] == "knowledge_gap_repeat" and payloads[str(r[0])].get("gap_id")
    ]
    labels: dict[str, str] = {}
    if gap_ids:
        labels = {
            str(r[0]): str(r[1])
            for r in (
                await session.execute(
                    text(
                        "SELECT id, topic_label FROM knowledge_gaps "
                        "WHERE status = 'open' AND id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": gap_ids},
                )
            ).all()
        }
    notes: list[NoteView] = []
    for note_id, kind, _payload, created_at, seen_at in rows:
        composed = _compose(str(kind), payloads[str(note_id)], role=role, gap_labels=labels)
        if composed is None:
            continue
        line, button, tone = composed
        notes.append(
            NoteView(
                id=str(note_id),
                kind=str(kind),
                source="pip",
                tone=tone,
                line=line,
                button=button,
                created_at=created_at,
                unread=seen_at is None,
                dismissible=True,
            )
        )
    return notes + await _linked(session, role=role, now=at)


async def mark_seen(session: AsyncSession, *, now: datetime | None = None) -> int:
    result = await session.execute(
        text(
            "UPDATE copilot_notes SET seen_at = :now, updated_at = :now "
            "WHERE seen_at IS NULL AND resolved_at IS NULL AND dismissed_at IS NULL"
        ),
        {"now": now or datetime.now(UTC)},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def dismiss(
    session: AsyncSession, *, note_id: UUID, user_id: UUID | None, now: datetime | None = None
) -> bool:
    """Put one note away for the whole account. Its condition still holds the open slot,
    so the same note does not come back until the condition clears and returns."""
    at = now or datetime.now(UTC)
    result = await session.execute(
        text(
            "UPDATE copilot_notes SET dismissed_at = :now, dismissed_by = :uid, "
            "seen_at = COALESCE(seen_at, :now), updated_at = :now "
            "WHERE id = :id AND dismissed_at IS NULL"
        ),
        {"now": at, "uid": user_id, "id": note_id},
    )
    return bool(getattr(result, "rowcount", 0))


async def mark_acted(session: AsyncSession, *, note_id: UUID, now: datetime | None = None) -> bool:
    at = now or datetime.now(UTC)
    result = await session.execute(
        text(
            "UPDATE copilot_notes SET acted_at = COALESCE(acted_at, :now), "
            "seen_at = COALESCE(seen_at, :now), updated_at = :now WHERE id = :id"
        ),
        {"now": at, "id": note_id},
    )
    return bool(getattr(result, "rowcount", 0))


__all__ = [
    "DETECTORS",
    "KEEP_DAYS",
    "MAX_SHOWN",
    "Button",
    "Detection",
    "NoteKind",
    "NoteView",
    "Thresholds",
    "detect_gaps",
    "detect_good_week",
    "detect_hot_leads",
    "detect_runway",
    "dismiss",
    "ist_week",
    "mark_acted",
    "mark_seen",
    "read_notes",
    "run_detectors",
]
