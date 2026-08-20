import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { API_BASE } from "@/lib/api/client";
import {
  RESTORE_DEADLINE_MS,
  ROTATION_RESULT_CACHE_MS,
  createRealmAuthn,
  isSoftRestoreFailure,
} from "@/lib/authn/realm";

/**
 * The single-flight rotation, the rotation barrier, and the restore deadline (D-174).
 *
 * §5.2 and §5.4 of `docs/evidence/raghava-platform-teardown.md`, plus §5.7 defect 1 — the
 * uncleared timer, which is the one that reintroduces the bug the single-flight exists to
 * prevent.
 *
 * These run against `createRealmAuthn` directly rather than through `adminAuthn`, because
 * the module-scoped instances are shared across a whole test process and this file needs
 * a fresh, isolated realm per case. Constructing one here is not the realm sharing
 * CLAUDE.md forbids — nothing routes a REQUEST through it — and `authnSourceGuards.test.ts`
 * separately pins that the app itself constructs exactly two.
 */

const SESSION = {
  realm: "admin",
  subject_id: "0192f0aa-0000-7000-8000-000000000001",
  mfa_complete: true,
  email_verified: true,
};

interface Pending {
  path: string;
  method: string;
  resolve: (body: unknown, init?: ResponseInit) => void;
  reject: (error: Error) => void;
}

/**
 * A `fetch` stub that hands each request back so a test can settle it when it likes.
 *
 * IT HONOURS `init.signal`, because a stub that ignores it cannot be used to reason about
 * cancellation at all — and cancellation is now load-bearing on this path twice over: the
 * restore deadline aborts the read it abandoned (`realm.ts::runRestoreWithDeadline`), and
 * every request carries a deadline of its own whose timer is only cleared when the request
 * settles (`lib/api/client.ts`). A stub that swallowed the abort would leave both hanging
 * and make the leftover-timer assertions below unreadable.
 */
function deferredFetch(): Pending[] {
  const pending: Pending[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      return new Promise<Response>((resolve, reject) => {
        const signal = init?.signal;
        if (signal) {
          if (signal.aborted) reject(signal.reason);
          else signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }
        pending.push({
          path: url.startsWith(API_BASE) ? url.slice(API_BASE.length) : url,
          method: init?.method ?? "GET",
          resolve: (body, responseInit) =>
            resolve(
              new Response(JSON.stringify(body), {
                status: 200,
                headers: { "content-type": "application/json" },
                ...responseInit,
              }),
            ),
          reject,
        });
      });
    }),
  );
  return pending;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("§5.2 — the single-flight rotation", () => {
  it("collapses concurrent rotations into ONE network call", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const a = authn.rotateSession();
    const b = authn.rotateSession();
    const c = authn.rotateSession();

    // The whole point. Two concurrent rotations would send the SAME cookie; the first
    // supersedes it and the second is a replay, which `apps/api/authn/sessions.py` revokes
    // the entire family for as `reuse_detected` — with no grace window, deliberately.
    expect(pending, "concurrent rotations must not each hit the network").toHaveLength(1);

    pending[0].resolve(SESSION);
    await expect(a).resolves.toEqual(SESSION);
    await expect(b).resolves.toEqual(SESSION);
    await expect(c).resolves.toEqual(SESSION);
  });

  it("answers a rotation that arrives just after one completed from the result cache", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const first = authn.rotateSession();
    pending[0].resolve(SESSION);
    await first;

    // The gap the in-flight promise alone leaves, and the one a React Strict Mode
    // double-mount lands in on every page load in development.
    await expect(authn.rotateSession()).resolves.toEqual(SESSION);
    expect(pending, "a remount immediately after a rotation must not rotate again").toHaveLength(1);
  });

  it("rotates again once the result cache has expired", async () => {
    vi.useFakeTimers();
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const first = authn.rotateSession();
    pending[0].resolve(SESSION);
    await first;

    vi.setSystemTime(Date.now() + ROTATION_RESULT_CACHE_MS + 1);
    void authn.rotateSession();
    expect(pending, "the cache must be a short grace, not a permanent answer").toHaveLength(2);
  });

  it("a failed rotation clears the in-flight slot so the next attempt is a real one", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const first = authn.rotateSession();
    pending[0].reject(new Error("network"));
    await expect(first).rejects.toBeTruthy();

    void authn.rotateSession();
    expect(pending, "a rejected rotation must not wedge the single-flight").toHaveLength(2);
  });
});

describe("the rotation barrier — ours has no server-side grace window", () => {
  it("holds other calls until an in-flight rotation has settled", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const rotation = authn.rotateSession();
    expect(pending).toHaveLength(1);

    // Dispatched WHILE the rotation is in flight. If it went out now it would carry the
    // cookie the rotation is about to supersede, and arriving after the supersede is
    // `reuse_detected` — the victim's whole session family revoked as theft.
    const read = authn.readSession();
    await Promise.resolve();
    expect(pending, "a request must not go out while a rotation is rotating the cookie").toHaveLength(1);

    pending[0].resolve(SESSION);
    await rotation;
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1].path).toBe("/v1/auth/admin/session");
    pending[1].resolve(SESSION);
    await expect(read).resolves.toEqual(SESSION);
  });

  it("does not make a waiting request inherit the rotation's failure", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const rotation = authn.rotateSession();
    const read = authn.readSession();
    pending[0].reject(new Error("network"));
    await expect(rotation).rejects.toBeTruthy();

    // The waiter wanted the ORDERING, not the outcome. Reporting "your rotation failed"
    // on an unrelated read is neither true of it nor actionable.
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    pending[1].resolve(SESSION);
    await expect(read).resolves.toEqual(SESSION);
  });
});

describe("§5.7 defect 1 — the restore deadline leaves no timer behind", () => {
  /**
   * Theirs races the restore against a `setTimeout` that is never cleared. When the
   * restore WINS, the timer still fires fifteen seconds later and calls
   * `resetAuthSessionRestoreCache()`, which nulls `refreshInFlight` — so if a DIFFERENT
   * refresh is in flight at that instant, the single-flight invariant is broken and two
   * callers send the same single-use cookie. The bug §5.2 exists to prevent,
   * reintroduced by the timeout added to fix a different one.
   */
  it("a completed restore leaves nothing that can fire later", async () => {
    vi.useFakeTimers();
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const restore = authn.restore("session");
    // The rotation barrier makes every non-rotating call reach `fetch` a microtask late;
    // advancing by zero flushes those without moving the fake clock.
    await vi.advanceTimersByTimeAsync(0);
    pending[0].resolve(SESSION);
    await expect(restore).resolves.toEqual({ ok: true, session: SESSION });

    // Every timer the app owns, run. In the reference this is where the leaked deadline
    // fires and resets the refresh cache.
    expect(vi.getTimerCount(), "the restore deadline was not cleared when the restore won").toBe(0);
    await vi.advanceTimersByTimeAsync(RESTORE_DEADLINE_MS * 2);

    // And the proof that nothing was broken by it: a rotation started AFTER the deadline
    // would have fired still single-flights and still caches.
    const first = authn.rotateSession();
    const second = authn.rotateSession();
    expect(pending.filter((p) => p.path.endsWith("/session/refresh"))).toHaveLength(1);
    pending[1].resolve(SESSION);
    await Promise.all([first, second]);
  });

  it("a restore that times out is a SOFT failure and still clears its timer", async () => {
    vi.useFakeTimers();
    deferredFetch();
    const authn = createRealmAuthn("admin");

    const restore = authn.restore("session");
    await vi.advanceTimersByTimeAsync(RESTORE_DEADLINE_MS + 1);
    const outcome = await restore;

    expect(outcome).toEqual({ ok: false, reason: "timeout" });
    expect(isSoftRestoreFailure(outcome), "a timeout must stay retryable").toBe(true);
    // §5.4: a slow network is not a logged-out user. Nothing is blocked, so a remount or
    // a navigation tries again instead of stranding a session that is probably fine.
    expect(authn.isBlocked("session")).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("§5.4 — hard and soft failures, and the audiences that hold them", () => {
  /**
   * Await the request, then refuse it.
   *
   * The `await` is not incidental: every call except `rotateSession` goes through the
   * rotation barrier first, so the `fetch` is issued a microtask later than the call that
   * caused it. A test that resolved `pending[i]` synchronously would be asserting against
   * a request that had not been made — the same ordering subtlety `lib/api/client.ts`
   * documents about its synchronous fast path, from the other side.
   */
  const refuse = async (
    pending: Pending[],
    index: number,
    code: string,
    status = 401,
  ): Promise<void> => {
    await vi.waitFor(() => expect(pending.length).toBeGreaterThan(index));
    pending[index].resolve(
      { type: `urn:calevate:auth/${code}`, title: "no", detail: "no", kind: "auth" },
      { status, headers: { "content-type": "application/problem+json" } },
    );
  };

  it("only `unauthorized` blocks — a server error does not", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const first = authn.restore("session");
    await refuse(pending, 0, "internal", 503);
    expect(await first).toEqual({ ok: false, reason: "unreachable" });
    expect(authn.isBlocked("session"), "a 503 is not evidence the session is dead").toBe(false);

    const second = authn.restore("session");
    await refuse(pending, 1, "unauthorized");
    expect(await second).toEqual({ ok: false, reason: "signed_out" });
    expect(authn.isBlocked("session")).toBe(true);
  });

  it("a half-authenticated admin session is `partial`, not signed out", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const restore = authn.restore("session");
    await refuse(pending, 0, "second_factor_required");

    // Alive, and one route wide. Treating it as signed out would throw away a session that
    // is one code away from working; treating it as ready would render a console every
    // call of which is refused.
    expect(await restore).toEqual({ ok: false, reason: "partial" });
    expect(authn.isBlocked("session")).toBe(false);
  });

  it("a dead console session does not block the sign-in page's audience", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const consoleRestore = authn.restore("session");
    await refuse(pending, 0, "unauthorized");
    await consoleRestore;

    // §5.4's whole reason for the split: one shared `blocked` flag would mean the one
    // screen whose job is to fix a dead session is the screen the dead session disables.
    expect(authn.isBlocked("session")).toBe(true);
    expect(authn.isBlocked("guest")).toBe(false);

    const guestRestore = authn.restore("guest");
    await vi.waitFor(() =>
      expect(pending, "the guest audience must still be willing to ask").toHaveLength(2),
    );
    await refuse(pending, 1, "unauthorized");
    await guestRestore;
  });

  it("concurrent restores of one audience share a single request", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");

    const a = authn.restore("session");
    const b = authn.restore("session");
    await vi.waitFor(() => expect(pending).toHaveLength(1));
    pending[0].resolve(SESSION);
    expect(await a).toEqual(await b);
  });

  it("`reset()` bumps the generation, which is what a stale restore is checked against", () => {
    const authn = createRealmAuthn("admin");
    const before = authn.generation();
    authn.reset();
    expect(authn.generation()).toBeGreaterThan(before);
  });
});

describe("the two realms are two independent instances", () => {
  it("share no rotation cache, no restore runtime and no generation", async () => {
    const pending = deferredFetch();
    const admin = createRealmAuthn("admin");
    const client = createRealmAuthn("client");

    const adminRotation = admin.rotateSession();
    pending[0].resolve(SESSION);
    await adminRotation;
    expect(pending[0].path).toBe("/v1/auth/admin/session/refresh");

    // The client realm must not be answered from the admin realm's cache. If it were,
    // one realm's credential would be standing in for the other's — the exact hazard
    // AUTH-MIGRATION §3 is written about.
    void client.rotateSession();
    expect(pending).toHaveLength(2);
    expect(pending[1].path).toBe("/v1/auth/client/session/refresh");
  });
});

describe("§5.3 — the retry ladder", () => {
  const rateLimit = (pending: Pending, retryAfter?: string): void => {
    pending.resolve(
      {
        type: "urn:calevate:rate_limit/too_many_attempts",
        title: "Too many",
        detail: "Too many",
        kind: "rate_limit",
      },
      {
        status: 429,
        headers: {
          "content-type": "application/problem+json",
          ...(retryAfter ? { "Retry-After": retryAfter } : {}),
        },
      },
    );
  };

  it("retries a 429 on a READ exactly once, then succeeds", async () => {
    vi.useFakeTimers();
    const pending = deferredFetch();
    const authn = createRealmAuthn("client");

    const read = authn.readSession();
    await vi.advanceTimersByTimeAsync(0);
    rateLimit(pending[0]);

    // The 1200ms the reference measured: switching console sections bursts past a
    // per-minute limit, and one pause turns an error flash into an unnoticed delay.
    await vi.advanceTimersByTimeAsync(1_200);
    expect(pending).toHaveLength(2);
    pending[1].resolve(SESSION);
    await expect(read).resolves.toEqual(SESSION);
  });

  it("does not retry a second time — one flag, one retry", async () => {
    vi.useFakeTimers();
    const pending = deferredFetch();
    const authn = createRealmAuthn("client");

    const read = authn.readSession().catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(0);
    rateLimit(pending[0]);
    await vi.advanceTimersByTimeAsync(1_200);
    rateLimit(pending[1]);
    await vi.advanceTimersByTimeAsync(5_000);

    expect(pending, "a retry rung must not become a retry loop").toHaveLength(2);
    await expect(read).resolves.toBeInstanceOf(Error);
  });

  it("never retries a WRITE, however it was refused", async () => {
    vi.useFakeTimers();
    const pending = deferredFetch();
    const authn = createRealmAuthn("client");

    // A retried POST is a second attempt at an action, and the server's Idempotency-Key
    // handling — not a client guess — is what makes that safe. `/v1/auth/**` does not
    // take that dependency yet, so nothing here may retry one.
    const out = authn.requestPasswordReset("a@example.com", "key-1").catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(0);
    rateLimit(pending[0]);
    await vi.advanceTimersByTimeAsync(5_000);

    expect(pending).toHaveLength(1);
    await expect(out).resolves.toBeInstanceOf(Error);
  });

  it("honours `Retry-After`, and abandons the retry when it exceeds the cap", async () => {
    vi.useFakeTimers();
    const pending = deferredFetch();
    const authn = createRealmAuthn("client");

    const read = authn.readSession().catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(0);
    // Ten minutes. A transport that silently shortened this would send the second request
    // while the budget is still spent; one that honoured it literally would be
    // indistinguishable from a hang. It refuses instead, with the server's own sentence.
    rateLimit(pending[0], "600");
    await vi.advanceTimersByTimeAsync(30_000);

    expect(pending).toHaveLength(1);
    await expect(read).resolves.toBeInstanceOf(Error);
  });
});

describe("the transport", () => {
  let pending: Pending[];

  beforeEach(() => {
    pending = deferredFetch();
  });

  it("sends the cookie and never a bearer token", async () => {
    const authn = createRealmAuthn("client");
    void authn.readSession();
    await vi.waitFor(() => expect(pending).toHaveLength(1));

    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.credentials, "without this the cookie is not attached at all").toBe("include");
    expect(JSON.stringify(init.headers)).not.toMatch(/Authorization/i);
    expect(JSON.stringify(init.headers), "this surface is tenant-free").not.toMatch(/X-Org-Slug/i);
  });

  it("carries the Idempotency-Key on a reset request", async () => {
    const authn = createRealmAuthn("client");
    void authn.requestPasswordReset("someone@example.com", "key-1234");
    await vi.waitFor(() => expect(pending).toHaveLength(1));

    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-1234");
    // Hard rule 6: the key is a random UUID, never the address it is keyed on.
    expect(JSON.stringify(init.headers)).not.toContain("someone@example.com");
  });

  it("sends no body at all when resending the second factor (§5.7 defect 5)", async () => {
    const authn = createRealmAuthn("admin");
    void authn.resendSecondFactor();
    await vi.waitFor(() => expect(pending).toHaveLength(1));

    // The live session IS the challenge. Nothing about the password needs to survive the
    // step, which is what lets the form clear it the instant step one succeeds.
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(init.body).toBeUndefined();
  });
});
