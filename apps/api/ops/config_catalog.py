"""How the platform configuration screen is organised: sections, labels and descriptions.

`GET /v1/ops/config` serves this beside the values, so the console renders the grouping and
the wording it is given rather than guessing from key prefixes. It is the ONE place a
setting's section, plain name and one-line description live.

It is a per-key table on purpose, like `core/platform_config.FIELD_APPLIES`: where a setting
belongs and what it is called are facts about its meaning, which no annotation carries.
`tests/ops_config_catalog_test.py` keeps it exhaustive: every managed key has an entry, no
entry names a key that is not managed, and every entry points at a declared section. A key
added without an entry still renders, under "Other", with a humanised label — never hidden.

`used_when` marks a setting that only one kind of engine reads. The route evaluates it
against the engine this deployment runs, so the console can set those rows aside as "not used
by the current engine" instead of each screen re-deriving which vendor reads what.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from calevate_shared.engine import EngineCapabilities

#: The section a key with no catalogue entry lands in. Only served when something is in it.
OTHER_SECTION: Final = "other"

#: Panels the console mounts inside a section, by id. The console maps each id to its
#: component and says so plainly when it meets an id it does not know.
PANEL_RATE_CARD: Final = "rate_card"
PANEL_FX_RATE: Final = "fx_rate"
PANEL_NUMBER_PRICE: Final = "number_price"
PANEL_TTS_PLAN_FEE: Final = "tts_plan_fee"
PANEL_ENGINE_MINUTE_PRICE: Final = "engine_minute_price"
PANEL_MODEL_PRICING: Final = "model_pricing"
PANEL_DASHBOARD_DATA_USE: Final = "dashboard_data_use"
PANEL_SERVER_ONLY_KEYS: Final = "server_only_keys"


@dataclass(frozen=True, slots=True)
class Subsection:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    label: str
    #: One line under the section heading.
    hint: str
    subsections: tuple[Subsection, ...] = ()
    #: Panels rendered above the section's settings, then below them.
    panels_before: tuple[str, ...] = ()
    panels_after: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EngineScope:
    """A setting only some engines read, and the sentence that says which."""

    sentence: str
    applies: Callable[[str, EngineCapabilities], bool]


@dataclass(frozen=True, slots=True)
class FieldMeta:
    section: str
    subsection: str
    label: str
    description: str
    used_when: EngineScope | None = None


SECTIONS: Final[tuple[Section, ...]] = (
    Section(
        "voice-engine",
        "Voice engine",
        "Which platform runs each conversation, and the addresses it uses to reach us.",
        (
            Subsection("engine", "Active engine"),
            Subsection("thinnest", "ThinnestAI"),
            Subsection("pipecat", "Our own runtime (Pipecat)"),
            Subsection("cartesia", "Cartesia"),
        ),
        panels_after=(PANEL_ENGINE_MINUTE_PRICE,),
    ),
    Section(
        "telephony",
        "Telephony and carrier",
        "Which carrier carries our own runtime's calls, how its callbacks are trusted, and "
        "who may sell us numbers.",
        (
            Subsection("carrier", "Carrier"),
            Subsection("callbacks", "Callback security"),
            Subsection("features", "Call features"),
            Subsection("numbers", "Phone numbers"),
        ),
    ),
    Section(
        "calling-limits",
        "Calling limits and pacing",
        "How fast outbound calls start and how many lines they may use at once.",
        (Subsection("limits", "Limits"),),
    ),
    Section(
        "language-models",
        "Language models and tiers",
        "Which model answers each client tier, the platform default, and the Azure "
        "deployments behind them.",
        (
            Subsection("tiers", "Client tiers"),
            Subsection("default", "Platform default"),
            Subsection("azure", "Azure OpenAI"),
        ),
        panels_after=(PANEL_MODEL_PRICING, PANEL_DASHBOARD_DATA_USE),
    ),
    Section(
        "speech",
        "Speech",
        "How callers are transcribed, and how many agents may use the Studio voice.",
        (
            Subsection("stt", "Speech-to-text (STT)"),
            Subsection("tts", "Text-to-speech (TTS)"),
        ),
    ),
    Section(
        "knowledge",
        "Knowledge search",
        "Which store answers knowledge-base lookups outside a call, and any shadow comparison.",
        (
            Subsection("store", "Store"),
            Subsection("shadow", "Shadow comparison"),
        ),
    ),
    Section(
        "billing",
        "Billing and pricing",
        "What a minute sells for, the exchange-rate fallback, payments and invoice identity.",
        (
            Subsection("prices", "Prices"),
            Subsection("payments", "Payments"),
            Subsection("invoices", "Invoices (GST)"),
        ),
        panels_before=(PANEL_RATE_CARD,),
        panels_after=(PANEL_FX_RATE, PANEL_NUMBER_PRICE, PANEL_TTS_PLAN_FEE),
    ),
    Section(
        "compliance",
        "Compliance",
        "How long consent and registration checks stay valid, and who verifies identity.",
        (Subsection("checks", "Checks"),),
    ),
    Section(
        "integrations",
        "Integrations",
        "Lead sources and outside services clients connect to.",
        (
            Subsection("leads", "Lead sources and CRM"),
            Subsection("google", "Google sign-in for calendars"),
        ),
    ),
    Section(
        "notifications",
        "Notifications",
        "Where client email, hot-lead alerts and operator alarms are sent from and to.",
        (
            Subsection("email", "Email"),
            Subsection("alerts", "Operator alerts and notices"),
            Subsection("whatsapp", "WhatsApp"),
        ),
    ),
    Section(
        "security",
        "Security and access",
        "The switch over all sign-in, and whether new clients can sign themselves up.",
        (Subsection("access", "Access"),),
    ),
    Section(
        "infrastructure",
        "Infrastructure",
        "Database, storage, and the settings only the server's environment can hold.",
        (
            Subsection("database", "Database"),
            Subsection("storage", "Object storage"),
        ),
        panels_after=(PANEL_SERVER_ONLY_KEYS,),
    ),
    Section(
        "observability",
        "Observability",
        "Tracing, the release name on error reports, and certificate monitoring.",
        (
            Subsection("tracing", "Tracing"),
            Subsection("monitoring", "Monitoring"),
        ),
    ),
    Section(
        OTHER_SECTION,
        "Other",
        "Settings this release has not filed under a section yet. Editable like any other.",
        (Subsection("other", "Other"),),
    ),
)

_OWNED_RUNTIME = EngineScope(
    "Used only when calls run on our own voice runtime (Pipecat) through our carrier.",
    lambda _name, caps: caps.agent_hosting == "owned_runtime",
)
_OUR_STT = EngineScope(
    "Used only when the voice engine transcribes with our speech-to-text settings.",
    lambda _name, caps: caps.is_ours("stt"),
)
_THINNEST = EngineScope(
    "Used only when the voice engine is ThinnestAI.",
    lambda name, _caps: name == "thinnest",
)
_CARTESIA = EngineScope(
    "Used only when the voice engine is Cartesia.",
    lambda name, _caps: name == "cartesia",
)


def _m(
    section: str,
    subsection: str,
    label: str,
    description: str,
    used_when: EngineScope | None = None,
) -> FieldMeta:
    return FieldMeta(section, subsection, label, description, used_when)


FIELD_META: Final[dict[str, FieldMeta]] = {
    # ---- voice engine ----------------------------------------------------------------
    "engine": _m(
        "voice-engine",
        "engine",
        "Active voice engine",
        "The platform every new call and agent publish goes through.",
    ),
    "webhook_base_url": _m(
        "voice-engine",
        "engine",
        "Webhook base URL",
        "Public address of the voice runtime that engines and carriers send call events to.",
    ),
    "engine_actions_base_url": _m(
        "voice-engine",
        "thinnest",
        "In-call actions base URL",
        "Public https address of our API that ThinnestAI calls for in-call tools.",
        _THINNEST,
    ),
    "thinnest_byok_enabled": _m(
        "voice-engine",
        "thinnest",
        "ThinnestAI runs on our own keys (BYOK)",
        "Turn on only after all three legs are set up in ThinnestAI; minutes then bill at "
        "the BYOK rate.",
        _THINNEST,
    ),
    "thinnest_clear_voice_band": _m(
        "voice-engine",
        "thinnest",
        "Voice band sold as Clear",
        "Which ThinnestAI voices are offered as Clear: Premium (any plan) or Studio (Pro and "
        "above). Attest that band's per-minute rate before offering it.",
        _THINNEST,
    ),
    "pipecat_stream_base_url": _m(
        "voice-engine",
        "pipecat",
        "Voice worker stream URL",
        "The wss:// address of our deployed voice worker that answered calls are streamed to.",
        _OWNED_RUNTIME,
    ),
    "cartesia_from_number_id": _m(
        "voice-engine",
        "cartesia",
        "Cartesia caller ID",
        "Cartesia's id for the outbound caller number; outbound calls are refused while unset.",
        _CARTESIA,
    ),
    # ---- telephony -------------------------------------------------------------------
    "carrier": _m(
        "telephony",
        "carrier",
        "Active telephony carrier",
        "The carrier our own runtime dials on and binds numbers to.",
        _OWNED_RUNTIME,
    ),
    "vobiz_api_base_url": _m(
        "telephony",
        "carrier",
        "Vobiz API URL",
        "The Vobiz REST address; change it only to point at a test double.",
        _OWNED_RUNTIME,
    ),
    "vobiz_signature_required": _m(
        "telephony",
        "callbacks",
        "Require Vobiz request signatures",
        "Refuse Vobiz callbacks without a valid signature. Turning it on before signing is "
        "set up refuses every call.",
        _OWNED_RUNTIME,
    ),
    "vobiz_callback_ips": _m(
        "telephony",
        "callbacks",
        "Vobiz callback IPs (override)",
        "Comma-separated source addresses to accept Vobiz callbacks from; unset uses the "
        "published list.",
        _OWNED_RUNTIME,
    ),
    "carrier_transfer_enabled": _m(
        "telephony",
        "features",
        "Transfer callers to a human",
        "Treat the carrier's transfer contract as verified. Off until it is.",
        _OWNED_RUNTIME,
    ),
    "carrier_recording_enabled": _m(
        "telephony",
        "features",
        "Record calls with the carrier",
        "Whether the carrier records calls. Agents follow the change when they are republished.",
        _OWNED_RUNTIME,
    ),
    "number_provider": _m(
        "telephony",
        "numbers",
        "Phone-number provider",
        "Which telephony vendor may sell this deployment a phone number.",
    ),
    # ---- calling limits --------------------------------------------------------------
    "carrier_cps": _m(
        "calling-limits",
        "limits",
        "Outbound calls started per second (CPS)",
        "At most this many dials start each second, matching the carrier account's limit.",
        _OWNED_RUNTIME,
    ),
    "carrier_concurrency": _m(
        "calling-limits",
        "limits",
        "Simultaneous calls on the carrier account",
        "Inbound and outbound together; the carrier refuses a dial over this.",
        _OWNED_RUNTIME,
    ),
    "thinnest_max_concurrent_calls": _m(
        "calling-limits",
        "limits",
        "Simultaneous calls on the ThinnestAI workspace",
        "Inbound and outbound together; set it to the ceiling ThinnestAI has confirmed.",
        _THINNEST,
    ),
    "thinnest_customer_plan": _m(
        "voice-engine",
        "thinnest",
        "ThinnestAI plan",
        "The plan our ThinnestAI account is on. It decides how many clients can have their "
        "own voice workspace: 3 on pay-as-you-go, 100 on Pro, 1,000 on Scale.",
        _THINNEST,
    ),
    "thinnest_developer_workspace_id": _m(
        "voice-engine",
        "thinnest",
        "ThinnestAI developer workspace id",
        "Our own ThinnestAI workspace id (org_…, Settings → General in their console). It is "
        "never treated as a client's own workspace.",
        _THINNEST,
    ),
    "inbound_reserve_ratio": _m(
        "calling-limits",
        "limits",
        "Share of lines kept free for inbound calls",
        "A fraction from 0 to 1 of the line limit that outbound calls may not use; at least "
        "one line always stays free.",
    ),
    # ---- language models -------------------------------------------------------------
    "llm_tier_standard_model": _m(
        "language-models",
        "tiers",
        "Standard tier model",
        "The model a client gets when they choose Standard. Only new choices move.",
    ),
    "llm_tier_plus_model": _m(
        "language-models",
        "tiers",
        "Plus tier model",
        "The model a client gets when they choose Plus. Only new choices move.",
    ),
    "llm_tier_pro_model": _m(
        "language-models",
        "tiers",
        "Pro tier model",
        "The model a client gets when they choose Pro. Only new choices move.",
    ),
    "platform_llm_model": _m(
        "language-models",
        "default",
        "Platform default LLM",
        "What an account runs when neither it nor its agent chose a model.",
    ),
    "azure_openai_resource": _m(
        "language-models",
        "azure",
        "Azure OpenAI resource",
        "The Azure OpenAI resource name: the first label of its endpoint hostname.",
    ),
    "azure_openai_deployment": _m(
        "language-models",
        "azure",
        "Azure OpenAI deployment",
        "The deployment id calls address; it must serve the Azure model below.",
    ),
    "azure_openai_model": _m(
        "language-models",
        "azure",
        "Model behind the Azure deployment",
        "Which model the deployment above was made from. Prices the leg; move it with the "
        "deployment.",
    ),
    "azure_openai_deployments": _m(
        "language-models",
        "azure",
        "Other Azure deployments",
        "model=deployment pairs, comma-separated, for every other Azure model clients may choose.",
    ),
    "azure_openai_embedding_deployment": _m(
        "language-models",
        "azure",
        "Azure embedding deployment",
        "The deployment that serves embeddings for knowledge search.",
    ),
    # ---- speech ----------------------------------------------------------------------
    "sarvam_stt_model": _m(
        "speech",
        "stt",
        "Sarvam STT model",
        "The transcriber every agent is published with.",
        _OUR_STT,
    ),
    "stt_autodetect_language": _m(
        "speech",
        "stt",
        "Detect the caller's language",
        "Let the transcriber detect the spoken language instead of pinning it. Off until "
        "it is proven on a real call.",
        _OUR_STT,
    ),
    "cartesia_agent_cap": _m(
        "speech",
        "tts",
        "Live agents allowed on the Studio voice",
        "Platform-wide ceiling on live agents using a Cartesia (Studio) voice; 0 switches it off.",
    ),
    # ---- knowledge -------------------------------------------------------------------
    "retrieval_provider": _m(
        "knowledge",
        "store",
        "Knowledge search store",
        "Which store answers a knowledge lookup outside a call. Calls are not affected.",
    ),
    "supermemory_base_url": _m(
        "knowledge",
        "store",
        "Supermemory URL",
        "Where a self-hosted Supermemory answers, if this deployment has one.",
    ),
    "supermemory_embedding_model": _m(
        "knowledge",
        "store",
        "Supermemory embedding model",
        "The model the Supermemory install embeds with, so its cost can be priced.",
    ),
    "retrieval_shadow_arm": _m(
        "knowledge",
        "shadow",
        "Shadow comparison store",
        "A second store asked the same question in the background; clients are always "
        "served by the main one.",
    ),
    "retrieval_shadow_tenant_ids": _m(
        "knowledge",
        "shadow",
        "Accounts in the shadow comparison",
        "Comma-separated account ids whose lookups are compared. Empty means none.",
    ),
    # ---- billing ---------------------------------------------------------------------
    "self_serve_inr_per_min": _m(
        "billing",
        "prices",
        "Self-serve price per minute (INR)",
        "The self-serve list price per calling minute. Recording a rate card rewrites it.",
    ),
    "usd_inr_rate": _m(
        "billing",
        "prices",
        "USD to INR fallback rate",
        "Used for dollar-priced costs only when no fresh published rate has been pulled.",
    ),
    "payment_provider": _m(
        "billing",
        "payments",
        "Payment provider",
        "Which payment provider takes prepaid top-ups.",
    ),
    "razorpay_key_id": _m(
        "billing",
        "payments",
        "Razorpay key ID",
        "The public key id handed to the browser checkout.",
    ),
    "gst_supplier_legal_name": _m(
        "billing",
        "invoices",
        "Supplier legal name",
        "Our legal name as printed on every invoice.",
    ),
    "gst_supplier_address": _m(
        "billing",
        "invoices",
        "Supplier registered address",
        "Our registered address as printed on every invoice.",
    ),
    "gst_supplier_gstin": _m(
        "billing",
        "invoices",
        "Supplier GSTIN",
        "Unset while we are not GST-registered; documents then render as a bill of supply.",
    ),
    "gst_supply_sac": _m(
        "billing",
        "invoices",
        "Service accounting code (SAC)",
        "The SAC our supply is classified under, as the accountant decides.",
    ),
    # ---- compliance ------------------------------------------------------------------
    "campaign_consent_max_age_days": _m(
        "compliance",
        "checks",
        "Maximum consent age for a campaign (days)",
        "A campaign over a list whose consent is older than this is refused. 0 turns the "
        "age check off.",
    ),
    "pe_verification_max_age_days": _m(
        "compliance",
        "checks",
        "How long a DLT PE verification stays valid (days)",
        "After this, a principal-entity registration must be re-verified. 0 turns the check off.",
    ),
    "kyc_verification_provider": _m(
        "compliance",
        "checks",
        "KYC verification provider",
        "The DigiLocker provider (cashfree). Unset means document review only; list it as a "
        "sub-processor first.",
    ),
    "kyc_verification_client_id": _m(
        "compliance",
        "checks",
        "KYC provider client ID",
        "The DigiLocker provider's API client ID. With the client secret it switches the "
        "DigiLocker option on; absent, clients see it as not available yet.",
    ),
    "kyc_verification_environment": _m(
        "compliance",
        "checks",
        "KYC provider environment",
        "production for real verifications; sandbox only with a test account.",
    ),
    # ---- integrations ----------------------------------------------------------------
    "google_sheets_provider": _m(
        "integrations",
        "leads",
        "Google Sheets delivery",
        "How leads are appended to a client's Google Sheet.",
    ),
    "meta_lead_retriever": _m(
        "integrations",
        "leads",
        "Meta Lead Ads retrieval",
        "How lead answers are fetched from Meta; unset means they are not fetched.",
    ),
    "google_oauth_client_id": _m(
        "integrations",
        "google",
        "Google OAuth client ID",
        "The platform's Google OAuth client that calendar connections authorise against.",
    ),
    "google_oauth_redirect_uri": _m(
        "integrations",
        "google",
        "Google OAuth redirect URL",
        "Where Google returns a client after they authorise a calendar.",
    ),
    # ---- notifications ---------------------------------------------------------------
    "email_provider": _m(
        "notifications",
        "email",
        "Email provider",
        "Which transport sends all mail: resend, or smtp as the fallback.",
    ),
    "smtp_host": _m(
        "notifications",
        "email",
        "SMTP host",
        "Used only when the email provider is smtp.",
    ),
    "smtp_port": _m(
        "notifications",
        "email",
        "SMTP port",
        "Used only when the email provider is smtp.",
    ),
    "smtp_username": _m(
        "notifications",
        "email",
        "SMTP username",
        "Used only when the email provider is smtp.",
    ),
    "smtp_use_tls": _m(
        "notifications",
        "email",
        "SMTP uses TLS",
        "Used only when the email provider is smtp.",
    ),
    "notifications_from": _m(
        "notifications",
        "email",
        "Send mail from",
        "The sender address. Its domain must be verified with the provider or mail stops.",
    ),
    "notifications_reply_to": _m(
        "notifications",
        "email",
        "Replies go to",
        "The Reply-To address: a mailbox a person reads. Unset sends replies to the sender.",
    ),
    "alerts_email": _m(
        "notifications",
        "alerts",
        "Operator alert email",
        "Where operator alerts are delivered. Unset means alerts are only logged.",
    ),
    "maintenance_notice_lead_hours": _m(
        "notifications",
        "alerts",
        "Maintenance notice lead time (hours)",
        "How far ahead clients are told about a planned maintenance window.",
    ),
    "whatsapp_enabled": _m(
        "notifications",
        "whatsapp",
        "WhatsApp hot-lead alerts",
        "Send hot-lead alerts on WhatsApp. Keep off until the business checklist is done.",
    ),
    "whatsapp_provider": _m(
        "notifications",
        "whatsapp",
        "WhatsApp provider",
        "Which WhatsApp transport sends the alerts.",
    ),
    "whatsapp_template_hot_lead": _m(
        "notifications",
        "whatsapp",
        "Hot-lead template name",
        "The approved template's name as registered with the provider.",
    ),
    "whatsapp_template_locale": _m(
        "notifications",
        "whatsapp",
        "Hot-lead template language",
        "The approved template's language tag.",
    ),
    "whatsapp_cloud_phone_number_id": _m(
        "notifications",
        "whatsapp",
        "WhatsApp sending number ID",
        "The sending number's id from the Meta console.",
    ),
    "whatsapp_cloud_graph_version": _m(
        "notifications",
        "whatsapp",
        "Meta Graph API version",
        "The pinned Graph API version, such as v22.0.",
    ),
    # ---- security --------------------------------------------------------------------
    "first_party_auth_enabled": _m(
        "security",
        "access",
        "Sign-in enabled",
        "The kill switch over all sign-in. Off locks everyone out, operators included.",
    ),
    "self_serve_signup_enabled": _m(
        "security",
        "access",
        "Self-serve sign-up",
        "Whether new clients can sign themselves up.",
    ),
    # ---- infrastructure --------------------------------------------------------------
    "db_pool_size": _m(
        "infrastructure",
        "database",
        "Database connection pool size",
        "Connections each process keeps open. Read from the environment at start-up only.",
    ),
    "db_statement_timeout_ms": _m(
        "infrastructure",
        "database",
        "Database statement timeout (ms)",
        "How long one query may run before it is cancelled.",
    ),
    "object_store_endpoint": _m(
        "infrastructure",
        "storage",
        "Object storage URL",
        "The S3-compatible storage endpoint the platform writes files to.",
    ),
    "object_store_bucket": _m(
        "infrastructure",
        "storage",
        "Storage bucket",
        "The bucket the platform writes files to.",
    ),
    # ---- observability ---------------------------------------------------------------
    "otel_exporter_otlp_endpoint": _m(
        "observability",
        "tracing",
        "OpenTelemetry collector URL",
        "Base URL of the OTLP/HTTP collector. Unset means no tracing at all.",
    ),
    "otel_traces_sample_ratio": _m(
        "observability",
        "tracing",
        "Trace sampling ratio",
        "The share of root traces kept, from 0 to 1; a sampled call is traced end to end.",
    ),
    "release_version": _m(
        "observability",
        "monitoring",
        "Release name",
        "Stamped on every error report and trace so it names the deploy.",
    ),
    "tls_origin_address": _m(
        "observability",
        "monitoring",
        "TLS origin to monitor",
        "host:port of the origin server whose certificate expiry is checked daily.",
    ),
}

#: Words that keep a fixed spelling when a key is humanised. Lower-case key → spelling.
_FIXED_WORDS: Final[dict[str, str]] = {
    "api": "API",
    "url": "URL",
    "urls": "URLs",
    "kek": "KEK",
    "byok": "BYOK",
    "dlt": "DLT",
    "tts": "TTS",
    "stt": "STT",
    "llm": "LLM",
    "id": "ID",
    "ids": "IDs",
    "db": "database",
    "tls": "TLS",
    "otel": "OpenTelemetry",
    "otlp": "OTLP",
    "smtp": "SMTP",
    "gst": "GST",
    "gstin": "GSTIN",
    "sac": "SAC",
    "cps": "CPS",
    "inr": "INR",
    "usd": "USD",
    "kyc": "KYC",
    "pe": "PE",
    "dsn": "DSN",
    "ips": "IPs",
    "oauth": "OAuth",
    "json": "JSON",
}

#: Product names. Pairs rather than entries in `_FIXED_WORDS` because several are engine
#: names, and a dict keyed by them reads to `tests/engine_name_drift_test.py` as a second
#: copy of the engine set, which a spelling table is not.
_BRAND_SPELLINGS: Final[tuple[tuple[str, str], ...]] = (
    ("openai", "OpenAI"),
    ("thinnest", "ThinnestAI"),
    ("vobiz", "Vobiz"),
    ("plivo", "Plivo"),
    ("pipecat", "Pipecat"),
    ("cartesia", "Cartesia"),
    ("sarvam", "Sarvam"),
    ("gnani", "Gnani"),
    ("azure", "Azure"),
    ("redis", "Redis"),
    ("alembic", "Alembic"),
    ("resend", "Resend"),
    ("whatsapp", "WhatsApp"),
)
_FIXED_WORDS.update(_BRAND_SPELLINGS)

#: Words that are always capitalised in a label, whatever position they take.
FIXED_SPELLINGS: Final[frozenset[str]] = frozenset(
    spelling for spelling in _FIXED_WORDS.values() if spelling.lower() != spelling
)


def humanise(key: str) -> str:
    """A plain name for a key with no catalogue entry, acronyms spelled correctly."""
    words = [_FIXED_WORDS.get(word, word) for word in re.split(r"_+", key.strip("_")) if word]
    if not words:
        return key
    first = words[0]
    words[0] = first if first in FIXED_SPELLINGS else first[:1].upper() + first[1:]
    return " ".join(words)


def meta_for(key: str) -> FieldMeta:
    """The catalogue entry for `key`, or an "Other" entry with a humanised label."""
    return FIELD_META.get(
        key,
        FieldMeta(
            OTHER_SECTION,
            "other",
            humanise(key),
            "This release has no description for this setting yet.",
        ),
    )


__all__ = [
    "FIELD_META",
    "FIXED_SPELLINGS",
    "OTHER_SECTION",
    "PANEL_DASHBOARD_DATA_USE",
    "PANEL_ENGINE_MINUTE_PRICE",
    "PANEL_FX_RATE",
    "PANEL_MODEL_PRICING",
    "PANEL_NUMBER_PRICE",
    "PANEL_RATE_CARD",
    "PANEL_SERVER_ONLY_KEYS",
    "PANEL_TTS_PLAN_FEE",
    "SECTIONS",
    "EngineScope",
    "FieldMeta",
    "Section",
    "Subsection",
    "humanise",
    "meta_for",
]
