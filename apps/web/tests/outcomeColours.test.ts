import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { OUTCOME_DOT, OUTCOME_ROW } from "@/app/c/[slug]/calls/callColumns";
import { OUTCOME_KIND_WORDS, type OutcomeKind, callOutcome } from "@/lib/callReview";

/**
 * EVERY OUTCOME THE API CAN RETURN HAS ITS OWN COLOUR (founder, 27 Oct 2026).
 *
 * The values are read from where they are defined, not retyped here: the outcome tag and
 * the lead move from the generated OpenAPI document, the call status from the shared
 * `CallStatus` literal. A value the server adds and this screen never heard of fails
 * here, rather than reaching the call log as a grey dot or as a colour shared with an
 * outcome that means something else.
 */

const OPENAPI = JSON.parse(readFileSync(join(process.cwd(), "src", "lib", "api", "openapi.json"), "utf8"));
const CALL_SUMMARY = OPENAPI.components.schemas.CallSummaryOut.properties;

function enumOf(property: { anyOf?: { enum?: string[] }[]; enum?: string[] }): string[] {
  const values = property.enum ?? property.anyOf?.flatMap((arm) => arm.enum ?? []) ?? [];
  if (values.length === 0) throw new Error("the property carries no enum in openapi.json");
  return values;
}

const OUTCOME_TAGS = enumOf(CALL_SUMMARY.outcome_tag);
const LEAD_MOVES = enumOf(CALL_SUMMARY.business_outcome_lead_status);

const EVENTS = readFileSync(join(process.cwd(), "..", "..", "packages", "shared", "src", "calevate_shared", "events.py"), "utf8");
const CALL_STATUSES = [...EVENTS.slice(EVENTS.indexOf("CallStatus = Literal[")).split("]")[0].matchAll(/"([a-z_]+)"/g)].map(
  (m) => m[1],
);

const done = { status: "completed", summary_state: "ready" } as const;

function kindOf(call: Parameters<typeof callOutcome>[0]): OutcomeKind {
  const { kind } = callOutcome(call);
  expect(OUTCOME_DOT[kind], `kind "${kind}" has no colour`).toMatch(/^bg-/);
  return kind;
}

describe("every outcome the API returns has a colour", () => {
  it("reads the server's vocabularies", () => {
    expect(OUTCOME_TAGS).toContain("needs_you");
    expect(LEAD_MOVES).toEqual(expect.arrayContaining(["contacted", "interested", "hot"]));
    expect(CALL_STATUSES).toEqual(expect.arrayContaining(["completed", "no_answer", "voicemail"]));
  });

  it.each(OUTCOME_TAGS)("outcome tag %s", (tag) => {
    kindOf({ ...done, outcome_tag: tag as never });
  });

  it.each(LEAD_MOVES)("the agent's own outcome moving the lead to %s", (move) => {
    kindOf({ ...done, outcome_tag: "answered", business_outcome: "own", business_outcome_label: "Own", business_outcome_lead_status: move as never });
  });

  it.each(CALL_STATUSES)("call status %s", (status) => {
    kindOf({ status, outcome_tag: null, summary_state: "ready" });
  });

  it("gives two different outcomes two different colours", () => {
    const kinds = Object.keys(OUTCOME_KIND_WORDS) as OutcomeKind[];
    expect(Object.keys(OUTCOME_DOT).sort()).toEqual([...kinds].sort());
    const colours = kinds.map((kind) => OUTCOME_DOT[kind]);
    expect(new Set(colours).size).toBe(colours.length);
    // The founder's two calls: "Ready to visit" (hot) and "Considering options" (interested).
    const hot = kindOf({ ...done, outcome_tag: "needs_you", business_outcome: "ready_to_visit", business_outcome_label: "Ready to visit", business_outcome_lead_status: "hot" });
    const interested = kindOf({ ...done, outcome_tag: "answered", business_outcome: "considering", business_outcome_label: "Considering options", business_outcome_lead_status: "interested" });
    expect(OUTCOME_DOT[hot]).not.toBe(OUTCOME_DOT[interested]);
    expect(OUTCOME_DOT[kindOf({ ...done, outcome_tag: "hung_up_early" })]).not.toBe(
      OUTCOME_DOT[kindOf({ ...done, outcome_tag: "answered", business_outcome: "not_interested", business_outcome_label: "Not interested", business_outcome_lead_status: "contacted" })],
    );
  });
});

// --- contrast: WCAG 2.2 SC 1.4.11, 3:1 for a graphical mark -----------------------------

const CSS = readFileSync(join(process.cwd(), "src", "app", "globals.css"), "utf8");
const ROOT = CSS.slice(CSS.indexOf(":root {"), CSS.indexOf("\n}", CSS.indexOf(":root {")));
const DARK = CSS.slice(CSS.indexOf(".dark {"), CSS.indexOf("\n}", CSS.indexOf(".dark {")));

function hexIn(block: string, name: string): string | null {
  return block.match(new RegExp(`\\n\\s*--${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1].toLowerCase() ?? null;
}

/** A `bg-*` class's hex in a palette: the `@theme` colour, its variable, the palette's value. */
function colourOf(className: string, palette: "light" | "dark"): string {
  const name = className.replace(/^bg-/, "");
  const variable = CSS.match(new RegExp(`--color-${name}:\\s*var\\(--([a-z0-9-]+)\\)`))?.[1];
  if (!variable) throw new Error(`${className} names no @theme colour in globals.css`);
  const hex = (palette === "dark" ? hexIn(DARK, variable) : null) ?? hexIn(ROOT, variable);
  if (!hex) throw new Error(`--${variable} has no hex value in globals.css`);
  return hex;
}

function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  const channel = (v: number) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

describe("every outcome colour is visible on the call log", () => {
  const rows = (Object.entries(OUTCOME_DOT) as [OutcomeKind, string][]).flatMap(([kind, className]) =>
    (["light", "dark"] as const).flatMap((palette) =>
      (["surface", "app"] as const).map((ground) => [kind, className, palette, ground] as const),
    ),
  );

  it.each(rows)("%s (%s) on the %s %s", (_kind, className, palette, ground) => {
    const groundHex = (palette === "dark" ? hexIn(DARK, ground) : null) ?? hexIn(ROOT, ground)!;
    expect(contrast(colourOf(className, palette), groundHex)).toBeGreaterThanOrEqual(3);
  });
});

describe("each call row is washed in its outcome's colour, faded", () => {
  it.each(Object.entries(OUTCOME_DOT) as [OutcomeKind, string][])("%s", (kind, dot) => {
    const colour = dot.replace(/^bg-/, "");
    const wash = OUTCOME_ROW[kind];
    expect(wash.split(" ")).toContainEqual(expect.stringMatching(new RegExp(String.raw`^bg-${colour}/\[0\.0\d\]$`)));
    expect(wash).toMatch(new RegExp(`dark:bg-${colour}/`));
  });
});
