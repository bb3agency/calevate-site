"""The caller verdict survives the container entrypoint.

Every other piece of the identity chain was built and tested in isolation: the answer leg
mints the claim onto the stream URL, `claim_from_stream_url` parses it, `fold_caller_identity`
reconciles it with the handshake, `assemble_call` refuses to advertise the in-call acts
without it, and `tools.py` refuses to let an agent claim a suppression unless the state is
`known`. `bot.py` read none of it. It called `create_transport` and handed `run_call` no
caller at all, so every call assembled with `caller=None`, every `CallEvent` left
`from_e164` NULL, and every in-call opt-out answered `caller_number_unknown` — to a person
asking not to be rung again.

These pin the two joints that were missing, at the level where the break was invisible:
the entrypoint reads the query, and `run_call` passes it on.
"""

from __future__ import annotations

import inspect
from typing import Any

import bot
from voice_worker import runtime as runtime_module
from voice_worker.carrier import claim_from_stream_url


class _Url:
    def __init__(self, url: str) -> None:
        self._url = url

    def __str__(self) -> str:
        return self._url


class _Socket:
    def __init__(self, url: str) -> None:
        self.url = _Url(url)


class _Args:
    def __init__(self, url: str | None) -> None:
        self.websocket = None if url is None else _Socket(url)


def test_the_entrypoint_reads_the_whole_url_and_not_just_the_path() -> None:
    """`_route_token` deliberately keeps only the last PATH segment, which is why the
    claim needed a second reader: a helper that returned the path would drop the query
    the control plane put the verdict in."""
    args = _Args("wss://worker.example/ws/pipecat:t:a?caller_state=known&caller=%2B919876500001")

    url = bot._stream_url(cast_args(args))

    assert "caller_state=known" in url


def test_a_socket_with_no_url_is_an_empty_string_and_not_a_refusal() -> None:
    """An absent query is `not_read`, an ordinary outcome — a call placed before the
    answer leg learned to mint a claim must still connect. Only a missing PATH is
    unroutable, and `_route_token` owns that refusal."""
    assert bot._stream_url(cast_args(_Args(None))) == ""


def test_the_verdict_the_entrypoint_reads_is_the_one_the_url_carries() -> None:
    """End to end over the two functions the entrypoint composes, so a change to either
    breaks here rather than at a caller's phone."""
    args = _Args("wss://worker.example/ws/pipecat:t:a?caller_state=known&caller=%2B919876500001")

    caller = claim_from_stream_url(bot._stream_url(cast_args(args))).caller

    assert caller is not None
    assert caller.state == "known"
    assert caller.e164 == "+919876500001"


def test_run_call_accepts_a_caller_and_forwards_it() -> None:
    """The second joint. `run_call` grew the parameter in the same change as the
    entrypoint; a signature that took it and dropped it would leave the whole chain
    passing its own unit tests and still telling every caller we cannot identify them.
    """
    signature = inspect.signature(runtime_module.WorkerRuntime.run_call)
    assert "caller" in signature.parameters, (
        "run_call no longer takes the caller verdict; the entrypoint has nowhere to put it"
    )

    source = inspect.getsource(runtime_module.WorkerRuntime.run_call)
    assert "caller=caller" in source, (
        "run_call takes the verdict and does not pass it to open_session — the parameter "
        "is accepted and discarded, which is the shape this test exists to catch"
    )


def test_the_entrypoint_passes_the_verdict_to_run_call() -> None:
    """The joint itself, asserted on the call site: `bot.run` must hand `run_call` the
    claim rather than letting it default to None."""
    source = inspect.getsource(bot)
    assert "caller=claim_from_stream_url(" in source, (
        "the entrypoint is assembling calls with no caller verdict again"
    )


def cast_args(args: _Args) -> Any:
    """The runner's argument object is a vendor type with a `websocket` attribute; these
    stubs carry the one attribute the two readers touch."""
    return args
