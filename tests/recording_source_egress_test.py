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

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

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


# ------------------------------------------------------- the other two unbounded things
#
# The hop bound exists because "an unbounded chain is a worker sitting in a redirect loop
# until its 60s timeout — a job slot held hostage by a third party". The same sentence was
# true of two things it did not cover: how many BYTES the third party sends, and for how
# LONG. `.content` read whatever arrived, and httpx's timeout is per operation, so a
# sender that keeps trickling never trips it.


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    """A body with NO `Content-Length`, which is what a chunked or hostile sender gives.

    Load-bearing, not a flourish: with a declared length present, the pre-flight check
    below would refuse first and a test aimed at the running total would pass without
    the running total existing. Sabotage caught exactly that — the first draft of this
    file went green with the cap deleted.
    """
    for part in parts:
        yield part


async def test_a_body_over_the_cap_is_abandoned_partway_rather_than_read(
    transport,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    s3,  # type: ignore[no-untyped-def]
) -> None:
    """The cap is enforced on the RUNNING TOTAL, which is the only place it can be.

    Reading the body and measuring it afterwards is not a limit: the memory is spent by
    the time the number exists, and the sender picks the number. The cap is shrunk here
    rather than a 115 MB fixture being built, because what is under test is the clause and
    not the constant — and the body is undeclared, so the clause under test is the only
    one that can fire.
    """
    monkeypatch.setattr(storage, "MAX_RECORDING_BYTES", 16)
    recorder = transport(httpx.Response(200, content=_chunks(b"RIFF" * 4, b"RIFF" * 4)))
    with pytest.raises(StorageUnavailableError) as caught:
        await copy_recording(source_url=PUBLIC, tenant_id=TENANT, call_id=CALL)
    assert "exceeded the" in str(caught.value), str(caught.value)
    assert recorder.asked == [PUBLIC], "the request was made — this is not a pre-flight refusal"
    assert s3.objects == {}, "an over-cap body must not reach the bucket either"


async def test_a_declared_oversize_body_costs_one_request_and_no_bytes(
    transport,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    s3,  # type: ignore[no-untyped-def]
) -> None:
    """`Content-Length` is a hint, not the enforcement — but when it is present and honest
    there is no reason to read a byte of what it describes.

    The body itself is INSIDE the cap, so the running total cannot be what refuses it and
    the store is stubbed so a missing refusal shows up as a copy that succeeded rather
    than as an unrelated credentials error.
    """
    monkeypatch.setattr(storage, "MAX_RECORDING_BYTES", 16)
    recorder = transport(
        httpx.Response(200, content=b"RIFF", headers={"content-length": "99999999"})
    )
    with pytest.raises(StorageUnavailableError) as caught:
        await copy_recording(source_url=PUBLIC, tenant_id=TENANT, call_id=CALL)
    assert "declares" in str(caught.value), str(caught.value)
    assert recorder.asked == [PUBLIC]
    assert s3.objects == {}, "nothing was stored from a body we refused"


async def test_a_body_inside_the_cap_still_arrives_whole(
    transport,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    s3,  # type: ignore[no-untyped-def]
) -> None:
    """The positive half. A cap that refused everything would satisfy both tests above,
    and a streamed read that dropped its last chunk would satisfy them too."""
    audio = b"RIFF" + bytes(range(256)) * 4
    transport(httpx.Response(200, content=audio))
    key = await copy_recording(source_url=PUBLIC, tenant_id=TENANT, call_id=CALL)
    assert s3.objects[key] == audio, "streamed in chunks, reassembled byte-exact"


async def test_a_sender_that_never_finishes_is_cut_off_by_the_whole_fetch_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound httpx cannot give us.

    `DOWNLOAD_TIMEOUT_S` is per operation: a handler that answers slowly, repeatedly,
    inside the read timeout is never refused by it. The deadline is over the WHOLE fetch —
    hops included — so a chain of individually-prompt responses cannot outlast it either.
    """
    monkeypatch.setattr(storage, "RECORDING_FETCH_DEADLINE_S", 0.25)

    async def crawl(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, content=b"RIFF")

    real_client = httpx.AsyncClient

    def _factory(**kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(crawl)
        return real_client(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(storage.httpx, "AsyncClient", _factory)
    started = time.perf_counter()
    with pytest.raises(StorageUnavailableError) as caught:
        await copy_recording(source_url=PUBLIC, tenant_id=TENANT, call_id=CALL)
    assert "exceeded" in str(caught.value)
    assert time.perf_counter() - started < 2.0, "the deadline fired, not the 60s read timeout"


def test_the_recording_stage_leaves_the_rest_of_the_pipeline_room() -> None:
    """The number has to be read against the budget it spends, not admired on its own.

    `copy_recording` is STEP 1 of `run_post_call_pipeline`, and arq cancels that job at
    `WorkerSettings.job_timeout`. Everything after the recording — extraction, the lead
    upsert, metering, the hot-lead alert, all of it under a 2-minute lead-visible SLO —
    has to fit in what this stage does not spend. Asserted the way
    `dispatch_tick_lease_test` asserts its lease against the same constant, because a
    comment claiming a relationship between two numbers is not a check on either.
    """
    from apps.workers import settings as worker_settings

    budget = float(worker_settings.WorkerSettings.job_timeout)
    assert budget / 2 > storage.RECORDING_FETCH_DEADLINE_S, (
        "the first stage may not claim half the whole pipeline's budget"
    )
    assert storage.DOWNLOAD_TIMEOUT_S <= storage.RECORDING_FETCH_DEADLINE_S, (
        "a per-operation timeout longer than the total deadline is a number that never fires"
    )
