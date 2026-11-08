import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CallingNumbersPage from "@/app/admin/calling-numbers/page";
import CallWordsPage from "@/app/admin/ops/call-words/page";
import { AgentsScreen } from "@/app/admin/tenants/[tenantId]/agents/AgentsScreen";
import TenantLayout from "@/app/admin/tenants/[tenantId]/layout";
import { MarginPanel } from "@/app/admin/tenants/[tenantId]/MarginPanel";
import { planLabel, type Margin, type TenantSummary } from "@/lib/api/admin";
import { FILING_BOARD_PATH, type FilingBoard } from "@/lib/api/callingNumberFilings";
import { CALL_WORDS_PATH } from "@/lib/api/callWords";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { CALL_WORDS } from "./fixtures/callWords";
import { agentRow } from "./fixtures/sharedReads";
import { noReply, renderAdminPage } from "./harness";

/**
 * Frontend audit W5 (8 Nov 2026), admin realm: wire codes printed where the console has a
 * label for them, and two lines that said the wrong thing in an edge state.
 */

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => `/admin/tenants/${TENANT}/agents`,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));

const TENANT = "0192f0aa-7777-7000-8000-0000000000b5";
const SLUG = "sri-traders";

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000c5",
  role: "superadmin",
  permissions: ["org:read", "admin:tenants", "ops:manage"],
};

function tenant(over: Partial<TenantSummary> = {}): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: SLUG,
    status: "active",
    plan_tier: "self_serve",
    vertical_template: "real_estate",
    live_agents: 1,
    calls_7d: 3,
    leads: 1,
    last_call_at: null,
    holds: [],
    capped: false,
    ...over,
  };
}

const MARGIN: Margin = {
  month: "2026-08",
  minutes_used: "12.50",
  calls: 6,
  revenue_inr: "0.00",
  rental_revenue_inr: "0.00",
  cost_inr: "17.98",
  margin_inr: "-17.98",
  margin_pct: null,
  legs_unpriced: 0,
  trial_cost_inr: "0.00",
  trial_in_month: false,
  paid_cost_inr: "17.98",
  paid_margin_inr: "-17.98",
  paid_margin_pct: null,
  tiers: {
    minutes_base_rung: "12.50",
    minutes_second_rung: "0.00",
    minutes_premium: "12.50",
    minutes_value: "0.00",
    minutes_unattributed: "0.00",
    cost_base_rung_inr: "17.98",
    cost_second_rung_inr: "0.00",
    cost_premium_inr: "17.98",
    cost_value_inr: "0.00",
    cost_unattributed_inr: "0.00",
  },
};

describe("admin wire codes shown as the console's own words", () => {
  it("names the plan the way the directory does, an unknown one in words", () => {
    expect(planLabel("self_serve")).toBe("Credits (signed up online)");
    expect(planLabel("prepaid")).toBe("Credits");
    expect(planLabel("trial")).toBe("Free trial");
    expect(planLabel("some_new_tier")).toBe("Some new tier");
    expect(planLabel("constructor")).toBe("Constructor");
  });

  it("heads every client page with the plan and business type as labels, not codes", async () => {
    await renderAdminRoute(
      <TenantLayout params={routeParams({ tenantId: TENANT })}>
        <h2>Sub-page body</h2>
      </TenantLayout>,
      { [ADMIN_ME_PATH]: ME, [`/v1/admin/tenants/${TENANT}`]: tenant() },
    );
    expect(await screen.findByText(/\/c\/sri-traders · Credits \(signed up online\) · Real estate/)).toBeTruthy();
    expect(screen.queryByText(/self serve|real estate\b/)).toBeNull();
  });

  it("titles the margin with the month's name, not its key", async () => {
    renderAdminPage(<MarginPanel tenantId={TENANT} />, {
      [ADMIN_ME_PATH]: ME,
      [`/v1/admin/tenants/${TENANT}/margin`]: MARGIN,
    });
    expect(await screen.findByText("Margin · August 2026")).toBeTruthy();
    expect(screen.queryByText(/2026-08/)).toBeNull();
  });

  it("names an agent's language rather than printing its tag", async () => {
    renderAdminPage(<AgentsScreen tenantId={TENANT} />, {
      [ADMIN_ME_PATH]: ME,
      [`/v1/admin/tenants/${TENANT}`]: tenant(),
      "/v1/agents": [agentRow({ language_primary: "en-IN" })],
      [`/v1/admin/organizations/${TENANT}/llm-defaults`]: noReply(),
    });
    expect(await screen.findByText(/Answers calls · English/)).toBeTruthy();
    expect(screen.queryByText(/en-IN/)).toBeNull();
  });
});

describe("edge states that said the wrong thing", () => {
  it("does not end a filed number's line with a dangling separator when no reference came back", async () => {
    const board: FilingBoard = {
      enforced_from: "2026-11-17",
      alarm_from: "2026-11-10",
      alarm: false,
      clients: [
        {
          tenant_id: TENANT,
          name: "Sri Traders",
          slug: SLUG,
          authorised_on: "2026-10-30",
          numbers: [{ number: "+914049001234", filed_on: "2026-11-02", filing_reference: null }],
          unfiled: 0,
        },
      ],
    };
    renderAdminPage(<CallingNumbersPage />, { [ADMIN_ME_PATH]: ME, [FILING_BOARD_PATH]: board });
    const filed = await screen.findByText(/^Filed /);
    expect(filed.textContent?.trim().endsWith("·")).toBe(false);
  });

  it("says nothing is waiting for words, rather than 'no list matches', once every list is written", async () => {
    const written = {
      ...CALL_WORDS,
      entries: CALL_WORDS.entries.map((entry) => ({ ...entry, edited: entry.asked_for ? true : entry.edited })),
    };
    renderAdminPage(<CallWordsPage />, { [ADMIN_ME_PATH]: ME, [CALL_WORDS_PATH]: written });
    expect(await screen.findByText("No list is waiting for your words.")).toBeTruthy();
    expect(screen.queryByText("No list matches.")).toBeNull();
  });
});
