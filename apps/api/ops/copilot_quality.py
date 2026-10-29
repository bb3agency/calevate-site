"""Pip's live success scores — `GET /v1/ops/copilot-quality` (D-937).

Read, never computed ahead: every figure comes from two stores Pip already writes on every
answer, over the last 7 or 30 days, for the client Pip or the admin Pip:

* `copilot_answer_outcomes` / `admin_copilot_answer_outcomes` (migration `c9e4a7d2f15b`):
  one row per answer — tool names and their outcomes, the immediate actions executed, the
  confirm card proposed, a screen opened, the leg that answered, two timings, a gate refusal,
  and the asker's thumbs;
* `copilot_actions` / `admin_copilot_actions` (D-694): what each action became (`done`,
  `undone`) and which confirm proposals a person accepted.

WHAT EACH SCORE MEANS
* An answer is DONE when it ended with the thing done: an action it executed is still in
  place (not undone), it opened a screen, or the asker gave it a thumbs up.
* Action success vs failure vs undone, per action tool: `done` and `undone` are the action
  log's statuses; `failed` is an answer whose call of that action failed (an executor error
  writes no log row, so the step outcome is the only record).
* Confirm proposals accepted vs abandoned: per tool, proposals shown (answers that offered
  the card) against confirm-tier actions people ran from the panel in the same window. They
  are window totals, not linked card by card: the confirm token does not carry the turn.
* Refusals: the gate's (`fair_use`, `consent`, `paused`, counted per question) and the
  permission ladder's (`refused` tool calls, per tool).
* Latency: time to first token and total, median and 90th percentile over answers; the p90
  is withheld below `P90_MIN` answers, where it would be the maximum under another name.
* Fallback: answers another leg than the account's own answered.

AREA. A client answer counts in every area whose tool it called (`copilot/areas.AREA_OF`);
an answer that called none is `no_tool`. The admin Pip has no areas, so its tools are all
`platform`. Action-log rows count in their tool's area.

CROSS-CLIENT READ. `copilot_quality_scan` enters each live tenant under its own
`app.tenant_id` inside one statement, so it must be called from an `admin_session()`
(`ops/reply_times.py` has the same shape). The admin realm's tables carry no tenant.

LOW SCORES. A group whose thumbs-down share or action-failure share is at or over the alarm
thresholds below (with enough votes or attempts to mean anything) is flagged `low`, and every
group carries up to `MAX_EXAMPLES` example answer ids to review — thumbs down first, then
failed tools, undone actions and unfinished answers. Ids only: the conversation text dies
with its sign-in run and is never copied here.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

QualityRealm = Literal["client", "admin"]

DEFAULT_WINDOW_DAYS: Final = 7
WINDOW_CHOICES: Final[tuple[int, ...]] = (7, 30)
MAX_WINDOW_DAYS: Final = 30

#: Answer rows read per report. Above it the report covers the newest and says so.
MAX_ANSWERS: Final = 100_000
MAX_ACTIONS: Final = 100_000
#: Example answer ids per group.
MAX_EXAMPLES: Final = 5
#: Below this many timed answers a group reports no p90.
P90_MIN: Final = 10

#: Thresholds shared by the page's `low` flags and the `copilot_quality_low` alarm. A share is
#: judged only over at least the minimum count, so two votes cannot raise an alarm.
THUMBS_DOWN_LOW_SHARE: Final = 0.4
MIN_VOTES: Final = 5
ACTION_FAILURE_LOW_SHARE: Final = 0.25
MIN_ATTEMPTS: Final = 5

NO_TOOL: Final = "no_tool"
PLATFORM: Final = "platform"

GateRefusal = Literal["fair_use", "consent", "paused"]
LowReason = Literal["thumbs_down", "action_failures"]
ExampleWhy = Literal["thumbs_down", "tool_failed", "action_undone", "unfinished"]


# --- the rows -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnswerRow:
    """One answer (or gate refusal) as the scores read it."""

    turn_id: UUID
    tenant_id: UUID | None
    created_at: datetime
    tools: tuple[str, ...] = ()
    failed_tools: tuple[str, ...] = ()
    refused_tools: tuple[str, ...] = ()
    acted: bool = False
    kept: bool = False
    undone: bool = False
    proposed_tool: str | None = None
    navigated: bool = False
    provider: str | None = None
    fell_back: bool = False
    first_token_ms: int | None = None
    total_ms: int | None = None
    completed: bool = True
    refusal: str | None = None
    vote: str | None = None
    vote_reason: str | None = None
    vote_note: str | None = None
    voted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActionRow:
    """One action-log row as the scores read it."""

    tool: str
    tier: str
    status: str
    source: str


# --- the report ---------------------------------------------------------------------------


class ReasonCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    count: int


class ExampleTurn(BaseModel):
    """An answer to review: its turn id and, on the client Pip, its account."""

    model_config = ConfigDict(extra="forbid")
    turn_id: str
    tenant_id: str | None
    why: ExampleWhy
    #: For a thumbs down with the reason `other`: the asker's own line, redacted on write.
    note: str | None = None


class QualityFigures(BaseModel):
    """One group's scores. Shares are 0..1, `None` when there is nothing to divide by."""

    model_config = ConfigDict(extra="forbid")

    answers: int
    done: int
    done_share: float | None
    thumbs_up: int
    thumbs_down: int
    thumbs_down_share: float | None
    reasons: list[ReasonCount]
    tool_failures: int
    permission_refusals: int
    actions_done: int
    actions_undone: int
    actions_failed: int
    action_failure_share: float | None
    proposals: int
    proposals_accepted: int
    proposals_abandoned: int
    fell_back: int
    first_token_typical_ms: int | None
    first_token_slow_ms: int | None
    total_typical_ms: int | None
    total_slow_ms: int | None
    low: list[LowReason]
    examples: list[ExampleTurn]


class AreaQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str
    figures: QualityFigures


class ToolQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    area: str
    is_action: bool
    figures: QualityFigures


class ProviderCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    answers: int


class CopilotQualityReport(BaseModel):
    """`GET /v1/ops/copilot-quality`. Lists are bounded by the area list, the registered tool
    list, the three gate refusals, the answering legs and `MAX_EXAMPLES`."""

    model_config = ConfigDict(extra="forbid")

    realm: QualityRealm
    window_days: int
    #: False when the window held more than `MAX_ANSWERS` answers and only the newest were read.
    complete: bool
    questions: int
    refusals: list[ReasonCount]
    overall: QualityFigures
    by_area: list[AreaQuality]
    by_tool: list[ToolQuality]
    by_provider: list[ProviderCount]
    thumbs_down_low_share: float
    min_votes: int
    action_failure_low_share: float
    min_attempts: int


# --- the computation ----------------------------------------------------------------------


def area_of(realm: QualityRealm, tool: str) -> str:
    """The area a tool belongs to; an area call the model wrote in the wrong form names it."""
    # Imported here: `copilot/admin_actions` imports `ops/routes`, which imports this module.
    from apps.api.copilot.areas import AREA_OF, AREAS, DO, FIND

    if realm == "admin":
        return PLATFORM
    if tool in AREA_OF:
        return AREA_OF[tool]
    for suffix in (FIND, DO):
        if tool.endswith(suffix) and tool[: -len(suffix)] in AREAS:
            return tool[: -len(suffix)]
    return "other"


def is_action(realm: QualityRealm, tool: str) -> bool:
    # Imported here for `area_of`'s reason.
    from apps.api.copilot.admin_actions import admin_tool_named
    from apps.api.copilot.write_tools import is_write_tool

    return admin_tool_named(tool) is not None if realm == "admin" else is_write_tool(tool)


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _median(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _p90(values: Sequence[int]) -> int | None:
    """Nearest-rank 90th percentile, withheld below `P90_MIN` values."""
    if len(values) < P90_MIN:
        return None
    ordered = sorted(values)
    rank = -(-9 * len(ordered) // 10)  # ceil(0.9 n)
    return ordered[rank - 1]


def is_done(answer: AnswerRow) -> bool:
    """Ended with the thing done: a kept action, an opened screen, or a thumbs up."""
    return answer.kept or answer.navigated or answer.vote == "up"


def _why(answer: AnswerRow) -> ExampleWhy | None:
    if answer.vote == "down":
        return "thumbs_down"
    if answer.failed_tools:
        return "tool_failed"
    if answer.undone:
        return "action_undone"
    if not answer.completed:
        return "unfinished"
    return None


_WHY_ORDER: Final[dict[str, int]] = {
    "thumbs_down": 0,
    "tool_failed": 1,
    "action_undone": 2,
    "unfinished": 3,
}


@dataclass(slots=True)
class _Group:
    """What one area or tool accumulates before it becomes `QualityFigures`."""

    answers: list[AnswerRow] = field(default_factory=list)
    actions: list[ActionRow] = field(default_factory=list)
    #: Only for a tool group: count failures/refusals/proposals of THIS tool, not the
    #: answer's other tools.
    tool: str | None = None
    realm: QualityRealm = "client"


def _figures(group: _Group) -> QualityFigures:
    answers = group.answers
    tool = group.tool
    votes_up = sum(1 for a in answers if a.vote == "up")
    votes_down = sum(1 for a in answers if a.vote == "down")
    reasons = Counter(a.vote_reason for a in answers if a.vote == "down" and a.vote_reason)

    def failed(a: AnswerRow) -> bool:
        return tool in a.failed_tools if tool else bool(a.failed_tools)

    tool_failures = sum(1 for a in answers if failed(a))
    refused = sum(
        (1 if tool in a.refused_tools else 0) if tool else len(a.refused_tools) for a in answers
    )
    # Action failures: answers whose call of an ACTION tool failed.
    actions_failed = sum(
        1
        for a in answers
        for name in a.failed_tools
        if (name == tool if tool else True) and is_action(group.realm, name)
    )
    done_rows = sum(1 for r in group.actions if r.status == "done")
    undone_rows = sum(1 for r in group.actions if r.status == "undone")
    attempts = done_rows + undone_rows + actions_failed
    proposals = sum(
        1 for a in answers if a.proposed_tool and (tool is None or a.proposed_tool == tool)
    )
    accepted = sum(
        1
        for r in group.actions
        if r.tier == "confirm" and r.source == "interactive" and r.status in ("done", "undone")
    )
    first = [a.first_token_ms for a in answers if a.first_token_ms is not None]
    total = [a.total_ms for a in answers if a.total_ms is not None and a.completed]

    low: list[LowReason] = []
    down_share = _share(votes_down, votes_up + votes_down)
    if votes_up + votes_down >= MIN_VOTES and (down_share or 0) >= THUMBS_DOWN_LOW_SHARE:
        low.append("thumbs_down")
    failure_share = _share(actions_failed, attempts)
    if attempts >= MIN_ATTEMPTS and (failure_share or 0) >= ACTION_FAILURE_LOW_SHARE:
        low.append("action_failures")

    flagged = [(why, a) for a in answers if (why := _why(a)) is not None]
    flagged.sort(
        key=lambda pair: (
            _WHY_ORDER[pair[0]],
            -(pair[1].voted_at or pair[1].created_at).timestamp(),
        )
    )
    examples = [
        ExampleTurn(
            turn_id=str(a.turn_id),
            tenant_id=str(a.tenant_id) if a.tenant_id else None,
            why=why,
            note=a.vote_note if why == "thumbs_down" else None,
        )
        for why, a in flagged[:MAX_EXAMPLES]
    ]
    done = sum(1 for a in answers if is_done(a))
    return QualityFigures(
        answers=len(answers),
        done=done,
        done_share=_share(done, len(answers)),
        thumbs_up=votes_up,
        thumbs_down=votes_down,
        thumbs_down_share=down_share,
        reasons=[ReasonCount(reason=r, count=n) for r, n in reasons.most_common()],
        tool_failures=tool_failures,
        permission_refusals=refused,
        actions_done=done_rows,
        actions_undone=undone_rows,
        actions_failed=actions_failed,
        action_failure_share=failure_share,
        proposals=proposals,
        proposals_accepted=accepted,
        proposals_abandoned=max(0, proposals - accepted),
        fell_back=sum(1 for a in answers if a.fell_back),
        first_token_typical_ms=_median(first),
        first_token_slow_ms=_p90(first),
        total_typical_ms=_median(total),
        total_slow_ms=_p90(total),
        low=low,
        examples=examples,
    )


def build_report(
    answers: Iterable[AnswerRow],
    actions: Iterable[ActionRow],
    *,
    realm: QualityRealm,
    days: int,
    complete: bool = True,
) -> CopilotQualityReport:
    """The report over already-read rows. Pure, so it is tested on seeded rows."""
    rows = list(answers)
    asked = [a for a in rows if a.refusal is None]
    refusals = Counter(a.refusal for a in rows if a.refusal is not None)
    log = list(actions)

    overall = _Group(answers=asked, actions=log, realm=realm)
    areas: dict[str, _Group] = defaultdict(lambda: _Group(realm=realm))
    tools: dict[str, _Group] = {}

    def tool_group(name: str) -> _Group:
        if name not in tools:
            tools[name] = _Group(tool=name, realm=realm)
        return tools[name]

    for answer in asked:
        named = set(answer.tools)
        if answer.proposed_tool:
            named.add(answer.proposed_tool)
        touched = {area_of(realm, name) for name in named} or {NO_TOOL}
        for area in touched:
            areas[area].answers.append(answer)
        for name in named:
            tool_group(name).answers.append(answer)
    for row in log:
        areas[area_of(realm, row.tool)].actions.append(row)
        tool_group(row.tool).actions.append(row)

    providers = Counter(a.provider for a in asked if a.provider)
    return CopilotQualityReport(
        realm=realm,
        window_days=days,
        complete=complete,
        questions=len(rows),
        refusals=[ReasonCount(reason=r, count=n) for r, n in sorted(refusals.items())],
        overall=_figures(overall),
        by_area=[
            AreaQuality(area=name, figures=_figures(group))
            for name, group in sorted(areas.items(), key=lambda item: -len(item[1].answers))
        ],
        by_tool=[
            ToolQuality(
                tool=name,
                area=area_of(realm, name),
                is_action=is_action(realm, name),
                figures=_figures(group),
            )
            for name, group in sorted(
                tools.items(), key=lambda item: (-len(item[1].answers), item[0])
            )
        ],
        by_provider=[ProviderCount(provider=p, answers=n) for p, n in providers.most_common()],
        thumbs_down_low_share=THUMBS_DOWN_LOW_SHARE,
        min_votes=MIN_VOTES,
        action_failure_low_share=ACTION_FAILURE_LOW_SHARE,
        min_attempts=MIN_ATTEMPTS,
    )


# --- the reads ----------------------------------------------------------------------------

_CLIENT_SCAN: Final = text(
    "SELECT s.* FROM copilot_quality_scan(:since) AS s ORDER BY s.created_at DESC LIMIT :cap"
)

_ADMIN_ANSWERS: Final = text(
    "SELECT NULL::uuid AS scanned_tenant_id, 'answer' AS kind, a.turn_id, a.created_at, "
    "a.tools::text[] AS tools, a.failed_tools::text[] AS failed_tools, "
    "a.refused_tools::text[] AS refused_tools, cardinality(a.action_ids) > 0 AS acted, "
    "EXISTS (SELECT 1 FROM admin_copilot_actions x "
    "WHERE x.id = ANY (a.action_ids) AND x.status = 'done') AS kept, "
    "EXISTS (SELECT 1 FROM admin_copilot_actions x "
    "WHERE x.id = ANY (a.action_ids) AND x.status = 'undone') AS undone, "
    "a.proposed_tool, a.navigated, a.provider, a.fell_back, a.first_token_ms, a.total_ms, "
    "a.completed, a.refusal, a.vote, a.vote_reason, a.vote_note, a.voted_at "
    "FROM admin_copilot_answer_outcomes a WHERE a.created_at >= :since "
    "ORDER BY a.created_at DESC LIMIT :cap"
)

_ADMIN_ACTIONS: Final = text(
    "SELECT tool, tier, status, source FROM admin_copilot_actions "
    "WHERE created_at >= :since ORDER BY created_at DESC LIMIT :cap"
)


def _answer(row: object) -> AnswerRow:
    m = row._mapping  # type: ignore[attr-defined]
    return AnswerRow(
        turn_id=UUID(str(m["turn_id"])),
        tenant_id=UUID(str(m["scanned_tenant_id"])) if m["scanned_tenant_id"] else None,
        created_at=m["created_at"],
        tools=tuple(m["tools"] or ()),
        failed_tools=tuple(m["failed_tools"] or ()),
        refused_tools=tuple(m["refused_tools"] or ()),
        acted=bool(m["acted"]),
        kept=bool(m["kept"]),
        undone=bool(m["undone"]),
        proposed_tool=m["proposed_tool"],
        navigated=bool(m["navigated"]),
        provider=m["provider"],
        fell_back=bool(m["fell_back"]),
        first_token_ms=m["first_token_ms"],
        total_ms=m["total_ms"],
        completed=bool(m["completed"]),
        refusal=m["refusal"],
        vote=m["vote"],
        vote_reason=m["vote_reason"],
        vote_note=m["vote_note"],
        voted_at=m["voted_at"],
    )


@dataclass(frozen=True, slots=True)
class Window:
    answers: tuple[AnswerRow, ...]
    actions: tuple[ActionRow, ...]
    complete: bool


async def read_window(session: AsyncSession, *, realm: QualityRealm, since: datetime) -> Window:
    """The rows since `since`. On the client realm `session` must be an `admin_session()`."""
    cap = MAX_ANSWERS + MAX_ACTIONS + 1
    if realm == "client":
        rows = (await session.execute(_CLIENT_SCAN, {"since": since, "cap": cap})).all()
        answer_rows = [r for r in rows if r._mapping["kind"] == "answer"]
        action_rows = [
            ActionRow(
                tool=r._mapping["action_tool"],
                tier=r._mapping["action_tier"],
                status=r._mapping["action_status"],
                source=r._mapping["action_source"],
            )
            for r in rows
            if r._mapping["kind"] == "action"
        ]
        complete = len(rows) < cap
    else:
        answer_rows = list(
            (await session.execute(_ADMIN_ANSWERS, {"since": since, "cap": MAX_ANSWERS + 1})).all()
        )
        action_rows = [
            ActionRow(tool=r[0], tier=r[1], status=r[2], source=r[3])
            for r in (
                await session.execute(_ADMIN_ACTIONS, {"since": since, "cap": MAX_ACTIONS})
            ).all()
        ]
        complete = len(answer_rows) <= MAX_ANSWERS
    return Window(
        answers=tuple(_answer(r) for r in answer_rows[:MAX_ANSWERS]),
        actions=tuple(action_rows[:MAX_ACTIONS]),
        complete=complete and len(answer_rows) <= MAX_ANSWERS,
    )


async def copilot_quality_report(
    session: AsyncSession, *, realm: QualityRealm, days: int = DEFAULT_WINDOW_DAYS
) -> CopilotQualityReport:
    """The window's report (module docstring)."""
    window_days = max(1, min(days, MAX_WINDOW_DAYS))
    window = await read_window(
        session, realm=realm, since=datetime.now(UTC) - timedelta(days=window_days)
    )
    return build_report(
        window.answers,
        window.actions,
        realm=realm,
        days=window_days,
        complete=window.complete,
    )


__all__ = [
    "ACTION_FAILURE_LOW_SHARE",
    "DEFAULT_WINDOW_DAYS",
    "MAX_ANSWERS",
    "MAX_EXAMPLES",
    "MAX_WINDOW_DAYS",
    "MIN_ATTEMPTS",
    "MIN_VOTES",
    "NO_TOOL",
    "P90_MIN",
    "PLATFORM",
    "THUMBS_DOWN_LOW_SHARE",
    "WINDOW_CHOICES",
    "ActionRow",
    "AnswerRow",
    "AreaQuality",
    "CopilotQualityReport",
    "ExampleTurn",
    "QualityFigures",
    "ToolQuality",
    "Window",
    "area_of",
    "build_report",
    "copilot_quality_report",
    "is_action",
    "is_done",
    "read_window",
]
