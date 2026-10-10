import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentScriptPage from "@/app/c/[slug]/agents/[agentId]/script/page";
import type { Me } from "@/lib/api/client";
import { EMPTY_SCRIPT, type ScriptOut } from "@/lib/api/script";

import { renderClientPage } from "./harness";
import { agentRow, settledPending } from "./fixtures/sharedReads";

/**
 * Who may change the call script.
 *
 * `GET /v1/agents/{id}/script` and `POST …/script/preview` are `agents:read`, so staff open
 * the builder and see the room left; the draft autosave, "Put it live", restore and undo
 * are `org:manage`, which only the owner holds (`core/rbac.ROLE_PERMISSIONS`). An editor
 * that autosaves for staff would be a stream of refusals.
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

const SCRIPT: ScriptOut = {
  script: { ...EMPTY_SCRIPT, opening_line: "Namaskaram, this is Sri Clinic." },
  draft: { script: { ...EMPTY_SCRIPT, opening_line: "Namaskaram! Sri Clinic." }, saved_at: "2026-10-10T12:00:00+00:00" },
  stored_schema_version: 2,
  context: null,
  version: 3,
  is_freeform: false,
  has_pending: false,
  standard_variables: [],
};

const page = (
  <AgentScriptPage params={Promise.resolve({ slug: "acme", agentId: "agent-1" })} />
);

function routes(who: Me, script: ScriptOut = SCRIPT) {
  return {
    "/v1/me": who,
    "/v1/agents/agent-1": agentRow(),
    "/v1/agents/agent-1/script": script,
    "POST /v1/agents/agent-1/script/preview": { compiled: "", instructions_chars: 100, instructions_limit: 8000, native_steps: 0 },
    "POST /v1/agents/agent-1/script/publish": { version: 4, live: true },
    "/v1/agents/agent-1/script/proposed-rules": [],
    "/v1/agents/agent-1/pending": settledPending(),
    "/v1/agents/agent-1/script/tests": {
      available: false,
      unavailable_reason: "Not yet.",
      cost_note: "",
      latest: null,
    },
  };
}

describe("changing the call script", () => {
  it("is open to an owner: Put it live is offered while the draft differs", async () => {
    await renderClientPage(page, routes(me("owner", ["agents:read", "org:read", "org:manage"])));
    const live = await screen.findByRole("button", { name: "Put it live" });
    await waitFor(() => expect(live.matches(":disabled")).toBe(false));
  });

  it("is closed to staff, who see the draft read-only and why", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(me("staff", ["agents:read", "agents:write", "org:read"])),
    );
    expect(await screen.findByText("Only an account owner can change this script.")).toBeTruthy();
    const live = screen.getByRole("button", { name: "Put it live" });
    expect(live.matches(":disabled")).toBe(true);
    expect(screen.getByText(/View only/)).toBeTruthy();
    expect(screen.getByLabelText("Opening line").matches(":disabled")).toBe(true);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 1500));
    });
    expect(calls.some((call) => call.method === "PUT" || call.path.endsWith("/publish"))).toBe(false);
  });
});
