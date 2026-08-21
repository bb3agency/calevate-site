"""The QA sampling queue — our weekly 5% spot-check, in the admin console (SURFACES §1).

    GET  /v1/admin/qa-samples                 the queue, across clients
    GET  /v1/admin/qa-samples/{sample_id}     one sampled call, transcript REDACTED
    POST /v1/admin/qa-samples/{sample_id}/review

**Admin realm, not client.** SURFACES §1 puts it there in as many words — "QA sampling:
spot-check ~5% of calls per client per week (queue surfaced in admin)" — and the reason
survives inspection: this is OUR quality process, worked by OUR reviewers, and the row
carries a verdict one of us formed about the client's call. Shipping it into the client
app would publish our internal grading of their calls and turn an internal control into
a support conversation. What the client gets from the same control is the monthly report
(`/v1/quality/reports`, client realm) — the claim, not the working.

ISOLATION (hard rule 1) — the `admin/holds.py` shape, for the same reasons
--------------------------------------------------------------------------
`qa_call_samples` is FORCE-RLS'd on `app.tenant_id` and `app.admin` widens
`organizations` and nothing else (b57e2f9c4a13). So the queue is built the way the hold
queue is: enumerate tenants on the directory session, then ENTER each tenant with
`tenant_session()` and read its own rows under ordinary RLS. Nothing is widened, no
policy changes, and no request ever holds a cross-tenant view of a call.

The cost is N+1 by construction — the trade `tenant_overview` and `held_tenants` both
document, payable at M1 scale and answered by a materialized queue if the client list
ever gets long enough to notice.

HARD RULE 5 — WHAT A REVIEWER SEES
-----------------------------------
The detail route returns `crm.service.get_call(session, call_id, raw=False)`: the SAME
function, with the SAME argument, that serves the client's own call screen, so the
transcript is `text_redacted` and the summary has been through the identical `redact()`
pass. There is deliberately NO raw variant on this router. Raw transcript text has
exactly one route in this codebase — `GET /v1/calls/{call_id}/transcript/raw`,
`calls:read_raw` plus an `audit_log` write in the same transaction — and a reviewer who
needs it uses that one, from the client realm, and is audited like everybody else. A
second raw path built for convenience is a second answer to hard rule 5, and the second
answer is always the one that rots.

The detail read IS audited even though it is redacted (`qa_sample.read`). SEC-COMP §5
makes admin reads auditable, and unlike the hold queue — which discloses no personal
data and is refreshed all day — this route discloses one call's conversation to somebody
outside the tenant. That is exactly the read an audit trail exists for. The LIST is not
audited: it carries ids, timings and tags and is the page a reviewer refreshes.

PERMISSIONS
------------
* list — `org:read`. Reading a work list is not acting on it, and D-22 forbids gating a
  GET on a permission read-only impersonation refuses (`holds_routes.py` makes this
  argument in full). Both admin roles hold it.
* detail — `calls:read`. It discloses a redacted call, which is precisely what that
  permission means in the client realm; using the same name for the same disclosure
  keeps one vocabulary. Both admin roles hold it; neither holds `calls:read_raw` except
  `superadmin`, and this route never asks for raw anyway.
* review — `admin:tenants`. Recording a verdict is a mutation, so it carries a mutating
  permission and an impersonating admin is refused it (D-22, no acting-as).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm import service as crm
from apps.api.crm.schemas import CallDetailOut
from apps.api.db.session import tenant_session
from apps.api.quality import sampling
from apps.api.quality.models import QA_SAMPLE_RATE, QA_VERDICTS, Verdict

router = APIRouter(prefix="/v1/admin/qa-samples", tags=["admin"])

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py` and this module is `sampling_routes.py` — the same situation and the
# same resolution as `holds_routes.py`.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
QueueReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
CallReader = Annotated[Principal, Depends(requires("calls:read", realm="admin"))]
Reviewer = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

_DIRECTORY = "SELECT id, name, slug FROM organizations WHERE deleted_at IS NULL ORDER BY name"


class QaSampleOut(BaseModel):
    """One sampled call. Ids, timings and tags — no transcript text, no phone number."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    call_id: UUID
    agent_name: str

    #: The draw, in full, so the queue can defend itself: the IST week, how many calls
    #: that week held, how many 5% came to, this call's rank in the deterministic order,
    #: and the seed that order was computed from. `selection_seed` is on the wire on
    #: purpose — it is what lets anyone re-run `md5(seed || call_id)` and check us.
    week_start: date
    population: int
    target: int
    selection_rank: int
    selection_seed: str
    selected_at: datetime

    started_at: datetime | None
    duration_s: int | None
    direction: str
    outcome_tag: str | None
    sentiment: str | None
    disclosure_played: bool | None

    verdict: Verdict | None
    reviewed_at: datetime | None


class QaSampleDetailOut(BaseModel):
    """A sampled call opened for review — the queue row plus the REDACTED call.

    `call` is `CallDetailOut` exactly as the client's own screen receives it: transcript
    turns hold `text_redacted` and each carries `redacted: true`. This model adds no
    field of its own to the call, which is the point — there is one shape for "a call as
    a human reads it", and this surface uses it rather than defining a reviewer's
    variant that could quietly diverge on what it masks.
    """

    model_config = ConfigDict(extra="forbid")

    sample: QaSampleOut
    call: CallDetailOut


class QaReviewIn(BaseModel):
    """A reviewer's conclusion. An enum and nothing else.

    No note field, deliberately (hard rule 6): a free-text box on a cross-tenant queue is
    an invitation to type what the caller said into it, and `admin/holds.py` already
    refuses operator prose on a list for exactly that reason. What a reviewer found that
    the enum cannot express belongs in the incident it justifies, not in this row.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict


def _out(row: sampling.SampledCall, *, tenant_id: UUID, name: str, slug: str) -> QaSampleOut:
    return QaSampleOut(
        id=row.id,
        tenant_id=tenant_id,
        tenant_name=name,
        tenant_slug=slug,
        call_id=row.call_id,
        agent_name=row.agent_name,
        week_start=row.week_start,
        population=row.population,
        target=row.target,
        selection_rank=row.selection_rank,
        selection_seed=row.selection_seed,
        selected_at=row.selected_at,
        started_at=row.started_at,
        duration_s=row.duration_s,
        direction=row.direction,
        outcome_tag=row.outcome_tag,
        sentiment=row.sentiment,
        disclosure_played=row.disclosure_played,
        # The DB CHECK pins exactly these three strings, so the widening from `str | None`
        # to the Literal is safe — and if somebody widens the CHECK without widening
        # `Verdict`, pydantic refuses the row here rather than serving an unknown verdict.
        verdict=row.verdict,
        reviewed_at=row.reviewed_at,
    )


async def _directory(session: AsyncSession) -> list[tuple[UUID, str, str]]:
    rows = (await session.execute(text(_DIRECTORY))).all()
    return [(UUID(str(r[0])), str(r[1]), str(r[2])) for r in rows]


@router.get(
    "",
    response_model=list[QaSampleOut],
    openapi_extra=permission_meta("org:read"),
    summary=f"The weekly QA spot-check queue — {round(QA_SAMPLE_RATE * 100)}% of calls per client",
    description=(
        "Calls drawn for review, newest week first and in the draw's own order. Each row "
        "carries the frame it came from — the week, the number of calls in it, the "
        "number drawn — and the seed the order was computed from, so the sample can be "
        "recomputed and checked by anyone. `pending` (default) shows only calls nobody "
        "has reviewed yet. No transcript text and no phone number appear on this list."
    ),
)
async def list_qa_samples(
    session: AdminSession,
    principal: QueueReader,
    pending: bool = Query(True, description="only calls nobody has reviewed yet"),
    limit: int = Query(200, ge=1, le=500),
) -> list[QaSampleOut]:
    del principal  # the dependency IS the authorization
    queue: list[QaSampleOut] = []
    for tenant_id, name, slug in await _directory(session):
        async with tenant_session(tenant_id) as scoped:
            rows = await sampling.list_samples(scoped, pending_only=pending, limit=limit)
        queue += [_out(row, tenant_id=tenant_id, name=name, slug=slug) for row in rows]
    # Newest week first across ALL clients, then by the draw's own rank — the same order
    # each tenant's list already has, merged rather than re-decided.
    queue.sort(key=lambda row: (row.week_start, -row.selection_rank), reverse=True)
    return queue[:limit]


async def _locate(
    directory: AsyncSession, sample_id: UUID
) -> tuple[UUID, str, str, sampling.SampledCall]:
    """Find which tenant owns a sample, by asking each tenant's own RLS-scoped session.

    There is no cross-tenant read here and there is deliberately no `tenant_id` in the
    URL: an id the caller supplies alongside the row it names is a second source of truth
    about ownership, and the two can disagree. RLS answers the question instead.
    """
    for tenant_id, name, slug in await _directory(directory):
        async with tenant_session(tenant_id) as scoped:
            row = await sampling.find_sample(scoped, sample_id)
        if row is not None:
            return tenant_id, name, slug, row
    raise ProblemError.not_found("QA sample")


@router.get(
    "/{sample_id}",
    response_model=QaSampleDetailOut,
    openapi_extra=permission_meta("calls:read"),
    summary="A sampled call for review — transcript REDACTED (hard rule 5), read audited",
    description=(
        "The sampled call as a reviewer reads it: the draw's own record, and the call "
        "with its transcript in the redacted form every ordinary reader gets. Raw "
        "transcript text is NOT available here — it has one route in this API, which is "
        "role-checked and audit-logged. This read is itself written to the audit log."
    ),
)
async def get_qa_sample(
    sample_id: UUID,
    session: AdminSession,
    request: Request,
    principal: CallReader,
) -> QaSampleDetailOut:
    tenant_id, name, slug, row = await _locate(session, sample_id)
    async with tenant_session(tenant_id) as scoped:
        # The audit row is written in the SAME transaction as the read, so there is no
        # window in which a reviewer saw a client's conversation without it being
        # recorded — the shape `crm/routes.py::get_raw_transcript` uses. Redacted or not,
        # this is one tenant's call disclosed to somebody outside that tenant.
        await write_audit(
            scoped,
            action="qa_sample.read",
            actor=principal,
            tenant_id=tenant_id,
            object_type="call",
            object_id=str(row.call_id),
            ip=client_request_ip(request),
        )
        call = await crm.get_call(scoped, row.call_id, raw=False)
    return QaSampleDetailOut(sample=_out(row, tenant_id=tenant_id, name=name, slug=slug), call=call)


@router.post(
    "/{sample_id}/review",
    response_model=QaSampleOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record a reviewer's verdict on a sampled call — first writer wins",
    description=(
        "Records what the reviewer concluded: `clean`, `concern` or `defect`. A call can "
        "only be reviewed once — a second verdict is refused rather than overwriting the "
        "first, so a disagreement is visible instead of silent. Audit-logged."
    ),
)
async def review_qa_sample(
    sample_id: UUID,
    body: QaReviewIn,
    session: AdminSession,
    request: Request,
    principal: Reviewer,
) -> QaSampleOut:
    tenant_id, name, slug, _row = await _locate(session, sample_id)
    # `requires(..., realm="admin")` resolved this principal against `admin_users`, so
    # the id is present — and the CHECK behind this write refuses a verdict that cannot
    # name its reviewer, so a None here would surface as an IntegrityError at commit
    # instead of a clear failure at the top (the argument `first_campaign_routes` makes).
    assert principal.user_id is not None
    async with tenant_session(tenant_id) as scoped:
        reviewed = await sampling.record_review(
            scoped, sample_id=sample_id, verdict=body.verdict, admin_id=principal.user_id
        )
        await write_audit(
            scoped,
            action="qa_sample.reviewed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="call",
            object_id=str(reviewed.call_id),
            # The verdict is one of three of OUR words — not prose, not caller content —
            # so it is safe in the ledger, and the entry is useless without it.
            summary={"verdict": reviewed.verdict},
            ip=client_request_ip(request),
        )
    return _out(reviewed, tenant_id=tenant_id, name=name, slug=slug)


__all__ = ["QA_VERDICTS", "router"]
