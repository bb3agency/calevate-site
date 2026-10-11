"""The shared trial number's own line, in our terms (D-742).

One agent in the developer workspace that never answers and tells whoever rings the shared
trial number back what the number is. The adapter makes and reads it
(`engine/thinnest.ThinnestEngine.converge_trial_line_agent`); the number seam attaches it
(`campaigns/engine_numbers.converge_trial_line`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Its fixed name. It is found by it, so it is never made twice and never mistaken for a
#: client's agent (ours carry `#cv-<id>`).
TRIAL_LINE_AGENT_NAME: Final = "Calevate shared trial number (no answer)"


@dataclass(frozen=True, slots=True)
class TrialLineAgent:
    """The developer-workspace agent that answers nothing on the shared trial number."""

    ref: str
    answers_calls: bool
    message: str | None
    #: The platform's note when the message will not be spoken as written.
    message_note: str | None = None


__all__ = ["TRIAL_LINE_AGENT_NAME", "TrialLineAgent"]
