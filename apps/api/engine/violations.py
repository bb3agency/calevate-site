"""The engine's COMPLIANCE FLAGS against our account — a surface this tree had never heard of.

WHAT THIS IS. Bolna publishes `GET /violations/list` and `POST /violations/submit`:
*"Manage and track call violations using the Bolna Violations APIs. List violations with
filtering and pagination, and submit violation evidence."*
(`bolna-findings/mirror/pages/api-reference/violations/overview.md`). Their MCP tool list
says what fills it: *"Flagged call violations — content policy, regulatory, or fraud"*
(`bolna-findings/mirror/pages/build-with-ai/mcp-tool-list.md`), and their skill catalogue
calls the pair *"List compliance flags and submit evidence files for review"*
(`build-with-ai/skills-reference.md`).

**WHY IT IS A POLLER AND NOT A FEATURE.** A violation is raised BY THE VENDOR, against
the account we place every regulated Indian call through, and nothing pushes it to us:
there is no webhook for it, and Bolna signs nothing anyway (TRD §5). So the entire
notification channel is a list endpoint somebody has to read. Unread, the first thing we
would learn is enforcement — on an account that carries every client's calling.

**WHAT THE DOCUMENTATION DOES NOT SAY, stated here so nobody infers it later.** Three
things are absent from all three pages, and each is a question for the vendor rather than
a value to guess (OPERATIONS §2 gate 9v):

* **what raises one.** "Content policy, regulatory, or fraud" is a taxonomy, not a
  trigger. Whether a violation follows a recipient complaint, a carrier report, an
  automated transcript scan or a manual review is unstated.
* **the clock.** `POST /violations/submit` "updates the violation status and attaches the
  uploaded file" — with no deadline anywhere for doing so. `created_at` and `updated_at`
  are on the record, which is what a deadline would be measured from, so this module
  reports the AGE of the oldest open flag and lets a human judge it.
* **the consequence of ignoring one**, including whether it can suspend calling. Their
  FAQ documents a neighbouring enforcement — *"Agent is restricted due to disallowed
  content"* (`frequently-asked-questions.md`) — which is at least proof that this vendor
  does restrict accounts over compliance findings.

**THE FOUR STATUSES ARE NOT A LIFECYCLE WE MAY INFER.** The enum is
`pending`/`accepted`/`rejected`/`submitted` and the pages never define the members.
`accepted` could mean the flag was upheld against us or that our evidence was accepted —
opposite meanings, same word — so this module interprets exactly ONE of them, the one
that is unambiguous: `pending` is a flag nothing has been submitted against. Everything
else is counted and reported without a verdict.

WHAT WE DELIBERATELY DO NOT BUILD
----------------------------------
`POST /violations/submit` has no client here and must not get one. Its required argument
is `violation_file` — *"The evidence file to attach to the violation (e.g., a screenshot
or document)"* — and a machine cannot produce evidence. An automated submitter would file
something against a compliance finding to make a queue go green, which is the failure mode
this whole surface exists to catch. The operator submits, from the vendor console, with
the runbook in front of them (`runbooks/engine-violations.md`).

HARD RULE 6 IS THE REASON THIS MODULE HAS A NORMALIZER AT ALL
--------------------------------------------------------------
Their `Violation` schema carries `from_phone_number` and `to_phone_number` in E.164, an
`email`, and an `image_url`. **The example evidence path is
`…/violations/ce23f363-…/9845866566.png` beside `to_phone_number: '+919845866566'` —
the filename IS the recipient's number** (`api-reference/violations/list.md`). So the URL
is not a neutral handle: logging it, storing it or putting it in an alert detail would put
a phone number in a log line, which hard rule 6 forbids and which no reviewer would spot
because it looks like a path.

`EngineViolation` therefore carries `has_evidence: bool` and no URL, and carries no phone
number and no email at all. `_DISCARDED_FIELDS` names every key dropped at this boundary
so `tests/engine_violations_test.py` can assert, field by field, that none of their values
survives into our record. Dropping at the ADAPTER edge rather than at the log call is the
only version that stays true: a downstream caller cannot leak a field it was never given.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from calevate_shared.engine import ListingIncompleteReason

from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: How the vendor spells its own statuses (`api-reference/violations/list.md`, the `status`
#: enum on both the query parameter and the `Violation` schema). Not iterated at runtime —
#: it exists so a test can prove `OPEN_STATUS` is one of them and so an unrecognised value
#: is reported as unrecognised rather than silently counted as safe.
VENDOR_STATUSES: frozenset[str] = frozenset({"pending", "accepted", "rejected", "submitted"})

#: THE one status this module interprets, and the only one whose meaning is not ambiguous:
#: nothing has been submitted against this flag. See the module docstring for why
#: `accepted`/`rejected` are counted and not judged.
OPEN_STATUS = "pending"

#: Fields on their `Violation` that this adapter reads and DROPS. Named rather than
#: merely omitted so the hard-rule-6 test can assert on the set instead of on a hand-typed
#: list that drifts when the vendor adds a field. `image_url` is here for the reason the
#: module docstring gives: its last path segment is the recipient's phone number.
_DISCARDED_FIELDS: frozenset[str] = frozenset(
    {"from_phone_number", "to_phone_number", "email", "image_url", "user_id"}
)

#: The vendor's documented default page size is 20 with no published maximum
#: (`api-reference/violations/list.md`: `page_size` "Number of results per page",
#: `default: 20`, `minimum: 1`). We ask for 50 — the size their execution listing
#: documents as its maximum — because a violations page is small and fewer round trips is
#: strictly better. A server that caps us lower simply returns fewer rows and `has_more`
#: keeps the walk correct.
PAGE_SIZE = 50

#: A bound on paging. Ten pages of 50 is five hundred open flags in one sweep; an account
#: in that state has an incident, not a backlog, and the alarm has already fired by then.
#: The bound is what stops a vendor whose `has_more` sticks on True from turning a cron
#: into an unbounded request loop.
MAX_PAGES = 10

#: `datetime.fromisoformat`-shaped parser, injected by the adapter. Injected rather than
#: re-implemented here because `engine/bolna.py` already owns the vendor's date tolerances
#: (`_parse_dt`), and a second ISO parser in this package would be the "two ways per
#: problem" defect on a field that decides how old an unanswered compliance flag is.
DateParser = Callable[[Any], datetime | None]

#: One vendor round trip, as the adapter performs it — `BolnaEngine._request`. Typed with
#: `...` on purpose: the ladder it goes through (throttle, error normalization, non-JSON
#: 2xx) is `vendor_http.vendor_request`'s contract and is not this module's to restate.
VendorRequest = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class EngineViolation:
    """One compliance flag the engine holds against our account, in OUR vocabulary.

    Deliberately narrower than their payload — see the module docstring. Every field here
    is either an opaque vendor id (safe to log, the same class as `engine_agent_ref`) or a
    timestamp; nothing here can carry a phone number, an email or an evidence path.
    """

    #: The vendor's id for the flag. What an operator quotes when submitting evidence.
    violation_id: str
    #: Their `status` verbatim. NOT mapped onto a vocabulary of ours: three of the four
    #: members are undefined by their documentation, and a map would be four guesses.
    status: str
    #: Their `agent_id` — our `engine_agent_ref`, which `engine_agent_routes` resolves to
    #: the tenant whose call was flagged.
    engine_agent_ref: str | None
    #: Their `execution_id` — our `calls.engine_call_id`.
    engine_call_id: str | None
    #: When the flagged call happened, per their `date_of_call`.
    call_date: datetime | None
    #: When the flag was raised. The clock a deadline would run from, if one were
    #: documented.
    raised_at: datetime | None
    #: When it last changed state.
    updated_at: datetime | None
    #: Whether an evidence file is attached. The BOOLEAN, never the URL.
    has_evidence: bool

    @property
    def is_open(self) -> bool:
        """Nothing has been submitted against this flag yet."""
        return self.status == OPEN_STATUS


@dataclass(frozen=True, slots=True)
class ViolationListing:
    """What one sweep of the violations endpoint saw, and whether it saw all of it.

    `complete` stays a POSITIVE claim, exactly as `ExecutionListing.complete` does: an
    incomplete sweep must not read like a clean account. An operator told "no open
    violations" by a walk that stopped at its page cap has been told something false.
    """

    violations: tuple[EngineViolation, ...]
    complete: bool
    incomplete_reason: ListingIncompleteReason | None
    #: Rows the vendor returned that this adapter could not read into a record. Counted
    #: rather than dropped silently: a schema change lands here first.
    unreadable_rows: int
    pages_fetched: int

    @property
    def open_violations(self) -> tuple[EngineViolation, ...]:
        return tuple(v for v in self.violations if v.is_open)


@runtime_checkable
class SupportsViolations(Protocol):
    """An engine that publishes compliance flags against the account.

    NOT a member of `VoiceEngine` and not an `EngineCapabilities` flag, and both omissions
    are deliberate. `EngineCapabilities` describes which Protocol METHODS an adapter will
    honour (`require_capability` refuses at the call site of one) — a boolean there would
    advertise a capability with no method behind it. This is an optional surface a vendor
    either has or has not, so the honest test is whether the adapter implements it, which
    is what a structural Protocol asks. `fake` and `cartesia` do not implement it and the
    sweep reports itself skipped rather than failing.
    """

    async def list_violations(self, *, status: str) -> ViolationListing: ...


def _rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The violation rows in one listing response.

    `data` is the documented envelope key (`ViolationList.data`, "Array of violation
    objects"). A bare top-level array is tolerated because `vendor_request` wraps one as
    `{"data": [...]}` — the shape `GET /v2/agent/all` really returns.
    """
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def parse_violation(row: Mapping[str, Any], *, parse_dt: DateParser) -> EngineViolation | None:
    """One vendor row → one `EngineViolation`, or None when the row is not readable.

    INERT ON A SHAPE WE DID NOT EXPECT, the asymmetry every reader in this package uses
    (D-41): a row with no id or no status is returned as `None` and COUNTED by the caller,
    never as a confident record with empty fields. An unreadable violation that looked
    like a readable one in a `submitted` state would be the worst possible failure here —
    a flag reported as answered because we could not read it.
    """
    violation_id = row.get("id")
    status = row.get("status")
    if not isinstance(violation_id, str) or not violation_id:
        return None
    if not isinstance(status, str) or not status:
        return None
    agent_ref = row.get("agent_id")
    execution_id = row.get("execution_id")
    # `image_url` is read ONLY to decide the boolean, and the string is not bound to a
    # name that outlives this expression. See the module docstring: the path ends in the
    # recipient's phone number.
    has_evidence = bool(row.get("image_url"))
    return EngineViolation(
        violation_id=violation_id,
        status=status,
        engine_agent_ref=agent_ref if isinstance(agent_ref, str) and agent_ref else None,
        engine_call_id=execution_id if isinstance(execution_id, str) and execution_id else None,
        call_date=parse_dt(row.get("date_of_call")),
        raised_at=parse_dt(row.get("created_at")),
        updated_at=parse_dt(row.get("updated_at")),
        has_evidence=has_evidence,
    )


async def walk_violations(
    request: VendorRequest,
    *,
    status: str,
    parse_dt: DateParser,
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
) -> ViolationListing:
    """Page `GET /violations/list?status=…` to the end, or to our bound.

    The completeness rules are `BolnaEngine.list_executions`' rules, and they are the same
    rules on purpose — one way per problem, and this endpoint documents the same
    pagination contract (`api-reference/pagination.md` via
    `api-reference/violations/list.md`: *"You can utilize `has_more` in the API response to
    determine if you should fetch the next page"*):

    * every page ended on `has_more: false` → `complete=True`;
    * `has_more` absent and a FULL page returned → `full_page_suspected`. The flag is
      documented, so its absence means we are not reading the endpoint we think we are,
      and a full page under that uncertainty is the one shape that can hide rows;
    * our own bound stopped a walk that still said `has_more` → `page_cap_reached`;
    * a page we had not fetched carried only ids we already had → `next_link_no_progress`.

    De-duplicated by `violation_id` across pages: the vendor's list moves under a walk,
    and counting one flag twice would inflate an alarm an operator acts on.
    """
    collected: list[EngineViolation] = []
    seen: set[str] = set()
    unreadable = 0
    pages = 0
    reason: ListingIncompleteReason | None = None
    page_number = 1

    while True:
        payload = await request(
            "GET",
            "/violations/list",
            params={"status": status, "page_number": page_number, "page_size": page_size},
        )
        pages += 1
        rows = _rows(payload)
        new_rows = 0
        for row in rows:
            violation = parse_violation(row, parse_dt=parse_dt)
            if violation is None:
                unreadable += 1
                continue
            if violation.violation_id in seen:
                continue
            seen.add(violation.violation_id)
            collected.append(violation)
            new_rows += 1

        has_more = payload.get("has_more")
        if not isinstance(has_more, bool):
            # Believe the page rather than the missing flag: a SHORT page cannot be
            # hiding anything, a full one might be.
            if len(rows) >= page_size:
                reason = "full_page_suspected"
            break
        if not has_more:
            break
        if new_rows == 0:
            reason = "next_link_no_progress"
            break
        if page_number >= max_pages:
            reason = "page_cap_reached"
            break
        page_number += 1

    if reason is not None or unreadable:
        # Counts and our own word for the reason. No row content — hard rule 6, and this
        # payload is the one in this package that carries phone numbers.
        log.warning(
            "engine_violation_listing_incomplete",
            extra={
                "engine": "bolna",
                "reason": reason,
                "pages_fetched": pages,
                "violations": len(collected),
                "unreadable_rows": unreadable,
            },
        )
    return ViolationListing(
        violations=tuple(collected),
        complete=reason is None,
        incomplete_reason=reason,
        unreadable_rows=unreadable,
        pages_fetched=pages,
    )


__all__ = [
    "MAX_PAGES",
    "OPEN_STATUS",
    "PAGE_SIZE",
    "VENDOR_STATUSES",
    "DateParser",
    "EngineViolation",
    "SupportsViolations",
    "VendorRequest",
    "ViolationListing",
    "parse_violation",
    "walk_violations",
]
