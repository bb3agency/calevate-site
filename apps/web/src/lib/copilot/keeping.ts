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

/**
 * Under a fill Pip just made. On an autosaving screen it says what the screen DOES, not that
 * the save has happened: the fill lands before the debounced save runs, and a save can fail.
 */
export function filledNotice(surface: CopilotSurface): string {
  switch (savesOf(surface)) {
    case "autosave":
      return `Your draft saves by itself. Nothing goes live until you press ${liveStepOf(surface)}.`;
    case "immediate":
      return "This screen saves each change as it is made. Undo puts the earlier value back.";
    case "view":
      return "This only changed what the screen shows.";
    default:
      return "Nothing has been saved. Check the values, then use this screen's own save button.";
  }
}

/** "a, b and c". */
function listed(labels: readonly string[]): string {
  if (labels.length <= 1) return labels.join("");
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

/**
 * Pip's reply for a turn that only filled fields: what changed, once. How the screen keeps
 * it is `filledNotice`, in the card under the reply, so the reply does not say it as well.
 */
export function filledReply(surface: CopilotSurface, labels: readonly string[]): string {
  const what = listed(labels);
  switch (savesOf(surface)) {
    case "autosave":
      return `I changed ${what} in your draft.`;
    case "view":
      return `I changed what the screen shows: ${what}.`;
    case "immediate":
      return `I changed ${what}.`;
    default:
      return `I filled in ${what}.`;
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
