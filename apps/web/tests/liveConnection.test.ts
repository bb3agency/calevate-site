import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProblem } from "@/lib/api/client";
import type { SseEvent } from "@/lib/copilot/sse";
import { LiveConnection, type LiveConnectionDeps } from "@/lib/live/liveConnection";
import {
  BASE_STALE_MS,
  LIVE_SAFETY_POLL_MS,
  livePoll,
  liveStaleTime,
  setLiveHealthy,
} from "@/lib/live/liveStatus";
import { ALL_LIVE_FAMILIES, STATIC_FAMILIES } from "@/lib/live/topics";

/**
 * The live stream's client rules (D-774), with fake timers: a burst is one refetch per
 * query, an open stream catches up on what it missed, a dropped one reconnects with
 * jitter and hands the feeds back to their polls, a refusal stops it, a hidden tab lets it
 * go and catches up when it comes back.
 */

type Stream = {
  emit: (event: string, data?: unknown) => void;
  end: () => void;
  fail: (error: unknown) => void;
  signal: AbortSignal;
};

function harness(overrides: Partial<LiveConnectionDeps> = {}) {
  const streams: Stream[] = [];
  const invalidations: Set<string>[] = [];
  const readBefore: (number | undefined)[] = [];
  const health: boolean[] = [];
  let visible = true;
  const deps: LiveConnectionDeps = {
    open: (signal, onEvent) =>
      new Promise<void>((resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        streams.push({
          emit: (event, data = {}) => onEvent({ event, data: JSON.stringify(data) } satisfies SseEvent),
          end: resolve,
          fail: reject,
          signal,
        });
      }),
    invalidate: (families, before) => {
      invalidations.push(new Set(families));
      readBefore.push(before);
    },
    onHealth: (healthy) => health.push(healthy),
    isVisible: () => visible,
    random: () => 0.5,
    coalesceMs: 400,
    hiddenGraceMs: 30_000,
    ...overrides,
  };
  const connection = new LiveConnection(deps);
  return {
    connection,
    streams,
    invalidations,
    readBefore,
    health,
    setVisible: (next: boolean) => {
      visible = next;
      connection.visibilityChanged();
    },
  };
}

const flush = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  setLiveHealthy(false);
});

describe("LiveConnection", () => {
  it("catches up on ready, then turns a burst of notes into one refetch", async () => {
    const h = harness();
    h.connection.start();
    expect(h.streams).toHaveLength(1);

    h.streams[0].emit("ready", { heartbeat_s: 20, max_age_s: 1800 });
    expect(h.health).toEqual([true]);
    expect(h.invalidations).toEqual([new Set(ALL_LIVE_FAMILIES)]);

    for (let i = 0; i < 25; i += 1) h.streams[0].emit("change", { topic: "calls", at: "x" });
    h.streams[0].emit("change", { topic: "wallet", at: "x" });
    h.streams[0].emit("change", { topic: "no-such-topic", at: "x" });
    expect(h.invalidations).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(400);
    expect(h.invalidations).toHaveLength(2);
    const burst = h.invalidations[1];
    expect(burst.has("calls")).toBe(true);
    expect(burst.has("wallet")).toBe(true);
    expect(burst.has("dashboard")).toBe(true);
    expect(burst.has("kb")).toBe(false);
  });

  it("on ready refetches only what was read before the stream opened", async () => {
    vi.setSystemTime(1_000_000);
    const h = harness();
    h.connection.start();
    // The page's own reads land while the stream is still opening; they are not repeated.
    await vi.advanceTimersByTimeAsync(700);
    h.streams[0].emit("ready");
    expect(h.readBefore).toEqual([1_000_000]);

    // A note restarts every read in its families, whenever it was made.
    h.streams[0].emit("change", { topic: "calls", at: "x" });
    await vi.advanceTimersByTimeAsync(400);
    expect(h.readBefore.at(-1)).toBeUndefined();

    // A resync, and a drop, cover everything: notes were lost while the tab held its data.
    h.streams[0].emit("resync", { reason: "fell_behind" });
    expect(h.readBefore.at(-1)).toBeUndefined();
    h.streams[0].fail(new Error("network"));
    await flush();
    expect(h.readBefore.at(-1)).toBeUndefined();

    // The reopened stream catches up on what was read before IT opened.
    await vi.advanceTimersByTimeAsync(500);
    expect(h.streams).toHaveLength(2);
    h.streams[1].emit("ready");
    expect(h.readBefore.at(-1)).toBe(1_001_600);
  });

  it("reconnects after a drop with jittered backoff, and refetches meanwhile", async () => {
    const h = harness();
    h.connection.start();
    h.streams[0].emit("ready");
    h.streams[0].fail(new Error("network"));
    await flush();
    expect(h.health).toEqual([true, false]);
    // Polling takes over: everything on screen refetched so no interval waits stretched.
    expect(h.invalidations).toHaveLength(2);

    // attempt 0: 0.5 * 1s
    await vi.advanceTimersByTimeAsync(499);
    expect(h.streams).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.streams).toHaveLength(2);

    // attempt 1 fails before ready: 0.5 * 2s
    h.streams[1].fail(new Error("network"));
    await flush();
    await vi.advanceTimersByTimeAsync(999);
    expect(h.streams).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.streams).toHaveLength(3);

    h.streams[2].emit("ready");
    expect(h.invalidations.at(-1)).toEqual(new Set(ALL_LIVE_FAMILIES));
  });

  it("reopens at once after the server's planned close", async () => {
    const h = harness();
    h.connection.start();
    h.streams[0].emit("ready");
    h.streams[0].emit("closed", { reason: "max_age" });
    h.streams[0].end();
    await flush();
    expect(h.streams).toHaveLength(2);
  });

  it("stops when the session is refused, and does not hammer the server", async () => {
    const h = harness();
    h.connection.start();
    h.streams[0].fail(
      new ApiProblem(401, { type: "urn:calevate:problem/unauthorized", title: "Please sign in" }),
    );
    await flush();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(h.streams).toHaveLength(1);
  });

  it("lets go while hidden and catches up when the tab comes back", async () => {
    const h = harness();
    h.connection.start();
    h.streams[0].emit("ready");
    h.setVisible(false);
    await vi.advanceTimersByTimeAsync(29_999);
    expect(h.streams[0].signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.streams[0].signal.aborted).toBe(true);
    await flush();
    expect(h.health.at(-1)).toBe(false);

    h.setVisible(true);
    expect(h.streams).toHaveLength(2);
    h.streams[1].emit("ready");
    expect(h.invalidations.at(-1)).toEqual(new Set(ALL_LIVE_FAMILIES));
  });

  it("refetches everything on resync", () => {
    const h = harness();
    h.connection.start();
    h.streams[0].emit("ready");
    h.streams[0].emit("resync", { reason: "fell_behind" });
    expect(h.invalidations).toHaveLength(2);
    expect(h.invalidations[1]).toEqual(new Set(ALL_LIVE_FAMILIES));
  });
});

describe("livePoll", () => {
  it("keeps a feed's interval while the stream is down and stretches it while it is up", () => {
    const poll = livePoll<unknown>(20_000);
    expect(poll(undefined)).toBe(20_000);
    setLiveHealthy(true);
    expect(poll(undefined)).toBe(LIVE_SAFETY_POLL_MS);
    setLiveHealthy(false);
    expect(poll(undefined)).toBe(20_000);
  });

  it("leaves a stopped poll stopped", () => {
    setLiveHealthy(true);
    expect(livePoll<unknown>(false)(undefined)).toBe(false);
    expect(livePoll<{ done: boolean }>((q) => (q.done ? false : 1_000))({ done: true })).toBe(false);
  });
});

describe("liveStaleTime", () => {
  it("keeps a live family fresh for the safety period while the stream is healthy, and nothing else", () => {
    const live = { queryKey: ["dashboard", "acme"] };
    const notCovered = { queryKey: [Object.keys(STATIC_FAMILIES)[0], "acme"] };
    expect(liveStaleTime(live)).toBe(BASE_STALE_MS);
    setLiveHealthy(true);
    expect(liveStaleTime(live)).toBe(LIVE_SAFETY_POLL_MS);
    expect(liveStaleTime(notCovered)).toBe(BASE_STALE_MS);
    setLiveHealthy(false);
    expect(liveStaleTime(live)).toBe(BASE_STALE_MS);
  });
});
