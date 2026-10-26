"""WHICH LEADS and WHICH CALLS — the one definition (D-893 F2).

A lens is the set a person can read on their screen: the Leads table's filters
(`schemas.LeadLensIn`) and the Calls screen's (`schemas.CallLensIn`). The table, its counts,
its CSV export, the bulk action, a campaign's "add from a filter", Pip's `leads_find` /
`calls_find` and a plan's frozen targets (`copilot/plans.py`) all turn the lens into SQL
here, so "act on what I am looking at" means one thing everywhere.

Every value reaches the database as a bound parameter; a captured-field key is a parameter
too (`l.data ->> :key`), never part of the statement text.

Days are India days (D-709): `created_from = 2026-10-20` means from 00:00 IST that day, and
`created_to` includes the whole of its day (`< next day 00:00 IST`), the half-open form the
Calls screen already uses for `since`/`until`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.plans import IST
from apps.api.core.errors import ProblemError
from apps.api.crm.schemas import CallLensIn, CapturedFieldFilterIn, LeadLensIn
from apps.api.db.like import contains_pattern

#: The two lens shapes, under the names the plan and Pip use.
LeadLens = LeadLensIn
CallLens = CallLensIn

CallDirection = Literal["inbound", "outbound"]

#: One faceted filter: an extraction-schema key -> the values selected under it. Values are
#: OR'd, keys AND'd (`service._lead_scope`).
FieldFilters = dict[str, list[str]]

#: A call-back still to be placed (`callbacks.service.LIVE_STATUSES`).
_OPEN_CALLBACK: Final = "s.status IN ('scheduled', 'dialing')"


def day_start(day: date) -> datetime:
    """00:00 in India on `day`, as an aware instant."""
    return datetime.combine(day, time(0), tzinfo=IST)


def day_after(day: date) -> datetime:
    """00:00 in India on the day after `day`: the exclusive end of a range ending `day`."""
    return day_start(day + timedelta(days=1))


def _refuse_backwards(start: date | None, end: date | None, what: str) -> None:
    if start is not None and end is not None and end < start:
        raise ProblemError(
            kind="validation",
            code="lens_dates_backwards",
            title="That date range ends before it starts",
            detail=f"The {what} range ends before it starts.",
            remediation="Pick an end date on or after the start date.",
        )


# --- calls ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CallFilters:
    """What the Calls screen narrows by; the list, its CSV export and Pip read the same one,
    so "export what I am looking at" means exactly that."""

    status: str | None = None
    agent_id: UUID | None = None
    outcome: str | None = None
    direction: CallDirection | None = None
    #: Half-open `[since, until)` on when the call happened (`CALL_AT`); aware instants.
    since: datetime | None = None
    until: datetime | None = None
    #: The calls one campaign placed (`calls.campaign_id`), for its results' call links.
    campaign_id: UUID | None = None
    #: False leaves out free-trial test calls (`calls.trial_call`).
    test_calls: bool = True
    #: `done`: marked handled (`resolved`); `not_done`: anything else, unmarked included.
    follow_up: Literal["done", "not_done"] | None = None
    #: True: a call-back booked on the call is still to be placed; False: none is.
    callback_open: bool | None = None


#: When a call happened, for filtering and ordering the log: when it connected, else when it
#: was placed or arrived. On `started_at` alone a call still ringing, and one nobody
#: answered, fell outside every date range and sorted below the whole history.
CALL_AT: Final = "COALESCE(c.started_at, c.created_at)"


def call_where(filters: CallFilters) -> tuple[str, dict[str, Any]]:
    """`WHERE ...` over `calls c` and its parameters; `""` when nothing narrows it."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if filters.status:
        clauses.append("c.status = :status")
        params["status"] = filters.status
    if filters.agent_id:
        clauses.append("c.agent_id = :agent_id")
        params["agent_id"] = filters.agent_id
    if filters.outcome:
        clauses.append("c.outcome_tag = :outcome")
        params["outcome"] = filters.outcome
    if filters.direction:
        clauses.append("c.direction = :direction")
        params["direction"] = filters.direction
    if filters.since:
        clauses.append(f"{CALL_AT} >= :since")
        params["since"] = filters.since
    if filters.until:
        clauses.append(f"{CALL_AT} < :until")
        params["until"] = filters.until
    if filters.campaign_id:
        clauses.append("c.campaign_id = :campaign_id")
        params["campaign_id"] = filters.campaign_id
    if not filters.test_calls:
        clauses.append("c.trial_call IS NOT TRUE")
    if filters.follow_up == "done":
        clauses.append("c.follow_up_state = 'resolved'")
    elif filters.follow_up == "not_done":
        clauses.append("c.follow_up_state IS DISTINCT FROM 'resolved'")
    if filters.callback_open is not None:
        exists = (
            "EXISTS (SELECT 1 FROM scheduled_callbacks s WHERE s.source_call_id = c.id "
            f"AND s.tenant_id = c.tenant_id AND {_OPEN_CALLBACK})"
        )
        clauses.append(exists if filters.callback_open else f"NOT {exists}")
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


def call_filters(lens: CallLensIn) -> CallFilters:
    """The lens as the SQL-side filters: India days become instants."""
    _refuse_backwards(lens.from_day, lens.to_day, "call date")
    return CallFilters(
        status=lens.status,
        agent_id=lens.agent_id,
        outcome=lens.outcome,
        direction=lens.direction,
        since=None if lens.from_day is None else day_start(lens.from_day),
        until=None if lens.to_day is None else day_after(lens.to_day),
        campaign_id=lens.campaign_id,
        test_calls=lens.test_calls,
        follow_up=lens.follow_up,
        callback_open=lens.callback_open,
    )


async def count_calls(session: AsyncSession, filters: CallFilters) -> int:
    where, params = call_where(filters)
    row = (await session.execute(text(f"SELECT count(*) FROM calls c {where}"), params)).first()
    return int(row[0]) if row else 0


async def call_ids(session: AsyncSession, filters: CallFilters) -> list[UUID]:
    """Every call the lens matches, newest first. No cap: a plan freezes the whole set."""
    where, params = call_where(filters)
    rows = await session.execute(
        text(f"SELECT c.id FROM calls c {where} ORDER BY {CALL_AT} DESC, c.id DESC"), params
    )
    return [UUID(str(row[0])) for row in rows.all()]


# --- leads ---------------------------------------------------------------------------------


#: The `LeadLensIn` fields `LeadRowFilters` reads, for an audit row to name which were set.
LEAD_ROW_FILTER_FIELDS: Final = frozenset(
    {
        "created_from",
        "created_to",
        "last_call_from",
        "last_call_to",
        "last_outcome",
        "direction",
        "test_calls",
        "callback_open",
        "follow_up",
        "captured",
    }
)


@dataclass(frozen=True, slots=True)
class LeadRowFilters:
    """The lead predicates D-893 added to the table's lens, as `service._lead_scope` reads
    them. The latest call is `leads.last_call_id`."""

    created_from: date | None = None
    created_to: date | None = None
    last_call_from: date | None = None
    last_call_to: date | None = None
    last_outcome: str | None = None
    direction: CallDirection | None = None
    test_calls: bool = True
    callback_open: bool | None = None
    follow_up: Literal["done", "not_done"] | None = None
    captured: tuple[CapturedFieldFilterIn, ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, lens: LeadLensIn) -> LeadRowFilters:
        _refuse_backwards(lens.created_from, lens.created_to, "created")
        _refuse_backwards(lens.last_call_from, lens.last_call_to, "latest call")
        return cls(
            created_from=lens.created_from,
            created_to=lens.created_to,
            last_call_from=lens.last_call_from,
            last_call_to=lens.last_call_to,
            last_outcome=lens.last_outcome,
            direction=lens.direction,
            test_calls=lens.test_calls,
            callback_open=lens.callback_open,
            follow_up=lens.follow_up,
            captured=tuple(lens.captured),
        )


def lead_row_clauses(filters: LeadRowFilters, params: dict[str, Any]) -> list[str]:
    """The predicates over `leads l`, with their values added to `params`."""
    out: list[str] = []
    if filters.created_from is not None:
        out.append("l.created_at >= :lens_created_from")
        params["lens_created_from"] = day_start(filters.created_from)
    if filters.created_to is not None:
        out.append("l.created_at < :lens_created_to")
        params["lens_created_to"] = day_after(filters.created_to)
    last_call: list[str] = []
    if filters.last_call_from is not None:
        last_call.append(f"{CALL_AT} >= :lens_call_from")
        params["lens_call_from"] = day_start(filters.last_call_from)
    if filters.last_call_to is not None:
        last_call.append(f"{CALL_AT} < :lens_call_to")
        params["lens_call_to"] = day_after(filters.last_call_to)
    if filters.last_outcome is not None:
        last_call.append("c.outcome_tag = :lens_outcome")
        params["lens_outcome"] = filters.last_outcome
    if filters.direction is not None:
        last_call.append("c.direction = :lens_direction")
        params["lens_direction"] = filters.direction
    if filters.follow_up == "done":
        last_call.append("c.follow_up_state = 'resolved'")
    elif filters.follow_up == "not_done":
        last_call.append("c.follow_up_state IS DISTINCT FROM 'resolved'")
    if last_call:
        out.append(
            "EXISTS (SELECT 1 FROM calls c WHERE c.id = l.last_call_id AND "
            + " AND ".join(last_call)
            + ")"
        )
    if not filters.test_calls:
        out.append(
            "NOT EXISTS (SELECT 1 FROM calls c WHERE c.id = l.last_call_id "
            "AND c.trial_call IS TRUE)"
        )
    if filters.callback_open is not None:
        exists = (
            "EXISTS (SELECT 1 FROM scheduled_callbacks s WHERE s.lead_id = l.id "
            f"AND s.tenant_id = l.tenant_id AND {_OPEN_CALLBACK})"
        )
        out.append(exists if filters.callback_open else f"NOT {exists}")
    for index, wanted in enumerate(filters.captured):
        params[f"lens_ck{index}"] = wanted.key
        if wanted.op == "equals":
            out.append(f"lower(l.data ->> :lens_ck{index}) = lower(:lens_cv{index})")
            params[f"lens_cv{index}"] = wanted.value
        else:
            out.append(f"(l.data ->> :lens_ck{index}) ILIKE :lens_cv{index}")
            params[f"lens_cv{index}"] = contains_pattern(wanted.value)
    return out


def parse_field_filters(raw: Sequence[str], allowed: frozenset[str]) -> FieldFilters:
    """`f=key:value` -> `{key: [value, ...]}`, refusing anything this agent cannot filter on.

    Split on the FIRST colon, which is unambiguous because an extraction key is
    `^[a-z][a-z0-9_]{0,39}$` and therefore contains none — a value that contains one
    survives intact. An unknown key is refused, never dropped: dropping one would widen the
    set, which on the export is a mailed contact list and on a bulk action rows nobody chose.
    """
    parsed: FieldFilters = {}
    for entry in raw:
        key, sep, value = entry.partition(":")
        if not sep or not key or not value:
            raise ProblemError(
                kind="validation",
                code="lead_filter_malformed",
                title="Unreadable filter",
                detail=f"{entry!r} is not a filter. Filters are written `f=field:value`.",
                remediation="Re-apply the filter from the Leads screen.",
            )
        if key not in allowed:
            raise ProblemError(
                kind="validation",
                code="lead_filter_unknown_field",
                title="Unknown filter",
                detail=f"“{key}” is not a filterable field on this agent's capture list.",
                remediation=(
                    "Clear that filter and pick one from the panel. If it was a saved "
                    "view, open it again — the view will tell you which filters it lost."
                ),
            )
        parsed.setdefault(key, []).append(value)
    return parsed


@dataclass(frozen=True, slots=True)
class LeadScope:
    """A lead lens resolved against the account: the facets checked against the agent's
    capture list. What `lead_where` turns into SQL."""

    status: str | None
    search: str | None
    agent_id: UUID | None
    assigned_to: UUID | None
    field_filters: FieldFilters
    more: LeadRowFilters


async def resolve_lead_scope(session: AsyncSession, lens: LeadLensIn) -> LeadScope:
    """Check the lens's facets against the agent's capture list and freeze it.

    A lens with a semantic `ask` is refused: a ranking is not a set (the export refuses it
    for the same reason, `crm/routes._ASK_CANNOT_BE_EXPORTED`)."""
    from apps.api.crm import columns as lead_column_registry
    from apps.api.crm import service

    if lens.ask:
        raise ProblemError(
            kind="validation",
            code="lens_ask_not_a_set",
            title="A question can't choose a set of leads",
            detail="A question ranks the best matches rather than selecting every lead.",
            remediation="Use the filters (stage, dates, outcome, captured details) instead.",
        )
    available = lead_column_registry.available(await service.lead_columns(session, lens.agent_id))
    facets = frozenset(c.key for c in lead_column_registry.facetable(available))
    return LeadScope(
        status=lens.status,
        search=lens.search,
        agent_id=lens.agent_id,
        assigned_to=lens.assigned_to,
        field_filters=parse_field_filters(lens.f, facets),
        more=LeadRowFilters.of(lens),
    )


async def lead_ids(session: AsyncSession, scope: LeadScope) -> list[UUID]:
    """Every lead the lens matches, newest first. No cap: a plan freezes the whole set."""
    from apps.api.crm import service

    return await service.lead_ids_matching(
        session,
        status=scope.status,
        search=scope.search,
        agent_id=scope.agent_id,
        assigned_to=scope.assigned_to,
        field_filters=scope.field_filters,
        more=scope.more,
    )


def describe_lead_lens(lens: LeadLensIn) -> str:
    """The lens in the words a person reads on a plan card. Names fields, never values of a
    caller's data beyond what the person typed as the filter."""
    parts: list[str] = []
    if lens.status:
        parts.append(f"stage {lens.status}")
    if lens.search:
        parts.append("matching the search")
    if lens.created_from or lens.created_to:
        parts.append(_days("created", lens.created_from, lens.created_to))
    if lens.last_call_from or lens.last_call_to:
        parts.append(_days("last called", lens.last_call_from, lens.last_call_to))
    if lens.last_outcome:
        parts.append(f"last call {lens.last_outcome.replace('_', ' ')}")
    if lens.direction:
        parts.append(f"last call {lens.direction}")
    if not lens.test_calls:
        parts.append("no test calls")
    if lens.callback_open is not None:
        parts.append("with a call-back waiting" if lens.callback_open else "no call-back waiting")
    if lens.follow_up:
        parts.append("marked done" if lens.follow_up == "done" else "not marked done")
    if lens.assigned_to:
        parts.append("owned by one person")
    if lens.agent_id:
        parts.append("of one agent")
    parts += [f"{c.key.replace('_', ' ')} {c.op} “{c.value}”" for c in lens.captured]
    parts += [f"{entry.partition(':')[0].replace('_', ' ')} filter" for entry in lens.f]
    return "every lead" if not parts else "leads " + ", ".join(parts)


def _days(what: str, start: date | None, end: date | None) -> str:
    if start and end:
        return f"{what} {start.isoformat()} to {end.isoformat()}"
    if start:
        return f"{what} from {start.isoformat()}"
    assert end is not None
    return f"{what} up to {end.isoformat()}"


__all__ = [
    "CALL_AT",
    "LEAD_ROW_FILTER_FIELDS",
    "CallFilters",
    "CallLens",
    "FieldFilters",
    "LeadLens",
    "LeadRowFilters",
    "LeadScope",
    "call_filters",
    "call_ids",
    "call_where",
    "count_calls",
    "day_after",
    "day_start",
    "describe_lead_lens",
    "lead_ids",
    "lead_row_clauses",
    "parse_field_filters",
    "resolve_lead_scope",
]
