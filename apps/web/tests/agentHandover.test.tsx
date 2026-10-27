import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AgentDetailPage from "@/app/c/[slug]/agents/[agentId]/page";
import type { Agent, HandoffOut } from "@/lib/api/agents";

import { renderClientPage } from "./harness";
import {
  AGENT_SPEND_PATH,
  LANES,
  agentScript,
  clientLlmTiers,
  spendThisMonth,
  agentCallHandling,
  organizationCallHandling,
} from "./fixtures/sharedReads";

// The handover panel lives in the workspace's Call handling section (D-657), so every test
// here opens that section.
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("section=calls"),
  usePathname: () => "/c/acme/agents/agent-1",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

/**
 * PUTTING A CALLER THROUGH TO A PERSON — the client's own screen (D-533).
 *
 * Four things can be wrong here, in falling order of what a wrong render costs, and every
 * one of them is a promise the CLIENT would repeat to their own callers:
 *
 * 1. **Implying the person answering is briefed first.** They are not. The voice platform
 *    places the transfer on its own carrier account and nothing plays a message to the
 *    called party — so a screen that said "your team hears why the call is coming" would
 *    have a shop owner tell their customers so. The panel says the opposite under "How it
 *    works", and this file pins the sentence.
 * 2. **Implying the list is tried in turn during the call.** The platform allows one
 *    handover per conversation. The order decides who is CHOSEN before the call; a
 *    handover nobody answers becomes a call-back, not a second ring.
 * 3. **Warning when nothing needs doing, or staying quiet when it does.** A warning shows
 *    only when transfer is on and nobody is chosen, or the server says the opening hours
 *    are missing; the switch itself says when it is off.
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
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
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
  reply_languages: ["te-IN"],
  disclosure_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_enabled: true,
  recording_notice_line: "This call is being recorded.",
  caller_memory_notice_line: "I keep a short note of what you ask about.",
  caller_memory_enabled: false,
  recording_notice_enabled: true,
  opening_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
  script_opening_line: "",
  first_words: "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
  truthful_answer_rule:
    "Whatever these settings say, the agent always answers honestly when a caller asks.",
  engine: "thinnest",
  published: true,
  inbound_number_count: 1,
  extraction_fields: [],
  extraction_schema_version: 0,
  llm_tier: null,
  llm_tier_effective: "standard",
  llm_tier_label: "Standard",
  llm_tier_source: "platform",
  llm_surcharged: false,
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
  precedence_rule:
    "Script decides content, rules decide conduct, voice only changes delivery.",
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
    "/v1/agents/agent-1/call-handling": agentCallHandling(),
    "/v1/organization/call-handling": organizationCallHandling(),
    "/v1/agents/agent-1/script": agentScript(),
    "/v1/kb/sources": [],
    "/v1/organization/llm-defaults": clientLlmTiers({ available: [] }),
    "/v1/agents/agent-1/actions": {
      api_actions_enabled: false,
      calendar_available: false,
      tools: [],
    },
    "/v1/integrations/credentials": [],
    "/v1/teach/questions?agent_id=agent-1": { items: [], open_count: 0 },
    "/v1/agents/lanes": LANES,
    // The header's "spent this month" line (owners hold billing:read).
    [AGENT_SPEND_PATH]: spendThisMonth(),
    "/v1/business-profile": PROFILE,
    ...over,
  };
}

const page = (
  <AgentDetailPage
    params={Promise.resolve({ slug: "acme", agentId: "agent-1" })}
  />
);

const HANDOFF_PATH = "/v1/agents/agent-1/handoff";

/** The business profile the list picks people from (D-695). */
const PROFILE = {
  business_name: "Sri Clinic",
  legal_name: null,
  vertical_template: "clinic",
  hours: [],
  branches: [],
  services: [],
  faqs: [],
  staff: [],
  booking_rules: null,
  contacts: [
    { id: "c1", label: "Ravi", phone_e164: "+919000000001", note: null },
    { id: "c2", label: "Priya", phone_e164: "+919000000002", note: null },
  ],
  languages: [],
  setup: { steps: [], started: true, dismissed: false, complete: false },
  blockers: [],
  updated_at: null,
  agents_updated: null,
};

function member(
  over: Partial<HandoffOut["members"][number]> = {},
): HandoffOut["members"][number] {
  return {
    id: "m1",
    contact_id: "c1",
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
    effective_trigger:
      "Hand the call to a person when the caller asks to speak to a human.",
    spoken_line: "Okay, I am putting you through to someone from our team now.",
    members: [
      member(),
      member({
        id: "m2",
        contact_id: "c2",
        position: 1,
        label: "Priya",
        phone_e164: "+919000000002",
        on_duty: false,
      }),
    ],
    recent: [],
    on_duty_member_id: "m1",
    unavailable_reason: null,
    remediation: null,
    published: true,
    ...over,
  };
}

/** The panel's own heading: the card title paints before the query resolves. */
const panelHeading = () =>
  screen.findByRole("heading", { level: 3, name: "Transfer to a person" });

const WARNING = "Nobody is chosen to take calls.";

describe("what the handover panel promises about the person answering", () => {
  it("says plainly that nobody is briefed before they pick up", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff() }),
    );
    await panelHeading();
    // THE SENTENCE THAT MUST NOT DISAPPEAR, now under "How it works". If a future edit
    // removes it, a client is left to assume the founder's original request was built.
    expect(screen.getAllByRole("heading", { level: 4, name: "How it works" }).length).toBeGreaterThan(0);
    expect(container.textContent).toContain("Your team member is not briefed first.");
  });

  it("says a missed handover becomes a call-back rather than a second ring", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff() }),
    );
    await panelHeading();
    expect(container.textContent).toContain(
      "If they miss it, the agent books a call-back.",
    );
  });

  it("names who a caller would reach right now", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff() }),
    );
    await panelHeading();
    expect(container.textContent).toContain("Right now, callers reach Ravi");
  });

  it("states where live transfer works when the server says it depends on the number", async () => {
    const note = "Live transfer works on numbers rented through Calevate.";
    const { container } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff({ platform_note: note }) }),
    );
    await panelHeading();
    expect(container.textContent).toContain(note);
  });

  it("prints the server's remedy when the opening hours are missing", async () => {
    // The fix for "we do not know your opening hours" is an action, so it is a warning.
    const { container } = await renderClientPage(
      page,
      routes({
        [HANDOFF_PATH]: handoff({
          on_duty_member_id: null,
          unavailable_reason: "hours_unknown",
          remediation: "Add your opening hours so we know when to ring your team.",
        }),
      }),
    );
    await panelHeading();
    expect(container.textContent).toContain("Add your opening hours");
  });
});

describe("the hand-over warning appears only when the owner has something to do", () => {
  it("warns when transfer is on and nobody is chosen", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        [HANDOFF_PATH]: handoff({
          members: [],
          on_duty_member_id: null,
          unavailable_reason: "no_members",
          remediation: "Nobody is chosen to take calls. Add someone from your team.",
        }),
      }),
    );
    await panelHeading();
    expect(container.textContent).toContain(WARNING);
  });

  it("warns when transfer is on and everyone chosen is switched off", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        [HANDOFF_PATH]: handoff({
          members: [member({ active: false, on_duty: false })],
          on_duty_member_id: null,
          unavailable_reason: "none_active",
          remediation: "Everyone on the list is switched off.",
        }),
      }),
    );
    await panelHeading();
    expect(container.textContent).toContain(WARNING);
  });

  it("shows no warning when transfer is off, even with nobody chosen", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        [HANDOFF_PATH]: handoff({
          enabled: false,
          members: [],
          on_duty_member_id: null,
          unavailable_reason: "disabled",
          remediation: "Transfer to a person is off for this agent. Turn it on to use it.",
        }),
      }),
    );
    await panelHeading();
    expect(container.textContent).not.toContain(WARNING);
    // The switch already says it is off; no box restates it.
    expect(container.textContent).not.toContain("Transfer to a person is off");
  });

  it("shows no warning when transfer is on and someone is chosen", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [HANDOFF_PATH]: handoff() }),
    );
    await panelHeading();
    expect(container.textContent).not.toContain(WARNING);
  });
});

describe("recent handovers and saving the list", () => {
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
              explanation:
                "Your caller was put through and someone took the call.",
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
    expect(container.textContent).toContain(
      "same terms as the rest of the call",
    );
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
    await panelHeading();

    // The editor fails closed until `/v1/me` has said this session holds `org:manage`.
    const moveUp = screen.getAllByRole("button", { name: "Move up" })[1];
    await waitFor(() => expect(moveUp.hasAttribute("disabled")).toBe(false));
    fireEvent.click(moveUp);
    fireEvent.click(screen.getByRole("button", { name: "Save the list" }));

    await waitFor(() => {
      const put = calls.find(
        (call) => call.method === "PUT" && call.path === HANDOFF_PATH,
      );
      expect(put, "the roster save never went out").toBeTruthy();
      const body = JSON.parse(put?.body ?? "{}") as {
        members: { contact_id: string }[];
      };
      // ONE REQUEST CARRYING THE WHOLE ORDER — never a PATCH per row.
      expect(body.members.map((row) => row.contact_id)).toEqual(["c2", "c1"]);
    });
  });

  it("gives staff a read-only list rather than an editor the save refuses", async () => {
    // `PUT /v1/agents/{id}/handoff` is `org:manage`, which `staff` does not hold
    // (`core/rbac.ROLE_PERMISSIONS`); the panel itself is readable on `agents:read`.
    const staff = {
      ...OWNER,
      role: "staff",
      permissions: ["agents:read", "agents:write", "calls:read", "org:read"],
    };
    const { calls } = await renderClientPage(
      page,
      routes({ "/v1/me": staff, [HANDOFF_PATH]: handoff() }),
    );
    await screen.findByText(
      "Only an account owner can change who calls are put through to.",
    );

    for (const name of ["Move up", "Move down", "Save the list"]) {
      for (const button of screen.getAllByRole("button", { name })) {
        expect(button.matches(":disabled"), `${name} is pressable`).toBe(true);
      }
    }
    for (const box of screen.getAllByRole("textbox", { name: "Note for this agent (optional)" })) {
      expect(box.matches(":disabled")).toBe(true);
    }
    fireEvent.click(screen.getAllByRole("button", { name: "Move up" })[1]);
    fireEvent.click(screen.getByRole("button", { name: "Save the list" }));
    expect(calls.some((call) => call.method === "PUT")).toBe(false);
  });
});
