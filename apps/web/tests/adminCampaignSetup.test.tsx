import { cleanup, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantCampaignSetupPage from "@/app/admin/tenants/[tenantId]/campaign-setup/page";
import type { TenantSummary } from "@/lib/api/admin";
import type { Routes } from "./harness";

import { problem } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * Campaign setup, on its own Compliance route (D-661) — the registrar's verdicts on a
 * client's numbers and templates and their DLT entity registration. These cases moved
 * with the panel from the client Overview (`adminTenantDetail.test.tsx`).
 *
 * What they pin is what an operator must never be told by a failed read: "No numbers on
 * file" sends a client to buy a second connection, and "No templates registered" sends an
 * operator to file a template the registrar already holds under the same PE.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const NUMBERS_PATH = "/v1/campaigns/numbers";
const TEMPLATES_PATH = "/v1/campaigns/templates";

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 2,
    calls_7d: 412,
    leads: 96,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-7777-7000-8000-0000000000cc",
    role: "operator",
    permissions,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantCampaignSetupPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: me(["org:read", "admin:tenants"]),
    [NUMBERS_PATH]: [],
    [TEMPLATES_PATH]: [],
    ...routes,
  });
}

describe("campaign setup", () => {
  it("does not report a client as having no numbers when the numbers could not be read", async () => {
    const { container } = await render({
      [NUMBERS_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this client's numbers.",
        retryable: true,
      }),
    });
    await screen.findByText("We could not read this client's numbers.");
    expect(container.textContent).not.toContain("No numbers on file");
  });

  it("does not report an empty template list when the templates could not be read", async () => {
    const { container } = await render({
      [TEMPLATES_PATH]: problem(500, {
        title: "Upstream unavailable",
        detail: "We could not read this client's DLT templates.",
        retryable: true,
      }),
    });
    await screen.findByText("We could not read this client's DLT templates.");
    expect(container.textContent).not.toContain("No templates registered");
  });

  it("says an empty list is empty when the SERVER says so", async () => {
    const { container } = await render();
    await screen.findByText("No numbers on file.");
    expect(container.textContent).toContain("No templates registered.");
  });

  it("disables every write with its reason when the session lacks admin:tenants", async () => {
    await render({
      [ADMIN_ME_PATH]: me(["org:read"]),
      [NUMBERS_PATH]: [{ id: "n-1", e164: "+918041234567", series: "160", dlt_status: "pending" }],
      [TEMPLATES_PATH]: [
        { id: "t-1", classification: "service", status: "submitted", body: "Namaste…" },
      ],
    });
    await screen.findAllByText(/does not have permission to/);
    for (const name of ["Mark registered", "Registrar approved", "Register template", "Record registration"]) {
      const button = await screen.findByRole("button", { name });
      expect((button as HTMLButtonElement).disabled, `${name} must be disabled`).toBe(true);
    }
  });

  it("files the DLT registration date as IST, whatever zone the operator is in", async () => {
    const dltPath = `${TENANT_PATH}/dlt-registration`;
    const originalTz = process.env.TZ;
    try {
      for (const zone of ["UTC", "America/Los_Angeles", "Pacific/Auckland"]) {
        cleanup();
        process.env.TZ = zone;
        const { calls } = await render({
          [`POST ${dltPath}`]: { status: "active", tm_link_status: "linked" },
        });
        fireEvent.change(await screen.findByLabelText("Registered on (IST)"), {
          target: { value: "2026-08-10" },
        });
        // Every admin control is disabled until `/v1/admin/me` answers (it fails CLOSED).
        const submit = screen.getByRole("button", { name: "Record registration" }) as HTMLButtonElement;
        await vi.waitFor(() => expect(submit.disabled).toBe(false));
        fireEvent.click(submit);
        await vi.waitFor(() => {
          expect(calls.some((c) => c.method === "POST" && c.path === dltPath)).toBe(true);
        });
        const body = JSON.parse(
          calls.find((c) => c.method === "POST" && c.path === dltPath)?.body ?? "{}",
        );
        // Midnight IST on the picked day is 18:30Z the day before.
        expect(body.registered_at, `registered_at in ${zone}`).toBe("2026-08-09T18:30:00.000Z");
      }
    } finally {
      if (originalTz === undefined) delete process.env.TZ;
      else process.env.TZ = originalTz;
    }
  });
});
