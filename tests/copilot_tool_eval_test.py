"""Pip's tool-choice eval harness (`scripts/copilot_tool_eval.py`, D-779), run offline.

No model is called. The fake turn below stands in at `service.streamed_turn`, the seam the
production loop uses, so what is proven is the fixture, the request the harness would send
and the scorer; a model's accuracy comes only from an operator run with a credential.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from apps.api.copilot import service
from apps.api.copilot.admin_prompt import ADMIN_SYSTEM_PROMPT
from apps.workers import chat
from scripts import copilot_tool_eval as harness


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
        assert list(tools) == service.tool_array(realm)
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
    ("call_place", "agent_test_call"),
    ("lead_set_status", "leads_bulk_update"),
    ("platform_tenants", "admin_client_standing"),
)


@pytest.mark.parametrize(("first", "second"), SIBLINGS)
def test_overlapping_tools_each_name_the_other(first: str, second: str) -> None:
    descriptions = {
        tool["function"]["name"]: tool["function"]["description"]
        for tool in service.tool_array("admin")
    }
    assert f"`{second}`" in descriptions[first]
    assert f"`{first}`" in descriptions[second]
