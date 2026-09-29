"""The evidence an in-call opt-out tool call records — the BELT half of `compliance/optout.py`.

The voice worker's `record_do_not_call` tool reaches `apps/api/worker/tools.record_opt_out`,
which writes the suppression inside the request through `record_call_optout`. This module
holds the one thing that path and the post-call transcript pass must agree on: how a tool
call is described in `consent_ledger.evidence`.

A tool call cannot be trusted to be the only one: the model may invoke it twice and the
post-call transcript pass sees the same request again minutes later. All of them converge on
`record_call_optout`, whose dedupe makes a repeat a no-op.
"""

from __future__ import annotations

from apps.api.compliance.optout import OptOutSignal
from apps.api.core.logging import get_logger
from apps.workers.redaction import redact

log = get_logger(__name__)

# The tool call's own evidence rule id. It is not a phrase match — the agent's model
# decided this was an opt-out — and the ledger has to say so, because "a model judged it"
# and "these words were said" are different strengths of evidence to whoever defends the
# suppression later. The string is a ledger token already written to an append-only table,
# so it keeps its original spelling.
TOOL_RULE = "engine_tool_call"

# How much of the model's `reason` string is kept. It is model-generated text about what
# the caller said, so it is evidence, and it is bounded before it is stored.
_REASON_CHARS = 80


def tool_signal(*, reason: str | None, language: str | None) -> OptOutSignal:
    """The in-call path's `OptOutSignal`. No turn index — see the field's comment.

    `matched` is REDACTED, for the reason `detect_opt_out` redacts its own: it is written
    into `consent_ledger.evidence`, which is append-only, and the model's `reason` is a
    paraphrase of the caller that may quote their number back ("caller at 98765 43210
    asked to be removed"). A number stored there could never be taken out. Redaction runs
    before the cap so a number cut in half cannot slip past the redactor.
    """
    return OptOutSignal(
        rule=TOOL_RULE,
        language=(language or "unknown")[:8],
        turn_idx=None,
        matched=redact(reason or "").text[:_REASON_CHARS],
    )


__all__ = ["TOOL_RULE", "tool_signal"]
