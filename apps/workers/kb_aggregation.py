"""The weekly knowledge digest: what callers asked, as counts, to the business owner.

WHAT THIS IS AND WHAT IT DELIBERATELY IS NOT
---------------------------------------------
It is the aggregation half of the collective-knowledge lane: post-call rows in, distilled
patterns out (`apps/api/kb/patterns.py`), one email per agent per week to the client who
owns it. It is ADVICE — "your callers keep asking about X and the agent did not capture
it" — and it changes nothing about any agent.

It is NOT a publish path, and the distinction is the most important sentence in this
module. Hard rule 5's guarantee (an agent always answers truthfully about being an AI and
about being recorded) is enforced by `compose_engine_prompt` at PUBLISH time and re-proved
by the drift sweep. Anything that changed what an agent says without going through
`kb.service.publish_source` would be a second publish path, and a second publish path is
the most serious defect this repository could ship. So the digest's call to action is a
sentence telling the owner to open the Knowledge screen, which submits through the
existing gate — client submits, admin approves, T0 recompiles, the floor is re-appended.

WHY EMAIL AND NOT A QUEUE THE OWNER APPROVES
---------------------------------------------
A reviewable suggestion queue needs a durable, tenant-scoped, RLS'd table to hold a
suggestion and its state, and this wave cannot ship a migration. The choice was therefore
between an approval queue that half exists and a smaller loop that is entirely closed.
The digest is the closed one: it is computed, delivered, and acted on through a screen
that already works. `docs/` carries the table design for when a migration is available.

FAILURE POLICY: THE NEXT TICK IS THE RETRY
--------------------------------------------
Each agent is processed independently and a failure on one never fails the tick for the
rest — `kb_reconciliation`'s argument, and it matters more here because the failure this
job actually meets is a mail transport, which fails for everybody at once or for nobody.
There is no per-agent retry ladder and no dedupe row, and both omissions are deliberate:
a digest is a weekly summary of a window that does not move, so re-sending it next week is
the repair, and re-sending it twice this week is a nuisance rather than a defect. What is
NOT allowed is silence, so a tick that could not reach somebody alerts.

THE ONE INVARIANT THAT MAKES THAT SAFE: **`_sweep` NEVER RAISES AFTER IT HAS SENT
ANYTHING.** The tick sits behind arq's retry ladder, and a ladder over a loop that mails
is a loop that re-mails its whole PREFIX on every attempt — the agents before the one that
threw, three times over, while the agent that threw never gets a digest at all. Two things
hold the invariant, and both were defects here before they were rules:

* `_digest_one` contains everything about one agent INCLUDING THE SEND. The transports
  return False for the failures they expect (`workers/transport.py`), but `get_transport`
  reads settings, `asyncio.to_thread` re-raises whatever the thread raised, and an
  unexpected exception class from an HTTP client is not a hypothetical — leaving the send
  outside the guard made a single SMTP hiccup on agent 700 re-mail 699 clients.
* a `CallContentLeakError` is NOT retried. It is a deterministic code defect: the same
  window, the same vocabulary and the same rows will refuse it again on every attempt, so
  a ladder cannot fix it and can only multiply the mailing it was raised to stop. It
  alerts once and stops.

What remains raisable in `_sweep` is the one read that happens BEFORE the loop, which is
exactly where a retry costs nothing. `alert()` never raises (by contract, `core/alerting`),
so the tail of the sweep cannot undo a completed pass either.

HARD RULE 6
------------
Every log line and every alert carries ids and counts. No email address, no agent name, no
label, no count of any single caller's anything. The digest BODY is assembled from a
template, our own counts and the client's own extraction-schema labels, and
`patterns.assert_text_carries_no_call_content` re-checks the finished string — a
`CallContentLeakError` at that point is a code defect and pages rather than being swallowed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from arq import Retry
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.crm.performance import IST_ZONE
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb.insights import insights_for_agent, render_digest
from apps.api.kb.patterns import CallContentLeakError
from apps.api.quality.sampling import ist_week_start
from apps.workers.transport import get_transport

log = get_logger(__name__)

DIGEST_SUBJECT = "What your callers asked this week"

#: Monday, in the worker's own clock. arq evaluates cron fields in the worker's timezone,
#: so the SCHEDULE is not what decides which week is summarised — `closed_week` is, from
#: the firing instant converted to IST. `qa_sampling` makes the same separation for the
#: same reason, and it is the difference between a job that fires on the right minute and
#: a job that summarises the right seven days.
#:
#: 07:05 rather than the small hours: this is the one job in the tree whose output a human
#: reads on the morning it arrives, and a digest timestamped 03:00 looks automated in a
#: way that a Monday-morning one does not. It is also clear of the nightly retention and
#: pruning sweeps (03:40, 04:10), which is where the database is busy.
DIGEST_WEEKDAY = 0
DIGEST_HOUR = 7
DIGEST_MINUTE = 5

#: Agents whose owner gets a digest in one tick. The arithmetic that justifies it: one
#: bounded SELECT and one SMTP send per agent, at roughly a second each in the worst case,
#: is under half an hour at this ceiling — comfortably inside a weekly interval, so no
#: lease and no single-flight is needed.
#:
#: A fleet ABOVE the ceiling is not silently truncated: `_sweep` alerts, because a sweep
#: that skipped work reports fewer sends, which reads exactly like a quiet week.
KB_DIGEST_MAX_AGENTS = 1_500

_IST_TZ = ZoneInfo(IST_ZONE)

#: Live agents, one row per agent however many vendor objects it has. `engine_agent_routes`
#: is the deliberately-GLOBAL routing table (its own model says so), which is what makes a
#: cross-tenant enumeration possible at all — `agents` is tenant-scoped and an untenanted
#: read of it returns zero rows by design.
#:
#: DISTINCT is load-bearing: D-380 gives a prompt experiment's each arm its own
#: `engine_agent_ref` on this table, so an agent under test has several active rows and
#: would otherwise be mailed about several times in one tick.
_LIVE_AGENTS_SQL = (
    "SELECT DISTINCT tenant_id, agent_id FROM engine_agent_routes WHERE active "
    "ORDER BY tenant_id, agent_id LIMIT :limit"
)

#: The agent's own name and the tenant's notification address, in one read. `billing_email`
#: is the address every other client-facing notification in this tree uses
#: (`workers/notifications.py`); a second address column for a second kind of mail would be
#: a second answer to "where do we write to this client".
_RECIPIENT_SQL = (
    "SELECT a.name, o.billing_email FROM agents a "
    "JOIN organizations o ON o.id = a.tenant_id "
    "WHERE a.id = :aid AND a.status = 'live'"
)


@dataclass(frozen=True, slots=True)
class _Target:
    tenant_id: UUID
    agent_id: UUID


def closed_week(moment: datetime) -> tuple[datetime, datetime]:
    """The seven IST days that had ENDED when the job fired, as a UTC half-open interval.

    Half-open — `[since, until)` — so a call that ended exactly at the IST week boundary
    is counted once, in the week it belongs to, rather than in both or neither. The
    interval is returned in UTC because `calls.ended_at` is `timestamptz` and the
    comparison happens in the database; the IST-ness is in where the boundaries were CUT,
    which is what makes it an Indian business week (`quality/sampling` argues this at
    length for the QA draw and this is the same argument, so the Monday comes from that
    module rather than being computed a second way here).
    """
    this_monday = ist_week_start(moment)
    until_local = datetime.combine(this_monday, time.min, tzinfo=_IST_TZ)
    return (until_local - timedelta(days=7)).astimezone(UTC), until_local.astimezone(UTC)


async def send_agent_knowledge_digests(ctx: dict[str, Any], *_: object) -> str:
    """The tick. Behind the retry ladder, because a tick that dies has no next chance
    for a week — `apply_retention`'s argument, on a weekly cadence rather than a nightly.
    """
    attempt = int(ctx.get("job_try", 1))
    try:
        return await _sweep(datetime.now(UTC))
    except Retry:
        raise
    except CallContentLeakError:
        # NOT RETRIED, and this arm is the reason the module docstring's invariant is a
        # rule rather than an observation. `_digest_one` has already alerted and the
        # refusal is deterministic — same window, same vocabulary, same rows — so a
        # second and third attempt cannot deliver the digest that was refused and can
        # only re-mail every client the sweep had already reached before it. A privacy
        # alarm that triples the mailing is worse than the leak it is guarding against.
        raise
    except Exception as exc:
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=30.0 * attempt) from exc
        alert(
            "WORKER_TERMINAL",
            "kb_digest_sweep_abandoned",
            detail=(
                f"the weekly knowledge digest failed every attempt ({type(exc).__name__}); "
                "no client received one this week"
            ),
        )
        raise


async def _sweep(now: datetime) -> str:
    since, until = closed_week(now)

    async with untenanted_session() as session:
        rows = (
            await session.execute(text(_LIVE_AGENTS_SQL), {"limit": KB_DIGEST_MAX_AGENTS + 1})
        ).all()
    truncated = len(rows) > KB_DIGEST_MAX_AGENTS
    targets = [
        _Target(tenant_id=UUID(str(row[0])), agent_id=UUID(str(row[1])))
        for row in rows[:KB_DIGEST_MAX_AGENTS]
    ]

    sent = skipped = failed = 0
    for target in targets:
        outcome = await _digest_one(target, since=since, until=until)
        if outcome == "sent":
            sent += 1
        elif outcome == "failed":
            failed += 1
        else:
            skipped += 1

    if failed or truncated:
        alert(
            "WORKER_DELIVERY",
            "kb_digest_undelivered",
            detail=(
                f"{failed} weekly knowledge digest(s) could not be delivered"
                + (
                    f"; the fleet exceeds the per-tick ceiling of {KB_DIGEST_MAX_AGENTS} "
                    "agents, so the tail of the ordering was not reached at all"
                    if truncated
                    else ""
                )
            ),
        )
    log.info(
        "kb_digest_sweep",
        extra={"sent": sent, "skipped": skipped, "failed": failed, "agents": len(targets)},
    )
    return f"sent={sent} skipped={skipped} failed={failed}"


async def _digest_one(target: _Target, *, since: datetime, until: datetime) -> str:
    """One agent: distil, render, send. Never raises for one agent's sake.

    `CallContentLeakError` is the one exception that is NOT contained. Every other failure
    here is about this agent — a missing address, a schema that will not validate, a mail
    server — and containing it is what stops one sick tenant costing the rest their
    digest. A leak is about the CODE: it means a pattern or a rendered line named something
    no vocabulary declares, on this tenant and therefore plausibly on every tenant, and the
    correct response is to stop the sweep and page. Continuing would send the other
    fourteen hundred digests while the reason to doubt them was logged and stepped over.
    """
    try:
        async with tenant_session(target.tenant_id) as session:
            recipient = (
                await session.execute(text(_RECIPIENT_SQL), {"aid": target.agent_id})
            ).first()
            if recipient is None:
                return "skipped"
            agent_name, billing_email = recipient
            if not billing_email:
                return "skipped"

            insights = await insights_for_agent(
                session, agent_id=target.agent_id, since=since, until=until
            )
        if insights is None:
            return "skipped"

        body = render_digest(insights, agent_name=str(agent_name))
        if body is None:
            # A quiet week, or one that did not clear the k-anonymity floors. Not an
            # error and not a failure to deliver: there is nothing to say, and a weekly
            # email saying nothing is how a client learns to filter this address.
            return "skipped"
        # INSIDE THE GUARD. The transports answer False for the failures they expect, but
        # `get_transport()` reads settings and `asyncio.to_thread` re-raises whatever the
        # thread raised — and an exception escaping here escapes `_sweep`, which puts the
        # tick back on the retry ladder and re-mails every client already reached in this
        # pass. See the module docstring's invariant.
        delivered = await _send(str(billing_email), body)
    except CallContentLeakError:
        alert(
            "WORKER_TERMINAL",
            "kb_digest_content_refused",
            detail=(
                "the aggregate guard refused a knowledge digest: a pattern or a rendered "
                "line named something the agent's own vocabulary does not declare. The "
                "sweep is stopped; no further digests were sent"
            ),
            tenant_id=str(target.tenant_id),
            agent_id=str(target.agent_id),
        )
        raise
    except Exception as exc:
        # Deliberately broad and deliberately NOT swallowed — the return value is the
        # record, and the tick alerts on the count. What reaches here is one tenant's
        # data or one tenant's session; the type locates it without naming anything.
        log.warning(
            "kb_digest_failed",
            extra={
                "tenant_id": str(target.tenant_id),
                "agent_id": str(target.agent_id),
                "reason": type(exc).__name__,
            },
        )
        return "failed"

    log.info(
        "kb_digest",
        extra={
            "tenant_id": str(target.tenant_id),
            "agent_id": str(target.agent_id),
            "patterns": len(insights.patterns),
            "calls": insights.calls,
            "delivered": delivered,
        },
    )
    return "sent" if delivered else "failed"


async def _send(to: str, body: str) -> bool:
    """Off the event loop, for `notifications._send_email`'s reason: the SMTP transport is
    synchronous socket I/O on a timeout budget, and awaiting it inline would park every
    other job in this worker — including the 30-second campaign dispatch tick that hard
    rule 5's DNC deadline is defined against."""
    transport = get_transport()
    return await asyncio.to_thread(lambda: transport.send(to=to, subject=DIGEST_SUBJECT, body=body))


__all__ = [
    "DIGEST_HOUR",
    "DIGEST_MINUTE",
    "DIGEST_SUBJECT",
    "DIGEST_WEEKDAY",
    "KB_DIGEST_MAX_AGENTS",
    "closed_week",
    "send_agent_knowledge_digests",
]
