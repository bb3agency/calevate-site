"""Answering stops when the calling credit runs out, and starts again the moment it lands.

The founder's decision of 8 Sep 2026. `compliance.check_dispatch` has always refused
OUTBOUND at a balance of zero or below; inbound passes through none of it, so a client
whose top-up lapsed went on having their phone answered and `workers/pipeline.py` went on
debiting every answered minute against a wallet that could only get more negative — an
unbounded overdraft we absorb. At zero or below the agent now stops doing business and the
caller hears one short neutral line instead (`agents.service.CREDIT_STOP_MESSAGE`).

**WHAT IS IN THIS FILE AND WHAT IS NOT.** The decision — which agents, what they say, how
the engine is told — is `agents.service.reconcile_inbound_answering`, beside the publish
path it has to agree with. This is the ACTUATOR: one job, one tenant, no policy of its own.
The split is `workers/maintenance.py`'s and it is followed rather than re-argued.

**WHY A JOB AND NOT A CRON SWEEP.** The interesting thing is not the BALANCE, it is the
MOVEMENT, and `billing.service.record_entry` is the single writer of every credit movement
in this product — the argument `workers/wallet_alerts.py` sets out at length for the
low-balance email, and the same one applies here with more force, because this edge is a
third-party write and a sweep would spend a fleet's worth of vendor round trips per tick to
discover that nothing had changed. The entry that takes a wallet across zero going DOWN and
the entry that takes it back UP are each published in the SAME TRANSACTION as the ledger
row that earned them (BACKEND-PATTERNS §4), so a rolled-back charge cannot leave a phone
silent and a committed top-up cannot lose the job that brings it back.

**RECOVERY IS THE HALF THAT FAILS SILENTLY, SO IT HAS TWO PATHS TO IT.** A client who tops
up at 9pm must not find their phone still dead in the morning, and the failure mode of the
top-up edge is that nobody notices for a night. So besides the upward crossing:

* every republish of a live answering agent re-decides the question at the end of
  `agents.service.publish_agent`, which is also what stops the eleven paths that write an
  agent's real script from silently undoing the cutover;
* the post-call pipeline enqueues one of these jobs, at most once per call, whenever it
  meters a call for a tenant it finds exhausted — which is what catches an edge that never
  moved the ledger at all (a trial ending, a plan tier changing under a zero wallet).

**THIS JOB MAY RUN TWICE AND THAT IS ACCEPTED.** The outbox is at-least-once and
`reconcile_inbound_answering` is idempotent by construction: `agents.inbound_silenced_at`
records what the engine was observed to hold, so a second run makes no vendor call at all.

Hard rule 6: ids, counts and our own verdict words. No prompt body, no disclosure line, no
phone number, no balance.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq import Retry

from apps.api.agents.service import reconcile_inbound_answering
from apps.api.compliance.service import credits_exhausted
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine

log = get_logger(__name__)

#: Seconds to wait before each retry, indexed by the attempt that just failed. One entry
#: shorter than the budget, because the last attempt has nothing after it — the shape
#: `wallet_alerts.RETRY_BACKOFF_S` established. Short, unlike that one: a warning email can
#: wait five minutes and a phone line that is answering calls its owner cannot pay for, or
#: refusing calls its owner HAS paid for, cannot.
RETRY_BACKOFF_S: tuple[float, ...] = (15.0, 60.0)


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


async def apply_inbound_credit_state(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Make this tenant's answering agents agree with this tenant's wallet.

    **THE VERDICT IS RE-READ HERE, NEVER TAKEN FROM THE PAYLOAD.** The crossing that
    published this job is a fact about one ledger entry; what the agents must be told is a
    fact about the wallet NOW, and between the two lies the queue. A payload-driven job
    would silence a client who topped up while it was waiting, and would do it with the
    conviction of a job that ran successfully. `compliance.service.credits_exhausted` is
    the one predicate — the same one the dial gate, the launch gate and the client's own
    credits screen ask — so there is no second definition of "this account has run out"
    anywhere in this product.

    A retry is asked for only when the ENGINE could not be reached about an agent. Nothing
    else here can fail in a way a retry fixes, and a job that re-ran on a permanent refusal
    would spend its whole ladder alarming about the same agent.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    engine = get_engine()
    async with tenant_session(tenant_id) as session:
        exhausted = await credits_exhausted(session, tenant_id=tenant_id)
        outcome = await reconcile_inbound_answering(
            session, engine, tenant_id=tenant_id, exhausted=exhausted
        )
    if outcome.unsupported:
        # NOT a silent no-op, and no fallback to unbinding the number: that would trade the
        # founder's message for a dead line, which is the one outcome the decision refused.
        alert(
            "CORE_LOGIC",
            "inbound_cutover_unsupported",
            detail=(
                f"the {engine.name} adapter cannot override an agent's script, so nothing "
                "changes what a caller hears when a client's credit runs out: inbound is "
                "still answered normally. The client is not billed for it "
                "(workers/pipeline.py), so no overdraft accrues — but calls this client "
                "cannot pay for are still being served."
            ),
            tenant_id=str(tenant_id),
        )
        return "unsupported"
    if outcome.failed:
        attempt = int(ctx.get("job_try", 1))
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt))
        log.error(
            "inbound_cutover_abandoned",
            extra={"tenant_id": str(tenant_id), "failed": outcome.failed},
        )
        return f"abandoned:{outcome.failed}"
    return f"silenced={outcome.silenced} restored={outcome.restored} unchanged={outcome.unchanged}"


__all__ = ["apply_inbound_credit_state"]
