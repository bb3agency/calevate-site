"""Hard rule 6 at the one service that is handed raw call data by a third party.

"Never log phone numbers, transcript text or extraction payloads — log ids." Everywhere
else in this repo that rule is about data we assembled ourselves. Here it is about a
document a vendor POSTs at us: Bolna's execution payload carries
`recipient_phone_number`, a prefix-tagged transcript and `extracted_data` (TRD §5), and
this handler holds all of it in memory as `payload` while deciding what to do.

It is also the service where a leak would be least visible. voice-runtime has no
dashboard, no reviewer and no request log anybody reads; its output goes to stdout on a
box and into whatever ships logs off it. A phone number that starts appearing there is
found by an auditor, not by us.

**Read by capturing formatted output, not by reading the code, and not by reading
`record.__dict__`.** Redaction lives in `JsonFormatter.format` (core/logging.py):
`REDACT_KEYS` is applied to extras and `redact_text` to exception text at FORMAT time, so
a `caplog`-style assertion over record attributes tests the wrong object — it would pass
on a service that emits PII to stdout on every call. These tests attach a real handler
with the real formatter and read the bytes.

Both directions are asserted. A test that only proves "the phone number is absent" also
passes when nothing was logged at all, or when the handler was never reached; the
positive control — a line we know this path emits IS present — is what makes the absence
mean something.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import webhook_routes
from apps.api.core.logging import JsonFormatter
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

ENGINE_EGRESS_IP = "198.51.100.7"
ATTACKER_IP = "203.0.113.9"
EDGE_PROXY_IP = "127.0.0.1"
HOOK = "/hooks/v1/engine/bolna"
HEADERS = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

# The PII an execution payload actually carries. Every one of these must be absent from
# every line this service emits.
CALLER_PHONE = "+919876543210"
AGENT_PHONE = "+918041234567"
TRANSCRIPT = "user: naa peru Ramesh, naa number 9876543210. assistant: dhanyavaadalu."
EXTRACTED_NAME = "Ramesh Kumar"
EXTRACTED_EMAIL = "ramesh.kumar@example.com"
SECRETS = (CALLER_PHONE, AGENT_PHONE, TRANSCRIPT, EXTRACTED_NAME, EXTRACTED_EMAIL)


def _execution_payload(execution_id: str, status: str) -> dict[str, Any]:
    """A Bolna execution payload with everything filled in, shaped from TRD §5's
    description of what arrives at `completed`."""
    return {
        "execution_id": execution_id,
        "status": status,
        "agent_id": f"agent_{uuid.uuid4().hex[:8]}",
        "recipient_phone_number": CALLER_PHONE,
        "from_phone_number": AGENT_PHONE,
        "transcript": TRANSCRIPT,
        "extracted_data": {
            "name": EXTRACTED_NAME,
            "email": EXTRACTED_EMAIL,
            "callback_number": CALLER_PHONE,
        },
        "telephony_data": {"to_number": CALLER_PHONE, "duration": 92},
        "total_cost": 4.21,
    }


class _Capture(logging.Handler):
    """Every record any logger emits, rendered exactly as production renders it."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def logs() -> Iterator[_Capture]:
    """Attached to the ROOT logger: the point is to catch a line from a logger nobody
    thought to check — SQLAlchemy's, redis's, a library's — not only from ours."""
    capture = _Capture()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    try:
        yield capture
    finally:
        root.removeHandler(capture)
        root.setLevel(previous_level)


@pytest.fixture(autouse=True)
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client(peer_ip: str = EDGE_PROXY_IP, *, tolerate_crash: bool = False) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(
            app=voice_app, client=(peer_ip, 44444), raise_app_exceptions=not tolerate_crash
        ),
        base_url="http://runtime",
    )


def _assert_clean(logs: _Capture, *, context: str) -> None:
    leaked = [secret for secret in SECRETS if secret in logs.text]
    assert not leaked, (
        f"{context}: hard rule 6 — voice-runtime logged caller data: {leaked}\n"
        f"lines:\n{logs.text[:4000]}"
    )
    # The bare national-format number too: `redact_text` masks phone-shaped digit runs,
    # but only on strings it is applied to. A digit run that survives is a leak whether
    # or not it kept its `+91`.
    assert "9876543210" not in logs.text, f"{context}: a bare caller number reached the logs"


# --- 1. the happy path, which is where the payload is richest -----------------


async def test_a_full_execution_payload_leaves_no_caller_data_in_the_logs(
    logs: _Capture,
) -> None:
    """The `completed` transition is the one that carries cost, recording, transcript and
    extraction (TRD §5) — the richest payload the vendor ever sends, arriving on the
    service with the least supervision."""
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    status = f"completed-{uuid.uuid4().hex[:6]}"

    async with _client() as http:
        response = await http.post(
            HOOK, json=_execution_payload(execution_id, status), headers=HEADERS
        )

    assert response.status_code == 202
    _assert_clean(logs, context="accepted")

    # Positive control. Without it, "no PII in the logs" also passes on a run where the
    # handler was never reached or nothing was logged at all.
    #
    # Note what the control is NOT: the execution id. The receiver deliberately logs no
    # per-event line — correlation comes from the two durable rows it writes
    # (`webhook_inbox_events`, `webhook_deliveries`), which outlive log retention and are
    # queryable. Hard rule 6 says log ids rather than payloads; it does not require a log
    # line where a table already carries the fact.
    assert logs.lines, "no log output was captured — the assertions above proved nothing"
    assert '"metric": "webhook_ack_ms"' in logs.text, (
        "the ack budget must be recorded on the accepted path"
    )


async def test_the_response_body_does_not_echo_caller_data_either(logs: _Capture) -> None:
    """A response body is a log line on the vendor's side. The ack may name the execution
    id and the job id — ours, both — and nothing that came out of the payload."""
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    status = f"completed-{uuid.uuid4().hex[:6]}"

    async with _client() as http:
        response = await http.post(
            HOOK, json=_execution_payload(execution_id, status), headers=HEADERS
        )

    for secret in SECRETS:
        assert secret not in response.text, f"the ack echoed {secret[:12]}… back to the caller"
    _assert_clean(logs, context="response body")


# --- 2. every other exit, because failures are where redaction gets forgotten --


async def test_no_exit_path_leaks_the_payload(logs: _Capture) -> None:
    """Six branches, one assertion. Rejection, oversize, unreadable, unkeyable, accepted,
    duplicate — a leak on the flood paths is worse than one on the happy path, because
    the flood paths are the ones that run ten thousand times in a minute."""
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    status = f"completed-{uuid.uuid4().hex[:6]}"
    payload = _execution_payload(execution_id, status)

    async with _client(ATTACKER_IP) as stranger:
        await stranger.post(HOOK, json=payload)  # 401 — from off the allowlist
    async with _client() as http:
        # Oversized: the body is refused unread, and the refusal must not quote it.
        await http.post(HOOK, content=(TRANSCRIPT * 40_000).encode(), headers=HEADERS)
        # Unreadable: a JSON error message can carry a slice of the document it failed on.
        await http.post(HOOK, content=f'{{"transcript": "{TRANSCRIPT}"'.encode(), headers=HEADERS)
        # Unkeyable: no execution id, so the alert has nothing but the payload to name.
        await http.post(
            HOOK, json={k: v for k, v in payload.items() if k != "execution_id"}, headers=HEADERS
        )
        await http.post(HOOK, json=payload, headers=HEADERS)  # accepted
        await http.post(HOOK, json=payload, headers=HEADERS)  # duplicate

    _assert_clean(logs, context="all exit paths")


async def test_a_crash_inside_the_handler_does_not_spill_the_payload(
    logs: _Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path that is easiest to get wrong. `install_error_handlers` logs unhandled
    exceptions with `log.exception`, and a traceback is free-form text assembled by
    somebody else — which is exactly why `get_engine()` sets `hide_parameters=True` and
    the formatter runs `redact_text` over the rendered exception.

    The failure injected here is a database error mid-claim, i.e. the realistic version:
    a driver exception whose message would otherwise quote the statement's bound
    parameters, and whose transaction is holding the payload's own values.
    """
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    status = f"completed-{uuid.uuid4().hex[:6]}"
    payload = _execution_payload(execution_id, status)

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"claim failed for payload {payload}")

    monkeypatch.setattr(webhook_routes, "claim_inbox_event", _boom)

    async with _client(tolerate_crash=True) as http:
        response = await http.post(HOOK, json=payload, headers=HEADERS)

    assert response.status_code == 500
    for secret in SECRETS:
        assert secret not in response.text, "a 500 body leaked internals (hard rule: user-safe)"
    _assert_clean(logs, context="unhandled exception")


async def test_the_metric_and_alert_lines_carry_ids_and_labels_only(logs: _Capture) -> None:
    """`record_webhook_ack_ms` and `alert` fire on every request, including from
    strangers. They are the highest-volume lines this service produces, so anything they
    carry is carried everywhere — they must stay at ids, labels and numbers.
    """
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    status = f"completed-{uuid.uuid4().hex[:6]}"

    async with _client(ATTACKER_IP) as stranger:
        await stranger.post(HOOK, json=_execution_payload(execution_id, status))

    rejected = [line for line in logs.lines if "webhook_source_rejected" in line]
    assert rejected, "a caller off the allowlist must be alerted on"
    for line in rejected:
        for secret in SECRETS:
            assert secret not in line
    # The alert names the caller's address on purpose (a renumbered vendor is the
    # incident it exists for) and nothing else about them.
    assert ATTACKER_IP in "\n".join(rejected), "the alert must name the source ip to be actionable"

    metrics = [line for line in logs.lines if '"metric": "webhook_ack_ms"' in line]
    assert metrics, "every response is measured, including a refusal"
    for line in metrics:
        for secret in SECRETS:
            assert secret not in line
