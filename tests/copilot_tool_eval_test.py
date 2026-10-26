"""Pip's tool-choice eval harness (`scripts/copilot_tool_eval.py`, D-779), run offline.

No model is called. The fake turn below stands in at `service.streamed_turn`, the seam the
production loop uses, so what is proven is the fixture, the request the harness would send
and the scorer; a model's accuracy comes only from an operator run with a credential.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.copilot import service
from apps.api.copilot.admin_prompt import ADMIN_SYSTEM_PROMPT
from apps.api.copilot.prompt import SCREEN_OPEN
from apps.api.copilot.schemas import CopilotStepEvent
from apps.api.core import redis as redis_module
from apps.workers import chat
from scripts import copilot_tool_eval as harness


@pytest.fixture(autouse=True)
def _harness_owns_its_redis_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """`harness.main` runs its own `asyncio.run` loops, not the suite's session loop.

    A connection it opened in the process-wide Redis client would stay pooled after its loop
    closed, and the next test to draw it fails with "Event loop is closed" (the signup quota
    then refuses with a 503). So the harness builds a client of its own, which it closes in
    its own loop, and the suite's client is put back untouched afterwards.
    """
    monkeypatch.setattr(redis_module, "_client", None)


def _case(case_id: str) -> harness.Case:
    return next(case for case in harness.load_cases() if case.id == case_id)


def test_the_fixture_is_consistent_with_both_realms_tool_arrays() -> None:
    cases = harness.load_cases()
    assert harness.fixture_problems(cases) == []
    assert len(cases) >= 40
    assert {case.realm for case in cases} == {"client", "admin"}
    kinds = {case.kind for case in cases}
    assert {"read", "action", "fill", "navigate", "conversation", "guard"} <= kinds


def test_the_oracle_scores_every_case_right(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.main([]) == 0
    total = len(harness.load_cases())
    assert f"right {total}/{total}" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("case_id", "calls", "failure"),
    [
        ("c-create-on-form", ("set_fields",), "wrong_fill"),
        ("c-injected-note", ("dnc_add",), "forbidden"),
        ("c-lead-count", (), "missed"),
        ("c-thanks", ("business_snapshot",), "unwanted"),
        ("c-lead-count", ("leads_semantic_search",), "wrong_tool"),
        ("a-rate-untyped", ("healer_attest_rate",), "forbidden"),
    ],
)
def test_the_scorer_names_each_failure(case_id: str, calls: tuple[str, ...], failure: str) -> None:
    assert failure in harness.score(_case(case_id), calls).failures


def test_a_case_that_allows_words_or_a_lookup_accepts_either() -> None:
    case = _case("c-buy-credit")
    assert harness.score(case, ()).right
    assert harness.score(case, ("billing_overview",)).right


def test_a_fixture_naming_a_tool_the_realm_lacks_is_refused(tmp_path: Path) -> None:
    fixture = {
        "cases": [
            {
                "id": "x",
                "realm": "client",
                "kind": "read",
                "route": "/c/x",
                "title": "X",
                "question": "?",
                "expect": ["platform_tenants"],
            }
        ]
    }
    path = tmp_path / "f.json"
    path.write_text(json.dumps(fixture), "utf-8")
    problems = harness.fixture_problems(harness.load_cases(path))
    assert problems == ["x: client realm offers no `platform_tenants`"]


def test_a_provider_without_a_credential_refuses_rather_than_scoring(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(service, "chat_leg", lambda provider, *, model: None)
    assert harness.main(["--provider=azure"]) == harness.CANNOT_RUN
    assert "CANNOT RUN" in capsys.readouterr().out


def test_a_model_run_sends_the_production_turn_and_records_names_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    leg = chat.ChatLeg(
        url="https://model.invalid/v1", api_key="k", wire_model="m", dialect="google"
    )
    monkeypatch.setattr(service, "chat_leg", lambda provider, *, model: leg)
    sent: list[tuple[str, int]] = []

    async def fake_turn(
        used: chat.ChatLeg,
        messages: Sequence[chat.ChatMessage],
        tools: Sequence[Mapping[str, object]],
    ) -> AsyncIterator[chat.StreamEvent]:
        assert used is leg
        system: Any = messages[0]
        realm = "admin" if system["content"] == ADMIN_SYSTEM_PROMPT else "client"
        assert list(tools) in (
            service.tool_array(realm, account_open=True),
            service.tool_array(realm, account_open=False),
        )
        sent.append((realm, len(tools)))
        call = chat.ToolCall(id="1", name="leads_search", arguments='{"status": null}')
        usage = chat.TokenUsage(prompt_tokens=100, output_tokens=5, cached_prompt_tokens=60)
        yield chat.StreamEvent(
            outcome=chat.ChatOutcome(content="", tool_calls=(call,), usage=usage)
        )

    monkeypatch.setattr(service, "streamed_turn", fake_turn)
    record = tmp_path / "run.json"
    assert harness.main(["--provider=google", "--model=m", f"--record={record}"]) == 0
    out = capsys.readouterr().out
    total = len(harness.load_cases())
    assert len(sent) == total and {realm for realm, _ in sent} == {"client", "admin"}
    assert f"tokens: prompt={100 * total} cached={60 * total}" in out
    recorded = json.loads(record.read_text("utf-8"))
    assert recorded["calls"]["c-lead-count"] == ["leads_search"]
    assert "status" not in record.read_text("utf-8")

    assert harness.main([f"--replay={record}", "--min-right=0.99"]) == 1
    assert "FAIL c-thanks [unwanted]" in capsys.readouterr().out


#: Tools whose subjects overlap, so each description must say when to use the other
#: (Anthropic "Writing effective tools for agents", OpenAI function-calling guide; S14, S18).
SIBLINGS = (
    ("leads_search", "leads_semantic_search"),
    ("search_calls", "search_knowledge"),
    ("calls_recent", "search_calls"),
    ("agent_edit", "agent_edit_live"),
    ("agent_capture_fields_set", "agent_capture_fields_set_live"),
    ("call_place", "agent_test_call"),
    ("lead_set_status", "leads_bulk_update"),
    ("platform_tenants", "admin_client_standing"),
    ("agent_script_suggest", "agent_tests_fix"),
    ("propose_knowledge", "knowledge_teach"),
    ("agent_script_put_live", "agent_changes_apply"),
    ("agent_script_discard", "agent_changes_apply"),
    ("agent_prepare", "agent_publish"),
    ("billing_overview", "billing_settings"),
)


@pytest.mark.parametrize(("first", "second"), SIBLINGS)
def test_overlapping_tools_each_name_the_other(first: str, second: str) -> None:
    descriptions = {
        tool["function"]["name"]: tool["function"]["description"]
        for tool in (*service.tool_array("client"), *service.tool_array("admin"))
    }
    assert f"`{second}`" in descriptions[first]
    assert f"`{first}`" in descriptions[second]


# --- the operator's live run (D-816) ------------------------------------------------------


def test_the_live_run_refuses_without_the_spend_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.main(["--live"]) == harness.CANNOT_RUN
    assert "--spend" in capsys.readouterr().out


def test_a_live_answer_records_tools_tokens_and_a_redacted_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`run_copilot` is the seam: what the harness records is what the loop emitted."""
    usage = chat.TokenUsage(
        prompt_tokens=16_000, output_tokens=100, cached_prompt_tokens=12_000, cached_reported=True
    )
    capability = service.assist_capability(tenant_leg=None, quota_exhausted=False)

    async def fake_run(*_: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        assert kwargs.get("principal") is None
        step = CopilotStepEvent(id="s", tool="platform_tenants", status="running", args="")
        yield service.CopilotEvent(step=step)
        yield service.CopilotEvent(text="Call them on 9876543210.")
        yield service.CopilotEvent(
            spend=service.CopilotSpend(usage=usage, capability=capability, model="m")
        )

    monkeypatch.setattr(service, "run_copilot", fake_run)
    monkeypatch.setattr(harness, "spend_cost", lambda spent, model: Decimal("0.0712"))
    case = _case("a-roster")
    answer = asyncio.run(harness.live_answer(case, None))
    assert answer.tools == ["platform_tenants"]
    assert answer.tokens_in == 16_000 and answer.tokens_cached == 12_000
    assert answer.cost_inr == Decimal("0.0712")
    assert "9876543210" not in answer.answer
    assert "a-roster | platform_tenants | 16000 | 12000 | 100 | 0.0712" in harness.render_live(
        [answer]
    )


def test_two_live_records_compare_side_by_side(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    row = {"tools": ["leads_search"], "tokens_in": 16_000, "tokens_cached": None}
    before = {"answers": {"a-roster": {**row, "tokens_out": 90, "cost_inr": "0.40"}}}
    after = {"answers": {"a-roster": {**row, "tokens_out": 80, "cost_inr": "0.10"}}}
    paths = [tmp_path / "b.json", tmp_path / "a.json"]
    for path, body in zip(paths, (before, after), strict=True):
        path.write_text(json.dumps(body), "utf-8")
    assert harness.main(["--compare", *map(str, paths)]) == 0
    assert "a-roster | leads_search -> leads_search" in capsys.readouterr().out


# --- a follow-up does not redo an earlier request (D-832) --------------------------------


def test_a_case_replays_its_history_before_the_screen_that_shows_the_present() -> None:
    case = _case("c-talk-language-after-kept")
    messages = service.build_messages(case.payload, "", case.realm)
    roles = [message["role"] for message in messages]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
    assert "I am drafting the whole script now" in messages[4]["content"]
    assert 'saves="autosave"' in messages[-1]["content"]
    assert "None waiting. The last one was added to the draft." in messages[-1]["content"]


@pytest.mark.parametrize(
    ("calls", "failures"),
    [
        (("set_fields",), {"wrong_fill", "forbidden", "unwanted"}),
        (("agent_script_suggest",), {"forbidden", "unwanted"}),
        ((), set()),
    ],
)
def test_a_language_question_after_a_kept_suggestion_is_answered_in_words(
    calls: tuple[str, ...], failures: set[str]
) -> None:
    assert set(harness.score(_case("c-talk-language-after-kept"), calls).failures) == failures


def test_an_overloaded_vendor_is_retried_rather_than_ending_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google answered 503 on the VPS (19 Oct 2026) and the run died on its first question."""
    attempts = 0

    async def streamed_turn(*_args: Any, **_kwargs: Any) -> AsyncIterator[chat.StreamEvent]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            request = httpx.Request("POST", "https://example.invalid")
            raise httpx.HTTPStatusError(
                "overloaded", request=request, response=httpx.Response(503, request=request)
            )
        call = chat.ToolCall(id="c1", name="leads_search", arguments="{}")
        yield chat.StreamEvent(outcome=chat.ChatOutcome(content="", tool_calls=(call,)))

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(service, "chat_leg", lambda *_a, **_k: object())
    monkeypatch.setattr(service, "build_messages", lambda *_a, **_k: [])
    monkeypatch.setattr(service, "streamed_turn", streamed_turn)
    monkeypatch.setattr(asyncio, "sleep", no_wait)

    choose = harness.model_turn("google", "gemini-3.1-flash-lite")
    assert choose is not None
    case = harness.load_cases()[0]

    async def first_question() -> tuple[str, ...]:
        return (await choose(case)).calls

    assert asyncio.run(first_question()) == ("leads_search",)
    assert attempts == 2


# --- the server's own checks beside the model's choice (D-833) ---------------------------


def _call(name: str, arguments: dict[str, Any]) -> chat.ToolCall:
    return chat.ToolCall(id="c", name=name, arguments=json.dumps(arguments, ensure_ascii=False))


@pytest.mark.parametrize("case_id", ["c-script-after-kept", "c-talk-language-after-kept"])
def test_the_screen_and_question_follow_the_history_and_the_prefix_ignores_them(
    case_id: str,
) -> None:
    """The screen is per-request and sits in the last message, after the replayed turns; the
    system prompt is the same bytes for any screen, so the cached prefix is unchanged."""
    case = _case(case_id)
    messages = service.build_messages(case.payload, "", case.realm)
    assert [m["role"] for m in messages[:2]] == ["system", "user"]
    assert all(SCREEN_OPEN not in str(m["content"]) for m in messages[:-1])
    assert SCREEN_OPEN in str(messages[-1]["content"])
    assert str(messages[-1]["content"]).endswith(f"The person asks: {case.payload.question}")
    other = _case("c-lead-count")
    assert messages[0] == service.build_messages(other.payload, "", other.realm)[0]


def test_a_fill_resting_on_the_earlier_request_is_refused_by_the_server() -> None:
    """The production failure (19 Oct 2026): the opening line filled again because an
    earlier message asked for it."""
    case = _case("c-script-after-kept")
    fill = {"field_id": "script-opening_line", "value": "నమస్కారం అండి, thanks."}
    stale = _call(
        "set_fields", {"because": "make the opening line warmer and shorter", "items": [fill]}
    )
    assert harness.server_refuses(case, stale)
    scored = harness.score(case, ("set_fields",), ("set_fields",))
    assert scored.caught and not scored.right


def test_an_answer_to_pips_own_question_is_a_fill_the_server_accepts() -> None:
    case = _case("c-fill-answer-only")
    call = _call(
        "set_fields",
        {
            "because": "10 to 8, closed on Sundays",
            "items": [
                {"field_id": "intake-hours-open", "value": "10:00"},
                {"field_id": "intake-hours-close", "value": "20:00"},
                {"field_id": "intake-closed-days", "value": "Sunday"},
            ],
        },
    )
    assert not harness.server_refuses(case, call)


def _whole(answers: dict[str, str | None]) -> dict[str, Any]:
    return {
        "agent_id": "0192f3a4-0000-7000-8000-0000000a9e01",
        "mode": "whole",
        "change": None,
        "answers": answers,
    }


def test_a_whole_script_before_the_five_answers_is_refused_by_the_server() -> None:
    case = _case("c-script-whole-asks-first")
    invented = _whole({"what_you_offer": "Organic groceries", "customers": "Home cooks"})
    assert harness.server_refuses(case, _call("agent_script_suggest", invented))
    assert harness.server_refuses(case, _call("agent_script_suggest", _whole({})))


def test_a_whole_script_from_the_owners_typed_answers_is_accepted() -> None:
    case = _case("c-script-whole-answered")
    answers = _whole(
        {
            "what_you_offer": "Organic groceries",
            "customers": "Home cooks call to order",
            "good_outcome": "Take their name and area.",
            "never_say": "Never promise same-day delivery",
        }
    )
    assert not harness.server_refuses(case, _call("agent_script_suggest", answers))


def test_the_report_counts_wrong_calls_the_server_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "run.json"
    calls = {case.id: list(harness.oracle(case)) for case in harness.load_cases()}
    calls["c-script-after-kept"] = ["set_fields"]
    calls["c-thanks"] = ["business_snapshot"]
    body = {"calls": calls, "refused": {"c-script-after-kept": ["set_fields"]}}
    record.write_text(json.dumps(body), "utf-8")
    assert harness.main([f"--replay={record}"]) == 0
    out = capsys.readouterr().out
    assert "refused by the server, reaching nobody: 1/2 wrong" in out
    assert "FAIL c-script-after-kept [wrong_fill,forbidden,unwanted] called=['set_fields']" in out
    assert "refused_by_server=['set_fields']" in out


def test_a_refused_call_is_handed_back_and_the_next_turn_is_what_is_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production loop returns a refusal to the model and asks again, so the person sees
    the second turn; the harness asks once more the same way and scores it as `then`."""
    case = _case("c-script-after-kept")
    stale = _call(
        "set_fields",
        {
            "because": "make the opening line warmer and shorter",
            "items": [{"field_id": "script-opening_line", "value": "x"}],
        },
    )
    handed_back: list[str] = []

    async def streamed_turn(
        _leg: object, messages: Sequence[chat.ChatMessage], _tools: object
    ) -> AsyncIterator[chat.StreamEvent]:
        last: Any = messages[-1]
        if last["role"] == "tool":
            handed_back.append(str(last["content"]))
            yield chat.StreamEvent(outcome=chat.ChatOutcome(content="Yes, it is saved."))
            return
        yield chat.StreamEvent(outcome=chat.ChatOutcome(content="", tool_calls=(stale,)))

    monkeypatch.setattr(service, "chat_leg", lambda *_a, **_k: object())
    monkeypatch.setattr(service, "streamed_turn", streamed_turn)
    choose = harness.model_turn("google", "gemini-3.1-flash-lite")
    assert choose is not None

    async def ask() -> harness.Choice:
        return await choose(case)

    chosen = asyncio.run(ask())

    assert chosen.calls == ("set_fields",) and chosen.refused == ("set_fields",)
    assert chosen.then == ()
    assert handed_back and handed_back[0].startswith("The fill was refused and NOTHING was written")
    assert service.UNQUOTED_FILL_REASON in handed_back[0]
    scored = harness.score(case, chosen.calls, chosen.refused, chosen.then)
    assert not scored.right and scored.recovered


def test_the_report_counts_what_the_person_sees_after_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "run.json"
    calls = {case.id: list(harness.oracle(case)) for case in harness.load_cases()}
    calls["c-script-after-kept"] = ["set_fields"]
    calls["c-script-whole-asks-first"] = ["agent_script_suggest"]
    body = {
        "calls": calls,
        "refused": {
            "c-script-after-kept": ["set_fields"],
            "c-script-whole-asks-first": ["agent_script_suggest"],
        },
        "then": {"c-script-after-kept": [], "c-script-whole-asks-first": ["agent_script_suggest"]},
    }
    record.write_text(json.dumps(body), "utf-8")
    assert harness.main([f"--replay={record}"]) == 0
    out = capsys.readouterr().out
    total = len(harness.load_cases())
    assert "right on the turn after the refusal: 1/2" in out
    assert f"right in what the person sees: {total - 1}/{total}" in out
    assert "then=[] (recovered)" in out
    assert "then=['agent_script_suggest']\n" in out + "\n"


def test_a_second_wrong_turn_the_server_refuses_again_is_reported_as_held(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "run.json"
    calls = {case.id: list(harness.oracle(case)) for case in harness.load_cases()}
    calls["c-script-after-kept"] = ["set_fields"]
    body = {
        "calls": calls,
        "refused": {"c-script-after-kept": ["set_fields"]},
        "then": {"c-script-after-kept": ["set_fields"]},
        "then_refused": {"c-script-after-kept": ["set_fields"]},
    }
    record.write_text(json.dumps(body), "utf-8")
    assert harness.main([f"--replay={record}"]) == 0
    out = capsys.readouterr().out
    assert "right on the turn after the refusal: 0/1" in out
    assert "wrong again and refused again, so still nothing reached the person: 1" in out
    assert "then=['set_fields'] then_refused_by_server=['set_fields']" in out


def test_a_read_before_asking_what_a_new_agent_should_do_is_fine() -> None:
    case = _case("c-agent-create-missing")
    assert harness.score(case, ("agents_list",)).right
    assert harness.score(case, ()).right
    assert not harness.score(case, ("agent_create",)).right
