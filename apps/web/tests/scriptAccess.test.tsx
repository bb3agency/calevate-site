import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentScriptPage from "@/app/c/[slug]/agents/[agentId]/script/page";
import type { Me } from "@/lib/api/client";
import type { ScriptOut } from "@/lib/api/script";

import { renderClientPage } from "./harness";

/**
 * Who may save the call script.
 *
 * `GET /v1/agents/{id}/script` and `POST …/script/preview` are `agents:read`, so staff open
 * the builder and may preview a draft; `PUT …/script`, `…/apply` and `…/undo` are
 * `org:manage`, which only the owner holds (`core/rbac.ROLE_PERMISSIONS`). A Save button
 * offered to staff is a whole script typed and then refused.
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
  script: {
    opening_line: "Namaskaram, this is Sri Clinic.",
    steps: [],
    faqs: [],
    faq_fallback: "Our team will call you back with the details.",
    end_call_extra_rules: [],
    variables: [],
    raw_override: null,
  },
  version: 3,
  is_freeform: false,
  has_pending: true,
  standard_variables: [],
};

const page = (
  <AgentScriptPage params={Promise.resolve({ slug: "acme", agentId: "agent-1" })} />
);

function routes(who: Me) {
  return {
    "/v1/me": who,
    "/v1/agents/agent-1/script": SCRIPT,
    "PUT /v1/agents/agent-1/script": { version: 4, staged: true },
  };
}

describe("saving the call script", () => {
  it("is open to an owner", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(me("owner", ["agents:read", "org:read", "org:manage"])),
    );
    const save = await screen.findByRole("button", { name: "Save script" });
    await waitFor(() => expect(save.matches(":disabled")).toBe(false));
    fireEvent.click(save);
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PUT")).toBe(true),
    );
  });

  it("is closed to staff, with Apply and Undo, and the screen says why", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(me("staff", ["agents:read", "agents:write", "org:read"])),
    );

    expect(
      await screen.findByText("Only an account owner can save or apply this script."),
    ).toBeTruthy();
    for (const name of ["Save script", "Apply to live calls", /undo changes/i]) {
      expect(screen.getByRole("button", { name }).matches(":disabled")).toBe(true);
    }
    // Previewing is `agents:read`, so it stays open.
    expect(
      screen.getByRole("button", { name: /view compiled prompt/i }).matches(":disabled"),
    ).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Save script" }));
    expect(calls.some((call) => call.method !== "GET")).toBe(false);
  });
});
