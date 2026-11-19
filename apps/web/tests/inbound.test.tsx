import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import InboundLinePage from "@/app/c/[slug]/inbound/[lineId]/page";
import InboundPage from "@/app/c/[slug]/inbound/page";
import type { ActionsSettings, ActionTool } from "@/lib/api/actions";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";
import type { InboundLine } from "@/lib/api/inboundLines";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";

import { businessProfileFixture } from "./businessProfileFixture";
import { renderClientPage, type ApiCall, type Routes } from "./harness";
import { SHORT_LINE, defaultCopyUnder, longLines } from "./shortCopy";

/**
 * Inbound (D-997): the list of lines and one line's page. A line says what the business's
 * numbers say when called, in one agent's voice; these tests drive its writes over the wire.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "org:read", "org:manage", "leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENT_ID = "0192f0aa-3333-7000-8000-000000000002";
const OTHER_AGENT_ID = "0192f0aa-3333-7000-8000-000000000003";
const LINE_ID = "0192f0aa-4444-7000-8000-000000000001";
const OTHER_LINE_ID = "0192f0aa-4444-7000-8000-000000000002";

function agent(id: string, name: string): Agent {
  return {
    id,
    name,
    direction: "inbound",
    status: "live",
    language_primary: "te-IN",
    reply_languages: ["te-IN"],
    disclosure_line: "Namaskaram, this is an AI assistant for Sri Clinic.",
    ai_disclosure_line: "Namaskaram, this is an AI assistant for Sri Clinic.",
    ai_disclosure_enabled: true,
    recording_notice_line: "This call is being recorded.",
    caller_memory_notice_line: "I keep a short note of what you ask about.",
    caller_memory_enabled: false,
    caller_memory_paused: false,
    caller_has_screen: false,
    recording_notice_enabled: true,
    opening_line: "Namaskaram, this is an AI assistant for Sri Clinic. This call is being recorded.",
    script_opening_line: "",
    first_words: "Namaskaram, this is an AI assistant for Sri Clinic. This call is being recorded.",
    truthful_answer_rule: "Whatever these settings say, the agent always answers honestly when a caller asks.",
    engine: "thinnest",
    published: true,
    archived_at: null,
    inbound_number_count: 1,
    extraction_fields: [],
    extraction_schema_version: 0,
    llm_tier: null,
    llm_tier_effective: "standard",
    llm_tier_label: "Standard",
    llm_tier_source: "platform",
    llm_surcharged: false,
  };
}

const AGENTS = [agent(AGENT_ID, "Reception"), agent(OTHER_AGENT_ID, "Evening desk")];

const SCRIPT: CallScript = { ...EMPTY_SCRIPT, opening_line: "Namaskaram, Sri Clinic." };

function line(over: Partial<InboundLine> = {}): InboundLine {
  return {
    id: LINE_ID,
    name: "Calls to your number",
    agent_id: AGENT_ID,
    agent_name: "Reception",
    main_task: "",
    script: null,
    proposal: null,
    version: 0,
    published_at: null,
    live: false,
    actions_off: [],
    source_ids: [],
    numbers: [],
    created_at: "2026-11-16T04:00:00Z",
    ...over,
  };
}

function tool(name: string): ActionTool {
  return {
    id: `tool-${name}`,
    agent_id: AGENT_ID,
    config: {},
    credential_id: null,
    description: "",
    enabled: true,
    kind: "webhook",
    name,
    params: [],
    pre_call_message: null,
    provider: null,
    trigger: "",
  };
}

const ACTIONS: ActionsSettings = {
  api_actions_enabled: true,
  calendar_available: false,
  tools: [tool("book_visit"), tool("send_price_list")],
};

const NUMBER: CampaignNumber = {
  id: "num-1",
  e164: "+918041234567",
  series: "140",
  dlt_status: "approved",
  agent_id: OTHER_AGENT_ID,
  places_calls: false,
  activated: true,
  answerable: true,
  direction: "inbound",
  held: false,
  releasable: false,
  supplied_by_us: true,
};

const lineRoutes = (current: InboundLine, extra: Routes = {}): Routes => ({
  "/v1/me": ME,
  [`/v1/inbound-lines/${LINE_ID}`]: current,
  "/v1/inbound-lines": {
    lines: [current, line({ id: OTHER_LINE_ID, name: "Evening line", numbers: [{ id: "num-1", e164: NUMBER.e164 }] })],
  },
  [`/v1/inbound-lines/${LINE_ID}/calls`]: { calls: [] },
  [`/v1/inbound-lines/${LINE_ID}/test-calls`]: [],
  [`/v1/inbound-lines/${LINE_ID}/test-numbers`]: { numbers: [] },
  "/v1/agents": AGENTS,
  "/v1/kb/notes": { notes: [] },
  "/v1/kb/uploads": [],
  [`/v1/agents/${AGENT_ID}/actions`]: ACTIONS,
  "/v1/business-profile": businessProfileFixture(),
  "/v1/campaigns/numbers": [NUMBER],
  ...extra,
});

const linePage = () => <InboundLinePage params={Promise.resolve({ slug: "acme", lineId: LINE_ID })} />;
const listPage = () => <InboundPage params={Promise.resolve({ slug: "acme" })} />;

const writes = (calls: ApiCall[]) => calls.filter((c) => c.method !== "GET");
const bodyOf = (calls: ApiCall[], method: string, path: string) => {
  const call = calls.find((c) => c.method === method && c.path === path);
  expect(call, `${method} ${path}`).toBeTruthy();
  return JSON.parse(call?.body ?? "null") as unknown;
};

describe("the inbound list", () => {
  it("shows one row per line with its voice, numbers and state", async () => {
    await renderClientPage(listPage(), {
      "/v1/me": ME,
      "/v1/inbound-lines": {
        lines: [
          line({ live: true, script: SCRIPT, numbers: [{ id: "num-1", e164: NUMBER.e164 }] }),
          line({ id: OTHER_LINE_ID, name: "Evening line", agent_name: "Evening desk" }),
        ],
      },
    });
    const list = await screen.findByRole("list", { name: "Your inbound lines" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Live")).toBeTruthy();
    expect(within(rows[0]).getByText("Voice: Reception")).toBeTruthy();
    expect(within(rows[0]).getByText("+91 80412 34567", { exact: false })).toBeTruthy();
    expect(within(rows[1]).getByText("Draft")).toBeTruthy();
    expect(within(rows[1]).getByText("No number yet")).toBeTruthy();
    expect(within(rows[1]).getByRole("link", { name: "Evening line" }).getAttribute("href")).toBe(
      `/c/acme/inbound/${OTHER_LINE_ID}`,
    );
  });

  it("says there are none with one button when the account has no line", async () => {
    await renderClientPage(listPage(), { "/v1/me": ME, "/v1/inbound-lines": { lines: [] } });
    expect(await screen.findByText("No inbound lines yet.")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "New line" })).toHaveLength(1);
  });

  it("starts a line in the chosen agent's voice", async () => {
    const created = line({ agent_id: OTHER_AGENT_ID, agent_name: "Evening desk" });
    const rendered = await renderClientPage(listPage(), {
      "/v1/me": ME,
      "/v1/inbound-lines": { lines: [] },
      "/v1/agents": AGENTS,
      "POST /v1/inbound-lines": created,
    });
    await screen.findByText("No inbound lines yet.");
    fireEvent.click(screen.getByRole("button", { name: "New line" }));
    fireEvent.change(await screen.findByLabelText("Whose voice answers?"), { target: { value: OTHER_AGENT_ID } });
    fireEvent.click(screen.getByRole("button", { name: "Start the line" }));
    await waitFor(() => expect(writes(rendered.calls)).toHaveLength(1));
    expect(bodyOf(rendered.calls, "POST", "/v1/inbound-lines")).toEqual({ agent_id: OTHER_AGENT_ID });
  });
});

describe("one inbound line", () => {
  it("saves the main task", async () => {
    const rendered = await renderClientPage(
      linePage(),
      lineRoutes(line(), { [`PATCH /v1/inbound-lines/${LINE_ID}`]: line({ main_task: "Book visits." }) }),
    );
    fireEvent.change(await screen.findByRole("textbox", { name: "Main task" }), { target: { value: "Book visits." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(writes(rendered.calls)).toHaveLength(1));
    expect(bodyOf(rendered.calls, "PATCH", `/v1/inbound-lines/${LINE_ID}`)).toEqual({ main_task: "Book visits." });
    // Phone numbers names each number's line, so a change to the line reads that list again.
    const numberReads = () => rendered.calls.filter((c) => c.path === "/v1/campaigns/numbers").length;
    await waitFor(() => expect(numberReads()).toBeGreaterThan(1));
  });

  it("keeps Pip's draft by its proposal id, which saves and puts it live", async () => {
    const proposal = {
      id: "prop-1",
      status: "ready" as const,
      script: { ...SCRIPT, opening_line: "Namaskaram, thanks for calling Sri Clinic." },
      base_script: EMPTY_SCRIPT,
      left_out: [],
      disclosure: null,
      note: null,
      reason: null,
      why: {},
      fixes: null,
      requested_at: "2026-11-16T04:05:00Z",
    };
    const rendered = await renderClientPage(
      linePage(),
      lineRoutes(line({ main_task: "Book visits.", proposal }), {
        [`PUT /v1/inbound-lines/${LINE_ID}/script`]: line({ main_task: "Book visits.", script: proposal.script, live: true }),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add it to my draft" }));
    await waitFor(() => expect(writes(rendered.calls)).toHaveLength(1));
    expect(bodyOf(rendered.calls, "PUT", `/v1/inbound-lines/${LINE_ID}/script`)).toEqual({
      script: proposal.script,
      proposal_id: "prop-1",
    });
  });

  it("switches an action off for this line only", async () => {
    const rendered = await renderClientPage(
      linePage(),
      lineRoutes(line(), {
        [`PUT /v1/inbound-lines/${LINE_ID}/actions`]: line({ actions_off: ["send_price_list"] }),
      }),
    );
    const toggle = await screen.findByRole("switch", { name: "send_price_list" });
    expect((toggle as HTMLInputElement).checked).toBe(true);
    fireEvent.click(toggle);
    await waitFor(() => expect(writes(rendered.calls)).toHaveLength(1));
    expect(bodyOf(rendered.calls, "PUT", `/v1/inbound-lines/${LINE_ID}/actions`)).toEqual({ off: ["send_price_list"] });
  });

  it("adds a number and says which line it moves from", async () => {
    const rendered = await renderClientPage(
      linePage(),
      lineRoutes(line(), {
        [`POST /v1/inbound-lines/${LINE_ID}/numbers`]: line({ numbers: [{ id: "num-1", e164: NUMBER.e164 }] }),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add a number" }));
    expect(await screen.findByText("It moves from Evening line.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Move it here" }));
    await waitFor(() => expect(writes(rendered.calls)).toHaveLength(1));
    expect(bodyOf(rendered.calls, "POST", `/v1/inbound-lines/${LINE_ID}/numbers`)).toEqual({ number_id: "num-1" });
  });

  it("rings the owner's phone with a draft line, a saved number one tap away, and lists the call", async () => {
    const CALL_ID = "0192f0aa-5555-7000-8000-000000000001";
    const rendered = await renderClientPage(
      linePage(),
      lineRoutes(line({ main_task: "Book visits.", script: SCRIPT }), {
        [`/v1/inbound-lines/${LINE_ID}/test-numbers`]: { numbers: ["+919876543210"] },
        [`/v1/inbound-lines/${LINE_ID}/test-calls`]: [
          { call_id: CALL_ID, placed_at: "2026-11-16T05:00:00Z", status: "completed", duration_s: 64, has_recording: false },
        ],
        [`POST /v1/inbound-lines/${LINE_ID}/test-call`]: { status: "queued", blocked_reason: null, blocked_rule: null, call_id: CALL_ID },
      }),
    );
    const fold = (await screen.findByRole("heading", { name: "Test call" })).closest("section") as HTMLElement;
    // Before Calls taken, as on a campaign's page.
    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings.indexOf("Test call")).toBeLessThan(headings.indexOf("Calls taken"));
    const box = (await within(fold).findByRole("textbox", { name: /Number to call/ })) as HTMLInputElement;
    await waitFor(() => expect(box.value).toBe("+919876543210"));
    // The saved numbers are the account's, kept by the campaigns; a line only uses them.
    expect(within(fold).queryByRole("button", { name: /Remove/ })).toBeNull();
    // Vouching for the number is the owner's own tick (D-855): never sent unasked.
    const mine = within(fold).getByRole("checkbox", { name: /This number is my own/ }) as HTMLInputElement;
    expect(mine.checked).toBe(false);
    fireEvent.click(within(fold).getByRole("button", { name: "Call me" }));
    await waitFor(() => expect(writes(rendered.calls)).toHaveLength(1));
    expect(bodyOf(rendered.calls, "POST", `/v1/inbound-lines/${LINE_ID}/test-call`)).toEqual({
      number: "+919876543210",
      number_is_mine: false,
    });
    expect(await within(fold).findByText(/Calling you now/)).toBeTruthy();
    expect(within(fold).getByText("Your test calls")).toBeTruthy();
    for (const link of within(fold).getAllByRole("link", { name: "Open the call" })) {
      expect(link.getAttribute("href")).toBe(`/c/acme/calls/${CALL_ID}`);
    }
  });

  it("asks for the script before a line can be heard", async () => {
    await renderClientPage(linePage(), lineRoutes(line()));
    const fold = (await screen.findByRole("heading", { name: "Test call" })).closest("section") as HTMLElement;
    expect(within(fold).getByText("Write the script first, then hear it here.")).toBeTruthy();
    expect(within(fold).queryByRole("button", { name: "Call me" })).toBeNull();
  });

  it("offers Put it live for a saved script that is not live yet", async () => {
    await renderClientPage(linePage(), lineRoutes(line({ main_task: "Book visits.", script: SCRIPT })));
    expect(await screen.findByRole("button", { name: "Put it live" })).toBeTruthy();
    expect(screen.getByText("Not live yet")).toBeTruthy();
  });

  it("says a number on a line that is not live answers nobody, with the button that puts it live (D3)", async () => {
    const withNumber = line({ main_task: "Book visits.", script: SCRIPT, numbers: [{ id: "num-1", e164: NUMBER.e164 }] });
    const rendered = await renderClientPage(
      linePage(),
      lineRoutes(withNumber, {
        [`POST /v1/inbound-lines/${LINE_ID}/publish`]: { ...withNumber, live: true },
      }),
    );
    const fold = (await screen.findByRole("heading", { name: "Numbers" })).closest("section") as HTMLElement;
    expect(within(fold).getByText("Not answering")).toBeTruthy();
    fireEvent.click(within(fold).getByRole("button", { name: "Put this line live" }));
    await waitFor(() => expect(writes(rendered.calls)).toHaveLength(1));
    expect(writes(rendered.calls)[0]?.path).toBe(`/v1/inbound-lines/${LINE_ID}/publish`);
  });

  it("asks for the script first when a draft line has a number", async () => {
    await renderClientPage(linePage(), lineRoutes(line({ numbers: [{ id: "num-1", e164: NUMBER.e164 }] })));
    const fold = (await screen.findByRole("heading", { name: "Numbers" })).closest("section") as HTMLElement;
    expect(within(fold).getByText("Not answering")).toBeTruthy();
    expect(within(fold).queryByRole("button", { name: "Put this line live" })).toBeNull();
    expect(within(fold).getByRole("link", { name: "Write the script" }).getAttribute("href")).toBe("#line-script");
  });

  it("shows no warning on the numbers of a live line", async () => {
    await renderClientPage(
      linePage(),
      lineRoutes(line({ script: SCRIPT, live: true, numbers: [{ id: "num-1", e164: NUMBER.e164 }] })),
    );
    const fold = (await screen.findByRole("heading", { name: "Numbers" })).closest("section") as HTMLElement;
    expect(within(fold).queryByText("Not answering")).toBeNull();
    expect(within(fold).queryByRole("button", { name: "Put this line live" })).toBeNull();
  });

  it("counts only the sources still in the pick list as chosen", async () => {
    const KEPT = "0192f0aa-5555-7000-8000-0000000000a1";
    const GONE = "0192f0aa-5555-7000-8000-0000000000a2";
    await renderClientPage(
      linePage(),
      lineRoutes(line({ source_ids: [KEPT, GONE] }), {
        "/v1/kb/notes": {
          notes: [{ id: KEPT, name: "Opening hours", state: "in_use", version: 1, chunks: 1, changed_at: "2026-11-16T04:00:00Z", restorable: false }],
        },
      }),
    );
    await screen.findByRole("checkbox", { name: /Opening hours/ });
    expect(screen.getByText("1 chosen")).toBeTruthy();
    expect(screen.queryByText("2 chosen")).toBeNull();
  });

  it("links from the calls it took to all its calls in the call log (D-1006)", async () => {
    await renderClientPage(
      linePage(),
      lineRoutes(line(), {
        [`/v1/inbound-lines/${LINE_ID}/calls`]: {
          calls: [{ id: "call-1", started_at: "2026-11-16T05:00:00Z", duration_s: 64, status: "completed", outcome_tag: "answered" }],
        },
      }),
    );
    const fold = (await screen.findByRole("heading", { name: "Calls taken" })).closest("section") as HTMLElement;
    const all = await within(fold).findByRole("link", { name: "All its calls" });
    expect(all.getAttribute("href")).toBe(`/c/acme/calls?inbound_line_id=${LINE_ID}`);
  });
});

describe("the inbound screens speak in short lines", () => {
  const copy = defaultCopyUnder(["src/app/c/[slug]/inbound"], {
    attrs: /^(info|title|aria-label|placeholder)$/,
    constants: /_INFO$|_PLACEHOLDER$/,
  });

  it("reads the screens at all", () => {
    expect(copy.some((c) => c.text === "Add a number")).toBe(true);
  });

  it(`keeps every default line to about ${SHORT_LINE} characters`, () => {
    expect(longLines(copy)).toEqual([]);
  });
});
