"""The client's monthly QA report, in-app (SURFACES §2 trust surfaces, D-15).

    GET /v1/quality/reports

**Client realm, not admin.** The report is a document we SHOW a client — SURFACES lists
it under "trust surfaces (our differentiators made visible)", beside the redacted
transcript and the latency badge. Its whole value is that the client reads it. An admin
copy of this screen would be a report about the client that the client cannot see, which
is the opposite of the asset D-15 describes.

**`agents:read`, not `calls:read` and not `billing:read`.** The document is a statement
about the AGENT's behaviour and contains nothing from any call (see below), so it is
gated on the permission that means "may look at how this agent is configured and how it
behaves". Both client roles hold it, which is intended: `staff` are the people who work
the calls this agent produces, and a trust document nobody in the office may open is not
a trust document. It is also non-mutating, so read-only impersonation can open it (D-22)
and an operator on a support call sees exactly what the client sees.

**No audit row.** Nothing here is personal data — the payload is scenario class labels
(ours), extraction field labels (the client's own column names) and counts — and this is
a page a client may refresh. An audit chain that grows a row per page view stops being
readable, which is the argument `kyc_routes.py` and `holds_routes.py` both make. The
DOCUMENT's own honesty rules are enforced upstream in the generator and asserted against
every fixture transcript (`tests/eval_qa_report_test.py`, `tests/qa_report_in_app_test`).

**Nothing is computed here.** See `service.py`: the numbers are the harness's, stored per
run. A second computation would be a QA report that can disagree with itself.
"""

from __future__ import annotations

from typing import Annotated

from calevate_shared.qa_report import QaReport
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.quality import service

router = APIRouter(prefix="/v1/quality", tags=["quality"])

Session = Annotated[AsyncSession, Depends(db)]


@router.get(
    "/reports",
    response_model=list[QaReport],
    openapi_extra=permission_meta("agents:read"),
    summary="Monthly QA reports, newest month first (D-15)",
    description=(
        "Every stored quality report for this account, newest month first. Each one is "
        "the regression run we do before any change to the agent: how many scenarios "
        "were replayed, how many defects were found (zero is the only acceptable "
        "number), and which of your columns the model does not yet fill. An EMPTY list "
        "means no run has been stored for this account yet — it does not mean a clean "
        "run. Contains nothing from any real call."
    ),
)
async def list_quality_reports(
    session: Session,
    limit: int = Query(12, ge=1, le=60),
    _: Principal = Depends(requires("agents:read")),
) -> list[QaReport]:
    return await service.list_reports(session, limit=limit)


__all__ = ["router"]
