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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.crm.performance import IST_HOUR_SQL
from apps.api.crm.schemas import (
    CallDetailOut,
    CallSummaryOut,
    DashboardOut,
    LeadOut,
    TranscriptTurnOut,
)
from apps.api.db.result import rowcount_of

MAX_PAGE = 200

# The CSV export is the one read here with no page to bound it, and it materializes
# every row AND the whole file in the request. A tenant with 50k leads would turn one
# click into a hung worker, so the read is bounded and says so when it hits the bound —
# a silently truncated contact export is a worse failure than a refused one.
MAX_EXPORT_ROWS = 20_000


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

    Bounded by `MAX_EXPORT_ROWS`: every other read in this module is paged, and this
    one builds the entire file in memory inside the request.
    """
    columns = await lead_columns(session, agent_id)
    rows = (
        await session.execute(
            text(
                "SELECT phone_e164, name, status, source, call_count, created_at, data "
                "FROM leads WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT :limit"
            ),
            # One row over the cap, so hitting it is detectable without a second count.
            {"limit": MAX_EXPORT_ROWS + 1},
        )
    ).all()
    if len(rows) > MAX_EXPORT_ROWS:
        raise ProblemError.business_rule(
            "lead_export_too_large",
            f"This export is over the {MAX_EXPORT_ROWS:,}-lead limit for a single file.",
            remediation="Export one agent at a time with ?agent_id=, or ask us for a full extract.",
        )

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
                # IST by name, not by a fixed offset: EXTRACT on a timestamptz renders
                # it in the session's TimeZone, so `+ interval '5:30'` is only IST on a
                # database that happens to be set to UTC (same fix as performance.py).
                "  count(*) FILTER (WHERE started_at >= :since AND ("
                f"     {IST_HOUR_SQL} < 9 OR {IST_HOUR_SQL} >= 21"
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


# D-21 M2: a callback is a call whose reason is another call. Both numbers below are
# deliberately conservative, and both are about the person being rung rather than about
# us: three chained callbacks is already a robot that has phoned someone three times
# about one enquiry, and a follow-up a fortnight later is a cold call wearing a
# follow-up's clothes.
MAX_CALLBACK_DEPTH = 2
CALLBACK_WINDOW_DAYS = 7
# Outcomes a callback makes sense for. `resolved` is excluded on purpose: the whole
# point of recording an outcome is that we then act differently on it.
CALLBACK_OUTCOMES = ("needs_follow_up", "dropped")
CALLBACK_STATUSES = ("no_answer", "busy", "voicemail", "completed")


@dataclass(frozen=True, slots=True)
class CallbackPlan:
    """Everything the dispatch needs, plus the reason it is allowed."""

    lead_id: UUID
    agent_id: UUID
    phone_e164: str
    lead_name: str | None
    context_note: str
    depth: int


async def plan_callback(session: AsyncSession, call_id: UUID) -> CallbackPlan:
    """Decide whether this call may be followed up, and with what context.

    Refuses by NAMED rule rather than a bare 422, for the same reason the campaign
    launch gate does: the button needs to explain itself (SURFACES §2b).

    The context handed to the agent is OUR summary, never the transcript. A transcript
    is the most sensitive artefact we hold; a summary is what a human colleague would
    be told before picking up the phone, and it is what the extraction step already
    produced and the client already reads.
    """
    row = (
        await session.execute(
            text(
                "SELECT c.lead_id, c.agent_id, c.status, c.outcome_tag, c.summary, "
                "  c.created_at, c.callback_of_call_id, l.phone_e164, l.name, a.direction "
                "FROM calls c "
                "LEFT JOIN leads l ON l.id = c.lead_id "
                "JOIN agents a ON a.id = c.agent_id "
                "WHERE c.id = :cid"
            ),
            {"cid": call_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Call")
    (
        lead_id,
        agent_id,
        status,
        outcome,
        summary,
        created_at,
        parent,
        phone,
        lead_name,
        direction,
    ) = row

    if lead_id is None or phone is None:
        raise ProblemError.business_rule(
            "callback_no_lead",
            "This call is not linked to a lead, so there is no one to call back.",
        )
    if status not in CALLBACK_STATUSES:
        raise ProblemError.business_rule(
            "callback_call_unfinished",
            "This call has not finished yet.",
            remediation="Wait for the call to end, then try again.",
        )
    if status == "completed" and outcome not in CALLBACK_OUTCOMES:
        raise ProblemError.business_rule(
            "callback_not_needed",
            f"This call was marked {outcome or 'resolved'}, so no follow-up is due.",
        )
    if direction == "inbound":
        # The agent that ANSWERS is not necessarily configured to place calls, and
        # dispatching through it would fail at the gate anyway — say so here instead.
        raise ProblemError.business_rule(
            "callback_agent_inbound_only",
            "This agent only answers calls; it cannot place a callback.",
        )

    age_days = (datetime.now(UTC) - created_at).days if created_at else 0
    if age_days > CALLBACK_WINDOW_DAYS:
        raise ProblemError.business_rule(
            "callback_too_old",
            f"This call was {age_days} days ago; a follow-up now would read as a cold call.",
            remediation="Call the lead directly from the Leads table instead.",
        )

    depth = 0
    cursor = parent
    while cursor is not None and depth < 10:
        depth += 1
        cursor = (
            await session.execute(
                text("SELECT callback_of_call_id FROM calls WHERE id = :cid"), {"cid": cursor}
            )
        ).scalar()
    if depth >= MAX_CALLBACK_DEPTH:
        raise ProblemError.business_rule(
            "callback_chain_exhausted",
            "We have already followed up on this conversation twice.",
            remediation="A person should make the next call.",
        )

    note = (
        f"This is a follow-up to an earlier call. What happened last time: {str(summary).strip()}"
        if summary
        else "This is a follow-up to an earlier call that ended without a resolution."
    )
    return CallbackPlan(
        lead_id=UUID(str(lead_id)),
        agent_id=UUID(str(agent_id)),
        phone_e164=str(phone),
        lead_name=lead_name,
        context_note=note,
        depth=depth,
    )


async def link_callback(session: AsyncSession, *, handle: str, parent_call_id: UUID) -> None:
    """Stamp the new call as a follow-up of the old one, by engine handle.

    Separate from `dispatch_call` on purpose: that function is the ONE outbound entry
    point and must not grow a parameter per caller (D-21 button, campaigns, webhooks).
    """
    await session.execute(
        text(
            "UPDATE calls SET callback_of_call_id = :parent, updated_at = now() "
            "WHERE engine_call_id = :handle"
        ),
        {"parent": parent_call_id, "handle": handle},
    )


__all__ = [
    "CALLBACK_OUTCOMES",
    "MAX_CALLBACK_DEPTH",
    "MAX_EXPORT_ROWS",
    "MAX_PAGE",
    "CallbackPlan",
    "dashboard",
    "export_leads_csv",
    "get_call",
    "get_lead",
    "lead_columns",
    "lead_phone",
    "link_callback",
    "list_calls",
    "list_leads",
    "mask_phone",
    "plan_callback",
    "recording_key_for",
    "update_lead",
]
