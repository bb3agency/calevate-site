/**
 * The words this screen writes itself, one short line each. The server's verdict, each
 * blocker's reason, the drafts notice and the acceptance statement are NOT here: they are
 * server-owned (and the statement is legal text), so they are rendered as sent.
 * `tests/simpleCopyLegal.test.ts` holds every line here to the short-line budget.
 */
export const AGREEMENTS_COPY = {
  ready: "Ready to make calls",
  blocked: "Outgoing calls blocked",
  todoHeading: "Before calls can start",
  agreementsDone: "Agreements accepted",
  done: "Done",
  yourMove: "Your move",
  oursToDo: "Ours to do",
  reviewAndAccept: "Review and accept",
  seeAgreements: "See the agreements",
  verifyBusiness: "Verify your business",
  inboundFine: "Incoming calls still work.",
  nothingElse: "Nothing else is blocking calls.",
  nothingElseWhy: "A campaign can have its own checks. They show on the campaign.",
  sectionTitle: "Agreements to accept",
  sectionReadAgain: "Tap one to read it again.",
  sectionAccept: "Read each one, then accept below.",
  sectionOwner: "Only the account owner can accept.",
  drafts: "These are drafts",
  alsoTitle: "Also published",
  alsoNote: "To read only. Nothing to accept.",
  allAccepted: "All accepted.",
  allAcceptedWhy: "We will ask again if one changes in a way that needs it.",
  agreeHeading: "What you agree to",
  recordNote: "We save what you accepted, and when.",
  pending: "Saving…",
  success: "Accepted",
  noDate: "No start date yet",
} as const;

export const acceptLabel = (count: number): string =>
  `Accept ${count} agreement${count === 1 ? "" : "s"}`;

export const inForceFrom = (day: string): string => `In force from ${day}`;
