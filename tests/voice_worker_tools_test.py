"""The worker half of the four in-call tools: what the agent is handed, and when.

**WHAT IS UNDER TEST HERE IS NOT THE BEHAVIOUR — IT IS THE HONESTY OF THE HANDOFF.** Every
decision about an opt-out, a booking or a cancellation belongs to `apps/api/worker/tools.py`
and is proved against a real database in `tests/owned_runtime_tools_test.py`. What this file
holds down is the part that runs on a vendor's infrastructure: that the four tools are
advertised at all, that the model's arguments are narrowed the way the engine leg narrows
them, that the caller's identity is bound at assembly rather than asked of the model, and —
the sharp one — that a tool the API could not answer NEVER comes back as a success.

`FakeToolApi` is the seam `CallToolApi` exists for: no socket, no ASGI app, no database.
The client that really speaks HTTP is exercised end to end in `owned_runtime_tools_test.py`,
against the real app.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from calevate_shared.engine import pipecat_call_ref
from calevate_shared.worker_api import (
    CallbackBookIn,
    CallbackCancelIn,
    CallbackCancelOut,
    CallbackToolOut,
    HandoffToolIn,
    HandoffToolOut,
    OptOutToolIn,
    OptOutToolOut,
)
from voice_worker.api_client import WorkerApiError
from voice_worker.call_tools import (
    BOOK_CALLBACK_TOOL_NAME,
    CANCEL_CALLBACK_TOOL_NAME,
    HANDOFF_TOOL_NAME,
    OPT_OUT_TOOL_NAME,
    TOOL_BUDGET_S,
    _confirmed,
    build_call_tools,
)
from voice_worker.pipeline import FUNCTION_CALL_TIMEOUT_SECS

TENANT = uuid.UUID("01936b0a-0000-7000-8000-000000000001")
CALL_ID = "call-abc123"


@dataclass
class FakeToolApi:
    """The four calls, recorded. Raises `WorkerApiError` when `unreachable` is set."""

    unreachable: bool = False
    opt_out_answer: OptOutToolOut = field(
        default_factory=lambda: OptOutToolOut(status="recorded", say="they are removed")
    )
    booked: list[CallbackBookIn] = field(default_factory=list)
    opt_outs: list[OptOutToolIn] = field(default_factory=list)
    cancels: list[CallbackCancelIn] = field(default_factory=list)
    handoffs: list[HandoffToolIn] = field(default_factory=list)

    def _maybe_fail(self) -> None:
        if self.unreachable:
            raise WorkerApiError("the worker API could not be reached")

    async def opt_out(self, engine_call_id: str, request: OptOutToolIn) -> OptOutToolOut:
        self._maybe_fail()
        self.opt_outs.append(request)
        return self.opt_out_answer

    async def book_callback(self, engine_call_id: str, request: CallbackBookIn) -> CallbackToolOut:
        self._maybe_fail()
        self.booked.append(request)
        return CallbackToolOut(status="booked", say="booked", booked_for="Tuesday at 4:00 PM")

    async def cancel_callback(
        self, engine_call_id: str, request: CallbackCancelIn
    ) -> CallbackCancelOut:
        self._maybe_fail()
        self.cancels.append(request)
        return CallbackCancelOut(status="cancelled", say="we will not ring back", cancelled=1)

    async def handoff(self, engine_call_id: str, request: HandoffToolIn) -> HandoffToolOut:
        self._maybe_fail()
        self.handoffs.append(request)
        return HandoffToolOut(status="not_transferred", say="you cannot transfer")


@dataclass
class FakeParams:
    """`FunctionCallParams` as a tool handler uses it: arguments in, one result out."""

    arguments: dict[str, Any]
    result: Any = None

    async def result_callback(self, payload: Any) -> None:
        self.result = payload


def tools(api: Any, **kwargs: Any) -> dict[str, Any]:
    built = build_call_tools(api, tenant_id=TENANT, call_id=CALL_ID, **kwargs)
    return {schema.name: schema for schema in built}


async def call_tool(api: Any, name: str, arguments: dict[str, Any], **kwargs: Any) -> Any:
    params = FakeParams(arguments=arguments)
    await tools(api, **kwargs)[name].handler(params)
    return params.result


def test_all_four_tools_are_advertised() -> None:
    """THE DEFECT, STATED AS A COUNT. `assemble_call` advertised ONE tool while the rented
    engine served four, so an `owned_runtime` agent could not honour an opt-out, book or
    cancel a call-back, or ask for a person."""
    assert set(tools(FakeToolApi())) == {
        OPT_OUT_TOOL_NAME,
        BOOK_CALLBACK_TOOL_NAME,
        CANCEL_CALLBACK_TOOL_NAME,
        HANDOFF_TOOL_NAME,
    }


def test_no_tool_is_advertised_without_an_api_to_perform_it() -> None:
    """The OPPOSITE of `build_knowledge_tool`'s choice, on purpose: these are ACTS, not
    answers. A model that cannot reach the API cannot perform any of them, and four tools
    that could only ever fail would spend a turn of a live call arriving at a sentence the
    model could have said without them."""
    assert build_call_tools(None, tenant_id=TENANT, call_id=CALL_ID) == []


def test_the_opt_out_tool_asks_for_nothing_the_caller_might_not_give() -> None:
    """A caller who says "stop calling me" and nothing else must not be blocked by a model
    waiting for a reason."""
    assert tools(FakeToolApi())[OPT_OUT_TOOL_NAME].required == []


def test_the_tool_budget_is_under_the_frameworks_own_ceiling() -> None:
    """THE ORDERING IS THE PROPERTY, NOT THE NUMBER. The inner bound being smaller is what
    lets a hung API return OUR honest sentence inside the tool call; if Pipecat's ceiling
    fired first the model would see "the function failed and returned no result" and say
    something it made up — on the turn where a caller asked not to be called again."""
    assert TOOL_BUDGET_S < FUNCTION_CALL_TIMEOUT_SECS


@pytest.mark.asyncio
async def test_the_opt_out_hands_the_servers_own_words_to_the_model() -> None:
    api = FakeToolApi()
    result = await call_tool(api, OPT_OUT_TOOL_NAME, {"reason": "stop", "language": "te-IN"})
    assert result == {"status": "recorded", "say": "they are removed", "reason": ""}
    assert api.opt_outs[0].reason == "stop"


@pytest.mark.asyncio
async def test_an_unreachable_api_never_tells_a_caller_they_were_removed() -> None:
    """THE MOST IMPORTANT ASSERTION IN THIS FILE.

    The suppression was not written. A caller told "done" will not ring back to check —
    they will simply be called again by a platform that recorded nothing. The handler must
    therefore answer `not_recorded` and must forbid the claim in words.
    """
    result = await call_tool(FakeToolApi(unreachable=True), OPT_OUT_TOOL_NAME, {"reason": "stop"})
    assert result["status"] == "not_recorded"
    assert "Do NOT tell the caller they have been removed" in result["say"]
    assert "passing their request to a person" in result["say"]


@pytest.mark.asyncio
async def test_an_unreachable_api_does_not_claim_a_booking_or_a_cancellation() -> None:
    api = FakeToolApi(unreachable=True)
    booked = await call_tool(
        api, BOOK_CALLBACK_TOOL_NAME, {"callback_date": "2026-10-01", "callback_time": "10:00"}
    )
    cancelled = await call_tool(api, CANCEL_CALLBACK_TOOL_NAME, {})
    assert booked["status"] == "not_booked"
    assert cancelled["status"] == "not_cancelled"


@pytest.mark.asyncio
async def test_an_unreachable_api_still_forbids_promising_a_transfer() -> None:
    """The server's answer does not depend on anything it reads — this engine cannot
    transfer a caller — so an unreachable API changes nothing about what is true."""
    result = await call_tool(FakeToolApi(unreachable=True), HANDOFF_TOOL_NAME, {"reason": "x"})
    assert result["status"] == "not_transferred"
    assert "Do not say you are transferring them" in result["say"]


@pytest.mark.asyncio
async def test_the_spoken_form_is_carried_back_for_the_agent_to_read() -> None:
    """The confirm step is worthless if the agent reformats the time itself."""
    result = await call_tool(
        FakeToolApi(),
        BOOK_CALLBACK_TOOL_NAME,
        {"callback_date": "2026-10-01", "callback_time": "16:00", "confirmed": "yes"},
    )
    assert result["booked_for"] == "Tuesday at 4:00 PM"


@pytest.mark.asyncio
async def test_the_caller_is_bound_at_assembly_and_cannot_be_supplied_by_the_model() -> None:
    """A model able to put a number in a tool argument could suppress somebody else's.

    The identity comes from the carrier handshake and is closed over at assembly; an
    argument called `caller` or `e164` is simply not read.
    """
    api = FakeToolApi()
    await call_tool(
        api,
        OPT_OUT_TOOL_NAME,
        {"reason": "stop", "e164": "+919999999999", "caller": "+919999999999"},
        caller_state="known",
        caller_e164="+919812345672",
    )
    assert api.opt_outs[0].caller.e164 == "+919812345672"
    assert api.opt_outs[0].caller.state == "known"


@pytest.mark.asyncio
async def test_a_number_never_travels_under_a_state_that_does_not_mean_known() -> None:
    """The three other states each mean we do NOT have a number, for different reasons.
    Sending one under any of them would make the wire disagree with itself."""
    api = FakeToolApi()
    await call_tool(
        api,
        OPT_OUT_TOOL_NAME,
        {},
        caller_state="withheld_by_carrier",
        caller_e164="+919812345672",
    )
    assert api.opt_outs[0].caller.state == "withheld_by_carrier"
    assert api.opt_outs[0].caller.e164 is None


@pytest.mark.asyncio
async def test_the_call_ref_is_the_one_the_sink_mints() -> None:
    """A second spelling of one handle is the drift the quality bar refuses."""
    seen: list[str] = []

    class Recording(FakeToolApi):
        async def cancel_callback(
            self, engine_call_id: str, request: CallbackCancelIn
        ) -> CallbackCancelOut:
            seen.append(engine_call_id)
            return await super().cancel_callback(engine_call_id, request)

    await call_tool(Recording(), CANCEL_CALLBACK_TOOL_NAME, {})
    assert seen == [pipecat_call_ref(TENANT, CALL_ID)]


@pytest.mark.asyncio
async def test_a_blank_or_non_string_argument_does_not_raise_out_of_a_handler() -> None:
    """A `TypeError` out of a tool handler reaches the model as "the function failed and
    returned no result", which on every one of these four is worse than an empty hint."""
    api = FakeToolApi()
    result = await call_tool(api, OPT_OUT_TOOL_NAME, {"reason": 17, "language": "   "})
    assert result["status"] == "recorded"
    assert api.opt_outs[0].reason is None
    assert api.opt_outs[0].language is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        (False, False),
        ("1", False),
        (1, False),
        ("sure", False),
        (None, False),
        ("", False),
    ],
)
def test_confirmation_is_narrow_on_purpose(value: Any, expected: bool) -> None:
    """`tool_routes._truthy`'s rule, on this side of the wire. An unrecognised value is an
    unconfirmed booking, which costs one conversational turn; the other direction costs a
    caller a phone call at four in the morning."""
    assert _confirmed(value) is expected


@pytest.mark.asyncio
async def test_an_unconfirmed_booking_is_what_reaches_the_server() -> None:
    """The narrowing happens before the body is built, so the server never re-interprets a
    string — the two halves of our own product agree on a decided boolean."""
    api = FakeToolApi()
    await call_tool(
        api,
        BOOK_CALLBACK_TOOL_NAME,
        {"callback_date": "2026-10-01", "callback_time": "16:00", "confirmed": "maybe"},
    )
    assert api.booked[0].confirmed is False
