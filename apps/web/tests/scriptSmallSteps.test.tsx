import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { SmallSteps } from "@/app/c/[slug]/agents/[agentId]/script/SmallSteps";
import {
  DEFAULT_LIMITS,
  addSmallStep,
  moveSmallStep,
  procedurePointer,
  scriptAsText,
  sectionDetail,
  sectionReadable,
  sectionsOf,
  validate,
  type SmallStep,
} from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { diffScripts } from "@/app/c/[slug]/agents/[agentId]/script/scriptDiff";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

/**
 * A step's small steps (D-908): the ordered actions a caller does one at a time. The step's
 * 600 letters count the server's pointer to them, the list is checked like the server checks
 * it, and the editor adds, reorders and removes them with phone-sized controls.
 */

const INSTALL: SmallStep[] = [
  { action: "Ask them to open Chrome.", wait_for: "they say it is open" },
  { action: "Ask them to type rytukhata.app.", wait_for: "" },
];

function stage(extra: Partial<ConversationStage> = {}): ConversationStage {
  return {
    id: "install",
    name: "Install the app",
    mode: "guide",
    instruction: "Help them put the app on their phone.",
    sounds_like: "",
    branches: [],
    otherwise: "",
    collect: [],
    procedure: INSTALL,
    position: null,
    ...extra,
  };
}

function script(...stages: ConversationStage[]): CallScript {
  return { ...EMPTY_SCRIPT, schema_version: 2, stages };
}

describe("a step's small steps in the script model", () => {
  it("counts the server's pointer inside the step's letters, only when there are small steps", () => {
    const [section] = sectionsOf(script(stage()));
    expect(sectionDetail(section)).toBe(
      'Help them put the app on their phone. Then go through its steps under "Install the app" in [STEP BY STEP], one at a time.',
    );
    expect(procedurePointer("Install the app")).toContain('"Install the app"');
    const [plain] = sectionsOf(script(stage({ procedure: [] })));
    expect(sectionDetail(plain)).toBe("Help them put the app on their phone.");
    const room = DEFAULT_LIMITS.detailMax - procedurePointer("Install the app").length - 1;
    expect(validate(script(stage({ instruction: "x".repeat(room) })))).toEqual([]);
    expect(
      validate(script(stage({ instruction: "x".repeat(room + 1) }))).some((i) => i.field === "instruction"),
    ).toBe(true);
  });

  it("refuses an empty small step, a long one and more than the limit", () => {
    const issues = validate(
      script(
        stage({
          procedure: [
            { action: "  ", wait_for: "" },
            { action: "a".repeat(201), wait_for: "w".repeat(121) },
          ],
        }),
      ),
    ).map((i) => i.field);
    expect(issues).toEqual(["procedure-0", "procedure-1", "procedure-1"]);
    const many = Array.from({ length: 16 }, (_, i) => ({ action: `Step ${i}`, wait_for: "" }));
    expect(validate(script(stage({ procedure: many }))).some((i) => i.field === "procedure")).toBe(true);
  });

  it("adds at the end up to the limit and moves one without losing the rest", () => {
    expect(addSmallStep(INSTALL, 15)).toHaveLength(3);
    expect(addSmallStep(INSTALL, 2)).toHaveLength(2);
    expect(moveSmallStep(INSTALL, 1, 0).map((s) => s.action)).toEqual([
      "Ask them to type rytukhata.app.",
      "Ask them to open Chrome.",
    ]);
    expect(moveSmallStep(INSTALL, 0, 5)).toEqual(INSTALL);
  });

  it("reads as numbered lines in a review and in the hand-written text, and a change shows", () => {
    const [section] = sectionsOf(script(stage()));
    expect(sectionReadable(section).split("\n")).toEqual([
      "Help them put the app on their phone.",
      "1. Ask them to open Chrome. (wait for: they say it is open)",
      "2. Ask them to type rytukhata.app.",
    ]);
    expect(scriptAsText(script(stage()))).toContain("   1.1 Ask them to open Chrome. Wait for: they say it is open");
    const changed = script(stage({ procedure: [INSTALL[0]] }));
    expect(diffScripts(script(stage()), changed).length).toBeGreaterThan(0);
  });
});

function Harness({ initial }: { initial: SmallStep[] }) {
  const [steps, setSteps] = useState(initial);
  return (
    <>
      <SmallSteps id="t" steps={steps} limits={DEFAULT_LIMITS} issues={[]} onChange={setSteps} />
      <output data-testid="state">{JSON.stringify(steps)}</output>
    </>
  );
}

const state = () => JSON.parse(screen.getByTestId("state").textContent ?? "[]") as SmallStep[];

describe("the small steps editor", () => {
  it("adds, fills, moves and removes small steps", async () => {
    render(<Harness initial={INSTALL} />);
    expect(screen.getByText(/2 of 15/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add a small step" }));
    });
    const third = screen.getAllByLabelText("What they do")[2];
    await act(async () => {
      fireEvent.change(third, { target: { value: "Ask them to tap Add to Home screen." } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Move small step 3 earlier" }));
    });
    expect(state().map((s) => s.action)).toEqual([
      "Ask them to open Chrome.",
      "Ask them to tap Add to Home screen.",
      "Ask them to type rytukhata.app.",
    ]);
    expect((screen.getByRole("button", { name: "Move small step 1 earlier" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove small step 1" }));
    });
    expect(state()).toHaveLength(2);
  });

  it("stops offering more at the limit", () => {
    const full = Array.from({ length: 15 }, (_, i) => ({ action: `Step ${i}`, wait_for: "" }));
    render(<Harness initial={full} />);
    expect(screen.queryByRole("button", { name: "Add a small step" })).toBeNull();
    expect(screen.getByText(/15 small steps at most/)).toBeTruthy();
  });
});
