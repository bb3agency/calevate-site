/**
 * DARK MODE, RESOLVED: the product SHIPS it, rather than deleting 429 variants.
 *
 * The state this replaces was the half-wired one CLAUDE.md names as a defect. `globals.css`
 * declared `@custom-variant dark (&:is(.dark *))` and a full `.dark` token block; 429
 * `dark:` variants were written across the app against it; `tests/contrast.test.ts` measured
 * the dark palette at 4.5:1 — and NOTHING anywhere set `.dark` on `<html>`, so every one of
 * those was unreachable and the contrast gate was measuring a theme no user could enter.
 *
 * The fork was: wire the switch, or remove the pretence. Wiring it is a hundred lines and
 * makes 429 existing variants, a measured dark palette and a contrast gate all start doing
 * their jobs; removing it is a ~429-line deletion that makes a console that is bright white
 * at 11pm on the low-end Android the BRD names as the target device, and throws away work
 * that is already done and already tested. So: wired.
 *
 * ## Why the CLASS strategy stays, rather than moving to `prefers-color-scheme`
 *
 * `globals.css` already argued this and the argument holds: a media query cannot be
 * overridden per person. An owner whose phone is in dark mode but who wants the console
 * light — because a colleague reads over their shoulder, because the room is bright — has
 * no way to say so if the CSS keys on the OS. Class-based lets BOTH be true: the OS
 * preference is the default, and an explicit choice wins and persists.
 *
 * ## The three states, and why "system" is a real one rather than the absence of a choice
 *
 *   - `"system"` — nothing stored. Follows `prefers-color-scheme` and KEEPS following it,
 *     including when the OS flips at sunset while the tab is open.
 *   - `"light"` / `"dark"` — stored. Wins over the OS, on this device, until changed.
 *
 * A two-state toggle cannot express the third, which is the one that has to be reachable:
 * a person who taps once to try dark must be able to get back to "whatever my phone says".
 *
 * ## Flash-free is the whole engineering problem, and it is solved BEFORE React
 *
 * A theme applied in `useEffect` paints the light page first and repaints dark after
 * hydration — the white flash every one of these implementations ships with if the script
 * is not blocking. `themeScriptSource()` is stamped into the document as an inline
 * `<script>` at the top of `<body>` (see `app/layout.tsx`), so the browser executes it
 * synchronously while parsing, before any content of the page is painted, and the very
 * first paint is already correct.
 *
 * It is a STATIC string with no interpolation of any kind — nothing user-, route- or
 * env-derived reaches it — so the one hazard of `dangerouslySetInnerHTML` (injection) has
 * no path in. Everything it touches is wrapped in try/catch because `localStorage` throws
 * outright in a Safari private window and in a third-party iframe with storage blocked, and
 * a theme preference must never be the thing that stops a page from rendering.
 */

/** Where the explicit choice lives. Namespaced, because `localStorage` is per ORIGIN and
 *  this origin also serves the marketing site. */
export const THEME_STORAGE_KEY = "calevate.theme";

/** The class `globals.css`'s `@custom-variant dark` selects on. */
export const DARK_CLASS = "dark";

/** What a person chose, including choosing not to choose. */
export type ThemeChoice = "system" | "light" | "dark";

/** What is actually on screen once `system` has been resolved against the device. */
export type ResolvedTheme = "light" | "dark";

/** Human names, used by the toggle's accessible label and nowhere else. */
export const THEME_LABELS: Record<ThemeChoice, string> = {
  system: "match my device",
  light: "light",
  dark: "dark",
};

/**
 * The cycle order of the toggle: system → light → dark → system.
 *
 * Deliberately starts at the OS-following state rather than at light, so a first tap from
 * the default is a step AWAY from the device preference in the visible direction — and
 * three taps always return to where it started, which is what makes a single button an
 * honest control for three states.
 */
export function nextThemeChoice(current: ThemeChoice): ThemeChoice {
  return current === "system" ? "light" : current === "light" ? "dark" : "system";
}

/** The stored choice, or `"system"` when there is none — and when storage refuses to answer. */
export function readThemeChoice(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

/** Persist a choice, or forget it when the choice is "follow the device". */
export function writeThemeChoice(choice: ThemeChoice): void {
  try {
    if (choice === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // A browser that refuses storage still gets the theme for this page view; it just
    // cannot remember it. That is strictly better than failing the interaction.
  }
}

/** The device preference, defaulting to light where `matchMedia` is absent (jsdom, old engines). */
export function systemTheme(): ResolvedTheme {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** What a choice means on this device, right now. */
export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  return choice === "system" ? systemTheme() : choice;
}

/**
 * Put a resolved theme on the document.
 *
 * `style.colorScheme` as well as the class, and it is not decoration: it is what tells the
 * ENGINE to paint its own furniture dark — form control chrome, the scrollbar, the spelling
 * underline, `<input type="date">`'s picker. Without it a dark console renders a white
 * scrollbar and a white native date picker, which is the tell that a dark mode was bolted
 * on with classes alone.
 */
export function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement;
  root.classList.toggle(DARK_CLASS, theme === "dark");
  root.style.colorScheme = theme;
}

/**
 * The blocking inline script, as source.
 *
 * Kept as a string in a normal module (rather than written into `layout.tsx`) so the SUITE
 * can execute the exact bytes the browser executes — `tests/theme.test.ts` evals this and
 * asserts the document it produces. A hand-written copy in the layout would be the one
 * thing in the theme path with no test over it, and it is the one thing that runs before
 * anything else can correct it.
 *
 * It duplicates the small logic above ON PURPOSE and this is the one place in this seam
 * where duplication is right: this code must run with no imports, no bundle and no React,
 * as the parser reaches it. It is six lines, it is pinned by a test that runs the string,
 * and the alternative — shipping a module graph to set one class — is what causes the
 * flash this exists to prevent.
 */
export function themeScriptSource(): string {
  return (
    `(function(){try{` +
    `var c=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});` +
    `var d=c==="dark"||(c!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches);` +
    `var e=document.documentElement;` +
    `e.classList.toggle(${JSON.stringify(DARK_CLASS)},d);` +
    `e.style.colorScheme=d?"dark":"light";` +
    `}catch(_){}})();`
  );
}
