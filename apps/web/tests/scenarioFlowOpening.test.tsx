import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { DEFAULT_LIMITS } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import { renderClientPage } from "./harness";

/** The call flow starts at the campaign's opening line, the way every call does. */

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

const OPENING = "Hello, this is the farm desk. Is now a good time to talk?";
const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: OPENING,
  stages: [stage({ id: "a", name: "Install app", step: 1 }), stage({ id: "b", name: "Setup farms", step: 2 })],
};

const view = (script: CallScript, wide: boolean, onEditOpening?: () => void) =>
  renderClientPage(
    <ScenarioFlow
      agent={null}
      hear={{ allowed: true, reason: null, unknown: false }}
      script={script}
      limits={DEFAULT_LIMITS}
      issues={[]}
      languages={["te-IN"]}
      selected={null}
      readOnly={false}
      wide={wide}
      onSelect={() => {}}
      onChange={() => {}}
      onEditOpening={onEditOpening}
    />,
    {},
  );

describe("the opening in the call flow", () => {
  it("shows the stored opening first and links it to step 1", async () => {
    const edit = vi.fn();
    const { container } = await view(SCRIPT, true, edit);
    const node = await screen.findByRole("button", { name: /^Opening: Hello, this is the farm desk/ });
    expect(node.textContent).toContain(`“${OPENING}”`);
    expect(container.querySelector('path[data-link="@opening-a"]')).not.toBeNull();
    expect(container.querySelector('path[data-link="@opening-b"]')).toBeNull();
    expect(screen.getByText("Not now")).toBeTruthy();
    expect(screen.getByText("Offer a call back")).toBeTruthy();
    fireEvent.click(node);
    expect(edit).toHaveBeenCalledTimes(1);
  });

  it("closes the call on not now where call backs are not offered", async () => {
    await view({ ...SCRIPT, policies: { ...SCRIPT.policies, offer_call_backs: false } }, true);
    expect(await screen.findByText("End the call")).toBeTruthy();
    // Without a way to edit it, the opening is not a button.
    expect(screen.queryByRole("button", { name: /^Opening:/ })).toBeNull();
  });

  it("reads a placed call's own opening when the agent has one", async () => {
    await view({ ...SCRIPT, outbound_opening_line: "Calling about your farm. Can we talk now?" }, true, () => {});
    expect(await screen.findByText("Opening when it calls")).toBeTruthy();
    expect(screen.getByText("“Calling about your farm. Can we talk now?”")).toBeTruthy();
  });

  it("leads the stacked steps on a phone", async () => {
    await view(SCRIPT, false, () => {});
    const opening = await screen.findByRole("region", { name: "Opening" });
    expect(opening.textContent).toContain(OPENING);
    expect(opening.textContent).toContain("Next: 1.1");
    expect(opening.textContent).toContain("Not now: Offer a call back");
  });
});
