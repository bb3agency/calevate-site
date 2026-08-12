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

    # WHERE OPERATOR ALERTS GO (OPERATIONS §4; §8's pre-launch gate "alerts firing to
    # Sri's phone"). `apps/api/core/alerting.py` delivers through the SAME transport as
    # hot-lead notifications — one thing to configure, one thing to be broken.
    #
    # Unset means alerts are logged and delivered NOWHERE, which is the right local and
    # test default and is announced at boot (`alert_delivery_unconfigured`) rather than
    # discovered during an incident. Setting it is the pre-launch gate; a phone gets the
    # alert through its mail app until a BSP is chosen and the WhatsApp seam in
    # `apps/workers/whatsapp.py` can carry the second channel §4 also promises.
    alerts_email: str | None = None

    # THE EXTERNAL DEAD MAN (D-50's open residual, now closed). The ping URL of ONE
    # hosted dead-man check, pinged by `scripts/backup/backup-health.sh` only when every
    # backup check passed. Silence — a failed check, a dead host, a stopped systemd — is
    # what pages; there is deliberately no failure signal. The vendor comparison and the
    # rejected alternatives are argued in `scripts/host_heartbeat.py`; the schedule to
    # configure on the vendor side is in `infra/backup/README.md` §5.
    #
    # IT IS A CREDENTIAL: anyone holding it can silence the alarm by pinging it, which
    # is exactly the property that makes it usable from a shell with no auth header. So
    # it is injected from the secrets manager like every other one here, never committed,
    # and never logged (`host_heartbeat` prints a digest prefix instead).
    #
    # UNSET is the correct local, CI and test value and means the heartbeat is a no-op
    # that SAYS SO once rather than passing silently — a "configured" heartbeat that
    # reaches nobody is the exact defect this closes.
    backup_heartbeat_url: str | None = None

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

    # Google Sheets delivery for outbound CRM sync (D-23, `outbound_webhooks.kind =
    # 'google_sheets'`). Same seam as `whatsapp_provider`: `console` is the local dev
    # sink (refused outside APP_ENV=local), `service_account` selects the real adapter
    # in `apps/workers/google_sheets.py`, and any other name resolves to
    # `provider_not_implemented` and refuses to append rather than pretending. Unset
    # falls back to the dev sink locally and a refusal everywhere else.
    #
    # This exists as CONFIG rather than as `app_env == "local"` — which is what
    # selection used to key off — because "are we on a laptop" is not a statement about
    # Google Sheets, and the client-facing config surface has to gate on something that
    # is. `apps/api/integrations/routes.py` refuses to create a sheets endpoint when
    # this says the deployment cannot deliver to one.
    #
    google_sheets_provider: str | None = None

    # The service-account key the `service_account` provider signs with: the JSON blob
    # Google issues, injected from the secrets manager at deploy time exactly like
    # BOLNA_API_KEY and the Clerk keys (DEV-SETUP §4). Unset with the provider set is
    # itself a refusal — `get_sheets_transport` returns the unconfigured transport, so
    # the API stops offering the Sheets checkbox rather than creating endpoints that
    # cannot authenticate.
    #
    # THE PREVIOUS COMMENT HERE SAID KEY MATERIAL NEVER LIVES IN SETTINGS, and that
    # claim has to be corrected rather than quietly dropped. What `secret_ref` on the
    # endpoint row holds is a REFERENCE — `sm://google-sheets/default` — and that is
    # still true and still the rule: no key material in the database, ever. The
    # reference names WHICH credential the deployment should use; the credential itself
    # lives where every other vendor key in this system lives, which is the process
    # environment fed by the secrets manager. There is nowhere else for it to live: this
    # deployment has no runtime secret-fetching client, and inventing one for a single
    # key would be a second way to hold a secret.
    #
    # ONE key for the whole platform, not one per tenant, because the tenancy boundary
    # here is not ours to enforce: a client grants access by SHARING their own document
    # with our service account's address and revokes it by un-sharing. Per-tenant
    # service accounts would multiply GCP identities without narrowing what any one key
    # can reach — it can only ever reach documents someone chose to share with it.
    google_sheets_service_account_json: str | None = None

    # NO LANGFUSE OR POSTHOG KEYS HERE, DELIBERATELY. Both existed as settings with no
    # client anywhere in the tree: they would have been no-ops WITH real credentials,
    # and a settings field that looks like a credential is a claim that something is
    # wired. The next person reads `LANGFUSE_SECRET_KEY` in `.env.example`, fills it in,
    # and believes per-call token cost is being recorded. It is not. Removed rather than
    # faked, per TRD §2's own correction ("Langfuse is a SEAM ... PostHog is a config key
    # with no client either").
    #
    # TO RESTORE LANGFUSE: it is a vendor decision plus credentials, not a wiring job.
    # The v3 Python SDK is an OpenTelemetry SDK — `Langfuse(public_key=..., secret_key=
    # ..., host=...)` then `get_client()`, exporting spans to a Langfuse project
    # (https://github.com/langfuse/langfuse-python, https://pypi.org/project/langfuse/).
    # That makes it a SECOND tracing pipeline next to the OTel one this repo already
    # ships, so the decision is (a) a Langfuse project + keys, (b) a Decision-Log entry
    # choosing it over exporting the existing OTel spans to a Langfuse OTLP endpoint,
    # and (c) a call site — `apps/workers/extraction.py` is the only place that talks to
    # an LLM, and its payload must go through `observability.redact_trace_payload`
    # (hard rule 6) before it leaves the process.
    #
    # TO RESTORE POSTHOG: product analytics is a BROWSER concern and never belonged in
    # backend Settings. It restores as `NEXT_PUBLIC_POSTHOG_KEY` in `apps/web`, with a
    # DPDP sub-processor entry and the same field masking the teardown note records for
    # the competitor (docs/evidence/outpero-teardown-aug2026.md §9) — not as a Python
    # config field.
    sentry_dsn: str | None = None
    # Stamped onto every error so a report names the deploy that produced it.
    # CI sets it from the commit sha; unset is fine and reads as 'dev'.
    release_version: str = "dev"

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
    #
    # WHICH payment provider this deployment has. Exists as CONFIG rather than being
    # inferred from "is there a key id" for the same reason `google_sheets_provider`
    # does: a key id is a credential, not a statement that the capability exists, and
    # every surface that needs to know whether payment works was left reading the
    # credential and deciding for itself. `apps/api/billing/payments.py` owns the ONE
    # selector; the only name with anything behind it today is `razorpay`, and any
    # other name resolves to `provider_not_implemented` rather than looking configured.
    payment_provider: str | None = None
    # WHICH telephony vendor may sell this deployment a phone number (D-05: Exotel, with
    # Vobiz for the 140-series). Config rather than an inference from a credential, for
    # the same reason `payment_provider` is: a key is not a statement that the
    # capability exists. NO ADAPTER EXISTS FOR ANY VALUE — `apps/api/campaigns/
    # provisioning.py` owns the one selector and `PROVISIONING_IMPLEMENTED` is False —
    # so this setting currently decides only WHICH refusal an operator sees. A name
    # outside {exotel, vobiz} resolves to `provider_not_implemented` rather than looking
    # configured.
    number_provider: str | None = None
    # The PUBLIC key id, handed to the browser's checkout. Unset = the top-up intent
    # answers "payments not configured" rather than returning an unusable intent.
    razorpay_key_id: str | None = None
    # The webhook signing secret from their dashboard. Unset means the payment
    # receiver FAILS CLOSED — an unverifiable payment feed credits wallets on
    # anyone's say-so, which is worse than no feed at all.
    razorpay_webhook_secret: str | None = None


__all__ = ["EngineName", "Environment", "Settings"]
