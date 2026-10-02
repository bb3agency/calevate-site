"""The carrier signature seam: Vobiz V3, verified against the URL rebuilt from config.

VERIFIED-VENDOR-DOCS `vobiz-findings/mirror/pages/concepts/validating-callbacks.md:15-52`:
`X-Vobiz-Signature-V3 = base64(HMAC-SHA256(auth_token, base_url + "." + nonce))`, the
nonce in `X-Vobiz-Signature-V3-Nonce`, base_url with the query stripped; `-MA-V3` is the
same under the parent account's token. Signatures are sent only once the URL has auth
credentials configured (`:56-64`), which is why a missing one is refused only when
`VOBIZ_SIGNATURE_REQUIRED` says so.

What is driven: a valid signature (primary and parent-account header), a forged one, a
signature with no nonce, a missing one with and without the requirement, the
requirement with no key, a signature we hold no key for, and the property that matters
most behind a proxy — the signed URL is rebuilt from `WEBHOOK_BASE_URL`, so a request
whose Host differs still verifies and one signed over the proxy's own URL does not.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import carrier_auth
import carrier_routes
import pytest
from apps.api.core.settings import get_settings
from calevate_shared.carrier import VOBIZ_CALLBACK_IPS, answer_path
from calevate_shared.engine import owned_runtime_agent_ref
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

STREAM_BASE = "wss://calevate-pipecat-worker.example.invalid/ws"
PUBLIC = "https://hooks.calevate.example"
TOKEN = "vobiz-test-auth-token"
PARENT_TOKEN = "vobiz-parent-test-token"
NONCE = "12345678901234567890"
VOBIZ_IP = VOBIZ_CALLBACK_IPS[0]

Env = Callable[..., None]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    monkeypatch.setenv("PIPECAT_STREAM_BASE_URL", STREAM_BASE)
    monkeypatch.setenv("WEBHOOK_BASE_URL", f"{PUBLIC}/")
    for name in ("VOBIZ_AUTH_TOKEN", "VOBIZ_SIGNATURE_REQUIRED", "VOBIZ_CALLBACK_IPS"):
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


def _reference_v3(key: str, url: str, nonce: str) -> str:
    """The vendor's own sample, transcribed (`validating-callbacks.md:100-109`), as the
    oracle `carrier_auth.vobiz_v3_signature` is checked against."""
    msg = (url + "." + nonce).encode()
    return base64.b64encode(hmac.new(key.encode(), msg, hashlib.sha256).digest()).decode()


def _path() -> str:
    return answer_path("vobiz", owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4())))


def _signed(
    path: str, *, key: str = TOKEN, base: str = PUBLIC, header: str | None = None
) -> dict[str, str]:
    return {
        header or "X-Vobiz-Signature-V3": _reference_v3(key, base + path, NONCE),
        "X-Vobiz-Signature-V3-Nonce": NONCE,
    }


async def _post(path: str, headers: dict[str, str] | None = None) -> Any:
    sent = {"cf-connecting-ip": VOBIZ_IP, **(headers or {})}
    transport = ASGITransport(app=voice_app)
    # A Host that is NOT the public one: what this process sees behind nginx.
    async with AsyncClient(transport=transport, base_url="http://runtime:8100") as client:
        return await client.post(path, headers=sent)


# --- the primitive --------------------------------------------------------------------


def test_our_signer_matches_the_vendors_published_sample() -> None:
    url = f"{PUBLIC}/carrier/v1/vobiz/answer/x"
    assert carrier_auth.vobiz_v3_signature(TOKEN, url, NONCE) == _reference_v3(TOKEN, url, NONCE)


def test_the_signed_url_is_rebuilt_from_config_with_the_query_stripped() -> None:
    urls = carrier_auth.signed_base_urls(
        f"{PUBLIC}/",
        raw_path=b"/carrier/v1/vobiz/answer/a%3Ab?x=1",
        path="/carrier/v1/vobiz/answer/a:b",
    )

    assert urls == (f"{PUBLIC}/carrier/v1/vobiz/answer/a%3Ab",)


def test_a_proxy_that_re_encodes_the_path_still_yields_our_canonical_spelling() -> None:
    urls = carrier_auth.signed_base_urls(
        PUBLIC, raw_path=b"/carrier/v1/vobiz/answer/a:b", path="/carrier/v1/vobiz/answer/a:b"
    )

    assert urls == (
        f"{PUBLIC}/carrier/v1/vobiz/answer/a:b",
        f"{PUBLIC}/carrier/v1/vobiz/answer/a%3Ab",
    )


def test_with_no_raw_path_the_canonical_spelling_is_the_only_candidate() -> None:
    assert carrier_auth.signed_base_urls(PUBLIC, raw_path=None, path="/p/a:b") == (
        f"{PUBLIC}/p/a%3Ab",
    )


@pytest.mark.parametrize(
    ("headers", "key", "outcome"),
    [
        ({}, TOKEN, "absent"),
        ({"X-Vobiz-Signature-V3": "sig"}, None, "unverifiable"),
        ({"X-Vobiz-Signature-V3": "sig"}, TOKEN, "invalid"),
        ({"X-Vobiz-Signature-V3": "sig", "X-Vobiz-Signature-V3-Nonce": NONCE}, TOKEN, "invalid"),
    ],
    ids=["absent", "no-key", "no-nonce", "forged"],
)
def test_each_signature_outcome(headers: dict[str, str], key: str | None, outcome: str) -> None:
    assert (
        carrier_auth.check_signature(
            headers, carrier_auth.VOBIZ_SIGNATURE_V3, key=key, base_urls=(f"{PUBLIC}/p",)
        )
        == outcome
    )


def test_the_networks_parse_skips_blanks_and_counts_garbage() -> None:
    networks, invalid = carrier_auth.parse_networks(("", "10.0.0.0/8", "nope"))

    assert len(networks) == 1 and invalid == 1
    assert carrier_auth.ip_in("10.1.2.3", networks)
    assert not carrier_auth.ip_in("not-an-address", networks)
    assert carrier_auth.split_list(None) == ()


# --- the policy, through the route ----------------------------------------------------


async def test_a_valid_signature_is_admitted_whatever_host_this_process_sees(env: Env) -> None:
    env(VOBIZ_AUTH_TOKEN=TOKEN, VOBIZ_SIGNATURE_REQUIRED="true")
    path = _path()

    response = await _post(path, _signed(path))

    assert response.status_code == 200


async def test_the_parent_account_signature_is_accepted_too(env: Env) -> None:
    env(VOBIZ_AUTH_TOKEN=TOKEN, VOBIZ_SIGNATURE_REQUIRED="true")
    path = _path()
    headers = _signed(path, header="X-Vobiz-Signature-MA-V3")

    assert (await _post(path, headers)).status_code == 200


async def test_a_signature_over_the_proxys_own_url_is_refused(env: Env) -> None:
    """Rebuilding from `request.url` would accept this and refuse every real call."""
    env(VOBIZ_AUTH_TOKEN=TOKEN)
    path = _path()

    response = await _post(path, _signed(path, base="http://runtime:8100"))

    assert response.status_code == 404
    assert "wss://" not in response.text


async def test_a_signature_under_another_key_is_refused_even_when_not_required(env: Env) -> None:
    env(VOBIZ_AUTH_TOKEN=TOKEN)
    path = _path()

    response = await _post(path, _signed(path, key=PARENT_TOKEN))

    assert response.status_code == 404
    assert TOKEN not in response.text and PARENT_TOKEN not in response.text


@pytest.mark.parametrize(
    ("token", "required", "status"),
    [
        (TOKEN, "true", 404),
        (TOKEN, "false", 200),
        (None, "false", 200),
        (None, "true", 404),
    ],
    ids=["required", "optional", "no-key-optional", "required-without-key"],
)
async def test_an_unsigned_request(token: str | None, required: str, status: int, env: Env) -> None:
    env(VOBIZ_AUTH_TOKEN=token, VOBIZ_SIGNATURE_REQUIRED=required)

    assert (await _post(_path())).status_code == status


async def test_required_without_a_key_refuses_even_a_correctly_signed_request(env: Env) -> None:
    """A misconfiguration: nothing is admitted until the key is set."""
    env(VOBIZ_SIGNATURE_REQUIRED="true")
    path = _path()

    assert (await _post(path, _signed(path))).status_code == 404


async def test_a_signature_we_hold_no_key_for_is_admitted_on_the_source_check(env: Env) -> None:
    path = _path()

    assert (await _post(path, _signed(path))).status_code == 200


def test_the_reported_method_names_the_stronger_control(env: Env) -> None:
    """The forensic row's `signature_valid` is derived from this word."""
    from starlette.requests import Request

    env(VOBIZ_AUTH_TOKEN=TOKEN)
    path = "/carrier/v1/vobiz/events/r"
    signed = _signed(path)
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"cf-connecting-ip", VOBIZ_IP.encode()),
            *((k.lower().encode(), v.encode()) for k, v in signed.items()),
        ],
        "client": ("127.0.0.1", 1),
    }

    verified = carrier_routes.authenticate("vobiz", Request(scope))
    unsigned = carrier_routes.authenticate(
        "vobiz", Request({**scope, "headers": scope["headers"][:1]})
    )
    plivo = carrier_routes.authenticate("plivo", Request(scope))

    assert (verified.ok, verified.method) == (True, "signature")
    assert (unsigned.ok, unsigned.method, unsigned.reason) == (True, "source_ip", "unsigned")
    assert (plivo.ok, plivo.method) == (True, "none")
