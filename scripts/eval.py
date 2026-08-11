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
- **compliance** — the disclosure line was spoken, and a DNC request was acknowledged.

It runs against WHATEVER extractor is configured (D-36: Sarvam by default, Gemini as a
configurable fallback, offline when no key is present), and the report names the model
— comparing runs across different models is the entire point of gate 13.

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
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.workers.extraction import extract_call, get_extractor
from apps.workers.redaction import redact, spoken_digit_runs
from calevate_shared.extraction import ExtractionSchemaSpec

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
    passed: bool = True
    failures: list[Failure] = field(default_factory=list)
    captured: dict[str, Any] = field(default_factory=dict)
    outcome: str | None = None

    def fail(self, kind: str, message: str) -> None:
        self.passed = False
        self.failures.append(Failure(kind=kind, message=message))

    @property
    def kinds(self) -> set[str]:
        """The kinds this case failed on — `{UNSPECIFIED}` if it failed without one,
        so a hand-built result can never be silently treated as unwaivable."""
        return {f.kind for f in self.failures} or ({UNSPECIFIED} if not self.passed else set())


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
                f"must_redact {secret[:4]}… is not recoverable from the raw transcript, "
                "so this assertion can never fail",
            )
            continue
        if any(secret in form for form in redacted_forms):
            result.fail(REDACTION, f"redaction left {secret[:4]}… recoverable")


async def run_case(spec: ExtractionSchemaSpec, case: dict[str, Any]) -> CaseResult:
    result = CaseResult(case_id=case["id"], title=case["title"], scenario=case["scenario"])
    transcript = "\n".join(case["transcript"])

    _check_compliance(case, result)
    _check_redaction(case, result)

    output = await extract_call(spec, transcript)
    result.captured = output.data
    result.outcome = output.outcome_tag

    for key, expected in (case.get("expect") or {}).items():
        actual = output.data.get(key)
        if actual is None:
            # Nothing captured. A weaker model is allowed to be blind here.
            result.fail(CAPTURE_MISS, f"missed {key} (expected {expected!r})")
        elif str(actual).strip().lower() != str(expected).strip().lower():
            # Something captured, and it is WRONG. The SMB acts on the CRM row, not
            # on the call: a wrong callback number is worse than a blank one, so this
            # can never sit in a baseline.
            result.fail(CAPTURE_WRONG, f"{key}: expected {expected!r}, got {actual!r}")

    for key in case.get("expect_absent") or []:
        if output.data.get(key) is not None:
            # The failure mode that quietly ruins a CRM.
            result.fail(
                RESTRAINT, f"invented {key}={output.data[key]!r} — the caller never said it"
            )

    expected_outcome = case.get("expect_outcome")
    if expected_outcome and output.outcome_tag != expected_outcome:
        result.fail(OUTCOME, f"outcome: expected {expected_outcome}, got {output.outcome_tag}")

    if output.errors:
        result.fail(SCHEMA, f"schema validation errors: {sorted(output.errors)}")

    return result


async def run_suite(client: str) -> tuple[list[CaseResult], dict[str, Any]]:
    payload = json.loads(FIXTURES.read_text())
    spec = ExtractionSchemaSpec(version=1, fields=payload["schema"])
    results = [await run_case(spec, case) for case in payload["cases"]]
    meta = {
        "client": client,
        "model": get_extractor().model_name,
        "ran_at": datetime.now(UTC).isoformat(),
        "cases": len(results),
        "passed": sum(1 for r in results if r.passed),
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
    data = json.loads(BASELINE.read_text())
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
    data = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
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


def render(results: list[CaseResult], meta: dict[str, Any]) -> str:
    lines = [
        "# Calevate regression report",
        "",
        f"- Client: **{meta['client']}**",
        f"- Extraction model: **{meta['model']}**",
        f"- Run at: {meta['ran_at']}",
        f"- Result: **{meta['passed']}/{meta['cases']} passed**",
        "",
        "| # | Scenario | Result |",
        "|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.scenario} | {r.title} | {'PASS' if r.passed else 'FAIL'} |")
    lines.append("")
    for r in results:
        if r.passed:
            continue
        lines.append(f"### FAIL — {r.title} (`{r.case_id}`)")
        lines += [f"- {f}" for f in r.failures]
        lines.append("")
    return "\n".join(lines)


async def main_async(client: str, out: Path | None, update_baseline: bool) -> int:
    results, meta = await run_suite(client)
    model = str(meta["model"])

    if update_baseline:
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
        "--update-baseline",
        action="store_true",
        help="record the current failures as the accepted baseline for this model",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args.client, args.out, args.update_baseline))


if __name__ == "__main__":
    sys.exit(main())
