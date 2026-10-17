"""An erasure calls off the dials the voice platform has booked to the erased and not rung.

`check_dispatch` refuses an erased number for a NEW dial; a dial handed to the platform
before the erasure would still ring, and the platform refuses to delete a booked call's
content until it is cancelled (409, `thinnest-findings/mirror/snapshots/2026-10-15/pages/
api-reference/post-call/delete-call-content.md:506-509`). The erasure enqueues the DNC
recall job with call ids, and the job stops only dials the platform still holds unrung
(`calls/cancel-call.md:7`: a call ringing or connected would be ended on the line).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.compliance.deletion import RECALLED_DIALS_KEY
from apps.api.compliance.deletion_proof import certificate
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import dnc_recall, retention
from calevate_shared.engine import ExecutionSnapshot, RecallOutcome
from sqlalchemy import text
from tests.dial_recall_test import _quiet_platform, _tenant_with_dials
from tests.thinnest_erasure_test import _request

# Re-exported so pytest applies the halt file's autouse fixture here too: it settles the
# `queued` rows these cases create.
__all__ = ["_quiet_platform"]

ERASED = "+919812300001"
OTHER = "+919812300002"


class _Vendor:
    """The engine as the erasure recall uses it: a status read, then a stop."""

    name = "fake"

    def __init__(self, raw: dict[str, str] | None = None) -> None:
        #: The vendor's status per call; `scheduled` (booked, not rung) by default.
        self.raw = raw or {}
        self.stopped: list[str] = []

    def holds_credentials(self) -> bool:
        return True

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        raw = self.raw.get(call_id, "scheduled")
        status = {"scheduled": "queued", "ringing": "ringing", "completed": "completed"}[raw]
        return ExecutionSnapshot(
            engine_call_id=call_id,
            direction="outbound",
            status=status,
            raw_status=raw,
            terminal=raw == "completed",
            billable_ready=False,
        )

    async def end_call(self, call_id: str) -> RecallOutcome:
        self.stopped.append(call_id)
        return RecallOutcome.PREVENTED


async def _recall_payloads(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE job = :j ORDER BY created_at"),
                {"j": dnc_recall.DNC_RECALL_JOB},
            )
        ).scalars()
        return [row for row in rows if row.get("tenant_id") == str(tenant_id)]


async def _run(monkeypatch: pytest.MonkeyPatch, vendor: _Vendor, payload: dict[str, Any]) -> str:
    monkeypatch.setattr(dnc_recall, "get_engine", lambda: vendor)
    monkeypatch.setattr(dnc_recall, "alert", lambda *_a, **_kw: None)
    return await dnc_recall.recall_dials_for_dnc({}, payload)


async def _recalled(tenant_id: uuid.UUID) -> set[uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        return set(
            (
                await session.execute(
                    text("SELECT id FROM calls WHERE recall_requested_at IS NOT NULL")
                )
            )
            .scalars()
            .all()
        )


async def _erase_subject(tenant_id: uuid.UUID, phone: str) -> None:
    request_id = await _request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )


async def test_a_subject_erasure_calls_off_that_persons_booked_dial_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    erased_ref, other_ref = f"out_{uuid.uuid4()}", f"out_{uuid.uuid4()}"
    tenant_id, (erased, other) = await _tenant_with_dials(
        [{"engine_call_id": erased_ref, "to": ERASED}, {"engine_call_id": other_ref, "to": OTHER}]
    )

    request_id = await _request(tenant_id, ERASED)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    # The certificate states the dials asked to be called off (D-810), from the count the
    # erasure itself enqueued.
    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar_one()
    assert proof["scope"][RECALLED_DIALS_KEY] == 1
    document = certificate(proof)
    assert document is not None
    assert any(line.startswith("1 booked call to this person") for line in document["erased"])
    assert proof["actions"]["booked_dials"].startswith("1 booked call(s)")

    [payload] = await _recall_payloads(tenant_id)
    assert payload == {"tenant_id": str(tenant_id), "erasure": "subject", "call_ids": [str(erased)]}
    vendor = _Vendor()
    assert await _run(monkeypatch, vendor, payload) == ("found=1 prevented=1 rung=0 undetermined=0")
    assert vendor.stopped == [erased_ref]
    assert await _recalled(tenant_id) == {erased}
    assert other not in await _recalled(tenant_id)


async def test_a_tenant_erasure_calls_off_every_booked_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = [f"out_{uuid.uuid4()}" for _ in range(3)]
    tenant_id, call_ids = await _tenant_with_dials(
        [{"engine_call_id": ref, "to": f"+91981230001{i}"} for i, ref in enumerate(refs)]
    )
    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned', updated_at = now() WHERE id = :t"),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": request_id, "t": tenant_id},
        )
    await retention.execute_tenant_erasure(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM tenant_erasure_requests WHERE id = :r"),
                {"r": request_id},
            )
        ).scalar_one()
    assert proof["actions"]["booked_dials"].startswith("3 booked call(s)")

    [payload] = await _recall_payloads(tenant_id)
    assert payload["erasure"] == "tenant"
    assert set(payload["call_ids"]) == {str(c) for c in call_ids}
    vendor = _Vendor()
    await _run(monkeypatch, vendor, payload)
    assert sorted(vendor.stopped) == sorted(refs)
    assert await _recalled(tenant_id) == set(call_ids)


async def test_a_dial_already_ringing_or_ended_is_not_called_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    booked, ringing, ended = (f"out_{uuid.uuid4()}" for _ in range(3))
    settled = f"out_{uuid.uuid4()}"
    tenant_id, (booked_id, ringing_id, ended_id, settled_id) = await _tenant_with_dials(
        [
            {"engine_call_id": booked, "to": ERASED},
            # Our row still reads `queued` while the platform's call rings.
            {"engine_call_id": ringing, "to": ERASED},
            {"engine_call_id": ended, "to": ERASED, "status": "ringing"},
            {"engine_call_id": settled, "to": ERASED, "status": "completed"},
        ]
    )

    await _erase_subject(tenant_id, ERASED)

    [payload] = await _recall_payloads(tenant_id)
    assert str(settled_id) not in payload["call_ids"]
    vendor = _Vendor({ringing: "ringing", ended: "completed"})
    assert await _run(monkeypatch, vendor, payload) == ("found=3 prevented=1 rung=2 undetermined=0")
    assert vendor.stopped == [booked]
    assert await _recalled(tenant_id) == {booked_id}
    assert {ringing_id, ended_id}.isdisjoint(await _recalled(tenant_id))


async def test_a_retried_erasure_and_a_redelivered_recall_stop_nothing_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = f"out_{uuid.uuid4()}"
    tenant_id, _ = await _tenant_with_dials([{"engine_call_id": ref, "to": ERASED}])
    request_id = await _request(tenant_id, ERASED)
    job = {"tenant_id": str(tenant_id), "request_id": str(request_id)}

    await retention.execute_deletion_request({}, job)
    assert await retention.execute_deletion_request({}, job) == "already_completed"

    [payload] = await _recall_payloads(tenant_id)
    vendor = _Vendor()
    await _run(monkeypatch, vendor, payload)
    assert await _run(monkeypatch, vendor, payload) == "found=0"
    assert vendor.stopped == [ref]


async def test_a_dial_called_off_before_ringing_has_its_content_asked_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The erasure marks the booked call owed but holds it back (our row reads `queued`, and
    the platform answers 409 for it); once the platform says it was cancelled unrung, the
    deletion is sent."""
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    ref = f"out_{uuid.uuid4()}"
    tenant_id, (call_id,) = await _tenant_with_dials([{"engine_call_id": ref, "to": ERASED}])

    await _erase_subject(tenant_id, ERASED)

    async def content_jobs() -> list[dict[str, Any]]:
        async with untenanted_session() as session:
            rows = (
                await session.execute(
                    text("SELECT payload FROM outbox_messages WHERE job = :j"),
                    {"j": "delete_engine_call_content"},
                )
            ).scalars()
            return [row for row in rows if row.get("tenant_id") == str(tenant_id)]

    assert await content_jobs() == []
    [payload] = await _recall_payloads(tenant_id)
    await _run(monkeypatch, _Vendor(), payload)
    assert await content_jobs() == [{"tenant_id": str(tenant_id), "call_ids": [str(call_id)]}]
