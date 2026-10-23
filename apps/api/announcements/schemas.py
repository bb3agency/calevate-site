"""Wire models for the announcement bar (D-869)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.api.announcements.models import MAX_MESSAGE_CHARS, Audience, Tone

MAX_LINK_CHARS = 500
MAX_LINK_LABEL_CHARS = 40


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _link(value: str | None) -> str | None:
    """A link is an https address or a path inside the console ("/billing"). Anything else
    — `http:`, `javascript:`, a bare word — is refused, because the bar renders it as a link
    every client clicks."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith("https://") or (value.startswith("/") and not value.startswith("//")):
        return value
    raise ValueError("a link is an https:// address or a console path starting with /")


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("send the time with its offset, e.g. 2026-10-25T09:00:00+05:30")
    return value


class AnnouncementIn(Strict):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    link_url: str | None = Field(default=None, max_length=MAX_LINK_CHARS)
    link_label: str | None = Field(default=None, max_length=MAX_LINK_LABEL_CHARS)
    tone: Tone = "info"
    audience: Audience = "all"
    #: Required exactly when `audience` is `tenant`.
    target_tenant_id: UUID | None = None
    #: When it starts showing; now when left out. With an offset (IST: +05:30).
    starts_at: datetime | None = None
    #: When it stops by itself; never when left out (it shows until ended).
    ends_at: datetime | None = None

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("say something a client can read")
        return value

    @field_validator("link_url")
    @classmethod
    def _link_url(cls, value: str | None) -> str | None:
        return _link(value)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _offset(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def _shape(self) -> AnnouncementIn:
        if (self.audience == "tenant") != (self.target_tenant_id is not None):
            raise ValueError("name one client exactly when the audience is one client")
        if self.link_label and not self.link_url:
            raise ValueError("a link label needs a link")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("it must end after it starts")
        return self


class AnnouncementUpdateIn(Strict):
    """A PATCH: only the fields sent change. `link_url`, `link_label` and `ends_at` may be
    sent as null to clear them."""

    message: str | None = Field(default=None, min_length=1, max_length=MAX_MESSAGE_CHARS)
    link_url: str | None = Field(default=None, max_length=MAX_LINK_CHARS)
    link_label: str | None = Field(default=None, max_length=MAX_LINK_LABEL_CHARS)
    tone: Tone | None = None
    audience: Audience | None = None
    target_tenant_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("message")
    @classmethod
    def _message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("say something a client can read")
        return value

    @field_validator("link_url")
    @classmethod
    def _link_url(cls, value: str | None) -> str | None:
        return _link(value)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _offset(cls, value: datetime | None) -> datetime | None:
        return _aware(value)


AnnouncementState = Literal["scheduled", "showing", "finished", "ended"]


class AnnouncementAdminOut(Strict):
    id: UUID
    message: str
    link_url: str | None
    link_label: str | None
    tone: Tone
    audience: Audience
    target_tenant_id: UUID | None
    target_tenant_name: str | None
    starts_at: datetime
    ends_at: datetime | None
    ended_at: datetime | None
    #: `scheduled` (starts later), `showing`, `finished` (its end time passed) or `ended`
    #: (an operator pressed End).
    state: AnnouncementState
    created_at: datetime
    updated_at: datetime


class AnnouncementAdminListOut(Strict):
    items: list[AnnouncementAdminOut]
    total: int


class AnnouncementOut(Strict):
    """What a client is shown. No audience, no author: only the message and its link."""

    id: UUID
    message: str
    link_url: str | None
    link_label: str | None
    tone: Tone
    starts_at: datetime
    ends_at: datetime | None


class AnnouncementListOut(Strict):
    items: list[AnnouncementOut]


__all__ = [
    "AnnouncementAdminListOut",
    "AnnouncementAdminOut",
    "AnnouncementIn",
    "AnnouncementListOut",
    "AnnouncementOut",
    "AnnouncementState",
    "AnnouncementUpdateIn",
]
