"""A large Pip script change keeps what it got right and says exactly what it could not do.

Production, 9 Nov 2026: the founder asked Pip for a large restructuring of Varsha's script and
read "Could not write the suggestion: AI help could not make that change cleanly this time".
The edit returned the WHOLE script on a route-sized budget (15 s, 4,096 tokens); its one repair
asked for the whole script again; and a repair that did not come back, or still broke a rule
anywhere, threw the whole answer away. Now each repair asks only for the parts still broken and
lays them back by step id, the job gives a long script a job-sized budget, a repair that never
comes back still leaves the first answer's good parts, and what is left out is named.

The model is replaced at its one seam (`chat.complete`); the lines are English. A line that
names a technology company breaks a rule (`business_copy.provider_problem`), which is the
broken part in every case here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from apps.api.agents import script_proposals
from apps.api.core.queue import WORKER_JOB_TIMEOUT_S
from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers import script_proposal as worker
from apps.workers.extraction import (
    ASSIST_LADDER_LEGS,
    ASSIST_TIMEOUT_S,
)
from apps.workers.script_assist import (
    LeftOut,
    ScriptBrief,
)
from calevate_shared.call_script import CallScript, ConversationStage

BROKEN = "We book it on Google for you."
#: What each step is about: words rather than numbers, since a figure the owner's facts do
#: not give is itself a broken rule.
TOPICS = (
    "",
    "seeds",
    "soil",
    "water",
    "season",
    "delivery",
    "payment",
    "storage",
    "pests",
    "harvest",
    "market",
)


#: A warmer line per step, each opening differently and sharing few words with the others, so
#: the same-opening and repeated-line checks have nothing to say about the lines a test keeps.
WARM = (
    "",
    "Which seeds are you planning to sow this season?",
    "How is your soil holding up after the rains?",
    "Do your fields get enough water right now?",
    "When does your next crop season start?",
    "Where should we deliver your order?",
    "Would you like to pay at delivery or online?",
    "Is there a dry place to keep the bags?",
    "Have pests troubled your crop lately?",
    "Any idea yet when the harvest will be ready?",
    "Tell me, where do you usually sell your produce?",
)


def _warm(i: int) -> str:
    return WARM[i]


def _stage(i: int, line: str | None = None) -> ConversationStage:
    return ConversationStage(
        id=f"s{i}",
        name=f"Step {i}",
        instruction=f"Cover the {TOPICS[i]} part of the call.",
        sounds_like=line or f"Now the {TOPICS[i]}, is that fine?",
    )


#: A long script: ten steps, then the close (the most a script holds is twelve).
CURRENT = CallScript(
    schema_version=2,
    opening_line="Hello, this is Asha from Acme Seeds. Can we talk now?",
    goal="Help buyers with their seed orders.",
    stages=[
        *[_stage(i) for i in range(1, 11)],
        ConversationStage(
            id="close", name="Close", instruction="Thank them.", sounds_like="Thank you, bye."
        ),
    ],
)
BRIEF = ScriptBrief(
    description="A seed shop.",
    business_name="Acme Seeds",
    agent_name="Asha",
    business_type="retail",
    direction="inbound",
    language="en-IN",
)
CHANGE = "Rewrite every step's line so it sounds warmer, and set the main task to orders."


def _rewritten(i: int, *, broken: set[int]) -> dict[str, Any]:
    line = BROKEN if i in broken else _warm(i)
    return _stage(i, line).model_dump(mode="json")


def _answer(*, broken: set[int]) -> dict[str, Any]:
    """The whole edited script, as the edit writer returns it, with `broken` steps' lines
    naming a technology company."""
    body = CURRENT.model_dump(mode="json", exclude={"raw_override"})
    body["goal"] = "Help buyers place and track their seed orders."
    body["stages"] = [
        *[_rewritten(i, broken=broken) for i in range(1, 11)],
        CURRENT.stages[-1].model_dump(mode="json"),
    ]
    return body


class Model:
    """`chat.complete` answering the paid leg with each of `answers` in turn (a dict is the
    JSON content, the string "cut" a reply stopped at `max_tokens`), and the Sarvam standby
    unreachable, so only the paid leg's answers decide the outcome."""

    def __init__(self, *answers: dict[str, Any] | str) -> None:
        self.answers = list(answers)
        self.asked: list[list[Any]] = []
        self.max_tokens: list[int | None] = []

    async def __call__(
        self, leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any
    ) -> chat.ChatOutcome:
        if leg.dialect == "sarvam":
            raise httpx.ConnectError("standby down")
        self.asked.append(list(messages))
        self.max_tokens.append(kw.get("max_tokens"))
        answer = self.answers[min(len(self.asked) - 1, len(self.answers) - 1)]
        usage = chat.TokenUsage(prompt_tokens=9_000, output_tokens=3_000)
        if answer == "cut":
            return chat.ChatOutcome(content='{"stages": [', finish_reason="length", usage=usage)
        return chat.ChatOutcome(content=json.dumps(answer), finish_reason="stop", usage=usage)

    def note(self, n: int) -> str:
        """The repair note of the `n`th ask (1-based), as the model read it."""
        return str(self.asked[n - 1][-1]["content"])


@pytest.fixture(autouse=True)
def model_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)


def test_the_owner_never_reads_a_vendor_name_in_a_left_out_reason() -> None:
    rule = "names a technology company (google)"
    assert script_proposals.owner_rule(rule) == "Names a technology company."
    part = LeftOut("opening_line", "", rule)
    assert script_proposals.part_label(part) == "The opening line"


def test_the_proposal_job_budget_fits_inside_the_worker_job() -> None:
    """FAILS IF: the job's ladder plus its opening repairs can outlast arq's `job_timeout`,
    which would kill the job after the model was paid and before the meter row is written."""
    ladder = ASSIST_LADDER_LEGS * worker.PROPOSAL_REQUEST_TIMEOUT_S
    openings = 2 * ASSIST_LADDER_LEGS * ASSIST_TIMEOUT_S
    assert ladder + openings + 30 < WORKER_JOB_TIMEOUT_S
