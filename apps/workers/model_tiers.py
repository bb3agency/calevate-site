"""Which Gemini call may run on the cheaper Flex tier, and for how long it may wait (D-930).

Founder, 29 Oct 2026: AI work nobody is waiting on runs on Google's cheaper mode; anything a
person waits on stays on the standard mode. `MODEL_CALLS` is that rule applied to every call
this tree makes to a language model, in one place, each with its reason.

WHY FLEX AND NOT BATCH. Both are 50% of the standard price (ai.google.dev/gemini-api/docs/
pricing, updated 2026-10-28, read 29 Oct 2026: gemini-3.1-flash-lite $0.25/$1.50 standard,
$0.125/$0.75 Flex and Batch, per 1M input/output tokens; gemini-2.5-flash-lite $0.10/$0.40
standard, $0.05/$0.20 Flex and Batch; Flex is "Not available" on the free tier). Flex is the
same synchronous call with `service_tier: "flex"`, which the OpenAI-compatible surface every
Gemini leg here already speaks accepts (ai.google.dev/gemini-api/docs/openai, updated
2026-10-28), so it rides `chat.complete` with no second client. Batch is a job with a 24-hour
target turnaround (ai.google.dev/gemini-api/docs/batch-api, updated 2026-09-17), and its
OpenAI-compatible form cannot upload or download the request and result files ("Compatibility
for upload and download is currently not supported", the openai page above), so it would need
the native Files and `batchGenerateContent` surface: a second Gemini client, against the one
path rule. Nothing here is bulk enough to need it; the sweeps below are tens of calls an hour.

WHY THE WAIT IS BOUNDED BY THE TICK. Flex targets one to fifteen minutes and Google advises a
client timeout of ten minutes or more (the flex-inference page above), while a worker job is
cancelled at `WorkerSettings.job_timeout` (300 s) and the sweeps ask one item after another.
So a Flex attempt never starts unless a standard request still fits in the tick after it, and
after one Flex fallback the rest of that tick asks on standard: Flex was at capacity a moment
ago, and asking again would spend a second wait on the same answer. A tick therefore takes at
most one `FLEX_WAIT_CAP_S` longer than it did on standard.

UNKNOWN, and an operator gate (OPERATIONS §2): whether Google bills a Flex request the client
stopped waiting for. The docs say nothing. If it does, a timed-out Flex attempt costs its
Flex price on top of the standard answer that follows it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from apps.workers.chat import ChatOutcome, FlexRequest, ServiceTier


@dataclass(frozen=True, slots=True)
class ModelCall:
    tier: ServiceTier
    reason: str


#: Every language-model call in this tree, by the name its call site passes. A call that is
#: not on Gemini is listed with `standard` and says so, so the list is the whole inventory.
MODEL_CALLS: Final[Mapping[str, ModelCall]] = MappingProxyType(
    {
        # --- nobody is waiting: Flex ---------------------------------------------------
        "kb_gloss": ModelCall(
            "flex",
            "twice-hourly sweep writing English glosses of Telugu knowledge chunks; the "
            "chunk is searchable without one meanwhile",
        ),
        "copilot_memory": ModelCall(
            "flex", "hourly sweep distilling Pip's past conversations into facts it recalls"
        ),
        "caller_memory": ModelCall(
            "flex",
            "hourly sweep distilling finished calls into caller facts (returns early on an "
            "engine that keeps its own memory, which ThinnestAI does)",
        ),
        "business_copy_scheduled": ModelCall(
            "flex",
            "the daily check's refresh of an account's examples, 15 days after the last; "
            "the copy in use stays on screen until it lands",
        ),
        # --- a person is waiting: standard ---------------------------------------------
        "copilot_chat": ModelCall("standard", "Pip: a person is reading the answer as it streams"),
        "copilot_pdf_turn": ModelCall("standard", "Pip reading an attached PDF, in the chat"),
        "copilot_job": ModelCall(
            "standard",
            "Pip background jobs and routines: a tool-calling loop of many turns inside a "
            "240 s budget, which a 1-15 minute turn cannot fit, started by a person who is "
            "told when it is done",
        ),
        "agent_test": ModelCall("standard", "the agent test chat and its judge, on screen"),
        "script_draft": ModelCall("standard", "the script writer's button, with a spinner"),
        "kb_teach": ModelCall("standard", "the teach box sorts what the owner just typed"),
        "teach_questions": ModelCall(
            "standard", "queued by the owner opening the questions list, which shows the draft"
        ),
        "first_run": ModelCall("standard", "the Meet your agent screen waits on the questions"),
        "lead_fields_draft": ModelCall("standard", "the owner waits on the drafted fields"),
        "business_outcomes_draft": ModelCall(
            "standard", "at publish and on the owner's Write them for me button"
        ),
        "field_suggestions": ModelCall(
            "standard", "the owner's Check again button waits on the pass"
        ),
        "business_type": ModelCall(
            "standard", "an operator confirmed a type and watches the agents change"
        ),
        "business_copy_requested": ModelCall(
            "standard", "a new account, an owner asking Pip, or an operator asking"
        ),
        "document_ocr": ModelCall(
            "standard", "the owner uploaded a photo and watches it become knowledge"
        ),
        "extraction": ModelCall(
            "standard",
            "the post-call lead path; the first pass is Sarvam permanently (CLAUDE.md) and "
            "the Gemini extractor re-reads on an owner's request",
        ),
        "call_language": ModelCall("standard", "Sarvam, not Gemini: no Flex tier to ask for"),
        "embeddings": ModelCall(
            "standard",
            "an OpenAI-shaped embedding leg, not Gemini, and Flex lists no embedding model",
        ),
    }
)

#: The longest one Flex attempt may wait before the standard ask. Well under the tick budget,
#: so a tick that loses its one wait still has room for its standard work.
FLEX_WAIT_CAP_S: Final = 60.0

#: A Flex wait shorter than this is not worth starting: at a 1-15 minute target it would
#: mostly time out and add its length to the job for nothing.
FLEX_WAIT_MIN_S: Final = 15.0

#: How much of a job's time its model calls may use, under `WorkerSettings.job_timeout`
#: (300 s) by the same margin `copilot/service` keeps for its background budget (240 s).
JOB_MODEL_BUDGET_S: Final = 240.0


class FlexAllowance:
    """Whether the next model call of one job (or one tick) may ask on Flex, and how long.

    Refuses to exist for a call `MODEL_CALLS` keeps on standard, so a person-facing call
    cannot be handed a Flex request by mistake."""

    def __init__(
        self,
        call: str,
        *,
        budget_s: float = JOB_MODEL_BUDGET_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        entry = MODEL_CALLS[call]
        if entry.tier != "flex":
            raise ValueError(f"{call!r} keeps the standard tier: {entry.reason}")
        self.call = call
        self._clock = clock
        self._until = clock() + budget_s
        self._open = True

    def request(self, *, standard_timeout_s: float) -> FlexRequest | None:
        """A Flex request for the next call, or None to ask on standard.

        None after a fallback in this job, or when a wait plus a standard request would not
        fit in what is left of the budget."""
        if not self._open:
            return None
        wait = min(FLEX_WAIT_CAP_S, self._until - self._clock() - standard_timeout_s)
        return FlexRequest(wait_s=wait) if wait >= FLEX_WAIT_MIN_S else None

    def note(self, asked: FlexRequest | None, outcome: ChatOutcome) -> None:
        """Close Flex for the rest of the job after one fallback."""
        if asked is not None and outcome.service_tier != "flex":
            self._open = False


__all__ = [
    "FLEX_WAIT_CAP_S",
    "FLEX_WAIT_MIN_S",
    "JOB_MODEL_BUDGET_S",
    "MODEL_CALLS",
    "FlexAllowance",
    "ModelCall",
]
