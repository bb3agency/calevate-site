import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { WorkspacesSummaryPanel } from "@/app/admin/ops/WorkspacesSummaryPanel";
import TenantNumbersPage from "@/app/admin/tenants/[tenantId]/numbers/page";
import type { TenantSummary } from "@/lib/api/admin";
import {
  WORKSPACE_PATHS,
  type TenantWorkspace,
  type WorkspacesSummary,
} from "@/lib/api/engineWorkspaces";

import { problem, renderAdminPage, type ApiCall, type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * D-693: each client's own ThinnestAI customer workspace, on the operator's Numbers screen
 * and on the ops dashboard.
 *
 * - The workspace's state is said plainly, the plan's customer cap above all, with the
 *   lever that fixes it.
 * - The operator buys with the client's price AND our cost in view.
 * - "Release" and "Release our record" are separate acts, each confirmed.
 * - A number held in the platform account is flagged as testing only.
 * - The ops summary warns when the plan has one workspace or fewer left.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000ef";
const AGENT = "0192f0aa-7777-7000-8000-000000000444";
const NUMBER_ID = "0192f0aa-7777-7000-8000-000000000555";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const COSTS_PATH = `/v1/admin/numbers/tenants/${TENANT}`;
const ENGINE_PATH = `${COSTS_PATH}/engine`;

const SUPERADMIN: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000cd",
  role: "superadmin",
  permissions: ["org:read", "billing:read", "admin:tenants", "ops:manage"],
};

function workspace(over: Partial<TenantWorkspace> = {}): TenantWorkspace {
  return {
    available: true,
    status: "active",
    workspace_id: "ws_123",
    last_error_code: null,
    attempts: 1,
    provisioned_at: "2026-10-08T09:00:00Z",
    business_details: {
      status: "accepted",
      can_rent: true,
      review_note: null,
      submitted_at: "2026-10-08T09:10:00Z",
      checked_at: "2026-10-08T09:20:00Z",
    },
    purchase_step: "ready",
    purchase_blockers: [],
    client_inr_per_month: "499.00",
    numbers: { own_workspace: 1, platform_held: 1 },
    agents_in_platform_account: 0,
    ...over,
  };
}

function routes(own: TenantWorkspace, extra: Routes = {}): Routes {
  return {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [TENANT_PATH]: {
      id: TENANT,
      name: "Console Clinic",
      slug: "console-clinic",
      status: "active",
      plan_tier: "starter",
      vertical_template: "clinic",
      leads: 0,
      calls_7d: 0,
      live_agents: 1,
      last_call_at: null,
      capped: false,
      holds: [],
    } satisfies TenantSummary,
    [COSTS_PATH]: [],
    [ENGINE_PATH]: {
      managed_in_engine_console: true,
      platform: "ThinnestAI",
      steps: [],
      notes: [],
      numbers: [
        {
          e164: "+918012345672",
          provider: null,
          engine_owned: true,
          agent_id: AGENT,
          agent_name: "Front desk",
          unassigned: false,
          number_id: NUMBER_ID,
          platform_held: true,
        },
      ],
      other_numbers: 0,
      agents: [
        { agent_id: AGENT, name: "Front desk", engine_agent_ref: "ag_1", answers_a_number: true },
      ],
    },
    "/v1/agents": [],
    [WORKSPACE_PATHS.tenant(TENANT)]: own,
    [WORKSPACE_PATHS.cities(TENANT)]: [{ name: "Hyderabad", available: 4 }],
    [WORKSPACE_PATHS.available(TENANT, "Hyderabad", "", null)]: {
      numbers: [
        {
          number: "918012345679",
          e164: "+918012345679",
          city: "Hyderabad",
          client_inr_per_month: "499.00",
          vendor_inr_per_month: "350.00",
        },
      ],
      next_cursor: null,
    },
    ...extra,
  };
}

function render(own: TenantWorkspace, extra: Routes = {}) {
  return renderAdminRoute(<TenantNumbersPage params={routeParams({ tenantId: TENANT })} />, routes(own, extra));
}

function posts(calls: ApiCall[], path: string): ApiCall[] {
  return calls.filter((call) => call.method === "POST" && call.path === path);
}

async function enabledButton(name: string | RegExp): Promise<HTMLButtonElement> {
  const button = (await screen.findByRole("button", { name })) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  return button;
}

describe("the client's voice workspace panel", () => {
  it("shows the workspace, its numbers and its business details", async () => {
    await render(workspace());
    expect(await screen.findByText("Voice workspace")).toBeTruthy();
    expect(screen.getByText("ws_123")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText(/1 in the client's workspace, 1 held in the platform account/)).toBeTruthy();
    expect(screen.getByText("Approved")).toBeTruthy();
    expect(screen.getByText("Ready to buy")).toBeTruthy();
  });

  it("names the plan's customer cap and retries provisioning", async () => {
    const { calls } = await render(
      workspace({
        status: "plan_limit",
        workspace_id: null,
        last_error_code: "engine_plan_customer_limit",
        attempts: 3,
        provisioned_at: null,
        purchase_step: "workspace",
        purchase_blockers: ["engine_workspace_not_provisioned"],
      }),
      { [`POST ${WORKSPACE_PATHS.provision(TENANT)}`]: workspace() },
    );
    expect(await screen.findByText(/Upgrade the ThinnestAI plan, then Retry provisioning/)).toBeTruthy();
    expect(screen.getAllByText("Plan's customer limit reached").length).toBeGreaterThan(0);
    expect(screen.getByText("engine_plan_customer_limit")).toBeTruthy();
    expect(screen.getByText("The client's workspace is not active.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Find numbers" })).toBeNull();

    fireEvent.click(await enabledButton("Retry provisioning"));
    await waitFor(() => expect(posts(calls, WORKSPACE_PATHS.provision(TENANT))).toHaveLength(1));
  });

  it("offers no retry for an active workspace", async () => {
    await render(workspace());
    const retry = (await screen.findByRole("button", { name: "Retry provisioning" })) as HTMLButtonElement;
    expect(retry.disabled).toBe(true);
  });

  it("shows a failure with its error code", async () => {
    await render(workspace({ status: "failed", last_error_code: "engine_auth_failed", purchase_step: "workspace" }));
    expect(await screen.findByText("Provisioning failed", { selector: "div" })).toBeTruthy();
    expect(screen.getByText(/Last error: engine_auth_failed/)).toBeTruthy();
  });

  it("shows a rejected application's note, and sends and refreshes the details", async () => {
    const { calls } = await render(
      workspace({
        business_details: {
          status: "rejected",
          can_rent: false,
          review_note: "The name on the certificate does not match.",
          submitted_at: "2026-10-08T09:10:00Z",
          checked_at: null,
        },
        purchase_step: "business_details",
        purchase_blockers: ["business_details_not_approved"],
      }),
      {
        [`POST ${WORKSPACE_PATHS.businessDetails(TENANT)}`]: { status: "submitted" },
        [`POST ${WORKSPACE_PATHS.refreshDetails(TENANT)}`]: { status: "rejected" },
      },
    );
    expect(await screen.findByText("The name on the certificate does not match.")).toBeTruthy();
    expect(screen.getByText("Rejected — correct it and send again")).toBeTruthy();
    fireEvent.click(await enabledButton("Send business details"));
    fireEvent.click(await enabledButton("Refresh status"));
    await waitFor(() => expect(posts(calls, WORKSPACE_PATHS.businessDetails(TENANT))).toHaveLength(1));
    await waitFor(() => expect(posts(calls, WORKSPACE_PATHS.refreshDetails(TENANT))).toHaveLength(1));
  });

  it("says agents still in the platform account are recreated on their next publish", async () => {
    await render(workspace({ agents_in_platform_account: 2 }));
    expect(await screen.findByText(/2 agents are still in the platform account/)).toBeTruthy();
    expect(screen.getByText(/recreated in the client's workspace on their next publish/)).toBeTruthy();
  });

  it("confirms before offboarding", async () => {
    const { calls } = await render(workspace(), {
      [`POST ${WORKSPACE_PATHS.offboard(TENANT)}`]: problem(409, {
        type: "https://calevate.tech/problems/account_not_closed",
        detail: "This account is not closed.",
      }),
    });
    fireEvent.click(await enabledButton("Offboard"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Refused unless the account is closed/)).toBeTruthy();
    expect(posts(calls, WORKSPACE_PATHS.offboard(TENANT))).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Offboard" }));
    expect(await within(dialog).findByText("This account is not closed.")).toBeTruthy();
  });

  it("renders nothing on an engine without per-client workspaces", async () => {
    const { calls } = await render({ ...workspace(), available: false });
    await waitFor(() => expect(calls.some((call) => call.path === WORKSPACE_PATHS.tenant(TENANT))).toBe(true));
    expect(screen.queryByText("Voice workspace")).toBeNull();
  });
});

describe("an operator buying a number for the client", () => {
  it("shows the client's price and our cost, and buys with one request key", async () => {
    const { calls } = await render(workspace(), {
      [`POST ${WORKSPACE_PATHS.purchase(TENANT)}`]: {
        number_id: "0192f0aa-7777-7000-8000-000000000777",
        e164: "+918012345679",
        client_inr_per_month: "499.00",
        attachment: "applied",
        replayed: false,
        first_period: "trial",
      },
    });
    fireEvent.change(await screen.findByLabelText("City"), { target: { value: "Hyderabad" } });
    fireEvent.click(await enabledButton("Find numbers"));
    expect(await screen.findByText(/Client pays ₹499(\.00)? · our cost ₹350(\.00)? a month/)).toBeTruthy();
    fireEvent.click(await enabledButton("Buy +91 80123 45679"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/our cost is ₹350/)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Agent (optional)"), { target: { value: AGENT } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Buy for the client" }));

    expect(
      await screen.findByText(/₹499(\.00)? a month, free during the trial; charging starts at the first renewal after it\./),
    ).toBeTruthy();
    const [sent] = posts(calls, WORKSPACE_PATHS.purchase(TENANT)).map(
      (call) => JSON.parse(call.body ?? "null") as Record<string, unknown>,
    );
    expect(sent.number).toBe("918012345679");
    expect(sent.agent_id).toBe(AGENT);
    expect(sent.direction).toBe("both");
    expect(sent.request_key).toMatch(/^[A-Za-z0-9_-]{8,100}$/);
  });

  it("says an earlier request already bought it when the purchase is a replay", async () => {
    await render(workspace(), {
      [`POST ${WORKSPACE_PATHS.purchase(TENANT)}`]: {
        number_id: "0192f0aa-7777-7000-8000-000000000777",
        e164: "+918012345679",
        client_inr_per_month: "499.00",
        attachment: "unchanged",
        replayed: true,
        first_period: "replayed",
      },
    });
    fireEvent.change(await screen.findByLabelText("City"), { target: { value: "Hyderabad" } });
    fireEvent.click(await enabledButton("Find numbers"));
    fireEvent.click(await enabledButton("Buy +91 80123 45679"));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Buy for the client" }));
    expect(
      await screen.findByText("An earlier request already bought this number for the client. Nothing more was charged."),
    ).toBeTruthy();
  });

  it("keeps only digits in the search, ten at most", async () => {
    const searched = WORKSPACE_PATHS.available(TENANT, "Hyderabad", "8012345678", null);
    const { calls } = await render(workspace(), { [searched]: { numbers: [], next_cursor: null } });
    fireEvent.change(await screen.findByLabelText("City"), { target: { value: "Hyderabad" } });
    const digits = screen.getByLabelText("Contains (optional)") as HTMLInputElement;
    fireEvent.change(digits, { target: { value: "80 1234-5678 9" } });
    expect(digits.value).toBe("8012345678");
    expect(digits.maxLength).toBe(10);
    fireEvent.click(await enabledButton("Find numbers"));
    await waitFor(() => expect(calls.some((call) => call.path === searched)).toBe(true));
  });
});

describe("one release path for a number the voice platform holds", () => {
  const held = (on_engine: boolean) => ({
    id: NUMBER_ID,
    e164: "+918012345672",
    series: "standard",
    dlt_status: "pending",
    provider: on_engine ? "thinnest" : "plivo",
    engine_owned: true,
    engine_linked: true,
    agent_id: null,
    agent_name: null,
    monthly_rental_usd: null,
    released: false,
    platform_held: false,
    on_engine,
  });

  it("offers no generic Release on a voice-platform number, only releasing our record", async () => {
    await render(workspace(), { [COSTS_PATH]: [held(true)] });
    expect(await screen.findAllByText("+91 80123 45672")).toBeTruthy();
    await screen.findByText("Voice workspace");
    fireEvent.click(await screen.findByRole("button", { name: "More actions for +91 80123 45672" }));
    const menu = await screen.findByRole("menu");
    expect(within(menu).queryByRole("menuitem", { name: "Release" })).toBeNull();
    expect(within(menu).getByRole("menuitem", { name: "Release our record" })).toBeTruthy();
  });

  it("keeps the generic Release for a number bought elsewhere", async () => {
    await render(workspace(), { [COSTS_PATH]: [held(false)] });
    expect(await screen.findByRole("button", { name: "More actions for +91 80123 45672" })).toBeTruthy();
  });
});

describe("the engine numbers list", () => {
  it("flags a number held in the platform account as testing only", async () => {
    await render(workspace());
    expect(await screen.findByText("Held in the platform account (testing only)")).toBeTruthy();
  });

  it("releases a number for good after a warning that the month is not refunded", async () => {
    const { calls } = await render(workspace(), {
      [`POST ${WORKSPACE_PATHS.release(TENANT, NUMBER_ID)}`]: { number_id: NUMBER_ID, released: true },
    });
    fireEvent.click(await enabledButton("Release"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/This month is\s+not refunded/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Release for good" }));
    expect(await screen.findByText("Released. The monthly charge has stopped.")).toBeTruthy();
    expect(posts(calls, WORKSPACE_PATHS.release(TENANT, NUMBER_ID)).map((call) => JSON.parse(call.body ?? "null")))
      .toEqual([{ confirm: true }]);
  });

  it("releases only our record, and shows the refusal for a number the client still holds", async () => {
    const { calls } = await render(workspace(), {
      [`POST ${WORKSPACE_PATHS.forget(TENANT, NUMBER_ID)}`]: problem(409, {
        type: "https://calevate.tech/problems/engine_number_still_held",
        detail: "The client's own workspace still holds this number. Release it instead.",
      }),
    });
    fireEvent.click(await enabledButton("Release our record"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/without releasing anything at\s+ThinnestAI/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Release our record" }));
    expect(await within(dialog).findByText(/still holds this number/)).toBeTruthy();
    expect(posts(calls, WORKSPACE_PATHS.forget(TENANT, NUMBER_ID)).map((call) => JSON.parse(call.body ?? "null")))
      .toEqual([{ confirm: true }]);
  });
});

function summary(over: Partial<WorkspacesSummary> = {}): WorkspacesSummary {
  return {
    available: true,
    plan: "Growth",
    plan_cap: 10,
    counted: 7,
    headroom: 3,
    tenants: 8,
    provisioned: 6,
    by_status: { active: 6, plan_limit: 1, failed: 1 },
    failures: [],
    not_provisioned: 2,
    ...over,
  };
}

const ALLOWED = { allowed: true, reason: null };

describe("client voice workspaces on the ops dashboard", () => {
  it("shows provisioned against clients, the plan and its headroom", async () => {
    renderAdminPage(<WorkspacesSummaryPanel access={ALLOWED} />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      [WORKSPACE_PATHS.summary]: summary(),
    });
    expect(await screen.findByText("6 of 8 clients")).toBeTruthy();
    expect(screen.getByText(/Growth — 7 of 10 customers used/)).toBeTruthy();
    expect(screen.getByText("active: 6, plan_limit: 1, failed: 1")).toBeTruthy();
    expect(screen.queryByText("The plan is nearly full")).toBeNull();
  });

  it.each([
    [1, /One customer workspace is left/],
    [0, /No customer workspace is left/],
  ])("warns when the headroom is %i", async (headroom, sentence) => {
    renderAdminPage(<WorkspacesSummaryPanel access={ALLOWED} />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      [WORKSPACE_PATHS.summary]: summary({ headroom, counted: 10 - headroom }),
    });
    expect(await screen.findByText("The plan is nearly full")).toBeTruthy();
    expect(screen.getByText(sentence)).toBeTruthy();
  });

  it("links each failure to that client's admin page", async () => {
    renderAdminPage(<WorkspacesSummaryPanel access={ALLOWED} />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      [WORKSPACE_PATHS.summary]: summary({
        failures: [
          { tenant_id: TENANT, tenant_name: "Console Clinic", status: "plan_limit", last_error_code: "engine_plan_customer_limit" },
        ],
      }),
    });
    const link = await screen.findByRole("link", { name: "Console Clinic" });
    expect(link.getAttribute("href")).toBe(`/admin/tenants/${TENANT}/numbers`);
    expect(screen.getByText("engine_plan_customer_limit")).toBeTruthy();
  });

  it("asks nothing without the permission, and renders nothing on an engine without workspaces", async () => {
    const refused = renderAdminPage(<WorkspacesSummaryPanel access={{ allowed: false, reason: null }} />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
    });
    expect(refused.calls.some((call) => call.path === WORKSPACE_PATHS.summary)).toBe(false);
    refused.unmount();

    const { calls } = renderAdminPage(<WorkspacesSummaryPanel access={ALLOWED} />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      [WORKSPACE_PATHS.summary]: summary({ available: false }),
    });
    await waitFor(() => expect(calls.some((call) => call.path === WORKSPACE_PATHS.summary)).toBe(true));
    await waitFor(() => expect(screen.queryByText("Client voice workspaces")).toBeNull());
  });
});
