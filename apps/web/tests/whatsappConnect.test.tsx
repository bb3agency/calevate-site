import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import WhatsAppAdminPage from "@/app/admin/ops/whatsapp/page";
import IntegrationsPage from "@/app/c/[slug]/integrations/page";
import { blankAtEdge, blanksInOrder } from "@/app/c/[slug]/integrations/whatsapp/Templates";
import { fillTemplate, templateNameFrom } from "@/lib/api/whatsapp";
import { isMetaOrigin, readSessionMessage } from "@/lib/facebookSignup";

import {
  ACCOUNT,
  ADMIN_WHATSAPP,
  TEMPLATES,
  WHATSAPP_CONNECTED,
  WHATSAPP_OFF,
  WHATSAPP_READY,
} from "./fixtures/whatsapp";
import { renderAdminPage, renderClientPage, type Routes } from "./harness";

// Meta's window runs on facebook.com; here it answers as if the owner finished it.
vi.mock("@/lib/facebookSignup", async (original) => ({
  ...(await original<typeof import("@/lib/facebookSignup")>()),
  runEmbeddedSignup: vi.fn(async () => ({
    kind: "finished",
    result: {
      code: "meta-code",
      event: "FINISH",
      waba_id: "1111",
      phone_number_id: "2222",
      business_id: "3333",
    },
  })),
}));

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Lakshmi Traders", slug: "acme", status: "active" },
};

const SIGNUP = {
  state: "state-1",
  app_id: "123456",
  config_id: "654321",
  graph_version: "v25.0",
  extras: { setup: {} },
};

function routes(over: Routes = {}): Routes {
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
    "/v1/whatsapp": WHATSAPP_OFF,
    ...over,
  };
}

describe("Meta's window messages", () => {
  it("are read only from facebook.com and its subdomains", () => {
    expect(isMetaOrigin("https://www.facebook.com")).toBe(true);
    expect(isMetaOrigin("https://facebook.com")).toBe(true);
    expect(isMetaOrigin("https://evilfacebook.com")).toBe(false);
    expect(isMetaOrigin("http://www.facebook.com")).toBe(false);
    const data = JSON.stringify({
      type: "WA_EMBEDDED_SIGNUP",
      event: "FINISH",
      data: { waba_id: "1", phone_number_id: "2", business_id: "3" },
    });
    expect(readSessionMessage("https://www.facebook.com", data)?.waba_id).toBe("1");
    expect(readSessionMessage("https://evilfacebook.com", data)).toBeNull();
    expect(readSessionMessage("https://www.facebook.com", "{not json")).toBeNull();
  });
});

describe("template rules the owner can fix before Meta sees them", () => {
  it("refuses a blank at either end and blanks out of order", () => {
    expect(blankAtEdge("{{1}}, your order is ready.")).toBe(true);
    expect(blankAtEdge("Your order is ready, {{1}}.")).toBe(true);
    expect(blankAtEdge("Your order is ready, {{1}}. Thank you.")).toBe(false);
    expect(blanksInOrder("Hi {{1}}, it is {{2}}.")).toBe(true);
    expect(blanksInOrder("Hi {{2}}.")).toBe(false);
  });

  it("names the template the way Meta accepts and previews it with the examples", () => {
    expect(templateNameFrom("Order ready!")).toBe("order_ready");
    expect(fillTemplate("Hi {{1}}, thank you.", ["Ravi"])).toBe("Hi Ravi, thank you.");
  });
});

describe("Integrations > WhatsApp", () => {
  it("shows the provider guides, not a dead button, until Meta is set up", async () => {
    await renderClientPage(<IntegrationsPage />, routes());
    expect(await screen.findByText("Connecting through Meta is not switched on yet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Connect WhatsApp" })).toBeNull();
    expect(screen.getByLabelText("Menu path: Manage, then API Key")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Interakt" }));
    expect(screen.getByLabelText("Menu path: Settings, then Developer Settings")).toBeTruthy();
  });

  it("asks how the business uses WhatsApp, and hides the Business app choice while coexistence is off", async () => {
    await renderClientPage(
      <IntegrationsPage />,
      routes({ "/v1/whatsapp": WHATSAPP_READY, "POST /v1/whatsapp/signup": SIGNUP }),
    );
    expect(await screen.findByText("I'm new to WhatsApp Business")).toBeTruthy();
    expect(screen.queryByText("I use the WhatsApp Business app and want to keep it")).toBeNull();
    fireEvent.click(screen.getByText("I'm new to WhatsApp Business"));
    expect(screen.getByText(/Meta charges you for each message; Calevate adds nothing/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "See Meta’s prices" }).getAttribute("href")).toContain(
      "developers.facebook.com",
    );
  });

  it("connects through Meta and shows the PIN once", async () => {
    const { calls } = await renderClientPage(
      <IntegrationsPage />,
      routes({
        "/v1/whatsapp": WHATSAPP_READY,
        "POST /v1/whatsapp/signup": SIGNUP,
        "POST /v1/whatsapp/connect": { account: ACCOUNT, pin: "482913", failed_step: null },
        "/v1/whatsapp/templates": TEMPLATES,
      }),
    );
    fireEvent.click(await screen.findByText("I'm new to WhatsApp Business"));
    const connectButton = screen.getByRole("button", { name: "Connect WhatsApp" });
    // Enabled once the state and Meta's SDK are prepared, so the click opens the window at once.
    await waitFor(() => expect(connectButton.hasAttribute("disabled")).toBe(false));
    fireEvent.click(connectButton);
    expect(await screen.findByText("482913")).toBeTruthy();
    const connect = calls.find((c) => c.path === "/v1/whatsapp/connect");
    await waitFor(() => expect(connect).toBeTruthy());
    expect(JSON.parse(connect?.body ?? "{}")).toMatchObject({ state: "state-1", code: "meta-code", waba_id: "1111" });
  });

  it("shows a connected number with its templates in words", async () => {
    await renderClientPage(
      <IntegrationsPage />,
      routes({ "/v1/whatsapp": WHATSAPP_CONNECTED, "/v1/whatsapp/templates": TEMPLATES }),
    );
    expect(await screen.findByText("Lakshmi Traders")).toBeTruthy();
    // The sign-in buttons carry a hidden "Connected" success face; the status pill is the one shown.
    expect(screen.getAllByText("Connected").filter((el) => !el.closest("[aria-hidden]"))).toHaveLength(1);
    expect(await screen.findByText("Payment link")).toBeTruthy();
    expect(screen.getAllByText("Approved").length).toBeGreaterThan(0);
    expect(screen.getByText("Rejected by Meta")).toBeTruthy();
  });
});

describe("Admin > Clients' WhatsApp", () => {
  it("counts this week's connections against Meta's limit", async () => {
    renderAdminPage(<WhatsAppAdminPage />, {
      "/v1/admin/whatsapp": ADMIN_WHATSAPP,
      "/v1/admin/me": {
        user_id: "admin-1",
        realm: "admin",
        role: "superadmin",
        permissions: ["admin:tenants"],
        impersonating: false,
      },
    });
    expect(await screen.findByText("of 10 used")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText(/Lakshmi Traders/, { selector: "p" })).toBeTruthy();
  });
});
