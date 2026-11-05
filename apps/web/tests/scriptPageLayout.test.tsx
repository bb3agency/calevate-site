import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { ScriptBuilder } from "@/app/c/[slug]/agents/[agentId]/script/ScriptBuilder";
import { StrictnessSection } from "@/app/c/[slug]/agents/[agentId]/script/ScriptSections";
import type { Me } from "@/lib/api/client";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut, type ScriptProposal } from "@/lib/api/script";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { expectNoA11yViolations } from "./a11y";
import { noContent, renderClientPage } from "./harness";
import { agentRow, settledPending } from "./fixtures/sharedReads";
import { businessProfileFixture, NEUTRAL_WORDING } from "./businessProfileFixture";

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
      sounds_like: "Namaskaram andi, em kavali?",
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
const page = (
  <ScriptBuilder
    agentId="agent-1"
    knowledgeHref="/c/acme/knowledge"
    trainingHref="/c/acme/agents/agent-1?section=training"
  />
);

const routes = (script: ScriptOut, extra: Record<string, unknown> = {}) => ({
  "/v1/me": OWNER,
  "/v1/agents/agent-1": agentRow(),
  "/v1/agents/agent-1/script": script,
  "POST /v1/agents/agent-1/script/preview": PREVIEW,
  "/v1/agents/agent-1/script/proposed-rules": [],
  "/v1/agents/agent-1/pending": settledPending(),
  "/v1/agents/agent-1/script/proposal": { proposal: null },
  "/v1/business-profile": businessProfileFixture(),
  ...extra,
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("the Script tab leads with the opening line and the steps", () => {
  it("shows each step as its name, what it does and its example line, and the set-once parts as closed rows", async () => {
    const { container } = await renderClientPage(page, routes(out(FULL)));
    const list = await screen.findByRole("list", { name: "Steps of the call, in order" });
    const first = list.querySelector(":scope > li")?.textContent ?? "";
    expect(first).toContain("Greet");
    expect(first).toContain("Say hello and ask what they need.");
    expect(first).toContain("“Namaskaram andi, em kavali?”");
    expect(first).toContain("1 other way out");

    // Who it is, the goal and what it may do are on the page in full; the rest is one row.
    expect((screen.getByLabelText("Your business in one line") as HTMLInputElement).value).toBe(
      "An organic produce shop in Kukatpally",
    );
    expect((screen.getByLabelText("The goal") as HTMLTextAreaElement).closest("details")).toBeNull();
    expect(container.querySelector("#policies")?.closest("details")).toBeNull();
    const parts = screen.getByRole("heading", { name: "About the agent" }).closest("section") as HTMLElement;
    const folded = Array.from(parts.querySelectorAll("details"));
    expect(folded.map((d) => d.querySelector("summary h4")?.textContent)).toEqual(["More settings"]);
    expect(folded[0].open).toBe(false);
    expect(Array.from(folded[0].querySelectorAll("h5")).map((h) => h.textContent)).toEqual([
      "How it speaks",
      "When callers push back",
      "How it ends the call",
      "An example call",
    ]);
    // Closed, every form is still in the document: the assistant's fills and find work.
    expect(within(folded[0]).getByLabelText("Ending")).toBeTruthy();
    expect(within(folded[0]).getByText("Example to check")).toBeTruthy();
  });

  it("opens a step in place, with its rarer options folded and saying what they hold", async () => {
    await renderClientPage(page, routes(out(FULL)));
    const list = await screen.findByRole("list", { name: "Steps of the call, in order" });
    const card = list.querySelector(":scope > li") as HTMLElement;
    const open = within(card).getByRole("button", { expanded: false, name: /Greet/ });
    fireEvent.click(open);
    expect(within(card).getByLabelText("Example line")).toHaveProperty("value", "Namaskaram andi, em kavali?");
    const more = within(card).getByText("More options").closest("details") as HTMLDetailsElement;
    expect(more.open).toBe(false);
    expect(more.textContent).toContain("finds out Delivery area");
    // Far from the limit, no letters count is shown.
    expect(within(card).queryByText(/letters left/)).toBeNull();
    fireEvent.click(within(card).getByRole("button", { expanded: true, name: /Greet/ }));
    expect(within(card).queryByLabelText("Example line")).toBeNull();
  });

  it("shows how much room is left once the script nears the limit", async () => {
    await renderClientPage(
      page,
      routes(out(FULL), { "POST /v1/agents/agent-1/script/preview": { ...PREVIEW, instructions_chars: 7400 } }),
    );
    const meter = await screen.findByRole("meter", { name: "Room left in the instructions" }, { timeout: 4000 });
    expect(meter.getAttribute("aria-valuetext")).toBe("600 letters left");
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
    fireEvent.change(screen.getByRole("textbox", { name: "Opening line" }), { target: { value: "Namaskaram!" } });
    expect(await screen.findByText(/Not saved yet: one part needs finishing/)).toBeTruthy();
    await new Promise((r) => setTimeout(r, 1500));
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});

describe("a link to a part opens it", () => {
  it("leaves the rows closed for #policies, which Knowledge's Fix in script uses and is on the page", async () => {
    window.history.replaceState(null, "", "/c/acme/agents/agent-1/script#policies");
    const { container } = await renderClientPage(page, routes(out(FULL)));
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    expect(container.querySelector("#policies")?.closest("details")).toBeNull();
    expect(Array.from(container.querySelectorAll("details")).filter((d) => d.open)).toEqual([]);
  });

  it("opens More settings for a part folded inside it", async () => {
    window.history.replaceState(null, "", "/c/acme/agents/agent-1/script#objections");
    const { container } = await renderClientPage(page, routes(out(FULL)));
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    const open = Array.from(container.querySelectorAll("details")).filter((d) => d.open);
    expect(open.map((d) => d.querySelector("summary h4")?.textContent)).toEqual(["More settings"]);
    expect(open[0].querySelector("#objections")).toBeTruthy();
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

function listenToPip(): AssistantRequest[] {
  const asked: AssistantRequest[] = [];
  function Listener() {
    useAssistantRequests((request) => asked.push(request));
    return null;
  }
  render(<Listener />);
  return asked;
}

const PROPOSAL: ScriptProposal = {
  id: "p1",
  mode: "change",
  documents: [],
  status: "ready",
  request: "Make the opening line warmer and shorter",
  base_script: FULL,
  script: { ...FULL, opening_line: "Namaskaram andi, Raghava Organics!" },
  unplaced: [],
  disclosure: null,
  note: null,
  requested_at: "2026-10-18T10:00:00+00:00",
};

describe("asking Pip to change the script (D-820)", () => {
  it("prefills Pip with the request and sends nothing itself", async () => {
    const asked = listenToPip();
    const { calls } = await renderClientPage(
      page,
      routes(out(FULL), { "/v1/business-profile": businessProfileFixture() }),
    );
    // Empty, the ask says what is missing rather than sending nothing.
    const ask = await screen.findByRole("button", { name: "Ask Pip" });
    await waitFor(() => expect((ask as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(ask);
    expect(await screen.findByText("Write what should change.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("What should change?"), {
      target: { value: "Offer free delivery when someone asks for a discount" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask Pip" }));
    fireEvent.click(await screen.findByRole("button", { name: /Handle callers who say the price is too high$/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Let Pip draft the whole script: / }));
    expect(asked.map((a) => a.prompt)).toEqual([
      "Change this agent's script: Offer free delivery when someone asks for a discount",
      "Change this agent's script: Handle callers who say the price is too high",
      "Draft the whole script for this agent. Ask me the six questions first.",
    ]);
    expect(calls.some((c) => c.method === "POST" && !c.path.endsWith("/preview"))).toBe(false);
  });

  it("offers the price idea only to a business that quotes prices", async () => {
    await renderClientPage(
      page,
      routes(out(FULL), {
        "/v1/business-profile": businessProfileFixture({
          wording: { ...NEUTRAL_WORDING, price_label: null },
          services: [{ name: "Haircut", price_inr: "", notes: null }],
        }),
      }),
    );
    expect(await screen.findByRole("button", { name: /Make the opening line warmer and shorter$/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /price is too high$/ })).toBeNull();
  });

  it("says while Pip is writing", async () => {
    await renderClientPage(
      page,
      routes(out(FULL), { "/v1/agents/agent-1/script/proposal": { proposal: { ...PROPOSAL, status: "drafting", script: null } } }),
    );
    expect(await screen.findByText("Pip is writing your suggestion…")).toBeTruthy();
  });

  it("reviews the suggestion here and keeps it into the draft, not live", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(out(FULL), {
        "/v1/agents/agent-1/script/proposal": { proposal: PROPOSAL },
        "DELETE /v1/agents/agent-1/script/proposal/p1": noContent(),
      }),
    );
    expect(await screen.findByText("You asked: “Make the opening line warmer and shorter”")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "1 suggested change" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add it to my draft" }));
    await waitFor(() =>
      expect((screen.getByRole("textbox", { name: "Opening line" }) as HTMLTextAreaElement).value).toBe(
        "Namaskaram andi, Raghava Organics!",
      ),
    );
    expect(calls.some((c) => c.method === "DELETE" && c.path.endsWith("/script/proposal/p1"))).toBe(true);
    expect(calls.some((c) => c.path.endsWith("/script/publish"))).toBe(false);
    expect(await screen.findByText("Changes not live yet")).toBeTruthy();
  });

  it("does not offer back an edit made after the suggestion was written", async () => {
    const edited = { ...FULL, goal: "Take the order, the delivery area and a time." };
    await renderClientPage(
      page,
      routes(out(FULL, edited), { "/v1/agents/agent-1/script/proposal": { proposal: PROPOSAL } }),
    );
    expect(await screen.findByRole("heading", { name: "1 suggested change" })).toBeTruthy();
    const review = screen.getByRole("region", { name: "Pip's suggestion" });
    expect(within(review).getByText("Opening line")).toBeTruthy();
    expect(within(review).queryByText("The goal")).toBeNull();
  });

  it("has no axe violations with the ask open and a suggestion waiting", async () => {
    const { container } = await renderClientPage(
      page,
      routes(out(FULL), { "/v1/agents/agent-1/script/proposal": { proposal: PROPOSAL } }),
    );
    await screen.findByRole("button", { name: "Ask Pip" });
    await screen.findByRole("heading", { name: "1 suggested change" });
    await expectNoA11yViolations(container, "script page, Pip's ask and suggestion");
  });

  it("says why a suggestion could not be written", async () => {
    await renderClientPage(
      page,
      routes(out(FULL), {
        "/v1/agents/agent-1/script/proposal": {
          proposal: { ...PROPOSAL, status: "failed", script: null, note: "This month's AI help allowance is used up." },
        },
      }),
    );
    expect(await screen.findByText("Pip could not write that suggestion")).toBeTruthy();
    expect(screen.getByText("This month's AI help allowance is used up.")).toBeTruthy();
  });
});

describe("how closely it follows the steps", () => {
  it("is a two-way switch that sends the same values the radios did", () => {
    const sent: string[] = [];
    function Strictness() {
      const [value, setValue] = useState<"flexible" | "strict">("flexible");
      return (
        <StrictnessSection
          value={value}
          onChange={(next) => {
            sent.push(next);
            setValue(next);
          }}
        />
      );
    }
    render(<Strictness />);
    const group = screen.getByRole("radiogroup", { name: "How closely it follows the steps" });
    expect(within(group).getByRole("radio", { name: "As a guide" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(within(group).getByRole("radio", { name: "Closely" }));
    expect(within(group).getByRole("radio", { name: "Closely" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(within(group).getByRole("radio", { name: "As a guide" }));
    expect(sent).toEqual(["strict", "flexible"]);
  });
});
