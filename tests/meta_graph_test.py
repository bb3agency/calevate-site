"""The Meta Graph ADAPTER — the vendor half of the lead-retrieval slice.

`tests/meta_lead_ads_test.py` holds the seam: one capability selector, one refusal
vocabulary, one consent gate, proven against the shipped recording adapter. This file
holds the thing that would actually talk to Meta, and it exists to pin five claims the
seam cannot make:

1. **The request is the request.** Host, PINNED version, path, `fields`, and the token
   in an `Authorization: Bearer` header rather than in a URL that every proxy logs.
   Everything runs through `httpx.MockTransport`, so the URL and the headers are the
   real ones httpx would have put on the wire — a hand-written stand-in cannot get a
   path wrong, and getting the path wrong is the failure mode here.
2. **Errors are part of the interface.** Every Graph failure maps to exactly ONE
   authored reason code (never vendor prose), and to a verdict about whether trying
   again can help. A dead token and an aged-out lead are opposite answers and both are
   permanent; a 429 and a 500 are the same answer and it is "ask again".
3. **A credential is per lead source, and there is no fallback.** A source the token map
   does not name holds nothing and borrows nothing — the cross-tenant leak the keying
   exists to prevent.
4. **Hard rule 6.** No answer, no phone number, no access token and no vendor message
   reaches a log record. Asserted against the real JSON formatter, not by reading.
5. **The greppable constant means what it says.** `LEAD_RETRIEVAL_IMPLEMENTED` is True
   iff an adapter is importable and satisfies the Protocol.

NO NETWORK AND NO META APP: `graph.facebook.com` is egress-blocked from this
environment (403 on CONNECT), which is also why every claim in `apps/api/ingest/graph.py`
is documentation- or first-party-SDK-sourced and why OPERATIONS §2b still owes one live
delivery. These tests pin what we BUILT; they cannot and do not pin what Meta does.

Run: uv run pytest -q tests/meta_graph_test.py
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
import pytest
from apps.api.core.logging import JsonFormatter
from apps.api.ingest import graph, meta
from apps.api.ingest.graph import (
    GRAPH_API_VERSION,
    GRAPH_HOST,
    LEAD_FIELDS,
    LEAD_NOT_READABLE_REASON,
    MALFORMED_REASON,
    PERMISSION_DENIED_REASON,
    RATE_LIMITED_REASON,
    TOKEN_INVALID_REASON,
    UNAVAILABLE_REASON,
    UNREACHABLE_REASON,
    GraphLeadRetriever,
    parse_token_map,
)
from apps.api.ingest.recorded import RecordedLeadRetriever

SOURCE_ID = uuid.UUID("018f4c2a-0000-7000-8000-00000000beef")
TOKEN = "EAAG-a-page-access-token-that-is-not-real"
LEADGEN_ID = "900000000000123"

# One lead as Meta documents it: answers are a LIST per question and the names are
# whatever the CLIENT called their form fields — there is no fixed schema here.
FIELD_DATA: list[dict[str, Any]] = [
    {"name": "full_name", "values": ["Ravi Kumar"]},
    {"name": "phone_number", "values": ["+919876543210"]},
    {"name": "which_project", "values": ["Whitefield", "Sarjapur"]},
]


def _tokens(*, source_id: uuid.UUID = SOURCE_ID, token: str = TOKEN) -> str:
    return json.dumps({str(source_id): token})


def _retriever(handler: Any, *, tokens: str | None = None) -> GraphLeadRetriever:
    """An adapter wired to a mock transport. The transport is httpx's own, so the
    request the handler inspects is byte-for-byte what would have been sent."""
    return GraphLeadRetriever(
        tokens if tokens is not None else _tokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _error(code: int, *, subcode: int | None = None, status: int = 400) -> httpx.Response:
    """Graph's error envelope. The `message` is deliberately hostile: it quotes the lead
    we are refusing, which is exactly why nothing reads it."""
    body: dict[str, Any] = {
        "error": {
            "message": "Ravi Kumar +919876543210 could not be loaded",
            "type": "OAuthException",
            "code": code,
            "fbtrace_id": "A1bC2dE3fG4",
        }
    }
    if subcode is not None:
        body["error"]["error_subcode"] = subcode
    return httpx.Response(status, json=body)


# --- the request ---------------------------------------------------------------


async def test_the_request_is_the_pinned_graph_node_read_with_a_bearer_token() -> None:
    """An unpinned version silently follows whatever "current" means on the day, which
    is a breaking change nobody chose; a token in the query string is a token in every
    access log between us and Meta."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": LEADGEN_ID, "field_data": FIELD_DATA})

    result = await _retriever(handler).fetch_answers(source_id=SOURCE_ID, leadgen_id=LEADGEN_ID)

    assert result.status is meta.RetrievalStatus.RETRIEVED
    assert len(seen) == 1, "one lead, one Graph read"
    request = seen[0]
    assert request.method == "GET"
    assert str(request.url).startswith(f"{GRAPH_HOST}/{GRAPH_API_VERSION}/{LEADGEN_ID}")
    assert request.url.params["fields"] == LEAD_FIELDS
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert "access_token" not in str(request.url), "never in the URL"


def test_the_pinned_version_is_a_real_pin() -> None:
    """A `v` and a number, not a floating alias. `latest`, an empty string or a bare
    number would all "work" against the host and all mean something we did not choose."""
    assert GRAPH_API_VERSION.startswith("v")
    major = GRAPH_API_VERSION[1:].split(".")[0]
    assert major.isdigit() and int(major) >= 26, (
        "pinned from Meta's own SDKs (see the sourcing block in ingest/graph.py); "
        "raising it is a code change with a test run, never an environment variable"
    )


async def test_only_field_data_is_requested() -> None:
    """Everything else about the lead — which ad, which form, when — is already in the
    notification we authenticated, so asking for more would be reading personal data we
    have no use for and widening what a vendor response can carry into our process."""
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url.params["fields"])
        return httpx.Response(200, json={"field_data": FIELD_DATA})

    await _retriever(handler).fetch_answers(source_id=SOURCE_ID, leadgen_id=LEADGEN_ID)
    assert captured == ["field_data"]


async def test_the_answers_cross_the_seam_flat_and_never_as_field_data() -> None:
    """Meta's `values` is a LIST — a multi-select answer has two entries and dropping the
    second would quietly change what the person said. What leaves the adapter is our flat
    map, so nothing downstream ever learns that Meta's answers are a list at all."""
    result = await _retriever(
        lambda _: httpx.Response(200, json={"field_data": FIELD_DATA})
    ).fetch_answers(source_id=SOURCE_ID, leadgen_id=LEADGEN_ID)

    assert result.answers == {
        "full_name": "Ravi Kumar",
        "phone_number": "+919876543210",
        "which_project": "Whitefield, Sarjapur",
    }
    assert result.reason is None


async def test_a_lead_with_no_answers_is_not_a_lead() -> None:
    """A 200 carrying an empty or absent `field_data`. There is nothing to dial and
    nothing to put in a row, so the seam's own reason applies rather than a Graph one."""
    empty = await _retriever(lambda _: httpx.Response(200, json={"field_data": []})).fetch_answers(
        source_id=SOURCE_ID, leadgen_id=LEADGEN_ID
    )
    assert empty.status is meta.RetrievalStatus.RETRIEVED
    assert empty.answers == {}, "the ROUTE turns this into meta_lead_had_no_answers"


# --- credentials ---------------------------------------------------------------


async def test_a_source_the_map_does_not_name_holds_nothing_and_borrows_nothing() -> None:
    """The cross-tenant leak this keying exists to prevent. There is deliberately no
    fallback to "well, use the only token we have": a lead source pointed at a credential
    we do not hold has not been configured, and serving it with somebody else's token
    would put one client's leads in another client's CRM."""
    neighbour = uuid.uuid4()
    called: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={"field_data": FIELD_DATA})

    retriever = _retriever(handler)
    assert retriever.holds_credential_for(SOURCE_ID) is True
    assert retriever.holds_credential_for(neighbour) is False

    refused = await retriever.fetch_answers(source_id=neighbour, leadgen_id=LEADGEN_ID)
    assert refused.status is meta.RetrievalStatus.PERMANENT
    assert refused.reason == meta.NO_TOKEN_REASON, "the SEAM's name for it, not a second one"
    assert called == [], "and Meta was never asked"


async def test_each_source_reads_with_its_own_token() -> None:
    """One process serves every tenant, so the token is a parameter of the read and
    never constructor state — an adapter that closed over one client's credential would
    need one instance per client and a cache to keep them apart."""
    other = uuid.uuid4()
    presented: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        presented.append(request.headers["authorization"])
        return httpx.Response(200, json={"field_data": FIELD_DATA})

    retriever = _retriever(
        handler, tokens=json.dumps({str(SOURCE_ID): "EAAG-first", str(other): "EAAG-second"})
    )
    await retriever.fetch_answers(source_id=SOURCE_ID, leadgen_id=LEADGEN_ID)
    await retriever.fetch_answers(source_id=other, leadgen_id=LEADGEN_ID)
    assert presented == ["Bearer EAAG-first", "Bearer EAAG-second"]


def test_the_token_map_refuses_what_it_cannot_use_and_keeps_what_it_can() -> None:
    """A malformed secret is an operator error that has to surface as a named refusal on
    a client's setup card, not as a traceback whose next frame prints the credential."""
    good = uuid.uuid4()
    parsed = parse_token_map(
        json.dumps(
            {
                str(good): "EAAG-good",
                "not-a-uuid": "EAAG-orphan",
                str(uuid.uuid4()): "",
                str(uuid.uuid4()): 12345,
            }
        )
    )
    assert parsed == {good: "EAAG-good"}
    assert parse_token_map("") == {}
    assert parse_token_map("   ") == {}
    assert parse_token_map("{not json") == {}
    assert parse_token_map('["a-list"]') == {}


def test_the_token_map_is_case_insensitive_about_a_pasted_uuid() -> None:
    """An operator pastes a lead source id from a screen. `018F…` and `018f…` are the
    same source, and a source that reported "no token" while the operator was looking at
    the token would be an afternoon nobody gets back."""
    parsed = parse_token_map(json.dumps({str(SOURCE_ID).upper(): TOKEN}))
    assert parsed == {SOURCE_ID: TOKEN}


# --- the error mapping ---------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "expected_status", "expected_reason"),
    [
        # A dead credential. Meta's own SDK groups these subcodes as authorization
        # failures (see the sourcing block in graph.py), and they are permanent until a
        # human replaces the token — 460 is "the admin changed their password".
        (_error(190), meta.RetrievalStatus.PERMANENT, TOKEN_INVALID_REASON),
        (_error(190, subcode=463), meta.RetrievalStatus.PERMANENT, TOKEN_INVALID_REASON),
        (_error(1, subcode=460), meta.RetrievalStatus.PERMANENT, TOKEN_INVALID_REASON),
        (_error(102), meta.RetrievalStatus.PERMANENT, TOKEN_INVALID_REASON),
        # Alive, and not allowed to do this.
        (_error(10), meta.RetrievalStatus.PERMANENT, PERMISSION_DENIED_REASON),
        (_error(200), meta.RetrievalStatus.PERMANENT, PERMISSION_DENIED_REASON),
        (_error(299), meta.RetrievalStatus.PERMANENT, PERMISSION_DENIED_REASON),
        # THE ONE PLACE WE DIVERGE FROM META'S SDK, argued in graph.py: 100/33 is an
        # unreadable OBJECT (aged past 90 days, deleted, not ours), not a dead token.
        # Reading it as a token failure would page an operator for every expired lead.
        (_error(100, subcode=33), meta.RetrievalStatus.PERMANENT, LEAD_NOT_READABLE_REASON),
        (_error(100), meta.RetrievalStatus.PERMANENT, LEAD_NOT_READABLE_REASON),
        # Throttled: the request was REFUSED, not performed, so asking again is safe.
        (_error(4), meta.RetrievalStatus.TRANSIENT, RATE_LIMITED_REASON),
        (_error(17), meta.RetrievalStatus.TRANSIENT, RATE_LIMITED_REASON),
        (_error(341), meta.RetrievalStatus.TRANSIENT, RATE_LIMITED_REASON),
        (
            httpx.Response(429, text="slow down"),
            meta.RetrievalStatus.TRANSIENT,
            RATE_LIMITED_REASON,
        ),
        # Meta says it is having a problem.
        (_error(2, status=500), meta.RetrievalStatus.TRANSIENT, UNAVAILABLE_REASON),
        (httpx.Response(503, text="try later"), meta.RetrievalStatus.TRANSIENT, UNAVAILABLE_REASON),
        # No code we recognise, but the status says authorization. Erring toward the
        # credential gets a human involved, which is the recoverable direction.
        (httpx.Response(401, text=""), meta.RetrievalStatus.PERMANENT, TOKEN_INVALID_REASON),
        # A request WE built being wrong about this lead. Repeating it cannot fix that.
        (
            httpx.Response(400, text="nope"),
            meta.RetrievalStatus.PERMANENT,
            LEAD_NOT_READABLE_REASON,
        ),
        (httpx.Response(404, text=""), meta.RetrievalStatus.PERMANENT, LEAD_NOT_READABLE_REASON),
    ],
)
async def test_every_graph_failure_maps_to_one_authored_reason(
    response: httpx.Response,
    expected_status: meta.RetrievalStatus,
    expected_reason: str,
) -> None:
    """One table, and it is the interface: `webhook_inbox_events.last_error` renders in
    the client's activity view, so every entry has to be a code we wrote and a verdict a
    human can act on."""
    result = await _retriever(lambda _: response).fetch_answers(
        source_id=SOURCE_ID, leadgen_id=LEADGEN_ID
    )
    assert (result.status, result.reason) == (expected_status, expected_reason)
    assert result.answers == {}, "a refusal carries no answers"


async def test_a_transport_failure_is_transient_and_never_a_lost_lead() -> None:
    """A timeout is us being unable to ask, which is not a verdict about the lead. The
    route turns this into a 503 so Meta's own at-least-once ladder redelivers."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    result = await _retriever(handler).fetch_answers(source_id=SOURCE_ID, leadgen_id=LEADGEN_ID)
    assert result.status is meta.RetrievalStatus.TRANSIENT
    assert result.reason == UNREACHABLE_REASON


@pytest.mark.parametrize("body", [b"not json at all", b'"a bare string"', b"[1, 2, 3]"])
async def test_a_body_we_cannot_read_is_refused_rather_than_guessed(body: bytes) -> None:
    """Permanent on purpose: repeating a request that returned something unparseable
    gets the same thing back, and inventing a lead out of it is the one outcome worse
    than refusing."""
    result = await _retriever(lambda _: httpx.Response(200, content=body)).fetch_answers(
        source_id=SOURCE_ID, leadgen_id=LEADGEN_ID
    )
    assert (result.status, result.reason) == (meta.RetrievalStatus.PERMANENT, MALFORMED_REASON)


async def test_an_error_object_inside_a_200_is_still_a_refusal() -> None:
    """Not documented for a node read, and cheap to be right about anyway: the cost of
    assuming otherwise is treating a refusal as a lead with no answers."""
    result = await _retriever(
        lambda _: httpx.Response(200, json={"error": {"code": 190, "message": "x"}})
    ).fetch_answers(source_id=SOURCE_ID, leadgen_id=LEADGEN_ID)
    assert (result.status, result.reason) == (
        meta.RetrievalStatus.PERMANENT,
        TOKEN_INVALID_REASON,
    )


async def test_a_boolean_error_code_does_not_classify_as_a_server_error() -> None:
    """`True` is an `int` in Python, and code 1 is "an unknown error occurred" —
    transient. A malformed error body must not become a retry loop."""
    result = await _retriever(
        lambda _: httpx.Response(400, json={"error": {"code": True, "message": "x"}})
    ).fetch_answers(source_id=SOURCE_ID, leadgen_id=LEADGEN_ID)
    assert (result.status, result.reason) == (
        meta.RetrievalStatus.PERMANENT,
        LEAD_NOT_READABLE_REASON,
    )


# --- hard rule 6 ---------------------------------------------------------------


async def test_no_answer_no_number_no_token_and_no_vendor_message_reaches_a_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Asserted against the REAL formatter, because a field can be safe in the record and
    unsafe once serialized. The vendor's `message` here quotes the lead's name and number
    on purpose — that is the string an adapter is tempted to log."""
    with caplog.at_level(logging.INFO):
        await _retriever(
            lambda _: httpx.Response(200, json={"field_data": FIELD_DATA})
        ).fetch_answers(source_id=SOURCE_ID, leadgen_id=LEADGEN_ID)
        await _retriever(lambda _: _error(190, subcode=463)).fetch_answers(
            source_id=SOURCE_ID, leadgen_id=LEADGEN_ID
        )

    formatter = JsonFormatter()
    # OUR records. httpx's own `HTTP Request: <method> <full url>` line is excluded for
    # the reason `sheets_adapter_test` gives: production never emits it, because
    # `configure_logging` puts that logger at WARNING — and that is the test next door.
    emitted = "\n".join(
        formatter.format(record) for record in caplog.records if record.name != "httpx"
    )
    assert emitted, "the adapter is expected to say something"
    for forbidden in (
        "Ravi Kumar",
        "919876543210",
        TOKEN,
        "could not be loaded",
        LEADGEN_ID,
        "which_project",
    ):
        assert forbidden not in emitted, f"{forbidden!r} must never reach a log line"
    # What an operator DOES get: our reason, Meta's numeric code, and their trace id.
    assert TOKEN_INVALID_REASON in emitted
    assert "A1bC2dE3fG4" in emitted


# --- the greppable constant ----------------------------------------------------


def test_the_implemented_constant_and_the_adapter_agree() -> None:
    """`LEAD_RETRIEVAL_IMPLEMENTED` says one thing — an adapter is written — and it must
    not be flippable without one, in either direction. It deliberately says NOTHING
    about whether a deployment can fetch a lead; `lead_retrieval_capability` does."""
    assert meta.LEAD_RETRIEVAL_IMPLEMENTED is True
    assert issubclass(GraphLeadRetriever, object)
    for adapter in (GraphLeadRetriever(_tokens()), RecordedLeadRetriever()):
        assert isinstance(adapter, meta.LeadRetriever), (
            "both implementations satisfy the Protocol — a seam with one is untested"
        )
        assert adapter.name
    assert graph.PROVIDER == meta.GRAPH_PROVIDER, "one name, defined in the seam"
