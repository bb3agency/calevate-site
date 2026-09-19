"""The four in-call tools are REACHABLE, not merely built.

THE DEFECT THIS PINS. `pipeline.assemble_call` advertises the opt-out, call-back, cancel
and handoff tools only when it is handed a `tool_api` — deliberately, because unlike the
knowledge SEARCH these are ACTS, and four tools that can only fail waste a conversational
turn. The tools, their routes, their refusals and their sentences all shipped with tests
and NOTHING PASSED THAT ARGUMENT: `session.open_session` and `session.start_session` did
not take it, and `runtime` built a plain `WorkerApiClient` that cannot reach the routes.

So a caller on an `owned_runtime` call could say "stop calling me" and the agent had no
tool to do it with — the compliance hole (hard rule 5, SEC-COMP §2.3) that the whole tool
surface exists to close, still open behind a green suite. "A route nobody mounted, a job
nobody registered" is the shape CLAUDE.md names; this is its fourth form, a TOOL NOBODY
HANDED AN API TO.

WHY THE ASSERTION IS ON THE THREADING AND NOT ON THE TOOLS. What each tool does when it is
reached is already proved by `tests/owned_runtime_tools_test.py` and
`tests/voice_worker_tools_test.py`. The property those cannot see is whether the value ever
ARRIVES — and it did not. This file asserts the seam, in both directions: handed an api the
call advertises the acts, handed none it advertises only the search.

Run: uv run pytest -q tests/voice_worker_tool_wiring_test.py
"""

from __future__ import annotations

from typing import Any

from pipecat.adapters.schemas.tools_schema import ToolsSchema
from tests.voice_worker_pipeline_test import (
    CREDENTIALS,
    FakeTransport,
    RecordingSink,
    make_config,
)
from voice_worker import runtime, session

#: What `build_knowledge_tool` is called, so the two kinds of tool can be told apart
#: without pinning the ACT tools' names here — those belong to `call_tools` and a second
#: spelling of them is the drift this repo refuses.
_SEARCH_TOOL = "search_knowledge_base"


class _NullFetcher:
    """No pack. The knowledge tool is advertised either way (it answers a state), so this
    keeps the test about the ACTS rather than about the search."""

    async def fetch(self, object_key: str) -> bytes | None:
        return None


class _StubToolApi:
    """Shaped like `call_tools.CallToolApi` and never called. The wiring is what is under
    test; what a tool DOES when reached is proved in the tool suites."""

    async def record_do_not_call(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("the wiring test must never place a call")

    async def book_callback(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("the wiring test must never place a call")

    async def cancel_callback(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("the wiring test must never place a call")

    async def request_human_handoff(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("the wiring test must never place a call")


async def _tool_names(*, tool_api: Any) -> set[str]:
    call = await session.open_session(
        config=make_config(),
        credentials=CREDENTIALS,
        transport=FakeTransport(),
        sink=RecordingSink(),
        fetcher=_NullFetcher(),
        tool_api=tool_api,
    )
    tools = call.context.tools
    assert isinstance(tools, ToolsSchema)
    return {schema.name for schema in tools.standard_tools}


async def test_a_session_handed_a_tool_api_advertises_the_acts() -> None:
    """THE DEFECT, as it was: this returned only the search tool, because nothing passed
    an api. An agent cannot honour "stop calling me" with a tool it was never given."""
    names = await _tool_names(tool_api=_StubToolApi())

    assert _SEARCH_TOOL in names, "the knowledge tool is unconditional and must not regress"
    acts = names - {_SEARCH_TOOL}
    assert len(acts) == 4, (
        f"expected the four in-call ACTS beside the search tool, saw {sorted(names)} — "
        "a caller on this engine cannot opt out, book, cancel or reach a person"
    )


async def test_a_session_handed_no_tool_api_advertises_only_the_search() -> None:
    """The other half, and it is a real product decision rather than a fallback: an ACT
    the container cannot perform must not be offered, because a model handed a tool that
    can only fail spends a turn on it and then improvises."""
    names = await _tool_names(tool_api=None)

    assert names == {_SEARCH_TOOL}


def test_the_container_builds_a_client_that_can_reach_the_tool_routes() -> None:
    """`runtime` built a plain `WorkerApiClient`, which has no method for any of the four
    routes — so even with the threading above, every act would have failed at the client.

    Asserted on the TYPE the module will construct rather than by booting a container:
    `from_env` reads `load_worker_config()` and would need a full environment, which is a
    different test's subject. `CallToolApiClient` is a drop-in subclass — same pool, same
    header, same error type — so this is the whole of the change at that call site.
    """
    from voice_worker.api_client import WorkerApiClient
    from voice_worker.call_tools import CallToolApiClient

    assert issubclass(CallToolApiClient, WorkerApiClient), (
        "the tool client must remain a drop-in for the session client, or the swap in "
        "`runtime` changes more than which methods exist"
    )
    source = runtime.__file__
    with open(source, encoding="utf-8") as handle:
        body = handle.read()
    assert "CallToolApiClient.from_config(" in body, (
        "the container is building the client that cannot reach the tool routes again"
    )
