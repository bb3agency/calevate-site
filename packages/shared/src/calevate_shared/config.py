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
    # The engine's egress addresses — comma-separated, literal IPs only. This is the
    # ENTIRE authenticity control for an unsigned engine, and it is a value the VENDOR
    # owns: they can renumber without telling us, and while it is stale every webhook
    # 401s and every call waits for the 10-minute poller. It lives here so rotating it
    # is an environment change and a restart, not a code change and a deploy of the
    # latency-critical service. Not a secret — an allowlist. Parsing fails safe: junk
    # entries are dropped and an empty result falls back to the documented default
    # (apps/voice-runtime/engine_intake.py), because an empty allowlist is an outage.
    bolna_webhook_source_ips: str = "13.203.39.153"
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

    # WhatsApp transport for hot-lead alerts (ROADMAP M2). OFF by default and it must
    # stay off until the human checklist in workers/whatsapp.py is done: WABA + business
    # verification, an APPROVED template, and a recorded per-tenant opt-in (which needs
    # a column that does not exist yet). No BSP has been chosen in the decision log, so
    # `whatsapp_provider` is a seam, not a switch: any name other than `console`
    # resolves to `provider_not_implemented` and refuses to send, loudly.
    whatsapp_enabled: bool = False
    whatsapp_provider: str | None = None
    # The approved template's name and language, as registered with the provider. Here
    # rather than in code because re-approval is an operational event, not a deploy.
    whatsapp_template_hot_lead: str = "calevate_hot_lead_v1"
    whatsapp_template_locale: str = "en"

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    sentry_dsn: str | None = None
    # Stamped onto every error so a report names the deploy that produced it.
    # CI sets it from the commit sha; unset is fine and reads as 'dev'.
    release_version: str = "dev"
    posthog_key: str | None = None

    # OpenTelemetry (TRD §2). Base URL of an OTLP/HTTP collector — the exporter appends
    # `/v1/traces`. UNSET IS THE LOCAL DEFAULT AND MEANS NO TRACING AT ALL: no SDK
    # import, no middleware, no background exporter thread, so `uv run pytest` and a
    # dev box need nothing running (same contract as an absent SENTRY_DSN).
    otel_exporter_otlp_endpoint: str | None = None
    # Head sampling ratio for ROOT traces; child hops inherit the decision through the
    # traceparent, so a sampled call stays whole from webhook to Postgres. 10% because
    # the SLO BREACH is already caught on 100% of calls by the pipeline-lag metric —
    # traces are for diagnosing one, and a diagnosis needs a representative sample, not
    # every call. Config so an incident can raise it to 1.0 with a restart, not a deploy.
    otel_traces_sample_ratio: float = Field(default=0.1, ge=0.0, le=1.0)

    # Effective outbound pool = MIN(platform lines, model concurrency, trunk
    # channels) minus inbound_reserve. Values come from engine verification item 8.
    inbound_reserve_ratio: float = Field(default=0.3, ge=0.0, le=1.0)

    # Self-serve list price per calling minute, INR (D-34). One number for the whole
    # motion until per-tier pricing ships — it exists in config so the runway framing
    # ("about N minutes left") and the top-up flow price from the SAME source, and so
    # a price change is a deploy, not a code edit. Managed clients never see it: their
    # price lives in their `plans` row.
    self_serve_inr_per_min: Decimal = Decimal("6.00")

    # R-11's kill switch. Self-serve signup is the sharp edge of D-34 (anyone can sign
    # up and dial), so the public intake is OFF unless someone turned it on, and
    # closing it during an incident is an environment change, not a deploy.
    self_serve_signup_enabled: bool = False

    # Razorpay prepaid top-ups (D-34). NOTE: no Razorpay account has been provisioned
    # and the vendor contract is UNVERIFIED — see apps/api/billing/payments.py, which
    # isolates every assumption about their signing scheme and payload shape.
    # The PUBLIC key id, handed to the browser's checkout. Unset = the top-up intent
    # answers "payments not configured" rather than returning an unusable intent.
    razorpay_key_id: str | None = None
    # The webhook signing secret from their dashboard. Unset means the payment
    # receiver FAILS CLOSED — an unverifiable payment feed credits wallets on
    # anyone's say-so, which is worse than no feed at all.
    razorpay_webhook_secret: str | None = None


__all__ = ["EngineName", "Environment", "Settings"]
