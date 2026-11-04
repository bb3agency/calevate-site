import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CreditStrip } from "@/app/c/[slug]/ClientTopHeader";

import { renderClientPage } from "./harness";
import { prepaidWallet } from "./fixtures/sharedReads";

/**
 * THE CREDIT WARNING ON A PHONE. The bar's credit chip is hidden under `sm` for want of
 * room, so on a phone the same warning is a strip with one button, on every client screen
 * but the dashboard, where "Next steps" says it already.
 */

const where = vi.hoisted(() => ({ pathname: "/c/acme/leads" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => where.pathname,
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const strip = <CreditStrip slug="acme" />;

describe("the phone credit strip", () => {
  it("says calls have stopped, with Add credit as the one button", async () => {
    where.pathname = "/c/acme/leads";
    await renderClientPage(strip, {
      "/v1/billing/wallet": prepaidWallet({ balance_inr: "0.00", is_low: true, outbound_stopped: true }),
    });
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("Calls in and out stopped");
    const action = screen.getByRole("link", { name: "Add credit" });
    expect(action.getAttribute("href")).toBe("/c/acme/billing?tab=credits");
    // Hidden from `sm` up, where the bar's chip carries it.
    expect(status.className).toContain("sm:hidden");
  });

  it("says credit is low", async () => {
    where.pathname = "/c/acme/agents";
    await renderClientPage(strip, { "/v1/billing/wallet": prepaidWallet({ is_low: true }) });
    expect((await screen.findByRole("status")).textContent).toContain("Credit is low");
  });

  it("says nothing on a healthy balance, an invoiced account, or the dashboard", async () => {
    where.pathname = "/c/acme/leads";
    const { calls, unmount } = await renderClientPage(strip, { "/v1/billing/wallet": prepaidWallet() });
    await waitFor(() => expect(calls.some((call) => call.path === "/v1/billing/wallet")).toBe(true));
    expect(screen.queryByRole("status")).toBeNull();
    unmount();

    const invoiced = await renderClientPage(strip, {
      "/v1/billing/wallet": prepaidWallet({ prepaid: false, is_low: true, outbound_stopped: true }),
    });
    await waitFor(() => expect(invoiced.calls.length).toBeGreaterThan(0));
    expect(screen.queryByRole("status")).toBeNull();
    invoiced.unmount();

    where.pathname = "/c/acme";
    const home = await renderClientPage(strip, {
      "/v1/billing/wallet": prepaidWallet({ balance_inr: "0.00", is_low: true, outbound_stopped: true }),
    });
    await waitFor(() => expect(home.calls.length).toBeGreaterThan(0));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
