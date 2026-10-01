import { fireEvent, screen } from "@testing-library/react";

/**
 * The text behind an ⓘ (`components/console/infoTip.tsx`), opened the way a person opens
 * it. Help prose that moved into a tip is not in the DOM until the tip is opened, so an
 * assertion about that prose has to open it first. Leaves it open, so a later read sees
 * the tip re-rendered with the screen's current state.
 */
export async function readInfoTip(name: string): Promise<string> {
  const button = await screen.findByRole("button", { name: `About ${name}` });
  if (button.getAttribute("aria-expanded") !== "true") fireEvent.click(button);
  const panels = await screen.findAllByRole("dialog", { name });
  return panels.at(-1)?.textContent ?? "";
}
