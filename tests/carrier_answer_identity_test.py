"""The answer leg's caller identity, its authenticity seam, and the explicit carrier claim.

**WHAT THIS FILE IS TRYING TO CATCH**, and each one is a defect that shipped:

1. **The state drop.** `plivo_answer` took only the path ref, so the carrier's own
   parameters were structurally unreachable — not merely unread. The route now injects
   `Request`, reads the calling party through a per-carrier table, and mints it onto the
   stream URL as a claim the worker reads back. Driven end to end here, with the table's
   Plivo row filled by the TEST rather than by a guess in the source.
2. **A vendor name invented under pressure.** `www.plivo.com` is egress-blocked from this
   container (re-measured 19 Sep 2026: `curl: (56) CONNECT tunnel failed, response 403`,
   HTTP code `000`), so no Plivo parameter name, egress range or signature header may
   appear in our source. The founder's brief named `From`, `CallUUID` and
   `X-Plivo-Signature-V2`; `test_no_unverified_vendor_name_has_been_written_into_the_seam`
   is what keeps a plausible name from becoming a shipped one (D-631).
3. **Two spellings of one wire contract.** The claim's parameter names are declared in two
   deployables that may never import each other; this is the only place they can be
   compared.
4. **A `known` state with nothing behind it.** `apps/api/worker/tools.py:150` lets an agent
   tell a caller their number was suppressed only on `state == "known"`, so every path that
   can produce that word is driven, including the ones that must NOT produce it: a claim
   with no number, and two sources that disagree.
5. **Hard rule 6.** The number is carried and never logged, on both legs.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, ClassVar, cast, get_type_hints
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree.ElementTree import fromstring

import carrier_routes
import pytest
from apps.api.core.settings import get_settings
from calevate_shared.engine import owned_runtime_agent_ref
from calevate_shared.worker_api import CallerIdentityState
from httpx import ASGITransport, AsyncClient
from loguru import logger
from main import app as voice_app
from voice_worker import carrier

STREAM_BASE = "wss://calevate-pipecat-worker.example.invalid/ws"
CALLER = "+919876500011"

#: A contract row with a calling-party parameter filled in — i.e. what ONE founder reading
#: of `docs/evidence/carrier-caller-identity.md` §5(d) turns the shipped row into.
#:
#: **THE NAMES HERE ARE DELIBERATELY NOT PLAUSIBLE ONES.** `caller_param_a` cannot be
#: mistaken for a vendor fact by a future reader skimming this file, which a row spelling
#: `From` could. What is under test is the MECHANISM; the vendor's word for it is the one
#: thing this container cannot supply.
FILLED = replace(
    carrier_routes.CARRIER_ANSWER_CONTRACT[carrier_routes.ANSWER_CARRIER],
    calling_party=("caller_param_a", "caller_param_b"),
    calling_party_evidence_class="VENDOR-PUBLISHED",
    calling_party_evidence="a test fixture standing in for a read page",
)


@pytest.fixture
def stream_base(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`PIPECAT_STREAM_BASE_URL` set, through the environment the deployment really reads."""
    monkeypatch.setenv("PIPECAT_STREAM_BASE_URL", STREAM_BASE)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def filled_contract(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The table with its calling-party cell answered, which is the only missing half."""
    monkeypatch.setattr(
        carrier_routes,
        "CARRIER_ANSWER_CONTRACT",
        {carrier_routes.ANSWER_CARRIER: FILLED},
    )
    yield


async def _request(
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> Any:
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as client:
        return await client.request(method, path, headers=headers, content=content)


def _stream_url_of(body: str) -> str:
    (stream,) = list(fromstring(body))
    assert stream.text is not None
    return stream.text


def _claim_of(body: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(_stream_url_of(body)).query)


# --------------------------------------------------------------------------------------
# 1. Hard rule 11: what the seam is allowed to claim about the vendor.
# --------------------------------------------------------------------------------------


def test_the_shipped_plivo_row_is_unknown_in_every_cell_it_cannot_verify() -> None:
    """An empty cell means "nobody has read the page", and it must SAY so.

    The evidence class is what stops the next reader inheriting a conclusion instead of the
    evidence: a blank `calling_party` with a `VENDOR-PUBLISHED` class beside it would be a
    not-finding recorded as a vendor fact, which is exactly D-631.
    """
    row = carrier_routes.CARRIER_ANSWER_CONTRACT[carrier_routes.ANSWER_CARRIER]

    assert row.calling_party == ()
    assert row.source_ip_allowlist == ()
    assert row.signature_header is None
    assert row.echoes_stream_parameters is None
    for evidence_class, evidence in (
        (row.calling_party_evidence_class, row.calling_party_evidence),
        (row.source_ip_evidence_class, row.source_ip_evidence),
        (row.signature_evidence_class, row.signature_evidence),
    ):
        assert evidence_class == "UNKNOWN"
        assert "UNKNOWN" in evidence
        # The evidence must point somewhere a human can go and close it.
        assert "egress-blocked" in evidence or "docs/evidence/" in evidence


def test_no_unverified_vendor_name_has_been_written_into_the_seam() -> None:
    """The three names the brief supplied are plausible, unread, and must stay out.

    This asserts on the SOURCE rather than on the table, because the failure this guards
    against is somebody hard-coding a parameter or a header in a branch that the table does
    not govern. The names may appear in prose that says they are unverified — which is why
    the match is on a code-shaped context (quoted string or attribute), not on the word.
    """
    for module in (carrier_routes, carrier):
        source = inspect.getsource(module)
        for name in ("From", "CallUUID", "X-Plivo-Signature-V2"):
            for quoted in (f'"{name}"', f"'{name}'"):
                assert quoted not in source, (
                    f"{module.__name__} hard-codes {name!r}, a vendor fact nobody has read "
                    "(www.plivo.com is egress-blocked here — hard rule 11, D-631)"
                )


def test_the_answer_leg_speaks_the_one_state_vocabulary_that_reaches_the_wire() -> None:
    """Three modules, one literal. The tool wire spells the verdict, so a fourth spelling
    would be an opt-out refusal nobody could read (`apps/api/worker/tools.py:150`)."""
    assert carrier.CallerIdentityState is CallerIdentityState
    assert get_type_hints(carrier_routes.AnswerCallerIdentity)["state"] is CallerIdentityState


def test_the_two_deployables_spell_the_claim_parameters_the_same_way() -> None:
    """`carrier_routes` mints the query and `voice_worker.carrier` reads it back, and
    neither may import the other (hard rule 3). This is the only place they can be
    compared — the same discipline `TELEPHONY_SAMPLE_RATE_HZ` already gets."""
    assert carrier_routes.CLAIM_CARRIER_PARAM == carrier.CLAIM_CARRIER_PARAM
    assert carrier_routes.CLAIM_CALLER_PARAM == carrier.CLAIM_CALLER_PARAM
    assert carrier_routes.CLAIM_CALLER_STATE_PARAM == carrier.CLAIM_CALLER_STATE_PARAM


# --------------------------------------------------------------------------------------
# 2. The answer route: what it extracts, and what it forwards.
# --------------------------------------------------------------------------------------


async def test_todays_answer_forwards_a_named_unknown_rather_than_a_silent_null(
    stream_base: None,
) -> None:
    """With no parameter name read, the claim still SAYS why — and carries no number."""
    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))

    response = await _request(f"/carrier/v1/plivo/answer/{ref}")

    assert response.status_code == 200
    claim = _claim_of(response.text)
    assert claim[carrier_routes.CLAIM_CARRIER_PARAM] == [carrier_routes.ANSWER_CARRIER]
    assert claim[carrier_routes.CLAIM_CALLER_STATE_PARAM] == ["unparsed_by_client"]
    assert carrier_routes.CLAIM_CALLER_PARAM not in claim
    # Nothing digit-shaped may reach a URL when there is no number to put there.
    assert not any(ch.isdigit() for ch in urlparse(_stream_url_of(response.text)).query)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("method", "headers", "content", "path_suffix"),
    [
        ("GET", None, None, f"?caller_param_a={CALLER.replace('+', '%2B')}"),
        (
            "POST",
            {"content-type": "application/x-www-form-urlencoded"},
            f"caller_param_a={CALLER.replace('+', '%2B')}".encode(),
            "",
        ),
    ],
    ids=["query", "form-body"],
)
async def test_a_declared_parameter_is_read_and_forwarded_on_either_http_method(
    method: str,
    headers: dict[str, str] | None,
    content: bytes | None,
    path_suffix: str,
    stream_base: None,
    filled_contract: None,
) -> None:
    """The state drop, closed. UNKNOWN 2 (GET or POST?) is why both are driven.

    This is the assertion the whole change exists to make: the carrier's HTTP request into
    our own process carries the calling party, and it now survives into the stream URL
    instead of being thrown away one line before it was minted.
    """
    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))

    response = await _request(
        f"/carrier/v1/plivo/answer/{ref}{path_suffix}",
        method=method,
        headers=headers,
        content=content,
    )

    assert response.status_code == 200
    claim = _claim_of(response.text)
    assert claim[carrier_routes.CLAIM_CALLER_STATE_PARAM] == ["known"]
    assert claim[carrier_routes.CLAIM_CALLER_PARAM] == [CALLER]


async def test_a_declared_parameter_that_arrives_empty_is_the_carriers_own_answer(
    stream_base: None,
    filled_contract: None,
) -> None:
    """`withheld_by_carrier`, not `unparsed_by_client`: we asked and it said nothing.

    The two are different facts with different owners and the whole point of the state
    vocabulary is that a reader can tell them apart.
    """
    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))

    response = await _request(f"/carrier/v1/plivo/answer/{ref}?caller_param_a=")

    claim = _claim_of(response.text)
    assert claim[carrier_routes.CLAIM_CALLER_STATE_PARAM] == ["withheld_by_carrier"]
    assert carrier_routes.CLAIM_CALLER_PARAM not in claim


async def test_the_second_declared_name_is_tried_when_the_first_is_absent(
    stream_base: None,
    filled_contract: None,
) -> None:
    """A carrier that renames its parameter is a row edit, not a code change."""
    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))

    response = await _request(f"/carrier/v1/plivo/answer/{ref}?caller_param_b={CALLER[1:]}")

    claim = _claim_of(response.text)
    assert claim[carrier_routes.CLAIM_CALLER_STATE_PARAM] == ["known"]
    assert claim[carrier_routes.CLAIM_CALLER_PARAM] == [CALLER[1:]]


async def test_the_body_is_not_read_while_no_parameter_name_is_declared(
    stream_base: None,
) -> None:
    """Hard rule 3's budget on this route is STRUCTURAL, and this is what keeps it so.

    The handler's whole argument for having no third ack series is that it has no
    dependency that can make it slow. Reading a body nobody has a name to look in would
    spend that for nothing — so the read is gated on the table, and this proves the gate by
    making the read explode.
    """
    from starlette.requests import Request as StarletteRequest

    original = StarletteRequest.body

    async def _forbidden(self: Any) -> bytes:
        raise AssertionError("the answer route read a body with no parameter declared")

    StarletteRequest.body = _forbidden  # type: ignore[method-assign]
    try:
        ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))
        response = await _request(
            f"/carrier/v1/plivo/answer/{ref}",
            method="POST",
            headers={"content-type": "application/x-www-form-urlencoded"},
            content=b"caller_param_a=%2B919876500011",
        )
    finally:
        StarletteRequest.body = original  # type: ignore[method-assign]

    assert response.status_code == 200


async def test_the_answer_leg_logs_the_state_and_never_the_number(
    stream_base: None,
    filled_contract: None,
) -> None:
    """Hard rule 6. The number is carried on a URL we mint and is in NO line we write."""
    lines: list[str] = []
    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))
    sink = logger.add(lambda message: lines.append(str(message)), level="DEBUG")
    import logging

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record) + repr(getattr(record, "__dict__", {})))

    handler = _Capture()
    logging.getLogger().addHandler(handler)
    try:
        response = await _request(
            f"/carrier/v1/plivo/answer/{ref}?caller_param_a={CALLER.replace('+', '%2B')}"
        )
    finally:
        logging.getLogger().removeHandler(handler)
        logger.remove(sink)

    assert response.status_code == 200
    # Percent-encoded in the URL (`urlencode` escapes the leading `+`), which is what the
    # worker's `parse_qsl` reverses — the round trip is asserted separately.
    assert CALLER.lstrip("+") in _stream_url_of(response.text)
    assert not any(CALLER in line or CALLER.lstrip("+") in line for line in lines)


# --------------------------------------------------------------------------------------
# 3. Authenticity (issue 2).
# --------------------------------------------------------------------------------------


def test_with_no_published_egress_range_the_method_is_none_and_says_so() -> None:
    """Not a fail-open dressed up: an empty allowlist enforced is an outage with no remedy
    available to an operator, and the remedy is a VENDOR FACT rather than a setting
    (`calevate_shared.config:396` makes the same argument)."""
    verdict = carrier_routes.verify_answer_source(carrier_routes.ANSWER_CARRIER, "203.0.113.9")

    assert verdict.ok and verdict.method == "none"
    assert "no source-ip allowlist" in verdict.reason


def test_a_carrier_with_no_row_at_all_is_reported_as_such() -> None:
    verdict = carrier_routes.verify_answer_source("some-new-carrier", "203.0.113.9")

    assert verdict.method == "none"
    assert "no row in CARRIER_ANSWER_CONTRACT" in verdict.reason


@pytest.mark.parametrize(
    ("source_ip", "ok", "reason"),
    [
        ("198.51.100.7", True, "source ip allowlisted"),
        ("203.0.113.9", False, "source ip not allowlisted"),
        (None, False, "client ip not established"),
    ],
)
def test_a_declared_allowlist_enforces_itself_with_no_switch_to_remember(
    source_ip: str | None,
    ok: bool,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DATA-DRIVEN, not flag-driven: the day the row holds an address, enforcement is on.

    The `None` case is its own reason string on purpose — "not allowlisted" is a vendor
    renumber and "client ip not established" is the EDGE, two different runbook entries
    that an unsigned caller cannot afford to have look alike (`engine_intake.verify_source`
    draws the same line).
    """
    monkeypatch.setattr(
        carrier_routes,
        "CARRIER_ANSWER_CONTRACT",
        {
            carrier_routes.ANSWER_CARRIER: replace(
                carrier_routes.CARRIER_ANSWER_CONTRACT[carrier_routes.ANSWER_CARRIER],
                source_ip_allowlist=("198.51.100.7",),
                source_ip_evidence_class="VENDOR-PUBLISHED",
            )
        },
    )

    verdict = carrier_routes.verify_answer_source(carrier_routes.ANSWER_CARRIER, source_ip)

    assert verdict.ok is ok
    assert verdict.method == "source_ip"
    assert verdict.reason == reason


async def test_a_request_from_outside_a_declared_allowlist_mints_no_stream_url(
    stream_base: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal comes BEFORE the URL, and it looks exactly like an unknown ref.

    A distinct status or sentence would confirm to a prober that the ref it holds is real
    and only its address is wrong — which is the half worth not confirming. The two are
    told apart in the log, where only an operator reads.
    """
    monkeypatch.setattr(
        carrier_routes,
        "CARRIER_ANSWER_CONTRACT",
        {
            carrier_routes.ANSWER_CARRIER: replace(
                carrier_routes.CARRIER_ANSWER_CONTRACT[carrier_routes.ANSWER_CARRIER],
                source_ip_allowlist=("198.51.100.7",),
            )
        },
    )
    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))

    refused = await _request(
        f"/carrier/v1/plivo/answer/{ref}", headers={"cf-connecting-ip": "203.0.113.9"}
    )
    allowed = await _request(
        f"/carrier/v1/plivo/answer/{ref}", headers={"cf-connecting-ip": "198.51.100.7"}
    )

    assert refused.status_code == 404
    assert "wss://" not in refused.text
    assert allowed.status_code == 200


# --------------------------------------------------------------------------------------
# 4. The worker's side of the claim (issue 3).
# --------------------------------------------------------------------------------------


def test_the_url_this_service_mints_round_trips_through_both_worker_readers() -> None:
    """The route token and the claim travel on ONE URL and must not collide.

    `bot._route_token` reads `path.rsplit("/", 1)[-1]`, so a claim in a second PATH segment
    would have silently re-routed every call to a token that is not an agent ref. The claim
    is in the QUERY, which is not part of the path — asserted here rather than reasoned
    about, because the two readers live in files that never see each other.
    """
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    ref = owned_runtime_agent_ref(str(tenant_id), str(agent_id))

    url = carrier_routes.plivo_stream_url(
        STREAM_BASE,
        ref,
        carrier=carrier_routes.ANSWER_CARRIER,
        caller=carrier_routes.AnswerCallerIdentity(state="known", ground="test", e164=CALLER),
    )

    token = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    assert carrier.route_of(token) == carrier.CallRoute(tenant_id=tenant_id, agent_id=agent_id)

    claim = carrier.claim_from_stream_url(url)
    assert claim.present and claim.carrier == "plivo"
    assert claim.caller is not None and claim.caller.is_known
    assert claim.caller.e164 == CALLER


def test_a_socket_with_no_claim_is_absent_rather_than_wrong() -> None:
    """Absent is not disagreeing, and it is not a refusal on its own: an older answer
    route, a test fixture, or a front door that strips the query all land here."""
    assert carrier.claim_from_stream_url(f"{STREAM_BASE}/token").present is False


@pytest.mark.parametrize(
    ("query", "expected_state"),
    [
        ("caller_state=withheld_by_carrier", "withheld_by_carrier"),
        ("caller_state=not_read", "not_read"),
        # A word nobody minted is dropped rather than coerced — anything can connect to a
        # WebSocket URL, so every value here is attacker-controlled.
        ("caller_state=definitely_known&caller=%2B919000000000", None),
    ],
)
def test_a_claimed_state_is_taken_only_when_it_is_one_of_ours(
    query: str, expected_state: str | None
) -> None:
    claim = carrier.claim_from_stream_url(f"{STREAM_BASE}/token?{query}")

    if expected_state is None:
        assert claim.caller is None
    else:
        assert claim.caller is not None and claim.caller.state == expected_state


def test_a_claimed_known_with_no_number_may_not_authorise_a_suppression() -> None:
    """The sentence this stops is the one an agent says to a caller.

    `apps/api/worker/tools.py:150` writes the opt-out — and lets the agent claim it — only
    on `state == "known"`. A `known` with nothing behind it is exactly the case where an
    agent would say "you're off the list" and nothing would have been suppressed.
    """
    claim = carrier.claim_from_stream_url(f"{STREAM_BASE}/token?caller_state=known")

    assert claim.caller is not None
    assert claim.caller.state == "unparsed_by_client"
    assert not claim.caller.is_known
    assert "not usable" in claim.caller.ground


def test_a_claim_that_names_only_the_carrier_is_still_a_claim() -> None:
    claim = carrier.claim_from_stream_url(f"{STREAM_BASE}/token?carrier=exotel")

    assert claim.present and claim.carrier == "exotel" and claim.caller is None


# --------------------------------------------------------------------------------------
# 5. The fold: what happens when the claim and the detection disagree.
# --------------------------------------------------------------------------------------


def _known(e164: str) -> carrier.CallerIdentity:
    return carrier.CallerIdentity(state="known", ground="test known", e164=e164)


def _absent(state: CallerIdentityState) -> carrier.CallerIdentity:
    return carrier.CallerIdentity(state=state, ground=f"test {state}")


def test_no_claim_leaves_the_detection_exactly_as_it_was() -> None:
    detected = _absent("unparsed_by_client")

    assert carrier.fold_caller_identity(None, detected) is detected


def test_two_legs_that_agree_produce_one_known_naming_both() -> None:
    folded = carrier.fold_caller_identity(_known(CALLER), _known(CALLER))

    assert folded.is_known and folded.e164 == CALLER
    assert "agree" in folded.ground


def test_two_legs_that_name_different_callers_key_nothing_at_all() -> None:
    """**THE DISAGREEMENT IS NOT A TIE TO BREAK.** Keying a DNC suppression on the loser
    would suppress a stranger, so the number is DROPPED and `is_known` goes False — which
    is what makes `apps/api/worker/tools.py` refuse to let the agent claim success.

    ⚠ `unparsed_by_client` is the closest of four CLOSED words and is not the right one;
    the right word is a fifth ("two sources disagreed") and `CallerIdentityState` lives in
    `packages/shared`, outside this change's fence. The ground carries the distinction.
    """
    folded = carrier.fold_caller_identity(_known(CALLER), _known("+919876500099"))

    assert not folded.is_known
    assert folded.e164 is None
    assert "DIFFERENT" in folded.ground
    # Hard rule 6: the two numbers are recoverable from the carrier's CDR, not from a
    # string this module hands to a log line.
    assert CALLER not in folded.ground


def test_the_leg_that_has_a_number_wins_and_the_other_leg_is_recorded() -> None:
    """The case that closes the gap: on Plivo the detection is structurally
    `unparsed_by_client`, so the answer leg is the only one that can say anything."""
    folded = carrier.fold_caller_identity(_known(CALLER), _absent("unparsed_by_client"))

    assert folded.is_known and folded.e164 == CALLER
    assert "the other leg said" in folded.ground

    reverse = carrier.fold_caller_identity(_absent("not_read"), _known(CALLER))
    assert reverse.is_known and reverse.e164 == CALLER


@pytest.mark.parametrize(
    ("claimed", "detected", "winner"),
    [
        ("withheld_by_carrier", "unparsed_by_client", "withheld_by_carrier"),
        ("not_read", "unparsed_by_client", "unparsed_by_client"),
        ("not_read", "withheld_by_carrier", "withheld_by_carrier"),
        ("not_read", "not_read", "not_read"),
    ],
)
def test_the_more_informative_absence_wins_when_neither_leg_has_a_number(
    claimed: CallerIdentityState, detected: CallerIdentityState, winner: CallerIdentityState
) -> None:
    """A carrier's own "withheld" outranks our "we could not ask", which outranks
    "nobody asked" — because only the last one may ever mean unasked."""
    folded = carrier.fold_caller_identity(_absent(claimed), _absent(detected))

    assert folded.state == winner
    assert "the other leg said" in folded.ground


# --------------------------------------------------------------------------------------
# 6. Claim vs detection on the socket itself.
# --------------------------------------------------------------------------------------


class _SocketSaying:
    """A websocket that says `connected`, then one start message (`runner/utils.py:185-208`)."""

    headers: ClassVar[dict[str, str]] = {}

    def __init__(self, start_message: str) -> None:
        self._start = start_message

    def iter_text(self) -> Any:
        async def _messages() -> Any:
            yield '{"event": "connected"}'
            yield self._start

        return _messages()


PLIVO_START = '{"event": "start", "start": {"streamId": "s-1", "callId": "c-1"}}'
TWILIO_START = (
    '{"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1", "customParameters": {}}}'
)


async def test_an_explicit_claim_is_checked_against_the_detection_rather_than_replacing_it() -> (
    None
):
    """The detection is NOT deleted, and this is what still depends on it: the two ids.

    Without `start.streamId` and `start.callId` nothing can hang the leg up
    (`serializers/plivo.py:80-92`), so the claim can never be the only reader of the
    socket. What the claim buys is that a renamed handshake key becomes a refusal instead
    of a silently mis-serialised call.
    """
    claim = carrier.claim_from_stream_url(
        f"{STREAM_BASE}/token?carrier=plivo&caller_state=known&caller={CALLER}"
    )

    handshake = await carrier.read_plivo_handshake(_SocketSaying(PLIVO_START), claim=claim)

    assert handshake.stream_id == "s-1" and handshake.carrier_call_id == "c-1"
    # The fold: the socket said `unparsed_by_client`, the control plane had the number.
    assert handshake.caller.is_known and handshake.caller.e164 == CALLER


async def test_a_claim_that_disagrees_with_the_socket_refuses_the_call() -> None:
    """Fail closed. Serialising one protocol as another is a connected call with silence on
    it, and a mismatch is either a number bound to the wrong answer URL or somebody
    pretending to be a carrier. BLOCKER-1 means refusing costs nothing today."""
    claim = carrier.claim_from_stream_url(f"{STREAM_BASE}/token?carrier=plivo")

    with pytest.raises(carrier.CarrierClaimMismatchError) as refusal:
        await carrier.read_plivo_handshake(_SocketSaying(TWILIO_START), claim=claim)

    assert "plivo" in str(refusal.value) and "twilio" in str(refusal.value)
    # Distinguishable from a provisioning fault, which is a different page for a different
    # person — and still an `UnroutableCallError`, so no existing caller stops catching it.
    assert isinstance(refusal.value, carrier.UnroutableCallError)


async def test_a_claim_naming_another_carrier_is_believed_over_the_deployments_constant() -> None:
    """The control plane knows which carrier a number is on; this module holds a constant
    that is only a default. A claim of `twilio` must not be refused by a `plivo` constant —
    that would make the seam unusable the day D-05's Exotel arrives."""
    claim = carrier.claim_from_stream_url(f"{STREAM_BASE}/token?carrier=twilio")

    handshake = await carrier.read_plivo_handshake(_SocketSaying(TWILIO_START), claim=claim)

    assert handshake.stream_id == "MZ1" and handshake.carrier_call_id == "CA1"
    # Twilio's calling party IS mapped by the pinned client, from parameters the ANSWER
    # DOCUMENT supplies (`runner/utils.py:232,240-241`) — none supplied here.
    assert handshake.caller.state == "withheld_by_carrier"


async def test_with_no_claim_the_deployments_own_carrier_is_still_enforced() -> None:
    """Every existing caller keeps its behaviour, including the refusal it relied on."""
    with pytest.raises(carrier.UnroutableCallError) as refusal:
        await carrier.read_plivo_handshake(_SocketSaying(TWILIO_START))

    assert not isinstance(refusal.value, carrier.CarrierClaimMismatchError)


# --------------------------------------------------------------------------------------
# 7. The hop into the session — what makes the four in-call tools reachable at all.
# --------------------------------------------------------------------------------------


async def test_the_verdict_is_carried_into_the_session_and_not_merely_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**WITHOUT THIS ARGUMENT THE OPT-OUT TOOL IS NOT ADVERTISED AT ALL.**

    `assemble_call` takes `caller=None` by default and does not offer opt-out, book /
    cancel call-back or handoff to the model when it is absent — four tools that can only
    fail waste a conversational turn. So a caller on an owned_runtime call could not opt
    out, which is the compliance hole this round exists to close. Driven against a fake
    `start_session` because what is under test is the HOP, not the assembly.
    """
    seen: dict[str, Any] = {}

    async def _fake_start_session(_api: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return object()

    def _no_arming(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(carrier, "start_session", _fake_start_session)
    monkeypatch.setattr(carrier, "arm_first_turn", _no_arming)
    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))
    identity = _known(CALLER)

    await carrier.start_carrier_call(
        cast(Any, object()),
        token=ref,
        call_id="call-1",
        direction="inbound",
        transport=cast(Any, object()),
        credentials=cast(Any, object()),
        caller=identity,
        sink=cast(Any, object()),
        fetcher=cast(Any, object()),
    )

    assert seen["caller"] is identity


async def test_a_call_with_no_verdict_carries_the_honest_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`None` must not reach the session as `None`: `not_read` is the state that SAYS
    nobody asked, and it is the only word allowed to mean that."""
    seen: dict[str, Any] = {}

    async def _fake_start_session(_api: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(carrier, "start_session", _fake_start_session)
    monkeypatch.setattr(carrier, "arm_first_turn", lambda *a, **k: None)

    await carrier.start_carrier_call(
        cast(Any, object()),
        token=owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4())),
        call_id="call-2",
        direction="inbound",
        transport=cast(Any, object()),
        credentials=cast(Any, object()),
        sink=cast(Any, object()),
        fetcher=cast(Any, object()),
    )

    assert seen["caller"].state == "not_read"
    assert not seen["caller"].is_known


def test_a_carrier_we_have_no_contract_for_says_so_rather_than_guessing() -> None:
    """The arm that runs when the answer request comes from a carrier nobody has written
    a parameter contract for — a new provider, or a misrouted request.

    It must return the `unparsed_by_client` STATE with its ground, not `None` and not a
    guess at which parameter holds the calling party. Guessing here would put an
    unverified number into the identity of a live call; returning a state keeps the call
    explainable, which is the whole reason this function answers in states at all.
    """
    identity = carrier_routes.caller_identity_from_answer_request(
        "a-carrier-that-does-not-exist", {"From": "+919876500001"}
    )
    assert identity.state == "unparsed_by_client"
    assert identity.ground, "a state with no ground is not explainable"
    assert "a-carrier-that-does-not-exist" not in str(identity.e164 or "")
