"""`finalise_unsettled_call`: an answered call whose worker never settled it is finalised.

The carrier's hangup of an answered call defers this job (`carrier_events.enqueue_finalise`).
What is pinned: a settled call is left alone; an unsettled terminal call gets its post-call
promise under the settlement's own key, a refusal per worker-measured leg and the carrier's
`billsec` as its duration; a live row is never finalised; and the three job names that must
agree do.

Run: uv run python -m pytest -q tests/call_finalise_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine.carrier import CarrierCdr
from apps.api.worker import service as worker_service
from apps.workers import call_finalise, pipeline
from apps.workers import settings as worker_settings
from apps.workers.call_finalise import (
    POSTCALL_JOB,
    SETTLEMENT_MISSING_CODE,
    UNSETTLED_LEGS,
    finalise_unsettled_call,
)
from apps.workers.carrier_events import FINALISE_JOB
from sqlalchemy import text
from tests.carrier_event_job_test import make_call, make_tenant

pytestmark = [pytest.mark.rls]


class _Carrier:
    def __init__(self, cdr: CarrierCdr | None) -> None:
        self.cdr = cdr
        self.reads: list[str] = []

    async def fetch_cdr(self, carrier_call_id: str) -> CarrierCdr | None:
        self.reads.append(carrier_call_id)
        return self.cdr


def _cdr(ccid: str, billsec: int = 42) -> CarrierCdr:
    return CarrierCdr(
        carrier="vobiz",
        carrier_call_id=ccid,
        billed_seconds=billsec,
        duration_seconds=billsec + 5,
        total_cost_inr=Decimal("1.20"),
        currency="INR",
        answered_at=None,
        ended_at=None,
    )


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, Any]]]:
    fired: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(
        call_finalise, "alert", lambda stage, code, **kw: fired.append((stage, code, kw))
    )
    return fired


def test_the_three_job_names_agree_and_the_job_is_registered() -> None:
    assert POSTCALL_JOB == pipeline.POSTCALL_JOB == worker_service.POSTCALL_JOB
    assert finalise_unsettled_call.__name__ == FINALISE_JOB
    assert FINALISE_JOB in {getattr(fn, "__name__", "") for fn in worker_settings.FUNCTIONS}
    assert "carrier" not in UNSETTLED_LEGS


async def _finalised_state(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[Any, ...]:
    async with tenant_session(tenant_id) as session:
        duration = (
            await session.execute(
                text("SELECT duration_s FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()
        promised = (
            await session.execute(
                text("SELECT count(*) FROM outbox_messages WHERE dedupe_key = :k"),
                {"k": f"{worker_service.POSTCALL_DEDUPE_PREFIX}{call_id}"},
            )
        ).scalar()
        refused = (
            (
                await session.execute(
                    text(
                        "SELECT leg FROM call_metering_refusals "
                        "WHERE call_id = :c AND code = :code ORDER BY leg"
                    ),
                    {"c": call_id, "code": SETTLEMENT_MISSING_CODE},
                )
            )
            .scalars()
            .all()
        )
    return duration, promised, tuple(refused)


async def test_an_unsettled_answered_call_is_finalised_from_the_carrier_record(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, dict[str, Any]]]
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    ccid = f"vz-{uuid.uuid4().hex[:10]}"
    call_id = await make_call(tenant_id, agent_id, status="completed", carrier_call_id=ccid)
    carrier = _Carrier(_cdr(ccid, billsec=42))
    monkeypatch.setattr(call_finalise, "get_carrier", lambda name=None: carrier)

    outcome = await finalise_unsettled_call(
        {"job_try": 1}, {"tenant_id": str(tenant_id), "call_id": str(call_id)}
    )

    assert outcome == "finalised:cdr"
    assert carrier.reads == [ccid]
    duration, promised, refused = await _finalised_state(tenant_id, call_id)
    assert duration == 42
    assert promised == 1
    assert refused == tuple(sorted(UNSETTLED_LEGS))
    assert [code for _stage, code, _kw in alerts] == ["worker_settlement_missing"]

    # A second run, or a late settlement's claim, finds the promise and adds nothing.
    again = await finalise_unsettled_call(
        {"job_try": 1}, {"tenant_id": str(tenant_id), "call_id": str(call_id)}
    )
    assert again == "already_settled"
    assert (await _finalised_state(tenant_id, call_id))[1:] == (1, refused)


async def test_a_live_row_is_never_finalised(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, dict[str, Any]]]
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id = await make_call(tenant_id, agent_id, status="in_progress", carrier_call_id="vz-x")
    monkeypatch.setattr(call_finalise, "get_carrier", lambda name=None: _Carrier(None))

    outcome = await finalise_unsettled_call(
        {"job_try": 1}, {"tenant_id": str(tenant_id), "call_id": str(call_id)}
    )

    assert outcome == "not_terminal"
    assert (await _finalised_state(tenant_id, call_id))[1:] == (0, ())
    assert alerts == []


async def test_without_a_carrier_record_the_call_is_still_finalised(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, dict[str, Any]]]
) -> None:
    tenant_id, agent_id, _ref = await make_tenant()
    call_id = await make_call(tenant_id, agent_id, status="completed", carrier_call_id=None)
    monkeypatch.setattr(call_finalise, "get_carrier", lambda name=None: _Carrier(None))

    outcome = await finalise_unsettled_call(
        {"job_try": 1}, {"tenant_id": str(tenant_id), "call_id": str(call_id)}
    )

    assert outcome == "finalised:no_cdr"
    duration, promised, _refused = await _finalised_state(tenant_id, call_id)
    assert duration is None and promised == 1


async def test_a_call_that_is_not_there_is_permanent_and_loud(
    alerts: list[tuple[str, str, dict[str, Any]]],
) -> None:
    tenant_id, _agent_id, _ref = await make_tenant()
    with pytest.raises(ProblemError):
        await finalise_unsettled_call(
            {"job_try": 1}, {"tenant_id": str(tenant_id), "call_id": str(uuid.uuid4())}
        )
    assert [code for _stage, code, _kw in alerts] == ["call_finalise_abandoned"]
