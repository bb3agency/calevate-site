import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { LeftOutNotice, lineWarningsOf } from "@/app/c/[slug]/agents/[agentId]/script/PipProposal";
import { ProposalReview } from "@/app/c/[slug]/agents/[agentId]/script/ProposalReview";
import { diffScripts } from "@/app/c/[slug]/agents/[agentId]/script/scriptDiff";
import { DEFAULT_LIMITS, validate } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import {
  TURNS_MAX,
  TURNS_MIN,
  addTurn,
  examplesAsk,
  exampleProblems,
  isExamplePath,
  removeTurn,
  startExamples,
  warningsAt,
  type Examples,
  type LineWarning,
} from "@/app/c/[slug]/agents/[agentId]/script/stepExamples";
import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import type { ExamplesAsk } from "@/app/c/[slug]/agents/[agentId]/script/StepExamplesEditor";
import { ToastProvider } from "@/components/arc/toast";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import { expectNoA11yViolations } from "./a11y";
import { renderClientPage } from "./harness";

/**
 * A step's examples (script rebuild, 26 Nov 2026): per language, 3 to 5 ways the agent says
 * it and the hard moments, edited where the step is edited and shown on Pip's draft. Lines
 * are English placeholders standing in for the call's language.
 */

const EX: Examples = {
  turns: ["Way one.", "Way two.", "Way three."],
  confused: "Said again, shorter.",
  stuck: "One smaller action.",
  busy: "When should I call back?",
};

const stage = (over: Partial<ConversationStage>): ConversationStage => ({
  id: "a",
  name: "A",
  mode: "guide",
  instruction: "Do A.",
  sounds_like: "",
  branches: [],
  otherwise: "",
  collect: [],
  procedure: [],
  position: null,
  step: 1,
  scripts: {},
  qa: [],
  coaching: [],
  ...over,
});

const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: "Hello.",
  stages: [
    stage({ id: "intro", name: "Introduction", step: 1, examples: { "te-IN": EX } }),
    stage({ id: "open", name: "Open the app", step: 2, sounds_like: "Please open the app." }),
  ],
};

/** The flow with one scenario chosen, holding its own state so edits show. */
function Flow({
  start = SCRIPT,
  chosen,
  warnings = [],
  ask,
  onChange,
}: {
  start?: CallScript;
  chosen: string;
  warnings?: LineWarning[];
  ask?: ExamplesAsk;
  onChange?: (next: CallScript) => void;
}) {
  const [script, setScript] = useState(start);
  return (
    <ToastProvider>
      <ScenarioFlow
        agent={null}
        direction="outbound"
        hear={{ allowed: true, reason: null, unknown: false }}
        script={script}
        limits={DEFAULT_LIMITS}
        issues={validate(script, DEFAULT_LIMITS)}
        languages={["te-IN"]}
        selected={chosen}
        readOnly={false}
        wide
        warnings={warnings}
        writeExamples={ask ? () => ask : undefined}
        onSelect={() => {}}
        onChange={(next) => {
          setScript(next);
          onChange?.(next);
        }}
      />
    </ToastProvider>
  );
}

const examplesBlock = () => screen.getByTestId("examples");
const stagesOf = (fn: ReturnType<typeof vi.fn>) => (fn.mock.calls.at(-1)?.[0] as CallScript).stages;

describe("the examples model", () => {
  it("keeps between 3 and 5 turns", () => {
    let ex = { ...EX, turns: [...EX.turns] };
    expect(removeTurn(ex, 0).turns).toHaveLength(TURNS_MIN);
    for (let i = 0; i < 4; i += 1) ex = addTurn(ex);
    expect(ex.turns).toHaveLength(TURNS_MAX);
    expect(removeTurn(ex, 4).turns).toHaveLength(TURNS_MAX - 1);
  });

  it("starts hand-written examples from the old example line", () => {
    expect(startExamples("Old line.").turns).toEqual(["Old line.", "", ""]);
  });

  it("refuses a line over the limit and more than 5 turns, never a blank one", () => {
    const long = "x".repeat(201);
    const problems = exampleProblems({
      "te-IN": { ...EX, turns: ["", long, "a", "b", "c", "d", "e"], stuck: long },
    });
    expect(problems.map((p) => p.field)).toEqual(["examples-te-IN", "examples-te-IN-turn-1", "examples-te-IN-stuck"]);
    expect(exampleProblems({ "te-IN": { ...EX, turns: ["", "", ""] } })).toEqual([]);
  });

  it("places a warning on its own line, and drops it once that line is rewritten", () => {
    const w: LineWarning = { path: "stages.intro.examples.te-IN.turns.1", message: "Two actions.", text: "Way two." };
    expect(isExamplePath(w.path)).toBe(true);
    expect(isExamplePath("stages.intro")).toBe(false);
    expect(warningsAt([w], "intro", "te-IN", { turn: 1 }, "Way two.")).toHaveLength(1);
    expect(warningsAt([w], "intro", "te-IN", { turn: 0 }, "Way one.")).toHaveLength(0);
    expect(warningsAt([w], "intro", "te-IN", { turn: 1 }, "Rewritten.")).toHaveLength(0);
    expect(warningsAt([w], "intro", "hi-IN", { turn: 1 }, "Way two.")).toHaveLength(0);
  });

  it("asks Pip for the busy moment on the first step only", () => {
    expect(examplesAsk(true)).toContain("busy");
    expect(examplesAsk(false)).not.toContain("busy");
  });

  it("lists a step whose examples alone changed, and not one only re-spaced", () => {
    const changed: CallScript = {
      ...SCRIPT,
      stages: SCRIPT.stages.map((s) => (s.id === "intro" ? { ...s, examples: { "te-IN": { ...EX, stuck: "Other." } } } : s)),
    };
    expect(diffScripts(SCRIPT, changed).map((c) => c.id)).toEqual(["change:intro"]);
    const spaced: CallScript = {
      ...SCRIPT,
      stages: SCRIPT.stages.map((s) =>
        s.id === "intro" ? { ...s, examples: { "te-IN": { ...EX, turns: [...EX.turns, "  "], stuck: " One smaller  action. " } } } : s,
      ),
    };
    expect(diffScripts(SCRIPT, spaced)).toEqual([]);
  });
});

describe("examples in the scenario editor", () => {
  it("edits a way, adds up to five and removes down to three", async () => {
    const onChange = vi.fn();
    await renderClientPage(<Flow chosen="intro" onChange={onChange} />, {});
    const block = examplesBlock();
    fireEvent.change(within(block).getByRole("textbox", { name: "Way 2" }), { target: { value: "A new way." } });
    expect(stagesOf(onChange)[0].examples?.["te-IN"]?.turns).toEqual(["Way one.", "A new way.", "Way three."]);

    expect((within(block).getByRole("button", { name: "Remove way 1" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(block).getByRole("button", { name: "Add another way" }));
    fireEvent.click(within(block).getByRole("button", { name: "Add another way" }));
    expect(within(block).getAllByRole("textbox", { name: /^Way \d$/ })).toHaveLength(5);
    expect(within(block).queryByRole("button", { name: "Add another way" })).toBeNull();
    expect(within(block).getByText("5 is the most.")).toBeTruthy();
    fireEvent.click(within(block).getByRole("button", { name: "Remove way 5" }));
    expect(stagesOf(onChange)[0].examples?.["te-IN"]?.turns).toHaveLength(4);
  });

  it("asks what to say when busy on the first step only", async () => {
    const first = await renderClientPage(<Flow chosen="intro" />, {});
    expect(screen.getByLabelText("If they're confused")).toBeTruthy();
    expect(screen.getByLabelText("If they're stuck")).toBeTruthy();
    expect(screen.getByLabelText("If they're busy")).toBeTruthy();
    first.unmount();
    const later: CallScript = {
      ...SCRIPT,
      stages: SCRIPT.stages.map((s) => (s.id === "open" ? { ...s, examples: { "te-IN": EX } } : s)),
    };
    await renderClientPage(<Flow start={later} chosen="open" />, {});
    expect(screen.getByLabelText("If they're stuck")).toBeTruthy();
    expect(screen.queryByLabelText("If they're busy")).toBeNull();
  });

  it("shows a check's warning on the line it is about, with the detail behind a tap", async () => {
    const warnings: LineWarning[] = [
      { path: "stages.intro.examples.te-IN.turns.2", message: "Asks for two things.", detail: "Give one action and stop." },
    ];
    await renderClientPage(<Flow chosen="intro" warnings={warnings} />, {});
    const way3 = screen.getByRole("textbox", { name: "Way 3" });
    const line = way3.parentElement as HTMLElement;
    expect(within(line).getByText("Asks for two things.")).toBeTruthy();
    expect(way3.getAttribute("aria-describedby")).toContain("warn");
    expect(within(screen.getByRole("textbox", { name: "Way 1" }).parentElement as HTMLElement).queryByText("Asks for two things.")).toBeNull();
    expect(screen.queryByText("Give one action and stop.")).toBeNull();
    fireEvent.click(within(line).getByRole("button", { name: "Why?" }));
    expect(screen.getByText("Give one action and stop.")).toBeTruthy();
  });

  it("keeps an old step's example line read-only, with Pip or the owner to write examples", async () => {
    const run = vi.fn();
    const onChange = vi.fn();
    // The old line is the script box's while that box is empty, so give the box its own line.
    const old: CallScript = {
      ...SCRIPT,
      stages: SCRIPT.stages.map((s) => (s.id === "open" ? { ...s, scripts: { "te-IN": "Open it now." } } : s)),
    };
    await renderClientPage(<Flow start={old} chosen="open" ask={{ run, wait: null }} onChange={onChange} />, {});
    const empty = screen.getByTestId("examples-empty");
    expect(within(empty).getByText("Please open the app.")).toBeTruthy();
    expect(within(empty).queryByRole("textbox")).toBeNull();
    fireEvent.click(within(empty).getByRole("button", { name: "Let Pip write examples" }));
    expect(run).toHaveBeenCalledOnce();
    fireEvent.click(within(empty).getByRole("button", { name: "Write them myself" }));
    expect(stagesOf(onChange)[1].examples?.["te-IN"]?.turns).toEqual(["Please open the app.", "", ""]);
  });

  it("says why Pip cannot write examples yet", async () => {
    await renderClientPage(<Flow chosen="open" ask={{ run: () => {}, wait: "Save your changes first." }} />, {});
    const button = screen.getByRole("button", { name: "Let Pip write examples" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("Save your changes first.")).toBeTruthy();
  });

  it("passes axe with examples, warnings and the old line", async () => {
    const warnings: LineWarning[] = [{ path: "stages.intro.examples.te-IN.confused", message: "Too long.", detail: "Shorter." }];
    const a = await renderClientPage(<Flow chosen="intro" warnings={warnings} />, {});
    await expectNoA11yViolations(a.container, "scenario editor with examples");
    a.unmount();
    const b = await renderClientPage(<Flow chosen="open" ask={{ run: () => {} }} />, {});
    await expectNoA11yViolations(b.container, "scenario editor with an old example line");
  });
});

describe("examples on Pip's draft", () => {
  const PROPOSAL: CallScript = {
    ...SCRIPT,
    stages: SCRIPT.stages.map((s) => (s.id === "open" ? { ...s, examples: { "te-IN": { ...EX, turns: ["Open it.", "Tap it.", "Find it."] } } } : s)),
  };
  const warnings: LineWarning[] = [{ path: "stages.open.examples.te-IN.turns.1", message: "Reaction at the start." }];
  const review = (onApply = vi.fn()) =>
    render(
      <ProposalReview
        current={SCRIPT}
        proposal={PROPOSAL}
        languages={[{ tag: "te-IN", name: "Telugu" }]}
        warnings={warnings}
        onApply={onApply}
        onDiscard={() => {}}
      />,
    );

  it("shows the examples Pip wrote, with the warning on its line", () => {
    review();
    const readout = screen.getByTestId("examples-readout");
    expect(within(readout).getByText("Tap it.")).toBeTruthy();
    expect(within(readout).getByText("Reaction at the start.")).toBeTruthy();
    // Not on the first step: no busy line.
    expect(within(readout).queryByText(/If they're busy/)).toBeNull();
  });

  it("opens them for editing and keeps the edit", () => {
    const onApply = vi.fn();
    review(onApply);
    fireEvent.click(screen.getByRole("button", { name: "Review Open the app" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Way 3" }), { target: { value: "Find the app." } });
    fireEvent.click(screen.getByRole("button", { name: "Update Open the app" }));
    fireEvent.click(screen.getByRole("button", { name: "Add it to my draft" }));
    const kept = (onApply.mock.calls[0]?.[0] as CallScript).stages.find((s) => s.id === "open");
    expect(kept?.examples?.["te-IN"]?.turns).toEqual(["Open it.", "Tap it.", "Find the app."]);
  });

  it("passes axe, closed and open", async () => {
    const r = review();
    await expectNoA11yViolations(r.container, "draft review with examples");
    fireEvent.click(screen.getByRole("button", { name: "Review Open the app" }));
    await expectNoA11yViolations(r.container, "draft review with examples open");
  });

  it("takes line warnings out of the left-out notice and onto their lines", () => {
    const parts = [
      { part: "stages.open.examples.te-IN.turns.1", label: "Open the app", rule: "Reaction at the start.", added: false, unfixed: true },
      { part: "stages.open", label: "Open the app", rule: "Too many actions.", added: false, unfixed: true },
    ];
    expect(lineWarningsOf(parts)).toEqual([{ path: "stages.open.examples.te-IN.turns.1", message: "Reaction at the start." }]);
    render(<LeftOutNotice parts={parts} />);
    expect(screen.queryByText(/Reaction at the start/)).toBeNull();
    expect(screen.getByText(/Too many actions/)).toBeTruthy();
  });
});
