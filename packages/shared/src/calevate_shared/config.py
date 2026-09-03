"""Typed settings. The app fails fast on missing config, never at first use.

Any new environment variable is added here AND to `.env.example` (DEV-SETUP.md §4).
Secrets are never defaulted — a missing secret must raise at startup.
"""

import ipaddress
import logging
from collections.abc import Callable
from decimal import Decimal
from functools import lru_cache
from typing import Literal, get_args

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource

# The MODEL and ENDPOINT vocabulary lives in the portability contract, not here (D-410).
# `Settings` imports FROM `engine` and never the other way round: which models exist and
# what an Azure resource name may look like are facts about the leg an engine runs, and a
# second spelling of either in this file is the drift that lets the console accept a value
# the endpoint builder then refuses.
from calevate_shared.engine import (
    AZURE_OPENAI_DEFAULT_MODEL,
    AZURE_RESOURCE_PATTERN,
    AzureOpenAIModel,
)

#: Environment variables the deployment's `.env` legitimately carries FOR SOMEONE ELSE.
#:
#: botocore resolves these three itself — nothing in this repository passes credentials to
#: boto3 — so they are deliberately not `Settings` fields and never will be
#: (`scripts/check_env_parity.SDK_ENV_KEYS` carries the per-key argument). But
#: DEPLOYMENT §6 tier 1 requires them IN `.env`, and `scripts/vps-deploy.sh::preflight`
#: refuses to deploy a host whose `.env` lacks them.
#:
#: That combination was unbuildable (D-188). `model_config` sets `env_file=".env"` with
#: `extra="forbid"`, and pydantic-settings applies `forbid` to keys read from the DOTENV
#: FILE — not to unrelated `os.environ` entries. So the exact `.env` the deploy demands is
#: one `Settings()` REFUSES to construct: three `extra_forbidden` errors, every time, for
#: any process whose working directory is the deploy root. The containers escaped it only
#: by accident — `.dockerignore` keeps `.env` out of the image and compose delivers the
#: same values as process environment instead — but `scripts/bootstrap_admin.py` runs from
#: the repo root on the VPS by design, so THE FIRST ADMINISTRATOR COULD NOT BE CREATED.
#:
#: The fix is an explicit allow-list rather than `extra="ignore"` or
#: `dotenv_filtering="only_existing"`. Both of those would also swallow a MISSPELLED key —
#: `DATABSE_URL=` would become silence instead of a refusal — and `extra="forbid"` is
#: carrying that typo check for a file operators hand-edit over SSH. This names the three
#: keys that are somebody else's and keeps the refusal for everything else.
SDK_OWNED_ENV_KEYS: frozenset[str] = frozenset(
    {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"}
)


class _AppDotEnvSource(DotEnvSettingsSource):
    """`.env` minus the keys that belong to another library.

    Subclassed rather than filtered at the `settings_customise_sources` call site so the
    exclusion travels with the source: any future source reordering keeps it.
    """

    def __call__(self) -> dict[str, object]:
        values = super().__call__()
        # Case-insensitively, because pydantic-settings lower-cases dotenv keys before
        # matching them to fields (which is how `AWS_REGION` arrived as `aws_region` in
        # the error this exists to stop).
        return {k: v for k, v in values.items() if k.upper() not in SDK_OWNED_ENV_KEYS}


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
#: `apps/api/agents/models.py::ENGINES` was `("fake", "bolna")` — which was not a cosmetic
#: disagreement, because that tuple renders the `ck_agents_engine_enum` CHECK constraint,
#: so a deployment running `ENGINE=cartesia` could not insert an agent row at all. It
#: imports this now and the constraint was widened in `d7b1c48a2e93` (D-104). A set nobody
#: can import is a set everybody retypes.
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

# Bolna's documented egress addresses (D-31, TRD §5). THE only copy of these literals on
# any runtime path — `Settings.bolna_webhook_source_ips` defaults to them, and both the
# receiver (`apps/voice-runtime/engine_intake.py`) and the adapter
# (`apps/api/engine/bolna.py`) resolve their effective allowlist through
# `bolna_source_ips()` below. `scripts/pilot/gates_api.DOCUMENTED_EGRESS_IPS` restates them
# ON PURPOSE and argues why: a gate that imported the value it tests would be asking the
# code whether it agrees with itself.
#
# **THERE ARE THREE, AND THIS SET HELD ONE (D-412).** Every source this repository had
# read — the pinned OAS, `bolna-core.md`, `setup-webhook/SKILL.md`, `execution-payload.md`
# — named a single address, and they were current when they were read. Bolna has since
# renumbered to three, and their live docs say so in six places, with the consequence
# spelled out: *"Webhooks are sent from the following IP addresses. **Whitelist all
# three** on your server to ensure you receive all webhook events."*
# (`bolna-findings/mirror/pages/guides/post-call/polling-call-status-webhooks.md`;
# identically in `api-reference/executions/get_execution.md`, `concepts/security.md`,
# `api-reference/limits.md`, `concepts/call-flow.md` and `build-with-ai/agents-md.md`).
# The mirrored `llms-full.txt` in the same evidence tree still shows the OLD single-IP
# wording, so the two snapshots together date the change rather than merely asserting it.
#
# WHAT THE MISSING TWO COST, and it is not "some webhooks": `parse_source_ip_allowlist`
# fails SAFE, so a delivery from an address not in this set is REJECTED. Two of Bolna's
# three senders were being turned away at the receiver, and which sender carries a given
# transition is not ours to choose — so roughly two thirds of every status transition,
# `completed` included, never reached the post-call pipeline. That is survivable only
# because the executions poller is the guarantee of record (TRD §5, "payloads as hints,
# poller as truth") — and D-412 found that poller sending a malformed listing request at
# the same time. Both halves of the guarantee were down together.
#
# A NEW ADDRESS IS A CONFIG CHANGE, NOT A DEPLOY: `Settings.bolna_webhook_source_ips`
# overrides this default, which is why the vendor renumbering again costs an env edit.
DEFAULT_BOLNA_SOURCE_IPS: frozenset[str] = frozenset(
    {"13.203.39.153", "13.126.9.249", "13.202.133.53"}
)


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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Default precedence, with the dotenv source narrowed to keys that are OURS.

        Order is pydantic-settings' own (init > env > dotenv > secrets) and is restated
        rather than changed: the only edit is swapping the dotenv source for the one that
        drops `SDK_OWNED_ENV_KEYS`. See that constant for why the shipped `.env` was
        otherwise unloadable.

        THE REPLACEMENT IS BUILT FROM THE SOURCE WE WERE HANDED, NOT FROM `model_config`.
        It read `cls.model_config.get("env_file")`, which is the CLASS default and ignores
        what the caller asked for — so `Settings(_env_file=None)`, the documented way to
        say "this process has no dotenv", loaded `.env` anyway. That is not only a broken
        test hook: a production host with a leftover `.env` beside the binary would be read
        by a process that had explicitly disabled it, and `APP_ENV` is exactly the kind of
        key such a file carries. `tests/app_env_required_test.py` caught it, because it
        describes a forgetful deploy as "`_env_file=None` plus this dict and nothing else"
        and the value came back anyway.

        `dotenv_settings` already carries the caller's own resolution of every one of these
        options, so copying them off it keeps the ONLY behavioural change the filtering of
        SDK-owned keys.
        """
        source = dotenv_settings
        return (
            init_settings,
            env_settings,
            _AppDotEnvSource(
                settings_cls,
                env_file=getattr(source, "env_file", cls.model_config.get("env_file")),
                env_file_encoding=getattr(
                    source, "env_file_encoding", cls.model_config.get("env_file_encoding")
                ),
                case_sensitive=getattr(source, "case_sensitive", None),
                env_prefix=getattr(source, "env_prefix", None),
                env_nested_delimiter=getattr(source, "env_nested_delimiter", None),
                env_ignore_empty=getattr(source, "env_ignore_empty", None),
                env_parse_none_str=getattr(source, "env_parse_none_str", None),
            ),
            file_secret_settings,
        )

    # NO DEFAULT, ON PURPOSE. The environment is STATED, never inferred.
    #
    # This field used to default to `"local"`, and `"local"` is one of the two facts under
    # which `apps/api/core/auth.py::_verify_dev_token` accepts a `dev:<realm>:<subject-id>`
    # credential — an authentication bypass. `runtime_config_missing_keys` skipped its
    # provider checks under the same branch, so `/healthz/ready` reported a healthy service
    # while doing it. One forgotten variable therefore switched off both the authentication
    # and the alarm, and a deploy that never set APP_ENV looked exactly like one that did.
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

    # Where Bolna reaches OUR in-call ACTION execution endpoint (the ACTIONS feature). It
    # is apps/api, NOT voice-runtime: a data-returning action makes a synchronous external
    # call plus a credential decrypt, which hard rule 3 forbids on the latency-critical
    # webhook service — so the tool's `value.url` points here and the monolith (which
    # already holds httpx, the ORM and the engine adapter) runs it. Defaults to the local
    # apps/api origin; in production this is the public app-API origin Bolna's egress can
    # reach (e.g. https://app.calevate.tech). Distinct from `webhook_base_url`, which is
    # the voice-runtime receiver.
    actions_callback_base_url: str = Field(
        default="http://localhost:8000", max_length=255, pattern=r"^https?://[^\s]+$"
    )

    # `host:port` of the ORIGIN that terminates TLS for our public hostnames — the nginx
    # on the deployment host, reached from inside a container through the gateway
    # `compose.prod.yml` already wires as `host.docker.internal`.
    #
    # IT IS NOT THE PUBLIC HOSTNAME, AND THAT IS THE WHOLE POINT (OPERATIONS §4,
    # `workers/tls_expiry.py`). Traffic is proxied by Cloudflare in Full (strict), so a
    # TLS handshake to `hooks.calevate.tech` returns CLOUDFLARE's edge certificate, which
    # renews itself and is not ours to lose. The certificate that can actually expire is
    # the origin's — the certbot lineage nginx serves — and the only way to see it is to
    # handshake with the origin directly and name the host in SNI. nginx applies its
    # `deny all` for non-Cloudflare addresses at the HTTP layer, AFTER the handshake, so
    # the certificate is readable from here even though a request would not be served.
    #
    # Defaulted rather than left empty so that a host which configures nothing still
    # checks — the same choice `BACKUP_ALERT_COMMAND` makes for the same reason. The
    # check is a stated no-op under `APP_ENV=local`.
    tls_origin_address: str = Field(
        default="host.docker.internal:443", max_length=255, pattern=r"^[^\s:/]+:\d{1,5}$"
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
    #: The Bearer token the engine presents when it asks us who is ringing (D-513).
    #:
    #: On an INBOUND call the engine holds the number and we hold the memory, so it fetches
    #: caller details from `GET /v1/engine/caller-data/{engine}` at call setup and injects
    #: the answer into the agent's prompt. Their console takes a Bearer token for that
    #: endpoint and stores it (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/
    #: agent-setup/inbound-tab.md:38-42,63,78`, read 2 Sep 2026) — so the value is one WE
    #: choose and paste into their agent, not one they issue.
    #:
    #: ABSENT ⇒ THE ENDPOINT ANSWERS NOBODY, which is the safe reading of an unconfigured
    #: credential rather than an outage: a deployment that has not been wired to the engine
    #: simply greets every inbound caller generically, exactly as it does today. It is NOT
    #: `bolna_api_key` reused — that key authenticates US to THEM and would be travelling in
    #: the opposite direction, so a leak of one would be a leak of the other.
    bolna_caller_data_token: str | None = Field(default=None, max_length=256)
    # Bolna quotes cost in USD cents; the adapter converts at capture and STAMPS the rate
    # it used into usage_events.meta so any ledger row can be re-derived (hard rule 7).
    #
    # ⚠ THIS IS NOW THE FALLBACK, NOT THE RATE, and this comment used to say the opposite
    # ("a config row, not a live FX call: metering must be reproducible, not current").
    # Both halves of that sentence survive, but they are answered by different things now:
    # `apps/workers/fx_pull.py` pulls a PUBLISHED reference rate every five minutes into
    # `fx_rate_observations` and `engine/bolna.py::_cost` converts at it, so metering is
    # current; and it stays reproducible because the rate, its source and its publication
    # date are stamped on every ledger row and the observation history is append-only.
    # This value is what the conversion falls back to when nothing has been pulled or the
    # published rate has aged past `core/fx.MAX_QUOTE_AGE` — which is why it is still a
    # number a human owns, still bounded below, and still worth keeping accurate.
    #
    # BOUNDED BECAUSE IT IS MONEY AND IT IS CONSOLE-SETTABLE. `0` is type-valid and
    # makes every Bolna minute cost nothing — the platform bills zero and nobody
    # notices until the month closes — so the floor is EXCLUSIVE. The ceiling is two
    # orders of magnitude above any plausible USD/INR rate: a fat-fingered `8800`
    # would overcharge every client by 100x, and an ops console is exactly where that
    # keystroke happens.
    usd_inr_rate: Decimal = Field(default=Decimal("88.00"), gt=0, le=1000)

    # BYOK models — canonical stack per D-36: Sarvam does STT + LLM + TTS, and per D-127
    # it also does the FIRST post-call extraction, permanently, because that pass reads
    # the RAW transcript (`workers/pipeline.py` hands `turn.text`, not `redacted.text`, to
    # the extractor so a "callback number" field gets the actual digits) and G-2 forbids
    # raw PII reaching Google. `GEMINI_EXTRACTION_DEFAULT is False` is the greppable form
    # of that sentence (`workers/extraction.py`).
    sarvam_api_key: str | None = None
    # ⚠ THE AI STUDIO DEVELOPER API KEY. THIS COMMENT SAID "NO SURFACE IN THIS PRODUCT
    # OPENS THAT DOOR" AND THAT HAS BEEN FALSE SINCE D-456 — the correction matters more
    # than the sentence, because a reader trusting it would conclude an installed Gemini
    # key is inert, and it is not.
    #
    # THE REGION HALF IS VENDOR-PUBLISHED AND CONFIRMED. Google's own live Gemini discovery
    # document (`generativelanguage.googleapis.com/$discovery/rest?version=v1beta`, revision
    # `20260823`, read 27 Aug 2026) declares ONE global `rootUrl` and contains the string
    # "region" zero times and "residen" zero times; Google's own SDK raises
    # `ValueError("Gemini API does not support project/location.")` before a packet leaves
    # the machine (`googleapis/python-genai`, `google/genai/_api_client.py`, main, read
    # 27 Aug 2026). There is no region to ask for on this API.
    #
    # THE DATA-USE HALF IS **SECONDARY**, AND THIS COMMENT USED TO STATE IT FLATLY. Every
    # Google-owned host that publishes those terms is egress-blocked from this environment
    # (`ai.google.dev`, `policies.google.com`, `aistudio.google.com`, and `web.archive.org`
    # too — re-measured 27 Aug 2026), so NOBODY IN THIS TREE HAS READ THEM ON A GOOGLE HOST.
    # What is held is two independent third-party verbatim mirrors of the Gemini API
    # Additional Terms — captured **May 2025 and March 2026**, ten months apart, by
    # unrelated parties, and agreeing almost word for word, with a search-engine summary
    # agreeing again. Two independent captures that far apart do not drift into agreement
    # by accident, which is what makes this SECONDARY rather than hearsay; it is still not
    # a page anybody here opened. They say: on the
    # unpaid tier Google uses submitted content and responses "to provide, improve, and
    # develop Google products and services and machine learning technologies", human
    # reviewers "may read, annotate, and process your API input and output", and the terms
    # instruct in as many words: "Do not submit sensitive, confidential, or personal
    # information to the Unpaid Services." The EEA/Switzerland/UK carve-out that applies the
    # paid terms to free usage does NOT include India. For a Processor holding an Indian
    # SMB's callers' transcripts that is not a tradeoff, it is a disclosure we could not
    # make — which is still why this key is barred from the two surfaces below. Read the
    # label with the claim: SECONDARY is strong enough to keep a door SHUT and is not
    # strong enough to open one (hard rule 11).
    #
    # ⚠ **PAID DOES NOT MEAN UNLOGGED**, and a reader must not collapse the two. On the same
    # SECONDARY evidence the paid terms log prompts and responses for a limited period for
    # abuse detection, permit authorised employees to read flagged content, and state the
    # data "may be stored transiently or cached in any country" — an explicit disclaimer of
    # residency, not a residency claim. What an operator may attest is that the vendor does
    # not TRAIN on submitted content (`ops/dashboard_data_use_routes.py`, D-477); that is one
    # property and it is the only one the dashboard-eligibility gate turns on.
    #
    # WHAT CHANGED: D-127 disqualified it for the DASHBOARD leg and D-410 moved both LLM
    # surfaces to Azure — and then D-456/D-459 reopened the IN-CALL leg on two models the
    # thinking-off trap does not break. `LlmProvider` carries `"google"`,
    # `gemini-2.5-flash` and `-flash-lite` are in `SELECTABLE_LLM_MODELS`, and
    # `ops/model_pricing.py:65` maps the `google` provider to THIS field. So a client who
    # picks a Gemini agent runs on this credential, inside the engine, on the in-call leg.
    #
    # THE TWO BARS THAT DID NOT MOVE, which is the half a reader must not lose:
    # * The DASHBOARD assist leg. D-127 G-2 is a rule about RAW PII, and the unpaid tier's
    #   human-review disclosure is why this key is not an assist rung by default. **D-477
    #   made that a MECHANISM rather than a sentence**: `agents/llm_models
    #   .dashboard_leg_reason` bars the `google` leg until an operator attests, in the ops
    #   console, that the Cloud project this key belongs to is on the paid tier AND has not
    #   opted its logs back into the unpaid terms. Attesting does not on its own switch the
    #   assistant onto Google — no dashboard chat leg is built for it — and the console says
    #   so.
    # * The FIRST POST-CALL EXTRACTION, which reads the raw transcript.
    #   `GEMINI_EXTRACTION_DEFAULT is False` (`workers/extraction.py`) is the greppable
    #   form of that sentence and D-410 did not move it.
    # `gemini-3.*` stays `selectable=False` on its own separate ground — the vendor's
    # docs say 3.x does not support full thinking-off, and a candidate with no content is
    # dead air on a phone call.
    #
    # IT IS KEPT, AND THIS IS NOT A DEPRECATION — which is what this comment used to
    # claim, in a paragraph that contradicted itself two sentences later. It said hard
    # rule 8's two-step applied and that step one was done, "nothing in the tree [reads]
    # it", and then said it is read in exactly one place. Both cannot be true, and the
    # second one is: `assist_capability()` reads it on every call. A field that is READ
    # has not had step one taken, so there is no step two to schedule and the sentence
    # promising a later release was a schedule wearing a rule's clothes (CLAUDE.md: a
    # deferral is a decision-log entry naming what closes it, or it is not a deferral).
    #
    # ⚠ THIS COMMENT USED TO CLAIM A JOB THIS FIELD NO LONGER HAS, and the correction is
    # the point. It argued that the field was the one input separating "no AI credential"
    # from "the WRONG KIND of AI credential", because `assist_capability()` read it to
    # choose between two operator-facing sentences. **Nothing reads it any more.** D-410's
    # extraction rewrite deleted `ai_studio_key_disqualified` on its own reasoning, and
    # the two facts landed in different files by different hands — leaving a comment here
    # that was readable, confident and false. Grepping the tree, the only readers left are
    # `platform_config`'s metadata table and two tests, one of which tests this very claim.
    #
    # SO WHY IS IT STILL HERE? One reason, and it is the one previously recorded second:
    # `Settings` is `extra="forbid"` over a dotenv, so deleting the field turns any `.env`
    # still carrying `GEMINI_API_KEY` into a BOOT FAILURE. That is hard rule 8's two-step
    # deprecation in its ordinary form — stop reading it in this release, remove it in a
    # later one — and this is the release that stopped reading it.
    #
    # ⚠ **THE SAME QUESTION HANGS OVER THE IN-CALL LEG, AND NOTHING HERE GATES IT.** A
    # client who picks a Gemini agent sends RAW CALLER SPEECH through this credential on
    # every turn — strictly worse exposure than the dashboard leg's redacted screen text —
    # and at least one tenant is on `gemini-2.5-flash-lite` today. That is the founder's
    # question, not a column's: OPERATIONS §2 gate 41 owns it and names what closes it.
    #
    # WHAT CLOSES IT: deleting this field once no `.env` in use carries the key. That is a
    # deferral naming what closes it rather than a schedule, per CLAUDE.md. It is NOT
    # waiting on a decision, a vendor or a date.
    #
    # DO NOT restore the reader to make the old argument true again. An operator installing
    # a Gemini key for a product with no Gemini leg is now an unlikely path, and a
    # defensive branch that cannot realistically be reached is the coverage-ratchet
    # liability the extraction rewrite deleted it to avoid.
    gemini_api_key: str | None = None

    # OPENAI DIRECT — the `openai` leg's credential (D-456's third declared leg). ONE key,
    # unlike Azure's four: OpenAI's own API is a single OpenAI-compatible surface, so the
    # engine's credential store takes exactly one entry named `OPENAI`
    # (VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/providers.md:87,105-109`, "LLMs"
    # tab, "OpenAI" accordion — one row, `OPENAI` = "Your OpenAI API key"). The mapping of
    # this field to that store entry is an ENGINE concern (hard rule 2) and lives beside
    # the Azure four in `engine/bolna.py`; this field carries only the value the platform
    # installs.
    #
    # OFFERED TO NOBODY TODAY, and installable anyway — the same posture as `gemini_api_key`
    # one field up (D-456: `azure_openai`, `openai`, `google` are all DECLARED, only Azure's
    # two models are SELECTABLE). Every `openai`-leg model in `calevate_shared.engine
    # .LLM_MODELS` carries `selectable=False` because its list price is REPORTED, not read
    # (every OpenAI pricing host is egress-blocked here) — and `LlmModelSpec` refuses to make
    # a model selectable on an unverified price. The founder's resolution is the ops panel's
    # OPERATOR-ATTESTED price (`ops/model_pricing.py`): once the founder installs this key
    # AND attests a price from their own OpenAI invoice, the model becomes offerable. So this
    # credential is installed in anticipation of that attestation, exactly as an operator
    # would install a vendor key before switching its leg on.
    #
    # SEALED OUT OF THE PLAINTEXT TABLE BY ITS NAME (`api_key` is one of
    # `platform_config._SECRET_NAME_FRAGMENTS`), so `manageable_secret_keys()` picks it up
    # with no list to edit and `platform_secrets` holds it encrypted. Injected from the
    # secrets manager at deploy time, never a committed file, never logged. Bounded like the
    # Azure key: 512 is far above any real key and far below the megabyte a jsonb-replicated
    # string could carry.
    #
    # `applies: live` (`core/platform_config.FIELD_APPLIES`) and not `needs_republish`: NO
    # process caches this credential and no engine holds a copy of it, because no model runs
    # on the `openai` leg yet — so a rotation cannot be stale anywhere, which is the exact
    # condition `needs_republish` exists to warn about. `azure_openai_api_key` is
    # `needs_republish` BECAUSE the engine caches its copy; the day an `openai`-leg model is
    # switched on and the engine begins to hold this one, the lane that wires that reader
    # reclassifies this field in the same change (the repo's rule: the reader and its
    # classification land together).
    openai_api_key: str | None = Field(default=None, max_length=512)

    # AZURE OPENAI — BOTH LLM SURFACES, ONE RESOURCE (D-410). The in-call leg the engine
    # calls and the user-triggered dashboard AI read the same four values below.
    #
    # WHY FOUR RATHER THAN TWO, and it is Azure's shape rather than ours: the endpoint is
    # built from a RESOURCE name, the API addresses a DEPLOYMENT, and the deployment is
    # made FROM a model whose identity only the cost model needs. Three different strings
    # that every other OpenAI-compatible provider collapses into one, plus the key.
    #
    # WHAT IS NOT HERE, AND MUST NEVER BE: the REGION.
    # `calevate_shared.engine.AZURE_LOCATION` is a `Final` for the reason it says, and
    # `scripts/check_model_residency.py` fails the build on any `Settings` field whose
    # name says region, location or residency. Azure hides the region inside the resource
    # rather than in the URL, which makes `azure_openai_resource` the value that decides
    # residency in practice — read `AZURE_LOCATION` before changing it, and note that no
    # code here can check it. Since D-449 that constant reads `eastus2` and the product
    # makes NO Indian residency claim on either LLM surface; pointing this resource at an
    # Indian one would not restore the claim, it would just make the tree disagree with
    # its own declared posture.
    #
    # The GOOGLE CREDENTIALS THAT WERE HERE ARE GONE, deleted rather than deprecated:
    # `gcp_project_id` and `gcp_service_account_json` existed for the Vertex AI legs and
    # for nothing else, and D-410 removed the last reader of both. Google Sheets sync
    # (D-23) was the one candidate for keeping them and does not use them — it reads
    # `google_sheets_service_account_json` below through the same
    # `workers/google_oauth.py` handshake, which stays. A credential an operator can still
    # install and then believe in is the `COHERE_API_KEY` defect this file already
    # recorded once.

    # The resource name — the `<resource>` in `https://<resource>.openai.azure.com`.
    #
    # ORDINARY CONFIG, not a credential: it is in every URL the client builds, and it is
    # the value an operator will get wrong first, so it belongs on the console screen
    # where they can see and correct it.
    #
    # BOUNDED BY THE HOSTNAME IT BECOMES, from the ONE pattern in the engine contract
    # rather than a second one typed here: `azure_openai_base_url()` interpolates this at
    # the FRONT of the authority, so a value carrying a `/` or a `.` addresses a different
    # host entirely (`calevate_shared.engine._AZURE_RESOURCE_RE` has the attack in full).
    # Refusing it here means the operator learns at the moment they type it, in a message
    # naming this field, rather than from a builder raising inside a publish.
    azure_openai_resource: str | None = Field(
        default=None, min_length=2, max_length=64, pattern=AZURE_RESOURCE_PATTERN
    )
    # The static API key the v1 surface authenticates with, sent as
    # `Authorization: Bearer <key>` (D-410).
    #
    # THIS FIELD IS THE WHOLE REASON THE VERTEX ROTATION MACHINERY IS GONE. A regional
    # Vertex endpoint took a Google OAuth2 access token and nothing else, so D-404 built a
    # 4-hourly refresher, a dead man watching it and a runbook for when it stopped. Azure
    # takes a string that does not expire; the refresher, its cron registration, its alarm,
    # its runbook and `in_call_llm_heartbeat_url` were deleted in the same change, because
    # a watchdog over a loop that no longer exists still reports health.
    #
    # SEALED OUT OF THE PLAINTEXT TABLE BY ITS NAME: `api_key` is one of
    # `platform_config._SECRET_NAME_FRAGMENTS`, so `managed_fields()` excludes it and
    # `platform_secrets` holds it encrypted. Injected from the secrets manager at deploy
    # time, never a committed file, never logged.
    #
    # Bounded generously rather than tightly. An Azure OpenAI key is short (tens of
    # characters), but a ceiling that tracked today's format would refuse tomorrow's on a
    # value an operator cannot work around; 512 is far above any key and far below the
    # megabyte a jsonb-replicated string could otherwise carry.
    azure_openai_api_key: str | None = Field(default=None, max_length=512)

    # --- Google OAuth (Calendar actions) -------------------------------------------
    # The PLATFORM's Google Cloud OAuth client — the founder holds one Google project and
    # all client calendar connections authorize against it. `..._client_secret` is picked
    # up as a `platform_secrets` value by the "secret" name fragment; the id and redirect
    # are plain config. All three are None until a Google project exists — an EXTERNAL
    # blocker (a vendor account), which is why Calendar actions refuse cleanly rather than
    # half-working when they are unset.
    google_oauth_client_id: str | None = Field(default=None, max_length=256)
    google_oauth_client_secret: str | None = Field(default=None, max_length=512)
    google_oauth_redirect_uri: str | None = Field(default=None, max_length=512)

    # The DEPLOYMENT id — what the API actually addresses, and NOT the model name.
    #
    # ITS OWN FIELD BECAUSE AZURE MAKES IT ONE. Elsewhere `model` names a model; on Azure
    # an operator deploys a model under a name of their choosing and the request carries
    # THAT name, so it cannot be derived from `azure_openai_model` and must not be guessed
    # from it. `ModelConfig.llm_model` is where this value lands on the wire.
    #
    # ⚠ **THE ENGINE READS THIS NAME AND INFERS THINGS FROM IT, WHICH NOTHING HERE KNEW
    # UNTIL THEIR DOCS WERE READ.** VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/
    # providers/llm-model/azure-openai.md:69`: *"Azure deployment names are chosen freely,
    # so `model` here is often not the model name. Keep the underlying model name inside
    # the deployment name — `prod-gpt-5.4-mini` rather than `prod-voice-01`. Bolna resolves
    # the deployment to the model it serves, and that resolution is what selects GPT-5
    # handling and the right default `reasoning_effort`. A name it cannot resolve is
    # treated as a non-GPT-5 model and gets the wrong defaults."*
    #
    # HARMLESS FOR US TODAY AND A TRAP THE DAY IT IS NOT. `AzureOpenAIModel` is closed to
    # two GPT-4-class models, and "treated as a non-GPT-5 model" is the CORRECT handling
    # for both — so an opaque deployment id costs nothing right now. It stops being free
    # the moment a GPT-5 model is added to that Literal: a deployment named `prod-voice-01`
    # would then be served with GPT-4-era defaults on a GPT-5 model, silently, with no
    # error anywhere. Naming deployments after the model they serve costs nothing and
    # removes the failure in advance, so it is the instruction OPERATIONS §2's Azure gates
    # carry. The other half of that trap is in `AzureOpenAIModel`'s own comment.
    #
    # Bounded to the shape Azure accepts for a deployment id — letters, digits, hyphens
    # and underscores, up to 64 — so a value with a slash or a space cannot reach a URL.
    azure_openai_deployment: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
    )
    # THE DEPLOYMENT SERVING EVERY **OTHER** ALLOW-LISTED MODEL — the field that makes a
    # client's model CHOICE reach the wire instead of only the invoice (D-454).
    #
    # **THE DEFECT IT CLOSES, because a mapping field looks like gold-plating until you
    # see it.** `agents.llm_model` and `organizations.default_llm_model` let an account
    # pick between `gpt-4o-mini` and `gpt-4.1-mini`, which differ 2.7x in price. On Azure
    # the API addresses a DEPLOYMENT id, so with only the field above configured, a client
    # who picked the dearer model would be QUOTED and metered at its rate while every call
    # ran the cheaper deployment — charging for something we did not deliver, invisibly,
    # because nothing in a transcript or an execution payload names the model that
    # answered. Hard rule 7 is not only "use NUMERIC"; it is that a price describes what
    # actually happened.
    #
    # **A MAP, AND THIS FIELD IS THE HALF THAT IS NOT ALREADY SPELT ABOVE.**
    # `azure_openai_deployment` is, and stays, the deployment for `azure_openai_model` —
    # the pair this file already says must move together, and the value pushed to the
    # engine's own credential store (`AZURE_OPENAI_MODEL`, `engine/bolna.py`). So this
    # field carries the OTHERS, and an entry here naming `azure_openai_model` is IGNORED
    # rather than merged: two fields answering for one model is exactly how they come to
    # disagree, and the one the credential store reads has to win.
    # `apps/api/agents/llm_models.deployment_for()` is the single resolver over both, and
    # nothing else may read either field to answer "which deployment serves this model".
    #
    # **A BOUNDED STRING RATHER THAN `dict[str, str]`, and the reason is a guardrail
    # rather than taste.** `scripts/check_config_applies.py` requires every console-managed
    # field to be BOUNDED and fails closed on a shape it cannot bound-check — an object has
    # neither a `maxLength` nor a numeric range, so a dict field would have had to weaken
    # that guard (or teach it a new shape) to land. A `KEY=VALUE,KEY=VALUE` string is the
    # standard way this is carried in an environment anyway, and `pattern` makes the shape
    # a boundary refusal at the console rather than a parse error at 3am: nothing
    # malformed can be stored, so the parser has no failure branch to get wrong.
    #
    # 512 characters is far above the two entries the allow-list can produce and far below
    # the megabyte a jsonb-replicated string could otherwise carry.
    # THE EMBEDDING DEPLOYMENT — a THIRD deployment field, and it has to be one (D-502).
    #
    # An embedding model is served under its own Azure deployment, distinct from every chat
    # deployment above however it is named: posting `POST /embeddings` input at a chat
    # deployment is a 400, and posting chat messages at an embedding deployment is a 400 the
    # other way. It therefore cannot be derived from `azure_openai_deployment` and must not
    # be guessed from it — the same argument that gave the chat deployment its own field,
    # applied to a different endpoint on the same resource.
    #
    # SAME RESOURCE, SAME REGION, SAME CREDENTIAL, so this adds NO sub-processor: it is the
    # East US 2 resource D-449 already settled, reached through the one builder
    # `calevate_shared.engine.azure_openai_base_url`.
    #
    # None until an operator creates the deployment — an EXTERNAL step, so knowledge search
    # degrades to its sparse arm and to T0 rather than half-working
    # (`apps/api/retrieval/service.get_retriever` says so at ERROR). Bounded to the same
    # character class and 64-character ceiling as every other Azure deployment id here.
    azure_openai_embedding_deployment: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
    )
    # WHICH RETRIEVAL STORE ANSWERS A COLD LOOKUP (D-502). `compiled-facts` is T0 alone —
    # what shipped while the D-28 bake-off was open — and `pgvector` adds the T3 hybrid
    # store in the Postgres we already run.
    #
    # A SETTING RATHER THAN A CONSTANT because it is the seam the founder's exit clause
    # depends on: moving to a managed vendor is a third value here plus one adapter module,
    # with no caller touched. It is also the switch that turns the store OFF in one poll if
    # it misbehaves, without a deploy.
    #
    # ⚠ IT DOES NOT TOUCH THE CALL. In-call retrieval is T0 and the engine's own KB whatever
    # this says (`docs/evidence/kb-retrieval-bakeoff.md` §5.1, `tests/kb_tiers_test.py`).
    #
    # A closed `Literal` rather than a bounded string: a typo must be refused at the console
    # and at boot, not resolved to a silent fallback, and a new store is a decision-log entry
    # rather than a value somebody typed.
    retrieval_provider: Literal["compiled-facts", "pgvector"] = "compiled-facts"
    azure_openai_deployments: str = Field(
        default="",
        max_length=512,
        # Empty, or `model=deployment` pairs joined by commas. The deployment half is the
        # same character class and the same 64-character ceiling as the field above, so a
        # value that is legal here is legal there — one rule about what an Azure
        # deployment id may look like, written twice only because a regex cannot import.
        pattern=(
            r"^$|^[A-Za-z0-9][A-Za-z0-9._-]*=[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
            r"(,[A-Za-z0-9][A-Za-z0-9._-]*=[A-Za-z0-9][A-Za-z0-9._-]{0,63})*$"
        ),
    )
    # WHICH MODEL THE DEPLOYMENT WAS MADE FROM — read by the cost model, never sent.
    #
    # **THIS IS THE `gpt-4.1-mini` SWITCH** and the reason it is config rather than a
    # constant. Both allow-listed models are documented available in `AZURE_LOCATION` on
    # the mandated Regional Standard SKU since D-449 moved it to `eastus2`, so what
    # separates them is price — `gpt-4.1-mini` is 2.7x — and the operator who decides the
    # quality is worth it flips this and creates a matching deployment, with no deploy of
    # ours. (It shipped as a switch for a WEAKER reason: under `southindia` the default's
    # own regional availability was unconfirmed and, on the vendor's matrix, absent. See
    # `AZURE_OPENAI_DEFAULT_MODEL`.)
    #
    # `applies: live`, and the pairing is the part to get right: this and
    # `azure_openai_deployment` must move TOGETHER. Changing the model here without
    # pointing the deployment at a matching one prices a model nobody is running — which
    # is a WRONG INVOICE rather than an outage, and therefore the failure that would go
    # unnoticed longest.
    #
    # BOUNDED BY ITS TYPE rather than by a length: `AzureOpenAIModel` is the closed set in
    # the engine contract, so pydantic refuses an unknown identifier at the write path,
    # the boot-time load and the console alike, and a new model is a decision-log entry
    # rather than a typo.
    azure_openai_model: AzureOpenAIModel = AZURE_OPENAI_DEFAULT_MODEL
    # WHICH ENTRY IN THE ENGINE'S CREDENTIAL STORE HOLDS THE LLM KEY (D-404, re-aimed by
    # D-410).
    #
    # ⚠ **THE MARKED ASSUMPTION THIS FIELD CARRIED IS CLOSED, AND THE GUESS WAS WRONG.**
    # It defaulted to `AZURE` — a DERIVATION, and the comment said so: their published
    # provider matrix names credential entries after the provider in upper case (`OPENAI`,
    # `GOOGLE`, `SARVAM`), so `azure` became `AZURE`. The vendor's own credential-store
    # documentation is now readable and names FOUR keys for Azure OpenAI, none of them
    # `AZURE`:
    #
    #     | `AZURE_OPENAI_API_KEY`     | Your Azure API key           |
    #     | `AZURE_OPENAI_MODEL`       | Your Azure OpenAI model      |
    #     | `AZURE_OPENAI_API_BASE`    | Your Azure URL               |
    #     | `AZURE_OPENAI_API_VERSION` | Your Azure Model API version |
    #
    # VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/providers.md`, "LLMs" tab, "Azure
    # OpenAI" accordion, under *"All these keys **must** be added for the respective
    # provider."* (fetched 20 Aug 2026, sha256 63231b2b7a0c5a338dd1d6342dc65ea4ac055
    # 46f7ddb6a28bc3c9a4ec24791b9). The derivation was not merely off by a spelling: the
    # per-provider naming rule it generalised from is real for single-key providers and
    # does not hold for this one, which needs a key, an endpoint, a model and a version.
    # `apps/api/engine/bolna.py::_AZURE_PROVIDER_KEYS` holds all four with the evidence,
    # because vendor field names are an ENGINE concern (hard rule 2); this field carries
    # only the one the platform must PUSH rather than an operator type.
    #
    # A SETTING RATHER THAN A CONSTANT, STILL, AND THE REASON CHANGED. It used to be a
    # setting because nobody had read the right value. Now it is a setting because a
    # documented name and an account's actual name are different claims: the docs are a
    # snapshot, the store is a live system, and OPERATIONS §2 gate 16f is a `GET
    # /providers` against a real account that can still disagree with the page. If it
    # does, this is a console edit rather than a deploy — the difference between a
    # five-minute fix and an outage lasting until the next release.
    #
    # Console-managed (`applies: live`) for exactly that.
    #
    # NOT a credential itself: it is the NAME of one, it is not secret, and it must stay
    # out of `platform_secrets` so an operator can actually SEE what is currently
    # configured. The value it NAMES is `azure_openai_api_key`, which is held encrypted
    # and pushed to the engine, never echoed back.
    #
    # ⚠ THAT DID NOT HOLD BY ITSELF, AND THE CORRECTION IS LOAD-BEARING FOR THE GATE
    # ABOVE. This comment used to add "(whose sealing is keyed on `_json`/`_key` style
    # names)", which is wrong: `platform_config._SECRET_NAME_FRAGMENTS` also carries the
    # bare fragment `credential`, added for exactly the naming this field uses — so the
    # field WAS sealed, write-only, `last_four` and nothing else. An operator working
    # gate 16f is trying values against a leg that is down; "what is it set to right
    # now" is the whole question they have. It also routed the `pattern` below around
    # its only enforcement point, because the secrets write path validates non-emptiness
    # and nothing else. The exemption is now explicit and checked at import:
    # `platform_config._CREDENTIAL_REFERENCE_KEYS`.
    #
    # Bounded to the shape a credential-store key can take: their examples are
    # `OPENAI_API_KEY`-style, so upper-case ASCII, digits and underscores. The documented
    # default now fits that shape exactly, which it did not have to before.
    bolna_llm_credential_name: str = Field(
        default="AZURE_OPENAI_API_KEY",
        min_length=2,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]{1,63}$",
    )
    # `COHERE_API_KEY` WAS HERE AND IS GONE, for the reason the paragraph below gives
    # about Clerk. It was declared, classified `applies: live` in `platform_config`, and
    # therefore offered to an operator on the ops console as a key they could install —
    # and NOTHING in this repository ever read it. D-28 makes retrieval a managed API
    # service that owns its own embeddings, so no code path has ever needed one. A knob
    # that does nothing is worse than no knob: an operator who installs it believes the
    # embeddings leg is configured. If a future retrieval provider requires us to embed,
    # the field comes back in the same change as the code that reads it.

    # THE SIX `CLERK_*` FIELDS THAT WERE HERE ARE GONE (D-177). Two publishable keys, two
    # secret keys, a frontend-API hostname and a Svix webhook secret — the whole vendor
    # configuration surface for authentication, removed rather than deprecated, because a
    # setting nothing reads is a value an operator can still install and then believe in.
    # Authentication is first-party and configures nothing: see `apps/api/authn/`.

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

    # WHICH email transport this deployment uses. THE statement, and the only one:
    # `email_transport_reason()` below is the single resolver and `workers/transport
    # .get_transport()` is its only consumer, so "which transport is this deployment
    # using?" has exactly one answer and it is this field.
    #
    # It exists as CONFIG rather than being inferred from "is there an API key" for the
    # same reason `payment_provider` and `google_sheets_provider` do: a credential is not
    # a statement that a capability exists, and two independent reads of "is SMTP_HOST
    # set?" eventually disagree. Credential-presence sniffing also cannot express the
    # state this migration creates — a deployment that still HAS smtp_* rows and has
    # moved to Resend — without inventing a precedence order nobody can see.
    #
    # A SEAM, NOT A SWITCH, exactly as `whatsapp_provider` is: the names with an adapter
    # behind them are `resend` (the founder's choice, Aug 2026) and
    # `smtp` (kept as the escape hatch — see workers/transport.py for why). Any other
    # name resolves to `provider_not_implemented` and refuses to send, loudly, rather
    # than looking configured. `console` is deliberately NOT a name here: the local dev
    # sink is selected by APP_ENV=local with no provider set, which is what it already
    # was, and making it typeable would let a staging host silently deliver to a log.
    email_provider: str | None = Field(default=None, max_length=64)

    # The Resend API key (`re_…`). **ENV-ONLY, and NOT for the usual bootstrap reason** —
    # `core/settings.ENV_ONLY_REASONS` carries the argument and
    # `tests/resend_env_only_test.py` pins it. This comment shipped saying the opposite
    # ("lives encrypted in `platform_secrets`, set from `admin.calevate.tech/ops`"), which
    # was the right home for a vendor credential and the wrong one for THIS credential:
    # `scripts/host_alert.py` runs on the database host, opens no database connection, and
    # is what pages a human when a backup fails — so it can only ever read this key from
    # its own environment. Offering the console as a second home would mean an operator
    # rotating it on a screen, seeing it accepted, and watching mail keep going out under
    # the old key, because the environment silently wins in `apply_platform_overrides`.
    #
    # `EMAIL_PROVIDER` above is deliberately NOT env-only: selection is exactly the change
    # the console exists for. One fact, two hosts, no shared secret.
    #
    # Unset with `EMAIL_PROVIDER=resend` is a refusal by name (`no_resend_api_key`),
    # never a transport that reports success having sent nothing.
    resend_api_key: str | None = None

    # SMTP, kept as the escape hatch (`EMAIL_PROVIDER=smtp`). Any SMTP provider works,
    # which is what keeps a Resend outage or a suspended account a configuration change
    # rather than a deploy. Unreachable unless the provider names it — `smtp_host` alone
    # no longer selects anything, because selection is the field above.
    smtp_host: str | None = Field(default=None, max_length=253)
    # 1..65535 is the whole legal port space. `0` is type-valid, is what an empty box
    # submits as an integer, and would make every hot-lead alert fail at connect.
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=320)
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    # THE SENDER, for hot-lead notifications and for operator alerts alike — one address,
    # because a client who allowlists one and not the other has half a channel.
    #
    # DEFAULTED RATHER THAN NULL, and defaulted HERE. `get_transport()` used to carry an
    # inline `or "alerts@calevate.tech"`, so the platform had two spellings of its own
    # return address and the console showed neither. The default now lives with the field:
    # one definition, visible in `GET /v1/ops/config`, editable without a deploy.
    #
    # `support@calevate.tech` is the founder's choice and is the address the Calevate
    # domain is being verified for. A sender whose DOMAIN the provider has not verified is
    # not a soft failure — Resend refuses the send outright (403) — so changing this to an
    # unverified domain stops mail rather than sending it to spam. `workers/transport.py`
    # logs that refusal under its own event name for exactly that reason.
    #
    # 320 is the RFC 5321 maximum for an addr-spec (64 local + @ + 255 domain).
    notifications_from: str | None = Field(default="support@calevate.tech", max_length=320)

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

    # `IN_CALL_LLM_HEARTBEAT_URL` WAS HERE AND IS GONE (D-410), TWO HOURS AFTER IT WAS
    # BUILT, and it is worth one comment because deleting a watchdog normally is the
    # wrong move. D-408 added a second dead man because the in-call LLM bearer was
    # rotated every four hours by a job of ours, and the one failure that job could not
    # report was itself not running — a stopped worker meant nothing rotated, nothing
    # paged, and every client's LLM leg went dark within twelve hours. Azure OpenAI takes
    # a STATIC key, so there is no rotation loop; a dead man watching a loop that does
    # not exist is strictly worse than none, because silence is what it reports health
    # with and it would go on being silent forever. The refresher, the cron entry, the
    # alarm and the runbook went in the same change.

    # WhatsApp transport for hot-lead alerts (ROADMAP M2). OFF by default and it must
    # stay off until the human checklist in workers/whatsapp.py is done: WABA + business
    # verification, an APPROVED template, and a recorded per-tenant opt-in.
    #
    # D-91 CHOSE META CLOUD API DIRECT, and this comment said the opposite for as long as
    # the three keys below were missing: "No BSP has been chosen in the decision log, so
    # `whatsapp_provider` is a seam, not a switch: any name other than `console` resolves
    # to `provider_not_implemented`". A decision WAS taken (Cloud API over the Indian BSP
    # layer, argued at length in `apps/workers/whatsapp_cloud.py`), the adapter was
    # written, and `meta_cloud_api` selects it. What stayed true is the refusal for every
    # OTHER name — naming a BSP we have not written still fails loudly rather than looking
    # configured.
    whatsapp_enabled: bool = False
    whatsapp_provider: str | None = Field(default=None, max_length=64)
    # The approved template's name and language, as registered with the provider. Here
    # rather than in code because re-approval is an operational event, not a deploy.
    # A template name is an identifier at the provider, and a locale is a language tag;
    # neither is free text, and an EMPTY one would send a message naming no template.
    whatsapp_template_hot_lead: str = Field(default="calevate_hot_lead_v1", max_length=128)
    whatsapp_template_locale: str = Field(default="en", max_length=16)

    # ---- Meta Cloud API credentials (D-91) ----------------------------------------
    #
    # THESE THREE ARE WHAT MADE `WHATSAPP_PROVIDER=meta_cloud_api` A DEAD CONFIGURATION.
    # `apps/workers/whatsapp.py` carried a block headed "TEMPORARY SHIM — DELETE THE
    # `getattr`s WHEN THE SETTINGS KEYS LAND", reading them through
    # `getattr(settings, ..., "")` because this file was owned elsewhere. The keys never
    # landed, and `Settings` is `extra="forbid"` — so no environment variable, no console
    # row and no test could set them, `whatsapp_delivery_status()` returned
    # `cloud_api_access_token_missing` on every deployment for ever, and
    # `CloudApiWhatsAppTransport` was unreachable code with an operator being told to go
    # and mint a token that had nowhere to go. A shim whose stated exit condition never
    # happens is the half-wired feature the quality bar names.
    #
    # NONE OF THIS IS THE VENDOR'S HALF. The WABA, the business verification and the two
    # approved templates are external and stay external — they are the operational gate on
    # `whatsapp_cloud.CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA`, and `whatsapp_enabled` stays
    # False until a person closes it. Declaring the keys is what makes that gate the only
    # thing left, instead of the second of two.

    # The Meta system-user access token. A CREDENTIAL, and it seals BY NAME rather than by
    # anyone remembering to say so: `platform_config._SECRET_NAME_FRAGMENTS` carries the
    # bare fragment `token`, so `is_secret_key` is True, it is excluded from
    # `managed_fields()` and it lands in the encrypted `platform_secrets` path with
    # `last_four` as the only thing the console ever renders back. Verified rather than
    # assumed — the fragment list is a substring match and reading it is cheaper than
    # discovering a plaintext credential later.
    #
    # LONG-LIVED, so there is nothing to refresh: Cloud API uses a system-user token
    # rather than a refresh flow, which is why `CloudApiWhatsAppTransport` caches nothing
    # (unlike `google_sheets.GoogleSheetsTransport`, which mints hourly). NO max_length:
    # every genuine credential in this model is an opaque `str | None`, because a bound
    # guessed at a vendor's token format is a bound that refuses a valid token one
    # rotation from now.
    whatsapp_cloud_access_token: str | None = None
    # The sending number's id, from the Meta console — the `<phone-number-id>` path
    # segment of `POST /{version}/{phone-number-id}/messages`.
    #
    # NOT A CREDENTIAL and deliberately not named as one, exactly like `razorpay_key_id`
    # next to `razorpay_key_secret`: it identifies which number sends, it authenticates
    # nothing, and an operator working the WABA checklist needs to SEE it to check it
    # against the console. Meta's ids are numeric strings; the bound is generous because
    # the failure it guards is a paste of the wrong thing entirely, not a length.
    whatsapp_cloud_phone_number_id: str | None = Field(default=None, max_length=64)
    # Which Graph API version to call. PINNED, never floating: Meta versions the Graph
    # API, unversioned calls are not a supported form, and a floating version changes
    # behaviour under us on their release schedule.
    #
    # CONFIG HERE, CODE IN `ingest/graph.py`, AND THE DIFFERENCE IS ARGUED RATHER THAN
    # DRIFT. `GRAPH_API_VERSION` is a `Final` in the Lead Ads reader with a test saying
    # raising it "is a code change with a test run, never an environment variable" — and
    # that is right THERE, because the version decides the shape of the response that
    # module PARSES, so a bump can silently change what a lead's answers mean. This one
    # addresses a `POST` whose request body and error envelope we construct ourselves,
    # and the event that forces a bump is Meta deprecating a version on their clock —
    # the same kind of external operational event that put the template name and locale
    # above in config rather than in code.
    #
    # THE PATTERN IS THE PIN. `v` and two numbers, so `latest`, `22.0`, an empty string
    # and a pasted URL are all refused at the console boundary with the field's own
    # message — `ops/config_service.validated_value` enforces it on the write path, which
    # is the enforcement point a constraint on a console-settable field has to have. The
    # rejected alternative was a bare `max_length`: it admits every one of those values,
    # and each of them fails as an opaque 4xx from Meta mid-send instead of as a sentence
    # while somebody is typing.
    whatsapp_cloud_graph_version: str = Field(
        default="v22.0", max_length=8, pattern=r"^v[0-9]{1,3}\.[0-9]{1,2}$"
    )

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
    # BOLNA_API_KEY (DEV-SETUP §4). Unset with the provider set is
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

    # Self-serve list price per calling minute, INR (the single-tier voice decision,
    # superseding D-34/D-35/D-36's ₹6). One number for the whole motion — there is one
    # voice quality now (Sarvam Bulbul v3), so there is one client rate — and it exists
    # in config so the runway framing ("about N minutes left") and the top-up flow price
    # from the SAME source, and so a price change is a deploy, not a code edit. Managed
    # clients never see it: their price lives in their `plans` row.
    #
    # ₹5.00 is a founder-accepted ~22-30% gross margin against an all-in cost of roughly
    # ₹2.89-4.28/call-minute (TRD §10.1); the dominant unmeasured risk is Telugu/Indic
    # character density on the TTS leg (pilot gate 12), which can push the cost toward the
    # ceiling. That risk is knowingly carried, not hedged in this number.
    #
    # BOUNDED FOR THE SAME REASON `usd_inr_rate` IS, one surface closer to the client:
    # `0` is type-valid and would price every self-serve minute at nothing, so the
    # runway framing says "unlimited" and the top-up flow charges zero. Exclusive floor.
    # The ceiling is absurd on purpose — nobody sells a minute for ₹10,000 — and its job
    # is to catch a decimal point in the wrong place before it reaches a wallet.
    self_serve_inr_per_min: Decimal = Field(default=Decimal("5.00"), gt=0, le=10_000)

    # HOW OLD A LIST'S CONSENT MAY BE BEFORE A CAMPAIGN OVER IT IS REFUSED, in days.
    #
    # **THE NUMBER IS NOT OURS AND THE CODE SAYS SO WHEREVER IT IS READ.** What is ours is
    # the MECHANISM: `campaigns.consent_collected_at` has been a validated, non-future,
    # source-paired column since the provenance gate shipped and NOTHING read it, so a
    # list collected in 2019 launched today with a green gate. That is the half this
    # repository can fix. The THRESHOLD is a legal question — our own research records
    # that the TCCCPR Second Amendment (12 Feb 2025) time-boxed consent in both directions
    # (transaction-tied consent to seven days; inferred consent to the life of the
    # relationship it was inferred from) without stating a period for a marketing list of
    # the kind a client uploads (`apps/api/compliance/consent.py`, the researched note) —
    # so the figure belongs to counsel, routed through LEGAL-OPS-PLAYBOOK §20, and this is
    # a config row precisely so their answer is a value change rather than a release.
    #
    # 365 IS A STATED DEFAULT, NOT A FINDING. It is the same window the messaging leg
    # already applies (`consent.MESSAGING_CONSENT_VALIDITY_DAYS`, itself the outer edge of
    # the 6-12 month re-confirmation guidance), chosen so the two legs of one product do
    # not disagree about how long a consent lasts while counsel is deciding. Nobody has
    # told us 365 is the lawful figure for voice, and no sentence in this tree may say
    # they have (hard rule 11).
    #
    # `0` DISABLES THE AGE CHECK, and is offered because "we do not yet know" is a real
    # operator position and is better held explicitly than by an operator typing 36500.
    # Every other blocker on the list — provenance recorded, source not purchased — keeps
    # running at 0.
    campaign_consent_max_age_days: int = Field(default=365, ge=0, le=36_500)

    # HOW LONG A PE REGISTRATION VERIFICATION STAYS GOOD FOR, in days.
    #
    # `dlt_registrations.verified_at` records when an operator last checked the registrar
    # against the client's entity. It was SELECTed, returned and never compared to
    # anything, so a registration verified once was verified forever — while the national
    # DND scrub beside it expires at midnight (`preference_scrub.scrub_expiry`) and
    # `KYC_STATUSES` carries `expired`, both for the same reason: a stale compliance
    # verdict is worse than none, because it is indistinguishable from a fresh one.
    #
    # OURS, AND SAID PLAINLY. No registrar publishes an expiry for a PE registration and
    # this default does not claim one exists — it is the cadence at which WE re-look, and
    # a registration can be suspended by the registrar on any day between two looks. 365
    # days matches the annual re-verify rhythm OPERATIONS already keeps for vendor and
    # regulatory facts. `0` disables the staleness blocker for an operator who wants the
    # status alone to govern.
    pe_verification_max_age_days: int = Field(default=365, ge=0, le=36_500)

    # R-11's kill switch. Self-serve signup is the sharp edge of D-34 (anyone can sign
    # up and dial), so the public intake is OFF unless someone turned it on, and
    # closing it during an incident is an environment change, not a deploy.
    self_serve_signup_enabled: bool = False

    # D-166: first-party authentication is THE authentication this product has. Clerk is
    # being removed, not run beside it, so this is a KILL SWITCH rather than a cutover flag
    # — the same role `self_serve_signup_enabled` plays, and it sits here for the same
    # reason: closing a front door during an incident is an environment change, not a
    # deploy.
    #
    # DEFAULT TRUE, unlike every other switch in this block, and the asymmetry is the
    # point. The others gate a FEATURE, so off is the safe default and a deployment that
    # forgot them still works. This one gates the only way anybody signs in: a fresh VPS
    # that came up with it off would have no authentication at all, and the operator who
    # had to diagnose that would be locked out of the console that reports it. Off is
    # therefore an incident action taken deliberately, never a state a deployment reaches
    # by omission.
    #
    # Routes are MOUNTED either way and refuse with `first_party_auth_disabled` when this
    # is off — a conditionally-mounted router is invisible to `scripts/check_wiring.py`,
    # absent from the OpenAPI contract, and answers 404 where "switched off" and "wrong
    # path" must be distinguishable.
    first_party_auth_enabled: bool = True

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
    # Vobiz for the 140-series and Plivo for the 160-series — the engine's own
    # regulated-numbers table, `bolna-findings/mirror/pages/guides/inbound/
    # obtaining-regulated-phone-numbers.md:15-16`). Config rather than an inference from a
    # credential, for the same reason `payment_provider` is: a key is not a statement that
    # the capability exists. NO ADAPTER EXISTS FOR ANY VALUE — `apps/api/campaigns/
    # provisioning.py` owns the one selector and `PROVISIONING_IMPLEMENTED` is False —
    # so this setting currently decides only WHICH refusal an operator sees. A name
    # outside {exotel, plivo, vobiz} resolves to `provider_not_implemented` rather than
    # looking configured; that module's comment carries the evidence for each name,
    # including why `twilio` is deliberately not one of them.
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
    # invoice, and Rule 46(g) makes the HSN/SAC of the supply one too. The LEGAL PERSON
    # is settled — Calevate is a trade name of a sole proprietor (`docs/legal/
    # LEGAL-OPS-PLAYBOOK.md:16`, `:80-96`) — but the REGISTRATION is not: we are not
    # registered for GST and are not required to be at present turnover (§4), so there is
    # no GSTIN to print and no tax to collect. They are therefore config with NO DEFAULT
    # and no placeholder. A hardcoded specimen GSTIN would be the worst possible outcome: an
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
    # UNSET IS A SUPPORTED STATE, it is what every environment is in today, and while we
    # are not GST-registered it is the CORRECT state rather than a gap:
    # `billing/gst.py::SupplierIdentity.is_registered` is False, the document renders as
    # a BILL OF SUPPLY (CGST Rule 49) that names the missing keys, and it refuses the
    # "Tax Invoice" heading rather than printing an invalid one. It does NOT change what
    # the client owes — `invoice.py` argues why a forgotten variable must never silently
    # move money.
    gst_supplier_legal_name: str | None = Field(default=None, max_length=200)
    gst_supplier_address: str | None = Field(default=None, max_length=1000)
    # 15 characters. Its first two digits are the supplier's State and are what decides
    # CGST+SGST vs IGST, so this field is the single source of our place of supply —
    # there is deliberately no separate state setting to drift from it.
    # LENGTH-CAPPED AND DELIBERATELY NOT LENGTH-CHECKED. A GSTIN is exactly 15
    # characters, and an exact `min_length=15` here was WRONG — caught by
    # `invoice_gst_test`, which feeds a 14-character value on purpose. `billing/gst.py`
    # already degrades gracefully on a malformed one: `parse_gstin` treats it as ABSENT,
    # the document renders as a bill of supply naming the missing key, and nothing about what
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
    # `billing/gst.py` is the semantic gate and it degrades to a bill of supply.
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


#: WHOSE allowlist a `source_ip` engine is authenticated against (P2.6).
#:
#: `calevate_shared.engine.WEBHOOK_AUTH_BY_ENGINE` says which METHOD an engine uses. This
#: says which addresses that method reads, and until it existed the two were not the same
#: kind of thing: the method was looked up per engine and the addresses were always
#: Bolna's, so `engine_intake.verify_source` would have authenticated a second unsigned
#: engine's deliveries against Bolna's egress. That is exactly what the receiver's `hmac`
#: branch refuses in a paragraph of its own ("an allowlist is evidence about a DIFFERENT
#: engine's egress") — left live one branch above it, and invisible because `bolna` is the
#: only engine declaring the method.
#:
#: AN ABSENT ENTRY REFUSES. There is no fall-back to the single entry that happens to
#: exist; the receiver returns a distinct reason so an operator reading the alert sees
#: "this engine has no allowlist" rather than "this address is not allowlisted".
#:
#: HERE RATHER THAN IN THE RECEIVER, and that is not tidiness: `engine_name_drift_test`
#: forbids `apps/voice-runtime/engine_intake.py` from spelling an engine name in a
#: collection at all (D-103), because a second spelling of the engine set in that file is
#: how the set drifted last time. A table of RESOLVERS belongs next to the resolver it
#: names anyway — the two move together or the mapping is a second thing to update.
#:
#: Resolvers rather than address sets, for `bolna_source_ips`' own reason: an operator
#: rotating `BOLNA_WEBHOOK_SOURCE_IPS` during a vendor renumber must move this answer
#: without a redeploy, and a set captured at import would not.
SOURCE_IP_ALLOWLIST_BY_ENGINE: dict[str, Callable[[Settings], frozenset[str]]] = {
    "bolna": bolna_source_ips,
}


# --- email: the one selector ---------------------------------------------------
#
# The provider names that have an adapter behind them in `workers/transport.py`.
# `console` is absent on purpose — see `Settings.email_provider`.
EMAIL_PROVIDER_RESEND = "resend"
EMAIL_PROVIDER_SMTP = "smtp"
SELECTABLE_EMAIL_PROVIDERS: frozenset[str] = frozenset({EMAIL_PROVIDER_RESEND, EMAIL_PROVIDER_SMTP})

# AUTHORED reason codes for "this deployment cannot deliver email". Ours, never a
# vendor's error string, and greppable — each one is a sentence an operator can act on
# and a token a log search can find. Same shape as `billing/payments.py`'s codes.
NO_EMAIL_PROVIDER_REASON = "no_email_provider"
EMAIL_PROVIDER_NOT_IMPLEMENTED_REASON = "provider_not_implemented"
NO_SENDER_ADDRESS_REASON = "no_sender_address"
NO_RESEND_API_KEY_REASON = "no_resend_api_key"
NO_SMTP_HOST_REASON = "no_smtp_host"


def email_transport_reason(settings: Settings) -> str | None:
    """Why this deployment can deliver no email, or None when it can. ONE resolver.

    Both halves of the email question call THIS — `workers/transport.get_transport()`,
    which builds the transport, and `core/observability.init_observability`, which warns
    at boot that alerts have nowhere to go — for the same reason `bolna_source_ips` above
    is one resolver: a second read of the same fields is a second answer waiting to
    disagree, and the disagreement here reads as "the boot line said alerts were fine and
    no alert ever arrived".

    IT LIVES HERE, BESIDE THE FIELDS, rather than with the transports, and that is not
    tidiness. `apps/voice-runtime` calls `init_observability` at boot and is forbidden to
    import `apps.workers` (hard rule 3, pinned by
    tests/voice_runtime_import_surface_test.py) — so a resolver that lived with the
    transports could not be the one the boot check uses, and the boot check would have to
    re-derive it. `calevate_shared.config` is already in every deployable's boot graph.

    Returns an AUTHORED code, never a vendor string. None means a real transport is
    selectable — which under APP_ENV=local with no provider set includes the console
    sink, because a message logged to a developer's terminal genuinely was delivered.
    """
    provider = (settings.email_provider or "").strip().lower()
    if not provider:
        # The local dev sink. Unchanged from before this field existed: nothing
        # configured on a laptop is the console transport, and anywhere else it is a
        # deployment that cannot mail anybody and must say so.
        return None if settings.app_env == "local" else NO_EMAIL_PROVIDER_REASON
    if provider not in SELECTABLE_EMAIL_PROVIDERS:
        # `EMAIL_PROVIDER=sendgrid` fails loudly rather than looking configured. The name
        # rides along because "which one did you mean" is the operator's next question.
        return f"{EMAIL_PROVIDER_NOT_IMPLEMENTED_REASON}:{provider}"
    if not (settings.notifications_from or "").strip():
        # A provider with no return address cannot send, and both adapters would fail
        # obscurely rather than clearly: Resend answers 422 on a missing `from`, and
        # `EmailMessage["From"] = None` raises inside smtplib. The field is defaulted, so
        # reaching here means somebody explicitly blanked it — which is a configuration
        # mistake, and the boot check names it as one.
        return NO_SENDER_ADDRESS_REASON
    if provider == EMAIL_PROVIDER_RESEND:
        return None if settings.resend_api_key else NO_RESEND_API_KEY_REASON
    return None if settings.smtp_host else NO_SMTP_HOST_REASON


__all__ = [
    "DEFAULT_BOLNA_SOURCE_IPS",
    "EMAIL_PROVIDER_NOT_IMPLEMENTED_REASON",
    "EMAIL_PROVIDER_RESEND",
    "EMAIL_PROVIDER_SMTP",
    "NO_EMAIL_PROVIDER_REASON",
    "NO_RESEND_API_KEY_REASON",
    "NO_SENDER_ADDRESS_REASON",
    "NO_SMTP_HOST_REASON",
    "SELECTABLE_EMAIL_PROVIDERS",
    "SELECTABLE_ENGINES",
    "SOURCE_IP_ALLOWLIST_BY_ENGINE",
    "EngineName",
    "Environment",
    "Settings",
    "bolna_source_ips",
    "email_transport_reason",
    "parse_source_ip_allowlist",
]
