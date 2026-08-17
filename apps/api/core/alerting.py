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
the broken component is an alert nobody gets. This path touches no database, and the
one Redis call it makes CAN ONLY SUPPRESS — see the next paragraph — so it still
survives the failures it reports. The cost is honest and bounded: a process that dies
with alerts queued loses those SENDS, never the log lines.

THE BOUNDS ARE PER SERVICE, NOT PER PROCESS (D-160). This module's globals were the
whole story while every service ran one process, and `compose.prod.yml` has run
voice-runtime with `--workers=4` since D-55 answered the 500ms ack budget — so four
processes kept four windows and, worse, four token buckets, quietly making a
deliberate 20/hour bound into 80/hour. `core/alert_admission.py` moves the real
decision into one atomic Redis script keyed by service, and the globals below stay as
a per-process PRE-FILTER whose job is now only to keep one process from flooding its
own bounded queue. **The shared gate fails OPEN, absolutely**: unreachable, slow or
unreadable Redis all return "send". A cache outage therefore costs deduplication and
never delivery, which leaves the paragraph above true — the alert path cannot be
silenced by the infrastructure it exists to report on.

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
  at `ALERT_BUDGET_PER_HOUR`. What the bucket drops is counted AND NAMED on the next
  delivery, so the toll is visible instead of silent.

  Naming it is not a nicety. The bucket is one shared resource and the codes drawing on
  it are not equally important: `webhook_source_rejected` and
  `clerk_webhook_bad_signature` fire from anywhere on the internet with no credential,
  while `postcall_pipeline_stalled` is the alarm the whole system exists to raise. A
  stranger cannot silence the second — dedupe means their repeats are free, so they
  cost at most one token per code per window — but they CAN empty the burst at a moment
  of their choosing, and the refill is one token every three minutes. "12 other alerts
  were dropped" left the operator with no way to know which; the codes ride along now,
  so a dropped `postcall_pipeline_stalled` is a thing they read rather than a thing
  they infer.

Metrics are NAMED DOMAIN RECORDERS, not ad-hoc counters — the recorder names become
the SLO rule vocabulary (OPERATIONS §4), so adding one is a deliberate act.
"""

from __future__ import annotations

import atexit
import queue
import threading
import time
from dataclasses import dataclass, replace
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
    # Not an application stage: the host-side backup chain (`scripts/backup/notify.sh`)
    # emits it from outside Python entirely, so nothing here calls `alert()` with it.
    # It is a member because the alternative was worse — the backup work found no stage
    # that described "the nightly base backup did not run" and refused to mislabel it as
    # WORKER_TERMINAL to make it fit. A wrong stage on the one alarm that says the
    # database is unrecoverable is the wrong place to be tidy.
    "HOST_BACKUP",
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
# How many DISTINCT dropped codes the next delivery names before it stops listing them.
# Bounded because the state it feeds is a module global and the thing that fills it is a
# storm: an unbounded dict here would be the memory leak the queue cap already refuses.
# Twelve is more codes than one message can usefully carry on a phone, and the total
# count is reported whether or not every code fits.
ALERT_DROPPED_CODES_MAX = 12


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
    #: (code, occurrences) for what the bucket refused since the last delivery, most
    #: frequent first. A tuple because this crosses a thread boundary frozen.
    rate_limited_codes: tuple[tuple[str, int], ...] = ()


_service = "api"
_state_lock = threading.Lock()
_last_sent: dict[str, float] = {}
_suppressed: dict[str, int] = {}
_rate_limited = 0
_rate_limited_codes: dict[str, int] = {}
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
    verdict = _admit(f"{stage}:{code}", code)
    if verdict is None:
        return
    suppressed, rate_limited, rate_limited_codes = verdict
    notice = AlertNotice(
        stage=stage,
        code=code,
        detail=detail,
        ids=dict(ids),
        suppressed=suppressed,
        rate_limited=rate_limited,
        rate_limited_codes=rate_limited_codes,
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


def _admit(fingerprint: str, code: str) -> tuple[int, int, tuple[tuple[str, int], ...]] | None:
    """The two bounds. Returns (suppressed, rate_limited, dropped_codes), or None to drop.

    The lock is taken NON-BLOCKING on purpose. `apps/api/core/bootstrap.py` installs a
    SIGTERM handler that calls `alert()`, and a signal handler runs on the main thread
    — which may be the thread already inside this function. Blocking there would
    deadlock the process during a drain. An un-deduplicated send is the deliberate
    trade: at most one extra message, and only for an alert that arrived during a
    signal.
    """
    global _rate_limited
    if not _state_lock.acquire(blocking=False):
        return (0, 0, ())
    try:
        now = _now()
        last = _last_sent.get(fingerprint)
        if last is not None and now - last < ALERT_REPEAT_INTERVAL_S:
            _suppressed[fingerprint] = _suppressed.get(fingerprint, 0) + 1
            return None
        if not _take_token(now):
            _rate_limited += 1
            # Named, not just counted — and only up to the cap, so a storm of distinct
            # codes cannot grow this dict without bound. Once the cap is reached the
            # already-named codes keep counting; the total above covers the rest.
            if code in _rate_limited_codes or len(_rate_limited_codes) < ALERT_DROPPED_CODES_MAX:
                _rate_limited_codes[code] = _rate_limited_codes.get(code, 0) + 1
            return None
        _last_sent[fingerprint] = now
        suppressed = _suppressed.pop(fingerprint, 0)
        rate_limited, _rate_limited = _rate_limited, 0
        dropped = tuple(sorted(_rate_limited_codes.items(), key=lambda item: (-item[1], item[0])))
        _rate_limited_codes.clear()
        return (suppressed, rate_limited, dropped)
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

    BOTH HALVES, since D-160. Clearing only the local dict would leave the SHARED marker
    standing for the rest of the window — and that is worse than the bug this function
    was written for, because the shared marker silences every OTHER worker too. Called
    on the delivery thread, so the Redis half is affordable here.
    """
    from apps.api.core.alert_admission import forget as forget_shared

    forget_shared(service=_service, fingerprint=fingerprint)
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


def _admit_shared(notice: AlertNotice) -> AlertNotice | None:
    """The cross-process half of admission. None means another worker already sent it.

    RUNS ON THE DELIVERY THREAD, which is the only place it may: `_admit` above is
    reached from a SIGTERM handler and from voice-runtime's 500ms ack path, so it must
    stay pure memory. Here a bounded network call is affordable — nothing waits on this
    thread except `flush_alerts`, which has its own deadline.

    The counts are ADDED to what the local pre-filter already gathered, so a message
    reports every occurrence withheld across the whole service rather than the fraction
    this particular worker happened to receive.
    """
    from apps.api.core.alert_admission import admit

    verdict = admit(
        service=_service,
        fingerprint=f"{notice.stage}:{notice.code}",
        window_s=ALERT_REPEAT_INTERVAL_S,
        burst=ALERT_BURST,
        budget_per_hour=ALERT_BUDGET_PER_HOUR,
    )
    if not verdict.admitted:
        # Not an error and not a loss: the ERROR log line was written by `alert()`, and
        # a sibling process is telling this human the same thing right now.
        log.info("alert_suppressed_by_sibling", extra={"code": notice.code})
        return None
    if verdict.suppressed or verdict.rate_limited:
        return replace(
            notice,
            suppressed=notice.suppressed + verdict.suppressed,
            rate_limited=notice.rate_limited + verdict.rate_limited,
        )
    return notice


def _drain() -> None:
    while True:
        notice = _queue.get()
        # Read before the try: an exception must still be able to name the alert it
        # lost, and `None` is the shutdown sentinel rather than a notice.
        code = "shutdown" if notice is None else notice.code
        try:
            if notice is None:
                return
            admitted = _admit_shared(notice)
            if admitted is None:
                continue
            _deliver(admitted)
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
        if notice.rate_limited_codes:
            named = ", ".join(f"{code} x{count}" for code, count in notice.rate_limited_codes)
            # The codes are ours, not a caller's, so they need no redaction — and they
            # are the only way the operator learns WHICH alarm the bucket ate.
            lines.append(f"dropped: {named}")
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
    from apps.api.core.alert_admission import reset_admission

    flush_alerts(timeout=5.0)
    # The shared half too, or a test that resets alerting still inherits the previous
    # test's window from Redis and watches its alert vanish for reasons nothing in the
    # test file explains.
    reset_admission(service=_service)
    with _state_lock:
        _last_sent.clear()
        _suppressed.clear()
        _rate_limited_codes.clear()
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
#
# **EVERY RECORDER BELOW IS A STRUCTURED LOG LINE AND NOTHING ELSE. THERE IS NO
# CONSUMER.** Said here, at the top of the section, because the shape reads like
# telemetry: `_record` looks like a counter, the names read like series and the kwargs
# read like labels. Nothing scrapes them. There is no `/metrics` endpoint, no Prometheus,
# no collector and therefore no alerting rule can be written over any of these numbers —
# `docs/DEPLOYMENT.md` §8 defers the metrics endpoint, and the blocker is a deploy
# decision, not code missing from this file. What a recorder buys today is a greppable
# line with a stable name and stable labels, which is the whole of its value and is worth
# having: `journalctl`/`grep metric=pipeline_lag_seconds` answers the question, and the
# NAMES are the vocabulary an exporter would export unchanged on the day one lands.
#
# THE CONSEQUENCE THAT MATTERS, AND IT IS A RULE: **no alarm may depend on a recorder.**
# A threshold over a counter nobody reads is a promised alarm that cannot fire, which is
# worse than an absent one. Every alarm in this repository therefore travels `alert()`
# above — the email path (D-49), the same relay `scripts/backup/notify.sh` and
# `scripts/host_alert` use from outside Python — and announces itself at the WRITE that
# crosses the line rather than over a rate. `billing/ai_quota._announce_platform_headroom`
# and `billing/caps.announce_cap_headroom` are both that shape, and they are the shape to
# copy. If you find yourself wanting `if record_x() > threshold`, the answer is an
# `alert()` at the producing write, not a consumer for this stream.


def _record(name: str, value: float, **labels: str) -> None:
    """One structured log line. Read the section comment above before adding a caller:
    this reaches a log and no metrics pipeline, and no alarm may be built on it."""
    metrics_log.info("metric", extra={"metric": name, "value": value, **labels})


def record_webhook_ack_ms(ms: float, *, provider: str) -> None:
    """Hard rule 3's budget: voice-runtime must ack in < 500ms."""
    _record("webhook_ack_ms", ms, provider=provider)


def record_tool_ack_ms(ms: float, *, provider: str) -> None:
    """The IN-CALL tool endpoint's ack, against TRD §6.2's 100ms budget.

    A SECOND SERIES RATHER THAN A SECOND LABEL ON THE FIRST. `apps/voice-runtime/
    tool_routes.py` leaves through the receiver's `_ack`, so until this existed every
    in-call tool call was recorded as `webhook_ack_ms{provider=...}` — the same series as
    the post-call webhook receiver, distinguishable by nothing. They are different
    endpoints with different budgets (100ms against 500ms) and an order-of-magnitude
    different cost (0 database statements against 3), so the pooled p95 was a blend of two
    populations: a burst of cheap tool calls DILUTED the receiver's p95 and could hide a
    regression in it, and the tool endpoint's own budget could not be read off the series
    at all. A `surface=` label on one series would have kept the dilution — a percentile
    is computed over the series, not over the label.
    """
    _record("tool_ack_ms", ms, provider=provider)


def record_webhook_replay_divergence(*, provider: str) -> None:
    """A settled transition re-delivered with DIFFERENT body bytes.

    THE ONLY REPLAY SIGNAL AN UNSIGNED ENGINE CAN GIVE US, and until this counter existed
    there was none anywhere. Bolna signs nothing (D-31) and its delivery is at-most-once
    with no retry [TRD §5, verified in the OSS delivery code], so a SECOND delivery of one
    `{execution_id}:{raw_status}` is already a replay rather than a vendor retry — and one
    whose bytes differ from the delivery we settled is somebody composing payloads, not a
    network echo.

    A COUNTER AND NOT AN ALERT, deliberately. `webhook_routes._claim_and_enqueue` argues
    the case for the inbox hash and it applies here unchanged: an engine that DOES retry
    can legitimately re-deliver one transition with a fuller body, and an alarm that fires
    on healthy traffic is one nobody reads when a real one arrives. What the endpoint must
    never do is act on the divergence either — the payload is a hint, the authenticated Get
    Execution is the truth — so this records and moves on.
    """
    _record("webhook_replay_divergence", 1, provider=provider)


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


def record_reconciliation_listing_incomplete(*, reason: str) -> None:
    """A poll that could not promise it saw the whole window (D-31).

    Separate from `record_reconciliation_repair` on purpose: a repair is a call we FIXED,
    this is a stretch of the window we may never have looked at — the executions in it
    have no webhook, no repair and no metric of their own, so this counter is the only
    trace they leave. `reason` is the adapter's closed enum
    (`ListingIncompleteReason`), so it stays a stable label.
    """
    _record("reconciliation_listing_incomplete", 1, reason=reason)


def record_compliance_block(*, rule: str) -> None:
    _record("compliance_blocks", 1, rule=rule)


__all__ = [
    "ALERT_BUDGET_PER_HOUR",
    "ALERT_BURST",
    "ALERT_DROPPED_CODES_MAX",
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
    "record_reconciliation_listing_incomplete",
    "record_reconciliation_repair",
    "record_tool_ack_ms",
    "record_webhook_ack_ms",
    "record_webhook_replay_divergence",
    "reset_alerts",
]
