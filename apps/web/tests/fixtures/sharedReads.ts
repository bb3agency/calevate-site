import { noReply } from "../harness";
import { currentISTMonth } from "@/lib/api/invoice";
import type { LegalReadiness } from "@/lib/api/agreements";
import type { TenantSummary } from "@/lib/api/admin";
import type { Agent, HandoffOut } from "@/lib/api/agents";
import type { Me } from "@/lib/api/client";
import type { PeRegistration } from "@/lib/api/dltRegistration";
import { EMPTY_SCRIPT } from "@/lib/api/script";
import type { KycRecord } from "@/lib/api/kyc";
import type { LeadFields } from "@/lib/api/leadFields";
import type { ClientLlmDefaults } from "@/lib/api/llmModels";
import type { ClientMaintenance } from "@/lib/api/maintenance";
import type { HostedVoices } from "@/lib/api/opsHostedVoices";
import type { OwnNumbersStatus } from "@/lib/api/ownNumbers";
import type { PromptLayers } from "@/lib/api/prompts";
import type { Lanes } from "@/lib/api/publishing";
import type { WalletLots } from "@/app/c/[slug]/billing/lots";
import type { PlatformFee } from "@/lib/api/platformFee";
import type { Spend } from "@/lib/api/spend";
import type { Wallet } from "@/lib/api/wallet";
import type { AlertOptIn } from "@/lib/api/whatsappAlerts";
import type { ClientVoiceTuning } from "@/lib/api/voiceTuning";
import type { TeamAlertRule, TeamContacts } from "@/lib/api/teamAlerts";
import type { AccountReadiness, AgentReadiness } from "@/lib/api/readiness";

/**
 * Reads that many screens make and few tests are about, answered in their ordinary state.
 *
 * Every table has to answer every read its screen makes (`unansweredRoutes.ts`), and a
 * shell, a panel or a card that mounts on a dozen screens would otherwise be re-typed in a
 * dozen suites and drift in each. Each fixture is held to the generated wire type with
 * `satisfies`, so an API reshape breaks here rather than in a suite about something else.
 * A test that is ABOUT one of these states builds its own.
 */

/** No maintenance window scheduled — `GET /v1/maintenance` on an ordinary day. */
export const NO_MAINTENANCE = {
  state: "none",
  starts_at: null,
  ends_at: null,
  reason: null,
} satisfies ClientMaintenance;

const ACCEPTED = {
  blocking: true,
  version: "1+pre-review",
  provisional: true,
  effective_date: null,
  state: "accepted",
  headline: "Accepted.",
  accepted_version: "1+pre-review",
  accepted_at: "2026-08-20T06:00:00Z",
  accepted_by_name: "Padmavathi Rao",
} as const;

/** Every agreement accepted and nothing else in the way — `GET /v1/legal/readiness`. */
export const LEGAL_READY = {
  may_operate: true,
  verdict: "Nothing is holding up your outgoing calls.",
  outstanding_documents: 0,
  pending_legal_review: true,
  provisional_notice: "These documents are drafts.",
  acceptance_statement:
    "I accept the Terms of Service, the Privacy Policy, the Data Processing Addendum and the Acceptable Use Policy on behalf of this business.",
  acceptance_statement_version: "1+pre-review",
  can_accept: true,
  can_accept_reason: null,
  documents: [
    { ...ACCEPTED, slug: "terms", title: "Terms of Service", href: "/legal/terms" },
    { ...ACCEPTED, slug: "privacy", title: "Privacy Policy", href: "/legal/privacy" },
    {
      ...ACCEPTED,
      slug: "acceptable-use",
      title: "Acceptable Use",
      href: "/legal/acceptable-use",
    },
    { ...ACCEPTED, slug: "dpa", title: "Data Processing Addendum", href: "/legal/dpa" },
  ],
  blockers: [],
  upcoming: [],
} satisfies LegalReadiness;

/**
 * The path the header's live-calls pill reads — `useCalls` with the in-progress filter.
 * One spelling, so a test that answers it and the shell that asks cannot drift apart.
 */
export const LIVE_CALLS_PATH = "/v1/calls?status=in_progress&limit=20";

/** The path the top bar's bell reads — `useNotifications` with the bell's page size. */
export const NOTIFICATIONS_PATH = "/v1/notifications?limit=20";

/** The bell with nothing in it. */
export const EMPTY_NOTIFICATIONS = { items: [], unread: 0, attention_total: 0, seen_through: null };

/** The reads the client shell makes on every screen, in their ordinary state. */
export const CLIENT_SHELL_ROUTES = {
  "/v1/maintenance": NO_MAINTENANCE,
  "/v1/legal/readiness": LEGAL_READY,
  // No call in progress: the pill renders nothing.
  [LIVE_CALLS_PATH]: [],
  // No trial running: the shell's trial strip renders nothing.
  "/v1/billing/wallet": prepaidWallet(),
  // Nothing announced, an empty bell, and nothing waiting (the desktop alerts' read).
  "/v1/announcements": { items: [] },
  "/v1/attention": { total: 0, items: [] },
  [NOTIFICATIONS_PATH]: EMPTY_NOTIFICATIONS,
};

/** The owner has never been asked about WhatsApp alerts, and there is no channel yet. */
export const WHATSAPP_NEVER_ASKED = {
  status: "none",
  channel: null,
  captured_at: null,
  notice_version: null,
  messageable: false,
  current_notice_version: "whatsapp-alerts-v1",
  current_notice_text:
    "I agree that Calevate may send WhatsApp messages to this number to alert me about activity in my own account, such as a hot lead.",
  delivery_available: false,
  delivery_unavailable_reason: "no_credential",
} satisfies AlertOptIn;

/** Every call handling read's bounds: the pause (D-751) and the voice settings (F3, F9). */
export const CALL_HANDLING_BOUNDS = {
  turn_silence_min_ms: 200,
  turn_silence_max_ms: 3000,
  platform_turn_silence_ms: 250,
  platform_end_call_on_finish: true,
  nudge_after_min_s: 5,
  nudge_after_max_s: 180,
  platform_nudge_after_seconds: 8,
  nudge_count_min: 1,
  nudge_count_max: 5,
  platform_nudge_count: 1,
  nudge_phrase_max_chars: 120,
  end_after_silence_min_s: 5,
  end_after_silence_max_s: 180,
  platform_end_after_silence_seconds: 20,
  filler_lines_max: 8,
  filler_line_max_chars: 60,
  ambiences: ["off", "office", "office-quiet"] as ("off" | "office" | "office-quiet")[],
  platform_ambience: "off" as const,
  ambience_volume_min_pct: 5,
  ambience_volume_max_pct: 100,
  platform_ambience_volume_pct: 15,
  opening_wait_available: false,
  opening_wait_min_ms: 500,
  opening_wait_max_ms: 10000,
  opening_wait_step_ms: 100,
  platform_opening_wait_ms: null as number | null,
  reask_after_min_ms: 1500,
  reask_after_max_ms: 10000,
  reask_after_step_ms: 100,
  platform_reask_after_ms: 5000,
};

/** The "Patient caller" preset on a Telugu agent, not in use (D-907). */
export const PATIENT_CALLER = {
  applied: false,
  nudge_after_seconds: 20,
  nudge_count: 3,
  nudge_phrase: "కనిపించిందా అండి?",
  end_after_silence_seconds: 120,
  reask_after_ms: 0,
  call_cap_s: 900,
};

/** The voice settings of one level, none chosen. */
export const VOICE_OWN_NONE = {
  nudge_after_seconds: null,
  nudge_count: null,
  nudge_phrase: null,
  end_after_silence_seconds: null,
  filler_lines: null,
  ambience: null,
  ambience_volume_pct: null,
  opening_wait_ms: null as number | null,
  reask_after_ms: null as number | null,
};

/** Calevate's voice settings in force. */
export const VOICE_EFFECTIVE_DEFAULTS = {
  nudge_after_seconds_effective: 8,
  nudge_count_effective: 1,
  nudge_phrase_effective: "",
  end_after_silence_seconds_effective: 20,
  filler_lines_effective: [] as string[],
  ambience_effective: "off" as const,
  ambience_volume_pct_effective: 15,
  opening_wait_ms_effective: null as number | null,
  reask_after_ms_effective: 5000,
};

/** Every voice setting coming from Calevate. */
export const VOICE_SOURCES_PLATFORM = {
  nudge_after_seconds_source: "platform" as const,
  nudge_count_source: "platform" as const,
  nudge_phrase_source: "platform" as const,
  end_after_silence_seconds_source: "platform" as const,
  filler_lines_source: "platform" as const,
  ambience_source: "platform" as const,
  ambience_volume_pct_source: "platform" as const,
  opening_wait_ms_source: "platform" as const,
  reask_after_ms_source: "platform" as const,
};

/** An account that has chosen no voice setting. */
export const VOICE_ORGANIZATION_NONE = {
  organization_nudge_after_seconds: null,
  organization_nudge_count: null,
  organization_nudge_phrase: null,
  organization_end_after_silence_seconds: null,
  organization_filler_lines: null,
  organization_ambience: null,
  organization_ambience_volume_pct: null,
  organization_opening_wait_ms: null as number | null,
  organization_reask_after_ms: null as number | null,
};

/** One agent's pause before replying and hang-up (D-751), all on Calevate's defaults. */
export function agentCallHandling(agentId = "agent-1") {
  return {
    agent_id: agentId,
    turn_silence_ms: null,
    turn_silence_ms_effective: 250,
    turn_silence_source: "platform",
    end_call_on_finish: null,
    end_call_on_finish_effective: true,
    end_call_on_finish_source: "platform",
    organization_turn_silence_ms: null,
    organization_end_call_on_finish: null,
    opening_waits_for_caller: false,
    ...VOICE_OWN_NONE,
    ...VOICE_EFFECTIVE_DEFAULTS,
    ...VOICE_SOURCES_PLATFORM,
    ...VOICE_ORGANIZATION_NONE,
    bounds: CALL_HANDLING_BOUNDS,
    patient_caller: PATIENT_CALLER,
  };
}

/** The account read an owner's agent Settings makes to count the agents "All my agents"
 * changes: nothing chosen, no agent with its own value. */
export function organizationCallHandling() {
  return {
    turn_silence_ms: null,
    turn_silence_ms_effective: 250,
    end_call_on_finish: null,
    end_call_on_finish_effective: true,
    ...VOICE_OWN_NONE,
    ...VOICE_EFFECTIVE_DEFAULTS,
    agents_with_own: [],
    agents_with_own_total: 0,
    bounds: CALL_HANDLING_BOUNDS,
  };
}

/** The reads an agent's Settings makes for Tell my team (D-904): no team address yet, and an
 * agent that tells nobody. */
export function teamAlertReads(agentId = "agent-1") {
  return {
    "/v1/team-alerts/contacts": {
      contacts: [],
      max_contacts: 10,
      whatsapp_accounts: [],
    } satisfies TeamContacts,
    [`/v1/agents/${agentId}/team-alert`]: {
      contact_id: null,
      on_outcomes: [],
      on_fields: [],
      in_call: false,
      sends_to: null,
      in_call_live: false,
      outcomes: [{ key: "booked", label: "Booked", values: [] }],
      fields: [],
    } satisfies TeamAlertRule,
  };
}

/** An operator's turn detection for one agent (D-901), following the console. */
export function agentTurnDetection(agentId = "agent-1") {
  return {
    agent_id: agentId,
    turn_detection: null,
    turn_detection_effective: "ear" as const,
    console_turn_detection: "ear" as const,
    turn_silence_ms_effective: 250,
    turn_silence_source: "platform" as const,
  };
}

/** One agent's reply length (D-769), inheriting the platform's 300 tokens. */
export function agentReplyLength(agentId = "agent-1") {
  return {
    agent_id: agentId,
    max_reply_tokens: null,
    default: 300,
    effective: 300,
    min: 100,
    max: 800,
  };
}

/**
 * What one agent is told (D-882): a platform layer, the client's script and the truthful
 * answers, with the engine's copy last found in step.
 */
export function agentPromptLayers(agentId = "agent-1"): PromptLayers {
  const layers: PromptLayers["layers"] = [
    {
      key: "preamble",
      title: "Calevate's opening rules",
      purpose: "Names the agent and the business, and says platform rules come first.",
      owner: "platform",
      from_agent_settings: true,
      text: "--- PLATFORM RULES ---\nYou are Asha, answering calls for Sri Bakery.",
      chars: 68,
    },
    {
      key: "client_script",
      title: "The client's script",
      purpose: "The client's own script: who the agent is, its steps and its facts.",
      owner: "client",
      from_agent_settings: true,
      text: "<<CLIENT SCRIPT>>\n[IDENTITY]\nYou are Asha.\n[OPENING]\nNamaskaram, Sri Bakery.\n<</CLIENT SCRIPT>>",
      chars: 93,
    },
    {
      key: "truthful_answers",
      title: "Truthful answers (AI and recording)",
      purpose: "Always answer truthfully whether it is an AI and whether the call is recorded.",
      owner: "platform",
      from_agent_settings: false,
      text: "If asked whether you are an AI, say yes.",
      chars: 40,
    },
  ];
  return {
    agent_id: agentId,
    has_script: true,
    layers,
    separator_chars: 4,
    total_chars: 205,
    limit_chars: 20000,
    over_chars: 0,
    engine_added_chars: 3500,
    caller_memory: "kept_by_engine",
    on_engine: true,
    drift_state: "applied",
    drift_checked_at: "2026-10-25T04:30:00Z",
  };
}

/** The lane rules — `GET /v1/agents/lanes`, with the platform's call-cap bounds. */
export const LANES = {
  precedence_rule: "Script decides content.",
  lanes: [],
  call_cap_default_s: 600,
  call_cap_min_s: 60,
  call_cap_max_s: 3600,
} satisfies Lanes;

/** Handing calls to a person, switched off — `GET /v1/agents/{id}/handoff`. */
export function handoffOff(agentId: string): HandoffOut {
  return {
    agent_id: agentId,
    enabled: false,
    trigger: null,
    effective_trigger: "Hand the call to a person when the caller asks for one.",
    spoken_line: "Okay, I am putting you through to someone from our team now.",
    members: [],
    recent: [],
    on_duty_member_id: null,
    unavailable_reason: "disabled",
    remediation: "Transfer to a person is off for this agent. Turn it on to use it.",
    published: true,
  };
}

/**
 * One agent as `GET /v1/agents` lists it — live, published, on the platform's model. For a
 * screen that reads the roster only to name the agent it is about.
 */
export function agentRow(over: Partial<Agent> = {}): Agent {
  return {
    id: "agent-1",
    name: "Reception",
    direction: "inbound",
    status: "live",
    archived_at: null,
    language_primary: "te-IN",
    reply_languages: ["te-IN"],
    disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    recording_notice_enabled: true,
    caller_memory_notice_line: "I keep a short note of what you ask about.",
    caller_memory_enabled: false,
    caller_memory_paused: false,
    caller_has_screen: false,
    opening_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
    script_opening_line: "",
    first_words: "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    engine: "thinnest",
    published: true,
    inbound_number_count: 1,
    extraction_fields: [],
    extraction_schema_version: 0,
    llm_tier: null,
    llm_tier_effective: "standard",
    llm_tier_label: "Standard",
    llm_tier_source: "platform",
    llm_surcharged: false,
    ...over,
  };
}

/** A business that has not started KYC — `GET /v1/compliance/kyc` before anything is filed. */
export const KYC_NOT_STARTED = {
  recorded: false,
  is_verified: false,
  number_purchase_available: false,
  self_verification_available: false,
  status: null,
  entity_type: null,
  document_kind: null,
  document_ref: null,
  evidence_ref: null,
  signatory_name: null,
  submitted_at: null,
  rejection_reason: null,
  verification_provider: null,
  verification_reference: null,
  verification_source: null,
  verified_at: null,
  verified_name: null,
  kyc_path: null,
  legal_business_name: null,
  gst_registered: null,
  gstin: null,
  owner_id_type: null,
  owner_id_masked: null,
  name_match: null,
  digilocker_required: false,
  digilocker_required_reason: null,
  digilocker_outstanding: false,
  documents: [],
} satisfies KycRecord;

/** A prepaid wallet with money on it — the state most accounts are in. */
export function prepaidWallet(over: Partial<Wallet> = {}): Wallet {
  return {
    tenant_id: "o1",
    prepaid: true,
    balance_inr: "3400.00",
    is_low: false,
    low_balance_threshold_inr: "200.00",
    low_balance_alert_chosen: false,
    granted_inr: "0.00",
    paid_inr: "2500.00",
    trial: null,
    outbound_stopped: false,
    runway: {
      basis: "projected",
      days: 10,
      daily_burn_inr: "340.00",
      history_days: 30,
      beyond_horizon: false,
      window_days: 30,
      min_history_days: 7,
      max_days: 365,
    },
    minutes_left: [
      { voice_tier: "clear", label: "Clear", minutes: 240 },
      { voice_tier: "studio", label: "Studio", minutes: 171 },
    ],
    drawdown: {
      calls_inr: "8400.00",
      ai_assist_inr: "0.00",
      number_rental_inr: "0.00",
      adjustments_inr: "0.00",
      spent_inr: "8400.00",
      added_inr: "12100.00",
      refunded_inr: "0.00",
    },
    ...over,
  };
}

/**
 * A running trial as `GET /v1/billing/wallet` publishes it (D-536): dates and a day count,
 * no cost. Ends 10 Oct 2026, 10:58 pm IST — the founder's own example.
 */
export function activeTrialBlock(over: Partial<NonNullable<Wallet["trial"]>> = {}): NonNullable<Wallet["trial"]> {
  return {
    active: true,
    status: "active",
    days: 3,
    started_at: "2026-10-07T17:28:00Z",
    ends_at: "2026-10-10T17:28:00Z",
    days_remaining: 3,
    ended_at: null,
    test_calls_only: false,
    free_minutes: null,
    minutes_left: null,
    ...over,
  };
}

/** No DLT Principal Entity registration on file — `GET /v1/compliance/dlt-registration`. */
export const DLT_NOT_RECORDED = {
  recorded: false,
  status: null,
  tm_link_status: null,
  pe_id: null,
  entity_name: null,
  registered_at: null,
  verified_at: null,
  is_active: false,
  calevate_tm_id: null,
  calevate_tm_active: false,
} satisfies PeRegistration;

/** The account owner, as `GET /v1/me` answers for them. */
export const OWNER_ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage", "calls:read", "leads:read", "agents:read"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
} satisfies Me;

/** One client as the admin directory summarises it — `GET /v1/admin/tenants/{id}`. */
export function tenantSummary(over: Partial<TenantSummary> = {}): TenantSummary {
  return {
    id: "t1",
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 2,
    calls_7d: 412,
    leads: 96,
    last_call_at: "2026-08-12T09:15:00Z",
    holds: [],
    capped: false,
    ...over,
  };
}

/**
 * The lot queue — `GET /v1/billing/wallet/lots` — for a wallet holding one starter pack,
 * bought at the published card (Clear ₹4.00, Studio ₹7.00 a minute; `fixtures/rateCard.ts`).
 * `tiers` is the server's runway, floored to whole minutes as `wallet.tier_minutes` floors it.
 */
export function walletLots(over: Partial<WalletLots> = {}): WalletLots {
  return {
    tiers: [
      { voice_tier: "clear", label: "Clear", minutes_left: "500" },
      { voice_tier: "studio", label: "Studio", minutes_left: "285" },
    ],
    lots: [
      {
        lot_id: "0192f0aa-5555-7000-8000-000000000001",
        opened_at: "2026-09-01T04:30:00Z",
        credits_remaining: "2000.0000",
        clear_inr_per_min: "4.0000",
        studio_inr_per_min: "7.0000",
      },
    ],
    overdraft_inr: "0.00",
    ...over,
  };
}

/**
 * What the lots route answers for a wallet with nothing in it: 200, no open lot, zero
 * minutes on both qualities. The route has no 404 (`billing/wallet_routes.read_wallet_lots`).
 */
export const EMPTY_WALLET_LOTS = {
  tiers: [
    { voice_tier: "clear", label: "Clear", minutes_left: "0" },
    { voice_tier: "studio", label: "Studio", minutes_left: "0" },
  ],
  lots: [],
  overdraft_inr: "0.00",
} satisfies WalletLots;

/**
 * `GET /v1/organization/llm-defaults` as the CLIENT realm serves it (D-680): three tiers and
 * the server's words for each, no model and no provider. Following the Calevate default, with
 * an upgrade surcharge on the two dearer tiers so the price comparisons render.
 */
export function clientLlmTiers(over: Partial<ClientLlmDefaults> = {}): ClientLlmDefaults {
  return {
    default_llm_tier: null,
    effective_tier: "standard",
    effective_tier_label: "Standard",
    effective_is_available: true,
    in_force_surcharge_inr_per_minute: "0",
    upgrade_surcharge_inr_per_minute: "1.5000",
    tier_choosable: true,
    tier_note: null,
    available: [
      {
        tier: "standard",
        label: "Standard",
        description: "Quick, natural replies for everyday calls. Our lowest-cost option.",
        client_surcharge_inr_per_minute: "0",
        is_platform_default: true,
        is_available: true,
        unavailable_reason: null,
      },
      {
        tier: "plus",
        label: "Plus",
        description: "Stronger reasoning for longer calls and detailed questions.",
        client_surcharge_inr_per_minute: "1.5000",
        is_platform_default: false,
        is_available: true,
        unavailable_reason: null,
      },
      {
        tier: "pro",
        label: "Pro",
        description: "Our most capable option, for the most involved conversations.",
        client_surcharge_inr_per_minute: "1.5000",
        is_platform_default: false,
        is_available: true,
        unavailable_reason: null,
      },
    ],
    ...over,
  };
}

/**
 * `GET /v1/ops/voices/hosted?scope=added` on an engine that hosts no voices: the Voices page
 * prints the server's sentence (D-687).
 */
export const HOSTED_VOICES_PROBE_PATH = "/v1/ops/voices/hosted?scope=added";
export const NOT_HOSTED = {
  available: false,
  scope: "added",
  voices: [],
  cached: 0,
  offered: 0,
  studio_ready: false,
  clear_band: null,
  note: "Voices on this platform come from Calevate's own catalogue.",
  bands: {},
  plan_note: null,
} satisfies HostedVoices;

/** `GET /v1/numbers/own/status` — the path every screen that reads it is asked on. */
export const OWN_NUMBERS_STATUS_PATH = "/v1/numbers/own/status";

/**
 * A deployment that does not rent numbers in each client's own calling account (D-693):
 * `available: false`, every other field empty, and the screens hide the journey.
 */
export const OWN_NUMBERS_OFF = {
  available: false,
  paid: false,
  trial: null,
  step: null,
  blocker: null,
  account_setup: null,
  kyc_status: null,
  business_status: null,
  business_review_note: null,
  business_submitted_at: null,
  can_send_business_details: false,
  inr_per_month: null,
} satisfies OwnNumbersStatus;

/**
 * The reads the admin client overview's HEALTH SUMMARY makes (redesign #2): the per-client
 * judgement, healthy; the wallet and the line incidents left unanswered (they are not the
 * subject of the files that spread this in); no recent calls.
 */
export function adminOverviewSummaryReads(tenantId: string) {
  return {
    [`/v1/admin/client-health/${tenantId}`]: {
      tenant_id: tenantId,
      severity: null,
      signals: [],
      on_trial: false,
      spend_used_inr: null,
      spend_cap_inr: null,
    },
    "/v1/billing/wallet": noReply(),
    "/v1/healer/incidents?days=30&limit=20": noReply(),
    "/v1/calls?limit=5": [],
    ...adminAccountFactReads(tenantId),
  };
}

/**
 * The reads behind the overview's assistant facts (`accountFacts.ts`): KYC and pledge,
 * readiness, workspace, trial and the business profile. Left unanswered — the facts then
 * say "still loading", and no file that spreads this in is about them.
 */
export function adminAccountFactReads(tenantId: string) {
  return {
    [`/v1/admin/tenants/${tenantId}/kyc`]: noReply(),
    [`/v1/admin/tenants/${tenantId}/readiness`]: noReply(),
    [`/v1/admin/engine-workspaces/tenants/${tenantId}`]: noReply(),
    [`/v1/admin/tenants/${tenantId}/trial`]: noReply(),
    [`/v1/admin/tenants/${tenantId}/business-profile`]: noReply(),
    // The Overview usage card and its assistant facts (`UsagePanel`): the month spend read.
    [`/v1/admin/tenants/${tenantId}/spend?month=${currentISTMonth()}`]: noReply(),
  };
}

/** The monthly platform fee switched off and never raised — `GET /v1/billing/platform-fee`
 *  on a platform that charges none (D-707). The card renders nothing. */
export const PLATFORM_FEE_OFF = {
  enabled: false,
  amount_inr: null,
  exemption: null,
  outbound_paused: false,
  grace_days: 7,
  charges: [],
} satisfies PlatformFee;

/** `GET /v1/billing/spend` with no month: the agent header's "spent this month" read. */
export const AGENT_SPEND_PATH = "/v1/billing/spend";

/** A month with no charged call on any agent — the header says "Nothing spent this month". */
export function spendThisMonth(over: Partial<Spend> = {}): Spend {
  return {
    month: currentISTMonth(),
    charge_basis: "wallet_debit",
    calls: 0,
    minutes_used: "0.0000",
    retainer_inr: null,
    period_charge_inr: "0.00",
    itemised_charge_inr: "0.00",
    itemisation_residual_inr: "0.00",
    residual_reason: null,
    by_agent: [],
    top_calls: [],
    top_calls_truncated: false,
    ...over,
  };
}

/** `GET /v1/lead-fields`: the core only, no business fields, no draft. The leads screen
 *  reads it for `need_key`, the field it shows as "What they want". */
export const LEAD_FIELDS_CORE_ONLY = {
  agents: [],
  business_type: null,
  business_type_label: "Your business",
  can_draft: false,
  core_fields: [],
  draft: null,
  has_standard_set: false,
  need_key: "need",
  standard_fields: [],
} satisfies LeadFields;

/**
 * `GET /v1/agents/{id}/script` with a live script and no draft. The agent page's header
 * (Put it live) and its section menu (the Script line) read it on every section.
 */
export function agentScript(over: Record<string, unknown> = {}) {
  return {
    script: { ...EMPTY_SCRIPT, opening_line: "Namaskaram." },
    draft: null,
    stored_schema_version: 2,
    context: null,
    version: 4,
    is_freeform: false,
    has_pending: false,
    standard_variables: [],
    ...over,
  };
}

/**
 * `GET /v1/agents/{id}/pending` with nothing waiting and a Clear voice live. The script
 * builder reads it for the voice tier its "Put it live" step names.
 */
export function settledPending(over: Record<string, unknown> = {}) {
  const clear = { voice_id: "engine:anika", provider: null, voice_tier: "clear", catalog: null };
  return {
    agent_id: "agent-1",
    agent_status: "live",
    published: true,
    has_pending: false,
    pending: [],
    effective_call_cap_s: 600,
    call_cap_is_platform_default: true,
    worst_case_call_cost_inr: "12.50",
    precedence_rule: "Script decides content.",
    voice: {
      configured: clear,
      live: clear,
      republish_required: false,
      headline: "Callers hear Anika.",
      unnamed_note: null,
    },
    voice_tier_rates: [
      { voice_tier: "clear", label: "Clear", inr_per_min: "2.50", further_open_lots: 0 },
      { voice_tier: "studio", label: "Studio", inr_per_min: "4.00", further_open_lots: 0 },
    ],
    engine_verification: {
      state: "applied",
      confirmed: true,
      publishable: true,
      verified_at: "2026-10-13T09:20:00Z",
      headline: "The voice platform was read back and is running this script and voice.",
    },
    ...over,
  };
}

/** A client's calls at once (F7) on Calevate's paying-client default, keyed by its route. */
export function callLinesRoute(tenantId: string) {
  return {
    [`/v1/admin/organizations/${tenantId}/call-lines`]: {
      call_lines: 2,
      call_lines_chosen: null,
      source: "platform",
      on_trial: false,
      min_lines: 1,
      max_lines: 50,
      paid_default: 2,
      trial_default: 1,
    },
  };
}

/** How an agent's Studio voice sounds (D-843): a Studio voice on calm, every sample left. */
export function clientVoiceTuning(agentId = "agent-1", over: Partial<ClientVoiceTuning> = {}): ClientVoiceTuning {
  return {
    agent_id: agentId,
    studio: true,
    speed: null,
    volume: null,
    emotion: "calm",
    options: {
      speed_min: "0.6",
      speed_max: "1.5",
      speed_step: "0.01",
      volume_min: "0.5",
      volume_max: "2.0",
      emotions: ["neutral", "calm", "content", "sad", "angry", "scared", "happy", "excited"],
      previews_per_day: 20,
    },
    previews_left_today: 20,
    ...over,
  };
}

/** The roster's read of every agent's score (`Roster` asks for the whole roster). */
export const ROSTER_READINESS_PATH = "/v1/readiness?limit=200";

/** `GET /v1/readiness` before any agent has a score. */
export const NO_ACCOUNT_READINESS = {
  score: null,
  agents: [],
  top_fixes: [],
  computed_at: "2026-10-24T05:00:00Z",
} satisfies AccountReadiness;

/** `GET /v1/agents/{id}/readiness` for an agent with one thing left to do. */
export function agentReadiness(agentId = "agent-1", name = "Reception"): AgentReadiness {
  return {
    agent_id: agentId,
    agent_name: name,
    score: 85,
    max_score: 100,
    components: [
      { key: "tests", label: "Practice tests", points: 35, max_points: 35, state: "full", detail: "All 4 tests passed." },
      { key: "opening", label: "Opening line", points: 0, max_points: 15, state: "none", detail: "No opening line yet." },
    ],
    fixes: [
      {
        component: "opening",
        action: "Write the opening line callers hear first.",
        href: `/agents/${agentId}?section=script`,
        points: 15,
      },
    ],
    computed_at: "2026-10-24T05:00:00Z",
  };
}
