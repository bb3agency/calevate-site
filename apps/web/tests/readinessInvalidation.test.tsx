import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { READINESS_PATH, useAgreementsReadiness } from "@/lib/api/agreements";
import { useLaunchCheck } from "@/lib/api/campaigns";
import { useSetCaps } from "@/lib/api/caps";
import type { Session } from "@/lib/api/client";
import { PATHS, useAssignNumber } from "@/lib/api/numberProvisioning";

import { stubApi, type ApiCall } from "./harness";

/**
 * Writes on OTHER screens that move the outbound readiness verdict.
 *
 * `GET /v1/legal/readiness` (`legal/readiness.readiness_rows`) composes the spend cap
 * among its blockers, and the layout keeps it mounted for the nav badge with a 60-second
 * `staleTime`. So a write that moves a predicate and does not invalidate these keys leaves
 * the agreements screen, opened straight afterwards, asserting the state before the write:
 *
 * - putting a number on an agent re-reads readiness, so the screen never shows the account
 *   as it stood before the binding;
 * - raising a spending limit clears `spend_cap`, while the screen and the campaign's
 *   launch check still say outbound is stopped by it.
 */

const SESSION: Session = { orgSlug: "acme" };
const CAMPAIGN_ID = "0192f0aa-2222-7000-8000-000000000001";
const CHECK_PATH = `/v1/campaigns/${CAMPAIGN_ID}/launch-check`;

const ROUTES = {
  [READINESS_PATH]: { documents: [], blockers: [], outstanding_documents: 0 },
  [CHECK_PATH]: { ok: true, blockers: [] },
  [`POST ${PATHS.assign("num-1")}`]: {
    number_id: "num-1",
    agent_id: "agent-1",
    bound: 1,
    released: 0,
    failed: 0,
    unsupported: 0,
  },
  "PUT /v1/billing/caps": { capped: false },
};

function gets(calls: ApiCall[], path: string): number {
  return calls.filter((call) => call.method === "GET" && call.path === path).length;
}

function mountWith(useWrite: () => { mutate: (input: never) => void }) {
  const calls = stubApi(ROUTES);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  let write!: { mutate: (input: never) => void };

  function Probe() {
    useAgreementsReadiness(SESSION);
    useLaunchCheck(SESSION, CAMPAIGN_ID);
    write = useWrite();
    return null;
  }

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }

  render(
    <Wrapper>
      <Probe />
    </Wrapper>,
  );

  return {
    calls,
    fire: async (input?: unknown) => {
      for (const path of [READINESS_PATH, CHECK_PATH]) {
        await waitFor(() => expect(gets(calls, path)).toBe(1));
      }
      await act(async () => {
        write.mutate(input as never);
      });
    },
  };
}

describe("putting a number on an agent", () => {
  const assign = { numberId: "num-1", agentId: "agent-1", direction: "both" };

  it("re-reads readiness", async () => {
    const { calls, fire } = mountWith(() => useAssignNumber(SESSION));
    await fire(assign);
    await waitFor(() => expect(gets(calls, READINESS_PATH)).toBe(2));
  });
});

describe("changing the spending limit", () => {
  const caps = { capMinutes: null, capSpendInr: "90000.00" };

  it("re-reads readiness, whose spend-cap blocker the new limit sets or clears", async () => {
    const { calls, fire } = mountWith(() => useSetCaps(SESSION));
    await fire(caps);
    await waitFor(() => expect(gets(calls, READINESS_PATH)).toBe(2));
  });

  it("re-reads the campaign launch check, which refuses on the same cap", async () => {
    const { calls, fire } = mountWith(() => useSetCaps(SESSION));
    await fire(caps);
    await waitFor(() => expect(gets(calls, CHECK_PATH)).toBe(2));
  });
});
