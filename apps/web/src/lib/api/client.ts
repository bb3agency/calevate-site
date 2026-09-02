/**
 * The ONE way the frontend talks to the API.
 *
 * CLAUDE.md conventions: "typed client generated from OpenAPI; TanStack Query; no
 * ad-hoc fetch". This module is the seam that makes the second half enforceable — it
 * is the only place `fetch` appears, so auth headers, the org header and problem+json
 * handling cannot be forgotten one screen at a time.
 *
 * Errors are RFC-9457 (BACKEND-PATTERNS §3). `ApiProblem` preserves `kind`,
 * `retryable`, `remediation` and `fields`, so a screen can decide what to render —
 * a field-level message, a retry button, or an explanation — instead of showing a
 * generic "something went wrong" for all of them.
 */

import { AUTH_MODE_ENV, IS_PRODUCTION_BUILD } from "@/lib/authn/mode";

import type { components } from "./schema";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * A problem+json string, or nothing — where "nothing" includes the empty string.
 *
 * Every field this reads is prose destined for a screen, and a blank one is not a
 * sentence: it is the ABSENCE of one, and must fall through to whatever the caller has
 * to say instead. Treating `""` as a value is how a refusal reaches a client with no
 * words in it (see the constructor).
 */
function text(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed === "" ? undefined : trimmed;
}

export class ApiProblem extends Error {
  readonly status: number;
  readonly kind: string;
  readonly code: string;
  readonly retryable: boolean;
  readonly remediation?: string;
  readonly fields?: { field: string; rule: string; message: string }[];
  readonly traceId?: string;

  constructor(status: number, body: Record<string, unknown>) {
    // `??` alone was not enough and the gap only opened in production: `??` falls
    // through `null`/`undefined` and NOT through `""`, so a body carrying an empty
    // `detail` — which is what `problemFrom`'s fallback produced over HTTP/2, see below
    // — became an `Error` whose message was the empty string, and `ProblemNotice`
    // rendered a red box with no words in it.
    super(text(body.detail) ?? text(body.title) ?? "We could not finish that.");
    this.name = "ApiProblem";
    this.status = status;
    this.kind = text(body.kind) ?? "internal";
    // `type` is a URL whose last segment is the stable machine code. `"".split("/").pop()`
    // is `""`, not `undefined`, so the fallback beside it never fired on a body with no
    // `type` and callers comparing `code` met an empty string instead of "unknown".
    this.code = text(String(body.type ?? "").split("/").pop()) ?? "unknown";
    this.retryable = Boolean(body.retryable);
    this.remediation = text(body.remediation);
    this.fields = body.fields as ApiProblem["fields"];
    this.traceId = text(body.trace_id);
  }
}

/**
 * A refusal this browser produced itself, wearing the API's error shape.
 *
 * Auth can fail before any request leaves: an admin session built with no view-as grant
 * (below), or a local `dev:` token source that throws because there is no signed-in
 * subject to name. Those are the failures a user is least able to interpret, so they
 * must arrive with a sentence and a remediation — which is exactly what `ProblemNotice`
 * already renders, from `ApiProblem`, on every screen in the app. Inventing a second
 * error shape would mean teaching twenty screens about it.
 *
 * The examples here used to be Clerk's — "the deployment names Clerk but carries no
 * publishable key, Clerk never loaded". There is no identity vendor since D-177 and
 * therefore no vendor script to fail to load; the class survives because the causes
 * above are still local refusals wearing the API's shape.
 *
 * `status: 0` is the honest part: it is the conventional "no HTTP response happened"
 * (XHR's `status` for a request that never completed), so nothing here claims the
 * server said anything. `retryable: false` follows from the causes — a missing
 * environment variable does not fix itself on a second attempt — and keeps both the
 * retry button (`ProblemNotice`) and the query retry policy (`app/providers.tsx`) off.
 */
export class AuthProblem extends ApiProblem {
  constructor(code: string, detail: string, remediation: string) {
    super(0, {
      kind: "auth",
      // `ApiProblem` reads the last path segment of `type` as the machine code, so this
      // keeps `error.code` usable by callers the same way a server problem would.
      type: `urn:calevate:browser/${code}`,
      title: "You are not signed in",
      detail,
      remediation,
      retryable: false,
    });
    this.name = "AuthProblem";
  }
}

/**
 * HOW LONG THE BROWSER WAITS BEFORE IT STOPS WAITING — and why the number is ABOVE
 * nginx's rather than below it, which is the part a future reader will want to "fix".
 *
 * There was no deadline anywhere in this transport and `fetch` has none of its own, so a
 * request that never answered left a skeleton spinning forever with nothing on screen a
 * person could act on. That is the failure this closes.
 *
 * **70s is deliberately LONGER than `proxy_read_timeout 60s`**
 * (`infra/nginx/snippets/calevate-proxy.conf`), and inverting them would make the product
 * worse, not safer. Any request that REACHES nginx already ends at ~60s with a real status
 * — a 504 carrying a problem body, or at worst a status line `problemFrom` can render a
 * sentence from. A 30s client cap would pre-empt every one of those and replace the
 * server's own explanation with this file's generic one. The genuinely unbounded case is
 * the connection that never reaches nginx AT ALL — DNS that never resolves, a captive
 * portal that swallows the SYN, a socket a sleeping laptop left open — and 70s is what
 * bounds exactly that, leaving nginx's more informative answer first in every case where
 * there is one.
 *
 * It fits the longest legitimate request with room to spare: `POST /v1/calls/{id}/assist`
 * is bounded by `EXTRACTION_TIMEOUT_S = 30.0` (`apps/workers/extraction.py`) plus request
 * overhead, so nothing this app legitimately asks for is cut off by either ceiling.
 *
 * A tighter cap on ONE route is `{ timeoutMs }` at that call site — see `RequestOptions`.
 * Measurement can justify one; taste cannot, and lowering THIS value is the change that
 * silently costs every route its informative error.
 */
export const REQUEST_TIMEOUT_MS = 70_000;

/**
 * The deadline above, having been reached — as the `ApiProblem` every screen renders.
 *
 * `AuthProblem`'s shape and for its reason: a failure the browser produced itself still
 * has to arrive as a sentence with a remediation, because `ProblemNotice` is the only
 * failure channel these screens have. Without it a timeout surfaces as a bare
 * `DOMException: AbortError`, which `ProblemNotice` can only render as "Something went
 * wrong" — the generic message this deadline exists to avoid producing.
 *
 * `retryable: true` is what puts the "Try again" button back, and it is honest: unlike
 * `AuthProblem`'s causes, a request that ran out of time is the most retryable failure
 * there is (`ProblemNotice` makes the same argument for errors that never reached the API
 * at all). It also lets the query retry policy in `app/providers.tsx` have another go,
 * which is right for a read; mutations never auto-retry there.
 *
 * WHAT IT DELIBERATELY DOES NOT SAY is that nothing happened. We stopped listening; we did
 * not stop the server. A POST that timed out may well have been completed and charged for,
 * which is the entire reason `useCallAssist` holds its `Idempotency-Key` across a retry —
 * a reassuring sentence here would be a claim this transport cannot make.
 */
export class TimeoutProblem extends ApiProblem {
  constructor(timeoutMs: number) {
    super(0, {
      kind: "transient",
      type: "urn:calevate:browser/request_timeout",
      title: "Calevate did not answer in time",
      // `Math.max(1, …)` so a sub-second budget — which only a test has a reason to set —
      // cannot produce "did not answer within 0 seconds", a sentence that reads as a bug
      // report rather than as an explanation.
      detail: `Calevate did not answer within ${Math.max(1, Math.round(timeoutMs / 1000))} seconds, so we stopped waiting.`,
      remediation: "Check your connection and try again.",
      retryable: true,
    });
    this.name = "TimeoutProblem";
  }
}

/**
 * Run one network exchange under a deadline, and turn a breached one into a sentence.
 *
 * EXPORTED because `lib/authn/transport.ts` is the one other place this app calls `fetch`,
 * and it needs the same deadline for the same reason. `ApiProblem`, `problemFrom` and
 * `readBody` are already shared with it rather than copied; this is the fourth, and two
 * spellings of "stop waiting after a while" is exactly the drift that rule prevents.
 *
 * ## Why an `AbortController` of our own, rather than `AbortSignal.timeout()`
 *
 * The standard spelling would be `AbortSignal.any([signal, AbortSignal.timeout(ms)])`, and
 * it is the right default when nothing better is needed. Two things are bought by not
 * using it here, and neither is style:
 *
 * - **We know WHICH deadline fired without inspecting the rejection.** `AbortSignal.timeout`
 *   is told apart from a caller's abort by sniffing `err.name === "TimeoutError"` on
 *   whatever the fetch implementation chose to reject with. The flag below is set by the
 *   only line that can set it, so a fetch that rejects with a plain `AbortError` — or with
 *   anything at all — still produces the right problem for the right cause.
 * - **A caller's own abort stays the caller's.** It is forwarded with `signal.reason`
 *   intact and reaches them unwrapped, because a cancelled request is not a failed one and
 *   must not render as a refusal.
 *
 * The listener is removed rather than left to `{ once: true }`: a caller may hold ONE
 * long-lived signal across many requests, and a listener per request on it is a leak that
 * grows with session length.
 */
export async function withDeadline<T>(
  run: (signal: AbortSignal) => Promise<T>,
  { timeoutMs = REQUEST_TIMEOUT_MS, signal }: { timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<T> {
  const deadline = new AbortController();
  let expired = false;
  const timer = setTimeout(() => {
    expired = true;
    deadline.abort();
  }, timeoutMs);
  const forwardCallerAbort = () => deadline.abort(signal?.reason);
  if (signal) {
    // An ALREADY-aborted signal never fires `abort` again, so the listener alone would
    // let a cancelled request go out.
    if (signal.aborted) forwardCallerAbort();
    else signal.addEventListener("abort", forwardCallerAbort);
  }
  try {
    return await run(deadline.signal);
  } catch (cause) {
    if (expired) throw new TimeoutProblem(timeoutMs);
    throw cause;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forwardCallerAbort);
  }
}

/**
 * How `apiRequest` obtains the bearer credential for ONE call.
 *
 * A function, and asked per request rather than captured when the session object was
 * built. That shape was chosen for a vendor token that expired every sixty seconds and
 * is KEPT for `GrantSource` below, which still has one — a view-as grant expires in
 * minutes and re-mints transparently, and the dashboard polls every twenty seconds, so
 * "a console tab left open over lunch" is the normal case here rather than an edge. One
 * shape for both credentials the transport carries, so neither can be the one somebody
 * cached.
 *
 * SINCE D-177 THERE IS NO TOKEN ON THE DEPLOYED PATH AT ALL: the credential is the
 * realm's `HttpOnly` `__Host-` cookie the browser attaches itself (see `Session.token`
 * below), and this source is present only locally, where it hands back
 * `dev:<realm>:<id>` with no round trip.
 *
 * **The union is deliberate: a credential that is already known is returned, not
 * promised.** The local `dev:<realm>:<id>` token needs no round trip, and making it
 * `async` anyway would push the `fetch` call one microtask later than the request that
 * caused it — which is observable. It showed up immediately: tests that wait for the
 * screen to settle and then inspect the requests began to race, because the request was
 * no longer issued synchronously with the query that asked for it. Ordering is behaviour
 * here, so the fast path stays synchronous instead of the assertions being taught to
 * wait for an implementation detail.
 *
 * It can also THROW — synchronously or as a rejection — and callers must let it: see
 * `AuthProblem`.
 */
export type TokenSource = () => string | Promise<string>;

/**
 * How `apiRequest` obtains the D-22 view-as grant for ONE call.
 *
 * The same shape as `TokenSource`, and for the same reason rather than by imitation: a
 * grant is short-lived (`core/impersonation.py::GRANT_TTL`), so a string captured when
 * the session object was built would be stale on a console tab left open — which is the
 * normal case here, not an edge. Asked per request, the grant module can hand back the
 * cached one and silently re-mint when it is close to expiring.
 */
export type GrantSource = () => string | Promise<string>;

/**
 * Session context the API needs on every call.
 *
 * `token` is OPTIONAL and absent is the deployed case (D-177). The credential is the
 * realm's `HttpOnly`, `__Host-`-prefixed session cookie, which the browser attaches
 * itself through `credentials: "include"` and which no script on the page can read; there
 * is nothing for this file to fetch, cache or expire. It is present only on the local
 * path, where it is `dev:<realm>:<subject-uuid>` — see `core/auth.py`, which accepts that
 * shape only when `APP_ENV=local` AND the deployment holds no `PLATFORM_KEK`. Which one a
 * given realm builds is decided in `lib/authn/realmSessions.ts`, never here: this file is
 * the transport and knows nothing about realms.
 */
export interface Session {
  token?: TokenSource;
  orgSlug: string;
  /**
   * Admin realm only (D-22): WHICH tenant this read-only "view as client" session is
   * for. Addressing, not authority — `impersonationGrant` is the authority, and the API
   * refuses the pair when only this half is present.
   */
  impersonateOrg?: string;
  /**
   * Admin realm only (D-22): the signed grant authorising `impersonateOrg`.
   *
   * Required whenever `impersonateOrg` is set. It is a separate field rather than being
   * folded into `token` because it is not a credential: it never replaces the operator's
   * own admin-realm token, it only says which tenant that token may enter. Built by
   * `lib/api/admin.ts::viewAsSession`, which is the only place either field is set.
   */
  impersonationGrant?: GrantSource;
}

/**
 * The LOCAL credential, for one realm — the second guard described in `lib/authn/mode.ts`.
 *
 * `lib/authn/mode.ts` already refuses to resolve `"dev"` in a production build. This
 * checks the same fact again, at the moment the credential would be handed to `fetch`,
 * because the two guards protect against different mistakes: the first against a
 * misconfigured deployment, this one against a future refactor that reaches the dev
 * builder by some path that skipped the mode. A dev token is worth a full account
 * takeover on any API still running with `APP_ENV=local`, so it gets belt and braces.
 */
export function devToken(realm: "client" | "admin", subjectId: string): TokenSource {
  return () => {
    if (IS_PRODUCTION_BUILD) {
      throw new AuthProblem(
        "dev_token_refused",
        "This build asked for a local development token, which is never valid here.",
        `Set ${AUTH_MODE_ENV}=session — the deployed credential is the session cookie.`,
      );
    }
    return `dev:${realm}:${subjectId}`;
  };
}

/**
 * The client realm's LOCAL session. Kept as the local path (never removed, never
 * "temporarily" reachable in production): `lib/authn/realmSessions.ts` selects it when
 * `AUTH_MODE` is `dev`, and the whole frontend test suite runs through it.
 */
export function devSession(orgSlug: string): Session {
  const user = process.env.NEXT_PUBLIC_DEV_USER ?? "user_local";
  return { token: devToken("client", user), orgSlug };
}

// PUT is here for `/v1/billing/caps`, which states the WHOLE client-side pair of
// spending limits in one body — `null` on a field clears that side. PATCH would need a
// third state ("leave this one alone") that JSON makes easy to send by accident.
type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

interface RequestOptions {
  method?: Method;
  body?: unknown;
  /** Required by the API on any endpoint that can place a call or spend money. */
  idempotencyKey?: string;
  /**
   * Step-up confirmation (BACKEND-PATTERNS §7): the header must echo the action
   * being taken, e.g. `halt_outbound`. Only the ops surface needs it, but it lives
   * here so that surface does not need a `fetch` of its own — a hand-rolled call
   * loses problem+json parsing, and the big red switch is the last place that
   * should answer a refusal with a wall of raw JSON.
   */
  confirmAction?: string;
  /**
   * RFC 9110 §13.1.1 precondition: the entity-tag this write believes it is replacing.
   *
   * Sent verbatim, quotes included, exactly as the read handed it over — an entity-tag is
   * opaque and nothing outside the issuing module may parse a meaning out of it
   * (`apps/api/core/platform_config.etag_for`). It lives here beside `confirmAction` for
   * the same reason that one does: a surface that needed it would otherwise hand-roll a
   * `fetch` and lose problem+json parsing, and the 412 this header produces is the one
   * response on `/v1/ops/config` an operator most needs rendered rather than dumped.
   *
   * `/v1/ops/config` requires it on every PUT and DELETE and answers 428 without it
   * (`ops/config_routes.require_if_match`), which is what makes it a transport concern
   * rather than one screen's option.
   */
  ifMatch?: string;
  signal?: AbortSignal;
  /**
   * A tighter deadline than `REQUEST_TIMEOUT_MS` for THIS request — one line at the call
   * site, which is the point of it being an option rather than a constant.
   *
   * Deliberately a per-request override and not a per-route table: a table would be a
   * second place to keep in step with the routes, and the only reason to shorten a
   * deadline is a measurement of that one endpoint, which belongs beside the endpoint.
   * Raising it above the default is almost always wrong — nginx severs at 60s, so a
   * client waiting longer is waiting for a socket nobody is writing to.
   */
  timeoutMs?: number;
}

/**
 * THE `identity_mirror_pending` RETRY RUNG WAS HERE, AND IT IS GONE (D-177).
 *
 * It waited out a race that no longer exists: Clerk minted a session the instant an
 * account existed and sent the browser straight back to us, while the `user.created`
 * webhook travelled out of band — so `/signup` and `/invite`, the first thirty seconds of
 * every customer's and every colleague's life in the product, raced it. The API answered
 * `503 identity_mirror_pending` when it could not reconcile, and this transport spent four
 * extra attempts at 0.5s/1s/2s/4s before handing the refusal to a screen.
 *
 * There is no upstream to be behind now. A credential names a `users` row we issued, in
 * the same transaction that issued the session, so the state this rung existed for cannot
 * arise — and a retry loop for a code no server can produce is a wait nobody can trigger
 * and nobody can test.
 *
 * WORTH RECORDING RATHER THAN JUST DELETING, because the argument it carried is the one a
 * future retry rung has to meet: retrying a POST is against `app/providers.tsx`'s
 * `mutations: { retry: false }`, and it was permissible for this ONE code only because the
 * refusal came from the auth dependency, before any handler body ran, so a refused request
 * had provably executed nothing. Any future exception needs that same proof.
 */
export async function apiRequest<T>(
  session: Session,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  return sendRequest<T>(session, path, options);
}

async function sendRequest<T>(
  session: Session,
  path: string,
  {
    method = "GET",
    body,
    idempotencyKey,
    confirmAction,
    ifMatch,
    signal,
    timeoutMs,
  }: RequestOptions = {},
): Promise<T> {
  // Resolved HERE, per call, rather than when the session object was built. The `await`
  // is skipped when the source already has the string, so a local request still reaches
  // `fetch` in the same tick as the query that asked for it. If it throws, the throw
  // propagates: an `AuthProblem` reaching the screen as an error is the point, and
  // catching it to send the request anyway would put `Bearer undefined` on the wire.
  //
  // NO SOURCE IS THE DEPLOYED CASE and it sends NO header rather than an empty one: the
  // session cookie below is the credential, and `Authorization: Bearer ` would be a
  // malformed credential the API is obliged to refuse before it looks at the cookie.
  const requested = session.token?.();
  const token = typeof requested === "string" ? requested : await requested;

  const headers: Record<string, string> = {};
  // CONDITIONAL, for the reason the token above is: a request with no account named sends
  // NO header rather than an empty one. `/v1/me` answers a client with exactly one
  // membership without being told which account (`core/auth._load_client_principal`), and
  // that is what lets `/c` resolve "my console" for somebody who has just signed in and
  // does not know their own slug yet. `X-Org-Slug: ` would be a named account that does
  // not exist, refused before the API looks at the membership.
  //
  // Bracket notation, like the four below: `tests/cors_contract_test.py` reads this file
  // for every header name a request can carry and checks the API's CORS allowlist admits
  // it, and it knows two spellings — the object literal and a bracket assignment.
  if (session.orgSlug) headers["X-Org-Slug"] = session.orgSlug;
  // BRACKET NOTATION, deliberately, and it is the same shape as the four conditional
  // headers below rather than a style choice: `tests/cors_contract_test.py` reads this
  // file for every header name it can put on a request and checks the API's CORS
  // allowlist admits each one. It knows two spellings — the object literal above and a
  // bracket assignment — and a header written in a third would be one the browser sends
  // and the preflight rejects, which is invisible to curl and fatal in a browser.
  if (token !== undefined) headers["Authorization"] = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  if (confirmAction) headers["X-Confirm-Action"] = confirmAction;
  if (ifMatch) headers["If-Match"] = ifMatch;
  if (session.impersonateOrg) {
    // FAIL CLOSED ON THIS SIDE TOO. The API refuses `X-Impersonate-Org` without a grant
    // (`core/auth.py::_load_admin_principal`), so sending the org header alone can only
    // produce a 403 — and a 403 with no local explanation is how a broken seam gets
    // diagnosed as "the API is down". A session built without a grant source is a
    // programming error in this app, so it says so, in the shape every screen already
    // renders (`ProblemNotice`), before anything reaches the network.
    if (!session.impersonationGrant) {
      throw new AuthProblem(
        "impersonation_grant_missing",
        "This screen tried to view a client account without a view-as grant.",
        "Build the session with viewAsSession() (lib/api/admin.ts), which mints one.",
      );
    }
    headers["X-Impersonate-Org"] = session.impersonateOrg;
    // Resolved HERE, per call, like the bearer token above and for the same reason: a
    // grant expires in minutes and the module that hands it over re-mints transparently.
    const requestedGrant = session.impersonationGrant();
    headers["X-Impersonation-Grant"] =
      typeof requestedGrant === "string" ? requestedGrant : await requestedGrant;
  }

  // THE WHOLE EXCHANGE IS UNDER THE DEADLINE, not just the round trip. A response whose
  // headers arrive and whose body then stalls is the same hang from the reader's chair,
  // and both readers below consume that body — so the clock stops when the answer is in
  // hand, not when the status line is.
  // Returned, not `await`ed: an extra `await` here buys nothing and costs a microtask on
  // every request in the app. That is not hypothetical bookkeeping — see `TokenSource`
  // above, where one extra tick between a query and its `fetch` was directly observable in
  // the test suite.
  return withDeadline(async (deadlineSignal) => {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      // THE CREDENTIAL, in the deployed case (D-177). The realm's session is an HttpOnly,
      // `__Host-`-prefixed cookie no script can read, so it reaches the API only if this
      // says so — the API and the consoles are different origins, and the browser omits
      // cookies cross-origin by default. `lib/authn/transport.ts` says the same thing for
      // `/v1/auth/**`; the two are one transport the day that file's `fetch` goes away.
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: deadlineSignal,
    });

    if (!response.ok) throw await problemFrom(response);
    return (await readBody(response)) as T;
  }, { timeoutMs, signal });
}

/**
 * A non-2xx response, as the `ApiProblem` every screen already knows how to render.
 *
 * Exported because `lib/authn/transport.ts` is the ONE other place this app calls
 * `fetch` (see its docstring for why it must), and two spellings of "parse problem+json"
 * is exactly the drift CLAUDE.md's one-way-per-problem rule is about. A body that is not
 * JSON at all — an nginx 502, a proxy timeout page — falls back to the status text rather
 * than throwing a parse error over the top of the real failure.
 */
export async function problemFrom(response: Response): Promise<ApiProblem> {
  let problem: Record<string, unknown> = {};
  try {
    problem = await response.json();
  } catch {
    problem = transportProblem(response.status);
  }
  return new ApiProblem(response.status, problem);
}

/**
 * A failure something between the browser and our app produced, said in a person's words.
 *
 * ## Why `response.statusText` is not read here any more
 *
 * It used to be the whole of this fallback, and it is unusable in production for two
 * reasons that only appear once TLS and HTTP/2 are in front of the app —
 * `infra/nginx/calevate.conf.template` sets `http2 on` on every server block, so this is
 * the ordinary case rather than an exotic one:
 *
 * - **HTTP/2 carries no reason phrase.** RFC 9113 §8.3.2: it "does not define a way to
 *   carry the version or reason phrase that is included in an HTTP/1.1 status line". The
 *   Fetch Standard therefore leaves `statusText` empty and Chrome returns `""`
 *   (whatwg/fetch#599, read 2 Sep 2026) — so the sentence a client met on a 502 was the
 *   empty string, rendered as a red box with nothing in it.
 * - **Where it is NOT empty it is wire text.** Safari has returned the whole status line,
 *   `"HTTP/2.0 502"` (WebKit bug 176479), and an HTTP/1.1 hop gives "Bad Gateway". Both
 *   are protocol vocabulary printed at a shop owner as if it were an explanation.
 *
 * The STATUS is the only thing every transport guarantees us, so the sentence is derived
 * from it and nothing else. Each arm says whose problem it is and what happens next,
 * because that is the difference between a refusal a person can act on and a dead end.
 *
 * `retryable` is set here for the same reason: a body we did not write carries none, and
 * `Boolean(undefined)` said "do not offer to try again" on exactly the failures — a
 * gateway that blinked, a restart mid-deploy — that a second attempt fixes.
 */
function transportProblem(status: number): Record<string, unknown> {
  if (status === 429)
    return {
      kind: "rate_limited",
      detail: "Too many requests from this account just now.",
      remediation: "Wait a minute and try again.",
      retryable: true,
    };
  if (status === 413)
    return {
      kind: "too_large",
      detail: "That file is too big for us to accept.",
      remediation: "Send a smaller one, or split it in two.",
      retryable: false,
    };
  if (status >= 500)
    return {
      kind: "unavailable",
      detail: "Calevate is not answering right now.",
      // True and useful together: these clear on their own, and the client is not the
      // one who can clear them. Saying "check your connection" here would be a wrong
      // diagnosis — the connection reached us, which is how we got a status at all.
      remediation: "This is at our end, not yours. Try again in a moment.",
      retryable: true,
    };
  return {
    kind: "refused",
    detail: "That did not go through.",
    remediation: "Try again, and tell us if it keeps happening.",
    retryable: false,
  };
}

/** A 2xx body: `undefined` for 204, text for anything non-JSON, otherwise the JSON. */
export async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) return await response.text();
  return await response.json();
}

/**
 * Response types, aliased from the GENERATED schema so they cannot drift from the API.
 * Regenerate with `pnpm gen:api` after any change to a response model; the openapi
 * freshness guardrail (ENGINEERING-PRACTICES §2) checks this file is current.
 */
type Schemas = components["schemas"];

export type Dashboard = Schemas["DashboardOut"];
export type CallSummary = Schemas["CallSummaryOut"];
export type CallDetail = Schemas["CallDetailOut"];
export type LeadList = Schemas["LeadListOut"];
export type Lead = Schemas["LeadOut"];
export type LeadColumn = Schemas["ExtractionField"];
export type Me = Schemas["MeOut"];
export type CallLeadResult = Schemas["CallLeadOut"];
export type AgentSummary = Schemas["AgentOut"];
export type LeadStatus = Lead["status"];
