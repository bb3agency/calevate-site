/**
 * The writes this screen can open, one drawer at a time. A row's menu passes the row it
 * was opened from, so the act opens with that row pre-selected.
 */
export type Act =
  | { kind: "choose" }
  | { kind: "record" }
  | { kind: "correct"; entryId?: string }
  | { kind: "restate"; paymentRef?: string }
  | { kind: "refund"; paymentRef?: string }
  | { kind: "grant" }
  | { kind: "reprice"; lotId?: string };

/** The drawer title for each act — the same words the old panels carried as headings. */
export const ACT_TITLE: Record<Act["kind"], string> = {
  choose: "Fix or adjust",
  record: "Record a payment",
  correct: "Correct a wrong entry",
  restate: "A payment was for more than we recorded",
  refund: "Refund a payment",
  grant: "Give this client credit",
  reprice: "Sell a lot at another pack's rates",
};
