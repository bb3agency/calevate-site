"""The campaign page's Improve tab (D-992 item 8): what its calls teach, and the one-press
moves each card offers (`campaigns/improve.py`)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import improve, learning, notes_live, workspace
from apps.api.campaigns.engine_agent import put_campaign_live
from apps.api.campaigns.service import retry_policy_view
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm.outcomes import HUNG_UP_EARLY_S
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])
Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("leads:read"))]
Dispatcher = Annotated[Principal, Depends(requires("leads:dispatch"))]

OPENING_MAX: Final = 200


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WindowOut(_Out):
    start: str
    end: str


class HourOut(_Out):
    #: The hour of the day in IST, 0-23.
    hour: int
    #: People tried in this hour, each once however many times they were rung.
    people: int
    #: Of them, people who picked up in this hour.
    reached: int
    rate: float


class BlockOut(_Out):
    start: str
    end: str
    people: int
    reached: int
    rate: float
    #: The chance this block's answer rate beats the rest of the day's; None until judged.
    chance: float | None


class AppliedHoursOut(_Out):
    block: WindowOut
    #: The hours before, None for the whole platform window.
    before: WindowOut | None
    by: Literal["owner", "pip"]
    at: datetime


class BestHoursOut(_Out):
    state: Literal["empty", "too_few", "measuring", "actionable"]
    best: BlockOut | None
    blocks: list[BlockOut]
    hours: list[HourOut]
    #: The block, and the rest of the day, each need this many people tried.
    min_people_per_block: int
    #: The chance a block needs before it is recommended.
    chance_needed: float
    #: The campaign's own hours, None for the whole platform window.
    calling_hours: WindowOut | None
    applied: AppliedHoursOut | None
    #: Pip narrows the hours on its own once it is measured.
    auto: bool


class RetryOut(_Out):
    spread: bool
    max_attempts: int
    gaps_minutes: list[int]


class OpeningOut(_Out):
    variant: Literal["a", "b"]
    people: int
    answered: int
    stayed: int
    goal_reached: int
    stayed_rate: float | None
    goal_rate: float | None


class ListSizeOut(_Out):
    people: int
    answer_rate: float | None
    answered_needed: int
    #: None when it depends on an answer rate not measured yet.
    large_enough: bool | None


class OpeningDecisionOut(_Out):
    winner: Literal["a", "b"]
    chance_b_better: float
    #: The winner became the campaign's opening (False for the script's own, or a campaign
    #: with no script of its own to put it in).
    applied: bool
    opening_b: str
    at: datetime
    undone: bool
    can_undo: bool


class OpeningTestOut(_Out):
    opening_b: str | None
    state: Literal["off", "too_few", "measuring", "decided"]
    #: The chance the second opening keeps more people past the first twenty seconds.
    chance_b_better: float | None
    #: The same for reaching the goal; shown, never decides.
    goal_chance_b_better: float | None
    openings: list[OpeningOut]
    min_answered_per_opening: int
    win_chance: float
    #: Seconds a person must stay to count as staying.
    stayed_seconds: int
    list_size: ListSizeOut
    decision: OpeningDecisionOut | None


class CampaignInsightsOut(_Out):
    best_hours: BestHoursOut
    retry: RetryOut
    opening: OpeningTestOut


def _window(value: object) -> WindowOut | None:
    if not isinstance(value, dict) or "start" not in value or "end" not in value:
        return None
    return WindowOut(start=str(value["start"]), end=str(value["end"]))


def _block(rate: learning.BlockRate) -> BlockOut:
    return BlockOut(
        start=rate.block.start.strftime("%H:%M"),
        end=rate.block.end.strftime("%H:%M"),
        people=rate.people,
        reached=rate.reached,
        rate=round(rate.rate, 4),
        chance=None if rate.chance is None else round(rate.chance, 4),
    )


def _opening(o: learning.OpeningResult) -> OpeningOut:
    return OpeningOut(
        variant="b" if o.variant == "b" else "a",
        people=o.people,
        answered=o.answered,
        stayed=o.stayed,
        goal_reached=o.goal_reached,
        stayed_rate=None if o.stayed_rate is None else round(o.stayed_rate, 4),
        goal_rate=None if o.goal_rate is None else round(o.goal_rate, 4),
    )


def _decision(row: Any) -> OpeningDecisionOut | None:
    result = row.opening_test_result if isinstance(row.opening_test_result, dict) else None
    if result is None:
        return None
    undone = bool(result.get("undone_at"))
    script_opening = (
        str((row.script or {}).get("opening_line") or "") if isinstance(row.script, dict) else ""
    )
    return OpeningDecisionOut(
        winner="b" if result.get("winner") == "b" else "a",
        chance_b_better=float(result.get("chance_b_better") or 0.0),
        applied=bool(result.get("applied")),
        opening_b=str(result.get("opening_b") or ""),
        at=datetime.fromisoformat(str(result["at"])),
        undone=undone,
        can_undo=bool(result.get("applied"))
        and not undone
        and script_opening == result.get("opening_b"),
    )


async def _insights(session: AsyncSession, campaign_id: UUID) -> CampaignInsightsOut:
    row = (
        await session.execute(
            text(
                "SELECT calling_hours, retry_policy, best_hours_auto, best_hours_applied, "
                "opening_b, opening_test_result, script FROM campaigns "
                "WHERE id = :cid AND archived_at IS NULL"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    rates = await learning.answer_rate_by_hour(session, campaign_id)
    hours = row.calling_hours if isinstance(row.calling_hours, dict) else None
    verdict = learning.best_block(rates, hours)
    applied = improve.applied_now(row)
    retry = retry_policy_view(row.retry_policy)
    second = str(row.opening_b or "").strip() or None
    opening_state: Literal["off", "too_few", "measuring", "decided"] = "off"
    chance: float | None = None
    goal_chance: float | None = None
    openings: list[OpeningOut] = []
    if second:
        results = await learning.opening_results(session, campaign_id)
        test = learning.opening_verdict(results)
        opening_state = test.state
        chance, goal_chance = round(test.chance_b_better, 4), round(test.goal_chance_b_better, 4)
        openings = [_opening(o) for o in results]
    size = await learning.list_size(session, campaign_id)
    return CampaignInsightsOut(
        best_hours=BestHoursOut(
            state=verdict.state,
            best=_block(verdict.best) if verdict.best else None,
            blocks=[_block(b) for b in verdict.blocks],
            hours=[
                HourOut(hour=r.hour, people=r.people, reached=r.reached, rate=round(r.rate, 4))
                for r in rates
            ],
            min_people_per_block=learning.MIN_PEOPLE_PER_BLOCK,
            chance_needed=learning.BLOCK_CHANCE,
            calling_hours=_window(hours),
            applied=(
                AppliedHoursOut(
                    block=WindowOut(**applied["block"]),
                    before=_window(applied.get("before")),
                    by="pip" if applied.get("by") == "pip" else "owner",
                    at=datetime.fromisoformat(str(applied["at"])),
                )
                if applied
                else None
            ),
            auto=bool(row.best_hours_auto),
        ),
        retry=RetryOut(
            spread=bool(retry["spread"]),
            max_attempts=int(retry["max_attempts"]),
            gaps_minutes=[int(g) for g in retry["gaps_minutes"]],
        ),
        opening=OpeningTestOut(
            opening_b=second,
            state=opening_state,
            chance_b_better=chance,
            goal_chance_b_better=goal_chance,
            openings=openings,
            min_answered_per_opening=learning.MIN_ANSWERED_PER_OPENING,
            win_chance=learning.WIN_CHANCE,
            stayed_seconds=HUNG_UP_EARLY_S,
            list_size=ListSizeOut(
                people=size.people,
                answer_rate=None if size.answer_rate is None else round(size.answer_rate, 4),
                answered_needed=size.answered_needed,
                large_enough=size.large_enough,
            ),
            decision=_decision(row),
        ),
    )


@router.get(
    "/{campaign_id}/insights",
    response_model=CampaignInsightsOut,
    openapi_extra=permission_meta("leads:read"),
    summary="When people answer this campaign's calls, how it retries, and its opening test",
)
async def campaign_insights(campaign_id: UUID, session: Session, _: Reader) -> CampaignInsightsOut:
    return await _insights(session, campaign_id)


async def _audited(
    session: AsyncSession,
    principal: Principal,
    request: Request,
    campaign_id: UUID,
    action: str,
    summary: dict[str, object],
) -> None:
    assert principal.tenant_id is not None
    await write_audit(
        session,
        action=action,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=client_request_ip(request),
        summary=summary,
    )


@router.post(
    "/{campaign_id}/best-hours/apply",
    response_model=CampaignInsightsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Call only in the block of the day people answer most, inside the platform hours",
)
async def apply_best_hours(
    campaign_id: UUID, session: Session, request: Request, principal: Dispatcher
) -> CampaignInsightsOut:
    applied = await improve.apply_best_hours(session, campaign_id, by="owner")
    await _audited(
        session,
        principal,
        request,
        campaign_id,
        "campaign.best_hours_applied",
        {"block": applied["block"]},
    )
    return await _insights(session, campaign_id)


@router.post(
    "/{campaign_id}/best-hours/undo",
    response_model=CampaignInsightsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Put back the calling hours from before the best hours were applied",
)
async def undo_best_hours(
    campaign_id: UUID, session: Session, request: Request, principal: Dispatcher
) -> CampaignInsightsOut:
    await improve.undo_best_hours(session, campaign_id)
    await _audited(session, principal, request, campaign_id, "campaign.best_hours_undone", {})
    return await _insights(session, campaign_id)


class SwitchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: bool


@router.put(
    "/{campaign_id}/best-hours/auto",
    response_model=CampaignInsightsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Let Pip narrow the calling hours to the best block once it is measured",
)
async def set_best_hours_auto(
    campaign_id: UUID, payload: SwitchIn, session: Session, request: Request, principal: Dispatcher
) -> CampaignInsightsOut:
    await improve.set_best_hours_auto(session, campaign_id, on=payload.on)
    await _audited(
        session, principal, request, campaign_id, "campaign.best_hours_auto", {"on": payload.on}
    )
    return await _insights(session, campaign_id)


@router.put(
    "/{campaign_id}/retry-spread",
    response_model=CampaignInsightsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Ring each retry at a different time of day than the try that went unanswered",
)
async def set_retry_spread(
    campaign_id: UUID, payload: SwitchIn, session: Session, request: Request, principal: Dispatcher
) -> CampaignInsightsOut:
    await improve.set_retry_spread(session, campaign_id, on=payload.on)
    await _audited(
        session, principal, request, campaign_id, "campaign.retry_spread", {"on": payload.on}
    )
    return await _insights(session, campaign_id)


@router.post(
    "/{campaign_id}/opening-test/undo",
    response_model=CampaignInsightsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Put back the opening the test's winner replaced",
)
async def undo_opening(
    campaign_id: UUID, session: Session, request: Request, principal: Dispatcher
) -> CampaignInsightsOut:
    """Saved in its own transaction, then put on the calls as any script save is."""
    assert principal.tenant_id is not None
    async with tenant_session(principal.tenant_id) as own:
        await improve.undo_opening(own, campaign_id)
        await _audited(own, principal, request, campaign_id, "campaign.opening_test_undone", {})
    if await workspace.holds_engine_agent(session, campaign_id):
        try:
            await put_campaign_live(
                tenant_id=principal.tenant_id, campaign_id=campaign_id, require_holding=True
            )
        except ProblemError as exc:
            notes_live.kept_not_live(exc)
            raise
    return await _insights(session, campaign_id)


class PracticeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The second opening to compare with the script's own.
    opening_b: str = Field(min_length=1, max_length=OPENING_MAX)


class PracticeSideOut(_Out):
    line: str
    #: One plain sentence per mistake the practice checks find.
    mistakes: list[str]


class PracticeOut(_Out):
    own: PracticeSideOut
    second: PracticeSideOut
    #: Which has fewer mistakes; None when they have as many.
    fewer: Literal["a", "b"] | None


@router.post(
    "/{campaign_id}/opening-practice",
    response_model=PracticeOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Compare a second opening with the script's own through the practice checks",
)
async def opening_practice(
    campaign_id: UUID, payload: PracticeIn, session: Session, _: Reader
) -> PracticeOut:
    """For a list too small to tell two openings apart on calls. Reads and stores nothing
    beyond the campaign's own opening."""
    row = (
        await session.execute(
            text(
                "SELECT c.script, COALESCE(c.settings_overrides->>'language_primary', "
                "a.language_primary) AS language FROM campaigns c JOIN agents a "
                "ON a.id = c.agent_id WHERE c.id = :cid AND c.archived_at IS NULL"
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    own = (
        str((row.script or {}).get("opening_line") or "").strip()
        if isinstance(row.script, dict)
        else ""
    )
    if not own:
        raise ProblemError.business_rule(
            "campaign_no_opening",
            "This campaign's script has no opening of its own to compare with.",
            remediation="Write the opening in the script first.",
        )
    compared = improve.practice_compare(
        own, " ".join(payload.opening_b.split()), language=str(row.language or "")
    )
    return PracticeOut(
        own=PracticeSideOut(line=own, mistakes=[m.reason for m in compared.own.mistakes]),
        second=PracticeSideOut(
            line=compared.second.line, mistakes=[m.reason for m in compared.second.mistakes]
        ),
        fewer=compared.fewer,
    )
