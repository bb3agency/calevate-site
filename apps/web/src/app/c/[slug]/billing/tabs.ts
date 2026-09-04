/**
 * The four tabs of the billing hub, in one place (D-525).
 *
 * They are here rather than inline in `page.tsx` because three things have to agree about
 * them and two of them are not the page: the tab strip, the `?tab=` deep link the four
 * retired routes redirect into (`/credits`, `/usage`, `/spend`, `/invoice` each land on
 * the tab that answers them), and the panel that switches on the value. A literal repeated
 * in three places is the drift this repo has a guard for elsewhere and does not need to
 * invent here.
 *
 * The VALUES are the query-string vocabulary and are deliberately machine-spelled; the
 * LABELS are what a client reads. `overview` is first because it is the default and
 * because it is the tab that answers the question the hub exists for.
 */
export const BILLING_TABS = [
  { value: "overview", label: "Overview" },
  { value: "credits", label: "Credits" },
  { value: "transactions", label: "Transactions" },
  { value: "usage", label: "Usage" },
] as const;

export type BillingTab = (typeof BILLING_TABS)[number]["value"];

/** The tab shown when nothing asked for one, and when something asked for a tab we have
 *  no panel for — a bad `?tab=` in a pasted link must land on a screen, not a blank. */
export const DEFAULT_BILLING_TAB: BillingTab = "overview";

/** Is this string one of ours? Narrows, so callers get the union rather than a cast. */
export function isBillingTab(value: string | null | undefined): value is BillingTab {
  return BILLING_TABS.some((tab) => tab.value === value);
}
