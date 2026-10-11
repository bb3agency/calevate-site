/**
 * Forwarding fixtures (D-746). `NO_FORWARDING_ROUTES` is the state of a client with no
 * Calevate number yet, which renders nothing on the dashboard and the phone-number page,
 * so screens that merely host the prompt need only spread it into their routes.
 */
import type { AdminForwarding, Forwarding, ForwardingCodes, ForwardingTest } from "@/lib/api/forwarding";

export const NO_FORWARDING: Forwarding = {
  lines: [],
  calevate_numbers: [],
  testing_available: true,
  concurrency_testable: true,
  max_lines: 5,
};

export const NO_FORWARDING_ROUTES = { "/v1/forwarding": NO_FORWARDING };

export const LINE = {
  id: "l1",
  e164: "+919812345678",
  line_kind: "mobile",
  carrier: "airtel",
  mode: "conditional",
  ring_seconds: 20,
  calevate_number_id: "n1",
  calevate_number_e164: "+918012345678",
  status: "working",
  attested_at: "2026-10-11T04:00:00Z",
  last_tested_at: "2026-10-11T05:00:00Z",
  caller_id_finding: "business_number_shown",
  concurrency_finding: "one_arrived",
  last_test_outcome: "arrived",
  quiet_since: "2026-10-08T05:00:00Z",
} satisfies Forwarding["lines"][number];

export const WITH_LINE: Forwarding = {
  ...NO_FORWARDING,
  lines: [LINE],
  calevate_numbers: [{ id: "n1", e164: "+918012345678", answering: true }],
};

export const READY_TO_FORWARD: Forwarding = {
  ...NO_FORWARDING,
  calevate_numbers: [{ id: "n1", e164: "+918012345678", answering: true }],
};

export const SETTLED_TEST: ForwardingTest = {
  id: "t1",
  line_id: "l1",
  status: "settled",
  outcome: "arrived",
  legs_placed: 2,
  caller_id_finding: "business_number_shown",
  concurrency_finding: "one_arrived",
  failure_code: null,
  created_at: "2026-10-11T05:00:00Z",
  settled_at: "2026-10-11T05:03:00Z",
};

const gsm = (stars: string, evidence: "carrier_own" | "web_secondary") => [
  { condition: "no_answer", activate: `${stars}61*{number}**{seconds}#`, deactivate: "##61#", evidence, source: "https://example.invalid/codes" },
  { condition: "busy", activate: `${stars}67*{number}#`, deactivate: "##67#", evidence, source: "https://example.invalid/codes" },
  { condition: "unreachable", activate: `${stars}62*{number}#`, deactivate: "##62#", evidence, source: "https://example.invalid/codes" },
  { condition: "all_calls", activate: `${stars}21*{number}#`, deactivate: "##21#", evidence, source: "https://example.invalid/codes" },
  { condition: "everything", activate: null, deactivate: "##002#", evidence, source: "https://example.invalid/codes" },
];

export const CODES: ForwardingCodes = {
  carriers: [
    { carrier: "airtel", method: "codes", codes: gsm("**", "web_secondary"), unconfirmed: [], app_path: null, note: "Airtel's own page lists the all-calls code." },
    { carrier: "vi", method: "codes", codes: gsm("*", "carrier_own"), unconfirmed: [], app_path: null, note: null },
    {
      carrier: "jio",
      method: "app",
      codes: [],
      unconfirmed: [{ label: "Standard codes", codes: gsm("**", "web_secondary") }],
      app_path: "MyJio app: Profile > Mobile Settings > Service Settings > Call Forwarding.",
      note: "Jio publishes no codes.",
    },
  ],
  provider: { carrier: "provider", method: "ask_provider", codes: [], unconfirmed: [], app_path: null, note: null },
  ring_time_source: "https://example.invalid/standard",
  read_on: "2026-10-11",
};

export const ADMIN_FORWARDING: AdminForwarding = {
  lines: [LINE],
  recent_tests: [SETTLED_TEST],
  save_number_enabled: true,
  save_number_sent: 4,
};
