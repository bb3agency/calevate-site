"""The extraction request, as WP-C left it: the agent's language named, an output rule
after the transcript, the strict schema on the Sarvam leg, and reasoning effort stated.

Each test drives the shipped function and reads what it would put on the wire; no
credential and no network are needed (`chat.complete` is replaced at the seam the
extractors call through).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from apps.workers import chat
from apps.workers import extraction as extraction_module
from apps.workers.chat import ChatOutcome
from apps.workers.extraction import (
    RESPONSE_SCHEMA_NAME,
    SARVAM_EXTRACTION_REASONING_EFFORT,
    SarvamExtractor,
    build_response_schema,
    extract_call,
)
from calevate_shared.extraction import (
    MODEL_MOMENT_KINDS,
    ExtractionField,
    ExtractionSchemaSpec,
    MomentsBrief,
    build_extraction_prompt,
)

SPEC = ExtractionSchemaSpec(
    fields=[ExtractionField(key="name", label="Caller name", type="text")],
)
TRANSCRIPT = "agent: Namaste.\ncaller: Mera naam Arjun hai."
OUTPUT_RULE = (
    "Return only the JSON object, by the rules above. Use null for anything the caller did not say."
)


# --- 1. the language the prompt names (C3) ----------------------------------------------


def test_a_telugu_agent_keeps_the_wording_the_golden_set_was_scored_on() -> None:
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT, languages=["te-IN"])
    assert (
        "The call is in Telugu, often code-mixed with English or Hindi, and it may arrive in\n"
        "native Telugu script. Do not translate; extract."
    ) in prompt
    assert prompt == build_extraction_prompt(SPEC, TRANSCRIPT), "te-IN is the default"


def test_a_hindi_agent_is_named_as_hindi_and_not_telugu() -> None:
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT, languages=["hi-IN"])
    assert (
        "The call is in Hindi, often code-mixed with English, and it may arrive in\n"
        "native Devanagari script."
    ) in prompt
    assert "The call is in Telugu" not in prompt


def test_an_english_agent_is_named_without_a_native_script() -> None:
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT, languages=["en-IN"])
    assert "The call is in English, and the caller may mix in words from" in prompt
    assert "Latin script" not in prompt


def test_extra_languages_follow_the_primary_once_each() -> None:
    prompt = build_extraction_prompt(
        SPEC, TRANSCRIPT, languages=["te-IN", "hi-IN", "en-IN", "hi-IN"]
    )
    assert "The call is in Telugu" in prompt
    assert "The caller may also speak Hindi or English." in prompt


def test_an_unknown_code_falls_back_to_the_default_rather_than_being_named() -> None:
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT, languages=["xx-YY"])
    assert "The call is in Telugu" in prompt
    assert "xx-YY" not in prompt


# --- 2. the output rule after the transcript (C4) ---------------------------------------


@pytest.mark.parametrize("moments", [None, MomentsBrief()])
def test_the_output_rule_closes_the_prompt_after_the_fenced_transcript(
    moments: MomentsBrief | None,
) -> None:
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT, moments=moments)
    body, _, tail = prompt.partition("\nTranscript:\n")
    assert tail.rstrip().endswith(OUTPUT_RULE)
    assert (
        tail.index("Mera naam Arjun") < tail.index("End of transcript.") < tail.index(OUTPUT_RULE)
    )
    assert 'between "Transcript:" and "End of transcript."' in body, (
        "the evidence rule must fence the transcript, or the closing line reads as a caller's"
    )


# --- 3. the Sarvam leg on the wire (C1, C2) ---------------------------------------------


class _Wire:
    """`chat.complete` replaced: records each request and answers from a script."""

    def __init__(self, *answers: ChatOutcome | httpx.HTTPStatusError) -> None:
        self._answers = list(answers)
        self.requests: list[dict[str, Any]] = []

    async def complete(self, leg: chat.ChatLeg, messages: Any, **kwargs: Any) -> ChatOutcome:
        self.requests.append({"leg": leg, "messages": messages, **kwargs})
        answer = self._answers.pop(0)
        if isinstance(answer, httpx.HTTPStatusError):
            raise answer
        return answer


def _refused(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://sarvam.invalid/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(str(status), request=request, response=response)


ANSWER = ChatOutcome(content='{"name": "Arjun", "summary": "s"}', finish_reason="stop")


def _format(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(request["response_format"])


async def test_sarvam_is_sent_the_strict_schema_and_an_explicit_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _Wire(ANSWER)
    monkeypatch.setattr(extraction_module.chat, "complete", wire.complete)

    raw = await SarvamExtractor("key").run(SPEC, TRANSCRIPT, languages=("hi-IN",))

    assert raw["name"] == "Arjun"
    (request,) = wire.requests
    assert _format(request) == {
        "type": "json_schema",
        "json_schema": {
            "name": RESPONSE_SCHEMA_NAME,
            "strict": True,
            "schema": build_response_schema(SPEC),
        },
    }
    assert request["reasoning_effort"] == SARVAM_EXTRACTION_REASONING_EFFORT == "low"
    assert "The call is in Hindi" in request["messages"][0]["content"]


async def test_a_moments_request_carries_the_moments_list_in_its_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _Wire(ANSWER)
    monkeypatch.setattr(extraction_module.chat, "complete", wire.complete)

    await SarvamExtractor("key").run(SPEC, TRANSCRIPT, moments=MomentsBrief())

    schema = _format(wire.requests[0])["json_schema"]["schema"]
    assert "moments" in schema["required"]
    item = schema["properties"]["moments"]["items"]
    assert set(item["properties"]["kind"]["enum"]) == MODEL_MOMENT_KINDS
    assert "moments" not in build_response_schema(SPEC)["properties"]


async def test_a_400_on_the_schema_degrades_to_json_object_and_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    wire = _Wire(_refused(400), ANSWER)
    monkeypatch.setattr(extraction_module.chat, "complete", wire.complete)
    caplog.set_level(logging.WARNING)

    raw = await SarvamExtractor("key").run(SPEC, TRANSCRIPT)

    assert raw["name"] == "Arjun"
    assert [_format(r)["type"] for r in wire.requests] == ["json_schema", "json_object"]
    assert any(r.getMessage() == "sarvam_json_schema_unsupported" for r in caplog.records)


async def test_any_other_refusal_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    wire = _Wire(_refused(429))
    monkeypatch.setattr(extraction_module.chat, "complete", wire.complete)

    with pytest.raises(httpx.HTTPStatusError):
        await SarvamExtractor("key").run(SPEC, TRANSCRIPT)
    assert len(wire.requests) == 1


async def test_a_second_400_raises_the_first_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _refused(400)
    wire = _Wire(first, _refused(400))
    monkeypatch.setattr(extraction_module.chat, "complete", wire.complete)

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await SarvamExtractor("key").run(SPEC, TRANSCRIPT)
    assert raised.value is first


async def test_reasoning_can_be_switched_off_for_the_comparison_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _Wire(ANSWER)
    monkeypatch.setattr(extraction_module.chat, "complete", wire.complete)

    await SarvamExtractor("key", reasoning_effort="off").run(SPEC, TRANSCRIPT)

    assert wire.requests[0]["reasoning_effort"] == "off"


def test_off_is_sent_as_json_null_and_an_unset_effort_is_not_sent() -> None:
    leg = chat.ChatLeg(url="https://x.invalid", api_key="k", wire_model="m", dialect="sarvam")

    def body(effort: chat.ReasoningEffort | None) -> dict[str, Any]:
        return chat._request_body(
            leg,
            [],
            temperature=None,
            response_format=None,
            tools=None,
            tool_choice=None,
            stream=False,
            reasoning_effort=effort,
        )

    assert body("off")["reasoning_effort"] is None
    assert body("low")["reasoning_effort"] == "low"
    assert "reasoning_effort" not in body(None)


# --- 4. who is told the language --------------------------------------------------------


class _TwoArgumentDouble:
    """The shape every test double and the offline runner have: no keywords at all."""

    model_name = "double"

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        return {"name": "Arjun"}


async def test_a_runner_that_does_not_read_languages_is_not_handed_them() -> None:
    output = await extract_call(
        SPEC, TRANSCRIPT, extractor=_TwoArgumentDouble(), languages=("hi-IN",)
    )
    assert output.data == {"name": "Arjun"}
    assert not output.errors


# --- 5. the golden harness scores what the pipeline sends -------------------------------


class _ReadingDouble:
    """A runner that reads languages and reports usage, as the Sarvam leg does."""

    model_name = "reading-double"
    reads_languages = True

    def __init__(self) -> None:
        self.languages: list[tuple[str, ...]] = []
        self.last_usage: chat.TokenUsage | None = None

    async def run(
        self, spec: ExtractionSchemaSpec, transcript: str, *, languages: tuple[str, ...] = ()
    ) -> dict[str, Any]:
        self.languages.append(tuple(languages))
        self.last_usage = chat.TokenUsage(prompt_tokens=1200, output_tokens=300)
        return {}


async def test_the_harness_passes_each_cases_language_and_keeps_its_usage() -> None:
    from scripts import eval as harness

    case = {
        "id": "c",
        "title": "t",
        "scenario": 1,
        "vertical": "clinic",
        "language": "hi-IN",
        "transcript": ["agent: Namaste, AI assistant, call record ho rahi hai.", "caller: Haan."],
    }
    runner = _ReadingDouble()
    result = await harness.run_case(SPEC, case, runner)
    default = await harness.run_case(SPEC, {**case, "language": None}, runner)

    assert runner.languages == [("hi-IN",), ("te-IN",)]
    assert result.usage == chat.TokenUsage(prompt_tokens=1200, output_tokens=300)
    assert default.usage is not None and default.usage is not result.usage

    silent = await harness.run_case(SPEC, {**case, "transcript": []}, runner)
    assert silent.usage is None, "a case that never reached the model reports no cost"


def test_the_comparison_reports_tokens_per_provider_in_thousands() -> None:
    from scripts import eval as harness

    usage = chat.TokenUsage(prompt_tokens=123_456, output_tokens=7_890)
    runs = [
        harness.ProviderRun(
            provider="sarvam",
            model="sarvam-105b",
            results=[harness.CaseResult("a", "t", 1, usage=usage), harness.CaseResult("b", "t", 1)],
            regressions=[],
        ),
        harness.ProviderRun(provider="offline", model="o", results=[], regressions=[]),
    ]
    meta = {"client": "ci", "vertical": "all", "ran_at": "now", "cases": 2}
    document = harness.render_comparison(runs, meta)
    assert "| sarvam | 1/2 | 123.5 | 7.9 | 7890 |" in document
    assert "| offline | 0/0 |" in document
    assert "123456" not in document
