"""The console's values, in every process, without a restart (PLATFORM-CONFIG §6).

`get_settings()` is read on every request in four processes — api, voice-runtime,
workers and the pilot CLI — and **voice-runtime must not pay a database round trip on
its request path** (hard rule 3: ack under 500ms). So the read path here does no IO at
all: it hands back a dict that is already in memory, and everything that touches
Postgres or Redis happens on a background poll.

## The three layers, cheapest first

    read path      core.settings.get_settings()   in-memory, lru_cached, zero IO
    poll (~3s)     Redis GET of one integer       sub-millisecond, no DB connection
    on a change    Postgres SELECT of ~N rows     once per version bump, per process

This is `core/loadshed.py`'s shape — durable truth in Postgres, Redis as the cheap
shared cache, an in-process memo in front of both — reused rather than reinvented,
because two ways to propagate one global fact is how the two end up disagreeing. What
differs is the trigger: load-shed re-reads on a TTL, and this re-reads on a SENTINEL,
because the config payload is 50 rows rather than two booleans and re-reading it every
15 seconds in every process would be a database poll pretending to be a cache.

## The sentinel, and why the DATABASE bumps it

`platform_config_version` holds one integer. Every process remembers which version its
snapshot was built from; a poll compares. Equal — and that is the overwhelmingly common
case — costs one Redis GET and nothing else.

**The migration bumps it with a TRIGGER on `platform_settings`, not the application.**
An application-side bump is correct exactly as long as every writer remembers, and the
writers are not only ours: PLATFORM-CONFIG's own done-when for this phase is "a value
changed in psql reaches all four processes in <10s", and an operator editing a row at
3am is precisely the writer who will not run our bump. A trigger cannot be forgotten,
cannot be bypassed by a second code path, and makes the version a statement ABOUT the
data rather than a claim beside it.

## The propagation arithmetic (target: under 10 seconds)

* the writer bumps the row (trigger) and, after COMMIT, publishes the new integer to
  Redis — so peers usually see it on their very next poll, ≤ `_POLL_INTERVAL_S`;
* if that publish is lost (Redis down, process died between commit and publish), the
  Redis copy expires after `_SENTINEL_TTL_S` and the next poll reads Postgres;
* worst case is therefore `_SENTINEL_TTL_S + _POLL_INTERVAL_S` = 8s, with the normal
  case at 3s. The margin is deliberate: a target met only on the happy path is not met.

## When the store is unreachable

**The last good snapshot keeps serving, and the process alerts.** A config lookup must
never be able to take the phone system down (§6). Two states are told apart because an
operator's next move differs:

* `degraded` — we had a snapshot and cannot refresh it. The values in force are real
  ones, just possibly stale; the risk is that a change made in the console has not
  landed everywhere.
* `never_loaded` — a COLD START that has never reached the store. There is no "last
  good" to serve, so the process runs on `os.environ` + code defaults.

The second is the one that needed a decision, and the decision is: **serve, loudly.**
The alternative — refuse to boot without the store — would make `platform_settings` a
new single point of failure in front of a phone system that has never needed one, and
would do it for a table that is EMPTY on every deployment today. Env plus code defaults
is exactly the configuration every process ran on before this feature existed, the §4
bootstrap set is env-only regardless, and no security posture depends on a store value
(`ENV_ONLY_KEYS` is what guarantees that). So the failure direction is "the platform
runs as it did last release", which is safe, and it is announced with
`platform_config_never_loaded` rather than discovered.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any, get_args

from calevate_shared.config import Settings
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import REDACT_KEYS, get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import (
    ENV_ONLY_KEYS,
    apply_platform_overrides,
    effective_env,
    env_declares,
    env_var_for,
)
from apps.api.db.session import untenanted_session

if TYPE_CHECKING:  # a cycle at runtime, a plain name to the type checker
    from apps.api.ops.secret_service import ResolvedSecrets

log = get_logger(__name__)

#: How often a process asks whether the config changed. See the arithmetic above.
_POLL_INTERVAL_S = 3.0
#: How long the shared sentinel may live in Redis without anyone re-reading Postgres.
#: It is a BACKSTOP, not the mechanism — the writer publishes through on every change —
#: so its only job is bounding staleness when that publish is lost.
_SENTINEL_TTL_S = 5
_SENTINEL_KEY = "calevate:platform_config_version"

#: The version of a database that has never had a config change. Also what a cold start
#: with no store reports, so `version == 0` reads as "nothing from the store yet".
_UNKNOWN_VERSION = 0


# --- what may be managed from the console -------------------------------------
#
# Derived from the `Settings` model itself. There is deliberately NO hand-kept list of
# managed keys: a second list is exactly the drift this repo keeps finding, and it would
# have to be updated by whoever adds a field — which is the person who does not know
# this file exists.

#: `REDACT_KEYS` entries that are about PII IN A LOG PAYLOAD rather than about a
#: credential in a CONFIG FIELD NAME. Subtracted rather than the whole list being
#: re-typed, so extending `REDACT_KEYS` with a new credential pattern extends this too.
#:
#: Each of these would be a false positive here, and two of them are ones we actively
#: want managed: `alerts_email` (where operator alerts go — an operational value, and
#: the one an incident makes you want to change fastest) and `notifications_from`.
_PII_ONLY_REDACT_KEYS: frozenset[str] = frozenset(
    {
        "phone",
        "e164",
        "recipient",
        "transcript",
        "text",
        "body",
        "extraction",
        "payload",
        "email",
    }
)

#: Field-name fragments that mark a value as a CREDENTIAL, and therefore as something
#: `platform_settings` may never hold in plaintext. Those keys are phase 4's business
#: and live encrypted in `platform_secrets`; a plaintext row for one of them is the
#: exact failure mode §1 rejects the single-table design over.
#:
#: The base is `core/logging.REDACT_KEYS` minus the PII-only entries above — the same
#: patterns that decide what must never reach a log line decide what must never reach
#: this table, because both answer one question ("would disclosing this hurt?"). The
#: four additions are the ones a log line does not care about and a plaintext store must:
#:
#:   dsn          `SENTRY_DSN` embeds a project key in a URL.
#:   credential   the naming a future field is likely to use.
#:   private_key  likewise, and it is the one nobody would forgive.
#:   _json        `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON` is a signing key in a JSON blob.
#:   heartbeat    `BACKUP_HEARTBEAT_URL` is a credential and says so in its own comment:
#:                anyone holding it can silence the backup alarm by pinging it. It is
#:                named specifically because nothing about its SHAPE gives it away.
#:
#: A false POSITIVE costs a key that must be set in the environment (annoying); a false
#: NEGATIVE puts an API key in a plaintext table (catastrophic). The patterns are broad
#: on purpose, and the asymmetry is the reason.
_SECRET_NAME_FRAGMENTS: tuple[str, ...] = tuple(
    sorted(
        (set(REDACT_KEYS) - _PII_ONLY_REDACT_KEYS)
        | {"dsn", "credential", "private_key", "_json", "heartbeat"}
    )
)

# --- WHEN A CHANGE ACTUALLY TAKES EFFECT --------------------------------------
#
# `applies` is the most dangerous field the console publishes. A key reported `live`
# that is really snapshotted at process start is a lie that costs an outage: an operator
# changes it, sees no error, believes it took, and the platform keeps the old value
# until something unrelated restarts. §8's rule — "a field that silently does nothing is
# worse than no field" — applies with more force to a field that silently does nothing
# *for six hours*.
#
# WHY IT IS A TABLE AND NOT A DERIVATION. It is a fact about WHERE a value is read, not
# about what it is, and nothing in the type says whether the reader is `get_settings()`
# at the point of use or a constructor that ran at boot. Every attempt to infer it
# statically has the same failure: it guesses `live` for anything it cannot see through,
# and `live` is the answer that costs the outage. So it is enumerated, per key, with the
# reason — and the enumeration is made unrottable in two ways rather than trusted:
#
#   * `describe()` treats a MISSING entry as `UNCLASSIFIED` and marks the field
#     NOT EDITABLE, so a `Settings` field added tomorrow is never offered as `live` by
#     default. The fail-safe direction is "you cannot edit this yet", never "we assume
#     it works";
#   * `scripts/check_config_applies.py` fails CI on any managed field with no entry, any
#     entry naming a field that is no longer managed, and any entry with no reason.
#
# THE FOUR ANSWERS, and why four rather than two:

#: Read through `get_settings()` at the point of use. In force everywhere within one
#: poll interval, no restart.
LIVE = "live"
#: Consumed once, at process start. The value WILL apply after a restart, and does
#: nothing before one.
ON_RESTART = "on_restart"
#: Live for new work, but artefacts already created carry the old value. Neither `live`
#: nor `on_restart`: a restart does not fix it and waiting does not either — something
#: has to be re-published. Without this category the classification cannot be honest,
#: because `webhook_base_url` is in it and is the field most likely to be changed during
#: an incident.
NEEDS_REPUBLISH = "needs_republish"
#: The store can NEVER deliver this value, restart or not — the consumer reads the
#: environment directly, or reads it before the store is reachable. Distinct from
#: `on_restart`, which promises a restart is enough. `editable` is False for these and
#: the write path refuses them by name, because a console that stores a value which can
#: never apply is §8's defect with an extra six-hour delay bolted on.
ENV_ONLY = "env_only"
#: No entry in `FIELD_APPLIES`. Never offered for editing — see above.
UNCLASSIFIED = "unclassified"

APPLIES_VALUES: frozenset[str] = frozenset(
    {LIVE, ON_RESTART, NEEDS_REPUBLISH, ENV_ONLY, UNCLASSIFIED}
)


@dataclass(frozen=True, slots=True)
class AppliesRule:
    """One key's answer to "when does changing this actually do anything?".

    `caveat` is `None` only for `LIVE`, where there is nothing left to say. Every other
    classification carries the sentence the console renders beside the field, because a
    caveat in a runbook reaches nobody at the moment they are typing into the box.
    """

    applies: str
    caveat: str | None = None


#: EVERY managed key, classified. The guardrail fails if this is not exhaustive.
#:
#: The `LIVE` entries are the ones that were checked rather than assumed: each names a
#: call site that reads `get_settings()` per use. The other three categories are where
#: the audit found the console lying.
FIELD_APPLIES: dict[str, AppliesRule] = {
    # ---- env_only: the store cannot deliver these, and a restart does not help -----
    "db_pool_size": AppliesRule(
        ENV_ONLY,
        "the SQLAlchemy engine is built from a bare `Settings()` (db/session.py), which "
        "reads the environment only — and it is built BEFORE the store can be read, "
        "because reading the store needs a connection from it. A value stored here can "
        "never apply, restart or not: set DB_POOL_SIZE in the deployment's environment.",
    ),
    # ---- on_restart: consumed once, at process start -------------------------------
    "otel_exporter_otlp_endpoint": AppliesRule(
        ON_RESTART,
        "tracing is initialised once at boot (`init_tracing` returns early when a "
        "provider already exists) — a second provider would double every span",
    ),
    "otel_traces_sample_ratio": AppliesRule(
        ON_RESTART,
        "the sampler is fixed when the tracer provider is built, for the same reason",
    ),
    "release_version": AppliesRule(
        ON_RESTART,
        "it is stamped into the OTel resource and handed to `sentry_sdk.init` at boot, "
        "and into the `service_start` log line — nothing reads it again afterwards",
    ),
    "clerk_admin_publishable_key": AppliesRule(
        ON_RESTART,
        "the JWKS URL it encodes is baked into a `PyJWKClient` the first time a token of "
        "this realm is verified (`core/auth._jwk_clients`), and that client is held for "
        "the life of the process",
    ),
    "clerk_client_publishable_key": AppliesRule(
        ON_RESTART, "same as the admin key: the realm's `PyJWKClient` is built once"
    ),
    "clerk_frontend_api": AppliesRule(
        ON_RESTART,
        "the fallback JWKS host, and it is read at the same moment the realm's "
        "`PyJWKClient` is constructed — once per process",
    ),
    "usd_inr_rate": AppliesRule(
        ON_RESTART,
        "the Bolna adapter captures it as `_fx_rate` when `get_engine()` builds it, and "
        "that instance is cached for the life of the process — so a new rate does NOT "
        "reach the cost conversion stamped into usage_events until every process "
        "restarts. Until then, minutes are still costed at the old rate.",
    ),
    "cartesia_from_number_id": AppliesRule(
        ON_RESTART,
        "the Cartesia adapter captures it at construction and `get_engine()` caches the "
        "adapter for the life of the process",
    ),
    # ---- needs_republish: live for new work, stale on what already exists ----------
    "webhook_base_url": AppliesRule(
        NEEDS_REPUBLISH,
        "new agent publishes use it immediately, but every agent already published "
        "carries the OLD URL in its engine-side config — they must be re-published or "
        "their webhooks keep going to the previous address",
    ),
    "engine": AppliesRule(
        NEEDS_REPUBLISH,
        "`get_engine()` switches immediately, but every LIVE agent was created on the "
        "previous vendor and its `engine_agent_ref` means nothing to the new one — and "
        "its webhook URL still ends in the old engine's name. Every agent must be "
        "re-published before the switch is real. Switching BACK also returns the "
        "adapter instance cached earlier in this process, with the credentials and FX "
        "rate it was built with.",
    ),
    # ---- live: read through get_settings() at the point of use ---------------------
    "object_store_endpoint": AppliesRule(LIVE),  # workers/storage._client(), per call
    "object_store_bucket": AppliesRule(LIVE),  # workers/storage, per call
    "bolna_webhook_source_ips": AppliesRule(LIVE),  # bolna_source_ips(get_settings())
    "smtp_host": AppliesRule(LIVE),  # workers/transport.get_transport(), per send
    "smtp_port": AppliesRule(LIVE),
    "smtp_username": AppliesRule(LIVE),
    "smtp_use_tls": AppliesRule(LIVE),
    "notifications_from": AppliesRule(LIVE),
    "alerts_email": AppliesRule(LIVE),  # core/alerting, per alert
    "whatsapp_enabled": AppliesRule(LIVE),  # workers/whatsapp, per send
    "whatsapp_provider": AppliesRule(LIVE),
    "whatsapp_template_hot_lead": AppliesRule(LIVE),
    "whatsapp_template_locale": AppliesRule(LIVE),
    "google_sheets_provider": AppliesRule(LIVE),  # workers/sheets_sync, per delivery
    "meta_lead_retriever": AppliesRule(LIVE),  # ingest/meta, per retrieval
    "inbound_reserve_ratio": AppliesRule(
        LIVE,
        "read once per dispatch tick, before the loop — a tick that has started keeps "
        "the pool it computed, and the next one (≤30s later) uses the new value",
    ),
    "self_serve_inr_per_min": AppliesRule(LIVE),  # billing/service, per quote
    "self_serve_signup_enabled": AppliesRule(LIVE),  # tenancy/signup, per request
    "payment_provider": AppliesRule(LIVE),  # billing/payments.payment_capability()
    "number_provider": AppliesRule(LIVE),  # campaigns/provisioning, per call
    "razorpay_key_id": AppliesRule(LIVE),  # billing/payments, per capability read
    "gst_supplier_legal_name": AppliesRule(LIVE),  # billing/gst.supplier_identity()
    "gst_supplier_address": AppliesRule(LIVE),
    "gst_supplier_gstin": AppliesRule(LIVE),
    "gst_supply_sac": AppliesRule(LIVE),
    # The GCP project Vertex AI bills and runs in (D-127). `workers/extraction`
    # re-reads it per assist. It is plain config and not a credential on purpose — a
    # project id is in every URL the client builds and is the value an operator gets
    # wrong first, so it belongs where they can SEE it. The REGION is deliberately not
    # here and can never be: `calevate_shared.engine.VERTEX_LOCATION` is a `Final`
    # constant and `scripts/check_model_residency.py` fails the build on any `Settings`
    # field whose name says region, location, residency, vertex or aiplatform.
    "gcp_project_id": AppliesRule(LIVE),
    # ---- CREDENTIALS. Same question, higher stakes -------------------------------
    #
    # The Secrets panel implies exactly what the config panel implies — set it and it is
    # in force in seconds — and for two of these that was false. A rotated Bolna key that
    # never reaches the running adapter presents as "the vendor is rejecting our key",
    # which sends an operator to the vendor's dashboard rather than to a restart. They
    # are classified here, in the SAME table, because there is one question and it should
    # not have two answers in two places.
    "bolna_api_key": AppliesRule(
        ON_RESTART,
        "the Bolna adapter captures it when `get_engine()` builds it, and that instance "
        "is cached for the life of the process — a rotation here does NOT reach the "
        "adapter placing calls until every process restarts",
    ),
    "cartesia_api_key": AppliesRule(
        ON_RESTART, "captured at construction by the cached Cartesia adapter, as above"
    ),
    "sentry_dsn": AppliesRule(
        ON_RESTART,
        "`sentry_sdk.init` runs once at boot (`init_observability`); a new DSN does not "
        "redirect errors until the process restarts",
    ),
    "clerk_admin_secret_key": AppliesRule(
        ON_RESTART,
        "read when the realm's `PyJWKClient` is built, once per process — and under "
        "APP_ENV=local its PRESENCE is what disables dev tokens, so a process that "
        "started without it keeps accepting them until it restarts",
    ),
    "clerk_client_secret_key": AppliesRule(ON_RESTART, "same as the admin secret"),
    # Read at the point of use, per call or per request.
    "sarvam_api_key": AppliesRule(LIVE),  # workers/extraction.get_extractor(), per job
    # D-127 disqualified the AI Studio Developer API this key opens, so nothing sends it
    # anywhere. It is still `live` and that is not a fiction: `assist_capability()` reads
    # it per call, and its presence is what turns the generic "no credential" refusal into
    # the one an operator who installed it needs. Setting it therefore still changes what
    # the platform does within one poll interval — it changes the SENTENCE, not the
    # endpoint.
    "gemini_api_key": AppliesRule(LIVE),
    # The Vertex service-account key (D-127). `live`, and unlike `bolna_api_key` that was
    # checked rather than assumed: `workers/extraction.vertex_credentials()` parses it
    # per assist and `VertexGeminiExtractor` is constructed per assist, so a new key
    # reaches the next request.
    #
    # ROTATING WITHIN ONE ACCOUNT USED TO BE THE EXCEPTION and no longer is. The bearer
    # is cached in `google_oauth` on `(client_email, private_key_id, scope)`; when that
    # tuple was `(client_email, scope)` a new key on the SAME service-account address —
    # which is what Google's own console mints — kept the retired key's token in flight
    # for up to an hour, and this row said so instead of fixing it. `live` now means
    # live: the next assist misses the cache and signs with the new key. The one residue
    # is a key file with no `private_key_id`, which Google does not produce.
    "gcp_service_account_json": AppliesRule(LIVE),
    "cohere_api_key": AppliesRule(LIVE),
    "clerk_webhook_secret": AppliesRule(LIVE),
    "audit_chain_secret": AppliesRule(LIVE),  # compliance/audit._active_key(), per write
    "audit_chain_secret_retired": AppliesRule(LIVE),
    "idempotency_scope_secret": AppliesRule(LIVE),
    "impersonation_grant_secret": AppliesRule(LIVE),  # core/impersonation, per mint
    "smtp_password": AppliesRule(LIVE),  # workers/transport.get_transport(), per send
    "backup_heartbeat_url": AppliesRule(LIVE),
    "google_sheets_service_account_json": AppliesRule(LIVE),
    "meta_page_access_tokens": AppliesRule(LIVE),
    "razorpay_webhook_secret": AppliesRule(LIVE),
    "razorpay_key_secret": AppliesRule(LIVE),
}

#: The classification a field with no entry gets. Fail-safe by construction.
_UNCLASSIFIED_RULE = AppliesRule(
    UNCLASSIFIED,
    "this build does not record when a change to this key takes effect, so the console "
    "will not offer to change it. Classify it in core/platform_config.FIELD_APPLIES "
    "(scripts/check_config_applies.py fails CI until you do).",
)


def applies_rule(key: str) -> AppliesRule:
    """When a change to this key takes effect, and what the operator must do about it."""
    return FIELD_APPLIES.get(key, _UNCLASSIFIED_RULE)


# --- the per-key concurrency token --------------------------------------------
#
# WHY PER KEY AND NOT THE FLEET SENTINEL. `platform_config_version` already exists and
# is tempting: one integer, already bumped by the trigger, already read by every
# process. It is the wrong granularity for a conditional write, and choosing it would
# make the feature worse than not having it. The console shows 36 fields; two operators
# working on different fields at the same time is the NORMAL case, not the race. With a
# fleet-wide token, operator B's unrelated edit to `alerts_email` invalidates operator
# A's in-flight edit to `usd_inr_rate` — a conflict that is not one. False conflicts are
# not a small cost: they are how people learn to hit retry without reading, which turns
# a 412 back into last-write-wins with extra steps. The token has to be scoped to the
# thing being protected, which is the row.
#
# The token is a strong ETag over the row's `revision`, and `"0"` means "no row". That
# makes CREATE conditional too, with the same header and no second mechanism: two
# operators who both see an unset key both send `If-Match: "0"`, and exactly one wins.
_ETAG_ABSENT = 0


def etag_for(revision: int) -> str:
    """The ETag for a row at this revision. `"0"` is the ETag of an absent row.

    RFC 9110 §8.8.3 shape: an opaque, quoted entity-tag. Opaque is the operative word —
    a caller compares it and sends it back, and nothing outside this module may parse a
    meaning out of it.
    """
    return f'"{revision}"'


def parse_etag(value: str) -> int | None:
    """An `If-Match` value back to a revision, or `None` if it is not one of ours.

    Deliberately strict: no `*`, no weak (`W/`) tags, no comma lists. RFC 9110 permits
    all three, and every one of them would weaken this. `If-Match: *` means "any current
    representation" — for a config write that is exactly the unconditional write this
    exists to refuse. A weak tag is defined as semantic equivalence, which is a claim
    nobody can make about two different values of an FX rate. A list makes "which one
    did I actually overwrite" unanswerable in the audit row.
    """
    token = value.strip()
    if len(token) < 3 or not token.startswith('"') or not token.endswith('"'):
        return None
    digits = token[1:-1]
    return int(digits) if digits.isdigit() else None


#: How a value is rendered and edited in the console. Derived from the annotation, never
#: hand-mapped: a field whose type changes changes its editor with it.
ValueKind = str


@dataclass(frozen=True, slots=True)
class ConfigField:
    """One managed key, as the console needs to see it.

    `source` is the load-bearing field. §4's resolution order puts the environment above
    the store, so a key set in `.env` CANNOT be changed from the console — and a form
    that offered to change it anyway would be "a field that silently does nothing", which
    §8 calls worse than no field. `editable` is computed from it here, once, rather than
    re-derived by the console.
    """

    key: str
    env_var: str
    #: The value in force in THIS process, in its JSON form.
    value: Any
    #: `env` | `db` | `default` — where that value came from.
    source: str
    #: The code default, so the console can say what reverting would restore. `None`
    #: when there is none — read `has_default` to tell that apart from a default that
    #: genuinely IS null, which most optional fields here have.
    default: Any
    #: False for a REQUIRED field (`object_store_endpoint`). Such a field cannot be
    #: reverted — there is nothing to revert to — and in practice is always `env`
    #: sourced, because a process whose environment lacks it cannot construct `Settings`
    #: and therefore cannot boot.
    has_default: bool
    kind: ValueKind
    #: The allowed values, for a `Literal` field. Empty for everything else.
    options: tuple[str, ...]
    editable: bool
    #: `live` | `on_restart` | `needs_republish` | `env_only` | `unclassified` — when a
    #: change to this key actually takes effect. See `FIELD_APPLIES`.
    applies: str
    #: What the operator still has to do after changing it, or `None`. Carries the
    #: reason for every classification except `live`, where there is nothing left to
    #: say. Rendered beside the field, because a caveat in a runbook reaches nobody at
    #: the moment they are typing into the box.
    caveat: str | None
    #: The concurrency token for THIS key: the value a conditional write must send back
    #: in `If-Match`. `"0"` when no row is stored, which is a real state a write can be
    #: conditional on ("I believe nobody has set this") rather than an absence.
    etag: str
    #: Who last set it in the store, and when. Both `None` unless `source == "db"`.
    updated_by: str | None
    updated_at: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """What the store contributed, and how much that answer can be trusted."""

    version: int
    overrides: Mapping[str, Any]
    #: `monotonic()` of the last SUCCESSFUL store read; `None` on a cold start that has
    #: never reached it. The two are not the same state — see the module docstring.
    loaded_at: float | None
    #: True when the last refresh attempt failed. `loaded_at is not None and degraded`
    #: is "stale but real"; `loaded_at is None` is "never loaded".
    degraded: bool


_snapshot = ConfigSnapshot(version=_UNKNOWN_VERSION, overrides={}, loaded_at=None, degraded=False)
# One rebuild at a time per process. Not a distributed lock and not trying to be: a
# stampede across processes would be N small SELECTs on a version bump, which is not a
# stampede. What this prevents is the in-process version — the poll loop and a
# write-through refresh arriving together and both rebuilding, which would double the
# work and could install the OLDER of two reads last.
_refresh_lock = asyncio.Lock()
_refresher: asyncio.Task[None] | None = None


def snapshot() -> ConfigSnapshot:
    """The current snapshot. Synchronous, zero IO — safe on any request path."""
    return _snapshot


# --- typing a jsonb value back onto a Settings field --------------------------


def managed_fields() -> tuple[str, ...]:
    """Every `Settings` field the console may manage, computed from the model.

    Three exclusions, each structural rather than listed:

    1. **§4's bootstrap set** (`ENV_ONLY_KEYS`) — the keys whose relocation would be a
       security-posture inversion.
    2. **Anything whose NAME says credential** — see `_SECRET_NAME_FRAGMENTS`. These are
       phase 4's business and live encrypted in `platform_secrets`; a plaintext row for
       one of them is the failure mode §1 rejects the single-table design over.
    3. Nothing else. Every remaining field is a candidate, which is what makes ".env goes
       from ~54 keys to 6" a checkable claim rather than an aspiration.
    """
    return tuple(
        name
        for name in Settings.model_fields
        if name not in ENV_ONLY_KEYS and not is_secret_key(name)
    )


def is_secret_key(name: str) -> bool:
    """Does this field's NAME mark it as a credential?

    Substring matching, like the log redactor it borrows from: `clerk_admin_secret_key`,
    `smtp_password` and `meta_page_access_tokens` all have to be caught by a rule nobody
    maintains per field. A false POSITIVE here costs a key that has to be set in the
    environment (annoying); a false NEGATIVE puts an API key in a plaintext table
    (catastrophic). The asymmetry is why the patterns are deliberately broad.
    """
    lowered = name.lower()
    return any(fragment in lowered for fragment in _SECRET_NAME_FRAGMENTS)


def _adapter(field: str) -> TypeAdapter[Any]:
    """A validator for ONE `Settings` field, built from that field's own definition.

    THIS IS THE ANSWER TO "how do you type a jsonb value back onto a Pydantic field
    without a second copy of the field list". `FieldInfo.rebuild_annotation()` returns
    `Annotated[<annotation>, *<constraints>]` — the annotation AND the `Field(ge=…, le=…)`
    metadata, which is the half a bare `TypeAdapter(field.annotation)` would silently
    drop, so `otel_traces_sample_ratio = 5.0` would be stored and then rejected at the
    next boot. That is precisely the failure §7 says must be refused at the boundary.

    Not cached: `TypeAdapter` construction is cheap, this runs on writes and on snapshot
    rebuilds rather than per request, and a cache keyed on a field name would go stale
    against a reloaded model in exactly the tests that matter.

    WHAT THIS DOES NOT COVER, stated because a validator that implies more than it checks
    is worse than none: a cross-field `@model_validator` on `Settings` would not run
    here. There are none today. If one is added, this has to become a whole-model
    validation — and `platform_config_test` pins the field count so that adding one is
    visible.
    """
    return TypeAdapter(Settings.model_fields[field].rebuild_annotation())


def validate_value(field: str, raw: Any) -> Any:
    """Validate a candidate against the `Settings` model and return its JSON form.

    Returns what should be STORED: `dump_python(mode="json")` of the validated value, so
    a `Decimal` lands in `jsonb` as the string `"88.50"` rather than as a JSON double
    that is not 88.50 (hard rule 7). Reading it back through the same adapter recovers
    the `Decimal` exactly.

    Raises `ValidationError` — the caller turns it into problem+json with the field's own
    message, because "engine must be one of fake, bolna, cartesia" is a sentence an
    operator can act on and "invalid value" is not.
    """
    adapter = _adapter(field)
    return adapter.dump_python(adapter.validate_python(raw), mode="json")


def _typed(field: str, stored: Any) -> Any:
    """A stored JSON value as the Python value `Settings` expects, or `None` if it no
    longer validates (a row written by an older build against a field that has since
    narrowed)."""
    try:
        return _adapter(field).validate_python(stored)
    except ValidationError:
        return None


def typed_strict(field: str, stored: Any) -> Any:
    """Like `typed_value`, but a value that does not validate RAISES.

    The write path needs the two cases apart. `typed_value` folds "this row no longer
    parses" into `None`, which is the right answer on a background refresh (drop the row,
    keep serving) and the wrong one when deciding whether an incoming value is ALREADY
    the stored one: a broken row would compare equal to an incoming `null` and the write
    that was meant to repair it would be reported as a no-op.
    """
    return _adapter(field).validate_python(stored)


def typed_value(field: str, stored: Any) -> Any:
    """The public spelling of `_typed`, for a caller that has just validated a write.

    Same function, exported because the write path needs to project its own change onto
    a `Settings` copy before its transaction commits, and reaching into a private name
    from another module is how two definitions of "what does this jsonb mean" appear.
    """
    return _typed(field, stored)


def project(overrides: Mapping[str, Any]) -> tuple[Settings, ConfigSnapshot]:
    """What this process WOULD be running with exactly these overrides in force.

    Exists for one caller and one moment: a config write renders its response BEFORE the
    request's transaction commits, so re-reading the snapshot would report the value the
    operator has just replaced. Projecting is honest — this is the configuration one
    commit from now — and it keeps the write path from having to reproduce `describe`'s
    source logic in a second place.

    It changes NO module state. The real snapshot moves when the refresh does.
    """
    base = Settings()
    effective = base.model_copy(update=dict(overrides)) if overrides else base
    return effective, replace(snapshot(), overrides=dict(overrides))


def _is_decimal(field: str) -> bool:
    """Is this field money? — asked of the ANNOTATION, never of the JSON schema.

    THIS USED TO BE A HEURISTIC AND THE HEURISTIC WAS WRONG. It read "string type with a
    `pattern` and no `date-time` format" as `Decimal`, which is true of `Decimal`'s
    serialization schema and equally true of ANY string field carrying a
    `Field(pattern=…)`. The first such field — `webhook_base_url`, whose pattern now
    requires an `http(s)://` scheme — rendered in the console as a money editor. The
    right question is what the field IS, and the annotation answers it exactly.

    `Decimal | None` is unwrapped because an optional money field is still money.
    """
    annotation = Settings.model_fields[field].annotation
    return Decimal in {annotation, *get_args(annotation)}


def _kind_of(field: str) -> tuple[ValueKind, tuple[str, ...]]:
    """How the console should render this field, from its annotation.

    Derived rather than declared for the same reason `managed_fields` is: a per-field
    editor table is a second list, and the first field somebody adds without touching it
    renders as a text box that stores a string into an integer.
    """
    # Money first, and from the type: it must stay a string end to end (hard rule 7),
    # so it is its own kind rather than a number the browser could round.
    if _is_decimal(field):
        return "decimal", ()
    schema = _adapter(field).json_schema(mode="serialization")
    # `str | None` produces an anyOf; the interesting half is the non-null branch.
    variants = [v for v in schema.get("anyOf", [schema]) if v.get("type") != "null"]
    head = variants[0] if variants else schema
    if "enum" in head:
        return "enum", tuple(str(v) for v in head["enum"])
    return str(head.get("type", "string")), ()


# --- reading the store --------------------------------------------------------


async def _read_version() -> int:
    async with untenanted_session() as session:
        row = (
            await session.execute(text("SELECT version FROM platform_config_version WHERE id"))
        ).first()
    # No row = a database whose migration seeded nothing, which is a fresh install, not
    # an emergency: the settings table is empty too, so the honest version is "nothing".
    return int(row[0]) if row is not None else _UNKNOWN_VERSION


async def _read_rows() -> dict[str, Any]:
    async with untenanted_session() as session:
        rows = (await session.execute(text("SELECT key, value FROM platform_settings"))).all()
    return {str(key): value for key, value in rows}


async def _read_secrets() -> ResolvedSecrets:
    """Decrypt the current version of every stored credential, for this process.

    A LOCAL import, and deliberately: `ops.secret_service` imports this module for
    `is_secret_key`, so a module-level import here would be a cycle. Keeping the
    dependency one-way at module level and reaching down inside the one function that
    needs it is the same judgement `apps/api/main.py` makes about its routers — and it
    means a process that never refreshes never imports the crypto path at all.
    """
    from apps.api.ops.secret_service import resolve_secrets

    async with untenanted_session() as session:
        return await resolve_secrets(session)


async def _sentinel() -> int:
    """The current config version, from Redis when it is there and Postgres when it is not.

    Redis is a COST optimisation, never the truth: a miss, a flush or an outage costs one
    small Postgres read and changes no answer. That ordering is what makes a Redis
    incident invisible to config propagation instead of freezing it.
    """
    try:
        cached = await get_redis().get(_SENTINEL_KEY)
        if cached is not None:
            return int(cached)
    except Exception:
        log.warning("platform_config_sentinel_cache_unavailable")
    version = await _read_version()
    await publish_version(version)
    return version


async def publish_version(version: int) -> None:
    """Put the version in Redis with an expiry. Best effort, always expiring.

    Every write of this key carries a TTL — the same rule `core/loadshed` learned the
    hard way: a cached value with no expiry, plus one lost invalidation, is a stale
    answer that outlives the incident that caused it.
    """
    try:
        await get_redis().set(_SENTINEL_KEY, str(version), ex=_SENTINEL_TTL_S)
    except Exception:
        log.warning("platform_config_sentinel_publish_failed")


def _resolve(rows: Mapping[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """Store rows → the override layer, applying §4's resolution order.

    `os.environ` → `platform_settings` → code default. The environment winning is
    implemented HERE, by not offering the key at all, rather than by the settings layer
    preferring one source over another: a value that is never offered cannot be applied
    by a future caller who did not read this comment.

    Rows that no longer belong are dropped with a log line rather than raising: this runs
    on a background refresh in every process, and a single bad row must not be able to
    stop a fleet from picking up the good ones.
    """
    resolved: dict[str, Any] = {}
    managed = set(managed_fields())
    for key, stored in rows.items():
        if key not in managed:
            # A field that was renamed or removed, or a key somebody inserted by hand
            # that the model has never had. Loud, and skipped.
            log.warning("platform_config_row_unmanaged", extra={"config_key": key})
            continue
        if env_declares(key, environ):
            # The escape hatch doing its job (§4): the environment wins, and the console
            # renders this key read-only with that as the reason.
            continue
        value = _typed(key, stored)
        if value is None and stored is not None:
            log.warning("platform_config_row_invalid", extra={"config_key": key})
            continue
        resolved[key] = value
    return resolved


async def refresh(*, force: bool = False) -> ConfigSnapshot:
    """Poll the sentinel and, if it moved, rebuild the snapshot. Safe to call anywhere.

    Never raises. Every caller is either a background loop or a post-write write-through,
    and both have the same correct behaviour on failure: keep the last good snapshot and
    make some noise.
    """
    global _snapshot
    async with _refresh_lock:
        try:
            version = await _sentinel()
            # Double-checked inside the lock: a caller that queued behind a rebuild for
            # the same version has nothing to do.
            if not force and version == _snapshot.version and _snapshot.loaded_at is not None:
                if _snapshot.degraded:
                    _snapshot = replace(_snapshot, degraded=False)
                return _snapshot
            rows = await _read_rows()
            secrets = await _read_secrets()
        except Exception as exc:
            _snapshot = replace(_snapshot, degraded=True)
            if _snapshot.loaded_at is None:
                # COLD START WITH NO SNAPSHOT — the case the module docstring decides.
                # The process serves env + code defaults and says so; it does not refuse
                # to run, and it does not pretend the store was empty.
                alert(
                    "CORE_LOGIC",
                    "platform_config_never_loaded",
                    detail=(
                        "This process has never read platform_settings, so it is running "
                        "on environment variables and code defaults. Console changes are "
                        "NOT in force here."
                    ),
                    reason=type(exc).__name__,
                )
            else:
                alert(
                    "CORE_LOGIC",
                    "platform_config_stale",
                    detail=(
                        "platform_settings could not be re-read; the last known values "
                        "are still in force. A console change may not have propagated."
                    ),
                    reason=type(exc).__name__,
                )
            return _snapshot

        overrides = _resolve(rows, effective_env())
        # SECRETS RIDE THE SAME SENTINEL AND THE SAME LAYER. §6 proposed resolving them
        # lazily on a shorter TTL of their own; one mechanism is strictly better here —
        # the sentinel is FASTER than any TTL (a rotation propagates in ≤8s rather than
        # in a TTL's worth of luck), it is one thing to reason about rather than two, and
        # a rotation is precisely the change that must not wait. `_read_secrets` already
        # applied §4's precedence, so a key the environment declares never appears.
        #
        # `overrides` now holds live credentials. It is applied to `Settings` and dropped;
        # nothing logs it, nothing serializes it, and `ConfigFieldOut` cannot carry one
        # because `managed_fields()` excludes every credential-shaped key by name.
        overrides.update(secrets.values)
        if secrets.unreadable:
            # A row exists and no configured KEK opens it. The platform keeps running on
            # whatever the environment or the previous snapshot gave it — but an operator
            # has to know, because the symptom otherwise presents as "the vendor is
            # rejecting our key" and sends them to the wrong system entirely.
            alert(
                "CORE_LOGIC",
                "platform_secret_unreadable",
                detail=(
                    "Stored credentials could not be decrypted with this deployment's "
                    "PLATFORM_KEK. Put the outgoing key in PLATFORM_KEK_RETIRED if this "
                    "follows a rotation."
                ),
                keys=",".join(secrets.unreadable),
            )
        apply_platform_overrides(overrides)
        _snapshot = ConfigSnapshot(
            version=version,
            overrides=overrides,
            loaded_at=time.monotonic(),
            degraded=False,
        )
        log.info(
            "platform_config_loaded",
            extra={"config_version": version, "override_count": len(overrides)},
        )
        return _snapshot


async def _poll_forever() -> None:
    # Refresh FIRST, then sleep: a process that has just started is the one most likely
    # to be running on defaults, and making it wait a full interval before its first
    # read would put every deploy through `_POLL_INTERVAL_S` of stale config for no
    # reason. `refresh` never raises, so this loop cannot die.
    while True:
        await refresh()
        await asyncio.sleep(_POLL_INTERVAL_S)


def start_config_refresher() -> None:
    """Begin polling in this process. Idempotent — call it from any lifespan, once or ten
    times.

    THIS IS THE WHOLE ADOPTION SURFACE. A deployable that calls it picks up console
    changes within `_POLL_INTERVAL_S`; one that does not runs on env + defaults, exactly
    as it does today. That is what keeps voice-runtime's adoption a one-line change
    (hard rule 3 forbids putting anything else on its request path) and what lets the
    pilot CLI opt in without inheriting a background task it does not want.

    The first refresh happens INSIDE the loop rather than being awaited here: this is
    called during app startup, and blocking the boot of the latency-critical service on
    a database read is the opposite of the fail-safe direction chosen above. The task
    reference is held in a module global, so it cannot be garbage-collected mid-flight.
    """
    global _refresher
    if _refresher is not None and not _refresher.done():
        return
    _refresher = asyncio.get_event_loop().create_task(_poll_forever())


async def stop_config_refresher() -> None:
    """Cancel the poll. For shutdown and for tests that must not leak a task."""
    global _refresher
    if _refresher is None:
        return
    _refresher.cancel()
    with suppress(asyncio.CancelledError):
        await _refresher
    _refresher = None


def reset_for_test() -> None:
    """Drop the snapshot and the override layer. Test seam, named as one."""
    global _snapshot
    _snapshot = ConfigSnapshot(
        version=_UNKNOWN_VERSION, overrides={}, loaded_at=None, degraded=False
    )
    apply_platform_overrides({})


# --- the console's view -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredRow:
    """One `platform_settings` row's provenance, as the console shows it."""

    updated_by: str | None
    updated_at: str | None
    note: str | None
    #: The row's per-key revision, which is what an `If-Match` is compared against.
    #: See the migration for why it is a global sequence rather than a per-row counter.
    revision: int = 0


def describe(
    settings: Settings,
    *,
    rows: Mapping[str, StoredRow] | None = None,
    snap: ConfigSnapshot | None = None,
) -> list[ConfigField]:
    """Every managed key with its value, its SOURCE and whether it can be edited.

    The source is computed from the same two facts the RESOLUTION uses — does the
    environment declare it, and did the store contribute it — so the console can never
    be told a key is editable while the layer is refusing to apply it. That symmetry is
    the whole point of §8's read-only-with-the-reason rule.

    `value` is read off the `Settings` object the caller passes rather than recomputed
    from the layers, so what the console displays is literally what this process is
    using. A key whose row exists but whose value failed re-validation therefore shows
    its EFFECTIVE value (the env/default one) with `source: "default"` — which is the
    truth, and is what an operator needs to see when a row has gone bad.

    `rows` carries provenance and is optional: the ops route passes it (it has a
    session), and a caller that only wants values and sources need not open one.
    """
    current = snap or snapshot()
    environ = effective_env()
    provenance = rows or {}
    fields: list[ConfigField] = []
    for key in managed_fields():
        info = Settings.model_fields[key]
        adapter = _adapter(key)
        from_env = env_declares(key, environ)
        source = "env" if from_env else "db" if key in current.overrides else "default"
        # A REQUIRED field has no code default to fall back to, and `PydanticUndefined`
        # is not a value that can be serialized or shown. It reports `None`, and
        # `has_default` is what the console and the revert route read instead of
        # guessing from a null — `null` is a legitimate default for every optional
        # field here, so the two are not the same fact.
        default = None if info.is_required() else info.get_default(call_default_factory=True)
        kind, options = _kind_of(key)
        # Provenance is read for any key that HAS a row, not only for `source == "db"`:
        # an env-shadowed key or one whose stored value failed re-validation still has a
        # row, and its `etag` is what a conditional write has to match. Reporting `"0"`
        # for a key that does have a row would make every write to it fail forever.
        stored = provenance.get(key)
        rule = applies_rule(key)
        fields.append(
            ConfigField(
                key=key,
                env_var=env_var_for(key),
                value=adapter.dump_python(getattr(settings, key), mode="json"),
                source=source,
                has_default=not info.is_required(),
                default=(None if default is None else adapter.dump_python(default, mode="json")),
                kind=kind,
                options=options,
                # Three independent reasons a field cannot be edited here, and the
                # console renders the reason from `applies`/`caveat`: the environment
                # already decides it, the store could never deliver it, or this build
                # does not know when a change would take effect.
                editable=not from_env and rule.applies not in {ENV_ONLY, UNCLASSIFIED},
                applies=rule.applies,
                caveat=rule.caveat,
                etag=etag_for(stored.revision if stored else 0),
                updated_by=stored.updated_by if stored and source == "db" else None,
                updated_at=stored.updated_at if stored and source == "db" else None,
                note=stored.note if stored and source == "db" else None,
            )
        )
    return fields


__all__ = [
    "APPLIES_VALUES",
    "ENV_ONLY",
    "FIELD_APPLIES",
    "LIVE",
    "NEEDS_REPUBLISH",
    "ON_RESTART",
    "UNCLASSIFIED",
    "AppliesRule",
    "ConfigField",
    "ConfigSnapshot",
    "StoredRow",
    "applies_rule",
    "describe",
    "etag_for",
    "is_secret_key",
    "managed_fields",
    "parse_etag",
    "project",
    "publish_version",
    "refresh",
    "reset_for_test",
    "snapshot",
    "start_config_refresher",
    "stop_config_refresher",
    "typed_value",
    "validate_value",
]
