import { describe, expect, it } from "vitest";

import { skippedNote } from "@/app/c/[slug]/agents/[agentId]/script/ImprovementReview";
import { TOUR_STEPS } from "@/app/c/[slug]/agents/[agentId]/tour/tourModel";
import { splitHint } from "@/app/c/[slug]/setup/SetupWizard";
import { openingWaitsLine } from "@/components/callHandlingRows";
import { modeSummary } from "@/components/forwarding/copy";
import { originLine } from "@/components/leadFields/CallOutcomesView";
import { STEPS } from "@/lib/api/businessProfile";
import { DOCUMENT_KINDS, KYC_STATUS_COPY } from "@/lib/api/kyc";
import { ROLE_COPY } from "@/lib/api/members";
import type { Improvement } from "@/lib/api/script";
import { OUTCOME_ORDER, outcomeReason } from "@/lib/callReview";

import { SHORT_LINE, defaultCopyUnder, longLines, type Hidden } from "./shortCopy";

/**
 * BUTTONS, NOT PARAGRAPHS — the shared pieces every area screen borrows: Lead details, the
 * business-profile editor, call forwarding, the follow-up menu, the model choice, the
 * practice-test pieces, the test-call status, the trial and held-number notices, the agent
 * page's action, tour, Try it and Knows-by-heart parts, and the copy tables in `lib/`.
 *
 * No area guard reads these, because no area owns them; a long line here shows up on many
 * screens at once. Same rule as the areas (`shortCopy.ts`): one phone line by default, the
 * reason behind a tap.
 */

const SHARED = [
  "src/components/leadFields",
  "src/components/businessProfile",
  "src/components/forwarding",
  "src/components/calls",
  "src/components/improvement",
  "src/components/modelTierSetting.tsx",
  "src/components/arc/gauge.tsx",
  "src/components/callHandlingRows.tsx",
  "src/components/callHandlingVoiceRows.tsx",
  "src/components/callHandlingDefaults.tsx",
  "src/components/voiceButton.tsx",
  "src/components/patientCallerRow.tsx",
  "src/app/c/[slug]/TestCallStatus.tsx",
  "src/app/c/[slug]/TrialLockNotice.tsx",
  "src/app/c/[slug]/HeldNumberNotice.tsx",
  "src/app/c/[slug]/agents/actions/KindFields.tsx",
  "src/app/c/[slug]/agents/actions/BookingSetup.tsx",
  "src/app/c/[slug]/agents/actions/ParamEditor.tsx",
  "src/app/c/[slug]/agents/[agentId]/tour",
  "src/app/c/[slug]/agents/panels/openingLineFix.tsx",
  "src/app/c/[slug]/agents/[agentId]/script/ImprovementReview.tsx",
  "src/app/c/[slug]/agents/[agentId]/sections/tryIt.tsx",
  "src/app/c/[slug]/agents/[agentId]/sections/knownFacts.tsx",
  "src/lib/api/kyc.ts",
  "src/lib/api/members.ts",
  "src/lib/callReview.ts",
] as const;

/** What a person does not see without a tap, or never sees. */
const HIDDEN: Hidden = {
  elements: new Set(["InfoTip", "Disclosure", "HowItWorks", "details", "Popover", "Why", "ConfirmDialog"]),
  closedElements: new Set(["HowItWorks", "InfoTip"]),
  // `why` is a microphone dialog's text and opens on a tap; `info` is an ⓘ's body.
  attrs: /^(info|infoLabel|why|title|aria-[a-z]+|prompt|data-[a-z-]+)$/,
  // `operator` is the admin form's word for a KYC state, never shown to a client.
  props: new Set(["info", "facts", "prompt", "why", "operator"]),
  calls: new Set(["useCopilotSurface", "CopilotSurfaceScope"]),
  // The operator's KYC form check, which only the admin console renders.
  functions: new Set(["recordBlockReason"]),
  // An ⓘ's body (`*_INFO`), a request sent to Pip (`*_REQUEST`), what to try inside the
  // forwarding test's "Things to try" disclosure, and a finding's "Why?".
  constants: /(_INFO|_REQUEST)$|^(SELF_CHECKS|FINDING_WHY)$/,
};

/**
 * Kept word for word, and in view: each is a statement the person ticks to attest, so it is
 * never shortened to fit a guard.
 */
const KEPT_VERBATIM = new Set([
  "This number belongs to my business. Calevate may ring it to test the forward.",
  "This number is my own. Test calls to it can ring at any hour.",
]);

const improvement = (labels: string[]): Improvement => ({
  base: "draft",
  edits: labels.map((label, i) => ({ id: `e${i}`, op: "set_step", label, before: "", after: "", because: null, why: "" })),
  facts: [],
  for_keys: [],
  disclosure: null,
  created_at: "2026-10-28T00:00:00Z",
});

describe("the shared pieces speak in short lines", () => {
  const copy = defaultCopyUnder(SHARED, HIDDEN);

  it("reads every piece it guards", () => {
    // A walk that found nothing would pass for the wrong reason.
    for (const root of SHARED) expect(copy.some((c) => c.file.startsWith(root)), root).toBe(true);
  });

  it(`shows no default line longer than ${SHORT_LINE} characters`, () => {
    expect(longLines(copy, (text) => KEPT_VERBATIM.has(text))).toEqual([]);
  });

  it("keeps the attestations whole rather than trimmed to fit", () => {
    for (const line of KEPT_VERBATIM) expect(copy.some((c) => c.text === line), line).toBe(true);
  });

  it("measures a long sentence written as short pieces as one line", () => {
    const pieces = defaultCopyUnder(["tests/fixtures/shortCopySample.tsx"], HIDDEN);
    expect(longLines(pieces)).toEqual([
      "tests/fixtures/shortCopySample.tsx:4 (68) This sentence is split into pieces, each short, but it reads as one.",
    ]);
  });
});

describe("the shared copy tables say each state in one short line", () => {
  const short = (lines: string[]) => lines.filter((line) => line.length > SHORT_LINE);

  it("KYC states, document hints and role summaries", () => {
    expect(short(Object.values(KYC_STATUS_COPY).flatMap((c) => [c.label, c.headline, c.next]))).toEqual([]);
    expect(short(Object.values(DOCUMENT_KINDS).flatMap((d) => [d.label, d.hint]))).toEqual([]);
    expect(short(Object.values(ROLE_COPY).flatMap((r) => [r.label, r.can]))).toEqual([]);
  });

  it("business-setup steps: the line on screen, with the rest behind Why", () => {
    for (const step of STEPS) {
      expect(short([step.title, step.short, splitHint(step.hint).lead]), step.id).toEqual([]);
      expect(step.hint.length, step.id).toBeLessThanOrEqual(200);
    }
  });

  it("why a call reads the way it does", () => {
    const base = { callback_requested: false, callback: null, summary_state: "ready", status: "completed" } as const;
    const lines = [
      ...OUTCOME_ORDER.map((outcome_tag) => outcomeReason({ ...base, outcome_tag })),
      outcomeReason({ ...base, outcome_tag: "needs_you", callback_requested: true }),
      outcomeReason({ ...base, outcome_tag: "needs_you", next_step: "Confirm the visit" }),
    ];
    expect(short(lines)).toEqual([]);
  });

  it("composed lines at worst-case values", () => {
    const states = ["queued", "running", "failed", "skipped", null] as const;
    const lines = [
      ...states.flatMap((draft) => [originLine({ starting: true, draft }), originLine({ starting: false, draft })]),
      skippedNote(["e0", "e1", "e2"], improvement(["A", "B", "C"]))!.line,
      skippedNote(["e0"], improvement(["A"]))!.line,
      openingWaitsLine(10_000),
      modeSummary("conditional", 30),
      ...TOUR_STEPS.flatMap((step) => [step.title, step.body]),
    ];
    expect(short(lines)).toEqual([]);
  });
});
