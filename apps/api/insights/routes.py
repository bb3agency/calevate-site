"""Client-realm Knowledge Gaps read (SURFACES §2 — the urgent surface).

Every route declares its permission twice, the pattern `crm/routes.py` documents: a
dependency that ENFORCES it and `openapi_extra` that DOCUMENTS it, checked at boot by
`assert_policy_registry_complete`.

NO RAW-TRANSCRIPT GATE HERE, and its absence is the design: every quote this surface
returns comes from a column that only ever holds redacted text (hard rule 6). Reading is
`calls:read` (owner + staff). Answering or dismissing a gap is done by topic, through the
Questions to answer routes (`teach/routes.py`, D-893), which close every agent's gap on
that topic at once.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.insights import service
from apps.api.insights.schemas import KnowledgeGapListOut

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


__all__ = ["router"]
