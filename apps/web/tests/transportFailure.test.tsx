import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProblemNotice } from "@/components/ui";
import {
  ApiProblem,
  TimeoutProblem,
  TransportProblem,
  apiRequest,
  type Session,
} from "@/lib/api/client";
import { isUnreachable } from "@/lib/authn/problems";

import { stillLoading, stubApi } from "./harness";

/**
 * WHEN `fetch` ITSELF REJECTS — the one failure this transport used to throw away.
 *
 * Every other outcome already arrives as an `ApiProblem`: a non-2xx through `problemFrom`,
 * a breached deadline as `TimeoutProblem`, a local auth refusal as `AuthProblem`. A
 * rejected `fetch` had nothing. It reached `ProblemNotice` as a bare `TypeError`, took the
 * `problem === null` arm, and painted one generic sentence — with no kind, no reference,
 * no path and nothing written down anywhere. So the ONE class of failure where the browser
 * is the only witness was the one class that produced no evidence, which is how a live
 * write failure survived three rounds of diagnosis by inference.
 *
 * What is pinned here, and why each would be easy to lose again:
 *
 * 1. **The three rejection kinds stay three.** The browser tells us `TypeError` (the Fetch
 *    Standard's single network-error rejection) apart from an `AbortError`, and those have
 *    opposite meanings for an operator: something refused to carry the request or the
 *    reply, versus the browser abandoned it. Folding them into one loses the only
 *    discrimination we are given.
 * 2. **The two aborts that are NOT this stay out of it.** Our own deadline and a caller's
 *    `AbortSignal` both surface as `AbortError`, and `withDeadline` owns both.
 * 3. **A correlation id is minted here and SENT.** It is what turns "the box said no reply"
 *    into a grep: either the API's `request` log line carries that id or the request never
 *    arrived. Writes only — a read is re-readable, and stamping reads would buy the admin
 *    console's first `/v1/me` a preflight it does not have today.
 * 4. **The sentence names no cause and promises no outcome.** The server may have answered
 *    perfectly and had its answer withheld, so it may have DONE the thing.
 */

const SESSION: Session = { orgSlug: "acme" };

/** `fetch` rejecting, the way a browser rejects it. */
function rejectingFetch(cause: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(cause)),
  );
}

/** What a browser throws when the request could not be made or the reply not handed over. */
function networkError(): TypeError {
  return new TypeError("Failed to fetch");
}

/** The rejection, typed — every assertion below is about the thing that was thrown. */
async function failureOf(run: Promise<unknown>): Promise<TransportProblem> {
  try {
    await run;
  } catch (cause) {
    return cause as TransportProblem;
  }
  throw new Error("the request was expected to fail and did not");
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("a fetch that rejects", () => {
  it("arrives as an ApiProblem, so every screen already renders it", async () => {
    rejectingFetch(networkError());

    const error = await failureOf(
      apiRequest(SESSION, "/v1/agents", { method: "POST", body: {} }),
    );

    expect(error).toBeInstanceOf(TransportProblem);
    expect(error).toBeInstanceOf(ApiProblem);
    // `status: 0` is this app's spelling of "no HTTP response happened" — nothing here
    // claims the server said anything. It is also what `isUnreachable` reads, so the
    // sign-in surfaces keep telling a dead connection from an expired session.
    expect(error.status).toBe(0);
    expect(isUnreachable(error)).toBe(true);
  });

  it("distinguishes a blocked reply from a cancelled request, because the browser does", async () => {
    rejectingFetch(networkError());
    const blocked = await failureOf(
      apiRequest(SESSION, "/v1/agents", { method: "POST", body: {} }),
    );
    expect(blocked.reason).toBe("blocked");
    expect(blocked.code).toBe("transport_blocked");

    // An `AbortError` with NOBODY having aborted: the browser abandoned the request
    // itself — a navigation, a reload, a closed tab. Our deadline and a caller's signal
    // are the two other sources and both are handled by `withDeadline`, so what reaches
    // the classifier here can only be the browser's own.
    rejectingFetch(
      new DOMException("The user aborted a request.", "AbortError"),
    );
    const cancelled = await failureOf(
      apiRequest(SESSION, "/v1/agents", { method: "POST", body: {} }),
    );
    expect(cancelled.reason).toBe("cancelled");

    // Anything else is ADMITTED as unknown rather than guessed into one of the two above.
    rejectingFetch(new RangeError("something nobody predicted"));
    const unknown = await failureOf(
      apiRequest(SESSION, "/v1/agents", { method: "POST", body: {} }),
    );
    expect(unknown.reason).toBe("unknown");
  });

  it("carries the method and path an operator needs, and keeps the cause off the screen", async () => {
    const cause = networkError();
    rejectingFetch(cause);

    const error = await failureOf(
      apiRequest(SESSION, "/v1/kb/uploads/u-1", { method: "DELETE" }),
    );

    expect(error.request).toEqual({
      method: "DELETE",
      path: "/v1/kb/uploads/u-1",
    });
    // ATTACHED, never logged and never rendered (hard rule 6): a `TypeError`'s message
    // carries the request URL, and a URL can carry a phone number.
    expect(error.cause).toBe(cause);
    render(<ProblemNotice error={error} onRetry={() => {}} />);
    expect(screen.getByRole("alert").textContent).not.toContain(
      "/v1/kb/uploads/u-1",
    );
  });

  it("sends a correlation id on writes — the id that says whether the request arrived", async () => {
    const calls = stubApi({ "POST /v1/agents/a-1/publish": {} });

    await apiRequest(SESSION, "/v1/agents/a-1/publish", { method: "POST" });

    const sent = calls[0].headers["X-Correlation-Id"];
    // 32 hex characters, the shape `uuid.uuid4().hex` gives the API's own ids, so one log
    // search finds both halves of a request.
    expect(sent).toMatch(/^[0-9a-f]{32}$/);
  });

  it("puts that same id on the failure, where the screen shows it as the reference", async () => {
    rejectingFetch(networkError());

    const error = await failureOf(
      apiRequest(SESSION, "/v1/agents", { method: "POST", body: {} }),
    );

    expect(error.traceId).toMatch(/^[0-9a-f]{32}$/);
    render(<ProblemNotice error={error} onRetry={() => {}} />);
    // `kind: "transient"` is in `ProblemNotice`'s REFERENCE_KINDS precisely so this shows:
    // a failure only WE can look into is the case the reference exists for.
    expect(screen.getByText(error.traceId!)).toBeTruthy();
  });

  it("leaves reads unstamped, so the admin console's first /v1/me keeps its simple request", async () => {
    const calls = stubApi({ "/v1/dashboard": {} });

    await apiRequest(SESSION, "/v1/dashboard");

    expect(calls[0].headers["X-Correlation-Id"]).toBeUndefined();
  });

  it("says what it observed and nothing more", async () => {
    rejectingFetch(networkError());

    const error = await failureOf(
      apiRequest(SESSION, "/v1/agents", { method: "POST", body: {} }),
    );
    render(<ProblemNotice error={error} onRetry={() => {}} />);
    const box = screen.getByRole("alert").textContent ?? "";

    expect(box).toContain("No reply reached this page");
    // THE TWO CLAIMS IT MAY NOT MAKE. It cannot see WHY the reply was withheld — "check
    // your connection" sends a person to fix a connection that may be perfect — and it
    // cannot know whether the write landed, so it must not imply that nothing happened.
    expect(box).not.toContain("nothing was submitted");
    expect(box.startsWith("No reply")).toBe(true);
    // Retryable, which is honest and is what keeps the button the generic arm used to
    // grant unconditionally.
    expect(error.retryable).toBe(true);
    expect(screen.getByRole("button", { name: /^Try again$/ })).toBeTruthy();
  });

  it("does not steal the deadline's rejection", async () => {
    // The regression this guards: our own timeout reaches `fetch` as an `AbortError`, so a
    // classifier that ran before `withDeadline` would rewrite every timeout as
    // "cancelled" and lose the sentence that names the seconds waited.
    vi.useFakeTimers();
    stubApi({ "/v1/agents": stillLoading() });

    const pending = apiRequest(SESSION, "/v1/agents", {
      method: "POST",
      body: {},
    }).catch((cause: unknown) => cause);
    await vi.advanceTimersByTimeAsync(70_000);

    expect(await pending).toBeInstanceOf(TimeoutProblem);
  });

  it("does not steal a caller's own cancellation", async () => {
    // The other half: a cancelled request is not a failed one and must reach the caller
    // unwrapped, or a screen the user navigated away from paints a red box on the way out.
    stubApi({ "/v1/agents": stillLoading() });
    const controller = new AbortController();

    const pending = apiRequest(SESSION, "/v1/agents", {
      method: "POST",
      body: {},
      signal: controller.signal,
    }).catch((cause: unknown) => cause);
    controller.abort();

    expect(await pending).not.toBeInstanceOf(ApiProblem);
  });
});
