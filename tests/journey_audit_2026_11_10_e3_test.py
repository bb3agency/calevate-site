"""Journey audit E3 (10 Nov 2026): an outbound campaign over its whole life.

E3-01: a claim the dispatcher then refused (the hour, a pause, the halt, a full line, a
do-not-call entry) kept the try the claim stamped. A person nobody rang read "Last 22:30"
on the campaign screen and in their own data-access export, a do-not-call refusal kept
the attempt ("Try 1 of 3"), and a dial the voice platform refused after the line was
reserved counted the person among the "people called".

E3-02: outside the platform's 09:00-21:00 IST a campaign with no window of its own was
claimed and refunded every tick all night, while one with its own window was skipped.

E3-03: a campaign outside its calling hours was never visited, so one whose last calls
ended after the window closed stayed "running" with nobody left until the window next
opened.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.campaigns import results
from apps.api.compliance.service import add_to_dnc
from apps.api.db.session import tenant_session
from apps.api.engine.fake import FakeEngine
from apps.api.engine.vendor_http import lines_busy_error
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import TenantWork
from calevate_shared.engine import CallContext
from sqlalchemy import text

# The launched-campaign fixture and the module teardown that cancels what it started.
from tests.campaign_dispatch_audit_test import (
    _launched,
    _roomy_platform_pool,  # noqa: F401
    _settle_what_this_module_started,  # noqa: F401
    _tick_one_campaign,
)


def _ist(hour: int, minute: int) -> datetime:
    """An instant whose wall clock reads `hour:minute` IST, as the tests' pinned clock."""
    return datetime(2026, 8, 11, hour, minute, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _rows(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> dict[str, tuple[object, ...]]:
    async with tenant_session(tenant_id) as session:
        found = (
            await session.execute(
                text(
                    "SELECT phone_e164, status, attempts, last_attempt_at, last_call_id, "
                    "next_attempt_at FROM campaign_contacts WHERE campaign_id = :c"
                ),
                {"c": campaign_id},
            )
        ).all()
    return {str(r[0]): tuple(r[1:]) for r in found}


def _only(monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID) -> None:
    """The tick sees this one tenant, so another process's campaigns are not dialled."""

    async def _scan() -> list[TenantWork]:
        return [TenantWork(tenant_id, 0, True, False, False)]

    monkeypatch.setattr(campaign_dispatch, "_tenants_with_work", _scan)


# --------------------------------------------------------------------- E3-01


async def test_a_person_refused_for_do_not_call_before_the_dial_carries_no_try() -> None:
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876710001", "9876710002"))
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164="+919876710002", source="manual")

    result = await _tick_one_campaign(tenant_id, campaign_id)

    assert result["dialled"] == 1 and result["blocked"] == 1, result
    rows = await _rows(tenant_id, campaign_id)
    assert rows["+919876710001"][:2] == ("dialing", 1), "the dialable one rang"
    status, attempts, last_at, last_call, _next = rows["+919876710002"]
    assert status == "dnc_blocked"
    assert attempts == 0, "nobody rang this person, so no attempt is recorded"
    assert last_at is None and last_call is None, "no try is dated on a person never called"


async def test_a_refusal_by_the_hour_puts_the_previous_try_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876720001",))
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _ist(22, 30))

    result = await _tick_one_campaign(tenant_id, campaign_id)

    assert result == {"dialled": 0, "blocked": 1, "exhausted": 0}, result
    status, attempts, last_at, last_call, next_at = (await _rows(tenant_id, campaign_id))[
        "+919876720001"
    ]
    assert (status, attempts) == ("pending", 0)
    assert next_at is not None, "it waits for the hours"
    assert last_at is None, "a refusal at 22:30 must not read as a try at 22:30"
    assert last_call is None


class _LinesFullAfterOne(FakeEngine):
    """The voice platform placing one call, then refusing with every line in use."""

    def __init__(self) -> None:
        super().__init__()
        self.placed = 0

    async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
        if self.placed:
            raise lines_busy_error()
        self.placed += 1
        return await super().start_outbound_call(ref, to, ctx)


async def test_a_dial_refused_after_its_line_was_reserved_is_not_a_person_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876730001", "9876730002"))
    engine = _LinesFullAfterOne()
    monkeypatch.setattr("apps.api.agents.service.get_engine", lambda: engine)

    result = await _tick_one_campaign(tenant_id, campaign_id)

    assert result == {"dialled": 1, "blocked": 1, "exhausted": 0}, result
    status, attempts, last_at, last_call, _next = (await _rows(tenant_id, campaign_id))[
        "+919876730002"
    ]
    assert (status, attempts) == ("pending", 0)
    assert last_call is None, "the link to a call that never rang is undone"
    assert last_at is None
    async with tenant_session(tenant_id) as session:
        totals = await results.summary(session, campaign_id=campaign_id, include_spend=False)
    assert totals["tried"] == 1, f"'people called' counts only who rang: {totals['tried']}"


# --------------------------------------------------------------------- E3-02


async def test_a_tick_outside_the_platform_hours_leaves_the_list_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876740001", "9876740002"))
    _only(monkeypatch, tenant_id)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _ist(23, 15))
    blocks: list[str] = []
    monkeypatch.setattr(
        campaign_dispatch, "record_compliance_block", lambda *, rule: blocks.append(rule)
    )

    await campaign_dispatch._run_tick()

    for phone, row in (await _rows(tenant_id, campaign_id)).items():
        assert row == ("pending", 0, None, None, None), f"{phone} was claimed at night: {row}"
    assert blocks == [], f"nobody was claimed, so nothing was refused: {blocks}"


# --------------------------------------------------------------------- E3-03


async def test_a_campaign_whose_last_call_ends_after_its_window_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, campaign_id, _, _ = await _launched(phones=("9876750001",))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET calling_hours = CAST(:w AS jsonb) WHERE id = :c"),
            {"w": '{"start": "09:00", "end": "12:00"}', "c": campaign_id},
        )
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _ist(11, 58))
    assert (await _tick_one_campaign(tenant_id, campaign_id))["dialled"] == 1

    # The call ends at 12:03, after the window, and the pipeline settles its contact.
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT last_call_id FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
        await campaign_dispatch.resolve_campaign_contact(
            session, tenant_id=tenant_id, call_id=call_id, call_status="completed"
        )
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _ist(12, 5))
    _only(monkeypatch, tenant_id)

    await campaign_dispatch._run_tick()

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert status == "completed", "nobody is left to call, so the campaign is finished"
