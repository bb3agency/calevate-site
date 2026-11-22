import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TeamAlertsPanel } from "@/app/c/[slug]/agents/panels/teamAlerts";
import { CampaignNotes } from "@/app/c/[slug]/campaigns/CampaignNotes";
import { TeamList } from "@/app/c/[slug]/settings/alerts/TeamList";

import { FIXTURE_AGENT_ID, FIXTURE_CAMPAIGN_ID, notesFixture } from "./campaignFixtures";
import { renderClientPage, type ApiCall } from "./harness";
import { OWNER_ME, teamAlertReads } from "./fixtures/sharedReads";

/**
 * WHO HEARS ABOUT A CALL (D-904, D-967): the team half of the one list on Settings → Alerts
 * (each address confirmed by a code), and on an agent only WHEN: exactly the ticked outcomes,
 * positive ones ticked until the owner saves. WhatsApp is offered only when the account has its own WhatsApp
 * connected; otherwise one line says why it is not there.
 */

const AGENT = { id: "agent-1", name: "Varsha" };

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

describe("what an agent tells the list about", () => {
  it("ticks the positive outcome, lets the owner untick it, and saves exactly what is ticked", async () => {
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
    const goal = (await screen.findByLabelText(/Ready to buy/)) as HTMLInputElement;
    expect(goal.checked).toBe(true);
    expect(goal.disabled).toBe(false);
    expect(screen.queryByText(/Hot lead/)).toBeNull();
    expect(screen.getByText("Only you hear these. No one from your team yet.")).toBeTruthy();
    expect(screen.getByText("Tell me after a call that ends with")).toBeTruthy();
    fireEvent.click(goal);
    fireEvent.click(screen.getByLabelText("Booked"));
    const inCall = screen.getByLabelText(/Message my team while the caller is on the line/);
    expect(inCall.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText(/If Varsha can.t help, your team gets the caller.s details/)).toBeTruthy();
    fireEvent.click(inCall);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({
      on_outcomes: ["booked"],
      on_fields: [],
      in_call: true,
    });
  });

  it("offers a campaign's own answers under its name and saves them as that campaign's", async () => {
    const reads = teamAlertReads();
    const rule = {
      ...reads["/v1/agents/agent-1/team-alert"],
      fields: [{ key: "visit_day", label: "Visit day", values: ["Saturday", "Sunday"], positive: false, goal: false }],
      holders: [
        {
          kind: "campaign" as const,
          id: "camp-1",
          name: "Site visits",
          fields: [{ key: "visit_day", label: "Visit day", values: ["Saturday", "Sunday"], positive: false, goal: false }],
        },
      ],
    };
    const { calls } = await renderClientPage(
      <TeamAlertsPanel agent={AGENT} />,
      routes({ "/v1/agents/agent-1/team-alert": () => rule }),
    );
    const campaign = await screen.findByRole("region", { name: "Campaign Site visits" });
    expect(campaign.textContent).toContain("Its own calls only.");
    // The agent's own "Visit day" and the campaign's are two separate ticks.
    expect(screen.getAllByLabelText("Saturday")).toHaveLength(2);
    fireEvent.click(within(campaign).getByLabelText("Saturday"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}").on_fields).toEqual([
      { key: "visit_day", values: ["Saturday"], campaign_id: "camp-1" },
    ]);
  });
});

describe("a campaign's What it notes", () => {
  const notesPath = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}/notes`;
  const render = (notes: ReturnType<typeof notesFixture>) =>
    renderClientPage(
      <CampaignNotes slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} canWrite />,
      routes({ [notesPath]: notes }),
    );

  it("links its own list to its agent's alerts", async () => {
    const field: ReturnType<typeof notesFixture>["fields"][number] = {
      key: "visit_day",
      label: "Visit day",
      type: "enum",
      enum_values: ["Saturday"],
      reason: "when",
      required: false,
    };
    await render(notesFixture({ fields: [field] }));
    const link = await screen.findByRole("link", { name: "Set alerts" });
    expect(link.getAttribute("href")).toBe(`/c/acme/agents/${FIXTURE_AGENT_ID}?section=settings#team-alerts`);
  });

});
