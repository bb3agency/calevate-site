import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NewAgentPage from "@/app/c/[slug]/agents/new/page";
import { ENGINE_CATALOGUE_PATH } from "@/lib/api/engineCatalogue";
import type { LeadFields } from "@/lib/api/leadFields";
import type { PendingState } from "@/lib/api/publishing";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut, type ScriptProposal } from "@/lib/api/script";

import { operatorEngineCatalogue } from "./fixtures/engineCatalogue";
import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { problem, renderClientPage, type Routes } from "./harness";

/**
 * NEW AGENT IN FOUR STEPS (founder, 3 Nov 2026): Job, Voice, Script, Notes, then a finish.
 *
 * Step 1 reads the job's suggested name (`GET /v1/agents/starters`) and creates the agent with
 * `starter`; the opening line goes only when the owner typed one. The steps after it edit that
 * draft, each with a Skip: the Voice tab's picker and save, the script written for the business
 * read back once it lands, and the details it writes down with the "What it notes" tab's write.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/c/acme/agents/new",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const page = <NewAgentPage params={Promise.resolve({ slug: "acme" })} />;

const ANSWER = {
  job: "answer_calls",
  direction: "inbound",
  name_suggestion: "Front desk",
  step_titles: [
    "Greet the caller",
    "Find out what they need",
    "Answer from what you know",
    "Take their name",
    "Confirm their number",
    "Close the call",
  ],
  steps_written: false,
  captured_details: ["Their name", "What they want", "Best time to call back"],
  locked_reason: null as string | null,
};

const LEADS = {
  ...ANSWER,
  job: "call_leads",
  direction: "outbound",
  name_suggestion: "Follow-up caller",
};

const AGENT = "agent-9";
const BASE = `/v1/agents/${AGENT}`;

const STARTER: CallScript = {
  ...EMPTY_SCRIPT,
  goal: "Answer callers' questions.",
  stages: [{ id: "s1", name: "Greet the caller", instruction: "Say hello." }],
};

const WRITTEN: CallScript = {
  ...EMPTY_SCRIPT,
  goal: "Book site visits for Lakeview Properties.",
  opening_line: "Hello, Lakeview Properties here.",
  stages: [
    { id: "s1", name: "Find out buy or rent", instruction: "Ask." },
    { id: "s2", name: "Book a site visit", instruction: "Offer a slot." },
  ],
};

function scriptOut(script: CallScript): ScriptOut {
  return {
    script,
    stored_schema_version: 2,
    context: null,
    draft: null,
    version: 1,
    is_freeform: false,
    has_pending: false,
    standard_variables: [],
  };
}

function proposal(status: ScriptProposal["status"]): ScriptProposal {
  return {
    id: "p-1",
    mode: "starter",
    documents: [],
    status,
    request: null,
    base_script: STARTER,
    script: status === "ready" ? WRITTEN : null,
    unplaced: [],
    disclosure: null,
    note: null,
    requested_at: "2026-11-03T10:00:00Z",
  };
}

const PENDING: PendingState = {
  agent_id: AGENT,
  agent_status: "draft",
  published: false,
  has_pending: false,
  pending: [],
  effective_call_cap_s: 600,
  call_cap_is_platform_default: true,
  worst_case_call_cost_inr: "65.00",
  precedence_rule: "Script decides content, rules decide conduct, voice only changes delivery.",
  voice_tier_rates: [
    { voice_tier: "clear", label: "Clear", inr_per_min: "4.5000", further_open_lots: 0 },
    { voice_tier: "studio", label: "Studio", inr_per_min: "6.0000", further_open_lots: 0 },
  ],
  voice: { configured: null, live: null, republish_required: false, unnamed_note: null, headline: "No voice has been set on this agent." },
  engine_verification: {
    state: "unverified",
    confirmed: false,
    publishable: true,
    verified_at: null,
    headline: "Not on the voice platform yet.",
  },
};

const LEAD_FIELDS: LeadFields = {
  business_type: "real_estate",
  business_type_label: "Property",
  core_default_labels: {},
  core_fields: [
    { key: "name", label: "Name", type: "text", reason: "", required: false, enum_values: null },
    { key: "need", label: "What they want", type: "text", reason: "", required: false, enum_values: null },
  ],
  need_key: "need",
  standard_fields: [],
  has_standard_set: false,
  draft: null,
  can_draft: false,
  agents: [],
};

const BUDGET = { key: "budget", label: "Budget", type: "text" as const, reason: "", required: false, enum_values: null };

const created = agentRow({
  id: AGENT,
  name: "Reception",
  status: "draft",
  published: false,
  inbound_number_count: 0,
  engine_voice_id: null,
  extraction_fields: [BUDGET],
  extraction_schema_version: 3,
});

function routes(over: Routes = {}): Routes {
  return {
    "/v1/me": OWNER_ME,
    "/v1/agents/starters": { vertical: "real_estate", business_details: true, starters: [ANSWER, LEADS] },
    "POST /v1/agents": { id: AGENT, name: "Reception" },
    [BASE]: created,
    [`${BASE}/pending`]: PENDING,
    [ENGINE_CATALOGUE_PATH]: operatorEngineCatalogue({ models: [] }),
    [`${BASE}/script`]: scriptOut(WRITTEN),
    [`${BASE}/script/proposal`]: { proposal: null },
    "/v1/lead-fields": LEAD_FIELDS,
    ...over,
  };
}

/** Pick the first job, keep its name and create it: the flow's step 1. */
async function createAgent() {
  fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));
  await screen.findByLabelText(/^Name/);
  const create = screen.getByRole("button", { name: "Create agent" }) as HTMLButtonElement;
  await waitFor(() => expect(create.disabled).toBe(false));
  fireEvent.click(create);
  await screen.findByRole("heading", { name: "Pick a voice" });
}

async function toScript() {
  await createAgent();
  fireEvent.click(screen.getByRole("button", { name: "Skip" }));
}

describe("new agent: step 1, the job", () => {
  it("offers the three jobs first, all open, and reads no preview until one is picked", async () => {
    const { calls } = await renderClientPage(page, routes());
    expect(await screen.findByRole("heading", { name: "What should your new agent do?" })).toBeTruthy();
    for (const name of [/Answer my calls/, /Call new leads instantly/, /Run calling campaigns/]) {
      expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(false);
    }
    expect(calls.some((c) => c.path.includes("/starters"))).toBe(false);
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Job");
  });

  it("suggests the job's name and no ready-made opening", async () => {
    await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));

    const opening = (await screen.findByLabelText(/How it opens a call/)) as HTMLTextAreaElement;
    expect(opening.value).toBe("");
    expect((screen.getByLabelText(/^Name/) as HTMLInputElement).value).toBe("Front desk");
  });

  it("creates it from the job with the owner's name, then moves on to its voice", async () => {
    const { calls } = await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));
    const name = (await screen.findByLabelText(/^Name/)) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "Reception" } });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    expect(await screen.findByRole("heading", { name: "Pick a voice" })).toBeTruthy();
    const body = JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}");
    expect(body).toMatchObject({ name: "Reception", starter: "answer_calls", language_primary: "te-IN" });
    // The job sets the direction on the server; the client sends none.
    expect(body).not.toHaveProperty("direction");
    // Left empty, the opening is written for the business after creation (D-965).
    expect(body).not.toHaveProperty("opening_line");
  });

  it("sends the opening the owner typed, trimmed", async () => {
    const { calls } = await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));
    fireEvent.change(await screen.findByLabelText(/How it opens a call/), {
      target: { value: "  Hello, Lakeview Properties here. Looking to buy or rent?  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}");
    expect(body.opening_line).toBe("Hello, Lakeview Properties here. Looking to buy or rent?");
  });

  it("refuses an empty name in place and sends nothing", async () => {
    const { calls } = await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));
    fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Give this agent a name of at least two characters.")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's refusal inline and keeps what was typed", async () => {
    await renderClientPage(
      page,
      routes({
        "POST /v1/agents": problem(422, { code: "starter_direction_mismatch", title: "This job sets which way its calls go.", detail: "This job sets which way its calls go.", fields: [{ name: "direction" }] }),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Answer my calls/ }));
    await screen.findByLabelText(/^Name/);
    // The preview can be on screen before the session read that enables the button.
    const create = screen.getByRole("button", { name: "Create agent" }) as HTMLButtonElement;
    await waitFor(() => expect(create.disabled).toBe(false));
    fireEvent.click(create);

    expect(await screen.findByText(/This job sets which way its calls go/)).toBeTruthy();
    expect((screen.getByLabelText(/^Name/) as HTMLInputElement).value).toBe("Front desk");
  });

  it("keeps the blank flow one link away", async () => {
    await renderClientPage(page, routes({ "/v1/agents/lanes": { precedence_rule: "", lanes: [] } }));
    fireEvent.click(await screen.findByRole("button", { name: "Start from a blank agent instead" }));
    expect(await screen.findByText("What should it do?")).toBeTruthy();
  });
});

describe("new agent: step 2, the voice", () => {
  it("offers the enabled voices by rung with this account's rate for each", async () => {
    await renderClientPage(page, routes());
    await createAgent();
    expect(document.querySelector('[aria-current="step"]')?.textContent).toContain("Voice");
    expect(await screen.findByRole("group", { name: "Clear voices" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Studio voices" })).toBeTruthy();
    expect(await screen.findByText("Clear — ₹4.5 / min")).toBeTruthy();
    expect(screen.getByText("Studio — ₹6 / min")).toBeTruthy();
  });

  it("saves the picked voice with the Voice tab's write and moves on to the script", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ [`PATCH ${BASE}`]: { ...created, engine_voice_id: "engine:anjali" } }),
    );
    await createAgent();
    fireEvent.click(await screen.findByRole("radio", { name: /Anjali/ }));
    fireEvent.click(screen.getByRole("button", { name: "Use this voice" }));

    expect(await screen.findByRole("heading", { name: "Your script" })).toBeTruthy();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({ engine_voice_id: "engine:anjali" });
  });

  it("skips to the script without saving anything", async () => {
    const { calls } = await renderClientPage(page, routes());
    await toScript();
    expect(await screen.findByRole("heading", { name: "Your script" })).toBeTruthy();
    expect(calls.some((c) => c.method !== "GET" && c.method !== "POST")).toBe(false);
  });
});

describe("new agent: step 3, the script written for the business", () => {
  it("waits while it is written, then reads it back for review", async () => {
    let proposalReads = 0;
    let written = false;
    await renderClientPage(
      page,
      routes({
        [`${BASE}/script/proposal`]: () => {
          proposalReads += 1;
          // Drafting on the first read, then applied by the worker and cleared.
          if (proposalReads > 1) written = true;
          return { proposal: written ? null : proposal("drafting") };
        },
        [`${BASE}/script`]: () => scriptOut(written ? WRITTEN : STARTER),
      }),
    );
    await toScript();
    expect(await screen.findByRole("heading", { name: "Writing your script" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skip" })).toBeTruthy();

    expect(await screen.findByRole("heading", { name: "Your script" }, { timeout: 8000 })).toBeTruthy();
    expect(screen.getByText("Book site visits for Lakeview Properties.")).toBeTruthy();
    expect(screen.getByText("Book a site visit")).toBeTruthy();
    expect(screen.getByText("“Hello, Lakeview Properties here.”")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Edit it" }).getAttribute("href")).toBe(
      `/c/acme/agents/${AGENT}?section=script&from=starter`,
    );
    fireEvent.click(screen.getByRole("button", { name: "Looks good, continue" }));
    expect(await screen.findByRole("heading", { name: "What it writes down" })).toBeTruthy();
  }, 15_000);

  it("says plainly when it could not be written, and offers writing it or skipping", async () => {
    await renderClientPage(page, routes({ [`${BASE}/script/proposal`]: { proposal: proposal("failed") } }));
    await toScript();
    expect(await screen.findByRole("heading", { name: "We couldn't write the script" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Write it yourself" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(await screen.findByRole("heading", { name: "What it writes down" })).toBeTruthy();
  });

  it("asks again for the script when Try again is pressed", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        [`${BASE}/script/proposal`]: { proposal: proposal("failed") },
        [`POST ${BASE}/script/proposal/starter`]: proposal("drafting"),
      }),
    );
    await toScript();
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/script/proposal/starter"))).toBe(true),
    );
    expect(await screen.findByRole("heading", { name: "Writing your script" })).toBeTruthy();
  });

  it("sends a suggestion still waiting to the Script tab to be used", async () => {
    await renderClientPage(page, routes({ [`${BASE}/script/proposal`]: { proposal: proposal("ready") } }));
    await toScript();
    expect(await screen.findByRole("heading", { name: "Your script is written" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Review and use it" })).toBeTruthy();
  });
});

describe("new agent: step 4, what it writes down, and the finish", () => {
  async function toNotes() {
    await toScript();
    fireEvent.click(await screen.findByRole("button", { name: "Looks good, continue" }));
    await screen.findByRole("heading", { name: "What it writes down" });
  }

  it("shows the details on every lead and the agent's own", async () => {
    await renderClientPage(page, routes());
    await toNotes();
    expect(await screen.findByText("What they want")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove Budget" })).toBeTruthy();
  });

  it("removes and adds a detail with the tab's write, against the version read", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({ [`PUT ${BASE}/extraction-schema`]: { fields: [], version: 4 } }),
    );
    await toNotes();
    fireEvent.click(await screen.findByRole("button", { name: "Remove Budget" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({
      fields: [],
      expected_version: 3,
    });

    fireEvent.change(screen.getByLabelText("Add a detail"), { target: { value: "Site visit date" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2));
    const added = JSON.parse(calls.filter((c) => c.method === "PUT")[1]?.body ?? "{}");
    expect(added.fields).toContainEqual({
      key: "site_visit_date",
      label: "Site visit date",
      type: "text",
      required: false,
      reason: "",
      enum_values: null,
    });
  });

  it("refuses a detail it already writes down, in place", async () => {
    const { calls } = await renderClientPage(page, routes());
    await toNotes();
    fireEvent.change(await screen.findByLabelText("Add a detail"), { target: { value: "budget" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("It already writes this down.")).toBeTruthy();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("finishes with a test call and the agent, and says what was skipped", async () => {
    await renderClientPage(page, routes());
    await toNotes();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("heading", { name: "Reception is set up" })).toBeTruthy();
    const finish = within(screen.getByRole("heading", { name: "Reception is set up" }).closest("section") as HTMLElement);
    expect(finish.getByText("Voice skipped")).toBeTruthy();
    expect(finish.getByText("Script checked")).toBeTruthy();
    expect(finish.getByRole("link", { name: "Make a test call" }).getAttribute("href")).toBe(
      `/c/acme/agents/${AGENT}?section=training`,
    );
    expect(finish.getByRole("link", { name: "Go to the agent" }).getAttribute("href")).toBe(`/c/acme/agents/${AGENT}`);
  });
});
