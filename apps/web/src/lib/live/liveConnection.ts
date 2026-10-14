/**
 * The live change stream's client, without React (D-774): open, listen, coalesce, reconnect.
 *
 * Kept free of hooks and the DOM so its timing rules are testable with fake timers
 * (`tests/liveConnection.test.ts`); `useLiveUpdates` is the thin React wiring.
 *
 * - A burst of notes becomes ONE refetch per query: notes are gathered for `coalesceMs`
 *   from the first one and flushed together.
 * - `ready` (and `resync`) refetch every live family on screen, because nothing that
 *   changed while the stream was closed was announced to this tab.
 * - A dropped stream reconnects after a full-jitter backoff (1 s doubling to 30 s), so a
 *   restarted server is not met by every open tab in the same second. A planned close
 *   (`max_age`) reconnects at once. 401/403 stop it: the ordinary requests on screen get
 *   the same answer and the session gate deals with it.
 * - Hidden for `hiddenGraceMs`, it closes; visible again, it reopens and catches up.
 */

import { ApiProblem } from "@/lib/api/client";
import type { SseEvent } from "@/lib/copilot/sse";

import { ALL_LIVE_FAMILIES, familiesFor, isLiveTopic, type LiveTopic } from "./topics";

export interface LiveConnectionDeps {
  /** Open the stream; resolves when the server ends it, rejects on failure or abort. */
  open: (signal: AbortSignal, onEvent: (event: SseEvent) => void) => Promise<void>;
  /** Refetch every query in these families. */
  invalidate: (families: ReadonlySet<string>) => void;
  /** The stream became healthy (`ready` seen) or stopped being so. */
  onHealth: (healthy: boolean) => void;
  isVisible: () => boolean;
  random?: () => number;
  coalesceMs?: number;
  hiddenGraceMs?: number;
}

export const BACKOFF_BASE_MS = 1_000;
export const BACKOFF_MAX_MS = 30_000;
export const SESSION_ENDED_RETRY_MS = 30_000;

export class LiveConnection {
  private readonly deps: Required<LiveConnectionDeps>;
  private abort: AbortController | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private hiddenTimer: ReturnType<typeof setTimeout> | null = null;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private pending = new Set<LiveTopic>();
  private attempt = 0;
  private stopped = false;
  private blocked = false;
  private healthy = false;

  constructor(deps: LiveConnectionDeps) {
    this.deps = {
      random: Math.random,
      coalesceMs: 400,
      hiddenGraceMs: 30_000,
      ...deps,
    };
  }

  start(): void {
    this.stopped = false;
    if (this.deps.isVisible()) this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.abort?.abort();
    this.abort = null;
    this.setHealthy(false);
  }

  /** Call on `visibilitychange`. */
  visibilityChanged(): void {
    if (this.stopped) return;
    if (this.deps.isVisible()) {
      if (this.hiddenTimer) clearTimeout(this.hiddenTimer);
      this.hiddenTimer = null;
      if (this.abort === null && this.retryTimer === null) {
        this.blocked = false;
        this.attempt = 0;
        this.connect();
      }
      return;
    }
    if (this.hiddenTimer || this.abort === null) return;
    this.hiddenTimer = setTimeout(() => {
      this.hiddenTimer = null;
      this.abort?.abort();
    }, this.deps.hiddenGraceMs);
  }

  private clearTimers(): void {
    for (const timer of [this.retryTimer, this.hiddenTimer, this.flushTimer]) {
      if (timer) clearTimeout(timer);
    }
    this.retryTimer = this.hiddenTimer = this.flushTimer = null;
    this.pending.clear();
  }

  private setHealthy(next: boolean): void {
    if (next === this.healthy) return;
    this.healthy = next;
    this.deps.onHealth(next);
  }

  private note(topic: LiveTopic): void {
    this.pending.add(topic);
    if (this.flushTimer) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      const topics = [...this.pending];
      this.pending.clear();
      this.deps.invalidate(familiesFor(topics));
    }, this.deps.coalesceMs);
  }

  private catchUp(): void {
    this.pending.clear();
    if (this.flushTimer) clearTimeout(this.flushTimer);
    this.flushTimer = null;
    this.deps.invalidate(ALL_LIVE_FAMILIES);
  }

  private connect(): void {
    if (this.stopped || this.blocked) return;
    this.retryTimer = null;
    const abort = new AbortController();
    this.abort = abort;
    let closedReason: string | null = null;

    const onEvent = (event: SseEvent) => {
      if (event.event === "ready") {
        this.attempt = 0;
        this.setHealthy(true);
        this.catchUp();
        return;
      }
      if (event.event === "resync") {
        this.catchUp();
        return;
      }
      let data: unknown;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      const record = (data ?? {}) as Record<string, unknown>;
      if (event.event === "change" && isLiveTopic(record.topic)) this.note(record.topic);
      if (event.event === "closed" && typeof record.reason === "string") closedReason = record.reason;
    };

    void this.deps.open(abort.signal, onEvent).then(
      () => this.ended(abort, closedReason, null),
      (error: unknown) => this.ended(abort, closedReason, error),
    );
  }

  private ended(abort: AbortController, closedReason: string | null, error: unknown): void {
    if (this.abort === abort) this.abort = null;
    const wasHealthy = this.healthy;
    this.setHealthy(false);
    if (this.stopped || abort.signal.aborted) return;

    if (error instanceof ApiProblem && (error.status === 401 || error.status === 403)) {
      this.blocked = true;
      return;
    }
    // Polling takes over until the stream is back; refetch now so nothing waits on an
    // interval that was stretched while the stream was up.
    if (wasHealthy && closedReason !== "max_age") this.catchUp();

    let delay: number;
    if (closedReason === "max_age") {
      delay = 0;
    } else if (closedReason === "session_ended") {
      delay = SESSION_ENDED_RETRY_MS;
    } else if (error instanceof ApiProblem && error.retryAfterSeconds !== undefined) {
      delay = error.retryAfterSeconds * 1000;
    } else {
      const ceiling = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** this.attempt);
      delay = Math.round(this.deps.random() * ceiling);
      this.attempt += 1;
    }
    if (!this.deps.isVisible()) return;
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }
}
