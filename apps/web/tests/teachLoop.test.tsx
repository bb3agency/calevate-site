import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import { MakeCallTest } from "@/components/improvement/MakeCallTest";
import { SavedTests } from "@/components/improvement/SavedTests";
import { TryChat } from "@/components/improvement/TryChat";
import type { Me } from "@/lib/api/client";

import { noContent, renderClientPage, type Routes } from "./harness";

/**
 * The teach box and the improvement loop (founder decisions 9 and 11). Each test names the
 * failure it guards: an owner's words saved without review, a rule saved with no agent, a
 * voice note sorted before its words are checked, a struggle that cannot be acted on, and
 * a test from a call that copies more than the caller's redacted lines.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "agents:write", "calls:read", "kb:write", "org:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENTS = [
  { id: "agent-1", name: "Front desk", status: "live", direction: "inbound", language_primary: "te-IN", extraction_fields: [] },
  { id: "agent-2", name: "Orders", status: "live", direction: "outbound", language_primary: "te-IN", extraction_fields: [] },
];

function teaching(over: Record<string, unknown> = {}) {
  return {
    id: "teach-1",
    status: "ready",
    input_kind: "text",
    words: "Chilli powder is 120 rupees. Never promise same-day delivery.",
    items: [
      { kind: "fact", text: "Chilli powder is 120 rupees.", pinned: false },
      { kind: "fact", text: "Never promise same-day delivery.", pinned: false },
    ],
    agent_id: null,
    gap_id: null,
    note: null,
    error_code: null,
    created_at: "2026-10-10T10:00:00Z",
    ...over,
  };
}

async function renderKnowledge(over: Routes = {}) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": ME,
    "/v1/agents": AGENTS,
    "/v1/kb/sources": [],
    "/v1/kb/uploads": [],
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/delivery": { items: [], not_delivered_count: 0 },
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [] },
    ...over,
  });
}

describe("the teach box", () => {
  it("shows what was found for review, lets a fact become a rule, and asks which agent", async () => {
    const { calls } = await renderKnowledge({
      "POST /v1/kb/teach": teaching({ status: "queued", items: [] }),
      "/v1/kb/teach/teach-1": teaching(),
      "POST /v1/kb/teach/teach-1/save": { facts_added: 1, rules_added: 1, agent_id: "agent-2" },
    });
    fireEvent.change(await screen.findByLabelText("What should your agents know?"), {
      target: { value: "Chilli powder is 120 rupees. Never promise same-day delivery." },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Sort it$/ }));

    const list = await screen.findByRole("list", { name: "Check what we found" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    fireEvent.click(within(rows[1]!).getByRole("button", { name: "It's a rule" }));

    // A rule belongs to one agent: with two, nothing is saved until one is chosen.
    const save = screen.getByRole("button", { name: "Save 1 fact and 1 rule" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Which agent are the rules for?"), {
      target: { value: "agent-2" },
    });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/kb/teach/teach-1/save")).toBe(true),
    );
    const posted = calls.find((c) => c.path === "/v1/kb/teach/teach-1/save");
    expect(JSON.parse(posted?.body ?? "{}")).toEqual({
      items: [
        { kind: "fact", text: "Chilli powder is 120 rupees.", pinned: false },
        { kind: "rule", text: "Never promise same-day delivery.", pinned: false },
      ],
      agent_id: "agent-2",
    });
  });

  it("does not save what the owner unticked", async () => {
    const { calls } = await renderKnowledge({
      "POST /v1/kb/teach": teaching({ status: "queued", items: [] }),
      "/v1/kb/teach/teach-1": teaching(),
      "POST /v1/kb/teach/teach-1/save": { facts_added: 1, rules_added: 0, agent_id: null },
    });
    fireEvent.change(await screen.findByLabelText("What should your agents know?"), {
      target: { value: "Chilli powder is 120 rupees." },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Sort it$/ }));
    fireEvent.click(await screen.findByLabelText("Keep: Never promise same-day delivery."));
    fireEvent.click(screen.getByRole("button", { name: "Save 1 fact" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/v1/kb/teach/teach-1/save")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.path === "/v1/kb/teach/teach-1/save")?.body ?? "{}");
    expect(body.items).toEqual([{ kind: "fact", text: "Chilli powder is 120 rupees.", pinned: false }]);
    expect(body.agent_id).toBeNull();
  });

  it("shows the words heard in a voice note before anything is sorted", async () => {
    const { calls } = await renderKnowledge({
      "POST /v1/kb/teach": teaching({ status: "queued", items: [] }),
      "/v1/kb/teach/teach-1": teaching({ status: "heard", input_kind: "voice", words: "Chilli 120", items: [] }),
      "POST /v1/kb/teach/teach-1/words": teaching({ status: "queued", words: "Chilli is ₹120", items: [] }),
    });
    fireEvent.change(await screen.findByLabelText("What should your agents know?"), {
      target: { value: "Chilli 120" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Sort it$/ }));
    const heard = (await screen.findByLabelText(
      "This is what we heard. Fix anything we got wrong.",
    )) as HTMLTextAreaElement;
    expect(heard.value).toBe("Chilli 120");
    expect(calls.some((c) => c.path === "/v1/kb/teach/teach-1/save")).toBe(false);
    fireEvent.change(heard, { target: { value: "Chilli is ₹120" } });
    fireEvent.click(screen.getByRole("button", { name: /^Sort it$/ }));
    await waitFor(() =>
      expect(JSON.parse(calls.find((c) => c.path === "/v1/kb/teach/teach-1/words")?.body ?? "{}")).toEqual({
        words: "Chilli is ₹120",
      }),
    );
  });
});

describe("what it knows", () => {
  it("marks pinned facts and moves one up by sending the whole order", async () => {
    const { calls } = await renderKnowledge({
      "/v1/kb/knows": {
        facts: [
          { id: "f1", text: "Closed on Sundays.", question: null, pinned: true, origin: "quick_fact", created_at: "2026-10-10T10:00:00Z" },
          { id: "f2", text: "9 to 9", question: "Hours?", pinned: true, origin: "quick_fact", created_at: "2026-10-10T10:00:00Z" },
          { id: "f3", text: "We deliver in Kukatpally.", question: null, pinned: false, origin: "taught", created_at: "2026-10-10T10:00:00Z" },
        ],
        facts_state: "live",
        items: [
          { id: "u1", kind: "page", name: "Our menu", state: "live", url: "https://example.in/menu", updated_at: null },
        ],
      },
      "POST /v1/kb/facts/pinned-order": noContent(),
    });
    const pinned = await screen.findByRole("list", { name: "Pinned facts" });
    expect(within(pinned).getAllByLabelText("Pinned")).toHaveLength(2);
    expect(within(pinned).getByText("Hours?")).toBeTruthy();
    expect(screen.getByText("We deliver in Kukatpally.")).toBeTruthy();
    expect(screen.getByText("Our menu")).toBeTruthy();
    fireEvent.click(within(pinned).getAllByRole("button", { name: "Move up" })[1]!);
    await waitFor(() =>
      expect(JSON.parse(calls.find((c) => c.path === "/v1/kb/facts/pinned-order")?.body ?? "{}")).toEqual({
        ids: ["f2", "f1"],
      }),
    );
  });
});

describe("where it struggled", () => {
  it("links each struggle to its call and its script, and opens the teach box to answer it", async () => {
    await renderKnowledge({
      "/v1/kb/struggles": [
        {
          id: "g1",
          kind: "didnt_know",
          gap_id: "g1",
          agent_id: "agent-1",
          agent_name: "Front desk",
          topic: "Chilli",
          question: "Do you have chilli?",
          answer: "I don't know.",
          times: 3,
          calls: 2,
          last_call_id: "call-9",
          last_seen_at: "2026-10-10T10:00:00Z",
        },
      ],
    });
    fireEvent.click(await screen.findByRole("tab", { name: "Where it struggled" }));
    expect((await screen.findByRole("link", { name: "Open the call" })).getAttribute("href")).toBe(
      "/c/acme/calls/call-9",
    );
    expect(screen.getByRole("link", { name: "Fix in script" }).getAttribute("href")).toBe(
      "/c/acme/agents/agent-1/script#stages",
    );
    fireEvent.click(screen.getByRole("button", { name: "Add the answer" }));
    expect(await screen.findByText(/Answering a caller who asked/)).toBeTruthy();
  });
});

describe("make this call a test", () => {
  it("starts from the caller's redacted lines and saves what the agent should do", async () => {
    const { calls } = await renderClientPage(<MakeCallTest callId="call-9" />, {
      "/v1/me": ME,
      "/v1/calls/call-9/test-case-draft": {
        call_id: "call-9",
        agent_id: "agent-1",
        agent_name: "Front desk",
        caller_lines: ["naa number [phone], chilli undha?"],
        title: "Asked about chilli",
      },
      "POST /v1/calls/call-9/test-case": {
        id: "case-1",
        agent_id: "agent-1",
        source_call_id: "call-9",
        title: "Asked about chilli",
        caller_lines: ["naa number [phone], chilli undha?"],
        expected: "Gives the chilli price.",
        status: "idle",
        last_result: null,
        last_error: null,
        last_run_at: null,
        last_prompt_version: null,
        created_at: "2026-10-10T10:00:00Z",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Make this call a test" }));
    const line = (await screen.findByLabelText("Caller line 1")) as HTMLInputElement;
    expect(line.value).toBe("naa number [phone], chilli undha?");
    fireEvent.change(screen.getByLabelText("What should the agent do?"), {
      target: { value: "Gives the chilli price." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save test" }));
    await waitFor(() =>
      expect(JSON.parse(calls.find((c) => c.path === "/v1/calls/call-9/test-case")?.body ?? "{}")).toEqual({
        title: "Asked about chilli",
        caller_lines: ["naa number [phone], chilli undha?"],
        expected: "Gives the chilli price.",
      }),
    );
  });
});

describe("saved tests and the chat", () => {
  it("shows what the live agent said on the last run and runs them again", async () => {
    const { calls } = await renderClientPage(<SavedTests agentId="agent-1" />, {
      "/v1/me": ME,
      "/v1/agents/agent-1/test-cases": {
        cases: [
          {
            id: "case-1",
            agent_id: "agent-1",
            source_call_id: "call-9",
            title: "Asked about chilli",
            caller_lines: ["chilli undha?"],
            expected: "Gives the chilli price.",
            status: "idle",
            last_result: [{ said: "chilli undha?", reply: "Avunu, 120 rupees.", looked_up_knowledge: true, cut_short: false }],
            last_error: null,
            last_run_at: "2026-10-10T10:00:00Z",
            last_prompt_version: 3,
            created_at: "2026-10-10T10:00:00Z",
          },
        ],
        available: true,
        unavailable_reason: null,
        live_version: 4,
        cost_note: "Replies here are not charged.",
      },
      "POST /v1/agents/agent-1/test-cases/run": {
        cases: [],
        available: true,
        unavailable_reason: null,
        live_version: 4,
        cost_note: "Replies here are not charged.",
      },
    });
    expect(await screen.findByText("Agent: Avunu, 120 rupees.", { exact: false })).toBeTruthy();
    expect(screen.getByText(/before your latest change/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Run all" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/agents/agent-1/test-cases/run")).toBe(true),
    );
  });

  it("chats with the live agent and keeps the conversation going", async () => {
    const { calls } = await renderClientPage(<TryChat agentId="agent-1" />, {
      "/v1/me": ME,
      "POST /v1/agents/agent-1/try-chat": {
        session: "vr_1",
        reply: "Avunu andi, 120 rupees.",
        looked_up_knowledge: true,
        cut_short: false,
        cost_note: "Replies here are not charged.",
      },
    });
    fireEvent.change(screen.getByLabelText("What the caller says"), { target: { value: "chilli undha?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Avunu andi, 120 rupees.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("What the caller says"), { target: { value: "delivery?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/v1/agents/agent-1/try-chat")).toHaveLength(2));
    const second = JSON.parse(calls.filter((c) => c.path === "/v1/agents/agent-1/try-chat")[1]?.body ?? "{}");
    expect(second).toEqual({ message: "delivery?", session: "vr_1" });
  });
});
