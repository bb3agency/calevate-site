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

A TEST CALL NEVER MAKES A LEAD (founder, 5 Nov 2026). A test call is the owner ringing their
own agent; counting it would lower cost per lead with the owner's own enthusiasm. The
after-call rules move a lead on a test call like on any other (the timeline stays true), so
the exclusion is here, in the one definition, rather than in each reader: a move the
after-call rules made (`by = after_call_rules`) counts only once the lead has had a real call
at or before it. A person's own move counts whatever calls came before it, because a person
chose it. Moves carry no call id, so "a real call at or before the move" is the test: the
rules write the move after the call that caused it, so a move after a test call and before
any real call is that test call's.
"""

from __future__ import annotations

from typing import Final

from apps.api.crm.schemas import LeadStatus

#: The statuses that make a contact a lead.
LEAD_BAND: Final[tuple[LeadStatus, ...]] = ("interested", "hot", "won")

#: Built by joining quoted literals rather than `repr(LEAD_BAND)`: the same text, but one
#: `scripts/check_raw_sql.py` can trace to literals in this file, where `repr()` of a value
#: is text it cannot vouch for.
_BAND_SQL: Final = "(" + ", ".join(f"'{status}'" for status in LEAD_BAND) + ")"

#: Every lead of the session's account, one row each: `id`, `agent_id`, `first_call_id`,
#: `status`, `became_lead_at`. A derived table: `FROM {BECAME_LEADS_SQL} AS bl WHERE
#: bl.became_lead_at >= :start AND bl.became_lead_at < :end`. RLS on `leads` and
#: `lead_events` scopes it; the timeline read is one grouped pass over the account's
#: status moves, joined by hash rather than probed per lead.
#: A call that is not a test call: not a free-trial call and not a paid test call (D-697,
#: D-859), the same predicate `analytics/service._CALLS_IN_RANGE` leaves test calls out by.
REAL_CALL_SQL: Final = "NOT (c.trial_call OR c.paid_test_call)"

#: Each lead's first real call, by when it was made.
_FIRST_REAL_CALL = (
    "(SELECT c.lead_id, min(c.created_at) AS first_real_at FROM calls c "
    f"WHERE c.lead_id IS NOT NULL AND {REAL_CALL_SQL} GROUP BY c.lead_id)"
)

BECAME_LEADS_SQL: Final = (
    "(SELECT l.id, l.agent_id, l.first_call_id, l.status, "
    "COALESCE(r.reached_at, l.status_set_at, l.created_at) AS became_lead_at "
    "FROM leads l LEFT JOIN ("
    "SELECT e.lead_id, min(e.created_at) AS reached_at FROM lead_events e "
    f"LEFT JOIN {_FIRST_REAL_CALL} fr ON fr.lead_id = e.lead_id "
    f"WHERE e.type = 'status_change' AND e.payload ->> 'status' IN {_BAND_SQL} "
    "AND (e.payload ->> 'by' IS DISTINCT FROM 'after_call_rules' "
    "OR fr.first_real_at <= e.created_at) "
    "GROUP BY e.lead_id) r ON r.lead_id = l.id "
    # A row standing in the band with no timeline move into it (written before the timeline
    # existed) still counts; one whose only moves in were test calls' does not.
    "WHERE l.deleted_at IS NULL AND (r.reached_at IS NOT NULL OR ("
    f"l.status IN {_BAND_SQL} AND NOT EXISTS (SELECT 1 FROM lead_events t "
    f"WHERE t.lead_id = l.id AND t.type = 'status_change' "
    f"AND t.payload ->> 'status' IN {_BAND_SQL}))))"
)

__all__ = ["BECAME_LEADS_SQL", "LEAD_BAND", "REAL_CALL_SQL"]
