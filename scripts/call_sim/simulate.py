"""A simulated call: a model plays the persona, the agent model answers on our composed prompt.

The agent side is one chat completion per turn on the in-call model (`Settings.
thinnest_own_model_default`) over our Google key, through the transport the platform's other
model calls use (`apps/workers/chat.complete`), with the agent's reply ceiling and no
temperature, as the engine is sent none (`scripts/register_eval`). A tool the agent calls is
answered with a simulated result: the do-not-call and call-back actions say they were recorded,
the knowledge search returns the holder's pinned facts. The caller side is the same model told
to play the persona in the call's language; silence and speech-to-text junk are injected on the
persona's fixed turns (`personas`).

After the call, the step reading is asked once of the same model with the post-call judge's own
request and evidence check (`workers/step_progress.request_text`, `checked`), so the reading a
recording carries is the one the call page would show.

Not the voice platform: no speech, no interruptions, no timing, and the step list merged as text
rather than by ThinnestAI's own step handling. Each run is capped (`MAX_CALLER_TURNS`, the
caller's and the agent's reply ceilings, `--max-inr`).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import httpx
from apps.api.reliability.engine_actions import ACTION_NAMES, CALLBACK, OPT_OUT
from apps.workers.chat import (
    ChatLeg,
    ChatMessage,
    ChatOutcome,
    TokenUsage,
    complete,
    replayed_tool_call,
)
from calevate_shared.calling_window import IST
from calevate_shared.engine import google_openai_compat_base_url
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import ExtractionSchemaSpec
from calevate_shared.languages import find_language

from scripts.call_sim.agent import AgentUnderTest
from scripts.call_sim.personas import GARBLE, SILENCE, Persona
from scripts.call_sim.scorecard import Recording, SimTurn

MAX_CALLER_TURNS: Final = 12
#: A turn may call tools at most this many rounds before it must speak.
MAX_TOOL_ROUNDS: Final = 2
CALLER_MAX_TOKENS: Final = 80
JUDGE_MAX_TOKENS: Final = 3_000
TIMEOUT_S: Final = 40.0
RETRIES: Final = 3
#: What the caller model says to hang up.
HANG_UP: Final = "<END>"

Ask = Callable[
    [Sequence[ChatMessage], int, Sequence[dict[str, Any]] | None], Awaitable[ChatOutcome]
]


def google_ask(api_key: str, model: str, *, json_mode: bool = False) -> Ask:
    leg = ChatLeg(
        url=f"{google_openai_compat_base_url()}/chat/completions",
        api_key=api_key,
        wire_model=model,
        dialect="google",
    )

    async def ask(
        messages: Sequence[ChatMessage], max_tokens: int, tools: Sequence[dict[str, Any]] | None
    ) -> ChatOutcome:
        for attempt in range(RETRIES):
            try:
                return await complete(
                    leg,
                    messages,
                    timeout_s=TIMEOUT_S,
                    max_tokens=max_tokens,
                    tools=tools or None,
                    response_format={"type": "json_object"} if json_mode else None,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (429, 500, 503) or attempt == RETRIES - 1:
                    raise
            await asyncio.sleep(2 ** (attempt + 1))
        raise RuntimeError("unreachable")

    return ask


@dataclass(slots=True)
class Spend:
    """Tokens across a run, priced at the end by the caller (`eval_calls`)."""

    tokens_in: int = 0
    tokens_out: int = 0
    by_model: dict[str, list[int]] = field(default_factory=dict)

    def add(self, model: str, usage: TokenUsage | None) -> None:
        if usage is None:
            return
        row = self.by_model.setdefault(model, [0, 0])
        row[0] += usage.prompt_tokens
        row[1] += usage.output_tokens
        self.tokens_in += usage.prompt_tokens
        self.tokens_out += usage.output_tokens


def caller_brief(persona: Persona, agent: AgentUnderTest) -> str:
    language = find_language(agent.language)
    spoken = language.english_name if language is not None else agent.language
    who = f" Your name is {agent.contact_name}." if agent.contact_name else ""
    return (
        "You are a person on a phone call; the other side is a business's phone agent. "
        f"Speak only {spoken}, the way people talk on the phone: short, everyday words, the "
        f"way speech-to-text writes them.{who} You are this person: {persona.brief} "
        "Reply with only the words you say, one short line, no stage directions. "
        f"When the call is over for you, reply {HANG_UP}."
    )


def _tool_result(name: str, facts: Sequence[tuple[str, str]]) -> str:
    if name == ACTION_NAMES[OPT_OUT]:
        return json.dumps({"status": "recorded", "say": "Their number is removed."})
    if name == ACTION_NAMES[CALLBACK]:
        return json.dumps({"status": "proposed", "say": "Read the time back and ask them."})
    if "knowledge" in name or "search" in name:
        return json.dumps({"results": [f"{q} {a}" for q, a in facts] or ["No match."]})
    return json.dumps({"status": "done"})


async def _agent_turn(
    agent: AgentUnderTest, history: list[ChatMessage], ask: Ask, spend: Spend, model: str
) -> tuple[str, tuple[str, ...]]:
    tools: list[str] = []
    for _round in range(MAX_TOOL_ROUNDS + 1):
        offered = agent.tools if _round < MAX_TOOL_ROUNDS else ()
        outcome = await ask(history, agent.max_tokens, offered)
        spend.add(model, outcome.usage)
        if not outcome.tool_calls:
            history.append({"role": "assistant", "content": outcome.content})
            return outcome.content.strip(), tuple(tools)
        history.append(
            {
                "role": "assistant",
                "content": outcome.content or None,
                "tool_calls": [replayed_tool_call(c) for c in outcome.tool_calls],
            }
        )
        for call in outcome.tool_calls:
            tools.append(call.name)
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": _tool_result(call.name, agent.facts),
                }
            )
    return "", tuple(tools)


async def _caller_line(
    persona: Persona,
    agent: AgentUnderTest,
    turns: Sequence[SimTurn],
    ask: Ask,
    spend: Spend,
    model: str,
) -> str:
    messages: list[ChatMessage] = [{"role": "system", "content": caller_brief(persona, agent)}]
    for turn in turns:
        role = "assistant" if turn.speaker == "caller" else "user"
        messages.append({"role": role, "content": turn.text or SILENCE})
    outcome = await ask(messages, CALLER_MAX_TOKENS, None)
    spend.add(model, outcome.usage)
    return " ".join(outcome.content.split())


async def simulate(
    persona: Persona,
    agent: AgentUnderTest,
    *,
    agent_ask: Ask,
    caller_ask: Ask,
    spend: Spend,
    model: str,
    caller_model: str,
    max_turns: int = MAX_CALLER_TURNS,
) -> Recording:
    turns: list[SimTurn] = []
    history: list[ChatMessage] = [{"role": "system", "content": agent.system}]
    if agent.direction == "outbound":
        # On a placed call the person speaks first ("Hello"), then the greeting.
        turns.append(SimTurn("caller", "Hello."))
    turns.append(SimTurn("agent", agent.first_words))
    history.append({"role": "assistant", "content": agent.first_words})
    for n in range(1, max_turns + 1):
        if n in persona.silent_turns:
            said = SILENCE
        elif n in persona.garbled_turns:
            said = GARBLE[persona.garbled_turns.index(n) % len(GARBLE)]
        else:
            said = await _caller_line(persona, agent, turns, caller_ask, spend, caller_model)
        if not said or HANG_UP in said:
            break
        turns.append(SimTurn("caller", said))
        history.append({"role": "user", "content": said})
        reply, tools = await _agent_turn(agent, history, agent_ask, spend, model)
        turns.append(SimTurn("agent", reply, tools))
    return Recording(
        persona=persona.key,
        holder=agent.holder,
        language=agent.language,
        direction=agent.direction,
        source=f"live: {model} (caller {caller_model}), {datetime.now(IST):%Y-%m-%d}",
        turns=tuple(turns),
        prompt_sha=agent.prompt_sha,
        contact_name=agent.contact_name,
        prior_contact=agent.prior_contact,
    )


async def read_steps(
    rec: Recording, agent: AgentUnderTest, ask: Ask, spend: Spend, model: str
) -> Recording:
    """The post-call step reading of a simulated call, by the judge's own request and checks."""
    from apps.workers import step_progress as judge

    if agent.script is None:
        return rec
    turns = [
        TranscriptTurn(call_id="call-sim", idx=n, speaker=t.speaker, text=t.text or SILENCE)
        for n, t in enumerate(rec.turns, 1)
    ]
    lines = judge.redacted_lines(turns)
    spec = ExtractionSchemaSpec(fields=[])
    messages: list[ChatMessage] = [
        {"role": "system", "content": judge.ASK + " Answer as one JSON object."},
        {"role": "user", "content": judge.request_text(agent.script, lines, spec)},
    ]
    outcome = await ask(messages, JUDGE_MAX_TOKENS, None)
    spend.add(model, outcome.usage)
    try:
        raw = json.loads(outcome.content)
    except json.JSONDecodeError:
        return rec
    if not isinstance(raw, dict):
        return rec
    progress = judge.checked(raw, names=judge.step_names(agent.script), lines=lines, spec=spec)
    return replace(rec, progress=progress)


def price(spend: Spend, rates: Callable[[str], tuple[Decimal, Decimal]]) -> Decimal:
    """₹ for the run's tokens; `rates` gives (input, output) ₹ per 1,000 tokens for a model."""
    total = Decimal(0)
    for model, (tokens_in, tokens_out) in spend.by_model.items():
        rate_in, rate_out = rates(model)
        total += (Decimal(tokens_in) * rate_in + Decimal(tokens_out) * rate_out) / Decimal(1000)
    return total


__all__ = [
    "HANG_UP",
    "MAX_CALLER_TURNS",
    "Ask",
    "Spend",
    "caller_brief",
    "google_ask",
    "price",
    "read_steps",
    "simulate",
]
