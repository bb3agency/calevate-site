import { act } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiQuota } from "@/lib/api/aiQuota";
import type { Margin } from "@/lib/api/admin";
import type { CallDetail } from "@/lib/api/client";
import AdminLayout from "@/app/admin/layout";
import AcceptInvitationPage from "@/app/(auth)/auth/accept-invitation/page";
import ClientAccountPage from "@/app/(auth)/auth/account/page";
import AdminBootstrapPage from "@/app/(auth)/auth/admin/bootstrap/page";
import AdminForgotPasswordPage from "@/app/(auth)/auth/admin/forgot-password/page";
import AdminSessionPage from "@/app/(auth)/auth/admin/page";
import AdminResetPasswordPage from "@/app/(auth)/auth/admin/reset-password/page";
import AdminFirstPartySignInPage from "@/app/(auth)/auth/admin/sign-in/page";
import ClientForgotPasswordPage from "@/app/(auth)/auth/forgot-password/page";
import ClientResetPasswordPage from "@/app/(auth)/auth/reset-password/page";
import ClientFirstPartySignInPage from "@/app/(auth)/auth/sign-in/page";
import ClientHealthPage from "@/app/admin/health/page";
import FleetSpendPage from "@/app/admin/spend/page";
import TenantSpendPage from "@/app/admin/tenants/[tenantId]/spend/page";
import CommercialsPage from "@/app/admin/tenants/[tenantId]/commercials/page";
import TenantCreditsPage from "@/app/admin/tenants/[tenantId]/credits/page";
import LifecyclePage from "@/app/admin/tenants/[tenantId]/lifecycle/page";
import HeldAccountsPage from "@/app/admin/holds/page";
import NewClientPage from "@/app/admin/new/page";
import GlobalDncPage from "@/app/admin/ops/dnc/page";
import EngineLatencyPage from "@/app/admin/ops/engine-latency/page";
import OperatorsPage from "@/app/admin/operators/page";
import OpsConfigPage from "@/app/admin/ops/config/page";
import OpsPage from "@/app/admin/ops/page";
import AdminClientsPage from "@/app/admin/page";
import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import FeatureFlagsPage from "@/app/admin/tenants/[tenantId]/feature-flags/page";
import LlmModelPage from "@/app/admin/tenants/[tenantId]/llm-model/page";
import FirstCampaignReviewPage from "@/app/admin/tenants/[tenantId]/first-campaign-review/page";
import TenantInvoicePage from "@/app/admin/tenants/[tenantId]/invoice/page";
import TenantKycPage from "@/app/admin/tenants/[tenantId]/kyc/page";
import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import AgentDetailPage from "@/app/c/[slug]/agents/[agentId]/page";
import AgentScriptPage from "@/app/c/[slug]/agents/[agentId]/script/page";
import NewAgentPage from "@/app/c/[slug]/agents/new/page";
import AgentsPage from "@/app/c/[slug]/agents/page";
import AiAssistPage from "@/app/c/[slug]/ai-assist/page";
import AttentionPage from "@/app/c/[slug]/attention/page";
import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
import CallsPage from "@/app/c/[slug]/calls/page";
import CampaignReviewPage from "@/app/c/[slug]/campaign-review/page";
import CampaignsPage from "@/app/c/[slug]/campaigns/page";
import DataRightsPage from "@/app/c/[slug]/data-rights/page";
import CallerNoticePage from "@/app/c/[slug]/caller-notice/page";
import ClientInvoicePage from "@/app/c/[slug]/invoice/page";
import ClientSpendPage from "@/app/c/[slug]/spend/page";
import CallbacksPage from "@/app/c/[slug]/callbacks/page";
import DoNotCallPage from "@/app/c/[slug]/do-not-call/page";
import IntegrationsPage from "@/app/c/[slug]/integrations/page";
import LeadSourcesPage from "@/app/c/[slug]/lead-sources/page";
import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import LeadDetailPage from "@/app/c/[slug]/leads/[leadId]/page";
import LeadsPage from "@/app/c/[slug]/leads/page";
import MessagingConsentPage from "@/app/c/[slug]/messaging-consent/page";
import ClientRealmLayout from "@/app/c/[slug]/layout";
import DashboardPage from "@/app/c/[slug]/page";
import PerformancePage from "@/app/c/[slug]/performance/page";
import QualityPage from "@/app/c/[slug]/quality/page";
import QaSamplingPage from "@/app/admin/qa-sampling/page";
import QaSampleReviewPage from "@/app/admin/qa-sampling/[sampleId]/page";
import AlertsPage from "@/app/c/[slug]/settings/alerts/page";
import ClientLlmModelPage from "@/app/c/[slug]/settings/models/page";
import TeamPage from "@/app/c/[slug]/settings/team/page";
import CreditsPage from "@/app/c/[slug]/credits/page";
import UsagePage from "@/app/c/[slug]/usage/page";
import AgreementsPage from "@/app/c/[slug]/agreements/page";
import VerificationPage from "@/app/c/[slug]/verification/page";
import InvitePage from "@/app/invite/page";
import LegalDocumentRoute from "@/app/legal/[slug]/page";
import LegalIndexPage from "@/app/legal/page";
import Home from "@/app/page";
import ClientConsoleJunction from "@/app/c/page";
import SignupPage from "@/app/signup/page";

import {
  KNOWN_A11Y_EXEMPTIONS,
  UNSWEPT_SCREENS,
  expectNoA11yViolations,
  routePagesOnDisk,
  staleExemptions,
} from "./a11y";
import { renderAdminRoute } from "./adminRoute";
import { problem, renderClientPage, type Routes } from "./harness";

/**
 * The accessibility gate, over every screen the router serves.
 *
 * See `tests/a11y.ts` for why axe-core is used directly, what the exemption tables mean,
 * and — importantly — what this gate CANNOT see. A green run here is a statement about
 * the machine-checkable third of WCAG, not a claim that the console is accessible.
 *
 * ## Why a dedicated sweep, rather than scanning inside the harness
 *
 * The tempting design is to run axe from `renderClientPage`/`renderAdminPage` so all 266
 * existing renders are covered for free. Rejected for two reasons. `renderAdminPage` is
 * SYNCHRONOUS and `axe.run` is not, so it would have to become async and 97 call sites
 * across 8 files would change — churn with no assertion added. And most of those 266
 * renders are of empty, loading or error states, which is not where the barriers are: a
 * table with no rows has no unlabelled header. The screens below are rendered POPULATED,
 * which is the state a client actually uses and the state where axe has something to say.
 *
 * The cost of a hand-written sweep is that it falls behind the router. That is what
 * `the sweep covers every screen the router serves` below exists to prevent — it reads
 * `src/app` off disk, so a new `page.tsx` fails this file until it is either swept or
 * given a reason in `UNSWEPT_SCREENS`.
 */

const ORG = { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" };

/** An owner: the role that can see the most, and therefore renders the most markup. */
/**
 * A STOPPED wallet — the state of `/c/<slug>/credits` that renders the most markup: the
 * alert banner, the runway sentence, the full drawdown and the ledger beneath it. The
 * healthy state renders a strict subset of it, which is the same rule the agreements and
 * AI-help entries in this file are fixtured by.
 */
const WALLET_STOPPED = {
  tenant_id: "00000000-0000-0000-0000-0000000000aa",
  prepaid: true,
  balance_inr: "0.00",
  is_low: true,
  low_balance_threshold_inr: "200.00",
  outbound_stopped: true,
  runway: {
    basis: "empty",
    days: null,
    daily_burn_inr: "340.00",
    history_days: 30,
    beyond_horizon: false,
    window_days: 30,
    min_history_days: 7,
    max_days: 365,
  },
  minutes_left: 0,
  drawdown: {
    calls_inr: "8400.00",
    ai_assist_inr: "300.00",
    adjustments_inr: "0.00",
    spent_inr: "8700.00",
    added_inr: "8700.00",
    refunded_inr: "0.00",
  },
};

const WALLET_LEDGER = {
  entries: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      delta_inr: "-42.50",
      reason: "usage",
      ref: "call:9",
      balance_after_inr: "0.00",
      occurred_at: "2026-08-30T09:00:00Z",
      payment_ref: null,
    },
    {
      id: "22222222-2222-4222-8222-222222222222",
      delta_inr: "2500.00",
      reason: "topup",
      ref: "pay_a1b2c3",
      balance_after_inr: "2542.50",
      occurred_at: "2026-08-01T09:00:00Z",
      payment_ref: "pay_a1b2c3",
    },
  ],
  payments: [
    {
      payment_ref: "pay_a1b2c3",
      credited_inr: "2500.00",
      entries: 1,
      first_at: "2026-08-01T09:00:00Z",
    },
  ],
};

/** One attempt that never finished, so the panel above the top-up controls renders. */
const WALLET_ATTEMPTS = [
  {
    id: "33333333-3333-4333-8333-333333333333",
    receipt: "CAL-2608-0007",
    amount_inr: "2500.00",
    pack_id: null,
    outcome: "failed",
    started_at: "2026-08-30T10:00:00Z",
  },
];

const CREDIT_PACKS = {
  list_rate_inr_per_min: "8.00",
  packs: [
    {
      pack_id: "starter",
      amount_inr: "1000.00",
      paid_credits: "1000.00",
      bonus_credits: "0.00",
      total_credits: "1000.00",
      bonus_pct: "0",
      effective_rate_inr_per_min: "8.00",
      talk_time_minutes: 125,
      best_value: false,
    },
    {
      pack_id: "growth",
      amount_inr: "5000.00",
      paid_credits: "5000.00",
      bonus_credits: "400.00",
      total_credits: "5400.00",
      bonus_pct: "8",
      effective_rate_inr_per_min: "7.41",
      talk_time_minutes: 675,
      best_value: true,
    },
  ],
};

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: [
    "calls:read",
    "calls:read_raw",
    "leads:read",
    "leads:write",
    "leads:dispatch",
    "campaigns:read",
    "campaigns:write",
    "kb:read",
    "kb:write",
    "billing:read",
    // The wallet read every client role holds, `staff` included — `/c/<slug>/credits`
    // refuses without it, and a swept refusal is a sweep of a RestrictionNote rather
    // than of the screen.
    "wallet:read",
    "members:read",
    "members:write",
    "dnc:read",
    "dnc:write",
    // The integrations and lead-source screens gate their writes on `org:manage` and
    // their reads on `org:read`; an owner holds both, and without them those two screens
    // would be swept in their read-only costume — fewer controls, fewer chances to find a
    // defect, which is the opposite of what this sweep is for.
    "org:read",
    "org:manage",
    "agents:read",
  ],
  impersonating: false,
  organization: ORG,
};

const ADMIN_ME = {
  user_id: "admin-1",
  realm: "admin",
  role: "superadmin",
  permissions: ["admin:read", "admin:write"],
  impersonating: false,
};

/** One screen under test: what to render, and the wire it renders from. */
interface Screen {
  /** The route path, as `routePagesOnDisk` reports it — the coverage guard's key. */
  file: string;
  realm: "client" | "admin";
  element: () => React.ReactElement;
  routes: Routes;
}

/**
 * A live session row, as `GET /v1/auth/{realm}/session` answers it (D-174).
 *
 * Ids and state, with no email address — `SessionOut` in `apps/api/authn/routes.py`
 * deliberately carries none, and a fixture that invented one would be a fixture the
 * screens could accidentally learn to read.
 */
const ADMIN_SESSION_ROW = {
  realm: "admin",
  subject_id: "0192f0aa-0000-7000-8000-0000000000a1",
  mfa_complete: true,
  email_verified: true,
};

const CLIENT_SESSION_ROW = {
  realm: "client",
  subject_id: "0192f0aa-0000-7000-8000-0000000000c1",
  mfa_complete: true,
  email_verified: true,
};

/** The one refusal that means "there is no session here" — never `invalid_credentials`. */
const UNAUTHORIZED_SESSION = problem(401, {
  type: "urn:calevate:auth/unauthorized",
  title: "Unauthorized",
  detail: "Your session is not valid.",
  kind: "auth",
});

/**
 * Put a link token in the URL the way an emailed link does, then render.
 *
 * `useLinkToken` reads `location.search` in an effect and strips the parameter with
 * `history.replaceState`; jsdom implements both, so this is the real path rather than a
 * mock of it. The value is nonsense on purpose — nothing here submits it.
 */
function withLinkToken(
  path: string,
  element: React.ReactElement,
): React.ReactElement {
  window.history.replaceState(null, "", `${path}?token=a11y-sweep-token`);
  return element;
}

/** The invoice screens ask for the CURRENT IST month, so the fixture key must follow it. */
const IST_MONTH = new Date()
  .toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })
  .slice(0, 7);

/**
 * A month with money in it, in BOTH realms — the client's half and the operator's.
 *
 * POPULATED and NOT balanced on purpose: `itemised_charge_inr` is deliberately less than
 * `period_charge_inr` with a `residual_reason` beside it, because the residual panel is
 * markup this sweep would otherwise never see — it renders only when the server says
 * there is something to explain.
 *
 * The client fixture carries NO cost or margin field, and that is not an omission: the
 * response model declares none (`spend_routes.SpendOut`), and a fixture that invented one
 * would be a fixture the screen could accidentally learn to read.
 */
const SPEND = {
  month: IST_MONTH,
  charge_basis: "allocated",
  calls: 2,
  minutes_used: "18.5000",
  retainer_inr: "4999.00",
  period_charge_inr: "1250.00",
  itemised_charge_inr: "1200.00",
  itemisation_residual_inr: "50.00",
  residual_reason: "no_billable_minutes",
  by_agent: [
    {
      agent_id: "agent-1",
      agent_name: "Front desk",
      calls: 2,
      minutes: "18.5000",
      charged_inr: "1200.00",
    },
  ],
  top_calls: [
    {
      call_id: "c1",
      agent_id: "agent-1",
      agent_name: "Front desk",
      started_at: "2026-08-12T09:00:00Z",
      direction: "inbound",
      minutes: "12.0000",
      charged_inr: "900.00",
    },
  ],
  top_calls_truncated: false,
};

/** The operator's half of the same month: both directions, and the currency caveat. */
const TENANT_SPEND = {
  ...SPEND,
  plan_tier: "managed",
  revenue_inr: "6249.00",
  cost_inr: "2100.00",
  margin_inr: "4149.00",
  margin_pct: "66.40",
  cost_currency: "INR",
  cost_currency_stated: false,
  unattributed: { minutes: "0.0000", cost_inr: "120.00" },
  by_unit: [{ unit_type: "telephony_s", qty: "1110", cost_inr: "480.00" }],
  by_agent: [
    {
      ...SPEND.by_agent[0],
      cost_inr: "700.00",
      margin_inr: "500.00",
      cost_currency_assumed: true,
    },
  ],
  top_calls: [
    {
      ...SPEND.top_calls[0],
      cost_inr: "540.00",
      margin_inr: "360.00",
      cost_currency_assumed: true,
    },
  ],
};

/** The fleet board, with one client LOSING money so the marked row is swept too. */
const FLEET_SPEND = {
  month: IST_MONTH,
  clients: 2,
  revenue_inr: "6249.00",
  cost_inr: "7100.00",
  margin_inr: "-851.00",
  margin_pct: null,
  tenants: [
    {
      tenant_id: "t2",
      name: "Vasavi Dental",
      slug: "vasavi",
      plan_tier: "prepaid",
      minutes_used: "40.0000",
      calls: 9,
      revenue_inr: "0.00",
      cost_inr: "5000.00",
      margin_inr: "-5000.00",
      margin_pct: null,
    },
    {
      tenant_id: "t1",
      name: "Sri Traders",
      slug: "sri-traders",
      plan_tier: "managed",
      minutes_used: "18.5000",
      calls: 2,
      revenue_inr: "6249.00",
      cost_inr: "2100.00",
      margin_inr: "4149.00",
      margin_pct: "66.40",
    },
  ],
};

/**
 * One invoice fixture for BOTH realms, because there is one document: the admin screen
 * and the client screen render the same `components/invoiceDocument.tsx`. A configured,
 * GST-registered supply, so the sweep sees the fullest markup — identity block, place of
 * supply, per-line SAC and a tax head — rather than a bill of supply's shorter sheet.
 */
const INVOICE = {
  invoice_number: "CAL-202608-0192f0aa",
  month: IST_MONTH,
  generated_at: "2026-08-13T04:30:00Z",
  document_type: "tax_invoice",
  document_blockers: [],
  supplier: {
    legal_name: "Calevate",
    address: "Plot 42, Madhapur, Hyderabad 500081",
    gstin: "36AABCC1234D1Z5",
    state_name: "Telangana",
    sac: "998315",
  },
  organization: {
    id: "t1",
    name: "Sri Traders",
    billing_email: "accounts@example.com",
    gstin: "29AAACR5055K1Z6",
    state_name: "Karnataka",
  },
  place_of_supply: {
    state_code: "29",
    state_name: "Karnataka",
    supply_type: "interstate",
    basis:
      "Location of the recipient, a registered person (IGST Act s.12(2)(a)).",
  },
  line_items: [
    {
      description: "Monthly plan fee",
      qty: "1",
      unit_inr: "9999.00",
      amount_inr: "9999.00",
      sac: "998315",
    },
  ],
  subtotal_inr: "9999.00",
  gst_inr: "1799.82",
  gst_rate_pct: "18",
  tax_components: [{ label: "IGST", rate_pct: "18", amount_inr: "1799.82" }],
  total_inr: "11798.82",
  usage: { calls: 412, included_minutes: 500, minutes_used: "120.5" },
};

const slug = Promise.resolve({ slug: "acme" });
const tenant = Promise.resolve({ tenantId: "t1" });

/**
 * Fixtures below are POPULATED on purpose, and are about MARKUP rather than business
 * truth: a table needs rows before it can have a header defect, a form needs fields
 * before a label can be missing. The exact figures are asserted by the 43 behavioural
 * test files; here they only have to make the real branch render, which
 * `assertScreenRendered` enforces.
 */
const CALL = {
  id: "c1",
  agent_id: "a1",
  agent_name: "Reception",
  // `as const` so the literal survives into `satisfies CallDetail` below: a widened
  // `string` is not the closed union the wire declares.
  direction: "inbound" as const,
  status: "completed",
  caller_e164: "+919876543210",
  started_at: "2026-08-13T04:30:00Z",
  duration_s: 92,
  outcome_tag: "appointment_booked",
  sentiment: "positive",
  summary: "Caller asked for a Tuesday slot.",
  lead_id: "lead-a",
};

const AGENT = {
  id: "agent-1",
  name: "Front desk",
  published: true,
  status: "live",
  direction: "outbound",
  language: "te-IN",
  disclosure_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  // D-163: the two notices this agent volunteers, and the switch on each. Both ON, which
  // is what a new agent is born with — and the switches are the one pair of interactive
  // controls on the client agents screen, so they are exactly what this scan is for.
  ai_disclosure_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_enabled: true,
  recording_notice_line: "This call is being recorded.",
  caller_memory_notice_line: "I keep a short note of what you ask about.",
  caller_memory_enabled: false,
  recording_notice_enabled: true,
  opening_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
  truthful_answer_rule:
    "Whatever these settings say, the agent always answers honestly when a caller asks.",
  // D-440 widened `AgentOut`: when it was retired (NULL until it is) and how many lines it
  // answers in parallel. Both are REQUIRED on the wire.
  archived_at: null,
  inbound_number_count: 2,
  extraction_fields: [
    { key: "name", label: "Name", type: "string", required: true },
  ],
};

/** A retired agent, so the roster sweep covers the archive section as well as the roster. */
const ARCHIVED_AGENT = {
  ...AGENT,
  id: "agent-old",
  name: "Old receptionist",
  status: "archived",
  archived_at: "2026-07-02T09:30:00Z",
  published: false,
  inbound_number_count: 0,
};

/** One agent's activity, for the roster's second line. */
const AGENT_STATS = [
  {
    agent_id: "agent-1",
    status: "live",
    calls_total: 412,
    calls_inbound: 400,
    calls_outbound: 12,
    calls_connected: 380,
    outcomes: { appointment_booked: 120 },
    last_call_at: "2026-08-20T11:05:00Z",
  },
];

/**
 * One OPEN knowledge gap — a question a live agent could not answer, found from a redacted
 * transcript. Populated so the per-agent `KnowledgeGaps` card renders its full markup (the
 * count badge, the quote, and the Teach/Dismiss controls) rather than its empty state,
 * which is where the labelling risk this sweep is for actually lives.
 */
const KNOWLEDGE_GAP = {
  id: "0192f0aa-5555-7000-8000-000000000001",
  agent_id: "agent-1",
  agent_name: "Front desk",
  call_count: 3,
  example_answer: "I'm not certain about that — let me have the team call you back.",
  example_question: "Do you do root canal treatment?",
  first_seen_at: "2026-08-10T06:00:00Z",
  last_seen_at: "2026-08-13T04:30:00Z",
  occurrence_count: 5,
  signal: "dont_know",
  status: "open",
  topic_key: "root_canal",
  topic_label: "Root canal treatment",
  kb_source_id: null,
  resolution: null,
  resolved_at: null,
  resolved_by: null,
};

/**
 * A populated structured call script (`GET /v1/agents/{id}/script`), so the builder renders
 * its full authoring surface — opening line, ordered steps, FAQ pairs with a fallback, end-
 * call rules, declared merge variables and the AI-assist panel — rather than an empty form.
 * That is the state with the labelling risk (every step and FAQ is its own labelled control
 * pair), which is what this sweep exists to scan.
 */
const SCRIPT = {
  script: {
    opening_line:
      "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is recorded.",
    steps: [
      { instruction: "Confirm the caller's name and why they are calling." },
      { instruction: "Offer the next available appointment slot." },
    ],
    faqs: [
      {
        question: "What are your consultation charges?",
        answer: "Our consultation fee is {{ consultation_fee }}.",
      },
    ],
    faq_fallback:
      "I'm not certain about that — our team will call you back with the details.",
    end_call_extra_rules: ["Always thank the caller before ending the call."],
    variables: [
      { key: "consultation_fee", label: "Consultation fee", example: "₹500" },
    ],
    raw_override: null,
  },
  version: 4,
  is_freeform: false,
  has_pending: false,
  standard_variables: [
    { key: "business_name", label: "Business name" },
    { key: "caller_name", label: "Caller name" },
  ],
};

const LEAD = {
  id: "lead-a",
  name: "Ramesh Kumar",
  phone_e164: "+919876543210",
  status: "new",
  source: "call",
  data: { name: "Ramesh Kumar" },
  schema_version: 1,
  call_count: 2,
  is_repeat_caller: false,
  last_call_id: "c1",
  created_at: "2026-08-10T06:00:00Z",
  updated_at: "2026-08-13T04:30:00Z",
  assigned_to: null,
  assigned_to_name: null,
};

const CAMPAIGN = {
  id: "0192f0aa-2222-7000-8000-000000000001",
  name: "Diwali offer",
  status: "draft",
  classification: "promotional",
  contacts: 120,
  connected: 0,
  created_at: "2026-08-12T09:00:00Z",
  launched_at: null,
  consent_provenance_blocker: null,
};

/**
 * `GET /v1/legal/readiness` with nothing accepted — the state the agreements screen has
 * the most markup in, and the state a client actually arrives in.
 */
const LEGAL_READINESS = {
  may_operate: false,
  verdict:
    "Your agreements have not been accepted, so this account cannot make outgoing calls or publish an agent yet.",
  outstanding_documents: 2,
  pending_legal_review: true,
  provisional_notice: "These documents are drafts and have not been through legal review.",
  acceptance_statement:
    "I accept the Terms of Service and the Privacy Policy on behalf of this business.",
  acceptance_statement_version: "1+pre-review",
  can_accept: true,
  can_accept_reason: null,
  documents: [
    {
      slug: "terms",
      title: "Terms of Service",
      href: "/legal/terms",
      blocking: true,
      version: "1+pre-review",
      provisional: true,
      effective_date: null,
      state: "never_accepted",
      headline: "Not accepted yet.",
      accepted_version: null,
      accepted_at: null,
      accepted_by_name: null,
    },
    {
      slug: "privacy",
      title: "Privacy Policy",
      href: "/legal/privacy",
      blocking: true,
      version: "1+pre-review",
      provisional: true,
      effective_date: null,
      state: "accepted",
      headline: "Accepted.",
      accepted_version: "1+pre-review",
      accepted_at: "2026-08-20T06:00:00Z",
      accepted_by_name: "Priya Nair",
    },
    {
      slug: "subprocessors",
      title: "Sub-processors",
      href: "/legal/subprocessors",
      blocking: false,
      version: "1+pre-review",
      provisional: true,
      effective_date: null,
      state: "not_required",
      headline: "Published for you to read. There is nothing to accept.",
      accepted_version: null,
      accepted_at: null,
      accepted_by_name: null,
    },
  ],
  blockers: [
    {
      rule: "agreements_not_accepted",
      title: "Agreements not accepted",
      reason: "This account has not accepted its agreements yet.",
      actor: "client",
      next_step:
        "The account owner reads each agreement and accepts it on this screen.",
    },
  ],
};

const MEMBERS = [
  { id: "u1", name: "Priya Nair", role: "owner" },
  { id: "u2", name: "Kiran Babu", role: "staff" },
];

/** The Leads table's resolved columns (`apps/api/crm/columns.py`) — one fixed, one from
 *  the tenant's extraction schema, which is the shape the chooser and the CSV share. */
const LEAD_COLUMNS = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  {
    key: "budget_band",
    label: "Budget band",
    kind: "extraction",
    type: "enum",
  },
];

const USAGE = {
  month: "2026-08",
  minutes_used: "120.5",
  calls: 41,
  included_minutes: 500,
  overage_minutes: "0",
  overage_minutes_premium: "0",
  overage_minutes_value: "0",
  overage_cost_inr: "0.00",
  overage_rate_inr: "6.5000",
  overage_rate_value_inr: null,
  // D-455's model surcharge. Present and ZERO, which is the shipped state — every plan
  // quotes no surcharge until a founder sets one — and NOT absent: the field is required
  // on the wire, and a fixture missing it is a server this deployment cannot have.
  llm_surcharge_rate_inr: null,
  llm_surcharge_minutes: "0.00",
  llm_surcharge_inr: "0.00",
  llm_surcharge_models: [],
  monthly_fee_inr: "4999.00",
  cap_minutes: null,
  minutes_left: null,
  capped: false,
  spend_used_inr: "4999.00",
  plan_tier: "managed",
  credit_balance_inr: null,
};

/** A self-serve account that has just hit its AI ceiling — the state with the offer on
 *  it, so the sweep sees the notice, the button and the copy around them.
 *
 *  THE TWO COUNTS ARE PRODUCIBLE BY THE SERVER AT TODAY'S PRICE, and they were not: this
 *  fixture still carried 200 and 1,000, which divide ₹100 and ₹500 by a ₹0.50 nominal
 *  that has not existed since D-146. `billing/ai_quota.py` derives both from
 *  `assist_nominal_inr(model)` — ₹0.24 on `gpt-4o-mini` (D-410) — so ₹100 included is
 *  416 and the ₹500 block is 2,083. D-410 recomputed the same three figures in
 *  `aiQuota.test.tsx` and `callAssist.test.tsx` and did not reach this file; a fixture no
 *  server can answer with is a wrong number carrying a fixture's authority, and this one
 *  is the state an owner reads while deciding whether to spend ₹500.
 *
 *  `satisfies AiQuota` for the reason `wireFixtureGuard.test.ts` argues: the `Routes` map
 *  takes `unknown`, so a plain literal here is checked by nothing at all. It pins the
 *  SHAPE; the comment above is what pins the values, because no type can. */
const AI_QUOTA_AT_CEILING = {
  month: "2026-08",
  plan_tier: "self_serve",
  state: "ceiling_reached",
  included_inr: "100.00",
  used_inr: "100.00",
  allowance_inr: "100.00",
  remaining_inr: "0.00",
  requests_used: 214,
  requests_included: 416,
  requests_remaining: 0,
  extra_purchased_inr: null,
  extra_block_inr: "500.00",
  extra_block_requests: 2083,
  extra_available: true,
  extra_unavailable_reason: null,
} satisfies AiQuota;

const DASHBOARD = {
  calls_today: 3,
  calls_7d: 24,
  leads_new_7d: 9,
  hot_leads_open: 2,
  avg_duration_s_7d: 118,
  sentiment_split: { positive: 12, neutral: 8, negative: 4 },
  outcome_split: { appointment_booked: 9, enquiry: 15 },
  after_hours_captured_7d: 4,
  after_hours_basis: "default_window",
  minutes_used_month: "120.5",
  daily_7d: [
    {
      ist_date: "2026-08-07",
      total: 4,
      completed: 3,
      no_answer: 1,
      failed: 0,
      in_flight: 0,
    },
    {
      ist_date: "2026-08-08",
      total: 6,
      completed: 4,
      no_answer: 1,
      failed: 1,
      in_flight: 0,
    },
  ],
};

const TENANT_SUMMARY = {
  id: "t1",
  name: "Sri Traders",
  slug: "sri-traders",
  status: "active",
  vertical_template: "clinic",
  live_agents: 1,
  calls_7d: 12,
  leads: 4,
  last_call_at: null,
  holds: [],
  capped: false,
};

const HELD_TENANT = {
  tenant_id: "t1",
  name: "Sri Traders",
  slug: "sri-traders",
  plan_tier: "growth",
  signed_up_at: "2026-08-13T04:00:00Z",
  holds: ["kyc_missing"],
};

const PLATFORM = {
  load_shed_mode: "normal",
  outbound_halted: false,
  halt_reason: null,
  outbox_dead_letters: {
    depth: 9,
    oldest_at: "2026-08-04T04:15:00Z",
    by_job: [
      {
        job: "deliver_outbound_webhook",
        depth: 6,
        oldest_at: "2026-08-04T04:15:00Z",
      },
    ],
  },
  tm_registration: {
    status: "active",
    tm_id: "TM-110022",
    registered_at: "2026-01-04T06:30:00Z",
    verified_at: "2026-08-01T06:30:00Z",
    is_live: true,
  },
};

/**
 * The platform-configuration panel's read (PLATFORM-CONFIG §8 panel 2).
 *
 * Two fields rather than one, and not for volume: an EDITABLE row and an `env`-pinned
 * READ-ONLY row are different markup — one renders a button, the other renders the
 * refusal sentence with the variable name in it — so a one-row fixture would scan half
 * the panel.
 */
/** One installed credential and one that is not — different markup, so a one-row
 *  fixture would scan half the panel. Nothing here carries a value: there is no field
 *  on the wire that could. */
const OPS_SECRETS = {
  secrets: [
    {
      key: "bolna_api_key",
      env_var: "BOLNA_API_KEY",
      installed: true,
      version: 2,
      versions: 2,
      last_four: "9f3c",
      kek_id: 1633907231,
      created_at: "2026-08-10T06:30:00Z",
      created_by: "Ops",
      shadowed_by_env: false,
      testable: true,
    },
    {
      key: "sarvam_api_key",
      env_var: "SARVAM_API_KEY",
      installed: false,
      version: 0,
      versions: 0,
      last_four: "",
      kek_id: 0,
      created_at: null,
      created_by: null,
      shadowed_by_env: true,
      testable: true,
    },
  ],
};

const OPS_KEK = {
  active_kek_id: 1633907231,
  has_retired_kek: false,
  versions: 2,
  current: 2,
  pending: 0,
};

const OPS_CONFIG = {
  fields: [
    {
      key: "self_serve_inr_per_min",
      env_var: "SELF_SERVE_INR_PER_MIN",
      value: "6.00",
      source: "db",
      default: "6.00",
      has_default: true,
      kind: "decimal",
      options: [],
      editable: true,
      applies: "live",
      caveat: null,
      updated_by: "Ops",
      updated_at: "2026-08-12T09:00:00Z",
      note: "Q3 price change",
    },
    {
      key: "object_store_bucket",
      env_var: "OBJECT_STORE_BUCKET",
      value: "calevate-prod",
      source: "env",
      default: null,
      has_default: false,
      kind: "string",
      options: [],
      editable: false,
      applies: "live",
      caveat: null,
      updated_by: null,
      updated_at: null,
      note: null,
    },
  ],
  config_version: 42,
  stale: false,
  never_loaded: false,
  config_changed_at: "2026-08-12T09:00:00Z",
};

// TWO rows whose states differ: an ATTESTED, offerable Azure model (its values, source and
// "offerable" badge render) and an OpenAI model that is NOT offerable and NOT attested (the
// greyed reference, the "needs a credential and a price" verdict and the "offered only once
// you attest" note render). A one-row fixture would leave half the panel's markup unscanned.
const OPS_MODEL_PRICES = {
  prices: [
    {
      model: "gpt-4o-mini",
      provider: "azure_openai",
      credential_installed: true,
      price_attested: true,
      offerable: true,
      input_usd_per_mtok: "0.150000",
      output_usd_per_mtok: "0.600000",
      effective_from: "2026-08-01T00:00:00Z",
      attested_at: "2026-08-12T09:00:00Z",
      attested_by: "Ops",
      source_note: "Azure invoice 2026-08",
      reference_input_usd_per_mtok: "0.15",
      reference_output_usd_per_mtok: "0.60",
      reference_verified: true,
    },
    {
      model: "gpt-5.6-luna",
      provider: "openai",
      credential_installed: false,
      price_attested: false,
      offerable: false,
      input_usd_per_mtok: null,
      output_usd_per_mtok: null,
      effective_from: null,
      attested_at: null,
      attested_by: null,
      source_note: null,
      reference_input_usd_per_mtok: "0.20",
      reference_output_usd_per_mtok: "1.20",
      reference_verified: false,
    },
  ],
  as_of: "2026-08-23T00:00:00Z",
};

// TWO legs whose states differ: an ATTESTED, eligible Azure leg (its facts grid, provenance
// and the "assistant may run here" notice render) and a Google leg that is NOT eligible and
// NOT attested (the blocked-reason notice, the "nobody has looked" note and the record form
// render). A one-leg fixture would leave half the panel's markup unscanned.
const OPS_DASHBOARD_DATA_USE = {
  providers: [
    {
      provider: "azure_openai",
      eligible: true,
      blocked_reason: null,
      dashboard_leg_built: true,
      vendor_account_ref: "calevate-eastus2",
      paid_tier_confirmed: true,
      no_training_opt_in_confirmed: true,
      attested_at: "2026-08-20T09:00:00Z",
      attested_by: "Ops",
      source_note: "Azure portal read 2026-08-20",
    },
    {
      provider: "google",
      eligible: false,
      blocked_reason:
        "This platform cannot yet build a dashboard chat request for Google.",
      dashboard_leg_built: false,
      vendor_account_ref: null,
      paid_tier_confirmed: null,
      no_training_opt_in_confirmed: null,
      attested_at: null,
      attested_by: null,
      source_note: null,
    },
  ],
  statement:
    "I have opened this provider's own console and checked the account our API key belongs to.",
};

/**
 * The identity record, shared by the client screen that submits it and the admin screen
 * that decides it — they read the SAME endpoint (`/v1/compliance/kyc`), the admin one
 * through a view-as session, which is why one fixture serves both.
 */
const KYC_RECORD = {
  recorded: true,
  status: "submitted",
  is_verified: false,
  number_purchase_available: false,
  rejection_reason: null,
  document_kind: "gstin",
  document_ref: "29ABCDE1234F1Z5",
  entity_type: "private_limited",
  evidence_ref: "dpdp/kyc/2026/0007",
  signatory_name: "A Reddy",
  submitted_at: "2026-02-01T06:00:00Z",
  verified_at: null,
};

/** The admin tenant screens all hang off one tenant read plus the panels around it. */
/** One dated agreement, populated so the commercials screen renders every panel. */
const PLAN_ROW = {
  id: "plan-1",
  setup_fee_inr: "5000.0000",
  monthly_fee_inr: "9999.0000",
  included_minutes: 500,
  overage_rate_inr: "7.1250",
  overage_rate_value_inr: null,
  hard_cap_minutes: 2000,
  hard_cap_spend_inr: "20000.0000",
  client_cap_minutes: null,
  client_cap_spend_inr: null,
  concurrency_ceiling: 10,
  effective_from: null,
  effective_to: null,
  created_at: "2026-08-01T04:00:00Z",
  states_pricing: true,
};

const TENANT_ROUTES: Routes = {
  "/v1/admin/me": ADMIN_ME,
  // The KYC screen reads this through `viewAsSession(tenant.slug)`, so the request only
  // goes out AFTER the tenant read lands. Absent from this table the screen rendered its
  // generic failure notice instead of the record — and did so late enough that the scan
  // sometimes finished first, which is the vacuous pass `assertScreenRendered` exists to
  // refuse. It surfaced as an order-dependent failure the moment this file grew screens
  // ahead of it; the hole was always there.
  "/v1/compliance/kyc": KYC_RECORD,
  "/v1/admin/tenants/t1": TENANT_SUMMARY,
  "/v1/admin/tenants/t1/margin": {
    month: "2026-08",
    minutes_used: "1204.5",
    calls: 412,
    revenue_inr: "1015900.00",
    cost_inr: "402350.50",
    margin_inr: "613549.50",
    margin_pct: "60.39",
    tiers: {
      minutes_premium: "900.00",
      minutes_value: "280.00",
      minutes_unattributed: "24.50",
      cost_premium_inr: "300000.00",
      cost_value_inr: "90000.00",
      cost_unattributed_inr: "12350.50",
    },
  } satisfies Margin,
  "/v1/kb/sources?status=pending_approval": [],
  "/v1/kb/sources?status=approved": [],
  "/v1/agents": [AGENT],
  "/v1/campaigns/numbers": [],
  "/v1/campaigns/templates": [],
  // The owner's WhatsApp alert state, read by the operator panel. GRANTED on purpose:
  // it renders the "recorded on" line and the withdrawal control, which the never-asked
  // state does not.
  "/v1/admin/tenants/t1/whatsapp-alerts": {
    status: "granted",
    channel: "self_serve_console",
    captured_at: "2026-08-12T09:00:00Z",
    notice_version: "whatsapp-alerts-v1",
    messageable: true,
    current_notice_version: "whatsapp-alerts-v1",
    current_notice_text:
      "I agree that Calevate may send WhatsApp messages to this number to alert me about activity in my own account, such as a hot lead.",
    delivery_available: false,
    delivery_unavailable_reason: "no_credential",
  },
  "/v1/billing/caps": {
    month: "2026-08",
    plan_cap_minutes: 5000,
    plan_cap_spend_inr: "40000.00",
    client_cap_minutes: null,
    client_cap_spend_inr: null,
    effective_cap_minutes: 5000,
    effective_cap_spend_inr: "40000.00",
    minutes_used: "812.00",
    spend_used_inr: "5002.40",
    capped: false,
  },
};

/** A stored QA report, exactly as `GET /v1/quality/reports` serves one (D-15). */
const QA_REPORT = {
  version: 1,
  client: "acme",
  vertical: "clinic",
  as_of: "2026-07-31",
  model: "offline-heuristic",
  scenarios_total: 58,
  defects: 0,
  red_team: 11,
  everything_captured: { passed: 44, total: 58, basis: "measured" },
  field_left_blank: { passed: 14, total: 58, basis: "measured" },
  trend: "no_baseline",
  scenario_classes: [
    {
      scenario: 1,
      label: "A normal call, start to finish",
      meaning: "the caller's details reach your leads list correctly",
      count: 13,
    },
  ],
  known_limits: [{ label: "Budget (lakhs)", scenarios: 4 }],
};

/**
 * `GET /v1/admin/tenants/{id}/feature-flags` (SURFACES §1), populated so both shapes of
 * row render: a declared flag this client is explicitly overridden on, and a stored row
 * for a flag this build no longer declares.
 */
const FEATURE_FLAGS = {
  tenant_id: "t1",
  items: [
    {
      flag: "call_timing_breakdown",
      declared: true,
      description:
        "Show the per-call timing breakdown on this client's call detail screen. A debug view.",
      consumed_by: null,
      platform_default: false,
      override: true,
      enabled: true,
      source: "tenant_override",
      reason: "Latency complaint on ticket 4471 — timings on for the week.",
      set_by_admin_id: "admin-1",
      set_at: "2026-08-13T04:30:00Z",
    },
    {
      flag: "retired_beta_view",
      declared: false,
      description: null,
      consumed_by: null,
      platform_default: null,
      override: true,
      enabled: false,
      source: "tenant_override",
      reason: "Left over from an older release.",
      set_by_admin_id: "admin-1",
      set_at: "2026-06-01T04:30:00Z",
    },
  ],
};

/**
 * `GET /v1/admin/organizations/{org_id}/llm-defaults`, populated so every shape on the
 * model screen renders: a client with a default OF THEIR OWN (so the "in effect / from
 * this client's own choice" row and the price comparisons appear), a platform default to
 * fall back to, and a second priced option to compare it against.
 */
const LLM_DEFAULTS = {
  default_llm_model: "gpt-4.1-mini",
  effective_default: "gpt-4.1-mini",
  available: [
    {
      model: "gpt-4o-mini",
      provider: "azure-openai",
      platform_cost_inr_per_minute: "0.2400",
      client_surcharge_inr_per_minute: "0",
      is_platform_default: true,
    },
    {
      model: "gpt-4.1-mini",
      provider: "azure-openai",
      platform_cost_inr_per_minute: "0.4830",
      client_surcharge_inr_per_minute: "1.5000",
      is_platform_default: false,
    },
  ],
};

/** One row of the weekly QA spot-check queue (SURFACES §1). */
const QA_SAMPLE = {
  id: "s1",
  tenant_id: "t1",
  tenant_name: "Sri Traders",
  tenant_slug: "sri-traders",
  call_id: "c1",
  agent_name: "Reception",
  week_start: "2026-08-03",
  population: 40,
  target: 2,
  selection_rank: 1,
  selection_seed: "t1:2026-08-03",
  selected_at: "2026-08-10T04:00:00Z",
  started_at: "2026-08-05T06:30:00Z",
  duration_s: 154,
  direction: "inbound",
  outcome_tag: "resolved",
  sentiment: "positive",
  disclosure_played: true,
  verdict: null,
  reviewed_at: null,
};

const CLIENT_SCREENS: Screen[] = [
  {
    // The client shell: sidebar, nav and the mobile drawer that every screen renders
    // inside. `children` stands in for the page so the scan is about the CHROME.
    file: "c/[slug]/layout.tsx",
    realm: "client",
    element: () => (
      <ClientRealmLayout params={slug}>
        <p>screen body</p>
      </ClientRealmLayout>
    ),
    routes: {
      "/v1/me": ME,
      "/v1/attention": { total: 1, counts: { lead_blocked: 1 }, items: [] },
    },
  },
  {
    file: "c/[slug]/page.tsx",
    realm: "client",
    element: () => <DashboardPage params={slug} />,
    routes: {
      "/v1/me": ME,
      "/v1/dashboard": DASHBOARD,
      "/v1/usage": USAGE,
      // The calling-credit tile, in the state worth sweeping: STOPPED, which is the one
      // that carries a sentence and a link rather than a figure alone.
      "/v1/billing/wallet": WALLET_STOPPED,
      "/v1/calls?limit=6": [CALL],
      // The dashboard-home `KnowledgeGaps` card (all agents). One OPEN gap so the sweep
      // covers its populated markup — the count badge, the quote, the agent name and the
      // Teach/Dismiss controls — rather than the empty state.
      "/v1/knowledge-gaps?status=open&limit=20": {
        items: [KNOWLEDGE_GAP],
        open_count: 1,
        total: 1,
      },
    },
  },
  {
    // Two reports so the month picker renders — a single-report fixture would leave the
    // chip group unscanned, which is the control on this screen most likely to be wrong.
    file: "c/[slug]/quality/page.tsx",
    realm: "client",
    element: () => <QualityPage />,
    routes: {
      "/v1/me": ME,
      "/v1/quality/reports": [
        QA_REPORT,
        { ...QA_REPORT, as_of: "2026-06-30", defects: 1 },
      ],
    },
  },
  {
    file: "c/[slug]/calls/page.tsx",
    realm: "client",
    element: () => <CallsPage params={slug} />,
    routes: { "/v1/me": ME, "/v1/calls?limit=100": [CALL] },
  },
  {
    file: "c/[slug]/calls/[callId]/page.tsx",
    realm: "client",
    element: () => (
      <CallDetailPage
        params={Promise.resolve({ slug: "acme", callId: "c1" })}
      />
    ),
    routes: {
      "/v1/me": ME,
      // The REAL field names. This fixture used to send `turns` / `role` / `at_ms` /
      // `recording_available` — none of which the API has — so the page rendered an
      // empty transcript and no recording control, and axe was scanning a screen with
      // most of its content missing. The compiler could not catch it because a `Routes`
      // value is `unknown`; `satisfies CallDetail` is what makes it catchable now.
      "/v1/calls/c1": {
        ...CALL,
        transcript: [
          {
            idx: 0,
            speaker: "agent",
            text: "Namaskaram, Sri Clinic.",
            start_ms: 0,
            redacted: true,
          },
          {
            idx: 1,
            speaker: "caller",
            text: "I need a Tuesday slot.",
            start_ms: 2400,
            redacted: true,
          },
        ],
        has_recording: true,
        disclosure_played: true,
        extraction: { name: "Ramesh Kumar" },
        extraction_valid: true,
        moments: [
          {
            at_ms: 2400,
            kind: "field_captured",
            label: "Name captured",
            source: "derived",
          },
          {
            at_ms: 9000,
            kind: "highlight",
            label: "Caller asked about price",
            source: "model",
          },
        ],
      } satisfies CallDetail,
      "/v1/calls/c1/callback": { eligible: false, reason: "consent_missing" },
    },
  },
  {
    file: "c/[slug]/leads/page.tsx",
    realm: "client",
    element: () => <LeadsPage />,
    routes: {
      "/v1/me": ME,
      "/v1/agents": [AGENT],
      "/v1/members": MEMBERS,
      "POST /v1/leads/search": {
        items: [LEAD],
        // The server's resolved column list (`crm.columns`), one fixed column and one
        // extraction column, so the sweep sees the table the chooser actually renders.
        columns: LEAD_COLUMNS,
        available_columns: LEAD_COLUMNS,
        dropped_column_keys: [],
        total: 1,
        limit: 100,
        offset: 0,
        status_counts_matching_search: {
          new: 1,
          contacted: 0,
          interested: 0,
          hot: 0,
          won: 0,
          lost: 0,
        },
      },
      // The facet rail is part of this screen now, and it is swept WITH values in it —
      // an empty rail renders nothing and would prove nothing about its labelling.
      "/v1/leads/facets": {
        facets: [
          {
            key: "budget_band",
            label: "Budget band",
            values: [
              { value: "over_50l", count: 3, declared: true },
              { value: "under_20l", count: 1, declared: true },
            ],
          },
        ],
        omitted_field_count: 0,
      },
      "/v1/leads/views": {
        items: [
          {
            id: "view-1",
            name: "Hot this week",
            filters: {
              status: "hot",
              agent_id: null,
              assigned_to_me: false,
              fields: {},
            },
            columns: null,
            stale_filter_keys: [],
            stale_column_keys: [],
            created_at: "2026-08-10T06:00:00Z",
            updated_at: "2026-08-10T06:00:00Z",
          },
        ],
      },
    },
  },
  {
    file: "c/[slug]/leads/[leadId]/page.tsx",
    realm: "client",
    element: () => (
      <LeadDetailPage
        params={Promise.resolve({ slug: "acme", leadId: "lead-a" })}
      />
    ),
    routes: {
      "/v1/me": ME,
      "/v1/members": MEMBERS,
      "/v1/leads/lead-a": { ...LEAD, columns: LEAD_COLUMNS },
      "/v1/leads/lead-a/timeline?limit=50": {
        items: [
          {
            kind: "call",
            id: "c1",
            at: "2026-08-13T04:30:00Z",
            title: "Inbound call",
            detail: "Caller asked for a Tuesday slot.",
            href: "/calls/c1",
          },
        ],
        total: 1,
      },
    },
  },
  {
    file: "c/[slug]/agents/page.tsx",
    realm: "client",
    element: () => <AgentsPage params={slug} />,
    routes: {
      "/v1/me": ME,
      "/v1/agents": [AGENT],
      // The archive is a SECOND request (`GET /v1/agents` excludes it), and it is answered
      // with a row so the sweep covers the archive section rather than the two it would
      // otherwise see.
      "/v1/agents?status=archived": [ARCHIVED_AGENT],
      "/v1/agents/stats": AGENT_STATS,
      "/v1/agents/lanes": {
        precedence_rule: "Script decides content.",
        lanes: [
          {
            field: "script",
            lane: "staged",
            precedence: 1,
            why: "It waits for Apply.",
          },
          {
            field: "voice",
            lane: "live",
            precedence: 3,
            why: "Delivery only.",
          },
        ],
        call_cap_default_s: 600,
        call_cap_min_s: 60,
        call_cap_max_s: 3600,
      },
    },
  },
  {
    file: "c/[slug]/agents/[agentId]/page.tsx",
    realm: "client",
    element: () => (
      <AgentDetailPage
        params={Promise.resolve({ slug: "acme", agentId: "agent-1" })}
      />
    ),
    routes: {
      "/v1/me": ME,
      "/v1/agents/agent-1": AGENT,
      "/v1/kb/sources": [
        {
          id: "src-1",
          agent_id: "agent-1",
          name: "Clinic hours",
          kind: "text",
          status: "pending_approval",
          version: 1,
          is_active: false,
          published_at: null,
          chunks: 2,
        },
      ],
      "/v1/agents/agent-1/pending": {
        agent_id: "agent-1",
        agent_status: "live",
        published: true,
        // STAGED, so the sweep covers the amber "changes waiting" block — the state with
        // the most markup, of which the settled one is a subset.
        has_pending: true,
        pending: [
          {
            field: "script",
            lane: "staged",
            staged_version: 9,
            live_version: 4,
            staged_at: "2026-08-12T09:30:00Z",
            headline: "Script v9 is waiting to go live.",
            why: "It waits for Apply.",
          },
        ],
        effective_call_cap_s: 600,
        call_cap_is_platform_default: true,
        worst_case_call_cost_inr: "12.50",
        precedence_rule: "Script decides content.",
        // Diverged, so the sweep covers both voice facts rather than the single one an
        // agreeing agent renders.
        voice: {
          configured: { voice_id: "vidya", provider: "sarvam", catalog: null },
          live: { voice_id: "anushka", provider: "sarvam", catalog: null },
          republish_required: true,
          headline:
            "Callers still hear anushka; vidya reaches them at the next publish.",
        },
        engine_verification: {
          state: "unreachable",
          confirmed: false,
          verified_at: null,
          headline:
            "The voice platform accepted this publish and did not answer when we read it back, so we cannot confirm it is running it. Publish again to re-check.",
        },
      },
      // The Actions tab (ACTIONS feature) reads the agent's tools + the tenant's saved
      // credentials. One tool of each state so the scan covers the configured-action row,
      // the master switch and the credential list.
      "/v1/agents/agent-1/actions": {
        api_actions_enabled: true,
        calendar_available: false,
        tools: [
          {
            id: "tool-1",
            agent_id: "agent-1",
            kind: "custom_api",
            provider: null,
            name: "get_order_status",
            description: "Use when the caller asks about their order.",
            enabled: true,
            trigger: "during_call",
            pre_call_message: "One moment while I check.",
            credential_id: null,
            params: [
              { name: "order_id", source: "ai", type: "string", description: "the order id", required: true },
            ],
            config: { method: "GET", url: "https://api.example.com/orders" },
          },
        ],
      },
      "/v1/integrations/credentials": [
        {
          id: "cred-1",
          kind: "aisensy",
          label: "Main AiSensy key",
          last_four: "1234",
          version: 1,
          non_secret: null,
          created_at: "2026-08-12T09:30:00Z",
          updated_at: "2026-08-12T09:30:00Z",
        },
      ],
      // The `KnowledgeGaps` card scoped to this agent — one OPEN gap so the sweep covers
      // the count badge, the quote and the Teach/Dismiss controls, not the empty state.
      "/v1/knowledge-gaps?agent_id=agent-1&status=open&limit=20": {
        items: [KNOWLEDGE_GAP],
        open_count: 1,
        total: 1,
      },
    },
  },
  {
    // The structured call-script builder. Swept with a populated script so axe sees the
    // real authoring surface — labelled fields for the opening line, each step and FAQ, the
    // variable inserts, and the AI-assist panel — the state where a missing label bites.
    file: "c/[slug]/agents/[agentId]/script/page.tsx",
    realm: "client",
    element: () => (
      <AgentScriptPage
        params={Promise.resolve({ slug: "acme", agentId: "agent-1" })}
      />
    ),
    routes: {
      "/v1/me": ME,
      "/v1/agents/agent-1/script": SCRIPT,
    },
  },
  {
    file: "c/[slug]/agents/new/page.tsx",
    realm: "client",
    element: () => <NewAgentPage params={slug} />,
    routes: {
      "/v1/me": ME,
      "/v1/agents/lanes": {
        precedence_rule: "Script decides content.",
        lanes: [],
        call_cap_default_s: 600,
        call_cap_min_s: 60,
        call_cap_max_s: 3600,
      },
    },
  },
  {
    file: "c/[slug]/attention/page.tsx",
    realm: "client",
    element: () => <AttentionPage params={slug} />,
    routes: {
      "/v1/me": ME,
      "/v1/attention": {
        total: 2,
        counts: { lead_blocked: 1, campaign_stalled: 1 },
        items: [
          {
            kind: "lead_blocked",
            id: "att-1",
            title: "+919876543210 was not called",
            detail: "This person asked not to be called.",
            rule: "dnc",
            occurred_at: "2026-08-13T04:30:00Z",
            href: "/leads",
          },
          {
            kind: "campaign_stalled",
            id: "att-2",
            title: "Campaign is not making calls",
            detail: "Paused with 42 contacts still to call.",
            rule: "paused",
            occurred_at: "2026-08-12T11:00:00Z",
            href: "/campaigns",
          },
        ],
      },
    },
  },
  {
    file: "c/[slug]/campaign-review/page.tsx",
    realm: "client",
    element: () => <CampaignReviewPage />,
    routes: {
      "/v1/me": ME,
      "/v1/compliance/first-campaign-review": {
        required: true,
        status: "pending",
        submitted_at: "2026-08-12T09:00:00Z",
        decided_at: null,
        reviewer_note: null,
        campaign_id: "camp-1",
        campaign_name: "Diwali offer",
      },
    },
  },
  {
    // Swept with a campaign in the list AND the create form open, because the form is
    // where this screen's labelling risk lives: five consent radios, a date, a file
    // input and a classification picker, none of which exist on an empty list.
    file: "c/[slug]/campaigns/page.tsx",
    realm: "client",
    element: () => <CampaignsPage />,
    routes: {
      "/v1/me": ME,
      "/v1/agents": [AGENT],
      "/v1/campaigns": [CAMPAIGN],
      "/v1/campaigns/numbers": [
        {
          id: "num-1",
          e164: "+918041234567",
          series: "140",
          dlt_status: "approved",
        },
      ],
      "/v1/campaigns/templates": [
        {
          id: "tmpl-1",
          classification: "promotional",
          status: "approved",
          body: "Namaskaram, Sri Clinic has an offer for you.",
        },
      ],
    },
  },
  {
    file: "c/[slug]/lead-sources/page.tsx",
    realm: "client",
    element: () => <LeadSourcesPage />,
    routes: {
      "/v1/me": ME,
      "/v1/agents": [AGENT],
      "/v1/lead-sources": {
        items: [
          {
            id: "018f3c00-0000-7000-8000-000000000001",
            source: "meta_lead_ads",
            agent_id: null,
            active: true,
            mapping: { phone: "phone_number" },
            secret_fingerprint: "a1b2c3d4",
            previous_secret_expires_at: null,
            created_at: "2026-08-01T09:00:00Z",
            updated_at: "2026-08-01T09:00:00Z",
          },
        ],
        secret_header: "X-Ingest-Secret",
      },
      "/v1/lead-sources/activity": {
        items: [
          {
            source: "website_form",
            event: "lead.created",
            outcome: "accepted",
            deduplicated: 1,
            error: null,
            first_at: "2026-08-12T09:00:00Z",
            last_at: "2026-08-13T04:00:00Z",
          },
        ],
      },
    },
  },
  {
    // The owner's view on purpose: `calls:read_raw` is what renders the delivery log's
    // fifth column and its "View" control, so a sweep without it would miss the half of
    // the table that has any controls in it at all.
    file: "c/[slug]/integrations/page.tsx",
    realm: "client",
    element: () => <IntegrationsPage />,
    routes: {
      "/v1/me": ME,
      "/v1/integrations/endpoints": [
        {
          id: "e1",
          kind: "webhook",
          url: "https://crm.example.com/calevate",
          events: ["lead.created", "call.completed"],
          active: true,
          secret_fingerprint: "abc12345",
          include_recording_url: false,
          include_transcript: false,
          include_raw_transcript: false,
          created_at: "2026-08-01T10:00:00Z",
        },
      ],
      // The options both create forms are built from. Without it neither form renders,
      // and the sweep would scan a screen with no inputs on it at all.
      // `sheets_delivery_available: true` deliberately — the Sheets form is only OFFERED
      // where the deployment can deliver, so a false here would take its three labelled
      // inputs out of the sweep entirely.
      "/v1/integrations/events": {
        events: [
          "lead.created",
          "lead.updated",
          "call.completed",
          "campaign.completed",
        ],
        sheets_delivery_available: true,
      },
      "/v1/integrations/deliveries": [
        {
          id: "d1",
          event_type: "lead.created",
          status: "delivered",
          attempts: 1,
          first_at: "2026-08-13T10:00:00Z",
          last_at: "2026-08-13T10:00:00Z",
          payload_stored: true,
        },
        {
          id: "d2",
          event_type: "call.completed",
          status: "failed",
          attempts: 3,
          first_at: "2026-08-13T09:00:00Z",
          last_at: "2026-08-13T09:20:00Z",
          payload_stored: false,
        },
      ],
    },
  },
  {
    /**
     * Both forms are present at first paint for an owner, which is what this sweep needs:
     * the labelled inputs, the buttons, the two verdict boxes and the erasure register
     * with its expand controls. The certificate markup only exists after a request has
     * been opened, so it is scanned by its own axe call in `tests/dataRights.test.tsx`
     * rather than left uncovered.
     */
    file: "c/[slug]/data-rights/page.tsx",
    realm: "client",
    element: () => <DataRightsPage />,
    routes: {
      "/v1/me": ME,
      "/v1/compliance/deletion-requests?limit=100": [
        {
          request_id: "0192f0aa-4444-7000-8000-0000000000ab",
          subject_ref: "b1946ac92492d2347c6235b4d2611184",
          status: "pending",
          requested_at: "2026-08-14T06:00:00Z",
          completed_at: null,
          has_certificate: false,
        },
      ],
    },
  },
  {
    /**
     * Every region of this screen paints from ONE response, so a single fixture reaches
     * all of it: the two structured lists, both announcement groups, the open questions
     * and the copy control over the document. The two announcement lists are non-empty on
     * purpose — they render only when an agent has an announcement off, and an empty
     * fixture would sweep a screen missing the markup this entry exists to check.
     */
    file: "c/[slug]/caller-notice/page.tsx",
    realm: "client",
    element: () => <CallerNoticePage />,
    routes: {
      "/v1/me": ME,
      "/v1/compliance/caller-notice": {
        disclaimer:
          "This is a draft and not legal advice. Have your advocate review it.",
        collected: [
          {
            what: "Your name",
            why: "So we can address you and match you to your enquiry.",
          },
          {
            what: "Your phone number",
            why: "So we can call you back about your enquiry.",
          },
        ],
        retention: [
          { what: "Call recordings", days: 90 },
          { what: "Lead records", days: 365 },
        ],
        ai_disclosure_off: ["Reception agent"],
        recording_notice_off: ["Reception agent", "Follow-up agent"],
        open_questions: [
          "Who is your grievance officer, and how does a caller reach them?",
        ],
        notice_markdown:
          "# Privacy notice\n\nWhen you call us, an AI assistant answers.\n",
      },
    },
  },
  {
    file: "c/[slug]/do-not-call/page.tsx",
    realm: "client",
    element: () => <DoNotCallPage />,
    routes: {
      "/v1/me": ME,
      // A BARE ARRAY, which is what `GET /v1/dnc` actually returns
      // (`DncEntryOut[]`, schema.d.ts::list_entries_v1_dnc_get) and what `useDncList`
      // is typed for. This fixture used to wrap the rows in an `{items, total}`
      // envelope with `reason`/`created_at`/`note` fields the payload does not have, so
      // the scan rendered the EMPTY list and never saw a row: the screen happened to
      // survive it because `{}.length` is merely `undefined`. It stopped surviving the
      // moment anything called an array method on the value, which is the point — a
      // fixture that does not match the wire is a test of a screen nobody ships.
      "/v1/dnc?limit=500": [
        {
          id: "dnc-1",
          phone_e164: "+919876543210",
          added_at: "2026-08-11T10:00:00Z",
          removable: true,
          scope: "tenant",
          source: "call_optout",
        },
      ],
    },
  },
  {
    file: "c/[slug]/callbacks/page.tsx",
    realm: "client",
    element: () => <CallbacksPage />,
    routes: {
      "/v1/me": ME,
      // A BARE ARRAY, matching what `GET /v1/callbacks` returns
      // (`ScheduledCallbackOut[]`) and what `useCallbacks` is typed for. Both a live row
      // and a refused one, because the two render DIFFERENT controls — a waiting promise
      // offers "Call it off" and a settled one does not — and a fixture with only one of
      // them would sweep half the screen.
      "/v1/callbacks?limit=200&open_only=false": [
        {
          id: "cb-1",
          agent_id: "agent-1",
          lead_id: null,
          phone_e164: "+919876543210",
          requested_at: "2026-09-08T10:30:00Z",
          status: "scheduled",
          attempts: 0,
          explanation: "Waiting for the time they asked for.",
          last_call_id: null,
          settled_at: null,
          note: "wants the Gachibowli listing",
        },
        {
          id: "cb-2",
          agent_id: "agent-1",
          lead_id: null,
          phone_e164: "+919876543211",
          requested_at: "2026-09-01T10:30:00Z",
          status: "refused",
          attempts: 1,
          explanation: "This number is on the do-not-call list.",
          last_call_id: null,
          settled_at: "2026-09-01T10:31:00Z",
          note: null,
        },
      ],
    },
  },
  {
    file: "c/[slug]/knowledge/page.tsx",
    realm: "client",
    element: () => <KnowledgePage />,
    routes: {
      "/v1/me": ME,
      "/v1/agents": [AGENT],
      // The owner's staff-curation switch (D-487). Without it `StaffCurationSwitch`
      // renders its ProblemNotice and the scan would cover an error panel.
      "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
      "/v1/kb/sources": [
        {
          id: "kb-1",
          agent_id: "agent-1",
          title: "Clinic timings",
          status: "live",
          tier: "T1",
          version: 2,
          updated_at: "2026-08-10T06:00:00Z",
          submitted_by_name: "Priya Nair",
          review_note: null,
        },
      ],
    },
  },
  {
    file: "c/[slug]/messaging-consent/page.tsx",
    realm: "client",
    element: () => <MessagingConsentPage />,
    routes: { "/v1/me": ME },
  },
  {
    file: "c/[slug]/performance/page.tsx",
    realm: "client",
    element: () => <PerformancePage />,
    routes: {
      "/v1/me": ME,
      "/v1/performance?days=30": {
        days: 30,
        funnel: { calls: 51, connected: 39, qualified: 14 },
        connect_rate_pct: 76,
        qualify_rate_pct: 36,
        inbound: 30,
        outbound: 21,
        avg_duration_s: 154,
        outcomes: { appointment_booked: 14, no_answer: 8, enquiry: 29 },
        busiest_hours_ist: [
          0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 5, 3, 1, 0, 0, 4, 6, 9, 12, 7, 2, 0, 0,
          0,
        ],
      },
    },
  },
  {
    // NOT opted in, and the channel NOT deliverable — the state with the most markup on
    // it: the notice text, the grant control, and the "we cannot send yet" refusal that
    // an opted-in account never renders.
    file: "c/[slug]/settings/alerts/page.tsx",
    realm: "client",
    element: () => <AlertsPage />,
    routes: {
      "/v1/me": ME,
      "/v1/compliance/whatsapp-alerts": {
        status: "none",
        channel: null,
        captured_at: null,
        notice_version: null,
        messageable: false,
        current_notice_version: "whatsapp-alerts-v1",
        current_notice_text:
          "I agree that Calevate may send WhatsApp messages to this number to alert me about activity in my own account, such as a hot lead. I can withdraw this at any time from this screen.",
        delivery_available: false,
        delivery_unavailable_reason: "no_credential",
      },
    },
  },
  {
    // The state with the most markup on it: an account still on the platform default, so
    // the "in force now" box, the inherit row AND every priced option are on screen at
    // once — including the comparison sentences, which only render beside a baseline.
    file: "c/[slug]/settings/models/page.tsx",
    realm: "client",
    element: () => <ClientLlmModelPage params={slug} />,
    routes: {
      "/v1/me": ME,
      "/v1/organization/llm-defaults": {
        default_llm_model: null,
        effective_default: "gpt-4o-mini",
        available: [
          {
            model: "gpt-4o-mini",
            provider: "Azure OpenAI",
            platform_cost_inr_per_minute: "0.2400",
            client_surcharge_inr_per_minute: "0",
            is_platform_default: true,
          },
          {
            model: "gpt-4.1-mini",
            provider: "Azure OpenAI",
            platform_cost_inr_per_minute: "0.4830",
            client_surcharge_inr_per_minute: "1.5000",
            is_platform_default: false,
          },
        ],
      },
    },
  },
  {
    file: "c/[slug]/settings/team/page.tsx",
    realm: "client",
    element: () => <TeamPage />,
    routes: {
      "/v1/me": ME,
      "/v1/members": MEMBERS,
      "/v1/invitations": [
        {
          id: "inv-1",
          email: "kiran@example.com",
          role: "staff",
          created_at: "2026-08-12T09:00:00Z",
          expires_at: "2026-08-19T09:00:00Z",
        },
      ],
    },
  },
  {
    file: "c/[slug]/usage/page.tsx",
    realm: "client",
    element: () => <UsagePage />,
    routes: {
      "/v1/me": ME,
      "/v1/usage": USAGE,
      "/v1/billing/caps": {
        cap_minutes: null,
        cap_inr: null,
        notify_at_pct: 80,
        capped: false,
        updated_at: null,
      },
    },
  },
  {
    // Calling credit. Swept in the state that renders the MOST and is the most dangerous
    // to get wrong: STOPPED (the alert banner), with an unfinished payment above the
    // top-up controls, a full drawdown and a ledger row carrying a receipt button. The
    // receipt DIALOG is not in this sweep — opening it needs a click and this sweep
    // renders rather than drives — so `credits.test.tsx` sweeps it there.
    file: "c/[slug]/credits/page.tsx",
    realm: "client",
    element: () => <CreditsPage />,
    routes: {
      "/v1/me": ME,
      "/v1/billing/wallet": WALLET_STOPPED,
      "/v1/billing/wallet/ledger?limit=50": WALLET_LEDGER,
      "/v1/billing/wallet/topups": WALLET_ATTEMPTS,
      "/v1/billing/topups/capability": {
        online_payments_available: true,
        provider_orders_available: true,
      },
      "/v1/billing/topups/packs": CREDIT_PACKS,
    },
  },
  {
    // Swept AT THE CEILING, which is the state that renders the most: the warning
    // notice, the offer and the button that opens the money dialog. `within` would
    // render three tiles and nothing axe has an opinion about. The DIALOG itself is
    // swept in `aiQuota.test.tsx`, because opening it needs a click and this sweep
    // renders rather than drives.
    file: "c/[slug]/ai-assist/page.tsx",
    realm: "client",
    element: () => <AiAssistPage />,
    routes: { "/v1/me": ME, "/v1/billing/ai-quota": AI_QUOTA_AT_CEILING },
  },
  {
    // Per-rupee attribution, the client's half. Swept with a NON-ZERO residual so the
    // explanation panel is in the scan — it is the one block on this screen that renders
    // conditionally on something the server says rather than on a request landing.
    file: "c/[slug]/spend/page.tsx",
    realm: "client",
    element: () => <ClientSpendPage params={slug} />,
    routes: { "/v1/me": ME, [`/v1/billing/spend?month=${IST_MONTH}`]: SPEND },
  },
  {
    // The client's own invoice — the same sheet the admin entry below renders, from the
    // same fixture, because it is the same document (SLICE AL).
    file: "c/[slug]/invoice/page.tsx",
    realm: "client",
    element: () => <ClientInvoicePage />,
    routes: {
      "/v1/me": ME,
      [`/v1/billing/invoice?month=${IST_MONTH}`]: INVOICE,
    },
  },
  {
    // Agreements & readiness. Fixtured in the state with the MOST markup and the most to
    // get wrong: nothing accepted, so the verdict box, the draft notice, four document
    // cards, the acceptance checkbox with its statement, the submit button and a blocker
    // row are all on screen at once. The accepted state renders a strict subset.
    file: "c/[slug]/agreements/page.tsx",
    realm: "client",
    element: () => <AgreementsPage />,
    routes: { "/v1/me": ME, "/v1/legal/readiness": LEGAL_READINESS },
  },
  {
    file: "c/[slug]/verification/page.tsx",
    realm: "client",
    element: () => <VerificationPage />,
    routes: {
      "/v1/me": ME,
      "/v1/usage": USAGE,
      "/v1/compliance/kyc": KYC_RECORD,
      // The DLT half of the screen. Populated and NOT active, so both status rows and the
      // "what is on file" list render — the state with the most markup in it.
      "/v1/compliance/dlt-registration": {
        recorded: true,
        status: "submitted",
        tm_link_status: "pending",
        pe_id: "1101234567890123456",
        entity_name: "Sri Clinic Pvt Ltd",
        registered_at: "2026-07-01T04:00:00Z",
        verified_at: "2026-08-01T04:00:00Z",
        is_active: false,
      },
    },
  },
  {
    file: "invite/page.tsx",
    realm: "client",
    element: () => <InvitePage />,
    routes: { "/v1/me": ME },
  },
  {
    // The junction that turns "I have a session" into "this is my console". It renders a
    // skeleton while `/v1/me` answers and a refusal if it cannot, so both of its states
    // are scannable — and the skeleton is the one that matters here, because a junction
    // that announced nothing would leave a screen-reader user on a silent page while the
    // redirect was decided.
    file: "c/page.tsx",
    realm: "client",
    element: () => <ClientConsoleJunction />,
    routes: { "/v1/me": ME },
  },
  {
    file: "signup/page.tsx",
    realm: "client",
    element: () => <SignupPage />,
    routes: { "/v1/me": ME },
  },
  {
    file: "page.tsx",
    realm: "client",
    element: () => <Home />,
    routes: {},
  },
  // The public legal pages. Swept here so the coverage guard below sees them, and swept
  // AGAIN — over all eight documents rather than this one representative — in
  // tests/legal.test.tsx, because the documents differ in content and only one of them
  // has a five-column table.
  {
    file: "legal/page.tsx",
    realm: "client",
    element: () => <LegalIndexPage />,
    routes: {},
  },
  {
    file: "legal/[slug]/page.tsx",
    realm: "client",
    element: () => (
      <LegalDocumentRoute params={Promise.resolve({ slug: "privacy" })} />
    ),
    routes: {},
  },
];

const ADMIN_SCREENS: Screen[] = [
  {
    file: "admin/layout.tsx",
    realm: "admin",
    element: () => (
      <AdminLayout>
        <p>console body</p>
      </AdminLayout>
    ),
    routes: {
      "/v1/admin/me": ADMIN_ME,
      "/v1/admin/compliance/holds": [HELD_TENANT],
    },
  },
  {
    file: "admin/page.tsx",
    realm: "admin",
    element: () => <AdminClientsPage />,
    routes: { "/v1/admin/me": ADMIN_ME, "/v1/admin/tenants": [TENANT_SUMMARY] },
  },
  {
    file: "admin/health/page.tsx",
    realm: "admin",
    element: () => <ClientHealthPage />,
    routes: {
      "/v1/admin/client-health": [
        {
          tenant_id: "t1",
          name: "Sri Traders",
          slug: "sri-traders",
          plan_tier: "managed",
          status: "active",
          severity: "stop",
          signals: [
            {
              rule: "deliveries_failing",
              severity: "stop",
              causes: [],
              count: 3,
            },
          ],
          calls_7d: 2,
          calls_prev_7d: 40,
          calls_basis: "measured",
          last_call_at: "2026-08-10T06:30:00Z",
          spend_used_inr: "900.5000",
          spend_cap_inr: "1000.0000",
        },
      ],
    },
  },
  {
    file: "admin/holds/page.tsx",
    realm: "admin",
    element: () => <HeldAccountsPage />,
    routes: { "/v1/admin/compliance/holds": [HELD_TENANT] },
  },
  {
    file: "admin/qa-sampling/page.tsx",
    realm: "admin",
    element: () => <QaSamplingPage />,
    routes: { "/v1/admin/qa-samples?pending=true": [QA_SAMPLE] },
  },
  {
    file: "admin/qa-sampling/[sampleId]/page.tsx",
    realm: "admin",
    element: () => (
      <QaSampleReviewPage params={Promise.resolve({ sampleId: "s1" })} />
    ),
    routes: {
      "/v1/admin/qa-samples/s1": {
        sample: QA_SAMPLE,
        call: {
          ...CALL,
          summary: "Caller booked a Tuesday slot.",
          transcript: [
            {
              idx: 0,
              speaker: "agent",
              text: "Namaskaram, Sri Clinic.",
              lang: "te-IN",
              start_ms: 0,
              redacted: true,
            },
            {
              idx: 1,
              speaker: "caller",
              text: "Call me on [phone ••10].",
              lang: "te-IN",
              start_ms: 2400,
              redacted: true,
            },
          ],
          extraction: {},
          extraction_valid: true,
          has_recording: false,
          disclosure_played: true,
        },
      },
    },
  },
  {
    file: "admin/new/page.tsx",
    realm: "admin",
    element: () => <NewClientPage />,
    routes: { "/v1/admin/onboarding/unfinished": [] },
  },
  {
    // THREE FIXTURE ROUTES SHORTER THAN IT WAS: the config, credential and key panels
    // moved to `/admin/ops/config` (the founder's correction to D-457), so this screen
    // reads the platform row and nothing else.
    file: "admin/ops/page.tsx",
    realm: "admin",
    element: () => <OpsPage />,
    routes: {
      "/v1/admin/me": ADMIN_ME,
      "/v1/ops/platform": PLATFORM,
    },
  },
  {
    // Swept in the ALLOWED costume, which is the opposite choice from `ADMIN_ME` above
    // and is deliberate: the shared fixture holds no real permission at all, so it would
    // render three refusal notices — three `NoticeBox`es inside `Card`s, markup this
    // sweep already covers on a dozen screens — and leave the config form, the credential
    // table and the key-management panel, which is every interactive control on the
    // surface, unscanned. The refused costume is covered by `ops.test.tsx`'s own
    // withheld-panel assertions.
    file: "admin/ops/config/page.tsx",
    realm: "admin",
    element: () => <OpsConfigPage />,
    routes: {
      "/v1/admin/me": {
        ...ADMIN_ME,
        permissions: [...ADMIN_ME.permissions, "platform:config", "platform:secrets"],
      },
      "/v1/ops/config": OPS_CONFIG,
      "/v1/ops/model-prices": OPS_MODEL_PRICES,
      "/v1/ops/dashboard-data-use": OPS_DASHBOARD_DATA_USE,
      "/v1/ops/secrets": OPS_SECRETS,
      "/v1/ops/secrets/kek": OPS_KEK,
    },
  },
  {
    // Populated with TWO entries whose `source` differs, because the row renders the
    // source in the operator's words and the release confirmation quotes it back — a
    // one-source fixture would leave half of both strings unscanned.
    file: "admin/ops/dnc/page.tsx",
    realm: "admin",
    element: () => <GlobalDncPage />,
    routes: {
      "/v1/admin/me": ADMIN_ME,
      "/v1/ops/dnc/global?limit=500": [
        {
          id: "0192f0aa-7777-7000-8000-000000000001",
          phone_e164: "+919876543210",
          scope: "global",
          source: "regulator",
          added_at: "2026-08-12T09:00:00Z",
          removable: false,
        },
        {
          id: "0192f0aa-7777-7000-8000-000000000002",
          phone_e164: "+919812347788",
          scope: "global",
          source: "platform_block",
          added_at: "2026-08-11T09:00:00Z",
          removable: false,
        },
      ],
    },
  },
  {
    // TWO groups, EVERY LEG of each, and one group whose every leg is
    // `insufficient_samples` with no percentiles and no verdict: the withheld-figure
    // rendering is a different piece of markup from the measured one, and a fixture with
    // only measured rows would leave the state this endpoint exists to report honestly —
    // "not enough turns to say" — unscanned. The measured group deliberately splits its
    // verdicts (the model leg over target, the transcriber leg within it, the composed
    // reply over) so both paintings of the verdict cell are swept.
    file: "admin/ops/engine-latency/page.tsx",
    realm: "admin",
    element: () => <EngineLatencyPage />,
    routes: {
      // `ops:manage`, unlike the shared ADMIN_ME the two ops screens above use: this
      // screen WITHHOLDS its whole report from a session the server has refused, so the
      // shared fixture would sweep one sentence and none of the markup this entry exists
      // for. The refused costume is covered by its own test in opsEngineLatency.test.tsx.
      "/v1/admin/me": {
        ...ADMIN_ME,
        permissions: [...ADMIN_ME.permissions, "ops:manage"],
      },
      "/v1/ops/engine-latency?days=7": {
        window_days: 7,
        // The whole budget, as TRD §4 declares it and as the server sends it: five stages,
        // the crossing to the engine's US servers, what the shipped config actually waits,
        // two voice-to-voice targets, and the composed figures the server derives so no
        // browser has to — `composes` among them, false since the 500ms target.
        budget: {
          endpointing_ms: 100,
          stt_ms: 70,
          llm_ttft_ms: 150,
          tts_ttfa_ms: 80,
          retrieval_ms: 100,
          india_us_transit_floor_ms: 100,
          inherited_turn_detection_ms: 650,
          voice_to_voice_p50_ms: 500,
          voice_to_voice_p95_ms: 800,
          turn_ms: 300,
          pipeline_ms: 500,
          voice_to_voice_floor_ms: 600,
          voice_to_voice_headroom_p50_ms: -100,
          composes: false,
        },
        complete: false,
        groups: [
          {
            engine: "bolna",
            region: "us",
            calls: 12,
            turns: 240,
            legs: [
              {
                leg: "stt",
                budget_ms: 300,
                turns: 240,
                basis: "measured",
                p50_ms: 260,
                p95_ms: 401.5,
                max_ms: 612.3,
                turns_over_budget: 22,
                budget_breached: false,
                // The transcriber leg's unit is unconfirmed, so this fixture also sweeps
                // the caveat markup that renders only on such a row.
                unit_verified: false,
              },
              {
                leg: "llm_ttft",
                budget_ms: 350,
                turns: 240,
                basis: "measured",
                p50_ms: 412.5,
                p95_ms: 980.2,
                max_ms: 1633.04,
                turns_over_budget: 190,
                budget_breached: true,
                unit_verified: true,
              },
              {
                leg: "tts_ttfa",
                budget_ms: 300,
                turns: 238,
                basis: "measured",
                p50_ms: 288.1,
                p95_ms: 455,
                max_ms: 800,
                turns_over_budget: 61,
                budget_breached: false,
                unit_verified: true,
              },
              {
                leg: "turn",
                budget_ms: 950,
                turns: 238,
                basis: "measured",
                p50_ms: 981.4,
                p95_ms: 1720,
                max_ms: 2412,
                turns_over_budget: 130,
                budget_breached: true,
                unit_verified: false,
              },
            ],
          },
          {
            engine: "bolna",
            region: null,
            calls: 1,
            turns: 3,
            legs: [
              {
                leg: "stt",
                budget_ms: 300,
                turns: 0,
                basis: "insufficient_samples",
                turns_over_budget: 0,
                unit_verified: false,
              },
              {
                leg: "llm_ttft",
                budget_ms: 350,
                turns: 3,
                basis: "insufficient_samples",
                max_ms: 288.1,
                turns_over_budget: 0,
                unit_verified: true,
              },
              {
                leg: "tts_ttfa",
                budget_ms: 300,
                turns: 0,
                basis: "insufficient_samples",
                turns_over_budget: 0,
                unit_verified: true,
              },
              {
                leg: "turn",
                budget_ms: 950,
                turns: 0,
                basis: "insufficient_samples",
                turns_over_budget: 0,
                unit_verified: false,
              },
            ],
          },
        ],
      },
    },
  },
  {
    // TWO accounts, and the fixture's shape is the point of the entry. One is the SIGNED-IN
    // super admin, whose row renders the lockout sentence where its controls would be, and
    // one is a normal admin who has never followed their setup link — so the tier badge,
    // the "setup link outstanding" pill, the three row buttons and the self-refusal are all
    // in the tree at once. A one-row fixture would sweep the list and none of them.
    file: "admin/operators/page.tsx",
    realm: "admin",
    element: () => <OperatorsPage />,
    routes: {
      // `admin:operators`, not the shared ADMIN_ME: every route this screen calls carries
      // it, and without it the screen WITHHOLDS itself — the sweep would scan one refusal
      // panel and none of the markup this entry exists for. The refused costume has its
      // own test in adminOperators.test.tsx.
      "/v1/admin/me": {
        ...ADMIN_ME,
        user_id: "0192f0aa-7777-7000-8000-0000000000a1",
        permissions: [...ADMIN_ME.permissions, "admin:operators"],
      },
      "/v1/admin/operators": {
        operators: [
          {
            id: "0192f0aa-7777-7000-8000-0000000000a1",
            email: "founder@calevate.tech",
            name: "Sri J",
            role: "superadmin",
            created_at: "2026-07-01T04:30:00Z",
            activated: true,
          },
          {
            id: "0192f0aa-7777-7000-8000-0000000000a2",
            email: "asha@calevate.tech",
            name: "Asha Rao",
            role: "operator",
            created_at: "2026-08-14T09:15:00Z",
            activated: false,
          },
        ],
      },
    },
  },
  {
    file: "admin/tenants/[tenantId]/page.tsx",
    realm: "admin",
    element: () => <TenantDetailPage params={tenant} />,
    routes: TENANT_ROUTES,
  },
  {
    // Populated with a priced agreement AND a history row: the form, the "in effect"
    // definition list and the history table are three different pieces of markup, and
    // an unpriced fixture would scan none of them.
    file: "admin/tenants/[tenantId]/commercials/page.tsx",
    realm: "admin",
    element: () => <CommercialsPage params={tenant} />,
    routes: {
      ...TENANT_ROUTES,
      "/v1/admin/tenants/t1/commercial-terms": {
        tenant_id: "t1",
        state: "set",
        in_effect: PLAN_ROW,
        history: [PLAN_ROW],
        loosening_confirmation: "raise_spend_ceiling:t1",
      },
    },
  },
  {
    // A wallet that is LOW and has both a credit and a debit on it: the low-balance
    // notice, both movement signs and the ledger table are four separate pieces of
    // markup, and a fresh, empty, healthy wallet would scan none of them. All three
    // forms' inputs render on every branch of a successful read, and one entry is left
    // FULLY corrected so the correction panel's select renders with an option missing
    // rather than with everything on the ledger. `payments` is the SAME wallet grouped
    // by bank transfer (D-89) and is what the restatement panel and the payments table
    // render from — a page-level fixture without it renders neither.
    file: "admin/tenants/[tenantId]/credits/page.tsx",
    realm: "admin",
    element: () => <TenantCreditsPage params={tenant} />,
    routes: {
      ...TENANT_ROUTES,
      "/v1/admin/tenants/t1/credits?limit=50": {
        tenant_id: "t1",
        balance_inr: "150.00",
        is_low: true,
        low_balance_threshold_inr: "200.00",
        entries: [
          {
            id: "0192f0aa-5555-7000-8000-000000000002",
            delta_inr: "-2350.00",
            reason: "usage",
            ref: "0192f0aa-5555-7000-8000-0000000000c9",
            balance_after_inr: "150.00",
            occurred_at: "2026-08-13T05:30:00Z",
            reversible_inr: "0.00",
          },
          {
            id: "0192f0aa-5555-7000-8000-000000000001",
            delta_inr: "2500.00",
            reason: "topup",
            ref: "UTR-902311",
            balance_after_inr: "2500.00",
            occurred_at: "2026-08-12T05:30:00Z",
            reversible_inr: "2500.00",
          },
        ],
        payments: [
          {
            payment_ref: "UTR-902311",
            credited_inr: "2500.00",
            entries: 1,
            first_at: "2026-08-12T05:30:00Z",
          },
        ],
      },
    },
  },
  {
    file: "admin/tenants/[tenantId]/lifecycle/page.tsx",
    realm: "admin",
    element: () => <LifecyclePage params={tenant} />,
    routes: TENANT_ROUTES,
  },
  {
    file: "admin/tenants/[tenantId]/kyc/page.tsx",
    realm: "admin",
    element: () => <TenantKycPage params={tenant} />,
    routes: TENANT_ROUTES,
  },
  {
    file: "admin/tenants/[tenantId]/invoice/page.tsx",
    realm: "admin",
    element: () => <TenantInvoicePage params={tenant} />,
    routes: { [`/v1/admin/tenants/t1/invoice?month=${IST_MONTH}`]: INVOICE },
  },
  {
    file: "admin/tenants/[tenantId]/spend/page.tsx",
    realm: "admin",
    element: () => <TenantSpendPage params={tenant} />,
    routes: { [`/v1/admin/tenants/t1/spend?month=${IST_MONTH}`]: TENANT_SPEND },
  },
  {
    // Swept with a client in the RED, because the losing row carries markup the healthy
    // one does not — the warning glyph and its screen-reader-only prefix.
    file: "admin/spend/page.tsx",
    realm: "admin",
    element: () => <FleetSpendPage />,
    routes: { [`/v1/admin/spend?month=${IST_MONTH}`]: FLEET_SPEND },
  },
  {
    file: "admin/tenants/[tenantId]/first-campaign-review/page.tsx",
    realm: "admin",
    element: () => <FirstCampaignReviewPage params={tenant} />,
    routes: {
      ...TENANT_ROUTES,
      "/v1/compliance/first-campaign-review": {
        required: true,
        status: "pending",
        submitted_at: "2026-08-12T09:00:00Z",
        decided_at: null,
        reviewer_note: null,
        campaign_id: "camp-1",
        campaign_name: "Diwali offer",
      },
    },
  },
  {
    // TWO flags on purpose: one declared-and-overridden (so the "why / set" rows, the
    // radio group and the reason field all render) and one stored-but-no-longer-declared
    // (the leftover notice). A single-flag fixture would leave half this screen's markup
    // — including a whole notice box — unscanned.
    file: "admin/tenants/[tenantId]/feature-flags/page.tsx",
    realm: "admin",
    element: () => <FeatureFlagsPage params={tenant} />,
    routes: {
      ...TENANT_ROUTES,
      "/v1/admin/tenants/t1/feature-flags": FEATURE_FLAGS,
    },
  },
  {
    // A client with a default OF THEIR OWN, on purpose: it is the state that renders the
    // "from this client's own choice" resolution, the price comparison against the
    // platform default, and a live confirmation label. A client on the inherited default
    // would leave all three unscanned.
    file: "admin/tenants/[tenantId]/llm-model/page.tsx",
    realm: "admin",
    element: () => <LlmModelPage params={tenant} />,
    routes: {
      ...TENANT_ROUTES,
      "/v1/admin/organizations/t1/llm-defaults": LLM_DEFAULTS,
    },
  },
  {
    file: "admin/tenants/[tenantId]/agents/[agentId]/prompt/page.tsx",
    realm: "admin",
    element: () => (
      <AgentPromptPage
        params={Promise.resolve({ tenantId: "t1", agentId: "agent-1" })}
      />
    ),
    routes: {
      "/v1/admin/me": ADMIN_ME,
      "/v1/admin/tenants/t1": TENANT_SUMMARY,
      "/v1/admin/tenants/t1/agents/agent-1/prompt": [
        {
          id: "v2",
          version: 2,
          notes: "challenger",
          created_at: "2026-08-01T04:00:00Z",
          active: true,
        },
        {
          id: "v1",
          version: 1,
          notes: "control",
          created_at: "2026-07-01T04:00:00Z",
          active: false,
        },
      ],
      // The voice catalogue, read through the tenant's impersonation session like the
      // other two client-realm GETs on this screen.
      "/v1/agents/voices": [
        {
          id: "anushka",
          label: "Anushka",
          provider: "sarvam",
          tts_model: "bulbul:v3",
          gender: "female",
          languages: ["te-IN", "hi-IN", "en-IN"],
          note: "Warm, unhurried; the default for Telugu receptionists.",
          is_default: true,
          verified: false,
        },
      ],
      "/v1/agents/agent-1/pending": {
        agent_id: "agent-1",
        agent_status: "live",
        published: true,
        has_pending: false,
        pending: [],
        effective_call_cap_s: 600,
        call_cap_is_platform_default: true,
        worst_case_call_cost_inr: null,
        precedence_rule: "Script decides content.",
        // Configured and live DIFFER on purpose, so the sweep covers the state with the
        // most markup in it — the two-value block plus the amber republish line. The
        // agreeing state renders a strict subset of it.
        voice: {
          configured: {
            voice_id: "anushka",
            provider: "sarvam",
            catalog: null,
          },
          live: { voice_id: "vidya", provider: "sarvam", catalog: null },
          republish_required: true,
          headline:
            "Callers still hear vidya; anushka reaches them at the next publish.",
        },
        // Unconfirmed for the same reason the voice is diverged: the sweep should walk
        // the branch that renders MORE, not the reassuring one.
        engine_verification: {
          state: "unreadable",
          confirmed: false,
          verified_at: null,
          headline:
            "The voice platform accepted this publish; it did not report back enough for us to confirm it is running it. Publish again to re-check.",
        },
      },
      "/v1/agents/lanes": {
        precedence_rule: "Script decides content.",
        lanes: [],
        call_cap_default_s: 600,
        call_cap_min_s: 60,
        call_cap_max_s: 3600,
      },
      "/v1/agents/agent-1/experiment": {
        agent_id: "agent-1",
        rules: {
          metrics: [
            { key: "call_outcome_resolved", label: "calls the agent resolved" },
          ],
          default_metric: "call_outcome_resolved",
          minimum_calls_per_variant: 40,
          split_min_bp: 500,
          split_total_bp: 10000,
          peeking_caveat: "The 95% confidence is per reading.",
        },
        experiment: null,
      },
    },
  },
];

/**
 * The first-party authentication surface (D-174) — ten screens, both realms.
 *
 * A third list rather than entries in the two above, because these screens belong to
 * NEITHER realm's shell. They bring their own `<Providers>`, they render outside
 * `ClientRealmProvider` (an auth page holds no org slug — it does not yet know who is
 * asking), and the admin ones are not inside `app/admin/layout.tsx`. `realm: "admin"`
 * below is therefore a statement about the HARNESS — `renderAdminRoute` is the one that
 * adds no realm provider — and not about which realm the screen serves; the client-realm
 * pages here are marked the same way for the same reason.
 *
 * `KNOWN_A11Y_EXEMPTIONS` is pinned empty and none of these is in `UNSWEPT_SCREENS`:
 * these get swept, not excused.
 */
const AUTHN_SCREENS: Screen[] = [
  {
    file: "(auth)/auth/sign-in/page.tsx",
    realm: "admin",
    element: () => <ClientFirstPartySignInPage />,
    // The guest audience's restore. A signed-OUT answer is the state this page is for:
    // a session found here would bounce the visitor to the account page and the sweep
    // would scan a redirect instead of a form.
    routes: { "GET /v1/auth/client/session": UNAUTHORIZED_SESSION },
  },
  {
    file: "(auth)/auth/admin/sign-in/page.tsx",
    realm: "admin",
    element: () => <AdminFirstPartySignInPage />,
    routes: { "GET /v1/auth/admin/session": UNAUTHORIZED_SESSION },
  },
  {
    file: "(auth)/auth/forgot-password/page.tsx",
    realm: "admin",
    element: () => <ClientForgotPasswordPage />,
    routes: {},
  },
  {
    file: "(auth)/auth/admin/forgot-password/page.tsx",
    realm: "admin",
    element: () => <AdminForgotPasswordPage />,
    routes: {},
  },
  {
    // Scanned WITH a token in the URL, so what axe sees is the password form rather than
    // the "this link is missing its code" branch. `useLinkToken` reads `location` in an
    // effect, so setting it before the render is what the browser hands the page.
    file: "(auth)/auth/reset-password/page.tsx",
    realm: "admin",
    element: () =>
      withLinkToken("/auth/reset-password", <ClientResetPasswordPage />),
    routes: {},
  },
  {
    file: "(auth)/auth/admin/reset-password/page.tsx",
    realm: "admin",
    element: () =>
      withLinkToken("/auth/admin/reset-password", <AdminResetPasswordPage />),
    routes: {},
  },
  {
    file: "(auth)/auth/admin/bootstrap/page.tsx",
    realm: "admin",
    element: () =>
      withLinkToken("/auth/admin/bootstrap", <AdminBootstrapPage />),
    routes: {},
  },
  {
    file: "(auth)/auth/accept-invitation/page.tsx",
    realm: "admin",
    element: () =>
      withLinkToken("/auth/accept-invitation", <AcceptInvitationPage />),
    routes: {},
  },
  {
    // The two session-management screens are scanned SIGNED IN — the gate is fail-closed,
    // so a refused session renders `SessionGate` and the sweep would never reach the
    // panels, the modal or the sign-out controls that are the reason these pages exist.
    file: "(auth)/auth/admin/page.tsx",
    realm: "admin",
    element: () => <AdminSessionPage />,
    routes: { "GET /v1/auth/admin/session": ADMIN_SESSION_ROW },
  },
  {
    file: "(auth)/auth/account/page.tsx",
    realm: "admin",
    element: () => <ClientAccountPage />,
    routes: { "GET /v1/auth/client/session": CLIENT_SESSION_ROW },
  },
];

export const SCREENS: Screen[] = [
  ...CLIENT_SCREENS,
  ...ADMIN_SCREENS,
  ...AUTHN_SCREENS,
];

describe("every screen is scanned by axe", () => {
  it.each(SCREENS.map((s) => [s.file, s] as const))(
    "%s",
    async (_file, screen) => {
      const { container } =
        screen.realm === "client"
          ? await renderClientPage(screen.element(), screen.routes)
          : // `renderAdminRoute`, not `renderAdminPage`: several admin screens read
            // `use(params)` and therefore SUSPEND on first paint, which a bare synchronous
            // render leaves as an empty container.
            await renderAdminRoute(screen.element(), screen.routes);
      // Let every TanStack query resolve before scanning. Neither `renderClientPage` (which
      // only awaits the Suspense boundary) nor `renderAdminPage` (synchronous by design)
      // waits for the network, so without this the scan sees SKELETONS — which is the
      // vacuous pass `assertScreenRendered` refuses. A macrotask is enough: `stubApi`
      // answers from memory, so the only thing outstanding is React's own flush.
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      await expectNoA11yViolations(container, screen.file);
    },
  );
});

describe("the gate cannot quietly fall behind", () => {
  /**
   * The guard that makes the sweep a RULE rather than a list somebody once wrote.
   *
   * Without it, the sweep is only ever as complete as the last person's memory, and a
   * new screen ships unscanned while this file still reports green — the "guardrail that
   * looks like progress" CLAUDE.md warns about.
   */
  it("covers every screen the router serves", () => {
    const swept = new Set(SCREENS.map((s) => s.file));
    const missing = routePagesOnDisk().filter(
      (p) => !swept.has(p) && !Object.hasOwn(UNSWEPT_SCREENS, p),
    );
    expect(
      missing,
      `these route screens are not scanned for accessibility:\n  ${missing.join("\n  ")}\n` +
        `Add each to SCREENS in tests/a11y.test.tsx, or to UNSWEPT_SCREENS in tests/a11y.ts ` +
        `with a reason and what closes it.`,
    ).toEqual([]);
  });

  it("names no screen that no longer exists", () => {
    const onDisk = new Set(routePagesOnDisk());
    const ghosts = Object.keys(UNSWEPT_SCREENS).filter((p) => !onDisk.has(p));
    expect(
      ghosts,
      `UNSWEPT_SCREENS names screens that are gone: ${ghosts.join(", ")}`,
    ).toEqual([]);
  });

  /**
   * A waiver that has stopped firing is either fixed or pointing at deleted markup, and
   * either way leaving it teaches the next reader that the table is decorative. Same
   * role as `check_coverage_ratchet.stale_waivers`.
   */
  it("holds no exemption that has stopped applying", () => {
    const stale = staleExemptions();
    expect(
      stale,
      `KNOWN_A11Y_EXEMPTIONS entries that no longer match any violation — the markup was ` +
        `fixed or removed, so delete them: ${stale.join(", ")}`,
    ).toEqual([]);
  });

  /**
   * Raising the exemption count must cost a visible diff in a TEST as well as in the
   * table, so it is reviewed on its merits. The pin `check_coverage_ratchet`'s
   * `RAISED_BUDGETS` and `check_redaction_exposure`'s `KNOWN_SAFE_FIELDS` both carry.
   */
  it("pins the exemption set", () => {
    expect(Object.keys(KNOWN_A11Y_EXEMPTIONS).sort()).toEqual([]);
  });
});
