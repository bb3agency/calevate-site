"""The WhatsApp tables (migration `c8e5a2f7d914`, D-784), declared so `Base.metadata` is
complete. The migration is the schema of record.

`whatsapp_accounts` is one client's WhatsApp Business Account and sending number, connected
through Meta's Embedded Signup; the business token it sends with is an
`integration_credentials` row (`credential_id`), never a column here. `whatsapp_templates` is
the message templates submitted to that account and the review state Meta reports for them.
Both are FORCE-RLS'd. The account table's read policy also admits the one row a verified
Meta webhook names (`db/session.whatsapp_waba_session`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

ACCOUNT_STATUSES: Final = ("connecting", "connected", "needs_attention", "disconnected")
#: How the account arrived: a new WhatsApp Business account, a number already on the
#: WhatsApp Business app (coexistence), or an existing API account the client granted us.
ONBOARDINGS: Final = ("new", "business_app", "grant_access")
TEMPLATE_ORIGINS: Final = ("calevate", "client")
#: The categories a client may submit. AUTHENTICATION is Meta's one-time-code category and is
#: not offered: an agent never sends a login code.
TEMPLATE_CATEGORIES: Final = ("UTILITY", "MARKETING")
TEMPLATE_STATUSES: Final = (
    "draft",
    "pending",
    "approved",
    "rejected",
    "paused",
    "disabled",
    "deleted",
    "submit_failed",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _digits(column: str, *, nullable: bool) -> str:
    check = f"{column} ~ '^[0-9]{{1,64}}$'"
    return f"{column} IS NULL OR {check}" if nullable else check


class WhatsAppAccount(PKMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_accounts"
    __table_args__ = (
        CheckConstraint(_digits("waba_id", nullable=False), name="waba_id_digits"),
        CheckConstraint(_digits("phone_number_id", nullable=True), name="phone_number_id_digits"),
        CheckConstraint(_digits("business_id", nullable=True), name="business_id_digits"),
        CheckConstraint(_in("onboarding", ONBOARDINGS), name="onboarding_enum"),
        CheckConstraint(_in("status", ACCOUNT_STATUSES), name="status_enum"),
        CheckConstraint(
            "(status = 'disconnected') = (disconnected_at IS NOT NULL)", name="disconnected_iff"
        ),
        Index(
            "ux_whatsapp_accounts_live_waba",
            "waba_id",
            unique=True,
            postgresql_where=text("status <> 'disconnected'"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("integration_credentials.id", ondelete="SET NULL")
    )
    # Meta's ids are numeric strings; digits only because they are spliced into Graph paths.
    waba_id: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_number_id: Mapped[str | None] = mapped_column(String(64))
    business_id: Mapped[str | None] = mapped_column(String(64))
    # The client's OWN business number, as Meta displays it — not a caller's.
    display_phone_number: Mapped[str | None] = mapped_column(String(32))
    verified_name: Mapped[str | None] = mapped_column(Text)
    name_status: Mapped[str | None] = mapped_column(String(32))
    quality_rating: Mapped[str | None] = mapped_column(String(16))
    messaging_limit: Mapped[str | None] = mapped_column(String(32))
    onboarding: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="connecting")
    registered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    webhooks_subscribed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    #: Our code for the set-up step that did not finish, or NULL.
    setup_error: Mapped[str | None] = mapped_column(String(64))
    templates_seeded_at: Mapped[datetime | None] = mapped_column()
    #: When Meta last told us anything about this account (webhook health).
    last_event_at: Mapped[datetime | None] = mapped_column()
    #: The latest account-level event Meta reported (`account_update` / alerts), as a code.
    account_alert: Mapped[str | None] = mapped_column(String(64))
    account_alert_at: Mapped[datetime | None] = mapped_column()
    #: The latest failed-delivery error code Meta reported for a message we sent.
    last_send_error: Mapped[str | None] = mapped_column(String(64))
    last_send_error_at: Mapped[datetime | None] = mapped_column()
    connected_at: Mapped[datetime | None] = mapped_column()
    disconnected_at: Mapped[datetime | None] = mapped_column()


class WhatsAppTemplate(PKMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        CheckConstraint(r"name ~ '^[a-z0-9_]+$'", name="name_shape"),
        CheckConstraint(r"language ~ '^[a-z]{2,3}(_[A-Z]{2})?$'", name="language_shape"),
        CheckConstraint(_in("category", TEMPLATE_CATEGORIES), name="category_enum"),
        CheckConstraint(_in("origin", TEMPLATE_ORIGINS), name="origin_enum"),
        CheckConstraint(_in("status", TEMPLATE_STATUSES), name="status_enum"),
        CheckConstraint("length(body) BETWEEN 1 AND 1024", name="body_length"),
        CheckConstraint(_digits("meta_template_id", nullable=True), name="meta_template_id_digits"),
        UniqueConstraint("account_id", "name", "language"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("whatsapp_accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The business's own template text with `{{1}}`-style blanks. Never a caller's words.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: One `{label, example}` per blank, in order.
    variables: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    #: For a Calevate template, which job it serves (`templates.STANDARD`).
    purpose: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="draft")
    #: Meta's own word for the state, as last reported.
    meta_status: Mapped[str | None] = mapped_column(String(32))
    meta_template_id: Mapped[str | None] = mapped_column(String(64))
    #: Meta's rejection reason code (`INVALID_FORMAT`, …), never free text.
    rejection_code: Mapped[str | None] = mapped_column(String(128))
    category_changed_to: Mapped[str | None] = mapped_column(String(32))
    submitted_at: Mapped[datetime | None] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column()


__all__ = [
    "ACCOUNT_STATUSES",
    "ONBOARDINGS",
    "TEMPLATE_CATEGORIES",
    "TEMPLATE_ORIGINS",
    "TEMPLATE_STATUSES",
    "WhatsAppAccount",
    "WhatsAppTemplate",
]
