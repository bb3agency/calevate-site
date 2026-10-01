import type { LegalReadiness } from "@/lib/api/agreements";
import type { TenantSummary } from "@/lib/api/admin";
import type { Agent, HandoffOut } from "@/lib/api/agents";
import type { AutodialerNotice } from "@/lib/api/autodialerNotice";
import type { Me } from "@/lib/api/client";
import type { PeRegistration } from "@/lib/api/dltRegistration";
import type { DeliveryList } from "@/lib/api/kb";
import type { KycRecord } from "@/lib/api/kyc";
import type { ClientMaintenance } from "@/lib/api/maintenance";
import type { Lanes } from "@/lib/api/publishing";
import type { OfferedVoice, VoiceCatalogue } from "@/lib/api/voices";
import type { WalletLots } from "@/app/c/[slug]/billing/lots";
import type { Wallet } from "@/lib/api/wallet";
import type { AlertOptIn } from "@/lib/api/whatsappAlerts";

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
} satisfies LegalReadiness;

/**
 * The path the header's live-calls pill reads — `useCalls` with the in-progress filter.
 * One spelling, so a test that answers it and the shell that asks cannot drift apart.
 */
export const LIVE_CALLS_PATH = "/v1/calls?status=in_progress&limit=20";

/** The reads the client shell makes on every screen, in their ordinary state. */
export const CLIENT_SHELL_ROUTES = {
  "/v1/maintenance": NO_MAINTENANCE,
  "/v1/legal/readiness": LEGAL_READY,
  // No call in progress: the pill renders nothing.
  [LIVE_CALLS_PATH]: [],
};

/** Every agent's knowledge delivered — `GET /v1/kb/delivery` with nothing outstanding. */
export const KB_ALL_DELIVERED = {
  items: [],
  not_delivered_count: 0,
} satisfies DeliveryList;

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
    remediation: "Handing calls to a person is switched off for this agent.",
    published: true,
  };
}

/**
 * The voice catalogue in the state this deployment is in: a Studio voice (Cartesia,
 * Sonic 3.5) on offer, and the Clear rung (Gnani, Timbre v2.5) refused because nobody has
 * attested its price (`apps/api/agents/voice_offer.py` ground 2). Ids are spelled
 * `<tts_model>:<speaker>`, as `voices.voice_id_of` composes them.
 *
 * The refusal sentences are the server's, per realm: an operator is told which console row
 * to fill in, a client is told the tier is unavailable and never which vendor is behind it
 * (`voice_offer.client_unofferable_reason`, `voice_routes._tier_note`).
 */
export function voiceCatalogue(realm: "client" | "admin"): VoiceCatalogue {
  const clearRefusal =
    realm === "client"
      ? "the Clear voice is not available on your account yet — ask your account manager"
      : "nobody has recorded what a Gnani minute costs on this account, and an unpriced minute is unmetered spend rather than a free one — attest the Gnani TTS price in the ops console";
  const voices: OfferedVoice[] = [
    {
      id: "sonic-3.5:ananya",
      label: "Ananya",
      provider: "cartesia",
      tts_model: "sonic-3.5",
      speaker: "ananya",
      voice_tier: "studio",
      tier_label: "Studio",
      gender: null,
      languages: ["te-IN", "hi-IN", "en-IN"],
      note: "A studio read.",
      verified: true,
      offerable: true,
      unavailable_reason: null,
      not_on_offer: false,
    },
    {
      id: "timbre-v2.5:Suhana",
      label: "Suhana",
      provider: "gnani",
      tts_model: "timbre-v2.5",
      speaker: "Suhana",
      voice_tier: "clear",
      tier_label: "Clear",
      gender: null,
      languages: ["te-IN", "hi-IN", "en-IN"],
      note: "Timbre v2.5.",
      verified: true,
      offerable: false,
      unavailable_reason: clearRefusal,
      not_on_offer: false,
    },
  ];
  return {
    control: "ours",
    selectable: true,
    source: "engine",
    note: "Pick the voice this agent speaks in.",
    voices,
    tiers: [
      {
        provider: "gnani",
        label: "Clear",
        offerable: 0,
        in_catalogue: 1,
        note:
          realm === "client"
            ? "No Clear voice is available on your account at the moment, so there is nothing to choose in that quality here. Ask your account manager if you want one."
            : "1 Clear voice(s) are in the catalogue and none of them can be offered right now — the reason is on each row. Reading the catalogue again will not change that.",
      },
      { provider: "cartesia", label: "Studio", offerable: 1, in_catalogue: 1, note: null },
    ],
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
    disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    recording_notice_enabled: true,
    caller_memory_notice_line: "I keep a short note of what you ask about.",
    caller_memory_enabled: false,
    opening_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
    truthful_answer_rule:
      "Whatever these settings say, the agent always answers honestly when a caller asks.",
    engine: "pipecat",
    published: true,
    inbound_number_count: 1,
    extraction_fields: [],
    llm_model: null,
    llm_model_effective: "gpt-4o-mini",
    llm_model_source: "platform",
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
} satisfies KycRecord;

/** A prepaid wallet with money on it — the state most accounts are in. */
export function prepaidWallet(over: Partial<Wallet> = {}): Wallet {
  return {
    tenant_id: "o1",
    prepaid: true,
    balance_inr: "3400.00",
    is_low: false,
    low_balance_threshold_inr: "200.00",
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
      adjustments_inr: "0.00",
      spent_inr: "8400.00",
      added_inr: "12100.00",
      refunded_inr: "0.00",
    },
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

/** The autodialer notice filed with the access provider and in effect. */
export const AUTODIALER_NOTICE_RECORDED = {
  recorded: true,
  state: "notified",
  access_provider: "Airtel",
  objective: "Appointment reminders",
  notified_on: "2026-09-01",
  notice_reference: null,
  effective: true,
  declared_clis: ["+919848022338"],
  undeclared_clis: [],
} satisfies AutodialerNotice;

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
