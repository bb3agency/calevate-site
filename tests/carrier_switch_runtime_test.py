"""voice-runtime's answer routes per carrier, and the source-address allowlist (D-662).

What this file catches:

1. **The switch decides what is DIALLED, not what is SERVED.** Both carriers' answer
   routes answer whatever `Settings.carrier` says, so a number still bound to the other
   carrier keeps ringing through.
2. **Vobiz reads the calling party from its own request** (`From`, VERIFIED-VENDOR-DOCS
   `vobiz-findings/mirror/pages/xml/request.md:30`), on a form POST and on a GET.
3. **An outbound answer names the person we rang** (`To`, `:31`), never our own number,
   and carries our call id under a MAC the worker verifies.
4. **Plivo's route is unchanged** — the same path, the same bytes, no body read.
5. **The allowlist** is the published list by default, an operator override at runtime,
   and a refusal that looks exactly like an unknown ref.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from xml.etree.ElementTree import fromstring

import carrier_routes
import pytest
from apps.api.core.settings import get_settings
from calevate_shared.carrier import VOBIZ_CALLBACK_IPS, answer_path
from calevate_shared.engine import owned_runtime_agent_ref
from calevate_shared.worker_api import (
    CALL_CLAIM_EXPIRES_PARAM,
    CALL_CLAIM_MAC_PARAM,
    CALL_DIRECTION_PARAM,
    CALL_ID_PARAM,
    CALLER_SEAL_PARAM,
    open_caller_claim,
    verify_call_claim,
)
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

STREAM_BASE = "wss://calevate-pipecat-worker.example.invalid/ws"
VOBIZ_IP = VOBIZ_CALLBACK_IPS[0]
STRANGER_IP = "203.0.113.9"
CALLER = "+919876500011"
OUR_NUMBER = "+918000000001"
CLAIM_KEY = "k" * 32
FORM = {"content-type": "application/x-www-form-urlencoded"}

Env = Callable[..., None]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    """The deployment's environment, read through `get_settings()` as an operator sets it."""
    monkeypatch.setenv("PIPECAT_STREAM_BASE_URL", STREAM_BASE)
    for name in (
        "VOBIZ_AUTH_TOKEN",
        "VOBIZ_SIGNATURE_REQUIRED",
        "VOBIZ_CALLBACK_IPS",
        "CARRIER_CLAIM_SECRET",
        "CARRIER",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    def apply(**values: str | None) -> None:
        for name, value in values.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def _ref() -> str:
    return owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))


async def _request(
    path: str,
    *,
    method: str = "POST",
    source_ip: str | None = VOBIZ_IP,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> Any:
    sent = dict(headers or {})
    if source_ip is not None:
        sent["cf-connecting-ip"] = source_ip
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as client:
        return await client.request(method, path, headers=sent, content=content)


def _claim(body: str) -> tuple[str, dict[str, str]]:
    (stream,) = list(fromstring(body))
    assert stream.text is not None
    url = stream.text
    return url, {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def _form(**fields: str) -> bytes:
    return "&".join(f"{k}={quote(v, safe='')}" for k, v in fields.items()).encode()


# --- 1. the switch and the served routes -------------------------------------------------


@pytest.mark.parametrize("switch", ["vobiz", "plivo"])
@pytest.mark.parametrize("carrier", ["vobiz", "plivo"])
async def test_every_carrier_is_answered_whatever_the_switch_says(
    carrier: str, switch: str, env: Env
) -> None:
    env(CARRIER=switch)

    response = await _request(answer_path(carrier, _ref()), method="GET")  # type: ignore[arg-type]

    assert response.status_code == 200
    _url, claim = _claim(response.text)
    assert claim[carrier_routes.CLAIM_CARRIER_PARAM] == carrier


@pytest.mark.parametrize("carrier", ["twilio", "VOBIZ", "plivo2"])
async def test_an_unknown_carrier_is_refused_like_an_unknown_ref(carrier: str, env: Env) -> None:
    ref = _ref()

    unknown_carrier = await _request(f"/carrier/v1/{carrier}/answer/{quote(ref, safe='')}")
    unknown_ref = await _request("/carrier/v1/vobiz/answer/not-a-ref")

    assert unknown_carrier.status_code == unknown_ref.status_code == 404
    assert unknown_carrier.json()["type"] == unknown_ref.json()["type"]
    assert unknown_carrier.json()["detail"] == unknown_ref.json()["detail"]
    assert "wss://" not in unknown_carrier.text


async def test_a_carrier_with_no_contract_row_is_refused(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        carrier_routes,
        "CARRIER_ANSWER_CONTRACT",
        {"plivo": carrier_routes.CARRIER_ANSWER_CONTRACT["plivo"]},
    )

    response = await _request(answer_path("vobiz", _ref()))

    assert response.status_code == 404


def test_the_carrier_label_is_bounded_to_the_carriers_this_build_knows() -> None:
    assert carrier_routes.carrier_label("vobiz") == "vobiz"
    assert carrier_routes.carrier_label("x" * 400) == "unknown"


# --- 2. Vobiz inbound: the calling party -------------------------------------------------


async def test_vobiz_reads_the_calling_party_from_a_form_post_and_seals_it(env: Env) -> None:
    env(CARRIER_CLAIM_SECRET=CLAIM_KEY)
    ref = _ref()

    response = await _request(
        answer_path("vobiz", ref),
        headers=FORM,
        content=_form(CallUUID="c-1", From=CALLER, To=OUR_NUMBER, Direction="inbound"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.headers["cache-control"] == "no-store"
    url, claim = _claim(response.text)
    assert claim["caller_state"] == "known"
    # Hard rule 6: the number is on the URL only sealed, never in clear.
    assert CALLER.lstrip("+") not in url
    assert open_caller_claim(CLAIM_KEY, ref=ref, token=claim[CALLER_SEAL_PARAM]) == CALLER
    # Inbound carries no call claim: the worker mints its own call id.
    assert CALL_ID_PARAM not in claim
    assert url.startswith(STREAM_BASE)


async def test_vobiz_reads_the_calling_party_from_a_get_query(env: Env) -> None:
    response = await _request(
        f"{answer_path('vobiz', _ref())}?From={quote(CALLER, safe='')}", method="GET"
    )

    _url, claim = _claim(response.text)
    assert claim["caller_state"] == "known"
    # No signing key: the state travels, the number does not.
    assert CALLER_SEAL_PARAM not in claim


async def test_a_vobiz_request_with_an_empty_from_is_withheld_by_the_carrier(env: Env) -> None:
    response = await _request(answer_path("vobiz", _ref()), headers=FORM, content=_form(From=""))

    _url, claim = _claim(response.text)
    assert claim["caller_state"] == "withheld_by_carrier"


@pytest.mark.parametrize("value", ["anonymous", "private", "0000000", "12345", "+91 98765x"])
async def test_a_vobiz_from_that_is_not_a_number_is_withheld_and_sealed_nowhere(
    value: str, env: Env
) -> None:
    """A carrier's word for a hidden number is not a number. Read as `known`, it normalises
    to an empty string the worker would key an opt-out and a recalled memory on."""
    env(CARRIER_CLAIM_SECRET=CLAIM_KEY)

    response = await _request(answer_path("vobiz", _ref()), headers=FORM, content=_form(From=value))

    _url, claim = _claim(response.text)
    assert claim["caller_state"] == "withheld_by_carrier"
    assert CALLER_SEAL_PARAM not in claim


async def test_a_vobiz_body_over_the_cap_is_refused_before_it_is_parsed(env: Env) -> None:
    response = await _request(
        answer_path("vobiz", _ref()),
        headers=FORM,
        content=b"From=" + b"9" * (carrier_routes.CARRIER_ACK.max_body_bytes + 1),
    )

    assert response.status_code == 413


# --- 3. outbound: the called party and the signed call claim -----------------------------


async def test_an_outbound_answer_names_the_person_we_rang_and_signs_our_call_id(
    env: Env,
) -> None:
    env(CARRIER_CLAIM_SECRET=CLAIM_KEY)
    ref, call_id = _ref(), str(uuid.uuid4())

    response = await _request(
        answer_path("vobiz", ref, call_id=call_id),
        headers=FORM,
        content=_form(From=OUR_NUMBER, To=CALLER, Direction="outbound"),
    )

    assert response.status_code == 200
    _url, claim = _claim(response.text)
    # `From` on a dial we placed is OUR number; keying an opt-out on it would suppress us.
    assert open_caller_claim(CLAIM_KEY, ref=ref, token=claim[CALLER_SEAL_PARAM]) == CALLER
    assert claim[CALL_ID_PARAM] == call_id
    assert claim[CALL_DIRECTION_PARAM] == "outbound"
    assert verify_call_claim(
        CLAIM_KEY.encode(),
        ref=ref,
        call_id=call_id,
        direction="outbound",
        expires_at=claim[CALL_CLAIM_EXPIRES_PARAM],
        mac=claim[CALL_CLAIM_MAC_PARAM],
        now=float(claim[CALL_CLAIM_EXPIRES_PARAM]) - 60,
    )


@pytest.mark.parametrize("secret", [None, "k" * 31])
async def test_an_outbound_answer_without_a_usable_key_is_refused_not_served_unsigned(
    secret: str | None, env: Env
) -> None:
    """Served unsigned, the worker would run the dialled call as inbound on a row of its
    own and the dialled row would never settle. Refusing ends the call before anyone speaks."""
    env(CARRIER_CLAIM_SECRET=secret)
    call_id = str(uuid.uuid4())

    response = await _request(answer_path("vobiz", _ref(), call_id=call_id), method="GET")

    assert response.status_code == 503
    assert response.json()["type"].endswith("/carrier_call_claim_key_missing")
    assert "wss://" not in response.text


async def test_an_inbound_answer_without_a_key_is_still_served_with_no_number(env: Env) -> None:
    """Inbound has no row of ours to orphan, so a missing key costs only the caller's
    identity, and readiness names the missing key (`core/settings`)."""
    response = await _request(
        answer_path("vobiz", _ref()), headers=FORM, content=_form(From=CALLER)
    )

    assert response.status_code == 200
    _url, claim = _claim(response.text)
    assert claim["caller_state"] == "known"
    assert CALLER_SEAL_PARAM not in claim and CALL_ID_PARAM not in claim


async def test_an_outbound_path_whose_call_id_is_not_ours_is_refused(env: Env) -> None:
    response = await _request(answer_path("vobiz", _ref(), call_id="not-a-uuid"))

    assert response.status_code == 404
    assert "wss://" not in response.text


def test_a_carrier_with_no_called_party_declared_reports_why() -> None:
    identity = carrier_routes.caller_identity_from_answer_request(
        "plivo", {"To": CALLER}, direction="outbound"
    )

    assert identity.state == "unparsed_by_client"
    assert "outbound" in identity.ground and identity.e164 is None


# --- 4. Plivo, unchanged -----------------------------------------------------------------


async def test_plivos_answer_is_byte_for_byte_what_it_was(env: Env) -> None:
    """The Plivo row is UNKNOWN in every cell, so its document carries the state and
    nothing else, exactly as before the carrier seam existed."""
    ref = _ref()

    response = await _request(f"/carrier/v1/plivo/answer/{ref}", method="GET", source_ip=None)

    expected = carrier_routes.answer_document(
        f"{STREAM_BASE}/{quote(ref, safe='')}?carrier=plivo&caller_state=unparsed_by_client"
    )
    assert response.status_code == 200
    assert response.text == expected


# --- 5. the allowlist ------------------------------------------------------------------


async def test_vobiz_refuses_an_address_outside_its_published_list(env: Env) -> None:
    ref = _ref()

    refused = await _request(answer_path("vobiz", ref), source_ip=STRANGER_IP)
    allowed = await _request(answer_path("vobiz", ref), source_ip=VOBIZ_IP)

    assert refused.status_code == 404
    assert "wss://" not in refused.text
    assert refused.json()["type"] == (await _request("/carrier/v1/vobiz/answer/x")).json()["type"]
    assert allowed.status_code == 200


async def test_an_operator_override_replaces_the_published_list_without_a_release(
    env: Env,
) -> None:
    env(VOBIZ_CALLBACK_IPS=f" {STRANGER_IP} , 198.51.100.0/24 ")
    ref = _ref()

    published = await _request(answer_path("vobiz", ref), source_ip=VOBIZ_IP)
    single = await _request(answer_path("vobiz", ref), source_ip=STRANGER_IP)
    in_cidr = await _request(answer_path("vobiz", ref), source_ip="198.51.100.77")

    assert published.status_code == 404
    assert single.status_code == 200
    assert in_cidr.status_code == 200


def test_an_override_that_holds_no_valid_address_refuses_rather_than_opening(env: Env) -> None:
    """A typo in the operator's paste must not become "no allowlist at all"."""
    env(VOBIZ_CALLBACK_IPS="not-an-ip, also bad")

    verdict = carrier_routes.verify_answer_source("vobiz", VOBIZ_IP)

    assert not verdict.ok
    assert verdict.reason == "callback ip override holds no valid address"


def test_a_blank_override_falls_back_to_the_published_list(env: Env) -> None:
    env(VOBIZ_CALLBACK_IPS=" , ")

    assert carrier_routes.verify_answer_source("vobiz", VOBIZ_IP).ok
    assert not carrier_routes.verify_answer_source("vobiz", STRANGER_IP).ok


def test_an_unestablished_client_address_is_its_own_reason(env: Env) -> None:
    verdict = carrier_routes.verify_answer_source("vobiz", None)

    assert not verdict.ok and verdict.reason == "client ip not established"
