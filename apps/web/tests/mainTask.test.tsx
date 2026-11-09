import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import { MainTask } from "@/app/c/[slug]/agents/[agentId]/sections/mainTask";
import { ProposalReview, tally } from "@/app/c/[slug]/agents/[agentId]/script/ProposalReview";
import { changedSegments, diffScripts } from "@/app/c/[slug]/agents/[agentId]/script/scriptDiff";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut } from "@/lib/api/script";

import { renderClientPage } from "./harness";

/*
 * THE AGENT'S MAIN TASK ON THE AGENT PAGE (founder, 9 Nov 2026): three lines before "Show
 * more", an Edit that saves into the draft like any script edit, and "Re-adjust script",
 * which asks Pip for a suggestion reviewed on the Script tab. Then the review itself, which
 * marks what a suggestion adds, changes and removes.
 */

const GOAL = "Get the farmer to install the app and open it once while on the call.";

function scriptRead(goal: string, over: Partial<ScriptOut> = {}): ScriptOut {
  return {
    script: { ...EMPTY_SCRIPT, goal },
    draft: null,
    version: 3,
    is_freeform: false,
    has_pending: false,
    standard_variables: [],
    stored_schema_version: 2,
    context: null,
    ...over,
  } as ScriptOut;
}

/** jsdom lays nothing out: give the clamped box the overflow a browser would measure. */
function overflowing(on: boolean) {
  const scroll = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(on ? 120 : 40);
  const client = vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(60);
  onTestFinished(() => {
    scroll.mockRestore();
    client.mockRestore();
  });
}

async function renderTask(
  props: { out?: ScriptOut; canWrite?: boolean; openScript?: () => void } = {},
  routes: Record<string, unknown> = {},
) {
  return renderClientPage(
    <MainTask
      agentId="agent-1"
      out={props.out ?? scriptRead(GOAL)}
      canWrite={props.canWrite ?? true}
      openScript={props.openScript ?? (() => undefined)}
    />,
    routes,
  );
}

describe("the main task under the agent's name", () => {
  it("shows three lines, then Show more under the text, and Show less once open", async () => {
    overflowing(true);
    await renderTask();
    const label = screen.getByText("Main task:");
    const box = label.parentElement as HTMLElement;
    expect(box.textContent).toContain(GOAL);
    expect(box.style.webkitLineClamp).toBe("3");

    expect(screen.queryByRole("button", { name: "Read more" })).toBeNull();
    const more = screen.getByRole("button", { name: "Show more" });
    // Below the text, not beside it: the toggle follows the clamped block.
    expect(box.compareDocumentPosition(more) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(box.contains(more)).toBe(false);

    fireEvent.click(more);
    expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("offers no toggle when the task fits in three lines", async () => {
    overflowing(false);
    await renderTask();
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("gives someone who cannot manage the account no Edit and no Re-adjust", async () => {
    await renderTask({ canWrite: false });
    expect(screen.getByText(GOAL, { exact: false })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Edit main task" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-adjust script" })).toBeNull();
  });

  it("offers neither for a script written as one text", async () => {
    await renderTask({
      out: scriptRead(GOAL, { script: { ...EMPTY_SCRIPT, goal: GOAL, raw_override: "Say hello." } }),
    });
    expect(screen.queryByRole("button", { name: "Edit main task" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-adjust script" })).toBeNull();
  });

  it("saves an edited task into the draft as a compare-and-set, and says it is not live yet", async () => {
    const { calls } = await renderTask({}, {
      "PUT /v1/agents/agent-1/script/draft": { saved_at: "2026-11-09T08:00:00Z" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Edit main task" }));
    const field = screen.getByRole("textbox", { name: "Main task" }) as HTMLTextAreaElement;
    expect(field.value).toBe(GOAL);
    expect(field.maxLength).toBe(1000);

    // A blank task is refused here, before anything is sent.
    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Write its main task, or cancel.")).toBeTruthy();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);

    fireEvent.change(field, { target: { value: "Book a site visit for this week." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.path).toBe("/v1/agents/agent-1/script/draft");
    const body = JSON.parse(put.body ?? "{}");
    expect(body.script.goal).toBe("Book a site visit for this week.");
    // No draft was on file when the edit started: the server refuses one made since.
    expect(body).toHaveProperty("base_saved_at", null);
  });

  it("marks a task waiting in the draft as not live yet", async () => {
    await renderTask({
      out: scriptRead(GOAL, {
        draft: { script: { ...EMPTY_SCRIPT, goal: "Book a site visit." }, saved_at: "2026-11-09T08:00:00Z" },
      }),
    });
    expect(screen.getByText("Book a site visit.", { exact: false })).toBeTruthy();
    expect(screen.getByText("Not live yet")).toBeTruthy();
  });

  it("asks first, then asks Pip for a suggestion and opens the Script tab to review it", async () => {
    const openScript = vi.fn();
    const { calls } = await renderTask(
      { openScript },
      {
        "POST /v1/agents/agent-1/script/proposal/main-task": {
          id: "p1",
          mode: "change",
          documents: [],
          status: "drafting",
          request: `Adjust this script to its main task: ${GOAL}`,
          base_script: { ...EMPTY_SCRIPT, goal: GOAL },
          script: null,
          unplaced: [],
          disclosure: null,
          note: null,
          requested_at: "2026-11-09T08:00:00Z",
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Re-adjust script" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Uses your AI help allowance.");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    fireEvent.click(within(dialog).getByRole("button", { name: "Re-adjust script" }));
    await waitFor(() => expect(openScript).toHaveBeenCalledTimes(1));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.path).toBe("/v1/agents/agent-1/script/proposal/main-task");
  });
});

const STEP = {
  id: "pitch",
  name: "Explain the app",
  mode: "guide" as const,
  instruction: "Say what the app does. Ask if they farm paddy.",
  sounds_like: "",
  branches: [],
  otherwise: "",
  collect: [],
  position: null,
};

describe("a suggestion's major changes stand out", () => {
  it("marks the sentences a changed step adds and drops, in words as well as colour", () => {
    const current: CallScript = { ...EMPTY_SCRIPT, goal: GOAL, stages: [STEP] };
    const proposal: CallScript = {
      ...current,
      stages: [
        { ...STEP, instruction: "Say what the app does. Help them install it now." },
        { ...STEP, id: "close", name: "Close", instruction: "Thank them and end the call." },
      ],
    };
    const { container } = render(
      <ProposalReview current={current} proposal={proposal} onApply={() => undefined} onDiscard={() => undefined} />,
    );
    // Each row says its kind in a word beside the colour.
    expect(screen.getByText("New step")).toBeTruthy();
    expect(screen.getByText("Step changed")).toBeTruthy();
    // The counts above the list.
    expect(screen.getByRole("list", { name: "Changes by kind" }).textContent).toContain("1 new");

    const marks = Array.from(container.querySelectorAll("mark"));
    const added = marks.find((m) => m.textContent?.includes("Help them install it now."));
    const dropped = marks.find((m) => m.textContent?.includes("Ask if they farm paddy."));
    expect(added?.querySelector(".sr-only")?.textContent).toBe("New: ");
    expect(dropped?.querySelector(".sr-only")?.textContent).toBe("Removed: ");
    // The sentence both say alike is not marked.
    expect(marks.some((m) => m.textContent?.includes("Say what the app does."))).toBe(false);
  });

  it("does not list a change nobody would hear", () => {
    const current: CallScript = { ...EMPTY_SCRIPT, goal: GOAL, stages: [STEP] };
    const respaced: CallScript = {
      ...current,
      goal: `  ${GOAL.replace(" the app", "  the app")}\n`,
      stages: [{ ...STEP, instruction: `${STEP.instruction}  ` }],
    };
    expect(diffScripts(current, respaced)).toEqual([]);
  });

  it("splits a quote into sentences and marks only the new ones", () => {
    expect(changedSegments("One. Two? Three.", "One. Three.").map((s) => [s.text, s.changed])).toEqual([
      ["One.", false],
      ["Two?", true],
      ["Three.", false],
    ]);
  });

  it("counts new, changed and removed separately", () => {
    const current: CallScript = { ...EMPTY_SCRIPT, goal: GOAL, ending: "Bye.", stages: [STEP] };
    const proposal: CallScript = { ...current, goal: "Book a visit.", ending: "", stages: [] };
    expect(tally(diffScripts(current, proposal)).map((t) => t.label)).toEqual(["1 changed", "2 removed"]);
  });
});
