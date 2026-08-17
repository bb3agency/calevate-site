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

import { AUTH_MODE_ENV, IS_PRODUCTION_BUILD } from "@/lib/auth/mode";

import type { components } from "./schema";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiProblem extends Error {
  readonly status: number;
  readonly kind: string;
  readonly code: string;
  readonly retryable: boolean;
  readonly remediation?: string;
  readonly fields?: { field: string; rule: string; message: string }[];
  readonly traceId?: string;

  constructor(status: number, body: Record<string, unknown>) {
    super(String(body.detail ?? body.title ?? "Request failed"));
    this.name = "ApiProblem";
    this.status = status;
    this.kind = String(body.kind ?? "internal");
    // `type` is a URL whose last segment is the stable machine code.
    this.code = String(body.type ?? "").split("/").pop() ?? "unknown";
    this.retryable = Boolean(body.retryable);
    this.remediation = body.remediation as string | undefined;
    this.fields = body.fields as ApiProblem["fields"];
    this.traceId = body.trace_id as string | undefined;
  }
}

/**
 * A refusal this browser produced itself, wearing the API's error shape.
 *
 * Auth can fail before any request leaves: the deployment names Clerk but carries no
 * publishable key, Clerk never loaded, the session expired between two clicks. Those
 * are the failures a user is most likely to meet and least able to interpret, so they
 * must arrive with a sentence and a remediation — which is exactly what `ProblemNotice`
 * already renders, from `ApiProblem`, on every screen in the app. Inventing a second
 * error shape would mean teaching twenty screens about it.
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
 * How `apiRequest` obtains the bearer credential for ONE call.
 *
 * A function, and asked per request, because a Clerk session token lives about SIXTY
 * SECONDS — clerk-js refreshes it on a recurring interval and `getToken()` hands back
 * the current one ("How Clerk works: cookies", clerk.com/docs/guides/how-clerk-works).
 * A console tab left open over lunch would therefore send an expired token on its next
 * poll if the string had been captured once when the session object was built. The
 * dashboard polls every twenty seconds, so "left open" is the normal case, not an edge.
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
 * `token` resolves to a Clerk session token in a Clerk deployment and to
 * `dev:<realm>:<clerk_user_id>` locally — see `core/auth.py`, where that second path
 * requires BOTH `APP_ENV=local` AND an absent Clerk secret. Which one a given realm
 * builds is decided in that realm's own module, never here: this file is the transport
 * and knows nothing about realms.
 */
export interface Session {
  token: TokenSource;
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
 * The LOCAL credential, for one realm — the second guard described in `lib/auth/mode.ts`.
 *
 * `lib/auth/mode.ts` already refuses to resolve `"dev"` in a production build. This
 * checks the same fact again, at the moment the credential would be handed to `fetch`,
 * because the two guards protect against different mistakes: the first against a
 * misconfigured deployment, this one against a future refactor that reaches the dev
 * builder by some path that skipped the mode. A dev token is worth a full account
 * takeover on any API still running with `APP_ENV=local`, so it gets belt and braces.
 */
export function devToken(realm: "client" | "admin", clerkUserId: string): TokenSource {
  return () => {
    if (IS_PRODUCTION_BUILD) {
      throw new AuthProblem(
        "dev_token_refused",
        "This build asked for a local development token, which is never valid here.",
        `Set ${AUTH_MODE_ENV}=clerk and configure this realm's Clerk publishable key.`,
      );
    }
    return `dev:${realm}:${clerkUserId}`;
  };
}

/**
 * The client realm's LOCAL session. Kept as the local path (never removed, never
 * "temporarily" reachable in production): `lib/auth/clientRealm.tsx` selects it when
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
}

/**
 * The API's code for "your token is fine, our copy of your account has not landed yet".
 *
 * Clerk mints a session the instant an account exists and sends the browser straight
 * back to us, while the `user.created` webhook travels out of band — so `/signup` and
 * `/invite`, the first thirty seconds of every customer's and every colleague's life in
 * the product, race it. The API reconciles from Clerk's Backend API and only answers
 * this when it could not (`apps/api/core/clerk_identity.py`, D-124).
 */
export const IDENTITY_MIRROR_PENDING = "identity_mirror_pending";

/**
 * How long this transport is willing to wait for that mirror before giving the refusal
 * to the screen. Four extra attempts at 0.5s, 1s, 2s, 4s — about seven and a half
 * seconds, which is far longer than a Svix delivery and far shorter than a person's
 * patience with a form that appears to have hung.
 */
const MIRROR_RETRY_ATTEMPTS = 4;
const MIRROR_RETRY_BASE_MS = 500;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function apiRequest<T>(
  session: Session,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  /**
   * RETRYING A POST IS SAFE FOR THIS ONE CODE, AND ONLY BECAUSE OF WHERE IT IS RAISED.
   *
   * `mutations: { retry: false }` in `app/providers.tsx` is the rule and it stays the
   * rule: the expensive mutations place phone calls, and their safety net is the
   * server's `Idempotency-Key` handling rather than a client guess about whether the
   * first attempt landed. This is the one exception, and it is not a judgement call —
   * `identity_mirror_pending` is raised by the FastAPI auth dependency, before any route
   * handler body runs, so a request refused with it has provably executed nothing. There
   * is no attempt to have landed.
   *
   * It lives HERE, in the transport, rather than in `useSignup` and `useAcceptInvitation`
   * separately: both routes reach it, any future route taking `current_identity` reaches
   * it, and two copies of a backoff policy is where the second one drifts. The screens
   * are untouched — while this loops, the mutation is still `isPending`, so §52's
   * "loading is a skeleton" holds without either page knowing this exists; and if it
   * runs out, the refusal that arrives carries the server's own remediation sentence,
   * which is the one place that rule should be written.
   */
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await sendRequest<T>(session, path, options);
    } catch (error) {
      const waitable =
        error instanceof ApiProblem &&
        error.code === IDENTITY_MIRROR_PENDING &&
        attempt < MIRROR_RETRY_ATTEMPTS &&
        !options.signal?.aborted;
      if (!waitable) throw error;
      await sleep(MIRROR_RETRY_BASE_MS * 2 ** attempt);
    }
  }
}

async function sendRequest<T>(
  session: Session,
  path: string,
  { method = "GET", body, idempotencyKey, confirmAction, ifMatch, signal }: RequestOptions = {},
): Promise<T> {
  // Resolved HERE, per call, rather than when the session object was built — a Clerk
  // token expires in about a minute (see `TokenSource`). The `await` is skipped when the
  // source already has the string, so a local request still reaches `fetch` in the same
  // tick as the query that asked for it. If it throws, the throw propagates: an
  // `AuthProblem` reaching the screen as an error is the point, and catching it to send
  // the request anyway would put `Bearer undefined` on the wire.
  const requested = session.token();
  const token = typeof requested === "string" ? requested : await requested;

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "X-Org-Slug": session.orgSlug,
  };
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

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (!response.ok) throw await problemFrom(response);
  return (await readBody(response)) as T;
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
    problem = { detail: response.statusText };
  }
  return new ApiProblem(response.status, problem);
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
