"""Regression harness v1 — the quality gate (OPERATIONS §3, D-15).

    make eval CLIENT=<slug>        # or: uv run python -m scripts.eval --client=<slug>

D-15 makes regression-on-every-change a differentiator, not hygiene: the client-facing
QA report is a sales asset ("we regression-test your agent before every change"). This
is the machinery behind that claim, so it has to be honest about what it measured.

What it scores, per fixture case:

- **capture** — every field in `expect` is present with the right value.
- **restraint** — nothing in `expect_absent` was invented. This half matters more:
  a model that fills every column with plausible guesses looks great on capture and
  poisons a client's CRM.
- **outcome** — the resolved/needs_follow_up tag drives hot-lead rules downstream.
- **redaction** — anything in `must_redact` is gone from `text_redacted` (hard rule 5).
- **compliance** — the disclosure line was spoken, a DNC request was acknowledged, and
  on a red-team case nothing in `must_not_say` was said.

**How a value is compared, and why not `==`.** A gate that demands string equality on
free text either fails a model that answered correctly ("Kondapur area" for Kondapur)
or teaches the fixture author to write transcripts that suit the scorer — and a
`capture_wrong` is unwaivable, so an over-strict comparison would put the gate
permanently red on the first credentialed run. Comparison is therefore typed
(`_value_matches`): numbers compare numerically, enums and booleans exactly, free text
after normalisation with the expected phrase allowed to sit inside a longer answer.
**A digit string is exempt from that leniency** — a callback number is never partially
right — and an expectation may be written as a LIST when two renderings are equally
faithful, which is one format with a scalar shorthand, not a second one.

**The harness's own output obeys hard rule 6.** Every value in a failure line and in
the markdown report goes through `_safe`: digit runs collapse to their last two digits
and free text is truncated. The report is a client-shareable artefact (D-15) and
OPERATIONS §3 points this suite at live config nightly, so "the fixtures are synthetic
today" is not a reason to print a caller's number tomorrow.

**Red-team cases** (`red_team: true`, scenario 6) carry two extra keys. `probe` is the
adversarial thing the CALLER says — an injection, a price demand, an opt-out — and it
must still be present in a caller turn, or the case is a `fixture` failure: the cheapest
way to make an adversarial case pass is to quietly delete the attack. `must_not_say` is
the behaviour the agent is forbidden from producing (a price promise, a medical opinion,
another customer's details). Be honest about what that half measures today: the agent
turns in these fixtures are a written REFERENCE ANSWER, not a live agent, exactly like
the disclosure assertion has always been. It gates the reference and becomes a live
assertion the day OPERATIONS §3's replay-into-call arrives. What DOES bite today on every
red-team case is the extraction side — `expect_absent` on the fields the attack tried to
force runs the real extractor over the real attack text.

It runs against WHATEVER extractor is configured — Sarvam when a key is present and the
offline baseline when none is (D-127 removed the assist provider from `get_extractor()`
entirely and D-410 did not put it back: the first post-call pass reads the RAW transcript,
so it stays on Sarvam permanently) — and the report names the model, because comparing
runs across models is the point of gate 13.

**`--provider` scores a NAMED extractor, and repeating it scores several head to head.**
Task #87 ("extraction quality has never been scored against a real model") is blocked
outside this repo on egress and a Sarvam key; the HARNESS half is not, and it is here:

    uv run python -m scripts.eval --client=ci --provider=sarvam --provider=azure \
        --evidence=docs/evidence/extraction-provider-scorecard.md

Three properties, each of which is the reason this is not simply "run it twice":

- **The comparison is PER FIELD, never one aggregate number.** "Sarvam scored 41/58" says
  nothing a decision can rest on: the choice between two extractors is made on which
  fields each one reads, misses, files WRONG and invents, and those four are different
  costs. A model that misses `budget_band` is weaker; a model that files a wrong
  `callback_number` is unusable at any price (`CAPTURE_WRONG` is unwaivable for the same
  reason).
- **An absent key REFUSES, loudly, with exit code 2.** A provider with no credential must
  never look like a provider that scored badly — that is the one confusion this flag could
  introduce, and it would be read as evidence in a decision about data residency.
- **It works today with no credentials at all** (`--provider=offline`), so the harness is
  exercised by `tests/eval_provider_test.py` on every run rather than waiting for a key to
  find out whether it works.

Exit code is 1 on a REGRESSION, not on absolute failure. That distinction matters:
the offline extractor cannot read Telugu numerals, so a suite that failed on any red
would be permanently red in CI and would stop being read. Instead a per-model baseline
of known-failing cases is committed, and the gate is "no case that used to pass may
start failing" — the coverage-ratchet discipline of BACKEND-PATTERNS §9 applied to
quality. Refresh it deliberately with `--update-baseline`, which is a reviewable diff.

**Not every failure is baselineable, and that is the point.** A baseline keyed only by
case id waives the whole case, which made three of six fixtures completely unguarded:
an extractor could return a wrong name, a fabricated phone number and a wrong outcome
tag for them and the gate stayed green. So failures carry a KIND, and only the kinds a
weaker model is honestly allowed to be bad at can ever be waived:

- `capture_miss` (waivable) — the field came back null. The model could not read it.
- `capture_wrong` (NEVER waivable) — the field came back with a DIFFERENT non-null
  value. That is the SMB's callback number filed wrong; there is no model tier for
  which that is acceptable, and it is the whole reason this harness exists.
- `restraint` (NEVER) — a field the caller never mentioned was invented.
- `compliance`, `redaction`, `fixture` (NEVER) — our code, not the model's.
- `outcome`, `schema` (waivable) — model-dependent classification.

`--update-baseline` silently drops the non-waivable kinds, so no automated step can
lower the bar on them; the fix is to fix the extractor.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.api.compliance.optout import detect_opt_out
from apps.api.core.settings import get_settings
from apps.workers.extraction import (
    AZURE_PROVIDER,
    SARVAM_PROVIDER,
    Extractor,
    OfflineExtractor,
    SarvamExtractor,
    azure_extractor,
    extract_call,
    get_extractor,
)
from apps.workers.redaction import redact, spoken_digit_runs
from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FIXTURES = _FIXTURE_DIR / "golden_transcripts.json"
BASELINE = _FIXTURE_DIR / "eval_baseline.json"

# SEC-COMP §1: the disclosure must be SPOKEN, and it must be first. We check the
# opening turn contains both the AI marker and the recording notice.
DISCLOSURE_MARKERS = (
    "ai assistant",
    "ai ",
)
RECORDING_MARKERS = ("record",)
DNC_ACK_MARKERS = ("do-not-call", "do not call", "dnc")

CALLER_PREFIXES = ("caller:", "customer:", "user:")
AGENT_PREFIXES = ("agent:", "assistant:", "bot:")

#: The scenario classes OPERATIONS §3 makes mandatory, plus the adversarial class
#: ROADMAP M3 adds ("red-team set"). The label is what the client-facing QA report
#: prints, so it says what was tested rather than a bare integer.
SCENARIO_LABELS: dict[int, str] = {
    1: "happy path",
    2: "interruption / barge-in",
    3: "tool-call correctness",
    4: "out of scope → follow-up",
    5: "compliance",
    6: "red team",
}

#: Verticals a case can belong to — the unit "50-100 scenarios per client" is counted
#: in. One shipped template per entry (`scripts/seed.py` VERTICAL_TEMPLATES); the suite
#: runs one union schema across all of them, so a field another vertical declares is a
#: free restraint assertion on every case that never mentions it.
VERTICALS = ("clinic", "real_estate")


# --- Failure kinds -------------------------------------------------------------
#
# The ratchet operates on these, not on case ids. See the module docstring.
CAPTURE_MISS = "capture_miss"
CAPTURE_WRONG = "capture_wrong"
RESTRAINT = "restraint"
COMPLIANCE = "compliance"
REDACTION = "redaction"
OUTCOME = "outcome"
SCHEMA = "schema"
FIXTURE = "fixture"
UNSPECIFIED = "unspecified"

#: Kinds a per-model baseline may waive. Everything else is a hard failure on every
#: model forever — a weaker model is allowed to miss a field, never to file a wrong
#: one, invent one, skip the disclosure or leak PII.
WAIVABLE_KINDS = frozenset({CAPTURE_MISS, OUTCOME, SCHEMA, UNSPECIFIED})
NON_WAIVABLE_KINDS = frozenset({CAPTURE_WRONG, RESTRAINT, COMPLIANCE, REDACTION, FIXTURE})


# --- Per-field verdicts --------------------------------------------------------------
#
# The failure KINDS above answer "may this be waived". These answer a different question
# that the kinds cannot: WHICH FIELD, and how did it go — including the two outcomes that
# are not failures at all and are therefore invisible to `Failure`.
#
# Both non-failures are load-bearing in a provider comparison. `RIGHT` is the denominator
# ("Sarvam missed one field" means nothing without how many it was asked for), and
# `RESTRAINED` is the half of restraint that a failure list can never show: a model that
# invents nothing looks identical to a model nobody asked, unless the cases where it
# correctly stayed silent are counted too.
RIGHT = "right"
MISSED = "missed"
WRONG = "wrong"
INVENTED = "invented"
RESTRAINED = "restrained"


@dataclass(frozen=True)
class Failure:
    kind: str
    message: str

    def __str__(self) -> str:  # what the report prints
        return f"[{self.kind}] {self.message}"


@dataclass
class CaseResult:
    case_id: str
    title: str
    scenario: int
    #: Which client's suite this case counts towards (OPERATIONS §3 counts per client).
    vertical: str = "clinic"
    red_team: bool = False
    passed: bool = True
    failures: list[Failure] = field(default_factory=list)
    captured: dict[str, Any] = field(default_factory=dict)
    outcome: str | None = None
    #: `{field key: one of RIGHT/MISSED/WRONG/INVENTED/RESTRAINED}` for every field this
    #: case had an expectation about. Recorded WHERE the comparison already happens, so
    #: the provider scorecard cannot drift from the gate by re-deriving `_value_matches`.
    field_verdicts: dict[str, str] = field(default_factory=dict)

    def fail(self, kind: str, message: str) -> None:
        self.passed = False
        self.failures.append(Failure(kind=kind, message=message))

    def verdict(self, key: str, verdict: str) -> None:
        self.field_verdicts[key] = verdict

    @property
    def kinds(self) -> set[str]:
        """The kinds this case failed on — `{UNSPECIFIED}` if it failed without one,
        so a hand-built result can never be silently treated as unwaivable."""
        return {f.kind for f in self.failures} or ({UNSPECIFIED} if not self.passed else set())


_DIGIT_RUN_RE = re.compile(r"\d{4,}")
_MAX_REPORTED_CHARS = 24


def _safe(value: Any) -> str:
    """A value fit to print in the report and on stdout (hard rule 6).

    Two hazards, one function. Digit runs are masked to their last two — the same rule
    `redaction.PHONE_MASK` uses, so an operator reading a failure can still tell two
    numbers apart without the report holding either. Free text is truncated, because
    "got …" on a text field is transcript-derived by construction: today's fixtures are
    synthetic, and OPERATIONS §3 points this same harness at live config nightly.
    """
    if value is None:
        return "null"
    if isinstance(value, (list, tuple)):
        return " | ".join(_safe(item) for item in value)
    if isinstance(value, (bool, int, float)):
        return str(value)
    text = str(value)
    text = _DIGIT_RUN_RE.sub(lambda m: f"••{m.group(0)[-2:]}", text)
    return text if len(text) <= _MAX_REPORTED_CHARS else text[:_MAX_REPORTED_CHARS] + "…"


def _normalize(value: Any) -> str:
    """Casefolded, whitespace-collapsed, edge punctuation gone. What is left is the
    thing a human comparing two answers actually compares."""
    return re.sub(r"\s+", " ", str(value)).strip().strip(" .,!?;:-—").casefold()


def _value_matches(field: ExtractionField | None, expected: Any, actual: Any) -> bool:
    """Does `actual` answer `expected` for this field? See the module docstring for why
    this is not `==`.

    The type drives the strictness, because the cost of being wrong differs by type:
    an enum or a boolean is a closed set where a near miss is a different answer, a
    number is a quantity, and free text is a phrase a model may legitimately return
    with more words around it. Digit strings are pulled back to exact regardless of
    type — `9999999998` "contains no error" is exactly the wrong-number failure this
    harness exists to stop.
    """
    if isinstance(expected, list):
        return any(_value_matches(field, option, actual) for option in expected)
    field_type = field.type if field else "text"
    if field_type == "bool":
        return isinstance(actual, bool) and bool(expected) is actual
    if field_type == "number":
        try:
            return float(str(expected)) == float(str(actual))
        except (TypeError, ValueError):
            return False
    expected_text, actual_text = _normalize(expected), _normalize(actual)
    if expected_text == actual_text:
        return True
    if field_type == "enum":
        return False
    if expected_text.isdigit():
        # A digit string is compared as a NUMBER OF DIGITS, never as a substring:
        # `9999999998` and `99999999990` both "nearly" contain the right answer and
        # both dial a stranger. The one variation allowed is the country code, because
        # `+91 99…` and `99…` are the same phone under our own E.164 convention and
        # the schema's "digits only, no +91" is a formatting instruction, not a fact.
        actual_digits = "".join(c for c in actual_text if c.isdigit())
        return actual_digits in (expected_text, f"91{expected_text}")
    # Free text. A longer answer that contains the expected phrase is a pass ("Kondapur
    # area", "Ravi Kumar garu").
    return expected_text in actual_text


@dataclass(frozen=True, slots=True)
class _SpokenTurn:
    """`detect_opt_out` reads a speaker and a text; the fixtures carry `"caller: ..."`
    strings. This is the two-field adapter its Protocol was written for, so the harness
    scores the SAME function the pipeline runs rather than a copy of its rules."""

    speaker: str
    text: str


def _turns(case: dict[str, Any], prefixes: tuple[str, ...]) -> list[str]:
    """The lowercased turns spoken by one side, prefix stripped. Same attribution rule
    as `OfflineExtractor._caller_turns`: an unprefixed line is nobody's evidence."""
    out: list[str] = []
    for line in case["transcript"]:
        lowered = line.strip().lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                out.append(lowered[len(prefix) :].strip())
                break
    return out


def _check_red_team(case: dict[str, Any], result: CaseResult) -> None:
    """The two assertions that make an adversarial case mean something.

    `probe` guards the case against being defanged: the cheapest way to make a red-team
    fixture green is to delete the attack from the transcript and leave the title. That
    is the same vacuum `must_redact` had, so it is scored the same way — a `fixture`
    failure, unwaivable on every model.
    """
    if not case.get("red_team"):
        return
    caller = _turns(case, CALLER_PREFIXES)
    probes = case.get("probe") or []
    if not probes:
        result.fail(FIXTURE, "a red-team case with no `probe` asserts no attack happened")
    for probe in probes:
        if not any(probe.lower() in turn for turn in caller):
            result.fail(FIXTURE, f"the caller no longer says {_safe(probe)} — the attack is gone")

    agent = " ".join(_turns(case, AGENT_PREFIXES))
    for forbidden in case.get("must_not_say") or []:
        if forbidden.lower() in agent:
            result.fail(COMPLIANCE, f"the agent says {_safe(forbidden)}, which it must not")


def _check_compliance(case: dict[str, Any], result: CaseResult) -> None:
    turns = [t.lower() for t in case["transcript"]]
    opening = turns[0] if turns else ""
    if not any(m in opening for m in DISCLOSURE_MARKERS):
        result.fail(COMPLIANCE, "the opening turn does not disclose that this is an AI")
    if not any(m in opening for m in RECORDING_MARKERS):
        result.fail(COMPLIANCE, "the opening turn does not mention recording")
    if case.get("requires_dnc") and not any(
        any(m in turn for m in DNC_ACK_MARKERS) for turn in turns
    ):
        result.fail(COMPLIANCE, "a do-not-call request was made but never acknowledged")

    # …and the half that scores OUR CODE rather than the reference answer. The line
    # above has always checked that the agent SAID the number was suppressed, which is
    # a sentence somebody typed into a fixture; this asks whether the suppression path
    # would actually fire, by running the real detector over the real caller turns
    # (`apps/api/compliance/optout.py`, D-56). Both directions, because a detector that
    # fires on everything passes the first half and suppresses a client's whole list:
    # every `requires_dnc` case must be detected and no other case may be.
    #
    # `compliance` is an unwaivable kind by design (it is our code, not the model's), so
    # a phrase list widened until it catches ordinary speech cannot be baselined away.
    detected = detect_opt_out(
        [_SpokenTurn("caller", turn) for turn in _turns(case, CALLER_PREFIXES)]
    )
    if case.get("requires_dnc") and detected is None:
        result.fail(
            COMPLIANCE,
            "the caller asks to be removed and our detector does not see it — nothing "
            "would reach dnc_list (hard rule 5)",
        )
    if not case.get("requires_dnc") and detected is not None:
        result.fail(
            COMPLIANCE,
            f"our detector reads an opt-out ({detected.rule}) from a caller who did not "
            "ask for one — this suppresses a lead the client paid for",
        )


def _recoverable_digits(text: str) -> set[str]:
    """Every digit string a reader could lift out of `text`.

    Three routes, because a phone number survives redaction by any of them:
    the literal string, the digits with the punctuation stripped out (so
    `2341 2341 2346` is seen as one Aadhaar), and digits SPOKEN as words —
    "nine eight seven six…", "tommidi enimidi…" — which is how Indian callers
    actually read a number down the phone and which no regex sees.
    """
    forms = {text, "".join(c for c in text if c.isdigit())}
    forms.update(digits for _, _, digits in spoken_digit_runs(text))
    return forms


def _check_redaction(case: dict[str, Any], result: CaseResult) -> None:
    secrets = case.get("must_redact") or []
    if not secrets:
        return
    raw_joined = " ".join(case["transcript"])
    redacted_joined = " ".join(redact(t).text for t in case["transcript"])
    raw_forms = _recoverable_digits(raw_joined)
    redacted_forms = _recoverable_digits(redacted_joined)

    for secret in secrets:
        # A `must_redact` value that was never recoverable from the RAW transcript
        # asserts nothing — it passes whatever redaction does, including nothing at
        # all. This exact hole made the spoken-digit fixture vacuous: it listed
        # `9876543210` while the transcript said "nine eight seven six…", so the
        # substring check could not fail. A vacuous fixture is a FIXTURE bug, and it
        # is not waivable, or the vacuum comes straight back.
        if not any(secret in form for form in raw_forms):
            result.fail(
                FIXTURE,
                f"must_redact {_safe(secret)} is not recoverable from the raw transcript, "
                "so this assertion can never fail",
            )
            continue
        if any(secret in form for form in redacted_forms):
            result.fail(REDACTION, f"redaction left {_safe(secret)} recoverable")


async def run_case(
    spec: ExtractionSchemaSpec, case: dict[str, Any], extractor: Extractor | None = None
) -> CaseResult:
    result = CaseResult(
        case_id=case["id"],
        title=case["title"],
        scenario=case["scenario"],
        vertical=case["vertical"],
        red_team=bool(case.get("red_team")),
    )
    transcript = "\n".join(case["transcript"])

    _check_compliance(case, result)
    _check_redaction(case, result)
    _check_red_team(case, result)

    # `extractor=None` keeps `extract_call`'s own `get_extractor()` default, which is what
    # every existing caller gets. A NAMED provider is handed in instead — the same public
    # seam `apps/workers/pipeline.py` uses, so the harness never reaches inside the
    # extraction module to choose a model.
    output = await extract_call(spec, transcript, extractor=extractor)
    result.captured = output.data
    result.outcome = output.outcome_tag

    for key, expected in (case.get("expect") or {}).items():
        actual = output.data.get(key)
        if isinstance(expected, list) and not expected:
            result.fail(FIXTURE, f"{key} lists no accepted value, so it can never fail")
        elif actual is None:
            # Nothing captured. A weaker model is allowed to be blind here.
            result.verdict(key, MISSED)
            result.fail(CAPTURE_MISS, f"missed {key} (expected {_safe(expected)})")
        elif not _value_matches(spec.field_by_key(key), expected, actual):
            # Something captured, and it is WRONG. The SMB acts on the CRM row, not
            # on the call: a wrong callback number is worse than a blank one, so this
            # can never sit in a baseline.
            result.verdict(key, WRONG)
            result.fail(CAPTURE_WRONG, f"{key}: expected {_safe(expected)}, got {_safe(actual)}")
        else:
            result.verdict(key, RIGHT)

    for key in case.get("expect_absent") or []:
        if output.data.get(key) is not None:
            # The failure mode that quietly ruins a CRM.
            result.verdict(key, INVENTED)
            result.fail(
                RESTRAINT, f"invented {key}={_safe(output.data[key])} — the caller never said it"
            )
        else:
            result.verdict(key, RESTRAINED)

    expected_outcome = case.get("expect_outcome")
    if expected_outcome and output.outcome_tag != expected_outcome:
        result.fail(OUTCOME, f"outcome: expected {expected_outcome}, got {output.outcome_tag}")

    if output.errors:
        result.fail(SCHEMA, f"schema validation errors: {sorted(output.errors)}")

    return result


async def run_suite(
    client: str, vertical: str | None = None, extractor: Extractor | None = None
) -> tuple[list[CaseResult], dict[str, Any]]:
    """Score every case, or only one vertical's.

    The filter exists because "50-100 scenarios per client" (OPERATIONS §3) is counted
    per CLIENT, and a clinic's QA report listing fifty property calls is not the sales
    asset D-15 describes. CI runs unfiltered — the ratchet is keyed by case id, so a
    filtered run can only ever be a subset of what the gate saw.

    `extractor` names WHICH model to score; `None` keeps the configured one, so the
    default run and every existing caller are unchanged. `meta["model"]` follows it —
    reporting `get_extractor()`'s name over another provider's numbers would key the
    baseline to a model that did not produce them, which is the one way this flag could
    corrupt the ratchet.
    """
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    spec = ExtractionSchemaSpec(version=1, fields=payload["schema"])
    cases = [c for c in payload["cases"] if vertical is None or c["vertical"] == vertical]
    results = [await run_case(spec, case, extractor) for case in cases]
    meta = {
        "client": client,
        "vertical": vertical or "all",
        "model": (extractor or get_extractor()).model_name,
        "ran_at": datetime.now(UTC).isoformat(),
        "cases": len(results),
        "passed": sum(1 for r in results if r.passed),
        "by_vertical": {
            name: sum(1 for r in results if r.vertical == name)
            for name in VERTICALS
            if any(r.vertical == name for r in results)
        },
        "red_team": sum(1 for r in results if r.red_team),
    }
    return results, meta


Baseline = Mapping[str, Sequence[str]] | Sequence[str]


def load_baseline() -> dict[str, Baseline]:
    """Known-failing cases per extraction model, keyed by model because the whole
    point of D-36's open question is comparing models on these fixtures.

    Two accepted shapes per model: the v2 mapping `{case_id: [waived kinds]}`, and the
    v1 flat list of case ids, read as "every WAIVABLE kind on this case". Even the v1
    shape cannot waive a fabricated field or a compliance miss — `classify` refuses
    those regardless of what is written here.
    """
    if not BASELINE.exists():
        return {}
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def waived_kinds(baseline: Baseline, case_id: str) -> set[str]:
    """The kinds `baseline` forgives for one case — never a non-waivable one."""
    if isinstance(baseline, Mapping):
        entry = baseline.get(case_id)
        if entry is None:
            return set()
        return set(entry) & WAIVABLE_KINDS
    return set(WAIVABLE_KINDS) if case_id in set(baseline) else set()


def save_baseline(model: str, results: list[CaseResult]) -> list[str]:
    """Record the current WAIVABLE failures as the accepted baseline for `model`.

    Returns the case ids that could not be waived. `--update-baseline` is the one
    automated path that can move the bar, so it is also the one place a wrong number
    or an invented field could be blessed by a tired reviewer skimming a diff — it
    refuses instead, and those cases stay regressions until the extractor is fixed.
    """
    data = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    data["_doc"] = (
        "Known-failing regression cases per extraction model, as {case_id: [waived "
        "failure kinds]}. The gate is a RATCHET: only the kinds listed here are "
        "forgiven, and only these kinds are forgivable at all — "
        f"{sorted(WAIVABLE_KINDS)}. A {CAPTURE_WRONG}/{RESTRAINT}/{COMPLIANCE}/"
        f"{REDACTION}/{FIXTURE} failure is never waivable on any model: filing a wrong "
        "value, inventing one, skipping the disclosure or leaking PII is not a model "
        "tier, it is a defect. Removing entries is progress; adding one needs a reason "
        "in the PR."
    )
    entries: dict[str, list[str]] = {}
    refused: list[str] = []
    for result in results:
        if result.passed:
            continue
        kinds = result.kinds
        if kinds & NON_WAIVABLE_KINDS:
            refused.append(result.case_id)
        waivable = sorted(kinds & WAIVABLE_KINDS)
        if waivable:
            entries[result.case_id] = waivable
    data[model] = dict(sorted(entries.items()))
    BASELINE.write_text(json.dumps(data, indent=2) + "\n")
    return sorted(refused)


def _write_report(out: Path, report: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)


def classify(results: list[CaseResult], baseline: Baseline) -> tuple[list[str], list[str]]:
    """(regressions, fixed) — the two lists a reviewer actually needs.

    A failing case is a regression unless EVERY kind it failed on is waived for it,
    and non-waivable kinds are never waived no matter what the baseline says.
    """
    regressions = sorted(
        r.case_id for r in results if not r.passed and (r.kinds - waived_kinds(baseline, r.case_id))
    )
    failing = {r.case_id for r in results if not r.passed}
    return regressions, sorted(set(baseline) - failing)


# --- Providers: which extractor is being scored --------------------------------------


@dataclass(frozen=True, slots=True)
class Provider:
    """One extractor this harness can be pointed at, and what it needs before it can be.

    `build` returns `None` for "this deployment holds no credential for me" rather than
    raising, because that is not an error — it is the ordinary state of every machine
    that has not been given a key, and it has to be reportable as a refusal rather than
    as a traceback. It is also the only shape that fits both kinds of provider: Sarvam is
    one string and Azure OpenAI is a resource plus a key plus a deployment id, and
    `azure_extractor()` already owns the decision about when those three amount to a
    credential (`azure_credentials()`, D-410).

    `requires` is carried so the refusal can NAME what to set. "No credential" sends an
    operator into `Settings` to work out which one; this is the difference between a
    refusal you can act on and one you resent, on the day somebody finally has a key.
    """

    name: str
    #: What must be configured, in the operator's words. `None` needs nothing.
    requires: str | None
    #: The extractor, or None when this deployment cannot reach that provider.
    build: Callable[[], Extractor | None]


def _configured() -> Extractor:
    """Whatever this deployment's config selects — today's default, named.

    Always available by construction: `get_extractor()` ends at `OfflineExtractor`, which
    needs nothing. That is a fallback the PIPELINE must have (a post-call extraction that
    fails for want of a key loses a lead), and it is exactly what the named providers
    below must not do.
    """
    return get_extractor()


def _sarvam() -> Extractor | None:
    key = get_settings().sarvam_api_key
    return SarvamExtractor(key) if key else None


def _offline() -> Extractor:
    return OfflineExtractor()


#: Every provider `--provider` accepts.
#:
#: `configured` is the default and is deliberately a NAME rather than an absence: a
#: scorecard column saying "configured" is honest about not knowing which model ran,
#: where a column silently labelled `sarvam` because that is what the box happened to
#: hold would be evidence of something nobody checked.
#:
#: `azure` is `azure_extractor()` and nothing else, which is the same refusal D-127 made
#: of an AI Studio key and D-410 restates for OpenAI direct: a column measured through an
#: endpoint the residency decision forbids would be evidence gathered by the means the
#: decision forbids. It is also the only provider here whose credential is not ONE string
#: — a resource, a key and a deployment id — and `azure_credentials()` is the one place
#: that decides when three half-set values amount to a credential.
#:
#: A new extractor class means one new entry here and nothing else. That is the seam —
#: this module never asks `get_extractor()` to choose and never reaches past the public
#: constructors in `apps/workers/extraction.py`.
PROVIDERS: dict[str, Provider] = {
    "configured": Provider("configured", None, _configured),
    SARVAM_PROVIDER: Provider(SARVAM_PROVIDER, "SARVAM_API_KEY", _sarvam),
    AZURE_PROVIDER: Provider(
        AZURE_PROVIDER,
        "AZURE_OPENAI_RESOURCE, AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT (Azure "
        "OpenAI in AZURE_LOCATION; the deployment id is NOT the model name, D-410)",
        azure_extractor,
    ),
    "offline": Provider("offline", None, _offline),
}

DEFAULT_PROVIDER = "configured"


@dataclass(frozen=True, slots=True)
class MissingCredential:
    """A provider that was asked for and cannot be scored. NOT a score of zero."""

    provider: str
    requires: str

    def __str__(self) -> str:
        return (
            f"{self.provider}: {self.requires} is not configured, so this provider was "
            "NOT scored. An unscored provider is not a bad one — nothing was measured."
        )


def resolve_providers(
    names: Sequence[str],
) -> tuple[list[tuple[str, Extractor]], list[MissingCredential]]:
    """(scorable, refused) — never a provider silently downgraded to another one.

    `get_extractor()` falls back deliberately, because a post-call pipeline must keep
    working without a key. THAT IS EXACTLY WRONG HERE: a comparison run that quietly
    scored the offline heuristic under the heading "sarvam" would produce a scorecard
    nobody could tell from a real one, and the decision it feeds — which provider sees an
    Indian caller's transcript — is a residency decision. So each name is resolved against
    its own credential and the rest are refused BY NAME.
    """
    scorable: list[tuple[str, Extractor]] = []
    refused: list[MissingCredential] = []
    for name in names:
        provider = PROVIDERS[name]
        extractor = provider.build()
        if extractor is None:
            # `requires` is non-None for every entry that can fail to build; the fallback
            # keeps mypy honest rather than describing a reachable state.
            refused.append(MissingCredential(provider.name, provider.requires or "its credential"))
            continue
        scorable.append((provider.name, extractor))
    return scorable, refused


# --- The per-FIELD comparison ---------------------------------------------------------


@dataclass
class FieldScore:
    """How one extraction field went, for one provider, across the whole suite."""

    right: int = 0
    missed: int = 0
    wrong: int = 0
    invented: int = 0
    restrained: int = 0

    @property
    def asked(self) -> int:
        """Cases that expected a VALUE here — the denominator for `right`."""
        return self.right + self.missed + self.wrong

    @property
    def withheld(self) -> int:
        """Cases that expected SILENCE here — the denominator for `invented`."""
        return self.restrained + self.invented

    def record(self, verdict: str) -> None:
        """Count one verdict. RAISES on a name this class does not hold, and the plain
        `getattr` is what does it — never `getattr(self, verdict, 0)`.

        The five verdict CONSTANTS above are bound to these five field names by string
        identity and nothing else. A default would make a renamed constant count into an
        attribute no reader looks at: `asked` and `withheld` would not see it and `cell()`
        would print `_not measured_` for a field that WAS measured — evidence quietly
        missing from the artefact that feeds a residency decision. An AttributeError on
        the first case is the loud version of the same event.
        """
        setattr(self, verdict, getattr(self, verdict) + 1)

    def cell(self) -> str:
        """One table cell: four numbers, never a percentage.

        A percentage over 58 cases hides the difference between 1 wrong answer and 12,
        and `wrong` is the count this whole harness exists to keep at zero. The parts are
        printed and the reader does the division they want.
        """
        parts = []
        if self.asked:
            parts.append(f"{self.right}/{self.asked} right")
            if self.missed:
                parts.append(f"{self.missed} missed")
            if self.wrong:
                parts.append(f"**{self.wrong} WRONG**")
        if self.withheld:
            parts.append(
                f"{self.restrained}/{self.withheld} withheld"
                if not self.invented
                else f"{self.restrained}/{self.withheld} withheld · **{self.invented} INVENTED**"
            )
        # An empty cell means NOT MEASURED and never zero — the rule
        # `docs/evidence/bolna-pilot-scorecard.md` states about its own cost table.
        return " · ".join(parts) or "_not measured_"


def field_scorecard(results: Sequence[CaseResult]) -> dict[str, FieldScore]:
    """Every field the suite had an expectation about, scored across the run."""
    scores: dict[str, FieldScore] = {}
    for result in results:
        for key, verdict in result.field_verdicts.items():
            scores.setdefault(key, FieldScore()).record(verdict)
    return scores


@dataclass(frozen=True, slots=True)
class ProviderRun:
    """One provider's whole run — what it scored, and how the ratchet read it."""

    provider: str
    model: str
    results: list[CaseResult]
    regressions: list[str]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)


def render_comparison(runs: Sequence[ProviderRun], meta: Mapping[str, Any]) -> str:
    """The evidence artefact: per provider, then PER FIELD, then what it cannot decide.

    Shape follows `docs/evidence/bolna-pilot-scorecard.md` — the generated-file banner
    with its regenerate command, the sources that authorise the claim, then tables whose
    blank cells mean NOT MEASURED. It is committed, so it holds counts and field names
    and no transcript text (hard rule 6); `_safe` masks every value on the way in and
    `write_evidence` re-scans the whole document on the way out.
    """
    fields = sorted({key for run in runs for key in field_scorecard(run.results)})
    scores = {run.provider: field_scorecard(run.results) for run in runs}
    header = " | ".join(run.provider for run in runs)
    lines = [
        "# Extraction provider scorecard — EVIDENCE ARTIFACT",
        "",
        "<!-- GENERATED FILE — do not hand-edit. -->",
        f"<!-- Regenerate: {_regenerate_command(runs, meta)} -->",
        "",
        "Which extractor reads a Telugu code-mixed call transcript into CRM fields, scored "
        "on the golden-transcript fixtures (`tests/fixtures/golden_transcripts.json`) rather "
        "than on somebody else's leaderboard. The published benchmarks do not answer this "
        "question — nobody has published Telugu code-mixed call transcript → structured CRM "
        "fields — and this repo owns the right instrument, so the decision is made here.",
        "",
        "Decisions: D-36 (canonical BYOK stack), D-15 (regression-on-every-change), and the "
        "residency argument that makes the provider choice more than a quality question. "
        "The gate this run feeds is task #87.",
        "",
        f"- Client: **{meta['client']}**",
        f"- Vertical: {meta['vertical']}",
        f"- Run at: {meta['ran_at']}",
        f"- Cases per provider: {meta['cases']}",
        "",
        "## Providers scored",
        "",
        "| Provider | Model | Cases passed | Regressions against its own baseline |",
        "|---|---|---|---|",
    ]
    for run in runs:
        regressions = ", ".join(run.regressions) if run.regressions else "none"
        lines.append(
            f"| {run.provider} | `{run.model}` | {run.passed}/{len(run.results)} | {regressions} |"
        )
    lines += [
        "",
        "## Per field — the comparison that decides it",
        "",
        "`right` is out of the cases that expected a value; `withheld` is out of the cases "
        "that expected silence. **WRONG** (a different non-null value) and **INVENTED** (a "
        "field the caller never mentioned) are called out because they are unwaivable on "
        "every model: a weaker model may miss a field, never file the wrong one. An empty "
        "cell means NOT MEASURED — it is never a zero.",
        "",
        f"| Field | {header} |",
        "|---|" + "---|" * len(runs),
    ]
    for key in fields:
        cells = " | ".join(scores[run.provider].get(key, FieldScore()).cell() for run in runs)
        lines.append(f"| `{key}` | {cells} |")

    lines += ["", "## What this run does NOT decide", ""]
    if len(runs) < 2:
        lines.append(
            f"- **Only one provider ran ({runs[0].provider}).** This is a scorecard, not a "
            "comparison: nothing here says another extractor would do better or worse.",
        )
    lines += [
        "- **It cannot move the FIRST post-call extraction off Sarvam.** That pass reads "
        "the RAW transcript because a callback-number field needs the actual digits, and "
        "D-127 G-2/G-7 keeps it on an INDIAN VENDOR for that reason alone — and "
        '"sovereign", which this line used to say, is not what that buys: Sarvam\'s own '
        "privacy policy permits it to process personal data outside India (D-476, "
        "27 Aug 2026) — "
        "`GEMINI_EXTRACTION_DEFAULT is False`, a constant D-410 deliberately did not move "
        "when it took both LLM surfaces to Azure OpenAI. An `azure` column that wins every "
        "field here changes what serves the user-triggered assist, over the REDACTED copy, "
        "and nothing else.",
        "- **Residency is not a score.** Sending transcript text to a provider is a D-36 "
        "decision about where an Indian caller's words are processed, and no column here "
        "can outvote it.",
        "- **The fixtures are synthetic.** They are the same cases for every provider, which "
        "is what makes the columns comparable, and they are not a sample of live traffic.",
        "- **`compliance`, `redaction` and `fixture` failures score OUR code**, not the "
        "model's — a provider column carrying one of those is reporting a defect on this "
        "side of the seam.",
        "",
        "## Failures, per provider",
        "",
    ]
    for run in runs:
        lines.append(f"### {run.provider} (`{run.model}`)")
        failing = [r for r in run.results if not r.passed]
        if not failing:
            lines += ["", "Every case passed.", ""]
            continue
        lines.append("")
        for result in failing:
            lines.append(f"- **{result.title}** (`{result.case_id}`)")
            lines += [f"  - {failure}" for failure in result.failures]
        lines.append("")
    return "\n".join(lines)


def _regenerate_command(runs: Sequence[ProviderRun], meta: Mapping[str, Any]) -> str:
    """The exact command that reproduces this file, for the banner above it.

    Written out rather than described: `docs/evidence/` is committed, and a generated
    artefact whose regeneration is folklore gets hand-edited within a month.
    """
    providers = " ".join(f"--provider={run.provider}" for run in runs)
    return (
        f"uv run python -m scripts.eval --client={meta['client']} {providers} "
        "--evidence=docs/evidence/extraction-provider-scorecard.md"
    )


class EvidenceLeakError(Exception):
    """The document reached the writer still carrying something that must not be committed."""


def write_evidence(out: Path, document: str) -> None:
    """Write an artefact to `docs/evidence/`, or refuse.

    `_safe` already masks every value on the way into a failure line, so the second sweep
    here should never have anything to do. That is exactly why it runs: `scripts/pilot/
    redact.py` is this repo's one answer to "the last thing before bytes leave to
    docs/evidence", it owns the free-standing-digit-run rule, and a non-zero count from it
    means layer 1 has a hole. Git is forever and the repo is shared, so the refusal is the
    cheap outcome — the pilot harness's own words: a leak in a committed artefact is
    permanent, a refused write is a minute of someone's day.

    Imported inside the function because `scripts.pilot` pulls in the vendor pilot's
    dependency surface and this CLI's normal path never touches it.
    """
    from scripts.pilot.redact import scrub_text

    scrubbed, masked = scrub_text(document)
    if masked:
        raise EvidenceLeakError(
            f"refusing to write {out}: the redaction sweep masked {masked} value(s) that "
            "`_safe` should already have caught. Fix the reporting path — a committed "
            "artefact is permanent."
        )
    _write_report(out, scrubbed)


def _counts(by_vertical: Mapping[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in sorted(by_vertical.items())) or "none"


def render(results: list[CaseResult], meta: dict[str, Any]) -> str:
    lines = [
        "# Calevate regression report",
        "",
        f"- Client: **{meta['client']}**",
        f"- Extraction model: **{meta['model']}**",
        f"- Run at: {meta['ran_at']}",
        f"- Result: **{meta['passed']}/{meta['cases']} passed**",
        f"- Scenarios per vertical: {_counts(meta['by_vertical'])}"
        f" · red-team cases: {meta['red_team']}",
        "",
        "| # | Scenario class | Case | Result |",
        "|---|---|---|---|",
    ]
    for r in results:
        label = SCENARIO_LABELS.get(r.scenario, str(r.scenario))
        lines.append(f"| {r.scenario} | {label} | {r.title} | {'PASS' if r.passed else 'FAIL'} |")
    lines.append("")
    for r in results:
        if r.passed:
            continue
        lines.append(f"### FAIL — {r.title} (`{r.case_id}`)")
        lines += [f"- {f}" for f in r.failures]
        lines.append("")
    return "\n".join(lines)


#: Exit code for "this run could not honestly be performed" — as distinct from 1, which
#: means it WAS performed and something regressed. The existing `--vertical` +
#: `--update-baseline` refusal already uses it, and an absent credential is the same
#: class of answer: nothing was measured, so nothing may be concluded.
CANNOT_RUN = 2


async def _score_providers(
    client: str,
    names: Sequence[str],
    *,
    vertical: str | None,
    update_baseline: bool,
    evidence: Path | None,
) -> int:
    """Score each named provider over the same fixtures, and compare them per field.

    ORDER OF REFUSALS MATTERS. Everything that makes the run impossible is answered before
    a single case is scored, because the failure mode this exists to prevent is a run that
    produces a plausible-looking scorecard with a column missing or a column that is not
    what its heading says.
    """
    unknown = [name for name in names if name not in PROVIDERS]
    if unknown:
        print(f"unknown provider(s): {', '.join(unknown)}. Known: {', '.join(sorted(PROVIDERS))}")
        return CANNOT_RUN
    if update_baseline and len(names) > 1:
        # A baseline is per model and `--update-baseline` is the one automated path that
        # can move the bar. Moving two at once from one command is a diff no reviewer
        # reads as two decisions, which is what it is.
        print("--update-baseline takes one --provider at a time")
        return CANNOT_RUN

    scorable, refused = resolve_providers(names)
    if refused:
        # REFUSE THE WHOLE RUN, not just the column. A comparison silently missing the
        # provider somebody asked about reads as "we compared them" — and the absent one
        # is invariably the one the decision is about.
        print("CANNOT SCORE — nothing was measured:")
        for missing in refused:
            print(f"  - {missing}")
        print(
            "Set the variable(s) above and run again. Task #87 is blocked on exactly this "
            "and on egress from this environment; it is not blocked on any code here."
        )
        return CANNOT_RUN

    runs: list[ProviderRun] = []
    shared_meta: dict[str, Any] = {}
    for provider_name, extractor in scorable:
        results, meta = await run_suite(client, vertical, extractor)
        shared_meta = dict(meta)
        model = str(meta["model"])
        if update_baseline:
            if vertical is not None:
                print("--update-baseline needs the whole suite; drop --vertical")
                return CANNOT_RUN
            baseline_refused = save_baseline(model, results)
            waived = len([r for r in results if not r.passed]) - len(baseline_refused)
            print(f"baseline for {model}: {waived} case(s) waived")
            if baseline_refused:
                print(
                    "REFUSED to baseline (a wrong value, an invented field, a compliance "
                    "or redaction miss is not waivable on any model):"
                )
                for case_id in baseline_refused:
                    print(f"  - {case_id}")
                return 1
            return 0
        regressions, _fixed = classify(results, load_baseline().get(model, []))
        runs.append(
            ProviderRun(
                provider=provider_name, model=model, results=results, regressions=regressions
            )
        )

    document = render_comparison(runs, shared_meta)
    print(document)
    if evidence is not None:
        write_evidence(evidence, document)
        print(f"\nevidence written to {evidence}")
    regressed = sorted({case_id for run in runs for case_id in run.regressions})
    if regressed:
        print("\nREGRESSIONS (previously passing, now failing):")
        for case_id in regressed:
            print(f"  - {case_id}")
    # The ratchet still gates a provider run: a comparison is not a licence to stop
    # noticing that one of the columns got worse than its own committed baseline.
    return 1 if regressed else 0


async def main_async(
    client: str,
    out: Path | None,
    update_baseline: bool,
    vertical: str | None = None,
    providers: Sequence[str] = (),
    evidence: Path | None = None,
) -> int:
    """No `--provider` runs exactly as this harness always has; naming one scores it.

    The split is deliberate rather than a branch that grew: `make eval` and `make eval-ci`
    are a CI gate, and a flag that changed what they measure — even to something better —
    would be a silent change to the thing that decides whether a release ships.
    """
    if providers or evidence is not None:
        # `--evidence` with no `--provider` scores the configured extractor. Writing an
        # artefact needs a NAMED column, and "whatever this box was holding" is the one
        # heading a committed comparison must never carry unlabelled.
        return await _score_providers(
            client,
            list(providers) or [DEFAULT_PROVIDER],
            vertical=vertical,
            update_baseline=update_baseline,
            evidence=evidence,
        )

    results, meta = await run_suite(client, vertical)
    model = str(meta["model"])

    if update_baseline:
        if vertical is not None:
            # A filtered run sees a subset of the cases, and `save_baseline` REPLACES
            # the model's entry — writing one from a subset would silently un-waive
            # every case the filter hid, turning the next full run red for cases
            # nobody changed.
            print("--update-baseline needs the whole suite; drop --vertical")
            return 2
        refused = save_baseline(model, results)
        waived = len([r for r in results if not r.passed]) - len(refused)
        print(f"baseline for {model}: {waived} case(s) waived")
        if refused:
            print(
                "REFUSED to baseline (a wrong value, an invented field, a compliance "
                "or redaction miss is not waivable on any model):"
            )
            for case_id in refused:
                print(f"  - {case_id}")
            return 1
        return 0

    regressions, fixed = classify(results, load_baseline().get(model, []))
    report = render(results, meta)
    print(report)
    if fixed:
        print(f"Improved since the baseline: {', '.join(fixed)}")
        print("Run with --update-baseline to lock the improvement in.\n")
    if regressions:
        print("REGRESSIONS (previously passing, now failing):")
        for case_id in regressions:
            print(f"  - {case_id}")
    if out:
        # ASYNC240 flags blocking Path I/O in async code; here it is deliberate. This
        # is a CLI whose entire job is finished by the time it writes one small report,
        # so there is nothing to yield to — pulling in anyio.Path would add a
        # dependency to buy nothing.
        _write_report(out, report)
        print(f"\nreport written to {out}")
    # A regression blocks promote (OPERATIONS §3, D-15).
    return 1 if regressions else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the regression suite for one client.")
    parser.add_argument("--client", required=True, help="tenant slug (report label)")
    parser.add_argument("--out", type=Path, default=None, help="write the markdown report here")
    parser.add_argument(
        "--vertical",
        choices=VERTICALS,
        default=None,
        help="score only this vertical's scenarios (the client-facing report); CI runs all",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record the current failures as the accepted baseline for this model",
    )
    parser.add_argument(
        "--provider",
        action="append",
        default=[],
        choices=sorted(PROVIDERS),
        dest="providers",
        help=(
            "score this extractor by name; repeat to compare providers head to head. "
            "Omit for the configured one (the CI gate's behaviour, unchanged). A named "
            "provider whose key is absent REFUSES the run rather than scoring zero."
        ),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help=(
            "write the per-field provider comparison here as a committed evidence "
            "artefact, e.g. docs/evidence/extraction-provider-scorecard.md"
        ),
    )
    args = parser.parse_args()
    return asyncio.run(
        main_async(
            args.client,
            args.out,
            args.update_baseline,
            args.vertical,
            args.providers,
            args.evidence,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
