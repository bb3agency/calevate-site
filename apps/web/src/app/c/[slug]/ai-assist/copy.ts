/**
 * The words this screen writes itself, one short line each (`tests/simpleCopyLegal.test.ts`).
 * The charge dialog's wording is the shared `AcceptChargeDialog`'s and is not here.
 */
export const AI_ASSIST_COPY = {
  refused: "AI help and its cost are limited to the account owner.",
  loadingDescription: "AI help used this month.",
  loading: "Loading this month's AI help",
  used: "AI help used",
  usedTip:
    "Rewriting summaries, answering questions about calls, preparing files for your agents. Paid by us up to your allowance.",
  noneLeft: "none left this month",
  notIncluded: "No AI help is included on your plan.",
  meterLabel: "Share of this month's included AI help used",
  meterDone: "All of this month's included AI help is used",
  prepLabel: "Preparing your files and facts",
  prepNone: "part of the amount used · nothing added",
  extraLabel: "Extra added",
  extraNone: "None",
  extraNoneHint: "Nothing extra bought this month",
  extraHint: "Taken from your calling credit",
  billedTitle: "How AI help is billed",
  rowIncluded: "Included with your plan",
  rowUsed: "Used so far",
  rowPrep: "of which, preparing your files and facts",
  rowExtra: "Extra added",
  rowLeft: "Left this month",
  neverAffected: "Calls, campaigns and leads are never affected.",
  overNothing: "Nothing is charged. What you send is still being prepared.",
  overWhy: "Mostly from preparing what you added. We'll tell you before anything changes.",

  pausedTitle: "AI help is paused right now",
  pausedTip: "Paused for everyone while we check unusually high use. It comes back on its own.",
  pausedBody: "Calls and leads carry on. Nothing has been charged.",
  finishedTitle: "This month's AI help is finished",
  finishedBody: "It starts again next month.",
  ceilingTitle: "You have used this month's included AI help",
  ceilingOff: "AI help is off until next month.",
  ceilingCarryOn: "Calls, campaigns and leads carry on as before.",
  seePrice: "See what more AI help costs",
  addedTitle: "Added",
} as const;

export const usedOf = (allowance: string): string => `used of ${allowance} this month`;
export const aboutMore = (count: string): string => `about ${count} more uses`;
export const prepJobs = (count: number, formatted: string): string =>
  `part of the amount used · ${formatted} ${count === 1 ? "job" : "jobs"}`;
export const overBy = (amount: string): string => `You have used ${amount} more than this month's allowance.`;
export const addedLine = (amount: string): string =>
  `${amount} taken from your credit. AI help is back on.`;
