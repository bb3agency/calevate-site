"""Pip's tool-choice eval: does the first model turn call the right tool? (D-779)

    make copilot-eval PROVIDER=google MODEL=gemini-2.5-flash-lite
    uv run python -m scripts.copilot_tool_eval --provider=google --model=<id> [--record=out.json]
    uv run python -m scripts.copilot_tool_eval --provider=azure
    uv run python -m scripts.copilot_tool_eval --replay=out.json     # rescore a recorded run
    uv run python -m scripts.copilot_tool_eval                        # oracle: checks the fixture

Each case in `tests/fixtures/copilot_tool_choice.json` is one question on one screen. The
harness builds the realm's real message list and tool array (`service.build_messages`,
`service.tool_array`), sends ONE turn through the production request
(`service.streamed_turn`: same temperature, `tool_choice` and token ceiling), executes
nothing, and scores the tool names the model chose.

What a case scores:

- **right**: every call is in `expect`, everything in `expect_all` was called, or no call
  at all where `none_ok` allows answering in words.
- **wrong_fill**: `set_fields` called where the case does not expect it. The failure the
  prompt guards hardest, so it is counted on its own.
- **forbidden**: a tool the case names in `forbid` was called.
- **missed**: no tool was called where one was required.
- **unwanted**: a tool was called on a case that wants words only.

Only the FIRST turn is scored. Later turns need the tools executed against a database, and
a question's correct first move is what the tool array and the prompt decide; turns used
per question are therefore not measured here.

The oracle (default, no credential, runs in CI through `tests/copilot_tool_eval_test.py`)
answers with each case's own expectation. It proves the fixture is consistent with the live
tool arrays and that the scorer works; it says nothing about a model. A provider with no
credential refuses with exit code 2 rather than scoring as a model that chose nothing.

The output names case ids, kinds and tool names only. Arguments are never printed or
recorded, because a real model composes them from screen text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from apps.api.copilot import service
from apps.api.copilot.prompt import SET_FIELDS_TOOL_NAME, assert_screen_fits, render_screen
from apps.api.copilot.schemas import CopilotAskIn, CopilotRealm
from apps.workers.chat import TokenUsage
from apps.workers.extraction import AZURE_PROVIDER, GOOGLE_PROVIDER

FIXTURE: Final = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "copilot_tool_choice.json"
)

ORACLE: Final = "oracle"
CANNOT_RUN: Final = 2

#: What one model turn chose: the tool names, in call order, and what it cost.
Choice = tuple[tuple[str, ...], TokenUsage | None]
ChooseTurn = Callable[["Case"], Awaitable[Choice]]


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    realm: CopilotRealm
    kind: str
    payload: CopilotAskIn
    expect: frozenset[str]
    expect_all: frozenset[str]
    none_ok: bool
    forbid: frozenset[str]


@dataclass(slots=True)
class Score:
    case: Case
    calls: tuple[str, ...]
    failures: list[str] = field(default_factory=list)

    @property
    def right(self) -> bool:
        return not self.failures


def load_cases(path: Path = FIXTURE) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))["cases"]
    return [
        Case(
            id=row["id"],
            realm=row["realm"],
            kind=row["kind"],
            payload=CopilotAskIn.model_validate(
                {
                    "screen": {"route": row["route"], "title": row["title"], "realm": row["realm"]},
                    "question": row["question"],
                    "fields": row.get("fields", []),
                    "facts": row.get("facts", []),
                }
            ),
            expect=frozenset(row["expect"]),
            expect_all=frozenset(row.get("expect_all", [])),
            none_ok=bool(row.get("none_ok", False)),
            forbid=frozenset(row.get("forbid", [])),
        )
        for row in raw
    ]


def offered(realm: CopilotRealm) -> frozenset[str]:
    return frozenset(tool["function"]["name"] for tool in service.tool_array(realm))


def fixture_problems(cases: Sequence[Case]) -> list[str]:
    """A fixture that names a tool its realm does not offer would score every model wrong
    on it, so the fixture is checked against the live arrays before anything is scored."""
    problems = []
    ids = Counter(case.id for case in cases)
    problems += [f"{case_id}: duplicate id" for case_id, n in ids.items() if n > 1]
    for case in cases:
        names = case.expect | case.expect_all | case.forbid
        problems += [
            f"{case.id}: {case.realm} realm offers no `{n}`"
            for n in sorted(names - offered(case.realm))
        ]
        if not case.expect and not case.none_ok:
            problems.append(f"{case.id}: expects no tool but does not allow an answer in words")
        if case.expect & case.forbid:
            problems.append(f"{case.id}: a tool is both expected and forbidden")
        if not case.expect_all <= case.expect:
            problems.append(f"{case.id}: expect_all names a tool outside expect")
        assert_screen_fits(render_screen(case.payload))
    return problems


def score(case: Case, calls: Sequence[str]) -> Score:
    result = Score(case=case, calls=tuple(calls))
    called = set(calls)
    if not called:
        if not case.none_ok:
            result.failures.append("missed")
        return result
    if SET_FIELDS_TOOL_NAME in called and SET_FIELDS_TOOL_NAME not in case.expect:
        result.failures.append("wrong_fill")
    if called & case.forbid:
        result.failures.append("forbidden")
    if not case.expect:
        result.failures.append("unwanted")
    elif not called <= case.expect or not case.expect_all <= called:
        result.failures.append("wrong_tool")
    return result


def oracle(case: Case) -> tuple[str, ...]:
    """The expectation itself: the cheapest choice the case scores as right."""
    if case.expect_all:
        return tuple(sorted(case.expect_all))
    if case.none_ok or not case.expect:
        return ()
    return (sorted(case.expect)[0],)


def model_turn(provider: str, model: str | None) -> ChooseTurn | None:
    """One production turn on a named leg, or None when this machine holds no credential."""
    leg = service.chat_leg(provider, model=model)
    if leg is None:
        return None

    async def choose(case: Case) -> Choice:
        messages = service.build_messages(case.payload, "", case.realm)
        outcome = None
        async for event in service.streamed_turn(leg, messages, service.tool_array(case.realm)):
            outcome = event.outcome or outcome
        if outcome is None:
            return (), None
        return tuple(call.name for call in outcome.tool_calls), outcome.usage

    return choose


async def oracle_turn(case: Case) -> Choice:
    return oracle(case), None


def replay_turn(path: Path) -> ChooseTurn:
    recorded: Mapping[str, Sequence[str]] = json.loads(path.read_text(encoding="utf-8"))["calls"]

    async def choose(case: Case) -> Choice:
        return tuple(recorded.get(case.id, ())), None

    return choose


async def run(cases: Sequence[Case], choose: ChooseTurn) -> tuple[list[Score], list[TokenUsage]]:
    scores, usage = [], []
    for case in cases:
        calls, spent = await choose(case)
        scores.append(score(case, calls))
        if spent is not None:
            usage.append(spent)
    return scores, usage


def render(scores: Sequence[Score], usage: Sequence[TokenUsage], label: str) -> str:
    right = sum(s.right for s in scores)
    kinds = Counter(f for s in scores for f in s.failures)
    lines = [
        f"Pip tool-choice eval: {label}",
        f"right {right}/{len(scores)} ({100 * right / max(len(scores), 1):.0f}%)",
        "failures: " + (", ".join(f"{k}={n}" for k, n in sorted(kinds.items())) or "none"),
    ]
    by_kind: dict[str, list[Score]] = {}
    for s in scores:
        by_kind.setdefault(f"{s.case.realm}/{s.case.kind}", []).append(s)
    lines += [
        f"  {group}: {sum(s.right for s in group_scores)}/{len(group_scores)}"
        for group, group_scores in sorted(by_kind.items())
    ]
    if usage:
        prompt = sum(u.prompt_tokens for u in usage)
        cached = sum(u.cached_prompt_tokens for u in usage)
        output = sum(u.output_tokens for u in usage)
        lines.append(
            f"tokens: prompt={prompt} cached={cached} output={output} over {len(usage)} turns"
        )
    lines += [
        f"FAIL {s.case.id} [{','.join(s.failures)}] called={list(s.calls)} "
        f"expected={sorted(s.case.expect)}"
        for s in scores
        if not s.right
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score Pip's first-turn tool choice.")
    parser.add_argument(
        "--provider", default=ORACLE, choices=(ORACLE, GOOGLE_PROVIDER, AZURE_PROVIDER)
    )
    parser.add_argument("--model", help="the Gemini model id (google provider)")
    parser.add_argument("--replay", type=Path, help="rescore the calls recorded by --record")
    parser.add_argument("--record", type=Path, help="write the chosen tool names to this file")
    parser.add_argument("--only", choices=("client", "admin"), help="one realm only")
    parser.add_argument("--min-right", type=float, help="exit 1 below this share right (0-1)")
    args = parser.parse_args(argv)

    cases = [c for c in load_cases() if args.only in (None, c.realm)]
    problems = fixture_problems(cases)
    if problems:
        print("fixture is inconsistent with the tool arrays:\n" + "\n".join(problems))
        return CANNOT_RUN

    if args.replay is not None:
        choose, label = replay_turn(args.replay), f"replay of {args.replay.name}"
    elif args.provider == ORACLE:
        choose, label = oracle_turn, "oracle (fixture check, no model)"
    else:
        if args.provider == GOOGLE_PROVIDER and not args.model:
            print("--provider=google needs --model=<gemini id>")
            return CANNOT_RUN
        live = model_turn(args.provider, args.model)
        if live is None:
            print(f"CANNOT RUN: no credential for `{args.provider}` on this machine")
            return CANNOT_RUN
        choose, label = live, f"{args.provider} {args.model or '(deployment)'}"

    scores, usage = asyncio.run(run(cases, choose))
    print(render(scores, usage, label))
    if args.record is not None:
        recorded: dict[str, Any] = {
            "label": label,
            "calls": {s.case.id: list(s.calls) for s in scores},
        }
        args.record.write_text(json.dumps(recorded, indent=1, ensure_ascii=False) + "\n", "utf-8")
    share = sum(s.right for s in scores) / max(len(scores), 1)
    return 1 if args.min_right is not None and share < args.min_right else 0


if __name__ == "__main__":
    sys.exit(main())
