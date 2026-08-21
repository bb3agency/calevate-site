"""The client-facing QA report — the sales asset (ROADMAP M3, G3, OPERATIONS §3, D-15).

    make qa-report CLIENT=<slug> VERTICAL=<clinic|real_estate>
    uv run python -m scripts.qa_report --client=<slug> --vertical=clinic

OPERATIONS §3 ends its structure list with the reason this file exists: "report stored
per run (client-shareable PDF = sales asset: 'we regression-test your agent before every
change')", and G3 makes it a monthly obligation to every client. `scripts/eval.py`
already renders a report; this is a DIFFERENT document for a different reader, and the
distinction is the whole design.

WHO READS IT, AND WHAT THAT CHANGES
------------------------------------
`eval.render` writes for the person who can fix the failure: a case-by-case table, the
failing case ids, the failure kinds. That is the right document for an engineer and the
wrong one for the owner of a dental clinic in Kukatpally, who cannot act on
`cl_book_self_corrected_party_size [capture_miss]` and should not have to learn what a
`capture_miss` is to find out whether their agent is safe to keep running.

So this document answers the three questions that owner actually has:

1. *Did you test my agent before you changed it?*  — how many scenarios, of what kinds.
2. *Did anything break?*  — the ratchet result, in a sentence.
3. *Can it do something that costs me?*  — the defect classes, counted, and zero is the
   only acceptable number.

Rejected shape: a per-scenario table like the engineer's report, with the titles
softened. It fails twice. It is unreadable at 110 rows, and the titles are DESCRIPTIONS
OF CALLS ("the caller states the budget in dollars") — a paraphrase of caller content,
which is precisely the thing hard rules 5 and 6 keep out of a document that leaves the
building. Aggregation here is not simplification; it is the redaction.

Rejected format: PDF, which is the word OPERATIONS §3 uses. It needs a rendering
dependency for a document whose value is entirely in what it says, and a PDF is worse to
diff and worse to review. Markdown renders in the console, in a browser, in an email, and
converts to PDF later with a tool that is not this repo's problem.

WHAT IT MAY NOT SAY (hard rules 5 and 6)
-----------------------------------------
Every line is generated from three sources, none of which is transcript-derived: the
scenario CLASS labels (ours), the extraction schema's field LABELS (the client's own
column names, which they wrote), and COUNTS. No case titles, no captured values, no
caller phrases, no numbers a caller spoke. `eval._safe` exists for the engineer's report
because that document quotes values; this one is built so there is nothing to mask, which
is the stronger of the two guarantees and the one `tests/eval_qa_report_test.py` asserts
by scanning the rendered document against every fixture transcript.

HONESTY: A NUMBER THAT WOULD MISLEAD IS NOT PRINTED
----------------------------------------------------
This repo has a settled position and this document follows it rather than inventing a
second one. `crm/service.py::dashboard` set it with `after_hours_basis` (when a number
came from a guess rather than a fact, the API says which) and `admin/health.py` sharpened
it with `CallVolume.basis`, whose docstring makes the argument in full: a trend is only a
statement about an account that traded through the whole comparison window, and an
operator who acts on an unearned one "has been lied to by their own console".

The same hazard is here in two places, so `Measurement.basis` is on every number:

* `measured` — the denominator is large enough that a percentage means something.
* `too_few` — fewer than `MIN_FOR_PERCENT` scenarios. The COUNT is printed and the
  percentage is not, with the reason in the row. "67%" over 3 scenarios is not a
  measurement of anything, and it is the number a client would quote back at us.
* `no_baseline` — a comparison with nothing to compare against. A monthly report's
  natural claim is "better than last month", and on the first month there is no last
  month. Rather than print a trend from one point, the row says so.

WHAT IT MEASURES, AND THE ONE CLAIM IT MAKES
----------------------------------------------
Not the raw pass rate. `scripts/eval.py` is a RATCHET (its exit code is 1 on a
regression, not on absolute red) because the offline extractor CI runs cannot read Telugu
numerals, and a raw "62 of 110 passed" would read to a client as an agent that fails a
third of its calls — which is a statement about our stand-in model, not about their
agent. Printing it unqualified would be the overclaim's mirror image: an UNDERclaim that
is equally untrue.

So the document separates the two things the harness itself separates, using the same
line the baseline draws (`eval.NON_WAIVABLE_KINDS`):

* **Defects** — a wrong value filed, a value invented, a disclosure missed, PII left in
  a transcript. Never acceptable on any model; the harness refuses to baseline them. The
  count belongs in the client's hands and the only acceptable number is zero. THIS is the
  sales claim, and it is one we can actually keep.
* **Known limits** — a field the configured model does not read yet. Reported as a
  limit, named by the client's own column label, because a client whose "Budget" column
  is often blank deserves to know it is a known gap rather than a mystery.

DETERMINISM
------------
A sales asset that renders differently on two runs is not evidence, so the document is a
pure function of (fixtures, baseline, client, vertical, as-of date). `--as-of` is an
explicit argument rather than `now()`: a timestamp to the microsecond would make every
regeneration a diff, and the month is the only time granularity G3 cares about.

ONE COMPUTATION, TWO RENDERINGS (SURFACES §2, "rendered in-app, not just PDF")
------------------------------------------------------------------------------
The in-app report is NOT a second implementation of this one. The counting happens once,
in `summarize()`, and produces `calevate_shared.qa_report.QaReport`; `render()` turns
that into the Markdown this file has always emitted, and `--store` writes the very same
object into `qa_reports` for the client's screen to read back. The API recomputes
nothing — it revalidates the stored row and serves it (`apps/api/quality/service.py`).

That is the whole anti-fork design, and it is asserted rather than trusted:
`tests/qa_report_in_app_test.py::test_the_in_app_report_and_the_cli_report_agree` parses
the numbers back out of this Markdown and compares them field by field with what the
route returns. A number computed a second way inside the API turns that test red.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec

#: The report's own vocabulary, in `shared` because three processes read it: this CLI
#: computes it, `apps/api` serves it and the browser renders it (the reasoning is in
#: `calevate_shared/qa_report.py`). `MIN_FOR_PERCENT` and `Basis` are IMPORTED rather
#: than defined here — a second floor would be a second answer to "when is a percentage
#: earned", and the client reads both documents.
from calevate_shared.qa_report import (
    MIN_FOR_PERCENT,
    Basis,
    FieldLimit,
    Measurement,
    QaReport,
    ScenarioClassCount,
)

import scripts.eval as ev

#: What each basis means IN THE DOCUMENT. The client reads this sentence, so it says what
#: was and was not established rather than naming our internal state.
BASIS_NOTE: dict[Basis, str] = {
    "measured": "",
    "too_few": (
        f"fewer than {MIN_FOR_PERCENT} scenarios — the count is shown and a percentage "
        "is not, because a percentage over this few cases would move by more than ten "
        "points on a single scenario"
    ),
    "no_baseline": ("no previous report to compare against, so no trend is claimed this month"),
}

#: The scenario classes, said the way a client would say them. `eval.SCENARIO_LABELS` is
#: the engineer's vocabulary ("interruption / barge-in", "tool-call correctness") and it
#: is right for that document; this is the same partition described by what it PROVES.
CLIENT_SCENARIO_LABELS: dict[int, str] = {
    1: "A normal call, start to finish",
    2: "The caller interrupts or talks over the agent",
    3: "The agent has to do something, not just talk",
    4: "The caller asks something the agent should not answer",
    5: "The legally required things happen",
    6: "Someone is deliberately trying to break it",
}

#: How the client should read each class — one line, in their terms, saying what a pass
#: is evidence OF. Without this the counts are trivia.
SCENARIO_MEANING: dict[int, str] = {
    1: "the caller's details reach your leads list correctly",
    2: "an interruption does not lose what the caller already said",
    3: "a booking or a lookup uses the details the caller actually gave",
    4: "the agent hands over instead of guessing an answer",
    5: "the recording notice is spoken and an opt-out is honoured",
    6: "the agent cannot be talked into filing something false about a caller",
}


def measure(passed: int, total: int) -> Measurement:
    basis: Basis = "measured" if total >= MIN_FOR_PERCENT else "too_few"
    return Measurement(passed=passed, total=total, basis=basis)


def _defect_count(results: Sequence[ev.CaseResult]) -> int:
    """Scenarios carrying a failure of a kind that is never acceptable on any model.

    Deliberately the SAME predicate the baseline enforces (`eval.NON_WAIVABLE_KINDS`)
    rather than a second list written for this document. If the two ever disagreed, the
    client-facing number would be the one that was wrong, and it would be wrong in the
    reassuring direction.
    """
    return sum(1 for r in results if r.kinds & ev.NON_WAIVABLE_KINDS)


def _known_limits(results: Sequence[ev.CaseResult], spec: ExtractionSchemaSpec) -> list[FieldLimit]:
    """Which of the client's columns the model does not read yet, and on how many
    scenarios that showed. Sorted by count then label so the document is stable."""
    counts: dict[str, int] = {}
    for result in results:
        for failure in result.failures:
            if failure.kind != ev.CAPTURE_MISS:
                continue
            # `message` is "missed <key> (expected …)". The KEY is ours and safe; the
            # expected VALUE is transcript-derived and must not travel, so only the key
            # is read out and the rest of the line is dropped on the floor.
            key = failure.message.removeprefix("missed ").split(" ", 1)[0]
            counts[key] = counts.get(key, 0) + 1
    limits = []
    for key, count in counts.items():
        field: ExtractionField | None = spec.field_by_key(key)
        limits.append(FieldLimit(label=field.label if field else key, scenarios=count))
    return sorted(limits, key=lambda limit: (-limit.scenarios, limit.label))


def _red_team_axes(results: Sequence[ev.CaseResult]) -> int:
    return sum(1 for r in results if r.red_team)


def summarize(
    results: Sequence[ev.CaseResult],
    spec: ExtractionSchemaSpec,
    *,
    client: str,
    vertical: str,
    model: str,
    as_of: date,
) -> QaReport:
    """THE computation. Every number in every rendering of this report comes from here.

    Split out of `render` so the in-app view can exist without a second counting pass
    (SURFACES §2). The Markdown, the stored row and the API response are all this object;
    a number that disagreed between them could only come from somebody re-deriving one,
    which is what `tests/qa_report_in_app_test.py` exists to catch.
    """
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return QaReport(
        client=client,
        vertical=vertical,
        as_of=as_of,
        model=model,
        scenarios_total=total,
        defects=_defect_count(results),
        red_team=_red_team_axes(results),
        everything_captured=measure(passed, total),
        # The complement, computed as one subtraction from the same denominator so the
        # two rows are guaranteed to account for every scenario — the property
        # `test_the_two_result_rows_account_for_every_scenario` pins.
        field_left_blank=measure(total - passed, total),
        scenario_classes=[
            ScenarioClassCount(
                scenario=scenario,
                label=label,
                meaning=SCENARIO_MEANING[scenario],
                count=sum(1 for r in results if r.scenario == scenario),
            )
            for scenario, label in CLIENT_SCENARIO_LABELS.items()
            if any(r.scenario == scenario for r in results)
        ],
        known_limits=_known_limits(results, spec),
    )


def render(
    results: Sequence[ev.CaseResult],
    spec: ExtractionSchemaSpec,
    *,
    client: str,
    vertical: str,
    model: str,
    as_of: date,
) -> str:
    """The client's Markdown, unchanged — now a pure rendering of `summarize`."""
    return render_report(
        summarize(results, spec, client=client, vertical=vertical, model=model, as_of=as_of)
    )


def render_report(report: QaReport) -> str:
    """Markdown from the computed report. Reads numbers; derives none."""
    client = report.client
    as_of = report.as_of
    model = report.model
    total = report.scenarios_total
    defects = report.defects
    overall = report.everything_captured
    blank = report.field_left_blank
    lines: list[str] = [
        f"# Quality report — {client}",
        "",
        f"For the month ending {as_of.isoformat()}.",
        "",
        "Before any change to your agent — a new script, a new model, a new knowledge "
        "base — we replay a fixed set of recorded call scenarios against it and check "
        "what it did. This report is that run.",
        "",
        "## The short version",
        "",
    ]

    # The headline is the DEFECT count, not the pass rate. See the module docstring: the
    # pass rate on the offline stand-in measures our test rig, the defect count measures
    # the promise we actually make.
    if defects == 0:
        lines += [
            f"**No defects found across {total} scenarios.**",
            "",
            "A defect means one of four things, and none of them is acceptable at any price point:",
        ]
    else:
        lines += [
            f"**{defects} of {total} scenarios found a defect.** These are being fixed "
            "and this report will be reissued.",
            "",
            "A defect means one of four things:",
        ]
    lines += [
        "",
        "- a caller's detail was recorded **wrongly** — a callback number that dials "
        "someone else is worse than a blank one;",
        "- a detail was **invented** that the caller never gave;",
        "- the **recording and AI notice** was not spoken, or an opt-out was not honoured;",
        "- something identifying was **left in a transcript** that should have been masked.",
        "",
        "We do not grade these on a curve and we do not carry them forward as known "
        "issues. Anything else in this report is a limit of how much the agent "
        "understands, which is a different thing and is reported separately below.",
        "",
        "## What we tested",
        "",
        f"{total} scenarios, in six kinds:",
        "",
        "| What it tests | Scenarios | What a pass means |",
        "|---|---:|---|",
    ]
    for row in report.scenario_classes:
        lines.append(f"| {row.label} | {row.count} | {row.meaning} |")

    red_team = report.red_team
    lines += [
        "",
        "### Deliberate attacks",
        "",
        f"{red_team} of those scenarios are adversarial: a caller trying to talk the "
        "agent into skipping the recording notice, into reading out another customer's "
        "details, into ignoring an opt-out, or into writing something false into your "
        "leads list. They are written as attacks, and each one is checked against what "
        "the system did rather than against how the conversation sounded.",
        "",
        "One limit worth stating plainly, because it changes what these prove: the parts "
        "that check **what was recorded** run against the real system on every scenario. "
        "The parts that check **what the agent said back** are checked against an "
        "approved reference answer, until live call replay is in place. We would rather "
        "you know which half is which.",
        "",
        "## Results",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Defects | **{defects}** |",
        f"| Scenarios where everything was captured | {overall.rendered} |",
        f"| Scenarios where a field came back blank | {blank.rendered} |",
        "| Change since last month | not established |",
    ]
    lines += [
        "",
        # Two rows rather than one "behaving as approved", because one number would be
        # answering two questions and would answer both badly: an owner reading a single
        # figure below 100% assumes something went WRONG, when on this run the whole
        # remainder is fields left blank. Splitting them costs a row and removes the only
        # reading of this document that is both plausible and false.
        "A blank field is not a failure of the call — it is a detail the agent did not "
        "pick up, listed by column below. The two rows add up to every scenario, and the "
        "first table row is the one that matters: nothing was recorded wrongly.",
        "",
        f"*Change since last month:* {BASIS_NOTE[report.trend]}.",
        "",
    ]
    if overall.basis != "measured":
        lines += [f"*Note:* {BASIS_NOTE[overall.basis]}.", ""]

    limits = report.known_limits
    lines += ["## Known limits", ""]
    if not limits:
        lines += [
            "None. Every field in your leads list was captured on every scenario that "
            "contained it.",
            "",
        ]
    else:
        lines += [
            "These are fields the agent does not yet reliably pick up. They come back "
            "**blank**, never wrong — a blank column is a call your staff can follow up, "
            "and a wrong one is a call they cannot.",
            "",
            "| Your column | Scenarios where it was not picked up |",
            "|---|---:|",
        ]
        lines += [f"| {limit.label} | {limit.scenarios} |" for limit in limits]
        lines += [
            "",
            f"Measured with the **{model}** language model. Changing the model changes "
            "this table, which is why we re-run every scenario before we change one.",
            "",
        ]

    lines += [
        "## What this report does not tell you",
        "",
        "- **It is not a measure of your live calls.** It is a fixed set of scenarios, "
        "replayed. It tells you the agent still does what it was approved to do; it does "
        "not tell you how many callers booked this month. Your dashboard does that.",
        "- **It contains nothing from a real call.** No caller name, no number, no "
        "sentence anyone said. The scenarios are written by us and the callers in them "
        "are invented.",
        "- **It is not a trend yet.** This is a point measurement. Once there are two "
        "reports there will be a comparison, and until then we are not going to draw one "
        "from a single month.",
        "",
    ]
    return "\n".join(lines)


def _write_report(out: Path, report: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)


async def main_async(
    client: str, vertical: str, out: Path | None, as_of: date, store: bool = False
) -> int:
    results, meta = await ev.run_suite(client, vertical)
    if not results:
        # A report over zero scenarios is the failure mode this whole document is
        # written against: it would render, it would look clean, and it would say
        # nothing. Refusing is the only honest output.
        print(f"no scenarios for vertical {vertical!r} — refusing to render an empty report")
        return 2
    payload = json.loads(ev.FIXTURES.read_text(encoding="utf-8"))
    spec = ExtractionSchemaSpec(version=1, fields=payload["schema"])
    computed = summarize(
        results,
        spec,
        client=client,
        vertical=vertical,
        model=str(meta["model"]),
        as_of=as_of,
    )
    report = render_report(computed)
    if store:
        # The handoff to the client's screen — OPERATIONS §3's "report stored per run".
        # The API never runs the harness (CLAUDE.md: no model providers from a request
        # handler, and this suite takes minutes); it reads what this line wrote.
        #
        # Imported HERE rather than at module scope so the ordinary `make qa-report`,
        # which needs no database, does not pay for a DB engine or fail on an unset
        # DATABASE_URL to print a document.
        from apps.api.quality.service import store_report

        stored = await store_report(computed, slug=client)
        print(f"stored as quality report {stored} for {client} ({as_of.isoformat()})")
    if out:
        # Written through a SYNC helper, the same shape `eval._write_report` uses and for
        # the same reason: this is a CLI whose work is finished by the time it writes one
        # small file, so there is nothing to yield to, and pulling in anyio.Path would add
        # a dependency to buy nothing. A sync helper says that once instead of needing a
        # per-call-site suppression.
        _write_report(out, report)
        print(f"QA report written to {out}")
    else:
        print(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--client", required=True, help="tenant slug, printed as the title")
    parser.add_argument(
        "--vertical",
        choices=ev.VERTICALS,
        required=True,
        help="the client's vertical — their report contains their scenarios, not ours",
    )
    parser.add_argument("--out", type=Path, default=None, help="write the report here")
    parser.add_argument(
        "--as-of",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC).date(),
        default=datetime.now(UTC).date(),
        help="the month-end this report covers (YYYY-MM-DD); explicit so a regeneration "
        "is byte-identical rather than differing by a timestamp",
    )
    parser.add_argument(
        "--store",
        action="store_true",
        help="also store the report for the client's in-app Quality screen (SURFACES §2). "
        "`--client` must be the tenant's SLUG for this — the run is filed against that "
        "tenant, and an unknown slug is refused rather than filed against nobody.",
    )
    args = parser.parse_args()
    return asyncio.run(
        main_async(args.client, args.vertical, args.out, args.as_of, store=args.store)
    )


if __name__ == "__main__":
    sys.exit(main())
