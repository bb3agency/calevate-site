"""The regression harness's own tests.

A quality gate nobody tests is a quality gate that silently stops gating — which is
exactly what happened to the RBAC boot assertion earlier in this build. These pin down
the two behaviours the gate depends on: the ratchet direction, and that the fixtures
still parse into a valid schema.
"""

from __future__ import annotations

import json

from calevate_shared.extraction import ExtractionSchemaSpec
from scripts.eval import FIXTURES, CaseResult, classify, run_suite


def _result(case_id: str, passed: bool) -> CaseResult:
    return CaseResult(case_id=case_id, title=case_id, scenario=1, passed=passed)


def test_a_newly_failing_case_is_a_regression() -> None:
    results = [_result("a", False), _result("b", True)]
    regressions, fixed = classify(results, baseline=[])
    assert regressions == ["a"]
    assert fixed == []


def test_a_known_failure_is_not_a_regression() -> None:
    """Without this, the offline baseline would keep CI permanently red and the report
    would stop being read."""
    results = [_result("a", False)]
    regressions, _ = classify(results, baseline=["a"])
    assert regressions == []


def test_a_case_that_starts_passing_is_reported_as_fixed() -> None:
    """Progress has to be visible, or the baseline never shrinks."""
    results = [_result("a", True)]
    regressions, fixed = classify(results, baseline=["a"])
    assert regressions == []
    assert fixed == ["a"]


def test_fixtures_define_a_valid_extraction_schema() -> None:
    payload = json.loads(FIXTURES.read_text())
    spec = ExtractionSchemaSpec(version=1, fields=payload["schema"])
    keys = {f.key for f in spec.fields}
    for case in payload["cases"]:
        unknown = (set(case.get("expect", {})) | set(case.get("expect_absent", []))) - keys
        assert not unknown, f"{case['id']} references fields not in the schema: {unknown}"


async def test_the_mandatory_five_scenarios_are_all_covered() -> None:
    """OPERATIONS §3 names five scenarios and they are mandatory, not aspirational."""
    results, meta = await run_suite("test")
    assert {r.scenario for r in results} == {1, 2, 3, 4, 5}
    assert meta["model"], "the report must name the model it measured"


async def test_compliance_and_redaction_cases_pass_regardless_of_model() -> None:
    """Extraction quality is model-dependent and allowed to sit in the baseline.
    Disclosure, DNC acknowledgement and redaction are NOT — they are our code, and
    they must pass on every model, always."""
    results, _ = await run_suite("test")
    compliance = next(r for r in results if r.case_id == "core5_compliance")
    pii = next(r for r in results if r.case_id == "pii_spoken_number")
    assert compliance.passed, compliance.failures
    assert pii.passed, pii.failures
