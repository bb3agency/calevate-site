"""Tables behind the ACTIONS feature (migration e1f7a3c920b4).

`integration_credentials` — one saved, reusable, envelope-encrypted credential per
(tenant, vendor). Reused across agents and actions: an action references it by id, so
rotating the row updates every action that points at it ("rotate-updates-all", the
founder's requirement). NOT append-only — a rotation is an UPDATE of the sealed columns
under an optimistic-concurrency `version` bump, which is the standard shape for a mutable
credential and the one `credentials.py` argues for.

`action_tools` — one in-call tool definition per (agent, name). Carries the LLM-facing
description, the parameter spec (each slot bound to a static value, a call variable, or an
AI-inferred argument), the kind-specific config, the trigger (during/after the call) and
the reusable credential it uses. Mutable: editing a tool is an UPDATE; the change reaches
live calls at the next publish (the "Apply to live calls" action), exactly as a voice or
cap change does.

Both are tenant-scoped with FORCEd RLS (hard rule 1). The migration ships the policy and a
cross-tenant zero-rows test lives beside it.

WHY THE SECRET IS BYTES HERE AND NOT AN `sm://` REFERENCE. The platform's own vendor keys
live in `platform_secrets` and the outbound-webhook signing secret is a raw column; a
TENANT's third-party credential is a third case, and DATA-MODEL §11's `tenant_secrets`
names it: envelope-encrypted in-row under a per-tenant AAD context, so one tenant's
ciphertext cannot be moved into another's row (`core/envelope.seal`). It is never returned
by any route — `credentials.py` has no read-back, only `last_four`.
"""

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

# Which vendor a saved credential authenticates to. `custom_api` is the generic REST case
# (a bearer token or api key for the client's own endpoint); the WhatsApp BSPs and Google
# each get their own so a screen can label them and `whatsapp.py`/`calendar.py` can refuse
# a credential of the wrong kind.
INTEGRATION_KINDS = ("aisensy", "meta_cloud", "interakt", "custom_api", "google_calendar")

# The three top-level action types the founder's spec names. The WhatsApp BSP variant and
# the calendar provider are sub-selections in `provider` below, not separate kinds — a
# client picks "send a WhatsApp" and then which BSP delivers it.
ACTION_KINDS = ("custom_api", "whatsapp", "calendar")

# When the action runs. `during_call` is declared to the engine as a function the LLM may
# invoke mid-conversation; `after_call` is NOT a tool at all — it runs in the post-call
# pipeline once the transcript is in, so it never touches the latency path.
ACTION_TRIGGERS = ("during_call", "after_call")

# The concrete implementation behind a `whatsapp` or `calendar` action. `custom` is the
# "Other WhatsApp provider" fallback the spec asks for, delivered through the generic REST
# path. NULL for a `custom_api` action, whose implementation is the kind itself.
ACTION_PROVIDERS = ("aisensy", "meta_cloud", "interakt", "custom", "google")


class IntegrationCredential(PKMixin, TimestampMixin, Base):
    __tablename__ = "integration_credentials"
    __table_args__ = (
        CheckConstraint(f"kind IN {INTEGRATION_KINDS!r}", name="kind_enum"),
        # A non-blank human label per credential, so the picker on a tool form shows
        # something a person chose rather than a uuid.
        CheckConstraint("length(btrim(label)) > 0", name="label_not_blank"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)

    # Envelope (core/envelope.py). The secret plaintext is NEVER a column — sealed under
    # `integration_cred:<tenant_id>:<id>` so a row cannot be moved between tenants.
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kek_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Enough to tell two credentials apart in a support call; masked below 8 chars by
    # `core/envelope.last_four`. The only fragment of the secret this table can carry.
    last_four: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    # Optimistic-concurrency counter, bumped on every rotation. A rotate reads the version
    # it saw and writes `WHERE version = :seen`, so two concurrent rotations cannot both
    # land (BACKEND-PATTERNS §5) — CAS rather than read-then-write.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    # Non-secret configuration bound to THIS credential rather than to a tool, so it is
    # reused with the credential. Google Calendar's connected account email and granted
    # scopes go here; a plain api-key credential leaves it NULL.
    non_secret: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class ActionTool(PKMixin, TimestampMixin, Base):
    __tablename__ = "action_tools"
    __table_args__ = (
        CheckConstraint(f"kind IN {ACTION_KINDS!r}", name="kind_enum"),
        CheckConstraint(f"trigger IN {ACTION_TRIGGERS!r}", name="trigger_enum"),
        CheckConstraint(
            f"provider IS NULL OR provider IN {ACTION_PROVIDERS!r}", name="provider_enum"
        ),
        # A snake_case-ish function name, non-blank, so the engine declaration and the LLM
        # have something to call. The stricter shape (snake_case, unique per agent) is
        # enforced in `service.py` where a client-facing message can explain it.
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        # One tool name per agent — it is the function name the LLM calls, and two tools
        # answering to one name is an ambiguous dispatch. Names the columns the upsert
        # conflict-targets.
        UniqueConstraint("agent_id", "name", name="uq_action_tools_agent_name"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # The agent this tool belongs to. CASCADE: a tool has no meaning without its agent, and
    # a soft-deleted agent's tools should go with it rather than dangle.
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str | None] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # WHEN the LLM should call this — the text the model reads. For a during-call WhatsApp
    # send this is the client's natural-language "when during the call" condition.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    trigger: Mapped[str] = mapped_column(String, nullable=False, server_default="during_call")
    # The filler line the agent speaks while our endpoint runs the external call, so the
    # caller does not hear silence over the round trip (Bolna `pre_call_message`).
    pre_call_message: Mapped[str | None] = mapped_column(Text)

    # The saved credential this tool uses. SET NULL rather than RESTRICT so deleting a
    # credential does not wedge on its references — a tool whose credential vanished is
    # refused loudly at execution (`no_credential`) rather than being undeletable.
    credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("integration_credentials.id", ondelete="SET NULL")
    )

    # Kind-specific configuration and the parameter spec. JSONB rather than columns because
    # the three kinds carry different shapes and validation lives in `service.py`:
    #   custom_api: {method, url, headers[], query[], body[]}  each field {source, ...}
    #   whatsapp:   {phone_number_id?, template, language?, header_var?, body_vars[]}
    #   calendar:   {calendar_id, operation: book|check}
    # `params` is the normalized parameter spec each field references — a list of
    # {name, source: static|lead_var|ai, ...} — kept beside config so the engine
    # declaration and the executor read one shape.
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    params: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)


__all__ = [
    "ACTION_KINDS",
    "ACTION_PROVIDERS",
    "ACTION_TRIGGERS",
    "INTEGRATION_KINDS",
    "ActionTool",
    "IntegrationCredential",
]
