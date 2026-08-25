"use client";

/**
 * The control that was missing, and the reason 429 `dark:` variants were dead code.
 *
 * `lib/theme.ts` holds the decision and the flash-free mechanism; this is the part a person
 * can reach. One button, three states, cycling system → light → dark → system.
 *
 * ## Why one cycling button rather than a menu or a two-state switch
 *
 * A `ToggleSwitch` (ui.tsx) has two positions and there are three states — and the third,
 * "follow my device", is the one that has to stay reachable: it is the default, so a person
 * who taps once to look at dark mode must be able to get back to it, and a switch cannot
 * express it. A dropdown would express it and costs a popover, a focus trap and an outside-
 * click policy for a control used a handful of times per account; `interior/dropdown.tsx`
 * exists but is unimported (the audit's F-14), and adopting it is that lane's job, not a
 * dependency this seam should acquire.
 *
 * So: a `<button>`. Focusable, operable with Enter and Space with no key handling of our
 * own, and its accessible name states BOTH the current appearance and what the next press
 * does — because an icon-only control whose label is just "Theme" tells a screen-reader
 * user nothing about which of three states they are in.
 *
 * ## Why the visible state waits for mount
 *
 * The server cannot know what is in this browser's `localStorage`, so a first render that
 * claimed to know would be a hydration mismatch. It renders the default costume, then
 * corrects on mount — and, crucially, it does NOT call `applyTheme` before it has read the
 * stored choice. Applying "system" first would undo, for one frame, exactly the class the
 * blocking script in `app/layout.tsx` set from storage: the white flash this whole seam is
 * built to avoid, reintroduced by the component meant to prevent it.
 */

import { useCallback, useEffect, useState } from "react";

import { Monitor, Moon, Sun } from "lucide-react";

import {
  THEME_LABELS,
  applyTheme,
  nextThemeChoice,
  readThemeChoice,
  resolveTheme,
  systemTheme,
  writeThemeChoice,
  type ThemeChoice,
} from "@/lib/theme";

/** The current choice and a setter that persists it and repaints the document. */
export function useThemeChoice(): {
  choice: ThemeChoice;
  mounted: boolean;
  setChoice: (choice: ThemeChoice) => void;
} {
  const [choice, setChoiceState] = useState<ThemeChoice>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setChoiceState(readThemeChoice());
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    applyTheme(resolveTheme(choice));
    // While the choice is "system" the OS is still in charge — including when it flips at
    // sunset with this tab open. Without this listener "system" would mean "whatever the OS
    // said when the page loaded", which is a different and less useful promise.
    if (choice !== "system") return;
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query?.addEventListener) return;
    const onChange = (): void => applyTheme(systemTheme());
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [choice, mounted]);

  const setChoice = useCallback((next: ThemeChoice) => {
    writeThemeChoice(next);
    setChoiceState(next);
  }, []);

  return { choice, mounted, setChoice };
}

const ICONS: Record<ThemeChoice, typeof Monitor> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
};

/**
 * The appearance control, sized and shaped like the other header controls beside it
 * (`h-9 w-9`, `touch:h-11 touch:w-11` — the 44px finger target `globals.css` argues for).
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { choice, setChoice } = useThemeChoice();
  const Icon = ICONS[choice];
  const next = nextThemeChoice(choice);

  return (
    <button
      type="button"
      onClick={() => setChoice(next)}
      // Both halves in the name: which state you are in, and what pressing this does. A
      // control that only says "Theme" leaves a non-sighted reader unable to tell dark from
      // light, which is the whole content of the control.
      aria-label={`Appearance: ${THEME_LABELS[choice]}. Switch to ${THEME_LABELS[next]}.`}
      title={`Appearance: ${THEME_LABELS[choice]}`}
      className={
        "flex h-9 w-9 items-center justify-center rounded-md border border-line bg-surface " +
        "text-ink-muted hover:bg-black/5 touch:h-11 touch:w-11 dark:hover:bg-white/5" +
        (className ? ` ${className}` : "")
      }
    >
      <Icon aria-hidden className="h-4 w-4" />
    </button>
  );
}
