import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallbacksPage from "@/app/c/[slug]/callbacks/page";
import { CallAgain, type Dialer } from "@/app/c/[slug]/calls/CallAgain";
import type { CallbacksBulkResult, ScheduledCallback } from "@/lib/api/callbacks";
import type { Me } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";

import { expectNoA11yViolations } from "./a11y";
import { renderClientPage, type ApiCall } from "./harness";
import { PLAN_ID, planFixture } from "./planFixture";

/**
 * Moving and calling off call-backs, one or many (D-893 L1), and the Calls screen's
 * "Call them again", which asks for a plan and dials nobody.
 */

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["leads:read", "leads:dispatch"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

function waiting(n: number): ScheduledCallback {
  return {
    id: `0192f0aa-3333-7000-8000-00000000000${n}`,
    agent_id: "0192f0aa-2222-7000-8000-000000000002",
    lead_id: null,
    phone_e164: `+91******321${n}`,
    requested_at: "2026-09-29T10:30:00Z",
    status: "scheduled",
    attempts: 0,
    explanation: "Booked for the time the caller asked for.",
    last_call_id: null,
    settled_at: null,
    held: false,
    note: null,
  };
}

const LIST = "/v1/callbacks?limit=200&open_only=false";

function sent(calls: ApiCall[], method: string, path: string): Record<string, unknown> | null {
  const call = calls.find((c) => c.method === method && c.path === path);
  return call?.body ? (JSON.parse(call.body) as Record<string, unknown>) : null;
}

describe("moving a call-back", () => {
  it("offers only the call-back hours and sends the time with its India offset", async () => {
    const row = waiting(1);
    const { calls } = await renderClientPage(<CallbacksPage />, {
      "/v1/me": OWNER,
      [LIST]: [row],
      [`PATCH /v1/callbacks/${row.id}`]: { ...row, requested_at: "2026-09-30T05:30:00Z" },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Move" }));
    const dialog = await screen.findByRole("dialog", { name: "Move this call-back" });
    expect(within(dialog).getByText(/9am to 9pm/)).toBeTruthy();
    await expectNoA11yViolations(dialog, "Move a call-back");
    fireEvent.click(within(dialog).getByRole("button", { name: "Move it" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const body = sent(calls, "PATCH", `/v1/callbacks/${row.id}`);
    expect(String(body?.at)).toMatch(/T\d\d:\d\d:00\+05:30$/);
  });
});

describe("a call-back its campaign's pause holds (D-914)", () => {
  it("reads On hold with the reason, and a waiting one does not", async () => {
    const held: ScheduledCallback = {
      ...waiting(1),
      held: true,
      explanation: "On hold while its campaign is paused. It will be called once the campaign resumes.",
    };
    await renderClientPage(<CallbacksPage />, { "/v1/me": OWNER, [LIST]: [held, waiting(2)] });
    expect(await screen.findByText("On hold")).toBeTruthy();
    expect(screen.getByText(/will be called once the campaign resumes/)).toBeTruthy();
    expect(screen.getAllByText("Waiting").length).toBeGreaterThan(0);
  });
});

describe("changing the ticked call-backs", () => {
  it("calls them off each on its own and says which were left as they were, and why", async () => {
    const [a, b] = [waiting(1), waiting(2)];
    const result: CallbacksBulkResult = {
      changed: 1,
      results: [
        { callback_id: a.id, status: "cancelled", requested_at: null, reason: null },
        {
          callback_id: b.id,
          status: "not_waiting",
          requested_at: null,
          reason: "It is no longer waiting: it is being placed now or has already ended.",
        },
      ],
    };
    const { calls } = await renderClientPage(<CallbacksPage />, {
      "/v1/me": OWNER,
      [LIST]: [a, b],
      "POST /v1/callbacks/bulk": result,
    });

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select every call-back listed" }));
    const bar = await screen.findByRole("region", { name: "2 call-backs selected" });
    fireEvent.click(within(bar).getByRole("button", { name: "Call off" }));
    const dialog = await screen.findByRole("dialog", { name: "Call off 2 call-backs?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Do not ring them" }));

    expect(await screen.findByText("Called off 1 call-back.")).toBeTruthy();
    expect(screen.getByText(/1 left as it was: It is no longer waiting/)).toBeTruthy();
    expect(sent(calls, "POST", "/v1/callbacks/bulk")).toEqual({
      action: "cancel",
      callback_ids: [a.id, b.id],
    });
    // The selection is spent.
    expect(screen.queryByRole("region", { name: /selected/ })).toBeNull();
  });
});

const DIALER: Dialer = { id: "0192f0aa-2222-7000-8000-000000000009", name: "Follow-ups" };

function Again({ dialers }: { dialers: Dialer[] | undefined }) {
  const { session } = useClientRealm();
  return (
    <CallAgain
      session={session}
      dialers={dialers}
      scope={{ direction: "outbound", fromDay: "2026-10-20", toDay: "2026-10-26", testCalls: false }}
    />
  );
}

describe("calling the unanswered again", () => {
  it("asks how they agreed, then shows the plan; nobody is called before Approve", async () => {
    const { calls } = await renderClientPage(<Again dialers={[DIALER]} />, {
      "/v1/me": OWNER,
      "POST /v1/copilot/plans": planFixture({ tool: "calls_place_bulk" }),
      [`/v1/copilot/plans/${PLAN_ID}`]: planFixture({ tool: "calls_place_bulk" }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Call them again" }));
    const dialog = await screen.findByRole("dialog", { name: "Call them again" });
    await expectNoA11yViolations(dialog, "Call them again");
    fireEvent.click(within(dialog).getByRole("button", { name: "Show me the plan" }));
    expect(await within(dialog).findByText("Choose how they agreed to be called.")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    fireEvent.change(within(dialog).getByLabelText(/How did these people agree/), {
      target: { value: "inbound_enquiry" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Show me the plan" }));

    expect(await screen.findByRole("region", { name: /Plan:/ })).toBeTruthy();
    expect(sent(calls, "POST", "/v1/copilot/plans")).toEqual({
      tool: "calls_place_bulk",
      args: {
        lens: {
          last_outcome: "missed",
          direction: "outbound",
          last_call_from: "2026-10-20",
          last_call_to: "2026-10-26",
          test_calls: false,
        },
        lead_ids: null,
        agent_id: DIALER.id,
        classification: "service",
        consent_source: "inbound_enquiry",
      },
    });
    expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(false);
  });

  it("says plainly when no agent can place calls", async () => {
    await renderClientPage(<Again dialers={[]} />, { "/v1/me": OWNER });
    expect(await screen.findByText(/No agent can call out right now/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Call them again" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
