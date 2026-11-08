import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import IntegrationsPage from "@/app/c/[slug]/integrations/page";

import { TEMPLATES, WHATSAPP_CONNECTED } from "./fixtures/whatsapp";
import { renderClientPage, type Routes } from "./harness";

/** Frontend audit lane W7 (8 Nov 2026): first agent, numbers, KYC, settings sub-pages. */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Lakshmi Traders", slug: "acme", status: "active" },
};

function integrationRoutes(over: Routes = {}): Routes {
  return {
    "/v1/me": OWNER,
    "/v1/integrations/credentials": [],
    "/v1/integrations/connections/status": {
      google_calendar: false,
      google_sheets: false,
      zoho_crm: false,
      hubspot: false,
    },
    "/v1/integrations/endpoints": [],
    "/v1/integrations/deliveries": [],
    "/v1/integrations/events": { events: ["lead.created"], sheets_delivery_available: false },
    "/v1/whatsapp": WHATSAPP_CONNECTED,
    "/v1/whatsapp/templates": TEMPLATES,
    ...over,
  };
}

describe("where results are sent, in the owner's words", () => {
  const sheet = {
    id: "e1",
    kind: "google_sheets",
    url: "https://docs.google.com/spreadsheets/d/abc",
    events: ["lead.created"],
    active: true,
    secret_fingerprint: "ready",
    include_recording_url: false,
    include_transcript: false,
    include_raw_transcript: false,
    created_at: "2026-08-01T10:00:00Z",
  };

  it("calls an empty list destinations, never endpoints", async () => {
    const { container } = await renderClientPage(<IntegrationsPage />, integrationRoutes());
    expect(await screen.findByText("No destinations yet.")).toBeTruthy();
    expect(container.textContent).not.toMatch(/endpoint/i);
  });

  it("does not promise a sheet a new signing secret when it is stopped", async () => {
    await renderClientPage(
      <IntegrationsPage />,
      integrationRoutes({ "/v1/integrations/endpoints": [sheet] }),
    );
    fireEvent.click(await screen.findByRole("button", { name: `Stop sending events to ${sheet.url}` }));
    const dialog = await screen.findByRole("dialog", { name: "Stop sending to this destination?" });
    expect(dialog.textContent).not.toContain("signing secret");
    expect(dialog.textContent).not.toMatch(/endpoint/i);
  });
});

describe("a template Meta turned down", () => {
  it("says what to change, never Meta's raw reason code", async () => {
    const { container } = await renderClientPage(<IntegrationsPage />, integrationRoutes());
    const rejected = (await screen.findByText("Rejected by Meta")).closest("li") as HTMLElement;
    fireEvent.click(within(rejected).getByRole("button", { name: "Read" }));
    expect(
      within(rejected).getByText(
        "Put words before the first blank and after the last, and number the blanks 1, 2, 3.",
      ),
    ).toBeTruthy();
    expect(container.textContent).not.toContain("INVALID_FORMAT");
  });
});
