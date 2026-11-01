import { act, fireEvent, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";

import BillingPage from "@/app/c/[slug]/billing/page";
import { WALLET_LOTS_PATH } from "@/app/c/[slug]/billing/lots";
import { ClientRealmProvider } from "@/lib/api/session";

import { hubUsageIdle } from "./billingHub";
import { PLATFORM_FEE_OFF, prepaidWallet, walletLots } from "./fixtures/sharedReads";
import { renderClientPage, stillLoading } from "./harness";

/**
 * `?tab=credits` while the billing screen is ALREADY open. The header's "Add credit" chip
 * and Pip link there from every screen, billing included, and a link to the open route is
 * a soft navigation that keeps the screen mounted — so a tab read once on mount left the
 * chip doing nothing on the one screen where a reader most expects it to work.
 *
 * `tests/setup.ts` mocks `useSearchParams()` to read `window.location`, so moving the
 * address and re-rendering is the soft navigation as the screen sees it.
 */

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["wallet:read", "billing:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const ROUTES = {
  [WALLET_LOTS_PATH]: walletLots(),
  ...hubUsageIdle(),
  "/v1/me": ME,
  "/v1/billing/platform-fee": PLATFORM_FEE_OFF,
  "/v1/billing/wallet": prepaidWallet(),
  "/v1/billing/wallet/ledger?limit=50": { entries: [], payments: [] },
  "/v1/billing/wallet/topups": [],
  "/v1/billing/topups/packs": stillLoading(),
};

/** One promise for every render, as Next passes: a fresh one would suspend the page again. */
const PARAMS = Promise.resolve({ slug: "acme" });

function tree(client: QueryClient) {
  return (
    <QueryClientProvider client={client}>
      <ClientRealmProvider slug="acme">
        <BillingPage params={PARAMS} />
      </ClientRealmProvider>
    </QueryClientProvider>
  );
}

afterEach(() => window.history.replaceState(null, "", "/"));

describe("a link to ?tab=credits on the open billing screen", () => {
  it("opens Add credit over the view showing, and closing it lets the next link open it again", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    // `rerender` replaces the whole root, so `tree` repeats the providers this wraps in.
    const rendered = await renderClientPage(<BillingPage params={PARAMS} />, ROUTES, "acme", client);
    fireEvent.click(await screen.findByRole("radio", { name: "Statements" }));
    expect(screen.queryByRole("dialog", { name: "Add credit" })).toBeNull();

    const follow = async (search: string) => {
      window.history.replaceState(null, "", `/c/acme/billing${search}`);
      await act(async () => rendered.rerender(tree(client)));
    };

    await follow("?tab=credits");
    expect(await screen.findByRole("dialog", { name: "Add credit" })).toBeTruthy();
    // The view under the drawer is the one the reader had open, not the default.
    expect(screen.getByRole("radio", { name: "Statements" }).getAttribute("aria-checked")).toBe("true");

    const drawer = screen.getByRole("dialog", { name: "Add credit" });
    fireEvent.click(within(drawer).getAllByRole("button", { name: /close/i })[0]);
    await act(async () => rendered.rerender(tree(client)));
    expect(screen.queryByRole("dialog", { name: "Add credit" })).toBeNull();
    expect(window.location.search).toBe("?tab=statements");

    await follow("?tab=credits");
    expect(await screen.findByRole("dialog", { name: "Add credit" })).toBeTruthy();
  });
});
