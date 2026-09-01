"""The agent ROSTER: one query, one row mapper, and every reader of both.

WHY THIS IS ITS OWN MODULE AND NOT PART OF `agents/service.py`.

The query, the mapper and `AgentOut` were private to `agents/routes.py`, which was correct
while the only caller was an endpoint. It stopped being correct when a second caller
appeared that is not a request: `copilot/tools.py::agents_list` answers "which agents do I
have, and are they published?" and had exactly two ways to get that answer — call a route
handler from a service (a layering inversion this repo has no precedent for) or keep a
second copy of the SQL (D-103's defect class). Both were refused and the read tool was
dropped rather than built on either, which is the gap this module closes.

`service.py` WAS THE OBVIOUS HOME AND IT DOES NOT WORK — verified by running it, not by
reasoning about it. `AgentOut` carries `truthful_answer_rule`, whose one wording lives in
`compliance/disclosure.py` (hard rule 5: one sentence, served, everywhere it is shown), and
that module imports `compliance/optout.py`, which imports `compliance/service.py`, which
imports `agents/service.py`. Putting the roster in `agents/service.py` therefore closed the
loop and `ImportError: cannot import name 'agent_outbound_number_blocker' from partially
initialized module` came out of the first import of the app. NOTHING here reaches back into
`agents/service.py`, so this module sits on the far side of that cycle and the chain stays
one-way.

That leaves the module anatomy BACKEND-PATTERNS §1 asks for intact rather than bent: this
IS the service layer for the roster read — "business logic AND queries", no repository
layer — split into a file the way `agents/` already splits `publishing.py`,
`verification.py`, `lifecycle.py` and `llm_models.py` out of one service module, and with
the wire model in `agents/schemas.py` exactly as `crm/schemas.py` holds `LeadOut`.
`routes.py` is left thin.

Nothing about the wire contract changed in the move. `scripts/check_openapi_fresh.py` is
what proves that rather than this sentence.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from calevate_shared.engine import DisclosurePosture, compose_opening_line
from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.llm_models import resolve_llm_model
from apps.api.agents.models import AgentStatus
from apps.api.agents.schemas import AgentOut

#: The roster query, spelled once and reached from every reader (D-302).
#:
#: It used to live inside the `GET /v1/agents` handler, and `get_agent` CALLED THAT HANDLER
#: and filtered the result in Python — "RLS-scoped; small list per tenant in v1", said the
#: comment. Bounding the list turned that belief into a defect a reader could see: with a
#: `LIMIT` on the roster, the 201st agent of an account would be a 404 on its own detail
#: route, found by nothing except the person whose screen it is. Asking for the one row by
#: id is also the query that should always have been here — one indexed lookup instead of a
#: scan of every agent plus their extraction schemas, on the route a dashboard opens most.
#:
#: The inbound-number count is a CORRELATED SUBQUERY rather than a fourth join, because
#: `phone_numbers` is one-to-many against `agents` while `extraction_schemas` is joined by
#: primary key: a `LEFT JOIN ... GROUP BY` would multiply every agent by its numbers and
#: then need every selected column in the grouping key, including the schema's JSONB. The
#: subquery is one index lookup on `phone_numbers.agent_id` per row of a per-tenant list
#: every reader bounds at `AGENT_ROSTER_LIMIT`.
AGENT_ROSTER_SQL = (
    "SELECT a.id, a.name, a.direction, a.status, a.language_primary, "
    "a.disclosure_line, a.engine, a.engine_agent_ref, es.fields, "
    "a.ai_disclosure_line, a.ai_disclosure_enabled, "
    "a.recording_notice_line, a.recording_notice_enabled, a.archived_at, "
    "(SELECT count(*) FROM phone_numbers pn WHERE pn.agent_id = a.id), "
    # The two rungs of the model fallback that live in the database (D-454). Joined
    # rather than fetched per row: `organizations` is one PK lookup and RLS makes it the
    # caller's own row, and resolving the fallback from two statements would let an
    # account default change land between them — a roster whose rows disagree about which
    # model the account runs.
    "a.llm_model, o.default_llm_model, "
    # Sentence three and its switch (D-507). APPENDED rather than slotted beside the two
    # sentences above, so every existing positional index below keeps meaning what it
    # meant — a shifted index in a positional row read is a silent field swap.
    "a.caller_memory_notice_line, a.caller_memory_enabled "
    "FROM agents a LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
    "LEFT JOIN organizations o ON o.id = a.tenant_id "
    "WHERE a.deleted_at IS NULL"
)

#: The largest roster one read may return — the route's own `Query(200, ge=1, le=200)`
#: bound (D-302), stated beside the query rather than only in the signature that used to
#: own it. An agent list is short in every account we have, and "short in every account we
#: have" is exactly the assumption that stops being true without anyone editing the file:
#: each row carries the agent's whole extraction schema, so the response grows in two
#: dimensions at once.
AGENT_ROSTER_LIMIT = 200


def agent_out(r: Any) -> AgentOut:
    """One roster row as the wire model. THE ONLY mapper for that query."""
    # Through the ONE resolver (`agents/llm_models.py`), so the roster, the detail route
    # and the config the engine is actually sent cannot disagree about which model an
    # agent runs or which level chose it.
    resolved = resolve_llm_model(agent_model=r[15], organization_model=r[16])
    return AgentOut(
        id=r[0],
        name=r[1],
        direction=r[2],
        status=r[3],
        language_primary=r[4],
        disclosure_line=r[5],
        engine=r[6],
        published=bool(r[7]),
        extraction_fields=[ExtractionField.model_validate(f) for f in (r[8] or [])],
        ai_disclosure_line=r[9],
        ai_disclosure_enabled=bool(r[10]),
        recording_notice_line=r[11],
        recording_notice_enabled=bool(r[12]),
        caller_memory_notice_line=str(r[17]),
        caller_memory_enabled=bool(r[18]),
        archived_at=r[13],
        inbound_number_count=int(r[14]),
        llm_model=r[15],
        llm_model_effective=resolved.model,
        llm_model_source=resolved.source,
        # Through the ONE composer, so the roster, the publish path and the engine
        # cannot disagree about what this agent opens with (D-163).
        opening_line=compose_opening_line(
            DisclosurePosture(
                ai_disclosure_line=str(r[9]),
                ai_disclosure_enabled=bool(r[10]),
                recording_notice_line=str(r[11]),
                recording_notice_enabled=bool(r[12]),
                caller_memory_notice_line=str(r[17]),
                caller_memory_enabled=bool(r[18]),
            )
        ),
    )


async def list_agents(
    session: AsyncSession,
    *,
    limit: int = AGENT_ROSTER_LIMIT,
    status: AgentStatus | None = None,
) -> list[AgentOut]:
    """This account's agents, under the caller's own RLS session.

    THE DEFAULT HIDES THE ARCHIVE, and that is the one surprising thing here. Every other
    filter in this repo defaults to "no filter"; this one cannot, because the set it would
    include is the only unbounded one — a client who retires an agent a month for two years
    has an archive longer than the `LIMIT`, and the agents they actually use would fall off
    the end of their own roster with nothing on the screen to say so.

    `ORDER BY` is by status bucket first and creation second, so the archive — when it is
    asked for — reads newest-retirement-first and the working roster keeps the stable order
    it had. `archived_at DESC NULLS LAST` does both in one clause: it is NULL for every
    non-archived row, which leaves those rows to the second key.
    """
    rows = (
        await session.execute(
            text(
                f"{AGENT_ROSTER_SQL} "
                # Two spellings of one parameter, and neither is caller text: the
                # filter applies when it is given, and the `IS NULL` arm is what "no
                # bucket asked for" means. An f-string branch here would be two SQL
                # statements to keep in step (`scripts/check_raw_sql.py`).
                #
                # CAST because the parameter's only other appearance is compared to a
                # `character varying` column, which leaves `$1 IS NULL` with no type to
                # infer and makes Postgres refuse the whole statement as ambiguous.
                "AND (CAST(:status AS text) IS NULL AND a.status <> 'archived' "
                "OR a.status = CAST(:status AS text)) "
                "ORDER BY a.archived_at DESC NULLS LAST, a.created_at LIMIT :limit"
            ),
            {"limit": limit, "status": status},
        )
    ).all()
    return [agent_out(r) for r in rows]


async def agent_by_id(session: AsyncSession, agent_id: UUID) -> AgentOut | None:
    """ONE roster row by id, under the caller's own RLS session, or `None`.

    `None` rather than a raise, so the caller decides what a miss means: the detail route
    answers 404 — which is also RLS's answer for a neighbour's agent id (hard rule 1) — and
    the read-back after a write treats it as impossible. A service that raised
    `ProblemError.not_found` would be a service choosing an HTTP status.
    """
    row = (
        await session.execute(text(f"{AGENT_ROSTER_SQL} AND a.id = :aid"), {"aid": agent_id})
    ).first()
    return None if row is None else agent_out(row)


__all__ = [
    "AGENT_ROSTER_LIMIT",
    "AGENT_ROSTER_SQL",
    "agent_by_id",
    "agent_out",
    "list_agents",
]
