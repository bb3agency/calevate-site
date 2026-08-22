"""CRM request/response models.

**The response model IS the output whitelist** (BACKEND-PATTERNS §1). Every model here
sets `extra="forbid"`, which is what the redaction-exposure guardrail checks: a field
that is not declared cannot be serialized, so adding a raw transcript column to a query
cannot accidentally ship it to a browser.

Two fields are deliberately absent from every default response:
- `transcript_turns[].text` (raw) — `text_redacted` is the default view (hard rule 5).
- the engine's recording URL — clients get a short-lived presigned link to OUR copy.

A third is present but never raw: `summary` is transcript-DERIVED prose, so the service
puts it through the same `redact()` pass as `text_redacted` before it is serialized
(`crm.service.redacted_summary`). A field name here is not evidence of what the value
holds, which is why the redaction guardrail names `CallSummaryOut.summary` explicitly
and `tests/call_summary_redaction_test.py` is what proves the claim.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LeadStatus = Literal["new", "contacted", "interested", "hot", "won", "lost"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptTurnOut(Strict):
    idx: int
    speaker: Literal["agent", "caller"]
    # Redacted by default. The raw view is a separate, role-checked, audited endpoint.
    text: str
    lang: str | None = None
    start_ms: int | None = None
    redacted: bool = True


class CallSummaryOut(Strict):
    id: UUID
    agent_id: UUID
    agent_name: str | None = None
    direction: Literal["inbound", "outbound"]
    status: str
    # The other party's number IN FULL — `from_e164` inbound, `to_e164` outbound. A
    # calls list whose numbers are dots cannot be worked: the whole action available
    # from this screen is ringing back the person who called (D-436, founder). NULL only
    # when the engine gave us no number for the leg, never as a redaction.
    caller_e164: str | None = None
    started_at: datetime | None = None
    duration_s: int | None = None
    outcome_tag: str | None = None
    sentiment: str | None = None
    # REDACTED prose, not the stored column: the summary is derived from the transcript
    # (the offline extractor's is a transcript line verbatim), so it ships through the
    # same pass as `text_redacted`. Raw only from the audited raw-transcript route.
    summary: str | None = None
    lead_id: UUID | None = None


class CallMomentOut(Strict):
    """One jump-to point in a call's recording.

    `label` follows the SAME redaction switch as the transcript on the model it hangs
    off: `get_call(raw=False)` fills it from the redacted text and `raw=True` from the
    raw, so a marker can never be the one field on this screen that leaks (hard rule 5).
    There is no second `label_raw` on the wire — one field whose contents depend on the
    endpoint you called is the shape the transcript already established, and a second
    field would be a second thing to forget to gate.

    `source` is what a reader needs to know how much to trust `at_ms`. A `derived` marker
    was computed from the transcript's own turn offsets and cannot be at the wrong second;
    a `model` one is a suggestion from an unmeasured model (D-36) and the screen says so.
    """

    at_ms: int
    kind: Literal["field_captured", "opt_out", "highlight"]
    label: str
    source: Literal["derived", "model"]


class CallDetailOut(CallSummaryOut):
    transcript: list[TranscriptTurnOut] = Field(default_factory=list)
    #: REQUIRED, with no default, and that is deliberate rather than an oversight.
    #:
    #: A `default_factory` does not emit a schema `default`, so the property generates as
    #: OPTIONAL TypeScript — the optional-on-the-wire trap this repo has now been bitten
    #: by five times, and the reason `transcript` above is `transcript?:` in the client
    #: while the server has never once omitted it. Declaring it required makes the
    #: generated type say the true thing and deletes a branch the screen would otherwise
    #: carry for a case that cannot happen. `duration_s` on `RecordingLinkOut` and the
    #: whole of `TierSplitOut` were written the same way today; `transcript` is the older
    #: shape and moving it is a wider change than this one.
    #:
    #: Empty covers BOTH "the call had none" and "nobody has looked yet" — the screen
    #: hides the panel either way, and the distinction that matters to an operator is
    #: NULL-versus-`[]` in the column, which is not a client's question.
    moments: list[CallMomentOut]
    extraction: dict[str, Any] = Field(default_factory=dict)
    extraction_valid: bool = True
    has_recording: bool = False
    disclosure_played: bool | None = None


class RecordingLinkOut(Strict):
    """A short-lived link to OUR copy of a call's audio, and what the player needs to
    render before a single byte of it has arrived.

    `duration_s` is the CALL's metered length, which is what the seek bar is drawn from
    on first paint — `<audio>` reports `duration` as `NaN` until enough of the file has
    been fetched to know, and a scrubber that appears a second after the play button is
    a scrubber people click through. It is nullable because a call the poller never
    resolved has no metered length, and inventing one would put a wrong end on the bar.

    `expires_in_s` is DERIVED from that duration (`recording_link_ttl_s`), not a
    constant: a link shorter than its own audio expires mid-playback and the browser
    reports it as an unexplained network error.
    """

    url: str
    expires_in_s: int
    duration_s: int | None


class LeadOut(Strict):
    id: UUID
    #: E.164, in full. This is the client's OWN captured lead — the one field that makes
    #: the row actionable — and it is behind `leads:read` like every other field on this
    #: model. Hard rule 6 is about LOG LINES and is unaffected: nothing here reaches a
    #: log, a trace or an alarm payload.
    phone_e164: str
    name: str | None = None
    status: LeadStatus
    source: str
    data: dict[str, Any] = Field(default_factory=dict)
    schema_version: int | None = None
    call_count: int
    is_repeat_caller: bool
    last_call_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    # WHO OWNS THIS LEAD (ROADMAP M3). The id is what the assignee control writes back,
    # the name is what a person reads — and the two are separate fields rather than one
    # resolved string because a name is not an identity: two colleagues called Ravi are
    # not a bug the picker has to solve.
    assigned_to: UUID | None = None
    # NULL for an unassigned lead AND for an assignee this tenant can no longer name —
    # a member who was removed, or (impossibly, but the query does not assume it) a user
    # from another tenant. The resolution goes through `memberships`, which is RLS'd, so
    # a foreign id resolves to nothing rather than to a stranger's name. The screen says
    # "someone who has left" for the second case and never invents a name for it.
    assigned_to_name: str | None = None


class LeadColumnOut(Strict):
    """One selectable column of the Leads table — `crm.columns.LeadColumn` on the wire.

    `kind` is what lets the screen render a column without knowing its name: `fixed`
    columns come off `LeadOut`'s own attributes (the `phone` column is `phone_e164`
    there, the same full number the export writes), `extraction` columns come out of
    `LeadOut.data` under `key`.
    """

    key: str
    label: str
    kind: Literal["fixed", "extraction"]
    type: Literal["text", "number", "bool", "enum", "date"]


class LeadFacetValueOut(Strict):
    value: str
    #: Rows this value would give you, over every OTHER filter currently applied — the
    #: standard faceted-search count, and the same scope rule as
    #: `status_counts_matching_search` one field down.
    count: int
    #: `False` = a value the client's DATA holds that their capture list no longer
    #: declares. Offered anyway (a value that exists and cannot be filtered on is a table
    #: that lies), flagged so the UI can say which it is.
    declared: bool


class LeadFacetOut(Strict):
    key: str
    label: str
    values: list[LeadFacetValueOut]


class LeadFacetsOut(Strict):
    """The filter rail, built from the per-agent EXTRACTION SCHEMA (SURFACES §2).

    Enum fields only, and never a hard-coded list: different tenants and different
    verticals have different columns, so a fixed facet set would be wrong the day a
    second vertical lands. `crm.columns.facetable` is the definition, including why
    `status` and `source` are deliberately not here.
    """

    facets: list[LeadFacetOut]
    #: Enum fields beyond the rail's cap (`crm.service.MAX_FACET_FIELDS`). Reported
    #: rather than hidden — a missing ninth facet should be a sentence, not a mystery.
    omitted_field_count: int


class LeadLensIn(Strict):
    """The Leads table's lens — WHICH ROWS and WHICH COLUMNS — carried in a request BODY.

    It exists because of the one field in it that is personal data. `search` is matched
    against `leads.phone_e164` with a suffix LIKE (`crm.service._lead_scope`), so on a
    GET it is a customer's phone number written into nginx's `combined` access log
    (`$request` is the whole request line), into Cloudflare's edge log, into browser
    history and into the `Referer` of the next navigation. This repository already made
    that judgement twice — `POST /v1/dnc/check` is a POST because "the identifier IS the
    personal data", and SEC-COMP §4 requires a number in the body and never in a URL —
    and the leads screen is the busiest surface in the product to have been left out of
    it (hard rule 6).

    The field NAMES match the query parameters the GET routes take, including the two
    encoded ones (`columns` as a comma-separated string, `f` as `key:value` entries), so
    one parser serves both shapes and the client's lens object does not change form when
    it moves into a body.
    """

    status: str | None = None
    #: The one field that made this a body. Same 60-character bound the GET had.
    search: str | None = Field(None, max_length=60)
    agent_id: UUID | None = None
    assigned_to: UUID | None = None
    #: Comma-separated column keys, in display order. Omit for every column.
    columns: str | None = None
    #: Facet filters as `key:value`, repeated. An unknown key is REFUSED, never dropped —
    #: dropping one would widen the set, which on the export is a mailed contact list.
    f: list[str] = Field(default_factory=list)


class LeadSearchIn(LeadLensIn):
    """The lens plus the page. Export takes no page: it is the whole filtered set."""

    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class LeadListOut(Strict):
    """The Leads table is schema-driven (TRD §7): the columns travel WITH the rows so
    the frontend never hard-codes a client's fields."""

    items: list[LeadOut]
    #: The columns to RENDER, in order — the chooser's resolved answer, and byte-for-byte
    #: the same list `GET /v1/leads/export.csv` writes its header from for the same
    #: query string. It used to be the raw extraction schema while the screen hard-coded
    #: the fixed columns around it and the export hard-coded a different set; those two
    #: lists are now one registry (`crm.columns`).
    columns: list[LeadColumnOut]
    #: Everything the chooser may offer for this agent. `columns` is a subset of it.
    available_columns: list[LeadColumnOut]
    #: Column keys the request ASKED for that this agent's schema no longer has. The
    #: request still succeeds — a stale bookmark or a saved view outliving one schema
    #: edit must degrade to a narrower table, never to a 500 (`crm.columns` cites what
    #: the industry does instead). A dropped FILTER is refused rather than dropped,
    #: because that one widens the set; `crm.routes.get_leads` argues the asymmetry.
    dropped_column_keys: list[str]
    # Rows matching EVERY filter the request sent, `status` included — the denominator
    # in "showing 50 of 140".
    total: int
    limit: int
    offset: int
    # status → count for all six statuses, over the SAME search, agent and ASSIGNEE
    # scope as the page, but NOT narrowed by `status`. (The name predates the assignee
    # filter and is kept — a shipped field name is a contract, and it was already
    # imprecise about `agent_id`; `crm.service._lead_scope` is the definition.) Under a
    # "my leads" chip these are therefore MY leads by stage, which is the only reading
    # that answers the question the screen is asking. The name carries the scope on purpose: the
    # screen renders this as a badge row, and the two wrong readings of an unlabelled
    # `status_counts` are both damaging. Narrowed by status it would be one real number
    # and five zeroes — which is exactly the bug this replaces, where filtering to `hot`
    # told a client "new 0, contacted 0". Widened to the whole account it would be a
    # different population from the rows above it, and would cost a second unfiltered
    # scan on every keystroke of the debounced search.
    #
    # Always all six keys: a status with no leads answers 0 rather than going missing,
    # so the UI never has to tell "none of these" apart from "the server did not say".
    status_counts_matching_search: dict[str, int]


class LeadUpdateIn(Strict):
    # Statuses are a FIXED enum (D-21): analytics and hot-lead rules key off them, so
    # clients cannot add their own.
    status: LeadStatus | None = None
    name: str | None = Field(default=None, max_length=120)
    # THE OWNER, and the one field here where `null` is a value rather than a silence.
    #
    # A PATCH body that omits `assigned_to` means "leave the owner alone"; a body that
    # sends `"assigned_to": null` means "this lead has no owner", which is a real event
    # — the person who owned it left, or handed it back. Pydantic v2 tells the two apart
    # through `model_fields_set`, which holds exactly the fields the request supplied and
    # not the ones that took their default (pydantic.dev/docs/validation/latest/concepts/
    # models — "fields_set"); `crm.routes.patch_lead` reads it. Every other field here is
    # non-nullable in the domain, so `None` can keep meaning "unchanged" for them.
    #
    # A dedicated `PUT /v1/leads/{id}/assignee` was the alternative, and it would have
    # made the null unambiguous without the sentinel. Rejected because it would put TWO
    # routes on "edit this lead" — the status select and the assignee select sit in the
    # same table row, are the same permission, and would otherwise be two mutations, two
    # cache invalidations and two places for the next field to be added wrongly.
    assigned_to: UUID | None = None


# --- bulk actions (SURFACES §2) ------------------------------------------------
#
# The wire half of `crm.service`'s bulk block, which carries the research this shape
# comes from. Two things are worth having in the SCHEMA rather than only in the service:
# the two selection scopes are named in the request AND echoed in the response, and the
# outcome has three buckets rather than two.

#: How many leads one bulk action may move. Declared HERE, and imported by the service,
#: because `service` already imports `schemas` and the reverse would be a cycle — and
#: because the number is part of the contract: it bounds `ids` at the wire and is the
#: figure `lead_bulk_too_many` quotes back. Two constants would eventually be two numbers.
#:
#: The value is set by the status path being one `transition_status` call per lead —
#: deliberately, so bulk and single-lead share ONE discriminator rather than a set-based
#: copy of it — and by 500 rows being the point past which the honest answer to a person
#: operating a grid is a narrower filter. The refusal says exactly that.
MAX_BULK_LEADS = 500


class LeadBulkIn(Strict):
    """One bulk action, and the two ways of saying which leads it is about.

    **`scope` is required and has no default**, which is the whole guardrail. A default
    would decide the ambiguous case — page or query — on the caller's behalf, and that
    ambiguity is the defect this field exists to remove; a client that forgets to say
    gets a 422 rather than an action over a set it did not choose.

    The FILTER scope's predicates ride as the same query parameters `GET /v1/leads` and
    `GET /v1/leads/export.csv` take, with the same meanings, so there is one spelling of
    "which rows" across the screen, the file and this — EXCEPT `search`, which is here in
    the body because it matches a phone number and a query string is written to access
    logs, history and referrers (`LeadLensIn` carries the full argument). The lens's
    other members are not personal data and stay where they were.
    """

    scope: Literal["ids", "filter"]
    #: The filter scope's search term. Same 60-character bound the query parameter had.
    search: str | None = Field(None, max_length=60)
    #: The ticked rows, for `scope: "ids"`. Bounded by the same cap the filter scope is
    #: refused at, so neither route into the action can exceed it.
    ids: list[UUID] = Field(default_factory=list, max_length=MAX_BULK_LEADS)
    action: Literal["status", "assign"]
    status: LeadStatus | None = None
    #: The new owner, `null` to unassign. Named `assign_to` and not `assigned_to` on
    #: purpose: `assigned_to` is already a QUERY parameter on this route meaning "leads
    #: owned by this person" (the filter), and one word carrying both "which rows" and
    #: "what to write" is a mistake waiting for its first reviewer.
    assign_to: UUID | None = None
    #: What the screen told the person it was about to change, for `scope: "filter"`.
    #: A filter-scoped batch is confirmed against a count that can move while the dialog
    #: is open — a call lands, a colleague edits a row — and the researched rule is that
    #: the confirmation must describe the set that will actually be acted on. When this
    #: is sent and no longer matches, the action is refused rather than run over a
    #: different set than the one that was agreed to. Omitted = no such claim was made.
    expected_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _coherent(self) -> LeadBulkIn:
        if self.scope == "ids" and not self.ids:
            raise ValueError("scope 'ids' needs at least one lead id")
        if self.scope == "filter" and self.ids:
            raise ValueError("scope 'filter' takes its rows from the filter, not from ids")
        if self.action == "status" and self.status is None:
            raise ValueError("action 'status' needs a status")
        if self.action == "assign" and "assign_to" not in self.model_fields_set:
            # An ABSENT `assign_to` is not an unassignment — the same distinction
            # `LeadUpdateIn.assigned_to` makes, and the one a bulk action can least
            # afford to get wrong: it would clear the owner of every lead in the batch.
            raise ValueError("action 'assign' needs assign_to (send null to unassign)")
        return self


class LeadBulkFailureOut(Strict):
    """One lead the action did not move, named and explained.

    `(rule, reason)` is this API's established pair for a refusal — `BlockerOut`,
    `CallLeadOut.blocked_rule`/`blocked_reason`, `DispatchDecision` — so a client that
    already renders one of those renders this. `lead_id` and nothing else identifies the
    row: the response must be safe to log and to put in an audit summary (hard rule 6).
    """

    lead_id: UUID
    rule: str
    reason: str


class LeadBulkOut(Strict):
    """What the action DID — the three buckets, and which set it ran over.

    `scope` and `action` are echoed so the sentence on screen ("Moved 47 of the 1,240
    leads matching these filters") is built from the server's answer rather than from
    what the screen believed it had asked for.

    `changed + unchanged + len(failures) == requested`, always. `unchanged` is a success:
    a lead already in the target state is the caller's intent already satisfied (D-65,
    `db/transition.py`), and reporting it as a failure would make the most ordinary bulk
    outcome — re-running an action over a set that partly overlaps the last one — look
    like an incident.
    """

    action: Literal["status", "assign"]
    scope: Literal["ids", "filter"]
    requested: int
    changed: int
    unchanged: int
    #: Empty on a clean run. NEVER omitted and never summarised into a count alone: the
    #: client has to be able to see which rows were left behind, which is the difference
    #: between a partial success and a green tick over one.
    failures: list[LeadBulkFailureOut] = Field(default_factory=list)


# --- saved views (SURFACES §2: "named filter+column combinations per user") ----

#: How many views one person may keep on one account. A named lens is a small thing and
#: fifty of them is already a list nobody scans; the cap exists so an automated client
#: cannot make an unbounded table out of per-user UI state.
MAX_SAVED_VIEWS_PER_USER = 50

#: Facet keys one view may pin, and values per key. Both bound the WHERE clause a single
#: saved view can generate — `crm.service._lead_scope` emits one `= ANY` per key.
MAX_VIEW_FILTER_KEYS = 10
MAX_VIEW_FILTER_VALUES = 25


class SavedViewFilters(Strict):
    """What a saved view narrows the table to.

    **`search` is deliberately not a field.** A saved view is a named LENS — a stage, a
    set of facet values, an agent — and the search box is a transient lookup, not a lens.
    Storing one would also put a phone SUFFIX (what the box accepts) into a durable row
    for no product gain, which is a hard-rule-6 surface bought for nothing.

    **`assigned_to_me` is a boolean, not a user id.** Views are private to one user
    (see `SavedViewOut`), so the only owner a view can usefully pin is its own reader —
    and a stored uuid would be a dangling pointer the day that colleague leaves, where a
    boolean is resolved fresh against the caller on every read.
    """

    status: LeadStatus | None = None
    agent_id: UUID | None = None
    assigned_to_me: bool = False
    #: extraction-schema key → the values selected under it. OR within a key, AND across
    #: keys — the researched faceted-search semantic (`crm.service._lead_scope`).
    fields: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("fields")
    @classmethod
    def _bounded(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(v) > MAX_VIEW_FILTER_KEYS:
            raise ValueError(f"a view may filter on at most {MAX_VIEW_FILTER_KEYS} fields")
        for key, values in v.items():
            # The extraction-schema key grammar (`calevate_shared.extraction`). Checked
            # here as well as against the live schema at read time, because this is what
            # lands in the DB and the live check is what a schema edit invalidates.
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key):
                raise ValueError(f"{key!r} is not an extraction field key")
            if not values:
                raise ValueError(f"{key!r} selects no values; drop the key instead")
            if len(values) > MAX_VIEW_FILTER_VALUES:
                raise ValueError(f"{key!r} selects more than {MAX_VIEW_FILTER_VALUES} values")
        return v


class SavedViewIn(Strict):
    name: str = Field(min_length=1, max_length=60)
    filters: SavedViewFilters = Field(default_factory=SavedViewFilters)
    #: Column keys in the order the chooser left them. `null` = "whatever this agent
    #: has", which keeps a view useful when the capture list grows.
    columns: list[str] | None = Field(default=None, max_length=40)


class SavedViewUpdateIn(Strict):
    """Rename, or re-pin. Every field optional; an omitted one is left alone.

    `columns` cannot be cleared back to `null` through this route — sending `null` means
    "leave the columns alone", the same silence every other field here means. Clearing
    is `columns: []`, which `crm.saved_views` stores as "no choice made". Two spellings
    of "unset" on one field is how the assignee sentinel next door earned its comment,
    and this field does not need the ambiguity: an empty selection has no other meaning.
    """

    name: str | None = Field(default=None, min_length=1, max_length=60)
    filters: SavedViewFilters | None = None
    columns: list[str] | None = Field(default=None, max_length=40)


class SavedViewOut(Strict):
    """One saved view, RESOLVED against the agent's current extraction schema.

    **Private to its author.** Shared views are a separate slice with a separate
    question (who may edit a view three colleagues rely on), and the industry default
    for a saved view is private-unless-published — Tableau and SeaTable both create
    private and require an explicit act to share. Private-first is also the only choice
    that cannot leak: this table holds no shared row to get the permission wrong on.

    **`stale_*` is the graceful degradation.** A view pinned to a field an admin later
    removed from the capture list is not an error — the reader gets the view with the
    dead references REMOVED and named here, so the screen can say "this view also
    filtered on Budget, which your capture list no longer has" instead of 500ing or
    silently returning a different set of rows. Jira's answer to the same event is a
    broken filter and an integrity checker; this is cheaper and kinder.
    """

    id: UUID
    name: str
    filters: SavedViewFilters
    columns: list[str] | None
    #: Facet keys this view pinned that the agent's schema no longer declares. Already
    #: removed from `filters` above — reported so the removal is visible, never silent,
    #: because a silently dropped filter WIDENS the set the client is looking at.
    stale_filter_keys: list[str]
    #: Column keys this view pinned that no longer exist. Already removed from `columns`.
    stale_column_keys: list[str]
    created_at: datetime
    updated_at: datetime


class SavedViewListOut(Strict):
    items: list[SavedViewOut]


class LeadTimelineEventOut(Strict):
    """One line of a lead's history, PROJECTED — never `lead_events.payload` itself.

    `lead_events.payload` is JSONB written by six producers in three deployables
    (`crm.service.update_lead`, `ingest.service._timeline`, `workers.pipeline`,
    `workers.notifications`, and two paths in `workers.whatsapp`), with no schema
    between them and the column. Every one of them was read before this model was
    written, and today every one of them stores ids, authored rule/reason codes,
    booleans and counters — no phone number, no transcript text, no extraction payload
    (`crm.service.lead_timeline` records the audit key by key).

    That is a fact about today's writers, not a property of the column, and hard rules 5
    and 6 have to survive the seventh producer. So the read PROJECTS: the service builds
    every field below from a whitelist of keys, and a key nothing here names cannot
    reach a browser however it got into the row. The blob is never serialized, which is
    also why this model needs no `ACKNOWLEDGED_PASSTHROUGH` entry in
    `scripts/check_redaction_exposure.py` — there is no free-form dict to acknowledge.
    """

    id: UUID
    # A STRING, not a `Literal` of the five values `crm.models.LEAD_EVENT_TYPES` allows.
    # The database CHECK is the enum's home, and a build older than the database it is
    # talking to would otherwise 500 on `extra="forbid"` and take a client's whole
    # history off the screen rather than one unfamiliar row. The screen reads this
    # through `lookup` with a visible fallback — the same call the call-detail transcript
    # makes for `speaker`, and for the same reason.
    type: str
    occurred_at: datetime
    # "system" when the platform did it (a call landed, an alert went out), "member"
    # when a person did. The two are told apart HERE rather than by the screen sniffing
    # `actor_name`, because "a colleague we can no longer name" and "the platform" are
    # different sentences and both would otherwise render as an absent name.
    actor_kind: Literal["system", "member"]
    # The member's own name. None for a system event, and None for a member this tenant
    # can no longer name (removed, deactivated, or — see `LeadOut.assigned_to_name` —
    # never theirs to begin with). Resolved through `memberships`, so RLS decides.
    actor_name: str | None = None
    # Client-safe prose, composed by the service from the whitelist. Same doctrine as
    # `AttentionItemOut.title`/`detail`, which already projects rows from this table.
    title: str
    detail: str | None = None
    # The call this line is about, when there is one, so the screen can link to it.
    # OUR id — never the engine's handle, which is a vendor identifier (hard rule 2).
    call_id: UUID | None = None


class LeadTimelineOut(Strict):
    """A page of a lead's history, newest first.

    `total` is the size of the SET, counted with `count(*) OVER ()` in the same pass as
    the rows — never `len(items)`, which is the size of the page (BUILD-LOG §52, and
    `AttentionOut` makes the identical distinction in the identical words).
    """

    items: list[LeadTimelineEventOut]
    total: int
    limit: int
    offset: int


class CallLeadIn(Strict):
    """D-21: an owner may dispatch a single AI call from the Leads table, with an
    optional per-call note rendered into the agent's prompt."""

    agent_id: UUID
    context_note: str | None = Field(default=None, max_length=500)


class CallLeadOut(Strict):
    status: Literal["queued", "blocked"]
    call_handle: str | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None


class CallbackOut(Strict):
    """D-21 M2. `eligible` is a first-class answer, not an error: the call detail
    screen renders the button disabled with `blocked_reason` rather than hiding it,
    which is what SURFACES §2b asks of every gated action."""

    status: Literal["queued", "blocked"]
    call_handle: str | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None
    follow_up_number: int | None = None


class CallbackEligibilityOut(Strict):
    eligible: bool
    reason: str | None = None
    rule: str | None = None
    follow_up_number: int | None = None


class CallAssistOut(Strict):
    """One user-triggered re-summarise of a call (D-127 G-2/G-5/G-6).

    **EVERY FIELD IS REQUIRED — none carries a Pydantic default.** A default here
    generates an OPTIONAL property in the client this repo generates from OpenAPI, and
    all three of these are facts the screen has to state rather than shapes it may skip:
    an absent `disclosure` would render a Sarvam answer as the assistant's own (the one
    outcome G-6 rules out), and an absent `metered` would render "this cost you nothing"
    as the default for an assist that cost the allowance.

    Nothing here is persisted. The stored `calls.summary` is the FIRST pass, over the raw
    transcript; this is a second reading over the redacted copy, held for as long as the
    person is looking at it (`crm/assist.py` argues why overwriting one with the other
    would degrade the lead and rewrite history).
    """

    #: Transcript-DERIVED prose, and therefore treated exactly like `calls.summary`: it
    #: goes out through `crm.service.redacted_summary`, the same `redact()` pass that
    #: produced the `text_redacted` the model was given. Belt and braces — the model
    #: never saw an unredacted digit to copy — and the reason the redaction guardrail's
    #: entry for this field can say the same sentence as `CallDetailOut.summary`'s.
    #:
    #: MAY BE EMPTY, and the screen states that rather than rendering blankness: an
    #: assist that returned nothing is an outcome the client paid for and §52 does not
    #: let an empty state stand in for it.
    summary: str
    #: G-6. Non-null EXACTLY when something other than the assistant model answered, and
    #: the sentence is the one `AssistCapability.disclosure` composes — written once, so
    #: two surfaces cannot say different things about the same substitution.
    disclosure: str | None
    #: Did this reach `usage_events`? The screen says "this did not use any of your
    #: allowance" only when this is False, because saying it when it is True would be a
    #: claim about a client's money that is not true. `crm/assist.py::meter_assist` has
    #: exactly three ways to answer False, and only the first is routine:
    #:
    #: - a disclosed Sarvam fallback, which D-36 prices at zero;
    #: - an Azure answer that carried no `usage` block (D-410) — nothing is estimated,
    #:   and `ai_assist_unmeterable` pages because that spend is invisible to both the
    #:   tenant ceiling and the platform brake;
    #: - a RETRY of an attempt already metered under the same server-minted `ref`
    #:   (`billing/ai_quota.AssistMetered.recorded`), which is one assist charged once
    #:   rather than a free one.
    metered: bool


class DashboardDayOut(Strict):
    """One IST calendar day of the dashboard's 7-day call chart.

    **The four class counts PARTITION `calls.status`** — every value the CHECK
    constraint allows (`crm.models.CALL_STATUSES`) belongs to exactly one of them, so
    `completed + no_answer + failed + in_flight == total` on every bucket and an owner
    can check the arithmetic against the bar they are looking at.
    `tests/dashboard_daily_test.py` pins both halves of that claim: the partition
    against the constraint's own tuple, and the sum against real rows.

    The grouping is the one the product already uses. `CALL_STATUS_STYLES` in
    apps/web/src/components/ui.tsx already paints these exact sets in these exact
    colours, so a bar and a status badge on the same screen never disagree about what a
    call was:

    - `completed` (green) — the one status that means a conversation happened.
    - `no_answer` (amber) — `no_answer`, `busy`, `voicemail`. Three ways a dial reaches
      the network and not a person. Deliberately NOT folded into `failed`: nothing
      malfunctioned, and the owner's next move ("ring them back") is a different move
      from the one a failure calls for.
    - `failed` (red) — the dial itself broke. Ours to fix, not the callee's.
    - `in_flight` — `queued`, `ringing`, `in_progress`. Not an outcome YET, and a
      FOURTH field rather than a silent omission: today's bar always carries some, and
      a reader seeing three bands add to less than `total` cannot tell a live call from
      a dropped row. The chart draws three bands and may show this one as the gap.

    No status is dropped. A ninth one added to `CALL_STATUSES` without a class here
    fails the partition test rather than quietly unbalancing every bucket.
    """

    # The IST calendar day — not UTC, and not the browser's zone. Serialized `YYYY-MM-DD`
    # and meant to be rendered verbatim: re-parsing it as an instant in a client-side
    # timezone is how "Tuesday" becomes "Monday" for a reader in London.
    ist_date: date
    # Calls that STARTED on this day. A row with a NULL `started_at` was never dialled,
    # so it has no calendar day and appears in no bucket.
    total: int
    completed: int
    no_answer: int
    failed: int
    in_flight: int


class DashboardOut(Strict):
    calls_today: int
    calls_7d: int
    leads_new_7d: int
    hot_leads_open: int
    # THE WINDOW IS IN THE NAME, like every other bounded number on this model (D-215).
    #
    # This shipped as `avg_duration_s` and was the only tile here with no time bound at
    # all — the mean of every completed call the account has ever made, on a polled
    # endpoint, over a table nothing deletes from. It was the one field whose name did
    # not say its window because it did not have one.
    #
    # Renamed rather than quietly re-scoped: the number a client reads changes, and a
    # field that keeps its name while changing its meaning is the version of this fix
    # that costs somebody a support call. `PerformanceOut.avg_duration_s` keeps ITS name
    # because its window is a field on the same response (`days`), which is the other
    # honest way to say it.
    #
    # None, never 0, when no completed call fell inside the window: "no calls to measure"
    # and "the calls averaged nothing" are different facts, the same rule
    # `PerformanceOut.connect_rate_pct` follows.
    avg_duration_s_7d: int | None = None
    sentiment_split: dict[str, int] = Field(default_factory=dict)
    outcome_split: dict[str, int] = Field(default_factory=dict)
    after_hours_captured_7d: int = 0
    # WHICH definition of "after hours" produced the number above. `business_hours` =
    # this client's own recorded opening times; `default_window` = the 09:00-21:00 IST
    # fallback used while no agent has any hours recorded.
    #
    # It is a field rather than a comment because the two are not the same claim. The
    # fallback is a guess that is wrong in both directions — it undercounts the
    # late-night clinic and overcounts the salon that closes on Sundays — and a tile
    # that renders "14 captured after hours" identically from a guess and from a fact
    # invites a client to trust a number we did not earn. The UI can now say which one
    # it is holding, and prompt for the intake that turns the guess into the fact.
    after_hours_basis: Literal["business_hours", "default_window"] = "default_window"
    # Client-facing spend is INR NUMERIC, never a float (hard rule 7).
    #
    # NOT nullable, and no default. It was `Decimal | None = None` while the dashboard
    # read `spend_state` directly and a tenant with no row that month produced nothing
    # to send. `read_spend_counters` closed that: an absent OR month-stale row answers
    # `NO_SPEND_THIS_MONTH` — a real, correct zero — so the null arm became a state the
    # server can no longer be in, and a nullable field the server never nulls is a
    # branch every consumer must write and no test can ever reach. Zero minutes and
    # "we could not say" are different facts; this field now only ever carries the
    # first, and the second would have to be modelled deliberately if it returns.
    minutes_used_month: Decimal
    # The stacked bar chart: the last 7 IST calendar days, OLDEST FIRST, ending today.
    #
    # ALWAYS exactly 7 entries. A day with no calls answers zero rather than going
    # missing — the same rule `PerformanceOut.busiest_hours_ist` follows with its 24
    # hours, and for the same reason: a chart that omits its silent buckets reads as
    # data loss, and the UI must never have to tell "no calls that day" apart from "the
    # server did not say". The zero-fill is the server's job, not the chart's, because
    # only the server knows which seven days it meant.
    #
    # No default: `dashboard()` always emits all seven, so an empty list is a bug that
    # should surface loudly here rather than render as a week of flat bars.
    #
    # These bars do NOT sum to `calls_7d`, and that is not a defect in either. `calls_7d`
    # is a rolling 168 hours back from this instant; this is seven IST calendar days
    # ending tonight, so it holds today's part-day and reaches further back than the
    # rolling window on every day but one. Two different questions — "how busy has the
    # last week been" and "what did each day look like" — and a chart that had to agree
    # with a headline number would have to lie about one of them.
    daily_7d: list[DashboardDayOut]


# --- panels that used to answer `dict[str, Any]` --------------------------------
#
# These three returned an untyped dict, which meant OpenAPI advertised
# `additionalProperties: true` with no properties at all. Two things followed, and the
# second is the one that mattered: the frontend hand-wrote its own interfaces (free to
# drift), and `scripts/check_redaction_exposure.py` — which reads response MODELS — had
# nothing to read, so a field that later carried a raw phone or a transcript line would
# have shipped past the guardrail green. Every field below is declared, so it is now
# inspectable; none is a free-form dict, so none needs an ACKNOWLEDGED_PASSTHROUGH entry.
#
# No field carries a default: the services always emit every key, so a missing one is a
# bug that should surface as a loud 500 rather than a silently invented value.


class PerformanceFunnelOut(Strict):
    """Calls → connected conversations → LEADS that moved past `new` (crm/performance.py
    states each definition; `qualified` is lead-level on purpose)."""

    calls: int
    connected: int
    qualified: int


class PerformanceOut(Strict):
    days: int
    funnel: PerformanceFunnelOut
    # None, never 0, when the denominator is zero: "0% connected" and "no calls yet"
    # are different facts and the screen must keep them apart.
    connect_rate_pct: int | None
    qualify_rate_pct: int | None
    inbound: int
    outbound: int
    avg_duration_s: int | None
    # Outcome tag, or the bare status when a call was never tagged → count. Typed
    # VALUES, so this is a map and not the free-form passthrough the redaction
    # guardrail has to be told about.
    outcomes: dict[str, int]
    # Always exactly 24 buckets, index = IST hour; silent hours are 0, not absent.
    busiest_hours_ist: list[int]


AttentionKind = Literal["lead_blocked", "delivery_failed", "campaign_stalled", "kb_rejected"]


class AttentionItemOut(Strict):
    """One thing the platform refused to do quietly (crm/attention.py).

    `title` and `detail` are already client-safe prose composed by us — never a vendor
    string and never transcript text. A blocked lead is named by its captured lead NAME,
    falling back to its number in full, because "ring this person" is the action the row
    exists to prompt (D-436).
    """

    kind: AttentionKind
    id: str
    title: str
    detail: str
    # The machine name of the rule that fired ("dnc"), or the campaign status for a
    # stalled campaign. None for the sources that have no rule (deliveries, knowledge).
    rule: str | None
    occurred_at: datetime
    # Realm-relative link to the screen where the fix lives, e.g. "/leads".
    href: str | None


class AttentionOut(Strict):
    """The queue, and the two numbers that say what it is a page OF.

    `counts` and `total` are counted SEPARATELY from the rows (crm/attention.py argues
    it, and `LeadListOut.status_counts_matching_search` above is the same decision on the
    leads table). They are the size of the set, never the size of the page: `items` is
    capped at the request's `limit` and these are not, so `total > len(items)` is the
    normal state of a busy account and the screen says so in words. The bug this
    replaces capped each of the four sources at 25 and then counted what came back, so a
    client with 40 blocked leads read 25 — on the badge, in the nav bell, and in the "of
    M" the shortfall sentence divides by.
    """

    # Everything the four sources match, inside the queue's 14-day window. The nav bell
    # renders this, so it is the number an owner sees most often.
    total: int
    # kind → count, for the summary chips. Only the kinds present appear: absent means
    # genuinely zero, which is what lets the screen skip a chip rather than draw "0".
    counts: dict[str, int]
    # The newest `limit` across all four sources. Truly the newest: each source is
    # fetched to the merged limit, so nothing older is shown above something newer.
    items: list[AttentionItemOut]


class UsagePanelOut(Strict):
    """GET /v1/usage — this month's usage and what it costs (SURFACES §2b).

    **Every money field is a STRING.** The values are `Decimal` all the way through
    billing (hard rule 7) and the route stringifies them at the boundary, because a
    JSON float cannot hold a rupee amount exactly. They must stay strings to the
    screen; `Number()` on INR is how ₹10,159.00 becomes ₹10,158.999999999998.

    Our supplier cost (`unit_cost_paid`) is deliberately absent — that is the admin
    margin panel, and a client who can see it is a client negotiating against it.
    """

    month: str
    minutes_used: str
    calls: int
    included_minutes: int
    overage_minutes: str
    # The two TTS rungs the overage was split across (D-36's ladder, `billing/rates.py`).
    # They add to `overage_minutes` exactly, so an owner can check the arithmetic.
    overage_minutes_premium: str
    overage_minutes_value: str
    overage_cost_inr: str
    # The rate the overage was actually priced at, published so the invoice does not
    # re-read `plans` and risk quoting a different row.
    overage_rate_inr: str
    # The value rung's rate, or None when this plan quotes no separate one — in which
    # case BOTH rungs above were priced at `overage_rate_inr`. None rather than a repeat
    # of the premium rate, because "one rate" and "two rates that happen to be equal"
    # are different plans and the screen says different things about them.
    overage_rate_value_inr: str | None
    # THE LANGUAGE-MODEL SURCHARGE (D-455) — what this month's calling cost EXTRA because
    # the client chose a dearer AI model, and at what rate. Three figures that check
    # against each other by hand: `llm_surcharge_inr` is `llm_surcharge_minutes` x
    # `llm_surcharge_rate_inr`, and the minutes are a part of `minutes_used`.
    #
    # The rate is None exactly when the plan quotes no surcharge — in which case the total
    # is ₹0.00 because there is nothing to charge, not because nothing was upgraded. It is
    # published as a RATE (unrounded, `rate_to_display`) for the reason `overage_rate_inr`
    # is: the invoice re-prices from it and the line has to multiply out.
    llm_surcharge_rate_inr: str | None
    llm_surcharge_minutes: str
    llm_surcharge_inr: str
    # WHICH models the client chose, so the screen can name the cause of the number rather
    # than only its size. Empty when nothing this month carried a surcharge.
    llm_surcharge_models: list[str]
    # None until the client has a plan row with a fee (mid-onboarding is a real state).
    monthly_fee_inr: str | None
    cap_minutes: int | None
    minutes_left: int | None
    capped: bool
    spend_used_inr: str
    plan_tier: str
    # Credits only mean something for the self-serve motion (D-34); None for a managed
    # client, whose ₹0 wallet would otherwise invite a support ticket.
    credit_balance_inr: str | None


__all__ = [
    "MAX_SAVED_VIEWS_PER_USER",
    "MAX_VIEW_FILTER_KEYS",
    "MAX_VIEW_FILTER_VALUES",
    "AttentionItemOut",
    "AttentionKind",
    "AttentionOut",
    "CallDetailOut",
    "CallLeadIn",
    "CallLeadOut",
    "CallSummaryOut",
    "CallbackEligibilityOut",
    "CallbackOut",
    "DashboardDayOut",
    "DashboardOut",
    "LeadColumnOut",
    "LeadFacetOut",
    "LeadFacetValueOut",
    "LeadFacetsOut",
    "LeadListOut",
    "LeadOut",
    "LeadStatus",
    "LeadTimelineEventOut",
    "LeadTimelineOut",
    "LeadUpdateIn",
    "PerformanceFunnelOut",
    "PerformanceOut",
    "RecordingLinkOut",
    "SavedViewFilters",
    "SavedViewIn",
    "SavedViewListOut",
    "SavedViewOut",
    "SavedViewUpdateIn",
    "TranscriptTurnOut",
    "UsagePanelOut",
]
