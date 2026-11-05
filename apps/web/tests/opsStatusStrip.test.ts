import { describe, expect, it } from "vitest";

import { driftFact, stuckFact } from "@/app/admin/ops/OpsStatusStrip";
import type { DeadLetterQueue, EngineDrift } from "@/lib/api/admin";

/** A7-03: the strip painted green over a stalled queue and over agents nobody checked. */

const QUEUE: DeadLetterQueue = {
  depth: 0,
  oldest_at: null,
  by_job: [],
  deferred: 0,
  stalled_pending: 0,
  oldest_pending_at: null,
  stalled_after_minutes: 27,
  held_for_release: 0,
  held_for_bulk_worker: 0,
};

const DRIFT: EngineDrift = {
  live_agents: 70,
  never_checked: 0,
  out_of_sync: 0,
  in_sync: 70,
  undetermined: 0,
  oldest_drift_at: null,
  oldest_checked_at: "2026-11-05T04:00:00Z",
};

describe("the ops status strip", () => {
  it("counts a queue that stopped moving as stuck", () => {
    expect(stuckFact({ ...QUEUE, stalled_pending: 23844 })).toEqual({ value: "23,844", tone: "warn" });
    expect(stuckFact({ ...QUEUE, depth: 2, stalled_pending: 3 })).toEqual({ value: "5", tone: "warn" });
    expect(stuckFact(QUEUE)).toEqual({ value: "0", tone: "ok" });
  });

  it("does not call a zero from a server that sent no pending count green", () => {
    const older: Partial<DeadLetterQueue> = { ...QUEUE };
    delete older.stalled_pending;
    expect(stuckFact(older as DeadLetterQueue).tone).toBe("unknown");
  });

  it("says not checked, never 0 drifted, when nothing was checked", () => {
    expect(driftFact({ ...DRIFT, never_checked: 70, in_sync: 0 })).toEqual({ value: "Not checked", tone: "unknown" });
    expect(driftFact({ ...DRIFT, never_checked: 5, in_sync: 65 })).toEqual({ value: "5 not checked", tone: "unknown" });
    expect(driftFact({ ...DRIFT, out_of_sync: 2, in_sync: 68 })).toEqual({ value: "2 drifted", tone: "warn" });
    expect(driftFact(DRIFT)).toEqual({ value: "0 drifted", tone: "ok" });
  });
});
