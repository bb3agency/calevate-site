"""The forwarding API's request and response shapes (D-746). Responses are the whitelist."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

LineKind = Literal["mobile", "landline", "office_system"]
Carrier = Literal["airtel", "jio", "vi", "bsnl", "other"]
Mode = Literal["conditional", "all_calls"]
LineStatus = Literal["untested", "testing", "working", "not_working"]
CallerIdFinding = Literal["caller_shown", "business_number_shown", "other_number_shown"]
ConcurrencyFinding = Literal["both_arrived", "one_arrived", "not_tested"]
TestStatus = Literal["placing", "ringing", "settled", "failed"]
TestOutcome = Literal["arrived", "not_arrived", "answered_on_phone", "not_placed"]
Evidence = Literal["carrier_own", "standards_body", "web_secondary"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LineIn(Strict):
    #: The number callers already know, as typed.
    number: str = Field(min_length=6, max_length=24)
    line_kind: LineKind
    carrier: Carrier
    mode: Mode
    #: 5-30 in steps of 5 for `conditional`; 0 for `all_calls`.
    ring_seconds: int = Field(ge=0, le=30)
    calevate_number_id: UUID | None = None
    #: "This number belongs to my business."
    attest: bool


class LineChangeIn(Strict):
    line_kind: LineKind
    carrier: Carrier
    mode: Mode
    ring_seconds: int = Field(ge=0, le=30)
    calevate_number_id: UUID | None = None


class LineOut(Strict):
    id: UUID
    #: The business's own published number.
    e164: str
    line_kind: LineKind
    carrier: Carrier
    mode: Mode
    ring_seconds: int
    calevate_number_id: UUID | None
    calevate_number_e164: str | None
    status: LineStatus
    attested_at: datetime
    last_tested_at: datetime | None
    caller_id_finding: CallerIdFinding | None
    concurrency_finding: ConcurrencyFinding | None
    last_test_outcome: TestOutcome | None
    #: Calls normally arrive and none has for three days (D-746 quiet line).
    quiet_since: datetime | None


class CalevateNumberOut(Strict):
    id: UUID
    e164: str
    answering: bool


class ForwardingOut(Strict):
    lines: list[LineOut]
    calevate_numbers: list[CalevateNumberOut]
    #: The verification call can be placed on this deployment.
    testing_available: bool
    #: Two calls can be placed at once, so a test checks two callers get through.
    concurrency_testable: bool
    max_lines: int


class ForwardingTestOut(Strict):
    id: UUID
    line_id: UUID
    status: TestStatus
    outcome: TestOutcome | None
    legs_placed: int
    caller_id_finding: CallerIdFinding | None
    concurrency_finding: ConcurrencyFinding | None
    failure_code: str | None
    created_at: datetime
    settled_at: datetime | None


class CodeOut(Strict):
    condition: str
    activate: str | None
    deactivate: str | None
    evidence: Evidence
    source: str


class CodeSetOut(Strict):
    label: str
    codes: list[CodeOut]


class CarrierGuideOut(Strict):
    carrier: str
    method: Literal["codes", "app", "ask_provider"]
    codes: list[CodeOut]
    unconfirmed: list[CodeSetOut]
    app_path: str | None
    note: str | None


class CodesOut(Strict):
    carriers: list[CarrierGuideOut]
    provider: CarrierGuideOut
    #: Where the ring-time clause of the no-answer code comes from.
    ring_time_source: str
    read_on: str


class SaveNumberIn(Strict):
    enabled: bool


class SaveNumberOut(Strict):
    enabled: bool


class AdminForwardingOut(Strict):
    lines: list[LineOut]
    recent_tests: list[ForwardingTestOut]
    save_number_enabled: bool
    save_number_sent: int


__all__ = [
    "AdminForwardingOut",
    "CalevateNumberOut",
    "CarrierGuideOut",
    "CodesOut",
    "ForwardingOut",
    "ForwardingTestOut",
    "LineChangeIn",
    "LineIn",
    "LineOut",
    "SaveNumberIn",
    "SaveNumberOut",
]
