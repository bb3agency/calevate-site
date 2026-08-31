"""The bounded tool-calling loop: when it stops, what it costs, and what it discloses.

The provider is replaced at `chat.stream` / `chat.complete` — the SEAM ONE LAYER BELOW the
loop — so the accumulator, the frame filter and the request shape are still the real ones
and are proved separately in `apps/workers/chat_test.py`. What is faked here is only "what
the model said", which is the one thing no test can obtain honestly.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import httpx
import pytest
from calevate_shared.engine import GOOGLE_DIRECT_MODELS, google_openai_compat_base_url

from apps.api.copilot import service
from apps.api.copilot import tools as tools_module
from apps.api.copilot import write_tools
from apps.api.copilot.schemas import CopilotAskIn, CopilotFillItem
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers import extraction as extraction_module

#: A real selectable Gemini model, read from the catalogue rather than spelled here.
#: `tests/sarvam_model_identifier_test.py` keeps Google model ids in `engine.py` and
#: the lifecycle registry alone; a fixture that needs one reads it back. `min` only
#: makes the pick deterministic.
_GOOGLE_MODEL = min(GOOGLE_DIRECT_MODELS)

PAYLOAD = CopilotAskIn.model_validate(
    {
        "screen": {"route": "/c/x/agents/new", "title": "Build", "realm": "client"},
        "question": "set the opening time",
        "fields": [
            {"id": "open", "label": "Opens", "type": "text", "writable": True},
            {"id": "status", "label": "Status", "type": "text", "writable": False},
        ],
    }
)


@pytest.fixture
def azure_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment holding an Azure credential and NO Sarvam key: the top rung of the
    ladder, so anything that falls off it has to say so. All three Azure fields together —
    `azure_credentials()` requires all three and a half-set deployment is a different
    state with its own test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)


def _turn(
    *, content: str = "", arguments: str | None = None, usage: chat.TokenUsage | None = None
) -> list[chat.StreamEvent]:
    """One faked model turn as the events `chat.stream` would have yielded."""
    calls = (
        (chat.ToolCall(id="call-1", name="set_fields", arguments=arguments),)
        if arguments is not None
        else ()
    )
    return [
        *([chat.StreamEvent(text=content)] if content else []),
        chat.StreamEvent(
            outcome=chat.ChatOutcome(
                content=content,
                tool_calls=calls,
                finish_reason="tool_calls" if calls else "stop",
                usage=usage,
            )
        ),
    ]


def _scripted(
    monkeypatch: pytest.MonkeyPatch, turns: Sequence[list[chat.StreamEvent]]
) -> list[list[dict[str, Any]]]:
    """Replace `chat.stream` with a script, recording the messages each turn was sent."""
    sent: list[list[dict[str, Any]]] = []
    remaining = list(turns)

    def _stream(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> AsyncIterator[chat.StreamEvent]:
        sent.append([dict(message) for message in messages])
        events = remaining.pop(0) if remaining else _turn(content="…")

        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            for event in events:
                yield event

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    return sent


def _failing_stream(
    failure: Exception, *, after: str | None = None
) -> Callable[..., AsyncIterator[chat.StreamEvent]]:
    """A `chat.stream` replacement that fails — optionally AFTER emitting one fragment.

    The `after` argument is the whole point of the helper: "did anything reach the person
    before the provider died" is the fact `run_copilot` decides the fallback on, and the
    two tests below differ only in it.
    """

    def _stream(*args: Any, **kwargs: Any) -> AsyncIterator[chat.StreamEvent]:
        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            if after is not None:
                yield chat.StreamEvent(text=after)
            raise failure

        return _iterate()

    return _stream


async def _drain(payload: CopilotAskIn = PAYLOAD) -> list[service.CopilotEvent]:
    return [event async for event in service.run_copilot(payload)]


# --- when the loop stops ---------------------------------------------------------------


async def test_a_prose_answer_ends_the_loop_in_one_turn(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _scripted(monkeypatch, [_turn(content="Nine in the morning.")])
    events = await _drain()
    assert len(sent) == 1
    assert [e.text for e in events if e.text] == ["Nine in the morning."]
    assert events[-1].spend is not None


async def test_a_valid_set_fields_stops_the_loop_immediately(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Stop as soon as `set_fields` is called." A second turn after a successful fill
    would be a second chance to change what a person has already been shown."""
    sent = _scripted(
        monkeypatch,
        [
            _turn(arguments=json.dumps({"items": [{"field_id": "open", "value": "09:00"}]})),
            _turn(content="should never run"),
        ],
    )
    events = await _drain()
    assert len(sent) == 1
    assert [e.fill for e in events if e.fill] == [
        (CopilotFillItem(field_id="open", value="09:00"),)
    ]


async def test_only_the_first_set_fields_call_of_a_turn_is_honoured(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OpenAI documents rare incorrectness in PARALLEL tool calls. Honouring two would
    apply as two changes what the person asked for as one, and give them an Undo that
    reverses half of it."""
    turn = _turn(arguments=json.dumps({"items": [{"field_id": "open", "value": "09:00"}]}))
    outcome = turn[-1].outcome
    assert outcome is not None
    turn[-1] = chat.StreamEvent(
        outcome=chat.ChatOutcome(
            content=outcome.content,
            tool_calls=(
                *outcome.tool_calls,
                chat.ToolCall(
                    id="call-2",
                    name="set_fields",
                    arguments=json.dumps({"items": [{"field_id": "open", "value": "10:00"}]}),
                ),
            ),
            finish_reason="tool_calls",
        )
    )
    _scripted(monkeypatch, [turn])
    fills = [e.fill for e in await _drain() if e.fill]
    assert fills == [(CopilotFillItem(field_id="open", value="09:00"),)]


# --- the refusal feedback, and the cap --------------------------------------------------


async def test_a_refused_fill_goes_back_to_the_model_and_the_correction_is_applied(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """That is what the turn budget is FOR. Surfacing the first refusal would make the
    copilot fail at the thing it exists to do whenever it guesses one field id wrong."""
    sent = _scripted(
        monkeypatch,
        [
            _turn(arguments=json.dumps({"items": [{"field_id": "status", "value": "live"}]})),
            _turn(arguments=json.dumps({"items": [{"field_id": "open", "value": "09:00"}]})),
        ],
    )
    events = await _drain()
    assert len(sent) == 2
    # The second turn carries the assistant's tool call AND our tool result naming the
    # reason — without the assistant message the provider rejects an orphan tool result.
    roles = [message["role"] for message in sent[1]]
    assert roles[-2:] == ["assistant", "tool"]
    assert "`status` is not writable" in str(sent[1][-1]["content"])
    assert "NOTHING was written" in str(sent[1][-1]["content"])
    assert [e.fill for e in events if e.fill] == [
        (CopilotFillItem(field_id="open", value="09:00"),)
    ]


async def test_the_loop_is_capped_and_says_so_rather_than_spinning(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool-calling loop that cannot end is a spinner that never stops, which is the
    failure a person cannot act on.

    FAILS IF: `MAX_TURNS` stops bounding the loop. The script here refuses forever, so an
    unbounded loop hangs the test rather than failing it — which is why the assertion is on
    the CALL COUNT as well as on the message.
    """
    refusal = _turn(arguments=json.dumps({"items": [{"field_id": "status", "value": "live"}]}))
    sent = _scripted(monkeypatch, [refusal for _ in range(service.MAX_TURNS + 2)])
    events = await _drain()

    assert len(sent) == service.MAX_TURNS
    said = [e.text for e in events if e.text]
    assert said and said[-1].startswith(service.EXHAUSTED_MESSAGE)
    # The reason travels with it: "narrow the request" is unhelpful advice to somebody
    # whose real problem is that the field is read-only.
    assert "`status` is not writable" in said[-1]
    assert not [e.fill for e in events if e.fill]
    assert events[-1].spend is not None


async def test_the_azure_turn_requests_the_output_ceiling(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every streamed turn carries `MAX_ANSWER_TOKENS` — the spend valve.

    FAILS IF: the cap stops reaching `chat.stream`. Without it the only brake on a model
    that keeps talking is `TOTAL_BUDGET_S` — 90 seconds of PAID output tokens, per turn.
    """
    kwargs_seen: list[dict[str, Any]] = []

    def _stream(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> AsyncIterator[chat.StreamEvent]:
        kwargs_seen.append(kwargs)

        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            for event in _turn(content="Nine."):
                yield event

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    await _drain()
    assert kwargs_seen and kwargs_seen[0]["max_tokens"] == service.MAX_ANSWER_TOKENS


async def test_a_turn_cut_off_at_the_ceiling_is_logged_and_the_answer_still_lands(
    azure_only: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`finish_reason == "length"` is the valve FIRING — a runaway generation, cut off.

    The person still gets what was said (truncated prose has already reached the screen)
    and the run is still metered; what must not happen is silence, because a turn that HIT
    the ceiling spent the ceiling. FAILS IF: the warning stops being emitted, or a
    truncated turn starts being treated as an error that loses the answer.
    """
    truncated = [
        chat.StreamEvent(text="Nine in the mor"),
        chat.StreamEvent(
            outcome=chat.ChatOutcome(
                content="Nine in the mor",
                finish_reason="length",
                usage=chat.TokenUsage(prompt_tokens=100, output_tokens=service.MAX_ANSWER_TOKENS),
            )
        ),
    ]
    _scripted(monkeypatch, [truncated])
    with caplog.at_level("WARNING"):
        events = await _drain()
    assert [e.text for e in events if e.text] == ["Nine in the mor"]
    assert events[-1].spend is not None
    assert any(record.message == "copilot_answer_truncated" for record in caplog.records)


# --- the money -----------------------------------------------------------------------


async def test_a_multi_turn_answer_is_metered_as_one_summed_quantity(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ONE `usage_events` row pair per user action, not per model turn: `requests_used` is
    a `COUNT(DISTINCT ref)`, so N rows for one question would make the request count and
    the rupee ceiling disagree about the same month."""
    _scripted(
        monkeypatch,
        [
            _turn(
                arguments=json.dumps({"items": [{"field_id": "status", "value": "x"}]}),
                usage=chat.TokenUsage(prompt_tokens=100, output_tokens=10),
            ),
            _turn(
                arguments=json.dumps({"items": [{"field_id": "open", "value": "09:00"}]}),
                usage=chat.TokenUsage(prompt_tokens=150, output_tokens=20),
            ),
        ],
    )
    spend = (await _drain())[-1].spend
    assert spend is not None
    assert spend.usage == chat.TokenUsage(prompt_tokens=250, output_tokens=30)


async def test_one_unreported_turn_makes_the_whole_run_unmeterable(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-140's rule. Summing the turns that DID report and calling it the total is a
    fabricated quantity — smaller than the truth, on an append-only ledger,
    indistinguishable from a real one, invisible to both the tenant's ceiling and the
    platform brake. `None` reaches `meter_assist`, which fires `ai_assist_unmeterable` and
    asks an operator to look."""
    _scripted(
        monkeypatch,
        [
            _turn(
                arguments=json.dumps({"items": [{"field_id": "status", "value": "x"}]}),
                usage=chat.TokenUsage(prompt_tokens=100, output_tokens=10),
            ),
            _turn(
                arguments=json.dumps({"items": [{"field_id": "open", "value": "09:00"}]}),
                usage=None,
            ),
        ],
    )
    spend = (await _drain())[-1].spend
    assert spend is not None
    assert spend.usage is None


# --- the one selector, and the disclosed fallback ---------------------------------------


async def test_nothing_configured_is_a_refusal_with_a_remediation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", None, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)

    with pytest.raises(ProblemError) as raised:
        await _drain()
    assert raised.value.code == f"assist_{extraction_module.NO_CREDENTIAL_REASON}"
    assert raised.value.remediation


async def test_azure_failing_before_a_single_fragment_falls_back_and_discloses(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The disclosed fallback (D-127 G-6), plus what the substitution costs on THIS
    surface: the fallback answers in prose and cannot fill fields, and the person is told
    that rather than left to discover it."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    _stream = _failing_stream(httpx.ConnectError("azure is down"))

    sent_messages: list[list[dict[str, Any]]] = []
    sent_kwargs: list[dict[str, Any]] = []

    async def _complete(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> chat.ChatOutcome:
        sent_messages.append([dict(message) for message in messages])
        sent_kwargs.append(kwargs)
        return chat.ChatOutcome(content="Nine in the morning.", finish_reason="stop")

    monkeypatch.setattr(chat, "stream", _stream)
    monkeypatch.setattr(chat, "complete", _complete)

    events = await _drain()
    assert [e.text for e in events if e.text] == ["Nine in the morning."]
    # NO TOOLS ON THIS LEG, and the model is TOLD so as the last thing it reads. A model
    # told to use a capability it has not been given answers "I've filled that in for you"
    # and fills nothing, which is worse than saying no.
    assert sent_messages and sent_messages[-1][-1]["role"] == "system"
    assert "NOT available to you" in str(sent_messages[-1][-1]["content"])
    assert sent_kwargs and "tools" not in sent_kwargs[-1]
    # The spend valve travels on this leg too — `max_tokens` IS on Sarvam's own client's
    # request body (VERIFIED-VENDOR-SDK, `workers/chat.py`), unlike `tools`.
    assert sent_kwargs[-1]["max_tokens"] == service.MAX_ANSWER_TOKENS
    spend = events[-1].spend
    assert spend is not None
    assert spend.capability.provider == extraction_module.SARVAM_PROVIDER
    # D-36 prices this leg at zero, so nothing is metered.
    assert spend.usage is None
    disclosure = service.disclosure_for(spend.capability)
    assert disclosure is not None
    assert disclosure.endswith(service.FALLBACK_NO_TOOLS_NOTE)


async def test_azure_failing_after_a_fragment_does_not_restart_on_the_fallback(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE ONE PLACE THIS DEPARTS FROM `run_assist`. Its answer is one object returned at
    the end, so it can retry on the second leg; ours has already been partly rendered into
    somebody's screen, and restarting would print a second, different answer under the
    first."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)
    fallback_called = False

    _stream = _failing_stream(httpx.ReadError("cut"), after="Nine in the ")

    async def _complete(*args: Any, **kwargs: Any) -> chat.ChatOutcome:
        nonlocal fallback_called
        fallback_called = True
        return chat.ChatOutcome(content="unused")

    monkeypatch.setattr(chat, "stream", _stream)
    monkeypatch.setattr(chat, "complete", _complete)

    with pytest.raises(httpx.ReadError):
        await _drain()
    assert fallback_called is False


# --- the Gemini leg: the account's own model, NON-STREAMED, with tools (D-478) ----------

GOOGLE_TENANT = extraction_module.TenantModelLeg(
    model=_GOOGLE_MODEL, provider="google", serves_dashboard=True, blocked_reason=None
)


@pytest.fixture
def google_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment holding ONLY a Gemini key: no Azure leg, no Sarvam. So the account's own
    Gemini leg is the only thing that can answer, and it does so on rung 1."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", None, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "gk-test", raising=False)


def _scripted_complete(
    monkeypatch: pytest.MonkeyPatch, outcomes: Sequence[chat.ChatOutcome]
) -> list[dict[str, Any]]:
    """Replace `chat.complete` with a script, AND make `chat.stream` explode — so a test on
    the Gemini leg proves it is NON-STREAMED (the whole point of D-478's transport choice)
    rather than merely not asserting a stream."""
    calls: list[dict[str, Any]] = []
    remaining = list(outcomes)

    async def _complete(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> chat.ChatOutcome:
        calls.append({"leg": leg, "messages": [dict(m) for m in messages], "kwargs": kwargs})
        return remaining.pop(0) if remaining else chat.ChatOutcome(content="…")

    def _forbidden_stream(*args: Any, **kwargs: Any) -> AsyncIterator[chat.StreamEvent]:
        # A plain function that raises the instant it is CALLED — `chat.stream(...)` on the
        # Gemini path would blow up before iteration, which is louder than an assertion that
        # only fires if the test remembers to iterate.
        raise AssertionError("the Gemini copilot leg must never stream (openai/openai-python#2806)")

    monkeypatch.setattr(chat, "complete", _complete)
    monkeypatch.setattr(chat, "stream", _forbidden_stream)
    return calls


async def _drain_google() -> list[service.CopilotEvent]:
    return [event async for event in service.run_copilot(PAYLOAD, tenant_leg=GOOGLE_TENANT)]


async def test_the_gemini_leg_fills_a_field_non_streamed_on_the_accounts_own_model(
    google_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RUNG 1, END TO END. The account's own Gemini model answers with a `tool_calls` array
    from a single blocking completion, the field reaches the browser exactly as on the Azure
    leg, and the leg is addressed at the Gemini OpenAI-compat host with the account's model as
    the wire model. Nothing is disclosed — this is the account's own provider."""
    calls = _scripted_complete(
        monkeypatch,
        [
            chat.ChatOutcome(
                content="",
                tool_calls=(
                    chat.ToolCall(
                        id="c1",
                        name="set_fields",
                        arguments=json.dumps({"items": [{"field_id": "open", "value": "09:00"}]}),
                    ),
                ),
                finish_reason="tool_calls",
                usage=chat.TokenUsage(prompt_tokens=120, output_tokens=15),
            )
        ],
    )
    events = await _drain_google()

    assert len(calls) == 1
    leg = calls[0]["leg"]
    assert leg.dialect == "google"
    assert leg.wire_model == _GOOGLE_MODEL
    # Built from the one permitted emitter of the Developer API host — assert against the
    # builder, never a host literal (the residency guard grants that literal to engine.py
    # alone; spelling it here would be a second constructor it refuses).
    assert leg.url == f"{google_openai_compat_base_url()}/chat/completions"
    # Tools were sent (field-filling works), and no `stream` — this is `chat.complete`.
    assert "tools" in calls[0]["kwargs"]
    # NO `max_tokens` on this leg, deliberately: whether Gemini's OpenAI-compat surface
    # accepts the key is UNVERIFIED from this container (`service.MAX_ANSWER_TOKENS`'s
    # note), and an unsupported key is a 400 that kills a working leg.
    assert "max_tokens" not in calls[0]["kwargs"]
    assert [e.fill for e in events if e.fill] == [
        (CopilotFillItem(field_id="open", value="09:00"),)
    ]
    spend = events[-1].spend
    assert spend is not None
    assert spend.capability.provider == extraction_module.GOOGLE_PROVIDER
    # Metered under the ACCOUNT'S OWN model, not the Azure setting (hard rule 7).
    assert spend.model == _GOOGLE_MODEL
    assert spend.usage == chat.TokenUsage(prompt_tokens=120, output_tokens=15)
    # Nothing was substituted, so nothing is disclosed.
    assert service.disclosure_for(spend.capability) is None


async def test_the_gemini_leg_answers_in_prose_when_the_model_calls_no_tool(
    google_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary end of a question on the non-streamed leg: the whole answer arrives as one
    text event (like the Sarvam fallback), then the spend. Proves the non-streamed turn is
    reshaped into the loop's events correctly."""
    _scripted_complete(
        monkeypatch,
        [chat.ChatOutcome(content="Nine in the morning.", finish_reason="stop", usage=None)],
    )
    events = await _drain_google()

    assert [e.text for e in events if e.text] == ["Nine in the morning."]
    spend = events[-1].spend
    assert spend is not None
    assert spend.capability.provider == extraction_module.GOOGLE_PROVIDER
    # No usage block: unknown cost, never zero — `meter_assist` records it unmetered, loudly.
    assert spend.usage is None


# --- the read tools: results feed back, and the loop CONTINUES (phase 1) -----------------
#
# The seam here is `tools.run_read_tool`, one layer below the loop — the same choice this
# file makes for the provider. What the tools actually return, whose rows they can see and
# who may run them is `copilot/tools_test.py`'s subject, against a real database; what is
# faked here is only "the lookup answered", which is the one thing this file is about.

TOOL_CONTEXT = tools_module.ToolContext(
    tenant_id=uuid.UUID("00000000-0000-7000-8000-000000000001"), role="owner"
)


def _tool_turn(*calls: tuple[str, str], content: str = "") -> list[chat.StreamEvent]:
    """One faked model turn that calls N tools, by (name, arguments)."""
    tool_calls = tuple(
        chat.ToolCall(id=f"call-{index}", name=name, arguments=arguments)
        for index, (name, arguments) in enumerate(calls)
    )
    return [
        *([chat.StreamEvent(text=content)] if content else []),
        chat.StreamEvent(
            outcome=chat.ChatOutcome(
                content=content, tool_calls=tool_calls, finish_reason="tool_calls"
            )
        ),
    ]


def _fake_tools(monkeypatch: pytest.MonkeyPatch, answers: dict[str, str]) -> list[dict[str, Any]]:
    """Replace the tool runner with a lookup table, recording every invocation."""
    seen: list[dict[str, Any]] = []

    async def _run(name: str, arguments: str, *, context: Any) -> str:
        seen.append({"name": name, "arguments": arguments, "context": context})
        return answers.get(name, f"no answer scripted for {name}")

    monkeypatch.setattr(tools_module, "run_read_tool", _run)
    return seen


async def _drain_with_tools(payload: CopilotAskIn = PAYLOAD) -> list[service.CopilotEvent]:
    return [event async for event in service.run_copilot(payload, tool_context=TOOL_CONTEXT)]


async def test_every_request_offers_the_write_tool_and_every_read_tool(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The array is composed once and does not vary — not by screen, not by tenant, not by
    role (`service.tool_array`, and `tools_test` pins the byte-identity). Here we only prove
    the loop actually SENDS it: a registry nothing offers is a registry the model cannot
    use."""
    kwargs_seen: list[dict[str, Any]] = []

    def _stream(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> AsyncIterator[chat.StreamEvent]:
        kwargs_seen.append(kwargs)

        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            for event in _turn(content="Nine."):
                yield event

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)
    await _drain_with_tools()
    names = [tool["function"]["name"] for tool in kwargs_seen[0]["tools"]]
    assert names[0] == "set_fields"
    # Every family the registry composes actually reaches the wire: a read tool the loop
    # never sends is a question the model cannot answer, and a write tool it never sends
    # is a change it cannot offer.
    assert tools_module.READ_TOOL_NAMES <= set(names)
    assert {schema["function"]["name"] for schema in write_tools.write_tool_schemas()} <= set(names)


async def test_a_read_tool_result_is_fed_back_and_the_model_then_answers_in_prose(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE BEHAVIOURAL CHANGE OF PHASE 1. Before this, a turn that produced no `set_fields`
    call ENDED the loop — so a lookup would have been a tool call nobody answered and an
    answer nobody wrote. Now the result goes back as a `role: "tool"` message and the model
    gets another turn to use it.

    FAILS IF: the loop goes back to ending on "no set_fields call", which turns every
    business question into silence."""
    _fake_tools(monkeypatch, {"business_snapshot": "Last 30 days: 12 calls, 8 connected."})
    sent = _scripted(
        monkeypatch,
        [
            _tool_turn(("business_snapshot", '{"days": 30}')),
            _turn(content="You've had 12 calls and 8 connected."),
        ],
    )
    events = await _drain_with_tools()

    assert len(sent) == 2
    # The second turn carries the assistant's own tool call AND our result — an orphan
    # tool message (or an orphan tool CALL) is rejected by the provider.
    roles = [message["role"] for message in sent[1]]
    assert roles[-2:] == ["assistant", "tool"]
    assert sent[1][-2]["tool_calls"][0]["function"]["name"] == "business_snapshot"
    assert "12 calls, 8 connected" in str(sent[1][-1]["content"])
    assert [e.text for e in events if e.text] == ["You've had 12 calls and 8 connected."]
    assert events[-1].spend is not None


async def test_two_read_tools_chain_inside_one_answer(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEARCH → READ → ANSWER, which is the shape `MAX_TURNS` was raised for. The second
    lookup is chosen AFTER the first result is in the message list, which a single round of
    parallel calls cannot express."""
    seen = _fake_tools(
        monkeypatch,
        {"leads_search": "1 leads with status hot:\n- Ramesh", "calls_recent": "1 calls:\n- 90s"},
    )
    sent = _scripted(
        monkeypatch,
        [
            _tool_turn(("leads_search", '{"status": "hot", "limit": null}')),
            _tool_turn(("calls_recent", '{"limit": 5}')),
            _turn(content="Ramesh is your only hot lead; his last call ran 90s."),
        ],
    )
    events = await _drain_with_tools()

    assert len(sent) == 3
    assert [call["name"] for call in seen] == ["leads_search", "calls_recent"]
    # The chain is visible in the message list the LAST turn was sent: both results are
    # there, in order.
    contents = [str(message.get("content")) for message in sent[2]]
    assert any("Ramesh" in content for content in contents)
    assert any("90s" in content for content in contents)
    assert [e.text for e in events if e.text] == [
        "Ramesh is your only hot lead; his last call ran 90s."
    ]


async def test_independent_calls_in_one_turn_are_all_run_and_all_answered(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two lookups with no ordering between them are one turn, not two. Each gets its own
    `role: "tool"` message keyed by the id the model issued — a provider rejects the next
    request if an issued call has no result."""
    _fake_tools(monkeypatch, {"leads_search": "leads here", "calls_recent": "calls here"})
    sent = _scripted(
        monkeypatch,
        [
            _tool_turn(("leads_search", "{}"), ("calls_recent", "{}")),
            _turn(content="Both look fine."),
        ],
    )
    await _drain_with_tools()

    tool_messages = [message for message in sent[1] if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call-0", "call-1"]
    assert [message["content"] for message in tool_messages] == ["leads here", "calls here"]


async def test_more_lookups_than_the_per_turn_cap_are_refused_with_a_sentence(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A turn asking for a dozen lookups has stopped answering a question, and each one is a
    database round trip against a shared pool. The extras are REFUSED rather than dropped:
    a dropped call is an issued `tool_call_id` with no result, which the provider rejects."""
    seen = _fake_tools(monkeypatch, {"calls_recent": "calls here"})
    over = tools_module.MAX_CALLS_PER_TURN + 2
    sent = _scripted(
        monkeypatch,
        [_tool_turn(*(("calls_recent", "{}") for _ in range(over))), _turn(content="Done.")],
    )
    await _drain_with_tools()

    assert len(seen) == tools_module.MAX_CALLS_PER_TURN
    tool_messages = [message for message in sent[1] if message["role"] == "tool"]
    assert len(tool_messages) == over, "every issued call is answered, including the refused"
    assert "Not run" in str(tool_messages[-1]["content"])


async def test_the_tool_context_the_route_built_is_what_the_tool_is_run_under(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHO IS ASKING reaches the tool, because that is what scopes the RLS session and what
    the permission check judges. A loop that dropped it would run every lookup unscoped —
    which `tools.run_read_tool` refuses, so the symptom would be a copilot that can never
    look anything up rather than a leak; both are defects and this is the one that catches
    them."""
    seen = _fake_tools(monkeypatch, {"leads_search": "leads here"})
    _scripted(monkeypatch, [_tool_turn(("leads_search", "{}")), _turn(content="Done.")])
    await _drain_with_tools()

    assert seen[0]["context"] == TOOL_CONTEXT


async def test_a_turn_that_asks_for_a_write_and_a_lookup_is_still_the_write(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`set_fields` KEEPS ITS SEMANTICS EXACTLY: one call honoured, one fill, one Undo, loop
    over. It is checked first, so a mixed turn resolves the way it did before the read tools
    existed — the read results would have nowhere to go once the fill has been emitted, and
    a second round after the person has been shown a change is the very thing
    `test_a_valid_set_fields_stops_the_loop_immediately` forbids."""
    seen = _fake_tools(monkeypatch, {"leads_search": "leads here"})
    sent = _scripted(
        monkeypatch,
        [
            _tool_turn(
                ("leads_search", "{}"),
                ("set_fields", json.dumps({"items": [{"field_id": "open", "value": "09:00"}]})),
            ),
            _turn(content="should never run"),
        ],
    )
    events = await _drain_with_tools()

    assert len(sent) == 1
    assert seen == [], "no lookup runs once the fill has been decided"
    assert [e.fill for e in events if e.fill] == [
        (CopilotFillItem(field_id="open", value="09:00"),)
    ]


async def test_a_model_that_only_ever_looks_things_up_still_ends_with_a_sentence(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap is what stops a lookup loop being a spinner that never stops. FAILS IF:
    `MAX_TURNS` stops bounding the read path — the script here looks things up forever, so
    an unbounded loop hangs rather than fails, which is why the CALL COUNT is asserted."""
    _fake_tools(monkeypatch, {"calls_recent": "calls here"})
    sent = _scripted(
        monkeypatch,
        [_tool_turn(("calls_recent", "{}")) for _ in range(service.MAX_TURNS + 2)],
    )
    events = await _drain_with_tools()

    assert len(sent) == service.MAX_TURNS
    said = [e.text for e in events if e.text]
    assert said and said[-1].startswith(service.EXHAUSTED_MESSAGE)
    assert events[-1].spend is not None
