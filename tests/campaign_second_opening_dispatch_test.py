"""A campaign testing a second opening (D-992), and the dial bookkeeping around it.

Half of a campaign's people hear the second opening, chosen by their contact id so a retry
hears what the first try did. The dispatch stamps the variant on the contact BEFORE the dial
and hands the second opening to the call, where the agent's switched-on notices are joined
to it (`agents.service.campaign_first_words`).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import service as agents_service
from apps.api.campaigns import service as campaigns
from apps.api.db.session import tenant_session
from apps.api.engine.fake import FakeEngine
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import TenantWork, _Settling, opening_variant
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.dispatch_budget_test import (
    _daytime,  # noqa: F401  (autouse: the dial runs inside calling hours)
    _dlt_rows,
    _launched_campaign,
    _settle_what_this_module_started,  # noqa: F401  (autouse: leaves no running campaign)
    _tenant,
)

SECOND_OPENING = "Hello, this is a quick call about the offer you asked us to send."


def test_no_variant_is_chosen_while_no_second_opening_is_tested() -> None:
    contact = uuid.UUID(int=7)
    assert opening_variant(contact, None) is None
    assert opening_variant(contact, "   ") is None


def test_a_persons_half_is_fixed_by_their_contact_id() -> None:
    assert opening_variant(uuid.UUID(int=8), SECOND_OPENING) == "a"
    assert opening_variant(uuid.UUID(int=9), SECOND_OPENING) == "b"
    assert opening_variant(str(uuid.UUID(int=9)), SECOND_OPENING) == "b", "a retry agrees"


class _RecordingEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.openings: list[str | None] = []

    async def start_outbound_call(self, ref: Any, to: Any, ctx: CallContext) -> Any:
        self.openings.append(ctx.opening)
        return await super().start_outbound_call(ref, to, ctx)


async def test_a_person_in_the_second_half_is_stamped_and_hears_the_second_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Second opening", phones=("9876690011",)
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET opening_b = :b WHERE id = :c"),
            {"b": SECOND_OPENING, "c": campaign_id},
        )
    engine = _RecordingEngine()
    monkeypatch.setattr("apps.api.agents.service.get_engine", lambda: engine)
    # Which half a random contact id falls in is the unit tests' business above; here the
    # person is put in the second half so the run is the same every time.
    monkeypatch.setattr(campaign_dispatch, "opening_variant", lambda _c, b: "b" if b else None)

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    assert result["dialled"] == 1, result
    async with tenant_session(tenant_id) as session:
        stamped = (
            (
                await session.execute(
                    text("SELECT opening_variant FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            )
            .scalars()
            .all()
        )
    assert list(stamped) == ["b"]
    assert len(engine.openings) == 1
    assert SECOND_OPENING in (engine.openings[0] or "")


async def test_a_campaign_that_cannot_be_settled_out_of_hours_fails_only_its_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id = uuid.uuid4(), uuid.uuid4()
    work = TenantWork(
        tenant_id=tenant_id,
        active_outbound=0,
        has_running_campaign=True,
        has_due_schedule=False,
        has_due_callback=False,
    )

    async def _with_work() -> list[TenantWork]:
        return [work]

    async def _plan(_work: TenantWork, _pool: int) -> tuple[int, list[Any], list[_Settling]]:
        return 0, [], [_Settling(tenant_id, campaign_id, {})]

    async def _settle(*_: Any) -> None:
        raise RuntimeError("settle failed")

    monkeypatch.setattr(campaign_dispatch, "_tenants_with_work", _with_work)
    monkeypatch.setattr(campaign_dispatch, "_plan_tenant", _plan)
    monkeypatch.setattr(campaign_dispatch, "_settle_out_of_hours", _settle)

    failures: list[Any] = []
    await campaign_dispatch._dispatch_fleet(0, failures)

    assert [(f.tenant_id, f.step, f.error) for f in failures] == [
        (tenant_id, "settle", "RuntimeError")
    ]


async def test_a_recheck_that_raises_after_the_dial_is_alarmed_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The vendor has accepted the call, so a raise here would read as "not placed"."""

    async def _down(_session: Any) -> Any:
        raise RuntimeError("halt state unreadable")

    alarms: list[tuple[uuid.UUID, str, str]] = []
    monkeypatch.setattr(agents_service, "read_halt_state", _down)
    monkeypatch.setattr(
        agents_service,
        "_alarm_unconfirmed_bookkeeping",
        lambda call_id, *, step, exc: alarms.append((call_id, step, type(exc).__name__)),
    )
    call_id = uuid.uuid4()

    await agents_service._recall_if_stopped_while_dialling(
        uuid.uuid4(), call_id=call_id, phone_e164="+919900000000"
    )

    assert alarms == [(call_id, "stop_recheck", "RuntimeError")]


async def test_a_second_opening_too_long_with_its_notices_is_refused_when_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over the call's first-words ceiling the engine would speak the greeting instead, while
    the person is counted as hearing the second opening; so it is refused, naming the limit."""
    from apps.api.agents.engine_limits import OPENING_TOO_LONG
    from apps.api.campaigns.workspace_routes import OpeningBIn, save_opening_b
    from apps.api.core.errors import ProblemError

    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Long opening", phones=("9876690051",)
    )
    engine = FakeEngine()
    async with tenant_session(tenant_id) as session:
        speaker = await agents_service.campaign_agent_row(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    limit = len(
        agents_service.campaign_first_words(
            speaker, SECOND_OPENING, call_is_recorded=engine.capabilities.records_audio
        )
    )
    monkeypatch.setattr(agents_service, "get_engine", lambda: engine)
    monkeypatch.setattr(
        agents_service, "hosted_agent_limits", lambda _e: SimpleNamespace(call_opening_chars=limit)
    )
    principal = SimpleNamespace(tenant_id=tenant_id)

    async with tenant_session(tenant_id) as session:
        await save_opening_b(
            campaign_id,
            OpeningBIn(opening_b=SECOND_OPENING),
            session,
            principal,  # type: ignore[arg-type]
        )
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await save_opening_b(
                campaign_id,
                OpeningBIn(opening_b=f"{SECOND_OPENING} And one thing more."),
                session,
                principal,  # type: ignore[arg-type]
            )
    assert refused.value.code == OPENING_TOO_LONG
    assert f"at most {limit:,}" in refused.value.detail
    async with tenant_session(tenant_id) as session:
        kept = (
            await session.execute(
                text("SELECT opening_b FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert kept == SECOND_OPENING, "the refused opening was not saved"
