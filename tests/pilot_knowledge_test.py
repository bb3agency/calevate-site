"""Gate 8's probes, run against engines that behave the way the vendor might.

A probe that has never run is exactly as unverified as the vendor it is aimed at, and
the outcomes worth testing are the NEGATIVE ones: they are the answers that change our
architecture, and they are the ones nobody writes a fixture for. So every engine double
here is a plausible Bolna: one whose KB list carries the agent linkage, one whose list
does not (the silent "no agent has a knowledge base" world), one whose list is not
agent-scoped at all (cross-tenant attribution), one whose delete leaves the agent
pointing at a dead `rag_id`, and one whose detach is a polite no-op.

The doubles implement only `scripts.pilot.knowledge.KbEngine` — three methods — which is
why the probes were narrowed to that Protocol. `FakeEngine` from `apps.api.engine.fake`
is used unmodified as the well-behaved control, so the happy path is proven against the
adapter the conformance suite already governs rather than against a mock of it.
"""

from __future__ import annotations

import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.fake import FakeEngine
from calevate_shared.engine import EngineAgentRef, EngineKBRef, KBSourceRef
from scripts.pilot.knowledge import (
    CHECK_NAMES,
    ContactOutcome,
    HistoryObservation,
    KbModeLedger,
    KbProbeAgent,
    KnowledgeProbeInputs,
    ProbeMisuseError,
    RetrievalOutcome,
    SlowEndpointObservation,
    percentile,
    probe_batch_campaign,
    probe_h1_history_handling,
    probe_kb_agent_linkage,
    probe_kb_delete_clears_agent_reference,
    probe_telugu_retrieval,
    probe_tool_call_budget,
    run_gate8,
)
from scripts.pilot.results import SubCheck

# --- engine doubles -----------------------------------------------------------


class _RecordingEngine:
    """Base double: attach/detach really work, `list_kb` is what each subclass varies."""

    def __init__(self) -> None:
        self.attached: dict[EngineAgentRef, list[EngineKBRef]] = {}
        self._seq = 0

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        self._seq += 1
        handle = f"rag_{self._seq}"
        self.attached.setdefault(ref, []).append(handle)
        return handle

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        for held in self.attached.values():
            if kb in held:
                held.remove(kb)
                return
        raise ProblemError(
            kind="dependency",
            code="engine_rejected",
            title="Voice engine rejected the request",
            detail="The voice platform does not hold that knowledge base.",
        )

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        return list(self.attached.get(ref, []))


class LinkageBlindEngine(_RecordingEngine):
    """`GET /knowledgebase/all` rows do not name the agent (or name it differently), so
    the adapter's strict filter drops every row. The KB is really there — DELETE still
    accepts the handle — which is exactly what makes the empty list a lie."""

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        return []


class UnscopedListEngine(_RecordingEngine):
    """The list is account-wide and our filter is not filtering: every agent's list
    contains every other agent's handles. Cross-tenant, on one shared account."""

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        return [h for held in self.attached.values() for h in held]


class PhantomAttachEngine(_RecordingEngine):
    """Attach returns a handle that addresses nothing: the list is empty AND the delete
    is refused, so the probe must refuse to conclude anything about the list."""

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        self._seq += 1
        return f"rag_ghost_{self._seq}"

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        return []


class NoOpDetachEngine(_RecordingEngine):
    """Detach returns 2xx and removes nothing — D-41's silent lie, in code."""

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        return None


def _agent(ref: str, kb_id: str) -> KbProbeAgent:
    return KbProbeAgent(
        ref=ref,
        source=KBSourceRef(kb_id=kb_id, title=f"faq-{kb_id}", text="pilot fixture text"),
    )


def _check(checks: tuple[SubCheck, ...], name: str) -> SubCheck:
    match = [c for c in checks if c.name == name]
    assert match, f"{name} missing from {[c.name for c in checks]}"
    return match[0]


# --- D-41 (a): does the list carry the agent linkage? -------------------------


async def test_linkage_present_passes_against_the_fake_adapter() -> None:
    engine = FakeEngine()
    out = await probe_kb_agent_linkage(engine, _agent("agent_a", "kb1"), _agent("agent_b", "kb2"))
    check = _check(out.checks, "kb_list_carries_agent_linkage")
    assert check.status == "pass"
    assert check.measurements["rows_attributed_to_primary"] == 1


async def test_linkage_absent_fails_and_names_the_silent_wrong_answer() -> None:
    """The outcome the gate exists for: an empty list that is not an empty KB."""
    out = await probe_kb_agent_linkage(
        LinkageBlindEngine(), _agent("agent_a", "kb1"), _agent("agent_b", "kb2")
    )
    check = _check(out.checks, "kb_list_carries_agent_linkage")
    assert check.status == "fail"
    assert check.measurements["delete_accepted_handle"] == 1
    assert "EVERY agent as holding no knowledge base" in check.detail


async def test_unscoped_list_fails_as_cross_tenant_attribution() -> None:
    out = await probe_kb_agent_linkage(
        UnscopedListEngine(), _agent("agent_a", "kb1"), _agent("agent_b", "kb2")
    )
    check = _check(out.checks, "kb_list_carries_agent_linkage")
    assert check.status == "fail"
    assert "cross-tenant" in check.detail


async def test_phantom_attach_is_inconclusive_not_a_verdict() -> None:
    out = await probe_kb_agent_linkage(
        PhantomAttachEngine(), _agent("agent_a", "kb1"), _agent("agent_b", "kb2")
    )
    check = _check(out.checks, "kb_list_carries_agent_linkage")
    assert check.status == "not_run"
    assert check.detail.startswith("INCONCLUSIVE")


async def test_linkage_probe_always_reports_the_raw_capture_gap() -> None:
    out = await probe_kb_agent_linkage(FakeEngine(), _agent("a", "kb1"), _agent("b", "kb2"))
    assert any("raw-response capture hook" in f for f in out.findings)


# --- D-41 (b): does delete clear the agent's reference? -----------------------


async def test_delete_reference_is_inconclusive_without_an_instrument() -> None:
    """Our Protocol has no agent read-back, and the probe must say so rather than guess."""
    out = await probe_kb_delete_clears_agent_reference(FakeEngine(), _agent("a", "kb1"))
    check = _check(out.checks, "kb_delete_clears_agent_reference")
    assert check.status == "not_run"
    assert check.detail.startswith("INCONCLUSIVE")
    assert any("NO agent read-back" in f for f in out.findings)


async def test_dangling_rag_id_fails_and_says_detach_grows_a_second_call() -> None:
    """The answer that adds work to our code: the KB is gone, the agent still points at
    it, so `detach_kb` is a delete PLUS an agent update — and does not become optional.

    `_RecordingEngine` mints predictable handles (`rag_1`, ...) precisely so the reader
    double can name the one the agent was left holding without reaching into the
    engine's internals.
    """
    engine = _RecordingEngine()

    async def dangling_reader(ref: EngineAgentRef) -> list[str]:
        return ["rag_1"]

    out = await probe_kb_delete_clears_agent_reference(
        engine, _agent("agent_a", "kb1"), agent_ref_reader=dangling_reader
    )
    check = _check(out.checks, "kb_delete_clears_agent_reference")
    assert check.status == "fail"
    assert "SECOND call" in check.detail


async def test_cleared_reference_passes() -> None:
    async def reader(ref: EngineAgentRef) -> list[str]:
        return []

    out = await probe_kb_delete_clears_agent_reference(
        FakeEngine(), _agent("agent_a", "kb1"), agent_ref_reader=reader
    )
    assert _check(out.checks, "kb_delete_clears_agent_reference").status == "pass"


async def test_behavioural_probe_fails_when_the_withdrawn_source_still_answers() -> None:
    async def still_answered(ref: EngineAgentRef, question_id: str) -> bool:
        return True

    out = await probe_kb_delete_clears_agent_reference(
        FakeEngine(),
        _agent("agent_a", "kb1"),
        still_answered=still_answered,
        withdrawn_question_id="q7",
    )
    check = _check(out.checks, "kb_delete_clears_agent_reference")
    assert check.status == "fail"
    assert "WITHDRAWN" in check.detail


async def test_noop_detach_is_caught_before_the_reference_question() -> None:
    """A detach that removes nothing is a bigger finding than the one we asked for."""
    out = await probe_kb_delete_clears_agent_reference(NoOpDetachEngine(), _agent("a", "kb1"))
    check = _check(out.checks, "kb_delete_clears_agent_reference")
    assert check.status == "fail"
    assert "silent lie" in check.detail


# --- Telugu retrieval and the one-way door ------------------------------------


def _scorer(answered_ids: set[str], latency_ms: float = 40.0):
    async def score(question_id: str) -> RetrievalOutcome:
        return RetrievalOutcome(
            question_id=question_id,
            answered=question_id in answered_ids,
            latency_ms=latency_ms,
        )

    return score


QUESTIONS = tuple(f"q{i}" for i in range(10))


async def test_poor_telugu_builtin_with_working_fallback_names_the_consequence() -> None:
    out = await probe_telugu_retrieval(
        kb_handle="rag_1",
        kb_mode="multilingual",
        question_ids=QUESTIONS,
        builtin=_scorer({"q0", "q1", "q2"}),
        external=_scorer(set(QUESTIONS)),
        ledger=KbModeLedger(),
    )
    builtin = _check(out.checks, "telugu_builtin_kb_retrieval")
    external = _check(out.checks, "telugu_external_kb_fallback")
    assert builtin.status == "fail"
    assert builtin.measurements["recall"] == 0.3
    assert external.status == "pass"
    assert any("in-call KB choice inverts" in f for f in out.findings)


async def test_both_routes_failing_reopens_the_provider_question() -> None:
    out = await probe_telugu_retrieval(
        kb_handle="rag_1",
        kb_mode="multilingual",
        question_ids=QUESTIONS,
        builtin=_scorer({"q0"}),
        external=_scorer({"q0", "q1"}),
        ledger=KbModeLedger(),
    )
    assert _check(out.checks, "telugu_builtin_kb_retrieval").status == "fail"
    external = _check(out.checks, "telugu_external_kb_fallback")
    assert external.status == "fail"
    assert "bake-off" in external.detail


async def test_missing_fallback_measurement_is_not_run_and_flags_the_one_way_door() -> None:
    out = await probe_telugu_retrieval(
        kb_handle="rag_1",
        kb_mode="multilingual",
        question_ids=QUESTIONS,
        builtin=_scorer({"q0"}),
        external=None,
        ledger=KbModeLedger(),
    )
    fallback = _check(out.checks, "telugu_external_kb_fallback")
    assert fallback.status == "not_run"
    assert "immutable" in fallback.detail
    assert any("one-way door" in f for f in out.findings)


async def test_good_builtin_recall_passes_but_the_fallback_row_still_stands_alone() -> None:
    out = await probe_telugu_retrieval(
        kb_handle="rag_1",
        kb_mode="multilingual",
        question_ids=QUESTIONS,
        builtin=_scorer(set(QUESTIONS)),
        external=None,
        ledger=KbModeLedger(),
    )
    assert _check(out.checks, "telugu_builtin_kb_retrieval").status == "pass"
    # A good built-in result must NOT be able to close the gate on its own.
    assert _check(out.checks, "telugu_external_kb_fallback").status == "not_run"


async def test_the_mode_ledger_refuses_a_second_mode_on_the_same_kb() -> None:
    ledger = KbModeLedger()
    await probe_telugu_retrieval(
        kb_handle="rag_1",
        kb_mode="multilingual",
        question_ids=QUESTIONS,
        builtin=_scorer(set(QUESTIONS)),
        external=None,
        ledger=ledger,
    )
    with pytest.raises(ProbeMisuseError, match="IMMUTABLE"):
        await probe_telugu_retrieval(
            kb_handle="rag_1",
            kb_mode="english",
            question_ids=QUESTIONS,
            builtin=_scorer(set(QUESTIONS)),
            external=None,
            ledger=ledger,
        )


def test_retrieval_outcome_carries_no_text_field() -> None:
    """Hard rule 6, structurally: `KbRetrievalLog.query` is a dated deferral for exactly
    this reason, and this probe must not become its accidental producer."""
    assert set(RetrievalOutcome.__dataclass_fields__) == {
        "question_id",
        "answered",
        "latency_ms",
    }


# --- tool-call budget ----------------------------------------------------------


def test_percentile_is_nearest_rank_and_never_interpolates() -> None:
    sample = [10.0, 20.0, 30.0, 40.0]
    assert percentile(sample, 0.95) == 40.0
    assert percentile(sample, 0.5) == 20.0
    with pytest.raises(ProbeMisuseError):
        percentile([], 0.95)


def test_tool_budget_not_run_below_the_sample_floor() -> None:
    out = probe_tool_call_budget(latencies_ms=[10.0] * 5, slow_endpoint=None)
    check = _check(out.checks, "custom_function_tool_call_budget")
    assert check.status == "not_run"
    assert check.measurements["samples"] == 5


def test_tool_budget_fails_when_p95_exceeds_the_hundred_ms_budget() -> None:
    latencies = [50.0] * 18 + [450.0, 500.0]
    out = probe_tool_call_budget(latencies_ms=latencies, slow_endpoint=None)
    check = _check(out.checks, "custom_function_tool_call_budget")
    assert check.status == "fail"
    assert check.measurements["tool_call_p95_ms"] == 450.0


def test_a_single_outlier_in_twenty_is_not_the_p95() -> None:
    """Nearest-rank, stated as a test so nobody 'fixes' it into interpolation: with 20
    samples the p95 is the 19th, so one slow call does not move it — and one slow call
    is not a latency problem, it is a sample."""
    out = probe_tool_call_budget(latencies_ms=[50.0] * 19 + [450.0], slow_endpoint=None)
    check = _check(out.checks, "custom_function_tool_call_budget")
    assert check.status == "pass"
    assert check.measurements["tool_call_p95_ms"] == 50.0


def test_hanging_endpoint_fails_and_rules_out_synchronous_provider_calls() -> None:
    out = probe_tool_call_budget(
        latencies_ms=None,
        slow_endpoint=[SlowEndpointObservation(injected_delay_ms=5000, behaviour="hung")],
    )
    check = _check(out.checks, "custom_function_slow_endpoint_behaviour")
    assert check.status == "fail"
    assert "dead air" in check.detail
    assert "observed_timeout_ceiling_ms" not in check.measurements


def test_an_observed_ceiling_is_recorded_as_a_dated_assumption() -> None:
    out = probe_tool_call_budget(
        latencies_ms=None,
        slow_endpoint=[
            SlowEndpointObservation(
                injected_delay_ms=9000, behaviour="apologised", gave_up_after_ms=4000
            )
        ],
    )
    check = _check(out.checks, "custom_function_slow_endpoint_behaviour")
    assert check.status == "pass"
    assert check.measurements["observed_timeout_ceiling_ms"] == 4000
    assert any("documents none" in f for f in out.findings)


def test_no_ceiling_found_is_inconclusive_not_absent() -> None:
    out = probe_tool_call_budget(
        latencies_ms=None,
        slow_endpoint=[SlowEndpointObservation(injected_delay_ms=3000, behaviour="answered")],
    )
    check = _check(out.checks, "custom_function_slow_endpoint_behaviour")
    assert check.status == "not_run"
    assert check.detail.startswith("INCONCLUSIVE")


# --- H1 working memory ---------------------------------------------------------


def test_rising_input_tokens_confirm_the_full_resend_cost_model() -> None:
    out = probe_h1_history_handling(
        [HistoryObservation(turn_index=i, input_tokens=100 * (i + 1)) for i in range(6)]
    )
    check = _check(out.checks, "h1_history_window_handling")
    assert check.status == "pass"
    assert "does not truncate" in check.detail


def test_a_plateau_reports_truncation_or_summarisation_without_choosing() -> None:
    counts = [100, 200, 300, 300, 300, 300]
    out = probe_h1_history_handling(
        [HistoryObservation(turn_index=i, input_tokens=c) for i, c in enumerate(counts)]
    )
    check = _check(out.checks, "h1_history_window_handling")
    assert check.status == "pass"
    assert "truncates OR summarises" in check.detail
    assert any("minute 1 is still honoured in minute 10" in f for f in out.findings)


def test_unreported_caching_is_absent_never_zero() -> None:
    out = probe_h1_history_handling(
        [HistoryObservation(turn_index=i, input_tokens=100 * (i + 1)) for i in range(4)]
    )
    check = _check(out.checks, "h1_provider_context_caching")
    assert check.status == "not_run"
    assert "ABSENT, not zero" in check.detail


def test_reported_zero_caching_is_a_measurement_and_fails() -> None:
    out = probe_h1_history_handling(
        [
            HistoryObservation(turn_index=i, input_tokens=100 * (i + 1), cached_input_tokens=0)
            for i in range(4)
        ]
    )
    check = _check(out.checks, "h1_provider_context_caching")
    assert check.status == "fail"
    assert check.measurements["turns_with_cached_tokens"] == 0


def test_two_turns_cannot_decide_a_growth_shape() -> None:
    out = probe_h1_history_handling(
        [HistoryObservation(turn_index=i, input_tokens=100) for i in range(2)]
    )
    assert _check(out.checks, "h1_history_window_handling").detail.startswith("INCONCLUSIVE")


# --- batch campaign ------------------------------------------------------------


def _contacts(n: int = 10, **overrides: object) -> list[ContactOutcome]:
    return [
        ContactOutcome(contact_id=f"c{i}", attempts=1, terminal_status="completed")
        for i in range(n)
    ]


def test_batch_not_run_says_the_unwired_column_stays_open() -> None:
    out = probe_batch_campaign(None)
    check = _check(out.checks, "batch_campaign_retry_policy")
    assert check.status == "not_run"
    assert "UNWIRED_BASELINE" in check.detail
    assert any("no batch method" in f for f in out.findings)


def test_batch_within_the_documented_policy_passes() -> None:
    outcomes = [
        *_contacts(9),
        ContactOutcome(
            contact_id="c9", attempts=3, terminal_status="completed", retried_after=("busy", "busy")
        ),
    ]
    out = probe_batch_campaign(outcomes)
    assert _check(out.checks, "batch_campaign_retry_policy").status == "pass"
    assert _check(out.checks, "batch_campaign_per_contact_status").status == "pass"


def test_too_many_attempts_drops_the_engine_campaign_column() -> None:
    outcomes = [
        *_contacts(9),
        ContactOutcome(contact_id="c9", attempts=5, terminal_status="completed"),
    ]
    out = probe_batch_campaign(outcomes)
    check = _check(out.checks, "batch_campaign_retry_policy")
    assert check.status == "fail"
    assert "two-step" in check.detail
    assert any("DNC additions" in f for f in out.findings)


def test_retry_on_an_undocumented_outcome_fails() -> None:
    outcomes = [
        *_contacts(9),
        ContactOutcome(
            contact_id="c9", attempts=2, terminal_status="completed", retried_after=("answered",)
        ),
    ]
    out = probe_batch_campaign(outcomes)
    check = _check(out.checks, "batch_campaign_retry_policy")
    assert check.status == "fail"
    assert "answered" in check.detail


def test_a_contact_without_a_terminal_status_fails() -> None:
    outcomes = [
        *_contacts(9),
        ContactOutcome(contact_id="c9", attempts=1, terminal_status=None),
    ]
    out = probe_batch_campaign(outcomes)
    check = _check(out.checks, "batch_campaign_per_contact_status")
    assert check.status == "fail"
    assert check.measurements["contacts_without_terminal_status"] == 1


# --- the gate as a whole -------------------------------------------------------


async def test_an_empty_run_reports_every_probe_as_not_run() -> None:
    """The property the scorecard depends on: NOT RUN cannot hide by being absent."""
    gate = await run_gate8(KnowledgeProbeInputs())
    assert tuple(c.name for c in gate.checks) == CHECK_NAMES
    assert all(c.status == "not_run" for c in gate.checks)
    assert all(c.detail.strip() for c in gate.checks)
    assert gate.status == "not_run"


async def test_one_unrun_probe_keeps_the_whole_gate_off_green() -> None:
    gate = await run_gate8(
        KnowledgeProbeInputs(
            engine=FakeEngine(),
            primary_agent=_agent("agent_a", "kb1"),
            control_agent=_agent("agent_b", "kb2"),
            batch_outcomes=tuple(_contacts()),
        )
    )
    assert _check(gate.checks, "kb_list_carries_agent_linkage").status == "pass"
    assert _check(gate.checks, "batch_campaign_retry_policy").status == "pass"
    assert gate.status == "not_run"  # live-call probes were never executed


async def test_a_failing_probe_makes_the_gate_red_and_keeps_the_findings() -> None:
    gate = await run_gate8(
        KnowledgeProbeInputs(
            engine=LinkageBlindEngine(),
            primary_agent=_agent("agent_a", "kb1"),
            control_agent=_agent("agent_b", "kb2"),
        )
    )
    assert gate.status == "fail"
    assert gate.findings
    payload = gate.as_dict()
    assert payload["label"] == "FAIL"


def test_gate_reports_no_free_text_beyond_ids_and_counts() -> None:
    """Hard rule 6 at the boundary this slice owns: measurements are numbers and short
    labels, so nothing text-shaped can reach the committed evidence artefact."""
    out = probe_batch_campaign(tuple(_contacts()))
    for check in out.checks:
        for key, value in check.measurements.items():
            assert not isinstance(value, str) or len(value) <= 40, key
