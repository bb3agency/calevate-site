import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScriptPartsEditor } from "@/app/c/[slug]/agents/[agentId]/script/ScriptPartsEditor";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";

import { expectNoA11yViolations } from "./a11y";

const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  goal: "Book a service visit.\nThen confirm the day.",
  opening_line: "Hello, this is the service desk.",
  stages: [
    {
      id: "greet",
      name: "Greet",
      mode: "guide",
      instruction: "Say who you are.",
      sounds_like: "",
      branches: [],
      otherwise: "",
      collect: [],
      position: null,
    },
  ],
};

const CANVAS = ["opening_line", "outbound_opening_line"] as const;

const toggle = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) });

describe("a saved script, edited one part at a time", () => {
  it("lists each part by name with a one-line preview, and no fields until one is opened", async () => {
    const { container } = render(
      <ScriptPartsEditor script={SCRIPT} leaveOut={CANVAS} steps={false} onSave={() => {}} onClose={() => {}} />,
    );
    const goal = toggle("The goal");
    expect(goal.getAttribute("aria-expanded")).toBe("false");
    expect(goal.textContent).toContain("Book a service visit.");
    expect(goal.textContent).not.toContain("Then confirm the day.");
    expect(toggle("Its role").textContent).toContain("Not set");
    expect(screen.queryByRole("textbox")).toBeNull();
    await expectNoA11yViolations(container, "script parts list");
  });

  it("leaves out the parts the canvas edits, the steps, and parts nobody can add to while empty", () => {
    render(<ScriptPartsEditor script={SCRIPT} leaveOut={CANVAS} steps={false} onSave={() => {}} onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: /^Opening line/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Greet/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Example call/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^What each step must reach/ })).toBeNull();
    expect(toggle("Quick facts")).toBeTruthy();
  });

  it("lists the opening line and each step where nothing else edits them", () => {
    render(<ScriptPartsEditor script={SCRIPT} leaveOut={["outbound_purpose", "outbound_opening_line"]} onSave={() => {}} onClose={() => {}} />);
    expect(toggle("Opening line").textContent).toContain("Hello, this is the service desk.");
    fireEvent.click(toggle("Greet"));
    expect((screen.getByRole("textbox", { name: "Step name" }) as HTMLInputElement).value).toBe("Greet");
    expect(screen.queryByRole("button", { name: /^Why you are calling/ })).toBeNull();
  });

  it("opens one part at a time and saves the whole script with only that part changed", () => {
    const onSave = vi.fn();
    render(<ScriptPartsEditor script={SCRIPT} leaveOut={CANVAS} steps={false} onSave={onSave} onClose={() => {}} />);
    fireEvent.click(toggle("Its role"));
    fireEvent.click(toggle("The goal"));
    expect(toggle("Its role").getAttribute("aria-expanded")).toBe("false");
    expect(toggle("The goal").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    const save = screen.getByRole("button", { name: "Save The goal" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "The goal" }), { target: { value: "Book a visit." } });
    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledWith({ ...SCRIPT, goal: "Book a visit." });
  });

  it("asks for Save or Cancel before another part opens over unsaved words, and Cancel drops them", () => {
    const onSave = vi.fn();
    render(<ScriptPartsEditor script={SCRIPT} leaveOut={CANVAS} steps={false} onSave={onSave} onClose={() => {}} />);
    fireEvent.click(toggle("The goal"));
    fireEvent.change(screen.getByRole("textbox", { name: "The goal" }), { target: { value: "Something else." } });
    fireEvent.click(toggle("Its role"));
    expect(toggle("The goal").getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Save or cancel this part first.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel The goal" }));
    expect(toggle("The goal").getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle("The goal"));
    expect((screen.getByRole("textbox", { name: "The goal" }) as HTMLTextAreaElement).value).toBe(SCRIPT.goal);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("holds Save on the builder's own problem with that part", () => {
    const onSave = vi.fn();
    render(<ScriptPartsEditor script={SCRIPT} leaveOut={CANVAS} steps={false} onSave={onSave} onClose={() => {}} />);
    fireEvent.click(toggle("Your business in one line"));
    const field = screen.getByRole("textbox", { name: "Your business in one line" });
    fireEvent.change(field, { target: { value: "x".repeat(201) } });
    fireEvent.click(screen.getByRole("button", { name: "Save Your business in one line" }));
    expect(onSave).not.toHaveBeenCalled();
    expect(field.getAttribute("aria-invalid")).toBe("true");
  });

  it("offers Pip's rewrite of the open part", () => {
    const onGenerate = vi.fn();
    render(
      <ScriptPartsEditor
        script={SCRIPT}
        leaveOut={CANVAS}
        steps={false}
        generatePart={{ languages: [{ tag: "te-IN", name: "Telugu" }], initial: "te-IN", onGenerate }}
        onSave={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /^Generate/ })).toBeNull();
    fireEvent.click(toggle("The goal"));
    const panel = screen.getByRole("region", { name: /The goal/ });
    fireEvent.click(within(panel).getByRole("button", { name: "Generate The goal in Telugu" }));
    expect(onGenerate).toHaveBeenCalledWith("The goal", "te-IN");
  });
});
