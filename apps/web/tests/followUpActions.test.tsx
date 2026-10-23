import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallsPage from "@/app/c/[slug]/calls/page";
import { ToastProvider } from "@/components/arc/toast";
import { callbackSlots, defaultCallbackSlot } from "@/components/calls/followUpActions";
import type { CallSummary, Me } from "@/lib/api/client";

import { problem, renderClientPage } from "./harness";

/**
 * The follow-up actions (D-869) on the call log: the ⋯ menu a mouse uses carries the same
 * actions the phone swipe does, so these drive them through the menu.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "leads:read", "leads:write", "leads:dispatch"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

function call(over: Partial<CallSummary> = {}): CallSummary {
  return {
    id: "c1",
    agent_id: "a1",
    agent_name: "Reception",
    direction: "inbound",
    status: "completed",
    caller_e164: "+919876543210",
    lead_name: "Ramesh Kumar",
    started_at: "2026-08-13T04:30:00Z",
    duration_s: 92,
    outcome_tag: "answered",
    summary_state: "ready",
    test_call: false,
    sentiment: "positive",
    summary: "Caller asked for a Tuesday slot.",
    lead_id: "lead-a",
    follow_up_state: null,
    ...over,
  };
}

function routes(over: Record<string, unknown> = {}) {
  return { "/v1/me": ME, "/v1/agents": [], "/v1/calls?limit=100": [call()], ...over };
}

const page = (
  <ToastProvider>
    <CallsPage params={Promise.resolve({ slug: "acme" })} />
  </ToastProvider>
);

async function openMenuItem(name: RegExp) {
  fireEvent.click(await screen.findByRole("button", { name: /More actions for Ramesh Kumar/ }));
  fireEvent.click(await screen.findByRole("menuitem", { name }));
}

describe("the time a call back can be booked for", () => {
  it("offers 9am to 8:45pm India time in quarter hours, today only from a little after now", () => {
    const tomorrow = callbackSlots("2026-10-26", "2026-10-25", 600);
    expect(tomorrow[0]).toBe(9 * 60);
    expect(tomorrow.at(-1)).toBe(20 * 60 + 45);
    // 10:00 now: 10:10 is the soonest, so 10:15 is the first slot.
    expect(callbackSlots("2026-10-25", "2026-10-25", 600)[0]).toBe(10 * 60 + 15);
  });

  it("starts at 10am tomorrow once today has closed", () => {
    expect(defaultCallbackSlot("2026-10-25", 20 * 60 + 50)).toEqual({ day: "2026-10-26", minutes: 600 });
  });
});

describe("marking a call (a person's mark, apart from the outcome)", () => {
  it("shows the mark on the row and offers Undo, which sends the old mark back with the new one expected", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "PUT /v1/calls/c1/follow-up": (c: { body: string | null }) => {
          const body = JSON.parse(c.body ?? "{}") as { state: string | null };
          return {
            call_id: "c1",
            state: body.state,
            previous_state: body.state === "resolved" ? null : "resolved",
            set_at: null,
            set_by: null,
            changed: true,
          };
        },
      }),
    );
    await openMenuItem(/Mark this call/);
    fireEvent.click(within(await screen.findByRole("dialog", { name: /Mark the call/ })).getByRole("button", { name: /^Done/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "/v1/calls/c1/follow-up")).toBe(true));
    const first = calls.find((c) => c.method === "PUT");
    expect(JSON.parse(first?.body ?? "{}")).toEqual({ state: "resolved" });

    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2));
    expect(JSON.parse(calls.filter((c) => c.method === "PUT")[1].body ?? "{}")).toEqual({
      state: null,
      expected_state: "resolved",
    });
  });

  it("says plainly that a colleague changed it first when the server answers 409", async () => {
    await renderClientPage(
      page,
      routes({
        "PUT /v1/calls/c1/follow-up": problem(409, {
          title: "Conflict",
          detail: "Someone else changed this call's mark since you last saw it.",
          kind: "conflict",
        }),
      }),
    );
    await openMenuItem(/Mark this call/);
    const dialog = await screen.findByRole("dialog", { name: /Mark the call/ });
    fireEvent.click(within(dialog).getByRole("button", { name: /^Needs you/ }));
    expect(await screen.findByText("A colleague changed this first")).toBeTruthy();
  });

  it("prints the mark beside the outcome, in words", async () => {
    await renderClientPage(page, routes({ "/v1/calls?limit=100": [call({ follow_up_state: "needs_you" })] }));
    expect((await screen.findAllByText("Marked: needs you")).length).toBeGreaterThan(0);
  });
});

describe("the actions that reach a person", () => {
  it("cannot call back without an agent that places calls, and says why", async () => {
    await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: /More actions for Ramesh Kumar/ }));
    const item = await screen.findByRole("menuitem", { name: "Call back" });
    expect(item.getAttribute("aria-disabled")).toBe("true");
    expect(item.textContent).toContain("None of your agents places calls yet");
  });

  it("shows a refused call back later as the reason, and keeps the dialog open", async () => {
    await renderClientPage(
      page,
      routes({
        "POST /v1/leads/lead-a/callbacks": {
          status: "blocked",
          blocked_reason: "This person asked not to be called.",
          blocked_rule: "dnc_tenant",
          callback_id: null,
          requested_at: null,
          rescheduled: false,
        },
      }),
    );
    await openMenuItem(/Call back later/);
    const dialog = await screen.findByRole("dialog", { name: /Call Ramesh Kumar back later/ });
    fireEvent.click(within(dialog).getByRole("button", { name: "Book the call back" }));
    expect(await within(dialog).findByText("This person asked not to be called.")).toBeTruthy();
    expect(within(dialog).queryByText(/dnc_tenant/)).toBeNull();
  });

  it("gives the server's reason when no WhatsApp message may be sent, and offers no Send", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/leads/lead-a/whatsapp": {
          available: false,
          reason: "Connect your WhatsApp number first.",
          rule: "whatsapp_not_connected",
          templates: [],
        },
      }),
    );
    await openMenuItem(/WhatsApp/);
    const dialog = await screen.findByRole("dialog", { name: /WhatsApp follow-up/ });
    expect(await within(dialog).findByText("Connect your WhatsApp number first.")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Send" })).toBeNull();
  });

  it("asks for every blank of the chosen message before sending it", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/leads/lead-a/whatsapp": {
          available: true,
          reason: null,
          rule: null,
          templates: [
            {
              id: "t1",
              name: "Follow-up",
              language: "en",
              category: "UTILITY",
              body: "Hello {{1}}, your slot is {{2}}.",
              variables: [
                { label: "Name", example: "Ramesh" },
                { label: "Slot", example: "Tuesday 10am" },
              ],
            },
          ],
        },
        "POST /v1/leads/lead-a/whatsapp": { status: "sent", reason: null, rule: null },
      }),
    );
    await openMenuItem(/WhatsApp/);
    const dialog = await screen.findByRole("dialog", { name: /WhatsApp follow-up/ });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Send" }));
    expect(within(dialog).getAllByText("Fill this in before sending.")).toHaveLength(2);
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Ramesh" } });
    fireEvent.change(within(dialog).getByLabelText("Slot"), { target: { value: "Tue 10am" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/v1/leads/lead-a/whatsapp")).toBe(true));
    const sent = calls.find((c) => c.method === "POST" && c.path === "/v1/leads/lead-a/whatsapp");
    expect(JSON.parse(sent?.body ?? "{}")).toMatchObject({ template_id: "t1", values: ["Ramesh", "Tue 10am"] });
    expect(sent?.headers["Idempotency-Key"] ?? sent?.headers["idempotency-key"]).toBeTruthy();
  });
});
