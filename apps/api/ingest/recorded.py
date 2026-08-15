"""The second implementation of `LeadRetriever` — a seam is only proven by one.

TRD §5's `fake` voice engine is the precedent and the argument: an adapter contract that
has exactly one implementation is a contract nobody has tested, because the one
implementation IS the contract. So `META_LEAD_RETRIEVER=recorded` selects this, and it
answers every read from a fixture instead of from Meta.

It buys three things that are not "tests pass":

1. **The whole ingest path runs with no Meta app.** A developer, and a staging box, can
   POST a signed leadgen notification and watch a lead land, a consent gate refuse, and
   an outbound call dispatch — the flow hard rule 5 forbids adding a bypass to. Staging
   fixtures are what that rule says to use instead, and this is one.
2. **The mapping is exercised on the vendor's shape.** The fixtures here are Meta's
   documented `field_data` — `[{"name": …, "values": [...]}]` — and this class runs them
   through the same `flatten_field_data` the Graph adapter uses. A fixture that were
   already flat would test our own convenience rather than their format.
3. **The refusal vocabulary has a producer that needs no network.** `answer_with` hands
   back any `RetrievedLead`, so every branch the route takes on a permanent or transient
   verdict can be driven deterministically.

**It is refused outside `APP_ENV=local`.** Same rule as the `console` sinks in
`workers/whatsapp.py` and `workers/sheets_sync.py`, and here it matters more than there:
a recorded retriever in production would fabricate a lead — a name and a phone number
that no person ever typed — and hand it to the compliance gate as though someone had.
The gate would pass it, because the gate's job is to check consent and DNC, not to doubt
that the lead exists. So the refusal is in the SELECTOR (`meta.lead_retrieval_capability`)
rather than in a warning here.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from apps.api.ingest.meta import RetrievalStatus, RetrievedLead, flatten_field_data

#: The provider name that selects this adapter (`META_LEAD_RETRIEVER=recorded`).
PROVIDER: Final = "recorded"

#: One lead, in Meta's own `field_data` shape, for a developer who just wants the path to
#: run. Obviously synthetic on purpose — the number is in the Indian mobile range so
#: `normalize_phone` accepts it, and the name says what it is. The consent question is
#: present and affirmed, because the interesting default is the flow that COMPLETES; a
#: developer who wants the refusal removes the mapping's `consent_field` and gets it.
DEFAULT_FIELD_DATA: Final[tuple[dict[str, Any], ...]] = (
    {"name": "full_name", "values": ["Recorded Sample Lead"]},
    {"name": "phone_number", "values": ["+919876500000"]},
    {"name": "may_we_call_you", "values": ["yes"]},
)


class RecordedLeadRetriever:
    """Answers from fixtures. No network, no credential, no vendor.

    `per_lead` keys are `leadgen_id`s: two different leads in one delivery must be able
    to carry two different people, or "we rang exactly one customer" could be proved by a
    coincidence in the fixture rather than by the dedupe.

    `sources` is the per-tenant half of the seam. `None` means "this retriever answers for
    any lead source", which is what a local dev box wants; a set means only those sources
    hold a credential, which is how the unavailable-for-THIS-client path is driven.
    """

    name = PROVIDER

    def __init__(
        self,
        field_data: tuple[dict[str, Any], ...] | list[dict[str, Any]] = DEFAULT_FIELD_DATA,
        *,
        per_lead: dict[str, list[dict[str, Any]]] | None = None,
        answers_with: RetrievedLead | None = None,
        sources: frozenset[UUID] | None = None,
    ) -> None:
        self._field_data = list(field_data)
        self._per_lead = per_lead or {}
        self._answers_with = answers_with
        self._sources = sources
        #: Which leads were asked for, in order. A recording adapter that did not record
        #: what it was asked would make "one delivery, one Graph read" unprovable.
        self.calls: list[str] = []

    def holds_credential_for(self, source_id: UUID) -> bool:
        return self._sources is None or source_id in self._sources

    async def fetch_answers(self, *, source_id: UUID, leadgen_id: str) -> RetrievedLead:
        self.calls.append(leadgen_id)
        if self._answers_with is not None:
            return self._answers_with
        return RetrievedLead(
            status=RetrievalStatus.RETRIEVED,
            # THROUGH the same normalizer the real adapter uses (see the docstring):
            # the fixture is Meta's shape, not ours.
            answers=flatten_field_data(self._per_lead.get(leadgen_id, self._field_data)),
        )


__all__ = ["DEFAULT_FIELD_DATA", "PROVIDER", "RecordedLeadRetriever"]
