import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import {
  spendSeriesPath,
  statementsPath,
  useSpendSeries,
  useStatements,
  type SpendSeries,
  type StatementList,
} from "@/lib/api/billingHistory";
import { useTeamMembers, type TeamMember } from "@/lib/api/members";

import { stubApi } from "./harness";

/**
 * The D-660 hooks the billing and team screens build on: the statement list, the daily
 * spend series and the team roster with addresses. What a screen relies on: the path and
 * query each hook sends, that paging follows `next_before`, that money stays a string, and
 * that a disabled hook makes no request.
 */

const SESSION = { orgSlug: "acme" };

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Providers({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return Providers;
}

const SERIES: SpendSeries = {
  basis: "wallet_debits",
  timezone: "Asia/Kolkata",
  from_date: "2026-09-25",
  to_date: "2026-10-01",
  days: [
    { date: "2026-09-30", calls_inr: "0.10", ai_assist_inr: "0.00", adjustments_inr: "0.00", spent_inr: "0.10" },
    { date: "2026-10-01", calls_inr: "0.20", ai_assist_inr: "0.00", adjustments_inr: "0.00", spent_inr: "0.20" },
  ],
  calls_inr: "0.30",
  ai_assist_inr: "0.00",
  adjustments_inr: "0.00",
  spent_inr: "0.30",
  by_agent: [{ agent_id: "agent-1", agent_name: "Front desk", calls_inr: "0.30" }],
};

function statementPage(months: string[], next: string | null): StatementList {
  return {
    statements: months.map((month) => ({
      month,
      closed: month !== "2026-10",
      document_type: "bill_of_supply",
      invoice_number: `CAL${month.slice(2, 4)}${month.slice(5)}abcdefghi`,
      total_inr: "0.00",
      credit_added_inr: "1000.00",
      wallet_spent_inr: "12.35",
      calls: 3,
      minutes_used: "4.50",
    })),
    next_before: next,
  };
}

describe("spendSeriesPath / statementsPath", () => {
  it("names a preset window or an inclusive range, and a cursor only when there is one", () => {
    expect(spendSeriesPath({ days: 7 })).toBe("/v1/billing/spend/daily?days=7");
    expect(spendSeriesPath({ from: "2026-09-01", to: "2026-09-30" })).toBe(
      "/v1/billing/spend/daily?from=2026-09-01&to=2026-09-30",
    );
    expect(statementsPath(6)).toBe("/v1/billing/statements?limit=6");
    expect(statementsPath(6, "2026-08")).toBe("/v1/billing/statements?limit=6&before=2026-08");
  });
});

describe("useSpendSeries", () => {
  it("reads the last 30 days by default and keeps every rupee a string", async () => {
    const calls = stubApi({ "/v1/billing/spend/daily?days=30": SERIES });
    const { result } = renderHook(() => useSpendSeries(SESSION), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls.map((c) => c.path)).toEqual(["/v1/billing/spend/daily?days=30"]);
    expect(result.current.data?.spent_inr).toBe("0.30");
    expect(typeof result.current.data?.days[0].spent_inr).toBe("string");
  });

  it("makes no request while disabled", async () => {
    const calls = stubApi({});
    renderHook(() => useSpendSeries(SESSION, { days: 7 }, { enabled: false }), {
      wrapper: wrapper(),
    });
    await act(async () => {});
    expect(calls).toHaveLength(0);
  });
});

describe("useStatements", () => {
  it("pages back by next_before and stops on the last page", async () => {
    const calls = stubApi({
      "/v1/billing/statements?limit=2": statementPage(["2026-10", "2026-09"], "2026-09"),
      "/v1/billing/statements?limit=2&before=2026-09": statementPage(["2026-08"], null),
    });
    const { result } = renderHook(() => useStatements(SESSION, { limit: 2 }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    expect(result.current.hasNextPage).toBe(false);
    expect(result.current.data?.pages.flatMap((p) => p.statements.map((s) => s.month))).toEqual([
      "2026-10",
      "2026-09",
      "2026-08",
    ]);
    expect(calls.map((c) => c.path)).toEqual([
      "/v1/billing/statements?limit=2",
      "/v1/billing/statements?limit=2&before=2026-09",
    ]);
  });

  it("never asks for more than the server's page ceiling", async () => {
    const calls = stubApi({ "/v1/billing/statements?limit=12": statementPage([], null) });
    const { result } = renderHook(() => useStatements(SESSION, { limit: 50 }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls[0].path).toBe("/v1/billing/statements?limit=12");
  });
});

describe("useTeamMembers", () => {
  it("reads the roster with addresses, and not at all for a session that cannot manage", async () => {
    const roster: TeamMember[] = [
      {
        id: "u1",
        name: "Asha",
        email: "asha@example.test",
        role: "owner",
        joined_at: "2026-09-01T04:30:00Z",
      },
    ];
    const calls = stubApi({ "/v1/team/members": roster });
    const { result } = renderHook(() => useTeamMembers(SESSION), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].email).toBe("asha@example.test");

    const none = stubApi({});
    renderHook(() => useTeamMembers(SESSION, { enabled: false }), { wrapper: wrapper() });
    await act(async () => {});
    expect(none).toHaveLength(0);
    expect(calls).toHaveLength(1);
  });
});
