"""Which model answers a question: the fast tier or the planning tier (D-694).

THE FOUNDER'S DECISION: the assistant's model is tiered by TASK, set in the console, and
Gemini only at first. A fast model answers and looks things up; a stronger one plans
multi-step requests and background jobs. Both are console settings
(`copilot_fast_model`, `copilot_planning_model`, typed to the Google leg), never constants,
and a setting is used only while its model is in `off_call_offerable_models()` — permitted
for the assistant (D-786: Gemini 3 models refused on calls are permitted here),
credential installed, price attested — and its data-use attestation is recorded. Anything
else falls to the next rung of the ONE selector (`workers/extraction.assist_capability`)
and the person is told whose answer it is (D-127 G-6).

THIS SUPERSEDES D-478 ON THE ASSISTANT. The assistant used to run on the ACCOUNT's own
model where that model's leg could serve the dashboard. It now runs on the platform's
console-chosen tier for every account, because the assistant is free (the fair-use cap)
and its model is a platform decision, not a client one. The account's model still runs its
phone agents, untouched.

THE ROUTING RULE IS DETERMINISTIC and is stated here in full, because a rule that picks a
paid model has to be one a reader can predict:

    planning  ⇐  the question is a background job, OR
                 it is at least `LONG_QUESTION_CHARS` long, OR
                 it lists two or more numbered steps, OR
                 it contains a MULTI-STEP or ROUTINE marker (`PLANNING_MARKERS`)
    fast      ⇐  everything else

The markers are English (and Tenglish) words. A Telugu- or Hindi-script request reaches the
planning tier through length or numbered steps, and otherwise runs on the fast tier — which
still has every tool and the same turn budget, so the cost of a miss is a weaker plan, not
a refusal.
"""

from __future__ import annotations

import re
from typing import Final, Literal

from apps.api.agents.assist_leg import google_leg_for
from apps.api.core.settings import get_settings
from apps.workers.extraction import TenantModelLeg

ModelTier = Literal["fast", "planning"]

#: A question this long is a brief, not a lookup.
LONG_QUESTION_CHARS: Final = 400

#: Words that mean "do several things" or "do this on a schedule". Matched case-insensitively
#: on word boundaries, so "plan" does not match "planet" and "every" matches "every day".
PLANNING_MARKERS: Final[tuple[str, ...]] = (
    "and then",
    "after that",
    "step by step",
    "for each",
    "for every",
    "every day",
    "every morning",
    "every evening",
    "every week",
    "every monday",
    "every friday",
    "each morning",
    "each day",
    "each week",
    "daily",
    "weekly",
    "routine",
    "recurring",
    "schedule",
    "remind me",
    "all my leads",
    "all leads",
    "all of my",
    "in bulk",
)

_MARKER_RE: Final = re.compile(
    r"\b(?:" + "|".join(re.escape(marker) for marker in PLANNING_MARKERS) + r")\b",
    re.IGNORECASE,
)
_NUMBERED_STEP_RE: Final = re.compile(r"(?m)^\s*\d{1,2}[.)]\s+\S")


def route_tier(question: str, *, background: bool = False) -> ModelTier:
    """The tier for one question. Pure, deterministic, and documented in the docstring."""
    if background or len(question) >= LONG_QUESTION_CHARS:
        return "planning"
    if len(_NUMBERED_STEP_RE.findall(question)) >= 2:
        return "planning"
    if _MARKER_RE.search(question):
        return "planning"
    return "fast"


def tier_model(tier: ModelTier) -> str:
    """The console setting for this tier."""
    settings = get_settings()
    return settings.copilot_planning_model if tier == "planning" else settings.copilot_fast_model


def tier_leg(tier: ModelTier) -> TenantModelLeg:
    """This tier's model as the selector's leg, or a leg that says why it cannot serve
    (`agents/assist_leg.google_leg_for`: key and attested price first, hard rule 7)."""
    return google_leg_for(tier_model(tier))


__all__ = [
    "LONG_QUESTION_CHARS",
    "PLANNING_MARKERS",
    "ModelTier",
    "route_tier",
    "tier_leg",
    "tier_model",
]
