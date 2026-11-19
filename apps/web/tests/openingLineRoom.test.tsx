import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { roomLabel } from "@/app/c/[slug]/agents/panels/openingLineFix";
import { OpeningEditor, type ScriptExamples } from "@/app/c/[slug]/agents/[agentId]/script/ScriptSections";
import { EMPTY_SCRIPT } from "@/lib/api/script";

/*
 * D-846: what an agent says first is the notices switched on and then its opening line, and
 * only so many characters can be said there. The script counts the line against the room the
 * server measured. A notice switch refused for want of room is `callNotices.test.tsx`'s.
 */

describe("the opening line's room (D-846)", () => {
  it("counts what is left, and how far over, the way the server counts", () => {
    expect(roomLabel("  Namaskaram  ", 12)).toEqual({ label: "2 characters left", over: false });
    expect(roomLabel("a".repeat(13), 12)).toEqual({ label: "1 character too long", over: true });
    // A code point is one character, as the server's len() counts it.
    expect(roomLabel("🙂", 1).over).toBe(false);
  });

  it("shows the room under the opening line in the script, and marks it when it is over", () => {
    const eg = { outboundPurpose: "" } as ScriptExamples;
    const opening = (line: string) => (
      <OpeningEditor
        script={{ ...EMPTY_SCRIPT, opening_line: line }}
        set={() => {}}
        direction="inbound"
        room={20}
        standardVariables={[]}
        eg={eg}
      />
    );
    const { rerender } = render(opening("Namaskaram"));
    expect(screen.getByText("10 characters left")).toBeTruthy();
    const box = screen.getByRole("textbox", { name: /Opening line/ });
    expect(box.getAttribute("aria-invalid")).toBeNull();

    rerender(opening("a".repeat(25)));
    expect(screen.getByText("5 characters too long")).toBeTruthy();
    expect(box.getAttribute("aria-invalid")).toBe("true");
    // The meter is part of the box's description, so the count is read with it.
    const meter = screen.getByRole("meter", { name: "Opening line length" });
    expect(box.getAttribute("aria-describedby")).toContain(meter.parentElement?.id ?? "missing");
  });
});
