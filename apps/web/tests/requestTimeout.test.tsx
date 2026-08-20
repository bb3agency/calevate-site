import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProblemNotice } from "@/components/ui";
import {
  ApiProblem,
  AuthProblem,
  REQUEST_TIMEOUT_MS,
  TimeoutProblem,
  apiRequest,
  type Session,
} from "@/lib/api/client";
import { signInMessage } from "@/lib/authn/problems";
import { authnRequest } from "@/lib/authn/transport";

import { stillLoading, stubApi } from "./harness";

/**
 * THE REQUEST DEADLINE — the one thing standing between a hung connection and a skeleton
 * that spins until the tab is closed.
 *
 * `fetch` has no timeout of its own and TanStack Query adds none, so before this the app
 * had NOWHERE that stopped waiting: a request that never answered produced no error, no
 * sentence and no way forward except a reload. Every assertion below is about the moment
 * the waiting ends and what the person is told when it does.
 *
 * What is deliberately pinned, and why each would be easy to break:
 *
 * 1. **The value, from both sides.** 70s is above nginx's `proxy_read_timeout 60s` ON
 *    PURPOSE — anything that reached nginx already fails at ~60s with a real status the
 *    app can render the server's own words from, and a shorter client cap would replace
 *    every one of those with this file's generic sentence. A future reader "tidying" it to
 *    30s is the predicted regression, so the number is asserted from below as well as
 *    above rather than merely named.
 * 2. **It arrives as a sentence, in the app's ONE failure shape.** A bare `AbortError`
 *    type-checks fine and renders as "Something went wrong", which is the outcome this
 *    whole change exists to avoid.
 * 3. **A caller's own cancellation is not a timeout.** They are opposite events — one is
 *    a failure to report, the other is a request nobody wants any more — and a transport
 *    that conflates them shows a refusal for a screen the user navigated away from.
 * 4. **Both transports have it.** `lib/authn/transport.ts` is the app's other `fetch`, and
 *    it is the one every console screen sits behind: a hung session restore is not one
 *    dead panel, it is a sign-in gate that never resolves.
 */

const SESSION: Session = { orgSlug: "acme" };

afterEach(() => {
  vi.useRealTimers();
});

describe("the request deadline", () => {
  it("stops waiting at 70s — not before, and not never", async () => {
    vi.useFakeTimers();
    stubApi({ "/v1/dashboard": stillLoading() });

    const pending = apiRequest(SESSION, "/v1/dashboard");
    // A rejection nobody is attached to yet is an unhandled rejection; this settles that
    // and lets the assertions read the outcome rather than racing it.
    const outcome = pending.then(
      () => "resolved" as const,
      (error: unknown) => error,
    );

    // ONE MILLISECOND SHORT. This is the half that fails if someone lowers the ceiling:
    // a 30s cap would already have fired here, taking the informative nginx error with it.
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1);
    expect(await Promise.race([outcome, Promise.resolve("still waiting")])).toBe(
      "still waiting",
    );

    await vi.advanceTimersByTimeAsync(1);
    expect(await outcome).toBeInstanceOf(TimeoutProblem);
  });

  it("is above nginx's proxy_read_timeout, which is the whole reason for the number", () => {
    // `infra/nginx/snippets/calevate-proxy.conf` — `proxy_read_timeout 60s`. Anything that
    // REACHES nginx therefore ends with a status the app can render the server's own
    // sentence from, and this deadline exists only for the connection that never got that
    // far. Asserted as the relationship rather than as a literal, because the literal is
    // meaningless without the number it has to sit above.
    const NGINX_PROXY_READ_TIMEOUT_MS = 60_000;
    expect(REQUEST_TIMEOUT_MS).toBeGreaterThan(NGINX_PROXY_READ_TIMEOUT_MS);
    // …and comfortably above the longest request this app legitimately makes:
    // `POST /v1/calls/{id}/assist`, bounded by `EXTRACTION_TIMEOUT_S = 30.0`.
    expect(REQUEST_TIMEOUT_MS).toBeGreaterThan(30_000);
  });

  it("takes a per-request override, so a tighter cap is one line at the call site", async () => {
    stubApi({ "/v1/dashboard": stillLoading() });

    // Real timers and a tiny budget: the override is the mechanism a measured route would
    // use, and exercising it here is what keeps it from rotting unused.
    await expect(apiRequest(SESSION, "/v1/dashboard", { timeoutMs: 5 })).rejects.toBeInstanceOf(
      TimeoutProblem,
    );
  });

  it("reaches the screen as a sentence with a remediation and a way forward", async () => {
    // The DEFAULT budget, not a shortened one: the sentence names the seconds waited, so
    // an override would test copy no user will ever read.
    vi.useFakeTimers();
    stubApi({ "/v1/dashboard": stillLoading() });

    const pending = apiRequest(SESSION, "/v1/dashboard").catch((cause: unknown) => cause);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    const error = await pending;

    // It wears the API's own error shape, so every screen already renders it. `status: 0`
    // is this app's spelling of "no HTTP response happened" — nothing here claims the
    // server said anything.
    expect(error).toBeInstanceOf(ApiProblem);
    expect((error as ApiProblem).status).toBe(0);
    expect((error as ApiProblem).code).toBe("request_timeout");
    // Retryable, which is honest and is also what puts the button back: a request that ran
    // out of time is the most retryable failure there is.
    expect((error as ApiProblem).retryable).toBe(true);

    render(<ProblemNotice error={error} onRetry={() => {}} />);
    // The sentence a person can act on — the seconds waited, said in words, not an
    // `AbortError` and not "Something went wrong".
    expect(screen.getByRole("alert").textContent).toContain("did not answer within 70 seconds");
    expect(screen.getByText("Check your connection and try again.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Try again$/ })).toBeTruthy();
    // WHAT IT MUST NOT SAY. We stopped listening; we did not stop the server. A POST that
    // timed out may have been completed and charged for — which is exactly why
    // `useCallAssist` holds its `Idempotency-Key` across the retry this button offers.
    expect(screen.getByRole("alert").textContent).not.toContain("nothing was submitted");

    // AND THE SAME RULE ON THE SIGN-IN SURFACES, which have their own copy ladder. A
    // timeout is `isUnreachable` (both are `status: 0`), so without an explicit arm it
    // inherits the connection-failure sentence — which ends "nothing was submitted" and
    // would be a flat claim about a password POST the server may well have processed.
    // `null` sends it to `ProblemNotice` instead, i.e. to the box asserted just above.
    expect(signInMessage(error)).toBeNull();
    // The neighbouring case still gets its sentence, so this is an exception and not a
    // hole: a connection that never opened really did submit nothing.
    expect(signInMessage(new AuthProblem("authn_unreachable", "d", "r"))).toContain(
      "nothing was submitted",
    );
  });

  it("reports a caller's own cancellation as theirs, never as a timeout", async () => {
    stubApi({ "/v1/dashboard": stillLoading() });

    const canceller = new AbortController();
    const pending = apiRequest(SESSION, "/v1/dashboard", { signal: canceller.signal });
    const outcome = pending.catch((cause: unknown) => cause);
    canceller.abort();

    // A cancelled request is not a failed one. Rendering it as a refusal would put an
    // error on a screen the person has already left.
    expect(await outcome).not.toBeInstanceOf(TimeoutProblem);
    expect((await outcome as Error).name).toBe("AbortError");
  });

  it("covers the auth transport too, where a hang is the whole console", async () => {
    vi.useFakeTimers();
    stubApi({ "GET /v1/auth/client/session": stillLoading() });

    // The SAME constant, which is the point: one deadline for the app, not one per
    // transport. `authnRequest` takes no budget of its own — it shares `client.ts`'s.
    const outcome = authnRequest("/v1/auth/client/session").catch((cause: unknown) => cause);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);

    // Without the deadline this promise never settles at all, which is the state a session
    // gate cannot recover from. It settles, and as the timeout's own problem — not
    // rewrapped as the generic "could not be reached", which would throw away the one
    // detail that says we waited rather than failed to connect.
    expect(await outcome).toBeInstanceOf(TimeoutProblem);
  });
});
