"""One alarm per service, however many worker processes there are (D-160).

`alert_delivery_test.py` pins what one process does. Everything here is about what FOUR
of them do, because that is what production runs: `compose.prod.yml` starts voice-runtime
with `--workers=${VOICE_RUNTIME_WORKERS:-4}`, D-55's measured answer to the 500ms ack
budget, and uvicorn workers are processes rather than threads.

Before this, `alerting`'s window and token bucket were module globals, so the shipped
behaviour was four independent 15-minute windows and — the one that would have been hard
to spot from an inbox — four independent token buckets, making a deliberate 20/hour bound
into 80/hour. Neither is visible to a single-process test, which is why both survived.

THE MULTI-PROCESS TESTS USE REAL SUBPROCESSES, for `voice_runtime_import_surface_test`'s
reason: this pytest process has one copy of `alerting` and its globals, so anything
simulated inside it would be proving something about a dict rather than about processes.
Threads would be the same lie in a cheaper costume — they share the globals too, which is
precisely the state that was NOT shared before.

They are slower than a unit test and they are the only honest way to ask the question.
The cheap properties (fail-open, service scoping, the reopen-on-failure rule) are unit
tests further down, against the same live Redis the suite already requires.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from apps.api.core import alert_admission

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Fires one alert in a FRESH interpreter and reports whether the transport ran.
#:
#: The console transport is selected by leaving `SMTP_HOST` unset, so the probe exercises
#: the whole delivery path — including the shared gate — without opening a socket.
#: `delivered` is read off a recording transport rather than off `flush_alerts`, which
#: only proves the queue drained and is equally true of a suppressed notice.
_WORKER = """
import json, sys
sys.path.insert(0, ".")
from apps.api.core import alerting
from apps.workers import transport as transport_module

class Recorder:
    name = "recording"
    def __init__(self): self.sent = []
    def send(self, *, to, subject, body):
        self.sent.append(subject)
        return True

recorder = Recorder()
transport_module.get_transport = lambda: recorder
alerting.configure_alerts(service=sys.argv[2])
alerting.alert("WORKER_DELIVERY", sys.argv[3], detail="probe")
alerting.flush_alerts(timeout=20.0)
with open(sys.argv[1], "w") as handle:
    json.dump({"delivered": len(recorder.sent)}, handle)
"""


def _fire_in_a_separate_process(*, service: str, code: str) -> int:
    """How many alerts that process actually SENT. A real fork, not a thread."""
    out = Path(tempfile.gettempdir()) / f"calevate-alert-mp-{uuid.uuid4().hex}.json"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _WORKER, str(out), service, code],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "PYTHONPATH": "",
                "ALERTS_EMAIL": "ops@example.test",
                "SMTP_HOST": "",
            },
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert proc.returncode == 0, f"the alert worker failed:\n{proc.stderr[-3000:]}"
        return int(json.loads(out.read_text())["delivered"])
    finally:
        out.unlink(missing_ok=True)


@pytest.fixture
def service() -> str:
    """A service name unique to this test, so a run cannot inherit another's window.

    Uniqueness rather than a reset, deliberately: the shared window SURVIVES process exit
    by design — a worker restart must not re-page an operator — so "clean up afterwards"
    is not a property this suite can rely on if a test crashes. A fresh namespace per test
    is hermetic whatever happened before.
    """
    name = f"probe-{uuid.uuid4().hex[:12]}"
    yield name
    alert_admission.reset_admission(service=name)


# --- the property the whole change exists for ----------------------------------------


def test_four_workers_firing_one_alarm_page_the_operator_once(service: str) -> None:
    """THE regression this closes. Four processes, one fingerprint, one email.

    Four because that is `VOICE_RUNTIME_WORKERS`'s default, not an arbitrary number: this
    test is a statement about the shipped topology. Before the shared gate every one of
    them delivered, so a single bad deploy arrived on a phone four times and the operator
    learned to expect duplicates — which is how the fifth copy, the one that was a
    different fault, gets skimmed past.
    """
    code = f"multiproc_{uuid.uuid4().hex[:8]}"
    delivered = sum(_fire_in_a_separate_process(service=service, code=code) for _ in range(4))
    assert delivered == 1, (
        f"{delivered} of 4 worker processes delivered the same alert — the suppression "
        "window is per-process again, so the operator is paged once per worker"
    )


def test_the_hourly_budget_is_the_services_and_not_each_workers(service: str) -> None:
    """The quieter half, and the one an inbox cannot diagnose.

    `ALERT_BURST` is 6 for the SERVICE. Each process starts with a full local bucket, so
    with per-process buckets four workers could send 24 distinct codes before anything was
    dropped — the bound reads as broken rather than as absent, because the alarm storm it
    exists to cap simply arrives four times larger.

    Distinct codes on purpose: dedupe cannot help here, which is what isolates the bucket.
    """
    from apps.api.core.alerting import ALERT_BURST

    # Comfortably more processes than the burst, so the bucket has to refuse someone.
    attempts = ALERT_BURST + 4
    sent = sum(
        _fire_in_a_separate_process(service=service, code=f"burst_{index}_{uuid.uuid4().hex[:6]}")
        for index in range(attempts)
    )

    assert sent <= ALERT_BURST, (
        f"{sent} distinct alerts were delivered against a service burst of {ALERT_BURST} — "
        "the token bucket is per-process, so the budget multiplies by worker count"
    )


# --- the decision, as a unit ----------------------------------------------------------


def _admit(service: str, fingerprint: str = "S:c", **kwargs: float) -> alert_admission.Admission:
    return alert_admission.admit(
        service=service,
        fingerprint=fingerprint,
        window_s=kwargs.get("window_s", 900.0),
        burst=int(kwargs.get("burst", 6)),
        budget_per_hour=kwargs.get("budget_per_hour", 20.0),
    )


def test_the_second_caller_inside_the_window_is_counted_not_sent(service: str) -> None:
    """The window itself, at its smallest: one in, the rest counted.

    A refused verdict carries no counts — they belong to the delivery that eventually
    reports them (`test_the_withheld_count_rides_the_next_delivery`), and a suppressed
    caller sends nothing, so there is nowhere for a number to go.
    """
    assert _admit(service).admitted
    for _ in range(3):
        refused = _admit(service)
        assert not refused.admitted
        assert refused.suppressed == 0, "a refusal reports no counts; it has no message"
        assert not refused.degraded, "this was a real decision, not a fallback"


def test_the_withheld_count_rides_the_next_delivery(
    service: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(alert_admission, "_now_ms", lambda: clock["t"])

    assert _admit(service).admitted
    for _ in range(11):
        _admit(service)
    clock["t"] += 900_000 + 1
    later = _admit(service)
    assert later.admitted
    assert later.suppressed == 11, (
        f"the reopened window reported {later.suppressed} withheld occurrences, not 11 — "
        "the count is what stops a persistent fault reading as a one-off"
    )


def test_one_services_alarm_never_silences_anothers(service: str) -> None:
    """`api`, `voice-runtime` and `workers` share codes and do not share meanings.

    An `outbox_queue_unreachable` in the workers and a same-named code in voice-runtime
    would be two different faults on two different call paths, and the subject line
    already distinguishes them — so folding them into one window would mean the second is
    never reported at all. No code is emitted from two services today, which is why this
    test uses synthetic ones: the property is what keeps that true. (The example here was
    `queue_enqueue_failed` until D-412 found that nothing emits it.)
    """
    other = f"{service}-other"
    try:
        assert _admit(service).admitted
        assert _admit(other).admitted, "a sibling service was silenced by an unrelated alarm"
    finally:
        alert_admission.reset_admission(service=other)


def test_a_failed_delivery_reopens_the_window_for_every_worker(service: str) -> None:
    """`alerting._forget`'s shared twin, and the fix is load-bearing.

    The window means "a human has been told"; a transport that returned False told nobody.
    Locally that was one `dict.pop`. With the marker in Redis, NOT clearing it would have
    made one SMTP blip silence the alarm across the whole service for fifteen minutes —
    the bug got strictly worse with the fix, which is why the twin exists.
    """
    assert _admit(service).admitted
    assert not _admit(service).admitted
    alert_admission.forget(service=service, fingerprint="S:c")
    assert _admit(service).admitted, (
        "a delivery that reached nobody left the window shut, so every worker in the "
        "service stays quiet until it expires"
    )


def test_the_burst_is_spent_by_distinct_codes_and_then_refuses(service: str) -> None:
    admitted = sum(1 for index in range(20) if _admit(service, f"S:c{index}", burst=6).admitted)
    assert admitted == 6, f"the bucket admitted {admitted} distinct codes against a burst of 6"


def test_what_the_bucket_ate_is_reported_and_not_silently_dropped(
    service: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(alert_admission, "_now_ms", lambda: clock["t"])

    for index in range(20):
        _admit(service, f"S:c{index}", burst=6)
    # One refill period at 20/hour is three minutes.
    clock["t"] += 180_000 + 1
    later = _admit(service, "S:fresh", burst=6)
    assert later.admitted
    assert later.rate_limited == 14, (
        f"the delivery reported {later.rate_limited} dropped alerts, not 14 — a bucket "
        "whose toll is invisible is indistinguishable from a bucket that is broken"
    )


# --- the failure mode that must never cost an alarm ------------------------------------


def test_an_unreachable_redis_sends_rather_than_swallows(
    service: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAIL OPEN, and this is the test that keeps `alerting`'s central promise honest.

    That module's docstring says the alert path survives the failures it reports. Putting
    Redis on the path is only compatible with that sentence if a broken Redis can never
    withhold an alarm — and Redis being down is EXACTLY when the alarms matter, because
    half the codes in this system fire when infrastructure breaks.

    Degraded is reported separately from admitted so an operator can tell "we sent because
    we may" from "we sent because we could not ask".
    """

    def _explode() -> tuple[object, object]:
        raise ConnectionError("redis is gone")

    monkeypatch.setattr(alert_admission, "_connect", _explode)
    verdict = _admit(service)
    assert verdict.admitted, "a Redis outage suppressed an alert — this must never happen"
    assert verdict.degraded, "the fallback must be distinguishable from a real decision"


def test_a_reply_we_cannot_parse_also_sends(service: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same direction for a Redis that answers with something unexpected — a version
    change, a proxy in the middle, a script that was replaced under us."""
    monkeypatch.setattr(
        alert_admission, "_connect", lambda: (object(), lambda **_: "not a list at all")
    )
    verdict = _admit(service)
    assert verdict.admitted and verdict.degraded
