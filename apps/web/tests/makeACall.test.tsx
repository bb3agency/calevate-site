import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import MakeCallPage from "@/app/c/[slug]/make-a-call/page";
import { ToastProvider } from "@/components/arc/toast";
import type { Agent } from "@/lib/api/agents";
import type { CallSummary, Me } from "@/lib/api/client";
import { clientNavigation } from "@/lib/clientNav";

import { problem, renderClientPage } from "./harness";

/**
 * Make a call (founder, 5 Nov 2026): the one form for one call to one person. What these
 * pin is what the person sees and what is sent: only agents that place calls, the request
 * by id or by number and never a number in a URL, every refusal as the gate's own sentence
 * with the one thing it cannot say (the next allowed time, where credit is added), one
 * Idempotency-Key per attempt, and the live card after the call is placed.
 */

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "leads:read", "leads:write", "leads:dispatch"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Rytu Store", slug: "acme", status: "active" },
};

const STAFF: Me = { ...OWNER, role: "staff", permissions: ["calls:read", "leads:read", "leads:write"] };

const DIALER = {
  id: "agent-out",
  name: "Field caller",
  published: true,
  status: "live",
  direction: "outbound",
} as unknown as Agent;
const RECEPTIONIST = {
  id: "agent-in",
  name: "Front desk",
  published: true,
  status: "live",
  direction: "inbound",
} as unknown as Agent;

const RECENT = "/v1/calls?placed_by_person=true&limit=10&test_calls=false";
const BOOKED = "/v1/callbacks?limit=200&open_only=true&booked_by_person=true";

function recentCall(over: Partial<CallSummary> = {}): CallSummary {
  return {
    id: "call-9",
    agent_id: "agent-out",
    agent_name: "Field caller",
    direction: "outbound",
    status: "completed",
    caller_e164: "+919812345678",
    lead_name: "Suresh",
    started_at: "2026-11-04T05:30:00Z",
    duration_s: 61,
    outcome_tag: "answered",
    summary_state: "ready",
    test_call: false,
    summary: null,
    lead_id: "lead-9",
    follow_up_state: null,
    ...over,
  } as CallSummary;
}

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/agents": [RECEPTIONIST, DIALER],
    [RECENT]: [],
    [BOOKED]: [],
    ...over,
  };
}

const page = (
  <ToastProvider>
    <MakeCallPage />
  </ToastProvider>
);

function arriveAt(search: string) {
  window.history.replaceState(null, "", `/c/acme/make-a-call${search}`);
}

afterEach(() => arriveAt(""));

function sent(calls: { path: string; method: string; body: string | null }[]) {
  return calls.filter((c) => c.method === "POST" && c.path === "/v1/one-calls").map((c) => JSON.parse(c.body ?? "{}"));
}

async function fillNumberForm(phone = "9876543210", reason = "Confirm Saturday's visit") {
  fireEvent.change(await screen.findByLabelText("Phone number"), { target: { value: phone } });
  fireEvent.change(screen.getByLabelText("Why are you calling?"), { target: { value: reason } });
}

describe("the sidebar", () => {
  it("names the screen Make a call, beside Campaigns", () => {
    const items = clientNavigation("acme")[0].items.map((item) => item.label);
    expect(items.indexOf("Make a call")).toBe(items.indexOf("Campaigns") - 1);
  });
});

describe("making a call by number", () => {
  it("offers only agents that place calls, and sends the number, agent and reason", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "POST /v1/one-calls": { status: "queued", call_id: "call-1", lead_id: "lead-1" },
        "/v1/calls/live?ids=call-1": [{ id: "call-1", status: "ringing", status_source: "engine", live_state: "live" }],
      }),
    );
    const agent = (await screen.findByLabelText("Agent")) as HTMLSelectElement;
    expect([...agent.options].map((o) => o.textContent)).toEqual(["Field caller"]);
    await fillNumberForm();
    fireEvent.change(screen.getByLabelText("Name (optional)"), { target: { value: "Ravi" } });
    fireEvent.click(screen.getByRole("button", { name: "Call now" }));

    await screen.findByRole("region", { name: "This call" });
    expect(sent(calls)).toEqual([
      { phone: "9876543210", name: "Ravi", agent_id: "agent-out", reason: "Confirm Saturday's visit", details: null },
    ]);
    // The live card follows the call and links to it.
    const card = await screen.findByRole("region", { name: "This call" });
    // The status line (the step track names "Ringing" too).
    await waitFor(() => expect(within(card).getAllByText("Ringing")).toHaveLength(2));
    expect(within(card).getByRole("link", { name: "See the call" }).getAttribute("href")).toBe("/c/acme/calls/call-1");
  });

  it("says how the call ended, links to it, and offers the next call", async () => {
    await renderClientPage(
      page,
      routes({
        "POST /v1/one-calls": { status: "queued", call_id: "call-1", lead_id: "lead-1" },
        "/v1/calls/live?ids=call-1": [{ id: "call-1", status: "no_answer", status_source: "call", live_state: null }],
      }),
    );
    await fillNumberForm();
    fireEvent.click(screen.getByRole("button", { name: "Call now" }));
    const card = await screen.findByRole("region", { name: "This call" });
    expect(await within(card).findByText("No answer")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Open the call" }).getAttribute("href")).toBe("/c/acme/calls/call-1");
    fireEvent.click(within(card).getByRole("button", { name: "Make another call" }));
    expect(await screen.findByLabelText("Phone number")).toBeTruthy();
  });

  it("asks for the number and the reason before sending anything", async () => {
    const { calls } = await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: "Call now" }));
    expect(await screen.findByText("Enter the number to call.")).toBeTruthy();
    expect(screen.getByText("Say why you are calling, in one line.")).toBeTruthy();
    expect(sent(calls)).toEqual([]);
  });

  it("says when no agent can place calls, and where to set one up", async () => {
    await renderClientPage(page, routes({ "/v1/agents": [RECEPTIONIST] }));
    expect(await screen.findByText(/No agent can place calls yet/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Set one up" }).getAttribute("href")).toBe("/c/acme/agents");
    expect((screen.getByRole("button", { name: "Call now" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("a refusal is the gate's answer", () => {
  it("outside calling hours, offers the next allowed time and books it there", async () => {
    let answer = 0;
    const { calls } = await renderClientPage(
      page,
      routes({
        "POST /v1/one-calls": () => {
          answer += 1;
          return answer === 1
            ? {
                status: "blocked",
                blocked_rule: "calling_hours",
                blocked_reason: "Calls can only be placed between 9 am and 9 pm. You can call from 9:00 am tomorrow.",
                opens_at: "2026-11-06T03:30:00Z",
              }
            : { status: "scheduled", callback_id: "cb-1", lead_id: "lead-1", requested_at: "2026-11-06T03:30:00Z" };
        },
      }),
    );
    await fillNumberForm();
    fireEvent.click(screen.getByRole("button", { name: "Call now" }));

    expect(await screen.findByText(/You can call from 9:00 am tomorrow/)).toBeTruthy();
    expect(screen.queryByText(/calling_hours/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Book it for/ }));
    expect(await screen.findByText(/Booked for/)).toBeTruthy();
    expect(sent(calls)[1].at).toBe("2026-11-06T03:30:00Z");
    expect(screen.getByRole("button", { name: "Call it off" })).toBeTruthy();
  });

  it("sends a refusal for credit to the screen that fixes it, without the rule's name", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "POST /v1/one-calls": {
          status: "blocked",
          blocked_rule: "no_credits",
          blocked_reason: "This account has no calling credit left.",
        },
      }),
    );
    await fillNumberForm();
    fireEvent.click(screen.getByRole("button", { name: "Call now" }));
    expect(await screen.findByText("This account has no calling credit left.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add credit" }).getAttribute("href")).toBe("/c/acme/billing");
    expect(container.textContent).not.toContain("no_credits");
  });

  it("puts the server's sentence for a bad number under the number", async () => {
    await renderClientPage(
      page,
      routes({
        "POST /v1/one-calls": problem(422, {
          title: "That number cannot be called",
          detail: "Enter a 10-digit mobile number, or a number with its country code.",
          kind: "validation",
          fields: [{ field: "phone", rule: "format", message: "not a phone number" }],
        }),
      }),
    );
    await fillNumberForm("12345");
    fireEvent.click(screen.getByRole("button", { name: "Call now" }));
    const phone = screen.getByLabelText("Phone number");
    await waitFor(() => expect(phone.getAttribute("aria-invalid")).toBe("true"));
    expect(screen.getAllByText(/10-digit mobile number/).length).toBeGreaterThan(0);
  });

  it("sends the same Idempotency-Key when a press that got no answer is retried", async () => {
    let answers = 0;
    const { calls } = await renderClientPage(
      page,
      routes({
        "POST /v1/one-calls": () => {
          answers += 1;
          return answers === 1
            ? problem(504, { title: "Timed out", kind: "transient", retryable: true })
            : { status: "queued", call_id: "call-1", lead_id: "lead-1" };
        },
        "/v1/calls/live?ids=call-1": [],
      }),
    );
    await fillNumberForm();
    fireEvent.click(screen.getByRole("button", { name: "Call now" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: /Call now|Try again/ }));
    await screen.findByRole("region", { name: "This call" });
    const keys = calls
      .filter((c) => c.path === "/v1/one-calls")
      .map((c) => (c as unknown as { headers: Record<string, string> }).headers["Idempotency-Key"]);
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
  });
});

describe("arriving from a lead or a call", () => {
  it("names the lead, preselects the agent and sends the lead's id, not its number", async () => {
    arriveAt("?lead=lead-a&agent=agent-out");
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/leads/lead-a": { id: "lead-a", name: "Lakshmi", phone_e164: "+919876543210" },
        "POST /v1/one-calls": { status: "queued", call_id: "call-2", lead_id: "lead-a" },
        "/v1/calls/live?ids=call-2": [],
      }),
    );
    expect(await screen.findByText("Lakshmi")).toBeTruthy();
    expect(screen.queryByLabelText("Phone number")).toBeNull();
    fireEvent.change(screen.getByLabelText("Why are you calling?"), { target: { value: "Your seeds are in" } });
    fireEvent.click(screen.getByRole("button", { name: "Call now" }));
    await screen.findByRole("region", { name: "This call" });
    expect(sent(calls)).toEqual([
      { lead_id: "lead-a", agent_id: "agent-out", reason: "Your seeds are in", details: null },
    ]);
  });

  it("follows up a call by its id, with no reason to type", async () => {
    arriveAt("?call=c1");
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/calls/c1": { id: "c1", lead_name: "Lakshmi", caller_e164: "+919876543210", lead_id: "lead-a" },
        "/v1/calls/c1/callback": { eligible: true, reason: null, rule: null, follow_up_number: 1 },
        "POST /v1/one-calls": { status: "queued", call_id: "call-3", lead_id: "lead-a", follow_up_number: 1 },
        "/v1/calls/live?ids=call-3": [],
      }),
    );
    expect(await screen.findByText("Calling back")).toBeTruthy();
    expect(screen.queryByLabelText("Why are you calling?")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Call now" }));
    await screen.findByRole("region", { name: "Call-back #1" });
    expect(sent(calls)).toEqual([{ call_id: "c1" }]);
  });
});

describe("the recent list and who may use the screen", () => {
  it("lists the calls people made, each linked to its call", async () => {
    await renderClientPage(page, routes({ [RECENT]: [recentCall()] }));
    const link = await screen.findByRole("link", { name: /Suresh/ });
    expect(link.getAttribute("href")).toBe("/c/acme/calls/call-9");
  });

  it("says none yet only from an answer", async () => {
    await renderClientPage(page, routes());
    expect(await screen.findByText(/No calls made from here yet/)).toBeTruthy();
  });

  it("refuses a role that cannot place calls, in words, with no form", async () => {
    await renderClientPage(page, routes({ "/v1/me": STAFF }));
    expect(await screen.findByText(/Only an account owner can place calls/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Call now" })).toBeNull();
  });
});
