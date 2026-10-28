import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import IntegrationsPage from "@/app/c/[slug]/integrations/page";
import type { Delivery, Endpoint } from "@/lib/api/integrations";
import { familiesFor } from "@/lib/live/topics";

import { renderClientPage } from "./harness";
import { WHATSAPP_OFF_ROUTES } from "./fixtures/whatsapp";

/**
 * A delivery that finally failed can be sent again, a retrying one says when it is tried
 * next, and a webhook's signing secret is replaced in place with the new one shown once.
 */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "calls:read", "leads:read", "org:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Traders", slug: "acme", status: "active" },
};
const STAFF = { ...OWNER, role: "staff", permissions: ["agents:read", "calls:read", "org:read"] };

const ENDPOINT: Endpoint = {
  id: "e1",
  kind: "webhook",
  url: "https://crm.example/hook",
  events: ["lead.created"],
  active: true,
  secret_fingerprint: "abc12345",
  include_recording_url: false,
  include_transcript: false,
  include_raw_transcript: false,
  created_at: "2026-10-01T10:00:00Z",
  previous_secret_expires_at: null,
};

function delivery(over: Partial<Delivery> = {}): Delivery {
  return {
    id: "d1",
    event_type: "lead.created",
    status: "failed",
    attempts: 8,
    first_at: "2026-10-25T10:00:00Z",
    last_at: "2026-10-26T10:00:00Z",
    payload_stored: false,
    next_attempt_at: null,
    resendable: true,
    ...over,
  };
}

function routes(me: unknown, deliveries: Delivery[], over: Record<string, unknown> = {}) {
  return {
    "/v1/me": me,
    "/v1/integrations/credentials": [],
    ...WHATSAPP_OFF_ROUTES,
    "/v1/integrations/connections/status": {
      google_calendar: false,
      zoho_crm: false,
      hubspot: false,
      sheets_share_with: null,
    },
    "/v1/integrations/endpoints": [ENDPOINT],
    "/v1/integrations/events": { events: ["lead.created"], sheets_delivery_available: false },
    "/v1/integrations/deliveries": deliveries,
    ...over,
  };
}

const page = <IntegrationsPage />;

describe("a delivery that finally failed", () => {
  it("can be sent again by someone who manages integrations", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(OWNER, [delivery()], { "POST /v1/integrations/deliveries/d1/resend": { id: "d1", status: "retrying" } }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Send this .* again/ }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/deliveries/d1/resend"))).toBe(
        true,
      ),
    );
  });

  it("is not offered to a reader who cannot change integrations", async () => {
    await renderClientPage(page, routes(STAFF, [delivery()]));
    expect(await screen.findByText("failed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Send this .* again/ })).toBeNull();
  });

  it("is not offered once the server says it cannot be sent", async () => {
    await renderClientPage(page, routes(OWNER, [delivery({ resendable: false })]));
    expect(await screen.findByText("failed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Send this .* again/ })).toBeNull();
  });
});

describe("a delivery waiting for its next attempt", () => {
  it("says when it is tried next", async () => {
    await renderClientPage(
      page,
      routes(OWNER, [
        delivery({ status: "retrying", attempts: 2, resendable: false, next_attempt_at: "2026-10-26T10:05:00Z" }),
      ]),
    );
    expect(await screen.findByText(/next try/)).toBeTruthy();
  });
});

describe("a new signing secret", () => {
  it("is issued after a confirmation and shown once with the old secret's deadline", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(OWNER, [], {
        "POST /v1/integrations/endpoints/e1/rotate-secret": {
          id: "e1",
          secret: "whsec_brand_new",
          secret_fingerprint: "def67890",
          previous_secret_expires_at: "2026-10-27T10:00:00Z",
        },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /New signing secret for/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Issue a new secret" }));

    expect(await screen.findByText("whsec_brand_new")).toBeTruthy();
    expect(screen.getByText(/Old secret works until/)).toBeTruthy();
    const rotation = calls.find((c) => c.path.endsWith("/endpoints/e1/rotate-secret"));
    expect(rotation?.method).toBe("POST");
  });
});

describe("live notes about integrations", () => {
  // `webhook_deliveries` announces `integrations`, and a failed delivery is an attention item.
  it("refresh the attention queue and the bell", () => {
    const families = familiesFor(["integrations"]);
    expect(families).toContain("attention");
    expect(families).toContain("notifications");
  });
});
