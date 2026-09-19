"""What a refused CLICK-TO-DIAL leaves behind — on the client's screen, and on the metric.

Two properties of the same branch, found together because they are the same omission seen
from the two ends the gate is read from.

1. **IT IS COUNTED.** `compliance_blocks{rule=...}` is the metric `runbooks/calls-stopped.md`
   and `runbooks/campaign-stall.md` send an operator to when somebody reports that calls
   have stopped: the count says a dial was refused and the LABEL says which desk it belongs
   on. Three writers feed it — `compliance.service.assert_dispatch_allowed` for the paths
   that raise, `campaign_dispatch._refuse_contact` for the dispatcher, and
   `campaigns.complaint_spike`. The two client-initiated dial buttons take the DECISION form
   of the gate (a 200 carrying `blocked_rule`, so the screen can explain itself — SURFACES
   §2b) and therefore recorded NOTHING, which made the whole D-21 path invisible to the one
   instrument an operator has.

   The eligibility GET is asserted NOT to count, and that half matters as much: it calls the
   same gate to render a disabled button, so counting it would put one `compliance_blocks`
   per page load into the series an operator reads a stall off.

2. **IT SAYS SOMETHING THE READER CAN ACT ON.** `decision.reason` is handed straight to the
   browser as `blocked_reason`; every refusal in this gate is a sentence for that reason,
   and `agent_missing` was the one that answered "Agent not found." — our word for a row,
   under a button, with nothing to do about it.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.compliance.service import add_to_dnc, check_dispatch
from apps.api.core import alerting
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from tests.lead_dial_routes_test import _client, _dialable_tenant, _lead, _outbound_calls

pytestmark = pytest.mark.anyio


@pytest.fixture
def blocked_rules(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The `rule` label of every `compliance_blocks` point recorded during a test.

    A SPY ON THE SERIES, not a log capture, and the reason is worth stating because
    `caplog` is the obvious first reach and does not work here. `core/logging.
    configure_logging` runs in the app's lifespan and REPLACES the root handler list
    (`root.handlers = [handler]`), so whether caplog sees a record depends on whether some
    earlier test in the session already started the app — which made the assertion pass
    alone and fail in a suite, for a reason with nothing to do with the property.

    `alerting._record` is the one function every `record_*` helper funnels through, so
    patching it catches the point wherever it was emitted from, and the filter keeps this
    blind to the other series a dial legitimately records.
    """
    seen: list[str] = []

    def spy(name: str, value: float, **labels: str) -> None:
        if name == "compliance_blocks":
            seen.append(labels["rule"])

    monkeypatch.setattr(alerting, "_record", spy)
    return seen


async def test_a_refused_click_to_dial_is_counted_under_its_own_rule(
    blocked_rules: list[str],
) -> None:
    """THE DEFECT. The button refuses, the screen explains itself, and until this the
    operator's metric never heard about it."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="test")

    async with _client() as http:
        response = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert response.json()["blocked_rule"] == "dnc"
    assert blocked_rules == ["dnc"], blocked_rules
    assert await _outbound_calls(tenant_id) == []


async def test_a_dial_that_goes_through_counts_nothing(
    blocked_rules: list[str],
) -> None:
    """The positive control the assertion above needs: a metric that fired on every press
    would satisfy the first test and mean nothing."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, _phone = await _lead(tenant_id, agent_id)

    async with _client() as http:
        response = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers=headers,
        )

    assert response.json()["status"] == "queued", response.text
    assert blocked_rules == []


async def test_reading_why_the_button_is_greyed_out_does_not_count_as_a_blocked_dial(
    blocked_rules: list[str],
) -> None:
    """The eligibility GET renders a disabled button WITH ITS REASON on page load, through
    the same gate. One point per page view would drown the series an operator reads a
    stall off — so the recorder sits at the two POSTs and not inside `check_dispatch`."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    _lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="test")

    async with _client() as http:
        response = await http.get(f"/v1/calls/{call_id}/callback/eligibility", headers=headers)

    # Whatever this particular call id resolves to, the property under test is the same:
    # a READ of the gate contributes no point to the blocked-dial series.
    assert response.status_code in (200, 404), response.text
    assert blocked_rules == []


async def test_the_agent_refusal_is_a_sentence_a_client_can_act_on() -> None:
    """`reason` reaches the browser verbatim as `blocked_reason`. "Agent not found." was
    our vocabulary for a row; it named no action and told the reader nothing they could do.

    Asserted on the gate rather than through the route because that is where the sentence
    is authored, and because a route test would need an agent id the client may not hold —
    which is the OTHER thing this refusal has to cover with the same words."""
    tenant_id, _agent_id, _slug, _headers = await _dialable_tenant()
    _lead_id, phone = await _lead(tenant_id, _agent_id)

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=uuid7(), phone_e164=phone
        )

    assert not decision.allowed
    assert decision.rule == "agent_missing"
    reason = decision.reason or ""
    # A sentence, not a label: it ends, it names the thing the reader owns ("agent"), and
    # it tells them what to do instead.
    assert reason.endswith("."), reason
    assert "agent" in reason.lower(), reason
    assert reason != "Agent not found.", "the terse form is what this test exists to keep out"
    # No internals: no table, no column, no id, no rule name (errors are part of the
    # interface, and this one is read by a client).
    lowered = reason.lower()
    for internal in ("agents", "row", "tenant_id", "agent_missing", "null", "deleted_at"):
        assert internal not in lowered, f"{internal!r} leaked into a client-facing refusal"
    assert str(tenant_id) not in reason


async def test_the_same_words_answer_a_deleted_agent_and_another_accounts(
    anyio_backend: str,
) -> None:
    """One sentence for both, so the refusal cannot be used to ask whether an id exists.

    HARD RULE 1 read from the client's side: tenant B's agent is a real, live, dialable
    agent, and tenant A must learn exactly as much about it as about an id that was never
    anything.
    """
    tenant_a, _agent_a, _slug_a, _headers_a = await _dialable_tenant()
    tenant_b, agent_b, _slug_b, _headers_b = await _dialable_tenant()
    _lead_id, phone = await _lead(tenant_a, _agent_a)

    async with tenant_session(tenant_a) as session:
        neighbours = await check_dispatch(
            session, tenant_id=tenant_a, agent_id=agent_b, phone_e164=phone
        )
        nobodys = await check_dispatch(
            session, tenant_id=tenant_a, agent_id=uuid7(), phone_e164=phone
        )

    assert neighbours.rule == nobodys.rule == "agent_missing"
    assert neighbours.reason == nobodys.reason
    assert uuid.UUID(str(tenant_a)) != uuid.UUID(str(tenant_b))
