"""The AI judge, for what no rule reads: register and naturalness. Live only, never in CI.

Everything with one right answer is decided by `scorecard` in code. This scores two criteria a
word list cannot, following the scorecard checklist of `docs/evidence/voice-agent-research-
2026-11-25.md` §D and the judge biases its §A5 names:

- one criterion per score, form-filled, with the evidence quoted BEFORE the score (G-Eval,
  arXiv:2303.16634; Wang et al., arXiv:2305.17926);
- length is penalised in the rubric, never rewarded (Zheng et al., arXiv:2306.05685: verbosity
  bias);
- a comparison asks both orders and averages them (Wang et al.: swapping the order can flip a
  verdict);
- the judge runs on Azure OpenAI where it is configured, a different family from the Gemini
  agent (self-enhancement bias); where it is not, it runs on Gemini and the report says the
  bias is not controlled;
- its scores are not calibrated against founder-labelled calls yet, so the report prints them
  as UNCALIBRATED and they never move the deterministic score or the CI baseline.

Hard rule 6: the quoted evidence stays in memory; a report carries the scores only.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from apps.workers.chat import ChatLeg, ChatMessage, complete
from calevate_shared.engine import azure_openai_base_url

from scripts.call_sim.scorecard import Recording
from scripts.call_sim.simulate import TIMEOUT_S, Ask, Spend, google_ask

CRITERIA: Final[dict[str, str]] = {
    "register": (
        "Does the agent speak the everyday spoken language people use on the phone, not written "
        "or textbook words? Short replies score higher than long ones that say the same."
    ),
    "naturalness": (
        "Does each reply react to what the person just said, without stock fillers repeated "
        "turn after turn, and move the call on one step at a time? Length earns nothing."
    ),
}
_ASK: Final = (
    "You grade the AGENT side of phone calls on one criterion. First copy up to three short "
    "agent lines as evidence, then give a score from 1 (poor) to 5 (excellent). Longer replies "
    'earn no credit. Answer as JSON: {"evidence": [..], "score": n}.'
)
_PAIR_ASK: Final = (
    "You compare the AGENT side of two phone calls with the same caller on one criterion. "
    "First copy up to two short agent lines from each call as evidence, then say which call "
    "is better: 1, 2, or 0 for equal. Longer replies earn no credit. Answer as JSON: "
    '{"evidence_1": [..], "evidence_2": [..], "better": n}.'
)
MAX_TOKENS: Final = 600
UNCONTROLLED: Final = (
    "The judge ran on the agent's own model family (no Azure OpenAI configured): its "
    "self-enhancement bias is not controlled."
)


@dataclass(frozen=True, slots=True)
class Judge:
    ask: Ask
    model: str
    other_family: bool


def judge_leg(gemini_key: str, gemini_model: str) -> Judge:
    """Azure OpenAI where all three credentials are set, else Gemini."""
    from apps.workers.extraction import azure_credentials

    azure = azure_credentials()
    if azure is None:
        return Judge(google_ask(gemini_key, gemini_model, json_mode=True), gemini_model, False)
    resource, key, deployment = azure
    leg = ChatLeg(
        url=f"{azure_openai_base_url(resource)}/chat/completions",
        api_key=key,
        wire_model=deployment,
        dialect="openai",
    )

    async def ask(messages: Sequence[ChatMessage], max_tokens: int, _tools: object) -> object:
        return await complete(
            leg,
            messages,
            timeout_s=TIMEOUT_S,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

    return Judge(ask, deployment, True)  # type: ignore[arg-type]


def _agent_lines(rec: Recording) -> str:
    return "\n".join(
        f"Agent: {t.text}" if t.speaker == "agent" else f"Person: {t.text}" for t in rec.turns
    )


def _json(content: str) -> dict[str, object]:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


async def grade(rec: Recording, judge: Judge, spend: Spend) -> dict[str, int | None]:
    """A 1-5 score per criterion; None where the answer had no evidence or no score."""
    out: dict[str, int | None] = {}
    for name, rubric in CRITERIA.items():
        outcome = await judge.ask(
            [
                {"role": "system", "content": f"{_ASK} Criterion: {rubric}"},
                {"role": "user", "content": _agent_lines(rec)},
            ],
            MAX_TOKENS,
            None,
        )
        spend.add(judge.model, outcome.usage)
        raw = _json(outcome.content)
        score = raw.get("score")
        has_evidence = isinstance(raw.get("evidence"), list) and bool(raw["evidence"])
        out[name] = score if isinstance(score, int) and 1 <= score <= 5 and has_evidence else None
    return out


async def prefer(a: Recording, b: Recording, judge: Judge, spend: Spend) -> dict[str, float | None]:
    """Per criterion, +1 when A is better in both orders, -1 when B is, 0 for a split or a tie:
    the mean of the two orders' verdicts, each read back into A's terms."""
    out: dict[str, float | None] = {}
    for name, rubric in CRITERIA.items():
        votes: list[int] = []
        for first, second, a_is in ((a, b, 1), (b, a, 2)):
            calls = f"CALL 1\n{_agent_lines(first)}\n\nCALL 2\n{_agent_lines(second)}"
            outcome = await judge.ask(
                [
                    {"role": "system", "content": f"{_PAIR_ASK} Criterion: {rubric}"},
                    {"role": "user", "content": calls},
                ],
                MAX_TOKENS,
                None,
            )
            spend.add(judge.model, outcome.usage)
            better = _json(outcome.content).get("better")
            if better in (0, 1, 2):
                votes.append(0 if better == 0 else (1 if better == a_is else -1))
        out[name] = sum(votes) / len(votes) if len(votes) == 2 else None
    return out


__all__ = ["CRITERIA", "UNCONTROLLED", "Judge", "grade", "judge_leg", "prefer"]
