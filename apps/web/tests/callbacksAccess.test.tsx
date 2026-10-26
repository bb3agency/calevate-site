import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallbacksPage from "@/app/c/[slug]/callbacks/page";
import type { ScheduledCallback } from "@/lib/api/callbacks";
import type { Me } from "@/lib/api/client";

import { renderClientPage } from "./harness";

/**
 * Who may call a promised call-back off.
 *
 * The list is `GET /v1/callbacks` (`leads:read`, which staff hold); calling one off is
 * `DELETE /v1/callbacks/{id}` (`leads:dispatch`, owner only — `core/rbac.ROLE_PERMISSIONS`).
 * A control offered to a role the route refuses is a button that answers with a 403.
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

const OWNER = me("owner", ["leads:read", "leads:dispatch"]);
const STAFF = me("staff", ["leads:read", "leads:write"]);

const WAITING: ScheduledCallback = {
  id: "0192f0aa-3333-7000-8000-000000000003",
  agent_id: "0192f0aa-2222-7000-8000-000000000002",
  lead_id: null,
  phone_e164: "+91******3210",
  requested_at: "2026-09-29T10:30:00Z",
  status: "scheduled",
  attempts: 0,
  explanation: "Booked for the time the caller asked for.",
  last_call_id: null,
  settled_at: null,
  note: null,
};

const LIST = "/v1/callbacks?limit=200&open_only=false";

describe("calling off a call-back", () => {
  it("is offered to a role that holds leads:dispatch", async () => {
    await renderClientPage(<CallbacksPage />, { "/v1/me": OWNER, [LIST]: [WAITING] });

    fireEvent.click(await screen.findByRole("button", { name: "Call it off" }));
    expect(await screen.findByText("Call this off?")).toBeTruthy();
  });

  it("is not offered to staff, and the screen says why instead", async () => {
    const { calls } = await renderClientPage(<CallbacksPage />, {
      "/v1/me": STAFF,
      [LIST]: [WAITING],
    });

    expect(await screen.findByText("Waiting")).toBeTruthy();
    expect(
      await screen.findByText("Only an account owner can call off a call-back."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Call it off" })).toBeNull();
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });
});

describe("a call-back's note", () => {
  // The note is ours, the agent's or a team member's: a retry of a new enquiry carries
  // "A new enquiry who did not answer the last try", which the caller never said.
  it("is labelled a note, not the caller's words", async () => {
    const note = "A new enquiry who did not answer the last try";
    await renderClientPage(<CallbacksPage />, { "/v1/me": OWNER, [LIST]: [{ ...WAITING, note }] });

    expect(await screen.findByText(`Note: ${note}`)).toBeTruthy();
    expect(screen.queryByText(/They said/)).toBeNull();

    // Nor does the confirmation say the person asked: a retry or a team's booking did not.
    fireEvent.click(screen.getByRole("button", { name: "Call it off" }));
    expect(await screen.findByText(/is due a call back at/)).toBeTruthy();
    expect(screen.queryByText(/asked to be rung back/)).toBeNull();
  });
});
