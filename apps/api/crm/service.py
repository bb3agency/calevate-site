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
from typing import Any, Literal, get_args
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.business_hours import count_after_hours_calls
from apps.api.core.errors import ProblemError
from apps.api.crm.performance import IST_HOUR_SQL
from apps.api.crm.schemas import (
    CallDetailOut,
    CallSummaryOut,
    DashboardOut,
    LeadOut,
    LeadStatus,
    TranscriptTurnOut,
)
from apps.api.db.result import rowcount_of

MAX_PAGE = 200

# Read off the response model's own Literal rather than retyped here, so the six
# buckets the API promises and the six the DB CHECK constraint allows cannot drift
# apart in a way that silently drops a status from every client's tally.
LEAD_STATUSES: tuple[str, ...] = get_args(LeadStatus)

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


def _lead_scope(
    params: dict[str, Any],
    *,
    search: str | None,
    agent_id: UUID | None,
) -> list[str]:
    """The filters that define WHICH leads a request is about, minus `status`.

    Shared by the list, its per-status counts and the CSV export, so that "export what
    I am looking at" is a property of one function rather than a coincidence between
    three copies of a WHERE clause. `status` is deliberately not here: the counts need
    the scope WITHOUT it (see `list_leads_page`).

    `agent_id` filters ROWS. It used to select only the extraction schema that supplies
    the table's COLUMNS while every agent's rows came back, so a two-agent tenant read
    agent B's leads under agent A's capture list — and the export's own too-large
    remediation ("Export one agent at a time with ?agent_id=") could never relieve the
    cap it advertised. `leads.agent_id` is NOT NULL and part of
    UNIQUE(tenant_id, phone_e164, agent_id), so a lead belongs to exactly one agent and
    "rows for this agent" is well defined (DATA-MODEL §5).
    """
    clauses = ["deleted_at IS NULL"]
    if search:
        # Name or phone suffix. Never a LIKE on the full number in a logged query
        # string — the route passes this as a bound parameter for that reason.
        clauses.append("(name ILIKE :search OR phone_e164 LIKE :phone_suffix)")
        params["search"] = f"%{search}%"
        params["phone_suffix"] = f"%{search}"
    if agent_id:
        clauses.append("agent_id = :agent_id")
        params["agent_id"] = agent_id
    return clauses


@dataclass(frozen=True, slots=True)
class LeadPage:
    """One page of leads, plus the two numbers that describe what it is a page OF."""

    items: list[LeadOut]
    # Rows matching EVERY filter, `status` included — what "showing 50 of 140" counts.
    total: int
    # status → count across ALL six statuses, for the same search/agent scope. Never
    # narrowed by `status`, which is the whole reason it exists.
    status_counts: dict[str, int]


async def list_leads_page(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    search: str | None = None,
    agent_id: UUID | None = None,
) -> LeadPage:
    """A page of leads and a truthful per-status breakdown of the set it came from.

    **Two queries, same as before.** The `SELECT count(*)` that produced `total` is now
    a `GROUP BY status` over the scope MINUS the status filter, and `total` is read back
    out of that map (or is its sum when no status is asked for). Same single pass over
    the same rows, a hash aggregate over at most six groups on top, and no second trip:
    the per-status counts are effectively free relative to the count we already paid
    for. Costing them as a separate query would have doubled the scan on every keystroke
    of the debounced search, which is the version of this that was not worth shipping.

    The counts follow the SEARCH (and the agent scope) and ignore the STATUS filter.
    That is the only combination that answers the question the UI is asking — "of what
    I am looking at, how much sits in each stage" — and it is also the cheap one: a
    whole-account breakdown next to a searched page would need its own unfiltered scan.
    The response field is named `status_counts_matching_search` so a reader never has to
    come here to find out which it is.
    """
    params: dict[str, Any] = {"limit": min(limit, MAX_PAGE), "offset": offset}
    scope = _lead_scope(params, search=search, agent_id=agent_id)
    scope_where = f"WHERE {' AND '.join(scope)}"

    grouped = (
        await session.execute(
            text(f"SELECT status, count(*) FROM leads {scope_where} GROUP BY status"), params
        )
    ).all()
    # Zero-fill: a status the tenant has none of must answer 0, not go missing. The UI
    # renders one badge per status, and an absent key there is indistinguishable from a
    # field the server failed to send.
    counts = dict.fromkeys(LEAD_STATUSES, 0)
    for name, count in grouped:
        counts[str(name)] = int(count)
    # A status outside the enum matches no rows, which is exactly what `.get(..., 0)`
    # says — and the row query below independently agrees by returning nothing.
    total = counts.get(status, 0) if status else sum(counts.values())

    row_clauses = list(scope)
    if status:
        row_clauses.append("status = :status")
        params["status"] = status
    rows = (
        await session.execute(
            text(
                "SELECT id, phone_e164, name, status, source, data, schema_version, "
                "call_count, is_repeat_caller, last_call_id, created_at, updated_at "
                f"FROM leads WHERE {' AND '.join(row_clauses)} "
                # `id DESC` is not decoration. OFFSET pagination is only correct over a
                # TOTAL order, and `updated_at` is not one: leads written by a single
                # import share it to the microsecond, and Postgres is free to order ties
                # differently per query — so a row lands on two pages while another
                # lands on none, with `total` staying right throughout. Offset itself is
                # kept deliberately (see the note in `list_leads`).
                "ORDER BY updated_at DESC, id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).all()
    return LeadPage(items=[_lead_out(r) for r in rows], total=total, status_counts=counts)


async def list_leads(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    search: str | None = None,
    agent_id: UUID | None = None,
) -> tuple[list[LeadOut], int]:
    """Rows and total only, for callers that do not want the status breakdown.

    Kept as the plain two-value read on top of `list_leads_page`; it costs the same
    queries, so there is no reason for a caller to reach past it for speed.

    On pagination: this stays LIMIT/OFFSET, and that is a decision rather than an
    oversight. Keyset pagination is the right answer at a size this product does not
    have — the page is capped at 200 rows, the largest tenant we plan for is tens of
    thousands of leads, and `total` plus "jump to page N" are both in the shipped
    contract and both incompatible with a cursor. What actually broke at scale was the
    ORDER BY, not the OFFSET, and that is fixed above. Revisit when a single tenant's
    lead table passes six figures or the UI grows infinite scroll.
    """
    page = await list_leads_page(
        session, limit=limit, offset=offset, status=status, search=search, agent_id=agent_id
    )
    return page.items, page.total


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


async def export_leads_csv(
    session: AsyncSession,
    *,
    agent_id: UUID | None = None,
    status: str | None = None,
    search: str | None = None,
) -> str:
    """CSV export with schema-driven columns (TRD §7 (e)).

    The phone is exported IN FULL: this is the client's own customer data, the export
    is role-gated and audit-logged by the route, and a CSV of masked numbers is useless
    for the follow-up call it exists to enable. That is a different judgement from the
    on-screen list, and it is deliberate.

    **Takes the same filters as `list_leads_page`, through the same `_lead_scope`.**
    It took `agent_id` alone, so a client who narrowed the table to `hot` and pressed
    Export downloaded every contact in the account — a difference between what the
    screen showed and what the file held, on the one route that emits unmasked numbers.
    Sharing the WHERE builder is what keeps the two in step as filters grow.

    Bounded by `MAX_EXPORT_ROWS`: every other read in this module is paged, and this
    one builds the entire file in memory inside the request. The bound now applies to
    the FILTERED rows, which is what makes the refusal's advice ("narrow it") reachable.
    """
    columns = await lead_columns(session, agent_id)
    params: dict[str, Any] = {"limit": MAX_EXPORT_ROWS + 1}
    clauses = _lead_scope(params, search=search, agent_id=agent_id)
    if status:
        clauses.append("status = :status")
        params["status"] = status
    rows = (
        await session.execute(
            text(
                "SELECT phone_e164, name, status, source, call_count, created_at, data "
                f"FROM leads WHERE {' AND '.join(clauses)} "
                # Tiebreaker for the same reason as the list — here the stakes are which
                # rows survive the LIMIT, so an unstable sort means two exports of one
                # unchanged account hand back two different sets of people.
                "ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            # One row over the cap, so hitting it is detectable without a second count.
            params,
        )
    ).all()
    if len(rows) > MAX_EXPORT_ROWS:
        raise ProblemError.business_rule(
            "lead_export_too_large",
            f"This export is over the {MAX_EXPORT_ROWS:,}-lead limit for a single file.",
            remediation=(
                "Narrow it — filter by status or search on the Leads screen and export "
                "again, or export one agent at a time with ?agent_id= — or ask us for a "
                "full extract."
            ),
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
    over an already tenant-scoped view, and the dashboard polls (D-24).

    **The after-hours tile prefers the client's own hours.** FLOWS §3 specifies the
    `after_hours` flag as derived from `agents.business_hours`; until the intake step
    landed there was nothing in that column, so this counted a hardcoded 09:00-21:00
    IST window instead. That window is right only for a client who happens to keep
    those hours and wrong in both directions otherwise — it misses the late-night
    clinic's 22:30 enquiry entirely and files every Sunday walk-in at the
    Sunday-closed salon as business as usual.

    The hardcoded window survives as a FALLBACK rather than being deleted, because a
    client who has not done the intake yet would otherwise watch a working tile drop to
    zero and read it as calls being lost. What is new is that the response says which
    of the two it is (`after_hours_basis`), so the number is never silently a guess
    wearing the clothes of a fact.
    """
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

    # One cheap existence check decides which definition the tile is entitled to. It is
    # asked of `agents` rather than inferred from the count above, because "no agent has
    # hours" and "hours are recorded and nothing fell outside them" are different facts
    # that both produce zero.
    has_hours = bool(
        (
            await session.execute(
                text("SELECT 1 FROM agents WHERE business_hours IS NOT NULL LIMIT 1")
            )
        ).scalar()
    )
    if has_hours:
        after_hours = await count_after_hours_calls(session, since=since_7d)
        after_hours_basis: Literal["business_hours", "default_window"] = "business_hours"
    else:
        after_hours = int(counts[3] or 0) if counts else 0
        after_hours_basis = "default_window"

    return DashboardOut(
        calls_today=int(counts[0] or 0) if counts else 0,
        calls_7d=int(counts[1] or 0) if counts else 0,
        avg_duration_s=int(counts[2]) if counts and counts[2] is not None else None,
        after_hours_captured_7d=after_hours,
        after_hours_basis=after_hours_basis,
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
    "LEAD_STATUSES",
    "MAX_CALLBACK_DEPTH",
    "MAX_EXPORT_ROWS",
    "MAX_PAGE",
    "CallbackPlan",
    "LeadPage",
    "dashboard",
    "export_leads_csv",
    "get_call",
    "get_lead",
    "lead_columns",
    "lead_phone",
    "link_callback",
    "list_calls",
    "list_leads",
    "list_leads_page",
    "mask_phone",
    "plan_callback",
    "recording_key_for",
    "update_lead",
]
