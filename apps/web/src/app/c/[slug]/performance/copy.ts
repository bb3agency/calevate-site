/**
 * The words this screen writes itself, one short line each (`tests/simpleCopyLegal.test.ts`).
 * What each chart's figures mean stays behind its ⓘ (`PerformanceCharts.tsx`).
 */
export const PERFORMANCE_COPY = {
  refused: "You need access to call records. Ask the account owner.",
  dates: "Dates",
  testCalls: "Include my test calls",
  glance: "This period at a glance",
  loadingFigures: "Loading the figures",
  activityTitle: "Activity over time",
  activityTip: "Drag the window under the chart to look closer. India time.",
  activityEmpty: "No calls in this stretch yet.",
  activityError: "We could not load your calls over time.",
  funnelTitle: "From calls to customers",
  outcomesTitle: "How calls ended",
  busyTitle: "When it gets busy",
  busyShow: "Show",
  busyCalls: "Calls",
  busyLeads: "New leads",
  busyError: "We could not load when your calls happen.",
  lengthTitle: "How long calls last",
  lengthCompare: "Compare by",
  lengthError: "We could not load how long your calls last.",
  lengthEmpty: "No completed calls in this period.",
  funnelEmpty: "No calls in this period yet.",
  outcomesEmpty: "No call results yet.",

  periodTitle: "Day by day, week by week",
  periodNote: "India time. Weeks start on Monday.",
  periodGroup: "Group by",
  periodError: "We could not load these figures.",
  periodEmpty: "No calls or new leads in this period.",
  spendNoAccess: "Spend is shown to people who can see billing.",
  spendWholeAccount: "Spend covers the whole account.",
  spendLink: "See spend in Usage",

  groupsTitle: "Who called, and how it went",
  groupsNote: "Your own test calls are not counted.",
  groupsCountBy: "Count by",
  repeatOnly: "Only people who called more than once",
  groupsError: "We could not count these calls.",
  groupsLoading: "Counting calls",
  groupsNone: "No calls in this period.",
  groupsNoRepeat: "Nobody called more than once in this period.",
} as const;

export const periodHeadline = (range: string): string => `How your agents did, ${range}.`;
