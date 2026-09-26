import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Actions } from "@/app/c/[slug]/agents/actions/Actions";
import type { ActionTool, ActionsSettings } from "@/lib/api/actions";
import type { Me } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";

import { renderClientPage } from "./harness";

/**
 * Who may change what an agent does mid-call.
 *
 * `GET /v1/agents/{id}/actions` and `GET /v1/integrations/credentials` are `org:read`, so
 * staff can open this panel; every write behind it — the master switch, a tool's switch, a
 * removal, a test run, a new credential or action — is `org:manage`, which only the owner
 * holds (`core/rbac.ROLE_PERMISSIONS`). Offering those controls to staff is offering a 403.
 */

function me(role: "owner" | "staff", permissions: string[]): Me {
  return {
    user_id: "u1",
    realm: "client",
    role,
    permissions,
    impersonating: false,
    withheld_acts: [],
    organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
  };
}

const TOOL: ActionTool = {
  id: "tool-1",
  agent_id: "agent-1",
  kind: "custom_api",
  name: "Look up an order",
  description: "Finds the caller's order by its number.",
  trigger: "during_call",
  enabled: true,
  params: [],
  config: {},
  credential_id: null,
  pre_call_message: null,
  provider: null,
};

const SETTINGS: ActionsSettings = {
  api_actions_enabled: true,
  calendar_available: false,
  tools: [TOOL],
};

function Panel() {
  const session = useClientSession();
  return <Actions agentId="agent-1" session={session} />;
}

function routes(who: Me) {
  return {
    "/v1/me": who,
    "/v1/agents/agent-1/actions": SETTINGS,
    "/v1/integrations/credentials": [],
    "PUT /v1/agents/agent-1/actions/enabled": { ...SETTINGS, api_actions_enabled: false },
  };
}

describe("the mid-call actions panel", () => {
  it("lets an owner flip the master switch", async () => {
    const { calls } = await renderClientPage(
      <Panel />,
      routes(me("owner", ["org:read", "org:manage"])),
    );
    const master = await screen.findByRole("switch", { name: /enable api actions/i });
    await waitFor(() => expect(master.matches(":disabled")).toBe(false));
    fireEvent.click(master);
    await waitFor(() =>
      expect(calls.some((call) => call.path.endsWith("/actions/enabled"))).toBe(true),
    );
  });

  it("gives staff no write the server will refuse, and says why", async () => {
    const { calls } = await renderClientPage(
      <Panel />,
      routes(me("staff", ["agents:read", "agents:write", "org:read"])),
    );

    expect(await screen.findByText("Look up an order")).toBeTruthy();
    expect(
      await screen.findByText(
        "Only an account owner can change what this agent can do mid-call.",
      ),
    ).toBeTruthy();

    const master = screen.getByRole("switch", { name: /enable api actions/i });
    const writes = [
      master,
      screen.getByRole("button", { name: "Remove Look up an order" }),
      screen.getByRole("button", { name: /test/i }),
      screen.getByRole("button", { name: /custom api/i }),
    ];
    for (const control of writes) expect(control.matches(":disabled")).toBe(true);

    fireEvent.click(master);
    expect(calls.some((call) => call.method !== "GET")).toBe(false);
  });
});
