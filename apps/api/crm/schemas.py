"""CRM request/response models.

**The response model IS the output whitelist** (BACKEND-PATTERNS §1). Every model here
sets `extra="forbid"`, which is what the redaction-exposure guardrail checks: a field
that is not declared cannot be serialized, so adding a raw transcript column to a query
cannot accidentally ship it to a browser.

Two fields are deliberately absent from every default response:
- `transcript_turns[].text` (raw) — `text_redacted` is the default view (hard rule 5).
- the engine's recording URL — clients get a short-lived presigned link to OUR copy.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from pydantic import BaseModel, ConfigDict, Field

LeadStatus = Literal["new", "contacted", "interested", "hot", "won", "lost"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptTurnOut(Strict):
    idx: int
    speaker: Literal["agent", "caller"]
    # Redacted by default. The raw view is a separate, role-checked, audited endpoint.
    text: str
    lang: str | None = None
    start_ms: int | None = None
    redacted: bool = True


class CallSummaryOut(Strict):
    id: UUID
    agent_id: UUID
    agent_name: str | None = None
    direction: Literal["inbound", "outbound"]
    status: str
    # Masked: a call list is the most-screenshotted page in the product.
    caller_masked: str | None = None
    started_at: datetime | None = None
    duration_s: int | None = None
    outcome_tag: str | None = None
    sentiment: str | None = None
    summary: str | None = None
    lead_id: UUID | None = None


class CallDetailOut(CallSummaryOut):
    transcript: list[TranscriptTurnOut] = Field(default_factory=list)
    extraction: dict[str, Any] = Field(default_factory=dict)
    extraction_valid: bool = True
    has_recording: bool = False
    disclosure_played: bool | None = None


class RecordingLinkOut(Strict):
    url: str
    expires_in_s: int


class LeadOut(Strict):
    id: UUID
    phone_masked: str
    name: str | None = None
    status: LeadStatus
    source: str
    data: dict[str, Any] = Field(default_factory=dict)
    schema_version: int | None = None
    call_count: int
    is_repeat_caller: bool
    last_call_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class LeadListOut(Strict):
    """The Leads table is schema-driven (TRD §7): the columns travel WITH the rows so
    the frontend never hard-codes a client's fields."""

    items: list[LeadOut]
    columns: list[ExtractionField]
    total: int
    limit: int
    offset: int


class LeadUpdateIn(Strict):
    # Statuses are a FIXED enum (D-21): analytics and hot-lead rules key off them, so
    # clients cannot add their own.
    status: LeadStatus | None = None
    name: str | None = Field(default=None, max_length=120)


class CallLeadIn(Strict):
    """D-21: an owner may dispatch a single AI call from the Leads table, with an
    optional per-call note rendered into the agent's prompt."""

    agent_id: UUID
    context_note: str | None = Field(default=None, max_length=500)


class CallLeadOut(Strict):
    status: Literal["queued", "blocked"]
    call_handle: str | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None


class DashboardOut(Strict):
    calls_today: int
    calls_7d: int
    leads_new_7d: int
    hot_leads_open: int
    avg_duration_s: int | None = None
    sentiment_split: dict[str, int] = Field(default_factory=dict)
    outcome_split: dict[str, int] = Field(default_factory=dict)
    after_hours_captured_7d: int = 0
    # Client-facing spend is INR NUMERIC, never a float (hard rule 7).
    minutes_used_month: Decimal | None = None


__all__ = [
    "CallDetailOut",
    "CallLeadIn",
    "CallLeadOut",
    "CallSummaryOut",
    "DashboardOut",
    "LeadListOut",
    "LeadOut",
    "LeadStatus",
    "LeadUpdateIn",
    "RecordingLinkOut",
    "TranscriptTurnOut",
]
