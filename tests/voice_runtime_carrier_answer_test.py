"""`docs/PIPECAT-MIGRATION.md` §6 step 6, the HTTP half: the answer document (D-610).

**WHAT THIS FILE IS TRYING TO CATCH.** The answer document is the one wire value between a
ringing number and a media stream, and `www.plivo.com` is egress-blocked from this
container (re-measured 15 Sep 2026: `curl: (56) CONNECT tunnel failed, response 403`). So
none of its grammar can be checked against the vendor. What CAN be checked, and is:

1. **We render exactly the element the shipped `pipecat-ai==1.10.0` runner renders.** The
   template is EXTRACTED from the installed tree and parsed, tag and full attribute set,
   rather than copied into this file — a copy would assert that we still agree with
   ourselves. A dependency bump that moves the grammar fails here instead of on a call.
2. **A ref that names no agent of ours is refused, and the refusal mints no stream URL** —
   so a stranger probing the path cannot learn the worker's address from it, and the
   carrier is never sent to open a socket the worker would have to refuse.
3. **The route is mounted on the live app** (`check_wiring` counts routers; this asserts
   the one that matters answers).
4. **The handler does no IO**, which is the property hard rule 3's budget rests on here —
   `carrier_routes`' docstring argues why that is asserted instead of a third ack series.
5. **The round trip closes across two deployables**: the URL this service mints carries a
   path segment the WORKER's `carrier.route_of` resolves to the same two ids.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree.ElementTree import fromstring

import carrier_routes
import pytest
from apps.api.core.settings import get_settings
from calevate_shared.engine import owned_runtime_agent_ref
from httpx import ASGITransport, AsyncClient
from main import app as voice_app
from voice_worker import carrier

STREAM_BASE = "wss://calevate-voice-worker.example.invalid/ws"


@pytest.fixture
def stream_base(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`PIPECAT_STREAM_BASE_URL` set, through the environment the deployment really reads.

    The env var and `get_settings.cache_clear()` rather than patching the module: the
    handler resolves the value through `get_settings()` on every request, which is the
    path an operator's change takes, and a patched attribute would test a different one.
    """
    monkeypatch.setenv("PIPECAT_STREAM_BASE_URL", STREAM_BASE)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def no_stream_base(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The unconfigured deployment, which is what every deployment is until BLOCKER-1."""
    monkeypatch.delenv("PIPECAT_STREAM_BASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _pipecat_source(relative: str) -> str:
    """One file of the INSTALLED pipecat tree, as text.

    Read off the imported package rather than from a path this file spells, so the source
    under assertion is the one the deployment will really ship.
    """
    import pipecat

    return (Path(pipecat.__file__).parent / relative).read_text(encoding="utf-8")


async def _get(path: str) -> Any:
    transport = ASGITransport(app=voice_app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as client:
        return await client.get(path)


# --------------------------------------------------------------------------------------
# 1. The document, against the source that gave it to us.
# --------------------------------------------------------------------------------------


def test_the_answer_document_is_pipecats_own_template_and_not_our_reading_of_it() -> None:
    """`plivo_answer_document` must render exactly the element the shipped runner renders.

    What is compared is the tag and the FULL attribute set, because the attributes are the
    part we could not verify any other way (Plivo's own grammar is egress-blocked here).
    """
    source = _pipecat_source("runner/run.py")
    match = re.search(r"<Response>\s*(<Stream [^>]*>)[^<]*</Stream>\s*</Response>", source)
    assert match, "pipecat no longer ships a Plivo answer template at the shape we read"
    theirs = fromstring(match.group(1) + "</Stream>")

    ours = fromstring(carrier_routes.plivo_answer_document("wss://voice.example.invalid/ws/token"))

    assert ours.tag == "Response"
    (stream,) = list(ours)
    assert stream.tag == theirs.tag == "Stream"
    assert stream.attrib == theirs.attrib
    assert stream.text == "wss://voice.example.invalid/ws/token"
    assert carrier_routes.ANSWER_DOCUMENT_CONTENT_TYPE == "application/xml"


def test_the_sample_rate_is_pinned_to_the_vendors_own_template_not_to_the_worker() -> None:
    """The second copy of 8000 in this tree is a copy of the SOURCE, not of the first copy.

    `carrier_routes` cannot import `voice_worker.pipeline` (hard rule 3 — that module
    drags pipecat and ONNX onto a 500ms path), so the constant is declared twice. This is
    what stops that from being two answers to one question: each is pinned independently
    to the vendor's own file, so a bump that moved the rate fails on both sides.
    """
    source = _pipecat_source("runner/run.py")
    match = re.search(r'contentType="audio/x-mulaw;rate=(\d+)"', source)
    assert match, "pipecat no longer states a telephony rate in its Plivo answer template"

    assert int(match.group(1)) == carrier_routes.TELEPHONY_SAMPLE_RATE_HZ


def test_the_answer_document_escapes_a_url_rather_than_concatenating_it() -> None:
    """A wire value with an `&` in it must not break the document a carrier parses."""
    url = "wss://voice.example.invalid/ws/a?x=1&y=2"
    document = carrier_routes.plivo_answer_document(url)

    assert "&amp;" in document
    (stream,) = list(fromstring(document))
    assert stream.text == url


# --------------------------------------------------------------------------------------
# 2. The route: mounted, served, and refusing.
# --------------------------------------------------------------------------------------


async def test_the_route_is_mounted_and_serves_the_document_for_a_real_ref(
    stream_base: None,
) -> None:
    """Mounted, right content type, and the stream URL names the agent that was asked for."""
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    ref = owned_runtime_agent_ref(str(tenant_id), str(agent_id))

    response = await _get(f"/carrier/v1/plivo/answer/{ref}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    (stream,) = list(fromstring(response.text))
    assert stream.text is not None and stream.text.startswith(STREAM_BASE)


@pytest.mark.parametrize(
    "ref",
    [
        "not-a-token",
        "pipecat:not-a-uuid:also-not",
        "bolna:11111111-1111-7111-8111-111111111111:22222222-2222-7222-8222-222222222222",
        "pipecat:11111111-1111-7111-8111-111111111111",
    ],
)
async def test_an_unknown_ref_is_refused_without_minting_a_stream_url(
    ref: str, stream_base: None
) -> None:
    """Anything can GET a URL, so the segment is attacker-controlled.

    THREE assertions and the last two are the ones with teeth: the refusal must not hand
    back the worker's address, and the PROSE of it must not quote the stranger's string.
    (RFC-9457's `instance` does carry the request path, and that is correct — it is the
    caller's own URL returned to the caller. What must not happen is the token reaching a
    line an operator reads, which is why `carrier_routes` logs a reason and no token.)
    """
    response = await _get(f"/carrier/v1/plivo/answer/{ref}")

    assert response.status_code == 404
    assert "wss://" not in response.text
    problem = response.json()
    assert ref not in problem["title"] + problem["detail"]


async def test_an_unconfigured_deployment_refuses_rather_than_pointing_at_nothing(
    no_stream_base: None,
) -> None:
    """No `PIPECAT_STREAM_BASE_URL` is a named refusal, never a guessed hostname.

    A served document pointing at a host that does not answer is a call that connects,
    rings and dies in silence — the failure a caller notices and nobody else does.
    """
    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))

    response = await _get(f"/carrier/v1/plivo/answer/{ref}")

    # `dependency` on the error ladder — 502, and retryable, which is the right answer for
    # a carrier that will fetch this URL again on the next call.
    assert response.status_code == 502
    assert "PIPECAT_STREAM_BASE_URL" in response.text
    # The refusal names the SETTING, never a hostname: nothing here invents an address.
    assert "example.invalid" not in response.text


async def test_serving_the_document_opens_no_database_and_no_redis_connection(
    stream_base: None,
) -> None:
    """Hard rule 3's budget is STRUCTURAL on this route, and this is what makes that true.

    The handler reads no body, opens no session, touches no Redis and enqueues nothing, so
    there is no dependency that can make its ack slow — which is the argument
    `carrier_routes` gives for having no third ack series. Asserted by making every one of
    those doors raise: if the handler reaches one, this fails.
    """
    import apps.api.core.redis as core_redis
    import apps.api.db.session as db_session

    def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the answer route performed IO")

    ref = owned_runtime_agent_ref(str(uuid.uuid4()), str(uuid.uuid4()))
    original_redis = core_redis.get_redis
    original_session = db_session.untenanted_session
    core_redis.get_redis = _forbidden  # type: ignore[assignment]
    db_session.untenanted_session = _forbidden  # type: ignore[assignment]
    try:
        response = await _get(f"/carrier/v1/plivo/answer/{ref}")
    finally:
        core_redis.get_redis = original_redis  # type: ignore[assignment]
        db_session.untenanted_session = original_session  # type: ignore[assignment]

    assert response.status_code == 200


# --------------------------------------------------------------------------------------
# 3. The round trip, across the two deployables that share the grammar.
# --------------------------------------------------------------------------------------


def test_the_stream_url_this_service_mints_is_one_the_worker_can_route() -> None:
    """The whole point of the design, in one assertion.

    `carrier_routes.plivo_stream_url` (voice-runtime, no pipecat) mints the URL; the
    carrier connects to it; `carrier.route_of` (voice-worker) reads the segment back. The
    two modules may never import each other, so this is the only place the agreement is
    checked — and the `%3A` encoding is exactly the part that would silently break it.
    """
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    ref = owned_runtime_agent_ref(str(tenant_id), str(agent_id))

    url = carrier_routes.plivo_stream_url(STREAM_BASE, ref)
    token = unquote(urlparse(url).path.rsplit("/", 1)[-1])

    assert "%3A" in url
    assert carrier.route_of(token) == carrier.CallRoute(tenant_id=tenant_id, agent_id=agent_id)
