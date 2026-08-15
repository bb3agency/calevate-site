/**
 * The browser half of D-124: waiting out the identity mirror instead of bouncing.
 *
 * The API reconciles a missing `users` row from Clerk's Backend API, so this path is the
 * belt to that braces — it is what a founder meets when Clerk's API is unreachable and
 * the Svix webhook is the only thing left to wait for. Before the fix the answer was a
 * 401, which `apiRequest` surfaces as "sign in again"; signing in again mints another
 * valid token and reproduces it, so the person is in a loop with no exit.
 *
 * Four properties, and the last two are what stop this from becoming a blanket retry:
 * the wait happens, it is BOUNDED and ends in the server's own sentence, and it applies
 * to exactly one code — never to another 503 and never to a real 401.
 *
 * `apiRequest` is exercised directly rather than through a screen: the loop lives in the
 * transport precisely so no screen has to know about it, and rendering one would test
 * that screen's copy instead of the policy.
 */

import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiProblem, IDENTITY_MIRROR_PENDING, apiRequest, type Session } from "@/lib/api/client";

const SESSION: Session = { token: () => "dev:client:user_new", orgSlug: "" };

/** The API's refusal, exactly as `core/clerk_identity._mirror_pending` renders it. */
const MIRROR_PENDING_BODY = {
  type: `https://calevate.tech/problems/${IDENTITY_MIRROR_PENDING}`,
  title: "Your account is still being set up",
  status: 503,
  detail: "Your sign-in worked, but this account has not finished being created on our side yet.",
  kind: "transient",
  retryable: true,
  remediation: "Wait a few seconds and try again — this clears by itself. Do not sign out.",
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/problem+json" },
  });
}

/** Queue of responses, one per call, so the ORDER of attempts is what is asserted. */
function stubFetch(...responses: Response[]): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() => {
    const next = responses.shift();
    if (!next) throw new Error("apiRequest made more attempts than the test allowed for");
    return Promise.resolve(next);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/**
 * Run `work` to completion, releasing the transport's backoff timers as it waits.
 *
 * Fake timers, because the real policy sleeps 0.5s + 1s + 2s + 4s and a test that waits
 * that out is a test nobody runs. The loop advances repeatedly rather than once: each
 * `await sleep(...)` is scheduled only after the previous attempt has rejected, so a
 * single jump would fire the first timer and then block forever on the second.
 */
async function withTimersReleased<T>(work: Promise<T>): Promise<T> {
  let settled = false;
  const tracked = work.finally(() => {
    settled = true;
  });
  for (let i = 0; i < 20 && !settled; i += 1) {
    await vi.advanceTimersByTimeAsync(10_000);
  }
  return tracked;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

test("waits out the mirror and returns the answer the retry earned", async () => {
  const fetchMock = stubFetch(
    jsonResponse(503, MIRROR_PENDING_BODY),
    jsonResponse(503, MIRROR_PENDING_BODY),
    jsonResponse(200, { tenant_id: "018f-abc", slug: "sunrise-dental" }),
  );

  const created = await withTimersReleased(
    apiRequest<{ slug: string }>(SESSION, "/v1/auth/signup", { method: "POST", body: {} }),
  );

  expect(created.slug).toBe("sunrise-dental");
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

test("gives up after a bounded wait and hands over the server's own sentence", async () => {
  // Five identical refusals: the first attempt plus the four the policy allows. A sixth
  // would exhaust the queue and throw a different error, which is how this test also
  // pins the bound from above.
  const fetchMock = stubFetch(
    ...Array.from({ length: 5 }, () => jsonResponse(503, MIRROR_PENDING_BODY)),
  );

  const failure = await withTimersReleased(
    apiRequest(SESSION, "/v1/invitations/accept", { method: "POST", body: {} }).catch(
      (error: unknown) => error,
    ),
  );

  expect(fetchMock).toHaveBeenCalledTimes(5);
  expect(failure).toBeInstanceOf(ApiProblem);
  const problem = failure as ApiProblem;
  expect(problem.code).toBe(IDENTITY_MIRROR_PENDING);
  // §52: the refusal a person is left with must be actionable, and the sentence is the
  // server's — a second copy of it here is a second copy to keep in step.
  expect(problem.remediation).toContain("Do not sign out");
});

test("another transient refusal is answered at once, not waited on", async () => {
  // `signup_load_shed` is also `kind: transient` and also 503. If the loop keyed on the
  // KIND rather than the code, a business meeting a reduced-mode platform would sit
  // through four backoffs before being told to try later.
  const fetchMock = stubFetch(
    jsonResponse(503, {
      type: "https://calevate.tech/problems/signup_load_shed",
      detail: "The platform is in reduced mode and is not creating accounts.",
      kind: "transient",
      retryable: true,
    }),
  );

  const failure = await withTimersReleased(
    apiRequest(SESSION, "/v1/auth/signup", { method: "POST", body: {} }).catch(
      (error: unknown) => error,
    ),
  );

  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect((failure as ApiProblem).code).toBe("signup_load_shed");
});

test("a real 401 is still a real 401 and is never retried", async () => {
  // The whole point of the API-side change is that an unmirrored identity STOPPED being
  // a 401. A transport that retried 401s would have papered over that instead, and would
  // also replay every genuinely expired session four times before saying so.
  const fetchMock = stubFetch(
    jsonResponse(401, {
      type: "https://calevate.tech/problems/unauthorized",
      detail: "Your session is not valid. Sign in again.",
      kind: "auth",
      retryable: false,
    }),
  );

  const failure = await withTimersReleased(
    apiRequest(SESSION, "/v1/auth/signup", { method: "POST", body: {} }).catch(
      (error: unknown) => error,
    ),
  );

  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect((failure as ApiProblem).status).toBe(401);
});
