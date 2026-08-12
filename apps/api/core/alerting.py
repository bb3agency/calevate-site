"""One alert function with a normalized failure_stage (BACKEND-PATTERNS §8).

The point of the enum: "where in the pipeline did this die" must be answerable from
the alert alone, without reading code.

**An alert has to reach a person.** OPERATIONS §4 promises "alerts (WhatsApp/email to
Sri)" and §8 makes "alerts firing to Sri's phone" a pre-launch gate. Until this file
grew a delivery path, `alert()` wrote an ERROR log line and stopped — so an exhausted
outbound webhook, an unkeyable engine payload, a stalled pipeline and a bad payment
signature all fired into a log nobody reads at 3am. The log line is still emitted
FIRST and unconditionally: it is the durable record, and delivery is best-effort on
top of it.

WHAT RUNS INLINE, AND WHAT DOES NOT. `alert()` is called from request handlers —
including `apps/voice-runtime`, whose entire ack budget is 500ms (hard rule 3) — from
ARQ workers, from the global exception handler, and from a SIGTERM handler. Inline it
therefore does only three things that cannot block: a log record, a dict lookup under
a non-blocking lock, and `put_nowait` on a bounded queue. Everything with an I/O
timeout attached — `SmtpTransport` waits up to 15 seconds for a socket — happens on a
single daemon thread. A blocking SMTP call inside a webhook handler would mean the
alerting system causing the outage it exists to report.

WHY NOT THE OUTBOX. Every other side effect in this repo goes through the
transactional outbox (BACKEND-PATTERNS §4), and this one deliberately does not: the
alarms that matter most are `outbox_dispatch_exhausted`, `pipeline_stalled` and
`enqueue_failed` — "the thing that delivers work is broken". An alert routed through
the broken component is an alert nobody gets. This path touches no database and no
Redis, so it survives the failures it reports. The cost is honest and bounded: a
process that dies with alerts queued loses those SENDS, never the log lines.

DEDUPLICATION AND RATE LIMITING are part of "reaches a human" — an inbox with 4,000
copies of one bad deploy is the same as no alert at all. Two bounds, both taken from
the established shape rather than invented:

* **Per-fingerprint repeat suppression**, the analogue of Alertmanager's
  `repeat_interval`: an alert is identified by a fingerprint (there, a hash of the
  label set; here `stage:code`), the first occurrence notifies immediately, and
  repeats inside the window are counted rather than sent — the count then rides the
  next delivery, so "still broken, 199 times" never reads as "happened once".
  Alertmanager's own default is 4h with `group_wait` 30s of batching in front; we use
  15 minutes and no batching, because there is ONE operator with no incident console
  to check, so the first signal must be immediate and staleness is the bigger risk.
  (https://prometheus.io/docs/alerting/latest/configuration/ — route `group_wait` 30s,
  `group_interval` 5m, `repeat_interval` 4h; PagerDuty's Events API v2 does the same
  thing with a caller-supplied `dedup_key`, which is why every alert here carries a
  stable code rather than a formatted string:
  https://developer.pagerduty.com/docs/events-api-v2/trigger-events/)
* **A global token bucket**, because dedupe alone does not survive a bad deploy: 500
  distinct codes are 500 distinct fingerprints. Bucket = `ALERT_BURST` tokens refilled
  at `ALERT_BUDGET_PER_HOUR`. What the bucket drops is counted and reported on the
  next delivery, so the toll is visible instead of silent.

Metrics are NAMED DOMAIN RECORDERS, not ad-hoc counters — the recorder names become
the SLO rule vocabulary (OPERATIONS §4), so adding one is a deliberate act.
"""

from __future__ import annotations

import atexit
import queue
import threading
import time
from dataclasses import dataclass
from typing import Literal

from apps.api.core.logging import get_logger, redact_mapping

log = get_logger("calevate.alert")
metrics_log = get_logger("calevate.metric")

FailureStage = Literal[
    "ROUTE_HANDLER",
    "CORE_LOGIC",
    "QUEUE_ENQUEUE",
    "OUTBOX_DISPATCH",
    "WORKER_DELIVERY",
    "WORKER_TERMINAL",
    "WORKER_STALL",
    "PROCESS_RESTART",
]


def alert(stage: FailureStage, code: str, *, detail: str | None = None, **ids: str) -> None:
    """Fire the alert path. `detail` must be a message we authored — never a payload.

    Returns as soon as the log record is written and the notice is queued. Never
    raises: this is called from an exception handler and from a signal handler, and
    failing on top of the failure being reported helps nobody.
    """
    log.error("alert", extra={"failure_stage": stage, "code": code, "detail": detail, **ids})
    try:
        _dispatch(stage, code, detail, ids)
    except Exception as exc:
        log.error("alert_dispatch_failed", extra={"code": code, "reason": type(exc).__name__})


# --- Delivery -----------------------------------------------------------------

# Per-fingerprint repeat suppression (Alertmanager's `repeat_interval`, tightened —
# see the module docstring for why 15 minutes and not 4 hours).
ALERT_REPEAT_INTERVAL_S = 900.0
# The global bound. Six in a burst is enough for "several things broke at once" to be
# legible on a phone; twenty an hour is more than one person can act on anyway.
ALERT_BURST = 6
ALERT_BUDGET_PER_HOUR = 20.0
# Bounded on purpose: an unbounded queue in front of a 15-second SMTP timeout is a
# memory leak with a delay fuse. Overflow is counted and logged, never awaited.
ALERT_QUEUE_MAX = 256
# One retry, on the delivery thread, for the blip case (a refused TCP connection, a
# greylisting 4xx). Longer than this belongs to the operator, not to a daemon thread.
DELIVERY_RETRY_DELAY_S = 5.0


@dataclass(frozen=True)
class AlertNotice:
    """What the delivery thread needs, captured at fire time. Frozen because it
    crosses a thread boundary and the caller has already moved on."""

    stage: FailureStage
    code: str
    detail: str | None
    ids: dict[str, str]
    suppressed: int
    rate_limited: int


_service = "api"
_state_lock = threading.Lock()
_last_sent: dict[str, float] = {}
_suppressed: dict[str, int] = {}
_rate_limited = 0
_tokens = float(ALERT_BURST)
_tokens_refilled_at = 0.0
_queue: queue.Queue[AlertNotice | None] = queue.Queue(maxsize=ALERT_QUEUE_MAX)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
# Re-entrancy is per-thread: the delivery thread must be able to swallow an alert
# raised by the transport it is calling, while other threads keep alerting normally.
_local = threading.local()
_unconfigured_warned = False


def _now() -> float:
    """Monotonic, and a function so tests can hold the clock still."""
    return time.monotonic()


def configure_alerts(*, service: str) -> None:
    """Name the process in every alert. Called from `init_observability`, which is the
    one place that already knows whether it is `api`, `voice-runtime` or `workers` —
    and "which process" is the first question an operator asks at 3am."""
    global _service
    _service = service


def _recipient() -> str | None:
    from apps.api.core.settings import get_settings

    return get_settings().alerts_email or None


def _dispatch(stage: FailureStage, code: str, detail: str | None, ids: dict[str, str]) -> None:
    if getattr(_local, "delivering", False):
        # Reached from inside the delivery path. The log line above already happened;
        # queueing here is how a broken transport becomes an infinite loop.
        return
    recipient = _recipient()
    if not recipient:
        _warn_unconfigured_once()
        return
    verdict = _admit(f"{stage}:{code}")
    if verdict is None:
        return
    suppressed, rate_limited = verdict
    notice = AlertNotice(
        stage=stage,
        code=code,
        detail=detail,
        ids=dict(ids),
        suppressed=suppressed,
        rate_limited=rate_limited,
    )
    try:
        _queue.put_nowait(notice)
    except queue.Full:
        # The alarm is not lost — the ERROR log line is already written. What is lost
        # is this SEND, and that fact is itself logged rather than swallowed.
        log.error("alert_queue_overflow", extra={"code": code, "depth": ALERT_QUEUE_MAX})
        return
    _ensure_worker()


def _warn_unconfigured_once() -> None:
    global _unconfigured_warned
    if _unconfigured_warned:
        return
    _unconfigured_warned = True
    log.warning("alert_delivery_unconfigured", extra={"service": _service})


def _admit(fingerprint: str) -> tuple[int, int] | None:
    """The two bounds. Returns (suppressed, rate_limited) to report, or None to drop.

    The lock is taken NON-BLOCKING on purpose. `apps/api/core/bootstrap.py` installs a
    SIGTERM handler that calls `alert()`, and a signal handler runs on the main thread
    — which may be the thread already inside this function. Blocking there would
    deadlock the process during a drain. An un-deduplicated send is the deliberate
    trade: at most one extra message, and only for an alert that arrived during a
    signal.
    """
    global _rate_limited
    if not _state_lock.acquire(blocking=False):
        return (0, 0)
    try:
        now = _now()
        last = _last_sent.get(fingerprint)
        if last is not None and now - last < ALERT_REPEAT_INTERVAL_S:
            _suppressed[fingerprint] = _suppressed.get(fingerprint, 0) + 1
            return None
        if not _take_token(now):
            _rate_limited += 1
            return None
        _last_sent[fingerprint] = now
        suppressed = _suppressed.pop(fingerprint, 0)
        rate_limited, _rate_limited = _rate_limited, 0
        return (suppressed, rate_limited)
    finally:
        _state_lock.release()


def _take_token(now: float) -> bool:
    global _tokens, _tokens_refilled_at
    if _tokens_refilled_at == 0.0:
        _tokens_refilled_at = now
    _tokens = min(
        float(ALERT_BURST),
        _tokens + (now - _tokens_refilled_at) * (ALERT_BUDGET_PER_HOUR / 3600.0),
    )
    _tokens_refilled_at = now
    if _tokens < 1.0:
        return False
    _tokens -= 1.0
    return True


def _forget(fingerprint: str) -> None:
    """Undo the suppression stamp after a delivery that never landed.

    The window means "a human has been told". A transport that returned False told
    nobody, so keeping the stamp would let one SMTP blip silence an alarm for the whole
    window. Best-effort under the same non-blocking lock, for the same reason.
    """
    if not _state_lock.acquire(blocking=False):
        return
    try:
        _last_sent.pop(fingerprint, None)
    finally:
        _state_lock.release()


def _ensure_worker() -> None:
    global _worker
    worker = _worker
    if worker is not None and worker.is_alive():
        return
    if not _worker_lock.acquire(blocking=False):
        return  # another thread is starting it; the notice is already queued
    try:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, name="calevate-alerts", daemon=True)
            _worker.start()
    finally:
        _worker_lock.release()


def _drain() -> None:
    while True:
        notice = _queue.get()
        # Read before the try: an exception must still be able to name the alert it
        # lost, and `None` is the shutdown sentinel rather than a notice.
        code = "shutdown" if notice is None else notice.code
        try:
            if notice is None:
                return
            _deliver(notice)
        except Exception as exc:
            log.error(
                "alert_delivery_crashed",
                extra={"code": code, "reason": type(exc).__name__},
            )
        finally:
            _queue.task_done()


def _deliver(notice: AlertNotice) -> None:
    """Runs ONLY on the delivery thread.

    The transport import is here rather than at module scope for two reasons that
    happen to agree: `apps/voice-runtime` imports this module and is forbidden to hold
    `apps.workers` (tests/voice_runtime_import_surface_test.py, hard rule 3), and
    `smtplib` has no business being on the ack path's import graph. One transport, the
    same one hot-lead notifications use — a second delivery mechanism would be a second
    thing to configure and a second thing to be broken.
    """
    recipient = _recipient()
    if recipient is None:
        return
    _local.delivering = True
    try:
        from apps.workers.transport import get_transport

        transport = get_transport()
        subject = _subject(notice)
        body = _body(notice)
        for attempt in (1, 2):
            if transport.send(to=recipient, subject=subject, body=body):
                log.info(
                    "alert_delivered",
                    extra={"code": notice.code, "transport": transport.name, "attempts": attempt},
                )
                return
            if attempt == 1 and DELIVERY_RETRY_DELAY_S:
                time.sleep(DELIVERY_RETRY_DELAY_S)
        log.error(
            "alert_delivery_failed",
            extra={
                "code": notice.code,
                "failure_stage": notice.stage,
                "transport": transport.name,
            },
        )
        _forget(f"{notice.stage}:{notice.code}")
    finally:
        _local.delivering = False


def _subject(notice: AlertNotice) -> str:
    """What a phone shows on a lock screen. Code first — it is the searchable token."""
    from apps.api.core.settings import get_settings

    return f"[calevate/{get_settings().app_env}/{_service}] {notice.code}"


def _body(notice: AlertNotice) -> str:
    """Ids only (hard rule 6), through the SAME redaction the logger uses.

    `detail` is authored by us but is routinely an upstream error string, and an id
    kwarg is whatever the call site passed — so both go through `redact_mapping`,
    which masks phone-shaped runs, blanks PII-shaped KEYS and caps free text. An email
    leaves the building; it is the last place to trust a caller.
    """
    safe = redact_mapping({"detail": notice.detail or "", **notice.ids})
    detail = str(safe.pop("detail", ""))
    lines = [
        f"stage:   {notice.stage}",
        f"code:    {notice.code}",
        f"service: {_service}",
    ]
    if detail:
        lines.append(f"detail:  {detail}")
    lines += [f"{key}: {value}" for key, value in sorted(safe.items())]
    if notice.suppressed:
        lines.append(
            f"note:    {notice.suppressed} further occurrence(s) of this alert were "
            f"suppressed in the last {ALERT_REPEAT_INTERVAL_S / 60:.0f} minutes"
        )
    if notice.rate_limited:
        lines.append(
            f"note:    {notice.rate_limited} other alert(s) were dropped by the rate "
            f"limit ({ALERT_BUDGET_PER_HOUR:.0f}/hour) since the last delivery"
        )
    lines.append("")
    lines.append(f"Search the logs for code={notice.code} for the full context.")
    return "\n".join(lines)


def flush_alerts(timeout: float = 5.0) -> bool:
    """Wait for queued alerts to be delivered. Returns whether the queue emptied.

    `Queue.join()` with a deadline — the shutdown hook must not hang a drain, and a
    test must not sleep on a guess.
    """
    with _queue.all_tasks_done:
        return bool(_queue.all_tasks_done.wait_for(lambda: _queue.unfinished_tasks == 0, timeout))


def reset_alerts() -> None:
    """Test seam: forget the suppression window, the bucket and the counters. The
    delivery thread is left running — it is a daemon holding no state between notices,
    and stopping it would race a test that is already inside one."""
    global _rate_limited, _tokens, _tokens_refilled_at, _unconfigured_warned
    flush_alerts(timeout=5.0)
    with _state_lock:
        _last_sent.clear()
        _suppressed.clear()
        _rate_limited = 0
        _tokens = float(ALERT_BURST)
        _tokens_refilled_at = 0.0
    _unconfigured_warned = False


@atexit.register
def _flush_on_exit() -> None:
    """A queued alert on a process that is shutting down is usually the MOST important
    one — `signal_received` and `unhandled_exception` both alert on the way out. Short
    deadline: a drain that hangs on SMTP is worse than a lost send."""
    flush_alerts(timeout=DELIVERY_RETRY_DELAY_S + 2.0)


# --- Named metric recorders ---------------------------------------------------
# One function per SLO-relevant quantity. Adding a recorder is how a new SLO gets
# a vocabulary; ad-hoc counters are not accepted (§8).


def _record(name: str, value: float, **labels: str) -> None:
    metrics_log.info("metric", extra={"metric": name, "value": value, **labels})


def record_webhook_ack_ms(ms: float, *, provider: str) -> None:
    """Hard rule 3's budget: voice-runtime must ack in < 500ms."""
    _record("webhook_ack_ms", ms, provider=provider)


def record_pipeline_lag(seconds: float, *, stage: str) -> None:
    """Post-call SLO: lead visible within 2 minutes of hangup (OPERATIONS §4)."""
    _record("pipeline_lag_seconds", seconds, stage=stage)


def record_outbox_lag(seconds: float) -> None:
    _record("outbox_lag_seconds", seconds)


def record_outbox_dlq_depth(depth: int) -> None:
    _record("outbox_dlq_depth", depth)


def record_extraction_failure(*, reason: str) -> None:
    _record("extraction_failures", 1, reason=reason)


def record_reconciliation_repair(*, kind: str) -> None:
    """A call the poller had to fix = a webhook we never got (D-31's whole point)."""
    _record("reconciliation_repairs", 1, kind=kind)


def record_compliance_block(*, rule: str) -> None:
    _record("compliance_blocks", 1, rule=rule)


__all__ = [
    "ALERT_BUDGET_PER_HOUR",
    "ALERT_BURST",
    "ALERT_QUEUE_MAX",
    "ALERT_REPEAT_INTERVAL_S",
    "AlertNotice",
    "FailureStage",
    "alert",
    "configure_alerts",
    "flush_alerts",
    "record_compliance_block",
    "record_extraction_failure",
    "record_outbox_dlq_depth",
    "record_outbox_lag",
    "record_pipeline_lag",
    "record_reconciliation_repair",
    "record_webhook_ack_ms",
    "reset_alerts",
]
