"""The auto-healer's three surfaces (D-701).

    GET    /v1/healer/incidents                   the client's own incidents, in plain words
    POST   /v1/healer/incidents/{id}/restore      the client gives their line back
    GET    /v1/healer/fallback-phone              the phone callers are handed to
    PUT    /v1/healer/fallback-phone              set it (owner)
    DELETE /v1/healer/fallback-phone              remove it (owner)
    GET    /v1/healer/proposals                   suggested fixes waiting for a person
    POST   /v1/healer/proposals/{id}/apply        approve one (only a script rollback changes
                                                  anything)
    POST   /v1/healer/proposals/{id}/dismiss      dismiss one

    GET    /v1/ops/healer                         playbooks, kill switches, paging channel
    GET    /v1/ops/healer/incidents               every incident, open first
    GET    /v1/ops/healer/actions                 the ledger
    POST   /v1/ops/healer/incidents/{id}/resolve  close an incident, giving back any held line
    POST   /v1/ops/healer/incidents/{id}/retry    run its next step now
    PUT    /v1/ops/healer/incidents/{id}/status   show or hide it on the status page
    POST   /v1/ops/healer/status-posts            post something on the status page by hand

    GET    /v1/public/status                      the public status page's data

Client reads are `org:read`; client writes `org:manage`, which a view-as session may use,
and every write is audited in the request's own transaction. The operator surface is
`ops:manage` in the admin realm; the two that change what clients or the public see take a
step-up. The public read discloses no tenant, agent or alarm code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.handoff import india_handoff_number
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import get_settings
from apps.api.core.stepup import StepUpGate
from apps.api.db.base import uuid7
from apps.api.healer import incidents, ledger, notices, proposals, protection
from apps.api.healer import status as status_page
from apps.api.healer.playbooks import PLAYBOOKS, paused_keys, unknown_paused_keys

router = APIRouter(prefix="/v1/healer", tags=["healer"])
ops_router = APIRouter(prefix="/v1/ops/healer", tags=["ops"])
public_router = APIRouter(prefix="/v1/public", tags=["public"])

Session = Annotated[AsyncSession, Depends(db)]
GlobalSession = Annotated[AsyncSession, Depends(global_db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Writer = Annotated[Principal, Depends(requires("org:manage"))]
Operator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]

LIST_MAX: Final = 100
STATUS_CACHE_CONTROL: Final = "public, max-age=30"


def resolve_confirmation(incident_id: UUID) -> str:
    return f"resolve_heal_incident:{incident_id}"


def status_confirmation(incident_id: UUID | None) -> str:
    return f"post_status:{incident_id}" if incident_id else "post_status"


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _actor(principal: Principal) -> tuple[Literal["admin", "user"], UUID | None]:
    return ("admin" if principal.is_admin else "user"), principal.user_id


# --- client ---------------------------------------------------------------------------------


class CallBackOut(_Out):
    """A caller who reached the line while it was not working properly."""

    call_id: UUID
    at: datetime


class ClientIncidentOut(_Out):
    id: UUID
    agent_id: UUID | None
    agent_name: str | None
    kind: Literal["agent_unwell", "line_protected", "platform_outage"]
    protection: Literal["none", "paused", "forwarded"]
    state: Literal["open", "resolved"]
    opened_at: datetime
    resolved_at: datetime | None
    campaigns_paused: int
    requeued: int
    missed_calls: int
    must_act: bool
    can_restore: bool
    headline: str
    what_happened: str
    what_we_did: str
    your_part: str
    call_backs: list[CallBackOut]


class ClientIncidentsOut(_Out):
    open: int
    items: list[ClientIncidentOut]


_CLIENT_ROWS = (
    "SELECT ci.id, ci.agent_id, a.name, ci.kind, ci.protection, ci.state, ci.opened_at, "
    "ci.resolved_at, ci.campaigns_paused, ci.requeued, ci.missed_calls, ci.must_act, "
    "i.last_outcome, ci.incident_id, i.scope FROM heal_client_incidents ci "
    "JOIN heal_incidents i ON i.id = ci.incident_id LEFT JOIN agents a ON a.id = ci.agent_id"
)

#: How many callers one incident lists for calling back; the rest are on the calls screen.
CALL_BACKS_MAX: Final = 20


async def _call_backs(
    session: AsyncSession, *, agent_id: UUID | None, since: datetime, until: datetime | None
) -> list[CallBackOut]:
    if agent_id is None:
        return []
    rows = (
        await session.execute(
            text(
                "SELECT id, created_at FROM calls WHERE agent_id = :aid AND direction = "
                "'inbound' AND NOT trial_call AND created_at >= :since AND (CAST(:until AS "
                "timestamptz) IS NULL OR created_at <= :until) AND (status = 'failed' OR "
                "(status = 'completed' AND coalesce(duration_s, 0) < :short)) "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {
                "aid": agent_id,
                "since": since,
                "until": until,
                "short": 10,
                "limit": CALL_BACKS_MAX,
            },
        )
    ).all()
    return [CallBackOut(call_id=r[0], at=r[1]) for r in rows]


async def _client_out(
    session: AsyncSession, row: Any, fallback: str | None, has_proposal: bool
) -> ClientIncidentOut:
    notice = notices.line_notice(
        kind=str(row[3]),
        protection=str(row[4]),
        agent_name=row[2],
        campaigns_paused=int(row[8]),
        fallback_phone=fallback,
        state=str(row[5]),
        missed_calls=int(row[10]),
        requeued=int(row[9]),
        worst_signal=(row[12] or "").removeprefix("signal:") or None,
        has_proposal=has_proposal,
    )
    return ClientIncidentOut(
        id=row[0],
        agent_id=row[1],
        agent_name=row[2],
        kind=row[3],
        protection=row[4],
        state=row[5],
        opened_at=row[6],
        resolved_at=row[7],
        campaigns_paused=int(row[8]),
        requeued=int(row[9]),
        missed_calls=int(row[10]),
        must_act=bool(row[11]),
        can_restore=row[5] == "open" and row[4] != "none",
        headline=notice.headline,
        what_happened=notice.what_happened,
        what_we_did=notice.what_we_did,
        your_part=notice.your_part,
        call_backs=await _call_backs(session, agent_id=row[1], since=row[6], until=row[7])
        if row[3] != "agent_unwell"
        else [],
    )


@router.get(
    "/incidents",
    response_model=ClientIncidentsOut,
    summary="Problems with your lines, what we did, and whether you need to act",
    openapi_extra=permission_meta("org:read"),
)
async def list_client_incidents(
    session: Session,
    principal: Reader,
    days: int = Query(30, ge=1, le=90, description="How many days of history to include."),
    limit: int = Query(20, ge=1, le=LIST_MAX, description="How many to return."),
) -> ClientIncidentsOut:
    rows = (
        await session.execute(
            text(
                _CLIENT_ROWS + " WHERE ci.state = 'open' OR ci.opened_at >= now() - "
                "make_interval(days => :days) ORDER BY (ci.state = 'open') DESC, "
                "ci.opened_at DESC LIMIT :limit"
            ),
            {"days": days, "limit": limit},
        )
    ).all()
    fallback = await protection.fallback_phone(session)
    has_proposal = bool(await proposals.pending_for_tenant(session, limit=1))
    items = [await _client_out(session, r, fallback, has_proposal) for r in rows]
    open_count = (
        await session.execute(
            text("SELECT count(*) FROM heal_client_incidents WHERE state = 'open'")
        )
    ).scalar_one()
    return ClientIncidentsOut(open=int(open_count), items=items)


@router.post(
    "/incidents/{incident_id}/restore",
    response_model=ClientIncidentOut,
    summary="Turn your line back on now",
    openapi_extra=permission_meta("org:manage"),
)
async def restore_client_line(
    incident_id: UUID, session: Session, principal: Writer, request: Request
) -> ClientIncidentOut:
    assert principal.tenant_id is not None
    row = (
        await session.execute(
            text(_CLIENT_ROWS + " WHERE ci.id = :id FOR UPDATE OF ci"), {"id": incident_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Incident")
    if row[5] != "open" or row[4] == "none" or row[1] is None:
        raise ProblemError.conflict(
            "line_not_held",
            "This line is already taking calls.",
            remediation="Refresh the page to see where it stands.",
        )
    actor_type, actor_id = _actor(principal)
    restored = await protection.restore_agent(
        session, tenant_id=principal.tenant_id, incident_id=row[13], agent_id=row[1]
    )
    if row[14] == "agent":
        await session.execute(
            text(
                "UPDATE heal_incidents SET state = 'resolved', resolved_at = now(), "
                "last_outcome = 'restored_by_person', updated_at = now() WHERE id = :id "
                "AND resolved_at IS NULL"
            ),
            {"id": row[13]},
        )
    await ledger.record(
        session,
        playbook="line_protection",
        step="restore",
        outcome="ok",
        incident_id=row[13],
        tenant_id=principal.tenant_id,
        agent_id=row[1],
        detail=f"by the client; requeued={restored.requeued}",
        actor_type=actor_type,
        actor_id=actor_id,
    )
    await write_audit(
        session,
        actor=principal,
        action="healer.line_restored",
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(row[1]),
        ip=client_request_ip(request),
        summary={"incident_id": str(row[13]), "requeued": restored.requeued},
    )
    fresh = (
        await session.execute(text(_CLIENT_ROWS + " WHERE ci.id = :id"), {"id": incident_id})
    ).one()
    return await _client_out(session, fresh, await protection.fallback_phone(session), False)


def _india_mobile(value: str) -> str:
    india_handoff_number(value)
    if not value.startswith("+91") or len(value) != 13 or value[3] not in "6789":
        raise ValueError("Enter an Indian mobile number, starting +91.")
    return value


class FallbackPhoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_e164: Annotated[str, Field(pattern=r"^\+91[6-9]\d{9}$"), AfterValidator(_india_mobile)]


class FallbackPhoneOut(_Out):
    phone_e164: str | None
    updated_at: datetime | None
    #: Whether the calling service can pass callers to this phone, or only play a message.
    forwarding_supported: bool


def _forwarding_supported() -> bool:
    from apps.api.agents.service import ForwardsLine
    from apps.api.engine import get_engine

    return isinstance(get_engine(), ForwardsLine)


async def _fallback_out(session: AsyncSession) -> FallbackPhoneOut:
    row = (
        await session.execute(text("SELECT phone_e164, updated_at FROM heal_fallback_phones"))
    ).first()
    return FallbackPhoneOut(
        phone_e164=row[0] if row else None,
        updated_at=row[1] if row else None,
        forwarding_supported=_forwarding_supported(),
    )


@router.get(
    "/fallback-phone",
    response_model=FallbackPhoneOut,
    summary="The phone your callers are passed to if your agent cannot take calls",
    openapi_extra=permission_meta("org:read"),
)
async def get_fallback_phone(session: Session, principal: Reader) -> FallbackPhoneOut:
    return await _fallback_out(session)


@router.put(
    "/fallback-phone",
    response_model=FallbackPhoneOut,
    summary="Set the phone your callers are passed to if your agent cannot take calls",
    openapi_extra=permission_meta("org:manage"),
)
async def put_fallback_phone(
    payload: FallbackPhoneIn, session: Session, principal: Writer, request: Request
) -> FallbackPhoneOut:
    assert principal.tenant_id is not None
    await session.execute(
        text(
            "INSERT INTO heal_fallback_phones (id, tenant_id, phone_e164, updated_by, "
            "created_at, updated_at) VALUES (:id, :tid, :phone, :by, now(), now()) "
            "ON CONFLICT (tenant_id) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164, "
            "updated_by = EXCLUDED.updated_by, updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": principal.tenant_id,
            "phone": payload.phone_e164,
            "by": principal.user_id,
        },
    )
    await write_audit(
        session,
        actor=principal,
        action="healer.fallback_phone_set",
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={"set": True},
    )
    return await _fallback_out(session)


@router.delete(
    "/fallback-phone",
    response_model=FallbackPhoneOut,
    summary="Stop passing callers to a phone; a held line plays a short message instead",
    openapi_extra=permission_meta("org:manage"),
)
async def delete_fallback_phone(
    session: Session, principal: Writer, request: Request
) -> FallbackPhoneOut:
    assert principal.tenant_id is not None
    await session.execute(text("DELETE FROM heal_fallback_phones"))
    await write_audit(
        session,
        actor=principal,
        action="healer.fallback_phone_removed",
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={"set": False},
    )
    return await _fallback_out(session)


class ProposalOut(_Out):
    id: UUID
    agent_id: UUID
    agent_name: str | None
    kind: Literal["rollback_prompt", "review_knowledge", "review_languages"]
    status: Literal["pending", "applied", "dismissed", "expired"]
    title: str
    body: str
    action_label: str
    #: The screen that makes the change, for a suggestion only the client can carry out.
    screen: Literal["knowledge", "agents"] | None
    can_apply: bool
    created_at: datetime
    decided_at: datetime | None


class ProposalsOut(_Out):
    pending: int
    items: list[ProposalOut]


def _proposal_out(p: proposals.Proposal) -> ProposalOut:
    copy = proposals.COPY[p.kind]
    screen = copy.get("screen")
    return ProposalOut(
        id=p.id,
        agent_id=p.agent_id,
        agent_name=p.agent_name,
        kind=p.kind,  # type: ignore[arg-type]
        status=p.status,  # type: ignore[arg-type]
        title=copy["title"],
        body=copy["body"],
        action_label=copy["action"],
        screen=screen,  # type: ignore[arg-type]
        can_apply=p.kind == "rollback_prompt" and p.status == "pending",
        created_at=p.created_at,
        decided_at=p.decided_at,
    )


@router.get(
    "/proposals",
    response_model=ProposalsOut,
    summary="Changes we suggest for a struggling agent; nothing changes until you approve",
    openapi_extra=permission_meta("org:read"),
)
async def list_proposals(
    session: Session,
    principal: Reader,
    days: int = Query(30, ge=1, le=90, description="How many days of decided ones to include."),
    limit: int = Query(20, ge=1, le=LIST_MAX, description="How many to return."),
) -> ProposalsOut:
    rows = await proposals.list_for_tenant(session, days=days, limit=limit)
    return ProposalsOut(
        pending=sum(1 for p in rows if p.status == "pending"),
        items=[_proposal_out(p) for p in rows],
    )


async def _decided(
    session: AsyncSession,
    principal: Principal,
    request: Request,
    proposal: proposals.Proposal,
    *,
    decision: Literal["applied", "dismissed"],
) -> ProposalOut:
    assert principal.tenant_id is not None
    actor_type, actor_id = _actor(principal)
    await ledger.record(
        session,
        playbook="agent_repair",
        step="decide",
        outcome="ok",
        tenant_id=principal.tenant_id,
        agent_id=proposal.agent_id,
        detail=f"{proposal.kind} {decision}",
        actor_type=actor_type,
        actor_id=actor_id,
    )
    await write_audit(
        session,
        actor=principal,
        action=f"healer.proposal_{decision}",
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(proposal.agent_id),
        ip=client_request_ip(request),
        summary={"proposal_id": str(proposal.id), "kind": proposal.kind},
    )
    fresh = [
        p
        for p in await proposals.list_for_tenant(session, days=90, limit=LIST_MAX)
        if p.id == proposal.id
    ]
    return _proposal_out(fresh[0] if fresh else proposal)


@router.post(
    "/proposals/{proposal_id}/apply",
    response_model=ProposalOut,
    summary="Approve a suggested change",
    openapi_extra=permission_meta("org:manage"),
)
async def apply_proposal(
    proposal_id: UUID, session: Session, principal: Writer, request: Request
) -> ProposalOut:
    assert principal.tenant_id is not None
    proposal = await proposals.apply(
        session,
        tenant_id=principal.tenant_id,
        proposal_id=proposal_id,
        by=principal.user_id,
        author=principal.client_user_id,
    )
    return await _decided(session, principal, request, proposal, decision="applied")


@router.post(
    "/proposals/{proposal_id}/dismiss",
    response_model=ProposalOut,
    summary="Dismiss a suggested change",
    openapi_extra=permission_meta("org:manage"),
)
async def dismiss_proposal(
    proposal_id: UUID, session: Session, principal: Writer, request: Request
) -> ProposalOut:
    proposal = await proposals.dismiss(session, proposal_id=proposal_id, by=principal.user_id)
    return await _decided(session, principal, request, proposal, decision="dismissed")


# --- operator -------------------------------------------------------------------------------


class PlaybookOut(_Out):
    key: str
    title: str
    triggers: list[str]
    action: str
    verify: str
    undo: str
    max_attempts: int
    cooldown_s: int
    blast_radius: Literal["agent", "tenant", "platform"]
    job: str | None
    automatic: bool
    pausable: bool
    paused: bool


class PagingOut(_Out):
    #: Whether this deployment can send WhatsApp at all, and if not which thing is missing.
    whatsapp_available: bool
    whatsapp_reason: str | None
    whatsapp_enabled: bool
    founder_number_set: bool
    #: The number was set in the console, which is the opt-in the send rests on.
    founder_number_from_console: bool
    email_set: bool


class HealerOverviewOut(_Out):
    enabled: bool
    paused: list[str]
    unknown_paused: list[str]
    playbooks: list[PlaybookOut]
    paging: PagingOut
    open_incidents: int
    escalated_incidents: int


@ops_router.get(
    "",
    response_model=HealerOverviewOut,
    summary="The healer's playbooks, kill switches and paging channels",
    openapi_extra=permission_meta("ops:manage"),
)
async def healer_overview(session: GlobalSession, principal: Operator) -> HealerOverviewOut:
    from apps.workers.whatsapp import whatsapp_delivery_status

    settings = get_settings()
    paused = paused_keys()
    counts = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE resolved_at IS NULL), count(*) FILTER (WHERE "
                "state = 'escalated' AND resolved_at IS NULL) FROM heal_incidents"
            )
        )
    ).one()
    console_set = (
        await session.execute(
            text("SELECT 1 FROM platform_settings WHERE key = 'healer_founder_whatsapp'")
        )
    ).first()
    delivery = whatsapp_delivery_status()
    return HealerOverviewOut(
        enabled=settings.healer_enabled,
        paused=sorted(paused),
        unknown_paused=list(unknown_paused_keys()),
        playbooks=[
            PlaybookOut(
                key=p.key,
                title=p.title,
                triggers=list(p.triggers),
                action=p.action,
                verify=p.verify,
                undo=p.undo,
                max_attempts=p.max_attempts,
                cooldown_s=p.cooldown_s,
                blast_radius=p.blast_radius,
                job=p.job,
                automatic=p.automatic,
                pausable=p.pausable,
                paused=p.pausable and (p.key in paused or not settings.healer_enabled),
            )
            for p in PLAYBOOKS
        ],
        paging=PagingOut(
            whatsapp_available=delivery.available,
            whatsapp_reason=delivery.reason,
            whatsapp_enabled=settings.whatsapp_enabled,
            founder_number_set=bool(settings.healer_founder_whatsapp),
            founder_number_from_console=console_set is not None,
            email_set=bool(settings.alerts_email),
        ),
        open_incidents=int(counts[0]),
        escalated_incidents=int(counts[1]),
    )


class IncidentOut(_Out):
    id: UUID
    playbook: str
    trigger_code: str
    scope: Literal["agent", "tenant", "platform"]
    tenant_id: UUID | None
    agent_id: UUID | None
    state: Literal["open", "mitigated", "escalated", "resolved"]
    attempts: int
    next_attempt_at: datetime | None
    component: Literal["calls", "dashboard", "numbers", "assistant"] | None
    public: bool
    public_title: str | None
    last_outcome: str | None
    opened_at: datetime
    mitigated_at: datetime | None
    escalated_at: datetime | None
    resolved_at: datetime | None


class IncidentsOut(_Out):
    items: list[IncidentOut]


def _incident_out(i: incidents.Incident) -> IncidentOut:
    return IncidentOut(
        id=i.id,
        playbook=i.playbook,
        trigger_code=i.trigger_code,
        scope=i.scope,  # type: ignore[arg-type]
        tenant_id=i.tenant_id,
        agent_id=i.agent_id,
        state=i.state,  # type: ignore[arg-type]
        attempts=i.attempts,
        next_attempt_at=i.next_attempt_at,
        component=i.component,  # type: ignore[arg-type]
        public=i.public,
        public_title=i.public_title,
        last_outcome=i.last_outcome,
        opened_at=i.opened_at,
        mitigated_at=i.mitigated_at,
        escalated_at=i.escalated_at,
        resolved_at=i.resolved_at,
    )


@ops_router.get(
    "/incidents",
    response_model=IncidentsOut,
    summary="Every healer incident, unresolved first",
    openapi_extra=permission_meta("ops:manage"),
)
async def list_incidents(
    session: GlobalSession,
    principal: Operator,
    days: int = Query(7, ge=1, le=90, description="How many days of resolved ones to include."),
    limit: int = Query(50, ge=1, le=LIST_MAX, description="How many to return."),
) -> IncidentsOut:
    rows = await incidents.list_incidents(session, days=days, limit=limit)
    return IncidentsOut(items=[_incident_out(i) for i in rows])


class ActionOut(_Out):
    id: UUID
    at: datetime
    incident_id: UUID | None
    playbook: str
    step: str
    outcome: Literal["ok", "failed", "skipped", "refused"]
    attempt: int
    tenant_id: UUID | None
    agent_id: UUID | None
    alarm_code: str | None
    detail: str | None
    actor_type: Literal["healer", "admin", "user"]


class ActionsOut(_Out):
    items: list[ActionOut]


@ops_router.get(
    "/actions",
    response_model=ActionsOut,
    summary="The healer's ledger, newest first",
    openapi_extra=permission_meta("ops:manage"),
)
async def list_actions(
    session: GlobalSession,
    principal: Operator,
    incident_id: UUID | None = Query(None, description="Only this incident's steps."),
    limit: int = Query(50, ge=1, le=LIST_MAX, description="How many to return."),
) -> ActionsOut:
    rows = (
        await session.execute(
            text(
                "SELECT id, at, incident_id, playbook, step, outcome, attempt, tenant_id, "
                "agent_id, alarm_code, detail, actor_type FROM heal_actions WHERE "
                "(CAST(:iid AS uuid) IS NULL OR incident_id = :iid) ORDER BY at DESC LIMIT :limit"
            ),
            {"iid": incident_id, "limit": limit},
        )
    ).all()
    return ActionsOut(
        items=[
            ActionOut(
                id=r[0],
                at=r[1],
                incident_id=r[2],
                playbook=r[3],
                step=r[4],
                outcome=r[5],
                attempt=int(r[6]),
                tenant_id=r[7],
                agent_id=r[8],
                alarm_code=r[9],
                detail=r[10],
                actor_type=r[11],
            )
            for r in rows
        ]
    )


async def _incident_or_404(session: AsyncSession, incident_id: UUID) -> incidents.Incident:
    incident = await incidents.read_incident(session, incident_id)
    if incident is None:
        raise ProblemError.not_found("Incident")
    return incident


@ops_router.post(
    "/incidents/{incident_id}/resolve",
    response_model=IncidentOut,
    summary="Resolve an incident, giving back any line it holds",
    openapi_extra=permission_meta("ops:manage"),
)
async def resolve_incident(
    incident_id: UUID,
    session: GlobalSession,
    principal: Operator,
    request: Request,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> IncidentOut:
    step_up.require(x_confirm_action, resolve_confirmation(incident_id))
    incident = await _incident_or_404(session, incident_id)
    if incident.resolved_at is None:
        from apps.workers.healer import restore_by_person

        await restore_by_person(incident, actor_type="admin", actor_id=principal.user_id)
    await write_audit(
        session,
        actor=principal,
        action="healer.incident_resolved",
        tenant_id=incident.tenant_id,
        object_type="heal_incident",
        object_id=str(incident.id),
        ip=client_request_ip(request),
        summary={"playbook": incident.playbook, "was": incident.state},
    )
    return _incident_out(await _incident_or_404(session, incident_id))


@ops_router.post(
    "/incidents/{incident_id}/retry",
    response_model=IncidentOut,
    summary="Run an incident's next step on the healer's next tick",
    openapi_extra=permission_meta("ops:manage"),
)
async def retry_incident(
    incident_id: UUID, session: GlobalSession, principal: Operator, request: Request
) -> IncidentOut:
    incident = await _incident_or_404(session, incident_id)
    await session.execute(
        text(
            "UPDATE heal_incidents SET next_attempt_at = now(), updated_at = now() "
            "WHERE id = :id AND resolved_at IS NULL"
        ),
        {"id": incident_id},
    )
    await write_audit(
        session,
        actor=principal,
        action="healer.incident_retried",
        tenant_id=incident.tenant_id,
        object_type="heal_incident",
        object_id=str(incident.id),
        ip=client_request_ip(request),
        summary={"playbook": incident.playbook},
    )
    return _incident_out(await _incident_or_404(session, incident_id))


class StatusPostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What the public reads. None takes the incident off the page.
    title: Annotated[str, Field(min_length=3, max_length=120)] | None
    component: Literal["calls", "dashboard", "numbers", "assistant"] | None = None


@ops_router.put(
    "/incidents/{incident_id}/status",
    response_model=IncidentOut,
    summary="Show an incident on the public status page, or take it off",
    openapi_extra=permission_meta("ops:manage"),
)
async def put_incident_status(
    incident_id: UUID,
    payload: StatusPostIn,
    session: GlobalSession,
    principal: Operator,
    request: Request,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> IncidentOut:
    step_up.require(x_confirm_action, status_confirmation(incident_id))
    incident = await _incident_or_404(session, incident_id)
    await incidents.set_public(
        session, incident_id, title=payload.title, component=payload.component
    )
    await write_audit(
        session,
        actor=principal,
        action="healer.status_posted" if payload.title else "healer.status_withdrawn",
        tenant_id=incident.tenant_id,
        object_type="heal_incident",
        object_id=str(incident.id),
        ip=client_request_ip(request),
        summary={"component": payload.component},
    )
    return _incident_out(await _incident_or_404(session, incident_id))


class NewStatusPostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=3, max_length=120)]
    component: Literal["calls", "dashboard", "numbers", "assistant"]


@ops_router.post(
    "/status-posts",
    response_model=IncidentOut,
    summary="Post a problem on the public status page by hand",
    openapi_extra=permission_meta("ops:manage"),
)
async def post_status(
    payload: NewStatusPostIn,
    session: GlobalSession,
    principal: Operator,
    request: Request,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> IncidentOut:
    step_up.require(x_confirm_action, status_confirmation(None))
    incident_id, _ = await incidents.open_incident(
        session,
        key=incidents.dedupe_key("status_post", uuid7()),
        playbook="status_post",
        trigger_code="status_post",
        scope="platform",
        component=payload.component,
        public_title=payload.title,
    )
    await write_audit(
        session,
        actor=principal,
        action="healer.status_posted",
        object_type="heal_incident",
        object_id=str(incident_id),
        ip=client_request_ip(request),
        summary={"component": payload.component},
    )
    return _incident_out(await _incident_or_404(session, incident_id))


# --- public ---------------------------------------------------------------------------------


class StatusComponentOut(_Out):
    key: Literal["calls", "dashboard", "numbers", "assistant"]
    name: str
    state: Literal["operational", "degraded", "outage"]


class StatusIncidentOut(_Out):
    id: str
    title: str
    component: Literal["calls", "dashboard", "numbers", "assistant"] | None
    state: Literal["ongoing", "resolved"]
    started_at: datetime
    resolved_at: datetime | None


class StatusPageOut(_Out):
    components: list[StatusComponentOut]
    incidents: list[StatusIncidentOut]
    updated_at: datetime


@public_router.get(
    "/status",
    response_model=StatusPageOut,
    summary="Whether calls, numbers, the dashboard and the assistant are working",
    description=(
        "Unauthenticated and identical for everyone. Each component's state and the "
        "incidents posted in the last ninety days. No account, agent or customer is named."
    ),
)
async def read_status(response: Response, session: GlobalSession) -> StatusPageOut:
    page = await status_page.status_page(session)
    response.headers["Cache-Control"] = STATUS_CACHE_CONTROL
    return StatusPageOut(
        components=[
            StatusComponentOut(key=c.key, name=c.name, state=c.state)  # type: ignore[arg-type]
            for c in page.components
        ],
        incidents=[
            StatusIncidentOut(
                id=i.id,
                title=i.title,
                component=i.component,  # type: ignore[arg-type]
                state=i.state,
                started_at=i.started_at,
                resolved_at=i.resolved_at,
            )
            for i in page.incidents
        ],
        updated_at=page.updated_at,
    )


__all__ = [
    "ops_router",
    "public_router",
    "resolve_confirmation",
    "router",
    "status_confirmation",
]
