import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useCancelCallback } from "@/lib/api/callbacks";
import { useEditLead } from "@/lib/api/leads";
import type { Session } from "@/lib/api/client";
import { familiesFor } from "@/lib/live/topics";

import { stubApi } from "./harness";

/**
 * A call row and a call's page say what its booked call back came to, and a lead says when
 * its next one is; all three are read through `scheduled_callbacks`. When a call back is
 * called off, placed or settled they must re-read, or "Call back booked" stays on a call
 * whose call back was cancelled.
 */

const SESSION: Session = { orgSlug: "acme" };
const ID = "0192f0aa-3333-7000-8000-000000000003";

describe("calling off a call-back", () => {
  it("re-reads the calls and leads that show it", async () => {
    stubApi({ [`DELETE /v1/callbacks/${ID}`]: { id: ID, status: "cancelled" } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidated = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useCancelCallback(SESSION), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(ID);
    });

    await waitFor(() => {
      const keys = invalidated.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
      expect(keys).toEqual(
        expect.arrayContaining(
          [["call", "acme"], ["calls", "acme"], ["calls-log", "acme"], ["lead", "acme"], ["leads", "acme"]].map(
            (key) => JSON.stringify(key),
          ),
        ),
      );
    });
  });
});

describe("renaming a lead", () => {
  it("re-reads the calls that name the caller from it", async () => {
    stubApi({ "PATCH /v1/leads/l1": { id: "l1", name: "Ravi" } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidated = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useEditLead(SESSION), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ leadId: "l1", edit: { name: "Ravi" } });
    });

    const keys = invalidated.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    for (const family of ["call", "calls", "calls-log"]) {
      expect(keys).toContain(JSON.stringify([family, "acme"]));
    }
  });

  // `leads` announces `leads`, and a teammate's rename reaches this screen as a note.
  it("is a live note the call log refetches on", () => {
    const families = familiesFor(["leads"]);
    for (const family of ["call", "calls", "calls-log"]) {
      expect(families).toContain(family);
    }
  });
});

describe("a live note about call-backs", () => {
  // `scheduled_callbacks` announces `callbacks` (apps/api/live/topics.py); the dispatch tick
  // moves rows with no screen open.
  it("refetches the calls and leads that read them", () => {
    const families = familiesFor(["callbacks"]);
    for (const family of ["call", "calls", "calls-log", "lead", "leads"]) {
      expect(families).toContain(family);
    }
  });
});
