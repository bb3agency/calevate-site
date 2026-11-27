import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { OPENING_KEY } from "@/app/c/[slug]/campaigns/flowLayout";
import { DEFAULT_LIMITS } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import type { GeneratePartProps } from "@/app/c/[slug]/agents/[agentId]/script/GeneratePart";
import type { AgentDirection } from "@/lib/api/agents";
import { EMPTY_SCRIPT, OPENING_LINE_MAX, type CallScript, type ConversationStage } from "@/lib/api/script";

import { renderClientPage } from "./harness";

/** The call flow starts at the campaign's opening line, the way every call does, and that box
 *  opens an editor for the opening line alone. */

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
const PLACED = "Calling about your farm. Can we talk now?";
const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: OPENING,
  stages: [stage({ id: "a", name: "Install app", step: 1 }), stage({ id: "b", name: "Setup farms", step: 2 })],
};

const view = ({
  script = SCRIPT,
  wide = true,
  selected = null,
  readOnly = false,
  direction = "outbound",
  onSelect = () => {},
  onChange = () => {},
  rewriteOpening,
}: {
  script?: CallScript;
  wide?: boolean;
  selected?: string | null;
  readOnly?: boolean;
  direction?: AgentDirection;
  onSelect?: (id: string | null) => void;
  onChange?: (next: CallScript) => void;
  rewriteOpening?: GeneratePartProps & { held?: string };
} = {}) =>
  renderClientPage(
    <ScenarioFlow
      agent={null}
      hear={{ allowed: true, reason: null, unknown: false }}
      direction={direction}
      script={script}
      limits={DEFAULT_LIMITS}
      issues={[]}
      languages={["te-IN"]}
      selected={selected}
      readOnly={readOnly}
      wide={wide}
      onSelect={onSelect}
      onChange={onChange}
      rewriteOpening={rewriteOpening}
    />,
    {},
  );

const ask = (over: Partial<GeneratePartProps & { held?: string }> = {}) => ({
  languages: [{ tag: "te-IN", name: "Telugu" }],
  initial: "te-IN",
  onGenerate: vi.fn(),
  ...over,
});

describe("the opening in the call flow", () => {
  it("shows the stored opening first, links it to step 1, and is chosen like a scenario", async () => {
    const onSelect = vi.fn();
    const { container } = await view({ onSelect });
    const node = await screen.findByRole("button", { name: /^First thing it says: Hello, this is the farm desk/ });
    expect(node.textContent).toContain(`“${OPENING}”`);
    expect(container.querySelector('path[data-link="@opening-a"]')).not.toBeNull();
    expect(container.querySelector('path[data-link="@opening-b"]')).toBeNull();
    expect(screen.getByText("Not now")).toBeTruthy();
    expect(screen.getByText("Offer a call back")).toBeTruthy();
    fireEvent.click(node);
    expect(onSelect).toHaveBeenCalledWith(OPENING_KEY);
  });

  it("closes the call on not now where call backs are not offered", async () => {
    await view({ script: { ...SCRIPT, policies: { ...SCRIPT.policies, offer_call_backs: false } } });
    expect(await screen.findByText("End the call")).toBeTruthy();
  });

  it("reads a both agent's placed-call opening when it has one", async () => {
    await view({ script: { ...SCRIPT, outbound_opening_line: PLACED }, direction: "both" });
    expect(await screen.findByText("First thing it says when it calls")).toBeTruthy();
    expect(screen.getByText(`“${PLACED}”`)).toBeTruthy();
  });

  it("reads the opening a campaign's calls speak, never a stray placed-call line", async () => {
    const onChange = vi.fn();
    await view({ script: { ...SCRIPT, outbound_opening_line: PLACED }, selected: OPENING_KEY, onChange });
    expect(await screen.findByRole("button", { name: /^First thing it says: Hello, this is the farm desk/ })).toBeTruthy();
    expect(screen.queryByText(`“${PLACED}”`)).toBeNull();
    const box = screen.getByRole("textbox", { name: "First thing it says" }) as HTMLTextAreaElement;
    expect(box.value).toBe(OPENING);
    fireEvent.change(box, { target: { value: "Hello again." } });
    const next = onChange.mock.calls[0][0] as CallScript;
    expect(next.opening_line).toBe("Hello again.");
    expect(next.outbound_opening_line).toBe(PLACED);
  });

  it("leads the stacked steps on a phone", async () => {
    await view({ wide: false });
    const opening = await screen.findByRole("region", { name: "First thing it says" });
    expect(opening.textContent).toContain(OPENING);
    expect(opening.textContent).toContain("Next: 1.1");
    expect(opening.textContent).toContain("Not now: Offer a call back");
  });
});

describe("the opening's own editor", () => {
  it("holds the opening line alone, edited in the canvas's working script", async () => {
    const onChange = vi.fn();
    await view({ selected: OPENING_KEY, onChange });
    const panel = await screen.findByRole("complementary", { name: "Edit the first thing it says" });
    const box = screen.getByRole("textbox", { name: "First thing it says" }) as HTMLTextAreaElement;
    expect(panel.contains(box)).toBe(true);
    expect(box.value).toBe(OPENING);
    expect(box.maxLength).toBe(OPENING_LINE_MAX);
    expect(panel.textContent).toContain(`${OPENING.length}/${OPENING_LINE_MAX}`);
    // Nothing else of the script: no scenario fields.
    expect(screen.queryByRole("textbox", { name: "What the caller might say" })).toBeNull();
    fireEvent.change(box, { target: { value: "Namaste." } });
    expect(onChange).toHaveBeenCalledWith({ ...SCRIPT, opening_line: "Namaste." });
  });

  it("edits a both agent's placed-call line in its own box", async () => {
    const onChange = vi.fn();
    const script = { ...SCRIPT, outbound_opening_line: PLACED };
    await view({ script, direction: "both", selected: OPENING_KEY, onChange });
    const box = (await screen.findByRole("textbox", { name: "First thing it says when it calls" })) as HTMLTextAreaElement;
    expect(box.value).toBe(PLACED);
    fireEvent.change(box, { target: { value: "Calling again." } });
    expect(onChange).toHaveBeenCalledWith({ ...script, outbound_opening_line: "Calling again." });
  });

  it("asks Pip to change the opening alone, by its part name", async () => {
    const rewrite = ask();
    await view({ selected: OPENING_KEY, rewriteOpening: rewrite });
    fireEvent.click(await screen.findByRole("button", { name: "Ask Pip to change First thing it says" }));
    fireEvent.change(screen.getByRole("textbox", { name: "What should Pip change in First thing it says?" }), {
      target: { value: "make it warmer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Rewrite" }));
    expect(rewrite.onGenerate).toHaveBeenCalledWith("Opening line", "te-IN", "make it warmer");
  });

  it("waits for unsaved changes before Pip rewrites it", async () => {
    await view({ selected: OPENING_KEY, rewriteOpening: ask({ held: "Save your changes first." }) });
    const button = (await screen.findByRole("button", { name: "Ask Pip to change First thing it says" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toBe("Save your changes first.");
  });

  it("is read-only for someone who cannot change the script", async () => {
    await view({ selected: OPENING_KEY, readOnly: true, rewriteOpening: ask() });
    const box = (await screen.findByRole("textbox", { name: "First thing it says" })) as HTMLTextAreaElement;
    expect(box.readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: /Ask Pip to change/ })).toBeNull();
  });

  it("opens under the opening on a phone", async () => {
    await view({ wide: false, selected: OPENING_KEY });
    const opening = await screen.findByRole("region", { name: "First thing it says" });
    const box = screen.getByRole("textbox", { name: "First thing it says" });
    expect(opening.contains(box)).toBe(true);
    expect(screen.getByRole("button", { expanded: true }).textContent).toContain(OPENING);
  });
});
