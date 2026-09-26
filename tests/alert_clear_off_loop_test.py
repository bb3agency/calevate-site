"""The alarm-clear sweep sends its mail OFF the event loop.

`Transport.send` is synchronous socket I/O (`smtplib` on a 15-second budget, or a blocking
httpx POST), and `sweep_alert_clears` is an arq job sharing its loop with
`dispatch_outbox` and `dispatch_campaign_tick`. Called inline, one slow mail server froze
every job on the worker for up to fifteen seconds per cleared episode, fifty episodes a
batch — the P6.3 defect `workers/notifications._send_email` already fixed for its own send.
"""

from __future__ import annotations

import threading

import pytest
from apps.api.core import alerting
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from sqlalchemy import text

A_PAGE = "razorpay_money_unapplied"


class ThreadRecordingTransport:
    name = "recording"

    def __init__(self) -> None:
        self.sent_on: list[int] = []

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent_on.append(threading.get_ident())
        return True


@pytest.mark.asyncio
async def test_a_clear_notice_is_sent_from_a_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.core import transport as transport_module
    from apps.workers.alerts import sweep_alert_clears

    alerting.reset_alerts()
    recorder = ThreadRecordingTransport()
    monkeypatch.setattr(transport_module, "get_transport", lambda: recorder)
    monkeypatch.setattr(get_settings(), "alerts_email", "ops@calevate.test")
    monkeypatch.setattr(alerting, "DELIVERY_RETRY_DELAY_S", 0.0)
    try:
        alerting.alert("ROUTE_HANDLER", A_PAGE, detail="capture could not be applied")
        assert alerting.flush_alerts(timeout=5.0)
        recorder.sent_on.clear()

        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE platform_alerts SET last_seen_at = now() - interval '3 hours' "
                    "WHERE code = :code AND cleared_at IS NULL"
                ),
                {"code": A_PAGE},
            )
            await session.commit()

        loop_thread = threading.get_ident()
        await sweep_alert_clears({})
    finally:
        alerting.reset_alerts()

    assert recorder.sent_on, "the clear was not announced"
    assert loop_thread not in recorder.sent_on, "a blocking send ran on the event loop"
