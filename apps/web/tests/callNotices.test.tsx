import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallNoticesPage from "@/app/c/[slug]/settings/call-notices/page";
import type { Agent } from "@/lib/api/agents";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { problem, renderClientPage, type ApiCall } from "./harness";

/*
 * D-1021: one AI switch and one recording switch for every call of the account, on
 * Settings, Call notices. A switch an agent's opening cannot take is refused naming that
 * agent, and its opening line is fixed in place.
 */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Raghava Organics", slug: "acme", status: "active" },
};

const RULE = "The agent never claims to be human. Ask it and it says so.";

function notices(over: Record<string, unknown> = {}) {
  return {
    ai_disclosure_enabled: false,
    recording_notice_enabled: false,
    calls_recorded: true,
    truthful_answer_rule: RULE,
    ...over,
  };
}

const LONG = "a".repeat(180);

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: "agent-1",
    name: "Varsha",
    direction: "outbound",
    status: "live",
    archived_at: null,
    language_primary: "te-IN",
    reply_languages: ["te-IN"],
    disclosure_line: "Idi Raghava Organics AI assistant.",
    ai_disclosure_line: "Idi Raghava Organics AI assistant.",
    ai_disclosure_enabled: false,
    recording_notice_line: "Ee call record avutundi.",
    recording_notice_enabled: false,
    caller_memory_notice_line: "Oka chinna note gurtu pettukuntanu.",
    caller_memory_enabled: false,
    caller_memory_paused: false,
    caller_has_screen: false,
    opening_line: "",
    script_opening_line: LONG,
    first_words: LONG,
    greeting_budget: {
      limit: 200,
      opening_chars: 180,
      opening_room: 200,
      opening_room_with_ai_disclosure: 165,
      opening_room_with_recording_notice: 175,
      opening_advised: 120,
    },
    truthful_answer_rule: RULE,
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
    ...over,
  };
}

const NO_ROOM = problem(422, {
  type: "https://calevate.tech/problems/opening_line_too_long_for_notice",
  title: "Shorten the opening line to switch this on",
  detail:
    "Varsha: Saying that it is an AI assistant adds a sentence your agent says at the start of every call, with its opening line. With it, what the agent says first would be 215 characters, and at most 200 can be spoken there. Nothing was changed.",
  remediation: "Open Varsha's script and change its opening line, then switch this on again.",
  kind: "business_rule",
  retryable: false,
  agent_id: "agent-1",
  agent_name: "Varsha",
});

const aiSwitch = () => screen.getByRole("switch", { name: /Say it is an AI assistant/ }) as HTMLInputElement;

describe("the account's call notices (D-1021)", () => {
  it("puts the truthful-answer guarantee above the switches, in the server's words", async () => {
    const { container } = await renderClientPage(<CallNoticesPage />, {
      "/v1/me": OWNER,
      "/v1/organization/call-notices": notices(),
    });

    const promise = await screen.findByText("The agent never claims to be human.");
    expect(promise.closest("details")).toBeNull();
    expect(screen.getByText("Ask it and it says so.").closest("details")?.open).toBe(false);
    expect(container.textContent).toContain("Ask it and it says so.");
    expect(promise.compareDocumentPosition(aiSwitch()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says plainly what switching each notice off does NOT do", async () => {
    await renderClientPage(<CallNoticesPage />, {
      "/v1/me": OWNER,
      "/v1/organization/call-notices": notices(),
    });

    const recording = await screen.findByRole("switch", { name: /Say the call is being recorded/ });
    const warning = document.getElementById(recording.getAttribute("aria-describedby") ?? "");
    expect(warning?.textContent).toBe("Calls are still recorded. Tell callers another way.");
    expect(warning?.getAttribute("data-notice")).toBe("warn");
    expect(document.getElementById(aiSwitch().getAttribute("aria-describedby") ?? "")?.textContent).toBe(
      "Calls won't bring it up, but always say so if asked.",
    );
  });

  it("sends only the switch that moved, to the account", async () => {
    const { calls } = await renderClientPage(<CallNoticesPage />, {
      "/v1/me": OWNER,
      "/v1/organization/call-notices": notices(),
      "PATCH /v1/organization/call-notices": notices({ ai_disclosure_enabled: true }),
    });

    await waitFor(() => expect(aiSwitch().disabled).toBe(false));
    await act(async () => {
      fireEvent.click(aiSwitch());
    });

    const patched = calls.find((call) => call.method === "PATCH");
    expect(patched?.path).toBe("/v1/organization/call-notices");
    expect(JSON.parse(patched?.body ?? "{}")).toEqual({ ai_disclosure_enabled: true });
    const saved = await screen.findByText("Saved. The next call uses this.");
    expect(saved.getAttribute("role")).toBe("status");
  });

  it("does not hand staff switches the route refuses", async () => {
    const staff = { ...OWNER, role: "staff", permissions: ["agents:read", "org:read"] };
    const { calls } = await renderClientPage(<CallNoticesPage />, {
      "/v1/me": staff,
      "/v1/organization/call-notices": notices(),
    });

    expect(await screen.findByText("Only an account owner can change the call notices.")).toBeTruthy();
    for (const toggle of screen.getAllByRole("switch")) {
      expect(toggle.hasAttribute("disabled")).toBe(true);
      fireEvent.click(toggle);
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
  });

  it("says nothing is announced where calls are not recorded", async () => {
    await renderClientPage(<CallNoticesPage />, {
      "/v1/me": OWNER,
      "/v1/organization/call-notices": notices({ recording_notice_enabled: true, calls_recorded: false }),
    });

    const recording = await screen.findByRole("switch", { name: /Say the call is being recorded/ });
    expect(document.getElementById(recording.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
      "Calls are not recorded now, so nothing is said.",
    );
  });
});

describe("a switch an agent's opening cannot take (D-846, D-865)", () => {
  it("names the agent, fixes its opening line in place and switches on again", async () => {
    let tries = 0;
    const { calls } = await renderClientPage(<CallNoticesPage />, {
      "/v1/me": OWNER,
      "/v1/organization/call-notices": notices(),
      "PATCH /v1/organization/call-notices": () =>
        tries++ === 0 ? NO_ROOM : notices({ ai_disclosure_enabled: true }),
      "/v1/agents/agent-1": agent(),
      "PUT /v1/agents/agent-1/script/opening-line": { opening_line: "Namaskaram", version: 7 },
    });

    await waitFor(() => expect(aiSwitch().disabled).toBe(false));
    fireEvent.click(aiSwitch());
    await screen.findByRole("button", { name: "Save and switch on" });
    // The AI notice's room, from the named agent's own budget.
    expect(screen.getByText("15 characters too long")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Varsha" }).getAttribute("href")).toContain(
      "/agents/agent-1",
    );
    fireEvent.change(screen.getByLabelText("Opening line"), { target: { value: "Namaskaram" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and switch on" }));
    await waitFor(() => expect(tries).toBe(2));
    const patches = calls.filter((c: ApiCall) => c.method === "PATCH");
    expect(patches.map((c) => JSON.parse(c.body ?? "{}"))).toEqual([
      { ai_disclosure_enabled: true },
      { ai_disclosure_enabled: true },
    ]);
  });

  it("offers Pip to shorten it, prefilled with the room and never sent", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await renderClientPage(<CallNoticesPage />, {
      "/v1/me": OWNER,
      "/v1/organization/call-notices": notices(),
      "PATCH /v1/organization/call-notices": NO_ROOM,
      "/v1/agents/agent-1": agent(),
    });
    await waitFor(() => expect(aiSwitch().disabled).toBe(false));
    fireEvent.click(aiSwitch());
    fireEvent.click(await screen.findByRole("button", { name: /Ask Pip to shorten it/ }));
    expect(asked.map((a) => a.prompt)).toEqual([
      "Shorten the opening line of Varsha to at most 165 characters, in the same language, keeping what it says.",
    ]);
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("refused because the opening already says who is calling, the owner rewrites the line", async () => {
    const introduces = problem(409, {
      type: "https://calevate.tech/problems/opening_introduces_agent",
      title: "The opening line already says who is calling",
      detail: "Varsha: With this on, your agent says who it is before the opening line, so callers would hear it twice.",
      remediation: "Open Varsha's script and change its opening line, then switch this on again.",
      kind: "conflict",
      retryable: false,
      agent_id: "agent-1",
      agent_name: "Varsha",
    });
    let tries = 0;
    const { calls } = await renderClientPage(<CallNoticesPage />, {
      "/v1/me": OWNER,
      "/v1/organization/call-notices": notices(),
      "PATCH /v1/organization/call-notices": () =>
        tries++ === 0 ? introduces : notices({ ai_disclosure_enabled: true }),
      "/v1/agents/agent-1": agent({ script_opening_line: "Namaskaram, Raghava Organics nundi." }),
      "PUT /v1/agents/agent-1/script/opening-line": { opening_line: "Emi kavali andi?", version: 8 },
    });
    await waitFor(() => expect(aiSwitch().disabled).toBe(false));
    fireEvent.click(aiSwitch());
    expect(await screen.findByRole("button", { name: /Ask .* to rewrite it/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Opening line"), { target: { value: "Emi kavali andi?" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and switch on" }));
    await waitFor(() => expect(tries).toBe(2));
    const put = calls.find((c: ApiCall) => c.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ opening_line: "Emi kavali andi?", when: "answers" });
  });
});
