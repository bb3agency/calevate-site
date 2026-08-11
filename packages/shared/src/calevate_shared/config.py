"""Typed settings. The app fails fast on missing config, never at first use.

Any new environment variable is added here AND to `.env.example` (DEV-SETUP.md §4).
Secrets are never defaulted — a missing secret must raise at startup.
"""

from decimal import Decimal
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "prod"]
# ThinnestAI was retired by D-31 before any adapter existed — do not re-add it.
EngineName = Literal["fake", "bolna"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="forbid")

    app_env: Environment = "local"

    # App role (NOSUPERUSER NOBYPASSRLS — RLS depends on it). Migrations use
    # alembic_database_url (owner role) and are the only thing that does.
    database_url: str
    alembic_database_url: str | None = None
    redis_url: str

    object_store_endpoint: str
    object_store_bucket: str

    # Public base URL of the voice-runtime deployable. It is baked into every agent's
    # config at publish time, so it must be the address the ENGINE can reach — not the
    # API's — and changing it means re-publishing every agent.
    webhook_base_url: str = "http://localhost:8100"

    # Engine selection is per-environment; `fake` is the default for local work so
    # the whole pipeline runs offline (DEV-SETUP.md §3).
    engine: EngineName = "fake"
    # Bolna webhooks are UNSIGNED (D-31) — there is deliberately no webhook secret.
    # Authenticity = source-IP allowlist + execution-id dedupe, and the
    # List-Executions poller is the guarantee of record (TRD §5).
    bolna_api_key: str | None = None
    # Bolna quotes cost in USD cents; the adapter converts at capture and STAMPS this
    # rate into usage_events.meta so any ledger row can be re-derived (hard rule 7).
    # A config row, not a live FX call: metering must be reproducible, not current.
    usd_inr_rate: Decimal = Decimal("88.00")

    # BYOK models — canonical stack per D-36: Sarvam does STT + LLM + TTS.
    # Gemini is a configurable FALLBACK, not the default.
    sarvam_api_key: str | None = None
    gemini_api_key: str | None = None
    # Embeddings are provider-managed if the D-28 RAG service bundles them;
    # Cohere is only needed if the bake-off selects a store that does not.
    cohere_api_key: str | None = None

    # Two SEPARATE Clerk applications — admin realm and client realm never share
    # session logic (TRD §11).
    clerk_admin_publishable_key: str | None = None
    clerk_admin_secret_key: str | None = None
    clerk_client_publishable_key: str | None = None
    clerk_client_secret_key: str | None = None
    # Custom domain so the flow is ours end to end (D-37); also the JWKS host.
    clerk_frontend_api: str = "accounts.calevate.tech"
    # Svix signing secret for the user/org mirror webhook (`whsec_...`). Absent means
    # the endpoint FAILS CLOSED — an unverifiable identity feed is worse than none.
    clerk_webhook_secret: str | None = None

    # HMAC material for the audit hash chain and idempotency scope fingerprints
    # (BACKEND-PATTERNS §4/§7). Local dev derives a constant when unset; prod MUST
    # inject it — rotating it starts a new chain, so it is rotated with a drill.
    audit_chain_secret: str | None = None

    # Email transport for hot-lead alerts (ROADMAP M1: email first, WhatsApp next).
    # Any SMTP provider works, which keeps the provider a deployment decision rather
    # than a code dependency. Unset in a non-local env = notifications report FAILURE
    # rather than silently pretending (see workers/transport.py).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    notifications_from: str | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    sentry_dsn: str | None = None
    # Stamped onto every error so a report names the deploy that produced it.
    # CI sets it from the commit sha; unset is fine and reads as 'dev'.
    release_version: str = "dev"
    posthog_key: str | None = None

    # Effective outbound pool = MIN(platform lines, model concurrency, trunk
    # channels) minus inbound_reserve. Values come from engine verification item 8.
    inbound_reserve_ratio: float = Field(default=0.3, ge=0.0, le=1.0)

    # Self-serve list price per calling minute, INR (D-34). One number for the whole
    # motion until per-tier pricing ships — it exists in config so the runway framing
    # ("about N minutes left") and the top-up flow price from the SAME source, and so
    # a price change is a deploy, not a code edit. Managed clients never see it: their
    # price lives in their `plans` row.
    self_serve_inr_per_min: Decimal = Decimal("6.00")


__all__ = ["EngineName", "Environment", "Settings"]
