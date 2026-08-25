"""Client-realm Knowledge Gaps endpoints (SURFACES §2 — the urgent surface).

Every route declares its permission twice, the pattern `crm/routes.py` documents: a
dependency that ENFORCES it and `openapi_extra` that DOCUMENTS it, checked at boot by
`assert_policy_registry_complete`.

NO RAW-TRANSCRIPT GATE HERE, and its absence is the design: every quote this surface
returns comes from a column that only ever holds redacted text (hard rule 6). Reading is
`calls:read` (owner + staff); acting on a gap — dismiss or teach — is `kb:write`, because
both are decisions about what the agent knows, the same permission the agent page's
knowledge controls carry (D-21). Both mutations write an `audit_log` row, like every other
client mutation.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.insights import service
from apps.api.insights.schemas import (
    GapDismissIn,
    GapTeachIn,
    KnowledgeGapListOut,
    KnowledgeGapOut,
)

router = APIRouter(prefix="/v1", tags=["insights"])

Session = Annotated[AsyncSession, Depends(db)]


@router.get(
    "/knowledge-gaps",
    response_model=KnowledgeGapListOut,
    openapi_extra=permission_meta("calls:read"),
    summary="Questions the agents could not answer — urgent first, across all agents",
)
async def list_knowledge_gaps(
    session: Session,
    agent_id: UUID | None = Query(default=None),
    status: str | None = Query(
        default="open",
        description="open (default, the urgent set) · taught · dismissed · all",
    ),
    limit: int = Query(default=50, ge=1, le=service.MAX_PAGE),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(requires("calls:read")),
) -> KnowledgeGapListOut:
    # "all" is the escape hatch for the history view; any other value is passed through as
    # a status filter, and an unknown one simply matches nothing rather than erroring.
    status_filter = None if status == "all" else status
    return await service.list_gaps(
        session, agent_id=agent_id, status=status_filter, limit=limit, offset=offset
    )


@router.post(
    "/knowledge-gaps/{gap_id}/dismiss",
    response_model=KnowledgeGapOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Dismiss a knowledge gap — it leaves the urgent list, occurrences stay",
)
async def dismiss_knowledge_gap(
    gap_id: UUID,
    payload: GapDismissIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("kb:write")),
) -> KnowledgeGapOut:
    out = await service.dismiss_gap(session, gap_id, principal=principal, reason=payload.reason)
    await write_audit(
        session,
        action="knowledge_gap.dismiss",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="knowledge_gap",
        object_id=str(gap_id),
        ip=client_request_ip(request),
        # Ids and a boolean — never the reason text or the quote, both of which are
        # transcript-derived and belong in no log line (hard rule 6).
        summary={"topic_key": out.topic_key, "had_reason": bool(payload.reason)},
    )
    return out


@router.post(
    "/knowledge-gaps/{gap_id}/teach",
    response_model=KnowledgeGapOut,
    openapi_extra=permission_meta("kb:write"),
    summary="Teach the missing answer — records it and seeds a KB draft for review",
)
async def teach_knowledge_gap(
    gap_id: UUID,
    payload: GapTeachIn,
    session: Session,
    request: Request,
    principal: Principal = Depends(requires("kb:write")),
) -> KnowledgeGapOut:
    out = await service.teach_gap(session, gap_id, principal=principal, payload=payload)
    await write_audit(
        session,
        action="knowledge_gap.teach",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="knowledge_gap",
        object_id=str(gap_id),
        ip=client_request_ip(request),
        # `kb_drafted` records whether a review draft was seeded; the taught answer itself
        # is client content and is not logged.
        summary={"topic_key": out.topic_key, "kb_drafted": payload.create_kb_draft},
    )
    return out


__all__ = ["router"]
