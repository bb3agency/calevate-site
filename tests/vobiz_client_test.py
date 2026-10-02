"""`VobizCarrier` against a transport stub: the requests it sends and how it reads answers.

Every expectation is the shape `vobiz-findings/mirror/pages/` documents; the stub answers in
those shapes and records what it was sent, so a path, a header or a body field that drifts
from the documentation fails here rather than on a live dial.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine import vendor_http
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.engine.vobiz import VobizCarrier, application_name, parse_cdr, parse_event

pytestmark = pytest.mark.anyio

AUTH_ID = "MA_TESTACCT"
BASE = "https://api.vobiz.ai/api/v1"

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _instant)


def _carrier(handler: Handler) -> VobizCarrier:
    return VobizCarrier(
        auth_id=AUTH_ID,
        auth_token="tok",
        base_url=BASE,
        client=httpx.AsyncClient(
            base_url=BASE,
            headers={"X-Auth-ID": AUTH_ID, "X-Auth-Token": "tok"},
            transport=httpx.MockTransport(handler),
        ),
    )


class _Recorder:
    def __init__(self, *responses: httpx.Response) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


async def _dial(carrier: VobizCarrier) -> str:
    placed = await carrier.place_call(
        from_e164="+911140000000",
        to_e164="+919876543210",
        answer_url="https://hooks.example/carrier/v1/vobiz/answer/r/outbound/c",
        hangup_url="https://hooks.example/carrier/v1/vobiz/events/r/outbound/c",
        ring_url="https://hooks.example/carrier/v1/vobiz/events/r/outbound/c",
        time_limit_s=660,
    )
    return placed.carrier_call_id


async def test_call_create_sends_the_documented_request() -> None:
    stub = _Recorder(httpx.Response(200, json={"message": "Call fired", "request_uuid": "u-1"}))
    assert await _dial(_carrier(stub)) == "u-1"

    (request,) = stub.requests
    assert request.method == "POST"
    # PascalCase with the trailing slash: a lowercase or slashless path answers 401.
    assert request.url.raw_path.decode() == f"/api/v1/Account/{AUTH_ID}/Call/"
    assert request.headers["X-Auth-ID"] == AUTH_ID
    assert request.headers["X-Auth-Token"] == "tok"
    body = json.loads(request.content)
    assert body == {
        "from": "+911140000000",
        "to": "+919876543210",
        "answer_url": "https://hooks.example/carrier/v1/vobiz/answer/r/outbound/c",
        "answer_method": "POST",
        "hangup_url": "https://hooks.example/carrier/v1/vobiz/events/r/outbound/c",
        "hangup_method": "POST",
        "ring_url": "https://hooks.example/carrier/v1/vobiz/events/r/outbound/c",
        "ring_method": "POST",
        "time_limit": 660,
    }


async def test_a_throttled_dial_is_retried_and_then_placed() -> None:
    stub = _Recorder(
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"request_uuid": "u-2"}),
    )
    assert await _dial(_carrier(stub)) == "u-2"
    assert len(stub.requests) == 2


async def test_a_dial_throttled_to_exhaustion_is_rate_limited_and_not_placed() -> None:
    stub = _Recorder(httpx.Response(429))
    with pytest.raises(ProblemError) as raised:
        await _dial(_carrier(stub))
    assert raised.value.code == "engine_rate_limited"
    assert len(stub.requests) == vendor_http.THROTTLE_MAX_ATTEMPTS


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
async def test_a_documented_refusal_proves_no_line_was_seized(status: int) -> None:
    stub = _Recorder(httpx.Response(status, json={"error": "refused"}))
    with pytest.raises(EngineRejectedError) as raised:
        await _dial(_carrier(stub))
    assert raised.value.request_refused is True
    assert len(stub.requests) == 1, "a refusal must not be retried"


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_a_server_error_is_never_retried_and_never_reads_as_refused(status: int) -> None:
    stub = _Recorder(httpx.Response(status))
    with pytest.raises(EngineRejectedError) as raised:
        await _dial(_carrier(stub))
    assert raised.value.request_refused is False
    assert len(stub.requests) == 1


async def test_a_timeout_is_unreachable_and_not_retried() -> None:
    attempts: list[httpx.Request] = []

    def boom(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProblemError) as raised:
        await _dial(_carrier(boom))
    assert raised.value.code == "engine_unreachable"
    assert len(attempts) == 1


async def test_402_is_a_refusal_only_on_call_create() -> None:
    """The widening is per call site: the shared ladder's default set is unchanged."""
    assert 402 not in vendor_http.REQUEST_REFUSED_STATUSES
    stub = _Recorder(httpx.Response(402))
    with pytest.raises(EngineRejectedError) as raised:
        await _carrier(stub).transfer("u-1", redirect_url="https://hooks.example/t")
    assert raised.value.request_refused is False


async def test_an_accepted_dial_without_a_call_id_is_not_a_refusal() -> None:
    stub = _Recorder(httpx.Response(200, json={"message": "Call fired"}))
    with pytest.raises(ProblemError) as raised:
        await _dial(_carrier(stub))
    assert raised.value.code == "engine_bad_response"


async def test_hang_up_reads_204_as_ended_and_404_as_nothing_to_end() -> None:
    stub = _Recorder(httpx.Response(204), httpx.Response(404, json={"error": "gone"}))
    carrier = _carrier(stub)
    assert await carrier.hang_up("u-1") is True
    assert await carrier.hang_up("u-1") is False
    assert stub.requests[0].method == "DELETE"
    assert stub.requests[0].url.raw_path.decode() == f"/api/v1/Account/{AUTH_ID}/Call/u-1/"


async def test_hang_up_raises_on_any_other_failure() -> None:
    with pytest.raises(EngineRejectedError):
        await _carrier(_Recorder(httpx.Response(500))).hang_up("u-1")


async def test_transfer_redirects_the_a_leg() -> None:
    stub = _Recorder(httpx.Response(202, json={"message": "call transferred"}))
    await _carrier(stub).transfer("u-1", redirect_url="https://hooks.example/transfer/tok")
    (request,) = stub.requests
    assert request.url.raw_path.decode() == f"/api/v1/Account/{AUTH_ID}/Call/u-1/"
    assert json.loads(request.content) == {
        "legs": "aleg",
        "aleg_url": "https://hooks.example/transfer/tok",
        "aleg_method": "POST",
    }


def _cdr(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "uuid": "u-1",
        "duration": 65,
        "billsec": 58,
        "answer_time": "2026-05-11T06:59:31Z",
        "end_time": "2026-05-11T07:00:29Z",
        "cost": 0.3,
        "total_cost": 0.36,
        "currency": "INR",
        "hangup_cause": "NORMAL_CLEARING",
    }
    data.update(overrides)
    return data


async def test_a_cdr_is_read_with_its_cost_as_an_exact_decimal() -> None:
    # The raw bytes carry a number a binary float cannot hold exactly.
    raw = (
        b'{"success": true, "data": {"uuid": "u-1", "billsec": 58, "duration": 65, '
        b'"total_cost": 0.1000000000000000055511151231257827, "currency": "INR", '
        b'"answer_time": "2026-05-11T06:59:31Z", "end_time": "2026-05-11T07:00:29Z"}}'
    )
    stub = _Recorder(httpx.Response(200, content=raw, headers={"content-type": "application/json"}))
    cdr = await _carrier(stub).fetch_cdr("u-1")

    assert cdr is not None
    assert stub.requests[0].url.raw_path.decode() == f"/api/v1/Account/{AUTH_ID}/cdr/u-1"
    assert cdr.billed_seconds == 58
    assert cdr.duration_seconds == 65
    assert cdr.total_cost_inr == Decimal("0.1000000000000000055511151231257827")
    assert cdr.currency == "INR"
    assert cdr.answered_at == datetime(2026, 5, 11, 6, 59, 31, tzinfo=UTC)
    assert cdr.ended_at == datetime(2026, 5, 11, 7, 0, 29, tzinfo=UTC)


async def test_a_cdr_not_written_yet_is_none() -> None:
    assert await _carrier(_Recorder(httpx.Response(404))).fetch_cdr("u-1") is None


async def test_a_cdr_in_the_wrong_shape_is_refused() -> None:
    stub = _Recorder(httpx.Response(200, json={"success": True, "data": []}))
    with pytest.raises(ProblemError) as raised:
        await _carrier(stub).fetch_cdr("u-1")
    assert raised.value.code == "engine_bad_response"


def test_a_charge_in_another_currency_never_becomes_rupees() -> None:
    cdr = parse_cdr(_cdr(currency="USD", total_cost=Decimal("0.01")), carrier_call_id="u-1")
    assert cdr.total_cost_inr is None
    assert cdr.currency == "USD"
    assert parse_cdr(_cdr(currency=None), carrier_call_id="u-1").total_cost_inr is None


def test_a_time_without_a_zone_is_not_assumed_utc() -> None:
    cdr = parse_cdr(_cdr(answer_time="2026-05-11 06:59:31", end_time=None), carrier_call_id="u")
    assert cdr.answered_at is None
    assert cdr.ended_at is None


def test_malformed_cdr_numbers_read_as_nothing() -> None:
    cdr = parse_cdr(
        _cdr(billsec=True, duration="65", total_cost="not-a-number"), carrier_call_id="u"
    )
    assert cdr.billed_seconds == 0
    assert cdr.duration_seconds == 0
    assert cdr.total_cost_inr is None
    assert parse_cdr(_cdr(total_cost=36), carrier_call_id="u").total_cost_inr == Decimal(36)
    assert parse_cdr(_cdr(total_cost=[1]), carrier_call_id="u").total_cost_inr is None
    assert parse_cdr(_cdr(billsec=Decimal("12")), carrier_call_id="u").billed_seconds == 12


@pytest.mark.parametrize(
    ("fields", "kind", "status"),
    [
        ({"Event": "Ring"}, "ringing", "ringing"),
        ({"Event": "StartApp"}, "answered", "in_progress"),
        ({"Event": "Hangup", "HangupCause": "NORMAL_CLEARING"}, "hangup", "completed"),
        ({"Event": "Hangup", "HangupCause": "USER_BUSY"}, "hangup", "busy"),
        ({"Event": "Hangup", "HangupCause": "NO_ANSWER"}, "hangup", "no_answer"),
        ({"Event": "Hangup", "HangupCause": "ORIGINATOR_CANCEL"}, "hangup", "no_answer"),
        ({"Event": "Hangup", "HangupCause": "CALL_REJECTED"}, "hangup", "failed"),
        ({"Event": "Hangup"}, "hangup", "failed"),
        # The numeric code when the cause name is not one we map (`hangup-causes.md`).
        ({"Event": "Hangup", "HangupCauseCode": "4010"}, "hangup", "completed"),
        ({"Event": "Hangup", "HangupCauseCode": "4000"}, "hangup", "completed"),
        ({"Event": "Hangup", "HangupCauseCode": "3010"}, "hangup", "busy"),
        ({"Event": "Hangup", "HangupCauseCode": "6010"}, "hangup", "no_answer"),
        ({"Event": "Hangup", "HangupCauseCode": "5030"}, "hangup", "failed"),
        ({"Event": "Hangup", "HangupCauseCode": "not-a-number"}, "hangup", "failed"),
        # An Application's hangup callback carries no `Event` (`applications.md:60-65`).
        ({"HangupCause": "NORMAL_CLEARING"}, "hangup", "completed"),
        ({"EndTime": "2026-10-02 10:00:00"}, "hangup", "failed"),
        ({}, "other", None),
        ({"Event": "MachineDetection"}, "machine", "voicemail"),
        ({"Event": "StartStream"}, "stream", None),
        ({"Event": "StopStream"}, "stream", None),
        ({"Event": "Redirect"}, "other", None),
    ],
)
def test_every_callback_maps_to_our_vocabulary(
    fields: dict[str, str], kind: str, status: str | None
) -> None:
    event = parse_event({"CallUUID": "u-1", "Direction": "outbound", **fields})
    assert event is not None
    assert event.kind == kind
    assert event.status == status
    assert event.carrier_call_id == "u-1"
    assert event.direction == "outbound"


def test_a_callback_naming_no_call_is_dropped_and_direction_is_never_guessed() -> None:
    assert parse_event({"Event": "Hangup"}) is None
    event = parse_event({"CallUUID": "u-1", "Event": "Ring", "Direction": "sideways"})
    assert event is not None and event.direction is None
    inbound = _carrier(_Recorder(httpx.Response(200))).parse_event(
        {"CallUUID": "u-2", "Event": "StartApp", "Direction": "inbound"}
    )
    assert inbound is not None and inbound.direction == "inbound"


async def test_bind_creates_one_application_per_agent_and_attaches_the_number() -> None:
    stub = _Recorder(
        httpx.Response(200, json={"objects": []}),
        httpx.Response(201, json={"app_id": 12345678901234567, "message": "created"}),
        httpx.Response(200, json={"message": "Number attached to application"}),
    )
    app_id = await _carrier(stub).bind_number(
        "+911140000000",
        answer_url="https://hooks.example/a",
        hangup_url="https://hooks.example/e",
        label="0199a0b0-agent",
    )
    assert app_id == "12345678901234567"
    listing, create, attach = stub.requests
    assert listing.method == "GET"
    assert listing.url.params["limit"] == "100"
    assert create.url.raw_path.decode() == f"/api/v1/Account/{AUTH_ID}/Application/"
    assert json.loads(create.content) == {
        "app_name": "calevate-0199a0b0-agent",
        "answer_url": "https://hooks.example/a",
        "answer_method": "POST",
        "hangup_url": "https://hooks.example/e",
        "hangup_method": "POST",
    }
    # The number is URL-encoded in the path, `+` -> `%2B`.
    assert attach.url.raw_path.decode() == (
        f"/api/v1/Account/{AUTH_ID}/numbers/%2B911140000000/application"
    )
    assert json.loads(attach.content) == {"application_id": "12345678901234567"}


async def test_a_rebind_updates_the_existing_application() -> None:
    stub = _Recorder(
        httpx.Response(
            200,
            json={"objects": [{"app_id": "77", "app_name": application_name("agent-1")}]},
        ),
        httpx.Response(200, json={"message": "changed"}),
        httpx.Response(200, json={"message": "attached"}),
    )
    app_id = await _carrier(stub).bind_number(
        "+911140000000", answer_url="https://a", hangup_url="https://e", label="agent-1"
    )
    assert app_id == "77"
    update = stub.requests[1]
    assert update.url.raw_path.decode() == f"/api/v1/Account/{AUTH_ID}/Application/77/"
    assert "app_name" not in json.loads(update.content)


async def test_the_application_search_pages_and_has_a_ceiling() -> None:
    other = [{"app_id": str(i), "app_name": f"other-{i}"} for i in range(100)]
    stub = _Recorder(httpx.Response(200, json={"objects": other}))
    with pytest.raises(ProblemError) as raised:
        await _carrier(stub).bind_number(
            "+911140000000", answer_url="https://a", hangup_url="https://e", label="x"
        )
    assert raised.value.code == "carrier_application_listing_too_long"
    offsets = [r.url.params["offset"] for r in stub.requests]
    assert offsets[:2] == ["0", "100"]


async def test_an_application_id_that_is_missing_is_refused() -> None:
    stub = _Recorder(
        httpx.Response(200, json={"objects": []}),
        httpx.Response(201, json={"message": "created"}),
    )
    with pytest.raises(ProblemError) as raised:
        await _carrier(stub).bind_number(
            "+911140000000", answer_url="https://a", hangup_url="https://e", label="x"
        )
    assert raised.value.code == "engine_bad_response"


def test_application_names_are_legal_at_the_carrier() -> None:
    assert application_name("ab:cd/ef gh_ij-k") == "calevate-ab-cd-ef-gh_ij-k"


async def test_unbind_detaches_and_treats_an_unknown_number_as_done() -> None:
    stub = _Recorder(httpx.Response(404, json={"error": "Number not in your account"}))
    await _carrier(stub).unbind_number("+911140000000")
    (request,) = stub.requests
    assert request.method == "DELETE"
    assert request.url.raw_path.decode().endswith("/numbers/%2B911140000000/application")


async def test_probe_reads_the_account_and_never_writes() -> None:
    accepted = _Recorder(httpx.Response(200, json={"auth_id": AUTH_ID}))
    assert await _carrier(accepted).probe() is True
    assert accepted.requests[0].method == "GET"
    assert accepted.requests[0].url.raw_path.decode() == "/api/v1/auth/me"
    assert await _carrier(_Recorder(httpx.Response(401))).probe() is False
    with pytest.raises(EngineRejectedError):
        await _carrier(_Recorder(httpx.Response(500))).probe()


async def test_without_credentials_every_request_is_refused_before_it_is_sent() -> None:
    carrier = VobizCarrier(auth_id=None, auth_token=None, base_url=BASE)
    assert carrier.configured() is False
    refusal = carrier.unavailable("place outbound calls")
    assert refusal is not None and refusal.code == "engine_not_configured"
    with pytest.raises(ProblemError) as raised:
        await carrier.hang_up("u-1")
    assert raised.value.code == "engine_not_configured"


async def test_a_configured_carrier_builds_its_own_authenticated_client() -> None:
    carrier = VobizCarrier(auth_id=AUTH_ID, auth_token="tok", base_url=BASE + "/")
    assert carrier.unavailable("anything") is None
    client = carrier._new_client()
    assert client.headers["X-Auth-ID"] == AUTH_ID
    assert str(client.base_url).rstrip("/") == BASE
    await client.aclose()


async def test_an_uninjected_carrier_opens_and_closes_one_client_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`get_carrier` builds a carrier per operation, so a client held by it would never be
    closed. Each request gets its own, closed when the request is done."""
    opened: list[httpx.AsyncClient] = []
    recorder = _Recorder(httpx.Response(200, json={"account": "ok"}))

    def _new_client(self: VobizCarrier) -> httpx.AsyncClient:
        client = httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(recorder))
        opened.append(client)
        return client

    monkeypatch.setattr(VobizCarrier, "_new_client", _new_client)
    carrier = VobizCarrier(auth_id=AUTH_ID, auth_token="tok", base_url=BASE)
    assert await carrier.probe() is True
    assert await carrier.probe() is True
    assert len(opened) == 2
    assert all(client.is_closed for client in opened)


async def test_a_remembered_binding_is_reused_only_when_it_is_this_agents() -> None:
    mine = application_name("agent-1")
    reused = _Recorder(
        httpx.Response(200, json={"app_id": "55", "app_name": mine}),
        httpx.Response(200, json={"message": "changed"}),
        httpx.Response(200, json={"message": "attached"}),
    )
    app_id = await _carrier(reused).bind_number(
        "+911140000000",
        answer_url="https://a",
        hangup_url="https://e",
        label="agent-1",
        known_binding_id="55",
    )
    assert app_id == "55"
    assert [r.method for r in reused.requests] == ["GET", "POST", "POST"]
    assert reused.requests[0].url.raw_path.decode() == f"/api/v1/Account/{AUTH_ID}/Application/55/"

    for first in (
        httpx.Response(200, json={"app_id": "55", "app_name": application_name("someone-else")}),
        httpx.Response(404, json={"error": "not found"}),
    ):
        searched = _Recorder(
            first,
            httpx.Response(200, json={"objects": []}),
            httpx.Response(201, json={"app_id": "56"}),
            httpx.Response(200, json={"message": "attached"}),
        )
        app_id = await _carrier(searched).bind_number(
            "+911140000000",
            answer_url="https://a",
            hangup_url="https://e",
            label="agent-1",
            known_binding_id="55",
        )
        assert app_id == "56", "another agent's application must never be repointed"

    with pytest.raises(EngineRejectedError):
        await _carrier(_Recorder(httpx.Response(500))).bind_number(
            "+911140000000",
            answer_url="https://a",
            hangup_url="https://e",
            label="agent-1",
            known_binding_id="55",
        )
