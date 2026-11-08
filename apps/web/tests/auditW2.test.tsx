import { act, fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { SectionEditor } from "@/app/c/[slug]/agents/[agentId]/script/SectionEditor";
import {
  DEFAULT_LIMITS,
  sectionsOf,
  updateSection,
  validate,
} from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";

import { renderClientPage } from "./harness";

/**
 * Frontend audit lane W2 (8 Nov 2026): the agent page and the knowledge screens.
 */

function oneStep(): CallScript {
  return {
    ...EMPTY_SCRIPT,
    schema_version: 2,
    stages: [
      {
        id: "need",
        name: "Find out the need",
        mode: "guide",
        instruction: "Ask what they need.",
        sounds_like: "",
        branches: [],
        otherwise: "",
        collect: [],
        procedure: [],
        position: null,
      },
    ],
  };
}

function StepHarness() {
  const [script, setScript] = useState(oneStep);
  const sections = sectionsOf(script);
  return (
    <SectionEditor
      section={sections[0]}
      index={0}
      sections={sections}
      context={null}
      limits={DEFAULT_LIMITS}
      issues={validate(script)}
      readOnly={false}
      onChange={(patch) => setScript((s) => updateSection(s, "need", patch))}
      onMove={() => {}}
      onDelete={() => {}}
    />
  );
}

describe("a step's More options", () => {
  it("stays open while the owner finishes the small step that opened it", async () => {
    const { container } = await renderClientPage(<StepHarness />, {});
    const details = () => container.querySelector("details") as HTMLDetailsElement;
    expect(details().open).toBe(false);

    await act(async () => {
      details().open = true;
      fireEvent(details(), new Event("toggle"));
    });
    fireEvent.click(screen.getByRole("button", { name: /Add a small step/ }));
    // An empty small step is an issue, which may open the panel; it is open already.
    expect(details().open).toBe(true);

    const action = screen.getByRole("textbox", { name: /What they do/ });
    fireEvent.change(action, { target: { value: "Ask them to open the app." } });
    // Finishing it clears the issue. The panel the owner is typing in must not shut.
    expect(details().open).toBe(true);
  });
});
