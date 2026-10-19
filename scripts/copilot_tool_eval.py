"""Pip's tool-choice eval: does the first model turn call the right tool? (D-779, D-816)

    make copilot-eval PROVIDER=google MODEL=gemini-2.5-flash-lite
    uv run python -m scripts.copilot_tool_eval --provider=google --model=<id> [--record=out.json]
    uv run python -m scripts.copilot_tool_eval --provider=azure
    uv run python -m scripts.copilot_tool_eval --replay=out.json     # rescore a recorded run
    uv run python -m scripts.copilot_tool_eval                        # oracle: checks the fixture

    # the operator's LIVE run: whole answers, real reads, real money (D-816)
    uv run python -m scripts.copilot_tool_eval --live --spend --tenant=<demo account uuid> \
        --record=before.json
    uv run python -m scripts.copilot_tool_eval --compare before.json after.json

Each case in `tests/fixtures/copilot_tool_choice.json` is one question on one screen, after
the earlier turns its optional `history` replays (D-832: a follow-up must not redo what an
earlier message asked for). The
harness builds the surface's real message list and tool array (`service.build_messages`,
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
a question's correct first move is what the tool array and the prompt decide.

The score is the model's choice. Beside it, each call is put through the checks the server
makes without a database (`service.validate_fill`, including D-833's quote of the latest
message, and each write tool's `grounded` check): a wrong call the server refuses goes back
to the model as a refusal and reaches nobody, so the report counts those apart
(`refused_by_server`). For such a call the harness then does what the production loop does,
hands the refusal back as the tool result (`service.refused_fill_turn`,
`service.refused_proposal_turn`) and asks once more, and scores that turn as `then`: "right
in what the person sees" counts a first choice that was right or a refused one followed by a
right turn.

**THE LIVE RUN** answers each question in full through `service.run_copilot`, the production
loop, on the production model tiers (`model_tiers.route_tier`), with the read tools executed
against this deployment's database — `--tenant` names the account the client cases and the
admin `account_open` cases read (use a demo account). No principal is passed, so every write
tool refuses inside itself and nothing is changed. It spends real money, so it refuses
without `--spend`, prints its own cost, and never runs in CI or pytest. Per question it
records the tools the answer used, the answer (through `redact()`), input, cached and output
tokens and the rupee cost at the attested rates; `--compare` prints two such records side by
side. Stdout carries case ids, tool names, counts and rupees only (hard rule 6).

The oracle (default, no credential, runs in CI through `tests/copilot_tool_eval_test.py`)
answers with each case's own expectation. It proves the fixture is consistent with the live
tool arrays and that the scorer works; it says nothing about a model. A provider with no
credential refuses with exit code 2 rather than scoring as a model that chose nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx
from apps.api.billing.ai_quota import assist_ledger_rows
from apps.api.copilot import model_tiers, service, write_tools
from apps.api.copilot.prompt import SET_FIELDS_TOOL_NAME, assert_screen_fits, render_screen
from apps.api.copilot.schemas import CopilotAskIn, CopilotRealm
from apps.api.core.settings import get_settings
from apps.api.ops.pricing_snapshot import install_pricing_readers, refresh_pricing_snapshot
from apps.workers import chat
from apps.workers.chat import TokenUsage
from apps.workers.extraction import AZURE_PROVIDER, GOOGLE_PROVIDER
from apps.workers.redaction import redact

FIXTURE: Final = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "copilot_tool_choice.json"
)

ORACLE: Final = "oracle"
CANNOT_RUN: Final = 2
#: Attempts per question when the vendor answers 429 or 5xx, with 2 s and 4 s pauses between.
RETRIES: Final = 3
TRANSIENT: Final = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class Choice:
    """What the model chose for one case: the tool names in call order, the names of the
    calls the server would refuse, and, when it refused one, what the model called on the
    turn after the refusal (`then`; `()` is an answer in words)."""

    calls: tuple[str, ...]
    usage: tuple[TokenUsage, ...] = ()
    refused: tuple[str, ...] = ()
    then: tuple[str, ...] | None = None


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
    #: Whether a client's account is open, which decides the admin tool surface
    #: (`service.tool_array(account_open=)`, D-816). Always True for a client case.
    account_open: bool = True


@dataclass(slots=True)
class Score:
    case: Case
    calls: tuple[str, ...]
    failures: list[str] = field(default_factory=list)
    refused: tuple[str, ...] = ()
    then: tuple[str, ...] | None = None

    @property
    def right(self) -> bool:
        return not self.failures

    @property
    def caught(self) -> bool:
        """Wrong, but every call the case did not expect is one the server refuses."""
        unexpected = set(self.calls) - self.case.expect
        return not self.right and bool(unexpected) and unexpected <= set(self.refused)

    @property
    def recovered(self) -> bool:
        """Caught, and the turn after the refusal was right: what the person ends up seeing."""
        return self.caught and self.then is not None and score(self.case, self.then).right


def load_cases(path: Path = FIXTURE) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))["cases"]
    return [
        Case(
            id=row["id"],
            realm=row["realm"],
            kind=row["kind"],
            payload=CopilotAskIn.model_validate(
                {
                    "screen": {
                        "route": row["route"],
                        "title": row["title"],
                        "realm": row["realm"],
                        "saves": row.get("saves"),
                        "live_step": row.get("live_step"),
                    },
                    "question": row["question"],
                    "fields": row.get("fields", []),
                    "facts": row.get("facts", []),
                    "history": row.get("history", []),
                }
            ),
            expect=frozenset(row["expect"]),
            expect_all=frozenset(row.get("expect_all", [])),
            none_ok=bool(row.get("none_ok", False)),
            forbid=frozenset(row.get("forbid", [])),
            account_open=row["realm"] == "client" or bool(row.get("account_open", False)),
        )
        for row in raw
    ]


def tools_for(case: Case) -> list[dict[str, Any]]:
    return service.tool_array(case.realm, account_open=case.account_open)


def offered(case: Case) -> frozenset[str]:
    return frozenset(tool["function"]["name"] for tool in tools_for(case))


def fixture_problems(cases: Sequence[Case]) -> list[str]:
    """A fixture that names a tool its surface does not offer would score every model wrong
    on it, so the fixture is checked against the live arrays before anything is scored."""
    problems = []
    ids = Counter(case.id for case in cases)
    problems += [f"{case_id}: duplicate id" for case_id, n in ids.items() if n > 1]
    for case in cases:
        names = case.expect | case.expect_all | case.forbid
        problems += [
            f"{case.id}: {case.realm} realm offers no `{n}`" for n in sorted(names - offered(case))
        ]
        if not case.expect and not case.none_ok:
            problems.append(f"{case.id}: expects no tool but does not allow an answer in words")
        if case.expect & case.forbid:
            problems.append(f"{case.id}: a tool is both expected and forbidden")
        if not case.expect_all <= case.expect:
            problems.append(f"{case.id}: expect_all names a tool outside expect")
        assert_screen_fits(render_screen(case.payload))
    return problems


def server_refusal(case: Case, call: chat.ToolCall) -> tuple[str, ...]:
    """The reasons the server's database-free checks refuse this call on this case; empty
    when they accept it."""
    if call.name == SET_FIELDS_TOOL_NAME:
        try:
            service.validate_fill(case.payload, call.arguments or "")
        except service.FillRefusedError as refused:
            return tuple(refused.reasons)
        return ()
    try:
        arguments = json.loads(call.arguments or "")
    except ValueError:
        return ("the tool call was not valid JSON",)
    if not isinstance(arguments, dict):
        return ("the tool call was not an object",)
    said = service.person_said(case.payload)
    problem = write_tools.grounding_problem(call.name, arguments, said)
    return () if problem is None else (problem,)


def server_refuses(case: Case, call: chat.ToolCall) -> bool:
    return bool(server_refusal(case, call))


def after_refusal(
    messages: Sequence[chat.ChatMessage],
    outcome: chat.ChatOutcome,
    call: chat.ToolCall,
    reasons: Sequence[str],
) -> list[chat.ChatMessage]:
    """The conversation the production loop sends next, with the refusal as the tool result."""
    if call.name == SET_FIELDS_TOOL_NAME:
        return service.refused_fill_turn(messages, outcome, call, reasons)
    return service.refused_proposal_turn(messages, outcome, call, "; ".join(reasons))


def score(
    case: Case,
    calls: Sequence[str],
    refused: Sequence[str] = (),
    then: Sequence[str] | None = None,
) -> Score:
    result = Score(
        case=case,
        calls=tuple(calls),
        refused=tuple(refused),
        then=None if then is None else tuple(then),
    )
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


async def _load_console_settings() -> None:
    """The keys an operator saved on the ops console, as Pip reads them in production. On a
    host whose Gemini key lives only there, `chat_leg` would otherwise find no credential."""
    from apps.api.core.platform_config import refresh

    await refresh(force=True)


def model_turn(provider: str, model: str | None) -> ChooseTurn | None:
    """One production turn on a named leg, or None when this machine holds no credential."""
    leg = service.chat_leg(provider, model=model)
    if leg is None:
        return None

    async def one(case: Case, messages: Sequence[chat.ChatMessage]) -> chat.ChatOutcome | None:
        outcome = None
        async for event in service.streamed_turn(leg, messages, tools_for(case)):
            outcome = event.outcome or outcome
        return outcome

    async def turn(case: Case) -> Choice:
        messages = service.build_messages(case.payload, "", case.realm)
        outcome = await one(case, messages)
        if outcome is None:
            return Choice(calls=())
        calls = tuple(call.name for call in outcome.tool_calls)
        refusals = [(call, server_refusal(case, call)) for call in outcome.tool_calls]
        refused = tuple(call.name for call, reasons in refusals if reasons)
        usage: tuple[TokenUsage, ...] = (outcome.usage,) if outcome.usage else ()
        first = next(((call, reasons) for call, reasons in refusals if reasons), None)
        if first is None:
            return Choice(calls=calls, usage=usage)
        # The production loop hands the refusal back and asks again, so the person sees
        # the second turn, not the first. One more turn is scored, as `then`.
        retry = await one(case, after_refusal(messages, outcome, *first))
        if retry is None:
            return Choice(calls=calls, usage=usage, refused=refused, then=())
        then = tuple(call.name for call in retry.tool_calls)
        usage += (retry.usage,) if retry.usage else ()
        return Choice(calls=calls, usage=usage, refused=refused, then=then)

    async def choose(case: Case) -> Choice:
        # A rate limit or an overloaded model is the vendor's moment, not the model's
        # choice: retried with backoff, as register_eval does, rather than ending the run.
        for attempt in range(RETRIES):
            try:
                return await turn(case)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in TRANSIENT or attempt == RETRIES - 1:
                    raise
            await asyncio.sleep(2 ** (attempt + 1))
        raise RuntimeError("unreachable")

    return choose


async def oracle_turn(case: Case) -> Choice:
    return Choice(calls=oracle(case))


def replay_turn(path: Path) -> ChooseTurn:
    body = json.loads(path.read_text(encoding="utf-8"))
    recorded: Mapping[str, Sequence[str]] = body["calls"]
    refused: Mapping[str, Sequence[str]] = body.get("refused", {})
    then: Mapping[str, Sequence[str]] = body.get("then", {})

    async def choose(case: Case) -> Choice:
        return Choice(
            calls=tuple(recorded.get(case.id, ())),
            refused=tuple(refused.get(case.id, ())),
            then=tuple(then[case.id]) if case.id in then else None,
        )

    return choose


async def run(cases: Sequence[Case], choose: ChooseTurn) -> tuple[list[Score], list[TokenUsage]]:
    scores: list[Score] = []
    usage: list[TokenUsage] = []
    for case in cases:
        chosen = await choose(case)
        scores.append(score(case, chosen.calls, chosen.refused, chosen.then))
        usage.extend(chosen.usage)
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
    wrong = [s for s in scores if not s.right]
    if wrong:
        lines.append(
            f"refused by the server, reaching nobody: {sum(s.caught for s in wrong)}"
            f"/{len(wrong)} wrong"
        )
    asked_again = [s for s in wrong if s.then is not None]
    if asked_again:
        ended_right = right + sum(s.recovered for s in wrong)
        lines += [
            f"right on the turn after the refusal: {sum(s.recovered for s in asked_again)}"
            f"/{len(asked_again)}",
            f"right in what the person sees: {ended_right}/{len(scores)}",
        ]
    lines += [
        f"FAIL {s.case.id} [{','.join(s.failures)}] called={list(s.calls)} "
        f"expected={sorted(s.case.expect)}"
        + (f" refused_by_server={list(s.refused)}" if s.refused else "")
        + (f" then={list(s.then)}" if s.then is not None else "")
        + (" (recovered)" if s.recovered else "")
        for s in wrong
    ]
    return "\n".join(lines)


# --- the live run (D-816) ---------------------------------------------------------------


@dataclass(slots=True)
class LiveAnswer:
    """One question answered in full. `cost_inr` is None when a model on it is unpriced."""

    case_id: str
    tools: list[str]
    answer: str
    tokens_in: int
    tokens_cached: int | None
    tokens_out: int
    cost_inr: Decimal | None
    error: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "tools": self.tools,
            "answer": self.answer,
            "tokens_in": self.tokens_in,
            "tokens_cached": self.tokens_cached,
            "tokens_out": self.tokens_out,
            "cost_inr": None if self.cost_inr is None else str(self.cost_inr),
            "error": self.error,
        }


def spend_cost(usage: TokenUsage, model: str) -> Decimal | None:
    """What the ledger would record for this usage, at the attested rates; None if unpriced."""

    try:
        rows = assist_ledger_rows(
            model=model,
            tokens_in=usage.prompt_tokens,
            tokens_out=usage.output_tokens,
            cached_tokens_in=usage.cached_tokens_in,
        )
    except ValueError:
        return None
    return sum((qty * price for _, qty, price in rows), Decimal("0"))


async def live_answer(case: Case, tenant_id: UUID | None) -> LiveAnswer:
    """One question through `service.run_copilot`, as the route runs it but with no
    principal, so every write tool refuses and nothing changes."""

    tools: list[str] = []
    text: list[str] = []
    usage_in = usage_out = 0
    cached: int | None = 0
    cost: Decimal | None = Decimal("0")
    try:
        async for event in service.run_copilot(
            case.payload,
            tenant_leg=model_tiers.tier_leg(model_tiers.route_tier(case.payload.question)),
            allow_azure=get_settings().copilot_azure_fallback,
            realm=case.realm,
            tool_context=service.ToolContext(
                tenant_id=tenant_id if case.account_open else None,
                role="superadmin" if case.realm == "admin" else "owner",
            ),
        ):
            if event.step is not None and event.step.status == "running":
                tools.append(event.step.tool)
            if event.text is not None:
                text.append(event.text)
            if event.spend is None or event.spend.usage is None:
                continue
            spent = event.spend.usage
            usage_in += spent.prompt_tokens
            usage_out += spent.output_tokens
            cached = (
                None
                if cached is None or spent.cached_tokens_in is None
                else (cached + spent.cached_prompt_tokens)
            )
            model = event.spend.model or get_settings().azure_openai_model
            priced = spend_cost(spent, model)
            cost = None if cost is None or priced is None else cost + priced
    except Exception as failure:  # an operator tool: one failed question must not end the run
        return LiveAnswer(
            case.id, tools, "", usage_in, cached, usage_out, cost, type(failure).__name__
        )
    return LiveAnswer(case.id, tools, redact("".join(text)).text, usage_in, cached, usage_out, cost)


async def live_run(cases: Sequence[Case], tenant_id: UUID | None) -> list[LiveAnswer]:

    install_pricing_readers()
    await refresh_pricing_snapshot()
    answers = []
    for case in cases:
        if case.account_open and tenant_id is None:
            continue
        answers.append(await live_answer(case, tenant_id))
    return answers


def render_live(answers: Sequence[LiveAnswer]) -> str:
    lines = ["case | tools | in | cached | out | ₹"]
    for a in answers:
        cached = "unreported" if a.tokens_cached is None else str(a.tokens_cached)
        cost = "unpriced" if a.cost_inr is None else str(a.cost_inr)
        lines.append(
            f"{a.case_id} | {','.join(a.tools) or '-'} | {a.tokens_in} | {cached} | "
            f"{a.tokens_out} | {cost}{' | ERROR ' + a.error if a.error else ''}"
        )
    priced = [a.cost_inr for a in answers if a.cost_inr is not None]
    lines.append(
        f"total: {len(answers)} questions, ₹{sum(priced, Decimal('0'))} "
        f"({len(answers) - len(priced)} unpriced)"
    )
    return "\n".join(lines)


def render_compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Two live records side by side, per case: tools, tokens in/cached/out and rupees."""
    lines = ["case | tools before -> after | in | cached | out | ₹"]
    for case_id in sorted(set(before["answers"]) | set(after["answers"])):
        b = before["answers"].get(case_id, {})
        a = after["answers"].get(case_id, {})
        lines.append(
            f"{case_id} | {','.join(b.get('tools', []))} -> {','.join(a.get('tools', []))} | "
            f"{b.get('tokens_in')} -> {a.get('tokens_in')} | "
            f"{b.get('tokens_cached')} -> {a.get('tokens_cached')} | "
            f"{b.get('tokens_out')} -> {a.get('tokens_out')} | "
            f"{b.get('cost_inr')} -> {a.get('cost_inr')}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score Pip's first-turn tool choice.")
    parser.add_argument(
        "--provider", default=ORACLE, choices=(ORACLE, GOOGLE_PROVIDER, AZURE_PROVIDER)
    )
    parser.add_argument("--model", help="the Gemini model id (google provider)")
    parser.add_argument("--replay", type=Path, help="rescore the calls recorded by --record")
    parser.add_argument("--record", type=Path, help="write the run to this file")
    parser.add_argument("--only", choices=("client", "admin"), help="one realm only")
    parser.add_argument("--min-right", type=float, help="exit 1 below this share right (0-1)")
    parser.add_argument("--live", action="store_true", help="answer each question in full")
    parser.add_argument("--spend", action="store_true", help="required with --live: it costs money")
    parser.add_argument("--tenant", type=UUID, help="the demo account --live reads")
    parser.add_argument("--compare", type=Path, nargs=2, help="two --live records side by side")
    args = parser.parse_args(argv)

    if args.compare is not None:
        before, after = (json.loads(p.read_text(encoding="utf-8")) for p in args.compare)
        print(render_compare(before, after))
        return 0

    cases = [c for c in load_cases() if args.only in (None, c.realm)]
    problems = fixture_problems(cases)
    if problems:
        print("fixture is inconsistent with the tool arrays:\n" + "\n".join(problems))
        return CANNOT_RUN

    if args.live:
        if not args.spend:
            print("CANNOT RUN: --live answers every question on the paid models; add --spend")
            return CANNOT_RUN
        answers = asyncio.run(live_run(cases, args.tenant))
        print(render_live(answers))
        if args.record is not None:
            body = {"answers": {a.case_id: a.as_record() for a in answers}}
            args.record.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", "utf-8")
        return 0

    if args.replay is not None:
        choose, label = replay_turn(args.replay), f"replay of {args.replay.name}"
    elif args.provider == ORACLE:
        choose, label = oracle_turn, "oracle (fixture check, no model)"
    else:
        if args.provider == GOOGLE_PROVIDER and not args.model:
            print("--provider=google needs --model=<gemini id>")
            return CANNOT_RUN
        asyncio.run(_load_console_settings())
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
            "refused": {s.case.id: list(s.refused) for s in scores if s.refused},
            "then": {s.case.id: list(s.then) for s in scores if s.then is not None},
        }
        args.record.write_text(json.dumps(recorded, indent=1, ensure_ascii=False) + "\n", "utf-8")
    share = sum(s.right for s in scores) / max(len(scores), 1)
    return 1 if args.min_right is not None and share < args.min_right else 0


if __name__ == "__main__":
    sys.exit(main())
