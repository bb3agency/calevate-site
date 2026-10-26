import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Session } from "@/lib/api/client";
import { useEngineCatalogue } from "@/lib/api/engineCatalogue";
import { queryKeys, useCallBack, useCallLead } from "@/lib/api/hooks";
import { useReplaceLeadFields, useReviewLeadFieldsDraft } from "@/lib/api/leadFields";
import { useLeadSuggestions } from "@/lib/api/leadSuggestions";
import { useEditLead } from "@/lib/api/leads";
import { PATHS, useAssignNumber } from "@/lib/api/numberProvisioning";
import { OWN_NUMBERS_PATHS, useReleaseOwnNumber } from "@/lib/api/ownNumbers";
import { useApplyScript, useUndoScript } from "@/lib/api/script";
import { useMarkCallFollowUp, useMarkLeadStatus } from "@/lib/api/swipe";
import { familiesFor } from "@/lib/live/topics";

import { stubApi } from "./harness";

/**
 * Client-realm writes whose result is shown under a DIFFERENT query family from the one
 * the write's own screen reads. Each case names the screen that stayed stale.
 */

const SESSION: Session = { orgSlug: "acme" };
const AGENT = "0192f0aa-1111-7000-8000-000000000001";
const CALL = "0192f0aa-3333-7000-8000-000000000001";
const LEAD = "0192f0aa-4444-7000-8000-000000000001";

function harness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidated = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const keys = () => invalidated.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  return { client, wrapper, keys };
}

const key = (...parts: unknown[]) => JSON.stringify(parts);

async function expectInvalidated(keys: () => string[], expected: string[]) {
  await waitFor(() => expect(keys()).toEqual(expect.arrayContaining(expected)));
}

describe("a number put on or taken off an agent", () => {
  it("re-reads the roster's and the agent's number count", async () => {
    stubApi({
      [`POST ${PATHS.assign("num-1")}`]: {
        number_id: "num-1",
        agent_id: AGENT,
        bound: 1,
        released: 0,
        failed: 0,
        unsupported: 0,
      },
    });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useAssignNumber(SESSION), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ numberId: "num-1", agentId: AGENT, direction: "inbound" });
    });
    await expectInvalidated(keys, [key("agents", "acme"), key("agent", "acme")]);
  });

  it("re-reads them when an own number is released", async () => {
    stubApi({ [`POST ${OWN_NUMBERS_PATHS.release("num-1")}`]: { released: true } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useReleaseOwnNumber(SESSION), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("num-1");
    });
    await expectInvalidated(keys, [key("agents", "acme"), key("agent", "acme")]);
  });

  it("is also announced on the live stream's numbers topic", () => {
    const families = familiesFor(["numbers"]);
    expect(families).toContain("agent");
    expect(families).toContain("agents");
  });
});

describe("writes that add or mark a call", () => {
  it("marking a follow-up re-reads the calls screen's log, not only the dashboard list", async () => {
    stubApi({ [`PUT /v1/calls/${CALL}/follow-up`]: { state: "resolved" } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useMarkCallFollowUp(SESSION), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ callId: CALL, state: "resolved" });
    });
    await expectInvalidated(keys, [key("calls-log", "acme"), key("call", "acme", CALL)]);
  });

  it("calling a lead and calling back re-read the log, and the call back its own call", async () => {
    stubApi({
      [`POST /v1/leads/${LEAD}/call`]: { call_id: CALL },
      [`POST /v1/calls/${CALL}/callback`]: { call_id: CALL },
    });
    const { wrapper, keys } = harness();
    const lead = renderHook(() => useCallLead(SESSION), { wrapper });
    await act(async () => {
      await lead.result.current.mutateAsync({ leadId: LEAD, agentId: AGENT });
    });
    const back = renderHook(() => useCallBack(SESSION, CALL), { wrapper });
    await act(async () => {
      await back.result.current.mutateAsync();
    });
    await expectInvalidated(keys, [JSON.stringify(queryKeys.callsLog("acme")), key("call", "acme", CALL)]);
  });
});

describe("a lead's status or owner changed", () => {
  it("the swipe deck refreshes everything the table's own edit does, facets included", async () => {
    stubApi({ [`PATCH /v1/leads/${LEAD}`]: { id: LEAD, status: "won" } });
    const { wrapper, keys } = harness();
    const deck = renderHook(() => useMarkLeadStatus(SESSION), { wrapper });
    await act(async () => {
      await deck.result.current.mutateAsync({ leadId: LEAD, status: "won" });
    });
    const table = renderHook(() => useEditLead(SESSION), { wrapper });
    await act(async () => {
      await table.result.current.mutateAsync({ leadId: LEAD, edit: { status: "won" } });
    });
    const expected = [
      key("leads", "acme"),
      key("lead-facets", "acme"),
      key("dashboard", "acme"),
      key("lead", "acme", LEAD),
      key("lead-timeline", "acme", LEAD),
    ];
    await waitFor(() => {
      for (const one of expected) expect(keys().filter((k) => k === one)).toHaveLength(2);
    });
  });
});

describe("lead details written for more than one agent", () => {
  it("reviewing the draft and replacing the fields re-read every agent's detail", async () => {
    stubApi({
      "POST /v1/lead-fields/draft/review": { kept: [] },
      "POST /v1/lead-fields/replace": { replaced: 0 },
    });
    const { wrapper, keys } = harness();
    const review = renderHook(() => useReviewLeadFieldsDraft(SESSION), { wrapper });
    await act(async () => {
      await review.result.current.mutateAsync([]);
    });
    const replace = renderHook(() => useReplaceLeadFields(SESSION), { wrapper });
    await act(async () => {
      await replace.result.current.mutateAsync({});
    });
    await waitFor(() => expect(keys().filter((k) => k === key("agent", "acme"))).toHaveLength(2));
  });

  it("accepting a suggested field re-reads that agent's detail", async () => {
    const base = `/v1/agents/${AGENT}/lead-suggestions`;
    stubApi({
      [base]: { state: "idle", suggestions: [] },
      [`POST ${base}/s-1/accept`]: { remaining: { state: "idle", suggestions: [] } },
    });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useLeadSuggestions(SESSION, AGENT), { wrapper });
    await act(async () => {
      await result.current.accept.mutateAsync("s-1");
    });
    await expectInvalidated(keys, [key("agent", "acme", AGENT)]);
  });
});

describe("putting a staged script live, or undoing it", () => {
  it("re-reads the history, whose 'Callers hear this now' mark moved", async () => {
    stubApi({
      [`POST /v1/agents/${AGENT}/script/apply`]: { version: 3 },
      [`POST /v1/agents/${AGENT}/script/undo`]: { version: 2 },
    });
    const { wrapper, keys } = harness();
    const apply = renderHook(() => useApplyScript(SESSION, AGENT), { wrapper });
    await act(async () => {
      await apply.result.current.mutateAsync({} as never);
    });
    const undo = renderHook(() => useUndoScript(SESSION, AGENT), { wrapper });
    await act(async () => {
      await undo.result.current.mutateAsync();
    });
    await waitFor(() =>
      expect(keys().filter((k) => k === key("script-versions", "acme", AGENT))).toHaveLength(2),
    );
  });
});

describe("the voice catalogue", () => {
  it("is cached per account, because which voices are offerable is", async () => {
    stubApi({ "/v1/agents/engine-catalogue": { available: true, voices: [], models: [] } });
    const { client, wrapper } = harness();
    const one = renderHook(() => useEngineCatalogue({ orgSlug: "acme" }), { wrapper });
    await waitFor(() => expect(one.result.current.isSuccess).toBe(true));
    const other = renderHook(() => useEngineCatalogue({ orgSlug: "zenith" }), { wrapper });
    await waitFor(() => expect(other.result.current.isSuccess).toBe(true));
    const cached = client
      .getQueryCache()
      .findAll({ queryKey: ["engine-catalogue"] })
      .map((query) => JSON.stringify(query.queryKey));
    expect(cached).toHaveLength(2);
    expect(cached.some((k) => k.includes("acme"))).toBe(true);
    expect(cached.some((k) => k.includes("zenith"))).toBe(true);
  });
});
