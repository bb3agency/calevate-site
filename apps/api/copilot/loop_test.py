"""The bounded tool-calling loop: when it stops, what it costs, and what it discloses.

The provider is replaced at `chat.stream` / `chat.complete` — the SEAM ONE LAYER BELOW the
loop — so the accumulator, the frame filter and the request shape are still the real ones
and are proved separately in `apps/workers/chat_test.py`. What is faked here is only "what
the model said", which is the one thing no test can obtain honestly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import httpx
import pytest
from calevate_shared.engine import GOOGLE_DIRECT_MODELS, google_openai_compat_base_url

from apps.api.copilot import service
from apps.api.copilot.sanitize import has_invisible
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


async def test_the_exhaustion_message_is_stripped_and_the_model_cannot_pad_it(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one text event this module ASSEMBLES rather than forwards.

    Every other fragment is stripped as it leaves `turn`; this one is built after the loop
    and quotes `field_id`s the MODEL wrote, so it needs both halves of the egress rule.

    FAILS IF: the strip is dropped (a tag-block character reaches the panel, where the
    preview a person approves and the string behind it can differ), or if the model's own
    id stops being bounded (it is quoted into the next turn's prompt AND onto the screen,
    so an unbounded one is a model that can paste a wall of text into somebody's panel).
    """
    padded = "z" * 5_000
    refusal = _turn(
        arguments=json.dumps(
            {"items": [{"field_id": f"status\U000e0041{padded}", "value": "live"}]}
        )
    )
    _scripted(monkeypatch, [refusal for _ in range(service.MAX_TURNS + 2)])
    events = await _drain()

    said = [e.text for e in events if e.text]
    assert said and said[-1].startswith(service.EXHAUSTED_MESSAGE)
    assert not has_invisible(said[-1])
    # Bounded, and bounded well under what the model sent — a real field id is 200 long
    # (`schemas._MAX_ID`), so nothing legitimate is being cut here.
    assert len(said[-1]) < len(padded)
