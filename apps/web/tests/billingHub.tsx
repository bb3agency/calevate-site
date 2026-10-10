import { fireEvent, screen } from "@testing-library/react";

import BillingPage from "@/app/c/[slug]/billing/page";
import { WALLET_LOTS_PATH } from "@/app/c/[slug]/billing/lots";
import { spendSeriesPath, statementsPath } from "@/lib/api/billingHistory";

import { PLATFORM_FEE_OFF, walletLots } from "./fixtures/sharedReads";
import { renderClientPage, stillLoading, type Routes } from "./harness";

/**
 * The billing hub (`/c/[slug]/billing`), rendered on a chosen view.
 *
 * ## Why a helper rather than a URL
 *
 * The screen reads its opening view from `?tab=`, and `tests/setup.ts` mocks
 * `useSearchParams()` to an empty `URLSearchParams` for the whole suite. Re-mocking
 * `next/navigation` per file to smuggle a query string in would test the mock; CLICKING
 * the control tests the control, which is the thing that has to work.
 *
 * Since the round-2 redesign the hub is a wallet header over three peer views on a
 * SegmentedControl (D-525, D-655): "Usage" (the default), "Transactions" and
 * "Statements" are radios, and "Credits" is the Add credit drawer the header's primary
 * button opens. "Overview" is the default view — the wallet panels it held now sit at the
 * foot of Usage — so it clicks nothing.
 *
 * ## The routes every view costs, and why some have defaults
 *
 * The hub reads `/v1/me`, the wallet, the ledger, the pack rate card and the LOT QUEUE on
 * mount whatever view is open, and the default Usage view also reads the month's usage,
 * the spending limit, the month's per-agent breakdown and the daily series. An unrouted
 * request fails the test (`unansweredRoutes.ts`), so each of those has a DEFAULT any caller
 * may override:
 *
 * - the lot queue answers one open lot (`walletLots()`);
 * - the five Usage reads NEVER ANSWER (`stillLoading()`). A suite about the wallet then
 *   meets skeletons where the month's figures would be — never a ₹0.00 it did not ask for,
 *   which several wallet assertions ("never a zero") would otherwise trip over. A suite
 *   about usage routes them itself, exactly as it always has.
 */
export const HUB_SPEND_ROUTE = `/v1/billing/spend?month=${encodeURIComponent(
  new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }).slice(0, 7),
)}`;
export const HUB_STATEMENTS_ROUTE = statementsPath(6);
export const HUB_SPEND_SERIES_ROUTE = spendSeriesPath({ days: 30 });

/** The five Usage-view reads, never answering — for a suite that renders the hub itself. */
export function hubUsageIdle(): Routes {
  return {
    "/v1/usage": stillLoading(),
    "/v1/billing/caps": stillLoading(),
    [HUB_SPEND_ROUTE]: stillLoading(),
    [HUB_STATEMENTS_ROUTE]: stillLoading(),
    [HUB_SPEND_SERIES_ROUTE]: stillLoading(),
    // The auto-recharge card on the Overview (D-699); its own suite answers these.
    "/v1/billing/auto-recharge": stillLoading(),
    "/v1/billing/auto-recharge/charges?limit=20": stillLoading(),
    // The monthly platform fee card (D-707), switched off: it renders nothing.
    "/v1/billing/platform-fee": PLATFORM_FEE_OFF,
  };
}

export async function renderBillingHub(
  routes: Routes,
  view?: "Overview" | "Credits" | "Transactions" | "Usage" | "Statements",
) {
  const rendered = await renderClientPage(
    <BillingPage params={Promise.resolve({ slug: "acme" })} />,
    {
      [WALLET_LOTS_PATH]: walletLots(),
      ...hubUsageIdle(),
      ...routes,
    },
  );
  if (view === "Credits") {
    fireEvent.click(await screen.findByRole("button", { name: "Add credit" }));
    // The drawer is portalled to <body>, outside the render container, so a suite reading
    // `container.textContent` on the Credits view reads the whole document instead.
    return { ...rendered, container: document.body };
  } else if (view !== undefined && view !== "Overview" && view !== "Usage") {
    fireEvent.click(await screen.findByRole("radio", { name: view }));
  }
  return rendered;
}
