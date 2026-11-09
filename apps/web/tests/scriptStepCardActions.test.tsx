import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SectionList, stepAnchor } from "@/app/c/[slug]/agents/[agentId]/script/SectionList";
import type { Section } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";

function step(id: string, name: string): Section {
  return {
    id,
    name,
    mode: "guide",
    instruction: "",
    sounds_like: "",
    branches: [],
    otherwise: "",
    collect: [],
    procedure: [],
    position: null,
  };
}

const STEPS = [step("greet", "Check it is a good time"), step("installed", "Check if installed"), step("close", "Close")];

function list(props: Partial<Parameters<typeof SectionList>[0]> = {}) {
  return render(
    <SectionList
      sections={STEPS}
      context={null}
      issues={[]}
      selected={null}
      readOnly={false}
      onOpen={() => {}}
      onMove={() => {}}
      {...props}
    />,
  );
}

describe("step cards: delete and add between", () => {
  it("every card has its own delete button, which asks for that step", () => {
    const onDelete = vi.fn();
    list({ onDelete });
    fireEvent.click(screen.getByRole("button", { name: "Delete Check if installed" }));
    expect(onDelete).toHaveBeenCalledWith("installed");
    expect(screen.getAllByRole("button", { name: /^Delete / })).toHaveLength(3);
  });

  it("adds between steps and after the last, never above step 1", () => {
    const onInsert = vi.fn();
    list({ onInsert });
    expect(screen.queryByRole("button", { name: /before 1|between 0/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add a step between 1 and 2" }));
    expect(onInsert).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "Add a step after 3" }));
    expect(onInsert).toHaveBeenLastCalledWith(3);
    expect(screen.getAllByRole("button", { name: /^Add a step/ })).toHaveLength(3);
  });

  it("shows a gap's button while either neighbour is hovered", () => {
    list({ onInsert: () => {} });
    const between = screen.getByRole("button", { name: "Add a step between 1 and 2" });
    expect(between.className).toContain("opacity-0");
    fireEvent.pointerEnter(document.getElementById(stepAnchor("greet"))!);
    expect(between.className).not.toContain("opacity-0");
    fireEvent.pointerLeave(document.getElementById(stepAnchor("greet"))!);
    fireEvent.pointerEnter(document.getElementById(stepAnchor("installed"))!);
    expect(between.className).not.toContain("opacity-0");
  });

  it("offers neither when the script cannot be changed", () => {
    list({ readOnly: true });
    expect(screen.queryByRole("button", { name: /^Delete / })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Add a step/ })).toBeNull();
  });
});
