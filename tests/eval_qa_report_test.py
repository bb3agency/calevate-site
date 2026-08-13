"""The client-facing QA report (ROADMAP M3, G3) — is it safe to send, and is it honest?

`scripts/qa_report.py` is the one artefact in this repo that is written to leave the
building and land in a customer's inbox as a SALES asset. That gives it two failure modes
the engineer's report does not have, and this module is about those two rather than about
whether the markdown is pretty:

1. **It leaks.** Hard rules 5 and 6 apply to every line of a document a client's owner
   reads, and the harness's inputs are transcripts. A QA report that quotes a caller's
   sentence to illustrate a capture miss has leaked exactly what the redaction pipeline
   exists to prevent, and it has leaked it into an email nobody can recall.
2. **It overclaims.** A sales asset with an incentive to flatter is the place a
   percentage over three cases, or a trend over one month, gets printed. The repo has a
   settled answer (`after_hours_basis`, `CallVolume.basis`) and the tests below hold this
   document to it.

The leak tests are written as SCANS of the rendered document rather than as unit tests of
the pieces, deliberately. A unit test proves the function it names is careful; a scan
proves the DOCUMENT is clean, including the parts a future section adds. The next person
to add a section to that report should have to defeat these tests on purpose.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
import scripts.eval as ev
import scripts.qa_report as qa
from calevate_shared.extraction import ExtractionSchemaSpec

AS_OF = date(2026, 8, 31)


def _spec() -> ExtractionSchemaSpec:
    payload = json.loads(ev.FIXTURES.read_text())
    return ExtractionSchemaSpec(version=1, fields=payload["schema"])


def _cases() -> list[dict[str, object]]:
    return list(json.loads(ev.FIXTURES.read_text())["cases"])


async def _report(vertical: str = "clinic") -> str:
    results, meta = await ev.run_suite("sunrise-clinic", vertical)
    return qa.render(
        results,
        _spec(),
        client="sunrise-clinic",
        vertical=vertical,
        model=str(meta["model"]),
        as_of=AS_OF,
    )


# --- Can it be sent? (hard rules 5 and 6) ----------------------------------------


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_the_report_contains_no_digit_run_at_all(vertical: str) -> None:
    """Stricter than `eval.render`'s rule, and it can afford to be.

    The engineer's report quotes values and therefore needs `_safe` to mask them; this
    document is built from counts and labels, so there is no legitimate long digit run in
    it whatsoever — not even a masked one. Asserting the absence rather than the masking
    is the stronger guarantee: masking has to be applied at each new call site and can be
    forgotten, while a rule of "no such digits exist here" is checked once, over
    everything, including sections that do not exist yet.
    """
    report = await _report(vertical)
    assert not re.search(r"\d{4,}", report.replace(AS_OF.isoformat(), "")), report


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_no_line_any_caller_or_agent_said_reaches_the_report(vertical: str) -> None:
    """The leak that would actually happen: an illustrative quote.

    Scans every turn of every fixture — both speakers, because the agent's line is a
    script we wrote but is still a sentence from a call and still describes what the
    caller wanted.
    """
    report = await _report(vertical)
    for case in _cases():
        for turn in case["transcript"]:  # type: ignore[index]
            body = str(turn).split(":", 1)[1].strip()
            assert body not in report, f"{case['id']}: a transcript line reached the report"


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_no_case_title_reaches_the_report(vertical: str) -> None:
    """Titles are ours, not the caller's — and they are still out.

    A title like "An NRI states the budget in dollars" is a PARAPHRASE of what one caller
    said, which is the same category of disclosure one step removed, and at 110 rows it
    would also be unreadable. This is the assertion behind the module docstring's
    "aggregation here is not simplification; it is the redaction".
    """
    report = await _report(vertical)
    for case in _cases():
        assert str(case["title"]) not in report, case["id"]
        assert str(case["id"]) not in report, case["id"]


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_no_captured_value_reaches_the_report(vertical: str) -> None:
    """The subtler leak: not the transcript, but what we EXTRACTED from it — a name, a
    locality, a callback time. `_known_limits` reads failure messages that contain both a
    field key and an expected value, and takes only the key; this is what stops that from
    silently changing.

    Scoped to FREE-TEXT fields. An enum member and a boolean are our own closed
    vocabulary — the schema author picked the word `book`, no caller uttered it, and it
    appears in this document inside the ordinary English word "booking". Asserting on
    those would make the test fire on prose, and a leak test that cries wolf is a leak
    test somebody loosens. What a caller actually SUPPLIES is the free text: their name,
    their locality, the words they chose for a callback time.
    """
    spec = _spec()
    text_keys = {f.key for f in spec.fields if f.type == "text"}
    results, _ = await ev.run_suite("sunrise-clinic", vertical)
    report = await _report(vertical)
    checked = 0
    for result in results:
        for key, value in result.captured.items():
            if key in text_keys and isinstance(value, str) and value.strip():
                checked += 1
                assert value not in report, f"{result.case_id}: {key} value reached the report"
    assert checked, "no free-text value was captured at all, so this asserts nothing"


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_the_report_names_the_clients_columns_and_not_our_keys(vertical: str) -> None:
    """The client reads their own column names. `budget_lakhs` is our schema; "Budget
    (lakhs)" is what they see on their leads screen, and a report that speaks our keys
    asks them to learn our internals to read their own results.

    The labels are removed from the section BEFORE the keys are looked for, because some
    keys are substrings of their own labels (`name` inside "Caller name"). Searching the
    raw text would fail on a correct document, which is the kind of test that gets
    deleted rather than fixed.
    """
    spec = _spec()
    # Bounded at the NEXT heading. An unbounded slice runs to the end of the document and
    # swallows the closing "no caller name, no number" disclaimer, which contains the
    # word `name` — the test would then be failing on the very sentence that promises
    # the thing it is checking.
    limits_section = (await _report(vertical)).split("## Known limits", 1)[1].split("\n## ", 1)[0]
    assert "| " in limits_section, "no limits table to check"
    stripped = limits_section
    for field in spec.fields:
        stripped = stripped.replace(field.label, "")
    for field in spec.fields:
        assert field.key not in stripped, field.key


# --- Is it honest? ----------------------------------------------------------------


def test_a_percentage_is_not_printed_over_too_few_scenarios() -> None:
    """The `after_hours_basis` precedent, as the rule this document actually applies.

    Below the floor the count stands alone; at or above it a percentage is earned. Both
    directions matter — a `basis` that never reaches `measured` is not honesty, it is a
    document that refuses to say anything.
    """
    scarce = qa.measure(2, 3)
    assert scarce.basis == "too_few"
    assert "%" not in scarce.rendered
    assert scarce.rendered == "2 of 3"

    ample = qa.measure(30, qa.MIN_FOR_PERCENT)
    assert ample.basis == "measured"
    assert "%" in ample.rendered


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_no_trend_is_claimed_from_a_single_run(vertical: str) -> None:
    """A monthly report's most natural sentence is "better than last month", and on the
    first month it is unsupported. `CallVolume.basis` refuses the same sentence for the
    same reason; this refuses it in prose the client can read."""
    report = await _report(vertical)
    assert "not established" in report
    assert qa.BASIS_NOTE["no_baseline"] in report


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_the_headline_defect_count_uses_the_harnesss_own_unwaivable_kinds(
    vertical: str,
) -> None:
    """The claim the document is built around, tied to the harness rather than restated.

    If `_defect_count` drifted from `eval.NON_WAIVABLE_KINDS` the client-facing number
    would be the wrong one, and it would be wrong in the reassuring direction — which is
    the only direction that matters for a sales asset.

    The real suite is clean, so comparing it against the live predicate proves NOTHING —
    both sides are zero and the assertion holds for any predicate at all. That is not a
    hypothetical: narrowing `_defect_count` to `capture_wrong` alone left this test green,
    which is a client-facing zero covering a missed disclosure. So each unwaivable kind is
    injected on its own and has to be counted on its own, and the clean suite is asserted
    to be clean SEPARATELY rather than doing both jobs badly.
    """
    results, _ = await ev.run_suite("sunrise-clinic", vertical)
    assert qa._defect_count(results) == 0
    report = await _report(vertical)
    assert "| Defects | **0** |" in report

    for kind in sorted(ev.NON_WAIVABLE_KINDS):
        planted = ev.CaseResult(case_id="planted", title="planted", scenario=1)
        planted.fail(kind, "injected")
        assert qa._defect_count([*results, planted]) == 1, (
            f"a {kind} failure does not reach the client's defect count"
        )

    for kind in sorted(ev.WAIVABLE_KINDS):
        # …and the other direction, or "count everything" would pass the loop above and
        # report a known blank field to the client as a defect.
        limited = ev.CaseResult(case_id="planted", title="planted", scenario=1)
        limited.fail(kind, "injected")
        assert qa._defect_count([limited]) == 0, f"{kind} is a limit, not a defect"


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_the_two_result_rows_account_for_every_scenario(vertical: str) -> None:
    """The split that replaced a single "behaving as approved" figure. If the two rows
    stopped partitioning the suite, a client could add them up and find scenarios
    missing — which is exactly the arithmetic an owner does to a report like this."""
    results, _ = await ev.run_suite("sunrise-clinic", vertical)
    clean = sum(1 for r in results if r.passed)
    assert qa.measure(clean, len(results)).passed + qa.measure(
        len(results) - clean, len(results)
    ).passed == len(results)


@pytest.mark.parametrize("vertical", list(ev.VERTICALS))
async def test_a_known_limit_is_reported_as_blank_and_never_as_wrong(vertical: str) -> None:
    """The distinction the whole document rests on: a field the model could not read is a
    BLANK column, and a blank column is recoverable by a human. Only `capture_miss` may
    reach this table — a `capture_wrong` is a defect and belongs in the headline, never
    softened into a limit."""
    results, _ = await ev.run_suite("sunrise-clinic", vertical)
    limits = qa._known_limits(results, _spec())
    misses = sum(1 for r in results for f in r.failures if f.kind == ev.CAPTURE_MISS)
    assert sum(limit.scenarios for limit in limits) == misses


# --- Is it reproducible? -----------------------------------------------------------


async def test_the_report_is_byte_identical_across_runs() -> None:
    """A sales asset that renders differently on two runs is not evidence. Two full
    renders, compared whole — the same reason `--as-of` is an argument rather than
    `now()`."""
    assert await _report("clinic") == await _report("clinic")


async def test_each_client_gets_their_own_scenarios_and_not_the_other_verticals() -> None:
    """Per-client, because extraction schemas are per-agent: a clinic's QA report listing
    fifty property calls is not the asset D-15 describes, and the counts are the client's
    evidence that we tested THEIR agent."""
    clinic, estate = await _report("clinic"), await _report("real_estate")
    assert clinic != estate
    counts = {v: sum(1 for c in _cases() if c["vertical"] == v) for v in ev.VERTICALS}
    assert f"{counts['clinic']} scenarios, in six kinds" in clinic
    assert f"{counts['real_estate']} scenarios, in six kinds" in estate


async def test_the_generator_refuses_to_render_a_report_over_no_scenarios(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure this document is most likely to have in production: a filter that
    matches nothing renders a clean-looking page which measured nothing at all — a
    "0 defects across 0 scenarios" that is technically true and is the single most
    misleading sentence this file could emit. It refuses instead, with exit 2.

    Driven by swapping the FIXTURE FILE rather than by mocking `run_suite`, so the
    refusal is proved on the real code path: the day somebody adds a caching layer or a
    second data source, a mock would keep passing and this will not.
    """
    # Every case belongs to the other vertical, so the clinic filter matches nothing.
    payload = json.loads(ev.FIXTURES.read_text())
    payload["cases"] = [c for c in payload["cases"] if c["vertical"] == "real_estate"]
    empty_for_clinic = tmp_path / "golden_transcripts.json"
    empty_for_clinic.write_text(json.dumps(payload))
    monkeypatch.setattr(ev, "FIXTURES", empty_for_clinic)

    assert await qa.main_async("nobody", "clinic", None, AS_OF) == 2
    # …and the control: the same file still renders for the vertical it does hold, so
    # the refusal is about an empty selection and not about a broken fixture path.
    assert await qa.main_async("somebody", "real_estate", tmp_path / "r.md", AS_OF) == 0
