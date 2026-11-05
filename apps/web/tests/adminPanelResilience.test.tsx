import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH } from "@/app/admin/access";
import { PanelBoundary } from "@/app/admin/PanelBoundary";
import { BusinessCopyPanel, capabilityLine } from "@/app/admin/tenants/[tenantId]/BusinessCopyPanel";

import { NO_BUSINESS_COPY, renderAdminPage } from "./harness";

/**
 * A7-07: one panel's missing field took down a client's whole overview. An API older than
 * the web sent no capability profile, the panel read `capabilities[key]`, and the admin
 * error page replaced the screen.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const ME = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000cc",
  role: "operator",
  permissions: ["org:read"],
};

function Boom(): never {
  throw new Error("boom");
}

describe("a client overview panel", () => {
  it("reads a response with no capability profile as not judged", async () => {
    const { capabilities: _dropped, ...older } = {
      ...NO_BUSINESS_COPY,
      model: null,
      cost_inr: null,
      absorbed: false,
      last_trigger: null,
      last_attempt_at: null,
    };
    renderAdminPage(<BusinessCopyPanel tenantId={TENANT} />, {
      [ADMIN_ME_PATH]: ME,
      [`/v1/admin/tenants/${TENANT}/business-copy`]: older,
    });
    expect(await screen.findByText("Takes bookings")).toBeTruthy();
    expect(screen.getAllByText("Not judged yet").length).toBeGreaterThan(0);
    expect(capabilityLine(undefined)).toBe("Not judged yet");
  });

  it("keeps a crash inside the panel that crashed", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderAdminPage(
      <div>
        <PanelBoundary title="Business examples">
          <Boom />
        </PanelBoundary>
        <p>Neighbour still here</p>
      </div>,
      {},
    );
    expect(screen.getByText("Business examples could not be shown.")).toBeTruthy();
    expect(screen.getByText("Neighbour still here")).toBeTruthy();
  });
});
