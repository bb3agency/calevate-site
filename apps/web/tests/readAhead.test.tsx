import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Session } from "@/lib/api/client";
import { queryKeys, useCall, usePrefetchCall } from "@/lib/api/hooks";
import { useLead, usePrefetchLead } from "@/lib/api/leads";
import { HOVER_INTENT_MS, useReadAhead } from "@/lib/readAhead";

import { stubApi } from "./harness";

const SESSION: Session = { orgSlug: "acme" };
const CALL = "0192f0aa-3333-7000-8000-000000000001";
const LEAD = "0192f0aa-4444-7000-8000-000000000001";

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("reading a row's page ahead", () => {
  it("reads after a mouse settles on the row, not while it passes over", () => {
    vi.useFakeTimers();
    const read = vi.fn();
    const { result } = renderHook(() => useReadAhead(read));

    const passing = result.current("a");
    passing.onPointerEnter({ pointerType: "mouse" });
    vi.advanceTimersByTime(HOVER_INTENT_MS - 1);
    passing.onPointerLeave();
    vi.advanceTimersByTime(HOVER_INTENT_MS);
    expect(read).not.toHaveBeenCalled();

    const settling = result.current("b");
    settling.onPointerEnter({ pointerType: "mouse" });
    vi.advanceTimersByTime(HOVER_INTENT_MS);
    expect(read).toHaveBeenCalledExactlyOnceWith("b");
  });

  it("reads at once on a press or on keyboard focus", () => {
    vi.useFakeTimers();
    const read = vi.fn();
    const { result } = renderHook(() => useReadAhead(read));

    result.current("touched").onPointerEnter({ pointerType: "touch" });
    result.current("touched").onPointerDown();
    result.current("focused").onFocus();
    expect(read.mock.calls).toEqual([["touched"], ["focused"]]);
    // A touch entering the row does not also queue a delayed read.
    vi.advanceTimersByTime(HOVER_INTENT_MS * 2);
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("puts the call's page in the cache under the key the page reads, and reads it once", async () => {
    const detail = { id: CALL, status: "completed", started_at: "2026-01-01T00:00:00Z" };
    const calls = stubApi({ [`GET /v1/calls/${CALL}`]: detail });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 10_000 } } });
    const wrapper = wrapperFor(client);

    const prefetch = renderHook(() => usePrefetchCall(SESSION), { wrapper });
    act(() => prefetch.result.current(CALL));
    await waitFor(() => expect(client.getQueryData(queryKeys.call(SESSION.orgSlug, CALL))).toEqual(detail));
    act(() => prefetch.result.current(CALL));

    const page = renderHook(() => useCall(SESSION, CALL), { wrapper });
    expect(page.result.current.data).toEqual(detail);
    expect(calls.filter((call) => call.path === `/v1/calls/${CALL}`)).toHaveLength(1);
  });

  it("puts the lead's page in the cache under the key the page reads", async () => {
    const lead = { id: LEAD, name: "Ravi" };
    const calls = stubApi({ [`GET /v1/leads/${LEAD}`]: lead });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 10_000 } } });
    const wrapper = wrapperFor(client);

    const prefetch = renderHook(() => usePrefetchLead(SESSION), { wrapper });
    act(() => prefetch.result.current(LEAD));
    await waitFor(() => expect(client.getQueryData(["lead", SESSION.orgSlug, LEAD])).toEqual(lead));

    const page = renderHook(() => useLead(SESSION, LEAD), { wrapper });
    expect(page.result.current.data).toEqual(lead);
    expect(calls.filter((call) => call.path === `/v1/leads/${LEAD}`)).toHaveLength(1);
  });
});
