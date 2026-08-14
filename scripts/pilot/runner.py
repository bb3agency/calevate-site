"""The pilot runner — one command that executes gates and records what it found.

    uv run python -m scripts.pilot preflight
    uv run python -m scripts.pilot run --gates 1,2,6
    uv run python -m scripts.pilot run --gates 2 --to +91XXXXXXXXXX \\
        --yes-place-real-calls-and-spend-money --max-calls 2

WHY THIS EXISTS. ROADMAP gate G0 is "engine scorecard passed + demo agent taking calls",
the first gate in the roadmap, and it has never been attempted — `docs/evidence/
bolna-pilot-scorecard.md` is still the empty template. OPERATIONS §2 describes thirteen
gates in prose, which means executing them today is an operator hand-curling for days
and typing conclusions into markdown. The parts that a machine can decide should be
decided by a machine, once, the same way every time, with the result in a file.

THE ONE INVARIANT THIS FILE ENFORCES ABOVE ALL OTHERS: **a gate that did not run cannot
be mistaken for one that passed.** Every unregistered gate is reported explicitly, with
who is expected to own it; the process exit code distinguishes "all green" from "nothing
went red but half of it never ran"; and the human-readable summary spells NOT RUN.

EXIT CODES
  0  every requested gate PASSED
  1  at least one gate FAILED
  2  no failure, but at least one requested gate did not run
  3  the harness REFUSED to run (production config, missing opt-in, bad argument)
  4  `reachability` only: this machine cannot reach the vendor API

2 is not a warning, it is the DRY-RUN exit. That is deliberate: a dry run has verified
nothing about the vendor, and a harness that exits 0 after verifying nothing is a
harness that will eventually be wired into something that believes it.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from apps.api.core.settings import get_settings
from apps.api.engine import get_engine
from calevate_shared.config import Settings

from scripts.pilot import gates_api, safety
from scripts.pilot.config import VENDOR_API_URL, format_preflight, preflight, probe_vendor
from scripts.pilot.gates_api import ATTESTABLE, GateContext
from scripts.pilot.redact import scrub
from scripts.pilot.results import STATUS_LABEL, GateRun
from scripts.pilot.safety import LIVE_CALL_FLAG, PilotRefusedError

GateRunner = Callable[[GateContext], Awaitable[GateRun]]

#: The gates this harness runs when the operator names none: the three that need only an
#: API key and a tunnel. Everything else needs a number, credit, or a file of observations.
DEFAULT_GATES = "1,2,6"

#: Sibling modules that may contribute gates. Imported OPTIONALLY: `scripts/pilot/` is
#: written by several slices in parallel, and a runner that crashes because a colleague's
#: module is mid-edit is a runner nobody can use on the day. A module that fails to
#: import contributes nothing and its gates report NOT RUN with the import error, which
#: is both honest and immediately diagnosable.
OPTIONAL_GATE_MODULES: tuple[str, ...] = (
    "scripts.pilot.latency",
    "scripts.pilot.concurrency",
    "scripts.pilot.knowledge",
    "scripts.pilot.fidelity",
)

#: Gates that no harness can execute, with the reason. Listing them is the point: an
#: operator reading the output must be able to tell "nobody has built this yet" from
#: "this is a conversation with a human being and always will be".
HUMAN_ONLY: dict[int, str] = {
    # 3 and 5 are the LISTENING gates: both are judgements about what a Telugu speaker
    # hears on a live PSTN call (was the name recognised; did it cut the caller off), and
    # no measurement we can take from this side observes either. They are listed here
    # rather than left to the generic "belongs to another slice" reason, which would
    # promise an implementation that is never coming. `scorecard.GATES` classifies both
    # as `human listening`, and the two statements must not drift apart.
    3: "Telugu STT/TTS quality on real PSTN — a Telugu speaker scoring a 10-utterance "
    "script by ear (scorecard evidence: human listening)",
    5: "Telugu turn-taking: barge-in and end-of-utterance on hesitant speech — an "
    "orchestration property judged by ear, not by a timer (scorecard: human listening)",
    9: "compute region + India data-residency terms — a written answer from the vendor",
    10: "agency model / sub-accounts tier — a written answer from the vendor",
    11: "support responsiveness — two support threads and a stopwatch",
    12: "commercials in writing — the BYOK platform fee and the rest of the contract",
}


def gate_registry() -> tuple[dict[int, GateRunner], dict[int, str]]:
    """Every gate implementation reachable right now, plus why the others are not.

    Returns (runners, unavailable_reasons). The second half is what stops a missing
    module from becoming a silent omission.
    """
    runners: dict[int, GateRunner] = dict(gates_api.GATES)
    unavailable: dict[int, str] = {}
    for module_name in OPTIONAL_GATE_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue  # not written yet; nothing to say about gates we cannot name
        except Exception as exc:
            unavailable[-1] = f"{module_name} failed to import: {type(exc).__name__}"
            continue
        contributed = getattr(module, "GATES", None)
        if isinstance(contributed, dict):
            for number, runner in contributed.items():
                runners.setdefault(int(number), runner)
    return runners, unavailable


def parse_attestations(pairs: Sequence[str]) -> dict[str, str]:
    """`key=value`, with a CLOSED vocabulary.

    An unknown key is an error, never an ignored line. The whole value of an attestation
    is that a human vouched for a specific fact; a typo that silently vouches for nothing
    would leave the gate reporting NOT RUN while its operator believes they answered it.
    """
    parsed: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        key = key.strip()
        if not sep:
            raise PilotRefusedError(f"--attest expects key=value, got {pair!r}")
        if key not in ATTESTABLE:
            known = "\n  ".join(f"{k} : {v}" for k, v in sorted(ATTESTABLE.items()))
            raise PilotRefusedError(
                f"--attest {key!r} is not an attestable fact. Known keys:\n  {known}"
            )
        parsed[key] = value.strip()
    return parsed


def load_captures(paths: Sequence[str]) -> list[dict[str, Any]]:
    """Raw webhook bodies saved off the tunnel.

    A file may hold one delivery or a list of them, because both are what a person
    actually ends up with — `tee` one body per file, or paste a session's worth into an
    array. Anything else is refused by name rather than skipped: a capture that silently
    contributed nothing would make gate 1 report NOT RUN for a reason the operator
    already believed they had solved.
    """
    captures: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PilotRefusedError(f"--webhook-capture {raw_path}: no such file") from exc
        except json.JSONDecodeError as exc:
            raise PilotRefusedError(
                f"--webhook-capture {raw_path}: not valid JSON ({exc.msg})"
            ) from exc
        if isinstance(payload, dict):
            captures.append(payload)
        elif isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            captures.extend(payload)
        else:
            raise PilotRefusedError(
                f"--webhook-capture {raw_path}: expected a delivery object or a list of them"
            )
    return captures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.pilot",
        description="Bolna pilot harness (OPERATIONS §2). Dry run unless told otherwise.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("preflight", help="What is missing before the pilot can start")
    pre.add_argument(
        "--no-network",
        action="store_true",
        help="Skip the vendor reachability probe (it is then reported UNVERIFIABLE, "
        "never assumed fine)",
    )

    # Its own subcommand as well as the first row of the preflight, because it is the one
    # check that needs nothing at all — no key, no credit, no number — and it is the one
    # that decides whether the machine in front of you can run the pilot at any point.
    sub.add_parser("reachability", help="Can this machine reach the vendor API at all?")

    run = sub.add_parser("run", help="Execute gates and record structured results")
    run.add_argument(
        "--gates",
        action="append",
        default=None,
        help="Gate numbers as OPERATIONS §2 numbers them: comma-separated, REPEATABLE, or "
        f"both (default: {DEFAULT_GATES}). Repeatable because argparse's default for a "
        "value option is last-one-wins, and `--gates 7 --gates 8` silently dropping gate 7 "
        "is precisely the class of quiet omission this harness exists to prevent.",
    )
    run.add_argument(
        "--to",
        default=None,
        help="The ONE destination number this run may dial, E.164. Never written to output.",
    )
    run.add_argument(
        LIVE_CALL_FLAG,
        dest="place_calls",
        action="store_true",
        help="Opt in to placing REAL calls that cost REAL money. Requires --max-calls.",
    )
    run.add_argument("--max-calls", type=int, default=None, help="Hard ceiling on calls placed")
    run.add_argument(
        "--minutes-per-call",
        default=str(safety.DEFAULT_MINUTES_PER_CALL),
        help="Assumed call length for the cost estimate",
    )
    run.add_argument(
        "--webhook-capture",
        action="append",
        default=[],
        metavar="FILE",
        help="Raw delivered webhook body saved off the tunnel (repeatable) — gate 1",
    )
    run.add_argument(
        "--missed-execution",
        action="append",
        default=[],
        metavar="ID",
        help="Execution id whose webhook was dropped (repeatable) — gate 6",
    )
    run.add_argument(
        "--attest",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="A fact a human observed. `--attest help` is not a key; see the error for the list.",
    )
    run.add_argument(
        "--since-hours",
        type=float,
        default=6.0,
        help="How far back the List-Executions poller window reaches (default: 6)",
    )
    run.add_argument("--out", default=None, metavar="FILE", help="Write the JSON result here")
    return parser


def _requested_gates(spec: str | Sequence[str] | None) -> list[int]:
    """Every gate the operator named, once each, in the order they named them.

    Accepts one comma-separated string, a repeated flag, or a mix of the two. Duplicates
    collapse rather than running a gate twice: a gate that appears twice in the output is
    a gate a reader has to reconcile with itself, and the second run's result would
    silently be the one a `dict`-keyed reader kept.
    """
    specs = [spec] if isinstance(spec, str) else list(spec or [DEFAULT_GATES])
    numbers: dict[int, None] = {}
    for one in specs:
        for part in one.split(","):
            token = part.strip()
            if not token:
                continue
            if not token.isdigit():
                raise PilotRefusedError(f"--gates: {token!r} is not a gate number")
            numbers.setdefault(int(token), None)
    if not numbers:
        raise PilotRefusedError("--gates named no gates")
    return list(numbers)


def _minutes(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise PilotRefusedError(f"--minutes-per-call: {raw!r} is not a number") from exc
    if value <= 0:
        raise PilotRefusedError("--minutes-per-call must be positive")
    return value


async def run_gates(
    numbers: Sequence[int], ctx: GateContext
) -> tuple[list[GateRun], list[dict[str, str]]]:
    """Run what exists; report what does not, by name."""
    runners, module_problems = gate_registry()
    results: list[GateRun] = []
    skipped: list[dict[str, str]] = []
    for problem in module_problems.values():
        skipped.append({"gate": "?", "reason": problem})
    for number in numbers:
        runner = runners.get(number)
        if runner is None:
            reason = HUMAN_ONLY.get(number)
            if reason is None:
                reason = (
                    "no implementation is registered in scripts/pilot/ for this gate — it "
                    "belongs to another slice and is NOT covered by this run"
                )
            results.append(GateRun(number=number, title="(not implemented)", blocked=reason))
            skipped.append({"gate": str(number), "reason": reason})
            continue
        results.append(await runner(ctx))
    return results, skipped


def render(results: Sequence[GateRun], estimate: safety.CostEstimate | None) -> str:
    lines = ["", "PILOT RESULTS (OPERATIONS §2)", ""]
    for result in results:
        lines.append(f"gate {result.number:>2}  {STATUS_LABEL[result.status]:<8} {result.title}")
        if result.blocked:
            lines.append(f"           - {result.blocked}")
        for check in result.checks:
            marker = STATUS_LABEL[check.status]
            attested = " [operator-attested]" if check.attested else ""
            lines.append(f"           {marker:<8} {check.name}{attested}: {check.detail}")
            for key, value in check.measurements.items():
                lines.append(f"                     {key} = {value}")
        for finding in result.findings:
            lines.append(f"           FINDING: {finding}")
        lines.append("")
    if estimate is not None:
        lines.append(estimate.render())
    counts = dict.fromkeys(STATUS_LABEL.values(), 0)
    for result in results:
        counts[STATUS_LABEL[result.status]] += 1
    lines.append(
        "SUMMARY: "
        + ", ".join(f"{count} {label}" for label, count in counts.items())
        + "   (NOT RUN is not PASS)"
    )
    return "\n".join(lines)


def exit_code(results: Sequence[GateRun]) -> int:
    if any(r.status == "fail" for r in results):
        return 1
    if any(r.status != "pass" for r in results) or not results:
        return 2
    return 0


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    numbers = _requested_gates(args.gates)
    attestations = parse_attestations(args.attest)
    captures = load_captures(args.webhook_capture)
    minutes = _minutes(args.minutes_per_call)

    safety.guard(settings, placing_calls=bool(args.place_calls))
    budget = safety.call_budget(opted_in=bool(args.place_calls), max_calls=args.max_calls)

    estimate = safety.estimate_cost(
        calls=budget, minutes_per_call=minutes, usd_inr_rate=settings.usd_inr_rate
    )
    # BEFORE the money moves, and flushed, because the next thing this process does may
    # ring a telephone.
    if budget:
        print(estimate.render(), flush=True)
        if args.to is None:
            raise PilotRefusedError(
                f"{LIVE_CALL_FLAG} needs --to <E.164>: there is nothing to dial."
            )
    else:
        print("DRY RUN — no calls will be placed. Nothing here spends money.", flush=True)

    ctx = GateContext(
        engine=get_engine(settings),
        settings=settings,
        calls_remaining=budget,
        to_e164=args.to,
        captured_webhooks=captures,
        missed_execution_ids=list(args.missed_execution),
        attestations=attestations,
        since=datetime.now(UTC) - timedelta(hours=args.since_hours),
    )
    results, skipped = await run_gates(numbers, ctx)

    artefact: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "engine": ctx.engine.name,
        "app_env": settings.app_env,
        "dry_run": budget == 0,
        "calls_permitted": budget,
        "cost_estimate": estimate.as_dict(),
        "gates": [r.as_dict() for r in results],
        "not_run": skipped,
    }
    # Defence in depth (hard rule 6). Layer one is that gates never write PII; this is
    # layer two, and a non-zero count means layer one has a defect that needs finding.
    cleaned, redactions = scrub(artefact)
    cleaned["redactions_applied"] = redactions

    print(render(results, estimate if budget else None))
    if redactions:
        print(
            f"\nWARNING: the output scrubber masked {redactions} value(s). A gate wrote "
            "something that looks like personal data — find it before committing this "
            "artefact.",
            file=sys.stderr,
        )
    if args.out:
        # Written from a thread: this coroutine owns the whole process and nothing else is
        # waiting on the loop, but a blocking write inside an `async def` is the habit
        # ASYNC240 exists to break, and the harness should not model the bad one.
        await asyncio.to_thread(
            Path(args.out).write_text,
            json.dumps(cleaned, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\nwrote {args.out}")
    else:
        print("\n(no --out given; JSON not written)")
    return exit_code(results)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    try:
        if args.command == "reachability":
            probe = probe_vendor()
            print(f"{VENDOR_API_URL} — {'REACHABLE' if probe.reachable else 'UNREACHABLE'}")
            print(f"  {probe.detail}")
            # Non-zero when unreachable: this is the check most likely to be wired into a
            # setup script, and "the network is blocked" must not exit 0.
            return 0 if probe.reachable else 4
        if args.command == "preflight":
            probe = None if args.no_network else probe_vendor()
            print(format_preflight(preflight(settings, probe)))
            return 0
        return asyncio.run(_run(args, settings))
    except PilotRefusedError as refusal:
        # An operator-facing refusal, not a traceback: this is read at 11pm and every one
        # of these messages names the thing to change.
        print(f"\n{refusal}", file=sys.stderr)
        return 3


__all__ = [
    "DEFAULT_GATES",
    "HUMAN_ONLY",
    "OPTIONAL_GATE_MODULES",
    "build_parser",
    "exit_code",
    "gate_registry",
    "load_captures",
    "main",
    "parse_attestations",
    "render",
    "run_gates",
]
