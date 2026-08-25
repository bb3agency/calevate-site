import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "@/components/theme";
import {
  DARK_CLASS,
  THEME_STORAGE_KEY,
  nextThemeChoice,
  readThemeChoice,
  resolveTheme,
  themeScriptSource,
} from "@/lib/theme";

/**
 * DARK MODE, now that it is reachable.
 *
 * The state this replaces: `globals.css` declared a class-based dark variant and a full
 * dark palette, 429 `dark:` variants were written against it, `tests/contrast.test.ts`
 * measured the dark tokens at 4.5:1 — and nothing in `src` ever set the class. Every one of
 * those was inert and the contrast gate was measuring a theme no user could enter.
 *
 * So the assertions here are the ones that make that gate mean something again: the class
 * really lands on `<html>`, an explicit choice really persists, and the default really
 * follows the device. Plus the one that cannot be seen by reading the app at all — that the
 * BLOCKING SCRIPT does its job, tested by executing the exact source string the browser is
 * given, because that code runs before React exists and nothing else can correct it.
 */

/** Point `matchMedia` at a device preference, the way `tests/setup.ts` does globally. */
function deviceIs(theme: "light" | "dark"): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-color-scheme: dark")
      ? theme === "dark"
      : query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.classList.remove(DARK_CLASS);
  document.documentElement.style.colorScheme = "";
  deviceIs("light");
});

afterEach(() => {
  window.localStorage.clear();
  document.documentElement.classList.remove(DARK_CLASS);
});

describe("the blocking no-flash script", () => {
  /**
   * Executed rather than read. A test that only asserted the string CONTAINED "dark" would
   * pass on a script with a syntax error in it — and a syntax error here is invisible: the
   * page renders perfectly, in the wrong theme, with one console message nobody sees.
   */
  const run = (): void => {
    (0, eval)(themeScriptSource());
  };

  it("stamps the stored choice before anything else runs", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    run();
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("follows the device when nothing has been chosen", () => {
    deviceIs("dark");
    run();
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);

    document.documentElement.classList.remove(DARK_CLASS);
    deviceIs("light");
    run();
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(false);
  });

  it("lets an explicit LIGHT choice beat a dark device", () => {
    deviceIs("dark");
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    run();
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");
  });

  it("survives a browser that refuses storage entirely", () => {
    // Safari's private mode and a storage-blocked iframe THROW on access rather than
    // returning null. A theme preference must never be the thing that stops a page.
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("SecurityError");
      },
    });
    expect(() => run()).not.toThrow();
    if (original) Object.defineProperty(window, "localStorage", original);
  });

  it("is inlined by the root layout, at the top of <body>, from this same module", () => {
    // The one thing a unit test cannot see: that the shipped source is what the document
    // actually carries. A second, hand-written copy in the layout would be the only piece
    // of this seam with nothing over it — and it is the piece that runs first.
    const layout = readFileSync(
      join(process.cwd(), "src", "app", "layout.tsx"),
      "utf8",
    );
    expect(layout).toContain("themeScriptSource()");
    expect(layout).toContain("suppressHydrationWarning");
    expect(layout.indexOf("themeScriptSource()")).toBeLessThan(layout.indexOf("{children}"));
  });
});

describe("the choice", () => {
  it("cycles system → light → dark → system, so the default stays reachable", () => {
    expect(nextThemeChoice("system")).toBe("light");
    expect(nextThemeChoice("light")).toBe("dark");
    expect(nextThemeChoice("dark")).toBe("system");
  });

  it("reads as `system` when nothing is stored, and when storage holds junk", () => {
    expect(readThemeChoice()).toBe("system");
    window.localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readThemeChoice()).toBe("system");
  });

  it("resolves `system` against the device and the other two against themselves", () => {
    deviceIs("dark");
    expect(resolveTheme("system")).toBe("dark");
    expect(resolveTheme("light")).toBe("light");
    deviceIs("light");
    expect(resolveTheme("system")).toBe("light");
    expect(resolveTheme("dark")).toBe("dark");
  });
});

describe("the toggle", () => {
  it("is a labelled button naming both the current state and the next one", async () => {
    await act(async () => {
      render(<ThemeToggle />);
    });
    const button = screen.getByRole("button", {
      name: "Appearance: match my device. Switch to light.",
    });
    expect(button.tagName).toBe("BUTTON");
    // A real <button>: operable with Enter and Space with no key handling of our own.
    expect(button.getAttribute("type")).toBe("button");
  });

  it("actually enters dark mode, and persists the choice", async () => {
    await act(async () => {
      render(<ThemeToggle />);
    });
    // system → light
    await act(async () => {
      screen.getByRole("button", { name: /Appearance/ }).click();
    });
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    // light → dark
    await act(async () => {
      screen.getByRole("button", { name: /Appearance/ }).click();
    });
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("returns to following the device, and FORGETS the choice when it does", async () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    deviceIs("light");
    await act(async () => {
      render(<ThemeToggle />);
    });
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);

    // dark → system
    await act(async () => {
      screen.getByRole("button", { name: /Appearance/ }).click();
    });
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(false);
  });

  it("does not undo the blocking script's work on first mount", () => {
    // The regression this guards: applying the DEFAULT before the stored choice has been
    // read strips `.dark` for a frame — the white flash the whole seam exists to prevent,
    // reintroduced by the component meant to prevent it.
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    (0, eval)(themeScriptSource());
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);
    render(<ThemeToggle />);
    expect(document.documentElement.classList.contains(DARK_CLASS)).toBe(true);
  });
});

describe("the theme the contrast gate measures", () => {
  it("exists, because something now sets the class it is keyed on", () => {
    // `tests/contrast.test.ts` computes the `.dark` palette at 4.5:1. That was measuring a
    // theme no user could enter. This is the link between the two: the class the CSS
    // selects on is the class the app sets.
    const css = readFileSync(join(process.cwd(), "src", "app", "globals.css"), "utf8");
    expect(css).toContain(`.${DARK_CLASS} {`);
    expect(css).toContain(`@custom-variant dark (&:is(.${DARK_CLASS} *))`);
    expect(themeScriptSource()).toContain(`"${DARK_CLASS}"`);
  });
});
