"""Run the in-call LLM credential rotation once, now (D-404).

THE OPERATOR HALF OF `runbooks/vertex-llm-credential.md`. The rotation is a cron every
four hours, so a fix applied during an incident — a corrected
`bolna_llm_credential_name`, a new IAM binding, an org policy finally set — is otherwise
unverifiable for up to four hours. That is four hours of an operator not knowing whether
they fixed it, on the one alarm whose whole value is lead time.

WHY A SCRIPT AND NOT AN ADMIN BUTTON. There is nothing to render: no input, no choice, no
result a client can see. The one thing an operator wants is the job's own log line, which
a console would have to reproduce. `correct_tts_tier.py` and `reconcile_credit_ledger.py`
already establish the shape for "the production caller of a worker-side operation".

SAFE TO RUN AT ANY TIME, and that is a property of the job rather than a claim here: every
tick mints a FRESH bearer and overwrites, so running it by hand is never a duplicate, never
needs to know whether the cron already ran, and cannot leave a half-applied state. It costs
one RS256 signature and two HTTPS round trips.

NO `--apply` FLAG, deliberately, and it is the one place this diverges from its two
siblings. Theirs write to an append-only ledger where a wrong run cannot be taken back, so
a dry run is the default and the write is opt-in. This writes a credential that the next
scheduled tick will overwrite anyway — a dry run would prove only that the code can be
imported, which is what the tests are for.
"""

from __future__ import annotations

import asyncio
import sys

from apps.api.core.logging import get_logger
from apps.workers.vertex_credential import refresh_in_call_llm_credential

log = get_logger(__name__)

#: Outcomes that mean "this deployment is not on that leg". Not failures — a deployment
#: with no GCP project is a coherent deployment — but they must not exit 0 either, because
#: an operator running this DURING an incident asked a question and got "not applicable",
#: which is an answer they need to see rather than a green tick they will read as fixed.
_SKIP_PREFIX = "skipped_"


async def main() -> int:
    outcome = await refresh_in_call_llm_credential({})
    if outcome.startswith("rotated"):
        print(f"OK: {outcome}")
        return 0
    if outcome.startswith(_SKIP_PREFIX):
        # Exit 3 so a wrapper can tell "not on this leg" from "tried and failed" without
        # parsing text. The reason is already in the worker's own log line.
        print(f"NOT APPLICABLE: {outcome} — see the worker log for which condition is unmet")
        return 3
    # The job has already alerted and logged which arm it was; repeating the detail here
    # would be a second place for it to be phrased differently.
    print(f"FAILED: {outcome} — see runbooks/vertex-llm-credential.md")
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(asyncio.run(main()))
