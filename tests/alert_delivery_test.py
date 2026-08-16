"""Does an alarm reach a human? (OPERATIONS §4 "alerts to WhatsApp/email to Sri";
§8 pre-launch gate "alerts firing to Sri's phone").

`alert()` used to write an ERROR log line and stop. Every alarm in this repo — an
exhausted outbound webhook, an unkeyable engine payload, a stalled post-call pipeline,
a bad Razorpay signature, a refused escalation — fired into a log nobody reads at 3am.
These tests pin the four properties that make the difference between "logged" and
"reached a human":

1. it is DELIVERED, through the transport that already exists (`workers/transport.py`),
2. it never blocks the caller — `alert()` runs on the voice-runtime ack path, whose
   entire budget is 500ms (hard rule 3), and SMTP has a 15-second timeout,
3. it is deduplicated and rate limited, because 4,000 copies is the same as none,
4. it carries ids and never a phone number (hard rule 6).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest
from apps.api.core import alerting
from apps.api.core.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATOR = "sri@calevate.tech"
PLANTED_PHONE = "+919876543210"


class RecordingTransport:
    """Stands in for `workers/transport.py`'s SMTP/console/null trio."""

    name = "recording"

    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.sent: list[dict[str, str]] = []
        self.threads: list[str] = []
        self.arrived = threading.Event()

    def send(self, *, to: str, subject: str, body: str) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        self.threads.append(threading.current_thread().name)
        self.arrived.set()
        return self.succeed


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> RecordingTransport:
    """A configured operator address + a transport we can look inside."""
    from apps.workers import transport as transport_module

    alerting.reset_alerts()
    recorder = RecordingTransport()
    monkeypatch.setattr(transport_module, "get_transport", lambda: recorder)
    monkeypatch.setattr(get_settings(), "alerts_email", OPERATOR)
    # The delivery retry is a real sleep in a background thread; tests must not pay it.
    monkeypatch.setattr(alerting, "DELIVERY_RETRY_DELAY_S", 0.0)
    yield recorder
    alerting.reset_alerts()


def _fire(code: str = "outbound_webhook_exhausted", **ids: str) -> None:
    alerting.alert("WORKER_DELIVERY", code, detail="delivery ladder exhausted", **ids)


def _delivered(recorder: RecordingTransport, expected: int = 1) -> list[dict[str, str]]:
    assert alerting.flush_alerts(timeout=5.0), "alert delivery did not drain"
    assert len(recorder.sent) == expected, f"expected {expected} deliveries, got {recorder.sent}"
    return recorder.sent


# --- 1. it reaches a human ----------------------------------------------------


def test_an_alert_is_delivered_to_the_operator(transport: RecordingTransport) -> None:
    _fire(tenant_id="019f-abc", call_id="019f-def")

    (message,) = _delivered(transport)
    assert message["to"] == OPERATOR
    # The subject is what a phone shows on the lock screen: the code has to be in it.
    assert "outbound_webhook_exhausted" in message["subject"]
    assert "WORKER_DELIVERY" in message["body"]
    assert "019f-abc" in message["body"]
    assert "019f-def" in message["body"]


def test_nothing_is_delivered_when_no_operator_address_is_configured(
    transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local/test default. An unconfigured deployment logs and says so at boot —
    it does not silently build a message and drop it."""
    monkeypatch.setattr(get_settings(), "alerts_email", None)

    _fire()

    assert alerting.flush_alerts(timeout=2.0)
    assert transport.sent == []


# --- 2. it never blocks the caller -------------------------------------------


def test_delivery_happens_off_the_calling_thread(transport: RecordingTransport) -> None:
    """Hard rule 3: `alert()` is called from the voice-runtime webhook handler, which
    has 500ms to ack. `SmtpTransport` waits up to 15 seconds for a socket."""
    _fire()
    caller = threading.current_thread().name

    _delivered(transport)
    assert transport.threads[0] != caller
    assert transport.threads[0].startswith("calevate-alert")


def test_alerting_does_not_pull_worker_code_into_the_voice_runtime_process() -> None:
    """The transport lives in `apps.workers`, which voice-runtime is forbidden to hold
    (tests/voice_runtime_import_surface_test.py: "worker code — hard rule 3 defers all
    real work to ARQ"). The import is therefore made INSIDE the delivery thread, and
    only when there is an operator address to deliver to — so a process that only ever
    imports and calls `alert()` still holds none of it.

    Asserted in a subprocess for the same reason that file gives: this pytest process
    has already imported the entire monolith.
    """
    probe = """
import json, sys
sys.path.insert(0, ".")
from apps.api.core.alerting import alert
alert("ROUTE_HANDLER", "webhook_unkeyable", engine="bolna")
with open(sys.argv[1], "w") as handle:
    json.dump(sorted(m for m in sys.modules if m.startswith("apps.workers")), handle)
"""
    out = Path(tempfile.gettempdir()) / f"calevate-alert-surface-{uuid.uuid4().hex}.json"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", probe, str(out)],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": "", "ALERTS_EMAIL": ""},
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr[-3000:]
        assert Path(out).read_text() == "[]", "alert() imported worker code on the caller"
    finally:
        out.unlink(missing_ok=True)


# --- 3. an alert storm is one message, not four thousand ----------------------


def test_repeat_occurrences_inside_the_window_collapse_into_one_delivery(
    transport: RecordingTransport,
) -> None:
    for _ in range(200):
        _fire(tenant_id="019f-abc")

    (message,) = _delivered(transport)
    assert "outbound_webhook_exhausted" in message["subject"]


def test_the_next_delivery_after_the_window_reports_what_was_suppressed(
    transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alertmanager's `repeat_interval` shape: the alarm re-notifies once the window
    passes, and the count of what was swallowed is part of the message — otherwise
    "still broken, 199 times" reads identically to "happened once"."""
    clock = {"t": 1_000.0}
    monkeypatch.setattr(alerting, "_now", lambda: clock["t"])

    for _ in range(200):
        _fire()
    clock["t"] += alerting.ALERT_REPEAT_INTERVAL_S + 1
    _fire()

    first, second = _delivered(transport, expected=2)
    assert "suppressed" not in first["body"]
    assert "199" in second["body"]


def test_a_storm_of_distinct_codes_is_capped_by_the_rate_limit(
    transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dedupe alone does not survive a bad deploy: 500 DIFFERENT codes are 500
    different fingerprints. The token bucket is the second bound, and what it drops is
    counted and reported rather than vanishing."""
    clock = {"t": 1_000.0}
    monkeypatch.setattr(alerting, "_now", lambda: clock["t"])

    for index in range(500):
        _fire(code=f"code_{index}")

    assert alerting.flush_alerts(timeout=5.0)
    assert len(transport.sent) == alerting.ALERT_BURST

    # A token refills, and the alert that rides it carries the toll.
    clock["t"] += 3600.0 / alerting.ALERT_BUDGET_PER_HOUR + 1
    _fire(code="after_the_storm")
    assert alerting.flush_alerts(timeout=5.0)
    assert "rate limit" in transport.sent[-1]["body"]
    assert str(500 - alerting.ALERT_BURST) in transport.sent[-1]["body"]


def test_the_bucket_names_the_alarms_it_ate(
    transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A count is not an alert. "12 other alerts were dropped" tells an operator that
    something was silenced and gives them no way to find out what.

    That matters because the bucket is ONE shared resource and the codes drawing on it
    are not equally important. `webhook_source_rejected` and
    `clerk_webhook_bad_signature` fire from anywhere on the internet with no credential;
    `postcall_pipeline_stalled` is the alarm the product exists to raise. Dedupe means a
    stranger's repeats are free, so they cannot hold a fingerprint down — but they CAN
    empty the burst, and the refill is one token every three minutes. The codes have to
    ride along.
    """
    clock = {"t": 1_000.0}
    monkeypatch.setattr(alerting, "_now", lambda: clock["t"])

    for index in range(alerting.ALERT_BURST):
        _fire(code=f"attacker_probe_{index}")  # drains the bucket
    alerting.alert("WORKER_STALL", "postcall_pipeline_stalled", detail="no jobs in 10m")
    alerting.alert("WORKER_STALL", "postcall_pipeline_stalled", detail="no jobs in 11m")
    alerting.alert("OUTBOX_DISPATCH", "outbox_dead_letter", detail="3 rows")

    assert alerting.flush_alerts(timeout=5.0)
    assert len(transport.sent) == alerting.ALERT_BURST, "the real alarms were dropped"

    clock["t"] += 3600.0 / alerting.ALERT_BUDGET_PER_HOUR + 1
    _fire(code="the_next_thing_that_broke")
    assert alerting.flush_alerts(timeout=5.0)

    body = transport.sent[-1]["body"]
    assert "postcall_pipeline_stalled x2" in body, "the operator must learn WHICH alarm was eaten"
    assert "outbox_dead_letter x1" in body
    # Most frequent first: the phone shows the top of the list.
    assert body.index("postcall_pipeline_stalled") < body.index("outbox_dead_letter")


def test_the_named_dropped_codes_are_bounded(
    transport: RecordingTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dict that holds them is a module global and the thing that fills it is a
    storm — unbounded here would be the memory leak the queue cap already refuses. The
    TOTAL is still reported for everything the list could not name."""
    clock = {"t": 1_000.0}
    monkeypatch.setattr(alerting, "_now", lambda: clock["t"])

    for index in range(200):
        _fire(code=f"code_{index}")

    clock["t"] += 3600.0 / alerting.ALERT_BUDGET_PER_HOUR + 1
    _fire(code="after")
    assert alerting.flush_alerts(timeout=5.0)

    body = transport.sent[-1]["body"]
    named = [line for line in body.splitlines() if line.startswith("dropped:")]
    assert len(named) == 1
    assert named[0].count(" x") == alerting.ALERT_DROPPED_CODES_MAX
    assert str(200 - alerting.ALERT_BURST) in body, "the total covers what the list could not"


def test_two_crash_classes_do_not_share_one_suppression_slot(
    transport: RecordingTransport,
) -> None:
    """The class of defect D-147 found ONE instance of.

    `_admit` fingerprints on `stage:code` and holds a fingerprint for fifteen minutes, so
    a single `unhandled_exception` code shared by every crash in the service means the
    first crash class to fire silences every other one for a quarter of an hour. An
    uncaught `ClientDisconnect` — free, from anywhere, indistinguishable from a flaky
    mobile network — did exactly that to the voice-runtime receiver. Catching it fixed
    one instance; putting the exception TYPE in the code fixes the class.

    Asserted through `alert()` with the codes `install_error_handlers` now builds, rather
    than by driving two crashes, because the property under test is the FINGERPRINT and
    a second app-level crash would only re-prove that a 500 alerts.
    """
    alerting.alert("ROUTE_HANDLER", "unhandled_exception:ClientDisconnect", detail="…")
    alerting.alert("ROUTE_HANDLER", "unhandled_exception:ClientDisconnect", detail="…")
    alerting.alert("ROUTE_HANDLER", "unhandled_exception:IntegrityError", detail="…")

    first, second = _delivered(transport, expected=2)
    assert "ClientDisconnect" in first["subject"], "the class is on the lock screen"
    assert "IntegrityError" in second["subject"]
    # The searchable token is unchanged, so a log search for the old code still works.
    assert "unhandled_exception" in first["subject"]


# --- 4. the alarm is not lost, and does not recurse ---------------------------


def test_a_failed_send_does_not_suppress_the_next_occurrence(
    monkeypatch: pytest.MonkeyPatch, transport: RecordingTransport
) -> None:
    """The dedupe window means "a human has been told". A transport that returned
    False told nobody, so the stamp is not kept — otherwise one SMTP blip silences the
    alarm for the whole window."""
    transport.succeed = False

    _fire()
    assert alerting.flush_alerts(timeout=5.0)
    # Two attempts for the first occurrence (one retry), then the stamp is dropped.
    assert len(transport.sent) == 2

    _fire()
    assert alerting.flush_alerts(timeout=5.0)
    assert len(transport.sent) == 4


def test_a_transport_that_alerts_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch, transport: RecordingTransport
) -> None:
    """ "The alert is that the outbox is broken" must not become an infinite loop when
    the alerting path itself trips something that alerts."""

    class ReentrantTransport(RecordingTransport):
        def send(self, *, to: str, subject: str, body: str) -> bool:
            alerting.alert("CORE_LOGIC", "raised_from_inside_delivery")
            return super().send(to=to, subject=subject, body=body)

    from apps.workers import transport as transport_module

    reentrant = ReentrantTransport()
    monkeypatch.setattr(transport_module, "get_transport", lambda: reentrant)

    _fire()

    assert alerting.flush_alerts(timeout=5.0)
    assert len(reentrant.sent) == 1


def test_a_raising_transport_does_not_reach_the_caller(
    monkeypatch: pytest.MonkeyPatch, transport: RecordingTransport
) -> None:
    """`alert()` is called from an exception handler and from a signal handler. It is
    not allowed to raise on top of the failure it is reporting."""

    class Exploding:
        name = "exploding"

        def send(self, **_: Any) -> bool:
            raise RuntimeError("smtp exploded")

    from apps.workers import transport as transport_module

    monkeypatch.setattr(transport_module, "get_transport", lambda: Exploding())

    _fire()  # must not raise
    assert alerting.flush_alerts(timeout=5.0)

    # And the thread survives to deliver the next one.
    monkeypatch.setattr(transport_module, "get_transport", lambda: transport)
    _fire(code="after_the_explosion")
    assert alerting.flush_alerts(timeout=5.0)
    assert len(transport.sent) == 1


# --- 5. hard rule 6 -----------------------------------------------------------


def test_a_planted_phone_number_does_not_survive_into_a_delivered_alert(
    transport: RecordingTransport,
) -> None:
    """An alert body is a message leaving the building. `detail` is authored by us but
    is frequently an upstream error string, and an id kwarg is whatever the call site
    passed."""
    alerting.alert(
        "WORKER_TERMINAL",
        "hot_lead_no_channel",
        detail=f"could not reach {PLANTED_PHONE}",
        tenant_id="019f-abc",
        caller_phone=PLANTED_PHONE,
    )

    (message,) = _delivered(transport)
    assert PLANTED_PHONE not in message["body"]
    assert "9876543210" not in message["body"]
    assert "[phone]" in message["body"] or "[redacted]" in message["body"]
    assert "019f-abc" in message["body"], "ids must survive — they are the whole point"


def test_a_transcript_shaped_detail_is_truncated_not_forwarded(
    transport: RecordingTransport,
) -> None:
    transcript = "caller said: " + ("i want an appointment tomorrow morning please " * 20)

    alerting.alert("CORE_LOGIC", "extraction_failed", detail=transcript, call_id="019f-aaa")

    (message,) = _delivered(transport)
    assert "truncated" in message["body"]
    assert len(message["body"]) < 1_000
