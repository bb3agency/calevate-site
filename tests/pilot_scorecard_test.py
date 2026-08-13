"""The pilot scorecard's result contract, its renderer, and the fixture recorder.

These tests are the reason the scorecard is evidence rather than a form. Each one names
the way of lying it closes; several of them were verified by BREAKING the rule and
watching the test go red, because a redaction test whose fixture contains no PII proves
nothing.

Everything here runs against the `fake` adapter and pure functions — there is no Bolna
account in this environment, and there must not need to be one for the machinery that
will handle a real payload to be trusted before it sees one.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.engine.bolna import BolnaEngine
from pydantic import ValidationError
from scripts.pilot.record import (
    UnredactedPayloadError,
    load_fixture,
    record_fixture,
    residual_pii,
    scrub_payload,
)
from scripts.pilot.scorecard import (
    GATES,
    ArtifactRef,
    Attestation,
    CostLine,
    EvidenceKind,
    EvidenceLeakError,
    GateResult,
    Measurement,
    Scorecard,
    SourceKind,
    Verdict,
    derive_overall,
    from_runner_result,
    render,
)

OBSERVED = datetime(2026, 8, 20, 11, 30, tzinfo=UTC)
SHA = "a" * 64

# Planted PII. Every value below is fictional, and every test that plants one asserts the
# literal string never reaches the artifact — the assertion is worthless without them.
PLANTED_CALLER = "+919876543210"
PLANTED_CALLEE = "+919812345678"
PLANTED_BARE = "919833344455"  # no plus: the form `redact()`'s own regex cannot anchor
PLANTED_INT = 919844455566
PLANTED_EMAIL = "ravi.kumar@example.com"
# A number read aloud in Telugu — the form no field-name scrubber can see, and the one an
# Indian caller actually produces. Ten digit words, above `spoken_digit_runs`' threshold.
PLANTED_LINE = (
    "Naa peru Ravi Kumar, naa number tommidi enimidi mooDu rendu okati aidu aaru edu rendu moodu"
)
PLANTED_RECORDING = (
    "https://s3.us-east-1.amazonaws.com/bolna/exec_abc123.wav"
    "?X-Amz-Credential=AKIAEXAMPLE&X-Amz-Signature=deadbeef"
)


def _passing(gate: int) -> GateResult:
    """A PASS for any gate, carrying whatever that gate's kind requires."""
    spec = GATES[gate]
    attestation = None
    if spec.evidence is not EvidenceKind.AUTOMATED:
        attestation = Attestation(
            statement="Confirmed in writing.",
            source_kind=SourceKind.EMAIL,
            source_ref="docs/evidence/bolna-commercials.md",
            dated=date(2026, 8, 19),
            attested_by="ops",
        )
    return GateResult(
        gate=gate,
        verdict=Verdict.PASS,
        observed_at=OBSERVED,
        operator="ops",
        attestation=attestation,
    )


def _scorecard(**overrides: Verdict) -> Scorecard:
    """A full scorecard, all gates passing except the ones named `g<N>=Verdict...`."""
    results = []
    for gate in sorted(GATES):
        verdict = overrides.get(f"g{gate}", Verdict.PASS)
        if verdict is Verdict.PASS:
            results.append(_passing(gate))
        elif verdict is Verdict.NOT_RUN:
            results.append(GateResult(gate=gate))
        else:
            results.append(
                GateResult(gate=gate, verdict=verdict, observed_at=OBSERVED, operator="ops")
            )
    return Scorecard(run_by="ops", results=tuple(results))


# --- 1. the verdict is derived, never typed -----------------------------------


def test_a_not_run_scorecard_is_not_a_pass() -> None:
    assert Scorecard.not_yet_run().overall is Verdict.NOT_RUN


def test_every_hard_gate_passing_is_the_only_way_to_pass() -> None:
    assert _scorecard().overall is Verdict.PASS


def test_one_red_hard_gate_makes_the_whole_scorecard_fail() -> None:
    card = _scorecard(g4=Verdict.FAIL)
    assert card.overall is Verdict.FAIL
    assert "THE ENGINE DECISION REOPENS" in render(card)
    assert "NO fallback engine" in render(card)


def test_a_red_hard_gate_beats_unrun_ones_rather_than_being_softened_by_them() -> None:
    """FAIL is loudest: the consequence has already been triggered, and "we also did not
    finish" must not read as a milder outcome than "we finished and it failed"."""
    assert _scorecard(g4=Verdict.FAIL, g6=Verdict.NOT_RUN).overall is Verdict.FAIL


def test_an_inconclusive_hard_gate_is_not_a_pass() -> None:
    assert _scorecard(g11=Verdict.INCONCLUSIVE).overall is Verdict.INCONCLUSIVE


def test_an_unrun_hard_gate_is_not_a_pass() -> None:
    assert _scorecard(g9=Verdict.NOT_RUN).overall is Verdict.NOT_RUN


def test_a_failing_soft_gate_does_not_reopen_the_engine_decision() -> None:
    """OPERATIONS §2: a soft gate shapes M1 scope, not the engine choice. If this ever
    flips to FAIL, the document stops being able to say the one thing it exists to say."""
    card = _scorecard(g8=Verdict.FAIL)
    assert card.overall is Verdict.PASS
    assert "**FAIL**" in render(card)  # still visible, just not decisive


def test_nobody_can_tick_pass_at_the_top() -> None:
    """The headline is a property, so the only route in would be a stray key in a results
    file. `extra="forbid"` closes it, loudly."""
    payload = _scorecard().model_dump(mode="json")
    payload["overall"] = "PASS"
    with pytest.raises(ValidationError, match="overall"):
        Scorecard.model_validate(payload)


def test_a_scorecard_must_report_every_gate_exactly_once() -> None:
    with pytest.raises(ValidationError, match="missing"):
        Scorecard(results=tuple(_passing(g) for g in sorted(GATES)[:-1]))
    with pytest.raises(ValidationError, match="duplicated"):
        Scorecard(results=(*[_passing(g) for g in sorted(GATES)], _passing(1)))


def test_derive_overall_refuses_a_set_with_no_hard_gates() -> None:
    with pytest.raises(ValueError, match="not a pilot scorecard"):
        derive_overall([GateResult(gate=7), GateResult(gate=8)])


# --- 2. "not run" cannot be dressed up ----------------------------------------


def test_an_unrun_gate_may_not_carry_evidence() -> None:
    """The defect in the template this replaces: a half-filled row that reads as work."""
    with pytest.raises(ValidationError, match="NOT RUN but carries"):
        GateResult(
            gate=4,
            measurements=(
                Measurement(name="p50", value=Decimal("1.05"), unit="s", method="stopwatch"),
            ),
        )
    with pytest.raises(ValidationError, match="NOT RUN but carries"):
        GateResult(gate=4, operator="ops")


def test_a_verdict_without_a_date_and_a_name_is_not_evidence() -> None:
    with pytest.raises(ValidationError, match="without observed_at"):
        GateResult(gate=4, verdict=Verdict.PASS)
    with pytest.raises(ValidationError, match="without observed_at"):
        GateResult(gate=4, verdict=Verdict.FAIL, observed_at=OBSERVED)


def test_observed_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        GateResult(
            gate=4, verdict=Verdict.PASS, observed_at=datetime(2026, 8, 20, 11, 30), operator="ops"
        )


def test_the_rendered_document_distinguishes_unrun_from_passed() -> None:
    document = render(Scorecard.not_yet_run(run_by="nobody yet"))
    assert "## VERDICT: NOT RUN" in document
    assert "has not been attempted" in document
    assert "**PASS**" not in document
    # A reader scanning the table must see it on every row, not only in the header.
    assert document.count("_NOT RUN_") >= len(GATES)


# --- 3. the human-only gates ---------------------------------------------------


@pytest.mark.parametrize("gate", [3, 5, 9, 10, 11, 12])
def test_a_human_gate_cannot_pass_without_an_attestation(gate: int) -> None:
    with pytest.raises(ValidationError, match="needs an Attestation"):
        GateResult(gate=gate, verdict=Verdict.PASS, observed_at=OBSERVED, operator="ops")


@pytest.mark.parametrize("gate", [9, 10, 11, 12])
def test_a_verbal_assurance_cannot_be_recorded_as_a_pass(gate: int) -> None:
    """Gate 12 decides our unit economics and gate 11 is the gate the previous vendor
    failed. "They said yes on the call" is representable — as INCONCLUSIVE."""
    verbal = Attestation(
        statement="They said the platform fee would be fine.",
        source_kind=SourceKind.VERBAL,
        source_ref="call with sales, no written follow-up",
        dated=date(2026, 8, 19),
        attested_by="ops",
    )
    with pytest.raises(ValidationError, match="cannot PASS on a verbal"):
        GateResult(
            gate=gate,
            verdict=Verdict.PASS,
            observed_at=OBSERVED,
            operator="ops",
            attestation=verbal,
        )
    inconclusive = GateResult(
        gate=gate,
        verdict=Verdict.INCONCLUSIVE,
        observed_at=OBSERVED,
        operator="ops",
        attestation=verbal,
    )
    assert inconclusive.verdict is Verdict.INCONCLUSIVE


def test_an_attestation_must_name_its_source() -> None:
    with pytest.raises(ValidationError):
        Attestation(
            statement="Residency confirmed.",
            source_kind=SourceKind.EMAIL,
            source_ref="",
            dated=date(2026, 8, 19),
            attested_by="ops",
        )


def test_the_human_gates_get_their_own_section_with_who_and_when() -> None:
    document = render(_scorecard())
    section = document.split("## The gates no program can answer")[1]
    for gate in (3, 5, 9, 10, 11, 12):
        assert f"| {gate} |" in section
    assert "2026-08-19" in section
    assert "_no source on file_" not in section


def test_an_unattested_human_gate_says_so_in_that_section() -> None:
    document = render(Scorecard.not_yet_run())
    section = document.split("## The gates no program can answer")[1]
    assert section.count("_no source on file_") == 6


# --- 4. never invent a measurement --------------------------------------------


def test_a_measurement_must_say_how_it_was_measured() -> None:
    with pytest.raises(ValidationError):
        Measurement(name="p95", value=Decimal("1.7"), unit="s")  # type: ignore[call-arg]


def test_money_is_never_a_float() -> None:
    with pytest.raises(ValidationError, match="never float"):
        Measurement(name="fee", value=1.5, unit="INR/min", method="written quote")
    ok = Measurement(name="fee", value=Decimal("1.5"), unit="INR/min", method="written quote")
    assert ok.value == Decimal("1.5")


def test_an_unmeasured_cost_renders_as_absent_and_never_as_zero() -> None:
    document = render(Scorecard.not_yet_run())
    cost_section = document.split("## Measured cost model")[1]
    assert "_not measured_" in cost_section
    assert "| 0 |" not in cost_section and "**0.00**" not in cost_section


def test_a_measured_cost_must_name_its_source() -> None:
    with pytest.raises(ValidationError, match="must name its source"):
        CostLine(leg="Platform fee", estimate="target <= 1.5", measured_inr_per_min=Decimal("1.20"))
    priced = CostLine(
        leg="Platform fee",
        estimate="target <= 1.5",
        measured_inr_per_min=Decimal("1.20"),
        source="written quote, 19 Aug 2026",
    )
    assert "**1.20**" in render(
        Scorecard(results=tuple(_passing(g) for g in sorted(GATES)), cost_model=(priced,))
    )


# --- 5. redaction of the artifact itself ---------------------------------------


@pytest.mark.parametrize(
    "leak",
    [
        PLANTED_CALLER,
        PLANTED_BARE,
        PLANTED_EMAIL,
        PLANTED_LINE,
        # Verhoeff-valid, so `redact()`'s validator actually fires. An invalid 12-digit
        # run is deliberately NOT redacted (it would eat every appointment reference in
        # every Telugu transcript), so planting one would have proved nothing.
        "Aadhaar 2345 6789 0124 was quoted on the call",
    ],
)
def test_evidence_prose_carrying_pii_is_refused_at_construction(leak: str) -> None:
    with pytest.raises(EvidenceLeakError) as exc:
        GateResult(gate=4, verdict=Verdict.PASS, observed_at=OBSERVED, operator="ops", summary=leak)
    # The refusal must not itself print the value: this message lands in a CI log, which
    # is why EvidenceLeakError deliberately escapes pydantic instead of becoming a
    # ValidationError (whose message would quote `input_value`).
    assert leak not in str(exc.value)


def test_a_recording_link_cannot_be_pasted_into_a_note() -> None:
    with pytest.raises(EvidenceLeakError, match="may not contain a URL"):
        GateResult(
            gate=4,
            verdict=Verdict.PASS,
            observed_at=OBSERVED,
            operator="ops",
            summary=f"listen here {PLANTED_RECORDING}",
        )


def test_an_artifact_path_may_not_escape_the_tree_or_be_a_link() -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(path="../../etc/passwd", sha256=SHA, describes="nope")
    with pytest.raises(EvidenceLeakError):
        ArtifactRef(path=PLANTED_RECORDING, sha256=SHA, describes="nope")


def test_the_whole_document_is_scanned_before_it_is_written() -> None:
    """Field validation covers the fields we thought of; this covers the ones we did not.

    The operator's own name is the cheapest way to prove the scan is on the DOCUMENT:
    `run_by` is validated, so the leak is injected past validation, exactly as a future
    unvalidated section would.
    """
    card = Scorecard.not_yet_run()
    leaky = card.model_copy(update={"engine": f"Bolna, contact {PLANTED_CALLER}"})
    with pytest.raises(EvidenceLeakError) as exc:
        render(leaky)
    assert PLANTED_CALLER not in str(exc.value)


# --- 6. determinism, and the committed document --------------------------------


def test_rendering_is_deterministic() -> None:
    card = _scorecard(g8=Verdict.FAIL, g13=Verdict.INCONCLUSIVE)
    assert render(card) == render(card)
    assert render(card) == render(Scorecard.model_validate(card.model_dump(mode="json")))


def test_the_committed_scorecard_matches_what_the_renderer_produces() -> None:
    """The committed artifact is generated, not written. If this fails, somebody
    hand-edited `docs/evidence/bolna-pilot-scorecard.md` — regenerate it instead, or the
    document and the results it claims to report have already diverged."""
    committed = Path(__file__).resolve().parents[1] / "docs/evidence/bolna-pilot-scorecard.md"
    assert committed.read_text(encoding="utf-8") == render(Scorecard.not_yet_run())


def test_a_results_file_round_trips() -> None:
    card = _scorecard(g11=Verdict.INCONCLUSIVE)
    assert Scorecard.model_validate(json.loads(card.model_dump_json())).overall is card.overall


# --- 7. the recorder: redaction is part of capture -----------------------------


def _realistic_payload() -> dict[str, Any]:
    """A Get Execution payload as Bolna documents it, with PII planted in five shapes —
    including two the field-name scrubber is deliberately not told about."""
    return {
        "id": "exec_abc123",
        "agent_id": "agent_xyz",
        "status": "completed",
        "direction": "inbound",
        "created_at": "2026-08-10T09:15:00Z",
        "ended_at": "2026-08-10T09:16:35Z",
        "conversation_duration": 95,
        "total_cost": 8.5,
        "cost_breakdown": {"platform": 5.0, "network": 1.5, "synthesizer": 1.4},
        "telephony_data": {
            "from_number": PLANTED_CALLER,
            "to_number": PLANTED_CALLEE,
            "recording_url": PLANTED_RECORDING,
        },
        "transcript": (
            "assistant: Namaskaram, idi Sunrise Clinic AI assistant.\n"
            f"user: {PLANTED_LINE}\n"
            f"assistant: Sare, {PLANTED_EMAIL} ki pamputhanu."
        ),
        "extracted_data": {"caller_name": "Ravi Kumar", "callback": PLANTED_CALLER},
        "latency_data": {
            "time_to_first_audio": 820,
            "transcriber": {"turns": [{"text": PLANTED_LINE, "ms": 210}]},
        },
        # The two the scrubber is not told about by key, on purpose.
        "metadata": {"crm_ref": f"lead for {PLANTED_BARE}", "alt_contact": PLANTED_INT},
    }


def test_capture_removes_every_planted_value(tmp_path: Path) -> None:
    record_fixture(
        _realistic_payload(),
        gate=4,
        name="execution_completed",
        source="GET /executions/{id}",
        captured_by="ops",
        captured_at=OBSERVED,
        fixtures_dir=tmp_path,
    )
    written = (tmp_path / "execution_completed.json").read_text(encoding="utf-8")
    for planted in (
        PLANTED_CALLER,
        PLANTED_CALLEE,
        PLANTED_BARE,
        str(PLANTED_INT),
        PLANTED_EMAIL,
        "Ravi Kumar",
        "X-Amz-Signature",
        "s3.us-east-1.amazonaws.com",
    ):
        assert planted not in written, f"{planted!r} survived capture"
    # ...and the fixture is still a fixture: the shape survived.
    body = json.loads(written)
    assert body["telephony_data"]["from_number"].startswith("+91")
    assert body["telephony_data"]["from_number"] != body["telephony_data"]["to_number"]
    assert set(body["extracted_data"]) == {"caller_name", "callback"}
    assert body["transcript"].count("\n") == 2
    assert body["latency_data"]["time_to_first_audio"] == 820


def test_the_manifest_records_what_was_removed(tmp_path: Path) -> None:
    record_fixture(
        _realistic_payload(),
        gate=4,
        name="execution_completed",
        source="GET /executions/{id}",
        captured_by="ops",
        captured_at=OBSERVED,
        fixtures_dir=tmp_path,
    )
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    entry = manifest["fixtures"]["execution_completed"]
    assert entry["gate"] == 4 and entry["captured_by"] == "ops"
    assert entry["captured_at"] == OBSERVED.isoformat()
    assert {"phone", "email"} <= set(entry["redactions"])
    assert len(entry["sha256"]) == 64


def test_the_spoken_telugu_number_is_caught_too() -> None:
    """A caller reading a number aloud is the case a field-name scrubber cannot see, and
    the case an Indian voice product meets every day."""
    scrubbed = scrub_payload({"notes": PLANTED_LINE})
    assert "tommidi enimidi" not in scrubbed["notes"]


def test_capture_is_fail_closed_when_the_scrub_misses(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The property that makes the recorder trustworthy: it verifies its own work.

    Simulated by neutering the scrubber, which is the honest stand-in for the real case
    (a vendor field nobody has seen). Nothing may be written, and the manifest must not
    gain an entry for a file that does not exist.
    """
    monkeypatch.setattr("scripts.pilot.record.scrub_payload", lambda payload: payload)
    with pytest.raises(UnredactedPayloadError) as exc:
        record_fixture(
            _realistic_payload(),
            gate=4,
            name="leaky",
            source="GET /executions/{id}",
            captured_by="ops",
            fixtures_dir=tmp_path,
        )
    assert "telephony_data" in str(exc.value)
    assert PLANTED_CALLER not in str(exc.value), "the refusal must not print the value"
    assert list(tmp_path.iterdir()) == []


def test_residual_pii_reports_paths_not_values() -> None:
    findings = residual_pii(_realistic_payload())
    assert "$.telephony_data.from_number" in findings
    assert "$.metadata.alt_contact" in findings
    assert all(PLANTED_CALLER not in path for path in findings)


def test_a_fixture_name_that_would_escape_the_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="snake_case"):
        record_fixture(
            {"id": "x"},
            gate=1,
            name="../../../etc/passwd",
            source="GET /executions/{id}",
            captured_by="ops",
            fixtures_dir=tmp_path,
        )


def test_capture_is_deterministic(tmp_path: Path) -> None:
    args: dict[str, Any] = {
        "gate": 4,
        "name": "execution_completed",
        "source": "GET /executions/{id}",
        "captured_by": "ops",
        "captured_at": OBSERVED,
        "fixtures_dir": tmp_path,
    }
    first = record_fixture(_realistic_payload(), **args).read_text(encoding="utf-8")
    assert record_fixture(_realistic_payload(), **args).read_text(encoding="utf-8") == first


# --- 8. the seam with the gate runner ------------------------------------------


def test_a_runner_result_converts_into_an_artifact_result() -> None:
    """The bridge between the two result types this wave produced.

    If `scripts/pilot/results.py` changes shape, this test is the alarm — which is the
    point of having it while two contracts exist. The end state is one type.
    """
    from scripts.pilot.results import GateRun, failed, not_run, passed

    ran = GateRun(
        number=4,
        title="Real-call latency",
        checks=(passed("p50", "stopwatch over 10 calls", p50_s=1.02),),
    )
    converted = from_runner_result(ran, observed_at=OBSERVED, operator="ops")
    assert converted.verdict is Verdict.PASS
    assert converted.measurements[0].value == Decimal("1.02")

    half = GateRun(
        number=4,
        title="Real-call latency",
        checks=(passed("p50", "ok", p50_s=1.02), not_run("p95", "only 3 calls placed")),
    )
    assert from_runner_result(half, observed_at=OBSERVED, operator="ops").verdict is (
        Verdict.INCONCLUSIVE
    ), "a partially executed gate is inconclusive, not unattempted"

    blocked = GateRun(number=4, title="Real-call latency", blocked="no credentials")
    assert from_runner_result(blocked, observed_at=OBSERVED, operator="ops").verdict is (
        Verdict.NOT_RUN
    )

    red = GateRun(number=4, title="Real-call latency", checks=(failed("p95", "1.9s over budget"),))
    assert from_runner_result(red, observed_at=OBSERVED, operator="ops").verdict is Verdict.FAIL


def test_a_runner_pass_on_a_human_gate_is_downgraded_without_a_written_source() -> None:
    """The runner cannot email a vendor, so it cannot produce the evidence gates 9-12
    require. It must not be able to produce the VERDICT either."""
    from scripts.pilot.results import GateRun, SubCheck

    ran = GateRun(
        number=12,
        title="Commercials in writing",
        checks=(SubCheck(name="fee", status="pass", detail="operator says", attested=True),),
    )
    converted = from_runner_result(ran, observed_at=OBSERVED, operator="ops")
    assert converted.verdict is Verdict.INCONCLUSIVE
    assert converted.summary and "written source" in converted.summary


# --- 9. the fixture is a real test of the adapter ------------------------------


async def test_a_recorded_payload_replays_through_the_bolna_adapter(tmp_path: Path) -> None:
    """What the capture is FOR (OPERATIONS §2 gates 1/2/4/7/8).

    The adapter is hand-maintained from documentation — Bolna publishes no OpenAPI spec —
    so a captured payload is the only thing that can falsify it. This test proves the
    redacted fixture is still adapter-grade input: if redaction broke the shape (a number
    that no longer parses, a transcript that no longer splits), the pilot would have
    captured a souvenir instead of a test.
    """
    record_fixture(
        _realistic_payload(),
        gate=4,
        name="execution_completed",
        source="GET /executions/{id}",
        captured_by="ops",
        captured_at=OBSERVED,
        fixtures_dir=tmp_path,
    )
    payload = load_fixture("execution_completed", fixtures_dir=tmp_path)

    engine = BolnaEngine(
        api_key="test-key",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        ),
    )
    snapshot = await engine.get_execution("exec_abc123")

    assert snapshot.status == "completed" and snapshot.billable_ready
    assert snapshot.engine_agent_ref == "agent_xyz"
    assert snapshot.from_e164 and snapshot.from_e164.startswith("+91")
    assert [t.idx for t in snapshot.transcript] == [0, 1, 2]
    assert snapshot.cost is not None and snapshot.cost.total_inr == Decimal("7.48")
