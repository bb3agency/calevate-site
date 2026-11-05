import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantCampaignsPage from "@/app/admin/tenants/[tenantId]/campaigns/page";
import { actOutcome } from "@/app/admin/tenants/[tenantId]/campaigns/CampaignsScreen";
import { TENANT_SECTIONS } from "@/app/admin/tenants/[tenantId]/tenantSections";
import type { TenantSummary } from "@/lib/api/admin";
import type { Routes } from "./harness";

import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * An operator's campaign archive / restore / delete (F-10): the buttons call the admin
 * routes with the per-campaign confirmation, the reason is required, and the screen says
 * whether the client was told.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const LIVE = "/v1/campaigns/page?limit=100";
const ARCHIVED = "/v1/campaigns/page?limit=100&archived=true";
const DRAFT = "0192f0aa-7777-7000-8000-0000000000d1";
const RUNNING = "0192f0aa-7777-7000-8000-0000000000d2";

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "general",
    live_agents: 1,
    calls_7d: 4,
    leads: 1,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

function me(permissions: string[]): AdminMe {
  return { realm: "admin", user_id: "0192f0aa-7777-7000-8000-0000000000cc", role: "operator", permissions };
}

function campaign(id: string, name: string, status: string, archivedAt: string | null = null) {
  return {
    id,
    name,
    classification: "service",
    status,
    contacts: 10,
    connected: 0,
    launched_at: status === "draft" ? null : "2026-11-01T05:00:00Z",
    created_at: "2026-11-01T04:00:00Z",
    archived_at: archivedAt,
  };
}

function page(items: unknown[], archivedTotal = 0) {
  return { items, total: items.length, status_counts: {}, archived_total: archivedTotal };
}

function render(routes: Partial<Routes> = {}, permissions = ["org:read", "admin:tenants"]) {
  return renderAdminRoute(<TenantCampaignsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: me(permissions),
    [LIVE]: page([campaign(DRAFT, "Spring draft", "draft"), campaign(RUNNING, "Renewals", "running")], 1),
    [ARCHIVED]: page([campaign(RUNNING, "Old list", "paused", "2026-11-02T05:00:00Z")]),
    ...routes,
  });
}

describe("admin campaigns", () => {
  it("is a section of the client's pages", () => {
    expect(TENANT_SECTIONS.map((s) => s.path)).toContain("/campaigns");
  });

  it("archives with a required reason and the per-campaign confirmation, and says the client was told", async () => {
    const path = `POST ${TENANT_PATH}/campaigns/${RUNNING}/archive`;
    const { calls } = await render({
      [path]: { changed: true, status: "paused", client_notified: true },
    });
    const rows = await screen.findAllByRole("button", { name: "Archive" });
    fireEvent.click(rows[1]);
    const confirm = await screen.findByRole("button", { name: "Archive it" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Client asked us to stop" } });
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(confirm);
    await screen.findByText("Archived. The client was told.");
    const call = calls.find((c) => `${c.method} ${c.path}` === path);
    expect(call).toBeDefined();
    expect(JSON.parse(call!.body ?? "{}")).toEqual({ reason: "Client asked us to stop" });
    expect(call!.headers["X-Confirm-Action"]).toBe(`archive_campaign:${RUNNING}`);
  });

  it("offers delete only on a draft that never called, with its own confirmation", async () => {
    const path = `DELETE ${TENANT_PATH}/campaigns/${DRAFT}`;
    const { calls } = await render({
      [path]: { changed: true, status: "deleted", client_notified: true },
    });
    const deletes = await screen.findAllByRole("button", { name: "Delete" });
    expect(deletes).toHaveLength(1);
    fireEvent.click(deletes[0]);
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "Duplicate draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete it" }));
    await screen.findByText("Deleted. The client was told.");
    const call = calls.find((c) => `${c.method} ${c.path}` === path);
    expect(call!.headers["X-Confirm-Action"]).toBe(`delete_campaign:${DRAFT}`);
  });

  it("restores from the archived list and says no notice was sent", async () => {
    await render({
      [`POST ${TENANT_PATH}/campaigns/${RUNNING}/restore`]: {
        changed: true,
        status: "paused",
        client_notified: false,
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Archived (1)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Restore" }));
    await screen.findByText("Restored as paused. The client was not sent a notice.");
  });

  it("disables every write without admin:tenants", async () => {
    await render({}, ["org:read"]);
    await screen.findAllByText(/does not have permission to/);
    for (const button of await screen.findAllByRole("button", { name: /^(Archive|Delete)$/ })) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("says nothing changed when the campaign was already archived", () => {
    expect(actOutcome("archive", { changed: false, status: "paused", client_notified: false })).toBe(
      "Already archived. Nothing changed.",
    );
  });
});

