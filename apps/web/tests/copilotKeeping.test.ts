import { describe, expect, it } from "vitest";

import { filledNotice, keepingOnWire, panelNotice, savesOf } from "@/lib/copilot/keeping";
import { redactForWire } from "@/lib/copilot/redaction";
import { mergeSurfaces } from "@/lib/copilot/registry";
import { noFill, type CopilotSurface } from "@/lib/copilot/types";

/**
 * How a screen keeps what Pip fills in, and what the panel says about it (D-832). The
 * founder's report: on the Script tab, which autosaves a draft and has "Put it live", the
 * panel said "use this screen's own save button", a button that is not there.
 */

const field = { id: "f", label: "Opening line", type: "textarea" as const, value: "" };
const surface = (over: Partial<CopilotSurface> = {}): CopilotSurface => ({
  route: "/c/{slug}/x",
  title: "X",
  realm: "client",
  fields: [field],
  apply: noFill,
  ...over,
});

describe("what the panel says after a fill", () => {
  it("names the live step on a screen that autosaves a draft, and no save button", () => {
    const script = surface({ saves: "autosave", liveStep: "Put it live" });
    expect(filledNotice(script)).toBe(
      "Pip changed your draft. It is saved as a draft; nothing goes live until you press Put it live.",
    );
    expect(filledNotice(script)).not.toMatch(/save button/);
    expect(panelNotice(script)).toMatch(/saved as a draft by themselves; nothing goes live until you press Put it live/);
  });

  it("keeps the save-button sentence for a form, which is also what an undeclared screen gets", () => {
    for (const form of [surface({ saves: "button" }), surface()]) {
      expect(filledNotice(form)).toBe("Nothing has been saved. Check the values, then use this screen's own save button.");
      expect(panelNotice(form)).toBe("Nothing is saved until you press this screen's own save button. ");
    }
  });

  it("says a screen that saves at once does, and a filter only changed the view", () => {
    expect(filledNotice(surface({ saves: "immediate" }))).toMatch(/saves each change as it is made/);
    expect(filledNotice(surface({ saves: "view" }))).toBe("This only changed what the screen shows.");
    expect(panelNotice(surface({ saves: "view" }))).toBe("");
  });

  it("says nothing about saving on a screen with nothing Pip can fill", () => {
    const readOnly = surface({ fields: [{ ...field, writable: false }], saves: "button" });
    expect(savesOf(readOnly)).toBeNull();
    expect(panelNotice(readOnly)).toBe("");
    expect(keepingOnWire(readOnly)).toEqual({});
  });
});

describe("what the request carries", () => {
  it("sends how edits are kept, the live step only with autosave", () => {
    expect(keepingOnWire(surface({ saves: "autosave", liveStep: "Put it live" }))).toEqual({
      saves: "autosave",
      live_step: "Put it live",
    });
    expect(keepingOnWire(surface({ liveStep: "ignored" }))).toEqual({ saves: "button" });
  });

  it("marks a spoken line with its language and leaves other fields as they were", () => {
    const pass = redactForWire([{ ...field, spokenLanguage: "te-IN" }, { ...field, id: "g" }], []);
    expect(pass.fields[0].spoken_language).toBe("te-IN");
    expect("spoken_language" in pass.fields[1]).toBe(false);
  });

  it("takes a merged tab's answer from the part that holds the fields", () => {
    const merged = mergeSurfaces({ route: "/r", title: "T", realm: "client", facts: [] }, [
      surface({ fields: [], saves: "view" }),
      surface({ saves: "autosave", liveStep: "Put it live" }),
    ]);
    expect(merged.saves).toBe("autosave");
    expect(merged.liveStep).toBe("Put it live");
  });
});
