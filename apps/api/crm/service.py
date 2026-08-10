"""CRM business logic AND queries — no repository layer (BACKEND-PATTERNS §1, §10).

Everything here runs on a session whose transaction already carries `app.tenant_id`,
so the isolation is RLS's job and no query in this file carries a `WHERE tenant_id`
belt for a belt-and-braces effect. That is deliberate: a `tenant_id` filter written by
hand is a filter that can be forgotten, and its presence would make it tempting to
trust the filter instead of the policy.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.crm.schemas import (
    CallDetailOut,
    CallSummaryOut,
    DashboardOut,
    LeadOut,
    TranscriptTurnOut,
)
from apps.api.db.result import rowcount_of

MAX_PAGE = 200


def mask_phone(value: str | None) -> str | None:
    """Last two digits only — enough for staff to recognise a caller they are already
    looking at, useless to anyone who screenshots the page."""
    if not value:
        return None
    return f"••••••{value[-2:]}" if len(value) > 2 else "••"


# --- calls --------------------------------------------------------------------


async def list_calls(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    agent_id: UUID | None = None,
) -> list[CallSummaryOut]:
    clauses = []
    params: dict[str, Any] = {"limit": min(limit, MAX_PAGE), "offset": offset}
    if status:
        clauses.append("c.status = :status")
        params["status"] = status
    if agent_id:
        clauses.append("c.agent_id = :agent_id")
        params["agent_id"] = agent_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.agent_id, a.name, c.direction, c.status, c.from_e164, "
                "c.to_e164, c.started_at, c.duration_s, c.outcome_tag, c.sentiment, "
                "c.summary, c.lead_id "
                f"FROM calls c JOIN agents a ON a.id = c.agent_id {where} "
                "ORDER BY c.started_at DESC NULLS LAST, c.id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).all()
    return [
        CallSummaryOut(
            id=r[0],
            agent_id=r[1],
            agent_name=r[2],
            direction=r[3],
            status=r[4],
            caller_masked=mask_phone(r[5] if r[3] == "inbound" else r[6]),
            started_at=r[7],
            duration_s=r[8],
            outcome_tag=r[9],
            sentiment=r[10],
            summary=r[11],
            lead_id=r[12],
        )
        for r in rows
    ]


async def get_call(session: AsyncSession, call_id: UUID, *, raw: bool = False) -> CallDetailOut:
    """`raw=True` returns unredacted transcript text. The CALLER is responsible for the
    role check and the audit_log write — this function does not decide policy, it just
    stops the default path from ever reaching the raw column."""
    row = (
        await session.execute(
            text(
                "SELECT c.id, c.agent_id, a.name, c.direction, c.status, c.from_e164, "
                "c.to_e164, c.started_at, c.duration_s, c.outcome_tag, c.sentiment, "
                "c.summary, c.lead_id, c.recording_url, c.disclosure_played "
                "FROM calls c JOIN agents a ON a.id = c.agent_id WHERE c.id = :cid"
            ),
            {"cid": call_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Call")

    column = "text" if raw else "text_redacted"
    turns = (
        await session.execute(
            text(
                f"SELECT idx, speaker, COALESCE({column}, ''), lang, start_ms "
                "FROM transcript_turns WHERE call_id = :cid ORDER BY idx"
            ),
            {"cid": call_id},
        )
    ).all()
    extraction = (
        await session.execute(
            text(
                "SELECT data, valid FROM call_extractions WHERE call_id = :cid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"cid": call_id},
        )
    ).first()

    return CallDetailOut(
        id=row[0],
        agent_id=row[1],
        agent_name=row[2],
        direction=row[3],
        status=row[4],
        caller_masked=mask_phone(row[5] if row[3] == "inbound" else row[6]),
        started_at=row[7],
        duration_s=row[8],
        outcome_tag=row[9],
        sentiment=row[10],
        summary=row[11],
        lead_id=row[12],
        has_recording=bool(row[13]),
        disclosure_played=row[14],
        transcript=[
            TranscriptTurnOut(
                idx=t[0], speaker=t[1], text=t[2], lang=t[3], start_ms=t[4], redacted=not raw
            )
            for t in turns
        ],
        extraction=(extraction[0] or {}) if extraction else {},
        extraction_valid=bool(extraction[1]) if extraction else True,
    )


async def recording_key_for(session: AsyncSession, call_id: UUID) -> str:
    row = (
        await session.execute(
            text("SELECT recording_url FROM calls WHERE id = :cid"), {"cid": call_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Call")
    if not row[0]:
        raise ProblemError.not_found("Recording")
    return str(row[0])


# --- leads --------------------------------------------------------------------


async def lead_columns(
    session: AsyncSession, agent_id: UUID | None = None
) -> list[ExtractionField]:
    """The Leads table columns ARE the extraction schema (TRD §7). With no agent filter
    we take the most recently published schema — a v1 tenant has exactly one agent, and
    a mixed list is better served by the per-agent view."""
    params: dict[str, Any] = {}
    where = ""
    if agent_id:
        where = "WHERE agent_id = :aid"
        params["aid"] = agent_id
    row = (
        await session.execute(
            text(f"SELECT fields FROM extraction_schemas {where} ORDER BY version DESC LIMIT 1"),
            params,
        )
    ).first()
    if row is None or not row[0]:
        return []
    return [ExtractionField.model_validate(f) for f in row[0]]


async def list_leads(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    search: str | None = None,
) -> tuple[list[LeadOut], int]:
    clauses = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": min(limit, MAX_PAGE), "offset": offset}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if search:
        # Name or phone suffix. Never a LIKE on the full number in a logged query
        # string — the route passes this as a bound parameter for that reason.
        clauses.append("(name ILIKE :search OR phone_e164 LIKE :phone_suffix)")
        params["search"] = f"%{search}%"
        params["phone_suffix"] = f"%{search}"
    where = f"WHERE {' AND '.join(clauses)}"

    total = (
        await session.execute(text(f"SELECT count(*) FROM leads {where}"), params)
    ).scalar() or 0
    rows = (
        await session.execute(
            text(
                "SELECT id, phone_e164, name, status, source, data, schema_version, "
                "call_count, is_repeat_caller, last_call_id, created_at, updated_at "
                f"FROM leads {where} ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).all()
    return [_lead_out(r) for r in rows], int(total)


def _lead_out(r: Any) -> LeadOut:
    return LeadOut(
        id=r[0],
        phone_masked=mask_phone(r[1]) or "",
        name=r[2],
        status=r[3],
        source=r[4],
        data=r[5] or {},
        schema_version=r[6],
        call_count=r[7],
        is_repeat_caller=r[8],
        last_call_id=r[9],
        created_at=r[10],
        updated_at=r[11],
    )


async def get_lead(session: AsyncSession, lead_id: UUID) -> LeadOut:
    row = (
        await session.execute(
            text(
                "SELECT id, phone_e164, name, status, source, data, schema_version, "
                "call_count, is_repeat_caller, last_call_id, created_at, updated_at "
                "FROM leads WHERE id = :lid AND deleted_at IS NULL"
            ),
            {"lid": lead_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Lead")
    return _lead_out(row)


async def lead_phone(session: AsyncSession, lead_id: UUID) -> tuple[str, str | None]:
    row = (
        await session.execute(
            text("SELECT phone_e164, name FROM leads WHERE id = :lid AND deleted_at IS NULL"),
            {"lid": lead_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Lead")
    return str(row[0]), row[1]


async def update_lead(
    session: AsyncSession,
    lead_id: UUID,
    *,
    status: str | None,
    name: str | None,
    actor: str,
) -> LeadOut:
    sets: list[str] = []
    params: dict[str, Any] = {"lid": lead_id}
    if status is not None:
        sets.append("status = :status")
        params["status"] = status
    if name is not None:
        sets.append("name = :name")
        params["name"] = name
    if not sets:
        return await get_lead(session, lead_id)

    result = await session.execute(
        text(
            f"UPDATE leads SET {', '.join(sets)}, updated_at = now() "
            "WHERE id = :lid AND deleted_at IS NULL"
        ),
        params,
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Lead")
    if status is not None:
        # The lead timeline is what makes "who moved this to won?" answerable.
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) SELECT gen_random_uuid(), tenant_id, id, "
                "'status_change', jsonb_build_object('status', :status), :actor, now(), now() "
                "FROM leads WHERE id = :lid"
            ),
            {"lid": lead_id, "status": status, "actor": actor},
        )
    return await get_lead(session, lead_id)


async def export_leads_csv(session: AsyncSession, *, agent_id: UUID | None = None) -> str:
    """CSV export with schema-driven columns (TRD §7 (e)).

    The phone is exported IN FULL: this is the client's own customer data, the export
    is role-gated and audit-logged by the route, and a CSV of masked numbers is useless
    for the follow-up call it exists to enable. That is a different judgement from the
    on-screen list, and it is deliberate.
    """
    columns = await lead_columns(session, agent_id)
    rows = (
        await session.execute(
            text(
                "SELECT phone_e164, name, status, source, call_count, created_at, data "
                "FROM leads WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
        )
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["phone", "name", "status", "source", "calls", "created_at", *[c.label for c in columns]]
    )
    for r in rows:
        data = r[6] or {}
        writer.writerow(
            [
                r[0],
                r[1] or "",
                r[2],
                r[3],
                r[4],
                r[5].isoformat() if r[5] else "",
                *[_csv_value(data.get(c.key)) for c in columns],
            ]
        )
    return buffer.getvalue()


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


# --- dashboard ----------------------------------------------------------------


async def dashboard(session: AsyncSession) -> DashboardOut:
    """One round trip per tile would be four round trips; these are cheap aggregates
    over an already tenant-scoped view, and the dashboard polls (D-24)."""
    since_7d = datetime.now(UTC) - timedelta(days=7)
    today = datetime.now(UTC).date()

    counts = (
        await session.execute(
            text(
                "SELECT "
                "  count(*) FILTER (WHERE started_at::date = :today) AS calls_today, "
                "  count(*) FILTER (WHERE started_at >= :since) AS calls_7d, "
                "  avg(duration_s) FILTER (WHERE status = 'completed') AS avg_duration, "
                "  count(*) FILTER (WHERE started_at >= :since AND ("
                "     EXTRACT(HOUR FROM started_at + interval '5 hours 30 minutes') < 9 "
                "     OR EXTRACT(HOUR FROM started_at + interval '5 hours 30 minutes') >= 21"
                "  )) AS after_hours "
                "FROM calls"
            ),
            {"today": today, "since": since_7d},
        )
    ).first()

    sentiment = (
        await session.execute(
            text(
                "SELECT sentiment, count(*) FROM calls WHERE sentiment IS NOT NULL "
                "AND started_at >= :since GROUP BY sentiment"
            ),
            {"since": since_7d},
        )
    ).all()
    outcome = (
        await session.execute(
            text(
                "SELECT outcome_tag, count(*) FROM calls WHERE outcome_tag IS NOT NULL "
                "AND started_at >= :since GROUP BY outcome_tag"
            ),
            {"since": since_7d},
        )
    ).all()
    leads = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE created_at >= :since) AS new_leads, "
                "count(*) FILTER (WHERE status = 'hot') AS hot_open "
                "FROM leads WHERE deleted_at IS NULL"
            ),
            {"since": since_7d},
        )
    ).first()
    minutes = (await session.execute(text("SELECT minutes_used FROM spend_state LIMIT 1"))).scalar()

    return DashboardOut(
        calls_today=int(counts[0] or 0) if counts else 0,
        calls_7d=int(counts[1] or 0) if counts else 0,
        avg_duration_s=int(counts[2]) if counts and counts[2] is not None else None,
        after_hours_captured_7d=int(counts[3] or 0) if counts else 0,
        sentiment_split={row[0]: int(row[1]) for row in sentiment},
        outcome_split={row[0]: int(row[1]) for row in outcome},
        leads_new_7d=int(leads[0] or 0) if leads else 0,
        hot_leads_open=int(leads[1] or 0) if leads else 0,
        minutes_used_month=Decimal(minutes) if minutes is not None else None,
    )


__all__ = [
    "dashboard",
    "export_leads_csv",
    "get_call",
    "get_lead",
    "lead_columns",
    "lead_phone",
    "list_calls",
    "list_leads",
    "mask_phone",
    "recording_key_for",
    "update_lead",
]
