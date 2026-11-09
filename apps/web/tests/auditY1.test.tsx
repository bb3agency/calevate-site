import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import { ProposalReview } from "@/app/c/[slug]/agents/[agentId]/script/ProposalReview";
import { ScriptBuilder } from "@/app/c/[slug]/agents/[agentId]/script/ScriptBuilder";
import { MainTask } from "@/app/c/[slug]/agents/[agentId]/sections/mainTask";
import type { Section } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import type { Me } from "@/lib/api/client";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut } from "@/lib/api/script";
import { UnsavedRegistry } from "@/lib/useUnsavedGuard";

import { businessProfileFixture } from "./businessProfileFixture";
import { renderClientPage } from "./harness";
import { agentRow, settledPending } from "./fixtures/sharedReads";

/**
 * Frontend audit 10 Nov 2026, lane Y1 (client agent screens: the script builder).
 */

function step(id: string, name: string, instruction: string, extra: Partial<Section> = {}): Section {
  return {
    id,
    name,
    mode: "guide",
    instruction,
    sounds_like: "",
    branches: [],
    otherwise: "",
    collect: [],
    procedure: [],
    position: null,
    ...extra,
  };
}

const GREET = step("greet", "Greet", "Say hello.");
const PRICE = step("price", "Price", "Say the price.");
const CLOSE = step("close", "Close", "Agree the next step.");
/** What Pip saw when it wrote the suggestion. */
const BASE: CallScript = { ...EMPTY_SCRIPT, schema_version: 2, stages: [GREET, PRICE, CLOSE] };

describe("a Pip suggestion reviewed after the owner changed the draft (Y1-01)", () => {
  it("does not offer a change to a step the owner deleted since, or count it as added", () => {
    const onApply = vi.fn();
    const proposal: CallScript = { ...BASE, stages: [GREET, { ...PRICE, instruction: "Say the price per kilo." }, CLOSE] };
    // The owner deleted Price while the suggestion was open.
    const current: CallScript = { ...BASE, stages: [GREET, CLOSE] };
    render(<ProposalReview current={current} base={BASE} proposal={proposal} onApply={onApply} onDiscard={() => undefined} />);

    const row = screen.getByText("Price").closest("li")!;
    expect(within(row).getByText("You deleted this step after Pip wrote this.")).toBeTruthy();
    const box = within(row).getByRole("checkbox") as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(box.disabled).toBe(true);
    // Nothing is left to add: the button cannot say it adds a change it would drop.
    expect(screen.queryByRole("button", { name: /Add it to my draft|Add all/ })).toBeNull();
    expect((screen.getByRole("button", { name: /to my draft/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("warns that keeping a change replaces what the owner wrote in that step since", () => {
    const onApply = vi.fn();
    const proposal: CallScript = { ...BASE, stages: [GREET, { ...PRICE, sounds_like: "It is 200 a kilo." }, CLOSE] };
    const current: CallScript = { ...BASE, stages: [GREET, { ...PRICE, instruction: "Say the price and the offer." }, CLOSE] };
    render(<ProposalReview current={current} base={BASE} proposal={proposal} onApply={onApply} onDiscard={() => undefined} />);

    const row = screen.getByText("Price").closest("li")!;
    expect(within(row).getByText("You changed this step since. Keeping this replaces your change.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add it to my draft" }));
    expect(onApply).toHaveBeenCalledOnce();
  });

  it("says nothing extra when the draft is still what Pip saw", () => {
    const proposal: CallScript = { ...BASE, stages: [GREET, { ...PRICE, instruction: "Say the price per kilo." }, CLOSE] };
    render(<ProposalReview current={BASE} base={BASE} proposal={proposal} onApply={() => undefined} onDiscard={() => undefined} />);
    expect(screen.queryByText(/after Pip wrote this|since\. Keeping/)).toBeNull();
    expect(screen.getByRole("button", { name: "Add it to my draft" })).toBeTruthy();
  });
});

describe("a suggestion reworded in the review (Y1-06)", () => {
  it("counts as unsaved work, so leaving the tab asks first", () => {
    const report = vi.fn();
    const proposal: CallScript = { ...BASE, goal: "Take orders and bookings." };
    render(
      <UnsavedRegistry.Provider value={{ report }}>
        <ProposalReview current={BASE} base={BASE} proposal={proposal} onApply={() => undefined} onDiscard={() => undefined} />
      </UnsavedRegistry.Provider>,
    );
    expect(report).not.toHaveBeenCalledWith(expect.anything(), true);
    fireEvent.click(screen.getByRole("button", { name: "Edit The goal" }));
    fireEvent.change(screen.getByLabelText("The goal", { selector: "textarea" }), {
      target: { value: "Take orders, bookings and returns." },
    });
    expect(report).toHaveBeenLastCalledWith(expect.any(String), true);
  });
});

// --- the builder ---------------------------------------------------------------------------

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Raghava Organics", slug: "acme", status: "active" },
};

const SAVED_AT = "2026-11-10T09:00:00.000001+00:00";
const page = (
  <ScriptBuilder agentId="agent-1" knowledgeHref="/c/acme/knowledge" trainingHref="/c/acme/agents/agent-1?section=training" />
);

function scriptOut(script: CallScript, draft: { script: CallScript; saved_at: string } | null = null): ScriptOut {
  return {
    script,
    draft,
    stored_schema_version: 2,
    context: null,
    version: 3,
    is_freeform: false,
    has_pending: false,
    standard_variables: [],
  };
}

const routes = (script: unknown, extra: Record<string, unknown> = {}) => ({
  "/v1/me": OWNER,
  "/v1/agents/agent-1": agentRow(),
  "/v1/agents/agent-1/script": script,
  "/v1/agents/agent-1/script/tests": { available: false, unavailable_reason: "Not yet.", cost_note: "", latest: null, history: [] },
  "POST /v1/agents/agent-1/script/preview": { compiled: "", instructions_chars: 2000, instructions_limit: 8000, native_steps: 0 },
  "POST /v1/agents/agent-1/script/check": { warnings: [] },
  "/v1/agents/agent-1/script/proposed-rules": [],
  "/v1/agents/agent-1/script/proposal": { proposal: null },
  "/v1/business-profile": businessProfileFixture(),
  "/v1/agents/agent-1/pending": settledPending(),
  ...extra,
});

function cards(): HTMLElement[] {
  const list = screen.getByRole("list", { name: "Steps of the call, in order" });
  return Array.from(list.querySelectorAll<HTMLElement>(":scope > li"));
}

describe("a step added after a step that ends the call (Y1-02)", () => {
  it("is reached: the step before it goes on to it, and it ends the call instead", async () => {
    // An agent that does both calling jobs closes each block with an explicit end
    // (`starters._block`), and an owner can pick "End the call" on any step.
    const script: CallScript = { ...BASE, stages: [GREET, { ...CLOSE, otherwise: "end" }] };
    await renderClientPage(page, routes(scriptOut(script)));
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    expect(cards()[1].textContent).toContain("Then: End the call");

    fireEvent.click(await screen.findByRole("button", { name: "Add a step after 2" }));
    await waitFor(() => expect(cards()).toHaveLength(3));
    expect(cards()[1].textContent).not.toContain("End the call");
    expect(cards()[2].textContent).toContain("Then: End the call");
  });

  it("between two steps, sits on the way from the first to the second", async () => {
    const script: CallScript = { ...BASE, stages: [{ ...GREET, otherwise: "close" }, CLOSE] };
    await renderClientPage(page, routes(scriptOut(script)));
    fireEvent.click(await screen.findByRole("button", { name: "Add a step between 1 and 2" }));
    await waitFor(() => expect(cards()).toHaveLength(3));
    // Greet no longer jumps over the new step to Close.
    expect(cards()[0].textContent).not.toContain("Close");
    expect(cards()[1].textContent).toContain("Then: 3. Close");
  });
});

describe("Add a step from the keyboard (Y1-04)", () => {
  it("reaches 'after the last step' once past that step, and lands in the new step's fields", async () => {
    const script: CallScript = { ...BASE, stages: [GREET, CLOSE] };
    await renderClientPage(page, routes(scriptOut(script)));
    const after = await screen.findByRole("button", { name: "Add a step after 2" });
    const lastDelete = screen.getByRole("button", { name: "Delete Close" });
    // Tab order is document order: the button must come after step 2's own controls.
    expect(lastDelete.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    after.focus();
    fireEvent.click(after);
    await waitFor(() => expect(cards()).toHaveLength(3));
    await waitFor(() => expect(cards()[2].contains(document.activeElement)).toBe(true));
    expect(["INPUT", "TEXTAREA"]).toContain(document.activeElement?.tagName);
  });
});

describe("a step added in the flow picture (Y1-07)", () => {
  it("does not pull the page to it, or take the focus, when the list is shown later", async () => {
    const real = window.matchMedia;
    window.matchMedia = ((query: string) => ({ ...real(query), matches: query.includes("min-width") || real(query).matches })) as typeof window.matchMedia;
    const scrolled = vi.fn();
    const scroll = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrolled;
    onTestFinished(() => {
      window.matchMedia = real;
      Element.prototype.scrollIntoView = scroll;
    });
    await renderClientPage(page, routes(scriptOut({ ...BASE, stages: [GREET, CLOSE] })));
    const menu = async () => fireEvent.click(await screen.findByRole("button", { name: "More actions for this script" }));
    await menu();
    fireEvent.click(await screen.findByRole("menuitem", { name: "Show the call as a flow" }));
    await waitFor(() => expect(screen.queryByRole("list", { name: "Steps of the call, in order" })).toBeNull());
    fireEvent.click(await screen.findByRole("button", { name: "Add a step" }));
    await menu();
    fireEvent.click(await screen.findByRole("menuitem", { name: "Show the steps as a list" }));
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    await new Promise((r) => setTimeout(r, 50));
    expect(scrolled).not.toHaveBeenCalled();
    expect(["INPUT", "TEXTAREA"]).not.toContain(document.activeElement?.tagName);
  });
});

describe("deleting one step from its card while another is open (Y1-08)", () => {
  it("leaves the open step open", async () => {
    await renderClientPage(page, routes(scriptOut({ ...BASE, stages: [GREET, PRICE, CLOSE] })));
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    const greet = () => within(cards()[0]).getAllByRole("button").find((b) => b.hasAttribute("aria-expanded"))!;
    fireEvent.click(greet());
    expect(greet().getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(await screen.findByRole("button", { name: "Delete Close" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete step" }));
    await waitFor(() => expect(cards()).toHaveLength(2));
    expect(greet().getAttribute("aria-expanded")).toBe("true");
  });
});

describe("adding a main task, then cancelling (Y1-05)", () => {
  it("puts the focus back on the button that opened the field", async () => {
    await renderClientPage(
      <MainTask agentId="agent-1" out={scriptOut({ ...BASE, goal: "" })} canWrite openScript={() => undefined} />,
      {},
    );
    fireEvent.click(screen.getByRole("button", { name: "Add its main task" }));
    await waitFor(() => expect(document.activeElement?.tagName).toBe("TEXTAREA"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add its main task" })));
  });
});

describe("the main task edited in the header while the builder holds unsaved steps (Y1-03)", () => {
  it("joins both: the new task and the owner's unsaved step, with no conflict to choose", async () => {
    const script: CallScript = { ...BASE, goal: "Take orders.", stages: [GREET, CLOSE] };
    let current = scriptOut(script, { script, saved_at: SAVED_AT });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { calls } = await renderClientPage(
      page,
      routes(() => current, { "PUT /v1/agents/agent-1/script/draft": { saved_at: "2026-11-10T09:10:00+00:00" } }),
      "acme",
      qc,
    );
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    // A new step with nothing written yet: the autosave waits for it.
    fireEvent.click(await screen.findByRole("button", { name: "Add a step after 2" }));
    await waitFor(() => expect(cards()).toHaveLength(3));

    // The header's Edit saved a new main task into the draft (`MainTask`).
    const later = "2026-11-10T09:05:00+00:00";
    current = scriptOut(script, { script: { ...script, goal: "Take orders and bookings." }, saved_at: later });
    await act(async () => {
      await qc.invalidateQueries();
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("This draft was changed somewhere else")).toBeNull();
    expect(cards()).toHaveLength(3);

    fireEvent.change(screen.getByPlaceholderText("For example: Ask what they need and when."), {
      target: { value: "Ask what else they need." },
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true), { timeout: 4000 });
    const body = JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}");
    expect(body.base_saved_at).toBe(later);
    expect(body.script.goal).toBe("Take orders and bookings.");
    expect(body.script.stages).toHaveLength(3);
  });

  it("still asks when both changed the same part", async () => {
    const script: CallScript = { ...BASE, goal: "Take orders.", stages: [GREET, CLOSE] };
    let current = scriptOut(script, { script, saved_at: SAVED_AT });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    await renderClientPage(page, routes(() => current), "acme", qc);
    await screen.findByRole("list", { name: "Steps of the call, in order" });
    fireEvent.click(await screen.findByRole("button", { name: "Add a step after 2" }));
    await waitFor(() => expect(cards()).toHaveLength(3));
    // Somebody else changed the steps too.
    current = scriptOut(script, { script: { ...script, stages: [GREET] }, saved_at: "2026-11-10T09:05:00+00:00" });
    await act(async () => {
      await qc.invalidateQueries();
    });
    expect(await screen.findByText("This draft was changed somewhere else")).toBeTruthy();
  });
});
