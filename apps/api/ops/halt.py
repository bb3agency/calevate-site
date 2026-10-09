"""The recall arm of the big red switch, shared by the button and the admin assistant.

`ops/routes.py::set_platform` and the admin assistant's `platform_halt_outbound` action
both throw the same switch, and both must pull back the dials the voice platform is
already holding (D-432). One function, so the two cannot come to disagree about whether a
halt recalls.
"""

from __future__ import annotations

from typing import Final

from apps.api.core.alerting import alert
from apps.api.core.queue import enqueue

#: The worker job that pulls queued dials back after a halt (`apps/workers/dial_recall`).
DIAL_RECALL_JOB: Final = "recall_queued_dials"


async def queue_dial_recall() -> None:
    """Enqueue the recall. NEVER RAISES.

    ENQUEUED DIRECTLY RATHER THAN THROUGH THE OUTBOX: the halt itself is written on its own
    connection and has already committed by the time this runs, so there is no shared fate
    for the outbox to preserve, and its dispatch tick would be seconds of ringing bought for
    nothing. A failure is alarmed, never raised — the halt has landed and is what matters,
    and refusing now would tell an operator the switch did not throw when it did.
    `dial_recall_not_queued` is the row in `runbooks/alarm-index.md`.
    """
    try:
        await enqueue(DIAL_RECALL_JOB)
    except Exception as exc:
        alert(
            "CORE_LOGIC",
            "dial_recall_not_queued",
            detail=(
                f"outbound was halted but the recall job could not be queued "
                f"({exc.__class__.__name__}); dials already accepted by the voice "
                "platform will ring unless the halt is re-posted"
            ),
        )


__all__ = ["DIAL_RECALL_JOB", "queue_dial_recall"]
