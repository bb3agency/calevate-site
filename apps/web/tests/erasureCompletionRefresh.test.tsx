import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { adminSession } from "@/lib/api/admin";
import { useTenantErasures, type TenantErasure } from "@/lib/api/erasure";

import { stubApi } from "./harness";

/**
 * The erasure worker, not the POST, marks the client erased. When the erasure read sees
 * it finish, the closure, the client and the directory must be read again, or the
 * Closing screen keeps offering "Reopen the account" for an erased client.
 */

const TENANT = "0192f0aa-1111-7000-8000-000000000009";

function erasure(status: "pending" | "completed"): TenantErasure {
  return {
    request_id: "0192f0aa-2222-7000-8000-000000000001",
    tenant_id: TENANT,
    status,
    reason: "Client asked",
    requested_at: "2026-11-24T05:00:00Z",
    completed_at: status === "completed" ? "2026-11-24T05:01:00Z" : null,
    proof: null,
    limitations: [],
  };
}

function harness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidated = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const keys = () => invalidated.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  return { client, wrapper, keys };
}

const AFTER_ERASURE = [
  JSON.stringify(["admin", "closure", TENANT]),
  JSON.stringify(["admin", "tenant", TENANT]),
  JSON.stringify(["admin", "tenants"]),
];

describe("an erasure finishing while its screen is open", () => {
  it("refreshes the closure, the client and the directory", async () => {
    let status: "pending" | "completed" = "pending";
    stubApi({ [`GET /v1/admin/tenants/${TENANT}/erasure`]: () => [erasure(status)] });
    const { client, wrapper, keys } = harness();
    const { result } = renderHook(() => useTenantErasures(adminSession(), TENANT), { wrapper });
    await waitFor(() => expect(result.current.data?.[0]?.status).toBe("pending"));
    expect(keys()).not.toEqual(expect.arrayContaining(AFTER_ERASURE));

    status = "completed";
    await act(async () => {
      await client.refetchQueries({ queryKey: ["admin", "tenant-erasure", TENANT] });
    });

    await waitFor(() => expect(keys()).toEqual(expect.arrayContaining(AFTER_ERASURE)));
  });

  it("refreshes nothing for an erasure that had already finished when the screen opened", async () => {
    stubApi({ [`GET /v1/admin/tenants/${TENANT}/erasure`]: () => [erasure("completed")] });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useTenantErasures(adminSession(), TENANT), { wrapper });
    await waitFor(() => expect(result.current.data?.[0]?.status).toBe("completed"));

    expect(keys()).toEqual([]);
  });
});
