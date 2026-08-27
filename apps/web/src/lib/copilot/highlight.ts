"use client";

/**
 * Marking the controls the assistant just filled in, so a person can see what changed
 * before they save it.
 *
 * ## Why an inline outline and not a Tailwind class
 *
 * The elements being marked belong to twenty different screens and several shared
 * components; adding a class means every one of those has to be willing to carry it, and
 * a `ring-` utility on a control that already has a `focus-visible:ring` fights with it
 * on the next Tab. An outline drawn directly on the node composes with every one of them,
 * is removed by exactly the code that added it, and cannot leak into a stylesheet other
 * screens read.
 *
 * `data-copilot-filled` rides along because it is what a test can assert on, and because
 * an operator inspecting a form should be able to see which values were not typed.
 *
 * A field with NO element on the page — a draft-backed screen whose control carries no
 * `id`, or a row scrolled out of a virtualised list — is simply not marked. The panel
 * lists what it filled by LABEL for that reason: the count and the names are the primary
 * report, and the outline is the confirmation on the form itself.
 */

const MARK = "data-copilot-filled";
/**
 * The console's brand green (`--brand`, `app/globals.css:24`) as a literal, because this
 * is written onto the node and never passes through Tailwind's token layer. It is one of
 * the two places in this feature that names a colour; the other is the launcher, which
 * uses the token properly because it is a className.
 */
const OUTLINE = "2px solid #16a05d";

function elementFor(id: string, root: ParentNode): HTMLElement | null {
  const found = root.querySelector(`#${CSS.escape(id)}`);
  return found instanceof HTMLElement ? found : null;
}

/** Mark exactly these ids and unmark everything previously marked under `root`. */
export function markFilled(ids: readonly string[], root: ParentNode = document): void {
  clearFilled(root);
  for (const id of ids) {
    const element = elementFor(id, root);
    if (element === null) continue;
    element.setAttribute(MARK, "true");
    element.style.outline = OUTLINE;
    element.style.outlineOffset = "1px";
  }
}

/** Remove every mark. Called by Undo, by a new question, and when the panel closes. */
export function clearFilled(root: ParentNode = document): void {
  for (const element of Array.from(root.querySelectorAll(`[${MARK}]`))) {
    if (!(element instanceof HTMLElement)) continue;
    element.removeAttribute(MARK);
    element.style.outline = "";
    element.style.outlineOffset = "";
  }
}
