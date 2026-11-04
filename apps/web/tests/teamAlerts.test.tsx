import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TeamAlertsPanel } from "@/app/c/[slug]/agents/panels/teamAlerts";
import { TeamList } from "@/app/c/[slug]/settings/alerts/TeamList";

import { renderClientPage, type ApiCall } from "./harness";
import { OWNER_ME, teamAlertReads } from "./fixtures/sharedReads";

/**
 * WHO HEARS ABOUT HOT LEADS (D-904, D-967): the team half of the one list on Settings → Alerts
 * (each address confirmed by a code), and on an agent only WHEN: a hot outcome always counts,
 * the owner may add more. WhatsApp is offered only when the account has its own WhatsApp
 * connected; otherwise one line says why it is not there.
 */

const AGENT = { id: "agent-1" };

function routes(overrides: Record<string, unknown> = {}) {
  return { "/v1/me": OWNER_ME, ...teamAlertReads(), ...overrides };
}

function list() {
  return (
    <ul>
      <TeamList canWrite reason={null} />
    </ul>
  );
}

describe("the team on the hot-lead list", () => {
  it("adds an email address and hides WhatsApp without the account's own connection", async () => {
    const reads = teamAlertReads();
    let added = false;
    const { calls } = await renderClientPage(list(), {
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
                  verified: false,
                  whatsapp_account_id: null,
                },
              ],
            }
          : reads["/v1/team-alerts/contacts"];
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Add someone from your team" }));
    expect(screen.getByText("WhatsApp needs your own account.")).toBeTruthy();
    expect(screen.queryByText("WhatsApp, from your own account")).toBeNull();

    fireEvent.change(screen.getByLabelText("Their email"), { target: { value: "team@rytu.in" } });
    fireEvent.click(screen.getByRole("button", { name: "Add and send code" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ channel: "email", address: "team@rytu.in" });
    expect(await screen.findByText(/Waiting for the code/)).toBeTruthy();
  });

  it("offers WhatsApp when the account has its own connection", async () => {
    await renderClientPage(
      list(),
      routes({
        "/v1/team-alerts/contacts": {
          contacts: [],
          max_contacts: 10,
          whatsapp_accounts: [{ id: "w1", label: "Rytu WhatsApp" }],
        },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add someone from your team" }));
    fireEvent.click(screen.getByLabelText("WhatsApp, from your own account"));
    expect(screen.getByLabelText("Their WhatsApp number")).toBeTruthy();
    expect(screen.getByLabelText("Approved template")).toBeTruthy();
  });
});

describe("what an agent tells the hot-lead list about", () => {
  it("keeps a hot outcome ticked and saves what the owner adds", async () => {
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
    const hot = (await screen.findByLabelText(/Ready to buy/)) as HTMLInputElement;
    expect(hot.checked && hot.disabled).toBe(true);
    expect(screen.getByText("You hear about these. No team yet.")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Booked"));
    fireEvent.click(screen.getByLabelText(/Tell the team during the call, too/));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({
      on_outcomes: ["booked"],
      on_fields: [],
      in_call: true,
    });
  });
});
