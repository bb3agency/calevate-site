"""The monthly QA report, as DATA — one computation, two renderings (D-15, SURFACES §2).

`make qa-report` has existed since M3 and rendered Markdown for a human to email.
SURFACES §2 asks for the same report "rendered in-app, not just PDF", and the obvious
way to get one — a second function in `apps/api` that counts the same fixtures its own
way — is the accumulation CLAUDE.md forbids. A QA report that disagrees with itself is
worse than no QA report: it is the sales asset arguing with the dashboard in front of
the client.

So the numbers are computed ONCE, by `scripts/qa_report.summarize`, into the model
below, and everything downstream is a rendering of it:

* the CLI's Markdown (`scripts/qa_report.render`) — unchanged output, now fed from here;
* the stored row (`qa_reports.data`) written by the same CLI run;
* the API response (`GET /v1/quality/reports/...`), which is this model, revalidated
  off the stored row and never recomputed.

**The type lives in `shared` for the reason `extraction.py` gives**: `scripts` computes
it, `apps/api` serves it, the frontend reads it through the generated client. A copy in
any of the three is a fourth answer to "how many defects were there".

WHAT IS NOT IN HERE (hard rules 5 and 6)
-----------------------------------------
Nothing transcript-derived. The fields are scenario CLASS labels (ours), extraction
field LABELS (the client's own column names, which they wrote) and COUNTS. `scripts/
qa_report`'s module docstring argues this at length and `tests/eval_qa_report_test.py`
asserts it against every fixture transcript; this model is built so there is nothing to
mask, which is the stronger guarantee.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Below this many scenarios a percentage is noise dressed as a measurement. Twelve is
#: the point where one scenario moves the figure by less than ten points.
MIN_FOR_PERCENT = 12

#: Why a number is trustworthy, or why it is not. `measured` = the denominator carries
#: it; `too_few` = the count is printed and the percentage is not; `no_baseline` = there
#: is nothing to compare against, so no trend is claimed. Same doctrine as
#: `CallVolume.basis` in admin/health.py — the caveat travels WITH the number so nothing
#: downstream can render a figure without the thing that qualifies it.
Basis = Literal["measured", "too_few", "no_baseline"]


class Measurement(BaseModel):
    """A number with the reason it is trustworthy attached, or the reason it is not."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: int
    total: int
    basis: Basis

    @property
    def rendered(self) -> str:
        """The one spelling of this number, used by the Markdown AND by the screen.

        A percentage lives here rather than in either renderer: two renderers rounding
        independently is exactly how the emailed report and the in-app one end up
        one point apart, and the client reads both.
        """
        if self.basis != "measured":
            return f"{self.passed} of {self.total}"
        return f"{self.passed} of {self.total} ({round(100 * self.passed / self.total)}%)"


class ScenarioClassCount(BaseModel):
    """One of the six scenario classes, counted, in the CLIENT's vocabulary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: int
    #: What it tests, said the way a client would say it — never `eval.SCENARIO_LABELS`,
    #: which is the engineer's vocabulary.
    label: str
    #: What a pass is evidence OF. Without this the counts are trivia.
    meaning: str
    count: int


class FieldLimit(BaseModel):
    """One column of the client's leads list that the configured model does not fill.

    Named by the client's own LABEL, never our key: `budget_lakhs` is our column and
    "Budget (lakhs)" is theirs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    scenarios: int


class QaReport(BaseModel):
    """The whole report, computed once.

    `scenarios_total` = `everything_captured.total` = `field_left_blank.total` by
    construction, and the two measurements' `passed` counts add up to it: the split
    exists because one number would answer two questions and answer both badly (see
    `scripts/qa_report.render`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Schema version of THIS model. Stored beside the data so a reader can refuse a row
    #: it does not understand rather than silently mis-render an old shape.
    version: Literal[1] = 1

    client: str
    vertical: str
    #: The month-end this report covers. Explicit rather than `now()` so a regeneration
    #: is byte-identical instead of differing by a timestamp.
    as_of: date
    #: The extraction model the scenarios ran against. Changing it changes the limits
    #: table, which is why it is printed beside it.
    model: str

    scenarios_total: int
    #: The headline. A wrong value filed, a value invented, a disclosure missed, PII left
    #: in a transcript — never acceptable on any model, and zero is the only acceptable
    #: number. NOT the pass rate: see `scripts/qa_report`'s docstring for why printing
    #: the raw pass rate would be an UNDERclaim rather than an honest one.
    defects: int
    #: How many of the scenarios are written as attacks.
    red_team: int

    everything_captured: Measurement
    field_left_blank: Measurement
    #: Always `no_baseline` today — there is one report, so there is no last month. It is
    #: a field rather than a constant because the moment a second month exists this is
    #: the number that changes, and a renderer that hard-coded "not established" would
    #: keep saying it.
    trend: Basis = "no_baseline"

    scenario_classes: list[ScenarioClassCount] = Field(default_factory=list)
    known_limits: list[FieldLimit] = Field(default_factory=list)


__all__ = [
    "MIN_FOR_PERCENT",
    "Basis",
    "FieldLimit",
    "Measurement",
    "QaReport",
    "ScenarioClassCount",
]
