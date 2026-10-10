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
 *
 * The redesigned call detail reads the server's own `summary_state` and `translation_state`
 * instead of inferring from `summary`/`outcome_tag`: it re-reads every 20 s while either is
 * `pending`, and gives up 30 minutes after the call started. The fixture therefore carries
 * both states and a call that started two minutes ago, so every "does not poll" case below
 * is decided by the call's state and not, silently, by its age.
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
    started_at: new Date(Date.now() - 2 * MINUTE).toISOString(),
    duration_s: 0,
    summary: null,
    summary_state: "pending",
    translation_state: "not_needed",
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
    expect(
      await readsAfterThreeMinutes(detail({ outcome_tag: "dropped", summary_state: "empty" })),
    ).toBe(1);
  });

  it("does not poll a call that has its summary", async () => {
    expect(
      await readsAfterThreeMinutes(
        detail({ summary: "Booked a cleaning.", outcome_tag: "resolved", summary_state: "ready" }),
      ),
    ).toBe(1);
  });

  it("keeps polling a completed call whose extraction has not landed", async () => {
    expect(await readsAfterThreeMinutes(detail())).toBeGreaterThan(1);
  });

  it("keeps polling a summarised call whose English lines are still being written", async () => {
    expect(
      await readsAfterThreeMinutes(
        detail({ summary: "Booked a cleaning.", summary_state: "ready", translation_state: "pending" }),
      ),
    ).toBeGreaterThan(1);
  });

  it("stops polling a pending call half an hour after it started", async () => {
    expect(
      await readsAfterThreeMinutes(
        detail({ started_at: new Date(Date.now() - 31 * MINUTE).toISOString() }),
      ),
    ).toBe(1);
  });

  it("keeps polling a call that is still in progress", async () => {
    expect(await readsAfterThreeMinutes(detail({ status: "in_progress" }))).toBeGreaterThan(1);
  });
});
