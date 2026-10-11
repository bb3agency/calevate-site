"""Compare in-call language models on one ThinnestAI agent, through its test chat (D-739).

    python -m scripts.compare_in_call_models show --tenant <uuid> --agent <uuid>
    python -m scripts.compare_in_call_models run --tenant <uuid> --agent <uuid> \\
        --agent-takes-no-calls [--models "GPT-OSS 120B,Prana [Voice],GPT-5 Mini,GPT-4.1 Nano"] \\
        [--judge] [--out results.json]

`show` changes nothing: it prints the model the agent holds at ThinnestAI, the agent's own
choice in our database and the ops console's in-call default. That is how to find which
model a past call ran on: ThinnestAI's call object carries no model (get-call.md, the
`CallReport` schema), so the agent's model at the time of the call is the answer, and it
is the one shown here unless somebody changed it since.

`run` puts the agent on each model in turn, talks the standard test callers through the
test chat (`agents/test_conversations.standard_scenarios`: a product question, the four
compliance probes, a vague answer, low interest, a price and quantity, a caller who goes
quiet and, for an outbound agent, "not interested"), scores every reply with the test
loop's hard checks (`hard_check`, which includes `agents/turn_checks`), optionally asks
the AI judge, prints a table with each model's price band and latency as ThinnestAI's
console lists them (`engine/thinnest._MODEL_CONSOLE_READING`, read by the founder 10 Oct
2026), and puts the agent back on the model it started on, whatever happens.

THE AGENT ANSWERS REAL CALLS ON WHATEVER MODEL IT HOLDS, so `run` refuses without
`--agent-takes-no-calls`: use an agent with no number and no running campaign (a copy of
the agent you want to judge). The settings drift sweep may put the agent back on its
published model mid-run; the model is re-read before every conversation and switched again
when it moved. Test chats are billed by ThinnestAI at a rate it does not publish; the judge,
when asked for, spends the dashboard AI chain and is not metered to any client.

Needs the ThinnestAI key, which lives in the ops console: run it inside the api image, where
the console's settings and keys are adopted at start (`runbooks/in-call-model-ear-test.md`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from apps.api.agents.test_conversations import (
    Scenario,
    Turn,
    hard_check,
    load_brief,
    speech_problems,
    standard_scenarios,
)
from apps.api.agents.test_window import send_test_message
from apps.api.core.platform_config import refresh as refresh_platform_config
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.catalogue import CatalogueModel, HoldsCatalogue
from apps.api.engine.test_chat import RunsTestChat
from apps.api.engine.thinnest_agent_model import DEFAULT_MODEL_LABEL, ThinnestAgentModel
from sqlalchemy import text

DEFAULT_MODELS: Final = ("GPT-OSS 120B", "Prana [Voice]", "GPT-5 Mini", "GPT-4.1 Nano")
#: Between test messages: the vendor refuses messages faster than a person types
#: (test-chat.md 429), and the test loop's worker waits the same.
PAUSE_S: Final = 4.0
_BAND: Final = {"none": "no surcharge: the voice's band", "premium": "Premium band ₹2.50/min"}


@dataclass(slots=True)
class ModelResult:
    label: str
    band: str
    latency_ms: int | None
    conversations: int = 0
    hard_failed: int = 0
    problems: Counter[str] = field(default_factory=Counter)
    judged: Counter[str] = field(default_factory=Counter)
    reply_chars: list[int] = field(default_factory=list)
    transcripts: list[dict[str, Any]] = field(default_factory=list)


async def _agent(tenant_id: UUID, agent_id: UUID) -> tuple[str, str, str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref, language_primary, direction, engine_model_id "
                    "FROM agents WHERE id = :aid AND deleted_at IS NULL"
                ),
                {"aid": agent_id},
            )
        ).first()
    if row is None or not row[0]:
        raise SystemExit("No published agent with that id in that tenant.")
    return str(row[0]), str(row[1]), str(row[2]), row[3]


def _models_client() -> ThinnestAgentModel:
    settings = get_settings()
    return ThinnestAgentModel(
        api_key=settings.thinnest_api_key, base_url=settings.thinnest_api_base_url
    )


async def show(tenant_id: UUID, agent_id: UUID) -> int:
    await refresh_platform_config(force=True)
    ref, language, direction, chosen = await _agent(tenant_id, agent_id)
    models = _models_client()
    try:
        held = await models.held(ref)
    finally:
        await models.aclose()
    print(f"agent {agent_id} ({direction}, {language})")
    print(f"  model held at ThinnestAI:       {held or 'none (default or retired)'}")
    print(f"  agent's own choice (our db):    {chosen or 'none'}")
    print(f"  ops console in-call default:    {get_settings().thinnest_in_call_default_model}")
    return 0


async def _converse(
    engine: RunsTestChat, agent_id: UUID, ref: str, scenario: Scenario
) -> list[Turn]:
    session: str | None = None
    turns: list[Turn] = []
    for line in scenario.turns:
        await asyncio.sleep(PAUSE_S)
        reply = await send_test_message(
            engine, agent_id=agent_id, engine_agent_ref=ref, message=line, session=session
        )
        session = reply.session or session
        results = reply.tool_results
        turns.append(
            Turn(
                said=line,
                reply=reply.reply,
                tools=[tool.name for tool in results] or list(reply.tools),
                statuses=[tool.status for tool in results],
                cut_short=reply.failed_part_way,
            )
        )
    return turns


async def _judge(
    tenant_id: UUID, agent_id: UUID, scenarios: list[Scenario], talks: list[list[Turn]]
) -> dict[str, str]:
    from apps.workers.agent_test_ai import conversation_text, judge_conversations

    async with tenant_session(tenant_id) as session:
        brief = await load_brief(session, agent_id)
    texts = [
        conversation_text(s, [(t.said, t.reply, t.tools) for t in turns])
        for s, turns in zip(scenarios, talks, strict=True)
    ]
    answer = await judge_conversations(brief, texts, {s.key for s in scenarios})
    return {key: judged.verdict for key, judged in answer.value.items()}


async def _run_model(
    candidate: CatalogueModel,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    ref: str,
    scenarios: list[Scenario],
    engine: RunsTestChat,
    models: ThinnestAgentModel,
    judge: bool,
    language: str,
) -> ModelResult:
    target = None if candidate.label == DEFAULT_MODEL_LABEL else candidate.model_id
    result = ModelResult(
        label=candidate.label,
        band=_BAND.get(candidate.surcharge or "", "not on record"),
        latency_ms=candidate.console_latency_ms,
    )
    talks: list[list[Turn]] = []
    for scenario in scenarios:
        held = await models.held(ref)
        if held != candidate.model_id and not (target is None and held is None):
            await models.switch(ref, target)
        turns = await _converse(engine, agent_id, ref, scenario)
        talks.append(turns)
        check = hard_check(scenario, turns, language=language)
        result.conversations += 1
        result.hard_failed += check.verdict == "failed"
        result.problems.update(p.kind for p in speech_problems(turns, language=language))
        result.reply_chars += [len(t.reply) for t in turns]
        result.transcripts.append(
            {
                "key": scenario.key,
                "turns": [{"caller": t.said, "agent": t.reply, "tools": t.tools} for t in turns],
                "hard_check": check.reason,
            }
        )
    if judge:
        verdicts = await _judge(tenant_id, agent_id, scenarios, talks)
        result.judged.update(verdicts.values())
    return result


def _table(results: list[ModelResult]) -> str:
    head = (
        "| Model | Price band (console) | Console latency | Hard checks passed | "
        "Shape problems | Judge (passed/needs fix/failed) | Avg reply chars |"
    )
    rows = [head, "|" + "---|" * 7]
    for r in results:
        passed = r.conversations - r.hard_failed
        problems = ", ".join(f"{k} {n}" for k, n in r.problems.most_common()) or "none"
        judged = (
            f"{r.judged['passed']}/{r.judged['needs_fix']}/{r.judged['failed']}"
            if r.judged
            else "not asked"
        )
        avg = round(sum(r.reply_chars) / len(r.reply_chars)) if r.reply_chars else 0
        latency = f"~{r.latency_ms} ms" if r.latency_ms else "not on record"
        rows.append(
            f"| {r.label} | {r.band} | {latency} | {passed}/{r.conversations} | {problems} | "
            f"{judged} | {avg} |"
        )
    return "\n".join(rows)


async def run(
    tenant_id: UUID, agent_id: UUID, labels: list[str], *, judge: bool, out: str | None
) -> int:
    await refresh_platform_config(force=True)
    engine = get_engine()
    if engine.name != "thinnest" or not isinstance(engine, HoldsCatalogue):
        raise SystemExit("The active engine is not ThinnestAI.")
    chat: RunsTestChat = engine  # type: ignore[assignment]
    ref, language, direction, _chosen = await _agent(tenant_id, agent_id)
    catalogue = {m.label: m for m in (await engine.read_catalogue()).models}
    candidates: list[CatalogueModel] = []
    for label in labels:
        model = catalogue.get(label)
        if model is None or not model.call_capable or not model.plan_allows:
            print(f"skipped {label!r}: not a call-capable model on this plan's list")
            continue
        candidates.append(model)
    scenarios = standard_scenarios(language, direction)
    models = _models_client()
    original = await models.held(ref)
    results: list[ModelResult] = []
    try:
        for candidate in candidates:
            print(f"running {candidate.label} ({len(scenarios)} conversations)...", flush=True)
            results.append(
                await _run_model(
                    candidate,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    ref=ref,
                    scenarios=scenarios,
                    engine=chat,
                    models=models,
                    judge=judge,
                    language=language,
                )
            )
    finally:
        await models.switch(ref, original)
        print(f"agent put back on {original or DEFAULT_MODEL_LABEL}")
        await models.aclose()
    print(_table(results))
    if out:
        report = json.dumps(
            [
                {
                    "model": r.label,
                    "band": r.band,
                    "latency_ms": r.latency_ms,
                    "hard_passed": r.conversations - r.hard_failed,
                    "conversations": r.conversations,
                    "problems": dict(r.problems),
                    "judged": dict(r.judged),
                    "transcripts": r.transcripts,
                }
                for r in results
            ],
            ensure_ascii=False,
            indent=2,
        )
        await asyncio.to_thread(Path(out).write_text, report, encoding="utf-8")
        print(f"transcripts written to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--tenant", type=UUID, required=True)
        cmd.add_argument("--agent", type=UUID, required=True)
    runner = sub.choices["run"]
    runner.add_argument("--models", default=",".join(DEFAULT_MODELS))
    runner.add_argument("--judge", action="store_true")
    runner.add_argument("--out")
    runner.add_argument("--agent-takes-no-calls", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "show":
        return asyncio.run(show(args.tenant, args.agent))
    if not args.agent_takes_no_calls:
        parser.error(
            "the agent answers real calls on whatever model it holds while this runs: use an "
            "agent with no number and no running campaign, and pass --agent-takes-no-calls"
        )
    labels = [label.strip() for label in args.models.split(",") if label.strip()]
    return asyncio.run(run(args.tenant, args.agent, labels, judge=args.judge, out=args.out))


if __name__ == "__main__":
    sys.exit(main())
