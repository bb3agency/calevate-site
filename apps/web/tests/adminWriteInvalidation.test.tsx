import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { adminSession, useKbDecision, useRecordKyc } from "@/lib/api/admin";
import { useReviewKyc } from "@/lib/api/kycReview";
import { useGrantCredits } from "@/lib/api/credits";
import { useReleaseNumber, useSetNumberAgent } from "@/lib/api/numbers";

import { stubApi } from "./harness";

/**
 * Which cached reads an admin write refreshes. A read under a key the write does not
 * prefix keeps showing the state before the click on the same screen.
 */

const TENANT = "0192f0aa-1111-7000-8000-000000000001";

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

describe("attaching an agent to a number", () => {
  it("refreshes the voice-platform numbers panel that names the answering agent", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/numbers/n-1/agent`]: {} });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useSetNumberAgent(TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ numberId: "n-1", agentId: "a-1" });
    });

    await waitFor(() => {
      expect(keys()).toContain(JSON.stringify(["admin", "engine-numbers", TENANT]));
    });
  });
});

describe("releasing a number", () => {
  it("refreshes the voice-platform numbers panel beside the list", async () => {
    stubApi({ [`POST /v1/admin/numbers/tenants/${TENANT}/n-1/release`]: {} });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useReleaseNumber(TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync("n-1");
    });

    await waitFor(() => {
      expect(keys()).toContain(JSON.stringify(["admin", "engine-numbers", TENANT]));
    });
  });
});

describe("a write that moves the wallet", () => {
  it("refreshes the tenant record whose minutes-left the wallet summary shows", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/credits/grants`]: {} });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useGrantCredits(adminSession(), TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        amountInr: "500",
        reason: "goodwill",
        grantRef: "G-1",
        amountConfirmation: "500",
      });
    });

    await waitFor(() => {
      expect(keys()).toEqual(
        expect.arrayContaining([
          JSON.stringify(["admin", "credits", TENANT]),
          JSON.stringify(["admin", "tenant", TENANT]),
        ]),
      );
    });
  });
});

describe("recording a KYC verification", () => {
  it("refreshes the review panel, the review queue and readiness, not only the record", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/kyc`]: { tenant_id: TENANT, status: "verified" } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useRecordKyc(TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ status: "verified" } as never);
    });

    await waitFor(() => {
      expect(keys()).toEqual(
        expect.arrayContaining([
          JSON.stringify(["admin", "tenant-kyc", TENANT]),
          JSON.stringify(["admin", "kyc-reviews"]),
          JSON.stringify(["admin", "tenant", TENANT]),
        ]),
      );
    });
  });
});

describe("a write that clears a health-board signal", () => {
  const HEALTH = JSON.stringify(["admin", "client-health"]);

  it("refreshes the board after a knowledge decision", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/kb/s-1/approve`]: {} });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useKbDecision(TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ sourceId: "s-1", decision: "approve" });
    });

    await waitFor(() => expect(keys()).toContain(HEALTH));
  });

  it("refreshes the board after a KYC review decision", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/kyc/review`]: { tenant_id: TENANT } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useReviewKyc(TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ decision: "approve" } as never);
    });

    await waitFor(() => expect(keys()).toContain(HEALTH));
  });

  it("refreshes the board after a recorded KYC verification", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/kyc`]: { tenant_id: TENANT, status: "verified" } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useRecordKyc(TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ status: "verified" } as never);
    });

    await waitFor(() => expect(keys()).toContain(HEALTH));
  });
});
