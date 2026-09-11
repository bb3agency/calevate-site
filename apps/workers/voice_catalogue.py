"""Keep the voice catalogue in step with the engine account (D-585).

WHAT IT DOES AND WHY IT IS A JOB
--------------------------------
`apps/api/agents/voice_sync.py` carries the argument for reading the catalogue from the
engine at all: our compiled list came from the MODEL vendor's SDK and the ENGINE's provider
offers a different subset (proved by a live `400 POST /v2/agent`, "Provided voice: Anushka
is not available for the provider: sarvam", 11 Sep 2026), and a CLONED voice cannot be in a
compiled list at all. This module is the clock on it.

TWO TRIGGERS, AND BOTH ARE NEEDED
---------------------------------
* **The cron** keeps the cache honest without anybody thinking about it — a voice the
  vendor withdraws stops being offered, a voice they add starts being offered.
* **`POST /v1/ops/voices/refresh`** exists because of the ONE event the cron cannot serve
  at a human's tempo: the founder clones a voice and wants to put a client on it now. A
  daily job would mean "your new voice appears tomorrow", which is not a product.

Hourly, and deliberately not faster: the list changes when a person does something to the
vendor account, the refresh route covers the case where that person is us, and the picker's
staleness budget is an hour of a list nobody edited. `run_at_startup` is NOT set, for the
reason `fx_pull` gives — a deploy of N workers would otherwise fire N simultaneous vendor
requests for one list that none of them urgently needs, and a process with no cached rows
serves `agents/voices.SEED_CATALOG` rather than nothing.

IDEMPOTENT, KEYED, RETRIED (BACKEND-PATTERNS §4/§5)
---------------------------------------------------
* IDEMPOTENT at the row: every voice is an upsert keyed on our catalogue id, so two runs
  converge on the same table. There is no claim row because the operation has no side
  effect to claim — it is a convergent overwrite of a cache.
* SINGLE-FLIGHT by arq's own cron job id (`refresh_voice_catalogue:<intended run>`), which
  is what stops two workers running one tick.
* RETRIED to `WORKER_MAX_TRIES` with the same ladder every other vendor-facing job uses,
  and the LAST attempt alerts before raising — that alert is the only dead letter this
  queue has (`apps/workers/settings.py`).
"""

from __future__ import annotations

from typing import Any, Final

from arq import Retry

from apps.api.agents.voice_sync import load_voice_catalogue, sync_voice_catalogue
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine

log = get_logger(__name__)

#: The minute of each hour the cron fires on. A constant rather than a literal in the
#: registration for `fx_pull.PULL_MINUTES`' reason: the schedule and the job's own
#: reasoning about its cadence must not be two numbers.
REFRESH_MINUTE: Final = 17

#: What an operator is paged with when the catalogue has stopped being refreshable. An
#: authored, stable code — it is an alert label and a runbook key, not prose.
SYNC_FAILED_CODE: Final = "voice_catalogue_sync_failed"


def _retry_after(attempt: int) -> int:
    """Exponential backoff in seconds: 30, 60, 120. The same shape as every other
    vendor-facing job's ladder, so an operator reading two of them reads one pattern."""
    return int(30 * 2 ** (attempt - 1))


async def refresh_voice_catalogue(ctx: dict[str, Any]) -> str:
    """Read the engine's voice list, cache it, and install it in THIS process.

    Returns a small summary (arq keeps it), which is what makes "the tick ran and changed
    nothing" answerable without reading a day of logs — and changing nothing is the
    expected outcome of almost every run.

    **THE SYNC AND THE INSTALL ARE ONE COMMIT'S WORTH OF WORK BUT TWO STEPS**, deliberately.
    The install re-reads the table rather than using the rows it just built, because the
    table is what the OTHER processes will read: a worker that installed the listing
    directly could serve a catalogue that a failed COMMIT means nobody else will ever see.

    A sync that read nothing is NOT an error here and does not retry. `sync_voice_catalogue`
    already alerted and already refused to apply it, and the previous catalogue is standing
    — asking the same question thirty seconds later gets the same answer.
    """
    attempt = int(ctx.get("job_try", 1))
    try:
        engine = get_engine()
        async with untenanted_session() as session:
            result = await sync_voice_catalogue(session, engine)
            await session.commit()
            in_force = await load_voice_catalogue(session)
    except Exception as exc:
        log.warning(
            "voice_catalogue_refresh_failed",
            extra={"attempt": attempt, "error": type(exc).__name__},
        )
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from exc
        # Alert THEN raise: returning would file the tick as a success with a number in it
        # that nobody reads. The catalogue in force is unchanged, which is survivable — the
        # thing an operator must know is that it has stopped being refreshed.
        alert(
            "WORKER_TERMINAL",
            SYNC_FAILED_CODE,
            detail=(
                "The voice catalogue could not be refreshed from the voice platform. The "
                "last synced catalogue (or the built-in seed) is still being offered, so "
                "no client is blocked — but a voice cloned or withdrawn on the platform "
                "will not appear or disappear until this succeeds. Check the engine "
                "credential, then POST /v1/ops/voices/refresh."
            ),
            error=type(exc).__name__,
        )
        raise
    return (
        f'{{"seen":{result.seen},"written":{result.written},"pruned":{result.pruned},'
        f'"complete":{str(result.complete).lower()},"in_force":{in_force}}}'
    )
