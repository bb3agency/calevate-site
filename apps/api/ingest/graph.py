"""The Meta Graph adapter — the ONLY place that knows Graph's request and error shapes.

`ingest/meta.py` owns the seam (the Protocol, the capability selector, the reason
vocabulary and the `field_data` → flat-map normalization); this file owns the vendor
half and nothing else. The import arrow runs one way: this module depends on the seam,
`meta.lead_retrieval_capability` imports this one INSIDE the function body so a
deployment that has not selected the retriever never imports httpx for it — the same
shape `workers/sheets_sync.get_sheets_transport` uses, and for the same reason.

What crosses the seam is `RetrievedLead`: our status, our reason code, our flat answers.
No Graph JSON, no vendor error string, and no HTTP status reaches a caller (hard rule 2
in spirit: the rest of the system consumes our normalized models).

RESEARCHED, NOT RECALLED
------------------------
`developers.facebook.com` AND `graph.facebook.com` are both refused by this sandbox's
egress proxy (403 on CONNECT, re-confirmed while writing this file), so no live call was
made and none of what follows was verified against a real Meta app. Each claim below is
marked with what it came from, exactly as `meta.py` and `workers/google_sheets.py` mark
theirs. The single live confirmation still owed is one real delivery read end to end —
OPERATIONS §2b is that gate.

- **The request.** `GET https://graph.facebook.com/{version}/{leadgen_id}?fields=field_data`
  with a Page access token holding `leads_retrieval`. The webhook is a change
  notification only; this second, authenticated read is where the answers live.
  <https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads/retrieving>
  — blocked here, so read via an independent implementation that shows the same call
  (<https://gist.github.com/tixastronauta/0b9c3b409a7ba96edffc>: `curl -G -d
  'access_token=…' https://graph.facebook.com/v2.5/<LEADGEN_ID>`) and Meta's own
  `Lead` object, whose readable fields include `field_data`
  (<https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/main/facebook_business/adobjects/lead.py>).
- **`field_data` is `[{"name": …, "values": [...]}]`** — the answers are a LIST per
  question (multi-select), and the names are whatever the client called their form
  fields, not a fixed schema. Same gist, and the shape `meta.flatten_field_data`
  already normalizes.
- **The version is PINNED, in code, deliberately.** Meta ships roughly two Graph
  versions a year and each is supported about two years; an unpinned call silently
  follows whatever "current" means on the day, which is a breaking change nobody
  chose. `v26.0` is the version Meta's OWN SDKs pin on `main` — first-party code, which
  is the strongest source available while the docs site is blocked:
  <https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/main/facebook_business/apiconfig.py>
  (`'API_VERSION': 'v26.0'`) and
  <https://raw.githubusercontent.com/facebook/facebook-nodejs-business-sdk/main/src/api.js>
  (`static get VERSION(): string { return 'v26.0'; }`). Released 2026-07-29 per
  ppc.land's version report (secondary; egress-blocked, read via search summary), which
  puts its two-year support window comfortably past anything we plan against. Bumping it
  is a code change with a test run, NOT an environment variable — a config knob here
  would let an operator select a sunset version at 3am.
- **The token goes in `Authorization: Bearer …`, not in the query string.** Meta
  documents the header form ("include your token in an authorization request header,
  preceded by Bearer"), and a credential in a URL is a credential in every access log,
  proxy trace and httpx exception message between us and them. DOCUMENTATION-SOURCED
  and unconfirmed live; if it were wrong the failure is a 190 → `meta_page_token_invalid`
  → an alert and a recorded refusal, which is the loud direction to be wrong in.
  <https://developers.facebook.com/docs/graph-api/get-started/> (blocked; read via
  search summary quoting the `-H 'Authorization: Bearer EAAJB…'` sample).
- **Leads are retrievable for 90 days**, after which they are deleted at Meta and
  unrecoverable by API, Ads Manager or support. That is the outer bound on any retry
  window; ours is far smaller (Meta's own webhook redelivery, ~36h). Widely and
  consistently reported by independent integrators; Meta's own page is blocked. So a
  lead that has aged out reads as a permanently missing object, which is what
  `LEAD_NOT_READABLE_REASON` says.
- **Rate limiting is generous for this access pattern.** Lead retrieval is throttled per
  Page at roughly `200 * 24 * (leads created in the last 90 days)` calls per 24h
  (secondary, consistently reported). We make exactly ONE read per lead — the
  `leadgen_id` inbox claim guarantees it — so steady-state consumption is one call
  against a budget of ~4,800 per lead. A 429 here means something else is wrong, and it
  is reported transient rather than absorbed.

ERROR CLASSIFICATION, AND THE ONE PLACE WE DIVERGE FROM META'S OWN SDK
----------------------------------------------------------------------
The numeric groupings come from Meta's OWN `RequestException::create` — first-party
code, not prose:
<https://raw.githubusercontent.com/facebook/facebook-php-business-sdk/main/src/FacebookAds/Http/Exception/RequestException.php>

    subcodes 458, 459, 460, 463, 464, 467 | codes 100, 102, 190 | type OAuthException
        -> AuthorizationException
    codes 1, 2      -> ServerException
    codes 4, 17, 341 -> ThrottleException
    code 10, codes 200-299 -> PermissionException

We follow it except for **code 100**, which their SDK calls an authorization failure and
we call an unreadable OBJECT. The divergence is deliberate and it is about who gets
woken up. On `GET /{leadgen_id}` the only thing that varies between calls is the lead id,
and Meta fuses three causes into one message for 100/33 — "Object with ID … does not
exist, cannot be loaded due to missing permissions, or does not support this operation".
A dead or revoked token does not present as 100; it presents as 190, which we classify
as a credential failure and alert on. So reading 100 as "the token is dead" would page
an operator for every lead that aged past 90 days or was deleted by the advertiser,
while reading 190 as "this one lead is odd" would leave a broken integration silent —
and only the second of those is unrecoverable.

**Known ambiguity, stated rather than papered over:** a Page token that never had
`leads_retrieval` granted may also surface as 100/33 rather than as a 200-series
permission error, because "missing permissions" is one of the three fused causes. So
`meta_lead_not_readable` is a reason with three possible remediations, and the client-
facing text has to carry all three (WEBHOOKS §2.6). Distinguishing them needs a live
Meta app to observe — OPERATIONS §2b gate 3.

RETRIES ARE NOT IMPLEMENTED HERE, ON PURPOSE
--------------------------------------------
A transient answer travels up as `RetrievalStatus.TRANSIENT`, the route answers 503, and
**Meta's own at-least-once delivery is the retry ladder** — backoff for hours, with the
`leadgen_id` inbox claim making every redelivery idempotent. A second backoff loop inside
this adapter would hold the request open across somebody else's outage and give a client
two different answers to "why was my lead late" depending on which layer retried. Same
decision, same reasoning, as `workers/google_sheets.py`.

Hard rule 6 throughout: an answer, a phone number and an access token never reach a log
line here. Reason codes, HTTP statuses, Meta's numeric error codes and the lead source
id — which is ours, not personal data — are the only things logged. The `leadgen_id` is
deliberately absent for the reason `routes._record_refusal` gives: a 15-digit Meta object
id is phone-shaped and the redactor cannot tell it from a number it must mask.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

import httpx

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.ingest.meta import (
    GRAPH_PROVIDER,
    NO_TOKEN_REASON,
    RetrievalStatus,
    RetrievedLead,
    flatten_field_data,
)

log = get_logger(__name__)

# The provider name that selects this adapter (`META_LEAD_RETRIEVER`). Imported from the
# seam rather than re-spelled: one definition, so a rename cannot leave the selector
# looking for a provider no adapter answers to.
PROVIDER: Final = GRAPH_PROVIDER

GRAPH_HOST: Final = "https://graph.facebook.com"
# See the docstring: pinned in code, from Meta's own SDKs, never from configuration.
GRAPH_API_VERSION: Final = "v26.0"

# The ONLY field we ask for. Everything else about the lead — which ad, which form, when
# — is already in the notification we authenticated, so requesting more would be reading
# personal data we have no use for (DPDP §6 purpose limitation) and widening what a
# vendor response can carry into our process.
LEAD_FIELDS: Final = "field_data"

# Long enough for a Graph read on a bad day, short enough that a batch of leads cannot
# hold the receiver open for a minute. A timeout is a TRANSIENT answer, so the cost of
# being wrong here is one redelivery, not a lost lead.
REQUEST_TIMEOUT_S: Final = 8.0

# --- authored reason codes -----------------------------------------------------
#
# Never vendor prose. A Graph error string may quote the lead we just refused, and these
# land in an alert, in `webhook_inbox_events.last_error` and in the client's own activity
# view (hard rule 6, and the same rule `workers/google_sheets.py` states for Google).

#: The credential is dead: expired, revoked, invalidated by a password change or an
#: app-review downgrade. Permanent for this lead AND for every other one until an
#: operator replaces the entry, which is why it alerts.
TOKEN_INVALID_REASON: Final = "meta_page_token_invalid"
#: The token is alive but not allowed to do this. Also permanent until someone acts.
PERMISSION_DENIED_REASON: Final = "meta_leads_retrieval_denied"
#: Meta will not give us this object: aged past the 90-day window, deleted, never ours,
#: or a token without `leads_retrieval` (see the ambiguity note in the docstring).
LEAD_NOT_READABLE_REASON: Final = "meta_lead_not_readable"
#: Throttled. Transient — the request was refused, not performed.
RATE_LIMITED_REASON: Final = "meta_rate_limited"
#: Meta says it is having a problem. Transient.
UNAVAILABLE_REASON: Final = "meta_graph_unavailable"
#: We could not complete the round trip at all. Transient.
UNREACHABLE_REASON: Final = "meta_graph_unreachable"
#: A 200 whose body is not the document this endpoint documents. Permanent for this
#: attempt: repeating a request that returned something we cannot parse gets the same
#: thing back, and a wrong lead is worse than a refused one.
MALFORMED_REASON: Final = "meta_graph_malformed_response"

# --- Meta's numeric vocabulary (their SDK's groupings; see the docstring) -------

_OAUTH_SUBCODES: Final = frozenset({458, 459, 460, 463, 464, 467})
_TOKEN_CODES: Final = frozenset({102, 190})
_PERMISSION_CODES: Final = frozenset({10, *range(200, 300)})
_THROTTLE_CODES: Final = frozenset({4, 17, 341})
_SERVER_CODES: Final = frozenset({1, 2})
# `GET /{object}` on something this token cannot see. Ours to read as "not this lead",
# NOT as "not this token" — the divergence argued in the docstring.
_UNREADABLE_OBJECT_CODE: Final = 100
# HTTP statuses that mean "the request was fine, the moment was not". Graph reports
# throttling in the body as well, but a bare 429 from an edge never reaches the body.
_TRANSIENT_STATUS: Final = frozenset({408, 429})


def parse_token_map(raw: str) -> dict[UUID, str]:
    """`{"<lead source id>": "<page access token>"}` → a usable map, or an empty one.

    Never raises and never logs a value: a malformed secret is an operator error that
    must surface as a named refusal on the client's setup card, not as a traceback whose
    next frame prints the credential. Unusable entries are COUNTED in the log so the
    operator can see that the secret was read and partly rejected, which is the failure
    that otherwise looks identical to "not configured yet".

    Keys are parsed as UUIDs rather than compared as strings so that `018F…` and `018f…`
    are the same lead source — a hand-pasted id differing only in case would otherwise be
    a source that reports "no token" while the operator is looking at the token.
    """
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        log.error("meta_token_map_unparseable")
        return {}
    if not isinstance(parsed, dict):
        log.error("meta_token_map_not_an_object")
        return {}

    tokens: dict[UUID, str] = {}
    rejected = 0
    for key, value in parsed.items():
        if not isinstance(value, str) or not value.strip():
            rejected += 1
            continue
        try:
            source_id = UUID(str(key))
        except ValueError:
            rejected += 1
            continue
        tokens[source_id] = value.strip()
    if rejected:
        log.error("meta_token_map_entries_rejected", extra={"rejected": rejected})
    return tokens


class GraphLeadRetriever:
    """`GET /{leadgen_id}?fields=field_data`, one attempt, one normalized answer.

    Built per capability lookup (the seam re-reads settings so a rotated secret takes
    effect without a restart, exactly like `get_sheets_transport`). That is affordable
    because the work per instance is one `json.loads` of a small map, against a call that
    is already making an HTTPS round trip and three database transactions.
    """

    name = PROVIDER

    def __init__(self, raw_tokens: str, *, client: httpx.AsyncClient | None = None) -> None:
        # Parsed once, here, so a malformed secret is one refusal rather than a parse
        # failure inside every read.
        self._tokens = parse_token_map(raw_tokens)
        # Same injection seam and same ownership rule as `GoogleSheetsTransport`: a
        # caller-supplied client is the caller's to close. It exists so tests drive this
        # adapter through httpx's real request plumbing (`httpx.MockTransport`) — a
        # hand-written stand-in cannot get a URL or a header wrong, and getting the URL
        # wrong is the failure mode here.
        self._client = client

    def holds_credential_for(self, source_id: UUID) -> bool:
        """Can this deployment read THIS client's leads? The whole per-tenant question.

        There is no fallback to "the only token we have". A lead source pointed at a
        credential we do not hold has not been configured yet, and serving it with
        somebody else's token is the cross-tenant leak this keying exists to prevent.
        """
        return source_id in self._tokens

    async def fetch_answers(self, *, source_id: UUID, leadgen_id: str) -> RetrievedLead:
        token = self._tokens.get(source_id)
        if token is None:
            # Reachable when a token is dropped between the capability check and the
            # read. Answering with the seam's own reason keeps one vocabulary for one
            # condition rather than inventing a second name for it here.
            return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=NO_TOKEN_REASON)

        owns_client = self._client is None
        http = self._client or httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_S,
            # Graph does not redirect a node read, and following one would replay the
            # Authorization header at whatever host answered.
            follow_redirects=False,
        )
        try:
            response = await http.get(
                f"{GRAPH_HOST}/{GRAPH_API_VERSION}/{leadgen_id}",
                params={"fields": LEAD_FIELDS},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            # The exception TYPE, never the exception: httpx puts the request URL in the
            # message, and a timeout on a lead read is not a sentence worth a credential.
            log.warning("meta_graph_transport_error", extra={"error": type(exc).__name__})
            return RetrievedLead(status=RetrievalStatus.TRANSIENT, reason=UNREACHABLE_REASON)
        finally:
            if owns_client:
                await http.aclose()

        if response.status_code != 200:
            return self._refusal(response, source_id=source_id)
        try:
            body = response.json()
        except ValueError:
            log.error("meta_graph_unparseable_body", extra={"source_id": str(source_id)})
            return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=MALFORMED_REASON)
        if not isinstance(body, dict):
            log.error("meta_graph_unexpected_body", extra={"source_id": str(source_id)})
            return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=MALFORMED_REASON)

        # A 200 carrying an `error` object is not documented for a node read, but Graph
        # is a big surface and the cost of assuming otherwise is treating a refusal as
        # an empty lead. Classified as though it had arrived with its status.
        if isinstance(body.get("error"), dict):
            return self._refusal(response, source_id=source_id, body=body)

        answers = flatten_field_data(body.get(LEAD_FIELDS))
        log.info(
            "meta_lead_retrieved",
            # Counts and ids only — never a field name (the client chose it and it can
            # be anything) and never an answer.
            extra={"source_id": str(source_id), "answers": len(answers)},
        )
        return RetrievedLead(status=RetrievalStatus.RETRIEVED, answers=answers)

    def _refusal(
        self, response: httpx.Response, *, source_id: UUID, body: Any = None
    ) -> RetrievedLead:
        """One Graph failure → one authored reason and a verdict on trying again."""
        error = _error_object(response if body is None else body)
        code = _as_int(error.get("code"))
        subcode = _as_int(error.get("error_subcode"))
        status = response.status_code

        retrieved = _classify(status=status, code=code, subcode=subcode)
        # The numbers are Meta's and are safe to log; their `message` is not, and is not
        # read anywhere in this module. `fbtrace_id` is what Meta's support asks for, and
        # it identifies a request rather than a person.
        log.warning(
            "meta_graph_refused",
            extra={
                "source_id": str(source_id),
                "reason": retrieved.reason,
                "status": status,
                "meta_code": code,
                "meta_subcode": subcode,
                "fbtrace_id": str(error.get("fbtrace_id") or ""),
            },
        )
        if retrieved.reason in (TOKEN_INVALID_REASON, PERMISSION_DENIED_REASON):
            # A page, not just a log: this client's integration is down NOW and stays
            # down until a human replaces the credential. Every subsequent lead from
            # this source will refuse until then, and the alert path's per-fingerprint
            # suppression is what keeps that one page rather than one per lead.
            alert(
                "ROUTE_HANDLER",
                retrieved.reason,
                source_id=str(source_id),
                meta_code=str(code),
            )
        return retrieved


def _error_object(carrier: Any) -> dict[str, Any]:
    """Graph's `{"error": {...}}`, or an empty dict. Never raises on a body we did not
    expect — an unparseable refusal is still a refusal and must classify by status."""
    body: Any = carrier
    if isinstance(carrier, httpx.Response):
        try:
            body = carrier.json()
        except ValueError:
            return {}
    if not isinstance(body, dict):
        return {}
    error = body.get("error")
    return error if isinstance(error, dict) else {}


def _as_int(value: Any) -> int | None:
    """A Meta error code as an int. `bool` is excluded before `int` because `True` is an
    `int` in Python and would classify as code 1 (a server error)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _classify(*, status: int, code: int | None, subcode: int | None) -> RetrievedLead:
    """The table in the module docstring, in the order the answers matter.

    Credential verdicts come FIRST, before the transient statuses, because a 429 in
    front of a dead token is still a dead token and retrying it for 36 hours would end
    with Meta unsubscribing the Page while an operator was never told why.
    """
    if subcode is not None and subcode in _OAUTH_SUBCODES:
        return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=TOKEN_INVALID_REASON)
    if code is not None:
        if code in _TOKEN_CODES:
            return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=TOKEN_INVALID_REASON)
        if code in _PERMISSION_CODES:
            return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=PERMISSION_DENIED_REASON)
        if code in _THROTTLE_CODES:
            return RetrievedLead(status=RetrievalStatus.TRANSIENT, reason=RATE_LIMITED_REASON)
        if code in _SERVER_CODES:
            return RetrievedLead(status=RetrievalStatus.TRANSIENT, reason=UNAVAILABLE_REASON)
        if code == _UNREADABLE_OBJECT_CODE:
            return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=LEAD_NOT_READABLE_REASON)
    if status in _TRANSIENT_STATUS:
        return RetrievedLead(status=RetrievalStatus.TRANSIENT, reason=RATE_LIMITED_REASON)
    if status >= 500:
        return RetrievedLead(status=RetrievalStatus.TRANSIENT, reason=UNAVAILABLE_REASON)
    if status in (401, 403):
        # No code we recognise, but the status says authorization. Erring toward the
        # credential is right here: it is the reading that gets a human involved.
        return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=TOKEN_INVALID_REASON)
    # Everything else in the 4xx band is a request WE built being wrong about THIS lead,
    # and repeating it cannot fix that either.
    return RetrievedLead(status=RetrievalStatus.PERMANENT, reason=LEAD_NOT_READABLE_REASON)


__all__ = [
    "GRAPH_API_VERSION",
    "GRAPH_HOST",
    "LEAD_FIELDS",
    "LEAD_NOT_READABLE_REASON",
    "MALFORMED_REASON",
    "PERMISSION_DENIED_REASON",
    "PROVIDER",
    "RATE_LIMITED_REASON",
    "REQUEST_TIMEOUT_S",
    "TOKEN_INVALID_REASON",
    "UNAVAILABLE_REASON",
    "UNREACHABLE_REASON",
    "GraphLeadRetriever",
    "parse_token_map",
]
