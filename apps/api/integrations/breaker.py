"""The webhook breaker: pause a destination that has failed for three days, hold what it
would have been sent, tell the owner, and replay it all on Resume (D-1049, W2.5).

**Paused, never deactivated, and nothing is dropped.** A paused endpoint keeps its
subscription and the fan-out keeps queueing its deliveries; the delivery worker records
each one `held` instead of sending it (`workers/outbound_webhooks`). Resume puts the held
deliveries, and the ones that failed during the streak, back on the retry sweep oldest
first, under their own delivery ids, so a receiver that saw any of them already dedupes it.

**When it trips.** Every delivery since the endpoint last accepted one has failed, the
first of those failures is at least `STREAK` old, the latest is within `STILL_FAILING`,
and the failures span at least `MIN_SPAN`. 72 hours is the plan's figure (MASTER-PLAN
W2.5); the span and the recency follow Svix, which disables an endpoint after five days of
failures and starts that clock only once failures 12 hours apart have been seen
(docs.svix.com/retries, read 28 Nov 2026), so one stale failure on a quiet endpoint never
trips it. Standard Webhooks asks a producer to tell the consumer through another channel
before disabling ("Deliverability and reliability", standard-webhooks spec, read 28 Nov
2026): the owner is emailed once per pause and a notice is posted to their bell.

Test deliveries are never counted. A `skipped` delivery is neither a failure nor a
success. Every kind of destination is covered: a spreadsheet that has not been shared with
us fails for the same three days a dead URL does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of
from apps.api.integrations.service import RETRYING
from apps.api.reliability.service import enqueue_outbox_once

log = get_logger(__name__)

STREAK: Final = timedelta(hours=72)
STILL_FAILING: Final = timedelta(hours=24)
MIN_SPAN: Final = timedelta(hours=12)

#: The delivery status of a delivery not sent because its endpoint is paused.
HELD: Final = "held"

#: The outbox job that tells the owner, once per pause (`workers/webhooks_breaker`).
PAUSED_NOTICE_JOB: Final = "notify_endpoint_paused"

ENDPOINT_PAUSED: Final = "integration_endpoint.paused"
ENDPOINT_RESUMED: Final = "integration_endpoint.resumed"

#: Outbound deliveries that count: not tests, not skipped.
_COUNTED: Final = "d.direction = 'out' AND NOT d.is_test AND d.status <> 'skipped'"

#: Per endpoint of this tenant (RLS on `outbound_webhooks`): the streak since its last
#: accepted delivery. `last_ok` is the latest `last_at` of a delivered row, and the streak
#: is every counted delivery that began after it.
_TRIPPED_SQL: Final = f"""
SELECT w.id, s.first_failed
FROM outbound_webhooks w
CROSS JOIN LATERAL (
  SELECT max(d.last_at) AS last_ok FROM webhook_deliveries d
  WHERE d.endpoint_id = w.id AND {_COUNTED} AND d.status = 'delivered'
) ok
CROSS JOIN LATERAL (
  SELECT min(d.first_at) AS first_failed, max(d.last_at) AS last_failed, count(*) AS n
  FROM webhook_deliveries d
  WHERE d.endpoint_id = w.id AND {_COUNTED} AND d.status IN ('failed', '{RETRYING}')
    AND d.first_at > COALESCE(ok.last_ok, '-infinity'::timestamptz)
) s
WHERE w.active AND w.paused_at IS NULL
  AND s.n >= 2
  AND s.first_failed <= now() - CAST(:streak AS interval)
  AND s.last_failed >= now() - CAST(:still AS interval)
  AND s.last_failed - s.first_failed >= CAST(:span AS interval)
ORDER BY w.id
"""


@dataclass(frozen=True, slots=True)
class Paused:
    endpoint_id: UUID
    paused_at: datetime
    failing_since: datetime


async def pause_tripped(session: AsyncSession, *, tenant_id: UUID) -> list[Paused]:
    """Pause every endpoint of this tenant whose streak has tripped, in this transaction,
    and promise each owner notice once per pause. CAS on `paused_at IS NULL`, so two
    sweeps pause an endpoint once."""
    tripped = (
        await session.execute(
            text(_TRIPPED_SQL), {"streak": STREAK, "still": STILL_FAILING, "span": MIN_SPAN}
        )
    ).all()
    paused: list[Paused] = []
    for endpoint_id, first_failed in tripped:
        row = (
            await session.execute(
                text(
                    "UPDATE outbound_webhooks SET paused_at = now(), failing_since = :since, "
                    "updated_at = now() WHERE id = :id AND active AND paused_at IS NULL "
                    "RETURNING paused_at"
                ),
                {"id": endpoint_id, "since": first_failed},
            )
        ).first()
        if row is None:
            continue
        item = Paused(
            endpoint_id=UUID(str(endpoint_id)), paused_at=row[0], failing_since=first_failed
        )
        await enqueue_outbox_once(
            session,
            job=PAUSED_NOTICE_JOB,
            payload={"tenant_id": str(tenant_id), "endpoint_id": str(item.endpoint_id)},
            dedupe_key=f"endpoint-paused:{item.endpoint_id}:{item.paused_at.isoformat()}",
        )
        await write_audit(
            session,
            action=ENDPOINT_PAUSED,
            actor=None,
            actor_type="system",
            tenant_id=tenant_id,
            object_type="outbound_webhook",
            object_id=str(item.endpoint_id),
            summary={"failing_since": item.failing_since.isoformat()},
        )
        log.info(
            "outbound_endpoint_paused",
            extra={"tenant_id": str(tenant_id), "endpoint_id": str(item.endpoint_id)},
        )
        paused.append(item)
    return paused


#: The deliveries Resume puts back on the sweep: every held one, and every one that failed
#: during the streak whose body the outbox still holds (`service.resend_delivery`'s test of
#: "can it be sent again"). A held delivery whose body is gone goes back too, and the sweep
#: settles it `failed` with `delivery_body_not_held`, the same as any retry whose body was
#: pruned. Spaced a millisecond apart in `created_at` order, because the sweep claims oldest
#: `next_attempt_at` first.
_REPLAY_SQL: Final = f"""
WITH due AS (
  SELECT d.id, row_number() OVER (ORDER BY d.created_at, d.id) AS n
  FROM webhook_deliveries d
  WHERE d.endpoint_id = :eid AND d.direction = 'out' AND NOT d.is_test
    AND (d.status = '{HELD}'
      OR (d.status = 'failed' AND d.first_at >= :since
          AND EXISTS (SELECT 1 FROM outbox_messages m WHERE m.id = d.outbox_message_id
                      AND m.payload <> '{{}}'::jsonb)))
)
UPDATE webhook_deliveries d SET status = '{RETRYING}',
  next_attempt_at = now() + due.n * interval '1 millisecond', reason = NULL, last_at = now()
FROM due WHERE d.id = due.id
"""


@dataclass(frozen=True, slots=True)
class Resumed:
    resumed: bool
    replayed: int


async def resume_endpoint(session: AsyncSession, *, endpoint_id: UUID) -> Resumed:
    """Unpause and replay. Idempotent: an endpoint that is not paused answers
    `resumed=False, replayed=0`, so a second click is not an error. MUST run inside the
    owner's `tenant_session`: the endpoint is found through RLS, and `webhook_deliveries`
    (no policy) is reached only by an endpoint id that passed it. The caller writes the
    audit row, with the person and their address."""
    row = (
        await session.execute(
            text(
                # RETURNING reads the new row, so the streak's start comes from the locked
                # old one.
                "WITH old AS (SELECT id, failing_since, paused_at FROM outbound_webhooks "
                "  WHERE id = :id AND active AND paused_at IS NOT NULL FOR UPDATE) "
                "UPDATE outbound_webhooks w SET paused_at = NULL, failing_since = NULL, "
                "updated_at = now() FROM old WHERE w.id = old.id "
                "RETURNING old.failing_since, old.paused_at"
            ),
            {"id": endpoint_id},
        )
    ).first()
    if row is None:
        found = (
            await session.execute(
                text("SELECT active FROM outbound_webhooks WHERE id = :id"), {"id": endpoint_id}
            )
        ).first()
        if found is None:
            raise ProblemError.not_found("Endpoint")
        if not found[0]:
            raise ProblemError.business_rule(
                "endpoint_inactive",
                "This endpoint is switched off, so there is nothing to resume.",
                remediation="Add the destination again to start sending to it.",
            )
        return Resumed(resumed=False, replayed=0)
    since = row[0] or row[1]
    replayed = rowcount_of(
        await session.execute(text(_REPLAY_SQL), {"eid": endpoint_id, "since": since})
    )
    return Resumed(resumed=True, replayed=replayed)


__all__ = [
    "ENDPOINT_PAUSED",
    "ENDPOINT_RESUMED",
    "HELD",
    "MIN_SPAN",
    "PAUSED_NOTICE_JOB",
    "STILL_FAILING",
    "STREAK",
    "Paused",
    "Resumed",
    "pause_tripped",
    "resume_endpoint",
]
