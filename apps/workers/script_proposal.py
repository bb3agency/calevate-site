"""The request budgets of Pip's background writing jobs.

What every script Pip writes goes through lives in the one writer
(`workers/script_writer.write_script`); these two budgets are shared with the other
background jobs that write long answers (company training, WhatsApp follow-ups).
"""

from __future__ import annotations

from typing import Final

#: One model request's budget in these jobs, in place of the route's `ASSIST_TIMEOUT_S`:
#: nobody waits on an HTTP response here. The ladder spends at most `ASSIST_LADDER_LEGS` of
#: these, inside the worker's `job_timeout`.
PROPOSAL_REQUEST_TIMEOUT_S: Final = 50.0

#: One answer's token ceiling in these jobs. A ceiling, not a target: billing follows the
#: tokens used. Gemini counts thinking tokens inside it; gemini-3.1-flash-lite's output limit
#: is 65,536 (aistudio.google.com/docs/models/gemini-3.1-flash-lite, May 2026), Azure's
#: gpt-4o-mini 16,384, so this is the most both paid legs take. The Sarvam standby keeps its
#: own 4,096.
PROPOSAL_MAX_TOKENS: Final = 16_384


__all__ = ["PROPOSAL_MAX_TOKENS", "PROPOSAL_REQUEST_TIMEOUT_S"]
