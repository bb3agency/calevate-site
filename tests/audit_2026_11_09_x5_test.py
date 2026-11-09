"""Engine adapter and API contract (audit 9 Nov 2026, round 4, lane X5).

X5-01: a dial the ThinnestAI adapter refused BEFORE `POST /calls` (the agent's opening line
could not be read, was missing, or came out too long once the call's details were filled
in) raised `carrier_dial_precondition_failed`, a code `DIAL_NOT_PLACED_CODES` lost when the
owned runtime was removed (D-763). `dispatch_call` then read it as "the phone may have
rung": the campaign contact was finished for good with an escalation, and the intent row
stayed `queued`, holding an outbound line, for a call nobody placed. A throttled agent read
was also reworded as a missing agent, which sent the owner to republish.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from apps.api.agents.service import dial_was_not_placed
from apps.api.campaigns import service as campaigns
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine.capabilities import DIAL_PRECONDITION_FAILED
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest import PURPOSE_MAX_CHARS, _dial_precondition_failed
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import _refused_on_our_side
from calevate_shared.engine import CallContext
from sqlalchemy import text
from tests.dispatch_budget_test import (
    _contacts,
    _daytime,  # noqa: F401  (autouse: the dial runs inside calling hours)
    _dlt_rows,
    _launched_campaign,
    _settle_what_this_module_started,  # noqa: F401  (autouse: leaves no running campaign)
    _tenant,
)
from tests.thinnest_engine_test import _agent_with_greeting, _engine, _recorder

TO = "+919876543210"


def _throttled() -> httpx.Response:
    # A wait past the ladder's ceiling, so the ladder stops at once rather than sleeping.
    return httpx.Response(
        429,
        headers={"Retry-After": "60"},
        json={"error": "Slow down.", "code": "rate_limit_resources"},
    )


async def _refusal(responses: dict[tuple[str, str], httpx.Response], **ctx: Any) -> ProblemError:
    handler, seen = _recorder(responses)
    with pytest.raises(ProblemError) as raised:
        await _engine(handler).start_outbound_call("ag_1", TO, CallContext(**ctx))
    assert all(r.method != "POST" for r in seen), "nothing may be dialled"
    return raised.value


async def test_a_dial_whose_opening_could_not_be_read_is_proven_not_placed() -> None:
    for answer in (
        httpx.Response(503, json={"error": "x", "code": "service_unavailable"}),
        httpx.Response(404, json={"error": "x", "code": "not_found"}),
        _agent_with_greeting(None),
    ):
        refusal = await _refusal({("GET", "/agents/ag_1"): answer})
        assert refusal.code == DIAL_PRECONDITION_FAILED
        assert dial_was_not_placed(refusal), refusal.detail
        assert _refused_on_our_side(refusal)


async def test_a_platform_that_did_not_answer_is_not_called_a_missing_agent() -> None:
    refusal = await _refusal({("GET", "/agents/ag_1"): httpx.Response(502, json={"error": "x"})})
    assert "missing" not in (refusal.detail or "")
    assert "Publish" not in (refusal.remediation or "")


async def test_a_throttled_agent_read_stays_a_throttle() -> None:
    refusal = await _refusal({("GET", "/agents/ag_1"): _throttled()})
    assert refusal.code == "engine_rate_limited"
    assert dial_was_not_placed(refusal)


async def test_an_opening_too_long_with_this_calls_name_is_refused_unplaced() -> None:
    greeting = "Namaste {{lead_name}}, " + "a" * (PURPOSE_MAX_CHARS - 40)
    refusal = await _refusal(
        {("GET", "/agents/ag_1"): _agent_with_greeting(greeting)}, lead_name="R" * 120
    )
    assert refusal.code == DIAL_PRECONDITION_FAILED
    assert dial_was_not_placed(refusal)
    assert str(PURPOSE_MAX_CHARS) in (refusal.detail or "")


class _UnbuildableDialEngine(FakeEngine):
    """The adapter's own refusal of a dial it could not build, raised where it is."""

    async def start_outbound_call(self, ref: str, to: str, ctx: CallContext) -> str:
        raise _dial_precondition_failed(missing="agent read")


async def test_a_campaign_contact_whose_dial_was_never_built_keeps_its_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Unbuilt", phones=("9876690001",)
    )
    monkeypatch.setattr("apps.api.agents.service.get_engine", lambda: _UnbuildableDialEngine())

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )

    assert result["dialled"] == 0 and result["exhausted"] == 0, result
    assert await _contacts(tenant_id, campaign_id) == [("pending", 0)]
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(text("SELECT status FROM calls WHERE direction = 'outbound'"))
        ).all()
    assert [str(r[0]) for r in rows] == ["failed"], "the intent row must not hold a line"
