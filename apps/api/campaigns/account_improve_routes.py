"""The account-wide Improve page (`campaigns/account_improve.py`, `campaigns/weekly_summary.py`):
one read of every section, and the account's weekly summaries."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import account_improve as acct
from apps.api.campaigns import diagnose, weekly_summary
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta, role_has

router = APIRouter(prefix="/v1/improve", tags=["improve"])
Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("leads:read"))]

HolderKind = Literal["campaign", "inbound_line"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NumberWeekOut(_Out):
    #: The Monday the IST week began.
    week_start: date
    placed: int
    answered: int


class NumberHealthOut(_Out):
    #: The account's own calling number.
    e164: str
    weeks: list[NumberWeekOut]
    recent_placed: int
    #: Null below `min_recent_placed` calls in the last week.
    recent_rate: float | None
    baseline_placed: int
    #: Null below `min_baseline_placed` calls in the four weeks before.
    baseline_rate: float | None
    #: The last week's rate fell sharply against its own baseline: carriers may be labelling
    #: the number as spam.
    dropped: bool


class NumbersOut(_Out):
    numbers: list[NumberHealthOut]
    min_recent_placed: int
    min_baseline_placed: int
    drop_ratio: float


class HolderRowOut(_Out):
    kind: HolderKind
    id: UUID
    name: str
    placed: int
    answered: int
    goals: int
    #: Each null below its sample (`min_answered`, `min_judged`).
    answer_rate: float | None
    goal_rate: float | None
    early_rate: float | None
    drop_off_share: float | None
    #: Null when the reader's role may not see money.
    spend_inr: Decimal | None
    cost_per_goal_inr: Decimal | None


class DifferenceOut(_Out):
    kind: acct.DifferenceKind
    best: str
    others: str
    #: What "Use what works" asks Pip to write; null for a setting the owner changes on the
    #: campaign itself.
    instruction: str | None


class CompareOut(_Out):
    holders: list[HolderRowOut]
    #: Null until two or more holders have `min_answered` answered calls.
    best_id: UUID | None
    differences: list[DifferenceOut]
    min_answered: int
    min_judged: int
    early_seconds: int
    total_spend_inr: Decimal | None
    total_goals: int
    total_cost_per_goal_inr: Decimal | None


class PatternAgentOut(_Out):
    id: UUID
    name: str


class MistakePatternOut(_Out):
    kind: str
    label: str
    calls: int
    #: Campaigns and lines it showed on, `min_holders` or more.
    holders: int
    agents: list[PatternAgentOut]


class PatternsOut(_Out):
    patterns: list[MistakePatternOut]
    min_holders: int


class FollowUpsOut(_Out):
    hot_leads: int
    callbacks_due: int


class ContactsOut(_Out):
    on_dnc: int
    unreachable: int
    called_too_often: int
    too_often_days: int


class PipFixOut(_Out):
    kind: acct.FixKind
    holder_kind: HolderKind
    holder_id: UUID
    holder_name: str
    at: datetime
    detail: str | None


class AccountImproveOut(_Out):
    window_days: int
    numbers: NumbersOut
    compare: CompareOut
    patterns: PatternsOut
    follow_ups: FollowUpsOut
    contacts: ContactsOut
    fixes: list[PipFixOut]


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _holder(h: acct.HolderFigures) -> HolderRowOut:
    return HolderRowOut(
        kind=h.kind,
        id=h.id,
        name=h.name,
        placed=h.placed,
        answered=h.answered,
        goals=h.goals,
        answer_rate=_round(h.answer_rate),
        goal_rate=_round(h.goal_rate),
        early_rate=_round(h.early_rate),
        drop_off_share=_round(h.drop_off_share),
        spend_inr=h.spend_inr,
        cost_per_goal_inr=h.cost_per_goal_inr,
    )


async def account_improve(session: AsyncSession, *, include_spend: bool) -> AccountImproveOut:
    numbers = await acct.number_health(session)
    comparison = await acct.compare_holders(session, include_spend=include_spend)
    patterns = await acct.mistake_patterns(session)
    follow = await acct.follow_up_counts(session)
    contacts = await acct.contact_health(session)
    fixes = await acct.pip_fixes(session)
    return AccountImproveOut(
        window_days=acct.WINDOW_DAYS,
        numbers=NumbersOut(
            numbers=[
                NumberHealthOut(
                    e164=n.e164,
                    weeks=[
                        NumberWeekOut(week_start=w.week_start, placed=w.placed, answered=w.answered)
                        for w in n.weeks
                    ],
                    recent_placed=n.recent_placed,
                    recent_rate=_round(n.recent_rate),
                    baseline_placed=n.baseline_placed,
                    baseline_rate=_round(n.baseline_rate),
                    dropped=n.dropped,
                )
                for n in numbers
            ],
            min_recent_placed=acct.MIN_RECENT_PLACED,
            min_baseline_placed=acct.MIN_BASELINE_PLACED,
            drop_ratio=acct.SPAM_DROP_RATIO,
        ),
        compare=CompareOut(
            holders=[_holder(h) for h in comparison.holders],
            best_id=comparison.best.id if comparison.best else None,
            differences=[
                DifferenceOut(kind=d.kind, best=d.best, others=d.others, instruction=d.instruction)
                for d in comparison.differences
            ],
            min_answered=diagnose.MIN_ANSWERED_CALLS,
            min_judged=diagnose.MIN_JUDGED_CALLS,
            early_seconds=diagnose.EARLY_HANG_UP_S,
            total_spend_inr=comparison.total_spend_inr,
            total_goals=comparison.total_goals,
            total_cost_per_goal_inr=comparison.total_cost_per_goal_inr,
        ),
        patterns=PatternsOut(
            patterns=[
                MistakePatternOut(
                    kind=p.kind,
                    label=p.label,
                    calls=p.calls,
                    holders=p.holders,
                    agents=[PatternAgentOut(id=a.id, name=a.name) for a in p.agents],
                )
                for p in patterns
            ],
            min_holders=acct.MIN_HOLDERS_FOR_PATTERN,
        ),
        follow_ups=FollowUpsOut(hot_leads=follow.hot_leads, callbacks_due=follow.callbacks_due),
        contacts=ContactsOut(
            on_dnc=contacts.on_dnc,
            unreachable=contacts.unreachable,
            called_too_often=contacts.called_too_often,
            too_often_days=contacts.too_often_days,
        ),
        fixes=[
            PipFixOut(
                kind=f.kind,
                holder_kind=f.holder_kind,
                holder_id=f.holder_id,
                holder_name=f.holder_name,
                at=f.at,
                detail=f.detail,
            )
            for f in fixes
        ],
    )


@router.get(
    "",
    response_model=AccountImproveOut,
    openapi_extra=permission_meta("leads:read"),
    summary="What would make results better across every campaign and line",
    description=(
        "Answer rate per calling number, the campaigns and lines compared, mistakes on two or "
        "more of them, follow-up counts, contact list health and Pip's recent fixes. Spend and "
        "cost per goal are null for a role without `billing:read`."
    ),
)
async def get_account_improve(session: Session, principal: Reader) -> AccountImproveOut:
    return await account_improve(
        session,
        include_spend=principal.role is not None and role_has(principal.role, "billing:read"),
    )


class WeekFiguresOut(_Out):
    """The counts a paragraph was written from (`weekly_summary.WeekFigures`); a field a
    row stored before it existed reads as null, and a stored key this model no longer names
    is dropped where the row is read (`_week_figures`), so the model itself still forbids
    unknown fields."""

    calls: int | None = None
    answered: int | None = None
    answer_rate: float | None = None
    drop_off_step: str | None = None
    goals: int | None = None
    fixes: int | None = None
    best_name: str | None = None
    best_goal_rate: float | None = None


class WeeklySummaryOut(_Out):
    id: UUID
    week_start: date
    #: Pip's paragraph, written from `figures` alone, never from a call's words. Named for
    #: what it is rather than `summary`, which in this API means a call's own summary.
    paragraph: str
    figures: WeekFiguresOut
    created_at: datetime


def _week_figures(stored: dict[str, object]) -> WeekFiguresOut:
    """A stored row's figures, with only the keys the model names."""
    return WeekFiguresOut.model_validate(
        {k: v for k, v in stored.items() if k in WeekFiguresOut.model_fields}
    )


@router.get(
    "/weekly-summaries",
    response_model=list[WeeklySummaryOut],
    openapi_extra=permission_meta("leads:read"),
    summary="Pip's weekly summaries of the account, newest week first",
)
async def list_weekly_summaries(
    session: Session,
    _: Reader,
    limit: int = Query(default=1, ge=1, le=weekly_summary.MAX_LISTED),
) -> list[WeeklySummaryOut]:
    return [
        WeeklySummaryOut(
            id=s.id,
            week_start=s.week_start,
            paragraph=s.summary,
            figures=_week_figures(s.figures),
            created_at=s.created_at,
        )
        for s in await weekly_summary.list_summaries(session, limit=limit)
    ]


__all__ = ["account_improve", "router"]
