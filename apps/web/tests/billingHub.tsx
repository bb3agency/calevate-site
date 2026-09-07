import { fireEvent, screen } from "@testing-library/react";

import BillingPage from "@/app/c/[slug]/billing/page";
import { WALLET_LOTS_PATH } from "@/app/c/[slug]/billing/lots";

import { problem, renderClientPage, type Routes } from "./harness";

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
 * ## The five routes every tab costs, and why one of them is stubbed as a refusal
 *
 * The hub reads `/v1/me`, the wallet, the wallet ledger, the pack rate card and the LOT
 * QUEUE on mount, whatever tab is open — the ledger because Overview needs to tell "spent
 * everything" apart from "never had anything", the packs because the "what calls cost"
 * explainer quotes the rates, and the lots because the runway, the per-purchase rates and
 * the lot list are all facts about the queue rather than about the balance (D-547).
 * `renderClientPage` throws on an unrouted request, deliberately, so a suite that stubs
 * only its own tab's endpoint finds out here rather than rendering an error state that
 * happens to contain the string it was looking for.
 *
 * `GET /v1/billing/wallet/lots` is therefore given a DEFAULT of 404 that any caller may
 * override. That is not a convenience: it is the state of every API build that has not
 * shipped the route yet, and it is the state the suites about other tabs should render in
 * — no lot list, no runway pair, and emphatically no per-minute figure invented from the
 * balance. A file about lots routes it explicitly and gets the other behaviour.
 */
export async function renderBillingHub(
  routes: Routes,
  tab?: "Overview" | "Credits" | "Transactions" | "Usage",
) {
  const rendered = await renderClientPage(
    <BillingPage params={Promise.resolve({ slug: "acme" })} />,
    { [WALLET_LOTS_PATH]: problem(404, { title: "Not found" }), ...routes },
  );
  if (tab !== undefined && tab !== "Overview") {
    fireEvent.click(await screen.findByRole("tab", { name: tab }));
  }
  return rendered;
}
