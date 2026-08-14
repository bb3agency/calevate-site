import { act } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AdminSignInPage from "@/app/(auth)/admin/sign-in/[[...sign-in]]/page";
import AdminLayout from "@/app/admin/layout";
import ClientSignInPage from "@/app/(auth)/sign-in/[[...sign-in]]/page";
import ClientSignUpPage from "@/app/(auth)/sign-up/[[...sign-up]]/page";
import ClientHealthPage from "@/app/admin/health/page";
import HeldAccountsPage from "@/app/admin/holds/page";
import NewClientPage from "@/app/admin/new/page";
import OpsPage from "@/app/admin/ops/page";
import AdminClientsPage from "@/app/admin/page";
import AgentPromptPage from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page";
import FirstCampaignReviewPage from "@/app/admin/tenants/[tenantId]/first-campaign-review/page";
import TenantInvoicePage from "@/app/admin/tenants/[tenantId]/invoice/page";
import TenantKycPage from "@/app/admin/tenants/[tenantId]/kyc/page";
import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import AgentsPage from "@/app/c/[slug]/agents/page";
import AttentionPage from "@/app/c/[slug]/attention/page";
import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
import CallsPage from "@/app/c/[slug]/calls/page";
import CampaignReviewPage from "@/app/c/[slug]/campaign-review/page";
import CampaignsPage from "@/app/c/[slug]/campaigns/page";
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
import TeamPage from "@/app/c/[slug]/settings/team/page";
import UsagePage from "@/app/c/[slug]/usage/page";
import VerificationPage from "@/app/c/[slug]/verification/page";
import InvitePage from "@/app/invite/page";
import Home from "@/app/page";
import SignupPage from "@/app/signup/page";

import {
  KNOWN_A11Y_EXEMPTIONS,
  UNSWEPT_SCREENS,
  expectNoA11yViolations,
  routePagesOnDisk,
  staleExemptions,
} from "./a11y";
import { renderAdminRoute } from "./adminRoute";
import { renderClientPage, type Routes } from "./harness";

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

const ORG = { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" };

/** An owner: the role that can see the most, and therefore renders the most markup. */
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

/** The invoice screen asks for the CURRENT IST month, so the fixture key must follow it. */
const IST_MONTH = new Date()
  .toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })
  .slice(0, 7);

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
  direction: "inbound",
  status: "completed",
  caller_masked: "+9198765•••10",
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
  disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  extraction_fields: [{ key: "name", label: "Name", type: "string", required: true }],
};

const LEAD = {
  id: "lead-a",
  name: "Ramesh Kumar",
  phone_masked: "+9198••••3210",
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

const MEMBERS = [
  { id: "u1", name: "Priya Nair", role: "owner" },
  { id: "u2", name: "Kiran Babu", role: "staff" },
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
  monthly_fee_inr: "4999.00",
  cap_minutes: null,
  minutes_left: null,
  capped: false,
  spend_used_inr: "4999.00",
  plan_tier: "managed",
  credit_balance_inr: null,
};

const DASHBOARD = {
  calls_today: 3,
  calls_7d: 24,
  leads_new_7d: 9,
  hot_leads_open: 2,
  avg_duration_s: 118,
  sentiment_split: { positive: 12, neutral: 8, negative: 4 },
  outcome_split: { appointment_booked: 9, enquiry: 15 },
  after_hours_captured_7d: 4,
  after_hours_basis: "default_window",
  minutes_used_month: "120.5",
  daily_7d: [
    { ist_date: "2026-08-07", total: 4, completed: 3, no_answer: 1, failed: 0, in_flight: 0 },
    { ist_date: "2026-08-08", total: 6, completed: 4, no_answer: 1, failed: 1, in_flight: 0 },
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
    by_job: [{ job: "deliver_outbound_webhook", depth: 6, oldest_at: "2026-08-04T04:15:00Z" }],
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
  },
  "/v1/kb/sources?status=pending_approval": [],
  "/v1/kb/sources?status=approved": [],
  "/v1/agents": [AGENT],
  "/v1/campaigns/numbers": [],
  "/v1/campaigns/templates": [],
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
      "/v1/calls?limit=6": [CALL],
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
    element: () => <CallDetailPage params={Promise.resolve({ slug: "acme", callId: "c1" })} />,
    routes: {
      "/v1/me": ME,
      "/v1/calls/c1": {
        ...CALL,
        turns: [
          { idx: 0, role: "agent", text_redacted: "Namaskaram, Sri Clinic.", at_ms: 0, redacted: true },
          { idx: 1, role: "caller", text_redacted: "I need a Tuesday slot.", at_ms: 2400, redacted: true },
        ],
        recording_available: false,
        extraction: { name: "Ramesh Kumar" },
      },
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
      "/v1/leads?limit=100": {
        items: [LEAD],
        columns: [{ key: "name", label: "Name" }],
        total: 1,
        limit: 100,
        offset: 0,
        status_counts_matching_search: { new: 1, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
      },
    },
  },
  {
    file: "c/[slug]/leads/[leadId]/page.tsx",
    realm: "client",
    element: () => <LeadDetailPage params={Promise.resolve({ slug: "acme", leadId: "lead-a" })} />,
    routes: {
      "/v1/me": ME,
      "/v1/members": MEMBERS,
      "/v1/leads/lead-a": { ...LEAD, columns: [{ key: "name", label: "Name" }] },
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
      "/v1/agents/lanes": {
        precedence_rule: "Script decides content.",
        lanes: [],
        call_cap_default_s: 600,
        call_cap_min_s: 60,
        call_cap_max_s: 3600,
      },
      "/v1/agents/agent-1/pending": {
        agent_id: "agent-1",
        agent_status: "live",
        published: true,
        has_pending: false,
        pending: [],
        effective_call_cap_s: 600,
        call_cap_is_platform_default: true,
        worst_case_call_cost_inr: "12.50",
        precedence_rule: "Script decides content.",
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
            title: "+9198765•••10 was not called",
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
        { id: "num-1", e164: "+918041234567", series: "140", dlt_status: "approved" },
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
          created_at: "2026-08-01T10:00:00Z",
        },
      ],
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
    file: "c/[slug]/do-not-call/page.tsx",
    realm: "client",
    element: () => <DoNotCallPage />,
    routes: {
      "/v1/me": ME,
      "/v1/dnc?limit=500": {
        items: [
          { id: "dnc-1", phone_masked: "+9198••••3210", reason: "requested_on_call", source: "call", created_at: "2026-08-11T10:00:00Z", note: null },
        ],
        total: 1,
      },
    },
  },
  {
    file: "c/[slug]/knowledge/page.tsx",
    realm: "client",
    element: () => <KnowledgePage />,
    routes: {
      "/v1/me": ME,
      "/v1/agents": [AGENT],
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
        busiest_hours_ist: [0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 5, 3, 1, 0, 0, 4, 6, 9, 12, 7, 2, 0, 0, 0],
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
        { id: "inv-1", email_masked: "k•••@example.com", role: "staff", created_at: "2026-08-12T09:00:00Z", expires_at: "2026-08-19T09:00:00Z" },
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
    file: "c/[slug]/verification/page.tsx",
    realm: "client",
    element: () => <VerificationPage />,
    routes: {
      "/v1/me": ME,
      "/v1/usage": USAGE,
      "/v1/compliance/kyc": KYC_RECORD,
    },
  },
  {
    file: "invite/page.tsx",
    realm: "client",
    element: () => <InvitePage />,
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
  {
    file: "(auth)/sign-in/[[...sign-in]]/page.tsx",
    realm: "client",
    element: () => <ClientSignInPage />,
    routes: {},
  },
  {
    file: "(auth)/sign-up/[[...sign-up]]/page.tsx",
    realm: "client",
    element: () => <ClientSignUpPage />,
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
    routes: { "/v1/admin/me": ADMIN_ME, "/v1/admin/compliance/holds": [HELD_TENANT] },
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
          signals: [{ rule: "deliveries_failing", severity: "stop", causes: [], count: 3 }],
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
    file: "admin/new/page.tsx",
    realm: "admin",
    element: () => <NewClientPage />,
    routes: { "/v1/admin/onboarding/unfinished": [] },
  },
  {
    file: "admin/ops/page.tsx",
    realm: "admin",
    element: () => <OpsPage />,
    routes: { "/v1/admin/me": ADMIN_ME, "/v1/ops/platform": PLATFORM },
  },
  {
    file: "admin/tenants/[tenantId]/page.tsx",
    realm: "admin",
    element: () => <TenantDetailPage params={tenant} />,
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
    routes: {
      [`/v1/admin/tenants/t1/invoice?month=${IST_MONTH}`]: {
        invoice_number: "CAL-202608-0192f0aa",
        month: IST_MONTH,
        generated_at: "2026-08-13T04:30:00Z",
        organization: { id: "t1", name: "Sri Traders", billing_email: "accounts@example.com" },
        line_items: [
          { description: "Monthly plan fee", qty: "1", unit_inr: "9999.00", amount_inr: "9999.00" },
        ],
        subtotal_inr: "9999.00",
        gst_inr: "1799.82",
        gst_rate_pct: "18",
        total_inr: "11798.82",
        usage: { calls: 412, included_minutes: 500, minutes_used: "120.5" },
      },
    },
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
    file: "admin/tenants/[tenantId]/agents/[agentId]/prompt/page.tsx",
    realm: "admin",
    element: () => (
      <AgentPromptPage params={Promise.resolve({ tenantId: "t1", agentId: "agent-1" })} />
    ),
    routes: {
      "/v1/admin/me": ADMIN_ME,
      "/v1/admin/tenants/t1": TENANT_SUMMARY,
      "/v1/admin/tenants/t1/agents/agent-1/prompt": [
        { id: "v2", version: 2, notes: "challenger", created_at: "2026-08-01T04:00:00Z", active: true },
        { id: "v1", version: 1, notes: "control", created_at: "2026-07-01T04:00:00Z", active: false },
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
          metrics: [{ key: "call_outcome_resolved", label: "calls the agent resolved" }],
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
  {
    file: "(auth)/admin/sign-in/[[...sign-in]]/page.tsx",
    realm: "admin",
    element: () => <AdminSignInPage />,
    routes: {},
  },
];

export const SCREENS: Screen[] = [...CLIENT_SCREENS, ...ADMIN_SCREENS];

describe("every screen is scanned by axe", () => {
  it.each(SCREENS.map((s) => [s.file, s] as const))("%s", async (_file, screen) => {
    const { container } =
      screen.realm === "client"
        ? await renderClientPage(screen.element(), screen.routes)
        // `renderAdminRoute`, not `renderAdminPage`: several admin screens read
        // `use(params)` and therefore SUSPEND on first paint, which a bare synchronous
        // render leaves as an empty container.
        : await renderAdminRoute(screen.element(), screen.routes);
    // Let every TanStack query resolve before scanning. Neither `renderClientPage` (which
    // only awaits the Suspense boundary) nor `renderAdminPage` (synchronous by design)
    // waits for the network, so without this the scan sees SKELETONS — which is the
    // vacuous pass `assertScreenRendered` refuses. A macrotask is enough: `stubApi`
    // answers from memory, so the only thing outstanding is React's own flush.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await expectNoA11yViolations(container, screen.file);
  });
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
    expect(ghosts, `UNSWEPT_SCREENS names screens that are gone: ${ghosts.join(", ")}`).toEqual([]);
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
