"""One alert function with a normalized failure_stage (BACKEND-PATTERNS §8).

The point of the enum: "where in the pipeline did this die" must be answerable from
the alert alone, without reading code. Sinks (Sentry, phone) are wired in OPERATIONS
§3; until then every alert is a structured ERROR log, which is already routable.

Metrics are NAMED DOMAIN RECORDERS, not ad-hoc counters — the recorder names become
the SLO rule vocabulary (OPERATIONS §4), so adding one is a deliberate act.
"""

from __future__ import annotations

from typing import Literal

from apps.api.core.logging import get_logger

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
    """Fire the alert path. `detail` must be a message we authored — never a payload."""
    log.error("alert", extra={"failure_stage": stage, "code": code, "detail": detail, **ids})


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
    "FailureStage",
    "alert",
    "record_compliance_block",
    "record_extraction_failure",
    "record_outbox_dlq_depth",
    "record_outbox_lag",
    "record_pipeline_lag",
    "record_reconciliation_repair",
    "record_webhook_ack_ms",
]
