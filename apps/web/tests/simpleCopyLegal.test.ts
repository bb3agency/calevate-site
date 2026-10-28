import { describe, expect, it } from "vitest";

import { AGREEMENTS_COPY, acceptLabel, inForceFrom } from "@/app/c/[slug]/agreements/copy";
import { AI_ASSIST_COPY, aboutMore, addedLine, ofAbout, overBy, prepJobs } from "@/app/c/[slug]/ai-assist/copy";
import { ASSISTANT_COPY } from "@/app/c/[slug]/assistant/copy";
import { CALLER_NOTICE_COPY, CALLER_NOTICE_KEPT } from "@/app/c/[slug]/caller-notice/copy";
import { DATA_RIGHTS_COPY, DATA_RIGHTS_KEPT, audioHeld, erasedOn, filedLine } from "@/app/c/[slug]/data-rights/copy";
import {
  DNC_COPY,
  DNC_KEPT,
  addLabel,
  charsLeft,
  entriesLabel,
  manyNumbers,
  showingLatest,
  tooMany,
} from "@/app/c/[slug]/do-not-call/copy";
import { CONSENT_COPY, lapsedOn } from "@/app/c/[slug]/messaging-consent/copy";
import { PERFORMANCE_COPY, periodHeadline } from "@/app/c/[slug]/performance/copy";
import { QUALITY_COPY, monthEnding, tricky, verdictLine } from "@/app/c/[slug]/quality/copy";

import { SHORT_LINE } from "./shortCopy";

/**
 * "Buttons, not paragraphs" for the legal, consent and insight screens: every line these
 * screens show by default is short enough to read at a glance on a 375px phone, in a
 * second language.
 *
 * Two kinds of words are deliberately outside the budget and are NOT checked here:
 * - server-owned text (an agreement, the acceptance statement, the caller-notice draft and
 *   its disclaimer, a verdict), which never passes through these constants;
 * - the `*_KEPT` sentences: compliance wording kept word for word and never behind a tap
 *   (UX-DOCTRINE §3, §8.7). Shortening one of those to pass this test would be the wrong fix.
 *
 * Keys ending in `Why` or `Tip` are shown only behind a tap ("Why?", an ⓘ), so they get a
 * looser budget: a short paragraph, not a page.
 */
const LINE = SHORT_LINE;
const BEHIND_A_TAP = 200;

const SCREENS: Record<string, Record<string, string>> = {
  agreements: AGREEMENTS_COPY,
  "caller-notice": CALLER_NOTICE_COPY,
  "data-rights": DATA_RIGHTS_COPY,
  "do-not-call": DNC_COPY,
  "messaging-consent": CONSENT_COPY,
  quality: QUALITY_COPY,
  performance: PERFORMANCE_COPY,
  "ai-assist": AI_ASSIST_COPY,
  assistant: ASSISTANT_COPY,
};

/** The composed lines, at realistic worst-case values (long Indian amounts, long dates). */
const COMPOSED: string[] = [
  acceptLabel(4),
  inForceFrom("30 September 2026"),
  filedLine("30 Sept 2026, 11:45 pm", "30 Sept 2026, 11:59 pm"),
  erasedOn("30 Sept 2026, 11:45 pm"),
  audioHeld("12 recordings", "30 Sept 2027, 11:45 pm"),
  manyNumbers("1,000"),
  tooMany("1,000", "500"),
  addLabel(500, "500"),
  entriesLabel(12_345, "12,345"),
  showingLatest("500"),
  charsLeft(280),
  lapsedOn("30 Sept 2026, 11:45 pm"),
  periodHeadline("30 Sept 2025 – 30 Sept 2026"),
  verdictLine(0, 120),
  verdictLine(12, 120),
  monthEnding("30 September 2026"),
  tricky(18),
  ofAbout("12,345"),
  aboutMore("12,345"),
  prepJobs(12, "12"),
  overBy("₹1,23,456.78"),
  addedLine("₹1,23,456.78"),
];

describe("short default copy on the legal, consent and insight screens", () => {
  for (const [screen, copy] of Object.entries(SCREENS)) {
    it(`${screen}: every default line is ${LINE} characters or fewer`, () => {
      const long = Object.entries(copy)
        .filter(([key]) => !/(Why|Tip)$/.test(key))
        .filter(([, line]) => line.length > LINE)
        .map(([key, line]) => `${key} (${line.length}): ${line}`);
      expect(long).toEqual([]);
    });

    it(`${screen}: what sits behind a tap is a short paragraph, not a page`, () => {
      const long = Object.entries(copy)
        .filter(([key]) => /(Why|Tip)$/.test(key))
        .filter(([, line]) => line.length > BEHIND_A_TAP)
        .map(([key, line]) => `${key} (${line.length})`);
      expect(long).toEqual([]);
    });
  }

  it("composed lines stay short at worst-case values", () => {
    expect(COMPOSED.filter((line) => line.length > LINE)).toEqual([]);
  });

  it("names no vendor in any line it writes (D-679)", () => {
    const every = [
      ...Object.values(SCREENS).flatMap((copy) => Object.values(copy)),
      ...COMPOSED,
      ...Object.values(CALLER_NOTICE_KEPT),
      ...Object.values(DATA_RIGHTS_KEPT),
      ...Object.values(DNC_KEPT),
    ];
    const vendors = /thinnest|cartesia|gemini|sarvam|azure|openai|google/i;
    expect(every.filter((line) => vendors.test(line))).toEqual([]);
  });

  it("keeps the compliance sentences whole rather than trimmed to fit", () => {
    // The guarantee and the live-check notice are pinned by meaning in their own suites;
    // here, only that nobody cut them down to pass the budget above.
    expect(CALLER_NOTICE_KEPT.guarantee).toContain("answers truthfully");
    expect(DNC_KEPT.liveCheck).toContain("including for a campaign that is already running");
    expect(DATA_RIGHTS_KEPT.noRestore).toBe("Nothing restores them.");
  });
});
