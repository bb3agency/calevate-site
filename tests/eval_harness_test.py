"""The regression harness's own tests.

A quality gate nobody tests is a quality gate that silently stops gating — which is
exactly what happened to the RBAC boot assertion earlier in this build. These pin down
the two behaviours the gate depends on: the ratchet direction, and that the fixtures
still parse into a valid schema.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from calevate_shared.extraction import ExtractionSchemaSpec
from scripts.eval import (
    FIXTURES,
    SCENARIO_LABELS,
    VERTICALS,
    CaseResult,
    _value_matches,
    classify,
    run_suite,
)


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
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    spec = ExtractionSchemaSpec(version=1, fields=payload["schema"])
    keys = {f.key for f in spec.fields}
    for case in payload["cases"]:
        unknown = (set(case.get("expect", {})) | set(case.get("expect_absent", []))) - keys
        assert not unknown, f"{case['id']} references fields not in the schema: {unknown}"


async def test_the_mandatory_five_scenarios_are_all_covered() -> None:
    """OPERATIONS §3 names five scenarios and they are mandatory, not aspirational.
    Scenario 6 is ROADMAP M3's red-team class, which grows on top of them and never
    instead of them — so this is a superset assertion, and every scenario number that
    appears has to be one the report can name."""
    results, meta = await run_suite("test")
    scenarios = {r.scenario for r in results}
    assert {1, 2, 3, 4, 5} <= scenarios
    assert scenarios <= set(SCENARIO_LABELS)
    assert meta["model"], "the report must name the model it measured"


async def test_each_vertical_carries_its_own_five() -> None:
    """ "50-100 scenarios per client" (OPERATIONS §3) is counted per CLIENT, so a
    vertical that borrows another's happy path has no happy path."""
    results, _ = await run_suite("test")
    for vertical in VERTICALS:
        scenarios = {r.scenario for r in results if r.vertical == vertical}
        assert {1, 2, 3, 4, 5, 6} <= scenarios, f"{vertical} is missing {scenarios}"


async def test_the_vertical_filter_returns_a_subset_of_the_gated_suite() -> None:
    """The client-facing report may narrow; it may never contain a case CI never saw,
    or a green client report would be compatible with a red gate."""
    everything, _ = await run_suite("test")
    all_ids = {r.case_id for r in everything}
    seen: set[str] = set()
    for vertical in VERTICALS:
        results, filtered_meta = await run_suite("test", vertical)
        assert results, f"{vertical} has no scenarios"
        assert {r.vertical for r in results} == {vertical}
        assert filtered_meta["cases"] == len(results)
        seen |= {r.case_id for r in results}
    assert seen == all_ids, "a case belongs to no vertical the report can print"


# --- How a captured value is compared -------------------------------------------
#
# Exact string equality was the original rule and it is wrong in both directions: it
# fails a model that answered correctly with three more words, and it teaches the
# fixture author to write for the scorer. `capture_wrong` is unwaivable, so the day a
# credentialed model runs this suite an over-strict comparison IS the permanently red
# gate the ratchet exists to avoid.


def _field(key: str) -> Any:
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return ExtractionSchemaSpec(version=1, fields=payload["schema"]).field_by_key(key)


@pytest.mark.parametrize(
    ("key", "expected", "actual", "accepted"),
    [
        # Free text: a longer answer that contains the expected phrase is right.
        ("name", "Ravi Kumar", "Ravi Kumar garu", True),
        ("preferred_location", "Kondapur", "Kondapur area", True),
        ("callback_time", "kal subah", "kal subah 8 baje", True),
        ("name", "Ravi Kumar", "Ramesh", False),
        # …but never a digit string. One digit off is the failure this harness exists
        # to stop, and "contains no error" is exactly how it would slip through.
        ("callback_number", "9999999999", "9999999998", False),
        ("callback_number", "9999999999", "99999999990", False),
        ("callback_number", "9999999999", "+91 9999999999", True),
        # Enums are a closed set: a near miss is a different answer.
        ("bhk_size", "2BHK", "2BHK flat", False),
        ("intent", "book", "BOOK", True),
        # Numbers compare as quantities, not as strings.
        ("budget_lakhs", 50, 50.0, True),
        ("budget_lakhs", 50, 5000000, False),
        # Booleans are not their string spellings.
        ("site_visit_interest", True, True, True),
        ("site_visit_interest", True, "yes", False),
        # A list of expectations means "any of these is faithful".
        ("timeline", ["next year", "vachche samvatsaram"], "vachche samvatsaram", True),
        ("timeline", ["next year", "vachche samvatsaram"], "ee nela", False),
    ],
)
def test_a_captured_value_is_compared_the_way_a_human_would(
    key: str, expected: Any, actual: Any, accepted: bool
) -> None:
    assert _value_matches(_field(key), expected, actual) is accepted


async def test_compliance_and_redaction_cases_pass_regardless_of_model() -> None:
    """Extraction quality is model-dependent and allowed to sit in the baseline.
    Disclosure, DNC acknowledgement and redaction are NOT — they are our code, and
    they must pass on every model, always."""
    results, _ = await run_suite("test")
    compliance = next(r for r in results if r.case_id == "core5_compliance")
    pii = next(r for r in results if r.case_id == "pii_spoken_number")
    assert compliance.passed, compliance.failures
    assert pii.passed, pii.failures
