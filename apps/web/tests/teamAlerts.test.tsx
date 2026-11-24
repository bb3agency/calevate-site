import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TeamAlertsPanel } from "@/app/c/[slug]/agents/panels/teamAlerts";
import { FoldGroup } from "@/app/c/[slug]/campaigns/FoldSection";
import { JobAlerts } from "@/app/c/[slug]/campaigns/JobAlerts";
import { TeamList } from "@/app/c/[slug]/settings/alerts/TeamList";

import { problem, renderClientPage, stillLoading, type ApiCall } from "./harness";
import { OWNER_ME, jobTeamAlert, teamAlertReads } from "./fixtures/sharedReads";

/**
 * WHO HEARS ABOUT A CALL (D-904, D-967, D-1040): the team half of the one list on Settings →
 * Alerts (each address confirmed by a code); on an agent only its in-call switch and a link per
 * campaign and line; on each campaign and line exactly the ticked outcomes and its own answers,
 * positive outcomes ticked until the owner saves. WhatsApp is offered only when the account has
 * its own WhatsApp connected; otherwise one line says why it is not there.
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

  const WAITING = {
    contacts: [{ id: "c1", channel: "email", address: "team@rytu.in", verified: false, whatsapp_account_id: null }],
    max_contacts: 10,
    whatsapp_accounts: [],
  };

  it("shows Remove working while it removes, and takes no second press", async () => {
    const { calls } = await renderClientPage(
      list(),
      routes({ "/v1/team-alerts/contacts": WAITING, "DELETE /v1/team-alerts/contacts/c1": stillLoading() }),
    );
    const remove = await screen.findByRole("button", { name: "Remove" });
    fireEvent.click(remove);
    await waitFor(() => expect(remove.getAttribute("aria-busy")).toBe("true"));
    fireEvent.click(remove);
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
  });

  it("drops a wrong code's refusal once a new code is sent", async () => {
    await renderClientPage(
      list(),
      routes({
        "/v1/team-alerts/contacts": WAITING,
        "POST /v1/team-alerts/contacts/c1/verify": problem(422, { title: "That code is not right", detail: "Check the code and try again." }),
        "POST /v1/team-alerts/contacts/c1/code": WAITING,
      }),
    );
    fireEvent.change(await screen.findByLabelText("Code we sent there"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText(/Check the code and try again\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Send a new code" }));
    await waitFor(() => expect(screen.queryByText(/Check the code and try again\./)).toBeNull());
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


describe("an agent's alerts", () => {
  it("keeps only the in-call switch and links each campaign and line to its own alerts", async () => {
    const reads = teamAlertReads();
    const { calls } = await renderClientPage(
      <TeamAlertsPanel agent={AGENT} />,
      routes({
        "/v1/agents/agent-1/team-alert": (call: ApiCall) =>
          call.method === "PUT"
            ? { ...reads["/v1/agents/agent-1/team-alert"], in_call: true }
            : reads["/v1/agents/agent-1/team-alert"],
      }),
    );
    const inCall = (await screen.findByLabelText(/Message my team while the caller is on the line/)) as HTMLInputElement;
    expect(screen.getByText("Only you hear these. No one from your team yet.")).toBeTruthy();
    // No outcome or answer is ticked here: those are each job's own.
    expect(screen.queryByText(/after a call that ends with/)).toBeNull();
    expect(screen.queryByText(/after a call where/)).toBeNull();
    const campaign = screen.getByRole("link", { name: "Campaign Existing customers" });
    expect(campaign.getAttribute("href")).toBe("/c/acme/campaigns/camp-1#campaign-alerts");
    expect(screen.getByRole("link", { name: "Inbound line Front desk" }).getAttribute("href")).toBe(
      "/c/acme/inbound/line-1#line-alerts",
    );
    expect(screen.getByText(/If Varsha can.t help, your team gets the caller.s details/)).toBeTruthy();
    fireEvent.click(inCall);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ in_call: true });
  });
});

describe("a campaign's and a line's own alerts", () => {
  it("ticks the positive outcome, offers its own answers once, and saves exactly what is ticked", async () => {
    const path = "/v1/campaigns/camp-1/team-alert";
    const { calls } = await renderClientPage(
      <FoldGroup>
        <JobAlerts kind="campaign" jobId="camp-1" />
      </FoldGroup>,
      routes({
        [path]: (call: ApiCall) =>
          call.method === "PUT"
            ? { ...jobTeamAlert("campaign", "camp-1"), saved: true, on_outcomes: ["booked"] }
            : jobTeamAlert("campaign", "camp-1"),
      }),
    );
    const goal = (await screen.findByLabelText(/Ready to buy/)) as HTMLInputElement;
    expect(goal.checked).toBe(true);
    expect(screen.getByText("Tell me after a call that ends with")).toBeTruthy();
    expect(screen.getAllByLabelText("Stuck")).toHaveLength(1);
    expect(screen.queryByLabelText(/Message my team while the caller is on the line/)).toBeNull();
    fireEvent.click(goal);
    fireEvent.click(screen.getByLabelText("Booked"));
    fireEvent.click(screen.getByLabelText("Stuck"));
    fireEvent.click(screen.getByRole("button", { name: "Save alerts" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe(path);
    expect(JSON.parse(put?.body ?? "{}")).toEqual({
      on_outcomes: ["booked"],
      on_fields: [{ key: "setup", values: ["Stuck"] }],
    });
  });

  it("saves a line's alerts to the line", async () => {
    const path = "/v1/inbound-lines/line-1/team-alert";
    const { calls } = await renderClientPage(
      <FoldGroup>
        <JobAlerts kind="line" jobId="line-1" />
      </FoldGroup>,
      routes({ [path]: () => jobTeamAlert("line", "line-1") }),
    );
    fireEvent.click(await screen.findByLabelText("Done"));
    fireEvent.click(screen.getByRole("button", { name: "Save alerts" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.path).toBe(path);
  });
});
