"""Does the quality gate actually gate?

`tests/eval_harness_test.py` pins the harness's plumbing — the ratchet direction, the
fixtures parsing. This file asks the only question that matters about a regression
suite: **construct the regression it claims to catch, and see whether it fails.**

The audit that produced this file found the answer was largely no. The gate ran the
shipped extractor against real code-mixed transcripts, and CI ran it honestly — but:

1. The baseline waived a whole CASE, so the three cases sitting in it could return a
   wrong name, a fabricated number and a wrong outcome tag and the gate stayed green.
   Only ONE fixture case was gating any capture at all.
2. `must_redact` listed `9876543210` while the transcript said "nine eight seven six…",
   so the substring check could never fail — the spoken-digit fixture, whose own note
   says "the one a pure regex cannot see", passed with the spoken-digit redaction layer
   switched off entirely.
3. Nothing stopped a change from gutting a fixture's `expect` and leaving the gate
   green with zero capture assertions.

So the tests below degrade the extractor deliberately — through the SHIPPED
`extract_call` path, by substituting the object `get_extractor()` returns — and assert
the gate goes red. Every degradation is a thing a real model does: an empty payload
from a filtered generation, a transposed digit, the right value in the wrong column, a
lead confabulated out of a silent call.

Nothing here needs model credentials. With no provider key configured the shipped path
resolves to `OfflineExtractor`, which is what CI runs, so a human can run this gate on
a laptop with `make eval-ci`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import apps.workers.extraction as extraction_module
import pytest
import scripts.eval as ev
from calevate_shared.extraction import ExtractionSchemaSpec

Mutator = Callable[[dict[str, Any], str], dict[str, Any]]


# --- Harnessing the shipped path ------------------------------------------------


class _Degraded:
    """Wraps the real offline extractor and corrupts its output.

    It keeps `model_name` identical so the SAME committed baseline applies — a
    degradation that changed the model name would land on an empty baseline and look
    caught for the wrong reason.
    """

    model_name = "offline-heuristic"

    def __init__(self, mutate: Mutator) -> None:
        self._mutate = mutate
        self._inner = extraction_module.OfflineExtractor()

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        return self._mutate(dict(await self._inner.run(spec, transcript)), transcript)


@contextmanager
def _extractor(mutate: Mutator) -> Iterator[None]:
    """Substitute the extractor `extract_call` resolves, leaving the rest of the
    shipped path — prompt build, schema validation, coercion — untouched."""
    real = extraction_module.get_extractor
    extraction_module.get_extractor = lambda: _Degraded(mutate)
    try:
        yield
    finally:
        extraction_module.get_extractor = real


async def _gate(mutate: Mutator) -> tuple[list[str], set[str]]:
    """Run the whole suite under a degradation. Returns (regressions, failure kinds)."""
    with _extractor(mutate):
        results, meta = await ev.run_suite("test")
    regressions, _ = ev.classify(results, ev.load_baseline().get(str(meta["model"]), []))
    kinds = {f.kind for r in results if r.case_id in set(regressions) for f in r.failures}
    return regressions, kinds


def _fixtures() -> dict[str, Any]:
    return json.loads(ev.FIXTURES.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# --- The degradations -----------------------------------------------------------


def _empty(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """What a provider returns when it declines: `choices: []` -> `{}`."""
    return {}


def _drop_name(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    raw.pop("name", None)
    return raw


def _wrong_name(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """Plausible and wrong — the interesting one. Nothing crashes, nothing is empty,
    and the SMB rings a stranger by the wrong name."""
    if raw.get("name"):
        raw["name"] = "Ramesh"
    return raw


def _invent_urgency(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """A model being helpful: every column filled, restraint gone."""
    raw["urgency"] = "urgent"
    return raw


def _always_resolved(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """Outcome drives the hot-lead rules; every call 'resolved' means no follow-up."""
    raw["outcome_tag"] = "resolved"
    return raw


def _transposed_digit(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """One digit off. The single failure this whole harness exists to stop."""
    if "tommidi tommidi" in transcript.lower():
        raw["callback_number"] = "9999999998"
    return raw


def _wrong_column(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """Right value, wrong column: the son's number filed as the patient's own."""
    if "koduku number" in transcript:
        raw["callback_number"] = "8888888888"
        raw["number_belongs_to"] = "self"
    return raw


def _lead_from_silence(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    if "Nenu vinapadutunnana" in transcript:
        raw |= {"name": "Ramesh", "intent": "book", "callback_number": "7777777777"}
    return raw


def _resolved_relative_time(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """ "kal subah" turned into a confident absolute timestamp, off by a day."""
    if "kal subah" in transcript:
        raw["callback_time"] = "2026-08-13T06:00:00"
    return raw


def _first_match_wins(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """The extractor as it behaved before it learned that a later clause can revoke an
    earlier one: the first name and the first enum value that matched, whatever the
    caller said afterwards. Reproduced as OUTPUT here, exactly like `_wrong_name` above,
    because the point is that the SUITE catches it — a self-corrected name and a
    replaced requirement come back confidently wrong rather than empty.
    """
    if "kaadu kaadu" in transcript and raw.get("name"):
        raw["name"] = "Ravi"
    if "saripodu" in transcript and raw.get("bhk_size"):
        raw["bhk_size"] = "2BHK"
    return raw


def _a_denial_read_as_a_statement(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """The other half of the same rule: the caller says do NOT cancel and asks where the
    site is, and both words are filed as facts about them."""
    if "cancel cheyakandi" in transcript:
        raw["intent"] = "cancel"
    if "site address" in transcript:
        raw["site_visit_interest"] = True
    return raw


def _only_baselined_cases(raw: dict[str, Any], transcript: str) -> dict[str, Any]:
    """Corrupt ONLY the cases the baseline already forgives.

    This is the probe that failed before the ratchet was made kind-aware: a whole-case
    waiver meant these fixtures were scored and then ignored.
    """
    if any(marker in transcript for marker in ("Ravi Kumar", "Suresh", "Anjali")):
        return {"name": "Ramesh", "urgency": "urgent", "outcome_tag": "dropped"}
    return raw


DEGRADATIONS: list[tuple[str, Mutator, str]] = [
    ("empty payload", _empty, ev.CAPTURE_MISS),
    ("a dropped field", _drop_name, ev.CAPTURE_MISS),
    ("a plausible but wrong name", _wrong_name, ev.CAPTURE_WRONG),
    ("an invented field", _invent_urgency, ev.RESTRAINT),
    ("every call tagged resolved", _always_resolved, ev.OUTCOME),
    ("a phone number one digit off", _transposed_digit, ev.CAPTURE_WRONG),
    ("the right value in the wrong column", _wrong_column, ev.CAPTURE_WRONG),
    ("a lead confabulated from silence", _lead_from_silence, ev.RESTRAINT),
    ("a relative time resolved to the wrong day", _resolved_relative_time, ev.CAPTURE_WRONG),
    ("the first match kept over the caller's correction", _first_match_wins, ev.CAPTURE_WRONG),
    ("a denial read as a statement", _a_denial_read_as_a_statement, ev.RESTRAINT),
    ("corruption confined to baselined cases", _only_baselined_cases, ev.RESTRAINT),
]


@pytest.mark.parametrize(
    ("label", "mutate", "expected_kind"),
    [pytest.param(lbl, fn, kind, id=lbl) for lbl, fn, kind in DEGRADATIONS],
)
async def test_a_degraded_extractor_fails_the_gate(
    label: str, mutate: Mutator, expected_kind: str
) -> None:
    regressions, kinds = await _gate(mutate)
    assert regressions, f"{label} did not fail the gate — it is not gating this"
    assert expected_kind in kinds, (
        f"{label} was caught, but as {sorted(kinds)}, not {expected_kind}"
    )


async def test_the_undegraded_suite_is_green() -> None:
    """The control. Without it, every test above could be passing because the gate is
    red for an unrelated reason."""
    results, meta = await ev.run_suite("test")
    regressions, _ = ev.classify(results, ev.load_baseline().get(str(meta["model"]), []))
    assert not regressions, f"the committed baseline is stale: {regressions}"


# --- The ratchet may only move one way ------------------------------------------


def test_only_excusable_failure_kinds_are_waivable() -> None:
    """A weaker model may miss a field. No model tier makes it acceptable to file a
    wrong value, invent one, skip the disclosure or leak PII."""
    assert ev.WAIVABLE_KINDS.isdisjoint(ev.NON_WAIVABLE_KINDS)
    for kind in (ev.CAPTURE_WRONG, ev.RESTRAINT, ev.COMPLIANCE, ev.REDACTION, ev.FIXTURE):
        assert kind in ev.NON_WAIVABLE_KINDS


def test_a_baseline_cannot_waive_a_fabricated_field() -> None:
    """Even if someone hand-edits the baseline to name the kind explicitly."""
    result = ev.CaseResult(case_id="c", title="c", scenario=1)
    result.fail(ev.RESTRAINT, "invented callback_number")
    regressions, _ = ev.classify([result], {"c": [ev.RESTRAINT, ev.CAPTURE_WRONG]})
    assert regressions == ["c"]


def test_update_baseline_refuses_to_bless_a_non_waivable_failure(tmp_path: Any) -> None:
    """`--update-baseline` is the one automated path that can move the bar, so it is
    the one place a wrong number could be blessed by a reviewer skimming a diff."""
    baseline = tmp_path / "baseline.json"
    real, ev.BASELINE = ev.BASELINE, baseline
    try:
        good = ev.CaseResult(case_id="miss", title="miss", scenario=1)
        good.fail(ev.CAPTURE_MISS, "missed party_size")
        bad = ev.CaseResult(case_id="fabricated", title="fabricated", scenario=1)
        bad.fail(ev.CAPTURE_WRONG, "callback_number: expected 9…9, got 9…8")
        refused = ev.save_baseline("some-model", [good, bad])
        assert refused == ["fabricated"]
        written = json.loads(baseline.read_text(encoding="utf-8"))["some-model"]
        assert written == {"miss": [ev.CAPTURE_MISS]}
    finally:
        ev.BASELINE = real


def test_the_committed_baseline_waives_nothing_unwaivable() -> None:
    """The file on disk, not the writer that produced it — a hand edit gets caught."""
    ids = {case["id"] for case in _fixtures()["cases"]}
    for model, entry in ev.load_baseline().items():
        assert isinstance(entry, dict), f"{model}: v1 flat lists waive too much; use kinds"
        for case_id, kinds in entry.items():
            assert case_id in ids, f"{model} waives {case_id}, which is not a fixture any more"
            unwaivable = set(kinds) - ev.WAIVABLE_KINDS
            assert not unwaivable, f"{model}/{case_id} tries to waive {sorted(unwaivable)}"


def test_a_model_with_no_baseline_entry_fails_closed() -> None:
    """Renaming the model must not hand the change under test a blank cheque."""
    result = ev.CaseResult(case_id="c", title="c", scenario=1)
    result.fail(ev.CAPTURE_MISS, "missed name")
    assert ev.classify([result], ev.load_baseline().get("a-model-nobody-baselined", []))[0] == ["c"]


# --- The fixtures must keep asserting something ---------------------------------

#: Deleting or gutting a case is the cheapest way to make a red gate green. These ids
#: are load-bearing: each covers a failure mode the product meets in the field.
REQUIRED_CASES = {
    "core5_happy_path",
    "core5_interruption",
    "core5_tool_call",
    "core5_out_of_scope",
    "core5_compliance",
    "pii_spoken_number",
    "callback_number_spoken_digits",
    "relative_number_attribution",
    "hindi_mixed_callback_time",
    "wrong_number_call",
    "hostile_caller_complaint",
    "silent_call",
    "telugu_script_booking",
}


def test_no_required_fixture_case_has_been_dropped() -> None:
    missing = REQUIRED_CASES - {case["id"] for case in _fixtures()["cases"]}
    assert not missing, f"fixture cases removed without replacing their coverage: {missing}"


def test_every_case_asserts_something() -> None:
    """A case with no `expect`, no `expect_absent` and no compliance flag passes no
    matter what the extractor does — it inflates the pass count and gates nothing."""
    for case in _fixtures()["cases"]:
        assertions = (
            len(case.get("expect") or {})
            + len(case.get("expect_absent") or [])
            + len(case.get("must_redact") or [])
            + bool(case.get("expect_outcome"))
            + bool(case.get("requires_dnc"))
        )
        assert assertions >= 2, f"{case['id']} asserts almost nothing ({assertions})"


def test_restraint_is_asserted_at_least_as_widely_as_capture() -> None:
    """Restraint is the half that protects the CRM, and it is the half that quietly
    erodes: it costs nothing to add an `expect`, and effort to list what must stay
    empty. Fixtures that only assert capture reward a model that guesses."""
    cases = _fixtures()["cases"]
    captures = sum(len(c.get("expect") or {}) for c in cases)
    restraints = sum(len(c.get("expect_absent") or []) for c in cases)
    assert restraints >= captures, f"{restraints} restraint assertions vs {captures} capture"


def test_the_fixtures_cover_what_this_product_actually_meets() -> None:
    """Telugu-first, code-mixed, spoken digits, relative times, and the ugly calls.
    A suite of clean English transcripts measures a product we do not sell."""
    cases = {c["id"]: c for c in _fixtures()["cases"]}
    joined = " ".join(t for c in cases.values() for t in c["transcript"])

    assert any("ఀ" <= ch <= "౿" for ch in joined), "no native Telugu script anywhere"
    assert "kal subah" in joined, "no Hindi-mixed call — Hyderabad SMBs take both"
    # Digits read aloud, which is how a caller gives a number on an Indian phone call.
    assert "tommidi tommidi" in joined
    schema_keys = {f["key"] for f in _fixtures()["schema"]}
    assert {"callback_number", "callback_time", "number_belongs_to"} <= schema_keys, (
        "the callback number is the field the SMB acts on; it must be in the schema"
    )
    assert any(c.get("must_redact") for c in cases.values())


def test_every_phone_number_in_the_fixtures_is_synthetic() -> None:
    """Golden fixtures are committed, shared with clients as sample QA reports, and
    read by every agent that touches this repo. A real number must never enter them."""
    import itertools
    import re

    def is_obviously_fake(digits: str) -> bool:
        """One repeated digit (9999999999) or a strict run (9876543210). Anything
        else could be somebody's phone, and "it looked made up" is not a defence."""
        if len(set(digits)) == 1:
            return True
        steps = {int(b) - int(a) for a, b in itertools.pairwise(digits)}
        return steps in ({1}, {-1})

    text = json.dumps(_fixtures(), ensure_ascii=False)
    for candidate in re.findall(r"\b[6-9]\d{9}\b", text):
        assert is_obviously_fake(candidate), f"{candidate} could be a real number"


# --- Redaction assertions must be capable of failing ----------------------------


async def test_a_must_redact_secret_that_is_not_in_the_transcript_is_a_fixture_bug() -> None:
    """The exact hole this audit found: `9876543210` listed while the caller says
    "nine eight seven six…". The substring check could not fail, so the case passed
    with spoken-digit redaction switched off entirely."""
    case = {
        "id": "vacuous",
        "title": "vacuous",
        "scenario": 5,
        "transcript": ["agent: idi AI assistant, call record avutundi."],
        "must_redact": ["9999999999"],
    }
    result = ev.CaseResult(case_id="vacuous", title="vacuous", scenario=5)
    ev._check_redaction(case, result)
    assert not result.passed
    assert result.kinds == {ev.FIXTURE}


async def test_spoken_digits_left_unredacted_fail_the_gate() -> None:
    """Words, not digits — what a regex cannot see and what the fixture claims to
    cover. Scored against the shipped `redact`, with the spoken-digit layer removed."""
    import apps.workers.redaction as redaction_module

    real = redaction_module.spoken_digit_runs
    redaction_module.spoken_digit_runs = lambda text: []
    try:
        results, _ = await ev.run_suite("test")
    finally:
        redaction_module.spoken_digit_runs = real
    leaking = [r.case_id for r in results if ev.REDACTION in r.kinds]
    assert "pii_spoken_number" in leaking, "spoken-digit redaction is not actually gated"


async def test_a_missing_disclosure_fails_on_every_model() -> None:
    """Compliance is our code, never the model's, so it is never baselineable."""
    case = {
        "id": "no_disclosure",
        "title": "no disclosure",
        "scenario": 5,
        "transcript": ["agent: Namaskaram, cheppandi.", "caller: Naaku appointment kavali."],
    }
    result = ev.CaseResult(case_id="no_disclosure", title="no disclosure", scenario=5)
    ev._check_compliance(case, result)
    assert result.kinds == {ev.COMPLIANCE}
    assert ev.classify([result], {"no_disclosure": list(ev.WAIVABLE_KINDS)})[0] == ["no_disclosure"]


# --- Runnable without credentials -----------------------------------------------


def test_the_gate_runs_with_no_provider_key() -> None:
    """A quality gate nobody can run locally is a quality gate that rots. With no key
    configured the shipped selector must land on the offline extractor — the same one
    CI scores, so a laptop run and a CI run compare."""
    from apps.api.core.settings import get_settings

    settings = get_settings()
    if settings.sarvam_api_key or settings.gemini_api_key:
        pytest.skip("a provider key is configured in this environment")
    extractor = extraction_module.get_extractor()
    assert isinstance(extractor, extraction_module.OfflineExtractor)
    assert extractor.model_name in ev.load_baseline(), (
        "CI's own model has no committed baseline, so CI is scoring against nothing"
    )
