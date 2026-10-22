/**
 * THE ONE MAP from a live change note's topic to the query families that show it (D-774).
 *
 * The server says "calls changed" (`apps/api/live/topics.py`); this file says which
 * TanStack queries to refetch when it does. Every query key in `src/` belongs to a FAMILY
 * (`familyOf`), and every family is either listed under the topics that change it or in
 * `STATIC_FAMILIES` with the reason nothing announces it. `tests/liveTopics.test.ts` reads
 * every `queryKey:` in the tree and fails when one is in neither, so a new feed cannot
 * silently miss live updates.
 */

/** The server's vocabulary, pinned against `apps/api/live/topics.py` by the test. */
export const LIVE_TOPICS = [
  "account",
  "agents",
  "alerts",
  "assistant",
  "callbacks",
  "calls",
  "campaigns",
  "conversation",
  "dnc",
  "healer",
  "integrations",
  "knowledge",
  "knowledge_gaps",
  "leads",
  "numbers",
  "platform",
  "quality",
  "wallet",
] as const;

export type LiveTopic = (typeof LIVE_TOPICS)[number];

/** Families whose first segment is a realm prefix take the next segment as well. */
const PREFIXED = new Set(["admin", "ops", "client"]);

/**
 * The family a query key belongs to: its first string segment, plus the second for the
 * `admin`/`ops`/`client` prefixes, plus the third for `admin/ops`. Everything after that
 * is the tenant, the id or the filter, which a note never names.
 */
export function familyOf(queryKey: readonly unknown[]): string | null {
  const [first, second, third] = queryKey;
  if (typeof first !== "string") return null;
  if (!PREFIXED.has(first) || typeof second !== "string") return first;
  const two = `${first}/${second}`;
  return two === "admin/ops" && typeof third === "string" ? `${two}/${third}` : two;
}

// What the client's home screen and its banners are built from. Most changes move one of
// these, so they ride along with the topic that moved them.
const SUMMARY = ["dashboard", "attention"] as const;

export const TOPIC_FAMILIES: Record<LiveTopic, readonly string[]> = {
  calls: [
    ...SUMMARY,
    "call",
    "calls",
    "calls-log",
    "callback-check",
    "performance",
    "quality",
    "trial",
    "usage",
    "admin/ops/reply-times",
    "admin/client-health",
    "admin/spend",
    "admin/fleet-spend",
    "admin/margin",
    "admin/tenants",
  ],
  leads: [
    ...SUMMARY,
    "lead",
    "leads",
    "lead-facets",
    "lead-timeline",
    "lead-views",
    "lead-captured",
    "lead-calling",
    "ingest-activity",
    "members",
    // `lead_field_drafts` announces `leads`; a draft that fails writes nothing else.
    "lead-fields",
    "admin/lead-fields",
  ],
  campaigns: [
    ...SUMMARY,
    "campaign",
    "campaigns",
    "campaign-check",
    "campaign-numbers",
    "dlt-templates",
    "pe-registration",
    "outbound-pledge",
    "outbound-consent-policy",
    "admin/campaigns",
    "admin/campaign-check",
  ],
  callbacks: [...SUMMARY, "callbacks", "callback-check"],
  knowledge_gaps: [...SUMMARY, "knowledge-gaps", "kb-struggles"],
  knowledge: [
    "kb",
    "kb-preview",
    "kb-staff-curation",
    "kb-upload",
    "kb-uploads",
    "kb-knows",
    "kb-teaching",
    "kb-teaching-open",
    "kb-struggles",
    "admin/kb",
    "admin/kb-preview",
  ],
  wallet: [
    ...SUMMARY,
    "wallet",
    "billing",
    "billing-caps",
    "billing-auto-recharge",
    "billing-spend-series",
    "billing-statements",
    "usage",
    "ai-quota",
    "invoice",
    "spend",
    "platform-fee",
    "trial",
    "admin/credits",
    "admin/invoice",
    "admin/margin",
    "admin/spend",
    "admin/fleet-spend",
    "admin/platform-fee",
    "admin/trial",
    "admin/tts-speaking-rate",
    "admin-payments",
  ],
  agents: [
    ...SUMMARY,
    "agent",
    "agents",
    "agents-archived",
    "agent-stats",
    "agent-starters",
    "agent-engine-state",
    "agent-experiment",
    "agent-handoff",
    "agent-lanes",
    "agent-pending",
    "agent-proposed-rules",
    "agent-test-cases",
    "call-test-case-draft",
    // Each agent's outcomes and its AI draft's state live on the `agents` row (D-836).
    "call-outcomes",
    "script",
    "script-tests",
    "script-versions",
    "script-proposal",
    "call-handling",
    "reply-length",
    "voice-tuning",
    "llm-defaults",
    "lead-fields",
    "actions",
    "caller-notice",
    "admin/agents",
    "admin/prompt",
    "admin/lead-fields",
    "admin/llm-defaults",
    "admin/ops/live-apply",
  ],
  numbers: [
    "attention",
    "own-numbers",
    "number-holder",
    "numbers-available",
    "campaign-numbers",
    "forwarding",
    "call-lines",
    "admin/numbers",
    "admin/engine-numbers",
    "admin/engine-business-details",
    "admin/engine-workspace",
    "admin/engine-workspaces",
    "admin/number-costs",
    "admin/forwarding",
  ],
  dnc: ["dnc", "dnc-evidence", "campaign-check", "admin/ops/dnc-global"],
  account: [
    ...SUMMARY,
    "me",
    "members",
    "invitations",
    "kyc",
    "business-profile",
    // The account's AI-written examples (D-827): a run writes `business_copies`.
    "business-copy",
    "admin/business-copy",
    "legal-readiness",
    "deletion-request",
    "deletion-requests",
    "whatsapp-alerts",
    // A trial start or end writes only `tenant_trials`, which announces `account`; the
    // wallet shows the active trial, so these move with it.
    "trial",
    "wallet",
    "admin/trial",
    "admin/credits",
    "admin/tenant",
    "admin/tenants",
    "admin/tenant-profile",
    "admin/tenant-members",
    "admin/invitations",
    "admin/kyc",
    "admin/kyc-reviews",
    "admin/tenant-kyc",
    "admin/holds",
    "admin/business-profile",
    "admin/business-type",
    "admin/closure",
    "admin/commercial-terms",
    "admin/feature-flags",
    "admin/onboarding",
    "admin/tenant-erasure",
    "admin/whatsapp-alerts",
    "admin/client-health",
  ],
  integrations: [
    "endpoints",
    "deliveries",
    "lead-sources",
    "ingest-activity",
    "whatsapp",
    "admin/whatsapp",
  ],
  // The caller's OWN Pip conversation (D-782). The server sends it on that person's channel
  // only, so it never moves when a colleague talks to Pip.
  conversation: ["copilot"],
  assistant: [
    "copilot-actions",
    "copilot-approval-preview",
    "copilot-approvals",
    "copilot-job",
    "copilot-jobs",
    "copilot-routine-runs",
    "copilot-routines",
  ],
  quality: ["quality", "admin/qa-samples"],
  healer: ["healer", "admin/healer", "admin/client-health"],
  alerts: ["admin/ops/alerts"],
  // Operator-stream only: a client's stream never carries `platform`, so the client
  // screens below that read platform settings keep their own polls.
  platform: [
    "admin/me",
    "admin/platform",
    "admin/operators",
    "admin/templates",
    "admin/number-pricing",
    "admin/ops/config",
    "admin/ops/dashboard-data-use",
    "admin/ops/in-call-data-use",
    "admin/ops/fx-rate",
    "admin/ops/inr-llm-prices",
    "admin/ops/kek",
    "admin/ops/maintenance",
    "admin/ops/model-prices",
    "admin/ops/rate-card",
    "admin/ops/secrets",
    "admin/ops/spoken-style",
    "admin/ops/voices",
    "ops/config-sources",
    "ops/engine-minute-prices",
    "ops/engine-model-bands",
    "ops/trial-number",
    "ops/tts-plan-fees",
    "admin/tts-speaking-rate",
    "client/maintenance",
    "engine-catalogue",
  ],
};

/** Families nothing announces, and why. */
export const STATIC_FAMILIES: Record<string, string> = {
  authn: "the sign-in options of this deployment; they change with a deploy, not a write",
  public: "the public status page, read by people with no session to stream to",
  "voice-preview": "a rendered audio sample; it is fetched once when asked for",
  "integration-options": "the fixed list of services an account can connect",
  "admin/qa-sample":
    "one sampled call under review; every read writes an audit row, so it is read once when opened",
  // "Meet your agent" (D-855): written only by its own screen and its workers, and polled
  // while a worker is on it, so nothing needs announcing.
  "first-run": "the first run, polled while its questions or build are being worked on",
  "first-run-recording": "one spoken piece of the brief, polled until it is heard",
  "junction-first-run": "read once by the sign-in junction to choose where to send an owner",
};

/** Every family a note about `topics` refetches. */
export function familiesFor(topics: Iterable<LiveTopic>): Set<string> {
  const out = new Set<string>();
  for (const topic of topics) for (const family of TOPIC_FAMILIES[topic]) out.add(family);
  return out;
}

/** Every family any note can refetch — what a reconnect refetches. */
export const ALL_LIVE_FAMILIES: ReadonlySet<string> = familiesFor(LIVE_TOPICS);

export function isLiveTopic(value: unknown): value is LiveTopic {
  return typeof value === "string" && (LIVE_TOPICS as readonly string[]).includes(value);
}
