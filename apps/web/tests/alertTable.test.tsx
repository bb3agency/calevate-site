import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AlertsPage from "@/app/c/[slug]/settings/alerts/page";
import { DAILY_SUMMARY_PATH } from "@/lib/api/proof";
import { WHATSAPP_ALERTS_PATH } from "@/lib/api/whatsappAlerts";

import { ALERTS_PAGE_READS, alertPreferencesFixture } from "./fixtures/alertPreferences";
import { renderClientPage, type Routes } from "./harness";

/**
 * ALERTS YOU CAN SHAPE (D-1048): the table draws only the cells the server offers, an
 * always-on row has no box to untick, the account cells are read-only to anyone the server
 * says may not change them, and a save sends back exactly the cells left off.
 */

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage", "leads:read", "leads:write"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

function routes(over: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    [WHATSAPP_ALERTS_PATH]: {
      status: "none",
      channel: null,
      captured_at: null,
      notice_version: null,
      messageable: false,
      current_notice_version: "whatsapp-alerts-v1",
      current_notice_text: "I agree.",
      delivery_available: false,
      delivery_unavailable_reason: "Not ready.",
    },
    "/v1/team-alerts/contacts": { contacts: [], max_contacts: 10, whatsapp_accounts: [] },
    [DAILY_SUMMARY_PATH]: { enabled: false, slot: "evening", email_addresses: 1, whatsapp: false },
    ...ALERTS_PAGE_READS,
    ...over,
  };
}

describe("the alert table", () => {
  it("sends back the cells left off, and offers no box on an always-on row", async () => {
    const { calls } = await renderClientPage(
      <AlertsPage />,
      routes({ "PUT /v1/notifications/preferences": alertPreferencesFixture() }),
    );
    // The first row is the hot-lead row; its email box is the first "by Email".
    const [email] = await screen.findAllByRole("checkbox", { name: /by Email/ });
    expect(screen.queryByRole("checkbox", { name: /Low credit/ })).toBeNull();
    expect(screen.getAllByText("Always").length).toBeGreaterThan(0);
    fireEvent.click(email!);
    fireEvent.click(screen.getByRole("button", { name: /Save alerts/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    const body = JSON.parse(put?.body ?? "{}");
    expect(body.off).toEqual(["hot_lead:email"]);
    expect(body.daily_cap).toBe(12);
  });

  it("keeps the account cells read-only for someone who does not set them", async () => {
    await renderClientPage(
      <AlertsPage />,
      routes({
        "/v1/notifications/preferences": alertPreferencesFixture({
          governs_account: false,
          account_editable: false,
        }),
      }),
    );
    const boxes = await screen.findAllByRole("checkbox", { name: /by Email/ });
    expect(boxes.every((b) => (b as HTMLInputElement).disabled)).toBe(true);
    expect(screen.getByText(/set by the owner/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /sample WhatsApp/ })).toBeNull();
  });
});
