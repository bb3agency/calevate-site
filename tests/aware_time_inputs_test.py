"""A booked time or a consent date with no timezone is refused at the wire, naming the field.

A bare `2026-11-10T10:00` names no instant: compared with the server's clock it raised (a
500) or was stored as if it were UTC (a call five and a half hours off). Every web form
sends an offset (`+05:30`, or an ISO instant), so only a hand-written request meets this.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from apps.api.callbacks.routes import CallbackMoveIn, CallbacksBulkIn
from apps.api.campaigns.routes import ConsentProvenanceIn
from apps.api.crm.one_call import OneCallIn
from apps.api.crm.swipe import ScheduleCallbackIn
from pydantic import BaseModel, ValidationError

NAIVE = "2026-11-10T10:00:00"
AWARE = "2026-11-10T10:00:00+05:30"
IST_OFFSET = timedelta(hours=5, minutes=30)


def _refused_field(model: type[BaseModel], body: dict[str, object]) -> list[object]:
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(body)
    return [error["loc"] for error in excinfo.value.errors()]


def test_a_moved_call_back_needs_its_offset() -> None:
    assert _refused_field(CallbackMoveIn, {"at": NAIVE}) == [("at",)]
    assert CallbackMoveIn.model_validate({"at": AWARE}).at.utcoffset() == IST_OFFSET


def test_a_bulk_move_needs_its_offset() -> None:
    body = {"action": "move", "callback_ids": [str(uuid.uuid4())]}
    assert _refused_field(CallbacksBulkIn, {**body, "at": NAIVE}) == [("at",)]
    assert CallbacksBulkIn.model_validate({**body, "at": AWARE}).at is not None


def test_a_booked_one_off_call_needs_its_offset() -> None:
    body = {"phone": "9876543210", "agent_id": str(uuid.uuid4()), "reason": "Follow up"}
    assert _refused_field(OneCallIn, {**body, "at": NAIVE}) == [("at",)]
    assert OneCallIn.model_validate({**body, "at": AWARE}).at is not None


def test_a_lead_call_back_needs_its_offset() -> None:
    assert _refused_field(ScheduleCallbackIn, {"at": NAIVE}) == [("at",)]
    assert ScheduleCallbackIn.model_validate({"at": AWARE}).at.utcoffset() == IST_OFFSET


def test_a_consent_date_needs_its_offset() -> None:
    body = {"source": "existing_customer"}
    assert _refused_field(ConsentProvenanceIn, {**body, "collected_at": NAIVE}) == [
        ("collected_at",)
    ]
    # The web sends the IST midnight as an ISO instant (`consentCollectedAt`).
    assert ConsentProvenanceIn.model_validate(
        {**body, "collected_at": "2026-11-07T18:30:00.000Z"}
    ).collected_at.utcoffset() == timedelta(0)
