"""The public API v1: `/api/v1/**`, reached with a tenant API key (D-1047).

Every route is a thin adapter over a door the console already uses, so there is no second
dial path, no second consent rule and no second suppression list:

- a call is `crm/one_call.place_one_call`, which asks `check_dispatch` and claims the
  `Idempotency-Key` exactly as Make a call does;
- a lead is `ingest/service.ingest_lead` under one of the account's own lead sources, so
  that source's mapping, consent field and dial rule apply;
- a campaign's launch, pause, resume and stop are the console's own handlers;
- do-not-call is `compliance/dnc`, whose removal already refuses a person's own opt-out.

What is new here is the SHAPE: frozen models (`schemas.py`), cursor pages, and reads that
honour the key's agent binding.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from calevate_shared.events import TERMINAL_STATUSES
from calevate_shared.lead_fields import business_only, with_core
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import PREPAID_TIERS
from apps.api.billing.service import get_balance, plan_tier_of
from apps.api.billing.trials import read_trial
from apps.api.campaigns import routes as campaign_routes
from apps.api.compliance import dnc
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import credits_exhausted
from apps.api.core.auth import client_request_ip, requires_key
from apps.api.core.context import Principal, request_facts_var
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm.captured import captured_fields
from apps.api.crm.one_call import OneCallIn, place_one_call
from apps.api.crm.service import redacted_summary
from apps.api.db.session import tenant_session
from apps.api.ingest import portals
from apps.api.ingest.routes import META_SOURCE
from apps.api.ingest.service import ingest_lead, load_config
from apps.api.public_api import schemas as s
from apps.api.public_api.deps import (
    KeyCall,
    KeyDb,
    bound_agents,
    calls_placed_today,
    daily_budget,
    paged,
    refund_daily_call,
    require_agent,
    spend_daily_call,
)
from apps.api.reliability.service import (
    body_hash,
    claim_inbox_event,
    mark_inbox_processed,
    require_idempotency_key,
)

router = APIRouter(prefix="/api/v1", tags=["public-api"])

#: The longest `GET /calls/{id}?wait=` may hold a request open, and how often it looks.
WAIT_MAX_S: Final = 30
WAIT_POLL_S: Final = 1.0
_AFTER = "CAST(:after AS uuid) IS NULL OR id < CAST(:after AS uuid)"
_AGENTS = "CAST(:agents AS uuid[]) IS NULL OR agent_id = ANY(CAST(:agents AS uuid[]))"

Limit = Query(s.PAGE_DEFAULT, ge=1, le=s.PAGE_MAX)
After = Query(None, description="`next_cursor` from the previous page")


def _meta(call: KeyCall, items: list[Any], more: bool) -> dict[str, Any]:
    return {
        "next_cursor": items[-1].id if more and items else None,
        "has_more": more,
        "api_version": call.api_version,
    }


# ================================================================== me, balance ====


@router.get(
    "/me",
    response_model=s.PublicMeOut,
    openapi_extra=permission_meta("org:read"),
    summary="The account and the key this request was made with",
)
async def me(
    call: KeyCall, session: KeyDb, _: Principal = Depends(requires_key("org:read"))
) -> s.PublicMeOut:
    org = (
        await session.execute(text("SELECT id, name, slug, status FROM organizations LIMIT 1"))
    ).one()
    key = (
        await session.execute(
            text("SELECT name, expires_at FROM api_keys WHERE id = :id"), {"id": call.key.id}
        )
    ).one()
    return s.PublicMeOut(
        account=s.PublicAccountOut(id=org[0], name=org[1], slug=org[2], status=org[3]),
        key=s.PublicKeyInfoOut(
            id=call.key.id,
            name=key[0],
            scopes=sorted(call.key.scopes),
            agent_ids=bound_agents(call),
            expires_at=key[1],
        ),
        api_version=call.api_version,
    )


@router.get(
    "/balance",
    response_model=s.PublicBalanceOut,
    openapi_extra=permission_meta("wallet:read"),
    summary="Prepaid balance in rupees, and today's API call budget",
)
async def balance(
    call: KeyCall, session: KeyDb, _: Principal = Depends(requires_key("wallet:read"))
) -> s.PublicBalanceOut:
    tenant_id = call.key.tenant_id
    now = datetime.now(UTC)
    trial = await read_trial(session, tenant_id=tenant_id)
    amount = (await get_balance(session, tenant_id=tenant_id)).amount_inr
    return s.PublicBalanceOut(
        balance_inr=str(amount.quantize(Decimal("0.01"))),
        prepaid=(await plan_tier_of(session, tenant_id)) in PREPAID_TIERS,
        outbound_stopped=await credits_exhausted(session, tenant_id=tenant_id),
        on_trial=trial is not None and trial.is_active(at=now),
        daily_call_budget=await daily_budget(session, tenant_id, now=now),
        calls_placed_today=await calls_placed_today(tenant_id, now=now),
    )


# ============================================================== agents, numbers ====

_AGENT_SQL: Final = (
    "SELECT id, name, direction, status, language_primary, engine_agent_ref, created_at "
    "FROM agents WHERE deleted_at IS NULL AND archived_at IS NULL"
)
_SCHEMA_SQL: Final = (
    "SELECT DISTINCT ON (agent_id) agent_id, fields FROM extraction_schemas "
    "WHERE agent_id = ANY(:ids) ORDER BY agent_id, version DESC"
)


async def _agents(session: AsyncSession, rows: list[Any]) -> list[s.PublicAgentOut]:
    ids = [r[0] for r in rows]
    fields = (
        {r[0]: r[1] for r in (await session.execute(text(_SCHEMA_SQL), {"ids": ids})).all()}
        if ids
        else {}
    )
    return [
        s.PublicAgentOut(
            id=r[0],
            name=r[1],
            direction=r[2],
            status=r[3],
            language=r[4],
            published=r[5] is not None,
            capture_fields=[
                s.PublicCaptureFieldOut(
                    key=f.key, label=f.label, type=f.type, choices=f.enum_values or None
                )
                for f in with_core(business_only(fields.get(r[0]) or []))
            ],
            created_at=r[6],
        )
        for r in rows
    ]


@router.get(
    "/agents",
    response_model=s.PublicAgentList,
    openapi_extra=permission_meta("agents:read"),
    summary="Your agents, with what each one captures from a call",
)
async def list_agents(
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("agents:read")),
    limit: int = Limit,
    after: UUID | None = After,
) -> s.PublicAgentList:
    rows = (
        await session.execute(
            text(
                f"{_AGENT_SQL} AND ({_AFTER}) AND (CAST(:agents AS uuid[]) IS NULL "
                "OR id = ANY(CAST(:agents AS uuid[]))) ORDER BY id DESC LIMIT :n"
            ),
            {"after": after, "agents": bound_agents(call), "n": limit + 1},
        )
    ).all()
    page, more = paged(rows, limit)
    data = await _agents(session, list(page))
    return s.PublicAgentList(data=data, **_meta(call, data, more))


@router.get(
    "/agents/{agent_id}",
    response_model=s.PublicAgentOut,
    openapi_extra=permission_meta("agents:read"),
    summary="One agent",
)
async def get_agent(
    agent_id: UUID,
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("agents:read")),
) -> s.PublicAgentOut:
    require_agent(call, agent_id)
    row = (await session.execute(text(f"{_AGENT_SQL} AND id = :id"), {"id": agent_id})).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return (await _agents(session, [row]))[0]


@router.get(
    "/numbers",
    response_model=s.PublicNumberList,
    openapi_extra=permission_meta("agents:read"),
    summary="Your phone numbers and what answers or calls from each",
)
async def list_numbers(
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("agents:read")),
    limit: int = Limit,
    after: UUID | None = After,
) -> s.PublicNumberList:
    rows = (
        await session.execute(
            text(
                "SELECT id, e164, direction, agent_id, inbound_line_id, released_at, created_at "
                f"FROM phone_numbers WHERE ({_AFTER}) ORDER BY id DESC LIMIT :n"
            ),
            {"after": after, "n": limit + 1},
        )
    ).all()
    page, more = paged(rows, limit)
    data = [
        s.PublicNumberOut(
            id=r[0],
            phone=r[1],
            direction=r[2],
            agent_id=r[3],
            inbound_line_id=r[4],
            active=r[5] is None,
            created_at=r[6],
        )
        for r in page
    ]
    return s.PublicNumberList(data=data, **_meta(call, data, more))


# ======================================================================= calls ====

_CALL_COLUMNS: Final = (
    "id, direction, status, agent_id, lead_id, campaign_id, inbound_line_id, "
    "CASE WHEN direction = 'inbound' THEN from_e164 ELSE to_e164 END, started_at, ended_at, "
    "duration_s, outcome_tag, business_outcome, business_outcome_label, summary, next_step, "
    "callback_requested, not_placed_reason, created_at, summary_state"
)


def _call(r: Any) -> dict[str, Any]:
    return {
        "id": r[0],
        "direction": r[1],
        "status": r[2],
        "finished": r[2] in TERMINAL_STATUSES,
        "agent_id": r[3],
        "lead_id": r[4],
        "campaign_id": r[5],
        "inbound_line_id": r[6],
        "phone": r[7],
        "started_at": r[8],
        "ended_at": r[9],
        "duration_s": r[10],
        "outcome": r[11],
        "business_outcome": r[12],
        "business_outcome_label": r[13],
        # Personal details masked by the same pass as the transcript (hard rule 5).
        "summary_redacted": redacted_summary(None if r[19] == "empty" else r[14]),
        "next_step": r[15],
        "callback_requested": r[16],
        "not_placed_reason": r[17],
        "created_at": r[18],
    }


async def _list_calls(
    session: AsyncSession,
    call: KeyCall,
    *,
    limit: int,
    after: UUID | None,
    direction: str | None,
    agent_id: UUID | None,
    campaign_id: UUID | None,
) -> s.PublicCallList:
    require_agent(call, agent_id)
    rows = (
        await session.execute(
            text(
                f"SELECT {_CALL_COLUMNS} FROM calls WHERE ({_AFTER}) AND ({_AGENTS}) "
                "AND (CAST(:direction AS text) IS NULL OR direction = CAST(:direction AS text)) "
                "AND (CAST(:agent AS uuid) IS NULL OR agent_id = CAST(:agent AS uuid)) "
                "AND (CAST(:campaign AS uuid) IS NULL OR campaign_id = CAST(:campaign AS uuid)) "
                "AND NOT trial_call AND NOT paid_test_call ORDER BY id DESC LIMIT :n"
            ),
            {
                "after": after,
                "agents": bound_agents(call),
                "direction": direction,
                "agent": agent_id,
                "campaign": campaign_id,
                "n": limit + 1,
            },
        )
    ).all()
    page, more = paged(rows, limit)
    data = [s.PublicCallOut(**_call(r)) for r in page]
    return s.PublicCallList(data=data, **_meta(call, data, more))


@router.get(
    "/calls",
    response_model=s.PublicCallList,
    openapi_extra=permission_meta("calls:read"),
    summary="Calls, newest first; test calls left out",
)
async def list_calls(
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("calls:read")),
    limit: int = Limit,
    after: UUID | None = After,
    direction: str | None = Query(None, pattern="^(inbound|outbound)$"),
    agent_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> s.PublicCallList:
    return await _list_calls(
        session,
        call,
        limit=limit,
        after=after,
        direction=direction,
        agent_id=agent_id,
        campaign_id=campaign_id,
    )


@router.get(
    "/inbound-calls",
    response_model=s.PublicCallList,
    openapi_extra=permission_meta("calls:read"),
    summary="Calls your agents answered, newest first",
)
async def list_inbound_calls(
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("calls:read")),
    limit: int = Limit,
    after: UUID | None = After,
    agent_id: UUID | None = None,
) -> s.PublicCallList:
    return await _list_calls(
        session,
        call,
        limit=limit,
        after=after,
        direction="inbound",
        agent_id=agent_id,
        campaign_id=None,
    )


async def _read_call(tenant_id: UUID, call: KeyCall, call_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(f"SELECT {_CALL_COLUMNS} FROM calls WHERE id = :id AND ({_AGENTS})"),
                {"id": call_id, "agents": bound_agents(call)},
            )
        ).first()
    if row is None:
        raise ProblemError.not_found("Call")
    return row


@router.get(
    "/calls/{call_id}",
    response_model=s.PublicCallDetailOut,
    openapi_extra=permission_meta("calls:read"),
    summary="One call, with its masked transcript. `?wait=30` holds until it finishes",
)
async def get_call(
    call_id: UUID,
    call: KeyCall,
    _: Principal = Depends(requires_key("calls:read")),
    wait: int = Query(0, ge=0, le=WAIT_MAX_S, description="Seconds to wait for the end"),
) -> s.PublicCallDetailOut:
    """Each look is its own short session, so a waiting request holds no connection."""
    tenant_id = call.key.tenant_id
    deadline = time.monotonic() + wait
    row = await _read_call(tenant_id, call, call_id)
    while row[2] not in TERMINAL_STATUSES and time.monotonic() < deadline:
        await asyncio.sleep(WAIT_POLL_S)
        row = await _read_call(tenant_id, call, call_id)
    async with tenant_session(tenant_id) as session:
        turns = (
            await session.execute(
                text(
                    "SELECT speaker, text_redacted FROM transcript_turns WHERE call_id = :id "
                    "ORDER BY idx LIMIT 2000"
                ),
                {"id": call_id},
            )
        ).all()
    return s.PublicCallDetailOut(
        **_call(row),
        transcript=[s.PublicTranscriptTurnOut(speaker=t[0], text_redacted=t[1]) for t in turns],
    )


@router.post(
    "/calls",
    response_model=s.PublicPlaceCallOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Call one person now or at a time: the same gate as every other call",
)
async def place_call(
    payload: s.PublicPlaceCallIn,
    request: Request,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:dispatch")),
) -> s.PublicPlaceCallOut:
    """`Idempotency-Key` is required: the request rings a real phone, and a retry of the
    same attempt is answered from its record rather than dialled again."""
    idem = require_idempotency_key(
        request.headers.get("Idempotency-Key"),
        title="Placing a call needs an Idempotency-Key header",
        detail="A call rings a real phone, so each attempt names itself once.",
    )
    if payload.follow_up_of is None and not (payload.reason or "").strip():
        raise ProblemError(
            kind="validation",
            code="one_call_no_reason",
            title="Say why you are calling",
            detail="The agent tells the person why it is calling, so it needs the reason.",
            fields=[{"field": "reason", "rule": "required", "message": "missing"}],
        )
    if call.key.agent_ids is not None and payload.agent_id is None:
        raise ProblemError(
            kind="validation",
            code="api_key_agent_required",
            title="Name the agent",
            detail="This key is limited to certain agents, so each call must name one.",
            fields=[{"field": "agent_id", "rule": "required", "message": "missing"}],
        )
    require_agent(call, payload.agent_id)
    if payload.follow_up_of is not None and call.key.agent_ids is not None:
        earlier = await _read_call(call.key.tenant_id, call, payload.follow_up_of)
        require_agent(call, earlier[3])
    spent = (
        await spend_daily_call(request, session, call.key.tenant_id) if payload.at is None else None
    )
    try:
        out = await place_one_call(
            session,
            principal=principal,
            request=OneCallIn(
                phone=payload.phone,
                lead_id=payload.lead_id,
                call_id=payload.follow_up_of,
                name=payload.name,
                agent_id=payload.agent_id,
                reason=payload.reason,
                details=payload.details,
                at=payload.at,
            ),
            idempotency_key=idem,
            ip=client_request_ip(request),
            audit_extra={"via_api_key": str(call.key.id)},
        )
    except Exception:
        if spent is not None:
            await refund_daily_call(spent)
        raise
    facts = request_facts_var.get() or {}
    if spent is not None and (out.status == "blocked" or facts.get("idempotent_replayed")):
        # A refused call rang nobody, and a replay is the first attempt's answer.
        await refund_daily_call(spent)
    return s.PublicPlaceCallOut(
        status=out.status,
        call_id=out.call_id,
        lead_id=out.lead_id,
        callback_id=out.callback_id,
        blocked_rule=out.blocked_rule,
        blocked_reason=out.blocked_reason,
        opens_at=out.opens_at,
    )


# ======================================================================= leads ====

_LEAD_COLUMNS: Final = (
    "id, phone_e164, name, status, source, agent_id, call_count, last_call_id, created_at, "
    "updated_at"
)


def _lead(r: Any) -> dict[str, Any]:
    keys = (
        "id",
        "phone",
        "name",
        "status",
        "source",
        "agent_id",
        "call_count",
        "last_call_id",
        "created_at",
        "updated_at",
    )
    return dict(zip(keys, r[:10], strict=True))


@router.get(
    "/leads",
    response_model=s.PublicLeadList,
    openapi_extra=permission_meta("leads:read"),
    summary="People your agents have spoken to or will call, newest first",
)
async def list_leads(
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("leads:read")),
    limit: int = Limit,
    after: UUID | None = After,
    agent_id: UUID | None = None,
) -> s.PublicLeadList:
    require_agent(call, agent_id)
    rows = (
        await session.execute(
            text(
                f"SELECT {_LEAD_COLUMNS} FROM leads WHERE deleted_at IS NULL AND ({_AFTER}) "
                f"AND ({_AGENTS}) AND (CAST(:agent AS uuid) IS NULL "
                "OR agent_id = CAST(:agent AS uuid)) ORDER BY id DESC LIMIT :n"
            ),
            {"after": after, "agents": bound_agents(call), "agent": agent_id, "n": limit + 1},
        )
    ).all()
    page, more = paged(rows, limit)
    data = [s.PublicLeadOut(**_lead(r)) for r in page]
    return s.PublicLeadList(data=data, **_meta(call, data, more))


@router.get(
    "/leads/{lead_id}",
    response_model=s.PublicLeadDetailOut,
    openapi_extra=permission_meta("leads:read"),
    summary="One person, with every detail captured, each under its own type",
)
async def get_lead(
    lead_id: UUID,
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("leads:read")),
) -> s.PublicLeadDetailOut:
    row = (
        await session.execute(
            text(
                f"SELECT {_LEAD_COLUMNS}, data, schema_version FROM leads "
                f"WHERE id = :id AND deleted_at IS NULL AND ({_AGENTS})"
            ),
            {"id": lead_id, "agents": bound_agents(call)},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Lead")
    captured = await captured_fields(
        session, agent_id=row[5], schema_version=row[11], data=dict(row[10] or {})
    )
    return s.PublicLeadDetailOut(
        **_lead(row),
        fields=[
            s.PublicLeadFieldOut(key=f.key, label=f.label, type=f.type, value=f.value)
            for f in captured
        ],
    )


@router.post(
    "/leads",
    response_model=s.PublicCreateLeadOut,
    status_code=202,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Send a lead through one of your lead sources: mapped, consent-checked, called",
)
async def create_lead(
    payload: s.PublicCreateLeadIn,
    request: Request,
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("leads:dispatch")),
) -> s.PublicCreateLeadOut:
    """`leads:dispatch` because a lead source may call the person at once. The source's
    own consent field decides whether it may; a missing answer keeps the lead and holds
    the call, as on the source's webhook."""
    idem = require_idempotency_key(
        request.headers.get("Idempotency-Key"),
        title="Sending a lead needs an Idempotency-Key header",
        detail="A new lead may be called at once, so each attempt names itself once.",
    )
    config = await load_config(session, payload.source_id)
    if config is None or config.source == META_SOURCE or portals.is_push_source(config.source):
        raise ProblemError.not_found("Lead source")
    require_agent(call, config.agent_id)
    claim = await claim_inbox_event(
        session,
        provider=f"api:{payload.source_id}",
        event_key=body_hash({"key": idem}),
        payload_hash=body_hash(payload.lead),
        event_name=config.source,
    )
    if claim.state == "duplicate":
        return s.PublicCreateLeadOut(status="duplicate")
    result = await ingest_lead(
        session,
        config=config,
        payload=payload.lead,
        received_at=time.time(),
        provenance={"via_api_key": str(call.key.id)},
    )
    await mark_inbox_processed(session, row_id=claim.row_id)
    return s.PublicCreateLeadOut(
        status="accepted",
        lead_id=result["lead_id"],
        calling=bool(result["dispatched"]),
        blocked_rule=result.get("blocked"),
    )


# =================================================================== do-not-call ====


@router.get(
    "/dnc",
    response_model=s.PublicDncList,
    openapi_extra=permission_meta("leads:read"),
    summary="Numbers no agent may call: your account's and the global ones",
)
async def list_dnc(
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("leads:read")),
    limit: int = Limit,
    after: UUID | None = After,
) -> s.PublicDncList:
    rows = (
        await session.execute(
            text(
                "SELECT id, phone_e164, scope, source, added_at FROM dnc_list "
                f"WHERE ({_AFTER}) ORDER BY id DESC LIMIT :n"
            ),
            {"after": after, "n": limit + 1},
        )
    ).all()
    page, more = paged(rows, limit)
    data = [
        s.PublicDncEntryOut(
            id=r[0],
            phone=r[1],
            scope=r[2],
            source=r[3],
            removable=dnc.is_removable(scope=r[2], source=r[3]),
            added_at=r[4],
        )
        for r in page
    ]
    return s.PublicDncList(data=data, **_meta(call, data, more))


@router.post(
    "/dnc",
    response_model=s.PublicDncAddOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Stop calling these numbers: in force before the next call goes out",
)
async def add_dnc(
    payload: s.PublicDncAddIn,
    request: Request,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:dispatch")),
) -> s.PublicDncAddOut:
    tenant_id = call.key.tenant_id
    result = await dnc.add_numbers(
        session, tenant_id=tenant_id, raw_numbers=payload.numbers, source=payload.source
    )
    await write_audit(
        session,
        action="dnc.added",
        actor=principal,
        tenant_id=tenant_id,
        object_type="dnc_list",
        ip=client_request_ip(request),
        summary={
            "added": result.added,
            "already_suppressed": result.already_suppressed,
            "malformed": result.malformed,
            "source": payload.source,
        },
    )
    return s.PublicDncAddOut(
        added=result.added,
        already_suppressed=result.already_suppressed,
        malformed=result.malformed,
    )


@router.post(
    "/dnc/check",
    response_model=s.PublicDncCheckOut,
    openapi_extra=permission_meta("leads:read"),
    summary="May this number be called? (POST, so the number is never in a URL)",
)
async def check_dnc(
    payload: s.PublicDncCheckIn,
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("leads:read")),
) -> s.PublicDncCheckOut:
    result = await dnc.check_number(session, tenant_id=call.key.tenant_id, raw=payload.phone)
    return s.PublicDncCheckOut(valid=result.valid, suppressed=result.suppressed, scope=result.scope)


@router.delete(
    "/dnc/{entry_id}",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Undo a number you added by hand; a person's own request cannot be undone",
)
async def remove_dnc(
    entry_id: UUID,
    payload: s.PublicDncRemoveIn,
    request: Request,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:dispatch")),
) -> Response:
    tenant_id = call.key.tenant_id
    removal = await dnc.remove_entry(session, tenant_id=tenant_id, entry_id=entry_id)
    await write_audit(
        session,
        action="dnc.removed",
        actor=principal,
        tenant_id=tenant_id,
        object_type="dnc_list",
        object_id=str(entry_id),
        ip=client_request_ip(request),
        summary={
            "source": removal.source,
            "subject_ref": removal.subject_ref,
            "reason_length": len(payload.reason),
        },
    )
    return Response(status_code=204)


# ==================================================================== campaigns ====

_CAMPAIGN_SQL: Final = (
    "SELECT id, name, status, agent_id, launched_at, created_at FROM campaigns "
    "WHERE archived_at IS NULL"
)


def _campaign(r: Any) -> s.PublicCampaignOut:
    return s.PublicCampaignOut(
        id=r[0], name=r[1], status=r[2], agent_id=r[3], launched_at=r[4], created_at=r[5]
    )


async def _bound_campaign(session: AsyncSession, call: KeyCall, campaign_id: UUID) -> Any:
    row = (
        await session.execute(
            text(f"{_CAMPAIGN_SQL} AND id = :id AND ({_AGENTS})"),
            {"id": campaign_id, "agents": bound_agents(call)},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return row


@router.get(
    "/campaigns",
    response_model=s.PublicCampaignList,
    openapi_extra=permission_meta("leads:read"),
    summary="Your campaigns, newest first",
)
async def list_campaigns(
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("leads:read")),
    limit: int = Limit,
    after: UUID | None = After,
) -> s.PublicCampaignList:
    rows = (
        await session.execute(
            text(f"{_CAMPAIGN_SQL} AND ({_AFTER}) AND ({_AGENTS}) ORDER BY id DESC LIMIT :n"),
            {"after": after, "agents": bound_agents(call), "n": limit + 1},
        )
    ).all()
    page, more = paged(rows, limit)
    data = [_campaign(r) for r in page]
    return s.PublicCampaignList(data=data, **_meta(call, data, more))


@router.get(
    "/campaigns/{campaign_id}",
    response_model=s.PublicCampaignOut,
    openapi_extra=permission_meta("leads:read"),
    summary="One campaign",
)
async def get_campaign(
    campaign_id: UUID,
    call: KeyCall,
    session: KeyDb,
    _: Principal = Depends(requires_key("leads:read")),
) -> s.PublicCampaignOut:
    return _campaign(await _bound_campaign(session, call, campaign_id))


@router.post(
    "/campaigns/{campaign_id}/contacts",
    response_model=s.PublicAddContactsOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Add people to a campaign's list: deduped, malformed numbers counted",
)
async def add_campaign_contacts(
    campaign_id: UUID,
    payload: s.PublicAddContactsIn,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:dispatch")),
) -> s.PublicAddContactsOut:
    await _bound_campaign(session, call, campaign_id)
    out = await campaign_routes.add_contacts(
        campaign_id,
        campaign_routes.AddContactsIn(
            contacts=[
                campaign_routes.ContactIn(phone=c.phone, name=c.name, custom=c.variables)
                for c in payload.contacts
            ]
        ),
        session,
        principal,
    )
    return s.PublicAddContactsOut(
        added=out.added, malformed=out.malformed, duplicate=out.duplicate, foreign=out.foreign
    )


@router.get(
    "/campaigns/{campaign_id}/launch-check",
    response_model=s.PublicLaunchCheckOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Whether the campaign can start now, and every reason it cannot",
)
async def campaign_launch_check(
    campaign_id: UUID,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:read")),
) -> s.PublicLaunchCheckOut:
    await _bound_campaign(session, call, campaign_id)
    out = await campaign_routes.launch_check(campaign_id, session, principal)
    return s.PublicLaunchCheckOut(
        ready=out.ready,
        blockers=[s.PublicLaunchBlockerOut(rule=b.rule, reason=b.reason) for b in out.blockers],
    )


@router.post(
    "/campaigns/{campaign_id}/launch",
    response_model=s.PublicLaunchOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Start calling: the compliance gate, then the do-not-call scrub, then running",
)
async def launch_campaign(
    campaign_id: UUID,
    request: Request,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:dispatch")),
) -> s.PublicLaunchOut:
    await _bound_campaign(session, call, campaign_id)
    out = await campaign_routes.launch(campaign_id, session, request, principal)
    return s.PublicLaunchOut(
        status=out.status, dialable=out.dialable, dnc_scrubbed=out.dnc_scrubbed
    )


async def _state(session: AsyncSession, campaign_id: UUID) -> s.PublicCampaignStateOut:
    status = (
        await session.execute(
            text("SELECT status FROM campaigns WHERE id = :id"), {"id": campaign_id}
        )
    ).scalar_one()
    return s.PublicCampaignStateOut(id=campaign_id, status=str(status))


@router.post(
    "/campaigns/{campaign_id}/pause",
    response_model=s.PublicCampaignStateOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Stop dialling now. Safe to repeat",
)
async def pause_campaign(
    campaign_id: UUID,
    request: Request,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:dispatch")),
) -> s.PublicCampaignStateOut:
    await _bound_campaign(session, call, campaign_id)
    await campaign_routes.pause(campaign_id, session, request, principal)
    return await _state(session, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/resume",
    response_model=s.PublicCampaignStateOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Dial again from where it stopped; every call is checked as it goes out",
)
async def resume_campaign(
    campaign_id: UUID,
    request: Request,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:dispatch")),
) -> s.PublicCampaignStateOut:
    await _bound_campaign(session, call, campaign_id)
    await campaign_routes.resume(campaign_id, session, request, principal)
    return await _state(session, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/stop",
    response_model=s.PublicCampaignStateOut,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Stop for good: nobody else on the list is called. Safe to repeat",
)
async def stop_campaign(
    campaign_id: UUID,
    request: Request,
    call: KeyCall,
    session: KeyDb,
    principal: Principal = Depends(requires_key("leads:dispatch")),
) -> s.PublicCampaignStateOut:
    await _bound_campaign(session, call, campaign_id)
    await campaign_routes.stop(campaign_id, session, request, principal)
    return await _state(session, campaign_id)


__all__ = ["WAIT_MAX_S", "router"]
