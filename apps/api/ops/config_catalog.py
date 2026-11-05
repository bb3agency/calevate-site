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
PANEL_IN_CALL_DATA_USE: Final = "in_call_data_use"
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
    #: One plain line, at most `DESCRIPTION_MAX` characters: what the setting does.
    description: str
    used_when: EngineScope | None = None
    #: What an engineer needs and the operator does not decide on (a vendor's field name,
    #: the source and date of a vendor figure, a side effect). Shown under "Details".
    details: str | None = None


#: The longest a setting's description may be: one line in the console's description column.
DESCRIPTION_MAX: Final = 100


SECTIONS: Final[tuple[Section, ...]] = (
    Section(
        "voice-engine",
        "Voice engine",
        "Which platform runs each conversation, and the addresses it uses to reach us.",
        (
            Subsection("engine", "Active engine"),
            Subsection("thinnest", "ThinnestAI"),
            # Platform-wide targets and limits on how agents answer, whichever engine runs.
            Subsection("quality", "Call quality"),
        ),
        panels_after=(PANEL_ENGINE_MINUTE_PRICE,),
    ),
    Section(
        "telephony",
        "Telephony",
        "Who may sell us numbers on an engine that rents none of its own.",
        (Subsection("numbers", "Phone numbers"),),
    ),
    Section(
        "calling-limits",
        "Calling limits and pacing",
        "How fast outbound calls start and how many lines they may use at once.",
        (Subsection("limits", "Limits"), Subsection("trial", "Free trials")),
    ),
    Section(
        "language-models",
        "Language models and tiers",
        "Which model answers each client tier, the platform default, and the Azure "
        "deployments behind them.",
        (
            Subsection("tiers", "Client tiers"),
            Subsection("assistant", "In-app assistant"),
            Subsection("default", "Platform default"),
            Subsection("azure", "Azure OpenAI"),
        ),
        panels_after=(PANEL_MODEL_PRICING, PANEL_IN_CALL_DATA_USE, PANEL_DASHBOARD_DATA_USE),
    ),
    Section(
        "speech",
        "Speech",
        "How callers are transcribed, how many agents may use the Studio voice, and which "
        "languages clients may give an agent.",
        (
            Subsection("stt", "Speech-to-text (STT)"),
            Subsection("tts", "Text-to-speech (TTS)"),
            Subsection("languages", "Agent languages"),
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
            Subsection("leads", "Lead sources"),
            Subsection("crm", "CRM connections"),
            Subsection("google", "Google: calendars, sign-in and file picker"),
            Subsection("client_whatsapp", "Clients' WhatsApp (Meta Embedded Signup)"),
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
        "healer",
        "Auto-healer",
        "The automatic repairs, their kill switches, and where alarm pages go.",
        (
            Subsection("switches", "Kill switches"),
            Subsection("paging", "Paging"),
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

_TEST_ENGINE = EngineScope(
    "Used only on the test engine: ThinnestAI holds its own numbers and call ceiling.",
    lambda name, _caps: name != "thinnest",
)
_OUR_STT = EngineScope(
    "Used only when the voice engine transcribes with our speech-to-text settings.",
    lambda _name, caps: caps.is_ours("stt"),
)
_THINNEST = EngineScope(
    "Used only when the voice engine is ThinnestAI.",
    lambda name, _caps: name == "thinnest",
)


def _m(
    section: str,
    subsection: str,
    label: str,
    description: str,
    used_when: EngineScope | None = None,
    *,
    details: str | None = None,
) -> FieldMeta:
    return FieldMeta(section, subsection, label, description, used_when, details)


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
        "Public address of the voice runtime that the engine sends call events to.",
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
        "ThinnestAI runs on all three of our own keys",
        "Speech, model and voice all on our keys. On: every minute bills at ₹1.",
        _THINNEST,
        details=(
            "Not our Studio tier. The keys are set in ThinnestAI's console or API. While on, per-"
            "agent voice and model choices lock."
        ),
    ),
    "thinnest_clear_voice_band": _m(
        "voice-engine",
        "thinnest",
        "ThinnestAI voice band sold as Clear",
        "The ThinnestAI band sold to clients as Clear: Studio (the default) or Premium.",
        _THINNEST,
        details=(
            "Not our Studio tier. Attest the band's per-minute rate before switching. The Studio "
            "band is on our pay-as-you-go account since 23 Oct 2026 (VENDOR-STATED, ThinnestAI "
            "replies §28.1)."
        ),
    ),
    "thinnest_in_call_default_model": _m(
        "voice-engine",
        "thinnest",
        "In-call language model for agents with none chosen",
        "Model for agents with none of their own; an agent's choice wins. Empty keeps Prana "
        "[Voice].",
        _THINNEST,
        details="Must be call-capable, priced, and allowed with Studio voices.",
    ),
    "thinnest_own_model": _m(
        "voice-engine",
        "thinnest",
        "Agents answer on our own Gemini model",
        "On: every agent, trial ones included, answers on our Google key.",
        _THINNEST,
        details=(
            "Clear keeps ThinnestAI's voice; Studio keeps our Cartesia voice. Refused until the "
            "Voices screen shows it ready."
        ),
    ),
    "thinnest_own_model_default": _m(
        "voice-engine",
        "thinnest",
        "Our language model for agents with none chosen",
        "The Gemini model agents on our own model use when they name none.",
        _THINNEST,
        details=(
            "Needs our Google key and an attested price. Gemini 2.5 ids are refused on our Google "
            "project (Google's models page, 13 Oct 2026; REPORTED in agents/assist_leg.py, D-786, "
            "not re-checked since)."
        ),
    ),
    "thinnest_reply_length": _m(
        "voice-engine",
        "thinnest",
        "Longest agent reply, in tokens",
        "Longest reply, 100 to 800 tokens, for agents with no length of their own. Keep it high.",
        _THINNEST,
        details=(
            "A reply that reaches it is cut off mid-sentence. 800 by default; ThinnestAI's own "
            "default is 300."
        ),
    ),
    "thinnest_own_rules": _m(
        "voice-engine",
        "thinnest",
        "Agents follow only our hand-over and lead rules",
        "On: ThinnestAI stops adding its lead, hand-over and call-back lines; ours state them.",
        _THINNEST,
        details="ThinnestAI's name for it is ownRules.",
    ),
    "thinnest_test_chat_call_mode": _m(
        "voice-engine",
        "thinnest",
        "Practice tests run as a call",
        "On: practice tests use the agent's call prompt, model and thinking level.",
        _THINNEST,
        details=(
            "Needs calling set up on the agent. ThinnestAI's name for it is Test Chat call mode."
        ),
    ),
    "thinnest_call_instructions": _m(
        "voice-engine",
        "thinnest",
        "Agents use our shorter call rules",
        "On: our call rules replace ThinnestAI's default ones, which are read on every turn.",
        _THINNEST,
        details=(
            "Ours are about 1,675 characters. Try a Telugu agent in practice tests (call mode) "
            "first. ThinnestAI's name for it is callInstructions."
        ),
    ),
    "thinnest_turn_detection": _m(
        "voice-engine",
        "thinnest",
        "How agents know the caller has finished",
        "Silence: the pause after the caller's last words ends the turn. Ear: live listening does.",
        _THINNEST,
        details="Under Ear the turn still ends only after that same pause, set in Call handling.",
    ),
    "thinnest_timer_turn_silence_ms": _m(
        "voice-engine",
        "thinnest",
        "Pause for an agent put on Silence on its own",
        "Pause after the caller's last words, used when the agent and account set none.",
        _THINNEST,
        details="ThinnestAI suggests 350-400 ms to start.",
    ),
    "thinnest_opening_wait_ms": _m(
        "voice-engine",
        "thinnest",
        "Silence before a waiting opening plays",
        "For agents that wait for hello: the silence before they speak first.",
        _THINNEST,
        details="Unset, nothing is sent and ThinnestAI waits 4 s.",
    ),
    "thinnest_acknowledgements": _m(
        "voice-engine",
        "thinnest",
        'Agents say "haan ji" while callers explain',
        "Only when turns end by ear. Spoken in the agent's voice and billed as voice "
        "characters on Studio.",
        _THINNEST,
    ),
    "thinnest_early_answers": _m(
        "voice-engine",
        "thinnest",
        "Agents start replying before the caller has finished",
        "On: replies start before the caller has finished. Off: they wait till the caller is done.",
        _THINNEST,
        details=(
            "A reply dropped because the caller kept talking is still billed to our Google key, "
            "outside usage."
        ),
    ),
    "thinnest_interrupt_words": _m(
        "voice-engine",
        "thinnest",
        "Words a caller must say to stop the agent",
        'Fewer stops it on a short answer like "Saturday". Under Ear, "haan ji" and '
        '"okay" never stop it.',
        _THINNEST,
    ),
    "reply_time_typical_target_ms": _m(
        "voice-engine",
        "quality",
        "Typical wait for an answer",
        "How long a caller should usually wait for the first word of the answer.",
        _THINNEST,
        details="Judged on each call's typical wait. A filler line does not count as the answer.",
    ),
    "reply_time_slow_target_ms": _m(
        "voice-engine",
        "quality",
        "Slow wait for an answer",
        "A call is over target when more than one wait in ten was longer than this.",
        _THINNEST,
        details="A filler line does not count as the answer.",
    ),
    "public_quality_page_enabled": _m(
        "voice-engine",
        "quality",
        "Public reply speed page",
        "On: a public page shows the platform's reply speed. Off: no public page does.",
        details="The admin Reply speed by language screen shows the figures either way.",
    ),
    "hot_facts_enabled": _m(
        "voice-engine",
        "quality",
        "Agents know the most asked facts by heart",
        "On: the most asked facts sit in each agent's instructions. Off: every fact is looked up.",
        _THINNEST,
        details="Answering from the instructions skips a search of about a second.",
    ),
    "hot_facts_max_chars": _m(
        "voice-engine",
        "quality",
        "Most characters of facts known by heart",
        "Caps what the facts known by heart add to a call's cost.",
        _THINNEST,
        details=(
            "Each character is read again on every reply. Agents use less when their script leaves"
            " less room."
        ),
    ),
    # ---- telephony -------------------------------------------------------------------
    "number_provider": _m(
        "telephony",
        "numbers",
        "Phone-number provider",
        "Which telephony vendor may sell this deployment a phone number.",
        _TEST_ENGINE,
    ),
    # ---- calling limits --------------------------------------------------------------
    "carrier_concurrency": _m(
        "calling-limits",
        "limits",
        "Simultaneous calls on the test engine",
        "Inbound and outbound together, on an engine with no call ceiling of its own.",
        _TEST_ENGINE,
    ),
    "thinnest_max_concurrent_calls": _m(
        "calling-limits",
        "limits",
        "Simultaneous calls on the ThinnestAI workspace",
        "Calls at once across every client, inbound and outbound. Set what ThinnestAI granted.",
        _THINNEST,
        details=(
            "ThinnestAI set 20 on our pay-as-you-go account on 23 Oct 2026, and on 30 Oct said it "
            "was increased again without a figure (VENDOR-STATED, docs/vendor/thinnest-"
            "replies-2026-10-12.md §28.1 and §41). Never set it above what ThinnestAI has "
            "confirmed."
        ),
    ),
    "trial_caller_number": _m(
        "calling-limits",
        "trial",
        "Shared trial number",
        "The number free-trial test calls ring from, rented in our ThinnestAI workspace.",
        _THINNEST,
        details="No AI answers it; a caller ringing back hears that it only places test calls.",
    ),
    "trial_daily_call_cap": _m(
        "calling-limits",
        "trial",
        "Test calls per trial account per day",
        "How many test calls one trial account may place in an IST day.",
        _THINNEST,
    ),
    "trial_call_max_seconds": _m(
        "calling-limits",
        "trial",
        "Longest trial test call",
        "Each trial test call is ended after this long, between 1 and 20 minutes.",
        _THINNEST,
    ),
    "trial_studio_minutes": _m(
        "calling-limits",
        "trial",
        "Studio minutes per trial account",
        "Minutes of Studio-voice test calls one trial account may make. 0 allows none.",
        _THINNEST,
        details="They cost us more. Once used, Studio test calls are refused and Clear ones go on.",
    ),
    "paid_test_copy_idle_days": _m(
        "calling-limits",
        "trial",
        "Days a paid account's test copy may sit unused",
        "Days before an unused test copy of a paying client's agent is removed.",
        _THINNEST,
        details=(
            "A paying client's test calls ride a copy of its agent until it has a number. The next"
            " test call makes the copy again."
        ),
    ),
    "staged_agent_languages_enabled": _m(
        "speech",
        "languages",
        "Extra agent languages offered to clients",
        "Offers Tamil, Kannada, Malayalam and Marathi to clients, each saying what it still needs.",
        details="Each stays hidden until it is reviewed, test-called and confirmed by ThinnestAI.",
    ),
    "staged_language_test_tenant_ids": _m(
        "speech",
        "languages",
        "Test accounts for the extra languages",
        "Our own test accounts, offered an extra language for its test call. Never a client.",
        details="Offered once that language's sentences are reviewed.",
    ),
    "forwarding_test_second_number": _m(
        "calling-limits",
        "trial",
        "Second number for forwarding tests",
        "A number we rent that rings with the trial number in a forwarding test. Unset: one call.",
        _THINNEST,
        details=(
            "The test rings the client's number from both at once, to check two callers get "
            "through."
        ),
    ),
    "forwarding_test_daily_cap": _m(
        "calling-limits",
        "trial",
        "Forwarding tests per client per day",
        "How many forwarding tests one client may run in an IST day. Each test is a short "
        "call we pay for.",
        _THINNEST,
    ),
    "self_serve_trial_days": _m(
        "calling-limits",
        "trial",
        "Free trial days for a new account",
        "Free trial days every new account starts with. A trial you set for a client replaces it.",
        details="Applies whether the business signed itself up or was invited.",
    ),
    "self_serve_trial_free_minutes": _m(
        "calling-limits",
        "trial",
        "Free trial minutes for a new account",
        "Free test-call minutes every new account starts with. A trial you set replaces it.",
        details="Applies whether the business signed itself up or was invited.",
    ),
    "thinnest_action_source_ips": _m(
        "voice-engine",
        "thinnest",
        "Where in-call actions come from",
        "Comma-separated addresses ThinnestAI sends in-call actions from.",
        _THINNEST,
        details=(
            "A call from another address is still served when it carries the agent's right secret,"
            " and raises one alarm, so bookings never stop."
        ),
    ),
    "thinnest_customer_plan": _m(
        "voice-engine",
        "thinnest",
        "ThinnestAI plan",
        "The plan our ThinnestAI account is on. Each option says how many client workspaces it "
        "allows.",
        _THINNEST,
    ),
    "thinnest_developer_workspace_id": _m(
        "voice-engine",
        "thinnest",
        "ThinnestAI developer workspace",
        "Our own ThinnestAI workspace, read from ThinnestAI so it is never typed.",
        _THINNEST,
        details="It is never treated as a client's own workspace.",
    ),
    "inbound_reserved_lines": _m(
        "calling-limits",
        "limits",
        "Lines kept free for inbound calls",
        "Lines outbound calls may not use. Unset: the automatic share below applies.",
        details="At least one line always stays free.",
    ),
    "inbound_reserve_ratio": _m(
        "calling-limits",
        "limits",
        "Automatic share kept free (when no line count is set)",
        "Used only while 'Lines kept free for inbound calls' is unset.",
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
    "copilot_fast_model": _m(
        "language-models",
        "assistant",
        "Assistant: quick answers model",
        "The Gemini model the in-app assistant answers and looks things up with.",
    ),
    "copilot_planning_model": _m(
        "language-models",
        "assistant",
        "Assistant: planning model",
        "The Gemini model for multi-step requests and background jobs.",
    ),
    "copilot_azure_fallback": _m(
        "language-models",
        "assistant",
        "Assistant: use Azure when Gemini is not set up",
        "With Gemini not set up, the assistant answers on Azure instead of the basic fallback.",
        details=(
            "Not set up means no key, price or data-use approval. A Gemini failure mid-question "
            "still uses the basic fallback."
        ),
    ),
    "copilot_daily_message_cap": _m(
        "language-models",
        "assistant",
        "Assistant: questions per account per day",
        "The fair-use cap. Past it, the assistant tells the client and an alarm is raised.",
    ),
    "copilot_daily_ktok_cap": _m(
        "language-models",
        "assistant",
        "Assistant: thousand tokens per account per day",
        "The fair-use cap on model usage, counted alongside the question cap.",
    ),
    "pip_notes_enabled": _m(
        "language-models",
        "assistant",
        "Assistant: notes on its own",
        "Pip leaves short notes in its panel about things it noticed in an account. Off stops "
        "new notes.",
    ),
    "pip_notes_daily_cap": _m(
        "language-models",
        "assistant",
        "Assistant: new notes per account per day",
        "The most new notes Pip leaves for one account in one IST day.",
    ),
    "pip_notes_hot_lead_hours": _m(
        "language-models",
        "assistant",
        "Assistant: hours before a hot lead is noted",
        "A hot lead nobody has called back for this long gets a note.",
    ),
    "pip_notes_runway_days": _m(
        "language-models",
        "assistant",
        "Assistant: days of credit left before a note",
        "Credit expected to run out within this many days at the account's own spending gets "
        "a note.",
    ),
    "pip_notes_gap_repeat_calls": _m(
        "language-models",
        "assistant",
        "Assistant: calls before an unanswered question is noted",
        "One question the agents could not answer, asked on this many calls in a week, gets "
        "a note.",
    ),
    "pip_notes_good_week_percent": _m(
        "language-models",
        "assistant",
        "Assistant: rise that makes a good week",
        "Calls and new leads both up by at least this much on the week before gets a note.",
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
    # ---- speech ----------------------------------------------------------------------
    "sarvam_stt_model": _m(
        "speech",
        "stt",
        "Sarvam STT model",
        "The transcriber every agent is published with.",
        _OUR_STT,
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
        "List price per minute",
        "The list price per calling minute on a client's first pack.",
        details="Recording a rate card rewrites it.",
    ),
    "credit_pack_expiry_months": _m(
        "billing",
        "prices",
        "Credit expires after (months)",
        "Months after purchase that pack credit lapses. Empty: new credit does not lapse.",
        details="The Terms promise 12, so fewer is refused.",
    ),
    "platform_fee_enabled": _m(
        "billing",
        "prices",
        "Monthly platform fee",
        "On: clients not on a trial or a waiver pay the amount below each month. Off: nobody does.",
        details="Charged separately from calling credit.",
    ),
    "platform_fee_inr": _m(
        "billing",
        "prices",
        "Monthly platform fee amount",
        "What each client pays per month while the fee is on. A fee already raised keeps "
        "its amount.",
    ),
    "ai_overage_block_inr": _m(
        "billing",
        "prices",
        "Extra AI help block",
        "What a client pays from calling credit for one more block of AI help in a month. "
        "A block already bought keeps its amount.",
    ),
    "usd_inr_rate": _m(
        "billing",
        "prices",
        "Manual USD to INR rate (only if no published rate exists)",
        "Used only before any rate is published, or while the override below is on.",
        details="Dollar costs normally convert at the published rate, even an old one.",
    ),
    "usd_inr_rate_override": _m(
        "billing",
        "prices",
        "Use the manual USD to INR rate instead of the published one",
        "While on, every dollar cost converts at the manual rate above.",
        details="Leave off unless you have a reason to distrust the published rate.",
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
    "razorpay_mode": _m(
        "billing",
        "payments",
        "Razorpay mode",
        "Test or live. It must match the key ID; production refuses test keys.",
    ),
    "auto_recharge_max_failures": _m(
        "billing",
        "payments",
        "Auto-recharge failures before it switches off",
        "Failed automatic recharges in a row before auto-recharge is turned off.",
    ),
    "number_hold_after_negative_days": _m(
        "billing",
        "payments",
        "Days below zero before numbers are held",
        "Days below zero before a client's rented numbers are held and no rent is charged.",
        _THINNEST,
        details=(
            "Calls to them stop, and each is given up before it renews unless the client tops up."
        ),
    ),
    "razorpay_reconciliation_days": _m(
        "billing",
        "payments",
        "Payment reconciliation window",
        "How many days of Razorpay payments and refunds the daily check compares.",
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
        "Maximum consent age for a campaign",
        "A campaign over a list whose consent is older than this is refused. 0 turns the "
        "age check off.",
    ),
    "pe_verification_max_age_days": _m(
        "compliance",
        "checks",
        "How long a DLT PE verification stays valid",
        "After this, a principal-entity registration must be re-verified. 0 turns the check off.",
    ),
    "a2p_declaration_enforced_from": _m(
        "compliance",
        "checks",
        "Calling numbers must be confirmed from",
        "From this day (IST), a call from a number the client has not confirmed is refused.",
        details="Before it, clients are only asked to confirm.",
    ),
    "kyc_verification_provider": _m(
        "compliance",
        "checks",
        "KYC verification provider",
        "The DigiLocker provider. Unset means document review only.",
        details="List it as a sub-processor before setting it.",
    ),
    "kyc_verification_client_id": _m(
        "compliance",
        "checks",
        "KYC provider client ID",
        "The DigiLocker provider's API client ID. With the secret, DigiLocker is offered.",
        details="Absent, clients see DigiLocker as not available yet.",
    ),
    "kyc_verification_environment": _m(
        "compliance",
        "checks",
        "KYC provider environment",
        "Production for real checks. Sandbox only with a test account.",
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
    "google_signin_redirect_uri": _m(
        "integrations",
        "google",
        "Google sign-in redirect URL",
        "Where Google returns someone who chose Continue with Google.",
        details="Register it on the same Google OAuth client.",
    ),
    "google_cloud_project_number": _m(
        "integrations",
        "google",
        "Google Cloud project number",
        "The project number the Google file picker uses to share picked sheets with us.",
    ),
    "zoho_oauth_client_id": _m(
        "integrations",
        "crm",
        "Zoho CRM OAuth client ID",
        "The platform's Zoho app that a client's Zoho CRM connection authorises against.",
    ),
    "zoho_oauth_redirect_uri": _m(
        "integrations",
        "crm",
        "Zoho CRM OAuth redirect URL",
        "Where Zoho returns a client after they authorise their CRM.",
    ),
    "zoho_accounts_url": _m(
        "integrations",
        "crm",
        "Zoho accounts server",
        "The Zoho data centre the app is registered in, such as https://accounts.zoho.in.",
    ),
    "hubspot_oauth_client_id": _m(
        "integrations",
        "crm",
        "HubSpot OAuth client ID",
        "The platform's HubSpot app that a client's HubSpot connection authorises against.",
    ),
    "meta_app_id": _m(
        "integrations",
        "client_whatsapp",
        "Meta app ID",
        "Calevate's Meta app that every client's WhatsApp connection is made through.",
    ),
    "whatsapp_signup_config_id": _m(
        "integrations",
        "client_whatsapp",
        "Embedded Signup configuration ID",
        "From Facebook Login for Business > Configurations in the Meta app dashboard.",
    ),
    "whatsapp_onboarding_weekly_limit": _m(
        "integrations",
        "client_whatsapp",
        "New WhatsApp clients per 7 days",
        "Meta's cap on new WhatsApp business customers in a rolling week.",
        details=(
            "10, or 200 once Meta has approved verification, app review and access verification."
        ),
    ),
    "whatsapp_coexistence_enabled": _m(
        "integrations",
        "client_whatsapp",
        "Offer WhatsApp Business app users coexistence",
        "Lets clients keep using the WhatsApp Business app beside us. Off until Meta allows it.",
        details="Waits on Meta confirming coexistence for Indian numbers.",
    ),
    "hubspot_oauth_redirect_uri": _m(
        "integrations",
        "crm",
        "HubSpot OAuth redirect URL",
        "Where HubSpot returns a client after they authorise their account.",
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
    "sender_security": _m(
        "notifications",
        "email",
        "Send sign-in and security mail from",
        "Codes, password resets and account security notices. Unset uses Send mail from.",
    ),
    "sender_billing": _m(
        "notifications",
        "email",
        "Send billing mail from",
        "Fees, top-ups, credit and rate notices. Unset uses Send mail from.",
    ),
    "sender_alerts": _m(
        "notifications",
        "email",
        "Send lead and team alerts from",
        "Hot-lead and caller alerts to a client's team. Unset uses Send mail from.",
    ),
    "sender_operator": _m(
        "notifications",
        "alerts",
        "Send operator alerts from",
        "Alarm mail to our own team. Unset uses Send mail from.",
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
        "Maintenance notice lead time",
        "How far ahead clients are told about a planned maintenance window.",
    ),
    "whatsapp_message_inr": _m(
        "notifications",
        "whatsapp",
        "Cost of one WhatsApp we send",
        "What one message from our WhatsApp account costs us, in rupees, from Meta's rate card.",
        details="Records the cost of the save-our-number message, which we absorb.",
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
    "whatsapp_template_healer_page": _m(
        "notifications",
        "whatsapp",
        "Alarm page template name",
        "The approved template that sends alarm pages on WhatsApp.",
    ),
    "whatsapp_template_line_notice": _m(
        "notifications",
        "whatsapp",
        "Line affected template name",
        "The approved template that tells a client their line was protected.",
    ),
    "whatsapp_template_owner_digest": _m(
        "notifications",
        "whatsapp",
        "Daily summary template name",
        "The approved template for an owner's daily summary.",
    ),
    "whatsapp_template_line_restored": _m(
        "notifications",
        "whatsapp",
        "Line restored template name",
        "The approved template that tells a client their line is back.",
    ),
    # ---- auto-healer -----------------------------------------------------------------
    "healer_enabled": _m(
        "healer",
        "switches",
        "Auto-healer on",
        "Off stops every automatic repair, line hold and scheduled sweep.",
        details="Detection, notices and the health score carry on.",
    ),
    "healer_paused_playbooks": _m(
        "healer",
        "switches",
        "Paused playbooks",
        "Comma-separated playbook keys the healer must not run. The healer page lists them.",
    ),
    "healer_founder_whatsapp": _m(
        "healer",
        "paging",
        "WhatsApp number for alarm pages",
        "Receives alarm pages on WhatsApp; write it with +91. Empty sends pages by email only.",
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
    "worker_max_jobs": _m(
        "infrastructure",
        "database",
        "Background jobs at once",
        "Jobs the background worker runs at the same time, kept below its connection pool.",
        details="Read from the environment at start-up only.",
    ),
    "db_statement_timeout_ms": _m(
        "infrastructure",
        "database",
        "Database statement timeout",
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
    "copilot_upload_bucket": _m(
        "infrastructure",
        "storage",
        "Pip uploads bucket",
        "The private bucket for files people attach to Pip. Unset turns attachments off.",
    ),
    "copilot_upload_access_key_id": _m(
        "infrastructure",
        "storage",
        "Pip uploads access key ID",
        "The ID of the R2 token scoped to the Pip uploads bucket only. Its secret is set "
        "under credentials.",
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

# ---- how each setting is edited -------------------------------------------------------
#
# `ops/config_controls.py` derives every setting's control from its `Settings` field: a
# `bool` is a switch, a `Literal` a choice, bounds become a number's min and max, a pattern
# becomes the format a text box checks. What follows is ONLY what the annotation cannot
# say: the human words for an option, a unit, a value that names something which exists
# elsewhere (a rented number, our workspace, a client), and which settings are dangerous
# enough to need a typed confirmation. The server's validation is unchanged by any of it.


@dataclass(frozen=True, slots=True)
class OptionLabel:
    value: str
    label: str
    #: One short line under the option, or None.
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class ControlHint:
    #: Overrides the derived kind (see `config_controls.CONTROL_KINDS`).
    kind: str | None = None
    #: The unit a number is counted in, in words: "seconds", "calls", "per minute".
    unit: str | None = None
    #: For a `Literal` field: labels for (a subset of) its members. For a plain string
    #: field whose code reads only a few values: THE choices, which the console offers in
    #: place of a text box. Either way every value must be one the code acts on, which
    #: `tests/ops_config_controls_test.py` checks against each reader's own constant.
    options: tuple[OptionLabel, ...] = ()
    #: Where the choices come from when they exist outside this file: an id the console
    #: maps to a live read (`ENTITY_SOURCES`).
    source: str | None = None
    #: The value is a comma-separated list of choices rather than one.
    multiple: bool = False
    placeholder: str | None = None
    #: One line under the input saying what a valid value looks like.
    help: str | None = None


#: The live reads an entity picker can be fed from, by id, and what each lists.
ENTITY_SOURCES: Final[dict[str, str]] = {
    "trial_numbers": "numbers our ThinnestAI developer workspace holds that no client has",
    "thinnest_workspace": "our own ThinnestAI workspace, read from ThinnestAI",
    "tenants": "client accounts on this platform",
}

_PROVIDER_ONLY_LOCAL = "For development only; refused outside a local machine."

CONTROL_HINTS: Final[dict[str, ControlHint]] = {
    # ---- choices among things that exist elsewhere ----------------------------------
    "trial_caller_number": ControlHint(kind="entity_picker", source="trial_numbers"),
    "forwarding_test_second_number": ControlHint(kind="entity_picker", source="trial_numbers"),
    "thinnest_developer_workspace_id": ControlHint(
        kind="entity_picker", source="thinnest_workspace"
    ),
    "retrieval_shadow_tenant_ids": ControlHint(
        kind="entity_picker", source="tenants", multiple=True
    ),
    # Options filled from `healer/playbooks.PLAYBOOKS` by `config_controls`.
    "healer_paused_playbooks": ControlHint(kind="multi_select", multiple=True),
    "staged_agent_languages_enabled": ControlHint(kind="multi_select", multiple=True),
    "staged_language_test_tenant_ids": ControlHint(
        kind="entity_picker", source="tenants", multiple=True
    ),
    # ---- labelled closed choices ----------------------------------------------------
    "engine": ControlHint(
        options=(
            OptionLabel("thinnest", "ThinnestAI", "ThinnestAI hosts the whole call."),
            OptionLabel("fake", "Test engine", "Places no real calls."),
        )
    ),
    "thinnest_clear_voice_band": ControlHint(
        options=(
            OptionLabel(
                "premium", "ThinnestAI Premium band", "Available on every ThinnestAI plan."
            ),
            OptionLabel(
                "studio",
                "ThinnestAI Studio band",
                "Needs ThinnestAI Pro or above; its free preview voice cannot be used. Not our "
                "Studio tier.",
            ),
        )
    ),
    # Hints filled from `engine/thinnest_customers.PLAN_CUSTOMER_CAPS` by `config_controls`.
    "thinnest_customer_plan": ControlHint(
        options=(
            OptionLabel("payg", "Pay as you go"),
            OptionLabel("pro", "Pro"),
            OptionLabel("scale", "Scale"),
            OptionLabel("enterprise", "Enterprise"),
        )
    ),
    "retrieval_provider": ControlHint(
        options=(
            OptionLabel("compiled-facts", "Compiled facts only", "No search store."),
            OptionLabel("pgvector", "Postgres search", "Searches in our own database."),
            OptionLabel("supermemory", "Supermemory", "A self-hosted Supermemory."),
        )
    ),
    "retrieval_shadow_arm": ControlHint(
        options=(
            OptionLabel("off", "Off"),
            OptionLabel("pgvector", "Postgres search"),
            OptionLabel("supermemory", "Supermemory"),
        )
    ),
    "razorpay_mode": ControlHint(
        options=(
            OptionLabel("test", "Test", "Test keys; no real money moves."),
            OptionLabel("live", "Live", "Real payments."),
        )
    ),
    "kyc_verification_environment": ControlHint(
        options=(
            OptionLabel("production", "Production", "Real verifications."),
            OptionLabel("sandbox", "Sandbox", "Only with a test account."),
        )
    ),
    # ---- free-text fields the code reads as a closed set ----------------------------
    "email_provider": ControlHint(
        kind="select",
        options=(
            OptionLabel("resend", "Resend"),
            OptionLabel("smtp", "SMTP server", "Uses the SMTP settings below."),
        ),
    ),
    "payment_provider": ControlHint(kind="select", options=(OptionLabel("razorpay", "Razorpay"),)),
    "number_provider": ControlHint(
        kind="select",
        options=(
            OptionLabel("plivo", "Plivo"),
            OptionLabel("exotel", "Exotel"),
        ),
    ),
    "whatsapp_provider": ControlHint(
        kind="select",
        options=(
            OptionLabel("meta_cloud_api", "Meta WhatsApp Cloud API"),
            OptionLabel("console", "Console log", _PROVIDER_ONLY_LOCAL),
        ),
    ),
    "google_sheets_provider": ControlHint(
        kind="select",
        options=(
            OptionLabel("client_account", "Each client's own Google account"),
            OptionLabel("console", "Console log", _PROVIDER_ONLY_LOCAL),
        ),
    ),
    "meta_lead_retriever": ControlHint(
        kind="select",
        options=(
            OptionLabel("graph", "Meta Graph API"),
            OptionLabel("recorded", "Recorded examples", _PROVIDER_ONLY_LOCAL),
        ),
    ),
    "kyc_verification_provider": ControlHint(
        kind="select", options=(OptionLabel("cashfree", "Cashfree DigiLocker"),)
    ),
    # ---- units ----------------------------------------------------------------------
    "self_serve_inr_per_min": ControlHint(unit="per minute"),
    "platform_fee_inr": ControlHint(unit="per month"),
    "ai_overage_block_inr": ControlHint(unit="per block"),
    "usd_inr_rate": ControlHint(unit="per US dollar"),
    "trial_call_max_seconds": ControlHint(kind="duration", unit="seconds"),
    "db_statement_timeout_ms": ControlHint(kind="duration", unit="milliseconds"),
    "maintenance_notice_lead_hours": ControlHint(unit="hours"),
    "campaign_consent_max_age_days": ControlHint(unit="days", help="0 turns the check off."),
    "pe_verification_max_age_days": ControlHint(unit="days", help="0 turns the check off."),
    "a2p_declaration_enforced_from": ControlHint(kind="date", help="A day in IST."),
    "self_serve_trial_days": ControlHint(unit="days"),
    "self_serve_trial_free_minutes": ControlHint(unit="minutes"),
    "credit_pack_expiry_months": ControlHint(unit="months"),
    "razorpay_reconciliation_days": ControlHint(unit="days"),
    "trial_daily_call_cap": ControlHint(unit="calls a day"),
    "trial_studio_minutes": ControlHint(unit="minutes"),
    "paid_test_copy_idle_days": ControlHint(unit="days"),
    "forwarding_test_daily_cap": ControlHint(unit="tests a day"),
    "whatsapp_message_inr": ControlHint(unit="rupees"),
    "thinnest_max_concurrent_calls": ControlHint(unit="calls at once"),
    "thinnest_reply_length": ControlHint(unit="tokens"),
    "thinnest_interrupt_words": ControlHint(unit="words"),
    "thinnest_opening_wait_ms": ControlHint(
        kind="duration",
        unit="milliseconds",
        help="Whole tenths, 500 to 10,000. Unset, nothing is sent and ThinnestAI waits 4 s.",
    ),
    "thinnest_timer_turn_silence_ms": ControlHint(
        kind="duration", unit="milliseconds", help="200 to 3,000."
    ),
    "thinnest_turn_detection": ControlHint(
        options=(
            OptionLabel("timer", "Silence", "The pause set in Call handling ends the turn."),
            OptionLabel("ear", "Ear", "Real-time listening ends the turn after the pause."),
            OptionLabel("smart", "Smart", "A model judges; replies start later."),
            OptionLabel(
                "timer_v2",
                "Silence + check",
                "At each pause a quick AI check asks whether the caller has finished. "
                "The pause is not used.",
            ),
        )
    ),
    "reply_time_typical_target_ms": ControlHint(kind="duration", unit="milliseconds"),
    "reply_time_slow_target_ms": ControlHint(kind="duration", unit="milliseconds"),
    "hot_facts_max_chars": ControlHint(unit="characters"),
    "carrier_concurrency": ControlHint(unit="calls at once"),
    "inbound_reserved_lines": ControlHint(
        unit="lines", help="Leave unset to use the automatic share."
    ),
    "copilot_daily_message_cap": ControlHint(unit="questions a day"),
    "copilot_daily_ktok_cap": ControlHint(unit="thousand tokens a day"),
    "pip_notes_daily_cap": ControlHint(unit="notes a day"),
    "pip_notes_hot_lead_hours": ControlHint(unit="hours"),
    "pip_notes_runway_days": ControlHint(unit="days"),
    "pip_notes_gap_repeat_calls": ControlHint(unit="calls"),
    "pip_notes_good_week_percent": ControlHint(unit="percent"),
    "auto_recharge_max_failures": ControlHint(unit="failures in a row"),
    "number_hold_after_negative_days": ControlHint(unit="days"),
    "db_pool_size": ControlHint(unit="connections"),
    "worker_max_jobs": ControlHint(unit="jobs"),
    # ---- formats --------------------------------------------------------------------
    "engine_actions_base_url": ControlHint(placeholder="https://api.calevate.tech"),
    "tls_origin_address": ControlHint(placeholder="api.calevate.tech:443", help="host:port"),
    "google_cloud_project_number": ControlHint(help="Digits only, from the Google Cloud console."),
    "whatsapp_cloud_graph_version": ControlHint(placeholder="v22.0"),
    "whatsapp_template_locale": ControlHint(placeholder="en"),
}

#: Settings whose change can stop calls, move money, lock people out or change what a
#: caller is told, with the sentence the change form shows. These ask the operator to type
#: the new value back; every other setting is confirmed with one click. The server's own
#: step-up check and audit write are the same for both.
HIGH_RISK: Final[dict[str, str]] = {
    "engine": "Every call and every agent publish moves to the engine you choose.",
    "webhook_base_url": "Call events stop arriving if this address is wrong.",
    "engine_actions_base_url": "In-call actions stop working if this address is wrong.",
    "thinnest_byok_enabled": "Every minute moves to the ₹1 full-BYOK rate on our own speech, "
    "model and voice keys, and every agent's voice and model choice is locked.",
    "thinnest_clear_voice_band": "Changes which ThinnestAI band clients are sold as Clear.",
    "thinnest_own_rules": "Every live agent is republished, and its hand-over, lead and "
    "call-back rules come from our prompt alone (on) or from ThinnestAI as well (off).",
    "thinnest_call_instructions": "Every live agent is republished, and how it speaks on calls "
    "follows our call rules (on) or ThinnestAI's default call rules (off).",
    "thinnest_in_call_default_model": "Changes the language model every agent with none of its "
    "own answers calls with, from its next call.",
    "thinnest_own_model": "Every live agent, free-trial agents in our developer workspace "
    "included, is republished onto our Google key (on) or back onto ThinnestAI's own model "
    "(off), and Studio minutes move to the own-voice-and-model rate.",
    "thinnest_own_model_default": "Changes the model every agent with none of its own answers "
    "calls with on our own model, from its next call.",
    "staged_agent_languages_enabled": "Every client can then give an agent the languages you "
    "choose, and callers hear its notices in them.",
    "thinnest_developer_workspace_id": "Decides which workspace is ours, not a client's.",
    "self_serve_inr_per_min": "Every client is charged this price.",
    "platform_fee_enabled": "Decides whether every client is asked for a monthly fee.",
    "platform_fee_inr": "Every client is asked for this amount each month while the fee is on.",
    "ai_overage_block_inr": "Every client who buys extra AI help pays this amount.",
    "usd_inr_rate": "Used only if no rate was ever published, or with the override on.",
    "usd_inr_rate_override": "Every dollar cost converts at your manual rate while this is on.",
    "payment_provider": "Clients pay through the provider you choose.",
    "razorpay_mode": "Live takes real money; test takes none.",
    "campaign_consent_max_age_days": "Decides which contact lists a campaign may call.",
    "pe_verification_max_age_days": "Decides when a DLT registration must be re-verified.",
    "a2p_declaration_enforced_from": "An earlier date stops every client's calls from "
    "unconfirmed numbers at once.",
    "kyc_verification_environment": "Sandbox verifications are not real identity checks.",
    "healer_enabled": "Off stops every automatic repair.",
    "first_party_auth_enabled": "Off locks everyone out, operators included.",
    "self_serve_signup_enabled": "Decides whether anyone can open an account unaided.",
    "azure_openai_resource": "A resource in another region moves where calls are processed.",
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
    ("plivo", "Plivo"),
    ("cartesia", "Cartesia"),
    ("sarvam", "Sarvam"),
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
    "CONTROL_HINTS",
    "ENTITY_SOURCES",
    "FIELD_META",
    "FIXED_SPELLINGS",
    "HIGH_RISK",
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
    "ControlHint",
    "EngineScope",
    "FieldMeta",
    "OptionLabel",
    "Section",
    "Subsection",
    "humanise",
    "meta_for",
]
