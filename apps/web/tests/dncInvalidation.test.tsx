import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Session } from "@/lib/api/client";
import { refreshAfterConfirm } from "@/lib/api/copilot";
import {
  DNC_DEPENDENT_KEYS,
  useAddDncNumbers,
  useRemoveDncEntry,
  useRestoreDncEntry,
} from "@/lib/api/dnc";

import { noContent, stubApi } from "./harness";

/**
 * A change to the suppression list moves the campaign launch check (its "dialable" count
 * excludes listed numbers) and the leads surfaces, not only the list. The screen's own
 * add, remove and restore used to refresh the list alone while Pip's confirmed `dnc_add`
 * refreshed more — and neither refreshed `campaign-check` — so the same change left
 * different screens stale depending on which door it came through.
 */

const SESSION: Session = { orgSlug: "acme" };
const ENTRY = "0192f0aa-2222-7000-8000-000000000009";

function harness(): { client: QueryClient; keys: unknown[][]; wrapper: (p: { children: ReactNode }) => ReactNode } {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const keys: unknown[][] = [];
  const original = client.invalidateQueries.bind(client);
  vi.spyOn(client, "invalidateQueries").mockImplementation((filters, options) => {
    keys.push([...((filters?.queryKey as unknown[] | undefined) ?? [])]);
    return original(filters, options);
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, keys, wrapper };
}

const EXPECTED = DNC_DEPENDENT_KEYS.map((key) => [...key, "acme"]);

describe("a do-not-call change refreshes every read it moves", () => {
  it("covers the campaign launch check", () => {
    expect(DNC_DEPENDENT_KEYS).toContainEqual(["campaign-check"]);
    expect(DNC_DEPENDENT_KEYS).toContainEqual(["dnc"]);
  });

  it("on add", async () => {
    stubApi({ "POST /v1/dnc": { added: 1, already_suppressed: 0, malformed: 0 } });
    const { keys, wrapper } = harness();
    const { result } = renderHook(() => useAddDncNumbers(SESSION), { wrapper });
    await act(() => result.current.mutateAsync({ numbers: ["9876543210"], source: "manual" }));
    expect(keys).toEqual(EXPECTED);
  });

  it("on remove", async () => {
    stubApi({ [`DELETE /v1/dnc/${ENTRY}`]: noContent() });
    const { keys, wrapper } = harness();
    const { result } = renderHook(() => useRemoveDncEntry(SESSION), { wrapper });
    await act(() => result.current.mutateAsync(ENTRY));
    expect(keys).toEqual(EXPECTED);
  });

  it("on restore", async () => {
    stubApi({ [`POST /v1/dnc/${ENTRY}/restore`]: noContent() });
    const { keys, wrapper } = harness();
    const { result } = renderHook(() => useRestoreDncEntry(SESSION), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        entryId: ENTRY,
        ground: "never_asked",
        note: null,
        latestEvidenceId: null,
      }),
    );
    expect(keys).toEqual(EXPECTED);
  });

  it.each(["dnc_add", "dnc_remove"])("on Pip's confirmed %s, the same keys", (tool) => {
    const { client, keys } = harness();
    refreshAfterConfirm(client, "acme", tool);
    expect(keys).toEqual(EXPECTED);
  });
});
