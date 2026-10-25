import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Session } from "@/lib/api/client";
import { useAcceptPledge, useSubmitForReview } from "@/lib/api/verifyBusiness";
import { familiesFor } from "@/lib/live/topics";

import { stubApi } from "./harness";

/**
 * The agreements screen, a campaign's launch check and the number-purchase step each ask
 * the server whether the account may dial, and the answer reads the KYC record and the
 * pledge. A write to either must re-read them, or they keep refusing after the fix.
 */

const SESSION: Session = { orgSlug: "acme" };

function harness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidated = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const keys = () => invalidated.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  return { wrapper, keys };
}

describe("accepting the no-cold-calls pledge", () => {
  it("re-reads the agreements screen and the launch check, which list the pledge", async () => {
    stubApi({
      "POST /v1/compliance/outbound-pledge": { version: 2, text_sha256: "x", is_current: true },
    });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useAcceptPledge(SESSION), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ version: 2, text_sha256: "x" });
    });

    await waitFor(() => {
      expect(keys()).toEqual(
        expect.arrayContaining([
          JSON.stringify(["legal-readiness", "acme"]),
          JSON.stringify(["campaign-check", "acme"]),
        ]),
      );
    });
  });
});

describe("sending the business for review", () => {
  it("re-reads every gate that waits on a verified business", async () => {
    stubApi({ "POST /v1/compliance/kyc/submit": { status: "pending" } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useSubmitForReview(SESSION), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({} as never);
    });

    await waitFor(() => {
      expect(keys()).toEqual(
        expect.arrayContaining([
          JSON.stringify(["kyc", "acme"]),
          JSON.stringify(["legal-readiness", "acme"]),
          JSON.stringify(["campaign-check", "acme"]),
          JSON.stringify(["own-numbers", "acme", "status"]),
        ]),
      );
    });
  });
});

describe("live notes about the account and campaigns", () => {
  // `kyc_records`, `organizations` and `tenant_trials` announce `account`;
  // `outbound_pledge_acceptances` announces `campaigns` (apps/api/live/topics.py).
  it("refetch the launch check and number-purchase step when KYC or payment moves", () => {
    const families = familiesFor(["account"]);
    expect(families).toContain("campaign-check");
    expect(families).toContain("admin/campaign-check");
    expect(families).toContain("own-numbers");
  });

  it("refetch the agreements screen when the pledge moves", () => {
    expect(familiesFor(["campaigns"])).toContain("legal-readiness");
  });

  // `credit_lots`, `spend_state`, `payment_disputes` and `monthly_fee_*` announce `wallet`:
  // the no_credits, spend_cap, payment_dispute and platform-fee blockers.
  it("refetch the outbound blockers when the wallet moves", () => {
    const families = familiesFor(["wallet"]);
    expect(families).toContain("legal-readiness");
    expect(families).toContain("campaign-check");
    expect(families).toContain("admin/campaign-check");
  });

  it("refetch the launch check when the campaign's agent moves", () => {
    const families = familiesFor(["agents"]);
    expect(families).toContain("campaign-check");
    expect(families).toContain("admin/campaign-check");
  });
});
