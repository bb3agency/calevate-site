import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { BusinessDetailsPanel } from "@/app/admin/ops/BusinessDetailsPanel";
import TenantNumbersPage from "@/app/admin/tenants/[tenantId]/numbers/page";
import type { TenantSummary } from "@/lib/api/admin";
import { ENGINE_BUSINESS_DETAILS_PATH } from "@/lib/api/numbers";

import { renderAdminPage, type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * D-691: a number rented in the voice platform's own console is RECORDED here, from the
 * platform's own list, and the platform is then told which agent answers it.
 *
 * 1. A number not yet recorded offers "Record this number"; a recorded one says so.
 * 2. Recording sends only the number, what it is for and the agent — never a price or a
 *    handle, which the server reads from the platform.
 * 3. The server's price and attachment outcome are what the row reports.
 * 4. The ops page shows the platform's business-details application and flags a lapse.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000ef";
const AGENT = "0192f0aa-7777-7000-8000-000000000444";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const COSTS_PATH = `/v1/admin/numbers/tenants/${TENANT}`;
const ENGINE_PATH = `${COSTS_PATH}/engine`;
const RECORD_PATH = `${ENGINE_PATH}/record`;

const SUPERADMIN: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000cd",
  role: "superadmin",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

function routes(extra: Routes = {}): Routes {
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
      steps: ["Rent it in the ThinnestAI console."],
      notes: [],
      numbers: [
        {
          e164: "+918012345671",
          provider: null,
          engine_owned: true,
          agent_id: null,
          agent_name: null,
          unassigned: true,
          number_id: null,
        },
        {
          e164: "+918012345672",
          provider: null,
          engine_owned: true,
          agent_id: AGENT,
          agent_name: "Front desk",
          unassigned: false,
          number_id: "0192f0aa-7777-7000-8000-000000000555",
        },
      ],
      other_numbers: 0,
      agents: [
        { agent_id: AGENT, name: "Front desk", engine_agent_ref: "ag_1", answers_a_number: true },
      ],
    },
    "/v1/agents": [],
    ...extra,
  };
}

function render(extra: Routes = {}) {
  return renderAdminRoute(
    <TenantNumbersPage params={routeParams({ tenantId: TENANT })} />,
    routes(extra),
  );
}

describe("recording a number the voice platform holds", () => {
  it("offers to record only the numbers not yet recorded", async () => {
    await render();
    const recorded = (await screen.findByText("Recorded for this client.")).closest("li");
    const offered = screen.getAllByRole("button", { name: "Record this number" });
    expect(offered).toHaveLength(1);
    expect(recorded).not.toBeNull();
    expect(within(recorded as HTMLElement).queryByRole("button", { name: "Record this number" }))
      .toBeNull();
    expect(within(recorded as HTMLElement).getByText("Answered by Front desk")).toBeTruthy();
  });

  it("sends the number, its use and its agent, and reports the server's price", async () => {
    const calls: unknown[] = [];
    await render({
      [RECORD_PATH]: (call: { body: string | null }) => {
        calls.push(JSON.parse(call.body ?? "null"));
        return {
          number_id: "0192f0aa-7777-7000-8000-000000000666",
          e164: "+918012345671",
          series: "standard",
          client_inr_per_month: "499.00",
          platform_attachment: "applied",
        };
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Record this number" }));
    fireEvent.change(screen.getByLabelText("Agent"), { target: { value: AGENT } });
    fireEvent.change(screen.getByLabelText("Used for"), { target: { value: "inbound" } });
    fireEvent.click(screen.getByRole("button", { name: "Record" }));

    await waitFor(() =>
      expect(calls).toEqual([{ e164: "+918012345671", direction: "inbound", agent_id: AGENT }]),
    );
    expect(await screen.findByText(/Recorded\. Charged at ₹499(\.00)? a month from today\./))
      .toBeTruthy();
  });

  it("says when the platform did not take the attachment, and that a brought number is free", async () => {
    await render({
      [RECORD_PATH]: {
        number_id: "0192f0aa-7777-7000-8000-000000000777",
        e164: "+918012345671",
        series: "standard",
        client_inr_per_month: null,
        platform_attachment: "partial",
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Record this number" }));
    fireEvent.click(screen.getByRole("button", { name: "Record" }));

    expect(await screen.findByText(/there is no monthly charge/)).toBeTruthy();
    expect(screen.getByText(/did not take which agent answers it yet/)).toBeTruthy();
  });
});

describe("the voice platform's business details on the ops page", () => {
  it("shows a lapsed application with its review note", async () => {
    renderAdminPage(<BusinessDetailsPanel />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      [ENGINE_BUSINESS_DETAILS_PATH]: {
        available: true,
        platform: "ThinnestAI",
        status: "suspended",
        business_name: "Console Clinic LLP",
        can_rent: false,
        submitted_at: "2026-10-08T09:41:12Z",
        review_note: "Approval withdrawn after a complaint.",
        lapsed: true,
      },
    });

    expect(await screen.findByText("ThinnestAI business details")).toBeTruthy();
    expect(screen.getByText("Approval withdrawn")).toBeTruthy();
    expect(screen.getByText("Console Clinic LLP")).toBeTruthy();
    expect(screen.getByText(/No new number can be rented/)).toBeTruthy();
    expect(screen.getByText(/Approval withdrawn after a complaint\./)).toBeTruthy();
  });

  it("renders nothing where numbers are not the platform's", async () => {
    const { calls } = renderAdminPage(<BusinessDetailsPanel />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      [ENGINE_BUSINESS_DETAILS_PATH]: {
        available: false,
        platform: null,
        status: null,
        business_name: null,
        can_rent: false,
        submitted_at: null,
        review_note: null,
        lapsed: false,
      },
    });
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.queryByText(/business details/)).toBeNull());
  });
});
