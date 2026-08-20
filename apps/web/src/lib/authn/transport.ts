/**
 * The cookie-credentialed transport for `/v1/auth/**`, and its 429 rung (D-174, §5.3).
 *
 * ## Why this is not `apiRequest`
 *
 * CLAUDE.md says `lib/api/client.ts` is the one place `fetch` appears, and the reason it
 * gives is the right one: auth headers, the org header and problem+json handling must not
 * be forgettable per screen. This module is the second and last place, because the
 * first-party auth surface has a DIFFERENT credential model and `apiRequest` cannot carry
 * both without a runtime branch on the very thing that must never branch:
 *
 * - `apiRequest` resolves a `TokenSource` and sends `Authorization: Bearer …`. There is no
 *   bearer here. The session is an `HttpOnly`, `Secure`, `__Host-`-prefixed cookie the
 *   browser attaches itself and JavaScript cannot read (AUTH-MIGRATION §6), so the
 *   credential arrives through `credentials: "include"` and through nothing else. Calling
 *   `apiRequest` would put `Bearer undefined` on the wire against an unauthenticated route.
 * - `apiRequest` sends `X-Org-Slug` on every call. `/v1/auth/**` is platform-level and
 *   tenant-free; a tenant header on a sign-in request is a claim nobody made.
 *
 * The two are closer than they were — D-177 gave `client.ts` `credentials: "include"`
 * and made its `TokenSource` optional, exactly as AUTH-MIGRATION §6 said it would — and
 * they are still two, because the two bullets above are still true: this surface sends no
 * `Authorization` and no `X-Org-Slug`, and `apiRequest` sends both. Collapsing them would
 * mean a runtime branch on the credential model inside the one function that must not
 * have one. The shared parts are SHARED rather than copied: `ApiProblem`, `problemFrom` and `readBody` all come from
 * `client.ts`, so a refusal from either transport renders through the same `ProblemNotice`
 * on every screen.
 *
 * ## Hard rule 6, in the browser
 *
 * Nothing here logs. Not a request, not a failure, not a status. Every argument this
 * module handles is an email address, a password, a one-time code or a single-use token,
 * and there is no log line worth having that is safe to write about any of them. The
 * refusals carry their own sentences to the screen; that is the whole reporting channel.
 */

import { API_BASE, ApiProblem, problemFrom, readBody, withDeadline } from "@/lib/api/client";

import { isRateLimited } from "./problems";

/**
 * One delayed retry for a 429 on a read, and how long it waits (§5.3 rung 4).
 *
 * The reference implementation's number was 1200ms with a good reason attached — rapidly
 * switching console sections bursts past a per-minute limit, and a single pause turns a
 * "something went wrong" flash into a delay nobody notices. It is kept.
 *
 * What is ADDED is `Retry-After`. The API's failure budget answers 429 with that header
 * (`apps/api/authn/throttle.py`), and guessing 1200ms when the server has stated a number
 * is throwing away the only authoritative answer. It is clamped: a server that says "wait
 * ten minutes" is telling the truth, but a transport that silently holds a request open
 * for ten minutes is indistinguishable from a hang, so anything past the cap becomes the
 * refusal instead — with the server's own sentence, which says how long to wait.
 */
const RATE_LIMIT_RETRY_MS = 1_200;
const RATE_LIMIT_RETRY_CAP_MS = 5_000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface AuthnRequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  /**
   * `Idempotency-Key`, for the two forms that must not act twice on a double submit.
   *
   * SENT, AND NOT YET HONOURED SERVER-SIDE — stated here rather than discovered later.
   * `apps/api/core/middleware.py` lists the header in the CORS allowlist and
   * `apps/api/reliability/service.py` implements the store, but `/v1/auth/**` does not
   * take the dependency, so today this header is inert on these routes. It is sent anyway
   * because the alternative is a form that has to be retrofitted at every call site the
   * day the backend takes it, and because the client-side half of the same guarantee —
   * one in-flight submit per form, below — is what actually protects the user right now.
   * Reported as a contract gap; the backend change is not this slice's to make.
   */
  idempotencyKey?: string;
  signal?: AbortSignal;
  /**
   * Private. Set by the 429 rung so it cannot fire twice, and kept as its OWN flag rather
   * than a shared attempt counter — §5.3's "one flag per retry reason, so a refresh retry
   * and a rate-limit retry cannot cancel each other".
   */
  retriedAfterRateLimit?: boolean;
}

/**
 * One call to the first-party auth API.
 *
 * The ladder, in order, and it is SHORTER than the reference's on purpose:
 *
 * 1. dispatch with the cookie;
 * 2. **429 on a GET** → one delayed retry (`Retry-After`, else 1200ms), once;
 * 3. anything else → the `ApiProblem` reaches the caller, which classifies it through
 *    `lib/authn/problems.ts`.
 *
 * ## Why there is no "refresh once and retry" rung, which §5.3's reference has
 *
 * Theirs makes sense for theirs: a short-lived access token in memory expires while the
 * refresh cookie is still good, so a 401 is routinely fixable by refreshing. **Ours has
 * no access token.** The cookie IS the session, `POST /v1/auth/{realm}/session/refresh`
 * requires a live authenticated session to work at all, and a 401 `unauthorized` means
 * the row is expired, revoked or unknown — a state no refresh can leave. A rung here
 * could only burn a request and then fail identically.
 *
 * Worse than useless, in fact, and this is the part worth writing down: refresh ROTATES,
 * and `apps/api/authn/sessions.py` documents that ours carries **no concurrency grace
 * window** — "ours rotates on PRIVILEGE CHANGE ONLY … a grace window here would buy
 * nothing and would sell a 10-second replay window for it". Presenting a superseded token
 * revokes the whole family as `reuse_detected`. A background rung that refreshed on
 * incidental 401s would be exactly the burst of parallel refreshes that reasoning rules
 * out, and its failure mode is not a retry — it is every session the person holds being
 * revoked as theft. The single-flight in `realm.ts` and the rotation barrier around it are
 * what make the one legitimate rotation caller safe; a retry rung would be a second,
 * uninvited one.
 */
export async function authnRequest<T>(
  path: string,
  options: AuthnRequestOptions = {},
): Promise<T> {
  const { method = "GET", body, idempotencyKey, signal, retriedAfterRateLimit } = options;

  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  let response: Response;
  try {
    // THE SAME DEADLINE THE OTHER TRANSPORT KEEPS, from the same constant — see
    // `client.ts::REQUEST_TIMEOUT_MS` for why the number is above nginx's rather than
    // below it. It matters at least as much here as there: every console screen sits
    // behind a session restore on this transport, so a request that never answers is not
    // one dead panel, it is a sign-in gate that spins forever with nothing to act on.
    //
    // The DEADLINE COVERS THE ROUND TRIP, and the body reads below sit outside it — which
    // is a smaller gap than it looks. A body that stalls after its headers arrived is by
    // definition a response that reached us from nginx, and nginx severs a stalled
    // upstream at `proxy_read_timeout`; the case with no ceiling of its own is the one
    // that never got that far, and that is the case this covers. Keeping the reads
    // outside also keeps the 429 rung below — which needs the `Response` in hand, then
    // sleeps, then recurses — out of a deadline it would otherwise spend its sleep
    // against. Each attempt gets its own clock, which is the correct reading of a retry.
    response = await withDeadline(
      (deadlineSignal) =>
        fetch(`${API_BASE}${path}`, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          // The whole credential. Without this the cookie is not attached cross-origin and
          // every authenticated route answers 401 — a failure that looks exactly like an
          // expired session and is not one.
          credentials: "include",
          signal: deadlineSignal,
        }),
      { signal },
    );
  } catch (cause) {
    // THE DEADLINE'S OWN REFUSAL PASSES THROUGH. `TimeoutProblem` is already an
    // `ApiProblem` carrying a sentence, a remediation and `status: 0`, so `isUnreachable`
    // reads it exactly as it reads the one below — and rewrapping it would throw away the
    // one detail that distinguishes "we waited 70 seconds" from "the connection failed".
    if (cause instanceof ApiProblem) throw cause;
    // A `fetch` that never produced a response: DNS, TLS, a dropped connection, an
    // aborted navigation. `AuthProblem`'s `status: 0` is how the rest of this app already
    // spells "no HTTP response happened", and `isUnreachable` is what reads it — which is
    // how §5.7 defect 9's conflation of a network failure with a signed-out session stays
    // impossible here. `cause` is attached rather than logged (hard rule 6).
    throw new ApiProblem(0, {
      kind: "auth",
      type: "urn:calevate:browser/authn_unreachable",
      title: "Calevate could not be reached",
      detail: "We could not reach Calevate.",
      remediation: "Check your connection and try again.",
      retryable: true,
      cause,
    });
  }

  if (!response.ok) {
    const problem = await problemFrom(response);
    const mayRetry =
      method === "GET" && isRateLimited(problem) && !retriedAfterRateLimit && !signal?.aborted;
    const delay = mayRetry ? retryDelayMs(response) : null;
    if (delay === null) throw problem;
    await sleep(delay);
    return authnRequest<T>(path, { ...options, retriedAfterRateLimit: true });
  }

  return (await readBody(response)) as T;
}

/**
 * How long the one 429 retry waits, or `null` for "do not retry — show the refusal".
 *
 * The server's `Retry-After` wins when it states something this transport can honour
 * without looking hung; **a stated delay past the cap means the retry is abandoned**,
 * not silently shortened. Shortening it would send the second request while the budget is
 * still spent, which is a second offence against the limiter that just refused, and the
 * refusal it produces carries the server's own sentence saying how long to wait — better
 * information than a spinner.
 *
 * RFC 9110 §10.2.3 allows either delta-seconds or an HTTP-date. Only the delta form is
 * read: `apps/api/authn/throttle.py` sends seconds, and the date form would need a clock
 * comparison against a server whose clock this browser has no reason to trust. An absent
 * or unparseable header falls to the default, which is the case the reference's 1200ms
 * was measured for.
 */
function retryDelayMs(response: Response): number | null {
  const header = response.headers.get("Retry-After");
  if (header === null || header.trim() === "") return RATE_LIMIT_RETRY_MS;
  const seconds = Number(header);
  if (!Number.isFinite(seconds) || seconds < 0) return RATE_LIMIT_RETRY_MS;
  const ms = seconds * 1_000;
  if (ms > RATE_LIMIT_RETRY_CAP_MS) return null;
  return Math.max(ms, RATE_LIMIT_RETRY_MS);
}
