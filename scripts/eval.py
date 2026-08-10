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
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.workers.extraction import extract_call, get_extractor
from apps.workers.redaction import redact
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


@dataclass
class CaseResult:
    case_id: str
    title: str
    scenario: int
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    captured: dict[str, Any] = field(default_factory=dict)
    outcome: str | None = None

    def fail(self, message: str) -> None:
        self.passed = False
        self.failures.append(message)


def _check_compliance(case: dict[str, Any], result: CaseResult) -> None:
    turns = [t.lower() for t in case["transcript"]]
    opening = turns[0] if turns else ""
    if not any(m in opening for m in DISCLOSURE_MARKERS):
        result.fail("the opening turn does not disclose that this is an AI")
    if not any(m in opening for m in RECORDING_MARKERS):
        result.fail("the opening turn does not mention recording")
    if case.get("requires_dnc") and not any(
        any(m in turn for m in DNC_ACK_MARKERS) for turn in turns
    ):
        result.fail("a do-not-call request was made but never acknowledged")


def _check_redaction(case: dict[str, Any], result: CaseResult) -> None:
    for turn in case["transcript"]:
        redacted = redact(turn).text
        for secret in case.get("must_redact", []):
            if secret in redacted:
                result.fail(f"redaction left {secret[:4]}… in the transcript")
    # Spoken digits are checked against the redacted text as a whole, since the run
    # may span a line.
    joined = " ".join(redact(t).text for t in case["transcript"])
    for secret in case.get("must_redact", []):
        digits_only = "".join(c for c in joined if c.isdigit())
        if secret in digits_only:
            result.fail(f"redaction left the digits of {secret[:4]}… recoverable")


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
            result.fail(f"missed {key} (expected {expected!r})")
        elif str(actual).strip().lower() != str(expected).strip().lower():
            result.fail(f"{key}: expected {expected!r}, got {actual!r}")

    for key in case.get("expect_absent") or []:
        if output.data.get(key) is not None:
            # The failure mode that quietly ruins a CRM.
            result.fail(f"invented {key}={output.data[key]!r} — the caller never said it")

    expected_outcome = case.get("expect_outcome")
    if expected_outcome and output.outcome_tag != expected_outcome:
        result.fail(f"outcome: expected {expected_outcome}, got {output.outcome_tag}")

    if output.errors:
        result.fail(f"schema validation errors: {sorted(output.errors)}")

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


def load_baseline() -> dict[str, list[str]]:
    """Known-failing case ids, per extraction model. Keyed by model because the whole
    point of D-36's open question is comparing models on these fixtures."""
    if not BASELINE.exists():
        return {}
    data = json.loads(BASELINE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def save_baseline(model: str, failing: list[str]) -> None:
    data = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    data["_doc"] = (
        "Known-failing regression cases per extraction model. The gate is a RATCHET: a "
        "case listed here is allowed to fail, and anything not listed is not. Removing "
        "entries is progress; adding one is a decision that needs a reason in the PR."
    )
    data[model] = sorted(failing)
    BASELINE.write_text(json.dumps(data, indent=2) + "\n")


def _write_report(out: Path, report: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)


def classify(results: list[CaseResult], baseline: list[str]) -> tuple[list[str], list[str]]:
    """(regressions, fixed) — the two lists a reviewer actually needs."""
    failing = {r.case_id for r in results if not r.passed}
    known = set(baseline)
    return sorted(failing - known), sorted(known - failing)


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
    failing = [r.case_id for r in results if not r.passed]

    if update_baseline:
        save_baseline(model, failing)
        print(f"baseline for {model} set to {len(failing)} known-failing case(s)")
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
