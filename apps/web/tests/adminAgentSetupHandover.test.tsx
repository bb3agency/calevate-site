import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentSetupHandover } from "@/app/admin/tenants/[tenantId]/numbers/AgentSetupHandover";
import type { TenantSummary } from "@/lib/api/admin";
import { WORKSPACE_PATHS, type AgentEngineRetirementRun } from "@/lib/api/engineWorkspaces";

import { problem, renderAdminPage, type ApiCall, type Routes } from "./harness";

/**
 * D-1019: an operator hands a client's agents' own engine agents to the lines and campaigns
 * that use them, from the client's voice workspace panel.
 *
 * - A dry run lists each agent with its outcome in plain words and the tests it would end.
 * - "Run it" exists only after a dry run, behind a confirm naming the client, and sends
 *   `dry_run: false` with the step-up header.
 * - A refusal is shown, the platform-setting one in its own words.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000001a1";
const AGENT_LINE = "0192f0aa-7777-7000-8000-0000000001b1";
const AGENT_CAMPAIGN = "0192f0aa-7777-7000-8000-0000000001b2";
const AGENT_UNUSED = "0192f0aa-7777-7000-8000-0000000001b3";
const AGENT_HELD = "0192f0aa-7777-7000-8000-0000000001b4";
const AGENT_WAITING = "0192f0aa-7777-7000-8000-0000000001b5";
const LINE = "0192f0aa-7777-7000-8000-0000000001c1";
const CAMPAIGN = "0192f0aa-7777-7000-8000-0000000001d1";
const EXPERIMENT = "0192f0aa-7777-7000-8000-0000000001e1";
const PATH = WORKSPACE_PATHS.agentEngineRetirement(TENANT);

const TENANT_SUMMARY: TenantSummary = {
  id: TENANT,
  name: "Sri Traders",
  slug: "sri-traders",
  status: "active",
  plan_tier: "prepaid",
  vertical_template: "retail",
  live_agents: 5,
  calls_7d: 0,
  leads: 0,
  last_call_at: null,
  holds: [],
  capped: false,
};

function runOut(dryRun: boolean): AgentEngineRetirementRun {
  return {
    tenant_id: TENANT,
    dry_run: dryRun,
    agents: [
      {
        agent_id: AGENT_LINE,
        outcome: "adopted_line",
        holder_id: LINE,
        reason: null,
        experiments_concluded: [EXPERIMENT],
      },
      {
        agent_id: AGENT_CAMPAIGN,
        outcome: "adopted_campaign",
        holder_id: CAMPAIGN,
        reason: null,
        experiments_concluded: [],
      },
      { agent_id: AGENT_UNUSED, outcome: "retired", holder_id: null, reason: null, experiments_concluded: [] },
      {
        agent_id: AGENT_HELD,
        outcome: "held",
        holder_id: null,
        reason: "several_uses",
        experiments_concluded: [],
      },
      {
        agent_id: AGENT_WAITING,
        outcome: "waiting",
        holder_id: null,
        reason: "platform_maintenance",
        experiments_concluded: [],
      },
    ],
  };
}

const agent = (id: string, name: string) => ({ id, name });

function routes(real: unknown = runOut(false)): Routes {
  return {
    [`/v1/admin/tenants/${TENANT}`]: TENANT_SUMMARY,
    "/v1/agents": [
      agent(AGENT_LINE, "Front desk"),
      agent(AGENT_CAMPAIGN, "Renewals caller"),
      agent(AGENT_UNUSED, "Old greeter"),
      agent(AGENT_HELD, "Busy agent"),
      agent(AGENT_WAITING, "Patient agent"),
    ],
    "/v1/inbound-lines": { lines: [{ id: LINE, name: "Main number" }] },
    "/v1/campaigns": [{ id: CAMPAIGN, name: "Diwali offers" }],
    [`POST ${PATH}`]: (call: ApiCall) =>
      (JSON.parse(call.body ?? "{}") as { dry_run: boolean }).dry_run ? runOut(true) : real,
  };
}

function render(extra: Routes = {}, canWrite = true) {
  return renderAdminPage(<AgentSetupHandover tenantId={TENANT} canWrite={canWrite} />, {
    ...routes(),
    ...extra,
  });
}

function posts(calls: ApiCall[]) {
  return calls.filter((call) => call.method === "POST" && call.path === PATH);
}

describe("Hand agents' setups to their work", () => {
  it("offers no Run it before a dry run", async () => {
    render();
    expect((await screen.findByRole("button", { name: "Dry run" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: "Run it" })).toBeNull();
  });

  it("renders the dry run's plan in plain words", async () => {
    const { calls } = render();
    fireEvent.click(await screen.findByRole("button", { name: "Dry run" }));

    const table = await screen.findByRole("table", { name: "What a run would do, per agent" });
    expect(posts(calls).map((call) => JSON.parse(call.body ?? "{}"))).toEqual([{ dry_run: true }]);
    expect(posts(calls)[0].headers["X-Confirm-Action"]).toBeUndefined();

    const rowOf = (name: string) => within(table).getByText(name).closest("tr") as HTMLElement;
    await waitFor(() => expect(within(rowOf("Front desk")).getByText("Its line Main number takes over its setup")).toBeTruthy());
    expect(within(rowOf("Front desk")).getByText("Ends 1 running script test")).toBeTruthy();
    await waitFor(() =>
      expect(within(rowOf("Renewals caller")).getByText("Campaign Diwali offers takes over its setup")).toBeTruthy(),
    );
    expect(within(rowOf("Old greeter")).getByText("Setup removed")).toBeTruthy();
    expect(within(rowOf("Busy agent")).getByText("Held: more than one line or campaign uses it")).toBeTruthy();
    expect(within(rowOf("Patient agent")).getByText("Waiting: the platform is in maintenance")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Run it" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("runs it behind a confirm naming the client, with the step-up header and dry_run false", async () => {
    const { calls } = render();
    fireEvent.click(await screen.findByRole("button", { name: "Dry run" }));
    fireEvent.click(await screen.findByRole("button", { name: "Run it" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Hand agents' setups to their work for Sri Traders",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Run it" }));

    await screen.findByText("Done. This is what happened to each agent.");
    const real = posts(calls)[1];
    expect(JSON.parse(real.body ?? "{}")).toEqual({ dry_run: false });
    expect(real.headers["X-Confirm-Action"]).toBe(`retire_agent_engine_agents:${TENANT}`);
    expect(await screen.findByRole("table", { name: "What the run did, per agent" })).toBeTruthy();
    // The plan it acted on is spent: another real run needs another dry run.
    expect(screen.queryByRole("button", { name: "Run it" })).toBeNull();
  });

  it("shows the refusal while agents still get a setup of their own", async () => {
    render({
      [`POST ${PATH}`]: (call: ApiCall) =>
        (JSON.parse(call.body ?? "{}") as { dry_run: boolean }).dry_run
          ? runOut(true)
          : problem(422, {
              type: "https://calevate.tech/problems/agents_still_hold_engine_agents",
              title: "Business rule",
              detail: "Agents still get a calling setup of their own when they are published.",
              kind: "business_rule",
              remediation:
                'Switch off the platform setting "Agents hold an engine agent of their own" first, or run a dry run to see what this would do.',
            }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Dry run" }));
    fireEvent.click(await screen.findByRole("button", { name: "Run it" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Run it" }));

    expect(
      await within(dialog).findByText("Agents still get a calling setup of their own when they are published."),
    ).toBeTruthy();
    expect(within(dialog).getByText(/Switch off the platform setting "Agents hold an engine agent of their own"/)).toBeTruthy();
  });

  it("shows a failed dry run and offers nothing to run", async () => {
    render({
      [`POST ${PATH}`]: problem(404, { title: "Not found", detail: "Client not found.", kind: "not_found" }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Dry run" }));
    expect(await screen.findByText("Client not found.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run it" })).toBeNull();
  });

  it("is read-only without write access", async () => {
    render({}, false);
    expect((await screen.findByRole("button", { name: "Dry run" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
