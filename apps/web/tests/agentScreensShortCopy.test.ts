import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { JOBS } from "@/app/c/[slug]/agents/actions/jobs";

import { WEB_ROOT } from "./copyScan";
import { SHORT_LINE, defaultCopyIn, isClassList, longLines, shown, type Hidden } from "./shortCopy";

/**
 * BUTTONS, NOT PARAGRAPHS — on the agent list, one agent's tabs (all but Training) and the
 * script editor, no line a person reads by default runs past about one phone line.
 *
 * The readers are small-business owners and staff, often on a phone and often reading
 * English as a second language. A line longer than {@link MAX} characters wraps to three or
 * four lines at 375px, which is where they stop reading. Longer reasoning still has a home:
 * behind a tap (an ⓘ, a "How it works", a disclosure), which this guard deliberately skips.
 *
 * What counts as "read by default" is `shortCopy.ts`'s walk (JSX text, copy props, and every
 * string that reads as prose, a `+` chain measured whole), minus:
 *  - the inside of an `InfoTip`, `Disclosure`, `HowItWorks` or `<details>`, and an `info`
 *    prop or property — those are opened by a tap;
 *  - `title` and `aria-*` attributes — a hover tooltip or a screen-reader name;
 *  - what the screen tells the assistant (`useCopilotSurface`, `CopilotSurfaceScope`), which
 *    no person sees;
 *  - class lists.
 * Words that come from the server (headlines, reasons) are not in the source and are not
 * judged here.
 */
const MAX = SHORT_LINE;

const ROOT = "src/app/c/[slug]/agents";

/** The files this pass rewrote, so a new long line in them fails here. */
const FILES = [
  "page.tsx",
  "Roster.tsx",
  "LaneGuide.tsx",
  "AgentBadge.tsx",
  "AgentReadiness.tsx",
  "AgentLifecycle.tsx",
  "AgentIdentity.tsx",
  "AgentModel.tsx",
  "[agentId]/AgentWorkspace.tsx",
  "[agentId]/sections/agentHeader.tsx",
  "[agentId]/sections/overview.tsx",
  "[agentId]/sections/settingsTab.tsx",
  "[agentId]/sections/deliverySections.tsx",
  "panels/publishing.tsx",
  "panels/openingNotices.tsx",
  "panels/delivery.tsx",
  "panels/voiceTuning.tsx",
  "panels/callHandling.tsx",
  "panels/callerContinuity.tsx",
  "panels/callerScreen.tsx",
  "panels/handover.tsx",
  "panels/teamAlerts.tsx",
  "panels/extraction.tsx",
  "panels/extractionRow.tsx",
  "actions/Actions.tsx",
  "actions/ToolRow.tsx",
  "actions/ToolDetail.tsx",
  "actions/BookingJob.tsx",
  "[agentId]/script/ScriptBuilder.tsx",
  "[agentId]/script/ScriptSections.tsx",
  "[agentId]/script/SectionEditor.tsx",
  "[agentId]/script/HandWritten.tsx",
  "[agentId]/script/PipAsk.tsx",
  "[agentId]/script/PipProposal.tsx",
  "[agentId]/script/ProposalReview.tsx",
  "[agentId]/script/ScriptHistory.tsx",
  "[agentId]/script/PutLive.tsx",
  "[agentId]/script/ScriptToolbar.tsx",
  "[agentId]/script/SmallSteps.tsx",
  "[agentId]/script/TaughtRules.tsx",
] as const;

/** What is shown only after a tap on these screens, or never to a person. */
const HIDDEN: Hidden = {
  // The element's own props (a Disclosure's title) are on screen; its children are not.
  elements: new Set(["InfoTip", "Disclosure", "HowItWorks", "details", "Popover"]),
  closedElements: new Set(["HowItWorks", "InfoTip"]),
  attrs: /^(info|title|aria-[a-z]+|className|href|id|key|prompt|data-[a-z-]+)$/,
  props: new Set(["info", "facts", "prompt", "why"]),
  // What the screen tells the assistant, which no person sees.
  calls: new Set(["useCopilotSurface", "CopilotSurfaceScope"]),
  // A request sent to the assistant, never shown. `wholeRequestFor` is `WHOLE_REQUEST` with
  // the agent's name in it, now measured whole rather than as two short template pieces.
  constants: /_REQUEST$|^wholeRequestFor$/,
  // Rendered only inside a disclosure its caller draws.
  functions: new Set(["NoticeDetails"]),
};

describe("agent screens speak in short lines", () => {
  it.each(FILES)("%s has no default line longer than one phone line", (relative) => {
    const found = longLines(defaultCopyIn(join(WEB_ROOT, ROOT, relative), HIDDEN));
    expect(found, `Shorten these, or move the reasoning behind a tap (Why / InfoTip):\n${found.join("\n")}`).toEqual([]);
  });

  it("keeps each job card on the Actions tab to a short title and line", () => {
    // `jobs.ts` also holds what the agent is told (default instructions, tool descriptions),
    // which no person reads on a card, so the cards are checked from the data itself.
    for (const job of JOBS) {
      expect(job.title.length, job.title).toBeLessThanOrEqual(MAX);
      expect(job.line.length, job.line).toBeLessThanOrEqual(MAX);
    }
  });

  it("catches a long line it is shown, so it is not passing by reading nothing", () => {
    // The walk must see a real component's copy: every file above yields lines, and a
    // known-long sentence passes through the same predicates as one.
    for (const relative of FILES) {
      expect(defaultCopyIn(join(WEB_ROOT, ROOT, relative), HIDDEN).length, relative).toBeGreaterThan(0);
    }
    const sample = "This sentence is deliberately much longer than one line on a small phone screen.";
    expect(shown(sample).length).toBeGreaterThan(MAX);
    expect(isClassList(sample)).toBe(false);
    expect(isClassList("flex flex-wrap items-center gap-x-2 gap-y-1 text-body font-medium text-ink")).toBe(true);
  });
});
