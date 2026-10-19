import { ASSISTANT_NAME } from "./assistantName";
import type { CopilotSaves, CopilotSurface } from "./types";

/**
 * How the screen keeps what Pip fills in, and the sentences that say so (D-832).
 *
 * The panel used to tell every screen "use this screen's own save button", which was wrong
 * on the Script tab: it autosaves a draft and has "Put it live" instead, so the owner went
 * looking for a button that is not there. Each screen now declares `saves`; the request
 * carries it so Pip says the same thing the panel does.
 */

/** The screen's answer, or null when it has nothing Pip can fill. */
export function savesOf(surface: CopilotSurface): CopilotSaves | null {
  if (!surface.fields.some((field) => field.writable !== false)) return null;
  return surface.saves ?? "button";
}

/** The `screen` half of the request that says how edits are kept. */
export function keepingOnWire(surface: CopilotSurface): { saves?: CopilotSaves; live_step?: string } {
  const saves = savesOf(surface);
  if (saves === null) return {};
  return saves === "autosave" && surface.liveStep ? { saves, live_step: surface.liveStep } : { saves };
}

const liveStepOf = (surface: CopilotSurface) => surface.liveStep ?? "the button that puts it live";

/** Under a fill Pip just made. */
export function filledNotice(surface: CopilotSurface): string {
  switch (savesOf(surface)) {
    case "autosave":
      return `${ASSISTANT_NAME} changed your draft. It is saved as a draft; nothing goes live until you press ${liveStepOf(surface)}.`;
    case "immediate":
      return "This screen saves each change as it is made. Undo puts the earlier value back.";
    case "view":
      return "This only changed what the screen shows.";
    default:
      return "Nothing has been saved. Check the values, then use this screen's own save button.";
  }
}

/** The empty panel's line about this screen's fields, or "" when it has none worth a line. */
export function panelNotice(surface: CopilotSurface): string {
  switch (savesOf(surface)) {
    case "button":
      return "Nothing is saved until you press this screen's own save button. ";
    case "autosave":
      return `Changes here are saved as a draft by themselves; nothing goes live until you press ${liveStepOf(surface)}. `;
    case "immediate":
      return "Changes here are saved as soon as they are made. ";
    default:
      return "";
  }
}
