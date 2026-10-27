import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { READ_FILE_REQUEST } from "@/app/c/[slug]/knowledge/TeachBox";
import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import { MAKE_TEST_REQUEST, MakeCallTest } from "@/components/improvement/MakeCallTest";
import { SavedTests } from "@/components/improvement/SavedTests";
import { TryChat } from "@/components/improvement/TryChat";
import type { Me } from "@/lib/api/client";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { noContent, problem, renderClientPage, type Routes } from "./harness";

/**
 * The teach box and the improvement loop (founder decisions 9 and 11). Each test names the
 * failure it guards: an owner's words saved without review, a rule saved with no agent, a
 * voice note sorted before its words are checked, and
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
    "/v1/kb/notes": { notes: [] },
    "/v1/kb/uploads": [],
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
    "/v1/teach/questions": { items: [], open_count: 0 },
    "/v1/kb/teach/open": { teaching: null },
    ...over,
  });
}

describe("the teach box", () => {
  it("shows what Pip sorted for review, lets a fact become a rule, and asks which agent", async () => {
    const { calls } = await renderKnowledge({
      "/v1/kb/teach/open": { teaching: teaching() },
      "POST /v1/kb/teach/teach-1/save": { facts_added: 1, rules_added: 1, agent_id: "agent-2" },
    });

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
      "/v1/kb/teach/open": { teaching: teaching() },
      "POST /v1/kb/teach/teach-1/save": { facts_added: 1, rules_added: 0, agent_id: null },
    });
    fireEvent.click(await screen.findByLabelText("Keep: Never promise same-day delivery."));
    fireEvent.click(screen.getByRole("button", { name: "Save 1 fact" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/v1/kb/teach/teach-1/save")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.path === "/v1/kb/teach/teach-1/save")?.body ?? "{}");
    expect(body.items).toEqual([{ kind: "fact", text: "Chilli powder is 120 rupees.", pinned: false }]);
    expect(body.agent_id).toBeNull();
  });

  it("asks Pip to teach the words in the box, and to read a photo or file attached to it", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await renderKnowledge();
    fireEvent.change(await screen.findByLabelText("What should your agents know?"), {
      target: { value: "Chilli powder is 120 rupees." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Let Pip teach it" }));
    // Pip reading a file sits with the other file path, in the Add area's File view.
    fireEvent.click(screen.getByRole("radio", { name: "File" }));
    fireEvent.click(screen.getByRole("button", { name: /^Let Pip read a photo or file: / }));
    expect(asked.map((a) => a.prompt)).toEqual([
      "Teach my agents this: Chilli powder is 120 rupees.",
      READ_FILE_REQUEST,
    ]);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("puts the words heard in a voice note in the box to check, and sorts nothing", async () => {
    class SpeakingRecorder {
      static isTypeSupported = () => true;
      mimeType = "audio/webm";
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      start() {}
      stop() {
        this.ondataavailable?.({ data: new Blob(["voice"], { type: "audio/webm" }) });
        this.onstop?.();
      }
    }
    vi.stubGlobal("MediaRecorder", SpeakingRecorder);
    // The upload is the one request that is an XMLHttpRequest (`apiUpload`); it answers
    // with the voice teaching, which the screen then reads until it is heard.
    const uploaded: string[] = [];
    class UploadXhr {
      status = 0;
      responseText = "";
      withCredentials = false;
      readonly upload = new EventTarget();
      private readonly events = new EventTarget();
      private url = "";
      open(_method: string, url: string): void {
        this.url = url;
      }
      setRequestHeader(): void {}
      getResponseHeader(): string {
        return "application/json";
      }
      addEventListener(type: string, listener: EventListener): void {
        this.events.addEventListener(type, listener);
      }
      abort(): void {}
      send(): void {
        uploaded.push(this.url);
        queueMicrotask(() => {
          this.status = 201;
          this.responseText = JSON.stringify(
            teaching({ status: "reading", input_kind: "voice", words: null, items: [] }),
          );
          this.events.dispatchEvent(new Event("load"));
        });
      }
    }
    vi.stubGlobal("XMLHttpRequest", UploadXhr);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    });
    Object.defineProperty(navigator, "permissions", {
      configurable: true,
      value: { query: vi.fn(async () => ({ state: "granted" })) },
    });
    try {
      const heard = teaching({ status: "heard", input_kind: "voice", words: "Chilli 120", items: [] });
      const { calls } = await renderKnowledge({

        "/v1/kb/teach/teach-1": heard,
        "POST /v1/kb/teach/teach-1/discard": { ...heard, status: "discarded" },
      });
      await act(async () => {
        fireEvent.click(await screen.findByRole("button", { name: "Say it" }));
      });
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /Stop/ }));
      });
      const box = screen.getByLabelText("What should your agents know?") as HTMLTextAreaElement;
      await waitFor(() => expect(box.value).toBe("Chilli 120"));
      await waitFor(() => expect(calls.some((c) => c.path === "/v1/kb/teach/teach-1/discard")).toBe(true));
      expect(calls.some((c) => c.path.endsWith("/save"))).toBe(false);
      expect(uploaded.some((url) => url.endsWith("/v1/kb/teach/upload"))).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
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
        pinned_not_yet_on: [],
      },
      // Files and links are drawn from the uploads list, which carries each one's kind.
      "/v1/kb/uploads": [
        {
          id: "u1",
          source_id: "s1",
          name: "Our menu",
          source_kind: "url",
          ingest_status: "processed",
          ingest_detail: null,
          review_state: "approved",
          is_live: true,
          version: 1,
          filename: null,
          byte_size: null,
          source_url: "https://example.in/menu",
          text_provenance: null,
          change_detected_at: null,
        },
      ],
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

  it("names each agent that does not have the pinned facts yet, and links to its script", async () => {
    await renderKnowledge({
      "/v1/kb/knows": {
        facts: [
          { id: "f1", text: "Closed on Sundays.", question: null, pinned: true, origin: "quick_fact", created_at: "2026-10-10T10:00:00Z" },
        ],
        facts_state: "live",
        items: [],
        pinned_not_yet_on: [
          {
            agent_id: "agent-1",
            agent_name: "Front desk",
            reason: "waiting_put_live",
            sentence: "Not yet on Front desk: it has script changes waiting.",
          },
          {
            agent_id: "agent-2",
            agent_name: "Caller",
            reason: "on_the_way",
            sentence: "Being added to Caller. This takes a minute.",
          },
        ],
      },
    });
    const list = await screen.findByRole("list", { name: "Agents that do not have these facts yet" });
    expect(within(list).getByText(/Not yet on Front desk/)).toBeTruthy();
    expect(within(list).getByText(/Being added to Caller/)).toBeTruthy();
    const link = within(list).getByRole("link", { name: "Open Front desk’s script" });
    expect(link.getAttribute("href")).toContain("/agents/agent-1?section=script");
    expect(within(list).getAllByRole("link")).toHaveLength(1);
  });
});

describe("make this call a test", () => {
  const DRAFT = {
    call_id: "call-9",
    agent_id: "agent-1",
    agent_name: "Front desk",
    caller_lines: ["naa number [phone], chilli undha?"],
    title: "Asked about chilli",
  };
  const SAVED = {
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
  };

  it("asks Pip to make the test and saves nothing itself", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await renderClientPage(<MakeCallTest callId="call-9" />, {
      "/v1/me": ME,
      "/v1/calls/call-9/test-case-draft": { ...DRAFT, pending: null },
    });
    fireEvent.click(await screen.findByRole("button", { name: /^Let Pip make this call a test: / }));
    expect(asked.map((a) => a.prompt)).toEqual([MAKE_TEST_REQUEST]);
    expect(screen.queryByLabelText("What should the agent do?")).toBeNull();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("opens the form Pip filled in for the person to check, change and save", async () => {
    const { calls } = await renderClientPage(<MakeCallTest callId="call-9" />, {
      "/v1/me": ME,
      "/v1/calls/call-9/test-case-draft": {
        ...DRAFT,
        pending: { expected: "Gives the chilli price.", title: null },
      },
      "POST /v1/calls/call-9/test-case": SAVED,
    });
    const line = (await screen.findByLabelText("Caller line 1")) as HTMLInputElement;
    expect(line.value).toBe("naa number [phone], chilli undha?");
    const expected = screen.getByLabelText("What should the agent do?") as HTMLTextAreaElement;
    expect(expected.value).toBe("Gives the chilli price.");
    fireEvent.change(expected, { target: { value: "Looks up chilli and gives the price." } });
    fireEvent.click(screen.getByRole("button", { name: "Save test" }));
    await waitFor(() =>
      expect(JSON.parse(calls.find((c) => c.path === "/v1/calls/call-9/test-case")?.body ?? "{}")).toEqual({
        title: "Asked about chilli",
        caller_lines: ["naa number [phone], chilli undha?"],
        expected: "Looks up chilli and gives the price.",
      }),
    );
  });

  it("discards what Pip filled in", async () => {
    const { calls } = await renderClientPage(<MakeCallTest callId="call-9" />, {
      "/v1/me": ME,
      "/v1/calls/call-9/test-case-draft": { ...DRAFT, pending: { expected: null, title: null } },
      "DELETE /v1/calls/call-9/test-case-draft/pending": noContent(),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "DELETE" && c.path === "/v1/calls/call-9/test-case-draft/pending"),
      ).toBe(true),
    );
    expect(calls.some((c) => c.method === "POST")).toBe(false);
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
      ...chatReadiness(null),
      "POST /v1/agents/agent-1/try-chat": {
        session: "vr_1",
        reply: "Avunu andi, 120 rupees.",
        looked_up_knowledge: true,
        cut_short: false,
        cost_note: "Replies here are not charged.",
      },
    });
    fireEvent.change(await screen.findByLabelText("What the caller says"), { target: { value: "chilli undha?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Avunu andi, 120 rupees.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("What the caller says"), { target: { value: "delivery?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/v1/agents/agent-1/try-chat")).toHaveLength(2));
    const second = JSON.parse(calls.filter((c) => c.path === "/v1/agents/agent-1/try-chat")[1]?.body ?? "{}");
    expect(second).toEqual({ message: "delivery?", session: "vr_1" });
  });

  it("shows the server's sentence instead of a chat box until the agent is ready", async () => {
    const reason = "Chats and tests talk to the agent as the calling system holds it, so they open once it is ready.";
    const { calls } = await renderClientPage(<TryChat agentId="agent-1" />, {
      "/v1/me": ME,
      ...chatReadiness(reason),
    });
    expect(await screen.findByText(reason)).toBeTruthy();
    expect(screen.queryByLabelText("What the caller says")).toBeNull();
    expect(calls.some((c) => c.path.endsWith("/try-chat"))).toBe(false);
  });

  it("keeps what was typed when a send is refused", async () => {
    await renderClientPage(<TryChat agentId="agent-1" />, {
      "/v1/me": ME,
      ...chatReadiness(null),
      "POST /v1/agents/agent-1/try-chat": problem(409, {
        code: "ai_assist_exhausted",
        title: "This month's AI help is used up.",
        detail: "This month's AI help is used up.",
      }),
    });
    const box = (await screen.findByLabelText("What the caller says")) as HTMLInputElement;
    fireEvent.change(box, { target: { value: "chilli undha?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/AI help is used up/)).toBeTruthy();
    expect(box.value).toBe("chilli undha?");
    expect(screen.queryByText("chilli undha?", { selector: "li" })).toBeNull();
  });
});

/** `GET .../script/tests`, which says whether the agent can be talked to yet. */
function chatReadiness(unavailable: string | null): Routes {
  return {
    "/v1/agents/agent-1/script/tests": {
      available: unavailable === null,
      unavailable_reason: unavailable,
      cost_note: "",
      latest: null,
      history: [],
    },
  };
}
