"""The recording fetch is an SSRF surface, and the URL is the VENDOR's.

`copy_recording` was the one outbound path left in the tree that fetched an externally
supplied address with no address check and `follow_redirects=True` — found by the
adversarial pass (D-135) after D-129 had established the doctrine everywhere else.

Why it is worth its own file rather than a line in the egress-guard suite: the guard's own
tests prove the *classifier* is right, over a resolver double. These prove the classifier
is CALLED, on the first URL and on every redirect hop, from the one caller whose input
nobody in this repo controls. The distinction is exactly the one D-116 turned up — a guard
that held on four surfaces and leaked on the fifth, because the fifth never called it.

Run: uv run pytest -q tests/recording_source_egress_test.py
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from apps.workers import storage
from apps.workers.storage import StorageUnavailableError, copy_recording

pytestmark = [pytest.mark.anyio]

TENANT = uuid.uuid4()
CALL = uuid.uuid4()

#: Reserved names never resolve, so the suite substitutes the RESOLVER seam rather than
#: exempting anything inside the shipped guard — the same choice `conftest` makes for the
#: integrations tests, and for the same reason: an exemption in the guard would be the
#: "bypass for testing" hard rule 5 forbids in those words.
PUBLIC = "https://recordings.example/call.wav"
INTERNAL = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"


class _Recorder:
    """Records every URL the client was asked for, so the assertions read what was
    REQUESTED rather than what we stored — a test on our own rows cannot fail on this."""

    def __init__(self, *responses: httpx.Response) -> None:
        self._responses = list(responses)
        self.asked: list[str] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(str(request.url))
        return self._responses.pop(0) if self._responses else httpx.Response(200, content=b"RIFF")


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Swap httpx's network for a recorder, leaving the guard and the hop loop real."""

    def _install(*responses: httpx.Response) -> _Recorder:
        recorder = _Recorder(*responses)
        real_client = httpx.AsyncClient

        def _factory(**kwargs: object) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(recorder.handler)
            return real_client(**kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(storage.httpx, "AsyncClient", _factory)
        return recorder

    return _install


async def test_a_vendor_url_naming_link_local_is_refused_before_a_socket_is_opened(
    transport,  # type: ignore[no-untyped-def]
) -> None:
    """The cloud-metadata address, which is what this class of bug is always used for.

    `asked == []` is the assertion that matters: a guard that refused AFTER the fetch
    would still have made the request, and the response body is what an attacker wants.
    """
    recorder = transport()
    with pytest.raises(StorageUnavailableError) as caught:
        await copy_recording(source_url=INTERNAL, tenant_id=TENANT, call_id=CALL)
    assert "refused" in str(caught.value)
    assert recorder.asked == [], "the refusal came after the request, which is not a refusal"


async def test_a_redirect_into_the_private_network_is_refused_at_the_hop(
    transport,  # type: ignore[no-untyped-def]
) -> None:
    """The bypass `follow_redirects=True` would have handed over for free.

    The first URL is unimpeachable and the SECOND is the attack — which is why vetting
    only the initial address is not a guard at all. The first hop must have happened
    (otherwise this passes for the wrong reason, proving nothing about redirects).
    """
    recorder = transport(httpx.Response(302, headers={"location": INTERNAL}))
    with pytest.raises(StorageUnavailableError) as caught:
        await copy_recording(source_url=PUBLIC, tenant_id=TENANT, call_id=CALL)
    assert "refused" in str(caught.value)
    assert recorder.asked == [PUBLIC], "the redirect target was fetched"


async def test_an_endless_redirect_chain_is_bounded_rather_than_waited_out(
    transport,  # type: ignore[no-untyped-def]
) -> None:
    """A worker that follows a loop until its 60s timeout is a job slot held hostage."""
    loop = [httpx.Response(302, headers={"location": PUBLIC}) for _ in range(10)]
    recorder = transport(*loop)
    with pytest.raises(StorageUnavailableError) as caught:
        await copy_recording(source_url=PUBLIC, tenant_id=TENANT, call_id=CALL)
    assert "redirect" in str(caught.value)
    assert len(recorder.asked) <= storage.RECORDING_REDIRECT_LIMIT + 1
