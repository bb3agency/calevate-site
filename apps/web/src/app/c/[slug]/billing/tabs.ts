/**
 * The billing hub's views, and the `?tab=` vocabulary that reaches them, in one place.
 *
 * D-525 made billing ONE screen; round 2 made it a wallet header (balance, runway, Add
 * credit) above three PEER VIEWS of the account's money — Usage, Transactions, Statements —
 * switched by a SegmentedControl, which D-655 allows for peer views of the same data.
 *
 * The `?tab=` values are a link contract older than this layout: `/credits`, `/usage`,
 * `/spend` and `/invoice` redirect into them (`lib/billingRedirect.ts`), and the dashboard,
 * the launch gate and the number purchase link to `?tab=credits` and `?tab=usage`. So the
 * retired values still resolve: `credits` opens the Add credit drawer over the default
 * view, and `overview` lands on Usage, where the wallet's own panels now live.
 */
export const BILLING_VIEWS = [
  { value: "usage", label: "Usage" },
  { value: "transactions", label: "Transactions" },
  { value: "statements", label: "Statements" },
] as const;

export type BillingView = (typeof BILLING_VIEWS)[number]["value"];

export const DEFAULT_BILLING_VIEW: BillingView = "usage";

export function isBillingView(value: string | null | undefined): value is BillingView {
  return BILLING_VIEWS.some((view) => view.value === value);
}

/** What a `?tab=` value asks for: a view, and whether the Add credit drawer opens. */
export function resolveBillingTab(tab: string | null | undefined): {
  view: BillingView;
  addCredit: boolean;
} {
  if (isBillingView(tab)) return { view: tab, addCredit: false };
  return { view: DEFAULT_BILLING_VIEW, addCredit: tab === "credits" };
}
