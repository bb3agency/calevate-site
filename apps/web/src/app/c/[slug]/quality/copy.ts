/**
 * The words this screen writes itself, one short line each (`tests/simpleCopyLegal.test.ts`).
 * The headline is the defect count, not the pass rate (`scripts/qa_report.py`).
 */
export const QUALITY_COPY = {
  description: "Practice calls we run on your agent. No real calls.",
  descriptionTip:
    "Before any change to your agent, we replay a fixed set of practice calls and check what it did. Nothing comes from a real call.",
  monthPicker: "Choose a month",
  loading: "Loading your quality reports",
  failed: "Your quality reports could not be loaded",
  failedBody: "This does not mean there are none.",
  retry: "Try again",
  emptyTitle: "No quality report yet",
  emptyBody: "It appears after our first test run.",

  fixing: "We are fixing these. The report will be reissued.",
  problems: "Defects found",
  captured: "Everything captured",
  blank: "Detail left blank",
  blankHint: "Missed, not wrong",
  blankTip: "A blank field is a detail the agent did not pick up, listed below. Nothing was recorded wrongly.",
  sinceLast: "Since last month:",
  noChange: "no change to report.",

  testedTitle: "What we tested",
  trickyTip:
    "Callers trying to skip the recording notice, get another customer's details, ignore an opt-out, or plant false leads.",
  colTests: "What it tests",
  colCount: "Tests",
  colMeaning: "What a pass means",
  tableLabel: "Practice calls replayed against your agent",

  limitsTitle: "Known limits",
  limitsNone: "None. Every detail was captured.",
  limitsIntro: "These come back blank, never wrong.",
  limitsWhy: "Your team can follow up a blank detail. A wrong one they cannot.",
  colDetail: "Detail",
  colMissed: "Missed in",
  limitsLabel: "Details the agent does not yet reliably pick up",

  defectTitle: "What counts as a defect",
  defectSubtitle: "Wrong, invented or exposed details; a missed notice.",
  notTitle: "What this report does not tell you",
  notSubtitle: "Not your live calls. No real call data. No trend yet.",
} as const;

export const verdictLine = (problems: number, total: number): string =>
  problems === 0
    ? `No defects found across ${total} scenarios`
    : `${problems} of ${total} scenarios found a defect`;

export const monthEnding = (day: string): string => `For the month ending ${day}`;

export const tricky = (count: number): string => `${count} of these are trick calls`;
