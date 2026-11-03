import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SearchField } from "@/components/arc/search-field";
import { TagInput } from "@/components/arc/tag-input";
import { isImeComposing } from "@/lib/imeEnter";

/**
 * Telugu and Hindi are typed through an IME whose Enter picks a candidate word. That Enter
 * must not also add the tag, run the search or send the message.
 */

describe("isImeComposing", () => {
  it("reads isComposing and the 229 key code, on React and native events", () => {
    expect(isImeComposing({ nativeEvent: new KeyboardEvent("keydown", { key: "Enter", isComposing: true }) })).toBe(true);
    expect(isImeComposing(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229 }))).toBe(true);
    expect(isImeComposing({ nativeEvent: new KeyboardEvent("keydown", { key: "Enter" }) })).toBe(false);
  });
});

describe("Enter that commits an IME candidate", () => {
  it("does not add a half-typed tag", () => {
    const onChange = vi.fn();
    render(<TagInput label="Words" value={[]} onChange={onChange} />);
    const box = screen.getByRole("combobox", { name: "Words" });
    fireEvent.change(box, { target: { value: "namaskaram" } });
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    fireEvent.keyDown(box, { key: "Enter", keyCode: 229 });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(["namaskaram"]);
  });

  it("does not run a search mid-word", () => {
    const onSearch = vi.fn();
    render(<SearchField label="Find" value="rama" onValueChange={() => {}} onSearch={onSearch} />);
    const box = screen.getByLabelText("Find");
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onSearch).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSearch).toHaveBeenCalledWith("rama");
  });
});
