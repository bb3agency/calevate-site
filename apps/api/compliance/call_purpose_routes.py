"""The promo check and the call purpose, as reads (D-943).

    POST /v1/compliance/promo-check                        any wording, checked
    GET  /v1/compliance/promo-check/agents/{agent_id}      an agent's script being edited
    GET  /v1/compliance/call-purpose/campaigns/{id}        a campaign's purpose + live script

All three are reads with no side effect and no model call; the reasoning is in
`compliance/call_purpose.py` and `compliance/promo_checks.py`. The words they return are
the client's own script, never a caller's.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import promo_checks
from apps.api.compliance.call_purpose import FIX, WHY, PromoReport, PurposeVerdict, ScriptPart
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
CampaignReader = Annotated[Principal, Depends(requires("leads:read"))]

#: How many pieces one check takes, and how long each may be: a whole structured script
#: is well under this, and the bound keeps a pasted novel from becoming a regex workload.
MAX_PARTS = 60
MAX_PART_CHARS = 20000


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WordingIn(Strict):
    where: str = Field(default="Your wording", max_length=120)
    wording: str = Field(max_length=MAX_PART_CHARS)
    #: `answer` = said only when a caller asks, which softens what it finds.
    kind: Literal["opening", "instruction", "answer", "template"] = "instruction"


class PromoCheckIn(Strict):
    parts: list[WordingIn] = Field(min_length=1, max_length=MAX_PARTS)


class FindingOut(Strict):
    phrase: str
    category: Literal["discount", "urgency", "free_offer", "cross_sell", "buy_now", "claim"]
    language: Literal["en", "hi", "te"]
    severity: Literal["strong", "soft"]
    where: str
    #: The matched words with a little of the script around them.
    quote: str
    why: str


class PromoReportOut(Strict):
    #: `clear`: nothing found. `check`: wording that is sometimes promotional.
    #: `promotional`: wording that makes a placed call promotional.
    verdict: Literal["clear", "check", "promotional"]
    blocks_launch: bool
    findings: list[FindingOut]
    truncated: bool
    fix: str


class PurposeOut(Strict):
    purpose: Literal[
        "transactional",
        "service_own_customer",
        "relationship_enquiry",
        "relationship_application",
        "promotional",
        "unclear",
    ]
    label: str
    basis: str
    window: str | None
    explanation: str


class AgentPromoCheckOut(Strict):
    agent_id: UUID
    places_calls: bool
    reading: Literal["draft", "saved"]
    report: PromoReportOut


class CampaignPurposeOut(Strict):
    campaign_id: UUID
    agent_id: UUID
    purpose: PurposeOut
    report: PromoReportOut
    blocks_launch: bool


def report_out(report: PromoReport) -> PromoReportOut:
    return PromoReportOut(
        verdict=report.verdict,
        blocks_launch=report.blocks_launch,
        findings=[
            FindingOut(
                phrase=finding.phrase,
                category=finding.category,
                language=finding.language,
                severity=finding.severity,
                where=finding.where,
                quote=finding.quote,
                why=WHY[finding.category],
            )
            for finding in report.findings
        ],
        truncated=report.truncated,
        fix=FIX,
    )


def purpose_out(verdict: PurposeVerdict) -> PurposeOut:
    return PurposeOut(
        purpose=verdict.purpose,
        label=verdict.label,
        basis=verdict.basis,
        window=verdict.window,
        explanation=verdict.explanation,
    )


@router.post(
    "/promo-check",
    response_model=PromoReportOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Check wording for offers and selling before a call says it",
)
async def promo_check(payload: PromoCheckIn, _: AgentReader) -> PromoReportOut:
    parts = [ScriptPart(part.where, part.wording, part.kind) for part in payload.parts]
    return report_out(promo_checks.wording_report(parts))


@router.get(
    "/promo-check/agents/{agent_id}",
    response_model=AgentPromoCheckOut,
    openapi_extra=permission_meta("agents:read"),
    summary="Check an agent's script for offers and selling",
)
async def agent_promo_check(agent_id: UUID, session: Session, _: AgentReader) -> AgentPromoCheckOut:
    check = await promo_checks.agent_check(session, agent_id)
    return AgentPromoCheckOut(
        agent_id=check.agent_id,
        places_calls=check.places_calls,
        reading="draft" if check.reading == "draft" else "saved",
        report=report_out(check.report),
    )


@router.get(
    "/call-purpose/campaigns/{campaign_id}",
    response_model=CampaignPurposeOut,
    openapi_extra=permission_meta("leads:read"),
    summary="What kind of call this campaign places, and whether its script is promotional",
)
async def campaign_call_purpose(
    campaign_id: UUID, session: Session, _: CampaignReader
) -> CampaignPurposeOut:
    check = await promo_checks.campaign_check(session, campaign_id)
    return CampaignPurposeOut(
        campaign_id=check.campaign_id,
        agent_id=check.agent_id,
        purpose=purpose_out(check.purpose),
        report=report_out(check.report),
        blocks_launch=check.blocks_launch,
    )


__all__ = ["purpose_out", "report_out", "router"]
