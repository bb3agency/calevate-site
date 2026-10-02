"""The live-transfer `<Dial>` document: off by default, Vobiz only, from a sealed token.

`/carrier/v1/{carrier}/transfer/{token}` is where the API redirects a live call for a
human handoff. The destination rides inside an AES-GCM token (`calevate_shared.
carrier_token`) because this route may not read the database and a number in a URL lands
in access logs. What is driven: off means no `<Dial>` is ever served; on serves the
vendor's grammar (VERIFIED-VENDOR-DOCS `vobiz-findings/mirror/pages/xml/dial.md:40-60`); a
forged, expired or wrong-purpose token, a carrier with no `<Dial>` grammar, and an order
our own minter got wrong are all refused with the one refusal every carrier route gives.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from xml.etree.ElementTree import fromstring

import carrier_routes
import pytest
from apps.api.core.settings import get_settings
from calevate_shared.carrier import VOBIZ_CALLBACK_IPS, transfer_path
from calevate_shared.carrier_token import seal
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

SECRET = "s" * 40
DESTINATION = "+919876500021"
OUR_NUMBER = "+918000000001"
ORDER: dict[str, Any] = {
    "to": DESTINATION,
    "caller_id": OUR_NUMBER,
    "timeout_s": 25,
    "time_limit_s": 900,
    "call": "0199a000-0000-7000-8000-000000000001",
}

Env = Callable[..., None]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    monkeypatch.setenv("CARRIER_CLAIM_SECRET", SECRET)
    for name in ("CARRIER_TRANSFER_ENABLED", "VOBIZ_AUTH_TOKEN", "VOBIZ_CALLBACK_IPS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    def apply(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def _token(
    order: dict[str, Any] | None = None, *, purpose: str = "transfer", ttl_s: int = 60
) -> str:
    return seal(SECRET, purpose, ORDER if order is None else order, ttl_s=ttl_s)


async def _fetch(carrier: str, token: str, *, method: str = "POST") -> Any:
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as client:
        return await client.request(
            method,
            transfer_path(carrier, token),  # type: ignore[arg-type]
            headers={"cf-connecting-ip": VOBIZ_CALLBACK_IPS[0]},
        )


async def test_with_transfer_switched_off_no_dial_is_ever_served(env: Env) -> None:
    response = await _fetch("vobiz", _token())

    assert response.status_code == 404
    assert "<Dial" not in response.text and DESTINATION not in response.text


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_a_valid_token_is_served_as_the_vendors_dial_grammar(method: str, env: Env) -> None:
    env(CARRIER_TRANSFER_ENABLED="true")

    response = await _fetch("vobiz", _token(), method=method)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.headers["cache-control"] == "no-store"
    root = fromstring(response.text)
    (dial,) = list(root)
    assert root.tag == "Response" and dial.tag == "Dial"
    assert dial.text == DESTINATION
    assert dial.attrib == {"callerId": OUR_NUMBER, "timeout": "25", "timeLimit": "900"}


async def test_a_whisper_url_becomes_confirm_sound_and_no_confirm_key_is_emitted(
    env: Env,
) -> None:
    """The vendor calls `confirmKey` enforcement unverified (`xml/dial.md:56`)."""
    env(CARRIER_TRANSFER_ENABLED="true")
    whisper = "https://hooks.calevate.example/whisper/1"

    response = await _fetch("vobiz", _token({**ORDER, "confirm_sound_url": whisper}))

    (dial,) = list(fromstring(response.text))
    assert dial.attrib["confirmSound"] == whisper
    assert "confirmKey" not in dial.attrib


@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        _token(purpose="caller"),
        seal("t" * 40, "transfer", ORDER, ttl_s=60),
        _token(ttl_s=-5),
    ],
    ids=["garbage", "wrong-purpose", "wrong-key", "expired"],
)
async def test_a_token_that_does_not_open_is_refused(token: str, env: Env) -> None:
    env(CARRIER_TRANSFER_ENABLED="true")

    response = await _fetch("vobiz", token)

    assert response.status_code == 404
    assert response.json()["type"].endswith("/carrier_ref_unknown")
    assert "<Dial" not in response.text


async def test_a_carrier_with_no_dial_grammar_is_refused(env: Env) -> None:
    env(CARRIER_TRANSFER_ENABLED="true")

    response = await _fetch("plivo", _token())

    assert response.status_code == 404
    assert "<Dial" not in response.text


@pytest.mark.parametrize(
    "change",
    [
        {"to": "9876500021"},
        {"to": 919876500021},
        {"caller_id": "+0123"},
        {"timeout_s": 0},
        {"timeout_s": True},
        {"time_limit_s": 86401},
        {"time_limit_s": "900"},
        {"call": 7},
        {"confirm_sound_url": "http://insecure.example/w"},
    ],
)
async def test_an_order_our_minter_got_wrong_is_refused(change: dict[str, Any], env: Env) -> None:
    env(CARRIER_TRANSFER_ENABLED="true")

    response = await _fetch("vobiz", _token({**ORDER, **change}))

    assert response.status_code == 404
    assert "<Dial" not in response.text


def test_an_order_with_no_call_id_is_still_a_valid_order() -> None:
    order = carrier_routes.transfer_order({k: v for k, v in ORDER.items() if k != "call"})

    assert order is not None and order.call_id is None and order.confirm_sound_url is None
