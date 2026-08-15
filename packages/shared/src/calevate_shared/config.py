"""Typed settings. The app fails fast on missing config, never at first use.

Any new environment variable is added here AND to `.env.example` (DEV-SETUP.md §4).
Secrets are never defaulted — a missing secret must raise at startup.
"""

import ipaddress
import logging
from decimal import Decimal
from functools import lru_cache
from typing import Literal, get_args

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "prod"]
# ThinnestAI was retired by D-31 before any adapter existed — do not re-add it.
# `cartesia` is a REAL adapter with a real conformance run (D-93), not a placeholder —
# but D-94 gates ADOPTING it on three triggers, one of which (BYOC SIP from an Indian
# DLT-registered carrier) is unanswered. Selectable, not recommended.
#
# THE ONE DEFINITION OF WHAT `ENGINE=` MAY BE (D-103). It is a `Literal` because pydantic
# validates the setting against it and mypy checks every comparison against it, and
# neither can be done with a runtime set — so this is the one spelling of these names on
# the selection axis, and `SELECTABLE_ENGINES` below is how every other module asks.
EngineName = Literal["fake", "bolna", "cartesia"]

#: The same set as a value, for the callers that need to CHECK membership rather than
#: annotate a field — `get_args` on the Literal, never a second tuple beside it.
#:
#: WHY IT EXISTS AT ALL (D-103). It did not, and the absence is what let three copies of
#: this set grow: `apps/voice-runtime/engine_intake.py` retyped it as its own `Literal`
#: and drifted to `("bolna", "fake")` after `cartesia` was added here, and
#: `apps/api/agents/models.py::ENGINES` still is `("fake", "bolna")` — which is not a
#: cosmetic disagreement, because that tuple renders the `ck_agents_engine_enum` CHECK
#: constraint, so a deployment running `ENGINE=cartesia` cannot insert an agent row at
#: all. A set nobody can import is a set everybody retypes.
#:
#: `tests/engine_name_drift_test.py` walks the tree for a second spelling and fails on
#: one, which is the part that keeps this the ONE definition rather than the first of
#: several. It is a frozenset rather than the raw tuple so no caller can mutate the
#: answer another caller is about to read.
SELECTABLE_ENGINES: frozenset[str] = frozenset(get_args(EngineName))

# Stdlib logger, not `apps.api.core.logging.get_logger`: `calevate_shared` is imported by
# every deployable and must not depend on `apps`. `get_logger` is `logging.getLogger`
# anyway, and `configure_logging` installs its JSON handler on the ROOT logger, so these
# records come out in the same format as everything else.
_log = logging.getLogger(__name__)

# Bolna's documented egress address (D-31, TRD §5). THE only copy of this literal on any
# runtime path — `Settings.bolna_webhook_source_ips` defaults to it, and both the
# receiver (`apps/voice-runtime/engine_intake.py`) and the adapter
# (`apps/api/engine/bolna.py`) resolve their effective allowlist through
# `bolna_source_ips()` below. `scripts/pilot/gates_api.DOCUMENTED_EGRESS_IP` restates it
# ON PURPOSE and argues why: a gate that imported the value it tests would be asking the
# code whether it agrees with itself.
DEFAULT_BOLNA_SOURCE_IPS: frozenset[str] = frozenset({"13.203.39.153"})


@lru_cache(maxsize=8)
def parse_source_ip_allowlist(configured: str) -> frozenset[str]:
    """Parse a configured webhook source-IP allowlist. Fails SAFE, never open.

    Three deliberate properties, because for an unsigned engine this string is the whole
    authenticity control (D-31: no signature, no retry, at-most-once):

    - entries must parse as literal IP addresses. A CIDR, a hostname or a `*` is not a
      supported entry, so nobody can turn the allowlist into a wildcard by typing one
      — and a typo cannot quietly widen trust;
    - unusable entries are dropped with a log line, not silently accepted;
    - if NOTHING usable remains, the built-in default stands. An empty allowlist would
      reject the engine itself, which is a total outage; an operator who wants to stop
      accepting webhooks stops the service, they do not blank a variable.

    Cached on the string because the receiver calls it per delivery inside a 500ms ack
    budget (hard rule 3) and the answer is a pure function of the input. The cache also
    means the "entry ignored" warning is emitted once per distinct value rather than
    once per webhook, which is the difference between a signal and a flood.
    """
    entries: set[str] = set()
    for part in configured.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            _log.warning("webhook_allowlist_entry_ignored", extra={"reason": "not an ip address"})
            continue
        entries.add(candidate)
    return frozenset(entries) or DEFAULT_BOLNA_SOURCE_IPS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="forbid")

    # NO DEFAULT, ON PURPOSE. The environment is STATED, never inferred.
    #
    # This field used to default to `"local"`, and `"local"` is the single value under
    # which `apps/api/core/auth.py::_verify_dev_token` accepts `dev:<realm>:<clerk_id>`
    # — a credential whose SUBJECT THE CALLER CHOOSES. `runtime_config_missing_keys`
    # skips its Clerk-key checks under the same branch, so `/healthz/ready` reported a
    # healthy service while doing it. One forgotten variable therefore switched off
    # both the authentication and the alarm, and a deploy that never set APP_ENV looked
    # exactly like one that did.
    #
    # A default that is safe locally and catastrophic in production is not a default;
    # it is a trap with an ergonomics argument attached. Removing it costs one line in
    # `.env.example` (already there) and one line in every deployment's env file, and
    # buys: no configuration can be `local` without someone having typed `local`.
    # `APP_ENV` is in `BOOTSTRAP_REQUIRED` too, so the failure an operator meets is a
    # sentence naming the variable and its allowed values rather than a Pydantic
    # traceback listing every optional model key (BACKEND-PATTERNS §2 step 1).
    app_env: Environment

    # App role (NOSUPERUSER NOBYPASSRLS — RLS depends on it). Migrations use
    # alembic_database_url (owner role) and are the only thing that does.
    database_url: str
    alembic_database_url: str | None = None
    redis_url: str

    # Persistent Postgres connections THIS PROCESS may hold. Per process, not per
    # deployable: every uvicorn worker and every ARQ worker builds its own engine, so
    # the cluster's connection budget is `db_pool_size x (all processes)` and it has to
    # fit under the server's `max_connections` (DEPLOYMENT §2a does that arithmetic).
    #
    # It is a setting rather than a constant because the right value differs by
    # deployable — the webhook receiver holds a connection for ~15ms, an admin request
    # for far longer — and re-sizing a pool during an incident must be an environment
    # change and a restart, not a deploy of the latency-critical service.
    #
    # The default is 16 because that is exactly the ceiling the code already had
    # (SQLAlchemy's default 5 + 10 overflow = 15, plus one), so no deployment loses
    # capacity by adopting it; what changes is that all 16 are POOLED instead of five
    # pooled and ten churning. `apps/api/db/session.py` argues why the overflow is the
    # expensive half.
    # THE UPPER BOUND IS NOT DECORATION. Every value here can now be set from the ops
    # console (D-95), and a type-valid value can still be catastrophic: `DB_POOL_SIZE =
    # 500` on the four voice-runtime processes asks Postgres for 2000 backends against
    # the `max_connections = 200` DEPLOYMENT §2a sizes for, so the first restart after
    # the change is the one that cannot open a connection. 32 is double the largest pool
    # in that table (16) and still cannot exhaust the server from one service alone.
    # `ge=1` stays: one connection is slow, not fatal, and a single-connection CLI is a
    # legitimate configuration.
    db_pool_size: int = Field(default=16, ge=1, le=32)

    # 63 is the S3 bucket-name maximum, and the endpoint bound is a URL's practical
    # ceiling. Both are console-settable, so a value the vendor cannot accept has to be
    # refused at the screen rather than at the first recording upload.
    object_store_endpoint: str = Field(max_length=255)
    object_store_bucket: str = Field(max_length=63)

    # Public base URL of the voice-runtime deployable. It is baked into every agent's
    # config at publish time, so it must be the address the ENGINE can reach — not the
    # API's — and changing it means re-publishing every agent.
    #
    # THE SCHEME IS REQUIRED. This string is concatenated into `webhook_url` and handed
    # to the vendor; `hooks.calevate.tech` with no scheme produces a URL the engine
    # silently never calls, and the symptom is every call's lead going missing with no
    # error anywhere on our side. A pattern refuses it at the console instead.
    webhook_base_url: str = Field(
        default="http://localhost:8100", max_length=255, pattern=r"^https?://[^\s]+$"
    )

    # Engine selection is per-environment; `fake` is the default for local work so
    # the whole pipeline runs offline (DEV-SETUP.md §3).
    engine: EngineName = "fake"
    # Bolna webhooks are UNSIGNED (D-31) — there is deliberately no webhook secret.
    # Authenticity = source-IP allowlist + execution-id dedupe, and the
    # List-Executions poller is the guarantee of record (TRD §5).
    bolna_api_key: str | None = None
    #: Cartesia Line control-plane key, sent as `X-API-Key` (D-93). Absent ⇒ the adapter
    #: reports itself unavailable through the one capability selector rather than failing
    #: at the first call, which is the same shape `payment_capability()` uses.
    cartesia_api_key: str | None = None
    #: Cartesia's id for the outbound caller ID. Absent ⇒ outbound calls REFUSE rather
    #: than dial from whatever number the vendor picks: a promotional campaign leaving on
    #: a service-series number is a TCCCPR breach we would discover from a complaint.
    cartesia_from_number_id: str | None = Field(default=None, max_length=128)
    # The engine's egress addresses — comma-separated, literal IPs only. This is the
    # ENTIRE authenticity control for an unsigned engine, and it is a value the VENDOR
    # owns: they can renumber without telling us, and while it is stale every webhook
    # 401s and every call waits for the 10-minute poller. It lives here so rotating it
    # is an environment change and a restart, not a code change and a deploy of the
    # latency-critical service. Not a secret — an allowlist. Parsing fails safe: junk
    # entries are dropped and an empty result falls back to `DEFAULT_BOLNA_SOURCE_IPS`
    # (`parse_source_ip_allowlist` above), because an empty allowlist is an outage.
    #
    # THIS FIELD IS THE SINGLE SOURCE OF TRUTH for who may deliver a Bolna webhook.
    # `apps/api/engine/bolna.py::verify_webhook` used to answer the same question from a
    # module constant of its own, which agreed with this field only until an operator
    # followed the documented recovery path (rotate the env var, restart) — after which
    # the adapter's `WebhookVerdict` and the receiver's verdict disagreed silently, in
    # the one direction nobody re-checks. Both now read this through `bolna_source_ips`.
    # The default is spelled from the same frozenset the fallback uses so the two cannot
    # drift either.
    bolna_webhook_source_ips: str = Field(
        default=",".join(sorted(DEFAULT_BOLNA_SOURCE_IPS)), max_length=1024
    )
    # Bolna quotes cost in USD cents; the adapter converts at capture and STAMPS this
    # rate into usage_events.meta so any ledger row can be re-derived (hard rule 7).
    # A config row, not a live FX call: metering must be reproducible, not current.
    #
    # BOUNDED BECAUSE IT IS MONEY AND IT IS CONSOLE-SETTABLE. `0` is type-valid and
    # makes every Bolna minute cost nothing — the platform bills zero and nobody
    # notices until the month closes — so the floor is EXCLUSIVE. The ceiling is two
    # orders of magnitude above any plausible USD/INR rate: a fat-fingered `8800`
    # would overcharge every client by 100x, and an ops console is exactly where that
    # keystroke happens.
    usd_inr_rate: Decimal = Field(default=Decimal("88.00"), gt=0, le=1000)

    # BYOK models — canonical stack per D-36: Sarvam does STT + LLM + TTS.
    # Gemini is a configurable FALLBACK, not the default.
    sarvam_api_key: str | None = None
    gemini_api_key: str | None = None
    # Embeddings are provider-managed if the D-28 RAG service bundles them;
    # Cohere is only needed if the bake-off selects a store that does not.
    cohere_api_key: str | None = None

    # Two SEPARATE Clerk applications — admin realm and client realm never share
    # session logic (TRD §11).
    clerk_admin_publishable_key: str | None = Field(default=None, max_length=256)
    clerk_admin_secret_key: str | None = None
    clerk_client_publishable_key: str | None = Field(default=None, max_length=256)
    clerk_client_secret_key: str | None = None
    # Custom domain so the flow is ours end to end (D-37); also the JWKS host.
    # 253 is the DNS name limit; a hostname is all this may ever be, because
    # `core/auth.jwks_url` interpolates it into `https://{host}/.well-known/jwks.json`
    # and a value carrying a scheme or a path would build a URL that fetches nothing.
    clerk_frontend_api: str = Field(default="accounts.calevate.tech", max_length=253)
    # Svix signing secret for the user/org mirror webhook (`whsec_...`). Absent means
    # the endpoint FAILS CLOSED — an unverifiable identity feed is worse than none.
    clerk_webhook_secret: str | None = None

    # HMAC material for the audit hash chain (BACKEND-PATTERNS §7). REQUIRED outside
    # `local`: it used to fall back to the constant `local-dev:{app_env}` in EVERY
    # environment, so a prod deploy that forgot it signed its tamper-evident ledger
    # with a key printed in this repository. `apps/api/compliance/audit.py` now refuses
    # to write or verify without it anywhere but `local`, and
    # `runtime_config_missing_keys` reports it at `/healthz/ready`.
    #
    # ROTATING IT NO LONGER STARTS A NEW CHAIN — the previous claim here, and the reason
    # rotation was described as a drill. `verify_chain` walks a KEY RING and each entry
    # is verified under the newest key that reproduces it, so history keeps verifying
    # across a rotation as long as the outgoing key moves to the field below.
    audit_chain_secret: str | None = None

    # The PREVIOUS `AUDIT_CHAIN_SECRET`, kept only so entries signed with it still
    # verify. Never used to sign. Unset is the normal state — the ring always contains
    # the pre-requirement `local-dev:{app_env}` fallback as its oldest generation
    # without any configuration, which is what makes the deploy that introduced this
    # requirement produce zero new breaks.
    #
    # DELIBERATELY NOT LENGTH-CHECKED, unlike the active key. A key that is already in
    # the ledger cannot be made longer retroactively; refusing it would convert a weak
    # historical key into an unverifiable one, which is strictly worse. The floor
    # applies where it can still change an outcome: the key we are about to sign with.
    audit_chain_secret_retired: str | None = None

    # HMAC material for idempotency scope fingerprints (BACKEND-PATTERNS §4). ITS OWN
    # SECRET, not the audit chain's, which is what it used to share.
    #
    # WHY IT IS SPLIT. `scope_key` is a PSEUDONYM — §4 forbids storing raw tenant/user
    # ids in `idempotency_records`, and a keyed hash is only a pseudonym while the key
    # is secret (EDPS/AEPD, "Introduction to the hash function as a personal data
    # pseudonymisation technique", §4: a plain hash over an enumerable identifier space
    # is reversible, and the fix is to enlarge the preimage space with a secret key).
    # That makes it a different PURPOSE from tamper-evidence, and NIST SP 800-57 Part 1
    # Rev. 5 §5.2 asks for one key per purpose.
    #
    # The operational half matters more here. The fingerprint has to be STABLE: change
    # the material and every in-flight `Idempotency-Key` stops matching its stored
    # record, so a client retry re-executes instead of replaying — for
    # `POST /v1/leads/{id}/call` that is a second call placed to a real person. While
    # this shared the audit chain's key, an audit-key rotation silently carried that
    # cost. This slice makes audit rotation a supported operation for the first time, so
    # welding a client-visible side effect to it would have been the wrong moment.
    # Unset is a derived constant under APP_ENV=local ONLY; anywhere else it is refused.
    idempotency_scope_secret: str | None = None

    # HMAC material for D-22 view-as grants (`apps/api/core/impersonation.py`). ITS OWN
    # SECRET, not a subkey of the one above, so that rotating it — which costs at most
    # one grant lifetime of re-minting — is not coupled to the audit chain's rotation,
    # which has to carry its outgoing value forward for history to keep verifying.
    # Unset is a derived constant under APP_ENV=local ONLY; anywhere else an
    # absent value refuses to mint or verify, because a guessable key here is forgeable
    # access to a client's data rather than an unverifiable ledger.
    impersonation_grant_secret: str | None = None

    # Email transport for hot-lead alerts (ROADMAP M1: email first, WhatsApp next).
    # Any SMTP provider works, which keeps the provider a deployment decision rather
    # than a code dependency. Unset in a non-local env = notifications report FAILURE
    # rather than silently pretending (see workers/transport.py).
    smtp_host: str | None = Field(default=None, max_length=253)
    # 1..65535 is the whole legal port space. `0` is type-valid, is what an empty box
    # submits as an integer, and would make every hot-lead alert fail at connect.
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=320)
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    # 320 is the RFC 5321 maximum for an addr-spec (64 local + @ + 255 domain).
    notifications_from: str | None = Field(default=None, max_length=320)

    # WHERE OPERATOR ALERTS GO (OPERATIONS §4; §8's pre-launch gate "alerts firing to
    # Sri's phone"). `apps/api/core/alerting.py` delivers through the SAME transport as
    # hot-lead notifications — one thing to configure, one thing to be broken.
    #
    # Unset means alerts are logged and delivered NOWHERE, which is the right local and
    # test default and is announced at boot (`alert_delivery_unconfigured`) rather than
    # discovered during an incident. Setting it is the pre-launch gate; a phone gets the
    # alert through its mail app until a BSP is chosen and the WhatsApp seam in
    # `apps/workers/whatsapp.py` can carry the second channel §4 also promises.
    alerts_email: str | None = Field(default=None, max_length=320)

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
    whatsapp_provider: str | None = Field(default=None, max_length=64)
    # The approved template's name and language, as registered with the provider. Here
    # rather than in code because re-approval is an operational event, not a deploy.
    # A template name is an identifier at the provider, and a locale is a language tag;
    # neither is free text, and an EMPTY one would send a message naming no template.
    whatsapp_template_hot_lead: str = Field(default="calevate_hot_lead_v1", max_length=128)
    whatsapp_template_locale: str = Field(default="en", max_length=16)

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
    google_sheets_provider: str | None = Field(default=None, max_length=64)

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

    # Meta Lead Ads answer retrieval (SURFACES §2b). Same seam as the two above and for
    # the same reason: `graph` is the only name with an adapter behind it
    # (`apps/api/ingest/graph.py`), any other name resolves to
    # `provider_not_implemented` and refuses to read rather than pretending, and unset
    # means this deployment does not fetch lead answers at all — the receiver still
    # verifies and records every delivery, and says so on the client's own setup card.
    #
    # A STATEMENT ABOUT THE CAPABILITY, never a credential: the tokens below are
    # separate and each lead source still needs its own.
    meta_lead_retriever: str | None = Field(default=None, max_length=64)

    # The Page access tokens the `graph` retriever reads with: a JSON object keyed by
    # LEAD SOURCE id (`inbound_webhooks.id`), `{"<uuid>": "<page-access-token>"}`,
    # injected from the secrets manager at deploy time like every other vendor key
    # (DEV-SETUP §4). Unset with the retriever selected is not a half-configuration: no
    # source holds a credential, so every source reports
    # `meta_page_token_not_configured` and no lead is invented out of metadata.
    #
    # WHY KEYED BY LEAD SOURCE AND NOT BY PAGE ID, which is the obvious choice and the
    # wrong one. A Page id arrives INSIDE a notification, and a notification is signed
    # with the app secret of the tenant it was sent to — so a tenant who names another
    # tenant's Page would have their lead read with the other tenant's token and written
    # into their own CRM. Keying on the lead source id makes that unexpressible: the id
    # is in the callback URL, we minted it, and it already resolves to exactly one
    # tenant. The credential is then also the boundary AT THE VENDOR — a token that
    # cannot read another Page's leads cannot leak them, whatever we ask Meta for. Same
    # shape as the Sheets argument above, one level in.
    #
    # NO KEY MATERIAL IN THE DATABASE (hard rule, SEC-COMP §5) and no reference column
    # either, because there is nothing for one to disambiguate: the reference IS the
    # lead source's own id, which the row already is. A stored copy of a value derived
    # from the primary key is a second thing that can drift — the same argument
    # `ingest/meta.py::verify_token_for` makes for deriving the verify token rather than
    # storing a second secret beside the first.
    #
    # ROTATION AND REVOCATION are operator actions on this one secret, with no database
    # write and no release: replace an entry to rotate, drop it to revoke. A long-lived
    # Page token has no expiry date but IS invalidated by a password change, a revoked
    # permission or an app-review downgrade, so `meta_page_token_invalid` is a refusal
    # the adapter must be able to name — it is not a hypothetical.
    meta_page_access_tokens: str | None = None

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
    # an LLM, and its payload must be redacted (hard rule 6) before it leaves the
    # process. That last clause used to name `observability.redact_trace_payload`, a
    # hand-called hook which has since been DELETED: the redaction now happens
    # automatically in `_RedactingSpanExporter`, on every span leaving the process,
    # because a hook each call site must remember is the one that gets forgotten. So a
    # Langfuse restoration inherits the guarantee only if it exports through that same
    # pipeline; a direct Langfuse SDK client would be a second, UNFILTERED path, which is
    # the exact defect `traces_sample_rate` turned out to be. Weigh that in (b).
    #
    # TO RESTORE POSTHOG: product analytics is a BROWSER concern and never belonged in
    # backend Settings. It restores as `NEXT_PUBLIC_POSTHOG_KEY` in `apps/web`, with a
    # DPDP sub-processor entry and the same field masking the teardown note records for
    # the competitor (docs/evidence/outpero-teardown-aug2026.md §9) — not as a Python
    # config field.
    sentry_dsn: str | None = None
    # Stamped onto every error so a report names the deploy that produced it.
    # CI sets it from the commit sha; unset is fine and reads as 'dev'.
    release_version: str = Field(default="dev", max_length=64)

    # OpenTelemetry (TRD §2). Base URL of an OTLP/HTTP collector — the exporter appends
    # `/v1/traces`. UNSET IS THE LOCAL DEFAULT AND MEANS NO TRACING AT ALL: no SDK
    # import, no middleware, no background exporter thread, so `uv run pytest` and a
    # dev box need nothing running (same contract as an absent SENTRY_DSN).
    otel_exporter_otlp_endpoint: str | None = Field(default=None, max_length=255)
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
    #
    # BOUNDED FOR THE SAME REASON `usd_inr_rate` IS, one surface closer to the client:
    # `0` is type-valid and would price every self-serve minute at nothing, so the
    # runway framing says "unlimited" and the top-up flow charges zero. Exclusive floor.
    # The ceiling is absurd on purpose — nobody sells a minute for ₹10,000 — and its job
    # is to catch a decimal point in the wrong place before it reaches a wallet.
    self_serve_inr_per_min: Decimal = Field(default=Decimal("6.00"), gt=0, le=10_000)

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
    payment_provider: str | None = Field(default=None, max_length=64)
    # WHICH telephony vendor may sell this deployment a phone number (D-05: Exotel, with
    # Vobiz for the 140-series). Config rather than an inference from a credential, for
    # the same reason `payment_provider` is: a key is not a statement that the
    # capability exists. NO ADAPTER EXISTS FOR ANY VALUE — `apps/api/campaigns/
    # provisioning.py` owns the one selector and `PROVISIONING_IMPLEMENTED` is False —
    # so this setting currently decides only WHICH refusal an operator sees. A name
    # outside {exotel, vobiz} resolves to `provider_not_implemented` rather than looking
    # configured.
    number_provider: str | None = Field(default=None, max_length=64)
    # The PUBLIC key id, handed to the browser's checkout. Unset = the top-up intent
    # answers "payments not configured" rather than returning an unusable intent.
    razorpay_key_id: str | None = Field(default=None, max_length=128)
    # The webhook signing secret from their dashboard. Unset means the payment
    # receiver FAILS CLOSED — an unverifiable payment feed credits wallets on
    # anyone's say-so, which is worse than no feed at all.
    razorpay_webhook_secret: str | None = None
    # The PRIVATE half of the key pair, used server-to-server to create orders
    # (`apps/api/billing/payments.py::RazorpayOrders`). Unset = `creates_orders` is False
    # with reason `no_api_secret` and no order is ever created — which is the state of
    # every deployment today. Kept apart from `razorpay_key_id` deliberately: the id goes
    # to a browser and this never does. It needs no `.env.example` line — that file is
    # the 8-key bootstrap set now (D-95), and because the NAME contains `secret`,
    # `platform_config.is_secret_key` classifies it automatically into the encrypted
    # `platform_secrets` path with no allowlist to edit.
    razorpay_key_secret: str | None = None

    # WHO CALEVATE IS ON AN INVOICE (SLICE AL). Rule 46 of the CGST Rules makes the
    # supplier's legal name, registered address and GSTIN mandatory particulars of a tax
    # invoice, and Rule 46(g) makes the HSN/SAC of the supply one too. All four are a
    # FOUNDER DECISION that has not been taken — ROADMAP M0 has no legal entity and
    # therefore no GST registration — so they are config with NO DEFAULT and no
    # placeholder. A hardcoded specimen GSTIN would be the worst possible outcome: an
    # official-looking document that fails validation in the recipient's return months
    # later, and CGST s.32 prohibits an unregistered person from collecting tax at all.
    #
    # NOT SECRETS, and deliberately not treated as such: a GSTIN and a registered address
    # are printed on every invoice we will ever issue and are published on the GST
    # portal. They are here rather than in the database because they describe the
    # DEPLOYMENT's own legal identity, not a tenant's — one entity issues every invoice —
    # and because changing them is a corporate event that should move with the deploy
    # that ships the new letterhead, not a row somebody can edit in a console.
    #
    # UNSET IS A SUPPORTED STATE and is what every environment is in today:
    # `billing/gst.py::SupplierIdentity.is_registered` is False, the document renders as
    # a PROFORMA that names the missing keys, and it refuses the "Tax Invoice" heading
    # rather than printing an invalid one. It does NOT change what the client owes —
    # `invoice.py` argues why a forgotten variable must never silently move money.
    gst_supplier_legal_name: str | None = Field(default=None, max_length=200)
    gst_supplier_address: str | None = Field(default=None, max_length=1000)
    # 15 characters. Its first two digits are the supplier's State and are what decides
    # CGST+SGST vs IGST, so this field is the single source of our place of supply —
    # there is deliberately no separate state setting to drift from it.
    # LENGTH-CAPPED AND DELIBERATELY NOT LENGTH-CHECKED. A GSTIN is exactly 15
    # characters, and an exact `min_length=15` here was WRONG — caught by
    # `invoice_gst_test`, which feeds a 14-character value on purpose. `billing/gst.py`
    # already degrades gracefully on a malformed one: `parse_gstin` treats it as ABSENT,
    # the document renders as a PROFORMA naming the missing key, and nothing about what
    # the client owes moves. Enforcing the exact length in the MODEL converts that
    # designed degradation into a process that will not boot, because `Settings()` is
    # constructed before anything can explain itself. The rule this field settles for
    # every bound added in this wave: a model-level bound exists to cap BLAST RADIUS
    # (what one value can do to the store and to every process that re-reads it), and it
    # must never be stricter than a consumer that already fails gracefully.
    gst_supplier_gstin: str | None = Field(default=None, max_length=32)
    # The Service Accounting Code our supply is classified under. 4 digits up to ₹5
    # crore aggregate turnover, 6 above it (Notification 78/2020-CT). WHICH code an AI
    # voice-agent subscription falls under is the accountant's call, not this repo's.
    # Capped, not checked, for the same reason as the GSTIN above: `_SAC_RE` in
    # `billing/gst.py` is the semantic gate and it degrades to a proforma.
    gst_supply_sac: str | None = Field(default=None, max_length=16)

    # THE KEY THAT OPENS THE CREDENTIAL STORE (PLATFORM-CONFIG §3). Base64 of exactly 32
    # random bytes; `apps/api/core/envelope.py` owns the encoding, the length rule and
    # the refusal, and is the only module that reads these two.
    #
    # A §4 BOOTSTRAP KEY: it can never move into `platform_settings`, because that is
    # the store it unlocks — a database holding both the lock and the key is encryption
    # as theatre. `core/settings.ENV_ONLY_KEYS` enforces that in code; the CI guardrail
    # that enforces it against future edits is §13 phase 6.
    #
    # Unset is a public, deterministic constant under APP_ENV=local ONLY, exactly like
    # the three HMAC secrets above; anywhere else an absent OR SHORT value is one
    # condition — "there is no usable key here" — and every read refuses.
    platform_kek: str | None = None

    # The PREVIOUS `PLATFORM_KEK`, kept only so DEKs wrapped under it still unwrap.
    # NEVER used to wrap, exactly as `audit_chain_secret_retired` is never used to sign
    # (D-86) — one rotation story, reused rather than reinvented. Unset is the normal
    # state. A value here that cannot be decoded is DROPPED with a log line rather than
    # refused: it only ever helps, so a typo in a decommissioned key must not be an
    # outage.
    platform_kek_retired: str | None = None


def bolna_source_ips(settings: Settings) -> frozenset[str]:
    """The addresses this deployment accepts Bolna webhooks from. ONE resolver.

    Both halves of the authenticity decision call THIS — the receiver that answers the
    delivery (`apps/voice-runtime/engine_intake.verify_source`) and the adapter that
    reports the verdict (`apps/api/engine/bolna.BolnaEngine.verify_webhook`) — so a
    widened or narrowed `BOLNA_WEBHOOK_SOURCE_IPS` moves both together or neither.

    Resolved per call rather than snapshotted at construction: `get_engine()` caches one
    adapter instance per process, so a construction-time snapshot would be a second
    thing that can go stale relative to the receiver. Per call is O(1) — `get_settings`
    is `lru_cache`d and so is the parse — which is what keeps it legal on the
    latency-critical path (hard rule 3).
    """
    return parse_source_ip_allowlist(settings.bolna_webhook_source_ips)


__all__ = [
    "DEFAULT_BOLNA_SOURCE_IPS",
    "SELECTABLE_ENGINES",
    "EngineName",
    "Environment",
    "Settings",
    "bolna_source_ips",
    "parse_source_ip_allowlist",
]
