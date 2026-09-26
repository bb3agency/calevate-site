import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "@/lib/api/client";
import { useCall } from "@/lib/api/hooks";

import { stubApi, type ApiCall } from "./harness";

/**
 * A call detail page polls while the post-call pipeline can still fill it in, and stops
 * when nothing more is coming.
 *
 * It used to poll until `summary` was truthy. A `no_answer`, `busy`, `failed` or
 * `voicemail` call has no transcript and never gets one (`workers/pipeline.py` says so
 * of its own sweep), and a completed call whose transcript was empty is stored with a
 * NULL summary and `outcome_tag = 'dropped'` — so for the commonest outbound result the
 * page re-read the call every minute for as long as the tab stayed open.
 */

const SESSION: Session = { orgSlug: "acme" };
const CALL_ID = "0192f0aa-3333-7000-8000-000000000001";
const PATH = `/v1/calls/${CALL_ID}`;
const MINUTE = 60_000;

function detail(over: Record<string, unknown> = {}) {
  return {
    id: CALL_ID,
    agent_id: "0192f0aa-3333-7000-8000-0000000000a1",
    agent_name: "Reception",
    direction: "outbound",
    status: "completed",
    caller_e164: null,
    started_at: "2026-09-26T04:00:00Z",
    duration_s: 0,
    summary: null,
    sentiment: null,
    outcome_tag: null,
    lead_id: null,
    extraction: {},
    extraction_valid: true,
    extraction_needs_review: {},
    has_recording: false,
    disclosure_played: null,
    moments: [],
    transcript: [],
    ...over,
  };
}

function reads(calls: ApiCall[]): number {
  return calls.filter((call) => call.method === "GET" && call.path === PATH).length;
}

async function readsAfterThreeMinutes(answer: Record<string, unknown>): Promise<number> {
  const calls = stubApi({ [PATH]: answer });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Probe() {
    useCall(SESSION, CALL_ID);
    return null;
  }
  render(
    <QueryClientProvider client={client}>
      <Probe />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(reads(calls)).toBe(1));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3 * MINUTE + 1_000);
  });
  return reads(calls);
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("how long a call detail keeps polling", () => {
  it.each(["no_answer", "busy", "failed", "voicemail"])(
    "does not poll a %s call, which will never get a summary",
    async (status) => {
      expect(await readsAfterThreeMinutes(detail({ status }))).toBe(1);
    },
  );

  it("does not poll a completed call the pipeline has already read", async () => {
    // An empty transcript: no summary, but the reading is in.
    expect(await readsAfterThreeMinutes(detail({ outcome_tag: "dropped" }))).toBe(1);
  });

  it("does not poll a call that has its summary", async () => {
    expect(
      await readsAfterThreeMinutes(detail({ summary: "Booked a cleaning.", outcome_tag: "resolved" })),
    ).toBe(1);
  });

  it("keeps polling a completed call whose extraction has not landed", async () => {
    expect(await readsAfterThreeMinutes(detail())).toBeGreaterThan(1);
  });

  it("keeps polling a call that is still in progress", async () => {
    expect(await readsAfterThreeMinutes(detail({ status: "in_progress" }))).toBeGreaterThan(1);
  });
});
