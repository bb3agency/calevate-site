"""Semantic search over LEADS — "show me leads who asked about a 3BHK in Gachibowli".

The question is asked in a person's own words about their callers' own words, and the
answer is a set of CRM ROWS. That shape is why this module exists between two others rather
than inside either: `retrieval/caller_search.py` knows about vectors and lexemes and
nothing about a client's screen, and `crm/service.py` knows about the screen and nothing
about vectors. This is the two-step that joins them.

--------------------------------------------------------------------------------
RANK, THEN FILTER — AND THE ORDER IS THE DESIGN
--------------------------------------------------------------------------------
1. `search_caller_chunks` fuses a dense and a sparse arm over this tenant's `lead`
   projections and returns ranked LEAD IDS (the store holds no content, so there is
   nothing else it could return).
2. `crm/service.leads_ranked_by_id` hydrates them THROUGH `_lead_scope` — the same filter
   builder the list, the facet counts and the CSV export use.

So every existing filter keeps working, by construction rather than by a second WHERE
clause somebody has to keep in step: searching inside "hot leads assigned to me" is those
leads ranked. The cost of this order is that filters can shrink the result, which is why
`_RANK_DEPTH` ranks deeper than any caller displays and why `LeadSearch.exhausted` reports
what actually came back instead of promising `limit` rows.

The rejected alternative was filter-then-rank — narrowing `caller_chunks` with the screen's
predicate inside the search statement. It is one round trip instead of two, and it was
refused because the predicate is built dynamically from the extraction schema's facet keys:
splicing it into the vector statement would put a runtime-shaped fragment into SQL that
runs under a tenant's RLS session, which is exactly the class `scripts/check_raw_sql.py`
exists to forbid (D-172). One extra indexed read by primary key is a cheap price for
keeping every dynamic fragment inside the module that already builds and tests it.

--------------------------------------------------------------------------------
A LEAD APPEARS ONCE, AT ITS BEST CHUNK
--------------------------------------------------------------------------------
A lead with many captured fields projects to several chunks, so the fused rows have to be
collapsed to leads. The score kept is the **MAX** over that lead's chunks, never the sum:
summing rewards a lead for HAVING more fields, which is a length bias and not relevance —
the lead that answered eleven questions would outrank the lead that actually said
"Gachibowli". Max says "this lead's best match", which is the question that was asked.

--------------------------------------------------------------------------------
MONEY (hard rule 7) AND WHO PAYS
--------------------------------------------------------------------------------
The QUESTION's embedding is metered against the CLIENT's AI quota under
`ASSIST_FEATURE_LEAD_SEARCH` — their own click, their own ceiling, and its own cost curve
so an operator can size lead search apart from knowledge search and call search. It is
bought only if it is priceable, before the provider is called, and a deployment that cannot
price it still answers from the sparse arm. INGESTION of these leads is the platform's
spend and belongs to the shared sweep: one claim, one price check, no second sweep here.

HARD RULE 6: this module logs a count and a tenant id. Not the question — a person
searching "3BHK Gachibowli" has typed a fact about a caller, and a search box is a log line
away from being a transcript.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.crm import service as crm_service
from apps.api.crm.lead_projection import LEAD_SUBJECT_KIND
from apps.api.crm.models import LEAD_STATUSES
from apps.api.crm.schemas import LEAD_ASK_MAX_CHARS, LeadOut
from apps.api.retrieval.caller_search import MAX_K, search_caller_chunks
from apps.api.retrieval.embedding import ASSIST_FEATURE_LEAD_SEARCH

log = get_logger(__name__)

#: The longest question this surface will embed — `crm/schemas.LEAD_ASK_MAX_CHARS`, which
#: is also the wire bound on `LeadLensIn.ask`. Re-exported rather than re-declared so the
#: route's 422 and this module's truncation cannot come to disagree about one number.
MAX_QUESTION_CHARS = LEAD_ASK_MAX_CHARS

#: How many CHUNKS are ranked before the screen's filters are applied.
#:
#: DEEPER THAN ANY CALLER DISPLAYS, and the depth is in CHUNKS while the answer is in
#: LEADS — two reasons to over-rank, and both would otherwise be silent. The filters run
#: afterwards and can remove any hit, so ranking exactly `limit` would let a status filter
#: that excluded two leads return two rows fewer with nothing to distinguish that from
#: "only three leads match"; and a lead with many captured fields contributes several
#: chunks, so `n` chunks is somewhere between `n` and one lead.
#:
#: `caller_search.MAX_K` is the store's own ceiling and this stays under it, so the store
#: never has to clamp a `k` this module chose — a clamp is the silent no-op the port
#: forbids.
_RANK_DEPTH = min(30, MAX_K)


@dataclass(frozen=True, slots=True)
class LeadSearch:
    """One search: the leads, best match first, and whether the ranking ran out."""

    leads: tuple[LeadOut, ...]
    #: status → count across ALL six statuses, over the MATCHED set and never narrowed by
    #: the status filter. `LeadPage.status_counts`' contract, held here so the Leads
    #: screen's chip row means the same thing in both modes: "of the leads that match this
    #: question, how many are hot".
    status_counts: dict[str, int]
    #: How many distinct leads the store ranked BEFORE the screen's filters. With
    #: `len(leads)` it is what lets a caller say "12 matched, 3 of them are hot" rather
    #: than implying the account has three matching leads.
    ranked: int
    #: True when the ranking hit `_RANK_DEPTH` — there may be more matches this search did
    #: not look at. `_listing`'s "there may be more" rule, as a field rather than as prose,
    #: because the copilot and the screen both have to say it and neither should guess it.
    exhausted: bool


async def search_leads(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    question: str,
    limit: int = 10,
    status: str | None = None,
    search: str | None = None,
    agent_id: UUID | None = None,
    assigned_to: UUID | None = None,
    field_filters: crm_service.FieldFilters | None = None,
) -> LeadSearch:
    """Leads whose captured answers match `question`, narrowed by the screen's filters.

    Returns an empty result — never raises — for an empty question or no match. "No lead
    said anything like that" is an answer a client acts on; an exception is not.
    """
    asked = question.strip()[:MAX_QUESTION_CHARS]
    if not asked:
        empty: dict[str, int] = dict.fromkeys(LEAD_STATUSES, 0)
        return LeadSearch(leads=(), status_counts=empty, ranked=0, exhausted=False)

    hits = await search_caller_chunks(
        session,
        tenant_id=tenant_id,
        question=asked,
        kinds=(LEAD_SUBJECT_KIND,),
        feature=ASSIST_FEATURE_LEAD_SEARCH,
        k=_RANK_DEPTH,
        agent_id=agent_id,
    )
    # Collapse chunks to leads, keeping each lead's BEST chunk and the fused order. `dict`
    # preserves insertion order and the hits arrive sorted, so the first time a lead is
    # seen is already its best — but the max is taken explicitly rather than relied upon,
    # because "the rows are sorted" is a property of a statement three modules away.
    best: dict[UUID, float] = {}
    for hit in hits:
        current = best.get(hit.subject_id)
        if current is None or hit.score > current:
            best[hit.subject_id] = hit.score
    ranked = sorted(best, key=lambda lead_id: best[lead_id], reverse=True)

    # HYDRATED WITHOUT `status`, then counted, then narrowed — `list_leads_page`'s order
    # and its reason: a per-status breakdown that the status filter had already narrowed
    # would say "hot 3" on a screen filtered to hot and nothing about the rest, which is
    # the number a person is looking at the chip row to find.
    matched = await crm_service.leads_ranked_by_id(
        session,
        lead_ids=ranked,
        search=search,
        agent_id=agent_id,
        assigned_to=assigned_to,
        field_filters=field_filters,
    )
    counts: dict[str, int] = dict.fromkeys(LEAD_STATUSES, 0)
    for lead in matched:
        counts[lead.status] = counts.get(lead.status, 0) + 1
    leads = [lead for lead in matched if status is None or lead.status == status]
    log.info(
        "lead_semantic_search",
        # Hard rule 6: counts and ids. The question is the one thing that must not be here.
        extra={
            "tenant_id": str(tenant_id),
            "chunks": len(hits),
            "ranked": len(ranked),
            "shown": len(leads),
        },
    )
    return LeadSearch(
        leads=tuple(leads[:limit]),
        status_counts=counts,
        # The number of leads the STORE matched, not the number shown and not the number
        # the account has. It is what lets a caller say "12 matched, 3 of them are hot"
        # instead of implying the account holds three leads.
        ranked=len(matched),
        exhausted=len(hits) >= _RANK_DEPTH,
    )


__all__ = ["MAX_QUESTION_CHARS", "LeadSearch", "search_leads"]
