import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { DEFAULT_LIMITS } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import type { WriteAccess } from "@/lib/api/hooks";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import { renderClientPage } from "./harness";

/** Dragging a scenario's dot onto another scenario makes it a next scenario (the canvas). */

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
  stages: [stage({ id: "a", name: "First", step: 1 }), stage({ id: "b", name: "Second", step: 2 })],
};

describe("drag to link", () => {
  it("links the dragged scenario to the one it is dropped on", async () => {
    const hear: WriteAccess = { allowed: true, reason: null, unknown: false };
    const onChange = vi.fn();
    await renderClientPage(
      <ScenarioFlow
        agent={null}
        hear={hear}
        script={SCRIPT}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={onChange}
      />,
      {},
    );
    const target = (await screen.findByRole("button", { name: /Scenario 2\.1: Second/ })).parentElement as HTMLElement;
    const dot = screen.getAllByTitle("Drag to a scenario to make it a next scenario")[0] as HTMLElement;
    dot.setPointerCapture = () => {};
    const x = Number.parseFloat(target.style.left) + 20;
    const y = Number.parseFloat(target.style.top) + 20;
    fireEvent.pointerDown(dot, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(dot, { pointerId: 1, clientX: x, clientY: y });
    fireEvent.pointerUp(dot, { pointerId: 1, clientX: x, clientY: y });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0]?.[0] as CallScript | undefined;
    const first = next?.stages?.find((s) => s.id === "a");
    expect(first?.branches?.map((b) => b.target)).toEqual(["b"]);
  });

  it("counts a drop just outside a card's edge, where its arrowhead is", async () => {
    const hear: WriteAccess = { allowed: true, reason: null, unknown: false };
    const onChange = vi.fn();
    await renderClientPage(
      <ScenarioFlow
        agent={null}
        hear={hear}
        script={SCRIPT}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={onChange}
      />,
      {},
    );
    const target = (await screen.findByRole("button", { name: /Scenario 2\.1: Second/ })).parentElement as HTMLElement;
    const dot = screen.getAllByTitle("Drag to a scenario to make it a next scenario")[0] as HTMLElement;
    dot.setPointerCapture = () => {};
    const x = Number.parseFloat(target.style.left) - 8;
    const y = Number.parseFloat(target.style.top) + 40;
    fireEvent.pointerDown(dot, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(dot, { pointerId: 1, clientX: x, clientY: y });
    fireEvent.pointerUp(dot, { pointerId: 1, clientX: x, clientY: y });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("says why when a drop links nothing", async () => {
    const hear: WriteAccess = { allowed: true, reason: null, unknown: false };
    const linked: CallScript = {
      ...SCRIPT,
      stages: [stage({ id: "a", name: "First", step: 1, branches: [{ when: "Second", target: "b" }] }), SCRIPT.stages[1] as ConversationStage],
    };
    await renderClientPage(
      <ScenarioFlow
        agent={null}
        hear={hear}
        script={linked}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={() => {}}
      />,
      {},
    );
    const target = (await screen.findByRole("button", { name: /Scenario 2\.1: Second/ })).parentElement as HTMLElement;
    const dot = screen.getAllByTitle("Drag to a scenario to make it a next scenario")[0] as HTMLElement;
    dot.setPointerCapture = () => {};
    const x = Number.parseFloat(target.style.left) + 20;
    const y = Number.parseFloat(target.style.top) + 20;
    fireEvent.pointerDown(dot, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerUp(dot, { pointerId: 1, clientX: x, clientY: y });
    expect(await screen.findByText("It already goes there.")).toBeTruthy();
  });
});
