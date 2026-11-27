import { act, createEvent, fireEvent, screen, within } from "@testing-library/react";
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

import KnowledgePage from "@/app/c/[slug]/knowledge/page";

import { businessProfileFixture } from "./businessProfileFixture";
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

describe("a step in exact words", () => {
  it("offers no fixed Telugu example line to an agent in another language", async () => {
    const script = oneStep();
    const stage = { ...script.stages![0]!, mode: "say" as const, instruction: "" };
    const sections = sectionsOf({ ...script, stages: [stage] });
    await renderClientPage(
      <SectionEditor
        section={sections[0]}
        index={0}
        sections={sections}
        context={null}
        limits={DEFAULT_LIMITS}
        issues={[]}
        readOnly={false}
        onChange={() => {}}
        onMove={() => {}}
        onDelete={() => {}}
      />,
      {},
    );
    const words = screen.getByRole("textbox", { name: "What it says, word for word" });
    expect(words.getAttribute("placeholder") ?? "").not.toMatch(/cheppagalara/);
  });
});

const OWNER = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "agents:write", "calls:read", "kb:write", "org:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const KNOWLEDGE_READS = {
  "/v1/me": OWNER,
  "/v1/agents": [],
  "/v1/kb/notes": { notes: [] },
  "/v1/kb/uploads": [],
  "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
  "/v1/kb/knows": { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] },
  "/v1/teach/questions": { items: [], open_count: 0 },
  "/v1/kb/teach/open": { teaching: null },
  "/v1/business-profile": businessProfileFixture({ services: [], faqs: [] }),
};

describe("the teach box review", () => {
  it("closes an edited item on Done, as a pointer press reaches it", async () => {
    await renderClientPage(<KnowledgePage />, {
      ...KNOWLEDGE_READS,
      "/v1/kb/teach/open": {
        teaching: {
          id: "teach-1",
          status: "ready",
          input_kind: "text",
          words: "We open at 9.",
          items: [{ kind: "fact", text: "We open at 9.", pinned: false }],
          agent_id: null,
          gap_id: null,
          note: null,
          error_code: null,
          created_at: "2026-11-08T10:00:00Z",
        },
      },
    });
    const list = await screen.findByRole("list", { name: "Check what we found" });
    fireEvent.click(within(list).getByRole("button", { name: "Edit" }));
    const box = within(list).getByRole("textbox", { name: "Edit" });
    box.focus();
    const done = within(list).getByRole("button", { name: "Done" });
    // A browser's mousedown moves focus off the box (its default action) before the click.
    const press = createEvent.mouseDown(done);
    fireEvent(done, press);
    if (!press.defaultPrevented) fireEvent.blur(box);
    fireEvent.click(within(list).getByRole("button", { name: /^(Done|Edit)$/ }));
    expect(within(list).queryByRole("textbox", { name: "Edit" })).toBeNull();
    expect(within(list).getByRole("button", { name: "Edit" })).toBeTruthy();
  });
});
