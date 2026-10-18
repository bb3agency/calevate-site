import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import AgentScriptPage from "@/app/c/[slug]/agents/[agentId]/script/page";
import { partSummaries } from "@/app/c/[slug]/agents/[agentId]/script/ScriptParts";
import type { Me } from "@/lib/api/client";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut } from "@/lib/api/script";

import { expectNoA11yViolations } from "./a11y";
import { renderClientPage } from "./harness";
import { agentRow, settledPending } from "./fixtures/sharedReads";

/**
 * The Script page is ordered by how often an owner needs each thing (founder, 11 Oct 2026:
 * "all of it is too much to read"): the opening line and the steps on the page, the parts
 * set once as a summary list whose rows open in place, History and the rest in the ⋯ menu.
 * These pin that nothing moved out of reach: every part is still in the document, a part
 * that holds the autosave says so on its closed row, a link to a part's anchor opens it,
 * and History still restores from the menu.
 */

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Raghava Organics", slug: "acme", status: "active" },
};

const FULL: CallScript = {
  ...EMPTY_SCRIPT,
  opening_line: "Namaskaram andi.",
  business_line: "An organic produce shop in Kukatpally",
  identity: "You answer the phone for the shop.",
  goal: "Take the order and the delivery area.",
  style: { tone: "warm", address_form: "andi", code_mix: "natural", sample_phrases: [], pronunciations: [] },
  stages: [
    {
      id: "greet",
      name: "Greet",
      mode: "guide",
      instruction: "Say hello and ask what they need.",
      sounds_like: "",
      branches: [{ when: "they want a person", target: "hand_over" }],
      otherwise: "",
      collect: ["Delivery area"],
      position: null,
    },
    { id: "order", name: "Take the order", mode: "guide", instruction: "Take the order.", sounds_like: "", branches: [], otherwise: "", collect: [], position: null },
  ],
  objections: [{ objection: "Too expensive.", response: "Explain it is organic." }],
  ending: "Thank them and say goodbye.",
  example_exchange: [{ speaker: "caller", text: "Tomatoes unnaya?" }],
  example_needs_review: true,
};

function out(script: CallScript, draft: CallScript | null = null): ScriptOut {
  return {
    script,
    draft: draft ? { script: draft, saved_at: "2026-10-10T12:00:00+00:00" } : null,
    stored_schema_version: 2,
    context: null,
    version: 3,
    is_freeform: false,
    has_pending: false,
    standard_variables: [{ key: "name", label: "Caller's name" }],
  };
}

const PREVIEW = { compiled: "FULL TEXT", instructions_chars: 2000, instructions_limit: 8000, native_steps: 2 };
const page = <AgentScriptPage params={Promise.resolve({ slug: "acme", agentId: "agent-1" })} />;

const routes = (script: ScriptOut, extra: Record<string, unknown> = {}) => ({
  "/v1/me": OWNER,
  "/v1/agents/agent-1": agentRow(),
  "/v1/agents/agent-1/script": script,
  "POST /v1/agents/agent-1/script/preview": PREVIEW,
  "/v1/agents/agent-1/script/proposed-rules": [],
  "/v1/agents/agent-1/pending": settledPending(),
  ...extra,
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("the script page leads with the opening line and the steps", () => {
  it("shows the steps as one-line summaries and the set-once parts as closed rows", async () => {
    const { container } = await renderClientPage(page, routes(out(FULL)));
    const list = await screen.findByRole("list", { name: "Steps of the call, in order" });
    const first = list.querySelector(":scope > li")?.textContent ?? "";
    expect(first).toContain("Greet");
    expect(first).toContain("1 other way out");
    expect(first).toContain("Finds out: Delivery area");

    const rows = Array.from(container.querySelectorAll("details")).map((d) => d.querySelector("summary h4")?.textContent);
    expect(rows).toEqual([
      "Who it is",
      "What a good call achieves",
      "How it speaks",
      "When callers push back",
      "What it may do",
      "How it ends the call",
      "An example call",
    ]);
    expect(Array.from(container.querySelectorAll("details")).every((d) => !d.open)).toBe(true);
    // Closed, every form is still in the document: the assistant's fills and find work.
    expect(screen.getByLabelText("Your business in one line")).toBeTruthy();
    expect(screen.getByText("An organic produce shop in Kukatpally")).toBeTruthy();
    expect(screen.getByText("1 line · waiting for a native speaker")).toBeTruthy();
  });

  it("says whether callers hear this draft", async () => {
    await renderClientPage(page, routes(out(FULL)));
    expect(await screen.findByText("Live")).toBeTruthy();
  });

  it("says when the draft is not live yet, beside the one primary action", async () => {
    await renderClientPage(page, routes(out(EMPTY_SCRIPT, FULL)));
    expect(await screen.findByText("Changes not live yet")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Put it live" })).toBeTruthy();
  });
});

describe("a part that needs finishing says so while it is closed", () => {
  it("marks the push-back row and holds the autosave", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(out(FULL, { ...FULL, objections: [{ objection: "Too far.", response: "" }] })),
    );
    expect(await screen.findByText(/1 part to finish/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Opening line"), { target: { value: "Namaskaram!" } });
    expect(await screen.findByText(/Not saved yet: one part needs finishing/)).toBeTruthy();
    await new Promise((r) => setTimeout(r, 1500));
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});

describe("a link to a part opens it", () => {
  it("opens What it may do for #policies, which Knowledge's Fix in script uses", async () => {
    window.history.replaceState(null, "", "/c/acme/agents/agent-1/script#policies");
    const { container } = await renderClientPage(page, routes(out(FULL)));
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    const open = Array.from(container.querySelectorAll("details")).filter((d) => d.open);
    expect(open.map((d) => d.querySelector("summary h4")?.textContent)).toEqual(["What it may do"]);
    expect(open[0].querySelector("#policies")).toBeTruthy();
  });
});

describe("the occasional actions are in the menu", () => {
  it("opens History from the ⋯ menu", async () => {
    await renderClientPage(
      page,
      routes(out(FULL), {
        "/v1/agents/agent-1/script/versions": [
          { version: 3, summary: "Added the delivery step", created_at: "2026-10-09T10:00:00+00:00", is_live: true },
        ],
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "More actions for this script" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "History" }));
    const drawer = await screen.findByRole("dialog", { name: "History" });
    expect(await within(drawer).findByText("Added the delivery step")).toBeTruthy();
  });

  it("still shows what the agent reads", async () => {
    const { calls } = await renderClientPage(page, routes(out(FULL)));
    fireEvent.click(await screen.findByRole("button", { name: "More actions for this script" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "See what the agent reads" }));
    expect(await screen.findByText("FULL TEXT")).toBeTruthy();
    expect(calls.some((c) => c.path.endsWith("/script/preview"))).toBe(true);
  });
});

describe("partSummaries", () => {
  it("reads plainly when nothing is written", () => {
    expect(partSummaries(EMPTY_SCRIPT, null)).toMatchObject({
      identity: "Not written yet",
      objections: "None yet",
      policies: "Offers call backs · tells prices · takes bookings",
      example: "None yet",
    });
  });

  it("never offers call backs on a trial", () => {
    const context = { call_backs_available: false } as Parameters<typeof partSummaries>[1];
    expect(partSummaries(EMPTY_SCRIPT, context).policies).toMatch(/^No call backs/);
  });
});

describe("accessibility with every part open", () => {
  it("has no axe violations", async () => {
    const { container } = await renderClientPage(page, routes(out(FULL)));
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    container.querySelectorAll("details").forEach((d) => {
      d.open = true;
    });
    fireEvent.click(screen.getByRole("button", { name: /^Greet/ }));
    await waitFor(() => expect(screen.getAllByLabelText("Step name").length).toBeGreaterThan(0));
    await expectNoA11yViolations(container, "script page, every part open");
  });
});

describe("the AI helper's actions", () => {
  it("keeps the one primary action apart from the other way to ask", async () => {
    await renderClientPage(page, routes(out(FULL)));
    fireEvent.click(await screen.findByRole("button", { name: "AI helper" }));
    const primary = await screen.findByRole("button", { name: "Suggest the change" });
    const other = screen.getByRole("button", { name: "Or draft the whole script from five questions" });
    // Two separate controls in one wrapping row, never one run of text.
    expect(primary).not.toBe(other);
    expect(primary.parentElement).toBe(other.parentElement);
    expect(primary.parentElement?.className).toContain("gap-x-4");
  });
});
