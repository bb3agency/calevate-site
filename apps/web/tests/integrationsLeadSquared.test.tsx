import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import IntegrationsPage from "@/app/c/[slug]/integrations/page";

import { problem, renderClientPage, type Routes } from "./harness";
import { WHATSAPP_OFF_ROUTES } from "./fixtures/whatsapp";

/**
 * LeadSquared as a destination (D-942): the keys and the destination in one form.
 *
 * Pinned here: the form sends exactly the three pasted values plus the events its one
 * optional field implies (a call result needs a field to land in), a refusal keeps the
 * form with the server's words, and the keys never reach the page after the save.
 */

const LSQ_PATH = "/v1/integrations/endpoints/leadsquared";

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Estates", slug: "acme", status: "active" },
};

function render(over: Partial<Routes> = {}) {
  return renderClientPage(<IntegrationsPage />, {
    "/v1/me": OWNER,
    "/v1/integrations/credentials": [],
    ...WHATSAPP_OFF_ROUTES,
    "/v1/integrations/connections/status": {
      google_calendar: false,
      google_sheets: false,
      zoho_crm: false,
      hubspot: false,
    },
    "/v1/integrations/endpoints": [],
    "/v1/integrations/deliveries": [],
    "/v1/integrations/events": {
      events: ["lead.created", "lead.updated", "call.completed", "campaign.completed"],
      sheets_delivery_available: false,
    },
    ...over,
  });
}

async function openLeadSquared(): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: "Add destination" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("radio", { name: /LeadSquared/ }));
  return dialog;
}

function fill(dialog: HTMLElement, outcomeField = ""): void {
  fireEvent.change(within(dialog).getByLabelText("API host"), {
    target: { value: "api-in21.leadsquared.com" },
  });
  fireEvent.change(within(dialog).getByLabelText("LeadSquared access key"), {
    target: { value: "u$access" },
  });
  fireEvent.change(within(dialog).getByLabelText("LeadSquared secret key"), {
    target: { value: "secret-value" },
  });
  if (outcomeField) {
    fireEvent.change(within(dialog).getByLabelText(/Field for call results/), {
      target: { value: outcomeField },
    });
  }
}

const CREATED = {
  id: "0192f0aa-5555-7000-8000-000000000001",
  kind: "leadsquared",
  api_host: "api-in21.leadsquared.com",
  events: ["lead.created"],
  fields: {},
  active: true,
};

describe("connecting LeadSquared", () => {
  it("sends new leads only when no call-result field is named", async () => {
    const { calls } = await render({ [LSQ_PATH]: CREATED });
    const dialog = await openLeadSquared();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Connect LeadSquared" }));

    await waitFor(() => expect(calls.some((c) => c.path === LSQ_PATH)).toBe(true));
    expect(JSON.parse(calls.find((c) => c.path === LSQ_PATH)!.body!)).toEqual({
      api_host: "api-in21.leadsquared.com",
      access_key: "u$access",
      secret_key: "secret-value",
      events: ["lead.created"],
      fields: {},
    });
    await screen.findByText("LeadSquared connected");
    expect(document.body.textContent).not.toContain("secret-value");
  });

  it("adds call results only with the field they are written to", async () => {
    const { calls } = await render({ [LSQ_PATH]: CREATED });
    const dialog = await openLeadSquared();
    fill(dialog, "mx_Call_Outcome");
    fireEvent.click(within(dialog).getByRole("button", { name: "Connect LeadSquared" }));

    await waitFor(() => expect(calls.some((c) => c.path === LSQ_PATH)).toBe(true));
    const sent = JSON.parse(calls.find((c) => c.path === LSQ_PATH)!.body!);
    expect(sent.events).toEqual(["lead.created", "call.completed"]);
    expect(sent.fields).toEqual({ mx_Call_Outcome: "outcome" });
  });

  it("keeps the form and shows the server's words when the host is refused", async () => {
    await render({
      [LSQ_PATH]: problem(422, {
        type: "https://calevate.tech/problems/leadsquared_host_unknown",
        title: "That is not a LeadSquared API host",
        detail: "Use the API host LeadSquared shows for your account.",
      }),
    });
    const dialog = await openLeadSquared();
    fill(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Connect LeadSquared" }));

    expect(await screen.findByText(/Use the API host LeadSquared shows/)).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Connect LeadSquared" })).toBeTruthy();
  });

  it("lists a LeadSquared destination without a signing-secret button", async () => {
    await render({
      "/v1/integrations/endpoints": [
        {
          id: CREATED.id,
          kind: "leadsquared",
          url: "https://api-in21.leadsquared.com",
          events: ["lead.created"],
          active: true,
          secret_fingerprint: "abcd1234",
          include_recording_url: false,
          include_transcript: false,
          include_raw_transcript: false,
          created_at: "2026-10-30T09:00:00Z",
          previous_secret_expires_at: null,
        },
      ],
    });
    expect(await screen.findByText("LeadSquared keys saved")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /New signing secret/ })).toBeNull();
  });
});
