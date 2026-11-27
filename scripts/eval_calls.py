"""Simulated-call scorecard: in-call quality measured on every change, not one test call at a time.

    uv run python -m scripts.eval_calls                                  # recorded, CI-safe
    uv run python -m scripts.eval_calls --fixture rytu --live --record /tmp/sim
    uv run python -m scripts.eval_calls --holder campaign:<uuid> --live --max-inr 40
    uv run python -m scripts.eval_calls --compare recA/ recB/            # two recorded runs
    uv run python -m scripts.eval_calls --live --compare old.json new.json [--judge]
    uv run python -m scripts.eval_calls --write-baseline                 # after a reviewed change
    uv run python -m scripts.eval_calls --release --holder campaign:<uuid> --max-inr 200

THE RELEASE GATE (`--release`, docs/OPERATIONS.md §3.1): a change to what an agent is told on
a call ships only with a live run on the release candidate's composed prompt. It is `--live
--gate` over `RELEASE_RUNS` runs of `RELEASE_PERSONAS` (the founder's calls of 27 and 28 Nov
2026, the caller who does not remember registering, and the hard-rule probes); the report and
its counts (`.json` beside it) are committed under docs/evidence/call-sim/, and it exits 1 when
a hard-rule kind shows or a gated kind (`scorecard.GATE_KINDS`) shows in a larger share of runs
than `live-baseline.json` holds. A reviewed run becomes that baseline with
`--write-live-baseline`; with none recorded every gated kind seen fails.

The caller personas (`call_sim/personas.py`) meet the agent. The agent side is what we
publish: the holder's composed engine prompt, its steps and its settings (`call_sim/agent.py`),
on the in-call model the console names (`Settings.thinnest_own_model_default`). Scoring is code
(`call_sim/scorecard.py`): every in-call check and mistake kind the product uses, plus the step
reading against how far a good call gets each persona, moved-on-after-unclear, a known value
asked, the truthful AI answer and the do-not-call step. The model is not what is measured: the
same model reads every version, so a change in score is a change in what we send.

WITHOUT `--live` it scores recorded transcripts (`scripts/fixtures/call_sim/recorded/<fixture>/`),
so CI is deterministic; `tests/call_sim_test.py` fails when that score moves off
`scripts/fixtures/call_sim/baseline.json`. Two recordings are English stand-ins of the founder's
test calls of 24 and 25 Nov 2026, two are his Telugu calls of 27 Nov (21:35, `stops_early`) and
28 Nov 2026 (00:48, `bare_okay`) as the call page showed them, name replaced; the rest are
hand-written stand-ins until a `--live --record` run replaces them. A recording made on another
prompt is named stale in the report.

WITH `--live` it spends real money on our Google key (only on the VPS): one agent reply per turn,
one caller line per turn, one step reading per call. It stops at `--max-inr`.

`--compare A B` scores two versions on the same personas: two recording directories, or with
`--live` two scripts (a CallScript JSON, or a fixture-shaped JSON with a "script" key) or two
whole prompts (a .txt file). `--judge` (live only) adds the AI judge for register and
naturalness (`call_sim/judge.py`), never part of the score or of CI.

Hard rule 6: reports carry kinds, counts and turn numbers, never a transcript line. Recordings are
simulated conversations, never customer data; write them outside the repo for a real holder.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from calevate_shared.call_script import CallScript
from calevate_shared.calling_window import IST

from scripts.call_sim import scorecard as sc
from scripts.call_sim.agent import FIXTURES, ROOT, AgentUnderTest, fixture_agent, holder_agent
from scripts.call_sim.personas import BY_KEY, Persona, personas_for

CANNOT_RUN: Final = 2
GATE_FAILED: Final = 1
REPORTS: Final = ROOT / "docs" / "evidence" / "call-sim"
BASELINE: Final = FIXTURES / "baseline.json"
#: The last reviewed live run's counts (`--write-live-baseline`), which `--gate` reads.
LIVE_BASELINE: Final = REPORTS / "live-baseline.json"
#: The personas the release gate runs: the founder's two calls and the hard-rule probes.
RELEASE_PERSONAS: Final = "stops_early,bare_okay,forgot_registering,cooperative,asks_ai,remove_me"
RELEASE_RUNS: Final = 10
DEFAULT_FIXTURE: Final = "rytu"
DEFAULT_MAX_INR: Final = Decimal("30")


def recorded_dir(fixture: str) -> Path:
    return FIXTURES / "recorded" / fixture


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


# --- recorded ---------------------------------------------------------------------------------


def recorded_card(directory: Path, agent: AgentUnderTest | None) -> sc.Scorecard:
    """The scorecard of a directory of recordings, scored against `agent`'s script and facts."""
    recordings = sc.load_recordings(directory)
    known = agent.known if agent is not None else ""
    card = sc.scorecard(agent.holder if agent else directory.name, recordings, known=known)
    notes: list[str] = []
    if agent is not None:
        stale = [r.persona for r in recordings if r.prompt_sha and r.prompt_sha != agent.prompt_sha]
        stand_in = [r.persona for r in recordings if not r.prompt_sha]
        if stale:
            notes.append(
                f"Stale: {', '.join(stale)} were recorded on another prompt; re-run with --live."
            )
        if stand_in:
            notes.append(
                f"Stand-ins, not model runs: {', '.join(stand_in)} (see each recording's source)."
            )
        if agent.script is not None:
            notes += [
                f"Script: {f}" for f in sc.script_findings(agent.script, language=agent.language)
            ]
    return sc.Scorecard(card.holder, card.personas, tuple(notes))


# --- live -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Live:
    key: str
    model: str
    caller_model: str


async def _prepare() -> tuple[str | None, str]:
    """The console's settings, spoken style and attested prices as a publish reads them; the
    Google key and the in-call model."""
    from apps.api.ops.spoken_style_store import refresh_spoken_style

    from scripts.register_eval import _prepare as prepare_settings

    found = await prepare_settings()
    await refresh_spoken_style()
    return found


def _rates(model: str) -> tuple[Decimal, Decimal]:
    from scripts.register_eval import price_for

    price = price_for(model)
    return price.input, price.output


def save_recording(rec: sc.Recording, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{rec.persona}.json").write_text(
        json.dumps(sc.recording_json(rec), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


async def live_card(
    agent: AgentUnderTest,
    personas: Sequence[Persona],
    live: Live,
    *,
    turns: int,
    max_inr: Decimal,
    record: Path | None,
    judge: bool,
) -> tuple[sc.Scorecard, list[sc.Recording], Decimal, list[str]]:
    from scripts.call_sim import judge as judging
    from scripts.call_sim.simulate import Spend, google_ask, price, read_steps, simulate

    agent_ask = google_ask(live.key, live.model)
    caller_ask = google_ask(live.key, live.caller_model)
    json_ask = google_ask(live.key, live.model, json_mode=True)
    spend = Spend()
    recordings: list[sc.Recording] = []
    notes: list[str] = []
    grader = judging.judge_leg(live.key, live.model) if judge else None
    for persona in personas:
        if price(spend, _rates) >= max_inr:
            notes.append(f"Stopped at the ₹{max_inr} budget before '{persona.key}'.")
            break
        rec = await simulate(
            persona,
            agent,
            agent_ask=agent_ask,
            caller_ask=caller_ask,
            spend=spend,
            model=live.model,
            caller_model=live.caller_model,
            max_turns=turns,
        )
        rec = await read_steps(rec, agent, json_ask, spend, live.model)
        recordings.append(rec)
        if record is not None:
            save_recording(rec, record)
        if grader is not None:
            grades = await judging.grade(rec, grader, spend)
            notes.append(
                f"Judge (UNCALIBRATED, {grader.model}) {persona.key}: "
                + ", ".join(f"{k} {v if v is not None else 'no answer'}" for k, v in grades.items())
            )
    if grader is not None and not grader.other_family:
        notes.append(judging.UNCONTROLLED)
    card = sc.scorecard(agent.holder, recordings, known=agent.known)
    return card, recordings, price(spend, _rates), notes


async def live_runs(
    agent: AgentUnderTest, args: argparse.Namespace, live: Live
) -> tuple[list[sc.Scorecard], Decimal, list[str]]:
    """`--runs` live runs of every persona, one budget across them all: the in-call model is
    not deterministic, so the gate reads how often a fault shows, never one call."""
    cards: list[sc.Scorecard] = []
    spent = Decimal(0)
    notes: list[str] = []
    for run_no in range(1, args.runs + 1):
        left = args.max_inr - spent
        if left <= 0:
            notes.append(f"Stopped at the ₹{args.max_inr} budget before run {run_no}.")
            break
        record = args.record / f"run{run_no}" if args.record and args.runs > 1 else args.record
        card, _recs, cost, more = await live_card(
            agent,
            _personas(args.personas, agent.direction),
            live,
            turns=args.turns,
            max_inr=left,
            record=record,
            judge=args.judge and run_no == 1,
        )
        cards.append(card)
        spent += cost
        notes += more
    return cards, spent, notes


def _live_baseline() -> sc.Tally | None:
    if not LIVE_BASELINE.exists():
        return None
    return sc.tally_of(json.loads(LIVE_BASELINE.read_text(encoding="utf-8")))


def gate_section(failed: Sequence[str]) -> str:
    if not failed:
        return "\n## Release gate: PASS\n\nNo gated kind rose against the live baseline.\n"
    return "\n## Release gate: FAIL\n\n" + "".join(f"- {f}\n" for f in failed)


# --- versions to compare ----------------------------------------------------------------------


def _version(path: Path) -> tuple[CallScript | None, str | None]:
    """A script (CallScript JSON, or a fixture-shaped JSON with "script") or a whole prompt."""
    if path.suffix == ".txt":
        return None, path.read_text(encoding="utf-8")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return CallScript.model_validate(raw.get("script", raw)), None


async def _agent(
    args: argparse.Namespace, vendor: str, version: Path | None = None
) -> AgentUnderTest:
    script, prompt = _version(version) if version is not None else (None, None)
    if args.holder:
        return await holder_agent(args.holder, vendor=vendor, script=script, prompt=prompt)
    return fixture_agent(
        args.fixture, vendor=vendor, script=script, prompt=prompt, language=args.language
    )


# --- output -----------------------------------------------------------------------------------


def write_report(text: str, name: str, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(IST):%Y-%m-%d}-{_slug(name)}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _personas(spec: str | None, direction: str) -> list[Persona]:
    offered = personas_for("outbound" if direction == "outbound" else "inbound")
    if not spec:
        return list(offered)
    keys = [k.strip() for k in spec.split(",") if k.strip()]
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        raise ValueError(f"unknown persona(s): {', '.join(unknown)}")
    return [BY_KEY[k] for k in keys]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.eval_calls", description=__doc__.split("\n\n")[0]
    )
    where = p.add_mutually_exclusive_group()
    where.add_argument(
        "--holder", help="campaign:<uuid> or line:<uuid> (live; read, never written)"
    )
    where.add_argument(
        "--fixture", default=DEFAULT_FIXTURE, help="a fixture under scripts/fixtures/call_sim"
    )
    p.add_argument("--live", action="store_true", help="call real models on our key (spends money)")
    p.add_argument("--recorded", type=Path, help="recordings directory (default: the fixture's)")
    p.add_argument(
        "--personas", help="comma-separated persona keys (default: all for the direction)"
    )
    p.add_argument("--turns", type=int, default=12, help="caller turns per call (live)")
    p.add_argument(
        "--max-inr", type=Decimal, default=DEFAULT_MAX_INR, help="stop at this spend (live)"
    )
    p.add_argument("--language", help="the fixture's call language for a live run (e.g. te-IN)")
    p.add_argument("--caller-model", help="the caller's model (default: the in-call model)")
    p.add_argument("--record", type=Path, help="write each live call's recording here")
    p.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"))
    p.add_argument("--judge", action="store_true", help="add the AI register judge (live only)")
    p.add_argument("--out", type=Path, default=REPORTS, help="report directory")
    p.add_argument("--no-report", action="store_true", help="print only")
    p.add_argument(
        "--write-baseline", action="store_true", help="store the recorded score as the CI baseline"
    )
    p.add_argument("--vendor-rules", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--runs", type=int, default=1, help="live runs of each persona")
    p.add_argument(
        "--gate",
        action="store_true",
        help="exit 1 when a gated kind rose against the live baseline (live only)",
    )
    p.add_argument(
        "--write-live-baseline",
        action="store_true",
        help=f"store this live run's counts as {LIVE_BASELINE.relative_to(ROOT)}",
    )
    p.add_argument(
        "--release",
        action="store_true",
        help=f"the release gate: --live --gate, {RELEASE_RUNS} runs of the release personas",
    )
    return p


async def run(args: argparse.Namespace) -> int:
    vendor = ""
    if args.vendor_rules:
        from scripts.register_eval import vendor_rules

        vendor = vendor_rules()
    live: Live | None = None
    if args.live:
        key, model = await _prepare()
        if not key:
            print("No Google key (GEMINI_API_KEY) here; --live runs on the VPS.", file=sys.stderr)
            return CANNOT_RUN
        live = Live(key, model, args.caller_model or model)
    elif args.holder:
        print("--holder needs --live: a holder has no recordings in the repo.", file=sys.stderr)
        return CANNOT_RUN

    if args.compare and live is None:
        a_dir, b_dir = args.compare
        base = fixture_agent(args.fixture, vendor=vendor)
        a, b = recorded_card(a_dir, base), recorded_card(b_dir, base)
        text = sc.render_compare(a, b, names=(a_dir.name, b_dir.name))
        return _emit(args, text, f"compare-{a_dir.name}-{b_dir.name}")

    if live is not None:
        if args.compare:
            cards: list[sc.Scorecard] = []
            runs: list[list[sc.Recording]] = []
            spent = Decimal(0)
            notes: list[str] = []
            for version in args.compare:
                agent = await _agent(args, vendor, version)
                record = args.record / version.stem if args.record else None
                card, recs, cost, more = await live_card(
                    agent,
                    _personas(args.personas, agent.direction),
                    live,
                    turns=args.turns,
                    max_inr=args.max_inr / 2,
                    record=record,
                    judge=False,
                )
                cards.append(card)
                runs.append(recs)
                spent += cost
                notes += more
            names = (args.compare[0].stem, args.compare[1].stem)
            text = sc.render_compare(cards[0], cards[1], names=names)
            if args.judge:
                text += await _judge_pairs(live, runs, notes)
            text += f"\n- Spent about ₹{spent:.2f} on {live.model}.\n"
            text += "".join(f"- {n}\n" for n in notes)
            return _emit(args, text, f"live-compare-{names[0]}-{names[1]}")
        agent = await _agent(args, vendor)
        cards, cost, notes = await live_runs(agent, args, live)
        card = cards[0]
        card = sc.Scorecard(card.holder, card.personas, (*notes, f"Spent about ₹{cost:.2f}."))
        meta = [
            f"Live run on {live.model} (caller {live.caller_model}), {args.turns} caller turns, "
            f"{len(cards)} run(s) per persona; the table is run 1"
        ]
        meta.append(f"Prompt sha256 {agent.prompt_sha[:12]}")
        meta.append(
            "The step list is merged as text; ThinnestAI's own step handling is not published."
        )
        text = sc.render(card, title="Simulated calls (live)", meta=meta)
        counted = sc.tally(agent.holder, agent.prompt_sha, cards)
        text += sc.render_tally(counted)
        status = 0
        if args.gate:
            failed = sc.gate_failures(counted, _live_baseline())
            text += gate_section(failed)
            status = GATE_FAILED if failed else 0
        if args.write_live_baseline:
            LIVE_BASELINE.parent.mkdir(parents=True, exist_ok=True)
            LIVE_BASELINE.write_text(
                json.dumps(sc.tally_json(counted), indent=2) + "\n", encoding="utf-8"
            )
            text += f"\n- Written as the live baseline: `{LIVE_BASELINE.relative_to(ROOT)}`.\n"
        emitted = _emit(args, text, f"live-{agent.holder}", tally=counted)
        return status or emitted

    agent = fixture_agent(args.fixture, vendor=vendor)
    directory = args.recorded or recorded_dir(args.fixture)
    card = recorded_card(directory, agent)
    if args.write_baseline and (args.fixture != DEFAULT_FIXTURE or args.recorded):
        print(
            f"--write-baseline holds the '{DEFAULT_FIXTURE}' recordings only; another fixture's "
            "recordings are held by their expected flags.",
            file=sys.stderr,
        )
        return CANNOT_RUN
    if args.write_baseline:
        BASELINE.write_text(json.dumps(sc.baseline_of(card), indent=2) + "\n", encoding="utf-8")
        print(f"baseline: {card.total} -> {BASELINE.relative_to(ROOT)}")
    shown = directory.relative_to(ROOT) if directory.is_relative_to(ROOT) else directory
    meta = [f"Recorded transcripts: `{shown}`"]
    text = sc.render(card, title="Simulated calls (recorded)", meta=meta)
    return _emit(args, text, f"recorded-{agent.holder}")


async def _judge_pairs(live: Live, runs: list[list[sc.Recording]], notes: list[str]) -> str:
    from scripts.call_sim import judge as judging
    from scripts.call_sim.simulate import Spend

    grader = judging.judge_leg(live.key, live.model)
    spend = Spend()
    lines = ["", "## AI judge (UNCALIBRATED; both orders averaged; +1 = A better)", ""]
    by_b = {r.persona: r for r in runs[1]}
    for a in runs[0]:
        b = by_b.get(a.persona)
        if b is None:
            continue
        votes = await judging.prefer(a, b, grader, spend)
        lines.append(
            f"- {a.persona}: "
            + ", ".join(f"{k} {'-' if v is None else f'{v:+.1f}'}" for k, v in votes.items())
        )
    if not grader.other_family:
        notes.append(judging.UNCONTROLLED)
    return "\n".join(lines) + "\n"


def _emit(args: argparse.Namespace, text: str, name: str, *, tally: sc.Tally | None = None) -> int:
    print(text)
    if not args.no_report:
        path = write_report(text, name, args.out)
        print(f"report: {path}")
        if tally is not None:
            counts = path.with_suffix(".json")
            counts.write_text(json.dumps(sc.tally_json(tally), indent=2) + "\n", encoding="utf-8")
            print(f"counts: {counts}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.release:
        args.live = args.gate = True
        args.personas = args.personas or RELEASE_PERSONAS
        args.runs = max(args.runs, RELEASE_RUNS)
    if args.judge and not args.live:
        print("--judge needs --live: the AI judge never runs in CI.", file=sys.stderr)
        return CANNOT_RUN
    if (args.gate or args.write_live_baseline or args.runs > 1) and not args.live:
        print(
            "--gate, --runs and --write-live-baseline read live runs; CI's gate is the "
            "recorded baseline (tests/call_sim_test.py).",
            file=sys.stderr,
        )
        return CANNOT_RUN
    if args.runs < 1:
        print("--runs must be at least 1.", file=sys.stderr)
        return CANNOT_RUN
    try:
        return asyncio.run(run(args))
    except (ValueError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        return CANNOT_RUN


if __name__ == "__main__":
    raise SystemExit(main())
