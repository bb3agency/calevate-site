import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TeamAlertsPanel } from "@/app/c/[slug]/agents/panels/teamAlerts";

import { renderClientPage, type ApiCall } from "./harness";
import { OWNER_ME, teamAlertReads } from "./fixtures/sharedReads";

/**
 * TELL MY TEAM (D-904): the owner adds a team address (confirmed by a code), and chooses when
 * this agent tells the team. WhatsApp is offered only when the account has its own WhatsApp
 * connected; otherwise one line says why it is not there.
 */

const AGENT = { id: "agent-1" };

function routes(overrides: Record<string, unknown> = {}) {
  return { "/v1/me": OWNER_ME, ...teamAlertReads(), ...overrides };
}

describe("Tell my team", () => {
  it("adds an email address and hides WhatsApp without the account's own connection", async () => {
    const reads = teamAlertReads();
    let added = false;
    const { calls } = await renderClientPage(<TeamAlertsPanel agent={AGENT} />, {
      ...routes(),
      "/v1/team-alerts/contacts": (call: ApiCall) => {
        if (call.method === "POST") added = true;
        return added
          ? {
              ...reads["/v1/team-alerts/contacts"],
              contacts: [
                {
                  id: "c1",
                  channel: "email",
                  address: "team@rytu.in",
                  is_default: true,
                  verified: false,
                  whatsapp_account_id: null,
                },
              ],
            }
          : reads["/v1/team-alerts/contacts"];
      },
    });
    expect(
      await screen.findByText("WhatsApp needs your own account."),
    ).toBeTruthy();
    expect(screen.queryByText("WhatsApp, from your own account")).toBeNull();
    expect(screen.getByText("Nothing is sent until an address is confirmed.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Team email"), { target: { value: "team@rytu.in" } });
    fireEvent.click(screen.getByRole("button", { name: "Add and send code" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ channel: "email", address: "team@rytu.in" });
    expect(await screen.findByText("Waiting for the code")).toBeTruthy();
  });

  it("offers WhatsApp when the account has its own connection", async () => {
    await renderClientPage(
      <TeamAlertsPanel agent={AGENT} />,
      routes({
        "/v1/team-alerts/contacts": {
          contacts: [],
          max_contacts: 10,
          whatsapp_accounts: [{ id: "w1", label: "Rytu WhatsApp" }],
        },
      }),
    );
    fireEvent.click(await screen.findByLabelText("WhatsApp, from your own account"));
    expect(screen.getByLabelText("Team WhatsApp number")).toBeTruthy();
    expect(screen.getByLabelText("Approved template")).toBeTruthy();
  });

  it("saves when the agent tells the team", async () => {
    const reads = teamAlertReads();
    const { calls } = await renderClientPage(
      <TeamAlertsPanel agent={AGENT} />,
      routes({
        "/v1/agents/agent-1/team-alert": (call: ApiCall) =>
          call.method === "PUT"
            ? { ...reads["/v1/agents/agent-1/team-alert"], in_call: true, on_outcomes: ["booked"] }
            : reads["/v1/agents/agent-1/team-alert"],
      }),
    );
    fireEvent.click(await screen.findByLabelText("Booked"));
    fireEvent.click(screen.getByLabelText(/Tell the team during the call, too/));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({
      contact_id: null,
      on_outcomes: ["booked"],
      on_fields: [],
      in_call: true,
    });
  });
});
