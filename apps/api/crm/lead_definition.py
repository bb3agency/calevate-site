"""What the product counts as a lead: the one definition every lead count and rate reads.

Every person called or calling gets a row in `leads`, so a row is a contact, a potential
lead, and not a lead. A LEAD is a person whose record reached interested, hot or won: they
showed interest. This is how an ad platform counts leads: Meta's "Leads (form)" is the form
responses people submitted, not everyone who saw the ad, and its cost per lead is spend over
those. The Leads screen keeps listing every contact by status; a COUNT or a RATE that says
"leads" comes from here, and one that means everyone says "people".

WHEN A PERSON BECAME A LEAD is the first `status_change` timeline row into the band. Both
writers of a status move write that row in the same transaction: the after-call rules
(`workers/pipeline._advance_lead_status`) and a person (`crm/service.set_lead_status`).
`status_set_at` is not the date: every later move (interested to hot, or a person's lost)
rewrites it, which would file one lead under several windows or drop it. A lead that later
fell out of the band (marked lost) still became a lead on that day, as a submitted form stays
a lead after the sale is lost, so each person is counted once, on one day, and a total of
leads is the same set with no window. A row standing in the band with no such timeline row
is dated by `status_set_at`, else `created_at`, rather than left out.
"""

from __future__ import annotations

from typing import Final

from apps.api.crm.schemas import LeadStatus

#: The statuses that make a contact a lead.
LEAD_BAND: Final[tuple[LeadStatus, ...]] = ("interested", "hot", "won")

_BAND_SQL: Final = repr(LEAD_BAND)

#: Every lead of the session's account, one row each: `id`, `agent_id`, `first_call_id`,
#: `status`, `became_lead_at`. A derived table: `FROM {BECAME_LEADS_SQL} AS bl WHERE
#: bl.became_lead_at >= :start AND bl.became_lead_at < :end`. RLS on `leads` and
#: `lead_events` scopes it; the timeline read is one grouped pass over the account's
#: status moves, joined by hash rather than probed per lead.
BECAME_LEADS_SQL: Final = (
    "(SELECT l.id, l.agent_id, l.first_call_id, l.status, "
    "COALESCE(r.reached_at, l.status_set_at, l.created_at) AS became_lead_at "
    "FROM leads l LEFT JOIN ("
    "SELECT e.lead_id, min(e.created_at) AS reached_at FROM lead_events e "
    f"WHERE e.type = 'status_change' AND e.payload ->> 'status' IN {_BAND_SQL} "
    "GROUP BY e.lead_id) r ON r.lead_id = l.id "
    f"WHERE l.deleted_at IS NULL AND (r.reached_at IS NOT NULL OR l.status IN {_BAND_SQL}))"
)

__all__ = ["BECAME_LEADS_SQL", "LEAD_BAND"]
