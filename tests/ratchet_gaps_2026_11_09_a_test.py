"""Branches the full ratchet left unexecuted: the dial gate's first-words refusal, an emptied
Indic call-purpose rule, and the call-back eligibility read outside calling hours."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.compliance import call_purpose
from apps.api.compliance import service as compliance_service
from apps.api.compliance.service import (
    CALLING_HOURS_RULE,
    DISCLOSURE_NOT_SAID_RULE,
    DispatchDecision,
    check_dispatch,
)
from apps.api.crm import lead_dial
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

pytestmark = [pytest.mark.rls]


async def test_the_dial_gate_refuses_first_words_that_drop_a_switched_on_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard on the composer: the real `join_first_words` always carries a switched-on
    notice, so a composer that dropped it is stood in for here, and the gate must refuse."""
    created = await create_org_with_receptionist(
        name="Gap Traders",
        slug=f"gap-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET ai_disclosure_enabled = true WHERE id = :a"),
            {"a": agent_id},
        )

    def opening_only(_notices: str, opening: str, **_kwargs: Any) -> str:
        return opening

    monkeypatch.setattr(compliance_service, "join_first_words", opening_only)
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919876600001"
        )

    assert decision.allowed is False
    assert decision.rule == DISCLOSURE_NOT_SAID_RULE, decision


def test_an_emptied_indic_word_list_switches_that_rule_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = {"te discount strong": ["ఆఫర్"], "hi discount strong": []}
    monkeypatch.setattr(call_purpose, "table", lambda _key: rules)

    built = call_purpose._indic_rules()

    assert [(r.language, r.category, r.severity) for r in built] == [("te", "discount", "strong")]


async def test_call_back_outside_calling_hours_says_when_it_can_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = SimpleNamespace(agent_id=uuid.uuid4(), phone_e164="+919876600001", depth=0)

    async def planned(_session: object, _call_id: uuid.UUID) -> SimpleNamespace:
        return plan

    async def after_hours(*_args: object, **_kwargs: object) -> DispatchDecision:
        return DispatchDecision(allowed=False, rule=CALLING_HOURS_RULE, reason="gate sentence")

    monkeypatch.setattr(lead_dial.service, "plan_callback", planned)
    monkeypatch.setattr(lead_dial, "check_dispatch", after_hours)

    out = await lead_dial.call_back_check(
        object(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        call_id=uuid.uuid4(),
    )

    assert out.eligible is False
    assert out.rule == CALLING_HOURS_RULE
    assert out.opens_at is not None and out.opens_at > datetime.now(UTC)
    assert out.reason == lead_dial.calling_hours_reason(out.opens_at, now=datetime.now(UTC))
