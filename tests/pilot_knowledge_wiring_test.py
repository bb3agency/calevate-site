"""Gate 8's REGISTRATION — the seam between the probes and the runner.

`tests/pilot_knowledge_test.py` covers the probes themselves. This file covers the thing
that was missing when they shipped: the probes were written, tested and INVISIBLE to the
runner, which reported gate 8 as "no implementation is registered ... it belongs to
another slice". A gate that cannot be reached from the CLI has not been delivered, so the
seam gets its own tests — the registry entry, the inputs file, and every way that file
can be absent, broken, or ask for something that cannot be trusted.

The rule the whole harness turns on is what most of these assert: an absent inputs file
reports NOT RUN **with the reason and the path**, never a silent pass and never a crash
that takes the rest of the run's gates down with it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from apps.api.engine.fake import FakeEngine
from calevate_shared.config import Settings
from scripts.pilot import knowledge, runner
from scripts.pilot.gates_api import GateContext


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        app_env="local",
        database_url="postgresql+psycopg://u:p@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        object_store_endpoint="http://localhost:9000",
        object_store_bucket="calevate",
        webhook_base_url="https://pilot.example.com",
        engine="fake",
    )


def _ctx(engine: Any = None) -> GateContext:
    return GateContext(engine=engine or FakeEngine(), settings=_settings())


def _check(result: Any, name: str) -> Any:
    matches = [c for c in result.checks if c.name == name]
    assert matches, f"no sub-check named {name!r} in {[c.name for c in result.checks]}"
    return matches[0]


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "gate8-inputs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- the registry --------------------------------------------------------------


def test_gate_8_is_registered_and_reachable_from_the_runner() -> None:
    """The defect this file exists for: `knowledge.py` exported no `GATES` mapping, so
    `--gates 8` reported that no implementation existed for a module holding 1,100 lines
    of implementation."""
    assert set(knowledge.GATES) == {8}
    runners, _unavailable = runner.gate_registry()
    assert 8 in runners


async def test_an_unregistered_gate_still_says_so_by_number() -> None:
    """The other half of the same property: registering gate 8 must not make an
    unimplemented gate look registered."""
    results, _skipped = await runner.run_gates([99], _ctx())
    assert results[0].status == "not_run"
    assert "no implementation is registered" in (results[0].blocked or "")


# --- the inputs file -----------------------------------------------------------


async def test_an_absent_inputs_file_is_not_run_with_the_path_and_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(knowledge.INPUTS_ENV, str(tmp_path / "absent.json"))
    result = await knowledge.run_gate_8(_ctx())
    assert result.status == "not_run"
    assert knowledge.DEFAULT_INPUTS_PATH in (result.blocked or "")
    assert knowledge.INPUTS_ENV in (result.blocked or "")
    assert knowledge.OPERATOR_SOURCED_FINDING in result.findings


async def test_a_malformed_inputs_file_blocks_without_quoting_its_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file can hold a Telugu FAQ and, if the operator pasted badly, a number. The
    refusal carries the exception TYPE and the path, never the content (hard rule 6)."""
    bad = tmp_path / "gate8-inputs.json"
    bad.write_text('{"min_recall": "+919876543210"}', encoding="utf-8")
    monkeypatch.setenv(knowledge.INPUTS_ENV, str(bad))
    result = await knowledge.run_gate_8(_ctx())
    assert result.status == "not_run"
    assert "could not be read" in (result.blocked or "")
    assert "9876543210" not in repr(result.as_dict())


async def test_a_present_file_produces_every_named_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(knowledge.INPUTS_ENV, str(_write(tmp_path, {"kb_mode": "multilingual"})))
    result = await knowledge.run_gate_8(_ctx())
    assert tuple(c.name for c in result.checks) == knowledge.CHECK_NAMES
    # Nothing was supplied, so nothing may be green.
    assert result.status == "not_run"


# --- observations replayed into the probe seams --------------------------------


async def test_recorded_retrieval_outcomes_reach_the_recall_arithmetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        knowledge.INPUTS_ENV,
        str(
            _write(
                tmp_path,
                {
                    "kb_handle": "rag-1",
                    "kb_mode": "multilingual",
                    "min_recall": 0.8,
                    "builtin_retrieval": [
                        {"question_id": f"q{i}", "answered": True, "latency_ms": 120.0}
                        for i in range(9)
                    ]
                    + [{"question_id": "q9", "answered": False}],
                    "external_retrieval": [
                        {"question_id": f"q{i}", "answered": True} for i in range(10)
                    ],
                },
            )
        ),
    )
    result = await knowledge.run_gate_8(_ctx())
    builtin = _check(result, "telugu_builtin_kb_retrieval")
    assert builtin.status == "pass"
    assert builtin.measurements["recall"] == 0.9
    assert _check(result, "telugu_external_kb_fallback").status in ("pass", "fail")


async def test_poor_telugu_retrieval_is_a_first_class_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The answer that decides TRD §6.2's fallback route. It must be decidable, and the
    recorded outcomes are what decide it."""
    monkeypatch.setenv(
        knowledge.INPUTS_ENV,
        str(
            _write(
                tmp_path,
                {
                    "kb_handle": "rag-1",
                    "builtin_retrieval": [
                        {"question_id": f"q{i}", "answered": i < 3} for i in range(10)
                    ],
                    "external_retrieval": [
                        {"question_id": f"q{i}", "answered": True} for i in range(10)
                    ],
                },
            )
        ),
    )
    result = await knowledge.run_gate_8(_ctx())
    assert _check(result, "telugu_builtin_kb_retrieval").status == "fail"


async def test_a_question_with_no_recorded_outcome_blocks_rather_than_scoring_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unasked question and a failed one are opposite facts. Defaulting one to the
    other moves recall in the direction that passes the gate, so the run refuses — and
    it refuses as a BLOCKED gate rather than an exception that kills the other gates."""
    monkeypatch.setenv(
        knowledge.INPUTS_ENV,
        str(
            _write(
                tmp_path,
                {
                    "kb_handle": "rag-1",
                    "question_ids": ["q0", "q1", "q2"],
                    "builtin_retrieval": [{"question_id": "q0", "answered": True}],
                },
            )
        ),
    )
    result = await knowledge.run_gate_8(_ctx())
    assert result.status == "not_run"
    assert "probe misuse" in (result.blocked or "")
    assert "q1" in (result.blocked or "")


async def test_tool_call_latencies_and_batch_outcomes_are_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        knowledge.INPUTS_ENV,
        str(
            _write(
                tmp_path,
                {
                    "tool_call_latencies_ms": [40.0 + i for i in range(25)],
                    "slow_endpoint": [
                        {
                            "injected_delay_ms": 4000,
                            "behaviour": "hung",
                            "gave_up_after_ms": None,
                        }
                    ],
                    "history": [{"turn_index": i, "input_tokens": 100 * (i + 1)} for i in range(6)],
                    "batch_outcomes": [
                        {
                            "contact_id": f"c{i}",
                            "attempts": 1,
                            "terminal_status": "completed",
                        }
                        for i in range(10)
                    ],
                },
            )
        ),
    )
    result = await knowledge.run_gate_8(_ctx())
    budget = _check(result, "custom_function_tool_call_budget")
    assert budget.measurements["samples"] == 25
    assert _check(result, "custom_function_slow_endpoint_behaviour").status == "fail"
    assert _check(result, "batch_campaign_per_contact_status").status == "pass"
    assert _check(result, "h1_history_window_handling").status in ("pass", "fail", "not_run")


# --- the KB-lifecycle probes drive the adapter live ----------------------------


async def test_naming_two_agents_runs_the_kb_lifecycle_probes_against_the_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """These two probes are the only part of gate 8 that is a live measurement, and they
    are DESTRUCTIVE — so they run only when the file names the pilot agents to point them
    at, and they go through the `VoiceEngine` adapter rather than raw HTTP."""
    monkeypatch.setenv(
        knowledge.INPUTS_ENV,
        str(
            _write(
                tmp_path,
                {
                    "primary_agent": {
                        "agent_ref": "fakeagent-primary",
                        "source": {"kb_id": "kb-1", "title": "FAQ", "text": "prashna samadhanam"},
                    },
                    "control_agent": {
                        "agent_ref": "fakeagent-control",
                        "source": {"kb_id": "kb-2", "title": "FAQ 2", "text": "vere samadhanam"},
                    },
                },
            )
        ),
    )
    result = await knowledge.run_gate_8(_ctx(FakeEngine()))
    # `fake` implements the linkage correctly, so the probe can decide it.
    assert _check(result, "kb_list_carries_agent_linkage").status == "pass"


async def test_without_agents_the_kb_probes_never_start_rather_than_starting_and_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The KB probes ATTACH and DELETE knowledge bases on a live engine, so "did not run"
    and "ran and fell over" are very different facts about someone's agent.

    Both land on NOT RUN, which is why the assertion is on the REASON: a probe that
    started without an agent reports an attach failure (`INCONCLUSIVE — attach_kb
    failed`), and a probe that was never reached reports that its inputs were not
    supplied. Asserting only the status cannot tell those apart — verified by sabotage:
    dropping the agent condition in `run_gate8` leaves the status untouched.
    """

    class _Counting:
        def __init__(self) -> None:
            self.calls = 0

        async def attach_kb(self, ref: str, source: Any) -> str:
            self.calls += 1
            return "kb"

        async def detach_kb(self, ref: str, kb: str) -> None:
            self.calls += 1

        async def list_kb(self, ref: str) -> list[str]:
            self.calls += 1
            return []

    engine = _Counting()
    monkeypatch.setenv(knowledge.INPUTS_ENV, str(_write(tmp_path, {})))
    result = await knowledge.run_gate_8(_ctx(engine))
    row = _check(result, "kb_list_carries_agent_linkage")
    assert row.status == "not_run"
    assert "inputs were not supplied" in row.detail
    assert engine.calls == 0


async def test_a_knowledge_source_with_no_text_blocks_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attaching an empty knowledge base would measure retrieval against nothing."""
    monkeypatch.setenv(
        knowledge.INPUTS_ENV,
        str(
            _write(
                tmp_path,
                {
                    "primary_agent": {
                        "agent_ref": "a",
                        "source": {"kb_id": "kb-1", "title": "FAQ"},
                    },
                    "control_agent": {
                        "agent_ref": "b",
                        "source": {"kb_id": "kb-2", "title": "FAQ 2", "text": "x"},
                    },
                },
            )
        ),
    )
    result = await knowledge.run_gate_8(_ctx(FakeEngine()))
    assert result.status == "not_run"
    assert "probe misuse" in (result.blocked or "")


async def test_a_missing_text_file_blocks_the_gate_by_type_not_by_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        knowledge.INPUTS_ENV,
        str(
            _write(
                tmp_path,
                {
                    "primary_agent": {
                        "agent_ref": "a",
                        "source": {
                            "kb_id": "kb-1",
                            "title": "FAQ",
                            "text_path": str(tmp_path / "nope.txt"),
                        },
                    },
                },
            )
        ),
    )
    result = await knowledge.run_gate_8(_ctx(FakeEngine()))
    assert result.status == "not_run"
    assert "could not be read" in (result.blocked or "")


def test_a_knowledge_source_may_keep_its_text_beside_the_file(tmp_path: Path) -> None:
    body = tmp_path / "faq.txt"
    body.write_text("prashna samadhanam", encoding="utf-8")
    source = knowledge.KbSourceInput(kb_id="kb-1", title="FAQ", text_path=str(body))
    assert source.resolve().text == "prashna samadhanam"


def test_question_ids_default_to_the_ones_actually_scored() -> None:
    inputs = knowledge.Gate8Inputs(
        builtin_retrieval=[
            knowledge.RetrievalOutcomeInput(question_id="q1", answered=True),
            knowledge.RetrievalOutcomeInput(question_id="q2", answered=False),
        ],
        external_retrieval=[knowledge.RetrievalOutcomeInput(question_id="q3", answered=True)],
    )
    assert inputs.resolved_question_ids() == ("q1", "q2", "q3")
    explicit = inputs.model_copy(update={"question_ids": ["q1"]})
    assert explicit.resolved_question_ids() == ("q1",)


# --- hard rule 6 ---------------------------------------------------------------


async def test_the_gate_result_carries_no_question_text_and_no_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        knowledge.INPUTS_ENV,
        str(
            _write(
                tmp_path,
                {
                    "kb_handle": "rag-1",
                    "builtin_retrieval": [
                        {"question_id": "q1", "answered": True},
                        {"question_id": "q2", "answered": False},
                    ],
                    "batch_outcomes": [
                        {"contact_id": "c1", "attempts": 1, "terminal_status": "completed"}
                    ],
                },
            )
        ),
    )
    result = await knowledge.run_gate_8(_ctx())
    serialized = repr(result.as_dict())
    assert "9876543210" not in serialized
    assert "q1" not in serialized  # opaque ids are inputs, not output rows
