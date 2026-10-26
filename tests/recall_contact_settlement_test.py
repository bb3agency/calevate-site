"""A campaign dial the platform cancelled before ringing settles its contact (D-812).

The DNC recall and the big red switch both stop dials the platform has booked and not yet
rung. When the platform confirms it caught one (`RecallOutcome.PREVENTED`) the call closes
as never connected, and its campaign contact must not then be put on the retry ladder by
the `failed` call: a suppressed person is never dialled again, and a contact the halt
stopped goes back to `pending` with its attempt refunded, to be dialled once the halt is
lifted. Any other verdict says the phone may have rung, so nothing changes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from apps.api.compliance import dnc_recall as api_dnc_recall
from apps.api.core import loadshed
from apps.api.db.session import tenant_session
from apps.workers import campaign_dispatch, dial_recall, dnc_recall
from calevate_shared.engine import RecallOutcome
from sqlalchemy import text
from tests.campaign_dispatch_audit_test import (  # noqa: F401 - autouse fixtures
    _calls_placed,
    _daytime,
    _launched,
    _roomy_platform_pool,
    _settle_what_this_module_started,
    _tick_one_campaign,
)


class _Stop:
    """The engine as the recall jobs use it: `outcome` for our dial, UNKNOWN for any
    other tenant's (the halt's scan is fleet-wide), so no neighbour's row is settled."""

    name = "fake"

    def __init__(self, ours: str, outcome: RecallOutcome) -> None:
        self.ours = ours
        self.outcome = outcome

    def holds_credentials(self) -> bool:
        return True

    async def end_call(self, call_id: str) -> RecallOutcome:
        return self.outcome if call_id == self.ours else RecallOutcome.UNKNOWN


async def _dialled(phone: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    """(tenant, campaign, call, engine call id): one contact claimed and dialled."""
    tenant_id, _, campaign_id, _, _ = await _launched(phones=(phone,))
    await _tick_one_campaign(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        call_id, ecid = (
            await session.execute(
                text(
                    "SELECT c.id, c.engine_call_id FROM campaign_contacts cc "
                    "JOIN calls c ON c.id = cc.last_call_id WHERE cc.campaign_id = :c"
                ),
                {"c": campaign_id},
            )
        ).one()
    return tenant_id, campaign_id, uuid.UUID(str(call_id)), str(ecid)


async def _state(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> tuple[str, str, int, bool]:
    """(call status, contact status, attempts, contact due now)."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.status, cc.status, cc.attempts, "
                    "  COALESCE(cc.next_attempt_at <= now(), true) "
                    "FROM campaign_contacts cc JOIN calls c ON c.id = cc.last_call_id "
                    "WHERE cc.campaign_id = :c"
                ),
                {"c": campaign_id},
            )
        ).one()
    return str(row[0]), str(row[1]), int(row[2]), bool(row[3])


async def _as_if_later(tenant_id: uuid.UUID) -> None:
    """Past every settle wait: the `failed` call is older than `FAILED_SETTLE_AFTER` and any
    contact's next attempt is due."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET updated_at = now() - interval '1 hour' WHERE status = 'failed'")
        )
        await session.execute(
            text(
                "UPDATE campaign_contacts SET next_attempt_at = now() - interval '1 second' "
                "WHERE next_attempt_at IS NOT NULL"
            )
        )


async def _dnc_recall(
    monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID, phone: str, engine: _Stop
) -> str:
    monkeypatch.setattr(dnc_recall, "get_engine", lambda: engine)
    monkeypatch.setattr(dnc_recall, "alert", lambda *_a, **_kw: None)
    return await dnc_recall.recall_dials_for_dnc(
        {}, {"phones": [phone], "tenant_id": str(tenant_id)}
    )


@asynccontextmanager
async def _halted() -> AsyncIterator[None]:
    await loadshed.set_platform_status(
        outbound_halted=True, halt_reason="recall settlement test", actor_id=None
    )
    try:
        yield
    finally:
        await loadshed.set_platform_status(outbound_halted=False, actor_id=None)


async def _halt_recall(monkeypatch: pytest.MonkeyPatch, engine: _Stop) -> str:
    monkeypatch.setattr(dial_recall, "get_engine", lambda: engine)
    monkeypatch.setattr(dial_recall, "alert", lambda *_a, **_kw: None)
    async with _halted():
        return await dial_recall.recall_queued_dials({})


async def test_a_suppressed_dial_cancelled_before_ringing_is_never_dialled_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id, call_id, ecid = await _dialled("9876670001")

    summary = await _dnc_recall(
        monkeypatch, tenant_id, "+919876670001", _Stop(ecid, RecallOutcome.PREVENTED)
    )

    assert summary.startswith("found=1 prevented=1"), summary
    assert (await _state(tenant_id, campaign_id))[:3] == ("failed", "dnc_blocked", 1)
    # The outcome handler a finished call runs finds no contact waiting on it...
    async with tenant_session(tenant_id) as session:
        assert (
            await campaign_dispatch.resolve_campaign_contact(
                session, tenant_id=tenant_id, call_id=call_id, call_status="failed"
            )
            is None
        )
    # ...and neither the unanswered-dial pass nor a later tick puts it back on the ladder.
    await _as_if_later(tenant_id)
    await _tick_one_campaign(tenant_id, campaign_id)
    assert (await _state(tenant_id, campaign_id))[:3] == ("failed", "dnc_blocked", 1)
    assert await _calls_placed(tenant_id) == 1


async def test_a_halted_dial_cancelled_before_ringing_is_refunded_and_dialled_after_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id, _call_id, ecid = await _dialled("9876670002")

    summary = await _halt_recall(monkeypatch, _Stop(ecid, RecallOutcome.PREVENTED))

    assert "prevented=" in summary and "prevented=0 " not in summary, summary
    # Closed as never connected, the attempt the claim spent refunded, and not due yet:
    # the halt's own thirty-minute wait (`_refuse_contact`'s).
    assert await _state(tenant_id, campaign_id) == ("failed", "pending", 0, False)

    # The halt is lifted; once the wait passes the contact is dialled again, on its first
    # counted attempt rather than its second.
    await _as_if_later(tenant_id)
    await _tick_one_campaign(tenant_id, campaign_id)
    assert await _calls_placed(tenant_id) == 2
    call_status, contact_status, attempts, _due = await _state(tenant_id, campaign_id)
    assert (contact_status, attempts) == ("dialing", 1)
    assert call_status == "queued"


@pytest.mark.parametrize("outcome", [RecallOutcome.UNKNOWN, RecallOutcome.ALREADY_RUNNING])
async def test_a_stop_that_may_have_rung_changes_nothing_on_the_dnc_path(
    monkeypatch: pytest.MonkeyPatch, outcome: RecallOutcome
) -> None:
    tenant_id, campaign_id, _call_id, ecid = await _dialled("9876670003")

    await _dnc_recall(monkeypatch, tenant_id, "+919876670003", _Stop(ecid, outcome))

    assert await _state(tenant_id, campaign_id) == ("queued", "dialing", 1, True)


@pytest.mark.parametrize("outcome", [RecallOutcome.UNKNOWN, RecallOutcome.ALREADY_RUNNING])
async def test_a_stop_that_may_have_rung_changes_nothing_on_the_halt_path(
    monkeypatch: pytest.MonkeyPatch, outcome: RecallOutcome
) -> None:
    tenant_id, campaign_id, _call_id, ecid = await _dialled("9876670004")

    await _halt_recall(monkeypatch, _Stop(ecid, outcome))

    assert await _state(tenant_id, campaign_id) == ("queued", "dialing", 1, True)


async def _callback_on(tenant_id: uuid.UUID, call_id: uuid.UUID, phone: str) -> uuid.UUID:
    """A call-back mid-dial on `call_id`, as `claim_due` and the dial leave it."""
    callback_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO scheduled_callbacks (id, tenant_id, agent_id, source_execution_id, "
                "  phone_e164, requested_at, booked_at, status, attempts, last_call_id) "
                "SELECT :id, :t, c.agent_id, :ex, :phone, now(), now(), 'dialing', 1, c.id "
                "FROM calls c WHERE c.id = :call"
            ),
            {
                "id": callback_id,
                "t": tenant_id,
                "ex": f"ex-{callback_id}",
                "phone": phone,
                "call": call_id,
            },
        )
    return callback_id


async def _callback(tenant_id: uuid.UUID, callback_id: uuid.UUID) -> tuple[str, int, str | None]:
    """(status, attempts, last_refusal_reason)."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempts, last_refusal_reason FROM scheduled_callbacks "
                    "WHERE id = :id"
                ),
                {"id": callback_id},
            )
        ).one()
    return str(row[0]), int(row[1]), row[2]


async def test_a_halted_call_back_cancelled_before_ringing_waits_again_with_its_attempt_refunded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _campaign_id, call_id, ecid = await _dialled("9876670005")
    callback_id = await _callback_on(tenant_id, call_id, "+919876670005")

    await _halt_recall(monkeypatch, _Stop(ecid, RecallOutcome.PREVENTED))

    assert await _callback(tenant_id, callback_id) == (
        "scheduled",
        0,
        dial_recall.BIG_RED_SWITCH_REASON,
    )


async def test_a_suppressed_call_back_cancelled_before_ringing_is_called_off_in_the_dnc_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _campaign_id, call_id, ecid = await _dialled("9876670006")
    callback_id = await _callback_on(tenant_id, call_id, "+919876670006")

    await _dnc_recall(monkeypatch, tenant_id, "+919876670006", _Stop(ecid, RecallOutcome.PREVENTED))

    assert await _callback(tenant_id, callback_id) == (
        "cancelled",
        1,
        dnc_recall.CALLBACK_SUPPRESSED_REASON,
    )


async def test_a_withdrawn_consent_calls_the_call_back_off_in_its_own_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _campaign_id, call_id, ecid = await _dialled("9876670007")
    callback_id = await _callback_on(tenant_id, call_id, "+919876670007")
    monkeypatch.setattr(dnc_recall, "get_engine", lambda: _Stop(ecid, RecallOutcome.PREVENTED))
    monkeypatch.setattr(dnc_recall, "alert", lambda *_a, **_kw: None)

    await dnc_recall.recall_dials_for_dnc(
        {},
        {
            "phones": ["+919876670007"],
            "tenant_id": str(tenant_id),
            "cause": api_dnc_recall.RECALL_CAUSE_CONSENT,
        },
    )

    assert await _callback(tenant_id, callback_id) == (
        "cancelled",
        1,
        dnc_recall.CALLBACK_CONSENT_WITHDRAWN_REASON,
    )


async def test_a_call_back_whose_dial_may_have_rung_is_left_to_its_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _campaign_id, call_id, ecid = await _dialled("9876670008")
    callback_id = await _callback_on(tenant_id, call_id, "+919876670008")

    await _halt_recall(monkeypatch, _Stop(ecid, RecallOutcome.UNKNOWN))

    assert await _callback(tenant_id, callback_id) == ("dialing", 1, None)
