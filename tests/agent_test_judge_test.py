"""The test-conversation judge (gaps D1-D5 of docs/evidence/prompting-practices-2026-10.md):
reason before verdict, the recording rule the agent was given, a judge from another model
family, the shuffled order, the account's own Gemini leg on the JSON ladder, and the
calibration report.

The model is replaced at `chat.complete`, so no credential or network is involved.
"""

from __future__ import annotations

import csv
import json
import uuid
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import assist_leg, lifecycle, test_conversations
from apps.api.agents.llm_models import install_dashboard_data_use_reader
from apps.api.agents.service import AgentRow, in_call_model
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.catalogue import CatalogueModel
from apps.workers import agent_test_ai, chat, script_assist
from apps.workers import agent_test_conversations as worker
from apps.workers.extraction import TenantModelLeg
from calevate_shared.engine import COPILOT_FAST_MODEL_DEFAULT, PLATFORM_RULES_TAIL_HEADER
from scripts import judge_calibration as calibration
from tests.agent_test_loop_test import BRIEF
from tests.hosted_voice_fakes import HostingEngine


@pytest.fixture(autouse=True)
def _nothing_attested() -> Any:
    install_dashboard_data_use_reader(None)
    yield
    install_dashboard_data_use_reader(None)


@pytest.fixture
def azure(monkeypatch: pytest.MonkeyPatch) -> Any:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)
    return settings


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch, azure: Any) -> Any:
    """Google's dashboard leg attested and keyed, and one Google model offerable."""
    monkeypatch.setattr(azure, "gemini_api_key", "g-test", raising=False)
    install_dashboard_data_use_reader(lambda: frozenset({"google"}))
    monkeypatch.setattr(
        assist_leg, "off_call_offerable_models", lambda: frozenset({COPILOT_FAST_MODEL_DEFAULT})
    )
    return azure


GOOGLE_LEG = TenantModelLeg(
    model="gemini-2.5-flash-lite", provider="google", serves_dashboard=True, blocked_reason=None
)


def _answering(body: dict[str, Any], legs: list[chat.ChatLeg], seen: list[str]) -> Any:
    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any) -> Any:
        legs.append(leg)
        seen.append(str(messages[-1]["content"]))
        return chat.ChatOutcome(
            content=json.dumps(body),
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=10, output_tokens=5),
        )

    return _complete


# --- D1: reason before verdict -----------------------------------------------------------


def test_the_judge_writes_its_reason_before_its_verdict() -> None:
    """FAILS IF: the strict schema puts the verdict before the reasoning that decides it
    (schema order is generation order)."""
    order = list(agent_test_ai._JUDGED_PROPERTIES)
    assert order[0] == "key" and order[-1] == "verdict"
    assert order.index("reason") < order.index("verdict")
    item = agent_test_ai._JUDGE_SCHEMA["properties"]["results"]["items"]  # type: ignore[index]
    assert item["required"] == order


# --- D2: the recording rule follows the engine -------------------------------------------


def test_the_judge_is_given_the_recording_answer_the_agent_was_given() -> None:
    """FAILS IF: the judge expects "the call is recorded" from an agent on an engine that
    records no audio, which would fail the truthful answer hard rule 5 requires."""
    recorded = agent_test_ai.truthful_answer_rules(BRIEF)
    assert "say yes: this call is recorded" in recorded
    unrecorded = agent_test_ai.truthful_answer_rules(replace(BRIEF, call_is_recorded=False))
    assert "the audio is not recorded" in unrecorded
    assert "yes: this call is recorded" not in unrecorded
    assert "you are an AI assistant" in unrecorded
    # The agent's own override header is not handed to the judge as an instruction.
    assert PLATFORM_RULES_TAIL_HEADER not in recorded
    assert "that the call is recorded" not in agent_test_ai.JUDGE_INSTRUCTION


async def test_the_judges_request_carries_the_agents_rules(
    azure: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    legs: list[chat.ChatLeg] = []
    seen: list[str] = []
    monkeypatch.setattr(chat, "complete", _answering({"results": []}, legs, seen))
    with pytest.raises(ProblemError):  # an empty verdict list is no answer on either leg
        await agent_test_ai.judge_conversations(
            replace(BRIEF, call_is_recorded=False), ["[k1] t\nCaller: hi\nAgent: hello"], {"k1"}
        )
    assert "the audio is not recorded" in seen[0]


async def test_a_brief_reads_the_engines_recording_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    created = await admin_service.create_organization(
        name="Judge Test",
        slug=f"tests-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Front desk",
            direction="inbound",
            language_primary="te-IN",
        )
        real = test_conversations.engine_capabilities()
        monkeypatch.setattr(
            test_conversations,
            "engine_capabilities",
            lambda: real.model_copy(update={"records_audio": False}),
        )
        brief = await test_conversations.load_brief(session, agent_id)
    assert brief.call_is_recorded is False


# --- D3: a judge from another family -----------------------------------------------------


def test_a_models_family_is_read_from_its_name_or_left_unknown() -> None:
    assert agent_test_ai.model_family("GPT-OSS 120B") == "openai"
    assert agent_test_ai.model_family("gpt-4o-mini") == "openai"
    assert agent_test_ai.model_family("gemini-2.5-flash-lite") == "google"
    assert agent_test_ai.model_family("sarvam-105b") == "sarvam"
    assert agent_test_ai.model_family("Prana [Voice]") is None
    assert agent_test_ai.model_family(None) is None


def test_an_agent_of_unknown_family_keeps_the_accounts_judge(azure: Any) -> None:
    assert agent_test_ai.judge_leg(GOOGLE_LEG, agent_model=None, quota_exhausted=False) is (
        GOOGLE_LEG
    )
    assert agent_test_ai.judge_leg(None, agent_model="Prana [Voice]", quota_exhausted=False) is (
        None
    )


def test_a_gemini_agent_is_judged_off_gemini(gemini: Any) -> None:
    """FAILS IF: our own Gemini agent (D-764) is graded by the same Gemini model."""
    assert agent_test_ai.answering_model(GOOGLE_LEG, quota_exhausted=False) == (
        "gemini-2.5-flash-lite"
    )
    leg = agent_test_ai.judge_leg(
        GOOGLE_LEG, agent_model="gemini-2.5-flash-lite", quota_exhausted=False
    )
    assert leg is None
    assert agent_test_ai.answering_model(leg, quota_exhausted=False) == (
        get_settings().azure_openai_model
    )


def test_an_openai_family_agent_is_judged_on_gemini_when_it_may_be(gemini: Any) -> None:
    leg = agent_test_ai.judge_leg(None, agent_model="GPT-OSS 120B", quota_exhausted=False)
    assert leg is not None and leg.model == COPILOT_FAST_MODEL_DEFAULT and leg.serves_dashboard


def test_with_no_other_family_the_judge_stays_and_never_drops_to_the_standby(
    azure: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Sarvam is another family but the disclosed standby; the judge is not moved there."""
    caplog.set_level("INFO")
    assert agent_test_ai.judge_leg(None, agent_model="GPT-OSS 120B", quota_exhausted=False) is (
        None
    )
    assert any(r.message == "agent_tests_judge_same_family" for r in caplog.records)


def test_the_in_call_model_is_the_one_a_publish_sends() -> None:
    engine = HostingEngine()
    row = cast(AgentRow, {"engine_model_id": "gpt-5-mini", "engine_voice_id": None})
    assert in_call_model(row, engine=engine) == "gpt-5-mini"
    # A choice of our own model while it is switched off is not the model the call runs.
    off = cast(AgentRow, {"engine_model_id": "byok:gemini-2.5-flash", "engine_voice_id": None})
    assert in_call_model(off, engine=engine) == get_settings().thinnest_in_call_default_model


async def test_an_engine_model_id_is_named_from_the_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = HostingEngine(
        models=(
            CatalogueModel(
                model_id="m-120", label="GPT-OSS 120B", call_capable=True, plan_allows=True
            ),
        )
    )

    class _Session:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            class _Result:
                def mappings(self) -> Any:
                    return self

                def first(self) -> dict[str, Any]:
                    return {"engine_model_id": "m-120", "engine_voice_id": None}

            return _Result()

    monkeypatch.setattr(worker, "tenant_session", lambda tenant_id: _Session())
    name = await worker.agent_in_call_model(uuid.uuid4(), uuid.uuid4(), engine)
    assert name == "GPT-OSS 120B" and engine.reads == 1


# --- D5: the order the judge reads -------------------------------------------------------


def test_the_judge_reads_a_shuffled_order_that_a_run_can_replay() -> None:
    first = agent_test_ai.judge_order(10, seed="run-a")
    assert sorted(first) == list(range(10))
    assert agent_test_ai.judge_order(10, seed="run-a") == first
    assert agent_test_ai.judge_order(10, seed="run-b") != first


# --- the account's own Gemini leg on the JSON ladder --------------------------------------


async def test_an_account_on_gemini_is_answered_by_gemini_and_says_so(
    gemini: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILS IF: an account whose Gemini leg serves the dashboard is answered by the
    standby while the answer claims Google (no disclosure, no usage to meter)."""
    legs: list[chat.ChatLeg] = []
    monkeypatch.setattr(chat, "complete", _answering({"ok": True}, legs, []))
    answer = await script_assist.ask_json(
        "d", "i", parse=lambda raw: raw.get("ok"), tenant_leg=GOOGLE_LEG
    )
    assert [leg.dialect for leg in legs] == ["google"]
    assert legs[0].wire_model == "gemini-2.5-flash-lite"
    assert answer.capability.provider == "google" and answer.usage is not None
    assert answer.model == "gemini-2.5-flash-lite"


async def test_a_silent_gemini_leg_falls_to_the_disclosed_standby(
    gemini: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any) -> Any:
        if leg.dialect == "google":
            return chat.ChatOutcome(content="not json", finish_reason="stop", usage=None)
        return chat.ChatOutcome(content='{"ok": true}', finish_reason="stop", usage=None)

    monkeypatch.setattr(chat, "complete", _complete)
    answer = await script_assist.ask_json(
        "d", "i", parse=lambda raw: raw.get("ok"), tenant_leg=GOOGLE_LEG
    )
    assert answer.capability.provider == "sarvam" and answer.capability.disclosure
    assert answer.model == script_assist.SARVAM_DEFAULT_LLM


# --- D4: calibration ---------------------------------------------------------------------


def test_agreement_is_scored_only_over_labelled_rows() -> None:
    judged = {
        "r:a": {"verdict": "passed", "model": "gpt-4o-mini", "position": 0, "of": 3},
        "r:b": {"verdict": "failed", "model": "gpt-4o-mini", "position": 1, "of": 3},
        "r:c": {"verdict": "needs_fix", "model": "gpt-4o-mini", "position": 2, "of": 3},
        "r:d": {"verdict": "passed", "model": "gpt-4o-mini", "position": 2, "of": 3},
    }
    labels = [
        {"run_id": "r", "key": "a", "human_verdict": "pass", "probe": ""},
        {"run_id": "r", "key": "b", "human_verdict": "failed", "probe": "ai"},
        {"run_id": "r", "key": "c", "human_verdict": "passed", "probe": ""},
        {"run_id": "r", "key": "d", "human_verdict": "", "probe": ""},
    ]
    pairs = calibration.pairs_from(labels, judged)
    assert len(pairs) == 3  # the unlabelled row is left out, never guessed
    result = calibration.agreement(pairs)
    assert result.exact == 2 and result.pass_agree == 2
    assert result.confusion[("passed", "needs_fix")] == 1
    assert result.kappa is not None and 0 < result.kappa < 1
    assert [p.position for p in pairs] == ["first", "middle", "last"]
    report = calibration.report(
        pairs, flipped=calibration.flips(judged, {"r:a": {"verdict": "failed"}})
    )
    assert "| all | 3 | 67% |" in report and "r:a: passed -> failed" in report


def test_kappa_is_undefined_when_everyone_says_the_same() -> None:
    same = [calibration.Pair(human="passed", judge="passed")] * 4
    assert calibration.cohen_kappa(same) is None
    assert calibration.cohen_kappa([]) is None
    assert "fill in `human_verdict`" in calibration.report([])


def test_the_export_is_blind_redacted_and_round_trips(tmp_path: Path) -> None:
    """FAILS IF: the labelling sheet shows the judge's verdict (the person would anchor on
    it), a number reaches it, or a result with no judge record is exported."""
    results = [
        {
            "key": "k1",
            "title": "Asks the price",
            "probe": None,
            "expect": "Gives the price.",
            "verdict": "failed",
            "conversation": [{"said": "my number is 9876543210", "reply": "ok", "tools": ["dnc"]}],
            "judge": {"verdict": "passed", "reason": "Fine.", "model": "m", "position": 0, "of": 1},
        },
        {"key": "k2", "title": "Old", "verdict": "passed", "conversation": []},
    ]
    exported = list(calibration.export_rows(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), results))
    assert len(exported) == 1
    row, entry = exported[0]
    assert "9876543210" not in row["conversation"]
    assert "passed" not in json.dumps(row) and row["human_verdict"] == ""
    assert entry["verdict"] == "passed" and entry["stored_verdict"] == "failed"
    sheet = tmp_path / "c.csv"
    with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=calibration.CSV_COLUMNS)
        writer.writeheader()
        writer.writerow({**row, "human_verdict": "Failed"})
    judge = tmp_path / "c.judge.json"
    judge.write_text(json.dumps({f"{row['run_id']}:k1": entry}), encoding="utf-8")
    assert calibration.main(["score", "--labels", str(sheet)]) == 0
    pairs = calibration.pairs_from(calibration.read_labels(sheet), calibration.read_judge(judge))
    assert pairs == [calibration.Pair(human="failed", judge="passed", model="m", position="first")]
