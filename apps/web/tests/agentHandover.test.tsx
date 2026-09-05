import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentDetailPage from "@/app/c/[slug]/agents/[agentId]/page";
import type { Agent, HandoffOut } from "@/lib/api/agents";

import { renderClientPage } from "./harness";

/**
 * PUTTING A CALLER THROUGH TO A PERSON — the client's own screen (D-533).
 *
 * Four things can be wrong here, in falling order of what a wrong render costs, and every
 * one of them is a promise the CLIENT would repeat to their own callers:
 *
 * 1. **Implying the person answering is briefed first.** They are not. The voice platform
 *    places the transfer on its own carrier account and nothing plays a message to the
 *    called party — so a screen that said "your team hears why the call is coming" would
 *    have a shop owner tell their customers so. The panel says the opposite, without a
 *    click, and this file pins the sentence.
 * 2. **Implying the list is tried in turn during the call.** The platform allows one
 *    handover per conversation. The order decides who is CHOSEN before the call; a
 *    handover nobody answers becomes a call-back, not a second ring.
 * 3. **Saying "working" when nobody is on duty.** The verdict is the server's, with the
 *    server's own remediation, because a screen that composed its own could disagree with
 *    the publish about the same agent.
 * 4. **Saving half an edit.** The whole list goes in one PUT; a re-order and a removal
 *    land together or not at all.
 */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: [
    "agents:read",
    "calls:read",
    "leads:read",
    "billing:read",
    "org:read",
    "org:manage",
    "kb:write",
  ],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

/**
 * The rest of this screen, stubbed to the minimum that keeps it quiet.
 *
 * DELIBERATELY NOT SHARED WITH `agentDetail.test.tsx`. That file's fixtures are shaped by
 * what IT asserts — the staged/live pointers, the voice, the lifecycle moves — and a common
 * fixture would make every change to one file's premise a change to the other's. What is
 * shared is the SCREEN, which is the thing under test in both. Each unrouted endpoint here
 * exists for one reason only: an unstubbed request throws in this harness, the panel that
 * made it renders its own `role="alert"`, and a second alert on the page turns every
 * assertion below into a race.
 */
const AGENT: Agent = {
  id: "agent-1",
  name: "Reception",
  direction: "inbound",
  status: "live",
  archived_at: null,
  language_primary: "te-IN",
  disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_enabled: true,
  recording_notice_line: "This call is being recorded.",
  caller_memory_notice_line: "I keep a short note of what you ask about.",
  caller_memory_enabled: false,
  recording_notice_enabled: true,
  opening_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
  truthful_answer_rule:
    "Whatever these settings say, the agent always answers honestly when a caller asks.",
  engine: "bolna",
  published: true,
  inbound_number_count: 1,
  extraction_fields: [],
  llm_model: null,
  llm_model_effective: "gpt-4o-mini",
  llm_model_source: "platform",
};

const PENDING = {
  agent_id: "agent-1",
  agent_status: "live",
  published: true,
  has_pending: false,
  pending: [],
  effective_call_cap_s: 600,
  call_cap_is_platform_default: true,
  worst_case_call_cost_inr: "65.00",
  precedence_rule: "Script decides content, rules decide conduct, voice only changes delivery.",
  voice: {
    configured: null,
    live: null,
    republish_required: false,
    headline: "Callers hear the default voice.",
  },
  engine_verification: null,
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER,
    "/v1/agents/agent-1": AGENT,
    "/v1/agents/agent-1/pending": PENDING,
    "/v1/kb/sources": [],
    "/v1/organization/llm-defaults": {
      default_llm_model: null,
      effective_default: "gpt-4o-mini",
      available: [],
    },
    "/v1/agents/agent-1/actions": {
      api_actions_enabled: false,
      calendar_available: false,
      tools: [],
    },
    "/v1/integrations/credentials": [],
    "/v1/knowledge-gaps?agent_id=agent-1&status=open&limit=20": {
      items: [],
      open_count: 0,
      total: 0,
    },
    ...over,
  };
}

const page = <AgentDetailPage params={Promise.resolve({ slug: "acme", agentId: "agent-1" })} />;

const HANDOFF_PATH = "/v1/agents/agent-1/handoff";

function member(over: Partial<HandoffOut["members"][number]> = {}): HandoffOut["members"][number] {
  return {
    id: "m1",
    position: 0,
    label: "Ravi",
    phone_e164: "+919000000001",
    active: true,
    hours: null,
    note: null,
    on_duty: true,
    ...over,
  };
}

function handoff(over: Partial<HandoffOut> = {}): HandoffOut {
  return {
    agent_id: "agent-1",
    enabled: true,
    trigger: null,
    effective_trigger: "Hand the call to a person when the caller asks to speak to a human.",
    spoken_line: "Okay, I am putting you through to someone from our team now.",
    members: [member(), member({ id: "m2", position: 1, label: "Priya", phone_e164: "+919000000002", on_duty: false })],
    recent: [],
    on_duty_member_id: "m1",
    unavailable_reason: null,
    remediation: null,
    published: true,
    ...over,
  };
}

describe("what the handover panel promises about the person answering", () => {
  it("says plainly that nobody is briefed before they pick up", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff() }),
    );
    // The panel's own heading, NOT the Card title above it: the title paints immediately
    // and the panel is a skeleton until the query resolves, so awaiting the title would
    // read `textContent` off the loading state — which is how three of these first passed
    // against a panel that had not rendered.
    // The panel's own heading, NOT the Card title above it: the title paints immediately
    // and the panel is a skeleton until the query resolves, so awaiting the title would
    // read `textContent` off the loading state — which is how three of these first passed
    // against a panel that had not rendered.
    await screen.findByRole("heading", { level: 3, name: /Putting a caller through to a person/ });
    // THE SENTENCE THAT MUST NOT DISAPPEAR. If a future edit removes it, a client is left
    // to assume the founder's original request was built.
    expect(container.textContent).toContain("not told anything before they pick up");
  });

  it("says a missed handover becomes a call-back rather than a second ring", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff() }),
    );
    // The panel's own heading, NOT the Card title above it: the title paints immediately
    // and the panel is a skeleton until the query resolves, so awaiting the title would
    // read `textContent` off the loading state — which is how three of these first passed
    // against a panel that had not rendered.
    // The panel's own heading, NOT the Card title above it: the title paints immediately
    // and the panel is a skeleton until the query resolves, so awaiting the title would
    // read `textContent` off the loading state — which is how three of these first passed
    // against a panel that had not rendered.
    await screen.findByRole("heading", { level: 3, name: /Putting a caller through to a person/ });
    expect(container.textContent).toContain("we do not try the next person on the same call");
  });

  it("names who a caller would reach right now", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff() }),
    );
    // The panel's own heading, NOT the Card title above it: the title paints immediately
    // and the panel is a skeleton until the query resolves, so awaiting the title would
    // read `textContent` off the loading state — which is how three of these first passed
    // against a panel that had not rendered.
    // The panel's own heading, NOT the Card title above it: the title paints immediately
    // and the panel is a skeleton until the query resolves, so awaiting the title would
    // read `textContent` off the loading state — which is how three of these first passed
    // against a panel that had not rendered.
    await screen.findByRole("heading", { level: 3, name: /Putting a caller through to a person/ });
    expect(container.textContent).toContain("Ravi");
  });

  it("prints the server's own reason and remedy when nobody is on duty", async () => {
    // FIVE CAUSES, and the screen must not collapse them: the fix for "we do not know your
    // opening hours" and the fix for "it is eleven at night" are different actions.
    const { container } = await renderClientPage(
      page,
      routes({
        [HANDOFF_PATH]: handoff({
          on_duty_member_id: null,
          unavailable_reason: "hours_unknown",
          remediation: "We do not know when your business is open, so we will not ring anyone.",
        }),
      }),
    );
    await screen.findByText("Nobody is available to take a call right now.");
    expect(container.textContent).toContain("we will not ring anyone");
  });

  it("tells a client the second recording exists and is kept on the same terms", async () => {
    // A client answering a deletion request has to know a call produced TWO recordings,
    // and what to do about it. The "what to do" half changed with the founder's decision
    // of 5 Sep 2026 — we now hold the second one and the same erasure reaches it — so this
    // assertion moved with the copy rather than being deleted: the row still has to say
    // the second recording exists.
    const { container } = await renderClientPage(
      page,
      routes({
        [HANDOFF_PATH]: handoff({
          recent: [
            {
              id: "h1",
              started_at: "2026-09-03T10:00:00Z",
              member: "Ravi",
              outcome: "connected",
              explanation: "Your caller was put through and someone took the call.",
              duration_s: 120,
              second_recording_at_platform: true,
              callback_id: null,
            },
          ],
        }),
      }),
    );
    await screen.findByText("Recent handovers");
    expect(container.textContent).toContain("recorded separately");
    expect(container.textContent).toContain("same terms as the rest of the call");
    // AND THE WITHDRAWN SENTENCE MUST NOT COME BACK. A screen telling a client to route an
    // erasure to us for something our own erasure already destroys would have them promise
    // their caller a step nobody performs.
    expect(container.textContent).not.toContain("Calevate does not hold");
  });

  it("sends the whole reordered list in one save", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff() }),
    );
    // The panel's own heading, NOT the Card title above it: the title paints immediately
    // and the panel is a skeleton until the query resolves, so awaiting the title would
    // read `textContent` off the loading state — which is how three of these first passed
    // against a panel that had not rendered.
    // The panel's own heading, NOT the Card title above it: the title paints immediately
    // and the panel is a skeleton until the query resolves, so awaiting the title would
    // read `textContent` off the loading state — which is how three of these first passed
    // against a panel that had not rendered.
    await screen.findByRole("heading", { level: 3, name: /Putting a caller through to a person/ });

    fireEvent.click(screen.getAllByRole("button", { name: "Move up" })[1]);
    fireEvent.click(screen.getByRole("button", { name: "Save the list" }));

    await waitFor(() => {
      const put = calls.find((call) => call.method === "PUT" && call.path === HANDOFF_PATH);
      expect(put, "the roster save never went out").toBeTruthy();
      const body = JSON.parse(put?.body ?? "{}") as { members: { label: string }[] };
      // ONE REQUEST CARRYING THE WHOLE ORDER — never a PATCH per row.
      expect(body.members.map((row) => row.label)).toEqual(["Priya", "Ravi"]);
    });
  });
});
