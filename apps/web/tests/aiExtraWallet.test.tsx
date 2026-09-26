import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useBuyAiExtra } from "@/lib/api/aiQuota";
import type { Session } from "@/lib/api/client";
import { useWallet } from "@/lib/api/wallet";

import { stubApi, type ApiCall } from "./harness";

/**
 * Buying more AI help debits the prepaid WALLET (`billing/ai_quota_routes.py`, a
 * `credit_ledger` debit), and the balance a client reads is `GET /v1/billing/wallet` —
 * on the dashboard tile and the billing screen, both of which the assistant dock is open
 * over. The purchase used to refresh only `/v1/usage`, so the balance beside the dock kept
 * the figure from before the debit.
 */

const SESSION: Session = { orgSlug: "acme" };
const WALLET = "/v1/billing/wallet";

function gets(calls: ApiCall[], path: string): number {
  return calls.filter((call) => call.method === "GET" && call.path === path).length;
}

describe("buying more AI help", () => {
  it("re-reads the wallet it just debited", async () => {
    const calls = stubApi({
      [WALLET]: { balance_inr: "1200.00" },
      "POST /v1/billing/ai-quota/extra": { month: "2026-09" },
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    let buy!: ReturnType<typeof useBuyAiExtra>;
    function Probe() {
      useWallet(SESSION);
      buy = useBuyAiExtra(SESSION);
      return null;
    }
    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(gets(calls, WALLET)).toBe(1));
    await act(async () => {
      buy.mutate("199.00");
    });
    await waitFor(() => expect(gets(calls, WALLET)).toBe(2));
  });
});
