import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentsPage from "@/app/c/[slug]/agents/page";
import UsagePage from "@/app/c/[slug]/usage/page";
import type { Agent } from "@/lib/api/agents";
import type { Me } from "@/lib/api/client";
import type { Caps } from "@/lib/api/caps";
import type { UsagePanel } from "@/lib/api/hooks";
import type { Lanes, PendingState } from "@/lib/api/publishing";

import { renderClientPage } from "./harness";

/**
 * The value beside a labelled row, not "some element on the page with this text".
 *
 * `Row` renders `<dt>{label}</dt><dd>{value}</dd>`, and several rows legitimately carry
 * the same rupee figure — a bare `findByText("₹42.50")` would match the line ABOVE the
 * total and pass without the total ever being computed. Asking for the total by name is
 * the difference between testing the sum and testing that the number exists somewhere.
 */
function rowValue(container: HTMLElement, label: string): string {
  const dt = [...container.querySelectorAll("dt")].find((el) => el.textContent === label);
  expect(dt, `row labelled ${JSON.stringify(label)}`).toBeDefined();
  return dt?.nextElementSibling?.textContent ?? "";
}

const TOTAL = "Total so far";

/**
 * Hard rule 7 at the last inch: INR crosses the wire as a STRING and reaches the DOM
 * as the same string.
 *
 * The API stringifies `Decimal` at the boundary precisely so nothing downstream rounds
 * it, and the frontend's whole obligation is to not undo that. `Number()` is the way it
 * gets undone — ₹10,159.00 becomes ₹10,158.999999999998 — and a type checker is happy
 * either way, because `string` and `number` both render.
 *
 * Two rules live here and both were argued in the code before they were tested:
 *
 * 1. `worst_case_call_cost_inr: null` means "your plan quotes no per-minute rate, so we
 *    cannot put a number on it". Rendering it as ₹0 is the one answer that is actively
 *    wrong: it tells an owner a ten-minute call is free.
 * 2. Money is added in whole PAISE, never in floats.
 */

const AGENT_ID = "0192f0aa-1111-7000-8000-000000000001";

const ME: Me = {
  impersonating: false,
  permissions: ["org:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENT: Agent = {
  id: AGENT_ID,
  name: "Front desk",
  direction: "inbound",
  status: "live",
  published: true,
  engine: "bolna",
  language_primary: "te-IN",
  disclosure_line: "Namaste, this is an AI assistant calling on behalf of Acme Clinic.",
  extraction_fields: [],
};

const LANES: Lanes = {
  call_cap_default_s: 600,
  call_cap_max_s: 1800,
  call_cap_min_s: 60,
  precedence_rule: "The most recent staged version wins.",
  lanes: [{ field: "prompt", lane: "staged", precedence: 1, why: "Needs a regression run." }],
};

function pending(over: Partial<PendingState> = {}): PendingState {
  return {
    agent_id: AGENT_ID,
    agent_status: "live",
    published: true,
    has_pending: false,
    pending: [],
    precedence_rule: LANES.precedence_rule,
    call_cap_is_platform_default: true,
    effective_call_cap_s: 600,
    worst_case_call_cost_inr: "10159.00",
    ...over,
  };
}

async function renderAgents(state: PendingState) {
  return await renderClientPage(<AgentsPage params={Promise.resolve({ slug: "acme" })} />, {
    "/v1/agents": [AGENT],
    "/v1/agents/lanes": LANES,
    [`/v1/agents/${AGENT_ID}/pending`]: state,
  });
}

describe("worst-case call cost", () => {
  it("renders a null cost as 'we cannot say', never as ₹0", async () => {
    // No per-minute rate on the plan means we genuinely do not know. Quoting zero is
    // not a conservative default — it is a wrong number a client can plan against.
    const { container } = await renderAgents(pending({ worst_case_call_cost_inr: null }));

    await screen.findByText("We cannot say yet");
    expect(container.textContent).not.toContain("₹0");
    expect(container.textContent).not.toContain("₹null");
    expect(container.textContent).toContain(
      "Your plan does not quote a per-minute rate, so we cannot put a number on it.",
    );
  });

  it("renders the exact NUMERIC digits, trailing zeros and all", async () => {
    // `Number("10159.00")` renders as "10159" — the paise silently vanish — and
    // arithmetic on it is where the last two decimals stop being trustworthy.
    //
    // Grouped, because the agents screen now formats this field through `formatINR`
    // like every other rupee figure in the console (the usage total above moved for the
    // same reason). It was the last caller printing `₹${wireString}` by hand, which
    // rendered ₹1,500.00 as "₹1500.00" and a rate of "6.5" as "₹6.5" — one amount, two
    // shapes, depending on which screen you were looking at. The DIGITS are still the
    // server's: `formatINR` groups the string and never parses it, which is the half of
    // hard rule 7 this file exists to hold.
    const { container } = await renderAgents(pending({ worst_case_call_cost_inr: "10159.00" }));

    await screen.findByText("₹10,159.00");
    expect(container.textContent).not.toContain("10158.99");
  });

  it("keeps a value only a Decimal can hold intact", async () => {
    // 0.1 + 0.2 territory. If anything on the path touches this with a float, the
    // string that lands on screen will not be the string the biller sent.
    await renderAgents(pending({ worst_case_call_cost_inr: "0.30" }));
    await screen.findByText("₹0.30");
  });
});

const CAPS: Caps = {
  capped: false,
  month: "2026-08",
  minutes_used: "120.5",
  spend_used_inr: "0.30",
  client_cap_minutes: null,
  client_cap_spend_inr: null,
  effective_cap_minutes: null,
  effective_cap_spend_inr: null,
  plan_cap_minutes: null,
  plan_cap_spend_inr: null,
};

function usage(over: Partial<UsagePanel> = {}): UsagePanel {
  return {
    month: "2026-08",
    calls: 12,
    capped: false,
    cap_minutes: null,
    minutes_left: null,
    included_minutes: 500,
    minutes_used: "120.5",
    credit_balance_inr: null,
    monthly_fee_inr: "0.10",
    overage_cost_inr: "0.20",
    overage_minutes: "0",
    overage_minutes_premium: "0",
    overage_minutes_value: "0",
    overage_rate_inr: "6.00",
    overage_rate_value_inr: "4.00",
    plan_tier: "growth",
    spend_used_inr: "0.30",
    ...over,
  };
}

async function renderUsage(panel: UsagePanel) {
  const rendered = await renderClientPage(<UsagePage />, {
    "/v1/usage": panel,
    "/v1/billing/caps": CAPS,
    "/v1/me": ME,
  });
  // The panel paints a skeleton until the query lands; every assertion below is about
  // the arithmetic, so waiting for the row to exist belongs here rather than in each.
  await screen.findByText(TOTAL);
  return rendered;
}

describe("the month's total", () => {
  it("adds two INR strings in paise, not in floats", async () => {
    // The canonical float trap: 0.1 + 0.2 = 0.30000000000000004. On an invoice total
    // that is the most embarrassing possible place for it to surface, and it is one
    // careless `Number()` away at all times.
    const { container } = await renderUsage(usage({ monthly_fee_inr: "0.10", overage_cost_inr: "0.20" }));

    expect(rowValue(container, TOTAL)).toBe("₹0.30");
    expect(container.textContent).not.toContain("0.30000000000000004");
  });

  it("carries paise into rupees rather than printing 100 of them", async () => {
    const { container } = await renderUsage(usage({ monthly_fee_inr: "10158.99", overage_cost_inr: "0.01" }));

    expect(rowValue(container, TOTAL)).toBe("₹10159.00");
    expect(container.textContent).not.toContain("10158.100");
  });

  it("treats an absent monthly fee as nothing, not as NaN", async () => {
    const { container } = await renderUsage(usage({ monthly_fee_inr: null, overage_cost_inr: "42.50" }));

    expect(rowValue(container, "Plan fee")).toBe("—");
    expect(rowValue(container, TOTAL)).toBe("₹42.50");
    expect(container.textContent).not.toContain("NaN");
  });

  it("keeps a credit (a negative total) signed and exact", async () => {
    const { container } = await renderUsage(usage({ monthly_fee_inr: "-5.75", overage_cost_inr: "1.25" }));

    expect(rowValue(container, TOTAL)).toBe("₹-4.50");
    expect(container.textContent).not.toContain("NaN");
  });
});
