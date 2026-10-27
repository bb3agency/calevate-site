"""Tables behind "Tell my team" (D-904, migration c4e9a2f7d816).

`team_alert_contacts` — the business's own addresses that may receive a caller's full
details, each verified once by a code mailed to it. Account-wide: one team inbox serves
every agent, and one of them may be the default an agent without a choice of its own uses.
Soft-removed (`removed_at`) so the alerts already sent to it keep their reference.

`team_alert_rules` — per agent, when to tell the team: chosen business outcomes, chosen values
of chosen choice fields, and whether the agent may tell the team during the call.

`team_alerts` — one row per (call, address): the idempotency key and the delivery record. Ids,
the trigger, the matched reasons (outcome keys and choice values the owner configured, never a
caller's words), the status and the attempts. The problem the agent described on the call is
NOT stored here: it rides in the outbox payload, which is cleared once the job is queued.

All three are tenant tables with FORCEd RLS (hard rule 1).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: Email is always offered. WhatsApp only through the client's OWN connected WhatsApp account
#: or provider (founder, 27 Oct 2026), with a template of theirs (D-904).
CONTACT_CHANNELS = ("email", "whatsapp")
#: What a WhatsApp alert template's body variables carry, in the order the owner chose.
WHATSAPP_SLOTS = ("name", "phone", "why", "link")
ALERT_TRIGGERS = ("after_call", "in_call")
ALERT_STATUSES = ("queued", "sent", "failed", "cancelled")

MAX_ADDRESS_CHARS = 254


class TeamAlertContact(PKMixin, TimestampMixin, Base):
    __tablename__ = "team_alert_contacts"
    __table_args__ = (
        CheckConstraint("channel IN ('email', 'whatsapp')", name="channel_enum"),
        CheckConstraint(
            "channel = 'email' OR (whatsapp_template IS NOT NULL "
            "AND jsonb_typeof(whatsapp_values) = 'array')",
            name="whatsapp_complete",
        ),
        CheckConstraint(
            f"char_length(address) BETWEEN 3 AND {MAX_ADDRESS_CHARS}", name="address_length"
        ),
        CheckConstraint("code_attempts >= 0", name="code_attempts_not_negative"),
        Index(
            "uq_team_alert_contacts_live_address",
            "tenant_id",
            "channel",
            "address",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index(
            "uq_team_alert_contacts_one_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default AND removed_at IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String, nullable=False, server_default="email")
    #: Lower-cased email address, or the team's WhatsApp number in E.164.
    address: Mapped[str] = mapped_column(Text, nullable=False)
    #: WhatsApp only: the client's own connected account or provider key the alert is sent
    #: through, their approved template, and which value fills each body variable in order.
    #: SET NULL when the credential is deleted; such an address no longer receives anything.
    whatsapp_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "integration_credentials.id",
            ondelete="SET NULL",
            name="fk_team_alert_contacts_wa_credential",
        )
    )
    whatsapp_template: Mapped[str | None] = mapped_column(Text)
    whatsapp_language: Mapped[str | None] = mapped_column(String)
    whatsapp_number_id: Mapped[str | None] = mapped_column(String)
    whatsapp_values: Mapped[list[str] | None] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    verified_at: Mapped[datetime | None] = mapped_column()
    #: Keyed hash of the pending code (`authn/codes.code_fingerprint`), never the code.
    code_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    code_expires_at: Mapped[datetime | None] = mapped_column()
    code_sent_at: Mapped[datetime | None] = mapped_column()
    code_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    removed_at: Mapped[datetime | None] = mapped_column()


class TeamAlertRule(PKMixin, TimestampMixin, Base):
    __tablename__ = "team_alert_rules"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_team_alert_rules_agent_id"),
        CheckConstraint("jsonb_typeof(on_outcomes) = 'array'", name="on_outcomes_is_array"),
        CheckConstraint("jsonb_typeof(on_fields) = 'array'", name="on_fields_is_array"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    #: NULL follows the account's default address.
    contact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("team_alert_contacts.id", ondelete="SET NULL")
    )
    #: Business outcome keys (`agents.business_outcomes`).
    on_outcomes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    #: `[{key, values: [...]}]` over the agent's choice (enum) fields.
    on_fields: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    in_call: Mapped[bool] = mapped_column(nullable=False, server_default="false")


class TeamAlert(PKMixin, TimestampMixin, Base):
    __tablename__ = "team_alerts"
    __table_args__ = (
        CheckConstraint(f"trigger IN {ALERT_TRIGGERS!r}", name="trigger_enum"),
        CheckConstraint(f"status IN {ALERT_STATUSES!r}", name="status_enum"),
        CheckConstraint("jsonb_typeof(reasons) = 'array'", name="reasons_is_array"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        # Once per call per address: an alert sent during the call is not repeated after it.
        UniqueConstraint("call_id", "contact_id", name="uq_team_alerts_call_contact"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[UUID] = mapped_column(
        ForeignKey("team_alert_contacts.id", ondelete="RESTRICT"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_at: Mapped[datetime | None] = mapped_column()


__all__ = [
    "ALERT_STATUSES",
    "ALERT_TRIGGERS",
    "CONTACT_CHANNELS",
    "MAX_ADDRESS_CHARS",
    "TeamAlert",
    "TeamAlertContact",
    "TeamAlertRule",
]
