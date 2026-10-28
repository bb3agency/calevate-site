import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KIND_COPY } from "@/app/c/[slug]/attention/rows";
import { HEARD_FAILURES } from "@/app/c/[slug]/agents/first/BriefStep";
import { HONEST_WORDS } from "@/app/c/[slug]/agents/first/HearItStep";
import { JOBS } from "@/app/c/[slug]/agents/new/StartFromJob";
import { MOVE_COPY, NUMBER_COPY, VERIFY_COPY } from "@/app/c/[slug]/go-live/GoLiveGuide";
import { splitHint } from "@/app/c/[slug]/setup/SetupWizard";
import { ATTENTION, FIRST, GO_LIVE, HOME, NEW_AGENT, SETUP, TRIAL } from "@/app/c/[slug]/setup/_ui/copy";
import { Why } from "@/components/why";
import { STEPS } from "@/lib/api/businessProfile";

import { SHORT_LINE } from "./shortCopy";

/**
 * "BUTTONS, NOT PARAGRAPHS" (founder, Oct 2026): every line the home, attention, go-live,
 * setup and first-agent screens show by default is one short line. About 60 characters is
 * the ceiling; a longer explanation belongs behind a "Why?" tap, which is not checked here.
 */
const MAX = SHORT_LINE;

/** Every string a copy table holds, with each function called on worst-case-ish values. */
function linesOf(value: unknown, path: string): [string, string][] {
  if (typeof value === "string") return [[path, value]];
  if (typeof value === "function") {
    // Big counts, then the longest words a screen passes in ("12 minutes", a language
    // name, a rupee figure), so the filled-in line is what is measured. The two date
    // lines are measured with a real date below.
    const fill = value as (...args: unknown[]) => unknown;
    return [...linesOf(fill(1000, 1000), `${path}(n)`), ...linesOf(fill("12 minutes", "12 minutes"), `${path}(s)`)];
  }
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, inner]) => linesOf(inner, `${path}.${key}`));
  }
  return [];
}

const TABLES: Record<string, unknown> = {
  HOME,
  TRIAL,
  ATTENTION,
  GO_LIVE,
  SETUP,
  FIRST,
  NEW_AGENT,
  KIND_COPY: Object.fromEntries(Object.entries(KIND_COPY).map(([k, v]) => [k, { label: v.label, action: v.action }])),
  MOVE_COPY: Object.fromEntries(Object.entries(MOVE_COPY).map(([k, v]) => [k, { title: v.title, hint: v.hint }])),
  VERIFY_COPY: Object.fromEntries(
    Object.entries(VERIFY_COPY).map(([k, v]) => [k, { title: v.title, hint: v.hint, action: v.action ?? "" }]),
  ),
  NUMBER_COPY: Object.fromEntries(
    Object.entries(NUMBER_COPY).map(([k, v]) => [k, { title: v.title, hint: v.hint, action: v.action ?? "" }]),
  ),
  HEARD_FAILURES,
  HONEST_WORDS: HONEST_WORDS.map((row) => row.line),
  JOBS: JOBS.map((job) => ({ title: job.title, line: job.line })),
  SETUP_HINT_LEADS: STEPS.map((step) => splitHint(step.hint).lead),
};

describe("short default copy", () => {
  const lines = Object.entries(TABLES).flatMap(([name, table]) => linesOf(table, name));

  it("has lines to check", () => {
    expect(lines.length).toBeGreaterThan(100);
  });

  it.each(lines)("%s fits on one short line", (_path, line) => {
    expect(line.length).toBeLessThanOrEqual(MAX);
  });

  it("keeps the trial date lines short with a real date in them", () => {
    const date = "Sat 31 Oct 2026, 11:30 pm IST";
    expect(HOME.trialLastDay("23 hours left").length).toBeLessThanOrEqual(MAX);
    expect(HOME.trialFree(date).length).toBeLessThanOrEqual(MAX);
  });
});

describe("splitHint", () => {
  it("keeps the first sentence and puts the rest behind the tap", () => {
    expect(splitHint("Callers ask this first. Mark the days you are closed.")).toEqual({
      lead: "Callers ask this first.",
      rest: "Mark the days you are closed.",
    });
  });

  it("keeps a one-sentence hint whole", () => {
    expect(splitHint("Add each branch callers can visit.")).toEqual({
      lead: "Add each branch callers can visit.",
      rest: null,
    });
  });
});

describe("Why", () => {
  it("shows only its label until tapped", () => {
    render(<Why>The longer reason.</Why>);
    const details = screen.getByText("Why?").closest("details");
    expect(details?.open).toBe(false);
    screen.getByText("Why?").click();
    expect(details?.open).toBe(true);
    expect(screen.getByText("The longer reason.")).toBeTruthy();
  });
});
