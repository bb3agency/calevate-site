import { fireEvent, screen } from "@testing-library/react";

import BillingPage from "@/app/c/[slug]/billing/page";

import { renderClientPage, type Routes } from "./harness";

/**
 * The billing hub (`/c/[slug]/billing`), rendered on a chosen tab (D-525).
 *
 * ## Why a helper rather than a URL
 *
 * The screen reads its opening tab from `?tab=`, and `tests/setup.ts` mocks
 * `useSearchParams()` to an empty `URLSearchParams` for the whole suite. Re-mocking
 * `next/navigation` per file to smuggle a query string in would test the mock; CLICKING
 * the tab tests the tab strip, which is the thing that has to work.
 *
 * `fireEvent`, not `userEvent`: this repo takes no dependency on `@testing-library/
 * user-event` (see `vitest.config.mts` on keeping the tree small), and a tab is a button.
 *
 * ## The four routes every tab costs
 *
 * The hub reads `/v1/me`, the wallet, the wallet ledger and the pack rate card on mount,
 * whatever tab is open — the ledger because Overview needs to tell "spent everything"
 * apart from "never had anything", and the packs because the "what calls cost" explainer
 * quotes the list rate. `renderClientPage` throws on an unrouted request, deliberately, so
 * a suite that stubs only its own tab's endpoint finds out here rather than rendering an
 * error state that happens to contain the string it was looking for.
 */
export async function renderBillingHub(
  routes: Routes,
  tab?: "Overview" | "Credits" | "Transactions" | "Usage",
) {
  const rendered = await renderClientPage(
    <BillingPage params={Promise.resolve({ slug: "acme" })} />,
    routes,
  );
  if (tab !== undefined && tab !== "Overview") {
    fireEvent.click(await screen.findByRole("tab", { name: tab }));
  }
  return rendered;
}
