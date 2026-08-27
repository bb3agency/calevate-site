"use client";

/**
 * THE LAST RESORT: writing a value into a control by driving its DOM node.
 *
 * Every registered screen that has a draft object or a per-field setter applies through
 * THAT (`paths.ts`, or a plain call to the setter). This file is for the screen that has
 * neither — a control owned by a component we do not hold the state of — and it is worse
 * in a way that is worth writing down, because "it works on the screen I tested" is
 * exactly how this technique gets adopted where it should not be:
 *
 * - it can only reach a control that is MOUNTED and carries an `id`;
 * - it depends on how React attaches its listeners, which is an implementation detail of
 *   React and not of the DOM;
 * - it is invisible to the type checker, so a renamed field is a runtime no-op.
 *
 * ## Why `el.value = x` alone does nothing, and what does
 *
 * React tracks the last value it wrote on the DOM node and skips the `change` event when
 * the node's value already matches — so assigning through the instance property both
 * fails to notify React AND poisons its tracker. The working technique is the
 * prototype's own setter plus a bubbling `input` event, and it is already proven in this
 * codebase: `app/c/[slug]/agents/[agentId]/script/ScriptBuilder.tsx` uses exactly this to
 * insert `{{variables}}` into a controlled textarea.
 *
 * FOR CHECKBOXES AND RADIOS THE ANALOGUE IS `.click()`, not `input`. React's `onChange`
 * for those is delegated from a `click`, so dispatching `input` on a checkbox updates
 * nothing. `ToggleSwitch` (`components/ui.tsx`) is the case that forced this: the input is
 * `sr-only`, the label WRAPS it and carries no `htmlFor`, so there is no id to look up
 * either — `clickByAccessibleName` below is how it is reached, by the name a person
 * hears, which is the only handle that component offers.
 */

/** Every element a fill can be written into, and nothing else. */
type Fillable = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

function nativeValueSetter(element: Fillable): ((value: string) => void) | null {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  const setter = descriptor?.set;
  return setter === undefined ? null : (value: string) => setter.call(element, value);
}

/**
 * Write `value` into the control with this `id`. Returns whether it landed.
 *
 * A boolean rather than a throw: a batch of six fills must not lose five because the
 * first named a control that has since unmounted, and the panel reports the count it
 * actually applied.
 */
export function fillById(id: string, value: string, root: ParentNode = document): boolean {
  const element = root.querySelector(`#${CSS.escape(id)}`);
  if (
    !(element instanceof HTMLInputElement) &&
    !(element instanceof HTMLTextAreaElement) &&
    !(element instanceof HTMLSelectElement)
  ) {
    return false;
  }

  if (element instanceof HTMLInputElement && (element.type === "checkbox" || element.type === "radio")) {
    const wanted = element.type === "radio" ? element.value === value : value === "true";
    if (element.checked === wanted) return true;
    // A radio is only ever turned ON: clicking the one that is already off in a group
    // turns the right one on and the browser turns the others off. There is no gesture
    // that turns a radio off, so a `false` for a radio is a fill with nothing to do.
    if (element.type === "radio" && !wanted) return false;
    element.click();
    return true;
  }

  const setter = nativeValueSetter(element);
  if (setter === null) return false;
  setter(value);
  // BUBBLES, because React listens at the root and not on the node.
  element.dispatchEvent(new Event("input", { bubbles: true }));
  // A `<select>` fires `change`, not `input`, in React's own event plumbing for it —
  // sending both costs nothing and neither is a gesture a controlled component
  // misinterprets.
  if (element instanceof HTMLSelectElement) {
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }
  return true;
}

/**
 * Turn a switch or checkbox that has NO id — `ToggleSwitch` — on or off, found by the
 * accessible name a person hears.
 *
 * The name is matched against the wrapping `<label>`'s text because that is where
 * `ToggleSwitch` puts it (an implicit label, deliberately: two agents' editors on one
 * screen would collide on any id scheme). Matching is exact after whitespace collapse,
 * not a substring: "Recording notice" and "Recording notice (outbound)" are two different
 * switches and a substring match would flip whichever the DOM listed first.
 */
export function clickByAccessibleName(name: string, on: boolean, root: ParentNode = document): boolean {
  const wanted = name.replace(/\s+/g, " ").trim();
  for (const label of Array.from(root.querySelectorAll("label"))) {
    const input = label.querySelector("input[type=checkbox]");
    if (!(input instanceof HTMLInputElement)) continue;
    // The label's text INCLUDING its hint block; the first line is the name. Comparing
    // the whole thing would fail on every switch that carries a hint.
    const heading = label.textContent ?? "";
    if (!heading.replace(/\s+/g, " ").trim().startsWith(wanted)) continue;
    if (input.checked !== on) input.click();
    return true;
  }
  return false;
}
